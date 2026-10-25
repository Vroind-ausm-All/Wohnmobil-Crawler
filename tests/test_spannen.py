"""P5-03 – Spannen statt Punktwerte, Abschlag bei unbekannter Marke, Mängelliste (ADR-054): Rechner, Hinweis, unbekannte Art,
Kalkulation, API und Oberflächen (Desktop, Handy)."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from tests.daten import BASIS, lade_cfg
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.anschreiben import hinweis_marke_unbekannt, hinweise
from wmscout.bewertung.auswertung import bewerte_alle, bewerte_anzeige
from wmscout.bewertung.rechner import Rechner
from wmscout.domaene import IMPORT_SUCHE
from wmscout.web.api import bewertung_json, fahrzeug_kurz

STICHTAG = datetime(2026, 10, 25, 12)
FZ = {"id": "x", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018, "km": 80000,
      "preis": 40000}


@pytest.fixture
def r():
    return Rechner(lade_cfg(), STICHTAG)


def _vgl(n, **k):
    return [{"id": f"v{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": 42000 + i * 1500,
             "zuletzt_gesehen": "2026-10-20T10:00:00", **k} for i in range(n)]


# ---------------------------------------------------------------- 1. Marke unbekannt
@pytest.mark.parametrize("marke, unbekannt", [(None, True), ("", True), ("Fiat", True), ("Mercedes", True), ("Knaus", False), ("Hymer", False)])
def test_marke_unbekannt(r, marke, unbekannt):
    assert r.marke_unbekannt({**FZ, "marke": marke}) is unbekannt


def test_abschlag_auf_den_haendler_vk(r):
    bekannt, unbekannt = r.kette(FZ, 50000), r.kette({**FZ, "marke": None}, 50000)
    assert unbekannt["vk"] == pytest.approx(bekannt["vk"] * 0.95) and unbekannt["mw_privat"] == bekannt["mw_privat"]
    assert unbekannt["max_ek"] < bekannt["max_ek"] and (unbekannt["abschlag"], bekannt["abschlag"]) == (0.05, 0.0)
    b = r.bewerte({**FZ, "id": "ohne", "marke": None}, [])
    assert b.abschlag_marke == 0.05 and r.bewerte(FZ, []).abschlag_marke == 0.0
    cfg = lade_cfg()
    cfg["rechner"]["abschlag_marke_unbekannt"] = 0
    assert Rechner(cfg, STICHTAG).kette({**FZ, "marke": None}, 50000)["vk"] == pytest.approx(bekannt["vk"])
    del cfg["rechner"]["abschlag_marke_unbekannt"]                                         # fehlt der Eintrag: 5 %
    assert Rechner(cfg, STICHTAG).kette({**FZ, "marke": None}, 50000)["abschlag"] == 0.05


def test_hinweis_nur_bei_unbekannter_marke(r):
    ohne = {**FZ, "id": "ohne", "marke": None}
    assert hinweis_marke_unbekannt(0.05) in hinweise(ohne, r.bewerte(ohne, []))
    assert hinweise(FZ, r.bewerte(FZ, [])) == []
    assert hinweis_marke_unbekannt(0.05) == ("Marke unbekannt – Händler-VK 5 % niedriger angesetzt; Marke beim Verkäufer erfragen, "
                                             "dann neu bewerten")


# ---------------------------------------------------------------- 2. Spannen
def test_spannen_umschliessen_den_punktwert(r):
    for n in (0, 2, 9):
        b = r.bewerte({**FZ, "id": f"s{n}"}, _vgl(n))
        assert b.max_ek_von <= b.max_ek <= b.max_ek_bis and b.privat_von <= b.marktwert_privat <= b.privat_bis
        assert all(x % 500 == 0 for x in (b.max_ek_von, b.max_ek_bis, b.privat_von, b.privat_bis))
    duenn, dicht = r.bewerte({**FZ, "id": "d0"}, []), r.bewerte({**FZ, "id": "d9"}, _vgl(9))
    assert dicht.max_ek_bis - dicht.max_ek_von < duenn.max_ek_bis - duenn.max_ek_von          # mehr Daten → engere Spanne


def test_keine_spanne_ohne_marktwert_oder_bei_manuellem_wert(r):
    keine = r.bewerte({**FZ, "id": "k", "ez_jahr": None}, [])
    assert keine.sicherheit == "keine" and keine.max_ek_von is None and keine.privat_von is None
    manuell = r.bewerte(FZ, [], marktwert_manuell=50000)
    assert manuell.sicherheit == "manuell" and manuell.max_ek_von is None and manuell.max_ek > 0


def test_unbekannte_art_nimmt_die_weiteste_spanne(cfg):
    from wmscout.bewertung.auswertung import fuer_rechner, kandidaten_arten
    a = {"id": "u1", "suche": IMPORT_SUCHE, "titel": "Camper Kastenwagen Wohnwagen", "ez_jahr": 2016, "km": 90000, "preis": 20000}
    assert len(kandidaten_arten(a)) > 1
    r = Rechner(cfg, STICHTAG)
    b = bewerte_anzeige(r, a, [])
    einzeln = [r.bewerte({**fuer_rechner(a), "art": art, "id": f"u1#{art}"}, []) for art in kandidaten_arten(a)]
    assert b.max_ek_von == min(x.max_ek_von for x in einzeln) and b.max_ek_bis == max(x.max_ek_bis for x in einzeln)
    assert b.privat_von == min(x.privat_von for x in einzeln) and b.privat_bis == max(x.privat_bis for x in einzeln)


# ---------------------------------------------------------------- 3. Mängelliste
def test_maengelliste(r):
    a = {**FZ, "id": "m", "beschreibung": "Leider Feuchtigkeit im Heck, etwas Rost am Rahmen. Solaranlage, Markise. Kein Wasserschaden."}
    b = r.bewerte(a, [])
    assert [m["name"] for m in b.maengel] == ["Feuchtigkeit", "Rost"] and all(m["wert"] < 0 for m in b.maengel)
    assert r.bewerte(FZ, []).maengel == []
    ohne_ez = r.bewerte({**a, "id": "m2", "ez_jahr": None}, [])
    assert ohne_ez.sicherheit == "keine" and [m["name"] for m in ohne_ez.maengel] == ["Feuchtigkeit", "Rost"]   # auch ohne Beträge


# ---------------------------------------------------------------- 4. Kalkulation
def test_kalkulation_rechenstand_und_eingefrorener_abschlag():
    cfg = lade_cfg()
    del cfg["rechner"]["abschlag_marke_unbekannt"]
    e = kalk.eingabe(cfg, {**FZ, "marke": None, "entfernung_km": 50}, _vgl(5), betrag=None, stichtag=STICHTAG, abholung="Firmensitz")
    assert e["version"] == kalk.VERSION == "E3" and e["rechner"]["abschlag_marke_unbekannt"] == 0.05
    mit = kalk.rechne(e)
    ohne = kalk.rechne(kalk.eingabe(lade_cfg(), {**FZ, "entfernung_km": 50}, _vgl(5), betrag=None, stichtag=STICHTAG, abholung="Firmensitz"))
    assert mit["szenarien"]["erwartet"]["haendler_vk"] < ohne["szenarien"]["erwartet"]["haendler_vk"]


# ---------------------------------------------------------------- 5. API und Oberfläche
def test_api_felder(cfg, db):
    jahr = date.today().year - 8
    db.speichere_treffer({"id": "w1", "titel": "Wohnmobil mit Wasserschaden", "preis": 20000, "km": 90000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Teilintegrierter")
    db.speichere_treffer({"id": "w2", "titel": "Wohnmobil ohne EZ", "preis": 20000, "km": 90000, "ort": "70173 Stuttgart"}, "Teilintegrierter")
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    k = fahrzeug_kurz(z["w1"])
    assert k["max_ek_von"] <= k["max_ek"] <= k["max_ek_bis"] and k["maengel"][0]["name"] == "Wasserschaden"
    assert hinweis_marke_unbekannt(0.05) in k["hinweise"]
    leer = fahrzeug_kurz(z["w2"])
    assert leer["max_ek_von"] is None and leer["max_ek_bis"] is None and leer["max_ek"] is None
    assert bewertung_json(z["w2"]["b"])["privat_von"] is None


def test_desktop_und_handy(server, db):
    jahr = date.today().year - 8
    db.speichere_treffer({"id": "w1", "titel": "Knaus Sky TI mit Wasserschaden <b>x</b>", "preis": 20000, "km": 90000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Teilintegrierter")
    db.con.commit()
    c = lokal(server)
    s, html, _ = c("GET", "/")
    assert s == 200 and "data-maxek-spanne" in html and "Max-EK (Spanne)" in html and "Mitte " in html
    assert 'data-maengel>Mängel laut Inserat: Wasserschaden<' in html and "data-maengel-liste" in html and "Im Inserat genannte Mängel" in html
    assert "data-spannen" in html and "<b>x</b>" not in html
    karte = re.search(r'<article[^>]*data-id="w1".*?</article>', html, re.S)
    assert karte and re.search(r"<b>\d{1,3}(\.\d{3})*–\d{1,3}(\.\d{3})* €</b>", karte.group(0))
    liste = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
    w1 = next(f for f in liste if f["id"] == "w1")
    assert w1["max_ek_von"] and w1["maengel"] == [{"name": "Wasserschaden", "wert": w1["maengel"][0]["wert"]}]
    d = c("GET", "/api/fahrzeug/w1")[1]
    assert d["bewertung"]["max_ek_von"] == w1["max_ek_von"] and d["bewertung"]["privat_von"] and d["maengel"] == w1["maengel"]
    js = (BASIS / "wmscout" / "web" / "static" / "mobil.js").read_text(encoding="utf-8")
    assert "function maxEkZelle" in js and "function maengelZeile" in js and "maengelZeile(f, true)" in js
    sw = (BASIS / "wmscout" / "web" / "static" / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"var VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 17 and "17: " in sw


# ---------------------------------------------------------------- 6. Korrekturrunde (QA P5-03)
@pytest.mark.parametrize("marke, modell, unbekannt", [
    ("Volkswagen", "California Ocean", False), ("Volkswagen", "Grand California 600", False), ("Mercedes", "Marco Polo", False),
    ("Ford", "Nugget Plus", False), ("Fiat", "Ducato", True), ("Mercedes", "Sprinter", True), ("Volkswagen", "Crafter", True),
    ("Volkswagen", None, True),
])
def test_werks_camper_haben_eine_marke(r, marke, modell, unbekannt):
    """QA B1: VW California, Marco Polo, Nugget – Basismarke ist zugleich die Aufbaumarke; kein Abschlag, kein Hinweis."""
    a = {**FZ, "id": f"w-{marke}-{modell}", "art": "Kastenwagen", "marke": marke, "modell": modell, "serie": None}
    assert r.marke_unbekannt(a) is unbekannt and (r.bewerte(a, []).abschlag_marke > 0) is unbekannt


def test_werks_camper_vergleichen_sich_ueber_die_marke(r):
    a = {**FZ, "id": "cal", "art": "Kastenwagen", "marke": "Volkswagen", "modell": "California Ocean", "serie": "California Ocean"}
    assert r.aehnlichkeit(a, {"id": "c2", "marke": "Volkswagen", "modell": "California Ocean", "serie": "California Ocean"})[1] == "reihe"
    assert r.aehnlichkeit({**a, "modell": "Ducato"}, {"id": "c3", "marke": "Volkswagen"})[1] == "andere"


def test_spanne_umschliesst_den_punktwert_auch_bei_dichten_daten(r):
    """QA B2: viele fast gleiche Vergleiche → sehr schmale Marktspanne; nach außen gerundet, nie Breite 0."""
    for n, streuung in ((80, 0), (150, 100), (40, 50)):
        vgl = [{"id": f"d{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": 45000 + (i % 3) * streuung,
                "zuletzt_gesehen": "2026-10-20T10:00:00"} for i in range(n)]
        b = r.bewerte({**FZ, "id": f"dicht{n}"}, vgl)
        assert b.max_ek_von <= b.max_ek <= b.max_ek_bis and b.max_ek_bis - b.max_ek_von >= 500
        assert b.privat_von <= b.marktwert_privat <= b.privat_bis and b.privat_bis - b.privat_von >= 500


def test_nach_aussen():
    from wmscout.bewertung.rechner import _nach_aussen
    assert _nach_aussen(10520, 10580) == (10500, 11000) and _nach_aussen(10500, 10500) == (10500, 11000)
    assert _nach_aussen(0, 0) == (0, 0) and _nach_aussen(0, 1900) == (0, 2000)


def test_max_ek_null_ohne_spanne_einheitlich(server, db):
    """QA B5: obere Grenze 0 → Desktop und Handy zeigen keine Spanne."""
    jahr = date.today().year - 30
    db.speichere_treffer({"id": "alt1", "titel": "Knaus Oldtimer", "preis": 3000, "km": 400000, "ez_jahr": jahr, "ort": "70173 Stuttgart"},
                         "Teilintegrierter")
    db.con.commit()
    c = lokal(server)
    f = next(x for x in c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1] if x["id"] == "alt1")
    assert f["max_ek"] == 0 and f["max_ek_bis"] == 0
    karte = re.search(r'<article[^>]*data-id="alt1".*?</article>', c("GET", "/")[1], re.S).group(0)
    assert "Max-EK (Spanne)" not in karte and "Max-EK</span><b>0 €</b>" in karte.replace("\n", "")


def test_kalibrierung_trennt_den_markenabschlag(cfg):
    """QA B3: Fälle mit Abschlag prüfen den Abschlag, nicht den Händleraufschlag."""
    from wmscout.bewertung import kalibrierung as kal
    p = kal.parameter(cfg)

    def fall(abschlag, vk):
        return {"quelle": "ankauf", "ref": "x", "datum": "2026-01-01", "ek": 30000, "max_ek": 30000, "vk_plan": 38000, "vk": vk,
                "kosten_plan": 4000, "kosten": None, "standzeit_plan": 90, "standzeit": None, "sicherheit": None, "nachgerechnet": False,
                "parameter": p, "abschlag_marke": abschlag}
    b = kal.bericht([fall(0.05, 40000) for _ in range(6)], cfg)                           # verkauft zum Preis ohne Abschlag
    vs = {v["parameter"]: v for v in b["vorschlaege"]}
    assert set(vs) == {"rechner.abschlag_marke_unbekannt"} and vs["rechner.abschlag_marke_unbekannt"]["neu"] == 0.0
    assert kal.bericht([fall(0.05, 38000) for _ in range(6)], cfg)["vorschlaege"] == []   # Abschlag stimmt
    assert {v["parameter"] for v in kal.bericht([fall(0.0, 34000) for _ in range(6)], cfg)["vorschlaege"]} == {"rechner.aufschlag_haendler_vk"}


def test_abschlag_in_annahmen_und_plan():
    """QA B4: Kalkulation nennt den Abschlag; der Plan beim Kauf speichert ihn (für die Kalibrierung)."""
    from wmscout.bewertung import ergebnis
    e = kalk.eingabe(lade_cfg(), {**FZ, "marke": None, "entfernung_km": 50}, _vgl(5), betrag=None, stichtag=STICHTAG, abholung="Firmensitz")
    erg = kalk.rechne(e)
    assert erg["abschlag_marke"] == 0.05 and any("davon − 5% für unbekannte Marke" in z for z in erg["annahmen"])
    assert ergebnis.plan_aus_kalkulation(erg, 1, standzeit_tage=90, differenzbesteuerung=True)["abschlag_marke"] == 0.05
    b = Rechner(lade_cfg(), STICHTAG).bewerte({**FZ, "id": "p", "marke": None}, [])
    assert ergebnis.plan_aus_bewertung(b, 20000, standzeit_tage=90, differenzbesteuerung=True)["abschlag_marke"] == 0.05
    html = (BASIS / "vorlagen" / "anfragen.html").read_text(encoding="utf-8")
    assert "data-marke-unbekannt" in html and "data-maengel" in html and "esc(b.maengel.map(" in html
