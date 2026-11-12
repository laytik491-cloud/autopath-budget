import fs from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1366, height: 768}, serviceWorkers: 'block'});
const page = await context.newPage();
const result = {release: 'MVP 1.0.0', version: '1.0.0', date: '2026-11-11', browser: browser.version(), checks: [], errors: [], note: 'Полная геометрия — сохранённый реальный ответ OSRM от 10.11.2026, 56063 точки, 9141358 м. Поиск названий подменён в тесте соответствующими координатами. LIVE-01 отдельного протокола проверяет сервис без подмены.'};
page.on('pageerror', error => result.errors.push(error.message));
const actual = fs.readFileSync('tests/fixtures/magadan-moscow.json', 'utf8');
await context.route('https://router.project-osrm.org/**', route => route.fulfill({contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: actual}));
await context.route('https://photon.komoot.io/**', route => {
  const magadan = new URL(route.request().url()).searchParams.get('q') === 'Магадан';
  return route.fulfill({contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: JSON.stringify({type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'Point', coordinates: magadan ? [150.8085, 59.5682] : [37.6176, 55.7558]}, properties: {name: magadan ? 'Магадан' : 'Москва'}}]})});
});
await context.route('**/main.mjs', async route => {
  const response = await route.fetch();
  await route.fulfill({response, body: await response.text() + '\nglobalThis.mapTest = {map, layer: () => routeLayer}; globalThis.testMessages = []; worker.addEventListener("message", event => { if (event.data.state) testMessages.push(event.data.state); });'});
});
const assert = (value, message) => { if (!value) throw new Error(message); };
const ready = () => page.waitForFunction(() => document.getElementById('startup').hidden, null, {timeout: 60000});
async function check(id, name, run) {
  try { const fact = await run(); result.checks.push({id, name, status: 'Пройден', fact}); console.log(id, 'PASS'); }
  catch (error) { result.checks.push({id, name, status: 'Не пройден', fact: error.message}); console.log(id, 'FAIL', error.message); }
}
try {
  await page.goto(process.env.APP_URL || 'http://127.0.0.1:8010/'); await ready();
  for (const [index, city] of [[0, 'Магадан'], [1, 'Москва']]) {
    await page.locator('#point-' + index).fill(city); await page.locator('.search[data-index="' + index + '"]').click(); await page.locator('#results-' + index + ' button').first().click();
  }
  await page.locator('#build').click();
  await page.waitForFunction(() => document.getElementById('distance').textContent === '9141,36 км', null, {timeout: 30000});
  await page.waitForTimeout(400);
  await check('LR-01', 'Полный путь и обе метки', async () => {
    const info = await page.evaluate(() => {
      const map = mapTest.map; const layer = mapTest.layer(); const size = map.getSize(); let count = 0; let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      layer.eachLayer(line => line.getLatLngs().forEach(point => { const p = map.latLngToContainerPoint(point); count++; minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }));
      return {count, minX, minY, maxX, maxY, width: size.x, height: size.y, zoom: map.getZoom(), markers: [...document.querySelectorAll('.leaflet-marker-icon')].map(x => x.getBoundingClientRect().toJSON()), map: document.getElementById('map').getBoundingClientRect().toJSON()};
    });
    assert(info.count === 56063, 'Утеряна часть геометрии');
    assert(info.minX >= 20 && info.maxX <= info.width - 20 && info.minY >= 20 && info.maxY <= info.height - 20, JSON.stringify(info));
    for (const m of info.markers) assert(m.left >= info.map.left && m.right <= info.map.right && m.top >= info.map.top && m.bottom <= info.map.bottom, 'Метка за рамкой');
    return info;
  });
  await check('LR-02', 'Цена сохраняет линию и ручной масштаб', async () => {
    const before = await page.evaluate(() => {mapTest.map.zoomIn(.5, {animate: false}); testMessages.length = 0; return {layer: L.stamp(mapTest.layer()), zoom: mapTest.map.getZoom()};});
    await page.locator('#price').fill('65'); await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '11883,77 ₽');
    const after = await page.evaluate(() => ({layer: L.stamp(mapTest.layer()), zoom: mapTest.map.getZoom(), sizes: testMessages.map(x => JSON.stringify(x).length), geometries: testMessages.filter(x => x.route?.geometry).length}));
    assert(before.layer === after.layer && before.zoom === after.zoom, JSON.stringify({before, after}));
    assert(after.geometries === 0 && after.sizes.every(x => x < 10000), 'Геометрия отправлена повторно');
    await page.locator('#price').fill('60'); await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '10969,63 ₽');
    return {before, after};
  });
  await check('LR-03', 'Возврат к целому пути одним нажатием', async () => {
    await page.evaluate(() => mapTest.map.setView([59.5682, 150.8085], 10, {animate: false}));
    await page.locator('#fit-route').click();
    const fits = await page.evaluate(() => {const map = mapTest.map; return map.getBounds().contains(mapTest.layer().getBounds()) && map.getZoom() < 5;});
    assert(fits, 'Путь остался за границами'); return 'После увеличения Магадана кнопка вернула весь путь.';
  });
  await check('LR-04', 'Карта и результат без прокрутки', async () => {
    await page.locator('#price').fill('60'); await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '10969,63 ₽');
    const facts = [];
    for (const [width, height] of [[1440, 900], [1366, 768], [1280, 720], [1024, 768], [768, 1024], [390, 844], [360, 800]]) {
      await page.setViewportSize({width, height}); await page.waitForTimeout(250);
      const fact = await page.evaluate(() => {
        const map = mapTest.map; const rect = document.getElementById('map').getBoundingClientRect(); const summary = document.querySelector('.trip-summary').getBoundingClientRect(); const form = document.querySelector('.form-panel').getBoundingClientRect(); const footer = document.querySelector('footer');
        return {width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight, formBottom: form.bottom, mapHeight: rect.height, summaryBottom: summary.bottom, footerTop: getComputedStyle(footer).display === 'none' ? innerHeight : footer.getBoundingClientRect().top, routeFits: map.getBounds().contains(mapTest.layer().getBounds())};
      });
      assert(fact.scrollWidth <= width && fact.scrollHeight <= height, JSON.stringify(fact));
      assert(fact.summaryBottom <= fact.footerTop && fact.formBottom <= fact.footerTop && fact.routeFits, JSON.stringify(fact));
      facts.push(fact);
      if (width === 1366) await page.screenshot({path: 'docs/mvp/screenshots/long-route.png', fullPage: true});
      if (width === 390) await page.screenshot({path: 'docs/mvp/screenshots/long-route-mobile.png', fullPage: true});
    }
    return facts;
  });
  await check('LR-05', 'Переключение ручного режима и возврат линии', async () => {
    await page.locator('#mode-manual').click(); await page.locator('#manual-distance').fill('150');
    await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '180,00 ₽');
    await page.locator('#mode-map').click();
    await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '10969,63 ₽');
    const n = await page.evaluate(() => {let n = 0; mapTest.layer().eachLayer(x => n += x.getLatLngs().length); return n;});
    assert(n === 56063, 'После возврата линия потеряна'); return n;
  });
  await check('LR-06', 'Справка и удалённый текст', async () => {
    const body = await page.locator('body').innerText(); assert(!body.includes('Поиск адресов — Photon.'), 'Текст остался');
    await page.locator('nav a[href="#help"]').click();
    assert(!(await page.locator('#help').innerText()).includes('Запуск на устройствах'), 'Инструкции остались');
    assert(!await page.locator('#help details').count(), 'Пункты устройств остались');
    const views = [];
    for (const [width, height] of [[1366, 768], [390, 844], [360, 800]]) {
      await page.setViewportSize({width, height});
      for (const name of ['help', 'result']) {
        await page.locator('nav a[href="#' + name + '"]').click();
        await page.locator('#' + name).waitFor({state: 'visible'});
        await page.waitForTimeout(100);
        const size = await page.evaluate(() => ({width: innerWidth, height: innerHeight, scrollHeight: document.documentElement.scrollHeight, scrollWidth: document.documentElement.scrollWidth}));

        assert(size.scrollHeight <= height && size.scrollWidth <= width, JSON.stringify({view: name, ...size}));
        views.push({view: name, ...size});
      }
    }
    return {removed: true, views};
  });
} finally {
  fs.writeFileSync('tests/results/long-route-results.json', JSON.stringify(result, null, 2)); await browser.close();
}
if (result.checks.some(x => x.status !== 'Пройден') || result.errors.length) process.exitCode = 1;
