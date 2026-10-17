"""Team (T1), Korrekturrunde 1 nach QA: Besichtigung und Status ohne Übernahme, Dubletten bei Zuweisung/Erzwingen, verwaiste Inserate,
Dubletten ohne Bewertung, Datenschutz der Zähler, gesperrte Datenbank, Kommandozeile, Prozess-Wettlauf, Suchlauf/Report mit Team."""
from __future__ import annotations

import argparse
import csv
import multiprocessing
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

import scout
import wmscout.app as app_modul
import wmscout.web.api as api_modul
from tests.daten import BASIS, FakeAbruf, baue_ads
from tests.prozess_helfer import arbeiter
from tests.test_handy import Client
from tests.test_team_bearbeitung import (JETZT, NEUN, anmelden, anzeige_ids, bearbeitung, dublette_herstellen, ids_der_liste,
                                         starte)
from wmscout.bearbeitung import (KONTAKTIERT, OHNE_ZUORDNUNG, VERWAIST, BearbeitungsKonflikt, TeamSicht,
                                 ablauf_grenze, zustand)
from wmscout.bewertung.auswertung import bewerte_alle, dubletten_ids
from wmscout.datenbank import Datenbank
from wmscout.importer import Importer
from wmscout.team import TeamSpeicher, lade_team_sicht


@pytest.fixture
def team(db, tmp_path):
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.ids = {n: t.nutzer_anlegen(n, "sicher1234", "inhaber" if n == "Anna" else "mitarbeiter") for n in ("Anna", "Ben", "Carl")}
    return t


@pytest.fixture
def server(cfg, db, importiert):
    srv = starte(cfg, db)
    yield srv
    srv.shutdown()
    srv.server_close()


def mit_dora(team):
    team.ids["Dora"] = team.nutzer_anlegen("Dora", "sicher1234")
    return team.ids["Dora"]


def status_von(db, ad_id):
    return db.con.execute("SELECT status FROM anzeigen WHERE id=?", (ad_id,)).fetchone()[0]


# ======================================================================= H2: alle Status in Arbeit übernehmen
@pytest.mark.parametrize("status", ["verhandlung", "besichtigung"])
def test_db_verhandlung_und_besichtigung_uebernehmen_wie_kontaktiert(db, team, importiert, status):
    a, b = anzeige_ids(db, 2)
    ben, carl, anna = team.ids["Ben"], team.ids["Carl"], team.ids["Anna"]
    assert db.setze_status(a, status, nutzer_id=carl)
    r = bearbeitung(db, a)
    assert r[0] == carl and r[2] == carl and r[3]                                  # Bearbeiter und Kontakt eingetragen
    assert status_von(db, a) == status
    with pytest.raises(BearbeitungsKonflikt):                                      # ein Kollege kann es nicht mehr kontaktieren
        db.setze_status(a, "kontaktiert", text="x", nutzer_id=ben)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, status, nutzer_id=ben)
    assert status_von(db, a) == status and bearbeitung(db, a)[0] == carl
    # erster Kontakt bleibt, wenn derselbe Bearbeiter später noch einmal den Status wechselt
    erster = bearbeitung(db, a)[3]
    assert db.setze_status(a, "kontaktiert", nutzer_id=carl) and bearbeitung(db, a)[3] == erster
    # Inhaber ändert den Status eines Kollegen-Inserats, ohne es zu übernehmen
    assert db.setze_status(a, "verhandlung" if status == "besichtigung" else "besichtigung", nutzer_id=anna, inhaber=True)
    assert bearbeitung(db, a)[0] == carl and bearbeitung(db, a)[2] == carl
    # Inhaber auf freiem Inserat: übernimmt und trägt den Kontakt ein
    assert db.setze_status(b, status, nutzer_id=anna, inhaber=True)
    assert bearbeitung(db, b)[0] == anna and bearbeitung(db, b)[2] == anna


def test_db_verhandlung_beachtet_dubletten(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    assert db.uebernimm(a, team.ids["Ben"], NEUN)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(b, "verhandlung", nutzer_id=team.ids["Carl"], dubletten=[a])
    assert status_von(db, b) == "neu" and bearbeitung(db, b) is None


def test_http_carl_verhandlung_auf_freiem_inserat_dora_kontaktiert_409(server, team, db):
    mit_dora(team)
    carl, dora, anna = (anmelden(server, n) for n in ("Carl", "Dora", "Anna"))
    z, y = ids_der_liste(carl, "alle", n=2)
    assert carl("POST", "/api/status", {"id": z, "status": "verhandlung"})[0] == 200
    assert bearbeitung(db, z)[0] == team.ids["Carl"] and bearbeitung(db, z)[2] == team.ids["Carl"]
    s, antwort, _ = dora("POST", "/api/status", {"id": z, "status": "kontaktiert", "text": "Hallo Dora"})
    assert s == 409 and "Carl" in antwort["fehler"] and antwort["grund"] == "konflikt"
    assert antwort["team"]["zustand"] == "kontaktiert" and status_von(db, z) == "verhandlung"
    assert db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (z,)).fetchone()[0] is None
    assert dora("POST", "/api/status", {"id": z, "status": "besichtigung"})[0] == 409
    assert dora("POST", "/api/nachgefasst", {"id": z, "text": "x"})[0] == 409
    # derselbe Weg mit „besichtigung“ und Zuordnung in der Übersicht
    assert carl("POST", "/api/status", {"id": y, "status": "besichtigung"})[0] == 200
    assert dora("POST", "/api/status", {"id": y, "status": "kontaktiert", "text": "x"})[0] == 409
    t = dora("GET", "/api/team")[1]["bearbeitung"]
    assert t[z]["zustand"] == "kontaktiert" and t[z]["bearbeiter"]["name"] == "Carl" and t[y]["bearbeiter"]["name"] == "Carl"
    # Inhaber darf den Status ändern, ohne zu übernehmen
    assert anna("POST", "/api/status", {"id": z, "status": "gekauft"})[0] == 200 and bearbeitung(db, z)[0] == team.ids["Carl"]
    # Mitarbeiter ohne Halterschaft: gekauft/abgesagt wie bisher nur auf freien Inseraten
    x = ids_der_liste(carl, "alle", n=3)[2]
    assert dora("POST", "/api/bearbeitung/%s/uebernehmen" % x, {})[0] == 200
    assert carl("POST", "/api/status", {"id": x, "status": "uninteressant"})[0] == 409


