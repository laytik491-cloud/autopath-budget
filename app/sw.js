const version = 'autopath-budget-1.0.0-b6d04ad45e';
const files = [
  './', './index.html', './style.css', './main.mjs', './worker.mjs', './storage.mjs',
  './config.json', './schema.sql', './manifest.webmanifest', './icon.svg',
  './vendor/icons/icon-192.png', './vendor/icons/icon-512.png',
  './python/calculator.py', './python/geo.py', './python/repository.py', './python/controller.py', './python/schema-v1.sql',
  './vendor/leaflet/leaflet.js', './vendor/leaflet/leaflet.css',
  './vendor/leaflet/images/layers.png', './vendor/leaflet/images/layers-2x.png',
  './vendor/leaflet/images/marker-icon.png', './vendor/leaflet/images/marker-icon-2x.png',
  './vendor/leaflet/images/marker-shadow.png',
  './vendor/pyodide/pyodide.js', './vendor/pyodide/pyodide.mjs',
  './vendor/pyodide/pyodide.asm.mjs', './vendor/pyodide/pyodide.asm.wasm',
  './vendor/pyodide/python_stdlib.zip', './vendor/pyodide/pyodide-lock.json'
];
const localUrls = new Set(files.map(path => new URL(path, self.registration.scope).href));

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(version);
    try {
      await cache.addAll(files);
    } catch (error) {
      await caches.delete(version);
      throw error;
    }
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('autopath-budget-') && name !== version).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const normalized = new URL(url.pathname, url.origin).href;
  if (!localUrls.has(normalized)) return;
  event.respondWith((async () => {
    const cache = await caches.open(version);
    const cached = await cache.match(normalized);
    return cached || fetch(request);
  })());
});
