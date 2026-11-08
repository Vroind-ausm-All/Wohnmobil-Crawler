"""P3-07 (ADR-045): Vorfilter der Vergleichsauswahl (R12) und Indizes nach ``EXPLAIN QUERY PLAN`` (Schema v16).

Geprüft: Der Vorfilter ändert kein Ergebnis (Zufallsbestand mit Randfällen, jede Bewertung gleich wie ohne Vorfilter), er durchsucht weniger,
eine veränderte Liste wird neu einsortiert, einfache Listen gehen weiter; die tatsächlich ausgeführten Anweisungen nutzen die neuen Indizes;
Schema 16 gegen Altbestände. Alles offline; keine Zeitmessung im Test (siehe TEST-REPORT).
"""
from __future__ import annotations

import copy
import random
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta

import pytest

from tests.daten import BASIS
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_kontakte import baue_v14, mit_kontakten
from tests.test_migration import pruefsumme, versionen
from wmscout import migrationen
from wmscout.bewertung.auswertung import bewerte_zeilen, vergleichsbasis
from wmscout.bewertung.rechner import Rechner, Vergleichsliste
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.sicherung import sicherungen

JETZT = datetime(2026, 10, 23, 12, 0)
ARTEN = ["Teilintegrierter", "Alkoven", "Integrierter", "Kastenwagen", None, "Import (unbekannt)", "Wohnwagen"]


def bestand(n=400, seed=11):
    """Zufällige Inserate mit Randfällen: Preis fehlt/unter 1.000 €/genau 1.000 €, Anbieter privat/gewerblich/unbekannt/ohne Schlüssel,
    EZ fehlt oder als Kommazahl, km fehlt, alte Anzeigen, Serie, Art nur im Titel."""
    r = random.Random(seed)
    zeilen = []
    for i in range(n):
        z = {"id": f"v{i}", "url": f"https://x.invalid/{i}", "suche": r.choice(ARTEN), "marke": r.choice(["Knaus", "Hymer", "Pössl", None]),
             "titel": r.choice(["Knaus Sky TI", "Hymer B 544 Alkoven", "Pössl Summit Kastenwagen", "Wohnmobil", "Integrierter Hymer"]),
             "preis": r.choice([None, 500, 999, 1000, *range(8000, 90000, 3700)]), "km": r.choice([None, *range(5000, 260000, 17000)]),
             "ez_jahr": r.choice([None, *range(1998, 2025)]), "serie": r.choice([None, "", "Sky TI", "B 544"]),
             "kurzbeschreibung": r.choice(["", "Markise Solar", "Feuchtigkeit hinten", "Wasserschaden"]),
             "zuletzt_gesehen": (JETZT - timedelta(days=r.choice([0, 5, 100, 200, 400]))).isoformat(timespec="seconds"),
             "erstmals_gesehen": (JETZT - timedelta(days=r.choice([400, 500]))).isoformat(timespec="seconds"),
             "ort": r.choice([None, "70173 Stuttgart", "20095 Hamburg"]), "status": r.choice([None, "neu", "kontaktiert"])}
        g = r.choice(["privat", "gewerblich", "unbekannt", "fehlt"])
        if g != "fehlt":
            z["gewerblich"] = {"privat": 0, "gewerblich": 1, "unbekannt": None}[g]
        if z["ez_jahr"] and r.random() < 0.08:
            z["ez_jahr"] = float(z["ez_jahr"]) + r.choice([0, 0, 0.5])              # auch kein ganzzahliges Jahr (Restliste, QA B1)
        zeilen.append(z)
    return zeilen


