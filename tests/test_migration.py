"""Migrationsrahmen: v1 (ZIP-Stand) und v2 (Stand vor Phase 1) -> v4 ohne Datenverlust, Sicherung vor Migration, Schutzregeln."""
import hashlib
import sqlite3

import pytest

from tests.test_datenbank import SCHEMA_V1
from wmscout import migrationen
from wmscout.datenbank import Datenbank
from wmscout.migrationen import AKTUELLE_VERSION, MigrationsFehler, lese_version, migriere
from wmscout.sicherung import SicherungsFehler, sichere, sicherungen, wiederherstellen


def _sql(pfad, befehl, *param):
    """SQL ausführen und die Verbindung sofort schließen (unter Windows sperrt eine offene Verbindung die Datei)."""
    con = sqlite3.connect(pfad)
    try:
        zeilen = con.execute(befehl, param).fetchall()
        con.commit()
        return zeilen
    finally:
        con.close()


# Stand vor Phase 1, unabhängig von migrationen.py nachgebaut (damit der Test den Altbestand wirklich abbildet)
SCHEMA_V2 = """
CREATE TABLE anzeigen (
    id TEXT PRIMARY KEY, url TEXT, suche TEXT, titel TEXT, preis INTEGER, vb INTEGER,
    ort TEXT, km INTEGER, ez_jahr INTEGER, marke TEXT, art TEXT, leistung TEXT, getriebe TEXT,
    kurzbeschreibung TEXT, beschreibung TEXT, gewerblich INTEGER DEFAULT 0, details_json TEXT,
    detail_geladen INTEGER DEFAULT 0, erstmals_gesehen TEXT, zuletzt_gesehen TEXT, preis_vorher INTEGER,
    status TEXT DEFAULT 'neu', notiz TEXT,
    bild TEXT, kontaktiert_am TEXT, anschreiben_text TEXT,
    preis_geaendert_am TEXT, nachgefasst_am TEXT, nachfass_anzahl INTEGER DEFAULT 0,
    angebot_betrag INTEGER, status_am TEXT, quelle TEXT);
CREATE INDEX idx_zuletzt ON anzeigen(zuletzt_gesehen);
CREATE TABLE nutzer (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, rolle TEXT NOT NULL DEFAULT 'mitarbeiter',
    passwort_hash TEXT NOT NULL, telefon TEXT, aktiv INTEGER NOT NULL DEFAULT 1, erstellt_am TEXT);
CREATE TABLE sitzungen (token_hash TEXT PRIMARY KEY, nutzer_id INTEGER NOT NULL, ablauf TEXT NOT NULL);
CREATE TABLE besichtigungen (
    id INTEGER PRIMARY KEY, anzeige_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'geplant',
    termin TEXT, adresse TEXT, zustaendig_id INTEGER, erstellt_von INTEGER, erstellt_am TEXT, geaendert_am TEXT,
    daten_json TEXT NOT NULL DEFAULT '{}', basis_json TEXT NOT NULL DEFAULT '{}', ergebnis_json TEXT,
    protokoll_json TEXT, endpreis INTEGER, version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX idx_besichtigung_anzeige ON besichtigungen(anzeige_id);
CREATE TABLE fotos (id INTEGER PRIMARY KEY, besichtigung_id INTEGER NOT NULL, mangel_key TEXT, datei TEXT NOT NULL,
    erstellt_am TEXT, nutzer_id INTEGER);
"""

ZEILEN_V1 = [
    ("1", "Knaus Sky TI 650", 40000, "kontaktiert", "alte Notiz Müller 0171 1234567", "2026-01-01T10:00:00"),
    ("2", "Hymer B-Klasse", 55500, "neu", None, "2026-01-02T10:00:00"),
    ("3", "Dethleffs Globebus", 1, "gekauft", "Preis 1 € = Platzhalter", "2026-01-03T10:00:00"),
]


def baue_v1(pfad):
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA_V1)
    con.executemany("INSERT INTO anzeigen (id, titel, preis, status, notiz, zuletzt_gesehen) VALUES (?,?,?,?,?,?)", ZEILEN_V1)
    con.commit()
    con.close()


