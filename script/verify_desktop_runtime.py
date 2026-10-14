"""Verify the packaged worker, including the orphan-process recovery path."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'dist/BioArt Browser.app/Contents/Resources/app/backend/bioart-backend'
ENV = {**os.environ, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}


def ready(process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.25)
        if readable:
            line = process.stdout.readline().decode()
            if line.startswith('BIOART_READY '):
                return json.loads(line.removeprefix('BIOART_READY '))
        if process.poll() is not None:
            raise RuntimeError(f'Worker exited: {process.returncode}')
    raise TimeoutError('No readiness handshake')


def get(port, endpoint, timeout=1):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{endpoint}', timeout=timeout) as response:
        return json.load(response)


def await_health(port):
    for _ in range(100):
        try:
            if get(port, '/api/health')['ok']:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise RuntimeError('Worker health check failed')


def await_closed(port):
    for _ in range(100):
        try:
            get(port, '/api/health')
        except OSError:
            return
        time.sleep(0.05)
    raise RuntimeError('Backend was left running')


def main():
    worker = subprocess.Popen([str(WORKER), 'serve', '--workspace', str(ROOT), '--port', '0',
                               '--ready-stdout', '--parent-pid', str(os.getpid())],
                              cwd='/', env=ENV, stdout=subprocess.PIPE)
    try:
        info = ready(worker)
        await_health(info['port'])
        stats = get(info['port'], '/api/stats')
        assert stats['artworks'] == 933 and stats['valid_files'] == 9524
        assert get(info['port'], '/api/search?q=%ED%8F%90')['total'] > 0
        codex = get(info['port'], '/api/codex/status', timeout=45)
        assert codex['available'] and codex['connected'], codex
        assert isinstance(get(info['port'], '/api/studio/projects'), list)
    finally:
        worker.terminate()
        worker.wait(timeout=5)
    await_closed(info['port'])
    # Simulate a native host crash; the orphan must notice its parent's loss.
    parent_code = """
import os, subprocess, sys
child = subprocess.Popen([sys.argv[1], 'serve', '--workspace', sys.argv[2], '--port', '0',
                          '--ready-stdout', '--parent-pid', str(os.getpid())], stdout=subprocess.PIPE)
print(child.stdout.readline().decode().strip(), flush=True)
child.wait()
"""
    parent = subprocess.Popen([sys.executable, '-c', parent_code, str(WORKER), str(ROOT)],
                              cwd='/', env=ENV, stdout=subprocess.PIPE)
    orphan = None
    try:
        orphan = ready(parent)
        await_health(orphan['port'])
        parent.kill()
        parent.wait(timeout=5)
        await_closed(orphan['port'])
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if orphan:
            try:
                os.kill(orphan['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
    report = {'packaged_worker': str(WORKER), 'path': ENV['PATH'], 'cwd': '/',
              'artworks': stats['artworks'], 'valid_files': stats['valid_files'],
              'search': 'passed', 'codex_subscription': 'connected', 'studio': 'passed', 'graceful_stop': 'passed', 'orphan_cleanup': 'passed'}
    (ROOT / 'build/desktop-runtime-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
