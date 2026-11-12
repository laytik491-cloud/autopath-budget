# База данных MVP 1.0.0

`autopath.sqlite` — пустая база поставки со схемой 2. Схемы `schema.sql` и `../app/schema.sql` совпадают. Таблицы: draft, point, route, manual_trip, event_log.

Рабочий расчёт хранится в браузере: Python создаёт SQLite, а storage.mjs записывает её образ в IndexedDB. Файл рядом с программой автоматически не изменяется. В режиме карты сохраняются draft, две point и route; в ручном — manual_trip. Repository сохраняет только один режим и проверяет целостность образа.

Создание отдельного пустого файла:

```bash
python3 database/init_db.py database/new.sqlite
```

Проверка SQL без изменения рабочей базы:

```bash
python3 database/verify_db.py
```

Скрипт выполняет 26 положительных и отрицательных проверок, записывает verification-results.json и verification-results.txt, создаёт отдельную тестовую autopath-test.sqlite. seed.sql содержит только контрольные данные для тестовой БД; программа их не загружает. queries.sql показывает SELECT и JOIN. Для 600 км, 8 л/100 км, 60 ₽/л и 4 участников ожидаются 48 л, 2880 ₽ и 720 ₽/чел.

Схема 2 и логический формат draft.schema_version=1 — разные параметры. Совместимый образ схемы 1 распознаётся и проверяется, неизвестный или повреждённый образ не перезаписывается. Отдельный файл tests/fixtures/schema-v1.sqlite применяется только в проверках Repository.

[ER-диаграмма](../docs/database/er-diagram.svg). Дополнительные проверки хранения находятся в tests/test_core.py, tests/test_manual.py и tests/storage.mjs.