# ======================================================================= H1: Besichtigung wie ein Kontakt
def test_http_besichtigung_anlegen_im_team(server, team, db):
    mit_dora(team)
    anna, ben, carl, dora = (anmelden(server, n) for n in ("Anna", "Ben", "Carl", "Dora"))
    x, y, z, w = ids_der_liste(ben, "alle", n=4)
    ci, bi = team.ids["Carl"], team.ids["Ben"]
    assert ben("POST", "/api/status", {"id": x, "status": "kontaktiert", "text": "Hallo Ben"})[0] == 200
    # Carl auf Bens Fahrzeug: 409, nichts angelegt, nichts geändert
    s, antwort, _ = carl("POST", "/api/besichtigung", {"anzeige_id": x})
    assert s == 409 and "Ben" in antwort["fehler"] and antwort["grund"] == "konflikt" and antwort["team"]["zustand"] == "kontaktiert"
    assert team.besichtigungen(offen=False, anzeige_id=x) == [] and status_von(db, x) == "kontaktiert" and bearbeitung(db, x)[0] == bi
    # Carl auf einem freien Fahrzeug: übernimmt, Status Besichtigung, Kontakt eingetragen – Dora kann es nicht noch einmal kontaktieren
    s, b, _ = carl("POST", "/api/besichtigung", {"anzeige_id": y, "termin": "2026-11-01T10:00"})
    assert s == 200 and b["zustaendig"]["id"] == ci
    assert status_von(db, y) == "besichtigung" and bearbeitung(db, y)[0] == ci and bearbeitung(db, y)[2] == ci
    s, antwort, _ = dora("POST", "/api/status", {"id": y, "status": "kontaktiert", "text": "Hallo Dora"})
    assert s == 409 and "Carl" in antwort["fehler"]
    assert dora("POST", "/api/besichtigung", {"anzeige_id": y})[0] == 409
    assert len(team.besichtigungen(offen=False, anzeige_id=y)) == 1
    # Inhaber weist die Besichtigung eines von Ben bearbeiteten Fahrzeugs Carl zu: Bearbeitung bleibt bei Ben
    s, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": ci, "termin": "2026-11-02T10:00"})
    assert s == 200 and b["zustaendig"]["id"] == ci and status_von(db, x) == "besichtigung"
    assert bearbeitung(db, x)[0] == bi and bearbeitung(db, x)[2] == bi
    # Mitarbeiter auf eigenem Fahrzeug weist einem Kollegen zu: Bearbeiter bleibt, Besichtiger ist Carl
    ben("POST", f"/api/bearbeitung/{z}/uebernehmen", {})
    s, b, _ = ben("POST", "/api/besichtigung", {"anzeige_id": z, "zustaendig_id": ci})
    assert s == 200 and b["zustaendig"]["id"] == ci and bearbeitung(db, z)[0] == bi and bearbeitung(db, z)[2] == bi
    # Mitarbeiter darf nicht erzwingen; unbekannter Besichtiger ändert nichts (400 vor jeder Änderung)
    assert carl("POST", "/api/besichtigung", {"anzeige_id": w, "erzwingen": True})[0] == 403
    s, antwort, _ = carl("POST", "/api/besichtigung", {"anzeige_id": w, "zustaendig_id": 9999})
    assert s == 400 and status_von(db, w) == "neu" and bearbeitung(db, w) is None


