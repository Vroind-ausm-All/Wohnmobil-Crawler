/* Service Worker: App-Gerüst offline verfügbar, zuletzt geladene Daten als Rückfall ohne Netz.
   Änderungen (Speichern, Fotos) puffert die App selbst und sendet sie, sobald wieder Netz da ist. */
var VERSION = 'wm-scout-19';      // 19: Top-Deals, Quelle, Deal-Score + Risikofaktoren (P6-01); 18: Händlermarkt im Fahrzeugdetail (P5-04); 17: Max-EK als Spanne, Mängelliste (P5-03); 16: Link zur Statusseite (P4-04); 15: Liste „Neu & gesenkt“, Abzeichen Neuigkeit (P4-03); 14: Suchprofil-Filter in der Liste (P4-01); 13: Datenqualität (Abzeichen, Markierungen im Detail, P3-08); 12: Kontaktverlauf im Fahrzeugdetail, Nachfassen bestätigen (P3-06); 11: Anbieter mit Herkunft + Korrektur im Fahrzeugdetail (P3-05); 10: Abzeichen Verfügbarkeit (reserviert/verkauft/offline, P3-04); 9: Gruppe „Gleiches Fahrzeug“ im Fahrzeugdetail (P3-02b, nur Anzeige); 8: Preisfeld im Formular „Inserat einlesen“ (P2-05); 7: Inserat einlesen (Link + Text, P2-05); 6: abgeschlossene Besichtigungen nie im Speicher (P1-14b); 5: Versionskonflikt (P1-07); 4: nur noch Positivliste (G0) – alte Caches werden gelöscht
var GERUEST = ['/m', '/static/mobil.css', '/static/mobil.js', '/static/besichtigung.js', '/static/textimport.js', '/static/textimport.css', '/static/dubletten.js', '/static/dubletten.css',
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
  // Positivliste (G0): nur, was die Handy-App für die Arbeit vor Ort ohne Netz braucht. Verkaufsanfragen, Ankäufe, Kalkulationen,
  // Auktionen und Händlerdaten (Kontakte, Unterschriften, Preise) landen nie im Speicher des Geräts; Team-Stand immer frisch.
  var lesbar = /^\/(m|manifest\.webmanifest)$/.test(url.pathname) || /^\/static\//.test(url.pathname) ||
               /^\/fotos\/\d+\//.test(url.pathname) ||
               /^\/api\/(ich|heute|katalog|nutzer|fahrzeuge|fahrzeug\/[\w-]+|besichtigung\/\d+)$/.test(url.pathname);
  if (!lesbar) return;
  // erst Netz (aktuelle Daten), bei Funkloch der zuletzt gespeicherte Stand
  e.respondWith(fetch(e.request).then(function (antwort) {
    if (antwort.status === 401) caches.delete(VERSION);       // abgemeldet oder Sitzung abgelaufen: nichts auf dem Gerät lassen
    if (antwort.headers.get('X-Scout-Offline') === 'nein') caches.open(VERSION).then(function (c) { c.delete(e.request); });
    else if (antwort.ok) { var kopie = antwort.clone(); caches.open(VERSION).then(function (c) { c.put(e.request, kopie); }); }
    return antwort;
  }).catch(function () {
    return caches.match(e.request).then(function (t) {
      return t || new Response(JSON.stringify({fehler: 'offline'}), {status: 503, headers: {'Content-Type': 'application/json'}});
    });
  }));
});
