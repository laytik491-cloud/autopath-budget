import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
const {chromium} = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const browser = await chromium.launch({headless: true});
const base = process.env.APP_URL || 'http://127.0.0.1:8010/';
const report = {version: '1.0.0', date: '2026-11-11', browser: browser.version(), checks: [], errors: []};
const assert = (value, message) => {if (!value) throw new Error(message);};
const ready = page => page.waitForFunction(() => document.getElementById('startup').hidden, null, {timeout: 60000});
const cost = (page, value) => page.waitForFunction(value => document.getElementById('mini-cost').textContent === value, value);
async function points(page) {
  for (const [index, value] of [[0, '59.5, 150.8'], [1, '60.1, 151.9']]) {
    await page.locator('#point-' + index).fill(value); await page.locator('#point-' + index).press('Enter');
  }
}
async function check(id, title, run) {
  try {const fact = await run(); report.checks.push({id, title, status: 'Пройден', fact}); console.log(id, 'PASS');}
  catch (error) {report.checks.push({id, title, status: 'Не пройден', fact: error.message}); console.log(id, 'FAIL', error.message);}
}
let server;
try {
  await check('GH-01', 'Сетевой адаптер включён, интернет недоступен', async () => {
    const context = await browser.newContext();
    try {
      await context.addInitScript(() => Object.defineProperty(Navigator.prototype, 'onLine', {get: () => true, configurable: true}));
      let calls = 0;
      await context.route('https://router.project-osrm.org/**', route => {calls++; return route.abort('internetdisconnected');});
      const page = await context.newPage(); page.on('pageerror', error => report.errors.push(error.message));
      await page.goto(base); await ready(page);
      assert(await page.evaluate(() => navigator.onLine), 'Флаг не включён');
      assert(await page.locator('#connection').count() === 0, 'Индикатор остался');
      await points(page); await page.locator('#build').click();
      await page.waitForFunction(() => document.getElementById('route-message').textContent.includes('Нет связи'), null, {timeout: 20000});
      assert(calls === 1, 'Нет реального запроса к адаптеру');
      const before = calls;
      await page.locator('#mode-manual').click(); await page.locator('#manual-distance').fill('150'); await cost(page, '180,00 ₽');
      assert(calls === before && !(await page.locator('body').innerText()).includes('Есть сеть'), 'Неверный статус или запрос');
      return 'При navigator.onLine=true запрос с реальным отказом fetch показывает ошибку; ручные150км=180руб./чел.; ложного индикатора нет.';
    } finally {await context.close();}
  });
  await check('GH-02', 'Доступный сервис при отрицательном флаге браузера', async () => {
    const context = await browser.newContext();
    try {
      await context.addInitScript(() => Object.defineProperty(Navigator.prototype, 'onLine', {get: () => false, configurable: true}));
      let calls = 0;
      await context.route('https://router.project-osrm.org/**', route => {
        calls++;
        return route.fulfill({contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: JSON.stringify({code: 'Ok', routes: [{distance: 100000, duration: 3600, geometry: {type: 'LineString', coordinates: [[150.8, 59.5], [151.9, 60.1]]}}]})});
      });
      const page = await context.newPage(); page.on('pageerror', error => report.errors.push(error.message));
      await page.goto(base); await ready(page); await points(page); await page.locator('#build').click(); await cost(page, '120,00 ₽');
      assert(calls === 1 && await page.locator('#connection').count() === 0, 'Флаг заблокировал запрос');
      return 'navigator.onLine=false не блокирует доступный тестовый ответ:100км=8л,480руб.,120руб./чел.';
    } finally {await context.close();}
  });
  await check('GH-03', 'Публикация app под именем репозитория', async () => {
    const appRoot = path.resolve('app');
    const prefix = '/autopath-budget/';
    const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png'};
    server = http.createServer((request, response) => {
      const pathname = new URL(request.url, 'http://localhost').pathname;
      if (!pathname.startsWith(prefix)) {response.writeHead(404); response.end(); return;}
      const filename = path.resolve(appRoot, decodeURIComponent(pathname.slice(prefix.length)) || 'index.html');
      if (!filename.startsWith(appRoot + path.sep)) {response.writeHead(403); response.end(); return;}
      fs.readFile(filename, (error, bytes) => {
        if (error) {response.writeHead(404); response.end(); return;}
        response.writeHead(200, {'content-type': types[path.extname(filename)] || 'application/octet-stream'}); response.end(bytes);
      });
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const address = `http://127.0.0.1:${server.address().port}${prefix}`;
    const context = await browser.newContext();
    try {
      const page = await context.newPage(); page.on('pageerror', error => report.errors.push(error.message));
      await page.goto(address); await ready(page);
      await page.locator('#mode-manual').click(); await page.locator('#manual-distance').fill('200'); await cost(page, '240,00 ₽');
      await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller) && document.getElementById('planner-save-state').dataset.saveStatus === 'saved');
      const info = await page.evaluate(async () => {
        const registration = await navigator.serviceWorker.ready;
        const keys = await (await caches.open('autopath-budget-1.0.0')).keys();
        return {scope: new URL(registration.scope).pathname, files: keys.length, paths: keys.map(x => new URL(x.url).pathname)};
      });
      assert(info.scope === prefix && info.files === 30 && info.paths.every(x => x.startsWith(prefix)), JSON.stringify(info));
      await page.reload(); await ready(page); await context.setOffline(true); await page.reload(); await ready(page); await cost(page, '240,00 ₽');
      await page.locator('#manual-distance').fill('300'); await cost(page, '360,00 ₽');
      assert(await page.locator('#connection').count() === 0, 'Индикатор появился после offline reload');
      return {...info, offlineReload: true, manualDistance: '300км', perPerson: '360руб.', note: 'Локальная имитация пути GitHub Pages; на GitHub workflow не запускался.'};
    } finally {await context.close();}
  });
} finally {
  if (server) await new Promise(resolve => server.close(resolve));
  await browser.close(); fs.writeFileSync('tests/results/github-ready-results.json', JSON.stringify(report, null, 2));
}
if (report.checks.some(x => x.status !== 'Пройден') || report.errors.length) process.exitCode = 1;
