const $ = id => document.getElementById(id);
let current = null;
let ready = false;
let requestId = 0;
let pickIndex = 0;
let routeLayer = null;
let displayedRoute = '';
let routeGeometry = null;
let geometryKey = '';
let markers = [null, null];
let pointDrafts = ['', ''];
const pending = new Map();
const worker = new Worker('./worker.mjs', {type: 'module'});
const money = value => String(value).replace('.', ',');
const routeMessages = {
  empty: 'Выберите две точки, чтобы узнать расстояние.',
  loading: 'Строим маршрут…',
  ready: 'Маршрут готов.',
  stale: 'Точки изменились. Постройте маршрут заново.',
  error: 'Не удалось построить маршрут. Проверьте точки и повторите запрос.'
};

function command(name, payload = {}) {
  if (!ready) return Promise.resolve(null);
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    worker.postMessage({id, command: name, payload});
  });
}

worker.onmessage = event => {
  const data = event.data;
  if (data.type === 'ready') {
    ready = true;
    $('startup').hidden = true;
    document.querySelectorAll('button[disabled], input[disabled]').forEach(control => control.disabled = false);
  }
  if (data.type === 'fatal' || data.fatal) {
    $('startup').textContent = data.error || 'Не удалось загрузить Python. Обновите страницу.';
    $('startup').classList.add('error');
  }
  if (data.state) render(data.state);
  if (data.id && pending.has(data.id)) {
    const action = pending.get(data.id);
    pending.delete(data.id);
    if (data.error) {
      $('route-message').textContent = data.error;
      $('route-message').classList.add('error');
      action.resolve(null);
    } else action.resolve(data.state);
  }
};
worker.onerror = () => {
  $('startup').hidden = false;
  $('startup').classList.add('error');
  $('startup').textContent = 'Не удалось запустить программу. Откройте её через launch.py и обновите страницу.';
};

const map = L.map('map', {zoomSnap: .25, zoomDelta: .5, preferCanvas: true}).setView([59.56, 150.80], 13);
map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener noreferrer">Leaflet</a>');
const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).on('tileerror', () => {
  $('map-warning').textContent = 'Не все участки карты загрузились. Можно рассчитать поездку по расстоянию.';
}).on('tileload', () => {
  $('map-warning').textContent = 'Выберите А и Б на карте. Метки можно перемещать.';
});

function pointIcon(index) {
  return L.divIcon({className: '', html: `<span class="map-marker ${index ? 'end' : ''}">${index ? 'Б' : 'А'}</span>`, iconSize: [30, 30], iconAnchor: [15, 15]});
}

function setPick(index) {
  pickIndex = index;
  [0, 1].forEach(i => {
    $(`pick-${i}`).classList.toggle('selected', i === index);
    $(`pick-${i}`).setAttribute('aria-pressed', String(i === index));
  });
}

async function selectPoint(index, point) {
  const state = await command('set_point', {index, point});
  const selected = state?.points?.[index];
  if (selected) {
    pointDrafts[index] = selected.label;
    $(`point-${index}`).value = selected.label;
    if (index === 0 && selected.lat === point.lat && selected.lon === point.lon) setPick(1);
  }
}