def test_http_besichtigung_auf_abgeschlossenem_inserat_eines_kollegen(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    x = ids_der_liste(ben, "alle", n=1)[0]
    ben("POST", f"/api/bearbeitung/{x}/uebernehmen", {})
    assert ben("POST", "/api/status", {"id": x, "status": "gekauft"})[0] == 403        # P1-15: „gekauft“ nur Inhaber/Abschluss
    assert ben("POST", "/api/status", {"id": x, "status": "abgesagt"})[0] == 200        # abgeschlossen, Ben hält das Inserat
    s, antwort, _ = carl("POST", "/api/besichtigung", {"anzeige_id": x})
    assert s == 409 and team.besichtigungen(offen=False, anzeige_id=x) == [] and status_von(db, x) == "abgesagt"
    assert anna("POST", "/api/besichtigung", {"anzeige_id": x})[0] == 200               # Inhaber darf, Status bleibt
    assert status_von(db, x) == "abgesagt" and bearbeitung(db, x)[0] == team.ids["Ben"]


def test_http_verhandlung_und_besichtigung_beachten_dubletten(server, team, db):
    a, b = dublette_herstellen(db)
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    assert ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    for status in ("verhandlung", "besichtigung", "kontaktiert"):
        s, antwort, _ = carl("POST", "/api/status", {"id": b, "status": status, "text": "x"})
        assert s == 409 and f"Dublette {a}" in antwort["fehler"] and antwort["team"]["dublette_von"]["id"] == a, status
    assert bearbeitung(db, b) is None and status_von(db, b) == "neu"
    assert ben("POST", "/api/status", {"id": b, "status": "verhandlung"})[0] == 200                  # die eigene Gruppe darf


def test_http_besichtigung_dublette_blockiert(server, team, db):
    a, b = dublette_herstellen(db)
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    assert ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    s, antwort, _ = carl("POST", "/api/besichtigung", {"anzeige_id": b})
    assert s == 409 and f"Dublette {a}" in antwort["fehler"] and bearbeitung(db, b) is None and status_von(db, b) == "neu"


def test_http_besichtigung_abschluss_im_team(server, team, db, monkeypatch):
    mit_dora(team)
    anna, ben, carl, dora = (anmelden(server, n) for n in ("Anna", "Ben", "Carl", "Dora"))
    x, y = ids_der_liste(ben, "alle", n=2)
    ci, bi = team.ids["Carl"], team.ids["Ben"]
    ben("POST", "/api/status", {"id": x, "status": "kontaktiert", "text": "Hallo Ben"})
    bid = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": ci})[1]["id"]
    # Dora ist weder Inhaberin noch Besichtigerin
    assert dora("POST", f"/api/besichtigung/{bid}/abschluss", {"entscheidung": "abgelehnt"})[0] == 403
    assert status_von(db, x) == "besichtigung"
    # der zugewiesene Besichtiger schließt ab: Inserat-Status folgt, die Bearbeitung bleibt bei Ben
    s, antwort, _ = carl("POST", f"/api/besichtigung/{bid}/abschluss", {"entscheidung": "abgelehnt"})
    assert s == 200 and status_von(db, x) == "abgesagt" and bearbeitung(db, x)[0] == bi
    fertig = team.besichtigung(bid)
    assert fertig["status"] == "abgeschlossen" and fertig["protokoll"]["entscheidung"] == "abgelehnt" and fertig["protokoll"]["abgeschlossen_von"] == "Carl"
    # Fehler im Status → 409 und das Protokoll bleibt unberührt (nicht halb gespeichert): Dublette y von Dora kontaktiert
    b2 = carl("POST", "/api/besichtigung", {"anzeige_id": y})[1]["id"]
    assert bearbeitung(db, y)[0] == ci
    db.con.execute("INSERT INTO bearbeitung(anzeige_id, bearbeiter_id, uebernommen_am, kontaktiert_von, kontaktiert_am) VALUES(?,?,?,?,?)",
                   ("duplikat-stand", team.ids["Dora"], NEUN, team.ids["Dora"], NEUN))
    db.con.commit()
    monkeypatch.setattr(api_modul.Kontext, "dubletten_von", lambda self, i: ["duplikat-stand"] if i == y else [])
    s, antwort, _ = carl("POST", f"/api/besichtigung/{b2}/abschluss", {"entscheidung": "offen"})
    monkeypatch.undo()
    assert s == 409 and "Dora" in antwort["fehler"]
    assert team.besichtigung(b2)["status"] == "geplant" and team.besichtigung(b2)["protokoll"] is None and status_von(db, y) == "besichtigung"


# ======================================================================= M1: Zuweisen/Erzwingen auf Dubletten
def md_dublette(db, quelle_id):
    """Fügt eine mobile.de-Dublette (id „md-…“) zu einem Kleinanzeigen-Inserat hinzu."""
    spalten = [r[1] for r in db.con.execute("PRAGMA table_info(anzeigen)") if r[1] not in ("id", "quelle", "url")]
    db.con.execute(f"INSERT INTO anzeigen (id, quelle, url, {','.join(spalten)}) SELECT 'md-39000000', 'mobile.de', "
                   f"'https://suchen.mobile.de/fahrzeuge/details.html?id=39000000', {','.join(spalten)} FROM anzeigen WHERE id=?", (quelle_id,))
    db.con.commit()
    return "md-39000000"


def echte_dublette_basis(db):
    return db.con.execute("SELECT id FROM anzeigen WHERE marke IS NOT NULL AND ez_jahr IS NOT NULL AND km IS NOT NULL AND ort IS NOT NULL "
                          "AND preis IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]


def test_http_erzwingen_auf_dublette_nimmt_reservierung_der_gruppe_mit(server, team, db):
    src = echte_dublette_basis(db)
    md = md_dublette(db, src)
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    assert ben("POST", f"/api/bearbeitung/{src}/uebernehmen", {})[0] == 200
    assert carl("POST", f"/api/bearbeitung/{md}/uebernehmen", {})[0] == 409
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{md}/uebernehmen", {"erzwingen": True})
    assert s == 200 and antwort["team"]["mein"] and antwort["team"]["dublette_von"]["mein"]
    # Bens Reservierung der Dublette ist auf Anna übergegangen – keine gegenseitige Blockade
    assert bearbeitung(db, src)[0] == team.ids["Anna"] and bearbeitung(db, md)[0] == team.ids["Anna"]
    assert anna("POST", "/api/status", {"id": src, "status": "kontaktiert", "text": "Anna"})[0] == 200
    s, antwort, _ = ben("POST", "/api/status", {"id": src, "status": "kontaktiert", "text": "Ben"})
    assert s == 409 and "Anna" in antwort["fehler"]


def test_http_zuweisen_auf_dublette_nimmt_reservierung_der_gruppe_mit(server, team, db):
    src = echte_dublette_basis(db)
    md = md_dublette(db, src)
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    ben("POST", f"/api/bearbeitung/{src}/uebernehmen", {})
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{md}/zuweisen", {"nutzer_id": team.ids["Carl"]})
    assert s == 200 and antwort["team"]["bearbeiter"]["name"] == "Carl" and antwort["team"]["dublette_von"]["mein"] is False
    assert bearbeitung(db, src)[0] == team.ids["Carl"] and bearbeitung(db, md)[0] == team.ids["Carl"]
    assert carl("POST", "/api/status", {"id": src, "status": "kontaktiert", "text": "Carl"})[0] == 200
    assert ben("POST", f"/api/bearbeitung/{src}/uebernehmen", {})[0] == 409


def test_http_zuweisen_und_erzwingen_scheitern_an_kontaktierter_dublette_eines_anderen(server, team, db):
    a, b = dublette_herstellen(db)
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Ben"})[0] == 200
    vorher = (bearbeitung(db, a), bearbeitung(db, b))
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Carl"]})
    assert s == 409 and antwort["grund"] == "konflikt" and f"Dublette {a}" in antwort["fehler"] and "Ben" in antwort["fehler"]
    assert "zuerst dort zuweisen" in antwort["fehler"]
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{b}/uebernehmen", {"erzwingen": True})
    assert s == 409 and "zuerst dort zuweisen" in antwort["fehler"]
    assert anna("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x", "erzwingen": True})[0] == 409
    assert anna("POST", "/api/nachgefasst", {"id": b, "text": "x", "erzwingen": True})[0] == 409
    assert (bearbeitung(db, a), bearbeitung(db, b)) == vorher and status_von(db, b) == "neu"            # nichts geändert
    # Weg: erst die kontaktierte Dublette zuweisen, dann die andere
    assert anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 200
    assert bearbeitung(db, a)[0] == team.ids["Carl"] and bearbeitung(db, a)[2] == team.ids["Ben"]       # Kontakt bleibt Ben
    assert anna("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 200
    assert carl("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "Carl"})[0] == 200


def test_db_weise_zu_und_erzwingen_mit_dubletten(db, team, importiert):
    a, b, c = anzeige_ids(db, 3)
    ben, carl, anna = team.ids["Ben"], team.ids["Carl"], team.ids["Anna"]
    db.uebernimm(a, ben, NEUN)
    db.uebernimm(c, carl, NEUN)
    db.weise_zu(b, anna, NEUN, dubletten=[a, c], grenze="")
    assert [bearbeitung(db, i)[0] for i in (a, b, c)] == [anna, anna, anna]
    # abgelaufene Reservierungen und deaktivierte Bearbeiter wandern nicht mit
    d, e = anzeige_ids(db, 5)[3:]
    db.uebernimm(d, ben, "2026-10-01T09:00:00")
    db.uebernimm(e, carl, NEUN)
    team.nutzer_aktiv_setzen("Carl", False)
    db.weise_zu(a, ben, "2026-10-14T10:00:00", dubletten=[d, e], grenze="2026-10-12T00:00:00")
    assert bearbeitung(db, d)[0] == ben and bearbeitung(db, d)[1] == "2026-10-01T09:00:00"            # Ben selbst: unverändert
    assert bearbeitung(db, e)[0] == carl                                                              # deaktiviert: unberührt
    # Konflikt: nichts geändert, Ausnahme nennt die Dublette
    db.setze_status(b, "kontaktiert", nutzer_id=anna)
    vorher = [bearbeitung(db, i) for i in (a, b)]
    with pytest.raises(BearbeitungsKonflikt) as e_:
        db.weise_zu(a, ben, NEUN, dubletten=[b])
    assert e_.value.anzeige_id == b and [bearbeitung(db, i) for i in (a, b)] == vorher
    assert db.uebernimm(a, ben, NEUN, dubletten=[b], erzwingen=True) is False and [bearbeitung(db, i) for i in (a, b)] == vorher


# ======================================================================= M2: verwaiste Inserate
def test_zustand_verwaist():
    aktiv = frozenset({1, 2})
    k = {"bearbeiter_id": 9, "uebernommen_am": NEUN, "kontaktiert_von": 9, "kontaktiert_am": NEUN, "status": "kontaktiert"}
    assert zustand(k, JETZT, 2, aktiv) == VERWAIST
    assert zustand({**k, "status": "verhandlung"}, JETZT, 2, aktiv) == VERWAIST and zustand({**k, "bearbeiter_id": None}, JETZT, 2, aktiv) == VERWAIST
    assert zustand({**k, "bearbeiter_id": 1}, JETZT, 2, aktiv) == KONTAKTIERT                              # neu zugewiesen: gehalten
    assert zustand({**k, "status": "gekauft"}, JETZT, 2, aktiv) == KONTAKTIERT                             # abgeschlossen: kein Fall für die Arbeit
    assert zustand({**k, "kontaktiert_von": None}, JETZT, 2, aktiv) == OHNE_ZUORDNUNG                      # nie kontaktiert: wie bisher
    nutzer = [{"id": i, "name": n, "rolle": "mitarbeiter", "aktiv": 1} for i, n in ((1, "Anna"), (2, "Ben"))] + \
             [{"id": 9, "name": "Dora", "rolle": "mitarbeiter", "aktiv": 0}]
    sicht = TeamSicht(nutzer, {"A": {"anzeige_id": "A", **{x: k[x] for x in k if x != "status"}}}, JETZT, 2, {"id": 2, "rolle": "mitarbeiter"})
    o = sicht.objekt_id("A", "kontaktiert")
    assert o["zustand"] == VERWAIST and o["bearbeiter"] is None and o["kontaktiert_von"]["name"] == "Dora" and o["kontaktiert_von"]["aktiv"] is False
    assert o["darf"]["uebernehmen"] and TeamSicht.ist_frei(o) and not TeamSicht.ist_triviale_sicht(o)


def test_http_verwaist_zaehler_und_uebernahme(server, team, db):
    mit_dora(team)
    anna, ben, dora = (anmelden(server, n) for n in ("Anna", "Ben", "Dora"))
    a, b = ids_der_liste(dora, "alle", n=2)
    assert dora("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Dora"})[0] == 200
    assert dora("POST", "/api/status", {"id": b, "status": "verhandlung"})[0] == 200
    t = anna("GET", "/api/team")[1]
    assert t["verwaist"] == 0 and {z["name"]: z["in_arbeit"] for z in t["zaehler"]}["Dora"] == 2
    team.nutzer_aktiv_setzen("Dora", False)
    for wer in (anna, ben):
        t = wer("GET", "/api/team")[1]
        assert t["verwaist"] == 2 and t["ohne_zuordnung"] == 0                                         # fällt in keinen Zähler mehr heraus
        assert t["bearbeitung"][a]["zustand"] == "verwaist" and t["bearbeitung"][a]["kontaktiert_von"]["name"] == "Dora"
        assert t["bearbeitung"][a]["darf"]["uebernehmen"] is True
    assert {z["name"] for z in anna("GET", "/api/team")[1]["zaehler"]} == {"Anna", "Ben", "Carl"}                    # Dora ist gesperrt
    assert {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle&wer=frei")[1]} >= {a, b}            # übernehmbar
    # Mitarbeiter übernimmt per Übernehmen; der Kontakt (Dora) bleibt als Tatsache stehen
    s, antwort, _ = ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert s == 200 and antwort["team"]["zustand"] == "kontaktiert" and antwort["team"]["mein"]
    assert antwort["team"]["kontaktiert_von"]["name"] == "Dora" and bearbeitung(db, a)[0] == team.ids["Ben"]
    # Inhaber per Zuweisen
    assert anna("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Anna"]})[0] == 200
    t = anna("GET", "/api/team")[1]
    assert t["verwaist"] == 0 and {z["name"]: z["in_arbeit"] for z in t["zaehler"]} == {"Anna": 1, "Ben": 1, "Carl": 0}


def test_zaehler_inaktiver_bearbeiter_nur_inserate_in_arbeit(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    db.setze_status(a, "kontaktiert", nutzer_id=team.ids["Carl"])
    db.setze_status(b, "kontaktiert", nutzer_id=team.ids["Carl"])
    db.setze_status(b, "gekauft", nutzer_id=team.ids["Carl"])
    team.nutzer_aktiv_setzen("Carl", False)
    z = db.team_zaehler(JETZT, ablauf_grenze(JETZT, 2), aktiv_tage=100000)
    assert z["verwaist"] == 1 and z["ohne_zuordnung"] == 0


# ======================================================================= M3: Dubletten ohne Bewertung
def test_dubletten_ids_gleich_wie_in_der_bewertung(cfg, db, importiert):
    assert dubletten_ids(db) == {}
    a, b = dublette_herstellen(db, 2)
    md = md_dublette(db, a)
    erwartet = {z["a"]["id"]: z["dubletten_ids"] for z in bewerte_alle(cfg, db, BASIS) if z["dubletten_ids"]}
    assert dubletten_ids(db) == erwartet and set(erwartet) == {a, b, md} and erwartet[a] == sorted([b, md])


def test_http_schreibzugriffe_im_team_bewerten_nicht_alles(server, team, db, monkeypatch):
    """/api/status, /nachgefasst, /uebernehmen, /zuweisen brauchen nur die Dubletten, nicht `bewerte_alle` (QA M3: 17 s für 10 Aufrufe)."""
    a, b = dublette_herstellen(db)
    ben, carl, anna = (anmelden(server, n) for n in ("Ben", "Carl", "Anna"))
    ids = ids_der_liste(ben, "alle", n=6)
    assert ben("POST", "/api/notiz", {"id": ids[0], "notiz": "leert den Zwischenspeicher der Bewertung"})[0] == 200
    aufrufe = []
    original = api_modul.bewerte_alle
    monkeypatch.setattr(api_modul, "bewerte_alle", lambda *x, **y: aufrufe.append(1) or original(*x, **y))
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "x"})[0] == 200
    assert carl("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"})[0] == 409            # Dublette erkannt
    assert ben("POST", "/api/nachgefasst", {"id": a, "text": "x"})[0] == 200
    assert ben("POST", f"/api/bearbeitung/{ids[3]}/uebernehmen", {})[0] == 200
    assert anna("POST", f"/api/bearbeitung/{ids[4]}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 200
    assert anna("POST", "/api/status", {"id": ids[5], "status": "verhandlung"})[0] == 200
    assert aufrufe == []


def test_dubletten_zwischenspeicher_erkennt_aenderungen_anderer_verbindungen(server, team, db, cfg):
    """Der Suchlauf schreibt über eine eigene Verbindung: neue Dubletten wirken sofort (PRAGMA data_version), ohne `veraendert()`."""
    a, b = anzeige_ids(db, 2)
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "x"})[0] == 200        # füllt den Zwischenspeicher: keine Dublette
    assert carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 200
    carl("POST", f"/api/bearbeitung/{b}/abgeben", {})
    suchlauf = Datenbank(cfg["ausgabe"]["datenbank"])                                                      # „Suchlauf“
    erste = suchlauf.con.execute("SELECT titel, marke, ez_jahr, km, ort, preis FROM anzeigen WHERE id=?", (a,)).fetchone()
    suchlauf.con.execute("UPDATE anzeigen SET titel=?, marke=?, ez_jahr=?, km=?, ort=?, preis=? WHERE id=?", (*tuple(erste), b))
    suchlauf.con.commit()
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})
    assert s == 409 and f"Dublette {a}" in antwort["fehler"]


