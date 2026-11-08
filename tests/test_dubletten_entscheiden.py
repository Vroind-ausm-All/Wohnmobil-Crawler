"""P3-02b: Dubletten bestätigen, ablehnen und aufheben – Domäne, Wirkung auf Bewertung und Team-Sperre, API, Rechte, Audit.

Datensätze: ``p1``/``p2`` sind gleiche Fahrzeuge an verschiedenen Orten (die Heuristik erkennt sie NICHT), ``x1``/``x2`` sind eine heuristische
Dublette (gleiche Marke, EZ, PLZ).
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import random
import threading
import time
from datetime import datetime

import pytest

from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import inserat_id, starte, treffer
from tests.test_handy import Client
from tests.test_team_bearbeitung import anmelden, lokal
from wmscout.bewertung.auswertung import bewerte_alle, bewerte_zeilen, dubletten_ids, vergleichsbasis_aus
from wmscout.datenbank import Datenbank
from wmscout.domaene import fahrzeug_status
from wmscout.dubletten import (DublettenFehler, DublettenKonflikt, Wirkung, aufheben_blockiert_durch, bestaetige, dubletten_vorschlaege, gruppe,
                               hebe_auf, lade_wirkung, lehne_ab, wende_an)
from wmscout.haendler import HaendlerSpeicher
from wmscout.normalisierung.identitaet import REGEL_VERSION
from wmscout.team import TeamSpeicher

LAUF = "2026-10-01T00:00:00"
TABELLEN = ("anzeigen", "inserate", "fahrzeuge", "bearbeitung")


def stand(db):
    """Alle Zeilen der Arbeitstabellen (ohne Protokolle) – zum bit-genauen Vergleich."""
    db.con.commit()
    return {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in TABELLEN}


def protokoll(db):
    db.con.commit()
    return {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in ("dubletten_entscheidungen", "fahrzeug_zuordnungen")}


def fahrzeug(db, anzeigen_id):
    return db.con.execute("SELECT fahrzeug_id FROM inserate WHERE anzeigen_id=?", (anzeigen_id,)).fetchone()[0]


def paar_p(db):
    db.speichere_treffer(treffer("p1"), "Alkoven")
    db.speichere_treffer(treffer("p2", ort="80331 München", km=91000), "Alkoven")
    return inserat_id(db, "p1"), inserat_id(db, "p2")


def drei(db):
    for i in ("a", "b", "c"):
        db.speichere_treffer(treffer(i, ort=f"8033{ord(i) - 96} München"), "Alkoven")
    return tuple(inserat_id(db, i) for i in ("a", "b", "c"))


# ---------------------------------------------------------------- Domäne: bestätigen
def test_bestaetigen_haengt_um_protokolliert_und_ist_idempotent(db):
    i1, i2 = paar_p(db)
    f1, f2 = fahrzeug(db, "p1"), fahrzeug(db, "p2")
    assert f1 < f2 and dubletten_vorschlaege(db) == []                   # die Heuristik schlägt dieses Paar nicht vor
    vorher = stand(db)
    erg = bestaetige(db, i2, i1, nutzer_id=7)                           # Reihenfolge der Argumente egal
    assert erg["neu"] is True and erg["bewegt"] == [i2]
    assert fahrzeug(db, "p1") == fahrzeug(db, "p2") == f1
    nachher = stand(db)
    assert nachher["inserate"] != vorher["inserate"] and nachher["anzeigen"] == vorher["anzeigen"] and nachher["bearbeitung"] == vorher["bearbeitung"]
    assert nachher["fahrzeuge"] == vorher["fahrzeuge"]                  # das verwaiste Fahrzeug bleibt (wird nie gelöscht)
    e = db.con.execute("SELECT * FROM dubletten_entscheidungen").fetchall()
    assert len(e) == 1 and (e[0]["inserat_a"], e[0]["inserat_b"]) == (i1, i2)
    assert (e[0]["entscheidung"], e[0]["status"], e[0]["nutzer_id"], e[0]["regel_version"]) == ("gleich", "gilt", 7, REGEL_VERSION)
    assert e[0]["konfidenz"] is None and e[0]["gruende_json"] == "[]"   # kein Vorschlag, der Mensch entscheidet: trotzdem festgehalten
    z = db.con.execute("SELECT * FROM fahrzeug_zuordnungen").fetchall()
    assert len(z) == 1 and (z[0]["entscheidung_id"], z[0]["inserat_id"], z[0]["von_fahrzeug"], z[0]["nach_fahrzeug"], z[0]["art"], z[0]["nutzer_id"]) \
        == (e[0]["id"], i2, f2, f1, "zusammen", 7) and z[0]["zeitpunkt"]
    ersatz = protokoll(db)
    for a, b in ((i1, i2), (i2, i1)):                                   # zweimal: kein Fehler, keine Doppelzeile
        assert bestaetige(db, a, b, 7) == {"entscheidung_id": e[0]["id"], "neu": False, "bewegt": []}
    assert protokoll(db) == ersatz and stand(db) == nachher
    assert [m["anzeigen_id"] for m in gruppe(db, i1)] == ["p1", "p2"]


def test_bestaetigen_friert_gruende_und_stufe_des_vorschlags_ein(db):
    db.speichere_treffer(treffer("x1"), "Alkoven")
    db.speichere_treffer(treffer("x2"), "Alkoven")
    i1, i2 = inserat_id(db, "x1"), inserat_id(db, "x2")
    v = dubletten_vorschlaege(db)[0]
    bestaetige(db, i1, i2, None)
    e = db.con.execute("SELECT konfidenz, gruende_json, nutzer_id FROM dubletten_entscheidungen").fetchone()
    assert e["konfidenz"] == v["stufe"] == "hoch" and e["nutzer_id"] is None
    import json
    assert json.loads(e["gruende_json"]) == v["gruende"]
    assert dubletten_vorschlaege(db) == []                              # nicht mehr offen


@pytest.mark.parametrize("a, b", [(1, 1), (1, 999999), (999999, 1), (True, 2), ("1", 2), (None, 2), (1.0, 2)],
                         ids=["selbst", "b-fehlt", "a-fehlt", "bool", "text", "none", "float"])
@pytest.mark.parametrize("funktion", [bestaetige, lehne_ab])
def test_unbekannte_oder_unsinnige_ids(db, funktion, a, b):
    paar_p(db)
    vorher = (stand(db), protokoll(db))
    with pytest.raises(DublettenFehler):
        funktion(db, a, b, None)
    assert (stand(db), protokoll(db)) == vorher


def test_aufheben_unbekannte_id(db):
    for falsch in (999, True, "1", None):
        with pytest.raises(DublettenFehler):
            hebe_auf(db, falsch, None)


def test_verschieden_in_der_gruppe_ergibt_konflikt_und_aendert_nichts(db):
    a, b, c = drei(db)
    lehne_ab(db, a, c, 1)
    bestaetige(db, a, b, 1)
    vorher = (stand(db), protokoll(db))
    with pytest.raises(DublettenKonflikt, match="verschieden"):
        bestaetige(db, b, c, 1)                                         # Gruppe {a, b, c} enthielte das Paar a/c
    assert (stand(db), protokoll(db)) == vorher
    with pytest.raises(DublettenKonflikt):
        bestaetige(db, a, c, 1)                                         # und das Paar selbst
    assert (stand(db), protokoll(db)) == vorher


def test_ablehnen_bei_gleichem_fahrzeug_ist_konflikt_und_wiederholung_harmlos(db):
    a, b, c = drei(db)
    bestaetige(db, a, b, 1)
    vorher = (stand(db), protokoll(db))
    with pytest.raises(DublettenKonflikt, match="Zusammenführung"):
        lehne_ab(db, a, b, 1)
    assert (stand(db), protokoll(db)) == vorher
    e1 = lehne_ab(db, a, c, 1)
    assert e1["neu"] is True
    assert lehne_ab(db, c, a, 1) == {"entscheidung_id": e1["entscheidung_id"], "neu": False}
    assert db.con.execute("SELECT COUNT(*) FROM dubletten_entscheidungen WHERE entscheidung='verschieden'").fetchone()[0] == 1


def test_kette_a_b_und_b_c_ergibt_eine_gruppe(db):
    a, b, c = drei(db)
    bestaetige(db, a, b, 1)
    erg = bestaetige(db, b, c, 1)
    assert erg["bewegt"] == [c]
    assert fahrzeug(db, "a") == fahrzeug(db, "b") == fahrzeug(db, "c")
    assert [m["anzeigen_id"] for m in gruppe(db, c)] == ["a", "b", "c"]
    ersatz = protokoll(db)
    assert bestaetige(db, a, c, 1)["neu"] is False and protokoll(db) == ersatz     # A=C folgt aus der Kette
    assert dubletten_ids(db)["c"] == ["a", "b"] and dubletten_ids(db)["a"] == ["b", "c"]


def test_kette_in_anderer_reihenfolge_haengt_die_ganze_gruppe_um(db):
    a, b, c = drei(db)
    bestaetige(db, b, c, 1)
    erg = bestaetige(db, a, b, 1)
    fa = fahrzeug(db, "a")
    assert erg["bewegt"] == [b, c] and fahrzeug(db, "b") == fahrzeug(db, "c") == fa
    assert db.con.execute("SELECT COUNT(*) FROM fahrzeug_zuordnungen").fetchone()[0] == 3


# ---------------------------------------------------------------- Domäne: aufheben
def test_aufheben_nur_in_umgekehrter_reihenfolge_und_bit_gleich(db):
    a, b, c = drei(db)
    s0 = stand(db)
    e1 = bestaetige(db, a, b, 1)["entscheidung_id"]
    s1 = stand(db)
    e2 = bestaetige(db, b, c, 1)["entscheidung_id"]
    s2 = stand(db)
    assert aufheben_blockiert_durch(db, e1) == e2 and aufheben_blockiert_durch(db, e2) is None
    vorher = (stand(db), protokoll(db))
    with pytest.raises(DublettenKonflikt, match=f"Entscheidung {e2}"):
        hebe_auf(db, e1, 1)                                             # außer der Reihe
    assert (stand(db), protokoll(db)) == vorher
    erg = hebe_auf(db, e2, 5)
    assert erg["neu"] is True and erg["zurueck"] == [c]
    assert stand(db) == s1                                              # Zustand bit-gleich wie vor E2
    assert hebe_auf(db, e1, 5)["zurueck"] == [b]
    assert stand(db) == s0 and s1 != s0 != s2                           # und wie ganz am Anfang
    zeilen = db.con.execute("SELECT art, von_fahrzeug, nach_fahrzeug, nutzer_id FROM fahrzeug_zuordnungen ORDER BY id").fetchall()
    assert [z["art"] for z in zeilen] == ["zusammen", "zusammen", "zurueck", "zurueck"] and zeilen[2]["nutzer_id"] == 5
    assert (zeilen[2]["von_fahrzeug"], zeilen[2]["nach_fahrzeug"]) == (zeilen[1]["nach_fahrzeug"], zeilen[1]["von_fahrzeug"])
    d = db.con.execute("SELECT status, aufgehoben_von, aufgehoben_am FROM dubletten_entscheidungen ORDER BY id").fetchall()
    assert [x["status"] for x in d] == ["aufgehoben", "aufgehoben"] and all(x["aufgehoben_von"] == 5 and x["aufgehoben_am"] for x in d)
    ersatz = protokoll(db)
    assert hebe_auf(db, e1, 5)["neu"] is False and protokoll(db) == ersatz     # zweites Aufheben: nichts
    assert bestaetige(db, a, b, 1)["neu"] is True                      # nach dem Aufheben wieder möglich (neue Zeile)
    assert db.con.execute("SELECT COUNT(*) FROM dubletten_entscheidungen").fetchone()[0] == 3


def test_unabhaengige_zusammenfuehrungen_in_beliebiger_reihenfolge_aufheben(db):
    ids = {}
    for n in "abcd":
        db.speichere_treffer(treffer(n, ort=f"8033{ord(n) - 96} München"), "Alkoven")
        ids[n] = inserat_id(db, n)
    s0 = stand(db)
    e1 = bestaetige(db, ids["a"], ids["b"], 1)["entscheidung_id"]
    e2 = bestaetige(db, ids["c"], ids["d"], 1)["entscheidung_id"]
    assert aufheben_blockiert_durch(db, e1) is None
    hebe_auf(db, e1, 1)                                                 # die frühere zuerst – die spätere ist unabhängig
    hebe_auf(db, e2, 1)
    assert stand(db) == s0


def test_aufheben_verschieden_aendert_nur_den_status(db):
    a, b, _ = drei(db)
    s0 = stand(db)
    e = lehne_ab(db, a, b, 1)["entscheidung_id"]
    assert hebe_auf(db, e, 1)["zurueck"] == [] and stand(db) == s0
    assert db.con.execute("SELECT status FROM dubletten_entscheidungen").fetchone()[0] == "aufgehoben"
    assert bestaetige(db, a, b, 1)["neu"] is True                       # keine Sperre mehr


def test_aufheben_verweigert_wenn_ein_inserat_inzwischen_woanders_ist(db):
    a, b, c = drei(db)
    e = bestaetige(db, a, b, 1)["entscheidung_id"]
    db.con.execute("UPDATE inserate SET fahrzeug_id=? WHERE id=?", (fahrzeug(db, "c"), b))          # Eingriff von außen
    db.con.commit()
    vorher = (stand(db), protokoll(db))
    with pytest.raises(DublettenKonflikt, match="anderen Fahrzeug"):
        hebe_auf(db, e, 1)
    assert (stand(db), protokoll(db)) == vorher


def test_fehler_mitten_im_aufheben_rollt_alles_zurueck(db, monkeypatch):
    a, b, c = drei(db)
    bestaetige(db, b, c, 1)
    e = bestaetige(db, a, b, 1)["entscheidung_id"]                      # bewegt b UND c: zwei Zeilen
    vorher = (stand(db), protokoll(db))
    original = db.con

    class Bruch:
        """Reicht ``execute`` durch, bricht aber beim zweiten Rückschritt ab (nach dem ersten UPDATE und INSERT)."""

        def __init__(self, con):
            self.con, self.n = con, 0

        def execute(self, sql, *args):
            if "INSERT INTO fahrzeug_zuordnungen" in sql and "'zurueck'" in sql:
                self.n += 1
                if self.n == 2:
                    raise RuntimeError("Absicht")
            return self.con.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.con, name)

    monkeypatch.setattr(db, "con", Bruch(original))
    with pytest.raises(RuntimeError):
        hebe_auf(db, e, 1)
    monkeypatch.setattr(db, "con", original)
    assert (stand(db), protokoll(db)) == vorher and not original.in_transaction


# ---------------------------------------------------------------- Wirkung: reine Funktionen
def test_wende_an_ohne_entscheidungen_gibt_dasselbe_objekt_zurueck():
    dup = {"x": [{"id": "y"}]}
    assert wende_an(dup, None, {}.get, lambda a: a["id"]) is dup
    assert wende_an(dup, Wirkung(), {}.get, lambda a: a["id"]) is dup


def test_wende_an_vereinigt_und_zieht_verschieden_ab():
    zeilen = {i: {"id": i} for i in "abcd"}
    dup = {"a": [zeilen["b"]], "b": [zeilen["a"]]}
    w = Wirkung((frozenset("bcd"),), frozenset({frozenset("ab"), frozenset("xy")}))
    erg = wende_an(dup, w, zeilen.get, lambda z: z["id"])
    assert {i: sorted(z["id"] for z in v) for i, v in erg.items()} == {"b": ["c", "d"], "c": ["b", "d"], "d": ["b", "c"]}   # a/b getrennt
    assert dup == {"a": [zeilen["b"]], "b": [zeilen["a"]]}                                                                  # Eingabe unverändert
    ids = wende_an({"a": ["b"], "b": ["a"]}, w, lambda i: i, lambda i: i)
    assert ids == {"b": ["c", "d"], "c": ["b", "d"], "d": ["b", "c"]}
    # nur "a" ist als Zeile bekannt (z. B. "b" hat keinen Preis): "b" bekommt "a" als Dublette, "a" kein unbekanntes Mitglied
    assert wende_an({}, Wirkung((frozenset("ab"),)), {"a": {"id": "a"}}.get, lambda z: z["id"]) == {"b": [{"id": "a"}]}


@pytest.mark.parametrize("stati, erwartet", [
    (["neu", "gekauft"], "gekauft"), (["kontaktiert", "besichtigung", "neu"], "besichtigung"), (["verhandlung", "kontaktiert"], "verhandlung"),
    (["besichtigung", "verhandlung"], "besichtigung"), (["kontaktiert", "vorbereitet"], "kontaktiert"), (["vorbereitet", "abgesagt"], "vorbereitet"),
    (["abgesagt", "uninteressant"], "abgesagt"), (["uninteressant", "neu"], "uninteressant"), (["abgesagt", "neu"], "abgesagt"),
    (["gekauft", "abgesagt"], "gekauft"), (["neu"], "neu"), ([], "neu"), ([None, "neu"], "neu"), (["x", "kontaktiert"], "kontaktiert"), (["x"], "neu"),
], ids=["k>n", "b>k", "v>k", "b>v", "k>vb", "vb>a", "a>u", "u>n", "a>n", "k>a", "neu", "leer", "none", "x+k", "x"])
def test_fahrzeug_status_rangfolge(stati, erwartet):
    assert fahrzeug_status(stati) == erwartet and fahrzeug_status(reversed(stati)) == erwartet and fahrzeug_status(iter(stati)) == erwartet


# ---------------------------------------------------------------- Wirkung: Bewertung
def test_ohne_entscheidungen_ist_alles_bit_gleich(cfg, db, importiert):
    mit_preis, aktive = [dict(r) for r in db.alle_mit_preis()], [dict(r) for r in db.aktive()]
    assert lade_wirkung(db).leer and len(aktive) > 10
    ohne = repr(bewerte_zeilen(cfg, BASIS, mit_preis, aktive, LAUF, jetzt=datetime(2026, 10, 20, 12), wirkung=None))
    mit = repr(bewerte_zeilen(cfg, BASIS, mit_preis, aktive, LAUF, jetzt=datetime(2026, 10, 20, 12), wirkung=lade_wirkung(db)))
    assert ohne == mit
    from wmscout.bewertung.auswertung import finde_duplikate
    from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
    alle = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    assert dubletten_ids(db) == {i: sorted(b["id"] for b in v) for i, v in finde_duplikate(alle).items()}


def test_bestaetigte_gruppe_wirkt_auf_duplikat_sperre_und_vergleichsbasis(cfg, db):
    i1, i2 = paar_p(db)
    db.speichere_treffer(treffer("q1", titel="Hymer B 544", marke="Hymer", ez_jahr=2012, km=120000, preis=30000), "Alkoven")
    db.setze_status("p1", "kontaktiert")
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "duplikat" not in zeilen["p2"]["a"] and zeilen["p2"]["dubletten_ids"] == []
    assert {a["id"] for a in vergleichsbasis_aus(db)} >= {"p1", "p2"}
    bestaetige(db, i1, i2, None)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "gleiches Fahrzeug schon bearbeitet: Anzeige p1" in zeilen["p2"]["a"]["duplikat"]
    assert zeilen["p2"]["sperre"] and "Anzeige p1" in zeilen["p2"]["sperre"]
    assert zeilen["p1"]["dubletten_ids"] == ["p2"] and zeilen["p2"]["dubletten_ids"] == ["p1"] and zeilen["q1"]["dubletten_ids"] == []
    basis = {a["id"] for a in vergleichsbasis_aus(db)}
    assert "q1" in basis and len({"p1", "p2"} & basis) == 1             # von der Gruppe nur das aktuellste Inserat
    assert zeilen["p2"]["a"]["tage_online"] >= 0


def test_ablehnen_hebt_die_heuristische_sperre_fuer_das_paar_auf(cfg, db):
    db.speichere_treffer(treffer("x1"), "Alkoven")
    db.speichere_treffer(treffer("x2"), "Alkoven")
    db.setze_status("x1", "kontaktiert")
    i1, i2 = inserat_id(db, "x1"), inserat_id(db, "x2")
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "gleiches Fahrzeug schon bearbeitet" in zeilen["x2"]["sperre"] and zeilen["x2"]["dubletten_ids"] == ["x1"]
    assert dubletten_ids(db) == {"x1": ["x2"], "x2": ["x1"]} and len({"x1", "x2"} & {a["id"] for a in vergleichsbasis_aus(db)}) == 1
    e = lehne_ab(db, i1, i2, 3)["entscheidung_id"]
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "duplikat" not in zeilen["x2"]["a"] and "gleiches Fahrzeug" not in (zeilen["x2"]["sperre"] or "")
    assert zeilen["x2"]["dubletten_ids"] == [] and dubletten_ids(db) == {}
    assert {"x1", "x2"} <= {a["id"] for a in vergleichsbasis_aus(db)}
    hebe_auf(db, e, 3)                                                  # Aufheben: die Heuristik wirkt wieder
    assert dubletten_ids(db) == {"x1": ["x2"], "x2": ["x1"]}


def test_bewertung_laedt_weiterhin_weder_datenbank_noch_sqlite3():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", "import sys, wmscout.bewertung.auswertung, wmscout.dubletten; "
                        "print('wmscout.datenbank' in sys.modules, 'sqlite3' in sys.modules)"],
                       capture_output=True, text=True, cwd=BASIS, timeout=60)
    assert r.stdout.strip() == "False False", r.stderr


# ---------------------------------------------------------------- Team: Datenbankebene (D3)
def test_team_sperre_der_bestaetigten_gruppe_gilt_auch_mit_veralteter_liste(cfg, db, tmp_path):
    """Der Aufrufer reicht eine veraltete (leere) Dublettenliste: die Datenbank ergänzt die bestätigte Gruppe selbst."""
    t = TeamSpeicher(db, tmp_path / "fotos")
    for n in ("Ben", "Carl"):
        t.nutzer_anlegen(n, "sicher1234", "mitarbeiter")
    ben, carl = _id(db, "Ben"), _id(db, "Carl")
    i1, i2 = paar_p(db)
    jetzt = datetime.now().isoformat(timespec="seconds")
    assert db.uebernimm("p1", ben, jetzt, "", dubletten=())
    assert db.uebernimm("p2", carl, jetzt, "", dubletten=()) and db.gib_ab("p2", carl)              # ohne Gruppe geht es
    bestaetige(db, i1, i2, None)
    assert db.bestaetigte_gruppe("p2") == ["p1"]
    assert db.uebernimm("p2", carl, jetzt, "", dubletten=()) is False                              # jetzt gesperrt, obwohl die Liste leer ist
    from wmscout.bearbeitung import BearbeitungsKonflikt
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status("p2", "kontaktiert", nutzer_id=carl, grenze="", dubletten=())
    with pytest.raises(BearbeitungsKonflikt):
        db.nachgefasst("p2", "Hallo", nutzer_id=carl, grenze="", dubletten=())
    assert db.uebernimm("p1", ben, jetzt, "", dubletten=()) is True                                # der Halter selbst darf
    # Zuweisen an Carl scheitert an der kontaktierten Dublette des Kollegen (Gruppe aus der Datenbank)
    db.setze_status("p1", "kontaktiert", nutzer_id=ben, grenze="", dubletten=())
    with pytest.raises(BearbeitungsKonflikt):
        db.weise_zu("p2", carl, jetzt, dubletten=(), grenze="")


def _id(db, name):
    return db.con.execute("SELECT id FROM nutzer WHERE name=?", (name,)).fetchone()[0]


def test_wettlauf_zweier_verbindungen_bestaetigen_gegen_uebernehmen(cfg, db, tmp_path):
    """Die Bestätigung läuft in einer offenen Transaktion einer zweiten Verbindung; die Übernahme wartet auf die Schreibsperre und sieht danach
    die Gruppe (D3) – auch wenn sie mit einer vor der Bestätigung berechneten Liste aufgerufen wird."""
    t = TeamSpeicher(db, tmp_path / "fotos")
    for n in ("Ben", "Carl"):
        t.nutzer_anlegen(n, "sicher1234", "mitarbeiter")
    ben, carl = _id(db, "Ben"), _id(db, "Carl")
    i1, i2 = paar_p(db)
    jetzt = datetime.now().isoformat(timespec="seconds")
    assert db.uebernimm("p1", ben, jetzt, "", dubletten=())
    zweite = Datenbank(cfg["ausgabe"]["datenbank"])
    ergebnis, fehler = [], []

    def uebernehmen():
        try:
            ergebnis.append(db.uebernimm("p2", carl, jetzt, "", dubletten=()))
        except Exception as e:  # noqa: BLE001
            fehler.append(e)

    try:
        with zweite.transaktion():
            bestaetige(zweite, i1, i2, None)                            # noch nicht festgeschrieben
            th = threading.Thread(target=uebernehmen)
            th.start()
            time.sleep(0.4)
            assert th.is_alive() and not ergebnis                       # wartet auf die Schreibsperre
        th.join(10)
    finally:
        zweite.con.close()
    assert not fehler and ergebnis == [False]
    assert db.con.execute("SELECT bearbeiter_id FROM bearbeitung WHERE anzeige_id='p2'").fetchone() is None


# ---------------------------------------------------------------- API
@pytest.fixture
def team_api(cfg, db, importiert, tmp_path):
    """Server mit Team (Anna Inhaberin, Ben und Carl Mitarbeiter, Hugo Standort-Zugang), p1/p2 (nicht heuristisch) und x1/x2 (heuristisch)."""
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    t.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    t.nutzer_anlegen("Carl", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale Nord", "20095", "Hamburg")
    t.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    paar_p(db)
    db.speichere_treffer(treffer("x1", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.speichere_treffer(treffer("x2", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    srv = starte(cfg, db)
    srv.test_db = db
    yield srv
    srv.shutdown()
    srv.server_close()


def ids(db, *anzeigen):
    return [inserat_id(db, a) for a in anzeigen]


def pfad(aktion):
    return f"/api/dubletten/{aktion}"


def test_api_bestaetigen_antwort_gruppe_und_wirkung(team_api, db):
    anna = anmelden(team_api, "Anna")
    i1, i2 = ids(db, "p1", "p2")
    vorher = stand(db)
    status, d, _ = anna("POST", pfad("bestaetigen"), {"a": i2, "b": i1})
    assert status == 200 and d["ok"] is True and d["neu"] is True and d["bewegt"] == [i2]
    assert [m["anzeigen_id"] for m in d["gruppe"]] == ["p1", "p2"] and d["fahrzeug_status"] == "neu" and d["inserat_id"] == i1
    e = d["entscheidungen"][0]
    assert (e["id"], e["entscheidung"], e["status"], e["nutzer"], e["aufhebbar"]) == (d["entscheidung_id"], "gleich", "gilt", "Anna", True)
    assert e["anzeige_a"] == "p1" and e["anzeige_b"] == "p2" and isinstance(e["gruende"], list)
    assert stand(db)["anzeigen"] == vorher["anzeigen"] and stand(db)["bearbeitung"] == vorher["bearbeitung"]
    status, d2, _ = anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})
    assert status == 200 and d2["neu"] is False and d2["bewegt"] == [] and len(d2["entscheidungen"]) == 1
    status, g, _ = anna("GET", "/api/dubletten/entscheidungen?anzeige=p2")
    assert status == 200 and g["anzeige"] == "p2" and [m["anzeigen_id"] for m in g["gruppe"]] == ["p1", "p2"]
    assert (g["darf_bestaetigen"], g["darf_ablehnen"], g["darf_aufheben"]) == (True, True, True) and g["entscheidungen"][0]["id"] == e["id"]
    status, ab, _ = anna("POST", pfad("aufheben"), {"entscheidung_id": e["id"]})
    assert status == 200 and ab["zurueck"] == [i2] and [m["anzeigen_id"] for m in ab["gruppe"]] == ["p1"]
    assert ab["entscheidungen"][0]["status"] == "aufgehoben" and ab["entscheidungen"][0]["aufgehoben_von"] and stand(db) == vorher


def test_api_fehler_400_404_409(team_api, db):
    anna = anmelden(team_api, "Anna")
    i1, i2 = ids(db, "p1", "p2")
    for daten in ({}, {"a": i1}, {"a": i1, "b": i1}, {"a": 999999, "b": i1}, {"a": "x", "b": i1}, {"a": True, "b": i1}):
        for aktion in ("bestaetigen", "ablehnen"):
            status, d, _ = anna("POST", pfad(aktion), daten)
            assert status == 400 and "fehler" in d, (aktion, daten)
    assert anna("POST", pfad("aufheben"), {"entscheidung_id": 999})[0] == 400
    assert anna("POST", pfad("aufheben"), {})[0] == 400
    assert anna("GET", "/api/dubletten/entscheidungen?anzeige=gibtsnicht")[0] == 404
    assert anna("GET", "/api/dubletten/entscheidungen")[0] == 404
    assert anna("POST", pfad("ablehnen"), {"a": i1, "b": i2})[0] == 200
    status, d, _ = anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})
    assert status == 409 and d["grund"] == "konflikt" and "verschieden" in d["fehler"]
    anna("POST", pfad("aufheben"), {"entscheidung_id": 1})
    assert anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})[0] == 200
    status, d, _ = anna("POST", pfad("ablehnen"), {"a": i1, "b": i2})
    assert status == 409 and d["grund"] == "konflikt"
    x1, x2 = ids(db, "x1", "x2")
    anna("POST", pfad("bestaetigen"), {"a": x1, "b": x2})
    anna("POST", pfad("bestaetigen"), {"a": i1, "b": x1})
    status, d, _ = anna("POST", pfad("aufheben"), {"entscheidung_id": 2})
    assert status == 409 and d["grund"] == "konflikt" and "Entscheidung 4" in d["fehler"]            # LIFO


def vorbereiten(db, aktion, i1, i2):
    """Voraussetzung je Aktion: Aufheben braucht eine geltende Entscheidung."""
    return bestaetige(db, i1, i2, None)["entscheidung_id"] if aktion == "aufheben" else None


RECHTE = {  # (Aktion, Nutzer) → erwarteter Status; Händler nie
    ("bestaetigen", "Anna"): 200, ("bestaetigen", "Ben"): 200, ("bestaetigen", "Hugo"): 403,
    ("ablehnen", "Anna"): 200, ("ablehnen", "Ben"): 403, ("ablehnen", "Hugo"): 403,
    ("aufheben", "Anna"): 200, ("aufheben", "Ben"): 403, ("aufheben", "Hugo"): 403,
}


@pytest.mark.parametrize("aktion, name", list(RECHTE), ids=[f"{a}-{n}" for a, n in RECHTE])
def test_api_rechte_je_rolle(team_api, db, aktion, name):
    i1, i2 = ids(db, "p1", "p2")
    eid = vorbereiten(db, aktion, i1, i2)
    vorher = (stand(db), protokoll(db))
    daten = {"entscheidung_id": eid} if aktion == "aufheben" else {"a": i1, "b": i2}
    status, d, _ = anmelden(team_api, name)("POST", pfad(aktion), daten)
    assert status == RECHTE[(aktion, name)], d
    if status == 403:
        assert d["grund"] == "recht" and (stand(db), protokoll(db)) == vorher             # verweigert: nichts geändert
    else:
        assert (stand(db), protokoll(db)) != vorher
        row = db.con.execute("SELECT nutzer_id, aufgehoben_von, status FROM dubletten_entscheidungen ORDER BY id DESC").fetchone()
        assert (row["aufgehoben_von"] if aktion == "aufheben" else row["nutzer_id"]) == _id(db, name)


@pytest.mark.parametrize("aktion", ["bestaetigen", "ablehnen", "aufheben"])
def test_api_rechte_einzelplatz_ohne_nutzer_darf_alles(cfg, db, importiert, aktion):
    i1, i2 = paar_p(db)
    eid = vorbereiten(db, aktion, i1, i2)
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        status, d, _ = c("POST", pfad(aktion), {"entscheidung_id": eid} if aktion == "aufheben" else {"a": i1, "b": i2})
        assert status == 200, d
        row = db.con.execute("SELECT nutzer_id, aufgehoben_von FROM dubletten_entscheidungen").fetchone()
        assert row["nutzer_id"] is None and (aktion != "aufheben" or row["aufgehoben_von"] is None)
        assert c("GET", "/api/dubletten/entscheidungen?anzeige=p1")[0] == 200
        assert db.con.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0              # ohne Nutzer wird nichts protokolliert
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_ohne_anmeldung_und_haendler_beim_lesen(team_api, db):
    assert Client(team_api.server_address[1])("POST", pfad("bestaetigen"), {"a": 1, "b": 2})[0] == 401
    status, d, _ = anmelden(team_api, "Hugo")("GET", "/api/dubletten/entscheidungen?anzeige=p1")
    assert status == 403 and d["grund"] == "recht"
    assert anmelden(team_api, "Ben")("GET", "/api/dubletten/entscheidungen?anzeige=p1")[0] == 200


@pytest.mark.parametrize("aktion", ["bestaetigen", "ablehnen", "aufheben"])
def test_api_csrf(team_api, db, aktion):
    anna = anmelden(team_api, "Anna")
    i1, i2 = ids(db, "p1", "p2")
    eid = vorbereiten(db, aktion, i1, i2)
    vorher = (stand(db), protokoll(db))
    daten = {"entscheidung_id": eid} if aktion == "aufheben" else {"a": i1, "b": i2}
    status, d, _ = anna("POST", pfad(aktion), daten, token=False)
    assert status == 403 and d["grund"] == "csrf" and (stand(db), protokoll(db)) == vorher
    anna.csrf = "falsch"
    assert anna("POST", pfad(aktion), daten)[0] == 403 and (stand(db), protokoll(db)) == vorher


def test_api_audit_eintrag(team_api, db):
    anna = anmelden(team_api, "Anna")
    i1, i2 = ids(db, "p1", "p2")
    assert anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})[0] == 200
    assert anna("POST", pfad("bestaetigen"), {"a": 999999, "b": i2})[0] == 400
    assert anmelden(team_api, "Ben")("POST", pfad("ablehnen"), {"a": i1, "b": i2})[0] == 403
    for _ in range(50):
        zeilen = db.con.execute("SELECT aktion, objekt, nutzer, rolle, status FROM audit WHERE pfad LIKE '/api/dubletten/%' ORDER BY id").fetchall()
        if len(zeilen) == 3:
            break
        time.sleep(0.1)
    assert [tuple(z) for z in zeilen] == [("aendern", "dublette:bestaetigen", "Anna", "inhaber", 200),
                                          ("aendern", "dublette:bestaetigen", "Anna", "inhaber", 400),
                                          ("aendern", "dublette:ablehnen", "Ben", "mitarbeiter", 403)]
    from wmscout.audit import einordnen
    assert einordnen("POST", "/api/dubletten/aufheben") == ("aendern", "dublette:aufheben") and einordnen("GET", "/api/dubletten/entscheidungen") is None


def test_api_vorschlaege_zeigen_was_der_nutzer_darf(team_api):
    for name, bestaetigen, ablehnen in (("Anna", True, True), ("Ben", True, False)):
        status, d, _ = anmelden(team_api, name)("GET", "/api/dubletten-vorschlaege")
        assert status == 200 and d["vorschlaege"]
        assert all((v["darf_bestaetigen"], v["darf_ablehnen"]) == (bestaetigen, ablehnen) for v in d["vorschlaege"])
        assert {"inserat_a", "inserat_b", "anzeigen_a", "anzeigen_b", "plattform_a", "plattform_b"} <= set(d["vorschlaege"][0])


def vorschlag_paare(client):
    return {frozenset((v["anzeigen_a"], v["anzeigen_b"])) for v in client("GET", "/api/dubletten-vorschlaege?limit=1000")[1]["vorschlaege"]}


def test_cache_wird_sofort_geleert_vorschlaege_fahrzeugliste_und_team_sperre(team_api, db, monkeypatch):
    """D2: nach Bestätigen/Ablehnen/Aufheben gilt der neue Stand sofort – nicht erst nach 30 s. Das Audit-Protokoll schreibt über eine zweite
    Verbindung und würde den Zwischenspeicher über ``data_version`` ohnehin verwerfen; hier ist es abgeschaltet, damit nur die ausdrückliche
    Leerung wirkt."""
    from wmscout.audit import AuditSpeicher
    monkeypatch.setattr(AuditSpeicher, "schreibe", lambda *a, **k: None)
    anna, ben, carl = (anmelden(team_api, n) for n in ("Anna", "Ben", "Carl"))
    x1, x2 = ids(db, "x1", "x2")
    i1, i2 = ids(db, "p1", "p2")
    assert ben("POST", "/api/status", {"id": "p1", "status": "kontaktiert", "text": "Hallo"})[0] == 200      # Ben hält p1; Zwischenspeicher warm
    assert frozenset(("x1", "x2")) in vorschlag_paare(anna)
    liste = {f["id"]: f for f in carl("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert not (liste["p2"]["sperre"] or "").startswith("gleiches Fahrzeug")                                # vorher: keine Dublette
    # 1. Bestätigen p1 = p2: Carl bekommt sofort 409 mit Hinweis auf Ben und die Dublette
    assert anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})[0] == 200
    status, d, _ = carl("POST", "/api/status", {"id": "p2", "status": "kontaktiert", "text": "Hallo"})
    assert status == 409 and d["grund"] == "konflikt" and "Ben" in d["fehler"] and "Dublette p1" in d["fehler"], d
    liste = {f["id"]: f for f in carl("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert "gleiches Fahrzeug schon bearbeitet: Anzeige p1" in liste["p2"]["sperre"]
    # 2. Aufheben: sofort wieder frei
    eid = db.con.execute("SELECT MAX(id) FROM dubletten_entscheidungen").fetchone()[0]
    assert anna("POST", pfad("aufheben"), {"entscheidung_id": eid})[0] == 200
    assert carl("POST", "/api/status", {"id": "p2", "status": "kontaktiert", "text": "Hallo"})[0] == 200
    # 3. Ablehnen x1/x2: Vorschlag verschwindet sofort, Team-Sperre fällt sofort
    assert ben("POST", "/api/status", {"id": "x1", "status": "kontaktiert", "text": "Hallo"})[0] == 200
    assert carl("POST", "/api/status", {"id": "x2", "status": "kontaktiert", "text": "Hallo"})[0] == 409           # heuristische Sperre
    assert anna("POST", pfad("ablehnen"), {"a": x1, "b": x2})[0] == 200
    assert frozenset(("x1", "x2")) not in vorschlag_paare(anna)
    assert carl("POST", "/api/status", {"id": "x2", "status": "kontaktiert", "text": "Hallo"})[0] == 200


def test_cache_wird_auch_im_einzelplatz_sofort_geleert(cfg, db, importiert):
    i1, i2 = paar_p(db)
    db.speichere_treffer(treffer("x1", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.speichere_treffer(treffer("x2", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.setze_status("p1", "kontaktiert")
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        assert frozenset(("x1", "x2")) in vorschlag_paare(c)
        liste = {f["id"]: f for f in c("GET", "/api/fahrzeuge?filter=alle")[1]}
        assert "gleiches Fahrzeug" not in (liste["p2"]["sperre"] or "")
        x1, x2 = inserat_id(db, "x1"), inserat_id(db, "x2")
        assert c("POST", pfad("bestaetigen"), {"a": i1, "b": i2})[0] == 200
        assert c("POST", pfad("ablehnen"), {"a": x1, "b": x2})[0] == 200
        assert frozenset(("x1", "x2")) not in vorschlag_paare(c)                                      # sofort, nicht erst nach 30 s
        liste = {f["id"]: f for f in c("GET", "/api/fahrzeuge?filter=alle")[1]}
        assert "gleiches Fahrzeug schon bearbeitet: Anzeige p1" in liste["p2"]["sperre"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_ohne_ablehnen_bleibt_die_heuristische_sperre_im_team(team_api, db):
    ben, carl = anmelden(team_api, "Ben"), anmelden(team_api, "Carl")
    assert ben("POST", "/api/status", {"id": "x1", "status": "kontaktiert", "text": "Hallo"})[0] == 200
    for _ in range(2):
        assert carl("POST", "/api/status", {"id": "x2", "status": "kontaktiert", "text": "Hallo"})[0] == 409


def test_bestaetigen_meldet_verschiedene_halter_und_uebertraegt_nichts(team_api, db):
    ben, carl, anna = (anmelden(team_api, n) for n in ("Ben", "Carl", "Anna"))
    i1, i2 = ids(db, "p1", "p2")
    assert ben("POST", "/api/bearbeitung/p1/uebernehmen", {})[0] == 200
    assert carl("POST", "/api/bearbeitung/p2/uebernehmen", {})[0] == 200
    vorher = stand(db)["bearbeitung"]
    status, d, _ = anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})
    assert status == 200 and d["warnung"]["grund"] == "verschiedene_halter"
    assert {(h["anzeige_id"], h["name"]) for h in d["warnung"]["halter"]} == {("p1", "Ben"), ("p2", "Carl")}
    assert stand(db)["bearbeitung"] == vorher                                                           # Reservierungen nicht übertragen
    # nur ein Halter: keine Warnung
    anna("POST", pfad("aufheben"), {"entscheidung_id": d["entscheidung_id"]})
    assert carl("POST", "/api/bearbeitung/p2/abgeben", {})[0] == 200
    status, d, _ = anna("POST", pfad("bestaetigen"), {"a": i1, "b": i2})
    assert status == 200 and "warnung" not in d


def test_fahrzeugstatus_in_der_antwort_ist_abgeleitet_und_nicht_gespeichert(team_api, db):
    anna = anmelden(team_api, "Anna")
    assert anna("POST", "/api/status", {"id": "p2", "status": "verhandlung", "text": "x"})[0] == 200
    assert anna("POST", "/api/status", {"id": "p1", "status": "kontaktiert", "text": "x"})[0] == 200
    vorher = stand(db)
    status, d, _ = anna("POST", pfad("bestaetigen"), {"a": ids(db, "p1")[0], "b": ids(db, "p2")[0]})
    assert d["fahrzeug_status"] == "verhandlung" and {m["status"] for m in d["gruppe"]} == {"kontaktiert", "verhandlung"}
    assert stand(db)["anzeigen"] == vorher["anzeigen"]                                                  # Ankaufsstatus bleibt je Inserat


# ---------------------------------------------------------------- CLI (nur Einzelplatz)
def test_cli_bestaetigen_ablehnen_aufheben_nur_im_einzelplatz(cfg, tmp_path):
    from tests.test_cli import _scout
    d = Datenbank(cfg["ausgabe"]["datenbank"])
    paar_p(d)
    d.speichere_treffer(treffer("p3", ort="80333 München", km=91500), "Alkoven")
    d.con.close()
    r = _scout(cfg, tmp_path, "dubletten", "bestaetigen", "p1", "p2")
    assert r.returncode == 0 and "Entscheidung 1: gleiches Fahrzeug" in r.stdout, r.stderr
    assert "nichts geändert" in _scout(cfg, tmp_path, "dubletten", "bestaetigen", "p2", "p1").stdout
    assert _scout(cfg, tmp_path, "dubletten", "ablehnen", "p1", "p2").returncode != 0               # Konflikt: schon dasselbe Fahrzeug
    assert "verschiedene Fahrzeuge" in _scout(cfg, tmp_path, "dubletten", "ablehnen", "p1", "p3").stdout
    for falsch in (("bestaetigen", "p1"), ("bestaetigen", "p1", "gibtsnicht"), ("aufheben", "x"), ("aufheben", "99")):
        r = _scout(cfg, tmp_path, "dubletten", *falsch)
        assert r.returncode != 0 and "Traceback" not in r.stderr, falsch
    r = _scout(cfg, tmp_path, "dubletten", "aufheben", "1")
    assert r.returncode == 0 and "aufgehoben; zurückgehängt: 1" in r.stdout, r.stderr
    d = Datenbank(cfg["ausgabe"]["datenbank"])
    assert fahrzeug(d, "p1") != fahrzeug(d, "p2")
    assert d.con.execute("SELECT COUNT(*) FROM fahrzeug_zuordnungen").fetchone()[0] == 2
    TeamSpeicher(d, tmp_path / "fotos").nutzer_anlegen("Anna", "sicher1234", "inhaber")
    d.con.close()
    r = _scout(cfg, tmp_path, "dubletten", "bestaetigen", "p1", "p2")
    assert r.returncode != 0 and "Einzelplatz" in r.stderr


# ---------------------------------------------------------------- QA-Korrekturen (H1, M1, N2) und Zufallsketten
def umfeld_a_a2_c(db):
    """A und C sind heuristische Dubletten (gleiche PLZ), A2 (anderer Ort) wird als gleich zu A bestätigt – C und A2 verbindet nur die Gruppe."""
    db.speichere_treffer(treffer("A", km=90000), "Alkoven")
    db.speichere_treffer(treffer("C", km=91000), "Alkoven")
    db.speichere_treffer(treffer("A2", ort="80331 München", km=92000), "Alkoven")
    assert dubletten_ids(db) == {"A": ["C"], "C": ["A"]}
    bestaetige(db, inserat_id(db, "A"), inserat_id(db, "A2"), None)
    return tuple(inserat_id(db, x) for x in ("A", "A2", "C"))


@pytest.mark.parametrize("zustand_n", ["aktiv", "lange_nicht_gesehen"])
def test_h1_gruppenmitglied_ohne_preis_wirkt_auf_sperre_und_anschreiben(cfg, db, zustand_n):
    db.speichere_treffer(treffer("P", preis=40000), "Alkoven")
    db.speichere_treffer(treffer("N", preis=None, ort="80331 München"), "Alkoven")
    if zustand_n != "aktiv":
        db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2026-01-01T10:00:00' WHERE id='N'")
    db.setze_status("N", "kontaktiert")
    db.con.commit()
    z0 = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "duplikat" not in z0["P"]["a"] and z0["P"]["dubletten_ids"] == []                 # vor der Bestätigung: keine Verbindung
    bestaetige(db, inserat_id(db, "P"), inserat_id(db, "N"), None)
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert dubletten_ids(db)["P"] == ["N"]
    assert z["P"]["dubletten_ids"] == ["N"] and "gleiches Fahrzeug schon bearbeitet: Anzeige N" in z["P"]["a"]["duplikat"]
    assert z["P"]["sperre"] and "Anzeige N" in z["P"]["sperre"] and z["P"]["brief"] is None and z["P"]["bereit"] is False
    assert "P" in {a["id"] for a in vergleichsbasis_aus(db)}                                 # die Vergleichsbasis bleibt bei Inseraten mit Preis


def test_m1_gruppe_uebernimmt_heuristische_nachbarn_ihrer_mitglieder_in_wende_an():
    zeilen = {i: {"id": i} for i in ("A", "A2", "C", "D")}
    heur = {"A": [zeilen["C"]], "C": [zeilen["A"]]}
    w = Wirkung((frozenset(("A", "A2")),))
    erg = wende_an(heur, w, zeilen.get, lambda z: z["id"])
    assert {i: sorted(z["id"] for z in v) for i, v in erg.items()} == {"A": ["A2", "C"], "A2": ["A", "C"], "C": ["A", "A2"]}
    # keine Hülle über Heuristik-Ketten: D~C bleibt bei C, erreicht A/A2 nicht
    heur2 = {**heur, "C": [zeilen["A"], zeilen["D"]], "D": [zeilen["C"]]}
    erg2 = wende_an(heur2, w, zeilen.get, lambda z: z["id"])
    assert sorted(z["id"] for z in erg2["A2"]) == ["A", "C"] and sorted(z["id"] for z in erg2["D"]) == ["C"]
    # „verschieden“ gegen irgendein Mitglied trennt C von der ganzen Gruppe
    ohne = wende_an(heur, Wirkung(w.gruppen, frozenset({frozenset(("C", "A2"))})), zeilen.get, lambda z: z["id"])
    assert {i: sorted(z["id"] for z in v) for i, v in ohne.items()} == {"A": ["A2"], "A2": ["A"]}


def test_m1_team_sperre_und_bewertung(cfg, db, tmp_path):
    a, a2, c = umfeld_a_a2_c(db)
    assert dubletten_ids(db) == {"A": ["A2", "C"], "A2": ["A", "C"], "C": ["A", "A2"]}
    t = TeamSpeicher(db, tmp_path / "fotos")
    for n in ("Ben", "Carl"):
        t.nutzer_anlegen(n, "sicher1234", "mitarbeiter")
    ben, carl = _id(db, "Ben"), _id(db, "Carl")
    jetzt = datetime.now().isoformat(timespec="seconds")
    assert db.uebernimm("C", ben, jetzt, "", dubletten=dubletten_ids(db)["C"])                 # Ben reserviert C
    assert db.uebernimm("A2", carl, jetzt, "", dubletten=dubletten_ids(db)["A2"]) is False     # Carl darf A2 nicht (Doppelansprache)
    # auch mit einer Liste, die nur die heuristischen Nachbarn von A2 kennt (Datenbank ergänzt Gruppe und deren Nachbarn selbst)
    assert db.uebernimm("A2", carl, jetzt, "", dubletten=["C"]) is False
    # Bewertung: C kontaktiert → A2 und A tragen den Vermerk; Vergleichsbasis nimmt von {A, A2, C} nur eines
    db.setze_status("C", "kontaktiert")
    z = {x["a"]["id"]: x for x in bewerte_alle(cfg, db, BASIS, LAUF)}
    assert "Anzeige C" in z["A2"]["a"]["duplikat"] and z["A2"]["dubletten_ids"] == ["A", "C"]
    assert len({"A", "A2", "C"} & {x["id"] for x in vergleichsbasis_aus(db)}) == 1


def test_m1_datenbank_ergaenzt_die_gruppen_der_listenmitglieder_selbst(db, tmp_path):
    """C kennt (veraltete Liste) nur den heuristischen Nachbarn A; Ben hält A2, das mit A bestätigt ist: die Datenbank findet A2 in derselben Transaktion."""
    umfeld_a_a2_c(db)
    t = TeamSpeicher(db, tmp_path / "fotos")
    for n in ("Ben", "Carl"):
        t.nutzer_anlegen(n, "sicher1234", "mitarbeiter")
    jetzt = datetime.now().isoformat(timespec="seconds")
    assert db.uebernimm("A2", _id(db, "Ben"), jetzt, "", dubletten=())
    assert db.bestaetigte_gruppe("C", ["A"]) == ["A2"] and db.bestaetigte_gruppe("C") == []
    assert db.uebernimm("C", _id(db, "Carl"), jetzt, "", dubletten=["A"]) is False


def test_m1_verschieden_gegen_mitglied_loest_c_von_der_ganzen_gruppe(db):
    a, a2, c = umfeld_a_a2_c(db)
    e = lehne_ab(db, a2, c, None)["entscheidung_id"]
    assert dubletten_ids(db) == {"A": ["A2"], "A2": ["A"]}
    hebe_auf(db, e, None)
    assert dubletten_ids(db) == {"A": ["A2", "C"], "A2": ["A", "C"], "C": ["A", "A2"]}


def test_ohne_entscheidungen_gilt_weiter_nur_die_heuristik(db):
    db.speichere_treffer(treffer("A", km=90000), "Alkoven")
    db.speichere_treffer(treffer("C", km=91000), "Alkoven")
    db.speichere_treffer(treffer("A2", ort="80331 München", km=92000), "Alkoven")
    assert dubletten_ids(db) == {"A": ["C"], "C": ["A"]}


def test_n2_aufheben_mit_unicode_ziffer_ist_ein_sauberer_fehler(cfg, tmp_path):
    from tests.test_cli import _scout
    for falsch in ("²", "٣", "1 2", "-1", ""):
        r = _scout(cfg, tmp_path, "dubletten", "aufheben", falsch)
        assert r.returncode != 0 and "Traceback" not in r.stderr and "Entscheidungsnummer" in r.stderr, falsch


def keine_waisen(db):
    assert db.con.execute("SELECT COUNT(*) FROM inserate i LEFT JOIN fahrzeuge f ON f.id=i.fahrzeug_id WHERE f.id IS NULL").fetchone()[0] == 0


@pytest.mark.parametrize("seed", range(10))
def test_zufallsketten_aufheben_in_beliebiger_reihenfolge_bit_gleich(db, seed):
    rnd = random.Random(seed)
    for k in range(6):
        db.speichere_treffer(treffer(f"q{k}", ort=f"{10115 + 1000 * k} Ort", km=50000 + 20000 * k), "Alkoven")
    ids_ = [inserat_id(db, f"q{k}") for k in range(6)]
    vorher = stand(db)
    offen = []
    for _ in range(8):
        a, b = rnd.sample(ids_, 2)
        try:
            e = bestaetige(db, a, b, 1)
            if e["neu"]:
                offen.append(e["entscheidung_id"])
        except DublettenKonflikt:
            pass
        keine_waisen(db)
    schritte = 0
    while offen:
        schritte += 1
        assert schritte < 200
        e = rnd.choice(offen)
        blockiert = aufheben_blockiert_durch(db, e)
        try:
            hebe_auf(db, e, 1)
            assert blockiert is None
            offen.remove(e)
        except DublettenKonflikt:
            assert blockiert is not None
        keine_waisen(db)
    assert stand(db) == vorher
