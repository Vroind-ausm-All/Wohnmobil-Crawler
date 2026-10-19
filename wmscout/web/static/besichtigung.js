/* Mängelabzug – exakte Kopie der Python-Rechnung (wmscout/bewertung/besichtigung.py) für den Offline-Betrieb.
   Verbindlich bleibt die Rechnung des Servers; tests/test_besichtigung_paritaet.py prüft, dass beide gleich rechnen. */
(function (ziel) {
  "use strict";
  var STUFEN = ["leicht", "mittel", "schwer"];
  var TAG = 86400000;

  function runde(x, auf) { auf = auf || 10; return Math.floor(x / auf + 0.5) * auf; }
  function zahl(x) { return String(x).replace(".", ","); }
  function alsZahl(w) {                 // wie _als_zahl in Python
    if (w === null || w === undefined || typeof w === "boolean" || String(w).trim() === "") return null;
    var s = String(w).replace(",", ".").trim();
    if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) return null;
    var x = Number(s);
    return isFinite(x) ? x : null;
  }
  function tausender(n) { return Number(n).toLocaleString("de-DE"); }

  function heuteUtc(heute) {           // heute: "YYYY-MM-DD" oder Date
    if (typeof heute === "string") { var t = heute.split("-"); return Date.UTC(+t[0], +t[1] - 1, +t[2]); }
    var d = heute || new Date();
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function dotAlterJahre(dot, heute) {
    var m = /^\s*(\d{2})(\d{2})\s*$/.exec(String(dot || ""));
    if (!m) return null;
    var woche = +m[1], jahr = 2000 + +m[2], h = heuteUtc(heute);
    if (woche < 1 || woche > 53 || jahr > new Date(h).getUTCFullYear()) return null;
    var jan4 = Date.UTC(jahr, 0, 4), wt = (new Date(jan4).getUTCDay() + 6) % 7;
    var montag = jan4 - wt * TAG + (Math.min(woche, 52) - 1) * 7 * TAG;
    var tage = Math.round((h - montag) / TAG);
    return Math.floor(Math.max(0, tage) / 365.25 * 10 + 0.5) / 10;
  }

  function feuchteStufe(wert, stufen) {
    for (var i = 0; i < stufen.length; i++) if (wert <= stufen[i].bis) return stufen[i].stufe;
    return stufen[stufen.length - 1].stufe;
  }

  function mangelIndex(katalog) {
    var idx = {};
    katalog.kategorien.forEach(function (k) {
      k.maengel.forEach(function (m) { idx[m.key] = Object.assign({}, m, { kategorie: k.name }); });
    });
    return idx;
  }

  function berechne(katalog, daten, basis, heute) {
    daten = daten || {};
    var g = katalog.grundsaetze, mess = katalog.messungen, index = mangelIndex(katalog);
    var posten = [], hinweise = [], ko = [];
    var marktwert = basis.marktwert_privat || 0;
    var messungen = daten.messungen || {};

    // Feuchtigkeit: höchster Wert je Bereich
    var fm = mess.feuchtigkeit, bereiche = {};
    var punkte = [];
    (messungen.feuchtigkeit || []).forEach(function (p) {
      var wert = alsZahl(p.wert);
      if (wert === null) {
        if (String(p.wert || "").trim()) hinweise.push("Messwert „" + p.wert + "“ ungültig – ignoriert");
        return;
      }
      punkte.push(p);
      var name = String(p.bereich || "").trim() || "ohne Bereich";
      bereiche[name] = Math.max(bereiche[name] || 0, wert);
    });
    Object.keys(bereiche).sort().forEach(function (name) {
      var stufe = feuchteStufe(bereiche[name], fm.stufen);
      if (stufe !== "ok") posten.push({ quelle: "messung", name: "Feuchtigkeit " + name + " (" + zahl(bereiche[name]) + " %)",
                                        stufe: stufe, betrag: runde(fm.kosten_je_bereich[stufe]) });
    });

    // Reifen
    var rm = mess.reifen;
    var reifen = (messungen.reifen || []).filter(function (r) { return String(r.dot || "").trim(); });
    reifen.forEach(function (r) {
      var alter = dotAlterJahre(r.dot, heute), pos = String(r.position || "").trim() || "Reifen";
      if (alter === null) hinweise.push("DOT „" + r.dot + "“ (" + pos + ") nicht lesbar – vierstellig eingeben, z. B. 2318");
      else if (alter > rm.max_alter_jahre) posten.push({ quelle: "messung", name: "Reifen " + pos + " " + zahl(alter) + " Jahre alt",
                                                         stufe: null, betrag: runde(rm.kosten_je_reifen) });
    });

    // km-Stand
    var km = mess.km, abgelesen = alsZahl(daten.km_abgelesen), inseriert = alsZahl(basis.km_anzeige);
    if (abgelesen && inseriert) {
      var mehr = Math.trunc(abgelesen - inseriert);
      if (mehr > km.toleranz_km) posten.push({ quelle: "messung", name: tausender(mehr) + " km mehr als in der Anzeige",
                                               stufe: null, betrag: runde(marktwert * km.prozent_je_10000_km * mehr / 10000) });
    }

    // erfasste Mängel
    (daten.maengel || []).forEach(function (m) {
      var k = index[m.key];
      if (!k) { hinweise.push("Unbekannter Mangel „" + m.key + "“ ignoriert"); return; }
      var stufe = k.stufen ? (m.stufe === undefined ? null : m.stufe) : null, betrag;
      var eingabe = alsZahl(m.betrag);
      if (eingabe !== null) betrag = eingabe;
      else if (String(m.betrag || "").trim()) { hinweise.push(k.name + ": Betrag „" + m.betrag + "“ ungültig"); return; }
      else if (k.stufen) {
        if (!(stufe in k.stufen)) { hinweise.push(k.name + ": Schweregrad fehlt"); return; }
        betrag = k.stufen[stufe];
      } else if (k.betrag !== undefined) betrag = k.betrag;
      else if (k.prozent !== undefined) betrag = marktwert * k.prozent;
      else { hinweise.push(k.name + ": Betrag fehlt"); return; }
      var name = k.frei ? String(m.name || "").trim() : k.name;
      posten.push({ quelle: "mangel", key: k.key, name: name || k.name, stufe: stufe, betrag: runde(betrag), notiz: m.notiz || "" });
      if (k.ko || (k.ko_ab && stufe && STUFEN.indexOf(stufe) >= STUFEN.indexOf(k.ko_ab))) ko.push(k.name);
    });

    // Summen
    var summe = posten.reduce(function (s, p) { return s + p.betrag; }, 0);
    var gutschrift = runde(Math.min(summe, (basis.reparaturrisiko || 0) * g.risiko_anrechnung));
    var anpassung = runde(alsZahl((daten.anpassung || {}).betrag) || 0);
    var netto = summe - gutschrift + anpassung;
    var faktor = basis.differenzbesteuerung === false ? 1.0 : 1.19;
    var ekAbzug = runde(netto * faktor);
    var maxEk = basis.max_ek || 0, maxEkNeu = maxEk - ekAbzug, angebot = basis.angebot || 0, r = g.rundung_vorschlag;
    var vorschlag = Math.max(0, Math.floor(Math.min(angebot - ekAbzug, maxEkNeu) / r) * r);

    // Pflichtpunkte
    var abgehakt = daten.pruefpunkte || {}, fehlend = [];
    katalog.pruefpunkte.forEach(function (p) {
      if (!p.pflicht) return;
      if (p.messung === "feuchtigkeit" && punkte.length < fm.mindest_messpunkte)
        fehlend.push(p.name + " (mind. " + fm.mindest_messpunkte + " Messpunkte, erfasst " + punkte.length + ")");
      else if (p.messung === "reifen" && reifen.length < rm.mindest_reifen)
        fehlend.push(p.name + " (mind. " + rm.mindest_reifen + ", erfasst " + reifen.length + ")");
      else if (!p.messung && !abgehakt[p.key]) fehlend.push(p.name);
    });

    return { posten: posten, summe_maengel: summe, risiko_gutschrift: gutschrift, anpassung: anpassung, netto_abzug: netto,
             ek_faktor: faktor, ek_abzug: ekAbzug, max_ek: maxEk, max_ek_neu: maxEkNeu, angebot: angebot, vorschlag: vorschlag,
             ko: ko, fehlende_pflicht: fehlend, vollstaendig: fehlend.length === 0, hinweise: hinweise };
  }

  var api = { berechne: berechne, dotAlterJahre: dotAlterJahre, mangelIndex: mangelIndex };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else ziel.Besichtigung = api;
})(typeof window !== "undefined" ? window : this);
