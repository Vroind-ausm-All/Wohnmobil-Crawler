"""P1-04a: SQLite-WAL und Sperr-Wartezeit – Lesende und Schreibende nebeneinander, Sicherung und Wiederherstellung im WAL-Modus."""
from __future__ import annotations

import multiprocessing
import sqlite3
import threading

import pytest

from tests import prozess_helfer
from wmscout.datenbank import STANDARD_WARTEZEIT, Datenbank, wal_aktiv
from wmscout.sicherung import SicherungsFehler, oeffne_lesend, sichere, wiederherstellen


def _treffer(i: int, preis: int = 30000) -> dict:
    return {"id": f"p{i}", "url": f"u{i}", "titel": f"Knaus {i}", "preis": preis}


def _modus(pfad) -> str:
    con = sqlite3.connect(pfad)
    try:
        return con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()


def test_neue_und_bestehende_datenbank_laufen_im_wal_modus(tmp_path):
    neu = tmp_path / "neu.sqlite"
    db = Datenbank(str(neu))
    assert db.journal_modus == "wal" and _modus(neu) == "wal"
    db.con.close()
    alt = tmp_path / "alt.sqlite"                     # Altbestand im bisherigen Modus DELETE
    db = Datenbank(str(alt), wal=False)
    db.speichere_treffer(_treffer(1), "Alkoven")
    db.con.close()
    assert _modus(alt) == "delete"
    db = Datenbank(str(alt))
    assert db.journal_modus == "wal" and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1
    db.con.close()


def test_wal_false_stellt_zurueck_fuer_netzlaufwerke(tmp_path):
    pfad = tmp_path / "a.sqlite"
    Datenbank(str(pfad)).con.close()
    db = Datenbank(str(pfad), wal=False)
    assert db.journal_modus == "delete" and _modus(pfad) == "delete"
    db.con.close()


def test_umstellung_bei_gesperrter_datenbank_warnt_statt_abzubrechen(tmp_path, caplog):
    pfad = tmp_path / "a.sqlite"
    Datenbank(str(pfad), wal=False).con.close()
    leser = sqlite3.connect(pfad, isolation_level=None)
    leser.execute("BEGIN")
    leser.execute("SELECT COUNT(*) FROM anzeigen").fetchone()          # hält eine Lesesperre (Modus DELETE)
    try:
        db = Datenbank(str(pfad), timeout=0.1)
        assert db.journal_modus == "delete"
        assert "Journalmodus wal" in caplog.text
    finally:
        leser.execute("ROLLBACK")
        leser.close()
    db.speichere_treffer(_treffer(1), "Alkoven")                          # arbeitet im alten Modus weiter
    db.con.close()


def test_standard_wartezeit_ist_busy_timeout(tmp_path):
    db = Datenbank(str(tmp_path / "a.sqlite"))
    assert db.con.execute("PRAGMA busy_timeout").fetchone()[0] == int(STANDARD_WARTEZEIT * 1000)
    db.con.close()


def test_config_wal_nur_wahrheitswerte():
    assert wal_aktiv({}) is True and wal_aktiv({"ausgabe": {"wal": False}}) is False
    with pytest.raises(ValueError, match="wal"):
        wal_aktiv({"ausgabe": {"wal": "nein"}})


def test_offene_lesetransaktion_blockiert_den_schreiber_nicht(tmp_path):
    """Kern von WAL: App/Bericht liest (offene Lesetransaktion), Suchlauf schreibt trotzdem sofort – ohne Wartezeit."""
    pfad = str(tmp_path / "a.sqlite")
    leser, schreiber = Datenbank(pfad), Datenbank(pfad, timeout=0)
    leser.speichere_treffer(_treffer(1), "Alkoven")
    leser.con.execute("BEGIN")
    assert leser.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1
    assert schreiber.speichere_treffer(_treffer(2), "Alkoven") == "neu"          # timeout=0: ohne WAL sofort „database is locked“
    assert leser.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1   # Leser sieht seinen festen Stand
    leser.con.execute("COMMIT")
    assert leser.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 2
    leser.con.close()
    schreiber.con.close()


def test_gegenprobe_ohne_wal_blockiert_der_leser(tmp_path):
    """Gegenprobe: Der Test oben prüft wirklich WAL – im alten Modus scheitert derselbe Ablauf."""
    pfad = str(tmp_path / "a.sqlite")
    leser = Datenbank(pfad, wal=False)
    leser.speichere_treffer(_treffer(1), "Alkoven")
    schreiber = Datenbank(pfad, timeout=0, wal=False)
    leser.con.execute("BEGIN")
    leser.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        schreiber.speichere_treffer(_treffer(2), "Alkoven")
    leser.con.execute("COMMIT")
    leser.con.close()
    schreiber.con.close()


