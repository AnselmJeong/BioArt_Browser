import { afterAll, describe, expect, test } from 'bun:test';
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Backend, exportPath, parseMessage } from '../../src/bun/backend';

const root = await mkdtemp(join(tmpdir(), 'bioart-desktop-'));
afterAll(() => rm(root, { recursive: true, force: true }));

describe('native boundary', () => {
  test('allows only structured known actions and http(s) external links', () => {
    expect(parseMessage({ action: 'external', url: 'https://bioart.niaid.nih.gov/' })?.action).toBe('external');
    for (const value of [null, 'hello', { action: 'exec', path: '/bin/sh' },
      { action: 'external', url: 'file:///etc/passwd' }, { action: 'external', url: 'javascript:alert(1)' },
      { action: 'external', url: 'https://user:secret@example.org' }, { action: 'reveal', path: 1 }])
      expect(parseMessage(value)).toBeNull();
  });
  test('reveal rejects traversal, siblings, missing files and symlink escapes', async () => {
    await mkdir(join(root, 'exports'));
    await mkdir(join(root, 'exports-other'));
    await writeFile(join(root, 'exports', 'ok.zip'), 'zip');
    await writeFile(join(root, 'exports-other', 'private'), 'private');
    await symlink(join(root, 'exports-other', 'private'), join(root, 'exports', 'escape'));
    expect(await exportPath(root, join(root, 'exports', 'ok.zip'))).toEndWith('/exports/ok.zip');
    for (const path of ['exports/../exports-other/private', 'exports/escape', 'exports/missing', 'exports'])
      await expect(exportPath(root, join(root, path))).rejects.toThrow();
  });
});

test('supervisor boots independently of workspace cwd, then terminates its child', async () => {
  const fake = join(root, 'fake.ts');
  await writeFile(fake, `const server=Bun.serve({port:0,hostname:'127.0.0.1',fetch:()=>Response.json({ok:true})});\nconsole.log('BIOART_READY '+JSON.stringify({port:server.port,pid:process.pid}));`);
  const launcher = join(root, 'fake-backend');
  const quote = (s: string) => "'" + s.replaceAll("'", "'\\''") + "'";
  await writeFile(launcher, `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(fake)} "$@"\n`, { mode: 0o755 });
  let unexpectedExit = false;
  const backend = new Backend(launcher, join(root, 'workspace-not-mounted'), () => {}, () => { unexpectedExit = true; });
  const url = await backend.start();
  expect((await fetch(url + '/api/health')).ok).toBe(true);
  await backend.stop();
  await backend.stop();
  await expect(fetch(url)).rejects.toThrow();
  expect(unexpectedExit).toBe(false);
});

test('supervisor reports an early backend failure', async () => {
  const backend = new Backend('/usr/bin/false', root, () => {}, () => {});
  await expect(backend.start()).rejects.toThrow('백엔드 종료');
  await backend.stop();
});
