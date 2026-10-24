/* Suchprofile (P4-01) – Desktop-App: Filter „Suchprofil“ in der Leiste, Verwaltung (Inhaber) und Abdeckungscheckliste je Plattform.
   Profile rufen nichts ab: sie filtern die eingegangenen Inserate. Alles aus Eingaben wird nur per textContent/value ausgegeben,
   Links nur bei http(s). Nichts wird im Browser gespeichert. */
(function () {
  "use strict";
  var SCOUT = window.SCOUT || {};
  if (!SCOUT.token) return;
  var PLATTFORM = { kleinanzeigen: "Kleinanzeigen", "mobile.de": "mobile.de", autoscout24: "AutoScout24" };
  var ZUSTAND = { fehlt: "kein Suchauftrag angelegt", angelegt: "angelegt, Treffer kommen an", pruefen: "angelegt, aber seit 14 Tagen kein passender Treffer – prüfen",
                  nicht_lesbar: "Eingang im Scout noch nicht lesbar" };
  var box = document.getElementById("suchprofile-box"), knopf = document.getElementById("profil-knopf"), auswahl = document.getElementById("profil-filter");
  var stand = null;

  function el(tag, attr, text) {
    var e = document.createElement(tag);
    Object.keys(attr || {}).forEach(function (k) { e.setAttribute(k, attr[k]); });
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function api(url, daten) {
    var opt = { credentials: "same-origin", headers: {} };
    if (daten !== undefined) {
      opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.headers["X-Scout-Token"] = SCOUT.token; opt.body = JSON.stringify(daten);
    }
    return fetch(url, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) { var e = new Error(d.fehler || ("Fehler " + r.status)); e.status = r.status; throw e; }
        return d;
      });
    });
  }
  function meldung(text, fehler) {
    var m = box.querySelector("[data-sp-meldung]");
    if (m) { m.textContent = text; m.className = fehler ? "warn" : "meta"; }
  }
  function datum(iso) { return iso ? String(iso).slice(8, 10) + "." + String(iso).slice(5, 7) + "." + String(iso).slice(0, 4) : "noch keiner"; }

  // ---------- Filter in der Leiste
  function filterSetzen() {
    var id = auswahl.value;
    if (!id) { if (window.scoutProfilFilter) window.scoutProfilFilter(null); return; }
    api("/api/suchprofil/" + encodeURIComponent(id) + "/treffer").then(function (d) {
      if (window.scoutProfilFilter) window.scoutProfilFilter(d.treffer);
    }, function (e) { meldung(e.message, true); });
  }
  function auswahlFuellen() {
    var alt = auswahl.value;
    auswahl.textContent = "";
    auswahl.appendChild(el("option", { value: "" }, "Suchprofil: alle Fahrzeuge"));
    stand.profile.filter(function (p) { return p.aktiv; }).forEach(function (p) {
      auswahl.appendChild(el("option", { value: String(p.id) }, p.name + " (" + p.treffer.passt + (p.treffer.unklar ? " + " + p.treffer.unklar + " unklar" : "") + ")"));
    });
    auswahl.value = alt && auswahl.querySelector('option[value="' + alt + '"]') ? alt : "";
    auswahl.hidden = !stand.profile.length;
  }

  // ---------- Formular
  function feld(form, name, beschriftung, wert, typ) {
    var l = el("label", { "class": "sp-feld" }, beschriftung);
    var i = el("input", { name: name, type: typ || "text" });
    if (wert !== null && wert !== undefined) i.value = String(wert);
    if (!stand.darf_aendern) i.disabled = true;
    l.appendChild(i); form.appendChild(l);
    return i;
  }
  function profilFormular(p) {
    var f = el("form", { "class": "sp-form" });
    feld(f, "name", "Name", p.name);
    var arten = el("fieldset", { "class": "sp-arten" }); arten.appendChild(el("legend", null, "Arten (leer = alle)"));
    stand.arten.forEach(function (a) {
      var l = el("label"), c = el("input", { type: "checkbox", value: a });
      c.checked = (p.arten || []).indexOf(a) >= 0; c.disabled = !stand.darf_aendern;
      l.appendChild(c); l.appendChild(document.createTextNode(" " + a)); arten.appendChild(l);
    });
    f.appendChild(arten);
    feld(f, "marken", "Marken (Komma, leer = alle)", (p.marken || []).join(", "));
    feld(f, "modell", "Modell enthält", p.modell);
    feld(f, "preis_min", "Preis von €", p.preis_min, "number"); feld(f, "preis_max", "bis €", p.preis_max, "number");
    feld(f, "ez_min", "EZ von", p.ez_min, "number"); feld(f, "ez_max", "bis", p.ez_max, "number");
    feld(f, "km_max", "km bis", p.km_max, "number");
    var aktiv = el("label", { "class": "sp-feld" }), ak = el("input", { type: "checkbox", name: "aktiv" });
    ak.checked = p.aktiv !== false; ak.disabled = !stand.darf_aendern;
    aktiv.appendChild(ak); aktiv.appendChild(document.createTextNode(" aktiv")); f.appendChild(aktiv);
    feld(f, "notiz", "Notiz", p.notiz);
    if (stand.darf_aendern) {
      var speichern = el("button", { type: "submit", "class": "btn primaer" }, p.id ? "Speichern" : "Profil anlegen");
      f.appendChild(speichern);
      if (p.id) {
        var weg = el("button", { type: "button", "class": "btn", "data-sp-loeschen": "" }, "Löschen");
        weg.onclick = function () {
          if (!confirm("Suchprofil „" + p.name + "“ und seine Checkliste löschen? Inserate bleiben unverändert.")) return;
          api("/api/suchprofil/" + p.id + "/loeschen", {}).then(laden, function (e) { meldung(e.message, true); });
        };
        f.appendChild(weg);
      }
    }
    f.onsubmit = function (ev) {
      ev.preventDefault();
      var d = { name: f.elements.name.value, aktiv: f.elements.aktiv.checked, modell: f.elements.modell.value || null, notiz: f.elements.notiz.value || null,
                marken: f.elements.marken.value.split(",").map(function (m) { return m.trim(); }).filter(Boolean),
                arten: Array.prototype.filter.call(arten.querySelectorAll("input"), function (c) { return c.checked; }).map(function (c) { return c.value; }) };
      var falsch = ["preis_min", "preis_max", "ez_min", "ez_max", "km_max"].filter(function (n) {
        var i = f.elements[n];
        if (i.value === "" && !i.validity.badInput) { d[n] = null; return false; }
        d[n] = i.valueAsNumber;
        return !isFinite(d[n]) || d[n] % 1 !== 0;
      });
      if (falsch.length) { meldung("Bitte ganze Zahlen eingeben: " + falsch.join(", "), true); return; }
      api(p.id ? "/api/suchprofil/" + p.id : "/api/suchprofile", d).then(function () { laden(); }, function (e) { meldung(e.message, true); });
    };
    return f;
  }
  function checkliste(p) {
    var t = el("table", { "class": "sp-abdeckung" }), kopf = el("tr");
    ["Plattform", "Suchauftrag angelegt", "Adresse des Suchauftrags", "Zustand", "letzter passender Treffer"].forEach(function (h) { kopf.appendChild(el("th", null, h)); });
    t.appendChild(kopf);
    p.abdeckung.plattformen.forEach(function (z) {
      var tr = el("tr", { "data-sp-plattform": z.plattform, "class": "sp-" + z.zustand });
      tr.appendChild(el("td", null, PLATTFORM[z.plattform] || z.plattform));
      var td = el("td"), c = el("input", { type: "checkbox", "aria-label": "Suchauftrag angelegt" });
      c.checked = z.angelegt; c.disabled = !stand.darf_aendern || z.zustand === "nicht_lesbar";
      td.appendChild(c); tr.appendChild(td);
      var tdu = el("td"), u = el("input", { type: "url", placeholder: "https://…", "aria-label": "Adresse" });
      u.value = z.url || ""; u.disabled = c.disabled; tdu.appendChild(u);
      if (z.url && /^https?:\/\//i.test(z.url)) tdu.appendChild(el("a", { href: z.url, target: "_blank", rel: "noopener noreferrer" }, " öffnen ↗"));
      tr.appendChild(tdu);
      tr.appendChild(el("td", null, ZUSTAND[z.zustand] || z.zustand));
      tr.appendChild(el("td", null, datum(z.letzter_treffer)));
      var sichern = function () {
        api("/api/suchprofil/" + p.id + "/auftrag", { plattform: z.plattform, angelegt: c.checked, url: u.value || null }).then(laden, function (e) { meldung(e.message, true); });
      };
      c.onchange = sichern; u.onchange = sichern;
      t.appendChild(tr);
    });
    return t;
  }
  function zeichnen() {
    // geöffnete Profile bleiben nach dem Speichern offen
    var offen = Array.prototype.map.call(box.querySelectorAll("details[open]"), function (d) { return d.getAttribute("data-sp-id") || "neu"; });
    box.textContent = "";
    box.appendChild(el("p", { "class": "meta" }, "Suchprofile filtern die eingegangenen Inserate (Suchlauf, gespeicherte Seiten, Text, Mails) – sie rufen nichts ab. " +
      "Die Checkliste zeigt je Plattform, ob dort ein Suchauftrag bzw. eine E-Mail-Benachrichtigung angelegt ist." + (stand.darf_aendern ? "" : " Ändern darf der Inhaber.")));
    box.appendChild(el("p", { "data-sp-meldung": "", "class": "meta" }, ""));
    stand.profile.forEach(function (p) {
      var d = el("details", { "class": "sp-profil", "data-sp-id": String(p.id) });
      d.appendChild(el("summary", null, p.name + (p.aktiv ? "" : " (inaktiv)") + " – " + p.treffer.passt + " passend, " + p.treffer.unklar + " unklar · Abdeckung " +
                       Math.round(p.abdeckung.quote * 100) + " %"));
      d.appendChild(profilFormular(p));
      d.appendChild(checkliste(p));
      d.open = offen.indexOf(String(p.id)) >= 0;
      box.appendChild(d);
    });
    if (stand.darf_aendern) {
      var neu = el("details", { "class": "sp-profil", "data-sp-neu": "" });
      neu.appendChild(el("summary", null, "＋ Neues Suchprofil"));
      neu.appendChild(profilFormular({ aktiv: true }));
      box.appendChild(neu);
    }
  }
  function laden() {
    return api("/api/suchprofile").then(function (d) { stand = d; zeichnen(); auswahlFuellen(); filterSetzen(); }, function (e) { if (box) box.textContent = e.message; });
  }

  if (knopf) knopf.onclick = function () {
    var panel = document.getElementById("suchprofile"), auf = panel.hidden;
    panel.hidden = !auf; knopf.setAttribute("aria-expanded", String(auf));
    if (auf) laden();
  };
  if (auswahl) auswahl.onchange = filterSetzen;
  laden();
})();
