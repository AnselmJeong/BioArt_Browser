"""Local Codex stdio adapter. Credentials remain owned by the official CLI."""
import asyncio
import contextlib
import json
import os
import shutil
from pathlib import Path


class CodexError(ValueError):
    pass


def executable():
    candidates = [os.environ.get("BIOART_CODEX_BIN"), shutil.which("codex"),
                  str(Path.home() / ".local/bin/codex"), "/opt/homebrew/bin/codex",
                  "/usr/local/bin/codex", "/Applications/Codex.app/Contents/Resources/codex"]
    for value in candidates:
        if value and Path(value).is_file() and os.access(value, os.X_OK):
            return str(Path(value).absolute())
    raise CodexError("Codex CLI를 찾지 못했습니다. Codex CLI를 설치한 뒤 앱을 다시 연결하세요.")


class CodexClient:
    def __init__(self):
        self.proc = None
        self.pending = {}
        self.queues = {}
        self.sequence = 0
        self.start_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.reader = None
        self.stderr = None
        self.thread_config = {}
        self.login_id = None
        self.login_error = None

    async def start(self):
        async with self.start_lock:
            if self.proc and self.proc.returncode is None:
                return
            env = dict(os.environ)
            # No accidental fallback to usage-based Platform authentication.
            env.pop("OPENAI_API_KEY", None)
            env["PATH"] = os.pathsep.join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "/usr/bin:/bin")])
            options = {"features.image_generation": True, "features.shell_tool": False,
                       "features.apps": False, "features.plugins": False,
                       "features.memories": False, "features.multi_agent": False,
                       "features.multi_agent_v2": False, "features.skip_host_skill_discovery": True,
                       "project_doc_max_bytes": 0, "web_search": "disabled"}
            args = [executable(), "app-server"]
            for key, value in options.items():
                args += ["-c", f"{key}={json.dumps(value)}"]
            self.proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, limit=64 * 1024 * 1024)
            self.reader = asyncio.create_task(self._read(self.proc))
            self.stderr = asyncio.create_task(self._drain(self.proc))
            try:
                await self.request("initialize", {"clientInfo": {"name": "bioart_studio", "title": "BioArt Studio", "version": "0.3.0"}, "capabilities": {"experimentalApi": False}})
                await self.send({"method": "initialized"})
                config = (await self.request("config/read", {"includeLayers": False}))["config"]
                # Do not expose the user's unrelated connectors to figure jobs.
                self.thread_config = {f"mcp_servers.{name}.enabled": False for name in config.get("mcp_servers", {})}
            except BaseException:
                await self.close()
                raise

    async def send(self, message):
        async with self.write_lock:
            if not self.proc or self.proc.returncode is not None:
                raise CodexError("Codex 연결이 종료되었습니다. 다시 시도하세요.")
            self.proc.stdin.write((json.dumps(message) + "\n").encode())
            await self.proc.stdin.drain()

    async def request(self, method, params, timeout=40):
        self.sequence += 1
        rid = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.send({"id": rid, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise CodexError("Codex 응답 시간이 초과되었습니다. 연결을 확인하고 다시 시도하세요.") from exc
        finally:
            self.pending.pop(rid, None)

    async def _read(self, proc):
        try:
            while line := await proc.stdout.readline():
                message = json.loads(line)
                if "id" in message and "method" not in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(CodexError(message["error"].get("message", "Codex 요청 실패")))
                        else:
                            future.set_result(message.get("result", {}))
                elif "id" in message:
                    # Figure generation never grants shell/file/network approvals.
                    await self.send({"id": message["id"], "error": {"code": -32601, "message": "BioArt supports image generation and structured output only; this tool is unavailable."}})
                else:
                    params = message.get("params", {})
                    if message.get("method") == "account/login/completed":
                        self.login_id = None
                        self.login_error = None if params.get("success") else params.get("error", "로그인 실패")
                    queue = self.queues.get(params.get("threadId"))
                    if queue:
                        await queue.put(message)
        except (OSError, ValueError, asyncio.LimitOverrunError):
            pass
        finally:
            error = CodexError("Codex 연결이 끊어졌습니다. 다시 연결하세요.")
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            for queue in self.queues.values():
                queue.put_nowait({"method": "bioart/disconnected", "params": {}})

    async def _drain(self, proc):
        # Drain without exposing credentials or unrelated user configuration in logs.
        while await proc.stderr.read(8192):
            pass

    async def account(self):
        await self.start()
        data = await self.request("account/read", {"refreshToken": False})
        account = data.get("account") or {}
        return {"available": True, "connected": account.get("type") == "chatgpt",
                "auth_type": account.get("type"), "plan": account.get("planType"),
                "login_pending": bool(self.login_id), "error": self.login_error}

    async def login(self):
        await self.start()
        if self.login_id:
            await self.request("account/login/cancel", {"loginId": self.login_id})
        result = await self.request("account/login/start", {"type": "chatgpt"})
        self.login_id = result.get("loginId")
        self.login_error = None
        return {"url": result["authUrl"]}

    async def begin(self, cwd, instructions, images, prompt, schema=None):
        if not (await self.account())["connected"]:
            raise CodexError("ChatGPT 구독으로 Codex에 로그인하세요. API 키 방식으로는 제작을 실행하지 않습니다.")
        result = await self.request("thread/start", {
            "cwd": str(cwd), "sandbox": "read-only", "approvalPolicy": "never",
            "ephemeral": True, "config": self.thread_config,
            "developerInstructions": instructions})
        tid = result["thread"]["id"]
        queue = asyncio.Queue()
        self.queues[tid] = queue
        params = {"threadId": tid, "input": [{"type": "text", "text": prompt}]
                  + [{"type": "localImage", "path": str(p)} for p in images]}
        if schema:
            params["outputSchema"] = schema
        try:
            result = await self.request("turn/start", params)
        except BaseException:
            self.queues.pop(tid, None)
            raise
        return tid, result["turn"]["id"], queue

    async def interrupt(self, tid, turn):
        await self.request("turn/interrupt", {"threadId": tid, "turnId": turn}, timeout=10)

    async def close(self):
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        for task in (self.reader, self.stderr):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self.login_id = None
        self.queues.clear()
