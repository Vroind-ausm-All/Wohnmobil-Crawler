"""Abgleich der alten Tabelle ``anzeigen`` (App, Bewertung) mit den v4-Tabellen (``inserate``, ``beobachtungen``,
``preis_historie``): Suchtreffer erscheinen in v4, Ereignisse in der App, Altbestand wird ergänzt – ohne Schemaänderung."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from wmscout.datenbank import IMPORT_SUCHE, Datenbank
from wmscout.ereignis_speicher import EreignisSpeicher
from wmscout.ereignisse import InseratEreignis
from wmscout.migrationen import AKTUELLE_VERSION, lese_version
from wmscout.quellen import Inserat

ZEIT = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _treffer(ad_id="k1", preis=30000, quelle="kleinanzeigen", **mehr) -> dict:
    return {"id": ad_id, "url": f"https://beispiel.invalid/{ad_id}", "titel": "Hymer B 678", "preis": preis, "quelle": quelle, **mehr}


def _ereignis(ad_id="m1", preis=34000, typ="neu", plattform="mobile.de", kanal="api") -> InseratEreignis:
    inserat = None if typ == "geloescht" else Inserat(
        quelle=plattform, anzeigen_id=ad_id, url=f"https://beispiel.invalid/{ad_id}", titel="Knaus Sky TI", preis=preis,
        ez_jahr=2018, km=70000)
    return InseratEreignis(plattform, ad_id, typ, kanal, ZEIT, inserat)


def _eins(db, sql, *p):
    return db.con.execute(sql, p).fetchone()


def _anzahl(db, tabelle) -> int:
    return db.con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


@pytest.fixture
def db(tmp_path):
    d = Datenbank(str(tmp_path / "anzeigen.sqlite"))
    # Ereignisse kommen nur über freigegebene automatische Kanäle (ADR-035); Push-Eingänge prüft tests/test_eingang.py
    for k in ("mobile.de", "kleinanzeigen"):
        d.con.execute("INSERT INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES (?, 'api', 1, 1) "
                      "ON CONFLICT(kennung) DO UPDATE SET zugriffsart='api', freigegeben=1, aktiv=1", (k,))
    d.con.commit()
    yield d
    d.con.close()


def test_suchtreffer_wird_in_v4_gespiegelt_und_nur_aenderungen_protokolliert(db):
    assert db.speichere_treffer(_treffer(), "Alkoven") == "neu"
    i = _eins(db, "SELECT * FROM inserate WHERE plattform='kleinanzeigen' AND anzeigen_id='k1'")
    assert (i["legacy_id"], i["preis"], i["verfuegbarkeit"], i["titel"]) == ("k1", 30000, "aktiv", "Hymer B 678")
    assert [tuple(r) for r in db.con.execute("SELECT kanal, ereignis_typ, preis FROM beobachtungen")] == [("suche", "neu", 30000)]
    assert [tuple(r) for r in db.con.execute("SELECT kanal, preis FROM preis_historie")] == [("suche", 30000)]

    assert db.speichere_treffer(_treffer(), "Alkoven") == "bekannt"           # gleicher Stand: nichts Neues protokolliert
    assert (_anzahl(db, "beobachtungen"), _anzahl(db, "preis_historie"), _anzahl(db, "inserate")) == (1, 1, 1)

    assert db.speichere_treffer(_treffer(preis=28500), "Alkoven") == "preis"
    assert [r[0] for r in db.con.execute("SELECT preis FROM preis_historie ORDER BY id")] == [30000, 28500]
    assert [r[0] for r in db.con.execute("SELECT ereignis_typ FROM beobachtungen ORDER BY id")] == ["neu", "geaendert"]
    assert _eins(db, "SELECT preis FROM anzeigen WHERE id='k1'")[0] == _eins(db, "SELECT preis FROM inserate")[0] == 28500


def test_leere_listenwerte_ueberschreiben_v4_nicht(db):
    db.speichere_treffer(_treffer(), "Alkoven")
    db.speichere_treffer({"id": "k1", "quelle": "kleinanzeigen", "url": "", "titel": None, "preis": None}, "Alkoven")
    i = _eins(db, "SELECT url, titel, preis FROM inserate")
    assert tuple(i) == ("https://beispiel.invalid/k1", "Hymer B 678", 30000)
    assert _anzahl(db, "beobachtungen") == 1


def test_eingelesene_seite_hat_kanal_manuell(db):
    db.speichere_treffer(_treffer("m9", quelle="mobile.de"), IMPORT_SUCHE, kanal="manuell")
    assert tuple(_eins(db, "SELECT plattform, kanal FROM beobachtungen")) == ("mobile.de", "manuell")


def test_ereignis_erscheint_in_der_app_mit_unbekannter_art(db):
    assert EreignisSpeicher(db).verarbeite(_ereignis()) == "neu"
    a = _eins(db, "SELECT * FROM anzeigen WHERE id='m1'")
    assert (a["quelle"], a["preis"], a["suche"], a["status"]) == ("mobile.de", 34000, IMPORT_SUCHE, "neu")
    assert _eins(db, "SELECT legacy_id FROM inserate WHERE anzeigen_id='m1'")[0] == "m1"


def test_ereignis_preisaenderung_und_loeschung_in_der_app(db):
    s = EreignisSpeicher(db)
    s.verarbeite(_ereignis())
    db.setze_status("m1", "kontaktiert", text="Hallo")
    assert s.verarbeite(_ereignis(preis=31000, typ="geaendert")) == "geaendert"
    a = _eins(db, "SELECT preis, preis_vorher, status FROM anzeigen WHERE id='m1'")
    assert tuple(a) == (31000, 34000, "kontaktiert")                           # Preis folgt, Ankaufstatus bleibt
    assert s.verarbeite(_ereignis(typ="geloescht")) == "geloescht"
    assert _eins(db, "SELECT status FROM anzeigen WHERE id='m1'")[0] == "kontaktiert"   # Löschung ändert keinen Ankaufstatus
    assert _eins(db, "SELECT verfuegbarkeit FROM inserate WHERE anzeigen_id='m1'")[0] == "offline"


def test_ereignis_behaelt_eine_bereits_bekannte_art(db):
    db.speichere_treffer(_treffer("m1", quelle="mobile.de"), "Import Alkoven (bestätigt)", kanal="manuell")
    EreignisSpeicher(db).verarbeite(_ereignis(preis=33000, typ="geaendert"))
    assert tuple(_eins(db, "SELECT suche, preis FROM anzeigen WHERE id='m1'")) == ("Import Alkoven (bestätigt)", 33000)
    assert _anzahl(db, "inserate") == 1


def test_erst_ereignis_dann_suche_ergibt_ein_inserat(db):
    EreignisSpeicher(db).verarbeite(_ereignis("x7", plattform="kleinanzeigen"))
    db.speichere_treffer(_treffer("x7", preis=33000), "Alkoven")
    assert _anzahl(db, "inserate") == 1 and _anzahl(db, "anzeigen") == 1
    assert tuple(_eins(db, "SELECT legacy_id, preis FROM inserate")) == ("x7", 33000)


def test_gleiche_id_anderer_plattform_ueberschreibt_die_app_zeile_nicht(db, caplog):
    db.speichere_treffer(_treffer("123", preis=20000), "Alkoven")              # Kleinanzeigen
    db.setze_status("123", "kontaktiert", text="Hallo")
    EreignisSpeicher(db).verarbeite(_ereignis("123", preis=99000))            # mobile.de, zufällig gleiche ID
    a = _eins(db, "SELECT quelle, preis, status FROM anzeigen WHERE id='123'")
    assert tuple(a) == ("kleinanzeigen", 20000, "kontaktiert")
    assert "gehört in „anzeigen“ zu kleinanzeigen" in caplog.text
    rows = db.con.execute("SELECT plattform, legacy_id FROM inserate ORDER BY plattform").fetchall()
    assert [tuple(r) for r in rows] == [("kleinanzeigen", "123"), ("mobile.de", None)]


def test_fehler_beim_spiegeln_rollt_auch_anzeigen_zurueck(db, monkeypatch):
    def kaputt(*a, **k):
        raise sqlite3.OperationalError("simulierter Fehler")

    monkeypatch.setattr(db, "spiegle_inserat", kaputt)
    with pytest.raises(sqlite3.OperationalError):
        db.speichere_treffer(_treffer(), "Alkoven")
    assert _anzahl(db, "anzeigen") == 0 and not db.con.in_transaction


def test_fehler_im_ereignis_rollt_auch_anzeigen_zurueck(db, monkeypatch):
    monkeypatch.setattr(db, "verknuepfe_inserat", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("simuliert")))
    with pytest.raises(sqlite3.OperationalError):
        EreignisSpeicher(db).verarbeite(_ereignis())
    assert (_anzahl(db, "anzeigen"), _anzahl(db, "inserate"), _anzahl(db, "beobachtungen")) == (0, 0, 0)


def test_altbestand_ohne_v4_gegenstueck_wird_beim_oeffnen_ergaenzt(tmp_path):
    """Zeilen, die nach der v4-Migration nur in ``anzeigen`` landeten (alter Code), bekommen beim Öffnen ihr Gegenstück."""
    pfad = str(tmp_path / "anzeigen.sqlite")
    Datenbank(pfad).con.close()
    con = sqlite3.connect(pfad)
    con.executemany("INSERT INTO anzeigen (id, url, titel, preis, quelle, erstmals_gesehen, zuletzt_gesehen) VALUES (?,?,?,?,?,?,?)",
                    [("alt1", "u1", "Bürstner", 25000, "", "2026-10-01T10:00:00", "2026-10-02T10:00:00"),
                     ("alt2", "u2", "Dethleffs", None, "mobile.de", "2026-10-01T10:00:00", "2026-10-01T10:00:00")])
    con.commit()
    vorher = con.execute("SELECT * FROM anzeigen ORDER BY id").fetchall()
    con.close()
    db = Datenbank(pfad)
    rows = db.con.execute("SELECT plattform, anzeigen_id, legacy_id, verfuegbarkeit FROM inserate ORDER BY anzeigen_id").fetchall()
    assert [tuple(r) for r in rows] == [("kleinanzeigen", "alt1", "alt1", "unbekannt"), ("mobile.de", "alt2", "alt2", "unbekannt")]
    assert [tuple(r) for r in db.con.execute("SELECT preis, kanal FROM preis_historie")] == [(25000, "abgleich")]
    assert [tuple(r) for r in db.con.execute("SELECT * FROM anzeigen ORDER BY id")] == [tuple(r) for r in vorher]   # unverändert
    assert db.gleiche_v4_ab() == 0                                            # idempotent
    db.con.close()
    assert lese_version(pfad) == AKTUELLE_VERSION                             # keine neue Schemaversion


def test_abgleich_verknuepft_ein_vorhandenes_ereignis_inserat(tmp_path):
    pfad = str(tmp_path / "anzeigen.sqlite")
    db = Datenbank(pfad)
    db.con.execute("INSERT INTO inserate (plattform, anzeigen_id, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                   "VALUES ('mobile.de', 'v1', 'aktiv', 'x', 'x')")
    db.con.execute("INSERT INTO anzeigen (id, url, titel, preis, quelle) VALUES ('v1', 'u', 't', 1, 'mobile.de')")
    db.con.commit()
    assert db.gleiche_v4_ab() == 0
    assert tuple(_eins(db, "SELECT COUNT(*), MAX(legacy_id) FROM inserate")) == (1, "v1")
    db.con.close()


def test_gesperrte_datenbank_verhindert_das_oeffnen_nicht(tmp_path, caplog):
    pfad = str(tmp_path / "anzeigen.sqlite")
    Datenbank(pfad).con.close()
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO anzeigen (id, url, titel, preis) VALUES ('s1', 'u', 't', 1)")
    con.commit()
    con.execute("BEGIN IMMEDIATE")                                            # anderer Schreiber hält die Sperre
    try:
        db = Datenbank(pfad, timeout=0.1)
        assert "v4-Abgleich übersprungen" in caplog.text
        db.con.close()
    finally:
        con.rollback()
        con.close()
    db = Datenbank(pfad)
    assert _eins(db, "SELECT legacy_id FROM inserate WHERE anzeigen_id='s1'")[0] == "s1"   # beim nächsten Öffnen nachgeholt
    db.con.close()
