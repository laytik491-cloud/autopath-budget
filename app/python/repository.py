import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from calculator import decimal_text, validate
from geo import validate_point, validate_route


class StorageError(ValueError):
    pass


def validate_draft(draft):
    try:
        if not isinstance(draft, dict) or draft.get('id') != 'current' or draft.get('schemaVersion') != 1:
            raise StorageError('Неподдерживаемый формат черновика')
        for name in ['revision', 'pointsRevision']:
            value = draft.get(name)
            if type(value) is not int or not 1 <= value <= 9007199254740991:
                raise StorageError('Некорректная версия черновика')
        mode = draft.get('mode', 'map')
        parameters = validate(draft.get('parameters', {}))
        if mode == 'manual':
            if draft.get('points') != [] or draft.get('route') is not None:
                raise StorageError('Ручное расстояние не является маршрутом')
            return {
                'id': 'current', 'schemaVersion': 1, 'mode': 'manual',
                'revision': draft['revision'], 'pointsRevision': draft['pointsRevision'],
                'distanceText': decimal_text(draft.get('distanceText', ''), '0.01', '1000000'),
                'parameters': parameters, 'points': [], 'route': None
            }
        if mode != 'map':
            raise StorageError('Неизвестный режим расчёта')
        points = draft.get('points')
        if not isinstance(points, list) or len(points) != 2:
            raise StorageError('В черновике должны быть две точки')
        points = [validate_point(point) for point in points]
        if points[0]['lat'] == points[1]['lat'] and points[0]['lon'] == points[1]['lon']:
            raise StorageError('Точки черновика совпадают')
        route = validate_route(draft.get('route'))
        if route.get('pointsRevision') != draft['pointsRevision']:
            raise StorageError('Маршрут не соответствует точкам')
        result = {
            'id': 'current', 'schemaVersion': 1,
            'revision': draft['revision'], 'pointsRevision': draft['pointsRevision'],
            'points': points, 'parameters': parameters,
            'route': {name: route[name] for name in ['distanceM', 'durationS', 'obtainedAt', 'pointsRevision']}
        }
        if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) > 102400:
            raise StorageError('Черновик превышает 100 КБ')
        return result
    except StorageError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StorageError('Черновик содержит некорректные данные')


