"""P3-01 (ADR-039): Fahrzeuge getrennt von Inseraten – Migration auf Schema 11 ohne Datenverlust, Trigger für neue Inserate, Fassade.

Geprüft wird gegen Altbestände der Versionen 1 (ZIP-Stand), 2 (vor Phase 1) und 10 (heutiger Stand). Jedes Inserat bekommt genau ein eigenes
Fahrzeug; es wird nichts zusammengeführt. Der Ankaufsstatus bleibt am Inserat (``anzeigen``/``bearbeitung``).
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.nachgebildet_mails import nachgebildet_ka_mail
from tests.test_eingang import roh as seite_roh
from tests.test_ereignisse import _freigeben, ereignis
from tests.test_mandanten import grund  # noqa: F401 – Fixture
from tests.test_migration import baue_v1, baue_v2, pruefsumme, tabellen, versionen
from tests.test_seitenimport import detailseite
from tests.test_text_import import KA_TEXT, KA_URL
from wmscout import mandanten, migrationen
from wmscout.datenbank import Datenbank
from wmscout.eingang import Rohdaten, SeitenEingang, TextEingang
from wmscout.eingang.email import MailEingang
from wmscout.importer import Importer
from wmscout.migrationen import AKTUELLE_VERSION, MigrationsFehler, lese_version, migriere
from wmscout.sicherung import sicherungen, wiederherstellen

JETZT = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- Hilfen
def _abbild(pfad, spalten: dict | None = None) -> dict:
    """Inhalt aller Tabellen (außer schema_version): {Tabelle: (Spalten, sortierte Zeilen)}. Mit ``spalten`` nur diese Spalten
    (so lässt sich ein Stand nach der Migration ohne die neue Spalte mit dem Stand davor vergleichen)."""
    con = sqlite3.connect(pfad)
    try:
        ergebnis = {}
        for t in sorted(tabellen(pfad) - {"schema_version"}):
            alle = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            if spalten is not None and t not in spalten:
                continue
            nutze = spalten[t] if spalten is not None else alle
            zeilen = sorted((repr(tuple(r)) for r in con.execute(f"SELECT {', '.join(nutze)} FROM {t}")))
            ergebnis[t] = (nutze, zeilen)
        return ergebnis
    finally:
        con.close()


def _nachher_wie_vorher(pfad, vorher: dict) -> dict:
    return _abbild(pfad, {t: c for t, (c, _) in vorher.items()})


def _alt_schritte(monkeypatch, bis: int):
    monkeypatch.setattr(migrationen, "AKTUELLE_VERSION", bis)
    monkeypatch.setattr(migrationen, "SCHRITTE", {v: f for v, f in migrationen.SCHRITTE.items() if v <= bis})


def baue_v10(pfad, monkeypatch, extra: int = 0):
    """Heutiger Stand (Schema 10) mit Kleinanzeigen- und mobile.de-Inseraten, einer Kollision (gleiche Anzeigen-ID auf zwei Plattformen,
    ``legacy_id`` NULL), Bearbeitung, Besichtigung, Ankauf, Beobachtungen und Preisverlauf."""
    with monkeypatch.context() as m:
        _alt_schritte(m, 10)
        db = Datenbank(str(pfad), wal=False)
        try:
            # Der heutige Code schreibt ``inserate.zuletzt_bestaetigt`` (Schritt 13); der Stand von Schema 10 kennt die Spalte nicht: für das Schreiben
            # anlegen und vor dem Schließen wieder entfernen, so entsteht ein Altbestand ohne die Spalte
            db.con.execute("ALTER TABLE inserate ADD COLUMN zuletzt_bestaetigt TEXT")
            db.speichere_treffer({"id": "k1", "url": "https://x.invalid/k1", "titel": "Knaus Sky TI", "preis": 30000, "quelle": "kleinanzeigen"}, "Alkoven")
            db.speichere_treffer({"id": "k2", "url": "https://x.invalid/k2", "titel": "Hymer B 544", "preis": 1, "quelle": None}, "Alkoven")
            db.speichere_treffer({"id": "m1", "url": "https://x.invalid/m1", "titel": "Dethleffs", "preis": 41500, "quelle": "mobile.de"}, "Import")
            db.con.execute("UPDATE anzeigen SET status='kontaktiert', notiz='Müller 0171 1234567', anschreiben_text='Hallo', angebot_betrag=25000 "
                           "WHERE id='k1'")
            db.con.execute("""INSERT INTO inserate (plattform, anzeigen_id, legacy_id, url, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen)
                              VALUES ('mobile.de', 'k1', NULL, 'https://y.invalid/k1', 'Gleiche ID, andere Plattform', 29000, 'aktiv', 'a', 'b')""")
            kollision = db.con.execute("SELECT id FROM inserate WHERE plattform='mobile.de' AND anzeigen_id='k1'").fetchone()[0]
            db.con.execute("INSERT INTO beobachtungen (inserat_id, plattform, kanal, ereignis_typ, zeitpunkt, preis, inhalt_hash) "
                           "VALUES (?, 'mobile.de', 'api', 'neu', 'z', 29000, 'h')", (kollision,))
            db.con.execute("INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?, 'z', 29000, 'api')", (kollision,))
            db.con.execute("INSERT INTO bearbeitung (anzeige_id, bearbeiter_id, uebernommen_am) VALUES ('k1', 1, '2026-10-01T10:00:00')")
            db.con.execute("INSERT INTO besichtigungen (anzeige_id, daten_json) VALUES ('k1', '{\"a\": 1}')")
            db.con.execute("""INSERT INTO ankaeufe (referenz, herkunft, anzeige_id, besichtigung_id, kaufpreis, plan_json, erstellt_am)
                              VALUES ('A-1', 'anzeige', 'k1', 1, 18000, '{}', '2026-10-02T10:00:00')""")
            db.con.execute("INSERT INTO ankauf_kosten (ankauf_id, art, betrag, datum, erstellt_am) VALUES (1, 'Reparatur', 300, '2026-10-03', 'z')")
            for i in range(extra):
                db.con.execute("INSERT INTO inserate (plattform, anzeigen_id, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                               "VALUES ('kleinanzeigen', ?, 'aktiv', 'a', 'b')", (f"x{i}",))
            db.con.commit()
            db.con.execute("ALTER TABLE inserate DROP COLUMN zuletzt_bestaetigt")
            db.con.commit()
        finally:
            db.con.close()


def baue(art: str, pfad, monkeypatch):
    {"v1": lambda: baue_v1(pfad), "v2": lambda: baue_v2(pfad), "v10": lambda: baue_v10(pfad, monkeypatch)}[art]()


def _sql(pfad, befehl, *param):
    con = sqlite3.connect(pfad)
    try:
        return con.execute(befehl, param).fetchall()
    finally:
        con.close()


def _pruefe_ein_fahrzeug_je_inserat(pfad):
    z = _sql(pfad, "SELECT (SELECT COUNT(*) FROM inserate), (SELECT COUNT(*) FROM fahrzeuge), (SELECT COUNT(DISTINCT fahrzeug_id) FROM inserate), "
                   "(SELECT COUNT(*) FROM inserate WHERE fahrzeug_id IS NULL), "
                   "(SELECT COUNT(*) FROM inserate WHERE fahrzeug_id NOT IN (SELECT id FROM fahrzeuge))")[0]
    assert z[0] > 0 and z[0] == z[1] == z[2] and z[3] == 0 and z[4] == 0, z


# ---------------------------------------------------------------- 1. Migration gegen Altbestände
@pytest.mark.parametrize("art", ["v1", "v2", "v10"])
def test_migration_altbestand_jedes_inserat_ein_fahrzeug_nichts_veraendert(tmp_path, monkeypatch, art):
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    baue(art, pfad, monkeypatch)
    vorher_version = lese_version(pfad)
    vorher = _abbild(pfad)
    assert migriere(pfad, ziel)[-1] == AKTUELLE_VERSION >= 11
    assert lese_version(pfad) == AKTUELLE_VERSION
    if art == "v10":
        assert vorher_version == 10 and len(vorher["inserate"][1]) == 4 and len(vorher["bearbeitung"][1]) == 1       # Kollision, Bearbeitung da
        assert len(vorher["ankaeufe"][1]) == len(vorher["besichtigungen"][1]) == 1
        assert _sql(pfad, "SELECT COUNT(*) FROM inserate WHERE legacy_id IS NULL")[0][0] == 1        # die Kollision
        assert versionen(pfad)[-(AKTUELLE_VERSION - 9):] == list(range(10, AKTUELLE_VERSION + 1))
    _pruefe_ein_fahrzeug_je_inserat(pfad)
    assert _nachher_wie_vorher(pfad, vorher) == vorher                    # alle bisherigen Tabellen und Spalten zeilen- UND inhaltsgleich
    assert {r[0] for r in _sql(pfad, "SELECT herkunft FROM fahrzeuge")} == {"migration"}
    if art == "v10":
        assert _sql(pfad, "SELECT status, notiz, angebot_betrag FROM anzeigen WHERE id='k1'") == [("kontaktiert", "Müller 0171 1234567", 25000)]
        assert _sql(pfad, "SELECT kaufpreis FROM ankaeufe") == [(18000,)]
        # die Kollision gehört zu einem eigenen Fahrzeug, nicht zu dem des Kleinanzeigen-Inserats
        ids = _sql(pfad, "SELECT fahrzeug_id FROM inserate WHERE anzeigen_id='k1'")
        assert len(ids) == 2 and ids[0] != ids[1]
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)] and _sql(pfad, "PRAGMA foreign_key_check") == []


def test_schema_von_schritt_11(tmp_path):
    pfad = tmp_path / "neu.sqlite"
    Datenbank(str(pfad), wal=False).con.close()
    assert [r[1] for r in _sql(pfad, "PRAGMA table_info(fahrzeuge)")] == ["id", "erstellt_am", "herkunft"]
    assert "fahrzeug_id" in [r[1] for r in _sql(pfad, "PRAGMA table_info(inserate)")]
    assert _sql(pfad, "SELECT name FROM sqlite_master WHERE type='trigger' AND name='inserate_fahrzeug_anlegen'") == [("inserate_fahrzeug_anlegen",)]
    assert _sql(pfad, "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_inserate_fahrzeug'")
    con = sqlite3.connect(pfad)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO fahrzeuge (erstellt_am, herkunft) VALUES ('x', 'unsinn')")
    finally:
        con.close()                                   # offene Verbindung sperrt unter Windows den Testordner
    # der Index wird für die Fassade tatsächlich benutzt
    plan = " ".join(str(r) for r in _sql(pfad, "EXPLAIN QUERY PLAN SELECT * FROM inserate WHERE fahrzeug_id = 1"))
    assert "idx_inserate_fahrzeug" in plan


# ---------------------------------------------------------------- 2. Sicherung und Wiederherstellung
def test_sicherung_vor_v11_ist_heil_und_stellt_den_alten_stand_wieder_her(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    vorher = _abbild(pfad)
    assert migriere(pfad, ziel) == list(range(11, AKTUELLE_VERSION + 1))
    kopien = [k for k in sicherungen(ziel, "db") if f"vor-v{AKTUELLE_VERSION}" in k.name]
    assert len(kopien) == 1
    assert _sql(kopien[0], "PRAGMA integrity_check") == [("ok",)] and lese_version(kopien[0]) == 10
    assert "fahrzeuge" not in tabellen(kopien[0]) and _abbild(kopien[0]) == vorher       # Stand vor der Migration, vollständig
    wiederherstellen(kopien[0], pfad, bestaetigt=True, ziel_ordner=ziel)
    assert lese_version(pfad) == 10 and _abbild(pfad) == vorher and "fahrzeuge" not in tabellen(pfad)
    assert migriere(pfad, ziel) == list(range(11, AKTUELLE_VERSION + 1))                 # und lässt sich erneut migrieren
    _pruefe_ein_fahrzeug_je_inserat(pfad)
    assert _nachher_wie_vorher(pfad, vorher) == vorher


# ---------------------------------------------------------------- 3. Idempotenz
def test_zweiter_lauf_und_zweite_ausfuehrung_des_schritts_aendern_nichts(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    stand = _abbild(pfad)
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_11(con)                     # Schritt selbst ist idempotent (IF NOT EXISTS, nur NULL-Zeilen)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _abbild(pfad) == stand


# ---------------------------------------------------------------- 4. Rollback
def _kein_stand_11(pfad):
    assert lese_version(pfad) == 10 and versionen(pfad)[-1] == 10
    assert "fahrzeuge" not in tabellen(pfad)
    assert "fahrzeug_id" not in [r[1] for r in _sql(pfad, "PRAGMA table_info(inserate)")]
    assert not _sql(pfad, "SELECT 1 FROM sqlite_master WHERE name IN ('inserate_fahrzeug_anlegen', 'idx_inserate_fahrzeug')")


def test_fehler_im_schritt_rollt_alles_zurueck(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    vorher = _abbild(pfad)
    echt = migrationen._schritt_11

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 11, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    _kein_stand_11(pfad)
    assert _abbild(pfad) == vorher
    assert any(f"vor-v{AKTUELLE_VERSION}" in k.name for k in sicherungen(ziel, "db"))             # Rückweg bleibt erhalten
    monkeypatch.undo()
    assert migriere(pfad, ziel) == list(range(11, AKTUELLE_VERSION + 1))                                           # nach Behebung läuft es durch


def test_invariante_inserate_und_fahrzeuge_passen_nicht_zusammen_rollback(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    con = sqlite3.connect(pfad)                       # Spalte existiert schon und ist belegt, aber ohne Fahrzeuge: Schritt kann das nicht heilen
    con.execute("ALTER TABLE inserate ADD COLUMN fahrzeug_id INTEGER")
    con.execute("UPDATE inserate SET fahrzeug_id = 7")
    con.commit()
    con.close()
    vorher = _abbild(pfad)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 10 and "fahrzeuge" not in tabellen(pfad) and _abbild(pfad) == vorher


def test_invariante_zeilenzahlen_fremder_tabellen_unveraendert(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    con = sqlite3.connect(pfad)                       # ein fremder Trigger würde beim Schritt Zeilen in bearbeitung anlegen
    con.execute("CREATE TRIGGER feind AFTER UPDATE ON inserate BEGIN INSERT INTO bearbeitung (anzeige_id) VALUES ('x' || NEW.id); END")
    con.commit()
    con.close()
    vorher = _abbild(pfad)
    with pytest.raises(MigrationsFehler, match="Zeilenzahlen") as fehler:
        migriere(pfad, ziel)
    assert "bearbeitung" in str(fehler.value)
    assert lese_version(pfad) == 10 and "fahrzeuge" not in tabellen(pfad) and _abbild(pfad) == vorher


def test_ohne_sicherung_keine_migration_auf_11(tmp_path, monkeypatch):
    pfad, blockiert = tmp_path / "db.sqlite", tmp_path / "ist-eine-datei"
    baue_v10(pfad, monkeypatch)
    blockiert.write_text("kein Ordner")
    fest = pruefsumme(pfad)
    with pytest.raises(MigrationsFehler, match="Sicherung"):
        migriere(pfad, blockiert)
    assert pruefsumme(pfad) == fest and lese_version(pfad) == 10


# ---------------------------------------------------------------- 5. Neue Inserate über alle Schreibwege
def _mit_versatz(db, n: int = 5):
    """Fahrzeug-IDs und Inserats-IDs laufen auseinander (sonst fiele eine Verwechslung von last_insert_rowid nicht auf)."""
    for _ in range(n):
        db.con.execute("INSERT INTO fahrzeuge (erstellt_am, herkunft) VALUES ('2026-01-01T00:00:00Z', 'migration')")
    db.con.commit()


def _pruefe_ids(db, erwartet_neu: int):
    """Jedes Inserat hat ein eigenes Fahrzeug; beobachtungen/preis_historie hängen am richtigen Inserat (Plattform stimmt, Preis stimmt)."""
    con = db.con
    z = con.execute("SELECT COUNT(*), COUNT(DISTINCT fahrzeug_id), SUM(fahrzeug_id IS NULL) FROM inserate").fetchone()
    assert (z[0], z[1], z[2]) == (erwartet_neu, erwartet_neu, 0)
    assert con.execute("SELECT COUNT(*) FROM inserate i JOIN fahrzeuge f ON f.id = i.fahrzeug_id WHERE f.herkunft = 'eingang'").fetchone()[0] == erwartet_neu
    assert all(i["fahrzeug_id"] != i["id"] for i in con.execute("SELECT * FROM inserate"))            # Versatz wirkt: IDs nicht zufällig gleich
    falsch = con.execute("SELECT COUNT(*) FROM beobachtungen b JOIN inserate i ON i.id = b.inserat_id WHERE i.plattform != b.plattform").fetchone()[0]
    assert falsch == 0 and con.execute("SELECT COUNT(*) FROM beobachtungen WHERE inserat_id NOT IN (SELECT id FROM inserate)").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM preis_historie WHERE inserat_id NOT IN (SELECT id FROM inserate)").fetchone()[0] == 0
    for tabelle in ("preis_historie", "beobachtungen"):       # der jeweils letzte Eintrag trägt den aktuellen Preis des Inserats
        letzter = f"SELECT COUNT(*) FROM {tabelle} t JOIN inserate i ON i.id = t.inserat_id WHERE t.preis IS NOT i.preis AND " \
                  f"t.id = (SELECT MAX(id) FROM {tabelle} WHERE inserat_id = t.inserat_id)"
        assert con.execute(letzter).fetchone()[0] == 0, tabelle
    assert con.execute("SELECT COUNT(*) FROM inserate WHERE preis IS NOT NULL AND id NOT IN (SELECT inserat_id FROM preis_historie)").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM inserate WHERE id NOT IN (SELECT inserat_id FROM beobachtungen)").fetchone()[0] == 0


def _treffer(ad_id, preis=30000, quelle="kleinanzeigen"):
    return {"id": ad_id, "url": f"https://beispiel.invalid/{ad_id}", "titel": "Hymer B 678", "preis": preis, "quelle": quelle}


def test_speichere_treffer_alle_kanaele_je_inserat_ein_fahrzeug(db):
    _mit_versatz(db)
    assert db.speichere_treffer(_treffer("s1"), "Alkoven") == "neu"
    assert db.speichere_treffer(_treffer("s2"), "Import", kanal="manuell") == "neu"
    assert db.speichere_treffer(_treffer("s3"), "Import", kanal="email") == "neu"
    assert db.speichere_treffer(_treffer("s4"), "Import", kanal="manuell", nur_leere=True) == "neu"       # Text-Import
    assert db.speichere_treffer(_treffer("s5", 20000, "mobile.de"), "Import") == "neu"
    assert db.speichere_treffer(_treffer("s1", 28000), "Alkoven") == "preis"                                # Wiederholung: kein neues Fahrzeug
    assert db.speichere_treffer(_treffer("s1", 28000), "Alkoven") == "bekannt"
    _pruefe_ids(db, 5)
    assert db.con.execute("SELECT COUNT(*) FROM fahrzeuge WHERE herkunft='eingang'").fetchone()[0] == 5


def test_importer_suche_seite_text_und_mail(cfg, db, ads):
    from tests.daten import FakeAbruf
    _mit_versatz(db)
    imp = Importer(cfg, db, abruf=FakeAbruf(ads))
    imp.lauf(cfg["suchen"])
    n = db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0]
    assert n >= 20
    _pruefe_ids(db, n)
    neue = [a for a in ads if not db.con.execute("SELECT 1 FROM inserate WHERE anzeigen_id=?", (a["id"],)).fetchone()]
    seite = SeitenEingang()
    if neue:
        imp.importiere(seite.lese(seite_roh(detailseite(neue[0]))), seite.kanal)
    text = TextEingang()
    imp.importiere(text.lese(TextEingang.rohdaten(KA_URL, KA_TEXT, "privat", JETZT)), text.kanal)
    mail = MailEingang()
    imp.importiere(mail.lese(Rohdaten(nachgebildet_ka_mail(), "m.eml", JETZT)), mail.kanal)
    n2 = db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0]
    assert n2 > n
    _pruefe_ids(db, n2)


def test_ereignisspeicher_neues_inserat_bekommt_eigenes_fahrzeug(cfg, db):
    _mit_versatz(db)
    imp = Importer(cfg, db)
    _freigeben(db, "mobile.de", "autoscout24")
    assert imp.importiere_ereignis(ereignis()) == "neu"
    assert imp.importiere_ereignis(ereignis("autoscout24")) == "neu"                       # gleiche Anzeigen-ID, andere Plattform
    assert imp.importiere_ereignis(ereignis(preis=32000, typ="geaendert")) == "geaendert"
    assert imp.importiere_ereignis(ereignis(typ="geloescht")) == "geloescht"
    _pruefe_ids(db, 2)
    zeilen = db.con.execute("SELECT plattform, fahrzeug_id FROM inserate ORDER BY id").fetchall()
    assert zeilen[0]["fahrzeug_id"] != zeilen[1]["fahrzeug_id"]
    assert db.con.execute("SELECT COUNT(*) FROM beobachtungen").fetchone()[0] == 4


def test_gleiche_v4_ab_legt_fahrzeug_an_und_preis_historie_haengt_am_richtigen_inserat(db):
    _mit_versatz(db)
    sql = "INSERT INTO anzeigen (id, titel, preis, quelle, erstmals_gesehen, zuletzt_gesehen) VALUES (?, 'T', ?, ?, 'a', ?)"
    db.con.execute(sql, ("alt1", 12000, None, "2026-10-01T10:00:00"))
    db.con.execute(sql, ("alt2", 13000, "mobile.de", "2026-10-02T10:00:00"))
    db.con.commit()
    assert db.gleiche_v4_ab() == 2
    assert db.gleiche_v4_ab() == 0
    assert db.con.execute("SELECT COUNT(*) FROM inserate WHERE fahrzeug_id IS NULL").fetchone()[0] == 0
    zeilen = db.con.execute("SELECT i.anzeigen_id, i.plattform, p.preis, p.kanal FROM preis_historie p JOIN inserate i ON i.id = p.inserat_id "
                            "ORDER BY i.anzeigen_id").fetchall()
    assert [tuple(z) for z in zeilen] == [("alt1", "kleinanzeigen", 12000, "abgleich"), ("alt2", "mobile.de", 13000, "abgleich")]
    assert db.con.execute("SELECT COUNT(DISTINCT fahrzeug_id) FROM inserate").fetchone()[0] == 2


def test_ergebnis_der_schreibfunktionen_unveraendert_inserat_id_ist_die_inserats_id(db):
    """``spiegle_inserat`` liefert die ``inserate.id`` (nicht die Fahrzeug-ID), obwohl ein Trigger danach selbst einfügt."""
    _mit_versatz(db, 7)
    db.schreibe_anzeige(_treffer("r1"), "Alkoven")
    iid = db.spiegle_inserat(_treffer("r1"), "suche")
    assert iid == db.con.execute("SELECT id FROM inserate WHERE anzeigen_id='r1'").fetchone()[0]
    assert db.con.execute("SELECT fahrzeug_id FROM inserate WHERE id=?", (iid,)).fetchone()[0] != iid


# ---------------------------------------------------------------- 6. Fassade
def test_fahrzeug_id_zu_und_inserate_von_fahrzeug(db):
    db.speichere_treffer(_treffer("ka1", quelle=None), "Alkoven")                         # Altform: quelle leer = Kleinanzeigen
    db.speichere_treffer(_treffer("md1", 20000, "mobile.de"), "Import")
    db.con.execute("INSERT INTO anzeigen (id, titel, erstmals_gesehen, zuletzt_gesehen) VALUES ('ohne', 'T', 'a', 'b')")      # kein Inserat dazu
    db.con.commit()
    ka, md = db.fahrzeug_id_zu("ka1"), db.fahrzeug_id_zu("md1")
    assert ka and md and ka != md
    assert db.fahrzeug_id_zu("gibtsnicht") is None and db.fahrzeug_id_zu("ohne") is None
    assert [r["anzeigen_id"] for r in db.inserate_von_fahrzeug(ka)] == ["ka1"]
    assert [(r["plattform"], r["anzeigen_id"]) for r in db.inserate_von_fahrzeug(md)] == [("mobile.de", "md1")]
    assert db.inserate_von_fahrzeug(999999) == []


def test_fahrzeug_id_zu_bei_kollision_nicht_ueber_legacy_id(db):
    """Dieselbe Anzeigen-ID zuerst auf mobile.de (nimmt ``legacy_id``), dann auf Kleinanzeigen (``legacy_id`` NULL)."""
    db.con.execute("""INSERT INTO inserate (plattform, anzeigen_id, legacy_id, titel, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen)
                      VALUES ('mobile.de', 'k9', 'k9', 'md', 'aktiv', 'a', 'b')""")
    db.con.commit()
    db.speichere_treffer(_treffer("k9", quelle="kleinanzeigen"), "Alkoven")
    assert db.con.execute("SELECT legacy_id FROM inserate WHERE plattform='kleinanzeigen' AND anzeigen_id='k9'").fetchone()[0] is None
    erwartet = db.con.execute("SELECT fahrzeug_id FROM inserate WHERE plattform='kleinanzeigen' AND anzeigen_id='k9'").fetchone()[0]
    assert db.fahrzeug_id_zu("k9") == erwartet
    assert [r["plattform"] for r in db.inserate_von_fahrzeug(erwartet)] == ["kleinanzeigen"]


# ---------------------------------------------------------------- 7. Leistung
def test_migration_mit_50000_inseraten(tmp_path, monkeypatch, capsys):
    pfad, ziel = tmp_path / "gross.sqlite", tmp_path / "sich"
    baue_v10(pfad, monkeypatch)
    con = sqlite3.connect(pfad)
    n = 50_000
    con.executemany("INSERT INTO inserate (plattform, anzeigen_id, url, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                    "VALUES ('kleinanzeigen', ?, ?, 'Wohnmobil', ?, 'aktiv', 'a', 'b')",
                    [(f"p{i}", f"https://x.invalid/{i}", 20000 + i % 5000) for i in range(n)])
    con.execute("INSERT INTO beobachtungen (inserat_id, plattform, kanal, ereignis_typ, zeitpunkt, preis, inhalt_hash) "
                "SELECT id, plattform, 'suche', 'neu', 'z', preis, 'h' FROM inserate WHERE anzeigen_id LIKE 'p%'")
    con.execute("INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) SELECT id, 'z', preis, 'suche' FROM inserate WHERE anzeigen_id LIKE 'p%'")
    con.commit()
    gesamt = con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0]
    con.close()
    assert gesamt == n + 4
    start = time.perf_counter()
    assert migriere(pfad, ziel)[-1] == AKTUELLE_VERSION
    dauer = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[P3-01] Migration 10 -> 11 mit {gesamt} Inseraten (inkl. Sicherung): {dauer:.2f} s")
    assert dauer < 10
    _pruefe_ein_fahrzeug_je_inserat(pfad)
    assert _sql(pfad, "SELECT COUNT(*) FROM fahrzeuge")[0][0] == gesamt


# ---------------------------------------------------------------- 8. Mandanten
def test_zwei_mandanten_migrieren_unabhaengig_mit_eigener_sicherung(grund, tmp_path, monkeypatch):
    mandanten.anlegen(grund, tmp_path, "firma-a", "Firma A", "https://a.test")
    mandanten.anlegen(grund, tmp_path, "firma-b", "Firma B", "https://b.test")
    cfgs = {k: mandanten.mandant_cfg(grund, tmp_path, k) for k in ("firma-a", "firma-b")}
    pfade = {k: Path(c["ausgabe"]["datenbank"]) for k, c in cfgs.items()}
    for p in pfade.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    baue_v10(pfade["firma-a"], monkeypatch)
    baue_v10(pfade["firma-b"], monkeypatch, extra=3)
    vorher = {k: _abbild(p) for k, p in pfade.items()}
    assert [len(vorher[k]["inserate"][1]) for k in pfade] == [4, 7]
    # A wird migriert, B bleibt dabei unberührt auf Schema 10
    fest_b = pruefsumme(pfade["firma-b"])
    assert migriere(pfade["firma-a"], cfgs["firma-a"]["sicherung"]["ordner"]) == list(range(11, AKTUELLE_VERSION + 1))
    assert pruefsumme(pfade["firma-b"]) == fest_b and lese_version(pfade["firma-b"]) == 10
    assert migriere(pfade["firma-b"], cfgs["firma-b"]["sicherung"]["ordner"]) == list(range(11, AKTUELLE_VERSION + 1))
    for k, p in pfade.items():
        _pruefe_ein_fahrzeug_je_inserat(p)
        assert _nachher_wie_vorher(p, vorher[k]) == vorher[k]
        eigene = sicherungen(Path(cfgs[k]["sicherung"]["ordner"]), "anzeigen")
        assert len(eigene) == 1 and f"vor-v{AKTUELLE_VERSION}" in eigene[0].name and _abbild(eigene[0]) == vorher[k]
    assert _sql(pfade["firma-a"], "SELECT COUNT(*) FROM fahrzeuge")[0][0] == 4 and _sql(pfade["firma-b"], "SELECT COUNT(*) FROM fahrzeuge")[0][0] == 7

