import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app' / 'python'))

from calculator import ValidationError, calculate, validate
from controller import TripController
from geo import GeoAdapter, GeoError, validate_point, validate_route
from repository import Repository, StorageError, validate_draft

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / 'app' / 'schema.sql').read_text(encoding='utf-8') if (ROOT / 'app' / 'schema.sql').exists() else (ROOT.parent / 'database' / 'schema.sql').read_text(encoding='utf-8')


def draft():
    return {
        'id': 'current', 'schemaVersion': 1, 'revision': 1, 'pointsRevision': 1,
        'points': [{'label': 'A', 'lat': 59.5, 'lon': 150.8}, {'label': 'B', 'lat': 60.1, 'lon': 151.9}],
        'parameters': {'consumption': '8', 'price': '60', 'participants': 4},
        'route': {'pointsRevision': 1, 'distanceM': 600000, 'durationS': 7200, 'obtainedAt': '2026-10-27T10:00:00+11:00'}
    }


class CalculatorTests(unittest.TestCase):
    def test_td01(self):
        self.assertEqual(calculate(600000, {'consumption': '8', 'price': '60', 'participants': '4'}), {'distanceKm': '600.00', 'litres': '48.00', 'total': '2880.00', 'perPerson': '720.00'})

    def test_td02_unrounded_share(self):
        self.assertEqual(calculate(123450, {'consumption': '8,5', 'price': '60', 'participants': '3'}), {'distanceKm': '123.45', 'litres': '10.49', 'total': '629.60', 'perPerson': '209.87'})

    def test_half_up(self):
        self.assertEqual(calculate(1000, {'consumption': '1', 'price': '0.5', 'participants': '1'})['total'], '0.01')

    def test_bounds(self):
        for consumption in ['0.1', '0,101', '99.999', '100']:
            validate({'consumption': consumption, 'price': '60', 'participants': '1'})
        for price in ['0.01', '0.011', '999.999', '1000']:
            validate({'consumption': '8', 'price': price, 'participants': '9'})

    def test_invalid_consumption(self):
        for consumption in ['', 'abc', '-1', '0', '0.099', '100.001', 'NaN', 'Infinity', '1e1']:
            with self.subTest(value=consumption), self.assertRaises(ValidationError):
                validate({'consumption': consumption, 'price': '60', 'participants': '4'})

    def test_invalid_price(self):
        for price in ['', 'abc', '-1', '0', '0.009', '1000.001', 'NaN', 'Infinity', '1e1']:
            with self.subTest(value=price), self.assertRaises(ValidationError):
                validate({'consumption': '8', 'price': price, 'participants': '4'})

    def test_invalid_participants(self):
        for count in ['', 'abc', '0', '1.5', '1,5', '10', 'True', '01']:
            with self.subTest(value=count), self.assertRaises(ValidationError):
                validate({'consumption': '8', 'price': '60', 'participants': count})

    def test_invalid_distance(self):
        for distance in [0, -1, float('nan'), float('inf'), None, True]:
            with self.subTest(value=distance), self.assertRaises(ValueError):
                calculate(distance, {'consumption': '8', 'price': '60', 'participants': '4'})


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name) / 'trip.sqlite', SCHEMA)

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip(self):
        data = self.repo.save(draft())
        self.repo.commit(data)
        self.assertEqual(self.repo.load()['parameters']['consumption'], '8')
        other = Repository(Path(self.temp.name) / 'other.sqlite', SCHEMA)
        self.assertEqual(other.load_bytes(data)['route']['distanceM'], 600000)

    def test_failed_candidate_not_committed(self):
        self.repo.commit(self.repo.save(draft()))
        candidate = draft()
        candidate['parameters']['price'] = '80'
        self.repo.save(candidate)
        self.repo.rollback()
        self.assertEqual(self.repo.load()['parameters']['price'], '60')

    def test_corrupt_image_keeps_previous(self):
        self.repo.commit(self.repo.save(draft()))
        with self.assertRaises(StorageError):
            self.repo.load_bytes(b'broken sqlite')
        self.assertEqual(self.repo.load()['parameters']['price'], '60')

    def test_schema_version(self):
        self.repo.commit(self.repo.save(draft()))
        with sqlite3.connect(str(self.repo.path)) as connection:
            connection.execute('PRAGMA user_version=99')
        invalid = self.repo.path.read_bytes()
        with self.assertRaises(StorageError):
            self.repo.load_bytes(invalid)

    def test_revision_mismatch(self):
        data = draft()
        data['route']['pointsRevision'] = 3
        with self.assertRaises(StorageError):
            self.repo.save(data)

    def test_size_boundary(self):
        data = draft()
        size = len(json.dumps(validate_draft(data), ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        data['points'][0]['label'] += 'a' * (102400 - size)
        validate_draft(data)
        data['points'][0]['label'] += 'a'
        with self.assertRaises(StorageError):
            validate_draft(data)

    def test_duplicate_point(self):
        data = draft()
        data['points'][1] = data['points'][0].copy()
        with self.assertRaises(StorageError):
            self.repo.save(data)

    def test_calendar_date(self):
        data = draft()
        data['route']['obtainedAt'] = '2026-02-30T10:00:00Z'
        with self.assertRaises(StorageError):
            self.repo.save(data)

    def test_clear(self):
        self.repo.commit(self.repo.save(draft()))
        self.repo.commit(self.repo.clear())
        self.assertIsNone(self.repo.load())
        with self.repo.connect() as connection:
            for name in ['draft', 'point', 'route', 'event_log']:
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0], 0)

    def test_log_app_version(self):
        self.repo.commit(self.repo.save(draft()))
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute('SELECT app_version FROM event_log').fetchone()[0], '1.0.0')
        configured = Repository(Path(self.temp.name) / 'configured.sqlite', SCHEMA, '1.1.2')
        configured.commit(configured.save(draft()))
        with configured.connect() as connection:
            self.assertEqual(connection.execute('SELECT app_version FROM event_log').fetchone()[0], '1.1.2')

    def test_event_limit(self):
        for _ in range(103):
            self.repo.commit(self.repo.save(draft()))
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM event_log').fetchone()[0], 100)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = TripController({}, Path(self.temp.name) / 'trip.sqlite', SCHEMA)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def prepare_route(self):
        data = draft()
        for index, point in enumerate(data['points']):
            await self.controller.handle('set_point', {'index': index, 'point': point})
        original = self.controller.geo.route
        async def route(points):
            return data['route'].copy()
        self.controller.geo.route = route
        try:
            return await self.controller.handle('build_route')
        finally:
            self.controller.geo.route = original

    async def test_demo_command_removed(self):
        state = await self.controller.handle('demo')
        self.assertEqual(state['messageType'], 'error')
        self.assertEqual(state['message'], 'Неизвестное действие')
        self.assertEqual(state['points'], [None, None])
        self.assertIsNone(state['route'])
        self.assertIsNone(state['costs'])
        self.assertNotIn('demo', state)
        self.assertIsNone(self.controller.take_snapshot())

    async def test_real_draft_restore_preserved(self):
        expected = draft()
        data = self.controller.repository.save(expected)
        state = await self.controller.handle('restore', {'bytes': list(data)})
        self.assertEqual(state['points'], expected['points'])
        self.assertEqual(state['route'], expected['route'])
        self.assertEqual(state['costs']['perPerson'], '720.00')
        self.assertEqual(state['saveStatus'], 'saved')
        self.assertIsNone(self.controller.take_snapshot())
        self.assertNotIn('demo', state)

    async def test_legacy_synthetic_not_restored(self):
        previous = draft()
        previous['points'][0]['label'] = 'Точка A · учебный пример'
        previous['points'][1]['label'] = 'Точка B · учебный пример'
        data = self.controller.repository.save(previous)
        state = await self.controller.handle('restore', {'bytes': list(data)})
        self.assertEqual(state['points'], [None, None])
        self.assertIsNone(state['route'])
        self.assertIsNone(state['costs'])
        self.assertNotIn('учебный', state['message'])
        self.assertEqual(state['saveStatus'], 'saving')
        snapshot = self.controller.take_snapshot()
        self.assertIsNotNone(snapshot)
        await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        self.assertIsNone(self.controller.repository.load())
        with self.controller.repository.connect() as connection:
            for name in ['draft', 'point', 'route', 'event_log']:
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0], 0)

    async def test_legacy_reset_failure_keeps_empty_view(self):
        previous = draft()
        previous['points'][0]['label'] = 'Точка A · учебный пример'
        previous['points'][1]['label'] = 'Точка B · учебный пример'
        data = self.controller.repository.save(previous)
        await self.controller.handle('restore', {'bytes': list(data)})
        snapshot = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': False})
        self.assertEqual(state['saveStatus'], 'error')
        self.assertEqual(state['points'], [None, None])
        self.assertIsNone(state['route'])
        self.assertIsNone(state['costs'])
        self.assertEqual(self.controller.repository.bytes(), data)

    async def test_similar_real_labels_are_preserved(self):
        previous = draft()
        previous['points'][0]['label'] = 'Точка A · учебный пример, улица'
        previous['points'][1]['label'] = 'Точка B · учебный пример, улица'
        data = self.controller.repository.save(previous)
        state = await self.controller.handle('restore', {'bytes': list(data)})
        self.assertEqual(state['points'], previous['points'])
        self.assertEqual(state['routeStatus'], 'ready')
        self.assertIsNone(self.controller.take_snapshot())

    async def test_parameters_without_network(self):
        state = await self.prepare_route()
        self.assertEqual(state['costs']['perPerson'], '720.00')
        state = await self.controller.handle('update_parameters', {'price': '65'})
        self.assertEqual(state['costs']['perPerson'], '780.00')
        state = await self.controller.handle('update_parameters', {'participants': '1.5'})
        self.assertIn('participants', state['fieldErrors'])
        self.assertIsNone(state['costs'])

    async def test_save_ack_and_failure(self):
        await self.prepare_route()
        snapshot = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        self.assertEqual(state['saveStatus'], 'saved')
        await self.controller.handle('update_parameters', {'price': '65'})
        snapshot = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': False})
        self.assertEqual(state['saveStatus'], 'error')
        self.assertEqual(self.controller.repository.load()['parameters']['price'], '60')

    async def test_point_change_ignores_late_route(self):
        await self.prepare_route()
        ready = asyncio.Event()
        release = asyncio.Event()
        async def delayed(points):
            ready.set()
            await release.wait()
            return draft()['route']
        self.controller.geo.route = delayed
        task = asyncio.create_task(self.controller.handle('build_route'))
        await ready.wait()
        await self.controller.handle('set_point', {'index': 1, 'point': {'label': 'C', 'lat': 61, 'lon': 152}})
        release.set()
        state = await task
        self.assertEqual(state['routeStatus'], 'stale')
        self.assertIsNone(state['costs'])

    async def test_clear_ignores_old_save(self):
        await self.prepare_route()
        old = self.controller.take_snapshot()
        await self.controller.handle('clear')
        current = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': old['token'], 'success': True})
        self.assertEqual(state['saveStatus'], 'saving')
        state = await self.controller.handle('storage_result', {'token': current['token'], 'success': True})
        self.assertEqual(state['saveStatus'], 'saved')
        self.assertIsNone(self.controller.repository.load())

    async def test_parameter_change_during_route(self):
        await self.prepare_route()
        ready = asyncio.Event()
        release = asyncio.Event()
        async def delayed(points):
            ready.set()
            await release.wait()
            return draft()['route']
        self.controller.geo.route = delayed
        task = asyncio.create_task(self.controller.handle('build_route'))
        await ready.wait()
        await self.controller.handle('update_parameters', {'price': '65'})
        release.set()
        state = await task
        self.assertEqual(state['costs']['perPerson'], '780.00')

    async def test_null_point_invalidates(self):
        await self.prepare_route()
        state = await self.controller.handle('set_point', {'index': 0, 'point': None})
        self.assertIsNone(state['points'][0])
        self.assertEqual(state['routeStatus'], 'stale')

    async def test_restore_bridge_error_locked(self):
        state = await self.controller.handle('restore', {'error': 'STORAGE', 'message': 'Хранилище недоступно'})
        self.assertEqual(state['messageType'], 'error')
        self.assertEqual(state['saveStatus'], 'error')
        await self.prepare_route()
        self.assertIsNone(self.controller.take_snapshot())

    async def test_messages(self):
        state = await self.prepare_route()
        self.assertEqual(state['messageType'], 'info')
        state = await self.controller.handle('set_point', {'index': 0, 'point': {'label': 'A', 'lat': 91, 'lon': 1}})
        self.assertEqual(state['messageType'], 'error')
        state = await self.prepare_route()
        self.assertEqual(state['messageType'], 'info')

    async def test_invalid_storage_locked(self):
        state = await self.controller.handle('restore', {'bytes': [1, 2, 3]})
        self.assertEqual(state['saveStatus'], 'error')
        state = await self.prepare_route()
        self.assertIsNone(self.controller.take_snapshot())
        self.assertEqual(state['saveStatus'], 'error')