class Repository:
    def __init__(self, path, schema_text, app_version='1.0.0'):
        self.path = Path(path)
        self.schema_text = schema_text
        self.app_version = str(app_version)
        self.migrated = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.connect() as connection:
                connection.executescript(schema_text)
        self.confirmed = self.path.read_bytes()
        self.check()
        self.confirmed = self.path.read_bytes()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path))
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def check(self):
        try:
            with self.connect() as connection:
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version not in (1, 2):
                    raise StorageError('Версия базы данных не поддерживается')
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise StorageError('База данных повреждена')
                if connection.execute('PRAGMA foreign_key_check').fetchall():
                    raise StorageError('Нарушены связи данных')
                expected = {
                    'draft': ['id', 'schema_version', 'revision', 'points_revision', 'consumption_text', 'price_text', 'participants', 'start_position', 'end_position'],
                    'point': ['draft_id', 'position', 'label', 'lat', 'lon'],
                    'route': ['draft_id', 'points_revision', 'distance_m', 'duration_s', 'obtained_at'],
                    'event_log': ['event_id', 'occurred_at', 'code', 'app_version', 'status']
                }
                if version == 2:
                    expected['manual_trip'] = ['id', 'revision', 'distance_text', 'consumption_text', 'price_text', 'participants']
                actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if actual != set(expected):
                    raise StorageError('Структура базы данных не поддерживается')
                reference = sqlite3.connect(':memory:')
                reference.executescript(self.schema_text if version == 2 else Path(__file__).with_name('schema-v1.sql').read_text())
                expected_sql = {row[0]: (row[1], row[2]) for row in reference.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
                reference.close()
                actual_sql = {row[0]: (row[1], row[2]) for row in connection.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
                if actual_sql != expected_sql:
                    raise StorageError('Структура базы данных не поддерживается')
                for name, columns in expected.items():
                    if [row[1] for row in connection.execute(f'PRAGMA table_info({name})')] != columns:
                        raise StorageError('Структура базы данных не поддерживается')
                if connection.execute('SELECT count(*) FROM event_log').fetchone()[0] > 100:
                    raise StorageError('Некорректный журнал событий')
            if version == 1:
                self.load(legacy=True)
                reference = sqlite3.connect(':memory:')
                reference.executescript(self.schema_text)
                sql = reference.execute("SELECT sql FROM sqlite_master WHERE name='manual_trip'").fetchone()[0]
                reference.close()
                with self.connect() as connection:
                    connection.execute(sql)
                    connection.execute('PRAGMA user_version=2')
                self.migrated = True
            self.load()
        except sqlite3.DatabaseError:
            raise StorageError('Файл базы данных повреждён')

    def load_bytes(self, data):
        original = self.confirmed
        try:
            self.path.write_bytes(bytes(data))
            self.check()
            self.confirmed = self.path.read_bytes()
            return self.load()
        except Exception:
            self.path.write_bytes(original)
            raise

    def load(self, legacy=False):
        try:
            with self.connect() as connection:
                manual = None if legacy else connection.execute('SELECT revision,distance_text,consumption_text,price_text,participants FROM manual_trip WHERE id=?', ('current',)).fetchone()
                if manual:
                    if any(connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0] for name in ['draft', 'point', 'route']):
                        raise StorageError('В базе сохранены два разных расчёта')
                    return validate_draft({
                        'id': 'current', 'schemaVersion': 1, 'mode': 'manual',
                        'revision': manual[0], 'pointsRevision': 1, 'distanceText': manual[1],
                        'points': [], 'route': None,
                        'parameters': {'consumption': manual[2], 'price': manual[3], 'participants': manual[4]}
                    })
                row = connection.execute('SELECT schema_version,revision,points_revision,consumption_text,price_text,participants FROM draft WHERE id=?', ('current',)).fetchone()
                if row is None:
                    if connection.execute('SELECT count(*) FROM point').fetchone()[0] or connection.execute('SELECT count(*) FROM route').fetchone()[0]:
                        raise StorageError('Обнаружены данные без черновика')
                    return None
                points = [{'label': item[0], 'lat': item[1], 'lon': item[2]} for item in connection.execute('SELECT label,lat,lon FROM point WHERE draft_id=? ORDER BY position', ('current',))]
                route = connection.execute('SELECT points_revision,distance_m,duration_s,obtained_at FROM route WHERE draft_id=?', ('current',)).fetchone()
                if not route:
                    raise StorageError('Маршрут черновика отсутствует')
                return validate_draft({
                    'id': 'current', 'schemaVersion': row[0], 'revision': row[1], 'pointsRevision': row[2],
                    'points': points, 'parameters': {'consumption': row[3], 'price': row[4], 'participants': row[5]},
                    'route': {'pointsRevision': route[0], 'distanceM': route[1], 'durationS': route[2], 'obtainedAt': route[3]}
                })
        except sqlite3.DatabaseError:
            raise StorageError('Не удалось прочитать черновик')

    def save(self, draft, code='DRAFT_SAVED'):
        draft = validate_draft(draft)
        self.path.write_bytes(self.confirmed)
        try:
            with self.connect() as connection:
                connection.execute('DELETE FROM draft WHERE id=?', ('current',))
                connection.execute('DELETE FROM manual_trip')
                p = draft['parameters']
                if draft.get('mode') == 'manual':
                    connection.execute('INSERT INTO manual_trip VALUES(?,?,?,?,?,?)', ('current', draft['revision'], draft['distanceText'], p['consumption'], p['price'], p['participants']))
                else:
                    connection.execute('INSERT INTO draft(id,schema_version,revision,points_revision,consumption_text,price_text,participants) VALUES(?,?,?,?,?,?,?)', ('current', 1, draft['revision'], draft['pointsRevision'], p['consumption'], p['price'], p['participants']))
                    for index, point in enumerate(draft['points']):
                        connection.execute('INSERT INTO point VALUES(?,?,?,?,?)', ('current', index, point['label'], point['lat'], point['lon']))
                    route = draft['route']
                    connection.execute('INSERT INTO route VALUES(?,?,?,?,?)', ('current', draft['pointsRevision'], route['distanceM'], route['durationS'], route['obtainedAt']))
                connection.execute('INSERT INTO event_log(occurred_at,code,app_version,status) VALUES(?,?,?,?)', (datetime.now(timezone.utc).isoformat(), code, self.app_version, 'ready' if code == 'ROUTE_READY' else 'saved'))
            return self.path.read_bytes()
        except sqlite3.DatabaseError:
            self.path.write_bytes(self.confirmed)
            raise StorageError('Не удалось записать черновик')

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
            with self.connect() as connection:
                connection.executescript(self.schema_text)
            return self.path.read_bytes()
        except (sqlite3.DatabaseError, OSError):
            self.path.write_bytes(self.confirmed)
            raise StorageError('Не удалось очистить данные')

    def commit(self, data):
        self.confirmed = bytes(data)
        self.path.write_bytes(self.confirmed)

    def rollback(self):
        self.path.write_bytes(self.confirmed)

    def bytes(self):
        return self.confirmed
