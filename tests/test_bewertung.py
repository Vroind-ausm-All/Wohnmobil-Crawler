import copy
from datetime import date

import pytest

from tests.daten import BASIS, lade_cfg
from wmscout.bewertung.anschreiben import Anschreiber, euro
from wmscout.bewertung.rechner import Rechner
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug

CFG = lade_cfg()
EZ = date.today().year - 8
FAHRZEUG = {"id": "x", "suche": "Teilintegrierter", "marke": "Knaus", "ez_jahr": EZ, "km": 80000, "preis": 45000,
            "titel": "Knaus Sky TI 650", "beschreibung": "Markise, Solar, keine Feuchtigkeit, rostfrei"}


@pytest.fixture
def vergleich():
    r = Rechner(copy.deepcopy(CFG))
    liste = []
    for i in range(20):
        b = {"id": f"v{i}", "suche": "Teilintegrierter", "marke": "Knaus" if i % 2 else "Hymer",
             "ez_jahr": EZ + (i % 5) - 2, "km": 60000 + i * 3000, "titel": "Vergleich", "zuletzt_gesehen": "2999"}
        b["preis"] = int(r.modellwert(b)[0] * 1.2)          # Markt liegt 20 % über dem Referenzmodell
        liste.append(b)
    liste.append({**liste[0], "id": "ausreisser", "preis": 999999})
    return liste


def test_wertfaktoren_und_verneinung():
    r = Rechner(copy.deepcopy(CFG))
    assert set(r.wertfaktoren(FAHRZEUG)) == {"Markise", "Solaranlage"}
    for text, erwartet in [("Feuchtigkeit im Heck", {"Feuchtigkeit"}), ("feuchtigkeitsfrei", set()),
                           ("Feuchtigkeitsmessung ohne Befund", set()), ("keine Risse, Feuchtigkeit oder Rost", set()),
                           ("Kein Rost, aber Feuchtigkeit hinten", {"Feuchtigkeit"}), ("Rostschutz neu", set())]:
        assert set(r.wertfaktoren({"beschreibung": text})) == erwartet, text


def test_bewertung_ohne_vergleiche():
    b = Rechner(copy.deepcopy(CFG)).bewerte(FAHRZEUG, [])
    assert b.sicherheit == "niedrig" and b.vergleich_anzahl == 0 and b.ampel in ("gruen", "gelb", "rot")
    assert b.marktwert_angebote == round(b.modellwert / 50) * 50


def test_vergleiche_kalibrieren_markt(vergleich):
    cfg = copy.deepcopy(CFG)
    b = Rechner(cfg).bewerte(FAHRZEUG, vergleich)
    g = 20 / (20 + cfg["rechner"]["vergleich_gewicht_k"])
    assert b.vergleich_anzahl == 20                          # Ausreißer entfernt
    assert abs(b.marktfaktor - (1 + 0.2 * g)) < 0.01
    assert b.sicherheit == "hoch"


@pytest.mark.parametrize("preis", [15000, 30000, 45000, 60000])
@pytest.mark.parametrize("jahre", [2, 8, 15, 22])
def test_fairness(vergleich, preis, jahre):
    cfg = copy.deepcopy(CFG)
    x = {**FAHRZEUG, "id": f"f{preis}{jahre}", "preis": preis, "ez_jahr": date.today().year - jahre}
    b = Rechner(cfg).bewerte(x, vergleich)
    assert b.erstangebot <= preis and b.erstangebot <= b.max_ek
    boden = cfg["rechner"]["fair_untergrenze_privatwert"] * b.marktwert_privat
    assert b.erstangebot >= min(boden, b.max_ek, preis * 0.95) - 100


def test_ohne_erstzulassung_kein_betrag(vergleich):
    cfg = copy.deepcopy(CFG)
    ohne = {**FAHRZEUG, "id": "ohne", "ez_jahr": None}
    b = Rechner(cfg).bewerte(ohne, vergleich)
    assert b.ampel == "grau" and b.sicherheit == "keine"
    text = Anschreiber(cfg, BASIS).text(ergaenze_fahrzeug(ohne), b)
    assert "€" not in text and "Erstzulassung" in text


def test_transport_nach_entfernung():
    cfg = copy.deepcopy(CFG)
    a = {"id": "t", "suche": "Kastenwagen", "ez_jahr": date.today().year - 5, "km": 50000, "entfernung_km": 300}
    k = cfg["rechner"]["kosten"]
    posten = Rechner(cfg).kosten(a, 40000)
    assert posten["Abholung (300 km)"] == round((k["transport_grundpauschale"] + 300 * k["transport_pro_km"]) / 10) * 10
    assert Rechner(cfg).kosten({**a, "entfernung_km": None}, 40000)["Transport"] == k["transport_pauschal"]


def test_anschreiben_passt_zu_modell_und_baujahr():
    cfg = copy.deepcopy(CFG)
    ez = date.today().year - 9
    a = ergaenze_fahrzeug({"id": "y", "suche": "Teilintegrierter", "titel": "Knaus Sky TI 650 MEG Platinum",
                           "ez_jahr": ez, "km": 85000, "preis": 52000, "vb": True, "ort": "70173 Stuttgart",
                           "beschreibung": "Markise, Rückfahrkamera, Scheckheft"})
    b = Rechner(cfg).bewerte(a, [])
    t = Anschreiber(cfg, BASIS).text(a, b)
    for teil in (f"Knaus Sky TI 650 MEG (EZ {ez}, rund 85.000 km)", "Vorbehaltlich einer Besichtigung",
                 euro(b.erstangebot), "unverbindlich", "Markise und Rückfahrkamera", "das Scheckheft",
                 f"Wohnmobil aus {ez}", "Besichtigung in Stuttgart", "gewerblicher Ankäufer"):
        assert teil in t
    if b.ampel != "gruen":
        assert "Wunschpreis von 52.000 €" in t
    jung = ergaenze_fahrzeug({**a, "id": "z", "ez_jahr": date.today().year - 2, "beschreibung": ""})
    assert "Dichtigkeitsgarantie" in Anschreiber(cfg, BASIS).text(jung, Rechner(cfg).bewerte(jung, []))
