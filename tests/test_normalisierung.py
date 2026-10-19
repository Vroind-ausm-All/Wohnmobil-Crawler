import pytest

from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug, marke_aus_text, modell_aus_text, serie_aus_modell
from wmscout.normalisierung.geo import entfernung_km, plz_aus_text


@pytest.mark.parametrize("titel, marke, modell", [
    ("Fiat Ducato Knaus Sky Ti 650 MEG 2017", "Knaus", "Sky TI 650 MEG"),
    ("Hymer B 678 SL Scheckheft", "Hymer", "B 678 SL"),
    ("Sunlight T68 Teilintegriert EZ 2018", "Sunlight", "T 68"),
    ("VW California Ocean 2016 mit Aufstelldach", "Volkswagen", "California Ocean"),
    ("Poessl Summit 600 Plus", "Pössl", "Summit 600"),
    ("Wohnmobil Dethleffs Trend T 7057 EB", "Dethleffs", "Trend T 7057 EB"),
    ("Hymer ML-T 570 T58", "Hymer", "ML-T 570"),
    ("Knaus Wohnmobil 2015", "Knaus", None),
])
def test_marke_und_modell(titel, marke, modell):
    m = marke_aus_text(titel)
    assert m == marke
    assert modell_aus_text(m, titel) == modell


def test_modell_aus_beschreibung_und_basisfahrzeug():
    a = ergaenze_fahrzeug({"titel": "Wohnmobil zu verkaufen", "marke": "Fiat", "ort": "70173 Stuttgart",
                           "beschreibung": "Wir verkaufen unseren Weinsberg CaraBus 600 MQ"})
    assert a["fahrzeug"] == "Weinsberg CaraBus 600 MQ"
    assert a["serie"] == "CaraBus" and a["plz"] == "70173"
    assert serie_aus_modell("Knaus", "Sky TI 650 MEG") == "Sky TI"


def test_geo():
    assert plz_aus_text("70173 Stuttgart") == "70173" and plz_aus_text("Stuttgart") is None
    assert entfernung_km("70173", "70173") == 0
    assert 560 < entfernung_km("70173", "10115") < 720      # Luftlinie ≈ 510 km, Straße ≈ 630 km
    assert entfernung_km("70173", None) is None
    assert entfernung_km("70173", "70999") is not None       # unbekannte PLZ → Mittel der Region
