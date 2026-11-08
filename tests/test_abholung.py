"""P5-06 – Abholung ab Firmensitz mit dem Auto oder ab Stuttgart Hbf mit der Bahn (ADR-057): Kosten, Reisezeiten, Übernachtung,
günstigerer Weg, Konfiguration, Kalkulation E6, Händlerstandorte, Oberfläche."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime

import pytest

from tests.daten import BASIS, lade_cfg
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.rechner import STANDARD_ABHOLUNG, Rechner, abholung_einstellungen, bahn_entfernung
from wmscout.normalisierung.geo import entfernung_km

OKTOBER = datetime(2026, 10, 25, 12)
FZ = {"id": "x", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018, "km": 80000,
      "preis": 40000}
VGL = [{"id": f"v{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": 46000 + i * 400,
        "zuletzt_gesehen": "2026-10-20T10:00:00"} for i in range(9)]


def _a(plz: str) -> dict:
    return {"plz": plz, "entfernung_km": entfernung_km("74354", plz)}


def _cfg(**abholung) -> dict:
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["abholung"].update(abholung)
    return cfg


# ---------------------------------------------------------------- 1. Konfiguration
def test_standort_besigheim_und_stuttgart_hbf():
    cfg = lade_cfg()
    assert cfg["anschreiben"]["plz"] == "74354" and cfg["rechner"]["kosten"]["abholung"]["bahn"]["ab_plz"] == "70173"
    assert abholung_einstellungen(cfg["rechner"]["kosten"]["abholung"])["bahn"]["ab_name"] == "Stuttgart Hbf"


@pytest.mark.parametrize("roh, erwartet", [(None, None), (False, None)])
def test_ohne_abschnitt_alte_formel(roh, erwartet):
    assert abholung_einstellungen(roh) is erwartet
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["abholung"] = roh
    k = cfg["rechner"]["kosten"]
    assert Rechner(cfg).transport({"entfernung_km": 200}) == k["transport_grundpauschale"] + 200 * k["transport_pro_km"]


def test_standardwerte_und_bahn_aus():
    voll = abholung_einstellungen(True)
    assert voll["auto"] == STANDARD_ABHOLUNG["auto"] and voll["bahn"] is None             # ohne Bahn-Eintrag keine Bahn-Variante
    assert abholung_einstellungen({"bahn": True})["bahn"] == STANDARD_ABHOLUNG["bahn"]
    assert abholung_einstellungen({"bahn": {}})["bahn"]["ticket_max"] == 160
    assert abholung_einstellungen({"bahn": False})["bahn"] is None


@pytest.mark.parametrize("roh, teil", [
    ("ja", "muss ein Abschnitt"), ({"auto": 5}, "auto muss"), ({"bahn": "x"}, "bahn muss"), ({"stundensatz": -1}, "stundensatz"),
    ({"wohnmobil_kmh": 0}, "wohnmobil_kmh"), ({"tag_max_stunden": 0}, "tag_max_stunden"), ({"stundensatz": "25"}, "stundensatz"),
    ({"auto": {"pkw_kmh": 0}}, "pkw_kmh"), ({"bahn": {"ab_plz": "7017"}}, "ab_plz"), ({"bahn": {"ticket_min": 200}}, "ticket_min"),
    ({"bahn": {"kmh": True}}, "kmh"),
    ({"stundensatz": float("nan")}, "stundensatz"), ({"stundensatz": float("inf")}, "stundensatz"),                    # QA B3
    ({"stundensaz": 99}, "unbekannte Einträge stundensaz"), ({"auto": {"pkw_km": 1}}, "auto -> unbekannte Einträge pkw_km"),
    ({"bahn": {"ab_plaz": "1"}}, "bahn -> unbekannte Einträge ab_plaz"), ({"auto": False}, "auto muss"),
    ({"bahn": {"ab_plz": "00000"}}, "ab_plz"), ({"bahn": {"zubringer_max_km": 0}}, "zubringer_max_km"),
])
def test_fehleingaben_verstaendlich(roh, teil):
    with pytest.raises(ValueError, match=re.escape(teil)):
        abholung_einstellungen(roh)
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["abholung"] = roh
    with pytest.raises(ValueError, match="config.yaml: rechner -> kosten -> abholung"):
        Rechner(cfg)


# ---------------------------------------------------------------- 2. Rechnung
def test_formel_auto_und_bahn():
    """Nachgerechnet mit den Werten aus config.yaml für 200 km (Auto) und 220 km (Bahn ab Stuttgart Hbf)."""
    ab = Rechner(lade_cfg()).abholung({"entfernung_km": 200, "entfernung_bahn_km": 220})
    auto, bahn = ab["varianten"]
    je_person = 200 / 90 + 1.0 + 200 / 80
    assert auto["euro"] == pytest.approx(2 * 200 * 0.30 + 200 * 0.25 + 2 * je_person * 25) and auto["uebernachtungen"] == 0
    reise = 0.5 + 220 / 110 + 0.75
    assert bahn["ticket"] == pytest.approx(66) and bahn["reise_stunden"] == pytest.approx(reise)
    assert bahn["euro"] == pytest.approx(6 + 66 + 200 * 0.25 + (reise + 1.0 + 200 / 80) * 25) and ab["gewaehlt"] == "bahn"


@pytest.mark.parametrize("plz, weg", [("74321", "auto"), ("74354", "auto"), ("80331", "bahn"), ("20095", "bahn"), ("50667", "bahn")])
def test_guenstigerer_weg_zaehlt(plz, weg):
    r = Rechner(lade_cfg())
    ab = r.abholung(_a(plz))
    assert ab["gewaehlt"] == weg and r.transport(_a(plz)) == min(v["euro"] for v in ab["varianten"])


def test_ticket_grenzen_und_uebernachtung():
    r = Rechner(lade_cfg())
    nah = r.abholung({"entfernung_km": 10, "entfernung_bahn_km": 5})["varianten"][1]
    weit = r.abholung(_a("20095"))                                       # Hamburg: Flexpreis-Obergrenze, an einem Tag nicht zu schaffen
    assert nah["ticket"] == 12 and weit["varianten"][1]["ticket"] == 160
    assert all(v["uebernachtungen"] == 1 for v in weit["varianten"])
    ohne = Rechner(_cfg(tag_max_stunden=30)).abholung(_a("20095"))
    assert all(v["uebernachtungen"] == 0 for v in ohne["varianten"]) and ohne["varianten"][1]["euro"] == pytest.approx(
        weit["varianten"][1]["euro"] - 90)


def test_teurer_wenn_weiter():
    r = Rechner(lade_cfg())
    kosten = [r.transport(_a(p)) for p in ("74321", "70173", "80331", "50667", "20095")]
    assert kosten == sorted(kosten)


def test_ohne_entfernung_pauschale_und_ohne_bahn():
    r = Rechner(lade_cfg())
    assert r.abholung({"plz": None, "entfernung_km": None}) is None
    assert r.kosten({"entfernung_km": None, "ez_jahr": 2018}, 40000)["Transport"] == 300
    nur_auto = r.abholung({"entfernung_km": 300, "entfernung_bahn_km": None})        # z. B. ab einem Händlerstandort
    assert [v["art"] for v in nur_auto["varianten"]] == ["auto"]
    assert [v["art"] for v in Rechner(_cfg(bahn=False)).abholung(_a("80331"))["varianten"]] == ["auto"]
    assert bahn_entfernung(_cfg(bahn=False)["rechner"], "80331") is None and bahn_entfernung(lade_cfg()["rechner"], None) is None


def test_posten_beschriftung():
    r = Rechner(lade_cfg())
    nah, weit = _a("74321"), _a("80331")
    assert f"Abholung (Auto, {nah['entfernung_km']} km)" in r.kosten({**nah, "ez_jahr": 2018}, 40000)
    assert f"Abholung (Bahn ab Stuttgart Hbf, {weit['entfernung_km']} km zurück)" in r.kosten({**weit, "ez_jahr": 2018}, 40000)


def test_bewertung_gerundet():
    b = Rechner(lade_cfg(), OKTOBER).bewerte({**FZ, **_a("80331")}, VGL)
    assert b.abholung["gewaehlt"] == "bahn"
    for v in b.abholung["varianten"]:
        assert v["euro"] % 10 == 0 and (v["stunden"] * 4).is_integer()
    bahn = b.abholung["varianten"][1]
    assert bahn["ticket"] % 5 == 0 and bahn["ticket"] >= 12 and (bahn["reise_stunden"] * 4).is_integer()
    assert Rechner(_cfg(), OKTOBER).bewerte({**FZ, "plz": None, "entfernung_km": None}, VGL).abholung is None


# ---------------------------------------------------------------- 3. Kalkulation E6
def test_kalkulation_e6_friert_ein_ohne_plz():
    cfg = lade_cfg()
    vorher = copy.deepcopy(cfg)
    e = kalk.eingabe(cfg, {**FZ, **_a("80331")}, VGL, betrag=30000, stichtag=OKTOBER, abholung="ab Firmensitz")
    assert cfg == vorher and e["version"] == kalk.VERSION and int(kalk.VERSION[1:]) >= 6
    assert "plz" not in e["fahrzeug"] and e["fahrzeug"]["entfernung_bahn_km"] == round(entfernung_km("70173", "80331"), -1)
    assert e["fahrzeug"]["entfernung_km"] % 10 == 0                     # QA B2: gerundet, sonst ließe sich die PLZ zurückrechnen
    assert e["rechner"]["kosten"]["abholung"]["bahn"]["zubringer_km"] == entfernung_km("74354", "70173")
    erg = kalk.rechne(json.loads(json.dumps(e)))
    assert erg["abholung"]["gewaehlt"] == "bahn" and erg == kalk.rechne(e)
    text = " ".join(erg["annahmen"])
    assert "ICE-Ticket ca." in text and "gerechnet: Bahn" in text and "Rückfahrt im Wohnmobil ca." in text


def test_kalkulation_haendlerstandort_ohne_bahn_und_alte_eingabe():
    e = kalk.eingabe(lade_cfg(), {**FZ, "plz": "80331", "entfernung_km": 40, "entfernung_bahn_km": None}, VGL, betrag=None,
                     stichtag=OKTOBER, abholung="ab Standort München")
    assert [v["art"] for v in kalk.rechne(e)["abholung"]["varianten"]] == ["auto"]
    alt = copy.deepcopy(e)                                                   # gespeicherte E5-Eingabe kannte keine Abholung
    alt["rechner"]["kosten"].pop("abholung")
    erg = kalk.rechne(alt)
    k = alt["rechner"]["kosten"]
    assert erg["abholung"] is None and "Abholung (40 km) " in " ".join(erg["annahmen"])
    b = Rechner({"rechner": alt["rechner"]}, OKTOBER).kosten({"entfernung_km": 40, "ez_jahr": 2018}, 40000)
    assert b["Abholung (40 km)"] == round((k["transport_grundpauschale"] + 40 * k["transport_pro_km"]) / 10) * 10


@pytest.mark.parametrize("h, text", [(0.25, "15 Min."), (1, "1 Std."), (3.75, "3 Std. 45 Min."), (12.5, "12 Std. 30 Min.")])
def test_stunden_text(h, text):
    assert kalk.stunden_text(h) == text


# ---------------------------------------------------------------- 4. Oberfläche
def test_detail_zeigt_abholung(server, db):
    jahr = date.today().year - 8
    for i in range(5):
        db.speichere_treffer({"id": f"p{i}", "titel": f"Knaus Sky TI {i}", "preis": 40000 + i * 300, "km": 60000 + i * 7000, "ez_jahr": jahr,
                              "ort": "80331 München"}, "Teilintegrierter")
    db.speichere_treffer({"id": "z1", "titel": "Knaus Sky TI", "preis": 30000, "km": 100000, "ez_jahr": jahr, "ort": "80331 München"},
                         "Teilintegrierter")
    db.con.commit()
    c = lokal(server)
    detail = re.search(r'<section id="dz1".*?</section>', c("GET", "/")[1], re.S).group(0)
    assert "data-abholung" in detail and "Bahn ab Stuttgart Hbf" in detail and "ICE-Ticket ca." in detail and "✓ gerechnet" in detail
    assert "Abholung (Bahn ab Stuttgart Hbf" in detail
    d = c("GET", "/api/fahrzeug/z1")[1]
    assert d["bewertung"]["abholung"]["gewaehlt"] == "bahn"


# ---------------------------------------------------------------- 5. Korrekturrunde (QA P5-06)
def test_firmensitz_weit_vom_bahnhof_ohne_bahn():
    """B1: Mandant mit Sitz in Hamburg – Bahn ab Stuttgart Hbf entfällt mit Hinweis, statt die Anreise nach Stuttgart zu vergessen."""
    cfg = lade_cfg()
    cfg["anschreiben"]["plz"] = "20095"
    a = {"plz": "70173", "entfernung_km": entfernung_km("20095", "70173")}
    ab = Rechner(cfg).abholung(a)
    assert [v["art"] for v in ab["varianten"]] == ["auto"] and "nicht gerechnet" in ab["hinweis"] and "Stuttgart Hbf" in ab["hinweis"]
    e = kalk.eingabe(cfg, {**FZ, **a}, VGL, betrag=None, stichtag=OKTOBER, abholung="ab Firmensitz")
    erg = kalk.rechne(e)
    assert [v["art"] for v in erg["abholung"]["varianten"]] == ["auto"] and "nicht gerechnet" in " ".join(erg["annahmen"])
    nah = Rechner(lade_cfg()).abholung(_a("80331"))
    assert nah["hinweis"] is None and nah["gewaehlt"] == "bahn"                  # Besigheim liegt nah genug an Stuttgart Hbf


def test_einfrieren_gegen_geaenderte_standardwerte(monkeypatch):
    """Nur wenige Einträge in config.yaml – spätere Code-Standards ändern gespeicherte Kalkulationen nicht."""
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["abholung"] = {"bahn": {}}
    e = kalk.eingabe(cfg, {**FZ, **_a("80331")}, VGL, betrag=30000, stichtag=OKTOBER, abholung="ab Firmensitz")
    vorher = kalk.rechne(e)
    monkeypatch.setitem(STANDARD_ABHOLUNG, "stundensatz", 99)
    monkeypatch.setitem(STANDARD_ABHOLUNG["bahn"], "ticket_pro_km", 9)
    assert kalk.rechne(e) == vorher


def test_echte_e5_eingabe_rechnet_unveraendert():
    """Eine E5-Eingabe kennt weder ``kosten.abholung`` noch ``entfernung_bahn_km`` – alte Formel, gleiche Kosten."""
    e = kalk.eingabe(lade_cfg(), {**FZ, **_a("80331")}, VGL, betrag=30000, stichtag=OKTOBER, abholung="ab Firmensitz")
    e["rechner"]["kosten"].pop("abholung")
    e["fahrzeug"].pop("entfernung_bahn_km")
    e["version"] = "E5"
    erg = kalk.rechne(e)
    k, km = e["rechner"]["kosten"], e["fahrzeug"]["entfernung_km"]
    assert erg["abholung"] is None
    assert f"Abholung ({km} km) {kalk._eur(round((k['transport_grundpauschale'] + km * k['transport_pro_km']) / 10) * 10)}" in " ".join(erg["annahmen"])


def test_nahverkehrsticket_und_beschriftung():
    """B4: im Nahbereich kein „ICE-Ticket“; B6: km mit Tausenderpunkt (Vorlage)."""
    r = Rechner(lade_cfg())
    assert r.abholung(_a("70173"))["varianten"][1]["ticket_art"] == "Nahverkehrsticket"
    assert r.abholung(_a("80331"))["varianten"][1]["ticket_art"] == "ICE-Ticket"
    assert "{{ v.km | tsd }}" in (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("h, text", [(0.999, "1 Std."), (1.999, "2 Std."), (0.01, "1 Min."), (2.5, "2 Std. 30 Min.")])
def test_stunden_text_ohne_60_minuten(h, text):
    assert kalk.stunden_text(h) == text                                                     # B5
