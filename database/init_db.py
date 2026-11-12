import argparse
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description='Создание пустой базы АвтоПуть Бюджет')
parser.add_argument('path', nargs='?', default=str(Path(__file__).with_name('autopath.sqlite')))
args = parser.parse_args()
path = Path(args.path)
if path.exists():
    raise SystemExit('Файл уже существует. Укажите новое имя для пустой базы')
path.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(path) as connection:
    connection.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
    result = connection.execute('PRAGMA integrity_check').fetchone()[0]
print(f'{path}: {result}, схема 2')