def baue_v2(pfad):
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA_V2)
    con.executemany("INSERT INTO anzeigen (id, titel, preis, status, notiz, zuletzt_gesehen) VALUES (?,?,?,?,?,?)", ZEILEN_V1)
    con.execute("UPDATE anzeigen SET kontaktiert_am='2026-01-05T09:00:00', anschreiben_text='Hallo Herr Müller', "
                "angebot_betrag=36000, nachfass_anzahl=2, quelle='kleinanzeigen', bild='b.jpg' WHERE id='1'")
    con.execute("INSERT INTO nutzer (name, passwort_hash, telefon, erstellt_am) VALUES ('Anna', 'scrypt$x', '+49170', '2026-01-01')")
    con.execute("INSERT INTO sitzungen VALUES ('h', 1, '2027-01-01T00:00:00')")
    con.execute("INSERT INTO besichtigungen (anzeige_id, zustaendig_id, daten_json) VALUES ('1', 1, '{\"a\": 1}')")
    con.execute("INSERT INTO fotos (besichtigung_id, datei) VALUES (1, 'x.jpg')")
    con.commit()
    con.close()


def zeilen(pfad, tabelle, spalten="*") -> list:
    con = sqlite3.connect(pfad)
    try:
        return sorted(map(tuple, con.execute(f"SELECT {spalten} FROM {tabelle}").fetchall()), key=repr)
    finally:
        con.close()


def spaltennamen(pfad, tabelle) -> list[str]:
    con = sqlite3.connect(pfad)
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")]
    finally:
        con.close()


def tabellen(pfad) -> set[str]:
    con = sqlite3.connect(pfad)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def pruefsumme(pfad) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def versionen(pfad) -> list[int]:
    return [r[0] for r in zeilen(pfad, "schema_version", "version")]


def test_v1_wird_erkannt_und_ohne_verlust_migriert(tmp_path):
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    baue_v1(pfad)
    assert lese_version(pfad) == 1
    spalten_alt = spaltennamen(pfad, "anzeigen")
    vorher = zeilen(pfad, "anzeigen")
    assert len(vorher) == 3

    assert migriere(pfad, ziel) == [2, 3, 4]
    assert lese_version(pfad) == AKTUELLE_VERSION == 4
    assert versionen(pfad) == [1, 2, 3, 4]                                       # Ausgangsstand 1 wird festgehalten
    nachher_spalten = spaltennamen(pfad, "anzeigen")
    assert set(spalten_alt) <= set(nachher_spalten) and set(migrationen.NEUE_SPALTEN) <= set(nachher_spalten)
    assert zeilen(pfad, "anzeigen", ", ".join(spalten_alt)) == vorher            # alle alten Zeilen und Spalten unverändert
    assert len(zeilen(pfad, "anzeigen")) == 3
    z = _sql(pfad, "SELECT status, notiz, preis FROM anzeigen WHERE id='1'")[0]
    assert z == ("kontaktiert", "alte Notiz Müller 0171 1234567", 40000)
    assert {"nutzer", "sitzungen", "besichtigungen", "fotos", "bearbeitung", "schema_version"} <= tabellen(pfad)
    assert spaltennamen(pfad, "bearbeitung") == ["anzeige_id", "bearbeiter_id", "uebernommen_am", "kontaktiert_von", "kontaktiert_am"]

    # Sicherung vor der Migration existiert, ist heil und enthält den Stand von Version 1
    kopie = sicherungen(ziel, "alt")
    assert len(kopie) == 1 and "vor-v4" in kopie[0].name
    assert _sql(kopie[0], "PRAGMA integrity_check")[0][0] == "ok"
    assert lese_version(kopie[0]) == 1 and zeilen(kopie[0], "anzeigen") == vorher


def test_v2_wird_erkannt_und_ohne_verlust_migriert(tmp_path):
    pfad, ziel = tmp_path / "heute.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    assert lese_version(pfad) == 2
    vorher = {t: zeilen(pfad, t) for t in ("anzeigen", "nutzer", "sitzungen", "besichtigungen", "fotos")}
    assert [len(v) for v in vorher.values()] == [3, 1, 1, 1, 1]

    assert migriere(pfad, ziel) == [3, 4]
    assert versionen(pfad) == [2, 3, 4]
    for t, alt in vorher.items():
        assert zeilen(pfad, t) == alt, t                                        # inkl. kontaktiert_am, Texte, Preise, Team
    z = _sql(pfad, "SELECT kontaktiert_am, anschreiben_text, angebot_betrag, status, notiz, quelle "
                                      "FROM anzeigen WHERE id='1'")[0]
    assert z == ("2026-01-05T09:00:00", "Hallo Herr Müller", 36000, "kontaktiert", "alte Notiz Müller 0171 1234567", "kleinanzeigen")
    assert lese_version(sicherungen(ziel, "heute")[0]) == 2


