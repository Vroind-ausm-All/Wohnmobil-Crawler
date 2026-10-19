"""Datenbank: Migration einer Datenbank im Ur-Schema (ZIP-Stand) ohne Datenverlust, Status-Logik."""
import sqlite3

from wmscout.datenbank import NEUE_SPALTEN, Datenbank

SCHEMA_V1 = """
CREATE TABLE anzeigen (
    id TEXT PRIMARY KEY, url TEXT, suche TEXT, titel TEXT, preis INTEGER, vb INTEGER,
    ort TEXT, km INTEGER, ez_jahr INTEGER, marke TEXT, art TEXT, leistung TEXT, getriebe TEXT,
    kurzbeschreibung TEXT, beschreibung TEXT, gewerblich INTEGER DEFAULT 0, details_json TEXT,
    detail_geladen INTEGER DEFAULT 0, erstmals_gesehen TEXT, zuletzt_gesehen TEXT, preis_vorher INTEGER,
    status TEXT DEFAULT 'neu', notiz TEXT);
"""


def test_migration_v1(tmp_path):
    pfad = tmp_path / "alt.sqlite"
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA_V1)
    con.execute("INSERT INTO anzeigen (id, titel, preis, status, notiz, zuletzt_gesehen) "
                "VALUES ('1', 'Knaus Sky TI 650', 40000, 'kontaktiert', 'alte Notiz', '2026-01-01T10:00:00')")
    con.commit()
    con.close()

    db = Datenbank(str(pfad))
    spalten = {r["name"] for r in db.con.execute("PRAGMA table_info(anzeigen)")}
    assert set(NEUE_SPALTEN) <= spalten
    zeile = db.con.execute("SELECT * FROM anzeigen WHERE id='1'").fetchone()
    assert (zeile["titel"], zeile["preis"], zeile["status"], zeile["notiz"]) == ("Knaus Sky TI 650", 40000,
                                                                                 "kontaktiert", "alte Notiz")
    assert db.setze_status("1", "kontaktiert", text="Hallo", betrag=35000)
    Datenbank(str(pfad))                                       # zweites Öffnen: Migration ist idempotent


def test_status_zuruecksetzen(db):
    db.speichere_treffer({"id": "a", "url": "u", "titel": "t", "preis": 1}, "Alkoven")
    db.setze_status("a", "kontaktiert", text="Hallo", betrag=900)
    db.setze_status("a", "neu")
    z = db.con.execute("SELECT * FROM anzeigen WHERE id='a'").fetchone()
    assert z["status"] == "neu" and z["kontaktiert_am"] is None and z["nachfass_anzahl"] == 0
    assert not db.setze_status("gibtsnicht", "kontaktiert")