def test_kontext_dubletten_zwischenspeicher_veraendert_verwirft_nicht_import_schon(cfg, db, importiert, tmp_path):
    suchlauf = app_modul.Suchlauf(cfg, cfg["ausgabe"]["datenbank"], BASIS)
    k = api_modul.Kontext(cfg, db, BASIS, "token", suchlauf, tmp_path / "fotos")
    a, b = anzeige_ids(db, 2)
    assert k.dubletten_von(a) == []
    erste = db.con.execute("SELECT titel, marke, ez_jahr, km, ort, preis FROM anzeigen WHERE id=?", (a,)).fetchone()
    db.con.execute("UPDATE anzeigen SET titel=?, marke=?, ez_jahr=?, km=?, ort=?, preis=? WHERE id=?", (*tuple(erste), b))
    db.con.commit()
    k.veraendert()
    assert k.dubletten_von(a) == []                       # Statuswechsel ändern keine Gruppen → Zwischenspeicher bleibt (schnell)
    k.dubletten_verwerfen()                               # Seitenimport über diese Verbindung
    assert k.dubletten_von(a) == [b] and k.dubletten_von(b) == [a]


# ======================================================================= M5: Datenschutz der Zähler, grund-Feld, N2
def test_http_zaehler_nur_eigene_zeile_ausser_inhaber(server, team, db):
    mit_dora(team)
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a, b = ids_der_liste(anna, "alle", n=2)
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    carl("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"})
    for wer, name in ((ben, "Ben"), (carl, "Carl")):
        s, roh, r = wer("GET", "/api/team")
        assert [z["name"] for z in roh["zaehler"]] == [name] and roh["zaehler"][0]["nutzer_id"] == team.ids[name]
        andere = {"Ben", "Carl"} - {name}
        assert all(z["nutzer_id"] == team.ids[name] for z in roh["zaehler"]) and andere
        # Kürzel an den Fahrzeugen sind für alle sichtbar (gegen Doppelkontakt)
        assert roh["bearbeitung"][a]["bearbeiter"]["name"] == "Ben" and roh["bearbeitung"][b]["bearbeiter"]["name"] == "Carl"
        assert roh["ohne_zuordnung"] == 0 and "verwaist" in roh
    assert [z["name"] for z in anna("GET", "/api/team")[1]["zaehler"]] == ["Anna", "Ben", "Carl", "Dora"]


