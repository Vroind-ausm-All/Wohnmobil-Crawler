"""Versionierte Schema-Migrationen (ADR-009).

Versionen: 1 = ZIP-Stand (Tabelle ``anzeigen`` im Ur-Schema), 2 = Stand vor Phase 1 (ergänzte Spalten + Team-Tabellen),
3 = Phase 1 (``schema_version``, ``bearbeitung``). Jeder Schritt läuft in einer eigenen Transaktion, ist idempotent
(``IF NOT EXISTS``, Spaltenprüfung) und wird erst nach erfolgreicher Sicherung der Datenbank ausgeführt.
Die DDL der Schritte ist eingefroren: spätere Änderungen gehören in einen neuen Schritt, nicht in einen alten.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .sicherung import SicherungsFehler, oeffne_lesend, sichere

AKTUELLE_VERSION = 3


class MigrationsFehler(RuntimeError):
    """Verständliche Meldung für den Betreiber; die Datenbank wurde dabei nicht verändert (oder zurückgerollt)."""


# ---------- Schritt 0/1: Ur-Schema (ZIP-Stand), nur für neue Datenbanken und Tests als Ausgangspunkt ----------
UR_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS anzeigen (
    id TEXT PRIMARY KEY, url TEXT, suche TEXT, titel TEXT, preis INTEGER, vb INTEGER,
    ort TEXT, km INTEGER, ez_jahr INTEGER, marke TEXT, art TEXT, leistung TEXT, getriebe TEXT,
    kurzbeschreibung TEXT, beschreibung TEXT, gewerblich INTEGER DEFAULT 0, details_json TEXT,
    detail_geladen INTEGER DEFAULT 0, erstmals_gesehen TEXT, zuletzt_gesehen TEXT, preis_vorher INTEGER,
    status TEXT DEFAULT 'neu', notiz TEXT)""",
)

# ---------- Schritt 2: Spalten, die nach dem ZIP-Stand dazukamen, und Team-Tabellen ----------
NEUE_SPALTEN = {"bild": "TEXT", "kontaktiert_am": "TEXT", "anschreiben_text": "TEXT", "preis_geaendert_am": "TEXT",
                "nachgefasst_am": "TEXT", "nachfass_anzahl": "INTEGER DEFAULT 0", "angebot_betrag": "INTEGER",
                "status_am": "TEXT", "quelle": "TEXT"}   # quelle: NULL = kleinanzeigen (Daten vor Phase 1)