def test_teilweise_ergaenzte_datenbank_gilt_als_v1_und_wird_vervollstaendigt(tmp_path):
    pfad = tmp_path / "halb.sqlite"
    baue_v1(pfad)
    con = sqlite3.connect(pfad)
    con.execute("ALTER TABLE anzeigen ADD COLUMN bild TEXT")
    con.execute("ALTER TABLE anzeigen ADD COLUMN quelle TEXT")
    con.execute("UPDATE anzeigen SET bild='b.jpg' WHERE id='2'")
    con.commit()
    con.close()
    assert lese_version(pfad) == 1
    assert migriere(pfad, tmp_path / "s") == [2, 3, 4]
    assert set(migrationen.NEUE_SPALTEN) <= set(spaltennamen(pfad, "anzeigen"))
    assert _sql(pfad, "SELECT bild FROM anzeigen WHERE id='2'")[0] == ("b.jpg",)


@pytest.mark.parametrize("baue", [baue_v1, baue_v2])
def test_zweiter_start_aendert_nichts(tmp_path, baue):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue(pfad)
    Datenbank(str(pfad), str(ziel)).con.close()
    fest, schema, anzahl = pruefsumme(pfad), zeilen(pfad, "schema_version"), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == []
    Datenbank(str(pfad), str(ziel)).con.close()
    assert pruefsumme(pfad) == fest and zeilen(pfad, "schema_version") == schema     # byte-identisch
    assert len(sicherungen(ziel, "db")) == anzahl                                    # keine weitere Sicherung


def test_neue_datenbank_direkt_in_aktueller_version_ohne_sicherung(tmp_path):
    neu, ziel = tmp_path / "neu.sqlite", tmp_path / "sich"
    Datenbank(str(neu), str(ziel)).con.close()
    assert versionen(neu) == [AKTUELLE_VERSION]
    assert not ziel.exists()                                                  # leere Datenbank wird nicht gesichert
    migriert = tmp_path / "migriert.sqlite"
    baue_v1(migriert)
    migriere(migriert, ziel)
    assert tabellen(neu) == tabellen(migriert)
    for t in tabellen(neu):
        assert sorted(spaltennamen(neu, t)) == sorted(spaltennamen(migriert, t)), t


def test_ohne_moegliche_sicherung_keine_migration(tmp_path):
    pfad, blockiert = tmp_path / "db.sqlite", tmp_path / "ist-eine-datei"
    baue_v1(pfad)
    blockiert.write_text("kein Ordner")
    fest = pruefsumme(pfad)
    with pytest.raises(MigrationsFehler, match="Sicherung"):
        Datenbank(str(pfad), str(blockiert))
    assert pruefsumme(pfad) == fest and lese_version(pfad) == 1 and "schema_version" not in tabellen(pfad)


def test_datenbank_neuer_als_code_bricht_ab_ohne_schreiben(tmp_path):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    migriere(pfad, ziel)
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO schema_version VALUES (99, '2030-01-01T00:00:00')")
    con.commit()
    con.close()
    fest, anzahl = pruefsumme(pfad), len(list(ziel.iterdir()))
    with pytest.raises(MigrationsFehler, match="99.*aktualisieren|Version 99"):
        Datenbank(str(pfad), str(ziel))
    assert pruefsumme(pfad) == fest and len(list(ziel.iterdir())) == anzahl


def test_fehlgeschlagener_schritt_wird_zurueckgerollt(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    vorher = {t: zeilen(pfad, t) for t in ("anzeigen", "nutzer", "besichtigungen")}

    def kaputt(con):
        con.execute("CREATE TABLE bearbeitung (anzeige_id TEXT PRIMARY KEY)")
        con.execute("DELETE FROM anzeigen")                                     # richtet Schaden an, dann Fehler
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 3, kaputt)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 2 and "bearbeitung" not in tabellen(pfad) and "schema_version" not in tabellen(pfad)
    assert {t: zeilen(pfad, t) for t in vorher} == vorher
    assert len(sicherungen(ziel, "db")) == 1                                   # Sicherung bleibt als Rückweg
    monkeypatch.undo()
    assert migriere(pfad, ziel) == [3, 4]                                          # nach Behebung läuft die Migration durch


