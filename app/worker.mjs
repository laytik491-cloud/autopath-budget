import {loadPyodide} from './vendor/pyodide/pyodide.mjs';
import {loadBytes, saveBytes} from './storage.mjs';

let dispatch;
let snapshot;
let currentView;
let newestGeneration = 0;
let writing = Promise.resolve();
let initialized = false;

function report(state, id) {
  self.postMessage(id === undefined ? {type: 'state', state} : {id, state});
}

function readState(result) {
  return JSON.parse(String(result));
}

function storageQueue() {
  const serialized = snapshot();
  const candidate = readState(serialized);
  if (!candidate) return;
  newestGeneration = Math.max(newestGeneration, candidate.generation);
  writing = writing.then(async () => {
    let success = false;
    let error = '';
    if (candidate.generation === newestGeneration) {
      try {
        await saveBytes(candidate.bytes);
        success = true;
      } catch (failure) {
        error = failure.name === 'QuotaExceededError' ? 'QUOTA' : 'STORAGE';
      }
    } else error = 'STALE';
    const state = await dispatch('storage_result', JSON.stringify({token: candidate.token, success, error}));
    report(readState(state));
    storageQueue();
  }).catch(failure => {
    self.postMessage({type: 'error', error: 'Не удалось сохранить данные: ' + failure.message});
  });
}

async function initialize() {
  const resources = ['config.json', 'schema.sql', 'python/calculator.py', 'python/geo.py', 'python/repository.py', 'python/controller.py', 'python/schema-v1.sql'];
  const responses = await Promise.all(resources.map(async path => {
    const response = await fetch(new URL(path, self.location.href));
    if (!response.ok) throw new Error('Не найден файл ' + path);
    return response.text();
  }));
  const pyodide = await loadPyodide({indexURL: new URL('./vendor/pyodide/', self.location.href).href});
  pyodide.FS.mkdirTree('/app');
  ['calculator.py', 'geo.py', 'repository.py', 'controller.py'].forEach((name, index) => {
    pyodide.FS.writeFile('/app/' + name, responses[index + 2]);
  });
  pyodide.FS.writeFile('/app/schema-v1.sql', responses[6]);
  pyodide.globals.set('_config_json', responses[0]);
  pyodide.globals.set('_schema_text', responses[1]);
  pyodide.runPython(`
import json
import sys
sys.path.insert(0, '/app')
from controller import TripController
_controller = TripController(json.loads(_config_json), '/app/current.sqlite', _schema_text)
_geometry_sent = None
def _encode_state(state):
    global _geometry_sent
    route = state.get('route')
    key = (state['pointsRevision'], route['obtainedAt']) if route and state['mode'] == 'map' and state['routeStatus'] == 'ready' else None
    if route and (key is None or key == _geometry_sent):
        route.pop('geometry', None)
    _geometry_sent = key
    return json.dumps(state, ensure_ascii=False, allow_nan=False)
async def _dispatch(command, payload):
    state = await _controller.handle(str(command), json.loads(str(payload)))
    return _encode_state(state)
def _snapshot():
    return json.dumps(_controller.take_snapshot(), ensure_ascii=False, allow_nan=False)
def _view():
    return _encode_state(_controller.view())
`);
  dispatch = pyodide.globals.get('_dispatch');
  snapshot = pyodide.globals.get('_snapshot');
  currentView = pyodide.globals.get('_view');
  let restored;
  try {
    const bytes = await loadBytes();
    restored = await dispatch('restore', JSON.stringify(bytes ? {bytes: Array.from(bytes)} : {}));
  } catch (failure) {
    restored = await dispatch('restore', JSON.stringify({error: 'STORAGE', message: failure.message}));
  }
  initialized = true;
  self.postMessage({type: 'ready', state: readState(restored)});
  storageQueue();
}

self.onmessage = async event => {
  const {id, command, payload = {}} = event.data || {};
  if (!initialized) {
    self.postMessage({id, error: 'Среда Python ещё загружается'});
    return;
  }
  try {
    const pending = dispatch(String(command), JSON.stringify(payload));
    setTimeout(() => {
      try { report(readState(currentView())); } catch {}
    }, 0);
    const state = await pending;
    report(readState(state), id);
    storageQueue();
  } catch (failure) {
    self.postMessage({id, error: failure.message || 'Не удалось выполнить действие'});
  }
};

initialize().catch(failure => {
  self.postMessage({type: 'error', fatal: true, error: 'Не удалось запустить Python. ' + failure.message});
});
