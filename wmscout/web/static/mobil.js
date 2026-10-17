/* Wohnmobil-Scout – Handy-App (PWA). Seiten per #/route, Daten per JSON-API, Besichtigungen auch ohne Netz:
   Eingaben werden lokal gespeichert (localStorage), Fotos in einer Warteschlange (IndexedDB) und übertragen,
   sobald wieder Netz da ist. Die Rechnung läuft offline mit besichtigung.js, verbindlich rechnet der Server. */
(function () {
  "use strict";
  var S = { ich: null, csrf: null, katalog: null, nutzer: null };
  var inhalt = document.getElementById("inhalt");

  // ---------------------------------------------------------------- Hilfen
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function link(u) { return /^https?:\/\//i.test(String(u || "")) ? esc(u) : "#"; }   // nur http(s) als Link
  function eur(x) { return x === null || x === undefined || x === "" ? "–" : Math.round(x).toLocaleString("de-DE") + " €"; }
  function tsd(x) { return x ? Number(x).toLocaleString("de-DE") : "?"; }
  function datum(iso) {
    if (!iso) return "ohne Termin";
    var d = new Date(iso);
    return d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" }) + " · " +
           d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) + " Uhr";
  }
  function heuteIso() { var d = new Date(); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  var toastUhr;
  function toast(t) {
    var el = document.getElementById("toast");
    el.textContent = t; el.classList.add("zeigen");
    clearTimeout(toastUhr); toastUhr = setTimeout(function () { el.classList.remove("zeigen"); }, 4000);
  }
  function ampelTag(a) { return '<span class="tag ' + esc(a) + '">' + esc({ gruen: "Grün", gelb: "Gelb", rot: "Rot" }[a] || "–") + "</span>"; }

  function api(pfad, daten, nochmal) {
    var opt = { credentials: "same-origin", headers: {} };
    if (daten !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.headers["X-Scout-Token"] = S.csrf || "";
      opt.body = JSON.stringify(daten);
    }
    return fetch(pfad, opt).then(function (r) {
      if (r.status === 401) { location.href = "/login?weiter=" + encodeURIComponent("/m" + location.hash); throw new Error("Bitte anmelden"); }
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.status === 403 && daten !== undefined && !nochmal) {        // Server neu gestartet → neues Token holen
          return ladeIch().then(function () { return api(pfad, daten, true); });
        }
        if (!r.ok) { var e = new Error(d.fehler || ("Fehler " + r.status)); e.status = r.status; e.grund = d.grund || ""; e.daten = d; throw e; }
        return d;
      });
    });
  }
  function ladeIch() { return api("/api/ich").then(function (d) { S.ich = d; S.csrf = d.csrf; return d; }); }
  function katalog() { return S.katalog ? Promise.resolve(S.katalog) : api("/api/katalog").then(function (k) { S.katalog = k; return k; }); }
  function nutzerListe() { return S.nutzer ? Promise.resolve(S.nutzer) : api("/api/nutzer").then(function (n) { S.nutzer = n; return n; }); }

  function kopiere(text) {
    var ta = document.createElement("textarea"), ok = false;
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(ta); ta.select();
    try { ok = document.execCommand("copy"); } catch (e) { /* weiter mit Clipboard-API */ }
    document.body.removeChild(ta);
    if (!ok && navigator.clipboard) { navigator.clipboard.writeText(text).catch(function () {}); ok = true; }
    return ok;
  }

  // ---------------------------------------------------------------- Offline-Puffer
  function entwurfLesen(bid) { try { return JSON.parse(localStorage.getItem("wm-entwurf-" + bid) || "null"); } catch (e) { return null; } }
  function entwurfSchreiben(bid, e) { try { localStorage.setItem("wm-entwurf-" + bid, JSON.stringify(e)); } catch (x) { /* Speicher voll */ } }
  function offeneEntwuerfe() {
    var ids = [];
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k.indexOf("wm-entwurf-") === 0 && (entwurfLesen(k.slice(11)) || {}).offen) ids.push(k.slice(11)); } } catch (e) { /* kein Speicher */ }
    return ids;
  }
  var idb = null;
  function fotoDb() {
    if (idb) return idb;
    idb = new Promise(function (ok, fehler) {
      if (!window.indexedDB) return fehler(new Error("kein IndexedDB"));
      var r = indexedDB.open("wm-scout", 1);
      r.onupgradeneeded = function () { r.result.createObjectStore("fotos", { keyPath: "nr", autoIncrement: true }); };
      r.onsuccess = function () { ok(r.result); }; r.onerror = function () { fehler(r.error); };
    });
    return idb;
  }
  function fotoStore(modus) { return fotoDb().then(function (db) { return db.transaction("fotos", modus).objectStore("fotos"); }); }
  function fotoMerken(f) { return fotoStore("readwrite").then(function (s) { return new Promise(function (ok) { s.add(f).onsuccess = function (e) { ok(e.target.result); }; }); }); }
  function fotosWartend() { return fotoStore("readonly").then(function (s) { return new Promise(function (ok) { s.getAll().onsuccess = function (e) { ok(e.target.result); }; }); }).catch(function () { return []; }); }
  function fotoErledigt(nr) { return fotoStore("readwrite").then(function (s) { s.delete(nr); }); }

  var syncLaeuft = false;
  function synchronisiere() {
    if (syncLaeuft || !navigator.onLine) return Promise.resolve();
    syncLaeuft = true;
    var kette = Promise.resolve();
    offeneEntwuerfe().forEach(function (bid) {
      kette = kette.then(function () { return speichereServer(bid).catch(function () {}); });
    });
    kette = kette.then(fotosWartend).then(function (liste) {
      return liste.reduce(function (p, f) {
        return p.then(function () {
          return api("/api/besichtigung/" + f.bid + "/foto", { bild: f.bild, mangel_key: f.mangel_key }).then(function (neu) {
            return fotoErledigt(f.nr).then(function () {
              if (B && String(B.id) === String(f.bid)) { B.fotos.push(neu); zeigeFotos(); }
            });
          }).catch(function () {});
        });
      }, Promise.resolve());
    });
    return kette.then(function () { syncLaeuft = false; syncAnzeige(); }, function () { syncLaeuft = false; syncAnzeige(); });
  }
  function syncAnzeige() {
    fotosWartend().then(function (f) {
      var n = offeneEntwuerfe().length + f.length, el = document.getElementById("sync");
      el.hidden = n === 0; el.textContent = n + " wartet";
    });
    document.getElementById("netz").hidden = navigator.onLine;
  }
  window.addEventListener("online", function () { syncAnzeige(); synchronisiere(); });
  window.addEventListener("offline", syncAnzeige);

  // ---------------------------------------------------------------- Seiten
  function heute() {
    return api("/api/heute").then(function (d) {
      var t = heuteIso(), ich = S.ich.nutzer;
      var heutige = d.termine.filter(function (b) { return (b.termin || "").slice(0, 10) === t; });
      inhalt.innerHTML =
        '<h1>Hallo ' + esc(ich.name) + "</h1>" +
        '<p class="leise">' + esc(new Date().toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" })) + "</p>" +
        '<div class="kacheln">' +
        '<a class="kachel" href="#/liste/bereit"><b>' + d.bereit + "</b><span>Anschreiben bereit</span></a>" +
        '<a class="kachel" href="#/liste/nachfassen"><b>' + d.nachfassen + "</b><span>Nachfassen</span></a>" +
        '<a class="kachel" href="#/liste/arbeit"><b>' + d.arbeit + "</b><span>In Arbeit</span></a></div>" +
        '<p><a class="knopf klein" href="/anfragen">Verkaufsanfragen</a> <a class="knopf klein" href="/verkaufen">+ Anfrage erfassen</a></p>' +
        "<h2>Besichtigungen heute</h2>" + (heutige.length ? heutige.map(terminKarte).join("") : '<p class="leise">Keine Termine für heute.</p>') +
        (d.termine.length > heutige.length ? '<p><a href="#/termine">Alle ' + d.termine.length + " offenen Besichtigungen →</a></p>" : "") +
        "<h2>Suche</h2>" + '<p class="leise">' + esc(d.suchlauf.laeuft ? "Läuft: " + (d.suchlauf.meldung || "") : (d.suchlauf.meldung || "Bereit")) +
        (d.suchlauf.naechste_auto ? " · nächste automatische Suche " + esc(d.suchlauf.naechste_auto.slice(11, 16)) + " Uhr" : "") + "</p>" +
        '<div class="reihe"><button class="knopf" data-aktion="suchen">↻ Neue Anzeigen suchen</button></div>' +
        (S.ich.team ? '<p class="leise mitte"><a href="#" data-aktion="abmelden">Abmelden</a></p>' : "");
    });
  }

  function terminKarte(b) {
    var ich = S.ich.nutzer;
    return '<div class="karte"><div class="zeile"><span class="titel">' + esc(b.fahrzeug) + '</span><span class="tag">' + esc((S.ich.besichtigung_status || {})[b.status] || b.status) + "</span></div>" +
      '<p class="leise">' + esc(datum(b.termin)) + (b.adresse ? " · " + esc(b.adresse) : "") + (b.zustaendig ? " · " + esc(b.zustaendig.name) : "") + "</p>" +
      '<div class="reihe">' + (b.darf_bearbeiten ? '<a class="knopf primaer klein" href="#/besichtigung/' + b.id + '">Besichtigung öffnen</a>' : "") +
      (b.karte ? '<a class="knopf klein" href="' + link(b.karte) + '" target="_blank" rel="noopener">Navigation</a>' : "") +
      (b.termin ? '<a class="knopf klein" href="/api/besichtigung/' + b.id + '/ics">Kalender</a>' : "") +
      (b.zustaendig && b.zustaendig.id !== ich.id ? '<a class="knopf klein" href="' + link(b.whatsapp) + '" target="_blank" rel="noopener">WhatsApp</a>' : "") +
      "</div></div>";
  }

  function termine() {
    return api("/api/heute").then(function (d) {
      inhalt.innerHTML = "<h1>Offene Besichtigungen</h1>" +
        (d.termine.length ? d.termine.map(terminKarte).join("") : '<p class="leise">Keine offenen Besichtigungen. Im Fahrzeug auf „Besichtigung planen“ tippen.</p>');
    });
  }

  var LISTEN = { bereit: "Anschreiben bereit", nachfassen: "Nachfassen", arbeit: "In Arbeit", alle: "Alle Fahrzeuge" };
  var WER = { alle: "Alle", meine: "Meine", frei: "Frei" };
  function liste(filter, suche) {
    var wer = S.ich.team ? (S.wer || "alle") : "alle";
    return api("/api/fahrzeuge?filter=" + encodeURIComponent(filter) + "&q=" + encodeURIComponent(suche || "") + (wer !== "alle" ? "&wer=" + wer : "")).then(function (l) {
      inhalt.innerHTML = "<h1>" + esc(LISTEN[filter] || "Fahrzeuge") + " (" + l.length + ")</h1>" +
        '<input type="search" id="suche" placeholder="Marke, Modell, Ort …" value="' + esc(suche || "") + '">' +
        '<div class="reihe">' + Object.keys(LISTEN).map(function (f) {
          return '<a class="knopf klein' + (f === filter ? " primaer" : "") + '" href="#/liste/' + f + '">' + esc(LISTEN[f]) + "</a>";
        }).join("") + "</div>" +
        (S.ich.team ? '<div class="reihe" role="group" aria-label="Wer">' + Object.keys(WER).map(function (w) {
          return '<button class="knopf klein' + (w === wer ? " primaer" : "") + '" data-aktion="wer" data-wer="' + w + '" aria-pressed="' + (w === wer) + '">' + WER[w] + "</button>";
        }).join("") + "</div>" : "") +
        (l.length ? l.map(function (f) {
          return '<a class="karte" href="#/fahrzeug/' + esc(f.id) + '"><div class="zeile"><span class="titel">' + esc(f.fahrzeug) + "</span>" + teamBadge(f.team) + ampelTag(f.ampel) + "</div>" +
            '<p class="leise">EZ ' + esc(f.ez_jahr || "?") + " · " + tsd(f.km) + " km · " + esc(f.ort || "") + (f.entfernung_km !== null ? " · " + tsd(f.entfernung_km) + " km entfernt" : "") + "</p>" +
            hinweisZeilen(f) +
            (f.nachfassen ? '<p class="leise" style="color:var(--gelb)">Nachfassen: ' + esc(f.nachfassen) + "</p>" : "") +
            '<div class="zahlen"><div><span>Wunschpreis</span>' + eur(f.preis) + "</div><div><span>Erstangebot</span><b>" + eur(f.erstangebot) +
            "</b></div><div><span>Max-EK</span>" + eur(f.max_ek) + "</div></div></a>";
        }).join("") : '<p class="leise">Nichts gefunden.</p>');
      var feld = document.getElementById("suche"), uhr;
      feld.oninput = function () { clearTimeout(uhr); uhr = setTimeout(function () { liste(filter, feld.value).then(function () { var f = document.getElementById("suche"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); }); }, 400); };
    });
  }

  // Hinweise zum Fahrzeug (z. B. Fahrzeugart nicht bestätigt): gelbe Zeile, Text nur über esc()
  function hinweisZeilen(f) {
    return (f.hinweise || []).map(function (h) { return '<p class="hinweis info">⚠ ' + esc(h) + "</p>"; }).join("");
  }

  // ---------------------------------------------------------------- Team (nur mit angelegten Nutzern, T2)
  // Badge = Symbol + Kürzel (nie nur Farbe); der Server entscheidet, die App zeigt seinen letzten Stand.
  var TEAM_SYMBOL = { reserviert: "◔", kontaktiert: "✉", ohne_zuordnung: "?", verwaist: "!" };
  function teamFrei(t) { return !t || ((t.zustand === "frei" || t.zustand === "ohne_zuordnung" || t.zustand === "verwaist") && !t.dublette_von); }
  function teamText(t) {
    if (!t) return "";
    var p = t.bearbeiter, dub = t.dublette_von;
    if (!p && dub && dub.bearbeiter) return "Dublette bearbeitet " + (dub.mein ? "du" : dub.bearbeiter.name) + " – nicht doppelt anschreiben";
    if (t.zustand === "reserviert") return (t.mein ? "Von dir" : "Von " + p.name) + " reserviert seit " + datum(t.seit) + (t.laeuft_ab ? ", frei ab " + datum(t.laeuft_ab) : "");
    if (t.zustand === "kontaktiert") return (t.mein ? "Du bearbeitest es" : (p ? p.name : "Ein Kollege") + " bearbeitet es");
    if (t.zustand === "ohne_zuordnung") return "In Arbeit, aber niemandem zugeordnet";
    if (t.zustand === "verwaist") return "Bearbeiter deaktiviert – übernehmen oder zuweisen lassen";
    return "Frei";
  }
  function teamBadge(t) {
    if (!t || (t.zustand === "frei" && !t.dublette_von)) return "";
    var p = t.bearbeiter, dub = !p && t.dublette_von && t.dublette_von.bearbeiter ? t.dublette_von : null;
    var z = dub ? "dublette" : t.zustand, mein = t.mein || (dub && dub.mein);
    var text = (dub ? "⧉" : TEAM_SYMBOL[z] || "•") + " " + (p ? p.kuerzel : dub ? dub.bearbeiter.kuerzel : { ohne_zuordnung: "ohne Zuordnung", verwaist: "verwaist" }[z] || z);
    return '<span class="tb tb-' + esc(z) + (mein ? " mein" : "") + '" title="' + esc(teamText(t)) + '">' + esc(text) + "</span>";
  }
  // Einheitliche Fehlermeldung; bei 409 (Kollege hält das Fahrzeug) mit dem Text des Servers und frischer Ansicht
  function teamFehler(e, id) {
    if (e.grund === "csrf") { toast("Sitzung abgelaufen – bitte neu laden"); return; }
    if (e.grund === "belegt") { toast("Datenbank kurz belegt – bitte erneut versuchen"); return; }
    toast((e.status === 409 ? "✕ Nicht senden – " : "") + e.message);
    if (e.status === 409 && id) fahrzeug(id);
  }

  function fahrzeug(id) {
    return Promise.all([api("/api/fahrzeug/" + encodeURIComponent(id)), nutzerListe()]).then(function (r) {
      var f = r[0], nutzer = r[1], b = f.bewertung, ich = S.ich.nutzer;
      var status = S.ich.status || {}, t = f.team, darf = (t && t.darf) || {};
      var fremd = !!t && !t.mein && !teamFrei(t), sperr = fremd ? " disabled" : "";
      inhalt.innerHTML =
        "<h1>" + esc(f.fahrzeug) + "</h1>" +
        '<p class="leise">' + ampelTag(f.ampel) + " EZ " + esc(f.ez_jahr || "?") + " · " + tsd(f.km) + " km · " + esc(f.ort || "") +
        (f.entfernung_km !== null ? " · " + tsd(f.entfernung_km) + " km entfernt" : "") + "</p>" +
        '<div class="karte"><div class="zahlen"><div><span>Wunschpreis</span>' + eur(f.preis) + "</div><div><span>Erstangebot</span><b>" + eur(f.erstangebot) +
        "</b></div><div><span>Max-EK</span>" + eur(f.max_ek) + "</div></div>" +
        '<p class="leise">Marktniveau ' + eur(b.marktwert_angebote) + " · Sicherheit " + esc(b.sicherheit) + "</p>" +
        '<a class="knopf klein" href="' + link(f.url) + '" target="_blank" rel="noopener">Anzeige öffnen ↗</a></div>' +
        hinweisZeilen(f) +
        (t ? '<div class="karte team"><div class="zeile">' + (teamBadge(t) || '<span class="tb tb-frei">frei</span>') + '<span class="leise">' + esc(teamText(t)) + "</span></div>" +
          '<div class="reihe">' + (darf.uebernehmen && !t.mein ? '<button class="knopf klein" data-aktion="uebernehmen">Ich übernehme</button>' : "") +
          (darf.abgeben ? '<button class="knopf klein" data-aktion="abgeben">Abgeben</button>' : "") +
          (darf.erzwingen && fremd && !darf.uebernehmen ? '<button class="knopf klein" data-aktion="erzwingen">Übernahme erzwingen</button>' : "") + "</div></div>" : "") +
        (f.status === "vorbereitet" ? '<p class="hinweis info">Text kopiert – noch nicht als gesendet bestätigt.</p>' +
          '<button class="knopf primaer voll" data-aktion="gesendet"' + sperr + '>gesendet ✓</button>' : "") +
        (f.nachfass_text ? "<h2>Nachfassen</h2><p class=\"leise\">" + esc(f.nachfassen) + '</p><textarea id="nf">' + esc(f.nachfass_text) + "</textarea>" +
          '<button class="knopf primaer voll" data-aktion="nachfassen"' + sperr + '>↻ Kopieren &amp; Anzeige öffnen</button>' : "") +
        (f.brief ? '<h2>Anschreiben</h2><textarea id="brief">' + esc(f.brief) + "</textarea>" +
          '<button class="knopf primaer voll" data-aktion="anschreiben"' + sperr + '>✉ Kopieren &amp; Anzeige öffnen</button>' +
          (fremd ? '<p class="hinweis warn">' + esc(teamText(t)) + " – nicht anschreiben.</p>" : "") :
          (f.anschreiben_text ? "<h2>" + (f.status === "vorbereitet" ? "Kopierter Text" : "Gesendet") + '</h2><textarea readonly>' + esc(f.anschreiben_text) + "</textarea>" : (f.sperre ? '<p class="hinweis info">Kein Anschreiben: ' + esc(f.sperre) + "</p>" : ""))) +
        "<h2>Status</h2><div class=\"reihe\">" + Object.keys(status).map(function (k) {
          return '<button class="knopf klein' + (k === f.status ? " primaer" : "") + '" data-status="' + esc(k) + '">' + esc(status[k]) + "</button>";
        }).join("") + "</div>" +
        '<label>Notiz<textarea id="notiz" style="min-height:70px">' + esc(f.notiz || "") + "</textarea></label>" +
        "<h2>Besichtigung</h2>" + f.besichtigungen.map(terminKarte).join("") +
        '<div class="karte"><label>Termin<input type="datetime-local" id="b-termin"></label>' +
        '<label>Adresse beim Verkäufer<input id="b-adresse" placeholder="Straße, Ort" value="' + esc(f.ort || "") + '"></label>' +
        '<label>Zuständig<select id="b-wer">' + (nutzer.length ? nutzer.map(function (n) {
          return '<option value="' + n.id + '"' + (n.id === ich.id ? " selected" : "") + ">" + esc(n.name) + "</option>";
        }).join("") : '<option value="">ich</option>') + "</select></label>" +
        '<button class="knopf primaer voll" style="margin-top:12px" data-aktion="planen">Besichtigung planen</button></div>';
      inhalt.dataset.id = f.id; inhalt.dataset.url = f.url; inhalt.dataset.quelle = f.quelle || ""; inhalt.dataset.erst = f.brief_betrag || "";
      inhalt.dataset.nfbetrag = f.nachfass_betrag || "";
      document.getElementById("notiz").onchange = function (e) { api("/api/notiz", { id: f.id, notiz: e.target.value }).then(function () { toast("Notiz gespeichert"); }); };
    });
  }

  // ---------------------------------------------------------------- Besichtigung
  var B = null, speicherUhr = null;
  var STANDARD_REIFEN = ["VL", "VR", "HL", "HR"];

  function besichtigung(id) {
    return Promise.all([api("/api/besichtigung/" + id), katalog()]).then(function (r) {
      var srv = r[0], lokal = entwurfLesen(id);
      B = { id: srv.id, basis: srv.basis, daten: srv.daten || {}, version: srv.version, fotos: srv.fotos, info: srv, katalog: r[1] };
      if (lokal && lokal.offen) { B.daten = lokal.daten; toast("Lokale Änderungen werden übertragen …"); }
      var d = B.daten;
      d.pruefpunkte = d.pruefpunkte || {}; d.messungen = d.messungen || {}; d.maengel = d.maengel || [];
      d.fahrzeug = d.fahrzeug || {}; d.anpassung = d.anpassung || { betrag: "", grund: "" };
      if (!d.messungen.feuchtigkeit) d.messungen.feuchtigkeit = [];
      if (!d.messungen.reifen) d.messungen.reifen = STANDARD_REIFEN.map(function (p) { return { position: p, dot: "" }; });
      zeichneBesichtigung();
      if (lokal && lokal.offen) speichern();
    });
  }

  function zeichneBesichtigung() {
    var k = B.katalog, d = B.daten, i = B.info, fz = d.fahrzeug, fertig = i.status === "abgeschlossen" || i.status === "abgebrochen";
    inhalt.classList.add("mit-leiste");
    inhalt.innerHTML =
      "<h1>" + esc(B.basis.fahrzeug) + "</h1>" +
      '<p class="leise">' + esc(datum(i.termin)) + (i.adresse ? " · " + esc(i.adresse) : "") + (i.zustaendig ? " · " + esc(i.zustaendig.name) : "") + "</p>" +
      '<div class="reihe">' + (i.karte ? '<a class="knopf klein" href="' + link(i.karte) + '" target="_blank" rel="noopener">Navigation</a>' : "") +
      (B.basis.url ? '<a class="knopf klein" href="' + link(B.basis.url) + '" target="_blank" rel="noopener">Inserat</a>' : '<span class="tag">Verkaufsanfrage ' + esc(B.basis.referenz || "") + "</span>") +
      (fertig ? '<a class="knopf klein primaer" href="/protokoll/' + B.id + '" target="_blank">Protokoll</a><a class="knopf klein" href="/ankaeufe">Ankäufe</a>' : "") + "</div>" +
      '<p class="hinweis info">Vorbehaltliches Angebot ' + eur(B.basis.angebot) + " · Max-EK " + eur(B.basis.max_ek) + " · Wunschpreis " + eur(B.basis.preis) + "</p>" +
      (fertig ? '<p class="hinweis ok">Diese Besichtigung ist abgeschlossen.</p>' : "") +

      "<h2>Fahrzeugdaten</h2>" +
      '<label>FIN<input data-fz="fin" value="' + esc(fz.fin) + '" autocapitalize="characters" maxlength="17"></label>' +
      '<div class="zwei"><label>Kennzeichen<input data-fz="kennzeichen" value="' + esc(fz.kennzeichen) + '" autocapitalize="characters"></label>' +
      '<label>km-Stand abgelesen<input data-feld="km_abgelesen" inputmode="numeric" value="' + esc(d.km_abgelesen) + '" placeholder="Anzeige: ' + tsd(B.basis.km_anzeige) + '"></label></div>' +
      '<div class="zwei"><label>HU bis (MM/JJJJ)<input data-fz="hu_bis" value="' + esc(fz.hu_bis) + '" inputmode="numeric"></label>' +
      '<label>Gasprüfung bis<input data-fz="gas_bis" value="' + esc(fz.gas_bis) + '" inputmode="numeric"></label></div>' +
      '<label>Anzahl Schlüssel<input data-fz="schluessel" value="' + esc(fz.schluessel) + '" inputmode="numeric"></label>' +

      "<h2>Prüfpunkte</h2>" + k.pruefpunkte.map(function (p) {
        if (p.messung) return "";
        return '<label class="check"><input type="checkbox" data-pp="' + esc(p.key) + '"' + (d.pruefpunkte[p.key] ? " checked" : "") + "><span>" + esc(p.name) +
          (p.pflicht ? "<small>Pflicht</small>" : "") + "</span></label>";
      }).join("") +

      "<h2>Feuchtigkeit (%)</h2><p class=\"leise\">Mind. " + k.messungen.feuchtigkeit.mindest_messpunkte + " Messpunkte: Ecken, Fenster, Dachluken, Heck, Bad, Bug.</p>" +
      '<div id="feuchte"></div><button class="knopf voll" data-aktion="messpunkt">+ Messpunkt</button>' +

      "<h2>Reifen (DOT, z. B. 2318)</h2>" + '<div id="reifen"></div><button class="knopf voll" data-aktion="reifen">+ Reifen (z. B. Reserve)</button>' +

      "<h2>Mängel</h2>" + '<div id="maengel"></div>' +
      k.kategorien.map(function (kat) {
        return '<details class="kat"><summary>' + esc(kat.name) + '</summary><div class="inhalt">' + kat.maengel.map(function (m) {
          var preis = m.stufen ? eur(m.stufen.leicht) + "–" + eur(m.stufen.schwer) : m.betrag ? eur(m.betrag) : m.prozent ? (m.prozent * 100).toLocaleString("de-DE") + " %" : "frei";
          return '<div class="mangel-wahl"><span>' + esc(m.name) + '<br><small class="leise">' + preis + '</small></span><button class="knopf klein" data-neu-mangel="' + esc(m.key) + '">+</button></div>';
        }).join("") + "</div></details>";
      }).join("") +

      "<h2>Weitere Fotos</h2>" + '<label class="knopf voll">📷 Foto aufnehmen<input type="file" accept="image/*" capture="environment" data-foto="" hidden></label>' +
      '<div class="fotos" data-fotos=""></div>' +

      "<h2>Anpassung</h2><p class=\"leise\">Zuschlag (+) oder Nachlass (−) mit Begründung, z. B. neue Batterie vorhanden.</p>" +
      '<div class="zwei"><label>Betrag (€)<input data-anp="betrag" inputmode="decimal" value="' + esc(d.anpassung.betrag) + '"></label>' +
      '<label>Grund<input data-anp="grund" value="' + esc(d.anpassung.grund) + '"></label></div>' +

      '<h2>Ergebnis</h2><div id="ergebnis"></div>' +
      (fertig ? "" : '<a class="knopf primaer voll" style="margin-top:12px" href="#/besichtigung/' + B.id + '/abschluss">Besichtigung abschließen →</a>') +
      '<div class="leiste" id="leiste"></div>';
    zeichneFeuchte(); zeichneReifen(); zeichneMaengel(); zeigeFotos(); rechne();
    if (fertig) inhalt.querySelectorAll("input,select,textarea,button[data-aktion],button[data-neu-mangel]").forEach(function (el) { el.disabled = true; });
  }

  function stufeVon(wert) {
    var f = B.katalog.messungen.feuchtigkeit, x = Number(String(wert).replace(",", "."));
    if (String(wert).trim() === "" || isNaN(x)) return "";
    for (var i = 0; i < f.stufen.length; i++) if (x <= f.stufen[i].bis) return f.stufen[i].stufe;
    return "schwer";
  }
  function zeichneFeuchte() {
    document.getElementById("feuchte").innerHTML = B.daten.messungen.feuchtigkeit.map(function (p, i) {
      return '<div class="mess"><input data-feuchte="' + i + '" data-teil="bereich" list="bereiche" placeholder="Bereich, z. B. Heck links" value="' + esc(p.bereich) + '">' +
        '<input data-feuchte="' + i + '" data-teil="wert" inputmode="decimal" placeholder="%" class="stufe-' + stufeVon(p.wert) + '" value="' + esc(p.wert) + '">' +
        '<button class="x" data-weg-feuchte="' + i + '" aria-label="Messpunkt löschen">×</button></div>';
    }).join("") + '<datalist id="bereiche"><option>Heck links<option>Heck rechts<option>Bug/Alkoven<option>Dachluke vorne<option>Dachluke hinten<option>Bad<option>Fenster Sitzgruppe<option>Eingangstür<option>Garage</datalist>';
  }
  function reifenStufe(dot) {
    var alter = window.Besichtigung.dotAlterJahre(dot, heuteIso()), max = B.katalog.messungen.reifen.max_alter_jahre;
    return String(dot || "").trim() ? (alter === null ? "mittel" : alter > max ? "schwer" : "ok") : "";
  }
  function zeichneReifen() {
    document.getElementById("reifen").innerHTML = B.daten.messungen.reifen.map(function (r, i) {
      var stufe = reifenStufe(r.dot);
      return '<div class="mess"><input data-reifen="' + i + '" data-teil="position" value="' + esc(r.position) + '">' +
        '<input data-reifen="' + i + '" data-teil="dot" inputmode="numeric" maxlength="4" placeholder="DOT" class="stufe-' + stufe + '" value="' + esc(r.dot) + '">' +
        '<button class="x" data-weg-reifen="' + i + '" aria-label="Reifen löschen">×</button></div>';
    }).join("");
  }
  function mangelDef(key) { return window.Besichtigung.mangelIndex(B.katalog)[key]; }
  function zeichneMaengel() {
    document.getElementById("maengel").innerHTML = B.daten.maengel.length ? B.daten.maengel.map(function (m, i) {
      var k = mangelDef(m.key) || { name: m.key };
      var ko = k.ko || (k.ko_ab && m.stufe && ["leicht", "mittel", "schwer"].indexOf(m.stufe) >= ["leicht", "mittel", "schwer"].indexOf(k.ko_ab));
      return '<div class="mangel' + (ko ? " ko" : "") + '"><div class="zeile"><b>' + esc(k.frei ? (m.name || k.name) : k.name) + '</b><button class="x knopf klein" data-weg-mangel="' + i + '">Entfernen</button></div>' +
        (k.frei ? '<label>Bezeichnung<input data-mangel="' + i + '" data-teil="name" value="' + esc(m.name) + '"></label>' : "") +
        (k.stufen ? '<div class="segment">' + ["leicht", "mittel", "schwer"].map(function (s) {
          return '<button data-mangel-stufe="' + i + '" data-stufe="' + s + '" class="' + (m.stufe === s ? "an" : "") + '">' + s + "<br><small>" + eur(k.stufen[s]) + "</small></button>";
        }).join("") + "</div>" : "") +
        '<div class="zwei"><label>' + (k.frei ? "Betrag (€)" : "Betrag abweichend (€)") + '<input data-mangel="' + i + '" data-teil="betrag" inputmode="decimal" value="' + esc(m.betrag) + '"></label>' +
        '<label>Notiz<input data-mangel="' + i + '" data-teil="notiz" value="' + esc(m.notiz) + '"></label></div>' +
        '<label class="knopf klein" style="margin-top:8px">📷 Foto<input type="file" accept="image/*" capture="environment" data-foto="' + esc(m.key) + '" hidden></label>' +
        '<div class="fotos" data-fotos="' + esc(m.key) + '"></div></div>';
    }).join("") : '<p class="leise">Noch keine Mängel erfasst – unten aus dem Katalog hinzufügen.</p>';
    zeigeFotos();
  }
  function zeigeFotos() {
    if (!B || !document.getElementById("maengel")) return;
    fotosWartend().then(function (wartend) {
      inhalt.querySelectorAll("[data-fotos]").forEach(function (box) {
        var key = box.getAttribute("data-fotos");
        var srv = B.fotos.filter(function (f) { return (f.mangel_key || "") === key; }).map(function (f) {
          return '<a href="/fotos/' + B.id + "/" + esc(f.datei) + '" target="_blank"><img src="/fotos/' + B.id + "/" + esc(f.datei) + '" alt=""></a>';
        });
        var lok = wartend.filter(function (f) { return String(f.bid) === String(B.id) && (f.mangel_key || "") === key; }).map(function (f) {
          return '<img class="wartet" src="' + f.bild + '" alt="wartet auf Upload">';
        });
        box.innerHTML = srv.concat(lok).join("");
      });
    });
  }

  function rechne() {
    var e = window.Besichtigung.berechne(B.katalog, B.daten, B.basis, heuteIso());
    B.ergebnis = e;
    document.getElementById("leiste").innerHTML = '<span><span class="klein">Abzug vom EK</span><br><b>' + eur(e.ek_abzug) + "</b></span>" +
      '<span style="text-align:right"><span class="klein">Vorschlag</span><br><b>' + eur(e.vorschlag) + "</b></span>";
    document.getElementById("ergebnis").innerHTML =
      (e.ko.length ? '<p class="hinweis warn"><b>Ankauf nicht empfohlen:</b> ' + e.ko.map(esc).join(", ") + "</p>" : "") +
      (e.fehlende_pflicht.length ? '<p class="hinweis info"><b>Noch offen:</b><br>' + e.fehlende_pflicht.map(esc).join("<br>") + "</p>" : '<p class="hinweis ok">Alle Pflichtpunkte erledigt.</p>') +
      (e.hinweise.length ? '<p class="hinweis info">' + e.hinweise.map(esc).join("<br>") + "</p>" : "") +
      "<table>" + e.posten.map(function (p) { return "<tr><td>" + esc(p.name) + (p.stufe ? " (" + esc(p.stufe) + ")" : "") + "</td><td>" + eur(p.betrag) + "</td></tr>"; }).join("") +
      "<tr><td><b>Summe Mängel</b></td><td><b>" + eur(e.summe_maengel) + "</b></td></tr>" +
      "<tr><td>− bereits einkalkuliertes Reparaturrisiko</td><td>" + eur(e.risiko_gutschrift) + "</td></tr>" +
      (e.anpassung ? "<tr><td>Anpassung" + (B.daten.anpassung.grund ? " (" + esc(B.daten.anpassung.grund) + ")" : "") + "</td><td>" + eur(e.anpassung) + "</td></tr>" : "") +
      "<tr><td>Netto-Abzug</td><td>" + eur(e.netto_abzug) + "</td></tr>" +
      "<tr><td>× " + String(e.ek_faktor).replace(".", ",") + (e.ek_faktor > 1 ? " (§25a, Marge bleibt gleich)" : "") + " = Abzug vom EK</td><td>" + eur(e.ek_abzug) + "</td></tr>" +
      "<tr><td>Vorbehaltliches Angebot</td><td>" + eur(e.angebot) + "</td></tr>" +
      "<tr><td>Max-EK nach Mängeln</td><td>" + eur(e.max_ek_neu) + "</td></tr>" +
      '<tr class="summe"><td>Endpreis-Vorschlag</td><td>' + eur(e.vorschlag) + "</td></tr></table>";
  }

  function geaendert() {
    rechne();
    entwurfSchreiben(B.id, { daten: B.daten, offen: true, zeit: Date.now() });
    syncAnzeige();
    clearTimeout(speicherUhr);
    speicherUhr = setTimeout(speichern, 1200);
  }
  function speichereServer(bid) {
    var e = entwurfLesen(bid);
    if (!e || !e.offen) return Promise.resolve();
    return api("/api/besichtigung/" + bid + "/speichern", { daten: e.daten }).then(function (antwort) {
      var aktuell = entwurfLesen(bid);
      if (aktuell && aktuell.zeit === e.zeit) entwurfSchreiben(bid, { daten: e.daten, offen: false, zeit: e.zeit });
      if (B && String(B.id) === String(bid)) B.version = antwort.version;
      return antwort;
    });
  }
  function speichern() {
    clearTimeout(speicherUhr);
    if (!B) return Promise.resolve();
    if (!navigator.onLine) { syncAnzeige(); return Promise.resolve(); }
    return speichereServer(B.id).then(syncAnzeige, function (e) { if (e.status === 409) toast(e.message); syncAnzeige(); });
  }

  function bildVerkleinern(datei) {
    return new Promise(function (ok, fehler) {
      var url = URL.createObjectURL(datei), img = new Image();
      img.onload = function () {
        var max = 1600, s = Math.min(1, max / Math.max(img.width, img.height)), c = document.createElement("canvas");
        c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        ok(c.toDataURL("image/jpeg", 0.8));
      };
      img.onerror = function () { URL.revokeObjectURL(url); fehler(new Error("Bild nicht lesbar")); };
      img.src = url;
    });
  }
  function fotoHinzu(input) {
    var datei = input.files && input.files[0], key = input.getAttribute("data-foto") || null;
    if (!datei) return;
    bildVerkleinern(datei).then(function (bild) {
      return fotoMerken({ bid: B.id, mangel_key: key, bild: bild }).then(function () {
        zeigeFotos(); syncAnzeige(); toast("Foto gespeichert"); return synchronisiere();
      });
    }).catch(function (e) { toast(e.message); });
    input.value = "";
  }

  // ---------------------------------------------------------------- Abschluss
  function abschluss(id) {
    return besichtigung(id).then(function () {
      var e = B.ergebnis, d = B.daten;
      inhalt.classList.remove("mit-leiste");
      inhalt.innerHTML = "<h1>Abschluss</h1><p class=\"leise\">" + esc(B.basis.fahrzeug) + "</p>" +
        (e.ko.length ? '<p class="hinweis warn"><b>Ankauf nicht empfohlen:</b> ' + e.ko.map(esc).join(", ") + "</p>" : "") +
        '<div class="karte"><table><tr><td>Abzug vom EK</td><td>' + eur(e.ek_abzug) + '</td></tr><tr class="summe"><td>Endpreis-Vorschlag</td><td>' + eur(e.vorschlag) + "</td></tr></table></div>" +
        '<label>Ergebnis<select id="a-entscheidung"><option value="gekauft">Gekauft – Protokoll unterschreiben</option><option value="offen">Noch offen / Bedenkzeit</option>' +
        '<option value="abgelehnt">Kein Kauf</option><option value="abgebrochen">Besichtigung abgebrochen</option></select></label>' +
        '<div id="a-kauf"><label>Vereinbarter Kaufpreis (€)<input id="a-preis" inputmode="numeric" value="' + e.vorschlag + '"></label>' +
        "<h2>Verkäufer</h2>" +
        '<label>Name<input id="a-v-name" autocomplete="off"></label><label>Anschrift<input id="a-v-anschrift" autocomplete="off"></label>' +
        '<label>Telefon<input id="a-v-tel" inputmode="tel" autocomplete="off"></label>' +
        "<h2>Erklärungen des Verkäufers</h2>" +
        '<label class="check"><input type="checkbox" id="a-eigentum"><span>Verkäufer ist Eigentümer, das Fahrzeug ist frei von Rechten Dritter (keine Finanzierung, kein Pfand).</span></label>' +
        '<label>Unfallschäden<select id="a-unfall"><option value="keine bekannt">keine bekannt</option><option value="ja">ja (siehe Bemerkung)</option></select></label>' +
        '<label>Bemerkung<textarea id="a-bemerkung" style="min-height:70px"></textarea></label>' +
        (e.vollstaendig ? "" : '<p class="hinweis info">Pflichtpunkte fehlen:<br>' + e.fehlende_pflicht.map(esc).join("<br>") + '</p><label>Begründung, warum trotzdem gekauft wird<input id="a-begruendung"></label>') +
        "<h2>Unterschriften</h2>" +
        '<label>Verkäufer<canvas class="unterschrift" id="u-verkaeufer"></canvas></label><button class="knopf klein" data-leeren="u-verkaeufer">Löschen</button>' +
        '<label>Ankäufer (' + esc(S.ich.firma.firma) + ')<canvas class="unterschrift" id="u-ankaeufer"></canvas></label><button class="knopf klein" data-leeren="u-ankaeufer">Löschen</button></div>' +
        '<p id="a-fehler" class="fehler"></p><button class="knopf primaer voll" data-aktion="abschliessen">Abschließen</button>' +
        '<p class="leise">Das Protokoll ist ein Muster – vor dem ersten Einsatz rechtlich prüfen lassen.</p>';
      document.getElementById("a-entscheidung").onchange = function (ev) { document.getElementById("a-kauf").hidden = ev.target.value !== "gekauft"; };
      var vk = B.basis.verkaeufer;          // Verkaufsanfrage: Verkäufer ist bekannt – vorbelegen, vor Ort prüfen
      if (vk) { document.getElementById("a-v-name").value = vk.name || ""; document.getElementById("a-v-tel").value = vk.telefon || ""; }
      ["u-verkaeufer", "u-ankaeufer"].forEach(unterschriftFeld);
    });
  }
  function unterschriftFeld(id) {
    var c = document.getElementById(id), ctx = c.getContext("2d"), zeichnet = false, r = window.devicePixelRatio || 1;
    c.width = c.offsetWidth * r; c.height = c.offsetHeight * r;
    ctx.scale(r, r); ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.strokeStyle = "#111";
    c.dataset.leer = "1";
    function pos(e) { var b = c.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; }
    c.addEventListener("pointerdown", function (e) { zeichnet = true; c.setPointerCapture(e.pointerId); var p = pos(e); ctx.beginPath(); ctx.moveTo(p[0], p[1]); });
    c.addEventListener("pointermove", function (e) { if (!zeichnet) return; var p = pos(e); ctx.lineTo(p[0], p[1]); ctx.stroke(); c.dataset.leer = "0"; });
    c.addEventListener("pointerup", function () { zeichnet = false; });
  }
  function abschliessen() {
    var ent = document.getElementById("a-entscheidung").value, fehler = document.getElementById("a-fehler");
    function wert(id) { var el = document.getElementById(id); return el ? el.value.trim() : ""; }
    function bild(id) { var c = document.getElementById(id); return c.dataset.leer === "1" ? null : c.toDataURL("image/png"); }
    var daten = { entscheidung: ent };
    if (ent === "gekauft") {
      daten.endpreis = parseInt(wert("a-preis").replace(/\D/g, ""), 10) || 0;
      daten.verkaeufer = { name: wert("a-v-name"), anschrift: wert("a-v-anschrift"), telefon: wert("a-v-tel"),
                           eigentum_frei: document.getElementById("a-eigentum").checked, unfall: wert("a-unfall") };
      daten.bemerkung = wert("a-bemerkung"); daten.begruendung_unvollstaendig = wert("a-begruendung");
      daten.unterschrift_verkaeufer = bild("u-verkaeufer"); daten.unterschrift_ankaeufer = bild("u-ankaeufer");
      if (!daten.verkaeufer.name) { fehler.textContent = "Name des Verkäufers fehlt"; return; }
      if (!daten.verkaeufer.eigentum_frei) { fehler.textContent = "Erklärung zu Eigentum/Rechten Dritter bestätigen"; return; }
    }
    if (!navigator.onLine) { fehler.textContent = "Für den Abschluss wird Netz gebraucht – alle Eingaben sind lokal gesichert."; return; }
    entwurfSchreiben(B.id, { daten: B.daten, offen: true, zeit: Date.now() });
    speichereServer(B.id).then(function () { return api("/api/besichtigung/" + B.id + "/abschluss", daten); }).then(function (r) {
      // kein automatisches Fenster (Handy-Browser blockieren das) – Protokoll-Knopf steht in der Besichtigung
      toast(r && r.ankauf ? "Abgeschlossen – Ankaufsvorgang angelegt (Ankäufe)" : "Abgeschlossen – Protokoll oben öffnen"); location.hash = "#/besichtigung/" + B.id;
    }, function (e) { fehler.textContent = e.message; });
  }

  // ---------------------------------------------------------------- Ereignisse
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-aktion],[data-status],[data-neu-mangel],[data-weg-mangel],[data-mangel-stufe],[data-weg-feuchte],[data-weg-reifen],[data-leeren]");
    if (!t) return;
    var a = t.getAttribute("data-aktion"), id = inhalt.dataset.id;
    if (a) e.preventDefault();
    if (a === "anschreiben" || a === "nachfassen") {
      // Kopieren sofort (braucht die Berührung), die Anzeige erst nach OK des Servers: bei 409 hält ein Kollege das Fahrzeug.
      // Gilt erst nach „gesendet ✓“ als kontaktiert (ADR-012).
      var text = document.getElementById(a === "anschreiben" ? "brief" : "nf").value, ok = kopiere(text), fenster = null, url = inhalt.dataset.url;
      try { fenster = window.open("", "_blank"); if (fenster) fenster.opener = null; } catch (x) { fenster = null; }
      var p = a === "anschreiben"
        ? api("/api/status", { id: id, status: "vorbereitet", text: text, betrag: parseInt(inhalt.dataset.erst, 10) || null })
        : api("/api/nachgefasst", { id: id, text: text, betrag: parseInt(inhalt.dataset.nfbetrag, 10) || null });
      p.then(function () {
        if (/^https?:\/\//i.test(url || "")) { if (fenster && !fenster.closed) fenster.location.href = url; else window.open(url, "_blank", "noopener"); }
        else if (fenster) fenster.close();
        toast(ok ? "Text kopiert ✓ – in " + (inhalt.dataset.quelle === "mobile.de" ? "mobile.de im „E-Mail“/„Nachricht“-Formular" : inhalt.dataset.quelle === "kleinanzeigen" ? "Kleinanzeigen" : "der Anzeige") + " einfügen, senden, dann „gesendet ✓“" : "Bitte Text markieren und kopieren");
        fahrzeug(id);
      }, function (err) { if (fenster) fenster.close(); teamFehler(err, id); });
    } else if (a === "gesendet") {
      api("/api/status", { id: id, status: "kontaktiert" }).then(function () { toast("Als gesendet gespeichert ✓"); fahrzeug(id); }, function (err) { teamFehler(err, id); });
    } else if (a === "uebernehmen" || a === "erzwingen" || a === "abgeben") {
      if (a === "erzwingen" && !confirm("Übernahme erzwingen? Der Kollege verliert das Fahrzeug.")) return;
      api("/api/bearbeitung/" + encodeURIComponent(id) + "/" + (a === "abgeben" ? "abgeben" : "uebernehmen"), a === "erzwingen" ? { erzwingen: true } : {})
        .then(function () { toast(a === "abgeben" ? "Abgegeben – wieder frei" : "Übernommen ✓"); fahrzeug(id); }, function (err) { teamFehler(err, id); });
    } else if (a === "wer") {
      S.wer = t.getAttribute("data-wer");
      var teil = location.hash.replace(/^#\/?/, "").split("/");
      liste(teil[0] === "liste" ? (teil[1] || "bereit") : "bereit", (document.getElementById("suche") || {}).value);
    } else if (t.hasAttribute("data-status")) {
      api("/api/status", { id: id, status: t.getAttribute("data-status") }).then(function () { toast("Status gespeichert"); fahrzeug(id); },
                                                                           function (err) { teamFehler(err, id); });
    } else if (a === "planen") {
      var termin = document.getElementById("b-termin").value;
      var planen = function (marktwert) {
        return api("/api/besichtigung", { anzeige_id: id, termin: termin || null, adresse: document.getElementById("b-adresse").value,
                                          zustaendig_id: document.getElementById("b-wer").value || null, marktwert: marktwert });
      };
      var geplant = function (b) { toast("Besichtigung geplant"); fahrzeug(id); if (b.zustaendig && b.zustaendig.id !== S.ich.nutzer.id && b.whatsapp) window.open(b.whatsapp, "_blank", "noopener"); };
      planen(undefined).then(geplant, function (err) {
        if (err.grund !== "marktwert") return toast(err.message);
        // P1-12: Erstzulassung fehlt – ohne eigenen Marktwert keine Beträge
        var eingabe = prompt(err.message + "\n\nMarktwert in €:");
        var mw = parseInt(String(eingabe || "").replace(/[^0-9]/g, ""), 10);
        if (!mw) return;
        planen(mw).then(geplant, function (e2) { toast(e2.message); });
      });
    } else if (a === "suchen") {
      api("/api/suchlauf", {}).then(function () { toast("Suche gestartet – dauert einige Minuten"); });
    } else if (a === "abmelden") {
      api("/api/logout", {}).then(function () { if (window.caches) caches.keys().then(function (n) { n.forEach(function (x) { caches.delete(x); }); }); location.href = "/login"; });
    } else if (a === "messpunkt") {
      B.daten.messungen.feuchtigkeit.push({ bereich: "", wert: "" }); zeichneFeuchte(); geaendert();
      var felder = inhalt.querySelectorAll("[data-feuchte][data-teil=bereich]"); felder[felder.length - 1].focus();
    } else if (a === "reifen") {
      B.daten.messungen.reifen.push({ position: "Reserve", dot: "" }); zeichneReifen(); geaendert();
    } else if (t.hasAttribute("data-neu-mangel")) {
      B.daten.maengel.push({ key: t.getAttribute("data-neu-mangel"), stufe: null, betrag: "", notiz: "" });
      zeichneMaengel(); geaendert(); document.getElementById("maengel").scrollIntoView({ behavior: "smooth" });
      toast("Mangel hinzugefügt – Schweregrad wählen");
    } else if (t.hasAttribute("data-weg-mangel")) {
      if (confirm("Mangel entfernen?")) { B.daten.maengel.splice(+t.getAttribute("data-weg-mangel"), 1); zeichneMaengel(); geaendert(); }
    } else if (t.hasAttribute("data-mangel-stufe")) {
      B.daten.maengel[+t.getAttribute("data-mangel-stufe")].stufe = t.getAttribute("data-stufe"); zeichneMaengel(); geaendert();
    } else if (t.hasAttribute("data-weg-feuchte")) {
      B.daten.messungen.feuchtigkeit.splice(+t.getAttribute("data-weg-feuchte"), 1); zeichneFeuchte(); geaendert();
    } else if (t.hasAttribute("data-weg-reifen")) {
      B.daten.messungen.reifen.splice(+t.getAttribute("data-weg-reifen"), 1); zeichneReifen(); geaendert();
    } else if (t.hasAttribute("data-leeren")) {
      var c = document.getElementById(t.getAttribute("data-leeren"));
      c.getContext("2d").clearRect(0, 0, c.width, c.height); c.dataset.leer = "1";
    } else if (a === "abschliessen") {
      abschliessen();
    }
  });
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!B || !inhalt.contains(t)) return;
    var d = B.daten;
    if (t.hasAttribute("data-fz")) d.fahrzeug[t.getAttribute("data-fz")] = t.value;
    else if (t.getAttribute("data-feld") === "km_abgelesen") d.km_abgelesen = t.value.replace(/\D/g, "");
    else if (t.hasAttribute("data-anp")) d.anpassung[t.getAttribute("data-anp")] = t.value;
    else if (t.hasAttribute("data-feuchte")) {
      d.messungen.feuchtigkeit[+t.getAttribute("data-feuchte")][t.getAttribute("data-teil")] = t.value;
      if (t.getAttribute("data-teil") === "wert") t.className = "stufe-" + stufeVon(t.value);
    } else if (t.hasAttribute("data-reifen")) {
      d.messungen.reifen[+t.getAttribute("data-reifen")][t.getAttribute("data-teil")] = t.value;
      if (t.getAttribute("data-teil") === "dot") t.className = "stufe-" + reifenStufe(t.value);   // nicht neu zeichnen: Fokus bleibt
    } else if (t.hasAttribute("data-mangel")) {
      d.maengel[+t.getAttribute("data-mangel")][t.getAttribute("data-teil")] = t.value;
    } else return;
    geaendert();
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!B) return;
    if (t.hasAttribute("data-pp")) { B.daten.pruefpunkte[t.getAttribute("data-pp")] = t.checked; geaendert(); }
    else if (t.hasAttribute("data-foto")) fotoHinzu(t);
  });

  // ---------------------------------------------------------------- Router
  function route() {
    var teile = (location.hash.replace(/^#\/?/, "") || "heute").split("/");
    inhalt.classList.remove("mit-leiste"); inhalt.removeAttribute("data-id");
    if (teile[0] !== "besichtigung") { if (B) speichern(); B = null; }
    document.querySelectorAll(".navi a").forEach(function (a) {
      var n = a.getAttribute("data-navi");
      a.classList.toggle("an", n === teile[0] || (n === "arbeit" && teile[0] === "liste" && teile[1] === "arbeit") ||
                               (n === "liste" && teile[0] === "liste" && teile[1] !== "arbeit"));
    });
    var seite;
    if (teile[0] === "liste") seite = liste(teile[1] || "bereit");
    else if (teile[0] === "fahrzeug") seite = fahrzeug(decodeURIComponent(teile[1]));
    else if (teile[0] === "besichtigung" && teile[2] === "abschluss") seite = abschluss(teile[1]);
    else if (teile[0] === "besichtigung") seite = besichtigung(teile[1]);
    else if (teile[0] === "termine") seite = termine();
    else seite = heute();
    window.scrollTo(0, 0);
    seite.catch(function (e) {
      if (e.message !== "Bitte anmelden") inhalt.innerHTML = '<p class="hinweis warn">' + esc(e.message || "Fehler") + (navigator.onLine ? "" : " – offline, bitte später erneut versuchen") + "</p>";
    });
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", function () { if (document.hidden && B) speichern(); });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(function () {});
  ladeIch().then(function () { route(); syncAnzeige(); synchronisiere(); }, function (e) {
    inhalt.innerHTML = '<p class="hinweis warn">' + esc(e.message) + "</p>";
  });
})();