class GeoTests(unittest.IsolatedAsyncioTestCase):
    async def test_photon(self):
        urls = []
        async def fetch(url):
            urls.append(url)
            return {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [150.8, 59.5]}, 'properties': {'name': 'Магадан', 'country': 'Россия'}}]}
        geo = GeoAdapter({'geocodingUrl': 'https://photon.komoot.io/api/'}, fetch)
        self.assertEqual((await geo.search('Магадан'))[0]['label'], 'Магадан, Россия')
        self.assertEqual(parse_qs(urlparse(urls[0]).query), {'q': ['Магадан'], 'limit': ['5']})

    async def test_search_cache(self):
        calls = []
        async def fetch(url):
            calls.append(url)
            return []
        geo = GeoAdapter({'geocodingUrl': 'https://example.test'}, fetch)
        await geo.search('AB')
        await geo.search('AB')
        self.assertEqual(len(calls), 1)

    async def test_malformed_photon(self):
        responses = [
            {'type': 'FeatureCollection', 'features': None},
            {'type': 'FeatureCollection', 'features': [None]},
            {'type': 'FeatureCollection', 'features': [{'properties': None, 'geometry': {}}]},
            {'type': 'FeatureCollection', 'features': [{'properties': {}, 'geometry': None}]},
            {'type': 'FeatureCollection', 'features': [{'properties': {}, 'geometry': {'type': 'Point', 'coordinates': None}}]}
        ]
        for response in responses:
            async def fetch(url):
                return response
            with self.subTest(response=response), self.assertRaises(GeoError):
                await GeoAdapter({}, fetch).search('AB')

    async def test_malformed_routes(self):
        for routes in [None, {}, {'0': {}}, 'bad', [None], []]:
            async def fetch(url):
                return {'code': 'Ok', 'routes': routes}
            with self.subTest(routes=routes), self.assertRaises(GeoError):
                await GeoAdapter({}, fetch).route(draft()['points'])

    async def test_invalid_coordinate(self):
        for value in [91, -91, None, 'NaN', float('inf'), True]:
            with self.subTest(value=value), self.assertRaises(GeoError):
                validate_point({'label': 'A', 'lat': value, 'lon': 1})

    async def test_route_response(self):
        async def fetch(url):
            return {'code': 'Ok', 'routes': [{'distance': 0, 'duration': 1}]}
        geo = GeoAdapter({}, fetch)
        with self.assertRaises(GeoError):
            await geo.route(draft()['points'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
