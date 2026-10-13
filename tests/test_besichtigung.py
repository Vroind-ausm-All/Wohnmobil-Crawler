"""Besichtigungsmodus: Mängelabzug (verbindliche Python-Rechnung)."""
from datetime import date

import pytest

from tests.daten import BASIS
from wmscout.bewertung.besichtigung import berechne, dot_alter_jahre, lade_katalog, mangel_index

KATALOG = lade_katalog(BASIS / "maengel.yaml")
HEUTE = date(2026, 10, 13)
GRUND = {"angebot": 32300, "max_ek": 35100, "marktwert_privat": 43000, "reparaturrisiko": 1500,
         "differenzbesteuerung": True, "km_anzeige": 85000}


def vollstaendig(**extra) -> dict:
    """Alle Pflichtpunkte erledigt, keine Mängel."""
    d = {"pruefpunkte": {p["key"]: True for p in KATALOG["pruefpunkte"]},
         "messungen": {"feuchtigkeit": [{"bereich": f"Punkt {i}", "wert": 11} for i in range(8)],
                       "reifen": [{"position": p, "dot": "2224"} for p in ("VL", "VR", "HL", "HR")]},
         "km_abgelesen": 85400, "maengel": []}
    d.update(extra)
    return d


def test_katalog_ist_konsistent():
    idx = mangel_index(KATALOG)
    assert len(idx) == sum(len(k["maengel"]) for k in KATALOG["kategorien"]), "doppelte Schlüssel"
    for m in idx.values():
        arten = [a for a in ("stufen", "betrag", "prozent", "frei") if a in m]
        assert len(arten) == 1, m
        if "stufen" in m:
            assert set(m["stufen"]) <= {"leicht", "mittel", "schwer"}


def test_ohne_maengel_bleibt_angebot():
    e = berechne(KATALOG, vollstaendig(), GRUND, HEUTE)
    assert e["vollstaendig"] and e["posten"] == [] and e["ek_abzug"] == 0
    assert e["vorschlag"] == 32300 and e["max_ek_neu"] == 35100


def test_abzug_mit_risikoanrechnung_und_25a():
    d = vollstaendig(maengel=[{"key": "delamination", "stufe": "mittel"}, {"key": "schluessel"}])
    e = berechne(KATALOG, d, GRUND, HEUTE)
    assert e["summe_maengel"] == 4000 + 300
    assert e["risiko_gutschrift"] == 750                      # 50 % von 1.500 €
    assert e["netto_abzug"] == 3550
    assert e["ek_abzug"] == 4220                              # 3.550 × 1,19 = 4.224,50 → 4.220
    assert e["max_ek_neu"] == 35100 - 4220
    assert e["vorschlag"] == 28050                            # 32.300 − 4.220 = 28.080 → auf 50 abgerundet
    assert e["ko"] == []


def test_regelbesteuerung_ohne_faktor():
    d = vollstaendig(maengel=[{"key": "zahnriemen"}])
    e = berechne(KATALOG, d, {**GRUND, "differenzbesteuerung": False}, HEUTE)
    assert e["ek_faktor"] == 1.0 and e["ek_abzug"] == 900 - 750


def test_messwerte_ergeben_stufen():
    d = vollstaendig()
    d["messungen"]["feuchtigkeit"] += [{"bereich": "Heck links", "wert": 17}, {"bereich": "Heck links", "wert": 24},
                                       {"bereich": "Bad", "wert": 35}]
    d["messungen"]["reifen"][0]["dot"] = "1518"            # 2018 → älter als 6 Jahre
    e = berechne(KATALOG, d, GRUND, HEUTE)
    namen = {p["name"]: (p["stufe"], p["betrag"]) for p in e["posten"]}
    assert namen["Feuchtigkeit Heck links (24 %)"] == ("mittel", 1800)   # höchster Wert je Bereich
    assert namen["Feuchtigkeit Bad (35 %)"] == ("schwer", 5000)
    assert namen["Reifen VL 8,5 Jahre alt"] == (None, 190)


def test_km_abweichung_und_prozent_maengel():
    d = vollstaendig(km_abgelesen=105000, maengel=[{"key": "serviceheft"}])
    e = berechne(KATALOG, d, GRUND, HEUTE)
    betraege = {p["name"]: p["betrag"] for p in e["posten"]}
    assert betraege["20.000 km mehr als in der Anzeige"] == 1290          # 43.000 × 1,5 % × 2
    assert betraege["Serviceheft/Wartungsnachweise fehlen"] == 860         # 2 % von 43.000


def test_freier_betrag_ueberschreibung_und_anpassung():
    d = vollstaendig(maengel=[{"key": "ausstattung_fehlt", "name": "Markise fehlt", "betrag": 800},
                              {"key": "bremsen", "stufe": "leicht", "betrag": 450}],
                     anpassung={"betrag": -200, "grund": "neue Batterie"})
    e = berechne(KATALOG, d, GRUND, HEUTE)
    assert [p["name"] for p in e["posten"]] == ["Markise fehlt", "Bremsen verschlissen"]
    assert e["summe_maengel"] == 1250 and e["anpassung"] == -200 and e["netto_abzug"] == 1250 - 750 - 200


def test_ko_maengel():
    d = vollstaendig(maengel=[{"key": "rost", "stufe": "mittel"}, {"key": "delamination", "stufe": "schwer"},
                              {"key": "faeulnis"}])
    e = berechne(KATALOG, d, GRUND, HEUTE)
    assert e["ko"] == ["Delamination an Wand oder Dach", "Fäulnis im Holz (Wasserschaden)"]


def test_vorschlag_nie_ueber_max_ek_und_nie_negativ():
    e = berechne(KATALOG, vollstaendig(), {**GRUND, "angebot": 40000}, HEUTE)
    assert e["vorschlag"] == 35100
    e = berechne(KATALOG, vollstaendig(maengel=[{"key": "faeulnis", "betrag": 90000}]), GRUND, HEUTE)
    assert e["vorschlag"] == 0


def test_pflichtpunkte_fehlen():
    e = berechne(KATALOG, {"pruefpunkte": {"fin": True}, "messungen": {"feuchtigkeit": [{"wert": 12}]}}, GRUND, HEUTE)
    assert not e["vollstaendig"]
    assert any("Feuchtigkeitsmessung" in f and "erfasst 1" in f for f in e["fehlende_pflicht"])
    assert "Probefahrt durchgeführt (Bremsen, Lenkung, Getriebe, Geräusche)" in e["fehlende_pflicht"]
    assert not any(f.startswith("FIN") for f in e["fehlende_pflicht"])


@pytest.mark.parametrize("dot, alter", [("2318", 8.4), ("0124", 2.8), ("5224", 1.8), ("9918", None), ("12", None),
                                        ("0130", None)])
def test_dot_alter(dot, alter):
    assert dot_alter_jahre(dot, HEUTE) == alter


def test_unbekannte_und_unvollstaendige_eingaben():
    d = vollstaendig(maengel=[{"key": "gibtsnicht"}, {"key": "bremsen"}], )
    d["messungen"]["reifen"].append({"position": "Reserve", "dot": "abc"})
    e = berechne(KATALOG, d, GRUND, HEUTE)
    assert e["posten"] == [] and len(e["hinweise"]) == 3
