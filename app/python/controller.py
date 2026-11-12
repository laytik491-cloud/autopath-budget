import copy

from calculator import ValidationError, calculate, calculate_manual, decimal_text, validate
from geo import GeoAdapter, GeoError, validate_point
from repository import Repository, StorageError


class TripController:
    def __init__(self, config, db_path, schema_text):
        self.repository = Repository(db_path, schema_text, config.get('appVersion', '1.0.0'))
        self.geo = GeoAdapter(config)
        self.state = self.empty_state()
        self.request_id = 0
        self.search_ids = [0, 0]
        self.token = 0
        self.pending = None
        self.candidates = {}
        self.read_only = False

    def empty_state(self):
        return {
            'mode': 'map', 'distanceText': '',
            'points': [None, None], 'parameters': {'consumption': '8', 'price': '60', 'participants': '4'},
            'fieldErrors': {}, 'costs': None, 'route': None, 'routeStatus': 'empty', 'saveStatus': 'idle',
            'message': '', 'messageType': 'info', 'searchResults': [[], []], 'searches': ['', ''],
            'pointsRevision': 1, 'revision': 1, 'generation': 0
        }

    def view(self):
        return copy.deepcopy(self.state)

    def draft(self):
        if self.state['mode'] == 'manual':
            return {
                'id': 'current', 'schemaVersion': 1, 'mode': 'manual',
                'revision': self.state['revision'], 'pointsRevision': self.state['pointsRevision'],
                'distanceText': self.state['distanceText'], 'points': [], 'route': None,
                'parameters': validate(self.state['parameters'])
            }
        return {
            'id': 'current', 'schemaVersion': 1, 'revision': self.state['revision'],
            'pointsRevision': self.state['pointsRevision'], 'points': copy.deepcopy(self.state['points']),
            'parameters': validate(self.state['parameters']), 'route': copy.deepcopy(self.state['route'])
        }

    def save(self, code='DRAFT_SAVED'):
        if self.read_only:
            self.state['saveStatus'] = 'error'
            self.state['messageType'] = 'error'
            self.state['message'] = 'Сохранённая база повреждена или несовместима. Очистите данные перед новой записью'
            return
        if not self.state['costs'] or self.state['fieldErrors']:
            return
        try:
            candidate = self.repository.save(self.draft(), code)
            self.queue_snapshot(candidate)
        except (StorageError, ValidationError) as error:
            self.state['saveStatus'] = 'error'
            self.state['messageType'] = 'error'
            self.state['message'] = str(error)

    def queue_snapshot(self, data):
        self.token += 1
        self.pending = {'token': self.token, 'generation': self.state['generation'], 'bytes': list(data)}
        self.candidates[self.token] = {'data': data, 'generation': self.state['generation'], 'revision': self.state['revision']}
        self.state['saveStatus'] = 'saving'

    def take_snapshot(self):
        result = self.pending
        self.pending = None
        return result

    def recalculate(self):
        errors = {}
        try:
            validate(self.state['parameters'])
        except ValidationError as error:
            errors.update(error.errors)
        if self.state['mode'] == 'manual':
            try:
                decimal_text(self.state['distanceText'], '0.01', '1000000')
            except ValueError as error:
                errors['distanceText'] = str(error)
        self.state['fieldErrors'] = errors
        if errors:
            self.state['costs'] = None
            return
        if self.state['mode'] == 'manual':
            self.state['costs'] = calculate_manual(self.state['distanceText'], self.state['parameters'])
        elif self.state['routeStatus'] == 'ready':
            self.state['costs'] = calculate(self.state['route']['distanceM'], self.state['parameters'])
        else:
            self.state['costs'] = None

    def invalidate(self):
        self.request_id += 1
        self.state['pointsRevision'] += 1
        self.state['revision'] += 1
        self.state['routeStatus'] = 'stale' if self.state['route'] else 'empty'
        self.state['costs'] = None
        self.state['saveStatus'] = 'idle'
        self.state['message'] = 'Точки изменились. Постройте маршрут заново' if self.state['route'] else ''

    async def handle(self, command, payload=None):
        payload = payload or {}
        if command not in ('storage_result', 'view'):
            self.state['messageType'] = 'info'
        try:
            if command == 'restore':
                if payload.get('error'):
                    self.read_only = True
                    self.state['saveStatus'] = 'error'
                    self.state['messageType'] = 'error'
                    self.state['message'] = str(payload.get('message') or 'Не удалось открыть сохранённые данные. Очистите данные перед новой записью')
                    return self.view()
                if 'bytes' in payload and payload['bytes'] is not None:
                    draft = self.repository.load_bytes(payload['bytes'])
                else:
                    draft = self.repository.load()
                if draft and draft.get('mode') != 'manual' and [point['label'] for point in draft['points']] == ['Точка A · учебный пример', 'Точка B · учебный пример']:
                    await self.handle('clear')
                    if self.state['messageType'] != 'error':
                        self.state['message'] = 'Сохранённый расчёт предыдущей версии сброшен. Выберите точки маршрута'
                    return self.view()
                if draft:
                    self.state['mode'] = draft.get('mode', 'map')
                    self.state['distanceText'] = draft.get('distanceText', '')
                    self.state['points'] = draft['points'] or [None, None]
                    self.state['parameters'] = {key: str(value) for key, value in draft['parameters'].items()}
                    self.state['route'] = draft['route']
                    self.state['pointsRevision'] = draft['pointsRevision']
                    self.state['revision'] = draft['revision']
                    self.state['routeStatus'] = 'ready' if draft['route'] else 'empty'
                    self.state['saveStatus'] = 'saved'
                    self.state['message'] = 'Расчёт по расстоянию восстановлен' if self.state['mode'] == 'manual' else 'Последний расчёт восстановлен. Линия маршрута появится после нового построения'
                    self.recalculate()
                if self.repository.migrated:
                    self.queue_snapshot(self.repository.bytes())
                    self.repository.migrated = False
            elif command == 'set_mode':
                mode = payload.get('mode')
                if mode not in ('map', 'manual'):
                    raise ValueError('Неизвестный режим расчёта')
                if mode != self.state['mode']:
                    self.request_id += 1
                    self.search_ids = [value + 1 for value in self.search_ids]
                    self.state['searchResults'] = [[], []]
                    if self.state['routeStatus'] == 'loading':
                        self.state['routeStatus'] = 'stale' if self.state['route'] else 'empty'
                    self.state['mode'] = mode
                    self.state['revision'] += 1
                    self.state['saveStatus'] = 'idle'
                    self.state['message'] = ''
                    self.recalculate()
                    if mode == 'manual' and not self.state['distanceText']:
                        self.state['fieldErrors'].pop('distanceText', None)
                    self.save()
            elif command == 'update_distance':
                if self.state['mode'] == 'manual':
                    self.state['distanceText'] = str(payload.get('distanceText', ''))
                    self.state['revision'] += 1
                    self.state['saveStatus'] = 'idle'
                    self.state['message'] = ''
                    self.recalculate()
                    self.save()
            elif command == 'set_point':
                if self.state['mode'] != 'map':
                    return self.view()
                index = payload.get('index')
                if index not in (0, 1):
                    raise GeoError('Неизвестная точка маршрута')
                point = validate_point(payload['point']) if payload.get('point') is not None else None
                other = self.state['points'][1 - index]
                if point and other and point['lat'] == other['lat'] and point['lon'] == other['lon']:
                    raise GeoError('Начало и конец маршрута совпадают')
                self.state['points'][index] = point
                self.search_ids[index] += 1
                self.state['searchResults'][index] = []
                if point:
                    self.state['searches'][index] = point['label']
                self.invalidate()
            elif command == 'search':
                if self.state['mode'] != 'map':
                    return self.view()
                index = payload.get('index')
                if index not in (0, 1):
                    raise GeoError('Неизвестная точка маршрута')
                self.search_ids[index] += 1
                search_id = self.search_ids[index]
                generation = self.state['generation']
                query = str(payload.get('query', '')).strip()
                self.state['searches'][index] = query
                self.state['searchResults'][index] = []
                self.state['message'] = 'Ищу адрес…'
                try:
                    results = await self.geo.search(query)
                except GeoError as error:
                    if search_id == self.search_ids[index] and generation == self.state['generation']:
                        self.state['message'] = str(error)
                        self.state['messageType'] = 'error'
                    return self.view()
                if search_id == self.search_ids[index] and generation == self.state['generation']:
                    self.state['searchResults'][index] = results
                    self.state['messageType'] = 'info'
                    self.state['message'] = 'Выберите подходящий адрес из списка' if results else 'Адрес не найден. Попробуйте уточнить запрос или выберите точку на карте'
            elif command == 'update_parameters':
                for key in ['consumption', 'price', 'participants']:
                    if key in payload:
                        self.state['parameters'][key] = str(payload[key])
                self.state['revision'] += 1
                self.state['saveStatus'] = 'idle'
                self.state['message'] = ''
                self.recalculate()
                self.save()
            elif command == 'build_route':
                if self.state['mode'] != 'map':
                    return self.view()
                if any(point is None for point in self.state['points']):
                    raise GeoError('Выберите начало и конец маршрута')
                self.request_id += 1
                request_id = self.request_id
                points_revision = self.state['pointsRevision']
                generation = self.state['generation']
                points = copy.deepcopy(self.state['points'])
                self.state['routeStatus'] = 'loading'
                self.state['costs'] = None
                self.state['message'] = 'Строю автомобильный маршрут…'
                try:
                    route = await self.geo.route(points)
                except GeoError as error:
                    if request_id == self.request_id and generation == self.state['generation']:
                        self.state['routeStatus'] = 'error'
                        self.state['message'] = str(error)
                        self.state['messageType'] = 'error'
                    return self.view()
                if request_id == self.request_id and points_revision == self.state['pointsRevision'] and generation == self.state['generation']:
                    route['pointsRevision'] = points_revision
                    self.state['route'] = route
                    self.state['routeStatus'] = 'ready'
                    self.state['revision'] += 1
                    self.state['message'] = 'Маршрут готов'
                    self.state['messageType'] = 'info'
                    self.recalculate()
                    self.save('ROUTE_READY')
            elif command == 'clear':
                generation = self.state['generation'] + 1
                self.request_id += 1
                self.search_ids = [value + 1 for value in self.search_ids]
                self.state = self.empty_state()
                self.state['generation'] = generation
                self.state['message'] = 'Данные очищены'
                self.read_only = False
                self.queue_snapshot(self.repository.clear())
            elif command == 'storage_result':
                token = payload.get('token')
                candidate = self.candidates.pop(token, None)
                if candidate and candidate['generation'] == self.state['generation']:
                    if payload.get('success'):
                        self.repository.commit(candidate['data'])
                        if token == self.token and candidate['revision'] == self.state['revision']:
                            self.state['saveStatus'] = 'saved'
                    else:
                        self.repository.rollback()
                        if token == self.token:
                            self.state['saveStatus'] = 'error'
                            self.state['messageType'] = 'error'
                            self.state['message'] = 'Не удалось сохранить данные в браузере. Текущий расчёт доступен до закрытия вкладки'
            elif command == 'view':
                pass
            else:
                raise ValueError('Неизвестное действие')
        except ValidationError as error:
            self.state['messageType'] = 'error'
            self.state['fieldErrors'] = error.errors
            self.state['costs'] = None
        except (GeoError, StorageError, ValueError) as error:
            self.state['message'] = str(error)
            self.state['messageType'] = 'error'
            if isinstance(error, StorageError):
                self.state['saveStatus'] = 'error'
            if command == 'restore':
                self.read_only = True
                self.state['saveStatus'] = 'error'
        return self.view()
