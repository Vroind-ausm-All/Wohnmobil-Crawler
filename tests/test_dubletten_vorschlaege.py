"""P3-02a: Schema 12 (Dublettenentscheidungen, Zuordnungsprotokoll), Vorschläge beim Lesen, API, CLI.

Alles ohne fachliche Wirkung: Bewertung, Anschreiben und Team-Sperre bleiben unverändert (``bewerte_zeilen`` vor/nach identisch).
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import json
import random
import sqlite3
import time

import pytest

from tests.test_cli import _scout
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue, baue_v10
from tests.test_team_bearbeitung import anmelden, lokal, server, starte  # noqa: F401 – Fixtures
from tests.test_migration import pruefsumme, tabellen, versionen
from wmscout import migrationen
from tests.daten import BASIS
from wmscout.bewertung.auswertung import bewerte_alle, dubletten_ids
from wmscout.datenbank import IMPORT_SUCHE, Datenbank
from wmscout.app import _kontext
from wmscout.dubletten import MAX_LIMIT, dubletten_vorschlaege, pruefe_dubletten
from wmscout.haendler import HaendlerSpeicher
from wmscout.migrationen import AKTUELLE_VERSION, MigrationsFehler, lese_version, migriere
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.sicherung import sicherungen, wiederherstellen
from wmscout.team import TeamSpeicher

NEU = ("dubletten_entscheidungen", "fahrzeug_zuordnungen")
JETZT = "2026-10-20T10:00:00Z"


def baue_v11(pfad, monkeypatch, ziel):
    """Stand von P3-01 (Schema 11) mit dem Bestand von ``baue_v10``."""
    baue_v10(pfad, monkeypatch)
    with monkeypatch.context() as m:
        _alt_schritte(m, 11)
        assert migriere(pfad, ziel / "stand11") == [11]
    assert lese_version(pfad) == 11


# ---------------------------------------------------------------- 1. Migration auf 12
@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v11"])
def test_migration_auf_12_ohne_datenverlust(tmp_path, monkeypatch, art):
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v11":
        baue_v11(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    zaehlung = {t: len(z) for t, (_, z) in vorher.items()}
    erledigt = migriere(pfad, ziel)
    assert erledigt == list(range(vorher_version + 1, 13)) or art == "v1" and erledigt == list(range(2, 13))
    assert lese_version(pfad) == AKTUELLE_VERSION == 12 and versionen(pfad)[-1] == 12
    assert set(NEU) <= tabellen(pfad)
    nachher = _abbild(pfad)
    assert {t: len(nachher[t][1]) for t in zaehlung if t != "fahrzeuge"} == {t: n for t, n in zaehlung.items() if t != "fahrzeuge"}
    for t in NEU:
        assert nachher[t][1] == []                                                    # neue Tabellen leer
    vorher_ohne_neu = {t: v for t, v in vorher.items() if t not in ("fahrzeuge",)}
    assert {t: v for t, v in _nachher_wie_vorher(pfad, vorher).items() if t in vorher_ohne_neu} == vorher_ohne_neu    # Inhalte und Spalten gleich
    if art in ("v10", "v11"):
        assert _sql(pfad, "SELECT status, notiz, angebot_betrag FROM anzeigen WHERE id='k1'") == [("kontaktiert", "Müller 0171 1234567", 25000)]
        assert _sql(pfad, "SELECT kaufpreis FROM ankaeufe") == [(18000,)]
        assert _sql(pfad, "SELECT COUNT(*) FROM inserate")[0][0] == 4
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)] and _sql(pfad, "PRAGMA foreign_key_check") == []
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v12" in k.name]
    assert len(kopien) == 1 and _sql(kopien[0], "PRAGMA integrity_check") == [("ok",)] and lese_version(kopien[0]) == vorher_version
    assert _abbild(kopien[0]) == vorher                                                   # Sicherung = Stand davor, vollständig


def test_sicherung_vor_v12_laesst_sich_zurueckspielen_und_erneut_migrieren(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    vorher = _abbild(pfad)
    assert migriere(pfad, ziel) == [12]
    kopie = [k for k in sicherungen(ziel, "db") if "vor-v12" in k.name][0]
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
    assert lese_version(pfad) == 11 and _abbild(pfad) == vorher and not set(NEU) & tabellen(pfad)
    assert migriere(pfad, ziel) == [12]
    assert _nachher_wie_vorher(pfad, vorher) == vorher


def test_zweiter_lauf_aendert_nichts_und_schritt_ist_idempotent(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    stand = _abbild(pfad)
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_12(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _abbild(pfad) == stand and _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def _noch_11(pfad, vorher):
    assert lese_version(pfad) == 11 and versionen(pfad)[-1] == 11
    assert not set(NEU) & tabellen(pfad) and _abbild(pfad) == vorher
    assert not _sql(pfad, "SELECT 1 FROM sqlite_master WHERE tbl_name IN ('dubletten_entscheidungen', 'fahrzeug_zuordnungen')")      # auch Indizes/Trigger


def test_verletzte_invariante_rollt_zurueck(tmp_path, monkeypatch):
    """Ein Nebeneffekt, der Zeilen bestehender Tabellen verändert, wird vom Schritt selbst bemerkt: alles zurück, Sicherung bleibt."""
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    vorher = _abbild(pfad)
    echt, aufrufe = migrationen._zaehle_v11, []

    def mit_nebeneffekt(con):
        aufrufe.append(1)
        if len(aufrufe) == 2:                                       # zweite Zählung = nach dem Schritt
            con.execute("INSERT INTO bearbeitung (anzeige_id) VALUES ('eingeschleust')")
        return echt(con)

    monkeypatch.setattr(migrationen, "_zaehle_v11", mit_nebeneffekt)
    with pytest.raises(MigrationsFehler, match="zurückgerollt") as fehler:
        migriere(pfad, ziel)
    assert "Zeilenzahlen" in str(fehler.value) and "bearbeitung" in str(fehler.value)
    _noch_11(pfad, vorher)
    assert any("vor-v12" in k.name for k in sicherungen(ziel, "db"))
    monkeypatch.undo()
    assert migriere(pfad, ziel) == [12]


def test_abweichende_vorhandene_tabelle_rollt_zurueck(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE fahrzeug_zuordnungen (x INTEGER)")        # IF NOT EXISTS würde das übergehen
    con.commit()
    con.close()
    vorher = _abbild(pfad)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 11 and _abbild(pfad) == vorher and "dubletten_entscheidungen" not in tabellen(pfad)


def test_fehler_im_schritt_rollt_zurueck(tmp_path, monkeypatch):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    vorher = _abbild(pfad)
    echt = migrationen._schritt_12

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 12, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    _noch_11(pfad, vorher)


class _Abbruch:
    """Reicht ``con.execute`` durch und bricht beim n-ten Aufruf ab (Abbruch MITTEN im Schritt)."""

    def __init__(self, con, n):
        self.con, self.n, self.i = con, n, 0

    def execute(self, *a):
        self.i += 1
        if self.i == self.n:
            raise RuntimeError(f"Abbruch bei {self.n}")
        return self.con.execute(*a)

    def __getattr__(self, name):
        return getattr(self.con, name)


@pytest.mark.parametrize("n", range(1, 33))
def test_abbruch_mitten_im_schritt_12_rollt_alles_zurueck(tmp_path, monkeypatch, n):
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v11(pfad, monkeypatch, tmp_path)
    vorher = _abbild(pfad)
    echt, aufrufe = migrationen._schritt_12, {}

    def abbrechen(con):
        p = _Abbruch(con, n)
        try:
            echt(p)
        finally:
            aufrufe["i"] = p.i

    monkeypatch.setitem(migrationen.SCHRITTE, 12, abbrechen)
    try:
        migriere(pfad, ziel)
        assert n > aufrufe["i"]                                           # nur Abbruchstellen hinter dem letzten Aufruf laufen durch
        assert lese_version(pfad) == 12
    except MigrationsFehler:
        _noch_11(pfad, vorher)
        assert any("vor-v12" in k.name for k in sicherungen(ziel, "db"))
        monkeypatch.setitem(migrationen.SCHRITTE, 12, echt)
        assert migriere(pfad, ziel) == [12]


def test_abbruch_tests_decken_alle_aufrufe_des_schritts_ab(tmp_path, monkeypatch):
    """Die Spanne 1–32 der Abbruchstellen reicht bis hinter den letzten ``execute``-Aufruf des Schritts."""
    pfad = tmp_path / "db.sqlite"
    baue_v11(pfad, monkeypatch, tmp_path)
    p = None
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        p = _Abbruch(con, 10_000)
        migrationen._schritt_12(p)
        con.execute("ROLLBACK")
    finally:
        con.close()
    assert 0 < p.i < 33


# ---------------------------------------------------------------- 2. Schema
@pytest.fixture
def con(tmp_path):
    pfad = tmp_path / "neu.sqlite"
    Datenbank(str(pfad), wal=False).con.close()
    c = sqlite3.connect(pfad)
    c.execute("PRAGMA foreign_keys = ON")
    for i in (1, 2, 3):
        c.execute("INSERT INTO inserate (plattform, anzeigen_id, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                  "VALUES ('kleinanzeigen', ?, 'aktiv', 'a', 'b')", (f"n{i}",))
    c.commit()
    yield c
    c.close()


def entscheidung(con, a=1, b=2, **kw):
    w = {"entscheidung": "gleich", "status": "gilt", "konfidenz": "hoch", "gruende_json": "[]", "regel_version": 1, "nutzer_id": None,
         "zeitpunkt": JETZT, **kw}
    cur = con.execute("INSERT INTO dubletten_entscheidungen (inserat_a, inserat_b, entscheidung, status, konfidenz, gruende_json, "
                      "regel_version, nutzer_id, zeitpunkt) VALUES (?,?,?,?,?,?,?,?,?)",
                      (a, b, w["entscheidung"], w["status"], w["konfidenz"], w["gruende_json"], w["regel_version"], w["nutzer_id"], w["zeitpunkt"]))
    return cur.lastrowid


def test_spalten_der_neuen_tabellen(con):
    spalten = lambda t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")]      # noqa: E731
    assert spalten("dubletten_entscheidungen") == ["id", "inserat_a", "inserat_b", "entscheidung", "status", "konfidenz", "gruende_json",
                                                   "regel_version", "nutzer_id", "zeitpunkt", "aufgehoben_von", "aufgehoben_am"]
    assert spalten("fahrzeug_zuordnungen") == ["id", "entscheidung_id", "inserat_id", "von_fahrzeug", "nach_fahrzeug", "art", "nutzer_id", "zeitpunkt"]


@pytest.mark.parametrize("kw", [
    {"entscheidung": "vielleicht"}, {"status": "offen"}, {"konfidenz": "niedrig"}, {"konfidenz": "HOCH"}, {"gruende_json": None},
    {"regel_version": None}, {"zeitpunkt": None},
], ids=["entsch", "status", "konf", "konf-gross", "gruende", "regel", "zeit"])
def test_check_und_not_null_der_entscheidungen(con, kw):
    with pytest.raises(sqlite3.IntegrityError):
        entscheidung(con, **kw)


@pytest.mark.parametrize("a, b", [(2, 1), (2, 2)], ids=["umgekehrt", "gleich"])
def test_paar_muss_geordnet_sein(con, a, b):
    with pytest.raises(sqlite3.IntegrityError):
        entscheidung(con, a, b)


def test_konfidenz_darf_fehlen_und_nur_eine_geltende_entscheidung_je_paar(con):
    e1 = entscheidung(con, konfidenz=None, entscheidung="verschieden")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        entscheidung(con)                                                                 # zweite geltende für (1, 2)
    con.rollback()
    entscheidung(con, 1, 3)                                                              # anderes Paar geht
    con.execute("UPDATE dubletten_entscheidungen SET status='aufgehoben', aufgehoben_am=?, aufgehoben_von=7 WHERE id=?", (JETZT, e1))     # von = Nutzer-ID
    entscheidung(con)                                                                    # nach Aufheben wieder eine geltende
    entscheidung(con, status="aufgehoben")                                              # beliebig viele aufgehobene
    assert con.execute("SELECT COUNT(*) FROM dubletten_entscheidungen WHERE inserat_a=1 AND inserat_b=2").fetchone()[0] == 3


def test_entscheidungen_nie_loeschen_nur_aufheben(con):
    e = entscheidung(con)
    con.commit()
    with pytest.raises(sqlite3.IntegrityError, match="nicht gelöscht"):
        con.execute("DELETE FROM dubletten_entscheidungen WHERE id=?", (e,))
    for sql in ("UPDATE dubletten_entscheidungen SET entscheidung='verschieden' WHERE id=?",
                "UPDATE dubletten_entscheidungen SET gruende_json='[1]' WHERE id=?",
                "UPDATE dubletten_entscheidungen SET inserat_b=3 WHERE id=?",
                "UPDATE dubletten_entscheidungen SET nutzer_id=5 WHERE id=?",
                "UPDATE dubletten_entscheidungen SET status='aufgehoben' WHERE id=?",                         # ohne aufgehoben_am
                "UPDATE dubletten_entscheidungen SET aufgehoben_am='x' WHERE id=?"):                         # ohne Statuswechsel
        with pytest.raises(sqlite3.IntegrityError, match="nur gilt -> aufgehoben"):
            con.execute(sql, (e,))
    con.execute("UPDATE dubletten_entscheidungen SET status='aufgehoben', aufgehoben_am=?, aufgehoben_von=NULL WHERE id=?", (JETZT, e))   # Einzelplatz
    con.commit()
    for sql in ("UPDATE dubletten_entscheidungen SET status='gilt', aufgehoben_am=NULL WHERE id=?",                # nicht wieder aufnehmen
                "UPDATE dubletten_entscheidungen SET aufgehoben_am='y' WHERE id=?"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql, (e,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM dubletten_entscheidungen")
    assert con.execute("SELECT status, aufgehoben_am FROM dubletten_entscheidungen").fetchall() == [("aufgehoben", JETZT)]


def zuordnung(con, e, art="zusammen"):
    return con.execute("INSERT INTO fahrzeug_zuordnungen (entscheidung_id, inserat_id, von_fahrzeug, nach_fahrzeug, art, nutzer_id, zeitpunkt) "
                       "VALUES (?, 2, 2, 1, ?, NULL, ?)", (e, art, JETZT)).lastrowid


def test_zuordnungen_sind_nur_anfuegbar(con):
    e = entscheidung(con)
    z1 = zuordnung(con, e)
    zuordnung(con, e, "zurueck")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
        con.execute("UPDATE fahrzeug_zuordnungen SET art='zurueck' WHERE id=?", (z1,))
    with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
        con.execute("DELETE FROM fahrzeug_zuordnungen WHERE id=?", (z1,))
    with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
        con.execute("DELETE FROM fahrzeug_zuordnungen")
    assert con.execute("SELECT COUNT(*) FROM fahrzeug_zuordnungen").fetchone()[0] == 2


def test_art_und_pflichtfelder_der_zuordnung(con):
    e = entscheidung(con)
    with pytest.raises(sqlite3.IntegrityError):
        zuordnung(con, e, "verbunden")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO fahrzeug_zuordnungen (entscheidung_id, inserat_id, von_fahrzeug, art, zeitpunkt) VALUES (?, 2, 2, 'zusammen', ?)", (e, JETZT))


def test_indizes_werden_von_den_abfragen_benutzt(con):
    plan = lambda sql: " ".join(str(r) for r in con.execute("EXPLAIN QUERY PLAN " + sql))      # noqa: E731
    assert "idx_dubletten_gilt" in plan("SELECT 1 FROM dubletten_entscheidungen WHERE inserat_a=1 AND inserat_b=2 AND status='gilt'")
    assert "idx_dubletten_gilt" in plan("SELECT inserat_a, inserat_b FROM dubletten_entscheidungen WHERE status='gilt'")
    assert "idx_dubletten_b" in plan("SELECT * FROM dubletten_entscheidungen WHERE inserat_b=2")
    assert "idx_zuordnungen_inserat" in plan("SELECT * FROM fahrzeug_zuordnungen WHERE inserat_id=2 ORDER BY id")


# ---------------------------------------------------------------- 3. Vorschläge beim Lesen
def treffer(i, **kw):
    return {"id": i, "url": f"https://x.invalid/{i}", "titel": "Knaus Sky TI 650 MEG", "preis": 40000, "km": 90000, "ez_jahr": 2016,
            "ort": "70173 Stuttgart", "marke": "Knaus", **kw}


def inserat_id(db, anzeigen_id):
    return db.con.execute("SELECT id FROM inserate WHERE anzeigen_id=?", (anzeigen_id,)).fetchone()[0]


def zustand(db):
    db.con.commit()
    return {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in sorted(tabellen_der(db))}


def tabellen_der(db):
    return [r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def test_vorschlag_ueber_plattformen_mit_ids_und_ohne_schreiben(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    db.speichere_treffer(treffer("m1", preis=41000, quelle="mobile.de"), IMPORT_SUCHE)
    db.speichere_treffer(treffer("andere", marke="Hymer", titel="Hymer B 544", ez_jahr=2012), "Alkoven")
    vorher = zustand(db)
    v = dubletten_vorschlaege(db)
    assert zustand(db) == vorher                                                      # nur lesen
    assert len(v) == 1
    p = v[0]
    ia, ib = inserat_id(db, "a1"), inserat_id(db, "m1")
    assert (p["inserat_a"], p["inserat_b"]) == (ia, ib) and ia < ib
    assert {p["anzeigen_a"], p["anzeigen_b"]} == {"a1", "m1"}
    assert (p["plattform_a"], p["plattform_b"]) == ("kleinanzeigen", "mobile.de")
    assert p["stufe"] == "hoch" and p["gruende"] and p["regel_version"] == 2
    assert p["a"]["fahrzeug_id"] != p["b"]["fahrzeug_id"]
    json.dumps(v)                                                                     # serialisierbar


def test_altform_quelle_leer_ist_kleinanzeigen(db):
    db.speichere_treffer(treffer("a1", quelle=None), "Alkoven")
    db.speichere_treffer(treffer("a2", quelle="kleinanzeigen"), "Alkoven")
    v = dubletten_vorschlaege(db)
    assert len(v) == 1 and (v[0]["plattform_a"], v[0]["plattform_b"]) == ("kleinanzeigen", "kleinanzeigen")


def test_ohne_dieselbe_fahrzeug_id_und_mit_entscheidung(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    db.speichere_treffer(treffer("a2"), "Alkoven")
    ia, ib = inserat_id(db, "a1"), inserat_id(db, "a2")
    assert len(dubletten_vorschlaege(db)) == 1
    # geltende Entscheidung „verschieden“ und „gleich“ blenden aus, aufgehobene nicht
    for art in ("verschieden", "gleich"):
        db.con.execute("INSERT INTO dubletten_entscheidungen (inserat_a, inserat_b, entscheidung, status, gruende_json, regel_version, zeitpunkt) "
                       "VALUES (?, ?, ?, 'gilt', '[]', 1, ?)", (ia, ib, art, JETZT))
        db.con.commit()
        assert dubletten_vorschlaege(db) == [], art
        db.con.execute("UPDATE dubletten_entscheidungen SET status='aufgehoben', aufgehoben_am=? WHERE status='gilt'", (JETZT,))
        db.con.commit()
        assert len(dubletten_vorschlaege(db)) == 1, art
    # dasselbe Fahrzeug (später durch eine bestätigte Zusammenführung): kein Vorschlag mehr
    fid = db.con.execute("SELECT fahrzeug_id FROM inserate WHERE id=?", (ia,)).fetchone()[0]
    db.con.execute("UPDATE inserate SET fahrzeug_id=? WHERE id=?", (fid, ib))
    db.con.commit()
    assert dubletten_vorschlaege(db) == []


def test_widerspruch_und_unsichere_paare_nicht_vorgeschlagen(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    db.speichere_treffer(treffer("w1", ez_jahr=2019), "Alkoven")                      # EZ-Abstand 3
    db.speichere_treffer(treffer("w2", km=300000), "Alkoven")                         # km weit weg
    db.speichere_treffer(treffer("w3", ort="80331 München"), "Alkoven")               # PLZ fern
    assert dubletten_vorschlaege(db) == []


def test_sortierung_hoch_vor_mittel(db):
    db.speichere_treffer(treffer("m1", titel="Knaus Sky TI Text", preis=70000, km=50000, ort="70173 Stuttgart"), "Alkoven")
    db.speichere_treffer(treffer("m2", titel="Knaus Sky TI Anders", preis=40000, km=50500, ort="70173 Stuttgart"), "Alkoven")
    db.speichere_treffer(treffer("h1"), "Alkoven")
    db.speichere_treffer(treffer("h2"), "Alkoven")
    stufen = [p["stufe"] for p in dubletten_vorschlaege(db)]
    assert stufen == sorted(stufen, key=["hoch", "mittel"].index) and stufen[0] == "hoch" and "mittel" in stufen


def test_entscheidungen_und_zuordnungen_wirken_nicht_auf_bewertung_und_team_sperre(cfg, db, importiert):
    """Frisch gelesen: ``bewerte_alle`` (Bewertung, Anschreiben, Dubletten) und ``dubletten_ids`` (Team-Sperre) vor und nach dem Eintragen von
    Entscheidungen (gleich + verschieden) und einer Zuordnungszeile – kein Vergleich vorab gelesener Listen."""
    for i in range(3):
        db.speichere_treffer(treffer(f"d{i}", km=90000 + 500 * i, titel="Knaus Sky TI 650 MEG privat"), "Alkoven")
    vorher, ids_vorher = repr(bewerte_alle(cfg, db, BASIS, "2026-10-01T00:00:00")), dubletten_ids(db)
    assert ids_vorher["d0"] == ["d1", "d2"] and "'dubletten_ids': ['d1', 'd2']" in vorher              # die geplanten Dubletten wirken (heutige Logik)
    v = dubletten_vorschlaege(db)
    assert {(p["anzeigen_a"], p["anzeigen_b"]) for p in v} >= {("d0", "d1"), ("d0", "d2"), ("d1", "d2")} or len(v) >= 3
    i0, i1, i2 = (inserat_id(db, f"d{i}") for i in range(3))
    sql = ("INSERT INTO dubletten_entscheidungen (inserat_a, inserat_b, entscheidung, status, gruende_json, regel_version, zeitpunkt) "
           "VALUES (?, ?, ?, 'gilt', '[]', 2, ?)")
    db.con.execute(sql, (i0, i1, "verschieden", JETZT))
    e = db.con.execute(sql, (i1, i2, "gleich", JETZT)).lastrowid
    db.con.execute("INSERT INTO fahrzeug_zuordnungen (entscheidung_id, inserat_id, von_fahrzeug, nach_fahrzeug, art, zeitpunkt) "
                   "VALUES (?, ?, 1, 2, 'zusammen', ?)", (e, i2, JETZT))
    db.con.commit()
    nachher, ids_nachher = repr(bewerte_alle(cfg, db, BASIS, "2026-10-01T00:00:00")), dubletten_ids(db)       # frisch aus der Datenbank gelesen
    assert nachher == vorher and ids_nachher == ids_vorher


def test_laufzeit_vorschlaege_mit_50000_inseraten(tmp_path, capsys):
    """Gesamte Strecke (Ergänzung, Zuordnung, Blockbildung, Vergleich) mit 50 000 Inseraten in der Datenbank."""
    db = Datenbank(str(tmp_path / "gross.sqlite"), wal=False)
    rng = random.Random(7)
    marken = ["Knaus", "Hymer", "Dethleffs", "Bürstner", "Pössl", "Weinsberg", "Adria", "Carado", "Hobby", "Fendt", "Frankia", "LMC"]
    n = 50_000
    zeilen = []
    for i in range(n):
        m = rng.choice(marken)
        zeilen.append((f"g{i}", f"https://x.invalid/{i}", f"{m} Modell {rng.randint(1, 300)} gepflegt", rng.randint(15, 90) * 1000, rng.randint(5, 250) * 1000,
                       rng.randint(2000, 2024), f"{rng.randint(10000, 99999)} Ort", m, "2026-10-01T10:00:00", "2026-10-02T10:00:00"))
    for i in range(0, 300, 10):                                                        # 30 geplante Dubletten
        z = zeilen[i]
        zeilen.append((f"p{i}", z[1] + "x", z[2], z[3] + 500, z[4] + 400, z[5], z[6], z[7], "2026-10-05T10:00:00", "2026-10-06T10:00:00"))
    db.con.executemany("INSERT INTO anzeigen (id, url, titel, preis, km, ez_jahr, ort, marke, erstmals_gesehen, zuletzt_gesehen) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", zeilen)
    db.con.executemany("INSERT INTO inserate (plattform, anzeigen_id, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                       "VALUES ('kleinanzeigen', ?, ?, ?, 'aktiv', ?, ?)", [(z[0], z[2], z[3], z[8], z[9]) for z in zeilen])
    db.con.commit()
    start = time.perf_counter()
    v = dubletten_vorschlaege(db)
    dauer = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[P3-02a] dubletten_vorschlaege mit {len(zeilen)} Inseraten (Datenbank, ohne Entscheidungen): {dauer:.2f} s, {len(v)} Vorschläge")
    gefunden = {frozenset((p["anzeigen_a"], p["anzeigen_b"])) for p in v}
    assert all(frozenset((f"g{i}", f"p{i}")) in gefunden for i in range(0, 300, 10))
    assert dauer < 120
    db.con.close()


# ---------------------------------------------------------------- 4. API
@pytest.fixture
def api(cfg, db, importiert, tmp_path):
    """Server mit Team (Anna Inhaberin, Ben Mitarbeiter, Hugo Standort-Zugang) und einer Dublette."""
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    t.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale Nord", "20095", "Hamburg")
    t.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.speichere_treffer(treffer("x1", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.speichere_treffer(treffer("x2", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    srv = starte(cfg, db)
    yield srv
    srv.shutdown()
    srv.server_close()


def test_api_rollen(api):
    for name in ("Anna", "Ben"):
        status, d, _ = anmelden(api, name)("GET", "/api/dubletten-vorschlaege")
        assert status == 200 and d["regel_version"] == 2 and d["anzahl"] == len(d["vorschlaege"]) >= 1
        p = next(x for x in d["vorschlaege"] if {x["anzeigen_a"], x["anzeigen_b"]} == {"x1", "x2"})
        assert p["stufe"] == "hoch" and p["gruende"] and p["plattform_a"] == "kleinanzeigen"
        assert "verkaeufer" not in json.dumps(d).lower() and "telefon" not in json.dumps(d).lower()
    status, d, _ = anmelden(api, "Hugo")("GET", "/api/dubletten-vorschlaege")
    assert status == 403 and d["grund"] == "recht"
    from tests.test_handy import Client
    assert Client(api.server_address[1])("GET", "/api/dubletten-vorschlaege")[0] == 401           # nicht angemeldet


def test_api_ohne_nutzer_einzelplatz(cfg, db, importiert):
    db.speichere_treffer(treffer("x1"), "Alkoven")
    db.speichere_treffer(treffer("x2"), "Alkoven")
    srv = starte(cfg, db)
    try:
        status, d, _ = lokal(srv)("GET", "/api/dubletten-vorschlaege")
        assert status == 200 and d["anzahl"] >= 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_veraendert_nichts(api, db):
    vorher = zustand(db)
    anmelden(api, "Anna")("GET", "/api/dubletten-vorschlaege")
    nachher = zustand(db)
    assert {t: z for t, z in nachher.items() if t not in ("sitzungen", "audit")} == {t: z for t, z in vorher.items() if t not in ("sitzungen", "audit")}


# ---------------------------------------------------------------- 5. CLI
def test_cli_dubletten(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    db.speichere_treffer(treffer("c1", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.speichere_treffer(treffer("c2", titel="Hobby Optima De Luxe 65", marke="Hobby", quelle="mobile.de"), IMPORT_SUCHE)
    db.speichere_treffer(treffer("c3", titel="Fendt Bianco 465", marke="Fendt", ez_jahr=2010, km=40000), "Alkoven")
    vorher = zustand(db)
    db.con.close()
    r = _scout(cfg, tmp_path, "dubletten")
    assert r.returncode == 0, r.stderr
    assert "[hoch] kleinanzeigen:c1 ~ mobile.de:c2" in r.stdout and "gleiche Marke" in r.stdout
    assert "1 offene Vorschläge" in r.stdout and "nichts zusammengeführt" in r.stdout
    assert _scout(cfg, tmp_path, "dubletten", "--stufe", "mittel").stdout.count("[") == 0
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    assert zustand(db) == vorher                                                       # nur lesen
    db.con.close()


def test_cli_ohne_dubletten(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "dubletten")
    assert r.returncode == 0 and "0 offene Vorschläge" in r.stdout


def test_ergaenze_fahrzeug_wird_wiederverwendet():
    """Keine zweite Ergänzungslogik: der Vorschlag nutzt dieselbe Funktion wie die Bewertung."""
    import wmscout.dubletten as modul
    assert modul.ergaenze_fahrzeug is ergaenze_fahrzeug


# ---------------------------------------------------------------- 6. Worst Case (B2), Limit, Cache
def viele_gleiche(db, n, praefix="w"):
    """n identische Inserate (gleiche Marke, EZ, km, PLZ, Titel) – der Worst Case der Paarbildung."""
    db.con.executemany("INSERT INTO anzeigen (id, url, titel, preis, km, ez_jahr, ort, marke, erstmals_gesehen, zuletzt_gesehen) "
                       "VALUES (?, ?, 'Hobby Optima De Luxe 65', 40000, 90000, 2016, '70173 Stuttgart', 'Hobby', '2026-10-01T10:00:00', '2026-10-01T10:00:00')",
                       [(f"{praefix}{i}", f"https://x.invalid/{praefix}{i}") for i in range(n)])
    db.con.executemany("INSERT INTO inserate (plattform, anzeigen_id, titel, preis, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) "
                       "VALUES ('kleinanzeigen', ?, 'Hobby Optima De Luxe 65', 40000, 'aktiv', 'a', 'b')", [(f"{praefix}{i}",) for i in range(n)])
    db.con.commit()


def test_worst_case_in_der_datenbank_ist_begrenzt_und_gekennzeichnet(db, capsys):
    viele_gleiche(db, 2500)
    start = time.perf_counter()
    erg = pruefe_dubletten(db)
    dauer = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[P3-02a] Worst Case 2500 gleiche Inserate (Datenbank): {dauer:.2f} s, {len(erg.vorschlaege)} Vorschläge")
    assert erg.gekuerzt == ["Hobby 2016"] and "nicht vollständig geprüft" in erg.hinweis and 0 < len(erg.vorschlaege) <= 2000
    assert dauer < 20


def test_api_limit_und_hinweis(api, db):
    viele_gleiche(db, 2500)
    c = anmelden(api, "Anna")
    status, d, _ = c("GET", "/api/dubletten-vorschlaege")
    assert status == 200 and len(d["vorschlaege"]) == d["limit"] == 200 and d["anzahl"] > 200
    assert d["unvollstaendig"] is True and "nicht vollständig geprüft" in d["hinweis"]
    status, d, _ = c("GET", "/api/dubletten-vorschlaege?limit=3")
    assert status == 200 and len(d["vorschlaege"]) == 3 and d["limit"] == 3
    assert c("GET", f"/api/dubletten-vorschlaege?limit={MAX_LIMIT}")[0] == 200
    for falsch in ("0", "-1", "abc", str(MAX_LIMIT + 1)):
        status, d, _ = c("GET", f"/api/dubletten-vorschlaege?limit={falsch}")
        assert status == 400 and "limit" in d["fehler"], falsch


def test_api_ohne_grosse_gruppe_ohne_hinweis(api):
    d = anmelden(api, "Ben")("GET", "/api/dubletten-vorschlaege")[1]
    assert d["unvollstaendig"] is False and d["hinweis"] is None and d["limit"] == 200


def test_cli_limit_und_hinweis(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    viele_gleiche(db, 2300)
    db.con.close()
    r = _scout(cfg, tmp_path, "dubletten", "--limit", "5")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("[hoch]") + r.stdout.count("[mittel]") == 5 and "angezeigt: 5" in r.stdout
    assert "Hinweis: Gruppe zu groß – nicht vollständig geprüft" in r.stdout
    for falsch in ("0", str(MAX_LIMIT + 1)):
        r = _scout(cfg, tmp_path, "dubletten", "--limit", falsch)
        assert r.returncode != 0 and "--limit" in r.stderr


def test_cache_der_vorschlaege_wird_verworfen_und_bei_fremdem_schreiben_neu_berechnet(cfg, db, tmp_path):
    k, _ = _kontext(cfg, db, BASIS)
    db.speichere_treffer(treffer("c1"), "Alkoven")
    db.speichere_treffer(treffer("c2"), "Alkoven")
    assert len(k.dubletten_vorschlaege().vorschlaege) == 1
    db.speichere_treffer(treffer("c3"), "Alkoven")                                  # eigene Verbindung: data_version ändert sich nicht
    assert len(k.dubletten_vorschlaege().vorschlaege) == 1                          # Zwischenspeicher gilt (wie dubletten_von)
    k.dubletten_verwerfen()
    assert len(k.dubletten_vorschlaege().vorschlaege) == 3
    fremd = Datenbank(cfg["ausgabe"]["datenbank"])                                  # Schreiben über eine andere Verbindung (wie der Suchlauf)
    fremd.speichere_treffer(treffer("c4"), "Alkoven")
    fremd.con.close()
    assert len(k.dubletten_vorschlaege().vorschlaege) == 6                          # ohne Verwerfen neu berechnet
