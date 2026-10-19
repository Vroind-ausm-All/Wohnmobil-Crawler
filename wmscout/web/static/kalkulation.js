/* Deal Intelligence (Phase E): Anzeige einer Kalkulation – gleiche Darstellung im Händlerportal und bei den Anfragen.
   Gerechnet wird ausschließlich auf dem Server (nachrechenbar); hier wird nur angezeigt. */
var Kalkulation = (function () {
  function esc(s) { return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function eur(x) { return x === null || x === undefined ? '–' : Math.round(x).toLocaleString('de-DE') + ' €'; }
  var AMPEL = {gruen: 'im Korridor', gelb: 'über „sicher bis“', rot: 'über der Obergrenze'};
  var NAMEN = {vorsichtig: 'vorsichtig', erwartet: 'erwartet', guenstig: 'günstig'};
  var ZEILEN = [['marktniveau', 'Marktniveau'], ['haendler_vk', 'Händler-VK'], ['kosten', 'Kosten'], ['provision', 'Provision'],
                ['ziel_marge', 'Zielmarge'], ['max_ek', 'Max-EK'], ['gewinn', 'Gewinn beim Betrag']];
  function html(e, pruefsumme) {
    if (!e) return '';
    if (!e.moeglich) return '<p class="hinweis info">' + esc(e.grund) + '</p>';
    var s = e.szenarien, namen = ['vorsichtig', 'erwartet', 'guenstig'].filter(function (n) { return s[n]; }), erw = s.erwartet, k = e.korridor, r = e.risiko;
    var h = '<div class="kalk"><div class="zeile"><b>Kalkulation' + (e.betrag ? ' bei ' + eur(e.betrag) : '') + '</b>' +
      (e.ampel ? '<span class="tag ' + esc(e.ampel) + '">' + esc(AMPEL[e.ampel]) + '</span>' : '') + '</div>' +
      '<div class="zahlen">' + (e.betrag ? '<div><span>Gewinn erwartet</span><b>' + eur(erw.gewinn) + '</b></div>' : '') +
      '<div><span>Max-EK sicher bis</span><b>' + eur(k.sicher_bis) + '</b></div><div><span>Obergrenze</span><b>' + eur(k.obergrenze) + '</b></div></div>' +
      '<p class="leise">' + (e.betrag && s.vorsichtig ? 'Gewinn vorsichtig ' + eur(s.vorsichtig.gewinn) + ' · günstig ' + eur(s.guenstig.gewinn) + ' · ' : '') +
      'Risiko ' + r.punkte + '/100 (' + esc(r.stufe) + ') · Datenlage ' + esc(e.sicherheit) + '</p>' +
      '<details><summary>Rechenweg, Annahmen, Unsicherheit</summary><table><tr><th></th>' +
      namen.map(function (n) { return '<th>' + esc(NAMEN[n]) + '</th>'; }).join('') + '</tr>' +
      ZEILEN.filter(function (z) { return s.erwartet[z[0]] !== undefined; }).map(function (z) {
        return '<tr><td>' + z[1] + '</td>' + namen.map(function (n) { return '<td>' + eur(s[n][z[0]]) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</table>' +
      (s.vorsichtig ? '' : '<p class="leise">Keine Marktspanne (Datenlage ' + esc(e.sicherheit) + ') – nur das erwartete Szenario.</p>') +
      '<p><b>Risiko</b></p><ul>' + r.gruende.map(function (g) { return '<li>' + esc(g.grund) + ' (+' + g.punkte + ')</li>'; }).join('') + '</ul>' +
      '<p><b>Annahmen</b></p><ul>' + e.annahmen.map(function (a) { return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' +
      (pruefsumme ? '<p class="leise">Prüfsumme der Eingabe ' + esc(pruefsumme) + ' – jede gespeicherte Kalkulation lässt sich damit exakt nachrechnen.</p>' : '') +
      '</details></div>';
    return h;
  }
  return {html: html, eur: eur, esc: esc};
})();
