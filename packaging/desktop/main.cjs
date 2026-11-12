const {app, BrowserWindow, Menu, net, protocol, session, shell} = require('electron');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

protocol.registerSchemesAsPrivileged([{
  scheme: 'autopath',
  privileges: {standard: true, secure: true, supportFetchAPI: true, allowServiceWorkers: true, corsEnabled: true, stream: true}
}]);

let window;

function openExternal(url) {
  if (new URL(url).protocol === 'https:') shell.openExternal(url);
}

function createWindow() {
  window = new BrowserWindow({
    title: 'АвтоПуть Бюджет',
    width: 1280,
    height: 820,
    minWidth: 360,
    minHeight: 640,
    backgroundColor: '#111213',
    icon: path.join(__dirname, '../app/vendor/icons/icon-512.png'),
    autoHideMenuBar: true,
    show: false,
    webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true}
  });
  window.webContents.setWindowOpenHandler(({url}) => {
    openExternal(url);
    return {action: 'deny'};
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('autopath://app/')) {
      event.preventDefault();
      openExternal(url);
    }
  });
  window.once('ready-to-show', () => window.show());
  window.on('closed', () => { window = null; });
  window.loadURL('autopath://app/');
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app.whenReady().then(() => {
    const root = path.resolve(__dirname, '../app');
    protocol.handle('autopath', request => {
      const url = new URL(request.url);
      if (url.hostname !== 'app' || request.method !== 'GET') return new Response('', {status: 403});
      let pathname;
      try { pathname = decodeURIComponent(url.pathname); } catch { return new Response('', {status: 400}); }
      const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
      const relative = path.relative(root, file);
      if (relative.startsWith('..') || path.isAbsolute(relative)) return new Response('', {status: 403});
      return net.fetch(pathToFileURL(file).href);
    });
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => callback(false));
    Menu.setApplicationMenu(process.platform === 'darwin' ? Menu.buildFromTemplate([
      {role: 'appMenu'}, {role: 'editMenu'}, {role: 'viewMenu'}, {role: 'windowMenu'}
    ]) : null);
    createWindow();
    app.on('activate', () => { if (!window) createWindow(); });
  });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
}
