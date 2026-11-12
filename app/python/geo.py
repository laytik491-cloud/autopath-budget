import asyncio
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode


class GeoError(ValueError):
    pass


def finite_number(value, minimum, maximum):
    if isinstance(value, bool) or value is None:
        raise GeoError('Некорректные координаты')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise GeoError('Некорректные координаты')
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise GeoError('Некорректные координаты')
    return number


def validate_point(point):
    if not isinstance(point, dict):
        raise GeoError('Выберите точку маршрута')
    label = point.get('label', '')
    if not isinstance(label, str) or not label.strip():
        raise GeoError('Укажите название точки')
    return {
        'label': label.strip(),
        'lat': finite_number(point.get('lat'), -90, 90),
        'lon': finite_number(point.get('lon'), -180, 180)
    }


def validate_route(route):
    if not isinstance(route, dict):
        raise GeoError('Сервис вернул некорректный маршрут')
    result = dict(route)
    for key in ['distanceM', 'durationS']:
        value = result.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise GeoError('Сервис вернул некорректное расстояние или время')
    date = result.get('obtainedAt', '')
    try:
        parsed = datetime.fromisoformat(date.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise GeoError('Некорректная дата маршрута')
    geometry = result.get('geometry')
    if geometry is not None:
        if not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
            raise GeoError('Сервис вернул некорректную линию маршрута')
        coordinates = geometry.get('coordinates')
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise GeoError('Сервис вернул пустую линию маршрута')
        for pair in coordinates:
            if not isinstance(pair, list) or len(pair) < 2:
                raise GeoError('Сервис вернул некорректную линию маршрута')
            finite_number(pair[0], -180, 180)
            finite_number(pair[1], -90, 90)
    return result


class GeoAdapter:
    def __init__(self, config=None, fetcher=None):
        self.config = config or {}
        self.fetcher = fetcher
        self.cache = {}
        self.last_search = 0
        self.search_lock = asyncio.Lock()

    async def fetch_json(self, url):
        try:
            if self.fetcher:
                return await asyncio.wait_for(self.fetcher(url), 15)
            from pyodide.http import pyfetch
            response = await asyncio.wait_for(pyfetch(url), 15)
            if response.status == 429:
                raise GeoError('Сервис ограничил запросы. Повторите позже')
            if response.status >= 400:
                raise GeoError('Картографический сервис временно недоступен')
            return await response.json()
        except asyncio.TimeoutError:
            raise GeoError('Время ожидания истекло. Повторите запрос')
        except GeoError:
            raise
        except Exception:
            raise GeoError('Нет связи с картографическим сервисом. Проверьте интернет')

    async def search(self, query):
        query = str(query).strip()
        if not 2 <= len(query) <= 200:
            raise GeoError('Введите адрес длиной от 2 до 200 символов')
        endpoint = self.config.get('geocodingUrl', self.config.get('geocoding_url', 'https://photon.komoot.io/api/'))
        if not endpoint:
            raise GeoError('Поиск адресов не настроен. Выберите точки на карте или введите координаты')
        if query in self.cache:
            return self.cache[query]
        async with self.search_lock:
            if query in self.cache:
                return self.cache[query]
            delay = max(0, 1.1 - (time.monotonic() - self.last_search))
            if delay:
                await asyncio.sleep(delay)
            self.last_search = time.monotonic()
            url = endpoint.rstrip('?') + ('&' if '?' in endpoint else '?') + urlencode({'q': query, 'limit': 5})
            data = await self.fetch_json(url)
            if isinstance(data, dict) and data.get('type') == 'FeatureCollection':
                features = data.get('features')
                if not isinstance(features, list):
                    raise GeoError('Сервис поиска вернул неверный ответ')
                data = []
                for feature in features[:5]:
                    if not isinstance(feature, dict):
                        raise GeoError('Сервис поиска вернул неверный ответ')
                    properties = feature.get('properties', {})
                    geometry = feature.get('geometry', {})
                    if not isinstance(properties, dict) or not isinstance(geometry, dict):
                        raise GeoError('Сервис поиска вернул неверный ответ')
                    coordinates = geometry.get('coordinates', [])
                    if geometry.get('type') != 'Point' or not isinstance(coordinates, list) or len(coordinates) < 2:
                        raise GeoError('Сервис поиска вернул неверный ответ')
                    label = ', '.join(str(properties[key]) for key in ['name', 'street', 'housenumber', 'city', 'state', 'country'] if properties.get(key))
                    data.append({'display_name': label, 'lat': coordinates[1], 'lon': coordinates[0]})
            if not isinstance(data, list):
                raise GeoError('Сервис поиска вернул неверный ответ')
            result = []
            for item in data[:5]:
                if not isinstance(item, dict):
                    raise GeoError('Сервис поиска вернул неверный ответ')
                result.append(validate_point({'label': item.get('display_name'), 'lat': item.get('lat'), 'lon': item.get('lon')}))
            self.cache[query] = result
            return result

    async def route(self, points):
        start, end = [validate_point(point) for point in points]
        if start['lat'] == end['lat'] and start['lon'] == end['lon']:
            raise GeoError('Начало и конец маршрута совпадают')
        endpoint = self.config.get('routingUrl', self.config.get('routing_url', 'https://router.project-osrm.org/route/v1/driving'))
        url = endpoint.rstrip('/') + f"/{start['lon']},{start['lat']};{end['lon']},{end['lat']}?overview=full&geometries=geojson&alternatives=false"
        data = await self.fetch_json(url)
        if not isinstance(data, dict) or data.get('code') != 'Ok':
            raise GeoError('Автомобильный путь между точками не найден')
        routes = data.get('routes')
        if not isinstance(routes, list) or not routes:
            raise GeoError('Сервис вернул некорректный маршрут')
        raw = routes[0]
        if not isinstance(raw, dict) or not raw.get('geometry'):
            raise GeoError('Сервис вернул некорректный маршрут')
        return validate_route({
            'distanceM': raw.get('distance'),
            'durationS': raw.get('duration'),
            'obtainedAt': datetime.now(timezone.utc).isoformat(),
            'geometry': raw.get('geometry')
        })
