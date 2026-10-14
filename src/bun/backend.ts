import { dirname, join, resolve, sep } from 'node:path';
import { realpath } from 'node:fs/promises';

export type DesktopMessage = { action: 'reveal'; path: string } | { action: 'external'; url: string };

export function parseMessage(value: unknown): DesktopMessage | null {
  if (!value || typeof value !== 'object') return null;
  if ('action' in value && value.action === 'reveal' && 'path' in value && typeof value.path === 'string')
    return { action: 'reveal', path: value.path };
  if ('action' in value && value.action === 'external' && 'url' in value && typeof value.url === 'string') {
    try {
      const url = new URL(value.url);
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password)
        return { action: 'external', url: url.href };
    } catch { /* Invalid URLs are ignored. */ }
  }
  return null;
}

export async function exportPath(workspace: string, requested: string): Promise<string> {
  const root = await realpath(join(workspace, 'exports'));
  const target = await realpath(resolve(requested));
  if (!target.startsWith(root + sep)) throw new Error('내보내기 폴더 밖의 파일은 열 수 없습니다.');
  return target;
}

export class Backend {
  private child: ReturnType<typeof Bun.spawn> | undefined;
  private stopping = false;
  constructor(private readonly executable: string, private readonly workspace: string,
    private readonly log: (line: string) => void, private readonly onExit: (code: number) => void) {}

  async start(): Promise<string> {
    const child = Bun.spawn([this.executable, 'serve', '--workspace', this.workspace,
      '--port', '0', '--ready-stdout', '--parent-pid', String(process.pid)], {
      // Workspace is explicit in argv; do not make Python bootstrap resolve an external-volume cwd.
      cwd: dirname(this.executable), env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdin: 'ignore', stdout: 'pipe', stderr: 'pipe',
    });
    this.child = child;
    void child.exited.then(code => { if (!this.stopping) this.onExit(code); });
    const consume = async (stream: ReadableStream<Uint8Array>, onLine: (s: string) => void) => {
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) { if (pending) onLine(pending); break; }
        pending += decoder.decode(value, { stream: true });
        let end: number;
        while ((end = pending.indexOf('\n')) >= 0) {
          onLine(pending.slice(0, end)); pending = pending.slice(end + 1);
        }
        if (pending.length > 65536) { onLine(pending); pending = ''; }
      }
    };
    void consume(child.stderr, this.log).catch(error => this.log(String(error)));
    try {
      const url = await new Promise<string>((resolveReady, reject) => {
        const timer = setTimeout(() => reject(new Error('백엔드가 45초 안에 시작되지 않았습니다. 볼륨 접근 권한을 확인하세요.')), 45000);
        void child.exited.then(code => { clearTimeout(timer); reject(new Error(`백엔드 종료 (${code})`)); });
        void consume(child.stdout, line => {
          this.log(line);
          if (!line.startsWith('BIOART_READY ')) return;
          try {
            const data: unknown = JSON.parse(line.slice(13));
            if (data && typeof data === 'object' && 'port' in data && typeof data.port === 'number'
              && Number.isInteger(data.port) && data.port > 0 && data.port <= 65535) {
              clearTimeout(timer); resolveReady(`http://127.0.0.1:${data.port}`);
            }
          } catch { /* Continue waiting for a valid readiness record. */ }
        }).catch(reject);
      });
      for (let attempt = 0; attempt < 100; attempt++) {
        if (this.stopping || child.exitCode !== null) throw new Error('백엔드가 종료되었습니다.');
        try {
          const response = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(500) });
          if (response.ok && (await response.json() as { ok?: boolean }).ok === true) return url;
        } catch { /* Listener is ready before ASGI startup completes. */ }
        await Bun.sleep(100);
      }
      throw new Error('백엔드 상태 확인에 실패했습니다.');
    } catch (error) { await this.stop(); throw error; }
  }

  async stop(): Promise<void> {
    this.stopping = true;
    const child = this.child;
    if (!child || child.exitCode !== null) return;
    child.kill('SIGTERM');
    const timer = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, 3000);
    await child.exited;
    clearTimeout(timer);
  }
}
