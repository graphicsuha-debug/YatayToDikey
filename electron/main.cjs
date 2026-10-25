const { app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

app.setName('Dikey Studio');
app.setAppUserModelId('com.suhay.dikey');
const smokeDirectory = process.env.DIKEY_SMOKE_TEST_DIR
  ? path.resolve(process.env.DIKEY_SMOKE_TEST_DIR)
  : process.argv.includes('--smoke-test') ? path.join(app.getPath('temp'), 'dikey-studio-smoke') : null;
if (smokeDirectory) {
  fs.mkdirSync(smokeDirectory, { recursive: true });
  app.setPath('userData', path.join(smokeDirectory, 'user-data'));
}

const statusPage = path.join(__dirname, 'status.html');
const statusPageUrl = pathToFileURL(statusPage).href;
let window = null;
let backend = null;
let backendOrigin = '';
let backendReady = false;
let startupPromise = null;
let closingPromise = null;
let allowExit = false;
let shuttingDown = false;
let logStream = null;
let dataDirectory = '';
const blockedRemoteRequests = [];

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const isStatusPage = url => url.split('?')[0] === statusPageUrl;
const isBackendUrl = url => {
  try { return !!backendOrigin && new URL(url).origin === backendOrigin; }
  catch { return false; }
};
const log = message => logStream?.write(`[${new Date().toISOString()}] ${message}\n`);

async function showStatus(state, message = '') {
  if (!window || window.isDestroyed() || shuttingDown) return;
  await window.loadFile(statusPage, { query: { state, message, version: app.getVersion() } });
  if (!smokeDirectory) window.show();
}

function reserveAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function localJson(route, timeout = 2000) {
  const response = await fetch(`${backendOrigin}${route}`, { signal: AbortSignal.timeout(timeout) });
  if (!response.ok) throw new Error(`Yerel uygulama yanıtı: ${response.status}`);
  return response.json();
}

function backendPaths() {
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, 'backend', 'dikey-backend.exe'),
      args: [],
      assets: path.join(process.resourcesPath, 'app-assets'),
      ffmpeg: path.join(process.resourcesPath, 'ffmpeg'),
    };
  }
  const root = path.resolve(__dirname, '..');
  const executable = path.join(root, 'build', 'backend', 'dikey-backend', 'dikey-backend.exe');
  return {
    command: fs.existsSync(executable) ? executable : path.join(root, '.venv', 'Scripts', 'python.exe'),
    args: fs.existsSync(executable) ? [] : ['-m', 'scripts.frozen_backend'],
    assets: root,
    ffmpeg: fs.existsSync(path.join(root, 'build', 'backend', 'ffmpeg')) ? path.join(root, 'build', 'backend', 'ffmpeg') : '',
  };
}

async function stopBackend() {
  backendReady = false;
  const child = backend;
  if (!child) return;
  backend = null;
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise(resolve => child.once('exit', resolve));
  try { child.stdin.end('__DIKEY_SHUTDOWN__\n'); }
  catch (error) { log(`Kapanış isteği gönderilemedi: ${error.message}`); }
  const ended = await Promise.race([exited.then(() => true), sleep(8000).then(() => false)]);
  if (ended) return;
  if (child.exitCode !== null || child.signalCode !== null) return;
  log('Video motoru kapanış süresini aştı; yalnızca uygulamanın kendi süreç ağacı durduruluyor.');
  if (process.platform === 'win32' && child.pid) {
    await new Promise(resolve => {
      const kill = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      kill.once('exit', resolve);
      kill.once('error', resolve);
    });
  } else {
    child.kill('SIGKILL');
  }
  await Promise.race([exited, sleep(2000)]);
}

