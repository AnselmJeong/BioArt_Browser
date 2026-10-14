import Electrobun, { BrowserWindow, ApplicationMenu, Utils, PATHS } from 'electrobun/main';
import { appendFileSync, mkdirSync } from 'node:fs';
import { access, readFile, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Backend, exportPath, parseMessage } from './backend';

const logs = Utils.paths.userLogs;
mkdirSync(logs, { recursive: true });
const log = (message: string) => appendFileSync(join(logs, 'desktop.log'), `${new Date().toISOString()} ${message}\n`);
const settingsPath = join(Utils.paths.userData, 'workspace.json');
const resources = join(PATHS.RESOURCES_FOLDER, 'app');
const escapeHTML = (text: string) => text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char] ?? char));
let workspace = '';
let backend: Backend | undefined;
let origin = '';
let starting = false;
let quitting = false;
const window = new BrowserWindow({ title: 'BioArt Browser', frame: { width: 1440, height: 920 },
  url: 'about:blank', renderer: 'native', sandbox: true,
  navigationRules: JSON.stringify(['^*', 'about:blank']) });

function splash(message: string, failed = false) {
  window.webview.setNavigationRules(['^*', 'about:blank']);
  window.webview.loadHTML(`<!doctype html><html lang="ko"><meta charset="utf-8"><style>
  body{margin:0;background:#f7f8f5;color:#25392f;font:16px -apple-system,sans-serif;display:grid;place-items:center;height:100vh}
  main{max-width:650px;padding:48px}small{letter-spacing:.18em;color:#617865}h1{font-size:36px;letter-spacing:-1px}
  p{line-height:1.8;white-space:pre-wrap;color:#56645b}button{padding:12px 18px;border:1px solid #ccd8ce;background:#fff;border-radius:8px;margin-right:8px;cursor:pointer}
  </style><main><small>BIOART · DESKTOP</small><h1>${failed ? '자료를 열지 못했습니다' : '라이브러리를 준비하고 있습니다'}</h1><p>${escapeHTML(message)}</p>
  ${failed ? `<button onclick="window.__electrobunSendToHost({action:'retry'})">다시 시도</button><button onclick="window.__electrobunSendToHost({action:'choose'})">작업 폴더 선택</button>` : ''}</main></html>`);
}

async function readWorkspace(path: string): Promise<string | undefined> {
  try {
    const value: unknown = JSON.parse(await readFile(path, 'utf8'));
    if (value && typeof value === 'object' && 'workspace' in value && typeof value.workspace === 'string') return value.workspace;
  } catch { /* First launch or a moved installation. */ }
  return undefined;
}
async function chooseWorkspace() {
  if (starting || quitting) return;
  const selected = await Utils.openFileDialog({ canChooseFiles: false, canChooseDirectory: true, allowsMultipleSelection: false });
  if (selected[0]) await start(selected[0]);
}
async function start(selected?: string) {
  if (starting || quitting) return;
  starting = true;
  splash('저장된 카탈로그와 그림을 연결하고 있습니다.\nmacOS가 외장 볼륨 접근을 요청하면 허용해 주세요.');
  try {
    await backend?.stop();
    workspace = selected ?? process.env.BIOART_WORKSPACE ?? process.env.BIOART_PROJECT_ROOT
      ?? await readWorkspace(settingsPath) ?? await readWorkspace(join(resources, 'desktop-workspace.json')) ?? '';
    if (!workspace) throw new Error('BioArt 작업 폴더를 선택해 주세요. 빈 폴더에 휴대용 프로젝트를 가져올 수도 있습니다.');
    await access(workspace);
    const executable = join(resources, 'backend/bioart-backend');
    await access(executable);
    log(`starting workspace=${workspace} executable=${executable}`);
    backend = new Backend(executable, workspace, log, code => {
      log(`backend exited unexpectedly: ${code}`);
      if (!starting && !quitting) splash(`로컬 서버가 종료되었습니다 (${code}). 다시 시도할 수 있습니다.`, true);
    });
    origin = await backend.start();
    await mkdir(Utils.paths.userData, { recursive: true });
    await writeFile(settingsPath, JSON.stringify({ workspace }));
    if (quitting) { await backend.stop(); return; }
    window.webview.setNavigationRules(['^*', `${origin}/*`]);
    window.webview.loadURL(`${origin}/`);
    log(`ready ${origin}`);
  } catch (error) {
    log(String(error));
    splash(`작업 폴더: ${workspace || '미선택'}\n${String(error)}\n\n원본 자료가 있는 볼륨이 연결되어 있고 접근이 허용되어 있는지 확인해 주세요.`, true);
  } finally { starting = false; }
}