@pytest.mark.parametrize("seed, toleranz", [(11, None), (12, None), (13, None), (14, 0), (15, -1), (16, 2.0), (17, 6)])
def test_vorfilter_aendert_kein_ergebnis(cfg, monkeypatch, seed, toleranz):
    if toleranz is not None:
        cfg["rechner"]["vergleich_jahre_toleranz"] = toleranz
    zeilen = bestand(seed=seed)
    mit = bewerte_zeilen(cfg, BASIS, copy.deepcopy(zeilen), copy.deepcopy(zeilen), jetzt=JETZT)
    monkeypatch.setattr(Vergleichsliste, "kandidaten", lambda self, *a: list(self))       # ohne Vorfilter: alle wie bisher
    ohne = bewerte_zeilen(cfg, BASIS, copy.deepcopy(zeilen), copy.deepcopy(zeilen), jetzt=JETZT)
    assert len(mit) == len(ohne) == len(zeilen)
    for a, b in zip(mit, ohne, strict=True):
        assert asdict(a["b"]) == asdict(b["b"]) and (a["sperre"], a["brief"], a["bereit"]) == (b["sperre"], b["brief"], b["bereit"]), a["a"]["id"]
    assert toleranz is not None and toleranz < 0 or sum(z["b"].vergleich_anzahl for z in mit) > 0     # es gab wirklich Vergleiche


def test_vergleiche_gleich_und_weniger_durchsucht(cfg):
    zeilen = bestand(seed=5)
    v = vergleichsbasis(zeilen, {})
    assert isinstance(v, Vergleichsliste)
    r, gesehen = Rechner(cfg, JETZT), []
    for a in [z for z in v if isinstance(z.get("ez_jahr"), int)]:
        assert r.vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v)), a["id"]
        gesehen.append(len(v.kandidaten(r.art(a), a["ez_jahr"], cfg["rechner"]["vergleich_jahre_toleranz"])))
    assert max(gesehen) < len(v) / 3                                                              # Vorfilter: nur ein Bruchteil je Anzeige


def test_veraenderte_liste_wird_neu_einsortiert(cfg):
    v = vergleichsbasis(bestand(seed=7), {})
    a = next(z for z in v if isinstance(z.get("ez_jahr"), int) and z.get("suche") == "Alkoven")
    r = Rechner(cfg, JETZT)
    assert r.vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v))           # Index aufgebaut
    v.append({**a, "id": "neu", "preis": a["preis"] or 30000, "gewerblich": 0})
    assert Rechner(cfg, JETZT).vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v))
    assert "neu" in {b["id"] for b in v.kandidaten(r.art(a), a["ez_jahr"], 0)}


def test_aenderung_bei_gleicher_laenge_wird_bemerkt(cfg):
    """QA B2: Ersetzen eines Eintrags (gleiche Länge) verwirft den Index."""
    v = vergleichsbasis(bestand(seed=7), {})
    a = next(z for z in v if isinstance(z.get("ez_jahr"), int) and z.get("suche") == "Alkoven")
    r = Rechner(cfg, JETZT)
    assert r.vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v))           # Index aufgebaut
    i = next(i for i, b in enumerate(v) if b["id"] != a["id"] and not b.get("preis"))
    v[i] = {**a, "id": "ersetzt", "preis": a["preis"] or 30000, "gewerblich": 0}
    assert "ersetzt" in {b["id"] for b in v.kandidaten(r.art(a), a["ez_jahr"], 0)}
    assert Rechner(cfg, JETZT).vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v))
    v.pop()
    v.insert(0, {**a, "id": "vorn", "preis": 31000, "gewerblich": 0})
    assert Rechner(cfg, JETZT).vergleiche(a, v) == Rechner(cfg, JETZT).vergleiche(a, list(v))


def test_jahr_als_text_wie_bisher(cfg):
    """Ein Jahr als Text brach schon bisher die Bewertung ab – mit Vorfilter genauso (kein stilles Weglassen)."""
    zeilen = [z for z in bestand(seed=3) if isinstance(z.get("ez_jahr"), int)]
    a = next(z for z in zeilen if z.get("preis") and z.get("suche") == "Alkoven")
    kaputt = {**a, "id": "text", "ez_jahr": "2015", "gewerblich": 0, "preis": 20000}
    for liste in (Vergleichsliste([*zeilen, kaputt]), [*zeilen, kaputt]):
        with pytest.raises(TypeError):
            Rechner(cfg, JETZT).vergleiche(a, liste)


