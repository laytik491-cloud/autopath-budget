import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_core import SCHEMA, ROOT, draft
from calculator import calculate_manual
from controller import TripController
from repository import Repository, StorageError


def manual(distance='150'):
    return {
        'id': 'current', 'schemaVersion': 1, 'mode': 'manual',
        'revision': 1, 'pointsRevision': 1, 'distanceText': distance,
        'points': [], 'route': None,
        'parameters': {'consumption': '8', 'price': '60', 'participants': 4}
    }


def legacy_image(path):
    data = draft()
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript((ROOT / 'app/python/schema-v1.sql').read_text())
        connection.execute("INSERT INTO draft(id,schema_version,revision,points_revision,consumption_text,price_text,participants) VALUES('current',1,1,1,'8','60',4)")
        for index, point in enumerate(data['points']):
            connection.execute('INSERT INTO point VALUES(?,?,?,?,?)', ('current', index, point['label'], point['lat'], point['lon']))
        connection.execute('INSERT INTO route VALUES(?,?,?,?,?)', ('current', 1, 600000, 7200, data['route']['obtainedAt']))
    return Path(path).read_bytes()


class ManualCalculatorTests(unittest.TestCase):
    def test_exact_decimal_comma(self):
        result = calculate_manual('123,45', {'consumption': '8,5', 'price': '60', 'participants': '3'})
        self.assertEqual(result, {'distanceKm': '123.45', 'litres': '10.49', 'total': '629.60', 'perPerson': '209.87'})

    def test_boundaries(self):
        self.assertEqual(calculate_manual('0.01', manual()['parameters'])['distanceKm'], '0.01')
        self.assertEqual(calculate_manual('1000000', manual()['parameters'])['total'], '4800000.00')

    def test_invalid_distance(self):
        for value in ['', '0', '-1', '0.009', '1000000.001', 'abc', 'NaN', 'Infinity', '1e3', None, True, '9' * 31]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate_manual(value, manual()['parameters'])

    def test_rounding_once(self):
        result = calculate_manual('0.125', {'consumption': '4', 'price': '1', 'participants': '2'})
        self.assertEqual(result['litres'], '0.01')
        self.assertEqual(result['total'], '0.01')
        self.assertEqual(result['perPerson'], '0.00')


class ManualRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name) / 'trip.sqlite', SCHEMA)

    def tearDown(self):
        self.temp.cleanup()

    def test_manual_roundtrip(self):
        self.repo.commit(self.repo.save(manual('00150,500')))
        loaded = self.repo.load()
        self.assertEqual(loaded['mode'], 'manual')
        self.assertEqual(loaded['distanceText'], '150.5')
        self.assertIsNone(loaded['route'])
        self.assertEqual(loaded['points'], [])

    def test_only_last_mode_saved(self):
        self.repo.commit(self.repo.save(draft()))
        self.repo.commit(self.repo.save(manual()))
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM draft').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM route').fetchone()[0], 0)
        self.repo.commit(self.repo.save(draft()))
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_trip').fetchone()[0], 0)

    def test_migration_preserves_real_route(self):
        old = legacy_image(Path(self.temp.name) / 'legacy.sqlite')
        loaded = self.repo.load_bytes(old)
        self.assertTrue(self.repo.migrated)
        self.assertEqual(loaded['route']['distanceM'], 600000)
        self.assertEqual(loaded['points'], draft()['points'])
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
        self.repo.commit(self.repo.save(manual()))
        self.assertEqual(self.repo.load()['mode'], 'manual')

    def test_modified_legacy_rejected(self):
        path = Path(self.temp.name) / 'legacy.sqlite'
        legacy_image(path)
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE unexpected (id INTEGER)')
        previous = self.repo.bytes()
        with self.assertRaises(StorageError):
            self.repo.load_bytes(path.read_bytes())
        self.assertEqual(self.repo.path.read_bytes(), previous)

    def test_invalid_manual_keeps_durable_data(self):
        self.repo.commit(self.repo.save(manual()))
        for distance in ['0', 'NaN', '1000001']:
            with self.assertRaises(StorageError):
                self.repo.save(manual(distance))
        self.assertEqual(self.repo.load()['distanceText'], '150')

    def test_no_fabricated_route(self):
        data = manual()
        data['route'] = draft()['route']
        with self.assertRaises(StorageError):
            self.repo.save(data)


class ManualControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = TripController({}, Path(self.temp.name) / 'trip.sqlite', SCHEMA)
        async def forbidden(*args):
            raise AssertionError('Ручной расчёт обратился в сеть')
        self.controller.geo.route = forbidden
        self.controller.geo.search = forbidden
        await self.controller.handle('set_mode', {'mode': 'manual'})

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def prepare(self):
        return await self.controller.handle('update_distance', {'distanceText': '150'})

    async def test_no_points_or_network_required(self):
        state = await self.prepare()
        self.assertEqual(state['costs']['litres'], '12.00')
        self.assertEqual(state['costs']['total'], '720.00')
        self.assertEqual(state['costs']['perPerson'], '180.00')
        await self.controller.handle('build_route')
        await self.controller.handle('search', {'index': 0, 'query': 'Магадан'})

    async def test_restore_manual(self):
        await self.prepare()
        snapshot = self.controller.take_snapshot()
        await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        other = TripController({}, Path(self.temp.name) / 'other.sqlite', SCHEMA)
        state = await other.handle('restore', {'bytes': snapshot['bytes']})
        self.assertEqual(state['mode'], 'manual')
        self.assertEqual(state['distanceText'], '150')
        self.assertEqual(state['costs']['perPerson'], '180.00')

    async def test_invalid_hides_result_and_preserves_saved(self):
        await self.prepare()
        snapshot = self.controller.take_snapshot()
        await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        state = await self.controller.handle('update_distance', {'distanceText': '0'})
        self.assertIsNone(state['costs'])
        self.assertIn('distanceText', state['fieldErrors'])
        self.assertIsNone(self.controller.take_snapshot())
        self.assertEqual(self.controller.repository.load()['distanceText'], '150')

    async def test_parameter_change(self):
        await self.prepare()
        state = await self.controller.handle('update_parameters', {'price': '65', 'participants': '3'})
        self.assertEqual(state['costs']['perPerson'], '260.00')

    async def test_switch_modes_does_not_reuse_manual_as_route(self):
        await self.prepare()
        state = await self.controller.handle('set_mode', {'mode': 'map'})
        self.assertIsNone(state['costs'])
        self.assertIsNone(state['route'])
        state = await self.controller.handle('set_mode', {'mode': 'manual'})
        self.assertEqual(state['costs']['perPerson'], '180.00')

    async def test_late_route_after_mode_switch(self):
        await self.controller.handle('set_mode', {'mode': 'map'})
        for index, point in enumerate(draft()['points']):
            await self.controller.handle('set_point', {'index': index, 'point': point})
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(points):
            started.set()
            await release.wait()
            return draft()['route']
        self.controller.geo.route = delayed
        task = asyncio.create_task(self.controller.handle('build_route'))
        await started.wait()
        await self.controller.handle('set_mode', {'mode': 'manual'})
        await self.prepare()
        release.set()
        state = await task
        self.assertEqual(state['mode'], 'manual')
        self.assertEqual(state['costs']['perPerson'], '180.00')
        self.assertIsNone(state['route'])

    async def test_save_failure_and_retry(self):
        await self.prepare()
        snapshot = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': False})
        self.assertEqual(state['saveStatus'], 'error')
        self.assertEqual(state['costs']['perPerson'], '180.00')
        await self.controller.handle('update_parameters', {})
        snapshot = self.controller.take_snapshot()
        state = await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        self.assertEqual(state['saveStatus'], 'saved')

    async def test_clear_manual(self):
        await self.prepare()
        state = await self.controller.handle('clear')
        snapshot = self.controller.take_snapshot()
        await self.controller.handle('storage_result', {'token': snapshot['token'], 'success': True})
        self.assertEqual(state['distanceText'], '')
        self.assertEqual(state['mode'], 'map')
        self.assertIsNone(self.controller.repository.load())

    async def test_legacy_restore_queues_migrated_image(self):
        image = legacy_image(Path(self.temp.name) / 'legacy.sqlite')
        state = await self.controller.handle('restore', {'bytes': list(image)})
        self.assertEqual(state['costs']['perPerson'], '720.00')
        snapshot = self.controller.take_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(int.from_bytes(bytes(snapshot['bytes'])[60:64], 'big'), 2)
