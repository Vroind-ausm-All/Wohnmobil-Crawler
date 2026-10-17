/* Formular „Inserat einlesen (Link + Text)“ (P2-05) – gemeinsam für Desktop-App und Handy-App.
   Der Nutzer fügt Adresse und kopierten Anzeigentext ein; gesendet wird an POST /api/import/text. Online-Aktion: nichts wird
   zwischengespeichert (kein localStorage, keine Offline-Warteschlange); bei Fehlern bleiben die Eingaben im Formular stehen.
   Alles Fremde (Titel, Ort, Hinweise) wird nur per textContent ausgegeben. */
(function () {
  "use strict";
  var MAX_TEXT = 50000, MAX_URL = 2000, zaehler = 0;
  var HINWEIS = "Nur den Anzeigentext einfügen – keine Namen, Telefonnummern oder Adressen des Verkäufers. " +
                "Kontaktdaten werden automatisch entfernt, Namen im Fließtext nicht immer.";
  var ERGEBNIS = { neu: "Neu gespeichert", preis: "Preis gesenkt – Anzeige aktualisiert", bekannt: "Bereits bekannt" };
  var AENDERUNG = { gesenkt: "gesenkt", gestiegen: "gestiegen", unveraendert: "unverändert" };
  var MAX_PREIS = 2000000;
  // Preis laut Anzeige: "24900", "24.900", "24 900", "24.900,-", "24.900 €" → Zahl; leer → null (kein Eintrag); sonst NaN
  function preisAus(wert) {
    var t = String(wert || "").replace(/[\s\u00a0\u202f]/g, "").replace(/€|eur(o)?$/i, "").replace(/,-$/, "");
    if (t === "") return null;
    t = t.replace(/\./g, "");
    if (!/^\d{1,7}$/.test(t)) return NaN;
    var n = parseInt(t, 10);
    return n >= 1 && n <= MAX_PREIS ? n : NaN;
  }
  var PLATTFORM = { kleinanzeigen: "Kleinanzeigen", "mobile.de": "mobile.de" };

  function el(tag, attr, text) {
    var e = document.createElement(tag);
    Object.keys(attr || {}).forEach(function (k) { e.setAttribute(k, attr[k]); });
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function zahl(n) { return Number(n).toLocaleString("de-DE"); }
  function laenge(s) { return Array.from(s).length; }                 // Zeichen wie auf dem Server (nicht UTF-16-Einheiten)
  function nurPfad(h) { return /^\/(?![/\\])/.test(String(h || "")) ? h : null; }   // nur Adressen dieser App

  function baue(wurzel, opt) {
    var nr = ++zaehler, id = function (s) { return "ti-" + nr + "-" + s; }, laeuft = false;
    wurzel.textContent = "";
    wurzel.classList.add("ti");

    var hinweis = el("p", { "class": "ti-hinweis", id: id("hinw") }, HINWEIS);
    var anleitung = el("p", { "class": "ti-leise" },
      "So geht’s: Anzeige im Browser öffnen, Adresse kopieren, den Anzeigentext markieren und kopieren, beides hier einfügen. " +
      "Die Adresse wird nicht abgerufen; gelesen wird nur der eingefügte Text.");

    var form = el("form", { novalidate: "", autocomplete: "off" });
    var lUrl = el("label", { "for": id("url") }, "Adresse der Anzeige (Link)");
    var url = el("input", { id: id("url"), name: "url", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false",
                            placeholder: "https://www.kleinanzeigen.de/s-anzeige/…", "aria-describedby": id("url-z") });
    var zUrl = el("span", { id: id("url-z"), "class": "ti-zaehler" });
    var lText = el("label", { "for": id("text") }, "Anzeigentext (aus der Anzeige kopiert)");
    var text = el("textarea", { id: id("text"), name: "text", rows: "10", spellcheck: "false", "aria-describedby": id("hinw") + " " + id("text-z"),
                                placeholder: "Titel, Preis, Kilometerstand, Erstzulassung, Beschreibung …" });
    text.className = "ti-text";
    var zText = el("span", { id: id("text-z"), "class": "ti-zaehler" });

    var preisZeile = el("div", { "class": "ti-preiszeile" });
    var lPreis = el("label", { "for": id("preis") }, "Preis laut Anzeige in € (optional, empfohlen)");
    var preis = el("input", { id: id("preis"), name: "preis", type: "text", inputmode: "numeric", autocomplete: "off", placeholder: "z. B. 24900",
                              "aria-describedby": id("preis-h"), "class": "ti-preisfeld" });
    var lVb = el("label", { "class": "ti-radio" });
    var vb = el("input", { type: "checkbox", name: id("vb") });
    lVb.appendChild(vb); lVb.appendChild(el("span", {}, "VB (Verhandlungsbasis)"));
    var preisHilfe = el("span", { id: id("preis-h"), "class": "ti-zaehler" },
      "Ein Preis aus dem Fließtext wird nie übernommen – nur ein klar gekennzeichneter Preis (VB, „Preis: …“) oder dieser Eintrag.");
    var preisFeld = el("div", { "class": "ti-preisfeld-box" });
    preisFeld.appendChild(lPreis); preisFeld.appendChild(preis);
    preisZeile.appendChild(preisFeld); preisZeile.appendChild(lVb);

    var gruppe = el("fieldset", { "class": "ti-anbieter" });
    gruppe.appendChild(el("legend", {}, "Anbieter laut Anzeige"));
    [["", "unbekannt"], ["privat", "privat"], ["gewerblich", "gewerblich"]].forEach(function (a, i) {
      var l = el("label", { "class": "ti-radio" });
      var r = el("input", { type: "radio", name: id("anbieter"), value: a[0] });
      if (i === 0) r.checked = true;
      l.appendChild(r); l.appendChild(el("span", {}, a[1]));
      gruppe.appendChild(l);
    });

    var knoepfe = el("div", { "class": "ti-knoepfe" });
    var senden = el("button", { type: "submit", "class": "ti-knopf ti-primaer" }, "Einlesen");
    var leeren = el("button", { type: "button", "class": "ti-knopf" }, "Felder leeren");
    knoepfe.appendChild(senden); knoepfe.appendChild(leeren);

    var fehler = el("div", { "class": "ti-fehler", role: "alert", hidden: "" });
    var ergebnis = el("div", { "class": "ti-ergebnis", "aria-live": "polite", hidden: "" });

    form.appendChild(lUrl); form.appendChild(url); form.appendChild(zUrl);
    form.appendChild(lText); form.appendChild(text); form.appendChild(zText);
    form.appendChild(preisZeile); form.appendChild(preisHilfe);
    form.appendChild(gruppe); form.appendChild(knoepfe);
    wurzel.appendChild(anleitung); wurzel.appendChild(hinweis); wurzel.appendChild(form);
    wurzel.appendChild(fehler); wurzel.appendChild(ergebnis);

    function zaehlerAktualisieren() {
      var nu = laenge(url.value), nt = laenge(text.value);
      zUrl.textContent = zahl(nu) + " / " + zahl(MAX_URL) + " Zeichen" + (nu > MAX_URL ? " – zu lang" : "");
      zText.textContent = zahl(nt) + " / " + zahl(MAX_TEXT) + " Zeichen" + (nt > MAX_TEXT ? " – zu lang, bitte nur den Anzeigentext einfügen" : "");
      zUrl.classList.toggle("ti-ueber", nu > MAX_URL); zText.classList.toggle("ti-ueber", nt > MAX_TEXT);
      url.setAttribute("aria-invalid", nu > MAX_URL ? "true" : "false"); text.setAttribute("aria-invalid", nt > MAX_TEXT ? "true" : "false");
    }
    url.addEventListener("input", zaehlerAktualisieren); text.addEventListener("input", zaehlerAktualisieren);
    zaehlerAktualisieren();

    function zeigeFehler(titel, zeilen) {
      fehler.textContent = "";
      fehler.appendChild(el("p", { "class": "ti-titel" }, titel));
      if (zeilen && zeilen.length) {
        var ul = el("ul");
        zeilen.forEach(function (z) { ul.appendChild(el("li", {}, z)); });
        fehler.appendChild(ul);
      }
      fehler.hidden = false; ergebnis.hidden = true; fehler.scrollIntoView({ block: "nearest" });
    }
    function zuruecksetzen() {
      url.value = ""; text.value = ""; preis.value = ""; vb.checked = false; preis.removeAttribute("aria-invalid");
      gruppe.querySelector("input[value='']").checked = true;
      zaehlerAktualisieren();
    }
    leeren.addEventListener("click", function () { zuruecksetzen(); fehler.hidden = true; ergebnis.hidden = true; url.focus(); });

    function fehlerAus(e) {
      var d = e.daten || {};
      if (e.status === 422) return ["Nicht gespeichert – die Anzeige wurde nicht übernommen.", d.hinweise && d.hinweise.length ? d.hinweise : [e.message]];
      if (e.status === 409 && e.grund === "deaktiviert") return ["Eingang ist abgeschaltet (Einstellungen). Es wurde nichts gespeichert.", []];
      if (e.status === 403 && e.grund === "csrf") return ["Sitzung abgelaufen – bitte die Seite neu laden und erneut versuchen.", []];
      if (e.status === 403) return ["Keine Berechtigung: " + e.message, []];
      if (e.status === undefined || e.status === 0 || e.grund === "netz") {
        return ["Keine Verbindung zur App – das Einlesen braucht Netz. Es wurde nichts gespeichert und nichts vorgemerkt; deine Eingaben bleiben stehen.", []];
      }
      return ["Nicht gespeichert: " + e.message, []];
    }

    function feld(liste, name, wert) {
      liste.appendChild(el("dt", {}, name));
      liste.appendChild(el("dd", {}, wert === null || wert === undefined || wert === "" ? "nicht erkannt" : String(wert)));
    }
    function zeigeErgebnis(d) {
      var k = d.erkannt || {};
      ergebnis.textContent = "";
      var preisUnsicher = d.preis_status === "unsicher" || d.preis_status === "fehlt";
      if (preisUnsicher) {
        var ph = el("div", { "class": "ti-preis-hinweis", role: "alert" });
        ph.appendChild(el("p", { "class": "ti-titel" }, "Kein Preis gespeichert – bitte den Preis eintragen"));
        (d.hinweise || []).filter(function (h) { return /^(Preis nicht sicher|Kein Preis|Text passt offenbar)/.test(h); })
          .forEach(function (h) { ph.appendChild(el("p", {}, h)); });
        ph.appendChild(el("p", { "class": "ti-leise" }, "Deine Eingaben bleiben stehen: Preis oben eintragen und noch einmal „Einlesen“ drücken."));
        ergebnis.appendChild(ph);
      }
      ergebnis.appendChild(el("p", { "class": "ti-titel ti-ok" }, "✓ " + (ERGEBNIS[d.ergebnis] || "Gespeichert") + " (" + (PLATTFORM[d.plattform] || d.plattform || "?") + ")"));
      var dl = el("dl", { "class": "ti-felder" });
      feld(dl, "Titel", k.titel);
      feld(dl, "Preis", k.preis === null || k.preis === undefined ? null : zahl(k.preis) + " €" + (k.vb ? " VB" : ""));
      feld(dl, "Kilometer", k.km === null || k.km === undefined ? null : zahl(k.km) + " km");
      feld(dl, "Erstzulassung", k.ez_jahr);
      feld(dl, "Ort", k.ort);
      if (d.preis_aenderung && AENDERUNG[d.preis_aenderung]) {
        feld(dl, "Preisänderung", AENDERUNG[d.preis_aenderung] + (d.preis_aenderung === "unveraendert" ? "" : " (vorher " + zahl(d.preis_vorher) + " €)"));
      }
      feld(dl, "Anbieter", k.gewerblich === true ? "gewerblich" : k.gewerblich === false ? "privat" : "unbekannt");
      ergebnis.appendChild(dl);
      var uebrige = (d.hinweise || []).filter(function (h) { return !(preisUnsicher && /^(Preis nicht sicher|Kein Preis|Text passt offenbar)/.test(h)); });
      if (uebrige.length) {
        ergebnis.appendChild(el("p", { "class": "ti-titel" }, "Hinweise"));
        var ul = el("ul", { "class": "ti-hinweise" });
        uebrige.forEach(function (h) { ul.appendChild(el("li", {}, "⚠ " + h)); });
        ergebnis.appendChild(ul);
      }
      var reihe = el("div", { "class": "ti-knoepfe" });
      ((opt.aktionen && opt.aktionen(d)) || []).forEach(function (a, i) {
        var ziel;
        if (a.href) { ziel = el("a", { "class": "ti-knopf" + (i === 0 ? " ti-primaer" : ""), href: nurPfad(a.href) || "#" }, a.text); if (a.neuesFenster) { ziel.target = "_blank"; ziel.rel = "noopener"; } }
        else { ziel = el("button", { type: "button", "class": "ti-knopf" + (i === 0 ? " ti-primaer" : "") }, a.text); }
        if (a.klick) ziel.addEventListener("click", function (ev) { ev.preventDefault(); a.klick(); });
        reihe.appendChild(ziel);
      });
      ergebnis.appendChild(reihe);
      ergebnis.hidden = false; fehler.hidden = true; ergebnis.scrollIntoView({ block: "nearest" });
    }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (laeuft) return;
      var u = url.value, t = text.value, an = gruppe.querySelector("input:checked").value, p = preisAus(preis.value);
      var probleme = [];
      if (Number.isNaN(p)) probleme.push("Der Preis muss eine ganze Zahl in Euro sein (1 bis " + zahl(MAX_PREIS) + "), z. B. 24900 – oder leer bleiben.");
      preis.setAttribute("aria-invalid", Number.isNaN(p) ? "true" : "false");
      if (!u.trim()) probleme.push("Bitte die Adresse (Link) der Anzeige einfügen.");
      if (!t.trim()) probleme.push("Bitte den Anzeigentext einfügen.");
      if (laenge(u) > MAX_URL) probleme.push("Die Adresse ist zu lang (höchstens " + zahl(MAX_URL) + " Zeichen).");
      if (laenge(t) > MAX_TEXT) probleme.push("Der Text ist zu lang (höchstens " + zahl(MAX_TEXT) + " Zeichen).");
      if (probleme.length) { zeigeFehler("Bitte prüfen:", probleme); return; }
      if (navigator.onLine === false) { zeigeFehler(fehlerAus({})[0], []); return; }
      laeuft = true; senden.disabled = true; senden.textContent = "Wird eingelesen …";
      fehler.hidden = true; ergebnis.hidden = true;
      opt.post("/api/import/text", { url: u, text: t, anbieter: an || null, preis: p, vb: vb.checked }).then(function (d) {
        var offen = d.preis_status === "unsicher" || d.preis_status === "fehlt";
        if (!offen) zuruecksetzen();                     // ohne sicheren Preis bleiben alle Eingaben stehen: nur der Preis muss ergänzt werden
        zeigeErgebnis(d);
        if (offen) preis.focus();
        if (opt.nachErfolg) opt.nachErfolg(d);
      }, function (e) {
        var f = fehlerAus(e); zeigeFehler(f[0], f[1]);
      }).then(function () {
        laeuft = false; senden.disabled = false; senden.textContent = "Einlesen";
      });
    });
    return { fokus: function () { url.focus(); } };
  }

  window.TextImport = { baue: baue, HINWEIS: HINWEIS, MAX_TEXT: MAX_TEXT, MAX_URL: MAX_URL };
})();