def test_ohne_ez_und_mit_einfacher_liste_wie_bisher(cfg):
    zeilen = bestand(seed=9)
    r = Rechner(cfg, JETZT)
    ohne_ez = next(z for z in zeilen if not z.get("ez_jahr"))
    assert r.marktniveau(ohne_ez, Vergleichsliste(zeilen))["n"] == 0 == r.marktniveau(ohne_ez, zeilen)["n"]


# ---------------------------------------------------------------- Abfragepläne der tatsächlich ausgeführten Anweisungen
def ausgefuehrt(db, aufruf) -> list[str]:
    gesehen = []
    db.con.set_trace_callback(gesehen.append)
    try:
        aufruf()
    finally:
        db.con.set_trace_callback(None)
    return [s for s in gesehen if s.lstrip().upper().startswith("SELECT")]


def plan(db, sql: str) -> str:
    return " | ".join(r["detail"] for r in db.con.execute("EXPLAIN QUERY PLAN " + sql))


def test_detailabruf_nutzt_den_teilindex(db):
    db.con.executemany("INSERT INTO anzeigen (id, url, titel, detail_geladen, erstmals_gesehen) VALUES (?, 'u', 't', ?, ?)",
                       [(str(i), i % 10 == 0, f"2026-10-{1 + i % 28:02d}T10:00:00") for i in range(500)])
    db.con.commit()
    for kennungen in (None, ["kleinanzeigen"]):
        (sql,) = ausgefuehrt(db, lambda: db.ohne_details(25, kennungen))       # noqa: B023 – sofort ausgeführt
        p = plan(db, sql)
        assert "idx_anzeigen_detail_offen" in p and "TEMP B-TREE" not in p, p
    assert [r["id"] for r in db.ohne_details(3)] == [r[0] for r in db.con.execute(
        "SELECT id FROM anzeigen WHERE detail_geladen=0 ORDER BY erstmals_gesehen DESC LIMIT 3")]


def test_besichtigung_zur_anfrage_nutzt_den_index(db):
    p = plan(db, "SELECT 1 FROM besichtigungen WHERE anfrage_id=1 AND status IN ('geplant', 'laeuft')")
    assert "idx_besichtigung_anfrage" in p and "SCAN" not in p, p
    assert "idx_besichtigung_anfrage" in plan(db, "SELECT id, basis_json, protokoll_json FROM besichtigungen WHERE anfrage_id=1")


# ---------------------------------------------------------------- Schema 16
def bis_16(monkeypatch):
    """Schritt 16 ist hier der letzte bekannte Schritt: die Tests prüfen ihn so, wie er zu seiner Zeit lief."""
    _alt_schritte(monkeypatch, 16)


def baue_v15(pfad, monkeypatch, tmp_path):
    baue_v14(pfad, monkeypatch, tmp_path)
    mit_kontakten(pfad)
    with monkeypatch.context() as m:
        _alt_schritte(m, 15)
        assert migriere(pfad, tmp_path / "stand15") == [15]
    assert lese_version(pfad) == 15


INDIZES = {"idx_anzeigen_detail_offen", "idx_besichtigung_anfrage"}


@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v15"])
def test_migration_auf_16_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_16(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v15":
        baue_v15(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    erledigt = migriere(pfad, ziel)
    assert erledigt[-1] == 16 and lese_version(pfad) == 16 and versionen(pfad)[-1] == 16
    neue = {t: v_ for t, v_ in vorher.items() if t != "fahrzeuge"}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    if art == "v15":
        assert _abbild(pfad) == vorher                                                            # nur Indizes, keine Daten
    assert INDIZES <= {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='index'")}
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)]
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v16" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_16_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_16(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v15(pfad, monkeypatch, tmp_path)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_16(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def test_fehler_im_schritt_16_rollt_zurueck_dann_gelingt_es(tmp_path, monkeypatch):
    bis_16(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v15(pfad, monkeypatch, tmp_path)
    vorher, echt = _abbild(pfad), migrationen._schritt_16

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 16, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 15 and _abbild(pfad) == vorher
    assert not INDIZES & {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='index'")}
    monkeypatch.setitem(migrationen.SCHRITTE, 16, echt)
    assert migriere(pfad, ziel) == [16]


def test_neue_datenbank_hat_die_indizes(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 16
    assert INDIZES <= {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