def test_http_grund_feld_unterscheidet_csrf_recht_und_konflikt(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a = ids_der_liste(anna, "alle", n=1)[0]
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {}, token=False)
    assert s == 403 and antwort["grund"] == "csrf"
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": True})
    assert s == 403 and antwort["grund"] == "recht"
    assert carl("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": team.ids["Carl"]})[1]["grund"] == "recht"
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert carl("POST", f"/api/bearbeitung/{a}/abgeben", {})[1]["grund"] == "recht"
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert s == 409 and antwort["grund"] == "konflikt" and antwort["fehler"] and "team" in antwort                     # rückwärtskompatibel
    s, antwort, _ = Client(server.server_address[1], host="fremd.example")("GET", "/api/ich")
    assert s == 403 and antwort["grund"] == "zugriff"
    s, antwort, _ = Client(server.server_address[1])("GET", "/api/team")
    assert s == 401 and "grund" not in antwort and antwort["fehler"]
    assert carl("POST", "/api/status", {"id": a, "status": "unbekannt"})[1].get("grund") is None             # 400: kein Grund nötig


@pytest.mark.parametrize("wert", ["false", "ja", 1, "true", 0, None, [True]])
def test_http_erzwingen_nur_mit_json_true(server, team, db, wert):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a = ids_der_liste(anna, "alle", n=1)[0]
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    # Mitarbeiter: kein 403 („false“ ist kein Erzwingen), sondern der normale Konflikt
    assert carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": wert})[0] == 409
    assert carl("POST", "/api/status", {"id": a, "status": "kontaktiert", "erzwingen": wert})[0] == 409
    assert carl("POST", "/api/nachgefasst", {"id": a, "text": "x", "erzwingen": wert})[0] == 409
    # Inhaber: ebenso kein Erzwingen
    assert anna("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": wert})[0] == 409
    assert anna("POST", "/api/status", {"id": a, "status": "kontaktiert", "erzwingen": wert})[0] == 409
    assert bearbeitung(db, a)[0] == team.ids["Ben"]
    assert anna("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": True})[0] == 200