def test_threads_mit_eigenen_verbindungen_verlieren_nichts(tmp_path):
    """Suchlauf-Thread, Ereigniseingang und App schreiben gleichzeitig, je mit eigener Verbindung: alle Zeilen kommen an."""
    pfad = str(tmp_path / "a.sqlite")
    Datenbank(pfad).con.close()
    fehler, start = [], threading.Barrier(4)

    def schreibe(nr: int):
        db = Datenbank(pfad)
        try:
            start.wait(10)
            for i in range(50):
                db.speichere_treffer(_treffer(nr * 1000 + i), "Alkoven")
                db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()
        except Exception as e:  # noqa: BLE001 – wird unten gemeldet
            fehler.append(repr(e))
        finally:
            db.con.close()

    threads = [threading.Thread(target=schreibe, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert fehler == []
    db = Datenbank(pfad)
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 200
    assert db.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.con.close()


def test_getrennte_prozesse_schreiben_parallel_ohne_datenverlust(tmp_path):
    """App und geplante Aufgabe (lauf.bat) sind getrennte Prozesse: echte Prozesse über spawn, nicht nur Threads."""
    pfad = str(tmp_path / "a.sqlite")
    Datenbank(pfad).con.close()
    ctx = multiprocessing.get_context("spawn")
    barriere, ergebnisse = ctx.Barrier(3), ctx.Queue()
    prozesse = [ctx.Process(target=prozess_helfer.schreiber, args=(pfad, nr, 40, barriere, ergebnisse)) for nr in range(3)]
    for p in prozesse:
        p.start()
    meldungen = [ergebnisse.get(timeout=120) for _ in prozesse]
    for p in prozesse:
        p.join(30)
    assert sorted(meldungen) == [(0, "ok"), (1, "ok"), (2, "ok")]
    db = Datenbank(pfad)
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 120
    db.con.close()


def test_sicherung_enthaelt_noch_nicht_zurueckgeschriebene_daten_und_ist_eine_datei(tmp_path):
    pfad = tmp_path / "daten" / "anzeigen.sqlite"
    db = Datenbank(str(pfad))
    db.speichere_treffer(_treffer(1), "Alkoven")
    assert (pfad.parent / "anzeigen.sqlite-wal").stat().st_size > 0      # Daten stehen (auch) noch in -wal
    kopie = sichere(pfad, tmp_path / "sicherungen")
    db.con.close()
    assert sorted(p.name for p in kopie.parent.iterdir()) == [kopie.name]  # kein -wal/-shm neben der Sicherung
    con = oeffne_lesend(kopie)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert con.execute("SELECT id FROM anzeigen").fetchall() == [("p1",)]
    finally:
        con.close()


def test_wiederherstellung_bricht_bei_offener_lesetransaktion_ab(tmp_path):
    """Im WAL-Modus übersieht BEGIN EXCLUSIVE Lesende; der Checkpoint erkennt sie. Nichts wird verändert."""
    pfad, ziel = tmp_path / "daten" / "anzeigen.sqlite", tmp_path / "sicherungen"
    db = Datenbank(str(pfad))
    db.speichere_treffer(_treffer(1), "Alkoven")
    kopie = sichere(pfad, ziel)
    db.speichere_treffer(_treffer(2), "Alkoven")
    db.con.execute("BEGIN")
    db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()
    try:
        with pytest.raises(SicherungsFehler, match="in Benutzung"):
            wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, sperr_timeout=0.2)
        assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 2
    finally:
        db.con.execute("COMMIT")
        db.con.close()
    assert len(list(ziel.glob("*vor-wiederherstellung*"))) == 0


def test_wiederherstellung_im_wal_modus_liefert_genau_den_gesicherten_stand(tmp_path):
    """Nach dem Austausch darf kein altes -wal über die zurückgespielte Datenbank laufen."""
    pfad, ziel = tmp_path / "daten" / "anzeigen.sqlite", tmp_path / "sicherungen"
    db = Datenbank(str(pfad))
    db.speichere_treffer(_treffer(1), "Alkoven")
    kopie = sichere(pfad, ziel)
    for i in range(2, 30):
        db.speichere_treffer(_treffer(i, 20000), "Alkoven")
    db.con.close()
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
    db = Datenbank(str(pfad))
    assert [r[0] for r in db.con.execute("SELECT id FROM anzeigen")] == ["p1"]
    assert db.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.journal_modus == "wal"
    db.con.close()
    vorher = next(ziel.glob("*vor-wiederherstellung*.sqlite"))          # der überschriebene Stand ist vollständig gesichert
    con = oeffne_lesend(vorher)
    try:
        assert con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 29
    finally:
        con.close()
