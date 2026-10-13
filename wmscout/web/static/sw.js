/* Service Worker: App-Gerüst offline verfügbar, zuletzt geladene Daten als Rückfall ohne Netz.
   Änderungen (Speichern, Fotos) puffert die App selbst und sendet sie, sobald wieder Netz da ist. */
var VERSION = 'wm-scout-1';
var GERUEST = ['/m', '/static/mobil.css', '/static/mobil.js', '/static/besichtigung.js',
               '/static/icon-192.png', '/static/icon-512.png', '/manifest.webmanifest'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) { return c.addAll(GERUEST); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (namen) {
    return Promise.all(namen.filter(function (n) { return n !== VERSION; }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  var lesbar = url.pathname === '/m' || url.pathname.indexOf('/static/') === 0 || url.pathname.indexOf('/api/') === 0
            || url.pathname.indexOf('/fotos/') === 0 || url.pathname === '/manifest.webmanifest';
  if (!lesbar || url.pathname === '/api/suchlauf') return;
  // erst Netz (aktuelle Daten), bei Funkloch der zuletzt gespeicherte Stand
  e.respondWith(fetch(e.request).then(function (antwort) {
    if (antwort.ok) { var kopie = antwort.clone(); caches.open(VERSION).then(function (c) { c.put(e.request, kopie); }); }
    return antwort;
  }).catch(function () {
    return caches.match(e.request).then(function (t) {
      return t || new Response(JSON.stringify({fehler: 'offline'}), {status: 503, headers: {'Content-Type': 'application/json'}});
    });
  }));
});