async function startBackend() {
  if (startupPromise || shuttingDown) return startupPromise;
  startupPromise = (async () => {
    await stopBackend();
    await showStatus('loading');
    try {
      const paths = backendPaths();
      if (!fs.existsSync(paths.command)) {
        throw new Error('Video motoru bulunamadı. Uygulamayı kurulum dosyasıyla yeniden kurun.');
      }
      const port = await reserveAvailablePort();
      if (shuttingDown) return;
      backendOrigin = `http://127.0.0.1:${port}`;
      const child = spawn(paths.command, paths.args, {
        cwd: app.isPackaged ? path.dirname(paths.command) : paths.assets,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          DIKEY_PORT: String(port),
          DIKEY_DATA_DIR: dataDirectory,
          DIKEY_ASSETS_DIR: paths.assets,
          DIKEY_FFMPEG_DIR: paths.ffmpeg,
          DIKEY_DESKTOP: '1',
          PYTHONUNBUFFERED: '1',
        },
      });
      backend = child;
      let spawnError = null;
      let exited = false;
      child.stdout.on('data', chunk => logStream?.write(chunk));
      child.stderr.on('data', chunk => logStream?.write(chunk));
      child.stdin.on('error', error => log(`Video motoru bağlantısı kapandı: ${error.message}`));
      child.on('error', error => { spawnError = error; log(`Video motoru başlatılamadı: ${error.message}`); });
      child.on('exit', (code, signal) => {
        exited = true;
        log(`Video motoru kapandı: code=${code}, signal=${signal || '-'}`);
        if (backend === child && backendReady && !shuttingDown) {
          backendReady = false;
          void showStatus('error', 'Video motoru beklenmedik şekilde kapandı. Yeniden deneyerek stüdyoyu açabilirsiniz.');
        }
      });
      log(`Video motoru başlatılıyor; bağlantı noktası ${port}.`);
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline && !shuttingDown) {
        if (spawnError) throw new Error('Video motoru çalıştırılamadı. Kurulumu yeniden çalıştırmayı deneyin.');
        if (exited) throw new Error('Video motoru açılırken durdu. Ayrıntılar uygulama günlüklerine kaydedildi.');
        let health = null;
        try { health = await localJson('/api/health', 1000); }
        catch { /* The loop allows the bundled process time to start listening. */ }
        if (health?.ok && health.ffmpeg) {
          if (shuttingDown) return;
          backendReady = true;
          await window.loadURL(backendOrigin);
          if (!smokeDirectory) window.show();
          log('Dikey Studio hazır.');
          return;
        }
        if (health?.ok && !health.ffmpeg) {
          throw new Error('Kurulumdaki video bileşenleri eksik. Uygulamayı yeniden kurun.');
        }
        await sleep(200);
      }
      if (!shuttingDown) throw new Error('Video motoru zamanında yanıt vermedi. Yeniden deneyin veya günlükleri kontrol edin.');
    } catch (error) {
      log(error.stack || error.message);
      await stopBackend();
      await showStatus('error', error.message || 'Uygulama başlatılamadı. Yeniden deneyin.');
    }
  })();
  try { await startupPromise; }
  finally { startupPromise = null; }
}

async function requestClose() {
  if (closingPromise || allowExit) return closingPromise;
  closingPromise = (async () => {
    if (backendReady) {
      try {
        const jobs = await localJson('/api/exports', 2000);
        const count = jobs.filter(job => ['queued', 'processing'].includes(job.status)).length;
        if (count > 0) {
          const { response } = await dialog.showMessageBox(window, {
            type: 'question', title: 'Dışa aktarma devam ediyor',
            message: `${count} video hâlâ hazırlanıyor.`,
            detail: 'Uygulamadan çıkarsanız devam eden dışa aktarmalar iptal edilir. Kaynak videolarınız ve tamamlanan çıktılarınız korunur.',
            buttons: ['İşleme devam et', 'İptal edip çık'], defaultId: 0, cancelId: 0, noLink: true,
          });
          if (response !== 1) return;
        }
      } catch (error) { log(`Kapanırken iş durumu okunamadı: ${error.message}`); }
    }
    shuttingDown = true;
    await stopBackend();
    allowExit = true;
    logStream?.end();
    app.quit();
  })();
  try { await closingPromise; }
  finally { closingPromise = null; }
}

async function runSmokeTest() {
  const result = { ok: false, version: app.getVersion(), packaged: app.isPackaged, backendReady, blockedRemoteRequests };
  try {
    if (!backendReady) throw new Error('Paketlenmiş video motoru hazır duruma gelemedi.');
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const ready = await window.webContents.executeJavaScript("Boolean(document.querySelector('.author-footer') && document.querySelector('video')?.getAttribute('src') && document.querySelector('canvas'))");
      if (ready) break;
      await sleep(150);
    }
    await window.webContents.executeJavaScript('document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))');
    await sleep(1000);
    const ui = await window.webContents.executeJavaScript(`(() => {
      const text = document.body.innerText;
      const canvas = document.querySelector('canvas');
      const video = document.querySelector('video');
      return {
        title: document.title,
        url: location.href,
        heading: document.querySelector('h1')?.innerText,
        hasSource: text.includes('Kaynak video'),
        hasPreview: text.includes('Dikey önizleme'),
        hasSettings: text.includes('Son dokunuşlar'),
        hasExportButton: text.includes('Dikey videoyu oluştur'),
        hasFooter: text.includes('Bu program Suha Yar tarafından yapılmıştır.'),
        hasLocalStatus: text.includes('Bilgisayarında çalışıyor'),
        canvas: canvas ? { width: canvas.width, height: canvas.height } : null,
        videoSource: video?.getAttribute('src'),
        videoDuration: Number.isFinite(video?.duration) ? video.duration : null,
        nodeUnavailable: typeof window.require === 'undefined' && typeof window.process === 'undefined',
        viewport: { width: innerWidth, height: innerHeight },
        bodyPreview: text.slice(0, 2500),
      };
    })()`);
    result.ui = ui;
    result.ok = !!(ui.hasSource && ui.hasPreview && ui.hasSettings && ui.hasExportButton && ui.hasFooter && ui.hasLocalStatus && ui.canvas?.width === 540 && ui.canvas?.height === 960 && ui.videoSource && ui.nodeUnavailable && blockedRemoteRequests.length === 0);
  } catch (error) {
    result.error = error.message;
  }
  try {
    const screenshot = await window.webContents.capturePage();
    fs.writeFileSync(path.join(smokeDirectory, 'smoke.png'), screenshot.toPNG());
  } catch (error) { result.captureError = error.message; result.ok = false; }
  fs.writeFileSync(path.join(smokeDirectory, 'smoke.json'), JSON.stringify(result, null, 2));
  shuttingDown = true;
  await stopBackend();
  allowExit = true;
  logStream?.end();
  app.exit(result.ok ? 0 : 1);
}

