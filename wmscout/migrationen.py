"""Versionierte Schema-Migrationen (ADR-009).

Versionen: 1 = ZIP-Stand (Tabelle ``anzeigen`` im Ur-Schema), 2 = Stand vor Phase 1 (ergänzte Spalten + Team-Tabellen),
3 = Phase 1 (``schema_version``, ``bearbeitung``), 4 = vorbereiteter Mehrquellen-Ereigniseingang, 5 = Verkäuferportal,
6 = Händlerportal (Standorte), 7 = Demo-Auktionen, 8 = gespeicherte Kalkulationen (Deal Intelligence),
9 = Ankaufsvorgänge (Besichtigung bis Verkauf), 10 = Audit-Protokoll und Leerlauf-Zeit der Sitzungen (G0b),
11 = Fahrzeuge getrennt von Inseraten (P3-01, ``fahrzeuge`` + ``inserate.fahrzeug_id``),
12 = Dublettenentscheidungen und Zuordnungsprotokoll (P3-02a, nur Tabellen, noch ohne fachliche Wirkung),
13 = Verfügbarkeit mit Bestätigungszeitpunkt (P3-04, ``inserate.zuletzt_bestaetigt``) und Index für ``fahrzeug_zuordnungen(entscheidung_id)``.
Jeder Schritt läuft in einer eigenen Transaktion, ist idempotent
(``IF NOT EXISTS``, Spaltenprüfung) und wird erst nach erfolgreicher Sicherung der Datenbank ausgeführt.
Die DDL der Schritte ist eingefroren: spätere Änderungen gehören in einen neuen Schritt, nicht in einen alten.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .sicherung import SicherungsFehler, oeffne_lesend, sichere

AKTUELLE_VERSION = 14


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


def _schritt_4(con: sqlite3.Connection):
    """Additive v4: alte App-Tabellen bleiben erhalten; neue Ereignisse nutzen Plattform-IDs."""
    con.execute("""CREATE TABLE IF NOT EXISTS quellen (
        kennung TEXT PRIMARY KEY, zugriffsart TEXT NOT NULL, freigegeben INTEGER NOT NULL DEFAULT 0,
        aktiv INTEGER NOT NULL DEFAULT 0, CHECK(freigegeben IN (0,1)), CHECK(aktiv IN (0,1)))""")
    con.execute("INSERT OR IGNORE INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES ('kleinanzeigen', 'web', 0, 0)")
    con.execute("""CREATE TABLE IF NOT EXISTS inserate (
        id INTEGER PRIMARY KEY, plattform TEXT NOT NULL, anzeigen_id TEXT NOT NULL,
        legacy_id TEXT UNIQUE, url TEXT, titel TEXT, preis INTEGER,
        verfuegbarkeit TEXT NOT NULL DEFAULT 'unbekannt',
        erstmals_gesehen TEXT NOT NULL, zuletzt_gesehen TEXT NOT NULL,
        UNIQUE(plattform, anzeigen_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS beobachtungen (
        id INTEGER PRIMARY KEY, inserat_id INTEGER NOT NULL REFERENCES inserate(id),
        plattform TEXT NOT NULL, kanal TEXT NOT NULL, ereignis_typ TEXT NOT NULL,
        ereignis_id TEXT, zeitpunkt TEXT NOT NULL, preis INTEGER, inhalt_hash TEXT NOT NULL,
        UNIQUE(plattform, kanal, ereignis_id))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_beobachtungen_inserat ON beobachtungen(inserat_id, zeitpunkt)")
    con.execute("""CREATE TABLE IF NOT EXISTS preis_historie (
        id INTEGER PRIMARY KEY, inserat_id INTEGER NOT NULL REFERENCES inserate(id),
        zeitpunkt TEXT NOT NULL, preis INTEGER NOT NULL, kanal TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_preis_historie_inserat ON preis_historie(inserat_id, zeitpunkt)")
    # Bestehende Fahrzeuge verlustfrei referenzieren; Status der Ankaufbearbeitung ist
    # KEINE Aussage darüber, ob das Inserat auf der Plattform noch verfügbar ist.
    con.execute("""INSERT OR IGNORE INTO inserate
        (plattform, anzeigen_id, legacy_id, url, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen)
        SELECT COALESCE(NULLIF(quelle, ''), 'kleinanzeigen'), id, id, url, titel, preis,
               'unbekannt', COALESCE(erstmals_gesehen, ''), COALESCE(zuletzt_gesehen, '')
          FROM anzeigen""")
    con.execute("""INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal)
        SELECT id, erstmals_gesehen, preis, 'migration'
          FROM inserate WHERE legacy_id IS NOT NULL AND preis IS NOT NULL""")


def _schritt_5(con: sqlite3.Connection):
    """Additive v5 (Phase B, ADR-025): Verkäuferportal. Eine Verkaufsanfrage ist ein vom Verkäufer selbst angebotenes Fahrzeug –
    bewusst getrennt von beobachteten Inseraten (``inserate``/``anzeigen``, Architekturregel 1). Geldbeträge als ganze Euro."""
    con.execute("""CREATE TABLE IF NOT EXISTS verkaeufer (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, telefon TEXT, plz TEXT, ort TEXT,
        einwilligung_am TEXT NOT NULL, einwilligung_version TEXT NOT NULL, erstellt_am TEXT NOT NULL,
        CHECK(email IS NOT NULL OR telefon IS NOT NULL))""")
    con.execute("""CREATE TABLE IF NOT EXISTS verkaufsanfragen (
        id INTEGER PRIMARY KEY, referenz TEXT UNIQUE, verkaeufer_id INTEGER NOT NULL REFERENCES verkaeufer(id),
        kanal TEXT NOT NULL, art TEXT, marke TEXT, modell TEXT, ez_jahr INTEGER, km INTEGER, preisvorstellung INTEGER,
        beschreibung TEXT, maengel TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'eingegangen',
        bearbeiter_id INTEGER, notiz TEXT, erfasst_von INTEGER, erstellt_am TEXT NOT NULL, aktualisiert_am TEXT NOT NULL,
        CHECK(kanal IN ('formular', 'telefon', 'vor_ort')),
        CHECK(status IN ('eingegangen', 'in_pruefung', 'angebot', 'abgelehnt', 'zurueckgezogen', 'gekauft')),
        CHECK(km IS NULL OR km >= 0), CHECK(preisvorstellung IS NULL OR preisvorstellung >= 0))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_verkaufsanfragen_status ON verkaufsanfragen(status, erstellt_am)")
    con.execute("""CREATE TABLE IF NOT EXISTS anfrage_fotos (
        id INTEGER PRIMARY KEY, anfrage_id INTEGER NOT NULL REFERENCES verkaufsanfragen(id),
        datei TEXT NOT NULL, erstellt_am TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS anfrage_verlauf (
        id INTEGER PRIMARY KEY, anfrage_id INTEGER NOT NULL REFERENCES verkaufsanfragen(id),
        zeitpunkt TEXT NOT NULL, nutzer_id INTEGER, ereignis TEXT NOT NULL, alt TEXT, neu TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_anfrage_verlauf ON anfrage_verlauf(anfrage_id, zeitpunkt)")



def _neue_spalte(con: sqlite3.Connection, tabelle: str, spalte: str, typ: str):
    if spalte not in {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}:
        con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")


def _schritt_6(con: sqlite3.Connection):
    """Additive v6 (Phase C, ADR-026): Händlerportal für eigene Standorte/Filialen. Ein Standort sieht freigegebene
    Verkaufsanfragen erst nach Prüfung; freigegeben ist eine Anfrage nur mit Einwilligung des Verkäufers UND Freigabe des
    Inhabers. Nur neue Tabellen und neue (leere) Spalten – nichts Bestehendes wird verändert."""
    con.execute("""CREATE TABLE IF NOT EXISTS standorte (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, plz TEXT, ort TEXT,
        status TEXT NOT NULL DEFAULT 'offen', geprueft_am TEXT, geprueft_von INTEGER, erstellt_am TEXT NOT NULL,
        CHECK(status IN ('offen', 'geprueft', 'gesperrt')))""")
    _neue_spalte(con, "nutzer", "standort_id", "INTEGER REFERENCES standorte(id)")
    _neue_spalte(con, "verkaufsanfragen", "weitergabe_einwilligung_am", "TEXT")
    _neue_spalte(con, "verkaufsanfragen", "freigegeben_am", "TEXT")
    _neue_spalte(con, "verkaufsanfragen", "freigegeben_von", "INTEGER")
    con.execute("""CREATE TABLE IF NOT EXISTS anfrage_interesse (
        id INTEGER PRIMARY KEY, anfrage_id INTEGER NOT NULL REFERENCES verkaufsanfragen(id),
        standort_id INTEGER NOT NULL REFERENCES standorte(id), nutzer_id INTEGER, zeitpunkt TEXT NOT NULL,
        UNIQUE(anfrage_id, standort_id))""")


def _schritt_7(con: sqlite3.Connection):
    """Additive v7 (Phase D, ADR-027): Demo-Auktionen für freigegebene Verkaufsanfragen. Beträge ganze Euro, Zeiten UTC.
    Gebote und Protokoll sind nur anfügbar (Trigger); das Protokoll ist zusätzlich hash-verkettet. Nur neue Tabellen."""
    con.execute("""CREATE TABLE IF NOT EXISTS auktionen (
        id INTEGER PRIMARY KEY, anfrage_id INTEGER NOT NULL REFERENCES verkaufsanfragen(id),
        status TEXT NOT NULL DEFAULT 'laeuft', demo INTEGER NOT NULL DEFAULT 1,
        startpreis INTEGER NOT NULL, mindestpreis INTEGER, schritt INTEGER NOT NULL,
        start_utc TEXT NOT NULL, ende_utc TEXT NOT NULL, verlaengerung_sek INTEGER NOT NULL DEFAULT 0,
        erstellt_von INTEGER, ergebnis TEXT, gewinner_gebot_id INTEGER, beendet_utc TEXT,
        entschieden_utc TEXT, entschieden_von INTEGER, grund TEXT,
        CHECK(status IN ('laeuft', 'beendet', 'zugeschlagen', 'abgelehnt', 'abgebrochen')),
        CHECK(demo = 1),
        CHECK(typeof(startpreis) = 'integer' AND startpreis > 0),
        CHECK(mindestpreis IS NULL OR (typeof(mindestpreis) = 'integer' AND mindestpreis > 0)),
        CHECK(typeof(schritt) = 'integer' AND schritt > 0), CHECK(verlaengerung_sek >= 0),
        CHECK(ende_utc > start_utc),
        CHECK(ergebnis IS NULL OR ergebnis IN ('kein_gebot', 'unter_mindestpreis', 'mindestpreis_erreicht')))""")
    # je Anfrage höchstens eine Auktion, die läuft, auf Entscheidung wartet oder zugeschlagen ist
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_auktion_aktiv ON auktionen(anfrage_id)
        WHERE status IN ('laeuft', 'beendet', 'zugeschlagen')""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_auktion_status ON auktionen(status, ende_utc)")
    con.execute("""CREATE TABLE IF NOT EXISTS gebote (
        id INTEGER PRIMARY KEY, auktion_id INTEGER NOT NULL REFERENCES auktionen(id),
        standort_id INTEGER NOT NULL REFERENCES standorte(id), nutzer_id INTEGER NOT NULL,
        betrag INTEGER NOT NULL, zeitpunkt_utc TEXT NOT NULL, wiederholungs_id TEXT NOT NULL,
        CHECK(typeof(betrag) = 'integer' AND betrag > 0), CHECK(length(wiederholungs_id) BETWEEN 8 AND 64),
        UNIQUE(auktion_id, nutzer_id, wiederholungs_id),
        UNIQUE(auktion_id, betrag))""")      # Gebote steigen streng: zwei gleich hohe Gebote kann es nicht geben
    con.execute("""CREATE TABLE IF NOT EXISTS auktion_protokoll (
        id INTEGER PRIMARY KEY, auktion_id INTEGER NOT NULL, zeitpunkt_utc TEXT NOT NULL, ereignis TEXT NOT NULL,
        nutzer_id INTEGER, daten_json TEXT NOT NULL, vorher_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_auktion_protokoll ON auktion_protokoll(auktion_id, id)")
    for tabelle in ("gebote", "auktion_protokoll"):
        for art in ("UPDATE", "DELETE"):
            con.execute(f"""CREATE TRIGGER IF NOT EXISTS {tabelle}_kein_{art.lower()} BEFORE {art} ON {tabelle}
                BEGIN SELECT RAISE(ABORT, '{tabelle} ist nur anfügbar'); END""")


def _schritt_8(con: sqlite3.Connection):
    """Additive v8 (Phase E, ADR-028): gespeicherte Kalkulationen mit eingefrorener Eingabe – jede lässt sich exakt nachrechnen.
    Nur anfügbar (Trigger). Je Gebot höchstens eine Kalkulation."""
    con.execute("""CREATE TABLE IF NOT EXISTS kalkulationen (
        id INTEGER PRIMARY KEY, zeitpunkt_utc TEXT NOT NULL, version TEXT NOT NULL, anlass TEXT NOT NULL,
        anfrage_id INTEGER NOT NULL REFERENCES verkaufsanfragen(id), auktion_id INTEGER REFERENCES auktionen(id),
        gebot_id INTEGER UNIQUE REFERENCES gebote(id), standort_id INTEGER REFERENCES standorte(id), nutzer_id INTEGER,
        betrag INTEGER, eingabe_json TEXT NOT NULL, eingabe_hash TEXT NOT NULL, ergebnis_json TEXT NOT NULL,
        CHECK(anlass IN ('gebot', 'gespeichert')), CHECK(betrag IS NULL OR (typeof(betrag) = 'integer' AND betrag > 0)))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_kalkulationen_anfrage ON kalkulationen(anfrage_id, id)")
    for art in ("UPDATE", "DELETE"):
        con.execute(f"""CREATE TRIGGER IF NOT EXISTS kalkulationen_kein_{art.lower()} BEFORE {art} ON kalkulationen
            BEGIN SELECT RAISE(ABORT, 'kalkulationen ist nur anfügbar'); END""")


def _schritt_9(con: sqlite3.Connection):
    """Additive v9 (Phase F, ADR-029): Ankaufsvorgang vom Kauf bis zum Verkauf; Besichtigungen auch für Verkaufsanfragen.
    Neue Tabellen und eine neue, leere Spalte ``besichtigungen.anfrage_id`` – nichts Bestehendes wird verändert.
    Verlauf und Kosten sind nur anfügbar (Korrekturen als Gegenbuchung)."""
    _neue_spalte(con, "besichtigungen", "anfrage_id", "INTEGER REFERENCES verkaufsanfragen(id)")
    con.execute("""CREATE TABLE IF NOT EXISTS ankaeufe (
        id INTEGER PRIMARY KEY, referenz TEXT UNIQUE, herkunft TEXT NOT NULL, anfrage_id INTEGER REFERENCES verkaufsanfragen(id),
        anzeige_id TEXT, besichtigung_id INTEGER NOT NULL UNIQUE REFERENCES besichtigungen(id), auktion_id INTEGER REFERENCES auktionen(id),
        standort_id INTEGER REFERENCES standorte(id), kalkulation_id INTEGER REFERENCES kalkulationen(id),
        status TEXT NOT NULL DEFAULT 'gekauft', kaufpreis INTEGER NOT NULL, plan_json TEXT NOT NULL,
        vertrag_am TEXT, vertrag_von INTEGER, uebergabe_am TEXT, zahlung_am TEXT, km_uebergabe INTEGER,
        vk_preis INTEGER, verkauft_am TEXT, storno_grund TEXT, erstellt_am TEXT NOT NULL, erstellt_von INTEGER,
        CHECK(herkunft IN ('anfrage', 'anzeige')),
        CHECK(status IN ('gekauft', 'uebergeben', 'verkauft', 'storniert')),
        CHECK(typeof(kaufpreis) = 'integer' AND kaufpreis > 0),
        CHECK(vk_preis IS NULL OR (typeof(vk_preis) = 'integer' AND vk_preis > 0)),
        CHECK(km_uebergabe IS NULL OR km_uebergabe >= 0))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ankaeufe_status ON ankaeufe(status, id)")
    con.execute("""CREATE TABLE IF NOT EXISTS ankauf_kosten (
        id INTEGER PRIMARY KEY, ankauf_id INTEGER NOT NULL REFERENCES ankaeufe(id), art TEXT NOT NULL, betrag INTEGER NOT NULL,
        notiz TEXT, datum TEXT NOT NULL, nutzer_id INTEGER, erstellt_am TEXT NOT NULL,
        CHECK(typeof(betrag) = 'integer' AND betrag != 0))""")
    con.execute("""CREATE TABLE IF NOT EXISTS ankauf_verlauf (
        id INTEGER PRIMARY KEY, ankauf_id INTEGER NOT NULL REFERENCES ankaeufe(id), zeitpunkt TEXT NOT NULL, nutzer_id INTEGER,
        ereignis TEXT NOT NULL, daten_json TEXT NOT NULL DEFAULT '{}')""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ankauf_verlauf ON ankauf_verlauf(ankauf_id, id)")
    con.execute("""CREATE TABLE IF NOT EXISTS ankauf_dokumente (
        id INTEGER PRIMARY KEY, ankauf_id INTEGER NOT NULL REFERENCES ankaeufe(id), art TEXT NOT NULL, datei TEXT NOT NULL,
        nutzer_id INTEGER, erstellt_am TEXT NOT NULL, CHECK(art IN ('vertrag', 'uebergabe', 'sonstiges')))""")
    for tabelle in ("ankauf_kosten", "ankauf_verlauf"):
        for art in ("UPDATE", "DELETE"):
            con.execute(f"""CREATE TRIGGER IF NOT EXISTS {tabelle}_kein_{art.lower()} BEFORE {art} ON {tabelle}
                BEGIN SELECT RAISE(ABORT, '{tabelle} ist nur anfügbar'); END""")


def _schritt_10(con: sqlite3.Connection):
    """Additive v10 (G0b, ADR-031): Audit-Protokoll – wer hat wann was gelesen oder geändert (nur anfügbar, ohne Inhalte der
    Anfrage, ohne Passwörter) – und letzte Nutzung je Sitzung für das Leerlauf-Zeitlimit (neue, leere Spalte)."""
    con.execute("""CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY, zeitpunkt TEXT NOT NULL, nutzer_id INTEGER, nutzer TEXT, rolle TEXT, ip TEXT,
        methode TEXT NOT NULL, pfad TEXT NOT NULL, status INTEGER NOT NULL, aktion TEXT NOT NULL, objekt TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_zeit ON audit(zeitpunkt)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_objekt ON audit(objekt, id)")
    for art in ("UPDATE", "DELETE"):
        con.execute(f"""CREATE TRIGGER IF NOT EXISTS audit_kein_{art.lower()} BEFORE {art} ON audit
            BEGIN SELECT RAISE(ABORT, 'audit ist nur anfügbar'); END""")
    _neue_spalte(con, "sitzungen", "zuletzt", "TEXT")


def _schritt_11(con: sqlite3.Connection):
    """Additive v11 (P3-01, ADR-039): ein Fahrzeug ist nicht dasselbe wie ein Inserat. Neue Tabelle ``fahrzeuge`` (bewusst nur
    Kennung, Herkunft, Zeitpunkt – Merkmale, FIN und Status folgen mit P3-02) und neue Spalte ``inserate.fahrzeug_id``.
    Jedes vorhandene Inserat bekommt genau ein eigenes Fahrzeug; es wird NICHTS zusammengeführt (Zuordnungen nur vorgeschlagen).
    Der Ankaufsstatus bleibt am Inserat (``anzeigen``/``bearbeitung``). Nichts Bestehendes wird verändert oder gelöscht."""
    con.execute("""CREATE TABLE IF NOT EXISTS fahrzeuge (
        id INTEGER PRIMARY KEY, erstellt_am TEXT NOT NULL,
        herkunft TEXT NOT NULL CHECK(herkunft IN ('migration', 'eingang')))""")
    _neue_spalte(con, "inserate", "fahrzeug_id", "INTEGER REFERENCES fahrzeuge(id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_inserate_fahrzeug ON inserate(fahrzeug_id)")
    vorher = _zaehle_v11(con)
    # Altbestand set-basiert. Die Gleichheit fahrzeuge.id = inserate.id gilt NUR für diesen Altbestand; kein Code darf sich darauf
    # verlassen (Zugriff immer über inserate.fahrzeug_id).
    con.execute("INSERT INTO fahrzeuge (id, erstellt_am, herkunft) SELECT id, ?, 'migration' FROM inserate WHERE fahrzeug_id IS NULL",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    con.execute("UPDATE inserate SET fahrzeug_id = id WHERE fahrzeug_id IS NULL")
    # Neue Inserate (Suche, Seiten-/Text-/Mail-Import, Ereigniseingang, Abgleich) bekommen ohne Zutun ein eigenes Fahrzeug.
    # In `inserate` nur mit einfachem INSERT oder UPSERT schreiben: INSERT OR REPLACE ließe ein verwaistes Fahrzeug zurück.
    con.execute("""CREATE TRIGGER IF NOT EXISTS inserate_fahrzeug_anlegen AFTER INSERT ON inserate WHEN NEW.fahrzeug_id IS NULL
        BEGIN
            INSERT INTO fahrzeuge (erstellt_am, herkunft) VALUES (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), 'eingang');
            UPDATE inserate SET fahrzeug_id = last_insert_rowid() WHERE id = NEW.id;
        END""")
    nachher = _zaehle_v11(con)
    if nachher != {**vorher, "fahrzeuge": nachher["inserate"]}:
        raise MigrationsFehler(f"Zeilenzahlen haben sich bei Schritt 11 geändert: {vorher} -> {nachher}")
    ohne = con.execute("SELECT COUNT(*) FROM inserate WHERE fahrzeug_id IS NULL").fetchone()[0]
    if ohne:
        raise MigrationsFehler(f"{ohne} Inserate ohne Fahrzeug nach Schritt 11")
    verschieden = con.execute("SELECT COUNT(DISTINCT fahrzeug_id) FROM inserate").fetchone()[0]
    if verschieden != nachher["inserate"]:
        raise MigrationsFehler(f"Schritt 11: Fahrzeuge und Inserate passen nicht 1:1 ({verschieden} verschiedene Fahrzeuge, {nachher['inserate']} Inserate)")
    lose = con.execute("SELECT COUNT(*) FROM inserate WHERE fahrzeug_id NOT IN (SELECT id FROM fahrzeuge)").fetchone()[0]
    if lose:
        raise MigrationsFehler(f"Schritt 11: {lose} Inserate verweisen auf ein fehlendes Fahrzeug")


_ZAEHLE_V11 = ("inserate", "beobachtungen", "preis_historie", "bearbeitung", "besichtigungen", "ankaeufe", "anzeigen", "fahrzeuge")


def _zaehle_v11(con: sqlite3.Connection) -> dict[str, int]:
    """Zeilenzahlen der Tabellen, die Schritt 11 nicht verändern darf (plus ``fahrzeuge``, das genau so viele Zeilen wie ``inserate`` bekommt)."""
    vorhanden = _tabellen(con)
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _ZAEHLE_V11 if t in vorhanden}


_SPALTEN_V12 = {
    "dubletten_entscheidungen": ["id", "inserat_a", "inserat_b", "entscheidung", "status", "konfidenz", "gruende_json", "regel_version",
                                 "nutzer_id", "zeitpunkt", "aufgehoben_von", "aufgehoben_am"],
    "fahrzeug_zuordnungen": ["id", "entscheidung_id", "inserat_id", "von_fahrzeug", "nach_fahrzeug", "art", "nutzer_id", "zeitpunkt"],
}


def _schritt_12(con: sqlite3.Connection):
    """Additive v12 (P3-02a): Grundlage für bestätigte Dublettenentscheidungen. ``dubletten_entscheidungen`` hält je Inseratspaar
    (``inserat_a < inserat_b``) höchstens EINE geltende Entscheidung (gleich/verschieden); aufgehobene bleiben als Verlauf stehen.
    Eine Entscheidung wird nie gelöscht und nie inhaltlich geändert: erlaubt ist nur ``gilt`` → ``aufgehoben`` mit ``aufgehoben_am``
    (``aufgehoben_von`` = Nutzer-ID, im Einzelplatz ohne Nutzer NULL); eine neue Entscheidung ist eine neue Zeile (Trigger).
    ``fahrzeug_zuordnungen`` protokolliert jedes Umhängen eines Inserats auf ein anderes Fahrzeug (nur anfügbar, Trigger).
    Beide Tabellen bleiben vorerst leer; es wird NICHTS zusammengeführt und kein Bestandsdatensatz verändert."""
    vorher = _zaehle_v11(con)
    con.execute("""CREATE TABLE IF NOT EXISTS dubletten_entscheidungen (
        id INTEGER PRIMARY KEY,
        inserat_a INTEGER NOT NULL REFERENCES inserate(id), inserat_b INTEGER NOT NULL REFERENCES inserate(id),
        entscheidung TEXT NOT NULL CHECK(entscheidung IN ('gleich', 'verschieden')),
        status TEXT NOT NULL CHECK(status IN ('gilt', 'aufgehoben')),
        konfidenz TEXT CHECK(konfidenz IS NULL OR konfidenz IN ('hoch', 'mittel')),
        gruende_json TEXT NOT NULL, regel_version INTEGER NOT NULL,
        nutzer_id INTEGER, zeitpunkt TEXT NOT NULL, aufgehoben_von INTEGER, aufgehoben_am TEXT,
        CHECK(inserat_a < inserat_b))""")
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_dubletten_gilt ON dubletten_entscheidungen(inserat_a, inserat_b)
        WHERE status = 'gilt'""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dubletten_b ON dubletten_entscheidungen(inserat_b)")      # „Entscheidungen zu Inserat X“
    con.execute("""CREATE TRIGGER IF NOT EXISTS dubletten_entscheidungen_kein_delete BEFORE DELETE ON dubletten_entscheidungen
        BEGIN SELECT RAISE(ABORT, 'dubletten_entscheidungen wird nicht gelöscht, nur aufgehoben'); END""")
    unveraendert = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in ("id", "inserat_a", "inserat_b", "entscheidung", "konfidenz", "gruende_json",
                                                              "regel_version", "nutzer_id", "zeitpunkt"))
    con.execute(f"""CREATE TRIGGER IF NOT EXISTS dubletten_entscheidungen_nur_aufheben BEFORE UPDATE ON dubletten_entscheidungen
        WHEN NOT (OLD.status = 'gilt' AND NEW.status = 'aufgehoben' AND OLD.aufgehoben_am IS NULL AND NEW.aufgehoben_am IS NOT NULL
                  AND OLD.aufgehoben_von IS NULL AND {unveraendert})
        BEGIN SELECT RAISE(ABORT, 'dubletten_entscheidungen: nur gilt -> aufgehoben (mit aufgehoben_am) erlaubt'); END""")
    con.execute("""CREATE TABLE IF NOT EXISTS fahrzeug_zuordnungen (
        id INTEGER PRIMARY KEY,
        entscheidung_id INTEGER NOT NULL REFERENCES dubletten_entscheidungen(id),
        inserat_id INTEGER NOT NULL REFERENCES inserate(id),
        von_fahrzeug INTEGER NOT NULL REFERENCES fahrzeuge(id), nach_fahrzeug INTEGER NOT NULL REFERENCES fahrzeuge(id),
        art TEXT NOT NULL CHECK(art IN ('zusammen', 'zurueck')), nutzer_id INTEGER, zeitpunkt TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_zuordnungen_inserat ON fahrzeug_zuordnungen(inserat_id, id)")
    for art in ("UPDATE", "DELETE"):
        con.execute(f"""CREATE TRIGGER IF NOT EXISTS fahrzeug_zuordnungen_kein_{art.lower()} BEFORE {art} ON fahrzeug_zuordnungen
            BEGIN SELECT RAISE(ABORT, 'fahrzeug_zuordnungen ist nur anfügbar'); END""")
    for tabelle, erwartet in _SPALTEN_V12.items():      # eine schon vorhandene, abweichende Tabelle würde von IF NOT EXISTS übergangen
        if [r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")] != erwartet:
            raise MigrationsFehler(f"Schritt 12: Tabelle {tabelle} hat nicht die erwarteten Spalten")
    nachher = _zaehle_v11(con)
    if nachher != vorher:
        raise MigrationsFehler(f"Zeilenzahlen haben sich bei Schritt 12 geändert: {vorher} -> {nachher}")


def _schritt_13(con: sqlite3.Connection):
    """Additive v13 (P3-04, ADR-042): ``inserate.zuletzt_bestaetigt`` = Zeitpunkt (UTC) der letzten Beobachtung, die die gespeicherte Verfügbarkeit
    bestätigt hat – anders als ``zuletzt_gesehen`` (jede Beobachtung, bei Mails die Einlesezeit) und Grundlage der Altersregel (eine ältere
    Beobachtung überschreibt keine neuere) und des abgeleiteten „vermutlich offline“. Altbestand: Für ``aktiv`` und ``offline`` war
    ``zuletzt_gesehen`` genau der Zeitpunkt der Beobachtung, die den Wert setzte; er wird übernommen (nach UTC). ``unbekannt`` bleibt ohne Wert.
    Außerdem der Index ``fahrzeug_zuordnungen(entscheidung_id)`` (Befund aus P3-02b). Kein Wert und keine Zeile wird verändert oder gelöscht."""
    vorher = _zaehle_v11(con)
    feste = "SELECT id, plattform, anzeigen_id, url, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen, fahrzeug_id FROM inserate ORDER BY id"
    vorher_inhalt = hashlib.sha256(repr([tuple(r) for r in con.execute(feste)]).encode()).hexdigest()
    _neue_spalte(con, "inserate", "zuletzt_bestaetigt", "TEXT")
    umzusetzen = []
    offen = con.execute("SELECT id, zuletzt_gesehen FROM inserate WHERE zuletzt_bestaetigt IS NULL AND verfuegbarkeit IN ('aktiv', 'offline')").fetchall()
    for iid, gesehen in offen:
        try:
            zeit = datetime.fromisoformat(gesehen).astimezone(timezone.utc).isoformat(timespec="seconds") if gesehen else None
        except (TypeError, ValueError):
            zeit = None                       # nicht lesbar: bleibt leer, die Anzeige fällt auf zuletzt_gesehen zurück
        if zeit:
            umzusetzen.append((zeit, iid))
    con.executemany("UPDATE inserate SET zuletzt_bestaetigt = ? WHERE id = ?", umzusetzen)
    con.execute("CREATE INDEX IF NOT EXISTS idx_zuordnungen_entscheidung ON fahrzeug_zuordnungen(entscheidung_id)")
    nachher = _zaehle_v11(con)
    if nachher != vorher:
        raise MigrationsFehler(f"Zeilenzahlen haben sich bei Schritt 13 geändert: {vorher} -> {nachher}")
    if hashlib.sha256(repr([tuple(r) for r in con.execute(feste)]).encode()).hexdigest() != vorher_inhalt:
        raise MigrationsFehler("Schritt 13: bestehende Inseratsspalten haben sich verändert")


def _schritt_14(con: sqlite3.Connection):
    """Additive v14 (P3-05, ADR-043): ``anzeigen.anbieter_herkunft`` = worauf die Anbieterart (``gewerblich`` 0/1) beruht, siehe ``anbieter.py``.
    Altbestand mit bekannter Anbieterart erhält ``altbestand`` (Herkunft nicht mehr feststellbar; Betreiberfrage F6: die Art selbst bleibt),
    unbekannte (NULL) bleiben ohne Herkunft. Kein bestehender Wert und keine Zeile wird verändert oder gelöscht."""
    vorher = _zaehle_v11(con)
    spalten = ", ".join(r[1] for r in con.execute("PRAGMA table_info(anzeigen)") if r[1] != "anbieter_herkunft")

    def inhalt() -> str:
        return hashlib.sha256(repr([tuple(r) for r in con.execute(f"SELECT {spalten} FROM anzeigen ORDER BY id")]).encode()).hexdigest()
    vorher_inhalt = inhalt()
    _neue_spalte(con, "anzeigen", "anbieter_herkunft", "TEXT")
    con.execute("UPDATE anzeigen SET anbieter_herkunft = 'altbestand' WHERE anbieter_herkunft IS NULL AND gewerblich IS NOT NULL")
    nachher = _zaehle_v11(con)
    if nachher != vorher:
        raise MigrationsFehler(f"Zeilenzahlen haben sich bei Schritt 14 geändert: {vorher} -> {nachher}")
    if inhalt() != vorher_inhalt:
        raise MigrationsFehler("Schritt 14: bestehende Spalten von „anzeigen“ haben sich verändert")


SCHRITTE: dict[int, Callable[[sqlite3.Connection], None]] = {2: _schritt_2, 3: _schritt_3, 4: _schritt_4, 5: _schritt_5,
                                                             6: _schritt_6, 7: _schritt_7, 8: _schritt_8, 9: _schritt_9,
                                                             10: _schritt_10, 11: _schritt_11, 12: _schritt_12, 13: _schritt_13,
                                                             14: _schritt_14}

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
