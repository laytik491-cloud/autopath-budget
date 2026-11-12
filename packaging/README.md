# АвтоПуть Бюджет

Исходники установленных приложений MVP 1.0.0. В `app` находится та же программа, что в браузерном проекте. Расчёты выполняет Python через Pyodide; JavaScript и платформенные оболочки обеспечивают окно, загрузку ресурсов и доступ к хранилищу.

## Подготовка

Нужны Node.js 24 и pnpm 11.25.0. Из этой папки выполните:

```bash
pnpm install --frozen-lockfile --ignore-scripts
node node_modules/electron/install.js
```

## Windows и macOS

Открыть окно разработки:

```bash
pnpm start
```

Собрать универсальный DMG на Mac:

```bash
pnpm dist:mac
```

Собрать EXE для Windows x64:

```bash
pnpm dist:win
```

Установщики появятся в `dist`. На Mac папка сборки должна находиться вне синхронизируемого Desktop/iCloud: служебные атрибуты Finder могут мешать подписи. При необходимости задайте `--config.directories.output=/абсолютный/путь/к/сборке` после команды electron-builder. Подпись Mac в этой конфигурации — ad hoc, нотариализация отключена. Для распространения с подтверждённым издателем потребуются собственные сертификаты Apple и Windows.

`desktop/main.cjs` регистрирует локальный защищённый адрес `autopath://app/`, загружает файлы из `app` и создаёт окно Electron. Хранилище имеет постоянный адрес и не зависит от свободного TCP-порта. Node.js в странице отключён; внешние ссылки открываются обычным браузером.

## Android

Нужен полный JDK 21 (включая `jlink`) и Android SDK с платформой 36 и Build Tools 36.0.0. Укажите путь SDK в локальном `android/local.properties` через `sdk.dir=...` или используйте настройки Android Studio. Этот файл не входит в репозиторий.

Перед первой сборкой Android и после изменения файлов в `app`:

```bash
pnpm android:sync
```

На macOS и Linux:

```bash
cd android
./gradlew assembleRelease
```

В Windows:

```powershell
cd android
.\gradlew.bat assembleRelease
```

Результат — `android/app/build/outputs/apk/release/app-release-unsigned.apk`. Перед установкой подпишите его своим ключом через `apksigner`; ключи и пароли не включаются в исходники. Готовый APK в выпуске 1.0.0 на GitHub уже подписан локальным ключом выпуска.

Минимальная версия Android — 12, версия приложения — 1.0.0, код версии — 1. `capacitor.config.json` использует локальные ресурсы из `app`, без внешнего сервера программы.

## Состав

```text
.
├── app/
├── android/
├── build/                  Значки для установщиков
├── desktop/main.cjs
├── capacitor.config.json
├── package.json
├── pnpm-lock.yaml
└── README.md
```

Зафиксированные зависимости: Electron 45.3.0, electron-builder 26.18.0, Capacitor 8.6.0. Версии включённых Pyodide и Leaflet указаны в основном проекте и их лицензиях внутри `app/vendor`.

## Документация

[Пояснительная записка](<docs/ВПКС Самарин MVP 1.0.0.docx>) и [результаты проверки](docs/ПРОВЕРКА.md) включены в исходники. Готовые DMG и EXE превышают 100 МиБ; на GitHub размещайте установщики в Releases.

[Скачать готовые приложения](https://github.com/laytik491-cloud/autopath-budget/releases/tag/v1.0.0).
