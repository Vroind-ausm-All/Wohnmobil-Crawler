"""P5-02 – Vergleichsauswahl nach Marke, Modellreihe und Fahrzeugklasse (ADR-053): Länge und Basisfahrzeug aus dem Text,
Ähnlichkeitsstufen und -gewichte, Wirkung auf den Marktfaktor, Erklärung, Konfiguration und nachrechenbare Kalkulation."""
from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from tests.daten import lade_cfg
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.rechner import STANDARD_AEHNLICHKEIT, Rechner, Vergleichsliste
from wmscout.normalisierung.fahrzeug import basisfahrzeug_aus_text, laenge_aus_text

STICHTAG = datetime(2026, 10, 25, 12)
ZIEL = {"id": "ziel", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018,
        "km": 80000, "preis": 50000, "beschreibung": "Länge 7,40 m, Basis Fiat Ducato"}


def _v(i, preis=48000, **k):
    return {"id": f"v{i}", "art": "Teilintegrierter", "ez_jahr": 2018, "km": 80000, "preis": preis,
            "zuletzt_gesehen": "2026-10-20T10:00:00", **k}


@pytest.fixture
def r():
    return Rechner(lade_cfg(), STICHTAG)


# ---------------------------------------------------------------- 1. Fahrzeugklasse aus dem Text
@pytest.mark.parametrize("text, meter", [
    ("Länge 7,40 m, Breite 2,32 m", 7.4), ("Gesamtlänge: 699 cm", 6.99), ("ca. 7,4 m lang", 7.4), ("Länge: 7.40m", 7.4),
    ("Fahrzeuglänge ca. 6,36m", 6.36), ("Länge 7400 mm", 7.4), ("Außenlänge 5,99 m", 5.99),
    ("Bettlänge 1,95 m", None), ("Markisenlänge 4 m", None), ("Länge 2 m", None), ("Länge 59 m²", None), ("Länge 13,5 m", None),
    ("7,40 m Markise", None), ("", None), (None, None),
    # QA P5-02 B3: Zubehör, Stellplatz, Anhänger
    ("Markisen-Länge 4,5 m", None), ("Markise 4,5 m lang", None), ("Stellplatz Länge 8 m", None), ("Kabel Länge 10 m", None),
    ("Länge Anhänger 5,20 m", None), ("Markise 4,5 m lang, Fahrzeug Länge 7,10 m", 7.1), ("Länge über alles 6,99 m", 6.99),
])
def test_laenge_aus_text(text, meter):
    assert laenge_aus_text(text) == meter


@pytest.mark.parametrize("text, basis", [
    ("auf Fiat Ducato 2.3 Multijet", "Fiat Ducato/Citroën Jumper/Peugeot Boxer"), ("Citroen Jumper", "Fiat Ducato/Citroën Jumper/Peugeot Boxer"),
    ("Peugeot Boxer", "Fiat Ducato/Citroën Jumper/Peugeot Boxer"), ("Mercedes-Benz Sprinter 316", "Mercedes Sprinter"),
    ("Ford Transit", "Ford Transit"), ("Iveco Daily 35C", "Iveco Daily"), ("Renault Master", "Renault Master/Opel Movano/Nissan NV400"),
    ("VW Crafter", "VW Crafter/MAN TGE"), ("VW T5 California", "VW Transporter"),
    ("Knaus T5", None), ("Transitbereich", None), ("Boxer Hund an Bord", None), ("Master-Bett", None), ("", None),
    ("Basis Mercedes Sprinter, Tausch gegen Ducato möglich", "Mercedes Sprinter"),        # erste Nennung zählt (QA B4)
])
def test_basisfahrzeug_aus_text(text, basis):
    assert basisfahrzeug_aus_text(text) == basis


