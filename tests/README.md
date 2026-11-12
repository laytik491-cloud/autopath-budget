# Проверка проекта

Из корня проекта выполните `python3 -m unittest discover -s tests -v`. Нужен Python 3.11 или новее; дополнительные пакеты не требуются. GitHub Actions выполняет этот набор на Python 3.12 и запускает `python database/verify_db.py`.

## Браузерные проверки

Нужен Node.js и Playwright. Проверенный набор использует Playwright 1.62.1. Для подготовки тестовой среды:

```text
npm install --no-save --no-package-lock playwright@1.62.1
npx playwright install chromium webkit
```

Запустите программу: `python3 launch.py --no-browser --port 8010`. В другом окне из корня проекта выполните:

```text
node tests/browser.mjs
node tests/storage.mjs
node tests/long-route.mjs
node tests/github-ready.mjs
node tests/webkit.mjs
```

Если адрес отличается, задайте APP_URL с напечатанным адресом. При внешней установке Playwright можно задать PLAYWRIGHT_PATH с абсолютным путём к index.mjs.

Браузерные проверки создают временные профили и не затрагивают личные данные. OSRM подменяется в тестах, кроме LIVE-01. storage.mjs специально вызывает transaction.abort и проверяет испорченный образ. Старый образ fixtures/schema-v1.sqlite нужен для проверки миграции. magadan-moscow.json — полный ответ OSRM для заданных координат от10.11.2026.

GitHub Actions не запускает браузерные сценарии. Локальные результаты находятся в results. В WebKit 26.5 известна ошибка полной перезагрузки без сети; этот тест может завершиться с кодом 1, хотя пересчёт открытой вкладки проходит. Физические устройства это не заменяет.
