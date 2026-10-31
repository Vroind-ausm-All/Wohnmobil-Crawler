"""P6-01 – Kombinierte Ankaufsliste (ADR-061): alle Quellen in einer Liste, nach Deal-Score sortiert, Quelle wählbar, Risikofaktoren
sichtbar (Desktop-Karte und -Detail, API, Handy-App)."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_team_bearbeitung import lokal, server, starte  # noqa: F401 – Fixtures
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.risikofaktoren import HOCH, MITTEL, risikofaktoren
from wmscout.web.api import nach_deal_score
from tests.daten import BASIS

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"
PRIVAT = {"typ": "privat"}


def _b(sicherheit="hoch", maengel=(), abholung=None, vergleiche=12):
    return SimpleNamespace(sicherheit=sicherheit, vergleich_anzahl=vergleiche, maengel=list(maengel), abholung=abholung)


def _codes(r):
    return [(x["code"], x["stufe"]) for x in r]


# ---------------------------------------------------------------- 1. Risikofaktoren (rein)
def test_ohne_risiko_leer():
    assert risikofaktoren({"anbieter": PRIVAT, "tage_online": 3, "entfernung_km": 50}, _b()) == []


@pytest.mark.parametrize("a, b, erwartet", [
    ({}, _b("keine"), ("bewertung", HOCH)),
    ({}, _b("niedrig", vergleiche=2), ("bewertung", HOCH)),
    ({}, _b(maengel=[{"name": "Feuchtigkeit", "wert": -0.08, "roh": -0.12}]), ("maengel", HOCH)),
    ({}, _b(maengel=[{"name": "Kratzer", "wert": -0.01}]), ("maengel", MITTEL)),
    ({"vermutlich_offline": True}, _b(), ("verfuegbarkeit", HOCH)),
    ({"verfuegbarkeit": "reserviert"}, _b(), ("verfuegbarkeit", MITTEL)),
    ({"datenqualitaet": {"stufe": "mittel", "markierungen": [{"art": "widerspruch", "text": "km passt nicht zum Text"}]}}, _b(), ("daten", HOCH)),
    ({"datenqualitaet": {"stufe": "schwach", "markierungen": [{"art": "fehlt", "text": "km fehlt"}]}}, _b(), ("daten", MITTEL)),
    ({"ausland": "AT", "entfernung_km": 900}, _b(), ("ausland", HOCH)),
    ({"entfernung_km": 650}, _b(), ("abholung", MITTEL)),
    ({}, _b(abholung={"gewaehlt": "auto", "varianten": [{"art": "auto", "euro": 640}]}), ("abholung", MITTEL)),
    ({"anbieter": {"typ": "unbekannt"}}, _b(), ("anbieter", MITTEL)),
    ({"tage_online": 75}, _b(), ("standzeit", MITTEL)),
])
def test_einzelne_faktoren(a, b, erwartet):
    r = risikofaktoren({"anbieter": PRIVAT, **a}, b)
    assert _codes(r) == [erwartet] and r[0]["text"]                                          # genau dieser Faktor, kein weiterer


def test_karte_ohne_doppelte_warnungen():
    """QA B2/B3: was die Karte schon als Mängel-, Hinweiszeile oder Abzeichen zeigt, kommt nur ins Detail; verkauft und gewerblich zählen."""
    r = risikofaktoren({"ausland": "AT", "anbieter": {"typ": "gewerblich"}, "nicht_verfuegbar": True, "verfuegbarkeit": "verkauft",
                        "tage_online": 61}, _b(maengel=[{"name": "Rost", "wert": -0.02}]))
    assert {x["code"]: x["karte"] for x in r} == {"maengel": False, "verfuegbarkeit": False, "ausland": False, "anbieter": False, "standzeit": True}
    assert "nicht mehr verfügbar (verkauft)" in [x["text"] for x in r]


@pytest.mark.parametrize("a, b", [
    ({}, _b(abholung={"gewaehlt": "lkw", "varianten": [{"art": "auto", "euro": 600}]})),
    ({}, _b(abholung={"gewaehlt": "auto", "varianten": [{"art": "auto", "euro": None}]})),
    ({}, _b(abholung={"gewaehlt": "auto", "varianten": []})),
    ({}, _b(maengel=[{"name": "x"}, "kaputt"])),
    ({"datenqualitaet": {"markierungen": [{"art": "widerspruch"}, None]}}, _b()),
    ({"tage_online": "70", "entfernung_km": None, "anbieter": None}, SimpleNamespace(sicherheit="niedrig")),
    ({}, None),
])
def test_unvollstaendige_strukturen_ohne_ausnahme(a, b):
    """QA B1: eine Ausnahme hier legte die ganze Liste lahm."""
    assert isinstance(risikofaktoren(a, b), list)


def test_entfernung_grenze_und_runden():
    assert risikofaktoren({"entfernung_km": 400}, _b()) == []
    assert risikofaktoren({"entfernung_km": 812.6}, _b())[0]["text"] == "weit entfernt (813 km)"


def test_grenzen_und_reihenfolge():
    nah = _b(abholung={"gewaehlt": "auto", "varianten": [{"art": "auto", "euro": 500}, {"art": "bahn", "euro": 900}]})
    assert risikofaktoren({"anbieter": PRIVAT, "entfernung_km": 800, "tage_online": 60}, nah) == []     # Abholkosten zählen, nicht km
    r = risikofaktoren({"anbieter": {"typ": "unbekannt"}, "tage_online": 90, "vermutlich_offline": True, "ausland": "PL"}, _b("keine"))
    assert [x["stufe"] for x in r] == [HOCH, HOCH, HOCH, MITTEL, MITTEL]                            # hohe zuerst, sonst feste Reihenfolge
    assert [x["code"] for x in r] == ["bewertung", "verfuegbarkeit", "ausland", "anbieter", "standzeit"]
    assert "1.200" in risikofaktoren({}, _b(abholung={"gewaehlt": "bahn", "varianten": [{"art": "bahn", "euro": 1196}]}))[0]["text"]


def test_auswertung_liefert_risiken(cfg, db, importiert):
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert all(isinstance(z["risiken"], list) for z in zeilen) and any(z["risiken"] for z in zeilen)


# ---------------------------------------------------------------- 2. Sortierung und API
def test_sortierschluessel():
    def z(score, v):
        return {"deal": {"score": score}, "b": SimpleNamespace(verhaeltnis=v)}
    zeilen = [z(None, 0.5), z(40, 0.9), z(80, 1.0), z(80, 0.7), z(None, None)]
    erg = sorted(zeilen, key=nach_deal_score)
    assert [(x["deal"]["score"], x["b"].verhaeltnis) for x in erg] == [(80, 0.7), (80, 1.0), (40, 0.9), (None, 0.5), (None, None)]


def test_api_sortierung_felder_top(server):
    c = lokal(server)
    liste = c("GET", "/api/fahrzeuge?filter=alle")[1]
    scores = [f["deal_score"] for f in liste]
    mit = [s for s in scores if s is not None]
    assert mit and mit == sorted(mit, reverse=True) and scores[:len(mit)] == mit                      # ohne Score am Ende
    assert all(isinstance(f["risiken"], list) and f["quelle_text"] == "Kleinanzeigen" for f in liste)
    top = c("GET", "/api/fahrzeuge?filter=top")[1]
    assert all(f["priorisiert"] for f in top) and {f["id"] for f in top} == {f["id"] for f in liste if f["priorisiert"]}
    assert c("GET", "/api/fahrzeuge?filter=alle&quelle=ebay")[0] == 400
    bereit = [f["deal_score"] for f in c("GET", "/api/fahrzeuge?filter=bereit")[1] if f["deal_score"] is not None]
    assert bereit == sorted(bereit, reverse=True)


def test_api_quelle_filter(cfg, db, importiert):
    ein = db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 2").fetchall()
    db.con.executemany("UPDATE anzeigen SET quelle='mobile.de' WHERE id=?", [(r["id"],) for r in ein])
    db.con.commit()
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        alle = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
        mob = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle&quelle=mobile.de")[1]
        ka = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle&quelle=kleinanzeigen")[1]
        assert {f["id"] for f in mob} == {r["id"] for r in ein} and all(f["quelle_text"] == "mobile.de" for f in mob)
        assert len(mob) + len(ka) == len(alle) and c("GET", "/api/fahrzeuge?filter=alle&quelle=autoscout24")[1] == []
        html = c("GET", "/")[1]
        assert '<option value="mobile.de">mobile.de</option>' in html and '<option value="kleinanzeigen">Kleinanzeigen</option>' in html
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- 3. Oberflächen
def test_desktop_karte_und_detail(server):
    c = lokal(server)
    html = c("GET", "/")[1]
    assert 'id="quelle"' in html and "quelleWahl.value" in html and "data-quelle-tag" in html and ">Kleinanzeigen<" in html
    karten = re.findall(r'<p class="risiken" data-risiken[^>]*>(.*?)</p>', html, re.S)
    assert karten and all(k.count('class="risk') <= 4 for k in karten)
    assert not any("Mängel genannt" in k or "schwerer Mangel" in k for k in karten)                 # Mängel nur in der Mängelzeile
    assert "data-risiken-detail" in html and "Risikofaktoren – vor einem Angebot prüfen" in html


def test_handy_app_statisch():
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    assert 'top: "Top-Deals"' in js and '"&quelle=" + encodeURIComponent(S.quelle)' in js
    assert "function risikoZeile" in js and "data-risiken-detail" in js and "risikoZeile(f, true)" in js and "dealTag(f)" in js
    assert re.search(r'esc\(x\.text\)', js)                                           # Texte nur über esc()
    css = (STATIC / "mobil.css").read_text(encoding="utf-8")
    assert ".risk.hoch" in css and ".tag.deal.top" in css
    from wmscout.domaene import PLATTFORM_TEXT                                       # Quellenliste im Gleichlauf (QA B6)
    feste = dict(re.findall(r'"?([\w.]+)"?: "([^"]+)"', re.search(r"var QUELLEN = \{(.*?)\};", js).group(1)))
    assert feste == PLATTFORM_TEXT
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"wm-scout-(\d+)", sw).group(1)) >= 19


def test_desktop_risiken_escaped(cfg, db, importiert):
    """Risikotexte enthalten Inseratsdaten (Mängelname, Datenqualität) – Chip, title-Attribut und Detailliste escaped."""
    from wmscout.ausgabe import render_html
    zeilen = bewerte_alle(cfg, db, BASIS)
    zeilen[0]["risiken"] = [{"code": "daten", "text": '<img src=x onerror=alert(1)> "q\'', "stufe": "hoch", "karte": True}]
    html = render_html(cfg, zeilen, BASIS)[0]
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