TEAM_TABELLEN = ("nutzer", "sitzungen", "besichtigungen", "fotos")
TEAM_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS nutzer (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, rolle TEXT NOT NULL DEFAULT 'mitarbeiter',
    passwort_hash TEXT NOT NULL, telefon TEXT, aktiv INTEGER NOT NULL DEFAULT 1, erstellt_am TEXT)""",
    """CREATE TABLE IF NOT EXISTS sitzungen (
    token_hash TEXT PRIMARY KEY, nutzer_id INTEGER NOT NULL, ablauf TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS besichtigungen (
    id INTEGER PRIMARY KEY, anzeige_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'geplant',
    termin TEXT, adresse TEXT, zustaendig_id INTEGER, erstellt_von INTEGER, erstellt_am TEXT, geaendert_am TEXT,
    daten_json TEXT NOT NULL DEFAULT '{}',   -- Eingaben: Prüfpunkte, Messungen, Mängel, Fahrzeugdaten
    basis_json TEXT NOT NULL DEFAULT '{}',   -- eingefrorene Bewertung beim Anlegen (Angebot, Max-EK, …)
    ergebnis_json TEXT,                      -- letzte verbindliche Abzugsrechnung
    protokoll_json TEXT,                     -- Abschluss: Verkäufer, vereinbarter Preis, Unterschriften
    endpreis INTEGER, version INTEGER NOT NULL DEFAULT 1)""",
    "CREATE INDEX IF NOT EXISTS idx_besichtigung_anzeige ON besichtigungen(anzeige_id)",
    """CREATE TABLE IF NOT EXISTS fotos (
    id INTEGER PRIMARY KEY, besichtigung_id INTEGER NOT NULL, mangel_key TEXT, datei TEXT NOT NULL,
    erstellt_am TEXT, nutzer_id INTEGER)""",
)


def _spalten(con: sqlite3.Connection, tabelle: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}


def _schritt_2(con: sqlite3.Connection):
    vorhanden = _spalten(con, "anzeigen")
    for spalte, typ in NEUE_SPALTEN.items():
        if spalte not in vorhanden:
            con.execute(f"ALTER TABLE anzeigen ADD COLUMN {spalte} {typ}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_zuletzt ON anzeigen(zuletzt_gesehen)")
    for sql in TEAM_SCHEMA:
        con.execute(sql)


def _schritt_3(con: sqlite3.Connection):
    # Vorbereitung für die Team-Funktionen: wer hat ein Inserat übernommen bzw. den Kontakt bestätigt
    con.execute("""CREATE TABLE IF NOT EXISTS bearbeitung (
        anzeige_id TEXT PRIMARY KEY, bearbeiter_id INTEGER, uebernommen_am TEXT,
        kontaktiert_von INTEGER, kontaktiert_am TEXT)""")


SCHRITTE: dict[int, Callable[[sqlite3.Connection], None]] = {2: _schritt_2, 3: _schritt_3}

_SCHEMA_VERSION = ("CREATE TABLE IF NOT EXISTS schema_version ("
                   "version INTEGER PRIMARY KEY, angewendet_am TEXT NOT NULL)")


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _tabellen(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def erkenne_version(con: sqlite3.Connection) -> int:
    """Ist-Stand: 0 = leere Datenbank, sonst Eintrag aus schema_version, ohne diesen 1 (ZIP) oder 2 (vollständig)."""
    tabellen = _tabellen(con)
    if "schema_version" in tabellen:
        v = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if v is not None:
            return int(v)
    if not tabellen:
        return 0
    if "anzeigen" not in tabellen:
        raise MigrationsFehler("Die Datei ist keine Wohnmobil-Scout-Datenbank (Tabelle „anzeigen“ fehlt). "
                               "Es wurde nichts verändert.")
    if set(NEUE_SPALTEN) <= _spalten(con, "anzeigen") and set(TEAM_TABELLEN) <= tabellen:
        return 2
    return 1


def lese_version(db_pfad: str | Path) -> int:
    """Nur lesen (z. B. für Diagnose); legt nichts an (``mode=ro``)."""
    con = oeffne_lesend(db_pfad)
    try:
        return erkenne_version(con)
    finally:
        con.close()


def pruefe_wiederherstellbar(pfad: str | Path):
    """Darf diese Datei als Datenbank eingespielt werden? Tabelle ``anzeigen`` vorhanden und Version nicht neuer als der Code.

    Wirft ``SicherungsFehler`` (Meldung für den Betreiber); die Datei wird nur lesend geöffnet.
    """
    pfad = Path(pfad)
    try:
        con = oeffne_lesend(pfad)
        try:
            if "anzeigen" not in _tabellen(con):
                raise SicherungsFehler("Die Sicherung ist keine Wohnmobil-Scout-Datenbank (Tabelle „anzeigen“ fehlt). "
                                       "Es wurde nichts verändert.")
            version = erkenne_version(con)
        finally:
            con.close()
    except (sqlite3.Error, MigrationsFehler) as e:
        raise SicherungsFehler(f"Die Sicherung lässt sich nicht als Wohnmobil-Scout-Datenbank lesen ({e}). Nichts verändert.") from e
    if version > AKTUELLE_VERSION:
        raise SicherungsFehler(f"Die Sicherung hat Schemaversion {version}, dieses Programm kennt nur Version {AKTUELLE_VERSION}. "
                               "Bitte das Programm aktualisieren. Es wurde nichts verändert.")


def _fuehre_aus(con: sqlite3.Connection, version: int, erkannt: int) -> bool:
    """Ein Schritt in einer Transaktion; Zeilenzahl von anzeigen und Team-Tabellen darf sich dabei nicht ändern.
    Rückgabe False: Ein anderer Prozess hatte den Schritt schon erledigt, hier wurde nichts getan."""
    con.execute("BEGIN IMMEDIATE")
    try:
        # Zweiter Prozess war schneller? Dann ist der Schritt schon erledigt (Idempotenz auch bei Wettlauf).
        if "schema_version" in _tabellen(con):
            aktuell = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
            if aktuell >= version:
                con.execute("ROLLBACK")
                return False
        else:
            con.execute(_SCHEMA_VERSION)
            if erkannt >= 1:       # Ausgangsstand von Altbeständen festhalten (Herkunft nachvollziehbar)
                con.execute("INSERT OR IGNORE INTO schema_version VALUES (?,?)", (erkannt, _jetzt()))
        vorher = _zaehle(con)
        SCHRITTE[version](con)
        nachher = _zaehle(con)
        if any(nachher.get(t) != n for t, n in vorher.items()):
            raise MigrationsFehler(f"Zeilenzahl hat sich bei Schritt {version} geändert: {vorher} -> {nachher}")
        con.execute("INSERT OR REPLACE INTO schema_version VALUES (?,?)", (version, _jetzt()))
        con.execute("COMMIT")
        return True
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise


def _zaehle(con: sqlite3.Connection) -> dict[str, int]:
    vorhanden = _tabellen(con)
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("anzeigen", *TEAM_TABELLEN) if t in vorhanden}


def _neu_anlegen(con: sqlite3.Connection) -> bool:
    """Neue, leere Datenbank: direkt in der aktuellen Version, ohne Sicherung (es gibt nichts zu sichern).

    Rückgabe False: Ein zweiter Prozess war schneller (Prüfung unter der Schreibsperre), nichts wurde getan.
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        if erkenne_version(con) != 0:
            con.execute("ROLLBACK")
            return False
        for sql in UR_SCHEMA:
            con.execute(sql)
        for v in sorted(SCHRITTE):
            SCHRITTE[v](con)
        con.execute(_SCHEMA_VERSION)
        con.execute("INSERT OR IGNORE INTO schema_version VALUES (?,?)", (AKTUELLE_VERSION, _jetzt()))
        con.execute("COMMIT")
        return True
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise


def _inzwischen_aktuell(db_pfad: Path) -> bool:
    try:
        return lese_version(db_pfad) >= AKTUELLE_VERSION
    except (sqlite3.Error, MigrationsFehler):
        return False


def migriere(db_pfad: str | Path, sicherung_ordner: str | Path | None = None) -> list[int]:
    """Bringt die Datenbank auf ``AKTUELLE_VERSION``. Rückgabe: ausgeführte Schritte (leer = nichts zu tun).

    Vor dem ersten Schritt wird die Datenbank gesichert (Backup-API + integrity_check); ohne gültige Sicherung
    erfolgt keine Änderung. Migrationssicherungen werden nie aufgeräumt (sie sind der Rückweg); das erledigt die
    nächste normale Sicherung nach der konfigurierten Aufbewahrung. Ist die Datenbank neuer als dieser Code,
    wird nichts geschrieben.
    """
    db_pfad = Path(db_pfad)
    sicherung_ordner = Path(sicherung_ordner) if sicherung_ordner else db_pfad.parent / "sicherungen"
    # isolation_level=None: Transaktionen steuern wir selbst (auch DDL gehört in die Transaktion)
    con = sqlite3.connect(str(db_pfad), timeout=30, isolation_level=None)
    try:
        try:
            erkannt = erkenne_version(con)
        except sqlite3.DatabaseError as e:
            raise MigrationsFehler(f"{db_pfad.name} lässt sich nicht als SQLite-Datenbank lesen ({e}). "
                                   "Mit „scout.py wiederherstellen“ eine Sicherung zurückspielen. Nichts verändert.") from e
        if erkannt > AKTUELLE_VERSION:
            raise MigrationsFehler(
                f"Die Datenbank {db_pfad.name} hat Schemaversion {erkannt}, dieses Programm kennt nur Version "
                f"{AKTUELLE_VERSION}. Bitte das Programm aktualisieren (nicht mit der alten Version weiterarbeiten). "
                "Es wurde nichts verändert.")
        if erkannt == 0:
            if _neu_anlegen(con):
                return [AKTUELLE_VERSION]
            con.close()
            return migriere(db_pfad, sicherung_ordner)     # parallel angelegt: Stand neu beurteilen
        offen = [v for v in sorted(SCHRITTE) if v > erkannt]
        if not offen:
            return []
        con.close()                # Verbindung vor der Sicherung freigeben (Windows-Dateisperren)
        try:
            kopie = sichere(db_pfad, sicherung_ordner, zusatz=f"vor-v{offen[-1]}", aufraeumen=False)
        except (SicherungsFehler, OSError, sqlite3.Error) as e:
            if _inzwischen_aktuell(db_pfad):          # ein anderer Prozess (App + geplante Aufgabe) hat in der Zwischenzeit migriert
                return []
            raise MigrationsFehler(f"Migration abgebrochen: Die Sicherung vor der Migration ist fehlgeschlagen ({e}). "
                                   "Die Datenbank wurde nicht verändert.") from e
        con = sqlite3.connect(str(db_pfad), timeout=30, isolation_level=None)
        erledigt = []
        for v in offen:
            try:
                ausgefuehrt = _fuehre_aus(con, v, erkannt)
            except Exception as e:  # noqa: BLE001 – Rollback ist erfolgt; verständliche Meldung mit Rückweg
                raise MigrationsFehler(f"Migration auf Version {v} fehlgeschlagen und zurückgerollt: {e}. "
                                       f"Sicherung vor der Migration: {kopie}") from e
            if ausgefuehrt:
                erledigt.append(v)
        return erledigt
    finally:
        con.close()