# ======================================================================= N1: Erzwingen protokollieren
def test_http_erzwingen_ueber_status_und_nachgefasst_wird_protokolliert(server, team, db, caplog):
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    a, b = ids_der_liste(anna, "alle", n=2)
    for ad_id in (a, b):
        ben("POST", f"/api/bearbeitung/{ad_id}/uebernehmen", {})
    with caplog.at_level("INFO", logger="scout"):
        assert anna("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Chef", "erzwingen": True})[0] == 200
        assert anna("POST", "/api/nachgefasst", {"id": b, "text": "Nachricht", "erzwingen": True})[0] == 200
    texte = [r.getMessage() for r in caplog.records if "Erzwungene Übernahme" in r.getMessage()]
    assert len(texte) == 2, texte
    for ad_id in (a, b):
        assert any(ad_id in t and "von Ben" in t and "durch Anna" in t for t in texte), texte
    caplog.clear()
    with caplog.at_level("INFO", logger="scout"):                                   # nichts zu erzwingen → kein Eintrag
        c = ids_der_liste(anna, "alle", n=3)[2]
        assert anna("POST", "/api/status", {"id": c, "status": "kontaktiert", "text": "x", "erzwingen": True})[0] == 200
    assert not [r for r in caplog.records if "Erzwungene Übernahme" in r.getMessage()]


# ======================================================================= N3: NULL-Zeitpunkt wie in Python
def test_db_uebernommen_am_null_wie_in_der_python_logik(db, team, importiert):
    a = anzeige_ids(db, 1)[0]
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    aktiv = frozenset(team.ids.values())
    db.con.execute("INSERT INTO bearbeitung(anzeige_id, bearbeiter_id, uebernommen_am) VALUES(?,?,NULL)", (a, ben))
    db.con.commit()
    zeile = db.bearbeitung_aktiv()[a]
    from wmscout.bearbeitung import halter
    for grenze, gehalten in (("", True), ("2026-10-12T00:00:00", False)):
        assert (halter(zeile, grenze, aktiv) == ben) is gehalten                                  # Python: None zählt als ""
        assert (db._fremde_halter([a], carl, grenze) is not None) is gehalten                     # SQL muss dasselbe sagen
        db.con.execute("UPDATE bearbeitung SET bearbeiter_id=? WHERE anzeige_id=?", (ben, a))
        assert db.uebernimm(a, carl, NEUN, grenze) is (not gehalten)                              # und die Übernahme ebenso
        db.con.execute("UPDATE bearbeitung SET bearbeiter_id=?, uebernommen_am=NULL WHERE anzeige_id=?", (ben, a))
        db.con.commit()
    z = db.team_zaehler(JETZT, "2026-10-12T00:00:00", aktiv_tage=100000)
    assert {n["name"]: n["reserviert"] for n in z["nutzer"]}["Ben"] == 0                           # abgelaufen → nicht reserviert
    z = db.team_zaehler(JETZT, "", aktiv_tage=100000)
    assert {n["name"]: n["reserviert"] for n in z["nutzer"]}["Ben"] == 1                            # läuft nie ab → reserviert
    assert db.status_von(a) == "neu"


# ======================================================================= N4: gesperrte Datenbank
def halte_sperre(pfad):
    sperr = sqlite3.connect(pfad, timeout=0.1)
    sperr.execute("BEGIN IMMEDIATE")
    return sperr