def test_schritt_3_scheitert_nach_erfolgreichem_schritt_2(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v1(pfad)
    monkeypatch.setitem(migrationen.SCHRITTE, 3, lambda con: 1 / 0)
    with pytest.raises(MigrationsFehler):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 2 and versionen(pfad) == [1, 2]               # Schritt 2 gilt, Schritt 3 nicht
    assert len(zeilen(pfad, "anzeigen")) == 3
    monkeypatch.undo()
    assert migriere(pfad, ziel) == [3, 4] and versionen(pfad) == [1, 2, 3, 4]


def test_unlesbare_datei_und_fremde_datenbank(tmp_path):
    kaputt = tmp_path / "kaputt.sqlite"
    kaputt.write_bytes(b"kein sqlite" * 200)
    with pytest.raises(MigrationsFehler, match="nicht als SQLite"):
        migriere(kaputt, tmp_path / "s")
    assert kaputt.read_bytes() == b"kein sqlite" * 200
    fremd = tmp_path / "fremd.sqlite"
    con = sqlite3.connect(fremd)
    con.execute("CREATE TABLE etwas (x)")
    con.commit()
    con.close()
    with pytest.raises(MigrationsFehler, match="keine Wohnmobil-Scout-Datenbank"):
        migriere(fremd, tmp_path / "s")
    assert tabellen(fremd) == {"etwas"}


def test_rueckweg_pre_migration_sicherung_stellt_v1_wieder_her(tmp_path):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v1(pfad)
    vorher = zeilen(pfad, "anzeigen")
    Datenbank(str(pfad), str(ziel)).con.close()
    assert lese_version(pfad) == 4
    wiederherstellen(sicherungen(ziel, "db")[0], pfad, bestaetigt=True, ziel_ordner=ziel)
    assert lese_version(pfad) == 1 and zeilen(pfad, "anzeigen") == vorher
    Datenbank(str(pfad), str(ziel)).con.close()                                # und lässt sich erneut migrieren
    assert lese_version(pfad) == 4 and len(zeilen(pfad, "anzeigen")) == 3


# ---------- Korrekturrunde 1: H1 (Migration räumt nicht auf), M3/M4-Mutanten, paralleles Anlegen, N2 ----------

def test_h1_migration_loescht_keine_sicherungen_auch_bei_voller_aufbewahrung(tmp_path):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    vorhandene = [sichere(pfad, ziel, behalten=20) for _ in range(15)]           # Betreiber: config sicherung.behalten = 20
    assert len(sicherungen(ziel, "db")) == 15
    assert migriere(pfad, ziel) == [3, 4]
    jetzt = sicherungen(ziel, "db")
    assert len(jetzt) == 16 and all(v in jetzt for v in vorhandene)               # nichts gelöscht, nur die Migrationssicherung dazu
    assert jetzt[-1].name.endswith("-vor-v4.sqlite")


def test_h1_migrationssicherungen_bleiben_bis_eine_normale_sicherung_nach_konfiguration_aufraeumt(tmp_path):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    for _ in range(12):
        sichere(pfad, ziel, behalten=20)
    migriere(pfad, ziel)
    assert len(sicherungen(ziel, "db")) == 13
    sichere(pfad, ziel, behalten=5)                                               # normale Sicherung räumt nach Konfiguration auf
    assert len(sicherungen(ziel, "db")) == 5


def test_m3_stille_zeilenverluste_in_einem_schritt_werden_zurueckgerollt(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    vorher = {t: zeilen(pfad, t) for t in ("anzeigen", "nutzer", "besichtigungen", "fotos")}
    monkeypatch.setitem(migrationen.SCHRITTE, 3, lambda con: con.execute("DELETE FROM anzeigen WHERE id='2'"))    # wirft keinen Fehler
    with pytest.raises(MigrationsFehler, match="Zeilenzahl"):
        migriere(pfad, ziel)
    assert {t: zeilen(pfad, t) for t in vorher} == vorher and lese_version(pfad) == 2
    monkeypatch.setitem(migrationen.SCHRITTE, 3, lambda con: con.execute("INSERT INTO nutzer (name, passwort_hash) VALUES ('Neu', 'x')"))
    with pytest.raises(MigrationsFehler, match="Zeilenzahl"):
        migriere(pfad, ziel)                                                       # auch zusätzliche Zeilen sind nicht erlaubt
    assert {t: zeilen(pfad, t) for t in vorher} == vorher


def test_m4_zweiter_prozess_war_schneller_schritt_laeuft_nicht_doppelt(tmp_path, monkeypatch):
    pfad = tmp_path / "db.sqlite"
    baue_v2(pfad)
    veraltet = sqlite3.connect(pfad, isolation_level=None)                          # hat Stand 2 erkannt ...
    assert migrationen.erkenne_version(veraltet) == 2
    migriere(pfad, tmp_path / "sich")                                               # ... da migriert ein anderer Prozess auf 3
    aufrufe = []
    monkeypatch.setitem(migrationen.SCHRITTE, 3, lambda con: aufrufe.append(1))
    migrationen._fuehre_aus(veraltet, 3, 2)
    veraltet.close()
    assert aufrufe == [] and versionen(pfad) == [2, 3, 4] and not veraltet_in_transaktion(pfad)


def veraltet_in_transaktion(pfad) -> bool:
    con = sqlite3.connect(pfad, timeout=0.5, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")                                              # gelingt nur, wenn keine Sperre hängen blieb
        con.execute("ROLLBACK")
        return False
    finally:
        con.close()


def test_m3_paralleles_neuanlegen_zweiter_bekommt_keinen_integrity_error(tmp_path):
    pfad = tmp_path / "neu.sqlite"
    a = sqlite3.connect(pfad, isolation_level=None)
    b = sqlite3.connect(pfad, isolation_level=None)
    assert migrationen.erkenne_version(a) == 0 and migrationen.erkenne_version(b) == 0     # beide sehen "leer"
    assert migrationen._neu_anlegen(a) is True
    assert migrationen._neu_anlegen(b) is False                                     # kein sqlite3.IntegrityError, nichts doppelt
    a.close()
    b.close()
    assert versionen(pfad) == [AKTUELLE_VERSION] and lese_version(pfad) == AKTUELLE_VERSION


def test_m3_paralleler_start_mehrerer_threads(tmp_path):
    import threading
    pfad, ziel = tmp_path / "neu.sqlite", tmp_path / "sich"
    start, fehler, ergebnisse = threading.Barrier(6), [], []

    def lauf():
        try:
            start.wait()
            ergebnisse.append(migriere(pfad, ziel))
        except BaseException as e:  # noqa: BLE001
            fehler.append(e)

    threads = [threading.Thread(target=lauf) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert fehler == []
    assert sorted(map(tuple, ergebnisse)) == [()] * 5 + [(AKTUELLE_VERSION,)]       # genau einer hat angelegt
    assert versionen(pfad) == [AKTUELLE_VERSION] and not ziel.exists()


def test_n2_lese_version_legt_nichts_an(tmp_path):
    fehlt = tmp_path / "gibtsnicht.sqlite"
    with pytest.raises(sqlite3.Error):
        lese_version(fehlt)
    assert not fehlt.exists() and list(tmp_path.iterdir()) == []
    leer = tmp_path / "leer.sqlite"
    leer.write_bytes(b"")
    assert lese_version(leer) == 0 and leer.stat().st_size == 0


def test_n3_app_nutzt_sicherungsordner_aus_der_konfiguration(cfg, tmp_path):
    from wmscout.app import Suchlauf
    baue_v1(tmp_path / "anzeigen.sqlite")
    cfg["ausgabe"]["datenbank"] = str(tmp_path / "anzeigen.sqlite")
    cfg["sicherung"] = {"ordner": "eigene-sicherungen", "behalten": 5}
    Suchlauf(cfg, cfg["ausgabe"]["datenbank"], tmp_path).oeffne_datenbank().con.close()
    assert len(sicherungen(tmp_path / "eigene-sicherungen", "anzeigen")) == 1       # nicht daten/sicherungen neben der Datenbank
    assert not (tmp_path / "sicherungen").exists()


# ---------- Korrekturrunde 2 ----------

@pytest.mark.parametrize("zusatz", [1])
def test_q24_q25_schemaversion_knapp_ueber_dem_code_wird_bei_wiederherstellung_und_start_abgewiesen(tmp_path, zusatz):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    migriere(pfad, ziel)
    neu = AKTUELLE_VERSION + zusatz
    kopie = sichere(pfad, ziel)
    fest_sicherung = pruefsumme(kopie)
    for datei in (pfad, kopie):
        con = sqlite3.connect(datei)
        con.execute("INSERT INTO schema_version VALUES (?, '2030-01-01T00:00:00')", (neu,))
        con.commit()
        con.close()
    leer = tmp_path / "ziel.sqlite"
    baue_v2(leer)
    fest = pruefsumme(leer)
    with pytest.raises(SicherungsFehler, match=f"Schemaversion {neu}"):                # Wiederherstellung
        wiederherstellen(kopie, leer, bestaetigt=True, ziel_ordner=ziel)
    assert pruefsumme(leer) == fest
    fest_live = pruefsumme(pfad)
    with pytest.raises(MigrationsFehler, match=f"Schemaversion {neu}"):                # Start
        Datenbank(str(pfad), str(ziel))
    assert pruefsumme(pfad) == fest_live and pruefsumme(kopie) != fest_sicherung       # (Kopie wurde absichtlich verändert)


def test_q23_parallel_angelegte_aeltere_datenbank_wird_neu_beurteilt_und_migriert(tmp_path, monkeypatch):
    """Ein zweiter Prozess (ältere Programmversion) legt die Datenbank gerade im Stand v2 an: nicht einfach "fertig" melden."""
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"

    def anderer_prozess_war_schneller(con):
        baue_v2(pfad)
        return False

    monkeypatch.setattr(migrationen, "_neu_anlegen", anderer_prozess_war_schneller)
    assert migriere(pfad, ziel) == [3, 4]
    assert lese_version(pfad) == AKTUELLE_VERSION and versionen(pfad) == [2, 3, 4]
    assert len(zeilen(pfad, "anzeigen")) == len(ZEILEN_V1) and len(sicherungen(ziel, "db")) == 1


def test_f2_sicherungsfehler_aber_anderer_prozess_hat_schon_migriert_ist_kein_fehler(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v2(pfad)
    echt = migrationen.sichere

    def anderer_prozess_migriert_dann_scheitert_die_sicherung(*a, **k):
        monkeypatch.setattr(migrationen, "sichere", echt)
        assert migriere(pfad, ziel) == [3, 4]
        raise SicherungsFehler("simuliert: Namenskonflikt")

    monkeypatch.setattr(migrationen, "sichere", anderer_prozess_migriert_dann_scheitert_die_sicherung)
    assert migriere(pfad, ziel) == []
    assert versionen(pfad) == [2, 3, 4] and len(zeilen(pfad, "anzeigen")) == len(ZEILEN_V1)


def test_f2_zwei_echte_prozesse_gleichzeitig_auf_altbestand_kein_abbruch_genau_eine_migration(tmp_path):
    import subprocess
    import sys
    import time
    from pathlib import Path
    code = ("import sys, time\nfrom wmscout.migrationen import migriere\n"
            "while time.time() < float(sys.argv[3]): pass\n"
            "try:\n    print('OK', migriere(sys.argv[1], sys.argv[2]))\n"
            "except Exception as e:\n    print('FEHLER', e)\n")
    wurzel = Path(__file__).resolve().parent.parent
    for runde in range(3):
        pfad, ziel = tmp_path / f"r{runde}.sqlite", tmp_path / f"sich{runde}"
        baue_v2(pfad)
        vorher = {t: zeilen(pfad, t) for t in ("anzeigen", "nutzer", "sitzungen", "besichtigungen", "fotos")}
        start = str(time.time() + 1.5)
        prozesse = [subprocess.Popen([sys.executable, "-c", code, str(pfad), str(ziel), start], cwd=wurzel, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        ausgaben = [p.communicate(timeout=120) for p in prozesse]
        meldungen = sorted(o.strip() for o, _ in ausgaben)
        assert all(m.startswith("OK") for m in meldungen), ausgaben
        assert all(m in {"OK []", "OK [3]", "OK [4]", "OK [3, 4]"} for m in meldungen), meldungen
        assert sum(m in {"OK [3]", "OK [3, 4]"} for m in meldungen) == 1, meldungen
        assert sum(m in {"OK [4]", "OK [3, 4]"} for m in meldungen) == 1, meldungen  # jeder Schritt genau einmal
        assert versionen(pfad) == [2, 3, 4]
        assert {t: zeilen(pfad, t) for t in vorher} == vorher                                      # nichts verloren
        for s in sicherungen(ziel, "r" + str(runde)):
            assert _sql(s, "PRAGMA integrity_check")[0][0] == "ok"
        assert not [p for p in ziel.iterdir() if p.name.startswith(".")]                           # keine Arbeits-/Reservierungsreste