map.on('click', event => {
  if (!ready) return;
  const {lat, lng} = event.latlng;
  selectPoint(pickIndex, {lat, lon: lng, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}`});
});
[0, 1].forEach(index => $(`pick-${index}`).onclick = () => setPick(index));

function render(state) {
  const old = current;
  current = state;
  document.body.classList.toggle('has-errors', Boolean(Object.keys(state.fieldErrors || {}).length || state.messageType === 'error'));
  const manual = state.mode === 'manual';
  $('planner').classList.toggle('manual-mode', manual);
  $('route-fields').hidden = manual;
  $('map-panel').hidden = manual;
  $('manual-fields').hidden = !manual;
  $('duration-row').hidden = manual;
  if (manual && map.hasLayer(tiles)) tiles.remove();
  if (!manual && !map.hasLayer(tiles)) tiles.addTo(map);
  for (const name of ['map', 'manual']) {
    $(`mode-${name}`).classList.toggle('selected', state.mode === name);
    $(`mode-${name}`).setAttribute('aria-pressed', String(state.mode === name));
  }
  const resetInputs = !old || old.generation !== state.generation;
  if (old && old.generation !== state.generation) {
    routeGeometry = null;
    geometryKey = '';
  }
  if (resetInputs) $('manual-distance').value = state.distanceText;
  const distanceError = state.fieldErrors?.distanceText || '';
  $('error-distanceText').textContent = distanceError;
  $('manual-distance').setAttribute('aria-invalid', String(Boolean(distanceError)));
  if (old?.mode === 'manual' && !manual) setTimeout(resizeMap, 30);
  const points = state.points || [null, null];
  points.forEach((point, index) => {
    const input = $(`point-${index}`);
    const status = $(`confirmed-${index}`);
    if (point) {
      if (document.activeElement !== input) {
        input.value = point.label;
        pointDrafts[index] = point.label;
      }
      status.textContent = '✓ Точка выбрана';
      status.classList.add('confirmed');
      if (!markers[index]) {
        markers[index] = L.marker([point.lat, point.lon], {icon: pointIcon(index), draggable: true}).addTo(map);
        markers[index].on('dragend', event => {
          const pos = event.target.getLatLng();
          selectPoint(index, {lat: pos.lat, lon: pos.lng, label: `${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}`});
        });
      } else markers[index].setLatLng([point.lat, point.lon]);
    } else {
      status.textContent = 'Точка ещё не выбрана';
      status.classList.remove('confirmed');
      if (markers[index]) { markers[index].remove(); markers[index] = null; }
    }
    const list = $(`results-${index}`);
    list.replaceChildren();
    for (const item of (state.searchResults?.[index] || [])) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = item.label;
      button.onclick = () => selectPoint(index, item);
      list.append(button);
    }
  });
  for (const field of ['consumption', 'price', 'participants']) {
    if (resetInputs) $(field).value = state.parameters[field];
    const error = state.fieldErrors?.[field] || '';
    $(`error-${field}`).textContent = error;
    $(field).setAttribute('aria-invalid', String(Boolean(error)));
  }
  $('build').disabled = !ready || state.routeStatus === 'loading';
  $('build').textContent = state.routeStatus === 'loading' ? 'Строим маршрут…' : 'Построить маршрут';
  $('route-message').textContent = state.message || (manual ? 'Расчёт обновляется при вводе.' : routeMessages[state.routeStatus]) || '';
  $('route-message').classList.toggle('error', state.routeStatus === 'error' || state.messageType === 'error');
  const route = state.route;
  const valid = !manual && state.routeStatus === 'ready' && route;
  const costs = state.costs;
  $('distance').textContent = costs ? `${money(costs.distanceKm)} км` : '— км';
  const minutes = valid ? Math.max(1, Math.round(route.durationS / 60)) : 0;
  $('duration').textContent = valid ? `${Math.floor(minutes / 60)} ч ${minutes % 60} мин` : '—';
  const routeKey = valid ? `${state.pointsRevision}:${route.obtainedAt}` : '';
  if (valid && route.geometry) {
    routeGeometry = route.geometry;
    geometryKey = routeKey;
  }
  const geometry = valid && geometryKey === routeKey ? routeGeometry : null;
  if (routeKey !== displayedRoute || geometry && !routeLayer) {
    if (routeLayer) routeLayer.remove();
    routeLayer = geometry ? L.geoJSON(geometry, {style: {color: '#ff8a24', weight: 4, opacity: .95}}).addTo(map) : null;
    displayedRoute = routeKey;
    if (routeLayer) requestAnimationFrame(fitRoute);
  }
  $('mini-total').textContent = costs ? `${money(costs.total)} ₽` : '— ₽';
  $('mini-litres').textContent = costs ? `${money(costs.litres)} л` : '— л';
  $('mini-cost').textContent = costs ? `${money(costs.perPerson)} ₽` : '— ₽';
  $('result-empty').hidden = Boolean(costs);
  $('result-content').hidden = !costs;
  if (costs) {
    $('per-person').textContent = `${money(costs.perPerson)} ₽`;
    $('total').textContent = `${money(costs.total)} ₽`;
    $('litres').textContent = `${money(costs.litres)} л`;
    $('participants-note').textContent = `Участников с водителем: ${state.parameters.participants}`;
    $('route-description').textContent = manual ? `Расстояние введено вручную: ${money(state.distanceText)} км` : `${points[0].label} → ${points[1].label}`;
    $('formula').textContent = `${money(costs.distanceKm)} км × ${money(state.parameters.consumption)} л/100 км × ${money(state.parameters.price)} ₽/л ÷ ${state.parameters.participants} чел. ≈ ${money(costs.perPerson)} ₽ на человека. Сумма рассчитана по точному расстоянию, до округления.`;
    $('route-date').textContent = manual ? 'Время в пути не определяется по расстоянию. Интернет для этого расчёта не требуется.' : `Маршрут получен: ${new Date(route.obtainedAt).toLocaleString('ru-RU')}. После открытия сохранённой поездки линия пути появится при новом построении.`;
  } else if (!manual && state.routeStatus === 'stale') {
    $('result-empty').textContent = 'Точки изменились. Постройте маршрут заново, чтобы получить актуальный расчёт.';
  } else if (Object.keys(state.fieldErrors || {}).length) {
    $('result-empty').textContent = 'Исправьте отмеченные параметры на экране «Поездка», чтобы получить расчёт.';
  } else $('result-empty').textContent = 'На экране «Поездка» введите расстояние вручную или постройте маршрут по карте.';
  const saves = {saving: 'Сохраняем поездку…', error: 'Не удалось сохранить. Текущий расчёт доступен, предыдущий черновик остаётся в хранилище.'};
  for (const id of ['save-state', 'planner-save-state']) {
    $(id).dataset.saveStatus = state.saveStatus;
    $(id).textContent = saves[state.saveStatus] || '';
    $(id).hidden = !saves[state.saveStatus];
  }
  $('retry-save').hidden = state.saveStatus !== 'error';
  $('fit-route').disabled = !points.some(Boolean);
}

async function search(index) {
  const text = $(`point-${index}`).value.trim();
  const match = text.match(/^(-?\d+(?:\.\d+)?)\s*[,;]\s*(-?\d+(?:\.\d+)?)$/);
  if (match) return selectPoint(index, {lat: Number(match[1]), lon: Number(match[2]), label: text});
  await command('search', {index, query: text});
}

document.querySelectorAll('.search').forEach(button => button.onclick = () => search(Number(button.dataset.index)));
[0, 1].forEach(index => {
  $(`point-${index}`).oninput = () => {
    pointDrafts[index] = $(`point-${index}`).value;
    command('set_point', {index, point: null});
  };
  $(`point-${index}`).onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); search(index); } };
});

function parameters() {
  return command('update_parameters', {consumption: $('consumption').value, price: $('price').value, participants: $('participants').value});
}
for (const name of ['consumption', 'price', 'participants']) {
  $(name).oninput = parameters;
  $(name).onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); $(name).blur(); } };
}
$('plus').onclick = () => { $('participants').value = Math.min(9, Math.max(1, (Number($('participants').value) || 0) + 1)); parameters(); };
$('manual-distance').oninput = () => command('update_distance', {distanceText: $('manual-distance').value});
$('manual-distance').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); $('manual-distance').blur(); } };
for (const mode of ['map', 'manual']) {
  $(`mode-${mode}`).onclick = () => command('set_mode', {mode});
}
$('minus').onclick = () => { $('participants').value = Math.max(1, (Number($('participants').value) || 1) - 1); parameters(); };
$('build').onclick = async () => {
  await parameters();
  await command('build_route');
};
$('retry-save').onclick = parameters;
$('clear').onclick = () => $('clear-dialog').showModal();
$('cancel-clear').onclick = () => $('clear-dialog').close();
$('confirm-clear').onclick = async () => {
  $('clear-dialog').close();
  await command('clear');
  pointDrafts = ['', ''];
  $('point-0').value = '';
  $('point-1').value = '';
  location.hash = '#planner';
};

function fitRoute() {
  if ($('planner').hidden || current?.mode === 'manual') return;
  map.invalidateSize({pan: false});
  const bounds = routeLayer ? routeLayer.getBounds() : L.latLngBounds([]);
  for (const point of current?.points || []) if (point) bounds.extend([point.lat, point.lon]);
  if (bounds.isValid()) map.fitBounds(bounds, {padding: [28, 28], maxZoom: 15, animate: false});
}

$('fit-route').onclick = fitRoute;

function resizeMap() {
  fitRoute();
}

new ResizeObserver(() => requestAnimationFrame(fitRoute)).observe($('map'));

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resizeMap, 100);
});

function showView() {
  const name = ['planner', 'result', 'help'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'planner';
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id !== name);
  document.querySelectorAll('nav a').forEach(link => link.classList.toggle('active', link.hash === `#${name}`));
  if (name === 'planner') setTimeout(resizeMap, 30);
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', showView);
showView();
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').then(registration => {
    function updateReady() {
      if (registration.waiting && navigator.serviceWorker.controller) {
        $('update').hidden = false;
        $('update-button').onclick = () => registration.waiting.postMessage({type: 'SKIP_WAITING'});
      }
    }
    updateReady();
    registration.addEventListener('updatefound', () => registration.installing?.addEventListener('statechange', updateReady));
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!refreshing && !$('update').hidden) { refreshing = true; location.reload(); }
    });
  }).catch(() => {
    $('startup').hidden = false;
    $('startup').textContent = 'Не удалось подготовить автономный запуск. Программа доступна в текущей вкладке.';
  });
}