def test_db_schreibzugriff_auf_gesperrter_datenbank_laesst_keine_transaktion_offen(cfg, db, team, importiert):
    pfad = cfg["ausgabe"]["datenbank"]
    kurz = Datenbank(pfad, timeout=0.1)
    a, b = anzeige_ids(db, 2)
    ben = team.ids["Ben"]
    db.uebernimm(a, ben, NEUN)
    sperr = halte_sperre(pfad)
    start = time.monotonic()
    try:
        for schreiben in (lambda: kurz.gib_ab(a, ben), lambda: kurz.setze_notiz(a, "x"), lambda: kurz.weise_zu(a, ben, NEUN),
                          lambda: kurz.setze_status(a, "uninteressant"), lambda: kurz.nachgefasst(a, "x"),
                          lambda: kurz.setze_status(a, "kontaktiert", nutzer_id=ben), lambda: kurz.uebernimm(b, ben, NEUN),
                          lambda: kurz.nachgefasst(a, "x", nutzer_id=ben)):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                schreiben()
            assert not kurz.con.in_transaction
        assert time.monotonic() - start < 4, "der Timeout-Parameter wirkt nicht (Standard wären 5 s je Versuch)"
    finally:
        sperr.rollback()
        sperr.close()
    # nach Freigabe geht alles wieder, und eine dritte Verbindung kann schreiben (keine Sperre blieb zurück)
    assert kurz.gib_ab(a, ben) and kurz.setze_notiz(a, "ok")
    dritte = sqlite3.connect(pfad, timeout=0.1)
    dritte.execute("UPDATE anzeigen SET notiz='dritte' WHERE id=?", (b,))
    dritte.commit()
    dritte.close()


def test_http_gesperrte_datenbank_ergibt_503_und_laesst_nichts_offen(cfg, db, importiert, team):
    mit_dora(team)
    pfad = cfg["ausgabe"]["datenbank"]
    kurz = Datenbank(pfad, timeout=0.1)
    srv = starte(cfg, kurz)
    try:
        ben, anna, carl = anmelden(srv, "Ben"), anmelden(srv, "Anna"), anmelden(srv, "Carl")
        a, b, c, d = ids_der_liste(ben, "alle", n=4)
        ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
        bid = ben("POST", "/api/besichtigung", {"anzeige_id": d})[1]["id"]
        anfragen = [("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"}, ben),
                    ("POST", "/api/status", {"id": c, "status": "uninteressant"}, ben),
                    ("POST", f"/api/bearbeitung/{c}/uebernehmen", {}, ben),
                    ("POST", f"/api/bearbeitung/{a}/abgeben", {}, ben),
                    ("POST", "/api/notiz", {"id": c, "notiz": "n"}, ben),
                    ("POST", f"/api/bearbeitung/{c}/zuweisen", {"nutzer_id": team.ids["Carl"]}, anna),
                    ("POST", "/api/nachgefasst", {"id": b, "text": "x"}, ben),
                    ("POST", "/api/besichtigung", {"anzeige_id": c}, ben),
                    # Schreibzugriffe des Team-Speichers (kein eigener Rollback): die Anfrage-Behandlung räumt auf
                    ("POST", f"/api/besichtigung/{bid}/planen", {"termin": "2026-11-05T10:00"}, ben),
                    ("POST", f"/api/besichtigung/{bid}/speichern", {"daten": {}}, ben),
                    ("POST", "/api/logout", {}, carl)]
        sperr = halte_sperre(pfad)
        try:
            for methode, url, daten, wer in anfragen:
                s, antwort, r = wer(methode, url, daten)
                assert s == 503, (url, s, antwort)
                assert antwort["fehler"] == "Datenbank kurz belegt – bitte erneut versuchen" and antwort["grund"] == "belegt"
                assert r.getheader("Retry-After") and not kurz.con.in_transaction, url
            assert ben("GET", "/api/team")[0] == 200                                                   # Lesen geht weiter
        finally:
            sperr.rollback()
            sperr.close()
        # nichts wurde halb geschrieben, und nach Freigabe funktionieren dieselben Anfragen
        assert status_von(db, b) == "neu" and bearbeitung(db, b) is None and bearbeitung(db, a)[0] == team.ids["Ben"]
        for methode, url, daten, wer in anfragen:
            assert wer(methode, url, daten)[0] in (200, 409), url
        dritte = sqlite3.connect(pfad, timeout=0.1)
        dritte.execute("UPDATE anzeigen SET notiz='dritte' WHERE id=?", (a,))
        dritte.commit()
        dritte.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_fehler_mitten_in_der_anfrage_rollt_zurueck(server, team, db, monkeypatch):
    ben = anmelden(server, "Ben")
    a = ids_der_liste(ben, "alle", n=1)[0]
    original = Datenbank._trage_kontakt_ein

    def kaputt(self, *args):
        original(self, *args)
        raise RuntimeError("Absturz nach dem Eintrag")
    monkeypatch.setattr(Datenbank, "_trage_kontakt_ein", kaputt)
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "x"})[0] == 500
    assert not db.con.in_transaction and bearbeitung(db, a) is None and status_von(db, a) == "neu"
    monkeypatch.undo()
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "x"})[0] == 200


# ======================================================================= N6: scout.py status --nutzer
def status_befehl(cfg, db, ad_id, status, nutzer=None):
    scout.cmd_status(cfg, db, argparse.Namespace(id=ad_id, status=status, notiz=None, nutzer=nutzer))


def test_kommandozeile_status_mit_und_ohne_nutzer(cfg, db, team, importiert, capsys):
    a, b, c = anzeige_ids(db, 3)
    status_befehl(cfg, db, a, "kontaktiert")                                                           # wie bisher: ohne Eintrag
    assert status_von(db, a) == "kontaktiert" and bearbeitung(db, a) is None
    assert lade_team_sicht(db, 2).objekt_id(a, "kontaktiert")["zustand"] == OHNE_ZUORDNUNG
    status_befehl(cfg, db, b, "verhandlung", nutzer="Ben")
    assert status_von(db, b) == "verhandlung" and bearbeitung(db, b)[0] == team.ids["Ben"] and bearbeitung(db, b)[2] == team.ids["Ben"]
    assert "gespeichert" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:                                                               # Kollege hält es
        status_befehl(cfg, db, b, "kontaktiert", nutzer="Carl")
    assert "Ben" in str(e.value) and bearbeitung(db, b)[0] == team.ids["Ben"]
    status_befehl(cfg, db, b, "gekauft", nutzer="Anna")                                                # Inhaber darf
    assert status_von(db, b) == "gekauft" and bearbeitung(db, b)[0] == team.ids["Ben"]
    with pytest.raises(SystemExit, match="nicht gefunden"):
        status_befehl(cfg, db, c, "kontaktiert", nutzer="Niemand")
    assert status_von(db, c) == "neu"