// The sandbox has an event-only bridge, with no general filesystem or RPC access.
Electrobun.events.on(`host-message-${window.webview.id}`, (event: { data: { detail: string } }) => {
  void (async () => {
    const value: unknown = JSON.parse(event.data.detail);
    if (value && typeof value === 'object' && 'action' in value) {
      if (value.action === 'retry') { await start(); return; }
      if (value.action === 'choose') { await chooseWorkspace(); return; }
    }
    const message = parseMessage(value);
    if (message?.action === 'reveal' && workspace) Utils.showItemInFolder(await exportPath(workspace, message.path));
    if (message?.action === 'external') Utils.openExternal(message.url);
  })().catch(error => log(`native action rejected: ${String(error)}`));
});
Electrobun.events.on(`new-window-open-${window.webview.id}`, (event: { data: { detail: string | { url: string } } }) => {
  const detail = event.data.detail;
  const message = parseMessage({ action: 'external', url: typeof detail === 'string' ? detail : detail.url });
  if (message?.action === 'external' && !message.url.startsWith(origin + '/')) Utils.openExternal(message.url);
});
window.webview.on('dom-ready', () => log('window DOM ready'));

ApplicationMenu.setApplicationMenu([
  { label: 'BioArt Browser', submenu: [{ label: 'BioArt Browser 정보', action: 'about' }, { type: 'separator' },
    { role: 'hide', accelerator: 'h' }, { role: 'hideOthers', accelerator: 'alt+h' }, { role: 'showAll' },
    { type: 'separator' }, { label: 'BioArt Browser 종료', role: 'quit', accelerator: 'q' }] },
  { label: '파일', submenu: [{ label: '작업 폴더 선택…', action: 'choose' }, { label: '내보내기 폴더 열기', action: 'exports' },
    { type: 'separator' }, { role: 'close', accelerator: 'w' }] },
  { label: '편집', submenu: [{ role: 'undo', accelerator: 'z' }, { role: 'redo', accelerator: 'shift+z' }, { type: 'separator' },
    { role: 'cut', accelerator: 'x' }, { role: 'copy', accelerator: 'c' }, { role: 'paste', accelerator: 'v' }, { role: 'selectAll', accelerator: 'a' }] },
  { label: '보기', submenu: [{ label: '다시 불러오기', action: 'reload', accelerator: 'r' }, { label: '실행 로그 보기', action: 'logs' },
    { role: 'toggleFullScreen', accelerator: 'ctrl+f' }] },
  { label: '윈도우', submenu: [{ role: 'minimize', accelerator: 'm' }, { role: 'zoom' }] },
]);
ApplicationMenu.on('application-menu-clicked', event => {
  const action = (event as { data?: { action?: string } }).data?.action;
  if (action === 'choose') void chooseWorkspace();
  if (action === 'exports' && workspace) Utils.openPath(join(workspace, 'exports'));
  if (action === 'logs') Utils.showItemInFolder(join(logs, 'desktop.log'));
  if (action === 'reload') { if (origin) window.webview.loadURL(origin + '/'); else void start(); }
  if (action === 'about') void Utils.showMessageBox({ title: 'BioArt Browser', message: 'BioArt Browser 0.4.0', detail: 'Electrobun 데스크톱 · 로컬 BioArt 라이브러리\n원본, 카탈로그, 도해는 선택한 작업 폴더에 보관됩니다.' });
});
Electrobun.events.on('before-quit', (event: { response: { allow: boolean } }) => {
  if (quitting) return;
  event.response = { allow: false };
  quitting = true;
  void (backend?.stop() ?? Promise.resolve()).finally(() => { log('shutdown complete'); Utils.quit(); });
});
process.on('SIGTERM', () => Utils.quit());
process.on('SIGINT', () => Utils.quit());
log(`Electrobun desktop started pid=${process.pid}`);
void start();