# ---------------------------------------------------------------- 2. Ähnlichkeit
def test_stufen_und_gewichte(r):
    erwartet = [
        (_v(1, marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI"), "modell", 2.5),
        (_v(2, marke="knaus", modell="Sky TI 700 MEG", serie="Sky TI"), "reihe", 1.8),
        (_v(3, marke="Knaus", modell="Van TI 550", serie="Van TI"), "marke", 1.0),
        (_v(4, marke="Dethleffs"), "klasse", 0.7),                                    # beide ohne Eintrag: Klasse „Mittel“ (QA B5)
        (_v(5, marke="Hymer"), "andere", 0.5),
        (_v(6), "andere", 0.5),
    ]
    for b, stufe, g in erwartet:
        assert r.aehnlichkeit(ZIEL, b) == (g, stufe)
    hymer = {**ZIEL, "marke": "Hymer", "modell": None, "serie": None}
    assert r.aehnlichkeit(hymer, _v(7, marke="Rapido")) == (0.7, "klasse")         # gleiche Markenklasse „Gehoben“
    assert r.aehnlichkeit(hymer, _v(8, marke="Carthago")) == (0.5, "andere")
    assert r.aehnlichkeit({**ZIEL, "marke": None}, _v(9, marke=None)) == (0.5, "andere")   # Marke unbekannt: keine „gleiche Marke“
    # QA B2: nur das Basisfahrzeug als Marke, Modell ohne Grundriss
    fiat = {**ZIEL, "marke": "Fiat", "modell": "Ducato", "serie": "Ducato"}
    assert r.aehnlichkeit(fiat, _v(10, marke="Fiat", modell="Ducato", serie="Ducato")) == (0.5, "andere")
    reihe = {**ZIEL, "modell": "Sky TI", "serie": "Sky TI"}
    assert r.aehnlichkeit(reihe, _v(11, marke="Knaus", modell="Sky TI", serie="Sky TI")) == (1.8, "reihe")


def test_fahrzeugklasse_im_gewicht(r):
    gleich = dict(marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI")
    assert r.aehnlichkeit(ZIEL, _v(1, beschreibung="Länge 7,40 m", **gleich))[0] == 2.5
    assert r.aehnlichkeit(ZIEL, _v(2, beschreibung="Länge 6,90 m", **gleich))[0] == pytest.approx(2.5 * 0.8)
    assert r.aehnlichkeit(ZIEL, _v(3, beschreibung="Länge 5,40 m", **gleich))[0] == pytest.approx(2.5 * 0.4)     # Untergrenze
    assert r.aehnlichkeit(ZIEL, _v(4, beschreibung="auf Mercedes Sprinter", **gleich))[0] == pytest.approx(2.5 * 0.8)
    assert r.aehnlichkeit(ZIEL, _v(5, beschreibung="Länge 6,90 m auf Mercedes Sprinter", **gleich))[0] == pytest.approx(2.5 * 0.8 * 0.8)
    assert r.aehnlichkeit(ZIEL, _v(6, beschreibung="Fiat Ducato, Länge unbekannt", **gleich))[0] == 2.5   # unbekannt: neutral
    ohne = {**ZIEL, "id": "ohne", "beschreibung": ""}
    assert r.aehnlichkeit(ohne, _v(7, beschreibung="Länge 5,40 m auf Mercedes Sprinter", **gleich))[0] == 2.5


def test_konfiguration_ueberschreibt_einzelne_werte():
    cfg = lade_cfg()
    assert cfg["rechner"]["vergleich_aehnlichkeit"] == STANDARD_AEHNLICHKEIT        # config.yaml nennt genau die Standardwerte
    cfg["rechner"]["vergleich_aehnlichkeit"] = {"andere": 0.1}
    r = Rechner(cfg, STICHTAG)
    assert r.aehnlichkeit(ZIEL, _v(1, marke="Hymer")) == (0.1, "andere") and r.aehnlichkeit(ZIEL, _v(2, marke="Knaus")) == (1.0, "marke")
    del cfg["rechner"]["vergleich_aehnlichkeit"]
    assert Rechner(cfg, STICHTAG).ae == STANDARD_AEHNLICHKEIT


# ---------------------------------------------------------------- 3. Wirkung auf den Marktwert
def _verhaeltnis_gleich(r, a, b, verhaeltnis):
    """Preis so, dass Preis ÷ Referenzwert genau ``verhaeltnis`` ist."""
    return {**b, "preis": round(r.modellwert(b)[0] * verhaeltnis)}


def test_aehnliche_vergleiche_bestimmen_den_marktfaktor(r):
    gleich = [_verhaeltnis_gleich(r, ZIEL, _v(i, marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI"), 1.10) for i in range(3)]
    andere = [_verhaeltnis_gleich(r, ZIEL, _v(10 + i, marke="Hymer"), 0.90) for i in range(7)]
    vgl = r.vergleiche(ZIEL, gleich + andere)
    assert len(vgl) == 10 and [v[3] for v in vgl].count("modell") == 3                 # kein Angebot ausgeschlossen
    mn = r.marktniveau(ZIEL, gleich + andere)
    assert mn["stufen"] == {"modell": 3, "andere": 7} and mn["n_marke"] == 3
    # 3 × 2,5 gegen 7 × 0,5: der gewichtete Median liegt beim gleichen Modell (vorher: 3 × 1,5 gegen 7 × 0,5 → andere Marken)
    assert mn["faktor"] == pytest.approx(10 / 14 * 1.10 + 4 / 14, abs=0.002)


def test_laenge_verschiebt_den_marktfaktor(r):
    kurz = [_verhaeltnis_gleich(r, ZIEL, _v(i, marke="Knaus", beschreibung="Länge 5,99 m"), 0.85) for i in range(4)]
    lang = [_verhaeltnis_gleich(r, ZIEL, _v(10 + i, marke="Knaus", beschreibung="Länge 7,49 m"), 1.05) for i in range(3)]
    mn = r.marktniveau(ZIEL, kurz + lang)
    assert mn["faktor"] == pytest.approx(7 / 11 * 1.05 + 4 / 11, abs=0.002)            # die ähnlich langen geben den Ausschlag
    ohne_laenge = {**ZIEL, "id": "ohne-laenge", "beschreibung": ""}
    assert r.marktniveau(ohne_laenge, kurz + lang)["faktor"] == pytest.approx(7 / 11 * 0.85 + 4 / 11, abs=0.002)   # sonst die Mehrheit


def test_bewertung_erklaert_auswahl_und_fahrzeugklasse(r):
    alle = [_v(1, marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI"), _v(2, marke="Knaus", modell="Sky TI 700", serie="Sky TI"),
            _v(3, marke="Hymer")]
    b = r.bewerte(ZIEL, alle)
    assert b.vergleich_stufen == {"modell": 1, "reihe": 1, "andere": 1} and b.vergleich_marke == 2
    assert b.fahrzeugklasse == {"laenge": 7.4, "basis": "Fiat Ducato/Citroën Jumper/Peugeot Boxer"}
    assert "(1 gleiches Modell, 1 gleiche Modellreihe, 1 andere Marke; ähnlichere zählen mehr)" in b.vergleich_basis
    assert b.vergleich_basis.endswith("· Fahrzeugklasse: 7,40 m, Fiat Ducato/Citroën Jumper/Peugeot Boxer")
    leer = r.bewerte({**ZIEL, "id": "leer", "beschreibung": None}, [])
    assert leer.vergleich_stufen == {} and leer.fahrzeugklasse == {} and "Fahrzeugklasse" not in leer.vergleich_basis
    ohne_ez = r.bewerte({**ZIEL, "id": "ohne-ez", "ez_jahr": None}, alle)
    assert ohne_ez.sicherheit == "keine" and ohne_ez.max_ek == 0


def test_einzelnes_aehnliches_angebot_ueberstimmt_den_markt_nicht():
    """QA P5-02 B1: ein gleiches Modell mit hohem Preis gegen 7 gestreute andere – Faktor nahe an gleichen Gewichten, Sicherheit nicht höher."""
    cfg = lade_cfg()
    neutral = copy.deepcopy(cfg)
    neutral["rechner"]["vergleich_aehnlichkeit"] = {"modell": 1, "reihe": 1, "marke": 1, "klasse": 1, "andere": 1, "basis_anders": 1,
                                                    "laenge_pro_meter": 0}
    erg = {}
    for name, c in (("neu", cfg), ("neutral", neutral)):
        r = Rechner(c, STICHTAG)
        alle = ([_verhaeltnis_gleich(r, ZIEL, _v(0, marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI"), 1.20)]
                + [_verhaeltnis_gleich(r, ZIEL, _v(10 + i, marke="Hymer"), 0.80 + i * 0.05) for i in range(7)])
        erg[name] = (r.marktniveau(ZIEL, alle)["faktor"], r.bewerte(ZIEL, alle).sicherheit)
    assert erg["neu"][0] - erg["neutral"][0] < 0.05                                     # vorher (3,0 gegen 0,4): +0,13
    rang = ["niedrig", "mittel", "hoch"]
    assert rang.index(erg["neu"][1]) <= rang.index(erg["neutral"][1])


@pytest.mark.parametrize("gewichte, erwartet", [
    ([3.0] + [0.4] * 7, [2.8 / 3] + [0.4] * 7), ([2.5] * 3 + [0.5] * 7, [2.5] * 3 + [0.5] * 7), ([1.0, 0.5], [0.5, 0.5]),
    ([5, 5, 1, 1, 1, 1, 1, 1], [3, 3, 1, 1, 1, 1, 1, 1]), ([], []), ([2.0], [2.0]),
])
def test_gedeckelt(gewichte, erwartet):
    from wmscout.bewertung.rechner import gedeckelt
    erg = gedeckelt(gewichte, 0.25)
    assert erg == pytest.approx(erwartet) and (not erg or max(erg) / sum(erg) <= max(0.25, 1 / len(erg)) + 1e-9)


def test_vorfilter_liefert_dasselbe(r):
    alle = [_v(i, preis=40000 + i * 500, marke=["Knaus", "Hymer", "Dethleffs"][i % 3], ez_jahr=2015 + i % 7, km=50000 + i * 3000,
               beschreibung=["Länge 7,10 m", "", "Mercedes Sprinter"][i % 3]) for i in range(40)]
    assert r.vergleiche(ZIEL, Vergleichsliste(alle)) == r.vergleiche(ZIEL, alle)


# ---------------------------------------------------------------- 4. Kalkulation nachrechenbar
def test_kalkulation_friert_aehnlichkeit_und_modell_ein():
    cfg = lade_cfg()
    del cfg["rechner"]["vergleich_aehnlichkeit"]
    alle = [_v(1, marke="Knaus", modell="Sky TI 650 MEG", serie="Sky TI", beschreibung="Länge 7,30 m"),
            *(_v(2 + i, marke="Hymer", preis=42000 + i * 3000) for i in range(4))]
    fahrzeug = {**ZIEL, "entfernung_km": 100}
    e = kalk.eingabe(cfg, fahrzeug, alle, betrag=30000, stichtag=STICHTAG, abholung="Firmensitz")
    assert e["version"] == kalk.VERSION == "E2" and e["rechner"]["vergleich_aehnlichkeit"] == STANDARD_AEHNLICHKEIT
    assert e["vergleich"][0]["modell"] == "Sky TI 650 MEG" and "Länge 7,30 m" in e["vergleich"][0]["beschreibung"]
    gespeichert = json.loads(json.dumps(e))
    erg = kalk.rechne(e)
    assert erg["moeglich"] and "1 gleiches Modell" in erg["vergleich_basis"]
    anders = copy.deepcopy(cfg)
    anders["rechner"]["vergleich_aehnlichkeit"] = {"andere": 0.01, "anteil_max": 1.0}
    assert kalk.rechne(gespeichert) == erg                                               # spätere Gewichte wirken nicht auf die gespeicherte
    assert kalk.rechne(kalk.eingabe(anders, fahrzeug, alle, betrag=30000, stichtag=STICHTAG, abholung="Firmensitz")) != erg
