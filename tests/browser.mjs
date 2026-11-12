import fs from 'node:fs';
const {chromium, webkit} = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const engine = process.env.BROWSER === 'webkit' ? webkit : chromium;
const browser = await engine.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1050}});
const base = process.env.APP_URL || 'http://127.0.0.1:8010/';
const output = {version: '1.0.0', date: '2026-11-11', browser: browser.version(), engine: process.env.BROWSER || 'chromium', checks: [], errors: [], note: 'OSRM подменён только в тесте. Проверки живых внешних сервисов отмечены отдельно.'};
const page = await context.newPage();
page.setDefaultTimeout(12000);
page.on('pageerror', error => output.errors.push(error.message));
let calls = 0;
let delayed = false;
await context.route('https://tile.openstreetmap.org/**', route => route.abort());
await context.route('https://router.project-osrm.org/**', async route => {
  calls++;
  if (delayed) await new Promise(resolve => setTimeout(resolve, 600));
  await route.fulfill({contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: JSON.stringify({code: 'Ok', routes: [{distance: 600000, duration: 7199, geometry: {type: 'LineString', coordinates: [[150.8, 59.5], [151.9, 60.1]]}}]})});
});
const assert = (value, message) => { if (!value) throw new Error(message); };
const ready = () => page.waitForFunction(() => document.getElementById('startup').hidden, null, {timeout: 60000});
const cost = value => page.waitForFunction(value => document.getElementById('mini-cost').textContent === value, value);
const saved = () => page.waitForFunction(() => document.getElementById('planner-save-state').dataset.saveStatus === 'saved');
const fill = (id, value) => page.locator('#' + id).fill(value);
const point = async (id, value) => { await fill('point-' + id, value); await page.locator('#point-' + id).press('Enter'); };
async function check(id, title, run) {
  try { const actual = await run(); output.checks.push({id, title, status: 'Пройден', actual}); console.log(id, 'PASS'); }
  catch (error) { output.checks.push({id, title, status: 'Не пройден', actual: error.message}); console.log(id, 'FAIL', error.message); }
}
try {
  await page.goto(base); await ready();
  await check('UI-01', 'Ручной расчёт без точек', async () => {
    const before = calls;
    await page.locator('#mode-manual').click(); await fill('manual-distance', '150'); await cost('180,00 ₽'); await saved();
    assert(await page.locator('#mini-litres').textContent() === '12,00 л', 'Литры');
    assert(await page.locator('#mini-total').textContent() === '720,00 ₽', 'Общая сумма');
    assert(calls === before, 'Был запрос маршрута');
    assert(await page.locator('#map-panel').isHidden(), 'Карта не скрыта');
    return 'Два нажатия: режим и поле; ввод 150 км дал 12 л, 720 ₽, 180 ₽/чел. без подтверждения и OSRM.';
  });
  await check('UI-02', 'Параметры и запятая сразу при вводе', async () => {
    await fill('manual-distance', '123,45'); await fill('consumption', '8,5'); await fill('participants', '3'); await cost('209,87 ₽');
    assert(await page.locator('#mini-total').textContent() === '629,60 ₽', 'Промежуточное округление');
    await fill('price', '65'); await cost('227,35 ₽');
    return '123,45 км × 8,5 × 60 / 100 / 3 = 209,87 ₽; цена 65 дала 227,35 ₽ без Enter.';
  });
  await check('UI-03', 'Ошибки не оставляют старый результат', async () => {
    for (const invalid of ['0', '-1', '1000001', 'abc', '']) {
      await fill('manual-distance', invalid); await cost('— ₽');
      assert(await page.locator('#manual-distance').getAttribute('aria-invalid') === 'true', 'Нет ошибки поля ' + invalid);
    }
    await fill('manual-distance', '150'); await fill('consumption', '8'); await fill('price', '60'); await fill('participants', '4'); await cost('180,00 ₽'); await saved();
    return 'Пустое значение, 0, отрицательное, превышение и текст скрывают старый итог; исправление восстанавливает расчёт.';
  });
  await check('UI-04', 'Восстановление ручного расчёта', async () => {
    await page.reload(); await ready(); await cost('180,00 ₽');
    assert(await page.locator('#mode-manual').getAttribute('aria-pressed') === 'true', 'Режим потерян');
    assert(await page.locator('#manual-distance').inputValue() === '150', 'Расстояние потеряно');
    return 'После полного reload восстановлены ручной режим, 150 км, параметры и 180 ₽/чел.';
  });
  await check('UI-05', 'Новый расчёт и полный запуск без сети', async () => {
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    await page.reload(); await ready();
    await context.setOffline(true); await page.reload(); await ready(); await cost('180,00 ₽');
    await fill('manual-distance', '250'); await cost('300,00 ₽'); await saved();
    await page.reload(); await ready(); await cost('300,00 ₽');
    return 'Реальное отключение сети: новый ввод 250 км, сохранение и повторный запуск дали 20 л, 1200 ₽, 300 ₽/чел.';
  });
  await check('UI-06', 'Новая поездка без старого маршрута и интернета', async () => {
    await page.locator('nav a[href="#result"]').click(); await page.locator('#clear').click(); await page.locator('#cancel-clear').click(); await cost('300,00 ₽');
    await page.locator('#clear').click(); await page.locator('#confirm-clear').click(); await saved();
    await page.locator('#mode-manual').click(); await fill('manual-distance', '50'); await cost('60,00 ₽'); await saved();
    await context.setOffline(false);
    return 'Отмена очистки сохраняет данные; подтверждение удаляет. С пустого состояния без сети 50 км дали 4 л, 240 ₽, 60 ₽/чел.';
  });
  await check('UI-07', 'Карта за три нажатия', async () => {
    await page.locator('#mode-map').click(); await cost('— ₽');
    const map = page.locator('#map');
    await map.click({position: {x: 150, y: 180}});
    await page.waitForFunction(() => document.getElementById('confirmed-0').textContent.includes('✓'));
    await map.click({position: {x: 300, y: 260}});
    await page.waitForFunction(() => document.getElementById('confirmed-1').textContent.includes('✓'));
    await page.locator('#build').click(); await cost('720,00 ₽'); await saved();
    assert(await page.locator('#duration').textContent() === '2 ч 0 мин', 'Некорректное округление времени');
    return 'При выбранном режиме карты: А, Б, построить — три нажатия. Ответ теста 600 км дал 48 л, 2880 ₽, 720 ₽/чел.; время без 60 минут.';
  });
  await check('UI-08', 'Смена точки скрывает старый итог', async () => {
    await fill('point-1', '60.1, 151.9'); await cost('— ₽');
    await page.locator('#point-1').press('Enter'); await page.locator('#build').click(); await cost('720,00 ₽');
    return 'Редактирование конечной точки сразу убирает прежний итог; новое построение возвращает актуальный расчёт.';
  });
  await check('UI-09', 'Ручной режим во время сетевого запроса', async () => {
    delayed = true;
    await page.locator('#build').click(); await page.locator('#mode-manual').click(); await fill('manual-distance', '100'); await cost('120,00 ₽');
    await page.waitForTimeout(900); await cost('120,00 ₽'); delayed = false;
    return 'Поздний OSRM не заменяет вручную введённые 100 км и 120 ₽/чел.';
  });
  await check('UI-10', 'Границы параметров и участников', async () => {
    await fill('participants', '9'); await page.locator('#plus').click(); assert(await page.locator('#participants').inputValue() === '9', 'Больше 9');
    await fill('participants', '1'); await page.locator('#minus').click(); assert(await page.locator('#participants').inputValue() === '1', 'Меньше 1');
    await fill('price', '0'); await cost('— ₽'); await fill('price', '1000'); await fill('consumption', '100'); await fill('manual-distance', '1000000'); await cost('1000000000,00 ₽');
    await saved();
    return 'Участники 1–9; нулевая цена отклонена; верхние границы дали 1 000 000 000 ₽ без переполнения.';
  });
  await check('UI-11', 'Телефон и большие значения', async () => {
    for (const width of [360, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 900}); await page.waitForTimeout(180);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      assert(!overflow, 'Горизонтальная прокрутка ' + width);
    }
    await fill('manual-distance', '150'); await fill('consumption', '8'); await fill('price', '60'); await fill('participants', '4'); await cost('180,00 ₽');
    await page.screenshot({path: 'docs/mvp/screenshots/manual.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844}); await page.waitForTimeout(180);
    await page.screenshot({path: 'docs/mvp/screenshots/mobile.png', fullPage: true});
    assert(await page.locator('.trip-summary').evaluate(element => element.getBoundingClientRect().bottom < 844), 'Результат ниже первого экрана');
    await page.setViewportSize({width: 1440, height: 1050});
    return '360/390/768/1440 px без горизонтальной прокрутки; на 390 px ручной результат помещается на первом экране.';
  });
  await check('UI-12', 'Подробный расчёт и справка', async () => {
    await page.locator('.summary-heading a').click();
    assert((await page.locator('#route-description').textContent()).includes('вручную'), 'Неверный источник');
    assert((await page.locator('#route-date').textContent()).includes('не определяется'), 'Выдуманное время');
    await page.screenshot({path: 'docs/mvp/screenshots/result.png', fullPage: true});
    await page.locator('nav a[href="#help"]').click();
    assert(!(await page.locator('#help').innerText()).includes('Запуск на устройствах'), 'Инструкции запуска остались');
    assert(await page.locator('#help details').count() === 0, 'Старые инструкции устройств');
    await page.screenshot({path: 'docs/mvp/screenshots/help.png', fullPage: true});
    await page.locator('nav a[href="#planner"]').click();
    return 'Подробности доступны одним нажатием; ручной источник указан, время не выдумано; инструкции запуска удалены из справки.';
  });
  await check('UI-13', 'Сохранение последнего корректного ввода', async () => {
    await saved(); await fill('manual-distance', '0'); await cost('— ₽');
    await page.reload(); await ready(); await cost('180,00 ₽');
    assert(await page.locator('#manual-distance').inputValue() === '150', 'Некорректное значение заменило сохранённый результат');
    return 'Неверный новый ввод не заменяет сохранённые 150 км; после открытия восстановлен последний корректный расчёт.';
  });
  await check('UI-14', 'Чистый интерфейс и готовность автономного кэша', async () => {
    const status = await context.request.get(new URL('prototype/', base).href);
    assert(status.status() === 404, 'Прототип доступен');
    assert(await page.locator('#demo').count() === 0, 'Пример остался');
    const cache = await page.evaluate(async () => {
      const cache = await caches.open('autopath-budget-1.0.0');
      const keys = await cache.keys();
      return {count: keys.length, external: keys.filter(x => new URL(x.url).origin !== location.origin).length, migration: keys.some(x => x.url.endsWith('/python/schema-v1.sql'))};
    });
    assert(cache.external === 0 && cache.migration && cache.count === 30, JSON.stringify(cache));
    return cache;
  });
  await check('LIVE-01', 'Живой OSRM и Photon', async () => {
    await context.unroute('https://router.project-osrm.org/**');
    await page.locator('#mode-map').click();
    await point(0, '55.75, 37.61'); await point(1, '55.76, 37.64');
    await page.locator('#build').click();
    await page.waitForFunction(() => document.getElementById('mini-cost').textContent !== '— ₽', null, {timeout: 22000});
    const distance = await page.locator('#distance').textContent();
    await page.screenshot({path: 'docs/mvp/screenshots/planner.png', fullPage: true});
    await fill('point-0', 'Москва'); await page.locator('.search[data-index="0"]').click();
    await page.locator('#results-0 button').first().waitFor({timeout: 22000});
    return {distance, addressResults: await page.locator('#results-0 button').count(), source: 'Живые публичные сервисы, подмена отключена'};
  });
} finally {
  fs.mkdirSync('tests/results', {recursive: true});
  fs.writeFileSync(`tests/results/${process.env.BROWSER || 'chromium'}-results.json`, JSON.stringify(output, null, 2));
  await browser.close();
}
if (output.checks.some(x => x.status !== 'Пройден') || output.errors.length) process.exitCode = 1;