function createWindow() {
  const { screen } = require('electron');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  window = new BrowserWindow({
    title: 'Dikey Studio', width: Math.min(1530, width), height: Math.min(980, height),
    minWidth: 780, minHeight: 620, show: false, backgroundColor: '#101014',
    autoHideMenuBar: true, icon: path.join(__dirname, 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false, contextIsolation: true, sandbox: true,
      webSecurity: true, allowRunningInsecureContent: false, webviewTag: false,
      backgroundThrottling: !smokeDirectory,
    },
  });
  window.setMenu(null);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => {
    if (!isBackendUrl(url) && !isStatusPage(url)) event.preventDefault();
  });
  window.webContents.on('will-redirect', (event, url) => {
    if (!isBackendUrl(url) && !isStatusPage(url)) event.preventDefault();
  });
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.on('page-title-updated', event => { event.preventDefault(); });
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.webContents.session.setPermissionCheckHandler(() => false);
  window.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'ws://*/*', 'wss://*/*'] }, (details, callback) => {
    const cancel = !isBackendUrl(details.url);
    if (cancel) blockedRemoteRequests.push(details.url);
    callback({ cancel });
  });
  window.webContents.session.on('will-download', (event, item) => {
    if (!isBackendUrl(item.getURL()) || !/^\/api\/exports\/[^/]+\/download$/.test(new URL(item.getURL()).pathname)) {
      event.preventDefault();
      return;
    }
    item.setSaveDialogOptions({
      title: 'Dikey videoyu kaydet',
      defaultPath: path.join(app.getPath('downloads'), path.basename(item.getFilename())),
      filters: [{ name: 'MP4 video', extensions: ['mp4'] }],
    });
    item.once('done', (_downloadEvent, state) => {
      if (state === 'interrupted' && !shuttingDown && window && !window.isDestroyed()) {
        void dialog.showMessageBox(window, { type: 'error', title: 'Video kaydedilemedi', message: 'Video seçtiğiniz konuma kaydedilemedi.', detail: 'Klasör izinlerini ve boş disk alanını kontrol edip Çıktılarım bölümünden tekrar indirin.' });
      }
    });
  });
  window.on('close', event => { if (!allowExit) { event.preventDefault(); void requestClose(); } });
  window.on('closed', () => { window = null; });
}

const lock = app.requestSingleInstanceLock();
if (!lock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show(); window.focus();
  });
  app.on('before-quit', event => { if (!allowExit) { event.preventDefault(); void requestClose(); } });
  app.on('window-all-closed', () => { if (allowExit) app.quit(); });
  app.whenReady().then(async () => {
    nativeTheme.themeSource = 'dark';
    Menu.setApplicationMenu(null);
    dataDirectory = path.join(app.getPath('userData'), 'data');
    fs.mkdirSync(dataDirectory, { recursive: true });
    logStream = fs.createWriteStream(path.join(dataDirectory, 'desktop.log'), { flags: 'a' });
    logStream.on('error', () => {});
    ipcMain.handle('desktop:retry', event => {
      if (!isStatusPage(event.senderFrame.url)) throw new Error('Bu işlem yalnızca başlangıç ekranında kullanılabilir.');
      void startBackend();
      return true;
    });
    ipcMain.handle('desktop:open-logs', event => {
      if (!isStatusPage(event.senderFrame.url)) throw new Error('Bu işlem yalnızca başlangıç ekranında kullanılabilir.');
      return shell.openPath(dataDirectory);
    });
    createWindow();
    await startBackend();
    if (smokeDirectory) await runSmokeTest();
  }).catch(error => {
    log(error.stack || error.message);
    dialog.showErrorBox('Dikey Studio açılamadı', 'Uygulama başlatılamadı. Kurulumu yeniden çalıştırmayı deneyin.\n\n' + error.message);
    void requestClose();
  });
}
