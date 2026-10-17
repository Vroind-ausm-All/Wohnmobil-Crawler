"""Ende-zu-Ende: Suchlauf → Bewertung → HTML/CSV/Anschreiben-Dateien."""
import csv
from pathlib import Path

from tests.daten import BASIS
from wmscout.ausgabe import schreibe_ausgaben
from wmscout.bewertung.auswertung import bewerte_alle, finde_duplikate
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug


def test_suchlauf_und_ausgaben(cfg, db, importiert):
    assert importiert == {"neu": 60, "preis": 0, "bekannt": 0, "details": 60, "fehler": None, "uebersprungen": []}   # P2-04: neues Feld
    assert finde_duplikate([ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]) == {}, "Testdaten mit Dubletten"
    assert {r["quelle"] for r in db.alle_mit_preis()} == {"kleinanzeigen"}

    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start="2000")
    gesperrt = [z for z in zeilen if z["sperre"] and "Sperrbegriff" in z["sperre"]]
    assert len(gesperrt) == 7 and all(not z["brief"] and not z["bereit"] for z in gesperrt)
    assert all(z["b"].vergleich_anzahl > 0 for z in zeilen)
    assert all(z["a"]["modell"] for z in zeilen)
    assert all(z["a"]["entfernung_km"] is not None for z in zeilen)
    bereit = [z for z in zeilen if z["bereit"]]
    assert bereit and all(z["a"]["fahrzeug"] in z["brief"] and "Vorbehaltlich" in z["brief"] for z in bereit)
    assert any(k.startswith("Abholung (") for k in bereit[0]["b"].kosten_posten)

    erg = schreibe_ausgaben(cfg, zeilen, BASIS)
    ordner = Path(cfg["ausgabe"]["ordner"])
    assert len(list((ordner / "anschreiben").glob("*.txt"))) == len(bereit)
    html = erg["html"].read_text(encoding="utf-8")
    assert "Wohnmobil-Scout" in html and bereit[0]["a"]["fahrzeug"] in html
    with open(erg["csv"], encoding="utf-8-sig") as f:
        tabelle = list(csv.DictReader(f, delimiter=";"))
    assert len(tabelle) == 60 and {"Max-EK", "Erstangebot", "Entfernung km", "Status"} <= set(tabelle[0])


def test_zweiter_lauf_erkennt_bekannte_und_preissenkung(cfg, db, ads, importiert):
    from tests.daten import FakeAbruf
    from wmscout.importer import Importer
    ads[0]["preis"] -= 1000
    stat = Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    assert stat["neu"] == 0 and stat["preis"] == 1 and stat["details"] == 0
    zeile = db.con.execute("SELECT preis, preis_vorher, preis_geaendert_am FROM anzeigen WHERE id=?",
                           (ads[0]["id"],)).fetchone()
    assert zeile["preis_vorher"] - zeile["preis"] == 1000 and zeile["preis_geaendert_am"]
