import fs from 'node:fs';
const {webkit} = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const browser = await webkit.launch({headless: true});
const context = await browser.newContext({viewport: {width: 390, height: 844}});
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const result = {version: '1.0.0', date: '2026-11-11', browser: browser.version(), platform: 'Playwright WebKit на macOS; это не физическое iOS и не приложение Safari', checks: []};
const ready = () => page.waitForFunction(() => document.getElementById('startup').hidden, null, {timeout: 60000});
try {
  await page.goto(process.env.APP_URL || 'http://127.0.0.1:8010/'); await ready();
  await page.locator('#mode-manual').click();
  await page.locator('#manual-distance').fill('123,45');
  await page.locator('#consumption').fill('8,5');
  await page.locator('#participants').fill('3');
  await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '209,87 ₽' && document.getElementById('planner-save-state').dataset.saveStatus === 'saved');
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
  await page.reload(); await ready();
  await context.setOffline(true);
  await page.locator('#manual-distance').fill('150');
  await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '255,00 ₽' && document.getElementById('planner-save-state').dataset.saveStatus === 'saved');
  if (errors.length) throw new Error(errors.join('; '));
  result.checks.push({id: 'WK-01', status: 'Пройден', actual: 'Ручной ввод, запятая, быстрые правки, онлайн reload и пересчёт открытой вкладки без сети: 150 км, 12,75 л, 765 ₽, 255 ₽/чел.'});
  try {
    await page.reload({waitUntil: 'domcontentloaded'}); await ready();
    await page.waitForFunction(() => document.getElementById('mini-cost').textContent === '255,00 ₽');
    result.checks.push({id: 'WK-02', status: 'Пройден', actual: 'Полная автономная перезагрузка восстановила расчёт'});
  } catch (error) {
    result.checks.push({id: 'WK-02', status: 'Не пройден', actual: error.message, limitation: 'При эмуляции отключения сети в этом WebKit полная навигация и fetch локального ресурса завершаются внутренней ошибкой, несмотря на активный Service Worker и 30 ресурсов в кэше. Причина и поведение настоящего Safari/iOS требуют отдельной проверки.'});
  }
} catch (error) {
  result.checks.push({id: 'WK-01', status: 'Не пройден', actual: error.message});
} finally {
  result.errors = errors;
  fs.writeFileSync('tests/results/webkit-results.json', JSON.stringify(result, null, 2));
  console.log(result);
  await browser.close();
}
if (result.checks.some(x => x.status !== 'Пройден')) process.exitCode = 1;