def test_kommandozeile_status_hilfe_nennt_ohne_zuordnung():
    r = subprocess.run([sys.executable, str(BASIS / "scout.py"), "status", "--help"], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "--nutzer" in r.stdout and "ohne Zuordnung" in " ".join(r.stdout.split())


# ======================================================================= Wettlauf über echte Prozesse
def test_wettlauf_zwei_prozesse_genau_ein_gewinner(cfg, db, team, importiert):
    """Zwei Python-Prozesse (spawn) gegen dieselbe Datenbankdatei: je Runde gewinnt genau einer (BEGIN IMMEDIATE trägt prozessübergreifend)."""
    ids = anzeige_ids(db, 20)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    plan = {ben: [], carl: []}
    runden = []
    for a in ids[:4]:
        runden.append(("u", a))
        for n in plan:
            plan[n].append(("u", a, ()))
    for a in ids[4:7]:
        runden.append(("k", a))
        for n in plan:
            plan[n].append(("k", a, ()))
    for a in ids[7:9]:
        runden.append(("v", a))
        for n in plan:
            plan[n].append(("v", a, ()))
    for g in ([ids[9], ids[10]], [ids[11], ids[12]]):                            # Dubletten gespiegelt: jeder nimmt eine andere
        runden.append(("dub", tuple(g)))
        plan[ben].append(("u", g[0], (g[1],)))
        plan[carl].append(("u", g[1], (g[0],)))
    assert len(runden) == 11
    ctx = multiprocessing.get_context("spawn")
    barriere, q = ctx.Barrier(2), ctx.Queue()
    prozesse = [ctx.Process(target=arbeiter, args=(cfg["ausgabe"]["datenbank"], n, plan[n], barriere, q)) for n in plan]
    for p in prozesse:
        p.start()
    try:
        ergebnisse = dict(q.get(timeout=240) for _ in prozesse)
    finally:
        for p in prozesse:
            p.join(timeout=60)
            if p.is_alive():
                p.terminate()
    for i, runde in enumerate(runden):
        r = {n: ergebnisse[n][i][0] for n in plan}
        assert not any(isinstance(x, str) and x.startswith("FEHLER") for x in r.values()), (runde, r)
        assert not any(ergebnisse[n][i][1] for n in plan), "offene Transaktion"
        gewinner = [n for n, x in r.items() if x is True]
        if runde[0] == "dub":
            assert len(gewinner) == 1, (runde, r)
            n_zeilen = db.con.execute("SELECT COUNT(*) FROM bearbeitung WHERE anzeige_id IN (?,?)", runde[1]).fetchone()[0]
            assert n_zeilen == 1, runde
        else:
            verlierer = [x for n, x in r.items() if n not in gewinner]
            assert len(gewinner) == 1 and verlierer == [False if runde[0] == "u" else "konflikt"], (runde, r)
            zeile = bearbeitung(db, runde[1])
            assert zeile[0] == gewinner[0]
            if runde[0] in ("k", "v"):
                assert zeile[2] == gewinner[0]
            if runde[0] == "k":
                assert db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (runde[1],)).fetchone()[0] == f"T{gewinner[0]}"


# ======================================================================= Suchlauf und Report mit Team
def lese_csv(ordner):
    with open(Path(ordner) / "anzeigen_bewertet.csv", encoding="utf-8-sig", newline="") as f:
        zeilen = list(csv.reader(f, delimiter=";"))
    return zeilen[0], {z[0]: z for z in zeilen[1:]}


def test_suchlauf_und_report_schreiben_team_spalten(cfg, db, team, importiert, monkeypatch):
    a, b = anzeige_ids(db, 2)
    db.setze_status(a, "kontaktiert", text="x", nutzer_id=team.ids["Ben"])
    db.uebernimm(b, team.ids["Carl"], datetime.now().isoformat(timespec="seconds"))
    cfg["email"] = {**(cfg.get("email") or {}), "aktiv": False}

    class Fake(Importer):
        def __init__(self, c, d):
            super().__init__(c, d, abruf=FakeAbruf(baue_ads()))
    monkeypatch.setattr(app_modul, "Importer", Fake)
    # Suchlauf._lauf (eigene Verbindung) → CSV
    lauf = app_modul.Suchlauf(cfg, cfg["ausgabe"]["datenbank"], BASIS)
    lauf.starte()
    lauf.thread.join(180)
    assert lauf.stand["fehler"] is None and not lauf.stand["laeuft"], lauf.stand
    kopf, zeilen = lese_csv(cfg["ausgabe"]["ordner"])
    assert kopf[-3:] == ["Bearbeiter", "Übernommen am", "Kontaktiert von"]
    assert zeilen[a][-3] == "Ben" and zeilen[a][-2].startswith("20") and zeilen[a][-1] == "Ben"
    assert zeilen[b][-3] == "Carl" and zeilen[b][-1] == ""
    assert all(z[-3:] == ["", "", ""] for i, z in zeilen.items() if i not in (a, b))
    # scout.py report (Kommandozeile)
    Path(cfg["ausgabe"]["ordner"], "anzeigen_bewertet.csv").unlink()
    scout.cmd_report(cfg, db, argparse.Namespace())
    kopf, zeilen = lese_csv(cfg["ausgabe"]["ordner"])
    assert zeilen[a][-3] == "Ben" and zeilen[a][-1] == "Ben" and zeilen[b][-3] == "Carl"
    # ohne Team (alle Nutzer gesperrt): Spalten leer
    for n in ("Anna", "Ben", "Carl"):
        team.nutzer_aktiv_setzen(n, False)
    scout.cmd_report(cfg, db, argparse.Namespace())
    _, zeilen = lese_csv(cfg["ausgabe"]["ordner"])
    assert all(z[-3:] == ["", "", ""] for z in zeilen.values())
