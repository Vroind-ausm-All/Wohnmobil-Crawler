/* Dubletten (P3-02b) – gemeinsam für Desktop-App (Vorschläge, Entscheiden, Aufheben) und Handy-App (nur Anzeige).
   Alles Fremde (Titel, Orte, Namen, Gründe) wird nur per textContent ausgegeben, Links nur bei http(s). Nichts wird im Browser gespeichert.
   Entschieden wird nie automatisch: jede Aktion verlangt eine ausdrückliche Bestätigung, der Server prüft Rolle und Stand (403/409). */
(function () {
  "use strict";
  var PLATTFORM = { kleinanzeigen: "Kleinanzeigen", "mobile.de": "mobile.de" };
  var STUFE = { hoch: "Übereinstimmung: hoch", mittel: "Übereinstimmung: mittel" };
  var FOLGE_GLEICH = "Gleiches Fahrzeug: Beide Inserate gelten als ein Fahrzeug – es wird nicht doppelt angeschrieben und zählt nur einmal in der Vergleichsbasis. " +
                     "Der Inhaber kann das wieder aufheben.";
  var FOLGE_VERSCHIEDEN = "Verschieden: Die beiden Inserate werden nie wieder als Dublette vorgeschlagen und nicht zusammengeführt. " +
                          "Nur der Inhaber kann diese Sperre später aufheben.";
  var FOLGE_AUFHEBEN = "Aufheben: Die Entscheidung wird zurückgenommen. Bei „gleiches Fahrzeug“ werden die Inserate wieder getrennt; " +
                       "bei „verschieden“ wird die Sperre für dieses Paar aufgehoben und es kann wieder vorgeschlagen werden.";

  function el(tag, attr, text) {
    var e = document.createElement(tag);
    Object.keys(attr || {}).forEach(function (k) { e.setAttribute(k, attr[k]); });
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function httpLink(u) { return /^https?:\/\//i.test(String(u || "")); }
  function plattform(p) { return PLATTFORM[p] || String(p || "?"); }
  function eur(x) { return x === null || x === undefined || x === "" ? "Preis ?" : Math.round(x).toLocaleString("de-DE") + " €"; }
  function zeit(iso) { return String(iso || "").slice(0, 16).replace("T", " "); }
  function externLink(url, text) {
    if (!httpLink(url)) return null;
    var a = el("a", { href: url, target: "_blank", rel: "noopener noreferrer", "class": "dub-link" }, text || "Anzeige öffnen ↗");
    return a;
  }
  function fehlerText(e) {
    if (e && e.status === 403 && e.grund === "csrf") return "Sitzung abgelaufen – bitte die Seite neu laden (F5).";
    if (e && e.status === 403) return "Nicht erlaubt: " + e.message;
    if (e && e.status === 409) return "Nicht möglich, weil sich der Stand geändert hat: " + e.message;
    return (e && e.message) || "Unbekannter Fehler";
  }

  // ------------------------------------------------------------ Gruppe „Gleiches Fahrzeug“ (Fahrzeugfenster, Handy)
  // daten: Antwort von GET /api/dubletten/entscheidungen bzw. der Entscheidungs-Aktionen.
  // opt: aktuell (Anzeigen-ID, wird ausgeblendet), statusText(status), verlauf (bool), aufheben(entscheidung) (nur wenn erlaubt), href(anzeigenId) | oeffnen(anzeigenId)
  function gruppeBox(daten, opt) {
    opt = opt || {};
    var andere = (daten.gruppe || []).filter(function (m) { return m.anzeigen_id !== opt.aktuell; });
    var verlauf = opt.verlauf ? (daten.entscheidungen || []) : [];
    if (!andere.length && !verlauf.length) return null;
    var box = el("section", { "class": "dub-box", "aria-label": "Dubletten" });
    box.appendChild(el("h4", {}, andere.length ? "Gleiches Fahrzeug" : "Dublettenentscheidungen"));
    if (andere.length) {
      var status = (opt.statusText ? opt.statusText(daten.fahrzeug_status) : daten.fahrzeug_status) || "–";
      box.appendChild(el("p", { "class": "dub-status" }, "Gleiches Fahrzeug wie " + andere.length + (andere.length === 1 ? " weiteres Inserat" : " weitere Inserate") +
                                                         " · Fahrzeugstatus (höchster aller Inserate): " + status));
      var ul = el("ul", { "class": "dub-liste" });
      andere.forEach(function (m) {
        var li = el("li");
        li.appendChild(el("span", { "class": "dub-titel" }, m.titel || "(ohne Titel)"));
        li.appendChild(el("span", { "class": "dub-meta" }, plattform(m.plattform) + " · " + eur(m.preis)));
        var ziel = null;
        if (opt.href) ziel = el("a", { href: opt.href(m.anzeigen_id), "class": "dub-link" }, "Fahrzeug ansehen");
        else if (opt.oeffnen) { ziel = el("button", { type: "button", "class": "dub-knopf klein", "data-dub-oeffnen": m.anzeigen_id }, "Details");
          ziel.onclick = function () { opt.oeffnen(m.anzeigen_id); }; }
        if (ziel) li.appendChild(ziel);
        var ext = externLink(m.url);
        if (ext) li.appendChild(ext);
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    if (verlauf.length) {
      box.appendChild(el("h5", {}, "Entscheidungsverlauf"));
      var ol = el("ol", { "class": "dub-verlauf" });
      verlauf.forEach(function (e) {
        var gilt = e.status === "gilt";
        var li = el("li", { "data-dub-entscheidung": String(e.id) });
        var kopf = (e.entscheidung === "gleich" ? "Gleiches Fahrzeug" : "Verschieden") + ": " + e.anzeige_a + " ↔ " + e.anzeige_b;
        li.appendChild(el("span", { "class": "dub-titel" }, kopf));
        li.appendChild(el("span", { "class": "dub-meta" }, (gilt ? "gilt" : "aufgehoben") + " · " + (e.nutzer || "unbekannt") + " · " + zeit(e.zeitpunkt)));
        if (!gilt && e.aufgehoben_am) li.appendChild(el("span", { "class": "dub-meta" }, "aufgehoben von " + (e.aufgehoben_von_name || "unbekannt") + " · " + zeit(e.aufgehoben_am)));
        if (gilt && daten.darf_aufheben && opt.aufheben) {
          if (e.aufhebbar) {
            var b = el("button", { type: "button", "class": "dub-knopf klein", "data-dub-aufheben": String(e.id) }, "Aufheben");
            b.onclick = function () { opt.aufheben(e, b); };
            li.appendChild(b);
          } else {
            li.appendChild(el("span", { "class": "dub-meta dub-sperr" }, "Erst die spätere Zusammenführung (Entscheidung " + e.blockiert_durch + ") aufheben."));
          }
        }
        ol.appendChild(li);
      });
      box.appendChild(ol);
    }
    return box;
  }

  // ------------------------------------------------------------ Vorschlagsliste (nur Desktop)
  // opt: get(url), post(url, daten) → Promise (Fehler mit status/grund/message), statusText, bestaetigung(text) → bool (Standard: confirm),
  //      meldung(text, warnung), nachAktion(antwort), oeffnen(anzeigenId)
  function vorschlaege(wurzel, opt) {
    wurzel.textContent = "";
    wurzel.classList.add("dub");
    var kopf = el("div", { "class": "dub-kopf" });
    var titel = el("h3", { id: "dub-titel" }, "Dublettenvorschläge");
    var neuLaden = el("button", { type: "button", "class": "dub-knopf", id: "dub-neu" }, "Neu prüfen");
    kopf.appendChild(titel); kopf.appendChild(neuLaden);
    var info = el("p", { "class": "dub-info", "aria-live": "polite" });
    var warnBox = el("div", { "class": "dub-warnung", role: "alert", hidden: "" });
    var fehlerBox = el("p", { "class": "dub-fehler", role: "alert", hidden: "" });
    var liste = el("div", { "class": "dub-karten" });
    [kopf, el("p", { "class": "dub-leise" }, "Vorschläge entstehen aus Marke, Erstzulassung und Ort. Entschieden wird nur von Menschen – nichts wird automatisch zusammengeführt."),
     info, warnBox, fehlerBox, liste].forEach(function (n) { wurzel.appendChild(n); });
    var laeuft = false;

    function frage(text) { return opt.bestaetigung ? opt.bestaetigung(text) : window.confirm(text); }
    function zeigeFehler(e) { fehlerBox.textContent = fehlerText(e); fehlerBox.hidden = false; if (opt.meldung && !wurzel.closest("[hidden]")) opt.meldung(fehlerText(e), true); }

    function seite(s, plat, anzeige) {
      var d = el("div", { "class": "dub-seite" });
      d.appendChild(el("b", { "class": "dub-titel" }, s.titel || anzeige));
      d.appendChild(el("span", { "class": "dub-meta" }, eur(s.preis) + " · " + (s.km ? Number(s.km).toLocaleString("de-DE") + " km" : "km ?") +
                                                      " · EZ " + (s.ez_jahr || "?") + " · " + (s.ort || "Ort ?")));
      d.appendChild(el("span", { "class": "dub-meta" }, plattform(plat) + " · Anzeige " + anzeige));
      var ext = externLink(s.url);
      if (ext) d.appendChild(ext);
      return d;
    }

    function entscheide(aktion, v, knopf, folge, bezeichnung) {
      if (laeuft) return;
      if (!frage(bezeichnung + "?\n\n" + folge + "\n\n" + (v.a.titel || v.anzeigen_a) + "\n" + (v.b.titel || v.anzeigen_b))) return;
      laeuft = true; knopf.disabled = true; fehlerBox.hidden = true;
      opt.post("/api/dubletten/" + aktion, { a: v.inserat_a, b: v.inserat_b }).then(function (d) {
        laeuft = false;
        var text = aktion === "bestaetigen" ? "Als gleiches Fahrzeug gespeichert ✓" : "Als verschieden gespeichert ✓";
        if (opt.meldung) opt.meldung(text, false);
        if (d.warnung) zeigeWarnung(d.warnung); else warnBox.hidden = true;
        if (opt.nachAktion) opt.nachAktion(d);
        lade();
      }, function (e) { laeuft = false; knopf.disabled = false; zeigeFehler(e); lade(); });
    }

    function zeigeWarnung(w) {
      warnBox.textContent = "";
      warnBox.appendChild(el("b", {}, "Achtung: "));
      warnBox.appendChild(document.createTextNode(w.text || "Verschiedene Kollegen halten Inserate dieser Gruppe."));
      var ul = el("ul");
      (w.halter || []).forEach(function (h) { ul.appendChild(el("li", {}, h.name + " hält Anzeige " + h.anzeige_id)); });
      warnBox.appendChild(ul);
      warnBox.appendChild(el("p", { "class": "dub-leise" }, "Bitte im Team klären, wer den Verkäufer anschreibt – die Reservierungen bleiben unverändert."));
      warnBox.hidden = false;
    }

    function karte(v) {
      var k = el("article", { "class": "dub-karte", "data-dub-paar": v.inserat_a + "-" + v.inserat_b });
      var kp = el("div", { "class": "dub-karten-kopf" });
      kp.appendChild(el("span", { "class": "dub-stufe dub-stufe-" + (v.stufe === "hoch" ? "hoch" : "mittel") }, STUFE[v.stufe] || ("Übereinstimmung: " + v.stufe)));
      k.appendChild(kp);
      var paar = el("div", { "class": "dub-paar" });
      paar.appendChild(seite(v.a, v.plattform_a, v.anzeigen_a));
      paar.appendChild(seite(v.b, v.plattform_b, v.anzeigen_b));
      k.appendChild(paar);
      if ((v.gruende || []).length) {
        k.appendChild(el("p", { "class": "dub-leise" }, "Gründe:"));
        var ul = el("ul", { "class": "dub-gruende" });
        v.gruende.forEach(function (g) { ul.appendChild(el("li", {}, g)); });
        k.appendChild(ul);
      }
      var aktion = el("div", { "class": "dub-aktionen" });
      if (v.darf_bestaetigen) {
        var g = el("button", { type: "button", "class": "dub-knopf primaer", "data-dub-gleich": "" }, "Gleiches Fahrzeug");
        g.onclick = function () { entscheide("bestaetigen", v, g, FOLGE_GLEICH, "Als gleiches Fahrzeug bestätigen"); };
        aktion.appendChild(g);
      }
      if (v.darf_ablehnen) {
        var n = el("button", { type: "button", "class": "dub-knopf", "data-dub-verschieden": "" }, "Verschieden");
        n.onclick = function () { entscheide("ablehnen", v, n, FOLGE_VERSCHIEDEN, "Als verschiedene Fahrzeuge festhalten"); };
        aktion.appendChild(n);
      }
      if (!v.darf_bestaetigen && !v.darf_ablehnen) aktion.appendChild(el("span", { "class": "dub-leise" }, "Keine Berechtigung zum Entscheiden."));
      else if (v.darf_bestaetigen && !v.darf_ablehnen) aktion.appendChild(el("span", { "class": "dub-leise" }, "„Verschieden“ entscheidet der Inhaber."));
      k.appendChild(aktion);
      return k;
    }

    function lade() {
      return opt.get("/api/dubletten-vorschlaege").then(function (d) {
        liste.textContent = "";
        (d.vorschlaege || []).forEach(function (v) { liste.appendChild(karte(v)); });
        var n = d.anzahl;
        titel.textContent = "Dublettenvorschläge (" + n + ")";
        info.textContent = n === 0 ? "Keine offenen Vorschläge." : (d.vorschlaege.length < n ? "Angezeigt: " + d.vorschlaege.length + " von " + n + "." : "");
        if (d.unvollstaendig) info.textContent += (info.textContent ? " " : "") + "Unvollständig geprüft: " + (d.hinweis || "Gruppe zu groß") + ".";
        if (opt.zaehler) opt.zaehler(n, !!d.unvollstaendig);
        return d;
      }, function (e) { zeigeFehler(e); });
    }
    neuLaden.onclick = lade;
    return { laden: lade, aufhebenFolge: FOLGE_AUFHEBEN };
  }

  // Aufheben (Fahrzeugfenster): Bestätigung mit Folgen, dann POST; ``fertig(antwort)`` bzw. ``fehler(e)``.
  function aufhebenFrage(e, bestaetigung) {
    var text = "Entscheidung aufheben?\n\n" + (e.entscheidung === "gleich" ? "Gleiches Fahrzeug" : "Verschieden") + ": " + e.anzeige_a + " ↔ " + e.anzeige_b + "\n\n" + FOLGE_AUFHEBEN;
    return bestaetigung ? bestaetigung(text) : window.confirm(text);
  }

  window.Dubletten = { gruppeBox: gruppeBox, vorschlaege: vorschlaege, aufhebenFrage: aufhebenFrage, fehlerText: fehlerText };
})();
