"""Offline-Vertragstests: Plattformidentität, Historie, Wiederholung, Freigaben und Migration."""
from datetime import datetime, timezone

import pytest

from tests.daten import FakeAbruf
from wmscout import quellen
from wmscout.ereignis_speicher import QuelleNichtFreigegeben
from wmscout.ereignisse import InseratEreignis
from wmscout.importer import Importer
from wmscout.migrationen import AKTUELLE_VERSION, lese_version, migriere
from wmscout.quellen import Inserat, QuellenFehler
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle


ZEIT = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def ereignis(plattform="mobile.de", anzeigen_id="123", preis=34000, typ="neu",
             kanal="api", ereignis_id=None):
    inserat = None if typ == "geloescht" else Inserat(
        quelle=plattform, anzeigen_id=anzeigen_id, url=f"https://beispiel.invalid/{anzeigen_id}",
        titel="Knaus Sky TI", preis=preis, ez_jahr=2018, km=70000)
    return InseratEreignis(plattform, anzeigen_id, typ, kanal, ZEIT, inserat, ereignis_id)


def _freigeben(db, *kennungen):
    for k in kennungen:
        db.con.execute("INSERT INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES (?, 'api', 1, 1)", (k,))
    db.con.commit()


def test_mehrere_plattformen_mit_gleicher_id_und_preisverlauf(cfg, db):
    importer = Importer(cfg, db)
    _freigeben(db, "mobile.de", "autoscout24")
    assert importer.importiere_ereignis(ereignis()) == "neu"
    assert importer.importiere_ereignis(ereignis("autoscout24")) == "neu"
    assert importer.importiere_ereignis(ereignis()) == "bekannt"
    assert importer.importiere_ereignis(ereignis(preis=32000, typ="geaendert")) == "geaendert"
    assert importer.importiere_ereignis(ereignis(typ="geloescht")) == "geloescht"
    assert importer.importiere_ereignis(ereignis(typ="geloescht")) == "bekannt"
    assert db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0] == 2
    rows = db.con.execute("SELECT plattform, preis, verfuegbarkeit FROM inserate ORDER BY plattform").fetchall()
    assert [(x["plattform"], x["preis"], x["verfuegbarkeit"]) for x in rows] == [
        ("autoscout24", 34000, "aktiv"), ("mobile.de", 32000, "offline")]
    assert [r[0] for r in db.con.execute(
        "SELECT preis FROM preis_historie ORDER BY id").fetchall()] == [34000, 34000, 32000]
    assert db.con.execute("SELECT COUNT(*) FROM beobachtungen").fetchone()[0] == 4


def test_push_kanaele_nie_ueber_den_ereignisspeicher(cfg, db):
    """ADR-035: E-Mail und manuelle Eingaben laufen über Importer.importiere (Regeln zu Art und Anbieter); Plattform und
    Eingangsweg getrennt prüft tests/test_eingang.py."""
    importer = Importer(cfg, db)
    _freigeben(db, "mobile.de")
    for kanal in ("manuell", "email"):
        with pytest.raises(ValueError, match="Push-Eingang"):
            importer.importiere_ereignis(ereignis(kanal=kanal))
    assert db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0] == 0


def test_automatische_ereignisse_nur_nach_expliziter_freigabe(cfg, db):
    importer = Importer(cfg, db)
    live = ereignis(kanal="stream", ereignis_id="v1")
    with pytest.raises(QuelleNichtFreigegeben):
        importer.importiere_ereignis(live)
    assert db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0] == 0
    db.con.execute("""INSERT INTO quellen (kennung, zugriffsart, freigegeben, aktiv)
                      VALUES ('mobile.de','api',1,1)""")
    db.con.commit()
    assert importer.importiere_ereignis(live) == "neu"
    assert importer.importiere_ereignis(live) == "bekannt"
    assert db.con.execute("SELECT COUNT(*) FROM beobachtungen").fetchone()[0] == 1
    db.con.execute("UPDATE quellen SET aktiv=0 WHERE kennung='mobile.de'")
    db.con.commit()
    with pytest.raises(QuelleNichtFreigegeben):
        importer.importiere_ereignis(ereignis(kanal="api", ereignis_id="v2"))


def test_kleinanzeigen_web_gesperrt_auch_mit_fake_und_detailabruf(cfg, db, monkeypatch, ads):
    monkeypatch.setitem(quellen.QUELLEN, "kleinanzeigen", KleinanzeigenQuelle)
    abruf = FakeAbruf(ads)
    importer = Importer(cfg, db, abruf=abruf)
    stat = importer.lauf(cfg["suchen"])
    assert stat["fehler"] and "nicht freigegeben" in stat["fehler"]
    assert abruf.abrufe == []
    db.speichere_treffer({"id": ads[0]["id"], "quelle": "kleinanzeigen",
                         "url": f"https://www.kleinanzeigen.de/s-anzeige/foo/{ads[0]['id']}-220-1234",
                         "titel": "Beispiel"}, "Kastenwagen")
    with pytest.raises(QuellenFehler, match="nicht freigegeben"):
        importer.details()
    assert abruf.abrufe == []


def test_ereignis_validierung(cfg, db):
    with pytest.raises(ValueError, match="unterschiedliche"):
        InseratEreignis("andere", "123", "neu", "email", ZEIT, ereignis().inserat)
    with pytest.raises(ValueError, match="Zeitzone"):
        InseratEreignis("mobile.de", "123", "neu", "email", datetime(2026, 10, 15), ereignis().inserat)
    with pytest.raises(ValueError, match="negativ"):
        ereignis(preis=-100)
    _freigeben(db, "mobile.de")
    assert Importer(cfg, db).importiere_ereignis(ereignis(typ="geloescht")) == "unbekannt"


def test_v4_altdaten_und_ankauf_werden_nicht_veraendert(tmp_path):
    from tests.test_migration import baue_v2, zeilen, sicherungen

    db_pfad = tmp_path / "alt.sqlite"
    baue_v2(db_pfad)
    alt = zeilen(db_pfad, "anzeigen")
    assert migriere(db_pfad, tmp_path / "backups") == [3, 4, 5, 6, 7, 8, 9, 10]
    assert lese_version(db_pfad) == AKTUELLE_VERSION == 10
    assert zeilen(db_pfad, "anzeigen") == alt
    assert len(zeilen(db_pfad, "inserate")) == len(alt)
    assert len(sicherungen(tmp_path / "backups", "alt")) == 1
    assert migriere(db_pfad, tmp_path / "backups") == []
