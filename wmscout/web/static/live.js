// Live-Aktualisierung (G1, ADR-032): Der Server meldet per Server-Sent Events nur „Art X hat sich geändert“; die Seite lädt
// dann über ihre normalen Routen nach. Mehrere Meldungen kurz hintereinander lösen nur ein Nachladen aus. Ohne SSE (alter Browser,
// Proxy puffert, Verbindung weg) bleibt das Abfragen der Seite in Abständen bestehen – Live.verbunden() sagt, ob es gerade nötig ist.
(function () {
  'use strict';
  var hoerer = [], quelle = null, verbunden = false, wartet = {}, ruhe = 400;
  function verteilen(e) {
    var d; try { d = JSON.parse(e.data); } catch (x) { return; }
    hoerer.forEach(function (h) {
      if (h.arten.indexOf(d.art) < 0 && d.art !== 'alles') return;
      var k = h.nr;
      clearTimeout(wartet[k]);
      wartet[k] = setTimeout(function () { h.f(d); }, ruhe);
    });
  }
  function starten() {
    if (quelle || !window.EventSource) return;
    quelle = new EventSource('/api/ereignisse');
    quelle.addEventListener('aenderung', verteilen);
    quelle.onopen = function () { verbunden = true; };
    quelle.onerror = function () { verbunden = false; };   // EventSource verbindet selbst neu (retry vom Server)
  }
  window.Live = {
    an: function (arten, f) { hoerer.push({arten: arten, f: f, nr: hoerer.length}); starten(); },
    verbunden: function () { return verbunden; }
  };
})();
