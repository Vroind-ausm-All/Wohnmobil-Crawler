"""Team-Übersicht (T1): wer bearbeitet welches Inserat? Reine Regeln, Datenbank (auch nebenläufig), Altbestände, HTTP, CSV."""
import csv
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from tests.daten import BASIS
from tests.test_handy import Client
from tests.test_migration import baue_v1, baue_v2
from wmscout.app import erstelle_server
from wmscout.ausgabe import render_html, schreibe_ausgaben
from wmscout.bearbeitung import (FREI, KONTAKTIERT, OHNE_ZUORDNUNG, RESERVIERT, BearbeitungsKonflikt, TeamSicht, ablauf_grenze,
                                 darf_abgeben, darf_erzwingen, darf_status, darf_uebernehmen, darf_zuweisen, halter, kuerzel,
                                 reservierung_tage, zustand)
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenbank import Datenbank
from wmscout.migrationen import AKTUELLE_VERSION, migriere
from wmscout.team import TeamSpeicher, lade_team_sicht

JETZT = datetime(2026, 10, 14, 12, 0, 0)
NEUN = "2026-10-14T09:00:00"


# ======================================================================= reine Funktionen
def test_kuerzel_initialen_und_zwei_buchstaben():
    k = kuerzel([{"id": 1, "name": "Anna Schmidt"}, {"id": 2, "name": "Ben"}, {"id": 3, "name": "carl-friedrich von Weizsäcker"}])
    assert k == {1: "AS", 2: "BE", 3: "CW"}
    assert kuerzel([{"id": 7, "name": "X"}, {"id": 8, "name": "Ö"}]) == {7: "X", 8: "Ö"}
    assert kuerzel([{"id": 1, "name": "1234"}]) == {1: "N1"}              # kein Buchstabe: Ersatz über die ID


def test_kuerzel_kollision_verlaengert_nach_id_und_ist_stabil():
    nutzer = [{"id": 2, "name": "Ben"}, {"id": 5, "name": "Bernd"}]
    assert kuerzel(nutzer) == {2: "BE", 5: "BER"}
    assert kuerzel(list(reversed(nutzer))) == {2: "BE", 5: "BER"}          # Reihenfolge der Liste egal
    # neue Kollegen ändern bestehende Kürzel nie
    mehr = nutzer + [{"id": 6, "name": "Berta"}, {"id": 9, "name": "Bernhard"}, {"id": 10, "name": "Anna Berg"}]
    k = kuerzel(mehr)
    assert {i: k[i] for i in (2, 5)} == {2: "BE", 5: "BER"}
    assert k[6] == "BERT" and k[9] == "BERN" and k[10] == "AB"
    assert len(set(k.values())) == len(k)
    # kommt der Kürzel-Träger mit kleinerer ID später dazu (ID-Reihenfolge), gilt die ID: Bernd (id 1) vor Ben (id 2)
    assert kuerzel([{"id": 1, "name": "Bernd"}, {"id": 2, "name": "Ben"}]) == {1: "BE", 2: "BEN"}


def test_kuerzel_identische_namen_bleiben_eindeutig():
    k = kuerzel([{"id": i, "name": "Ben"} for i in (1, 2, 3, 4)])
    assert len(set(k.values())) == 4 and k[1] == "BE" and k[2] == "BEN"


AKTIV = frozenset({1, 2, 3})


def _z(**kw):
    return {"bearbeiter_id": None, "uebernommen_am": None, "kontaktiert_von": None, "kontaktiert_am": None, "status": "neu", **kw}


def test_zustand_frei_reserviert_abgelaufen_kontaktiert():
    assert zustand(None, JETZT, 2, AKTIV) == FREI
    assert zustand(_z(), JETZT, 2, AKTIV) == FREI
    vor_1_tag = (JETZT - timedelta(days=1)).isoformat(timespec="seconds")
    vor_3_tage = (JETZT - timedelta(days=3)).isoformat(timespec="seconds")
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=vor_1_tag), JETZT, 2, AKTIV) == RESERVIERT
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=vor_3_tage), JETZT, 2, AKTIV) == FREI         # abgelaufen
    genau = (JETZT - timedelta(days=2)).isoformat(timespec="seconds")
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=genau), JETZT, 2, AKTIV) == RESERVIERT        # Grenze selbst gilt noch
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=vor_3_tage, kontaktiert_von=2, kontaktiert_am=vor_3_tage),
                   JETZT, 2, AKTIV) == KONTAKTIERT                                                     # Kontakt läuft nie ab


def test_zustand_reservierung_tage_null_laeuft_nie_ab():
    uralt = "2020-01-01T00:00:00"
    assert ablauf_grenze(JETZT, 0) == ""
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=uralt), JETZT, 0, AKTIV) == RESERVIERT
    assert zustand(_z(bearbeiter_id=2, uebernommen_am=uralt), JETZT, 2, AKTIV) == FREI


def test_zustand_inaktiver_bearbeiter_gilt_als_frei():
    frisch = JETZT.isoformat(timespec="seconds")
    z = _z(bearbeiter_id=9, uebernommen_am=frisch)
    assert zustand(z, JETZT, 2, AKTIV) == FREI and halter(z, ablauf_grenze(JETZT, 2), AKTIV) is None
    # auch ein bestätigter Kontakt bleibt Tatsache, hält das Inserat aber nicht mehr
    k = _z(bearbeiter_id=9, uebernommen_am=frisch, kontaktiert_von=9, kontaktiert_am=frisch)
    assert zustand(k, JETZT, 2, AKTIV) == KONTAKTIERT and halter(k, ablauf_grenze(JETZT, 2), AKTIV) is None


def test_zustand_altbestand_ohne_zuordnung():
    for status in ("kontaktiert", "verhandlung", "besichtigung"):
        assert zustand(_z(status=status), JETZT, 2, AKTIV) == OHNE_ZUORDNUNG
        assert zustand({"status": status}, JETZT, 2, AKTIV) == OHNE_ZUORDNUNG                           # ganz ohne Zeile
    for status in ("neu", "gekauft", "abgesagt", "uninteressant"):
        assert zustand(_z(status=status), JETZT, 2, AKTIV) == FREI
    # abgelaufene Reservierung auf einem schon kontaktierten Altbestand: wieder ohne Zuordnung, nicht „frei“
    alt = _z(status="kontaktiert", bearbeiter_id=2, uebernommen_am="2020-01-01T00:00:00")
    assert zustand(alt, JETZT, 2, AKTIV) == OHNE_ZUORDNUNG
    assert zustand({**alt, "uebernommen_am": JETZT.isoformat(timespec="seconds")}, JETZT, 2, AKTIV) == RESERVIERT


def test_regeln():
    assert darf_uebernehmen(None, 2) and darf_uebernehmen(2, 2) and not darf_uebernehmen(3, 2)
    assert darf_status(None, 2, "mitarbeiter") and darf_status(2, 2, "mitarbeiter")
    assert not darf_status(3, 2, "mitarbeiter") and darf_status(3, 2, "inhaber")
    assert darf_abgeben(RESERVIERT, 2, 2, "mitarbeiter") and darf_abgeben(RESERVIERT, 3, 2, "inhaber")
    assert not darf_abgeben(RESERVIERT, 3, 2, "mitarbeiter")
    assert not darf_abgeben(KONTAKTIERT, 2, 2, "inhaber") and not darf_abgeben(FREI, None, 2, "inhaber")
    assert darf_zuweisen("inhaber") and not darf_zuweisen("mitarbeiter") and darf_erzwingen("inhaber") and not darf_erzwingen(None)


def test_konfiguration_reservierung_tage():
    assert reservierung_tage({}) == 2 and reservierung_tage({"team": None}) == 2 and reservierung_tage({"team": {}}) == 2
    assert reservierung_tage({"team": {"reservierung_tage": 0}}) == 0 and reservierung_tage({"team": {"reservierung_tage": 5}}) == 5
    for falsch in ("zwei", 1.5, -1, True, [2], 100000):
        with pytest.raises(ValueError, match="reservierung_tage"):
            reservierung_tage({"team": {"reservierung_tage": falsch}})
    with pytest.raises(ValueError, match="team"):
        reservierung_tage({"team": 3})
    echt = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    assert echt["team"]["reservierung_tage"] == 2 and reservierung_tage(echt) == 2


def test_team_sicht_objekt_und_meldungen():
    nutzer = [{"id": 1, "name": "Anna", "rolle": "inhaber", "aktiv": 1}, {"id": 2, "name": "Ben", "rolle": "mitarbeiter", "aktiv": 1},
              {"id": 3, "name": "Carl", "rolle": "mitarbeiter", "aktiv": 0}]
    zeilen = {"A": {"anzeige_id": "A", "bearbeiter_id": 2, "uebernommen_am": "2026-10-14T10:42:00", "kontaktiert_von": None, "kontaktiert_am": None},
              "B": {"anzeige_id": "B", "bearbeiter_id": 3, "uebernommen_am": "2026-10-14T10:00:00", "kontaktiert_von": None, "kontaktiert_am": None},
              "C": {"anzeige_id": "C", "bearbeiter_id": 2, "uebernommen_am": "2026-10-10T08:00:00", "kontaktiert_von": 2,
                    "kontaktiert_am": "2026-10-10T09:15:00"}}
    ich = TeamSicht(nutzer, zeilen, JETZT, 2, {"id": 1, "rolle": "inhaber"})
    a = ich.objekt_id("A", "neu")
    assert a["zustand"] == RESERVIERT and a["bearbeiter"]["kuerzel"] == "BE" and a["seit"] == "2026-10-14T10:42:00"
    assert a["laeuft_ab"] == "2026-10-16T10:42:00" and not a["mein"] and a["darf"]["zuweisen"] and a["darf"]["erzwingen"]
    assert not a["darf"]["uebernehmen"] and a["darf"]["abgeben"]            # Inhaber darf jede Reservierung zurückgeben
    assert ich.objekt_id("B", "neu")["zustand"] == FREI                       # Carl deaktiviert
    c = ich.objekt_id("C", "kontaktiert")
    assert c["zustand"] == KONTAKTIERT and c["kontaktiert_von"]["name"] == "Ben" and c["laeuft_ab"] is None
    assert ich.konflikt_text("A") == "Reserviert von Ben (BE) seit 14.10. 10:42"
    assert ich.konflikt_text("C") == "Bereits kontaktiert, bearbeitet von Ben (BE) seit 10.10. 09:15"
    assert ich.konflikt_text("D", ["A"]) == "Dublette A: Reserviert von Ben (BE) seit 14.10. 10:42"
    d = ich.objekt_id("D", "neu", ["A"])
    assert d["zustand"] == FREI and d["dublette_von"]["id"] == "A" and not d["darf"]["uebernehmen"] and not TeamSicht.ist_frei(d)
    assert TeamSicht.ist_frei(ich.objekt_id("D", "neu")) and TeamSicht.ist_frei(ich.objekt_id("Z", "kontaktiert"))
    mit_tage_null = TeamSicht(nutzer, zeilen, JETZT, 0, {"id": 2, "rolle": "mitarbeiter"})
    ben = mit_tage_null.objekt_id("A", "neu")
    assert ben["mein"] and ben["laeuft_ab"] is None and ben["darf"]["abgeben"] and not ben["darf"]["zuweisen"]
    assert mit_tage_null.objekt_id("C", "kontaktiert")["mein"] and mit_tage_null.fremder_halter("A") is None


# ======================================================================= Datenbank
@pytest.fixture
def team(db, tmp_path):
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.ids = {n: t.nutzer_anlegen(n, "sicher1234", "inhaber" if n == "Anna" else "mitarbeiter") for n in ("Anna", "Ben", "Carl")}
    return t


def anzeige_ids(db, n=5):
    return [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT ?", (n,))]


def bearbeitung(db, ad_id):
    r = db.con.execute("SELECT bearbeiter_id, uebernommen_am, kontaktiert_von, kontaktiert_am FROM bearbeitung WHERE anzeige_id=?", (ad_id,)).fetchone()
    return tuple(r) if r else None


def anzeigen_zeile(db, ad_id):
    return tuple(db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone())


def test_upsert_rowcount_ist_null_bei_abgelehntem_update(db, team, importiert):
    """Grundlage der Konflikterkennung: ON CONFLICT … DO UPDATE … WHERE falsch ändert nichts und meldet rowcount 0."""
    a = anzeige_ids(db, 1)[0]
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    cur = db.con.execute(Datenbank._UEBERNAHME, {"id": a, "nutzer": ben, "jetzt": NEUN, "grenze": "", "erzwingen": 0})
    assert cur.rowcount == 1                                                # Einfügen
    cur = db.con.execute(Datenbank._UEBERNAHME, {"id": a, "nutzer": carl, "jetzt": "2026-10-14T11:00:00", "grenze": "", "erzwingen": 0})
    assert cur.rowcount == 0                                                # Bedingung falsch
    db.con.commit()
    assert bearbeitung(db, a) == (ben, NEUN, None, None)
    cur = db.con.execute(Datenbank._UEBERNAHME, {"id": a, "nutzer": ben, "jetzt": "2026-10-14T11:00:00", "grenze": "", "erzwingen": 0})
    assert cur.rowcount == 1                                                # eigene Reservierung, geändert
    db.con.commit()


def test_uebernahme_frei_fremd_eigen_abgelaufen_erzwingen_inaktiv(db, team, importiert):
    a, b, c, d = anzeige_ids(db, 4)
    anna, ben, carl = team.ids["Anna"], team.ids["Ben"], team.ids["Carl"]
    assert db.uebernimm(a, ben, NEUN) and bearbeitung(db, a) == (ben, NEUN, None, None)          # frei
    assert not db.uebernimm(a, carl, "2026-10-14T10:00:00") and bearbeitung(db, a) == (ben, NEUN, None, None)   # fremd
    assert db.uebernimm(a, ben, "2026-10-14T10:30:00") and bearbeitung(db, a)[1] == "2026-10-14T10:30:00"      # eigene verlängert
    # abgelaufen: Übernahme zu 09:00, Grenze 10:00 -> Carl darf
    assert db.uebernimm(b, ben, NEUN) and not db.uebernimm(b, carl, "2026-10-14T11:00:00", grenze="2026-10-14T08:00:00")
    assert db.uebernimm(b, carl, "2026-10-14T11:00:00", grenze="2026-10-14T10:00:00") and bearbeitung(db, b)[0] == carl
    # Grenze genau gleich: noch nicht abgelaufen
    assert db.uebernimm(c, ben, NEUN) and not db.uebernimm(c, carl, "2026-10-14T11:00:00", grenze=NEUN)
    # abgelaufen, aber kontaktiert: bleibt gehalten
    db.con.execute("UPDATE bearbeitung SET kontaktiert_von=?, kontaktiert_am=? WHERE anzeige_id=?", (ben, NEUN, c))
    db.con.commit()
    assert not db.uebernimm(c, carl, "2026-10-20T11:00:00", grenze="2026-10-19T00:00:00")
    # erzwingen (auch gegen Kontakt); kontaktiert_von bleibt
    assert db.uebernimm(c, anna, "2026-10-20T11:00:00", erzwingen=True) and bearbeitung(db, c) == (anna, "2026-10-20T11:00:00", ben, NEUN)
    # inaktiver Bearbeiter: Reservierung gilt als frei, auch ohne Ablauf
    assert db.uebernimm(d, ben, NEUN) and not db.uebernimm(d, carl, "2026-10-14T10:00:00")
    team.nutzer_aktiv_setzen("Ben", False)
    assert db.uebernimm(d, carl, "2026-10-14T10:00:00") and bearbeitung(db, d)[0] == carl


def test_uebernahme_mit_dublette(db, team, importiert):
    a, b, c = anzeige_ids(db, 3)
    ben, carl, anna = team.ids["Ben"], team.ids["Carl"], team.ids["Anna"]
    assert db.uebernimm(a, ben, NEUN)
    assert not db.uebernimm(b, carl, NEUN, dubletten=[a, c]) and bearbeitung(db, b) is None      # Dublette von Ben reserviert
    assert db.uebernimm(b, ben, NEUN, dubletten=[a, c])                                          # eigene Dublette: kein Konflikt
    assert db.uebernimm(c, anna, NEUN, dubletten=[a], erzwingen=True)                            # erzwingen übergeht auch Dubletten
    assert bearbeitung(db, a)[0] == anna and bearbeitung(db, c)[0] == anna                       # … und nimmt Bens Reservierung der Dublette mit
    assert db.uebernimm(c, carl, NEUN, dubletten=[b]) is False                                   # b gehört Ben
    # a (jetzt Anna, 14.10. 09:00): nicht abgelaufen blockiert die Dublette, abgelaufen nicht
    d, e = anzeige_ids(db, 5)[3:]
    assert not db.uebernimm(e, carl, "2026-10-14T10:00:00", grenze="2026-10-14T08:00:00", dubletten=[a])
    assert db.uebernimm(d, carl, "2026-10-20T00:00:00", grenze="2026-10-19T00:00:00", dubletten=[a])
    # deaktivierter Bearbeiter einer Dublette blockiert ebenfalls nicht
    team.nutzer_aktiv_setzen("Anna", False)
    assert db.uebernimm(e, carl, "2026-10-14T10:00:00", grenze="2026-10-14T08:00:00", dubletten=[a])


def test_kontakt_laeuft_nie_ab_auch_nicht_bei_dubletten_und_status(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    db.setze_status(a, "kontaktiert", text="x", nutzer_id=ben)
    db.con.execute("UPDATE bearbeitung SET uebernommen_am='2020-01-01T00:00:00' WHERE anzeige_id=?", (a,))
    db.con.commit()
    grenze = "2026-10-12T00:00:00"
    assert not db.uebernimm(b, carl, NEUN, grenze=grenze, dubletten=[a])                          # Dublette bestätigt kontaktiert
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "uninteressant", nutzer_id=carl, grenze=grenze)                        # trotz altem Zeitstempel
    assert not db.uebernimm(a, carl, NEUN, grenze=grenze)


def test_setze_status_kontaktiert_setzt_kontaktiert_von_und_rollback_bei_fremdem(db, team, importiert):
    a = anzeige_ids(db, 1)[0]
    anna, ben, carl = team.ids["Anna"], team.ids["Ben"], team.ids["Carl"]
    assert db.setze_status(a, "kontaktiert", text="Hallo", betrag=30000, nutzer_id=ben)
    b = bearbeitung(db, a)
    assert b[0] == ben and b[2] == ben and b[3] and b[1]                                          # Übernahme + erster Kontakt
    z = db.con.execute("SELECT status, anschreiben_text, angebot_betrag FROM anzeigen WHERE id=?", (a,)).fetchone()
    assert tuple(z) == ("kontaktiert", "Hallo", 30000)
    # Fremder: Konflikt, alles unverändert, keine offene Transaktion
    vorher_anz, vorher_bearb = anzeigen_zeile(db, a), bearbeitung(db, a)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "kontaktiert", text="Zweiter Text", nutzer_id=carl)
    with pytest.raises(BearbeitungsKonflikt):
        db.nachgefasst(a, "Nachfrage", nutzer_id=carl)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "uninteressant", nutzer_id=carl)                                      # Fremder, auch andere Status
    assert not db.con.in_transaction
    assert anzeigen_zeile(db, a) == vorher_anz and bearbeitung(db, a) == vorher_bearb
    # Inhaber darf andere Status setzen (ohne Übernahme), Kontakt nur erzwungen
    assert db.setze_status(a, "verhandlung", nutzer_id=anna, inhaber=True) and bearbeitung(db, a) == vorher_bearb
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "kontaktiert", nutzer_id=anna, inhaber=True)
    # Bearbeiter nachfassen: erster Kontakt bleibt, Zähler läuft
    assert db.nachgefasst(a, "Nachfrage", nutzer_id=ben)
    assert bearbeitung(db, a) == vorher_bearb and db.con.execute("SELECT nachfass_anzahl FROM anzeigen WHERE id=?", (a,)).fetchone()[0] == 1


def test_fehler_mitten_in_der_transaktion_rollt_uebernahme_und_status_zurueck(db, team, importiert, monkeypatch):
    """Übernahme und Status sind eine Einheit: bricht nach der Übernahme etwas ab, bleibt weder Reservierung noch Status."""
    a, b = anzeige_ids(db, 2)
    ben = team.ids["Ben"]
    vorher = anzeigen_zeile(db, a)
    db.setze_status(b, "verhandlung")      # Nachfassen trägt einen Kontakt nur bei schon kontaktierten Vorgängen ein (ADR-012)

    def kaputt(*args):
        raise sqlite3.OperationalError("simulierter Fehler")

    monkeypatch.setattr(db, "_trage_kontakt_ein", kaputt)
    with pytest.raises(sqlite3.OperationalError):
        db.setze_status(a, "kontaktiert", text="Hallo", nutzer_id=ben)
    with pytest.raises(sqlite3.OperationalError):
        db.nachgefasst(b, "Nachfrage", nutzer_id=ben)
    assert not db.con.in_transaction
    assert bearbeitung(db, a) is None and bearbeitung(db, b) is None and anzeigen_zeile(db, a) == vorher
    assert db.con.execute("SELECT COUNT(*) FROM bearbeitung").fetchone()[0] == 0


def test_setze_status_unbekannte_anzeige_legt_nichts_an(db, team):
    assert db.setze_status("gibtsnicht", "kontaktiert", nutzer_id=team.ids["Ben"]) is False
    assert db.nachgefasst("gibtsnicht", "x", nutzer_id=team.ids["Ben"]) is False
    assert db.con.execute("SELECT COUNT(*) FROM bearbeitung").fetchone()[0] == 0 and not db.con.in_transaction


def test_status_neu_leert_den_kontakt_bearbeiter_bleibt(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    db.setze_status(a, "kontaktiert", text="Hallo", nutzer_id=ben)
    assert db.setze_status(a, "neu", nutzer_id=ben)
    z = bearbeitung(db, a)
    assert z[0] == ben and z[2] is None and z[3] is None
    assert db.con.execute("SELECT status, kontaktiert_am FROM anzeigen WHERE id=?", (a,)).fetchone()[:] == ("neu", None)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "neu", nutzer_id=carl)                                                # Reservierung von Ben gilt weiter
    # freies Fahrzeug: jeder darf andere Status setzen, ohne Übernahme
    assert db.setze_status(b, "uninteressant", nutzer_id=carl) and bearbeitung(db, b) is None


def test_gib_ab_vor_und_nach_kontakt_und_zuweisen(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    anna, ben, carl = team.ids["Anna"], team.ids["Ben"], team.ids["Carl"]
    db.uebernimm(a, ben, NEUN)
    assert not db.gib_ab(a, carl) and bearbeitung(db, a)                                          # Fremder
    assert db.gib_ab(a, ben) and bearbeitung(db, a) is None                                       # Bearbeiter
    db.uebernimm(a, ben, NEUN)
    assert db.gib_ab(a, anna, inhaber=True) and bearbeitung(db, a) is None                        # Inhaber
    db.setze_status(b, "kontaktiert", text="x", nutzer_id=ben)
    vorher = bearbeitung(db, b)
    assert not db.gib_ab(b, ben) and not db.gib_ab(b, anna, inhaber=True) and bearbeitung(db, b) == vorher   # nach Kontakt nicht
    db.weise_zu(b, carl, "2026-10-14T13:00:00")
    assert bearbeitung(db, b) == (carl, "2026-10-14T13:00:00", ben, vorher[3])                    # kontaktiert_von bleibt
    db.weise_zu(a, carl, "2026-10-14T13:00:00")                                                   # auch ohne vorhandene Zeile
    assert bearbeitung(db, a) == (carl, "2026-10-14T13:00:00", None, None)


def test_team_zaehler_mit_festem_jetzt(db, team, importiert):
    a1, a2, a3, a4, a5, a6, a7, a8 = anzeige_ids(db, 8)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?", (NEUN,))
    db.con.execute("UPDATE anzeigen SET status='kontaktiert' WHERE id IN (?,?)", (a5, a8))
    db.con.execute("UPDATE anzeigen SET status='verhandlung' WHERE id=?", (a6,))
    db.con.execute("UPDATE anzeigen SET status='besichtigung' WHERE id=?", (a7,))
    zeilen = [(a1, ben, NEUN, None, None), (a2, ben, "2026-10-13T20:00:00", None, None),         # Ben: 2 reserviert, 1 heute übernommen
              (a3, carl, "2026-10-14T08:00:00", None, None),                                      # Carl: 1 reserviert, heute
              (a4, ben, "2026-10-01T08:00:00", None, None),                                       # abgelaufen: zählt nirgends
              (a6, ben, "2026-10-01T08:00:00", None, None),                                       # abgelaufen + Altbestand: ohne Zuordnung
              (a7, carl, "2026-10-14T08:30:00", None, None),                                      # Besichtigung, Carl reserviert: nicht ohne Zuordnung
              (a8, ben, "2026-10-10T08:00:00", ben, "2026-10-14T07:00:00")]                       # Ben kontaktiert heute, in Arbeit
    db.con.executemany("INSERT INTO bearbeitung VALUES (?,?,?,?,?)", zeilen)
    db.con.commit()
    grenze = ablauf_grenze(JETZT, 2)                                                              # 2026-10-12T12:00:00
    z = db.team_zaehler(JETZT, grenze)
    je = {n["name"]: n for n in z["nutzer"]}
    assert je["Ben"] == {"nutzer_id": ben, "name": "Ben", "reserviert": 2, "in_arbeit": 1, "kontakte_heute": 1, "uebernommen_heute": 1}
    assert je["Carl"] == {"nutzer_id": carl, "name": "Carl", "reserviert": 2, "in_arbeit": 0, "kontakte_heute": 0, "uebernommen_heute": 2}
    assert je["Anna"]["reserviert"] == 0 and z["ohne_zuordnung"] == 2                               # a5 (nie zugeordnet), a6 (abgelaufen)
    assert z["nutzer"][0]["name"] == "Anna"                                                       # nach Name sortiert
    # reservierung_tage = 0: nichts läuft ab, a4 und a6 sind wieder reserviert
    z0 = db.team_zaehler(JETZT, "")
    assert {n["name"]: n["reserviert"] for n in z0["nutzer"]} == {"Anna": 0, "Ben": 4, "Carl": 2} and z0["ohne_zuordnung"] == 1
    # deaktivierte Nutzer erscheinen nicht, ihre Reservierungen zählen nicht mehr als gehalten
    team.nutzer_aktiv_setzen("Carl", False)
    z = db.team_zaehler(JETZT, grenze)
    assert [n["name"] for n in z["nutzer"]] == ["Anna", "Ben"] and z["ohne_zuordnung"] == 3             # a7 (Carl inaktiv) kommt dazu
    # Inserate, die lange nicht gesehen wurden, zählen nicht
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2026-01-01T00:00:00'")
    db.con.commit()
    z = db.team_zaehler(JETZT, grenze)
    assert z["ohne_zuordnung"] == 0 and {n["name"]: n["reserviert"] for n in z["nutzer"]}["Ben"] == 0
    assert {n["name"]: n["kontakte_heute"] for n in z["nutzer"]}["Ben"] == 1                       # Kontakte von heute bleiben Statistik


def test_bearbeitung_aktiv_ein_select_mit_aktiv_flag(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    db.uebernimm(a, team.ids["Ben"], NEUN)
    db.uebernimm(b, team.ids["Carl"], NEUN)
    team.nutzer_aktiv_setzen("Carl", False)
    z = db.bearbeitung_aktiv()
    assert set(z) == {a, b} and z[a]["bearbeiter_aktiv"] == 1 and z[b]["bearbeiter_aktiv"] == 0 and z[a]["bearbeiter_id"] == team.ids["Ben"]
    db.con.execute("DELETE FROM nutzer WHERE name='Carl'")                                         # Waise: Bearbeiter existiert nicht mehr
    assert db.bearbeitung_aktiv()[b]["bearbeiter_aktiv"] == 0
    assert db.uebernimm(b, team.ids["Ben"], NEUN)                                                  # gilt als frei


# ----------------------------------------------------------------------- Nebenläufigkeit (zwei Verbindungen auf derselben Datei)
def _gleichzeitig(aufgaben):
    sperre = threading.Barrier(len(aufgaben))
    ergebnisse, fehler = [None] * len(aufgaben), []

    def lauf(i, f):
        try:
            sperre.wait(timeout=10)
            ergebnisse[i] = f()
        except BaseException as e:  # noqa: BLE001 – im Test sammeln und danach melden
            fehler.append(e)

    threads = [threading.Thread(target=lauf, args=(i, f)) for i, f in enumerate(aufgaben)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not fehler, fehler
    return ergebnisse


def test_nebenlaeufig_uebernahme_genau_ein_gewinner(cfg, db, team, importiert):
    pfad = cfg["ausgabe"]["datenbank"]
    verbindungen = [Datenbank(pfad), Datenbank(pfad)]                                              # zwei getrennte Verbindungen
    ids = anzeige_ids(db, 50)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    for ad_id in ids:
        ergebnis = _gleichzeitig([lambda ad_id=ad_id: verbindungen[0].uebernimm(ad_id, ben, NEUN),
                                  lambda ad_id=ad_id: verbindungen[1].uebernimm(ad_id, carl, NEUN)])
        assert sorted(ergebnis) == [False, True], (ad_id, ergebnis)
        assert bearbeitung(db, ad_id)[0] == (ben if ergebnis[0] else carl)
    for v in verbindungen:
        v.con.close()


def test_nebenlaeufig_status_kontaktiert_genau_ein_gewinner(cfg, db, team, importiert):
    pfad = cfg["ausgabe"]["datenbank"]
    verbindungen = [Datenbank(pfad), Datenbank(pfad)]
    ben, carl = team.ids["Ben"], team.ids["Carl"]

    def versuche(v, nutzer, ad_id):
        def f():
            try:
                return v.setze_status(ad_id, "kontaktiert", text=f"Text {nutzer}", nutzer_id=nutzer)
            except BearbeitungsKonflikt:
                return "konflikt"
        return f

    for ad_id in anzeige_ids(db, 20):
        ergebnis = _gleichzeitig([versuche(verbindungen[0], ben, ad_id), versuche(verbindungen[1], carl, ad_id)])
        assert sorted(map(str, ergebnis)) == ["True", "konflikt"], (ad_id, ergebnis)
        gewinner = ben if ergebnis[0] is True else carl
        assert bearbeitung(db, ad_id)[:1] + bearbeitung(db, ad_id)[2:3] == (gewinner, gewinner)
        assert db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (ad_id,)).fetchone()[0] == f"Text {gewinner}"
    for v in verbindungen:
        v.con.close()


def test_nebenlaeufig_dubletten_gespiegelt_hoechstens_einer(cfg, db, team, importiert):
    """Zwei Kollegen übernehmen gleichzeitig zwei Dubletten desselben Fahrzeugs: nur eine Übernahme gelingt."""
    pfad = cfg["ausgabe"]["datenbank"]
    verbindungen = [Datenbank(pfad), Datenbank(pfad)]
    ids = anzeige_ids(db, 40)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    for a, b in zip(ids[:20], ids[20:], strict=True):
        ergebnis = _gleichzeitig([lambda a=a, b=b: verbindungen[0].uebernimm(a, ben, NEUN, dubletten=[b]),
                                  lambda a=a, b=b: verbindungen[1].uebernimm(b, carl, NEUN, dubletten=[a])])
        assert sorted(ergebnis) == [False, True], (a, b, ergebnis)
    for v in verbindungen:
        v.con.close()


# ======================================================================= Altbestand
@pytest.mark.parametrize("baue", [baue_v1, baue_v2])
def test_altbestand_kontaktiert_ist_ohne_zuordnung_und_uebernehmbar(tmp_path, baue):
    pfad = tmp_path / "alt.sqlite"
    baue(pfad)
    vorher = sqlite3.connect(pfad).execute("SELECT id, status, notiz, preis FROM anzeigen ORDER BY id").fetchall()
    db = Datenbank(str(pfad), tmp_path / "sich")
    assert db.con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == AKTUELLE_VERSION
    assert [tuple(r) for r in db.con.execute("SELECT id, status, notiz, preis FROM anzeigen ORDER BY id")] == vorher
    assert db.con.execute("SELECT COUNT(*) FROM bearbeitung").fetchone()[0] == 0
    t = TeamSpeicher(db, tmp_path / "fotos")
    ben = t.nutzer_anlegen("Ben", "sicher1234")
    carl = t.nutzer_anlegen("Carl", "sicher1234")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2026-10-13T09:00:00'")
    db.con.commit()
    z = db.team_zaehler(JETZT, ablauf_grenze(JETZT, 2))
    assert z["ohne_zuordnung"] == 1                                                                # Anzeige „1“ ist „kontaktiert“
    sicht = lade_team_sicht(db, 2, {"id": ben, "rolle": "mitarbeiter"}, JETZT)
    assert sicht.objekt_id("1", "kontaktiert")["zustand"] == OHNE_ZUORDNUNG and sicht.objekt_id("2", "neu")["zustand"] == FREI
    assert sicht.objekt_id("1", "kontaktiert")["darf"]["uebernehmen"]
    # übernehmbar, auch durch Nachfassen/Kontakt, und die alten Daten bleiben
    assert db.setze_status("1", "kontaktiert", nutzer_id=ben)
    b = bearbeitung(db, "1")
    assert b[0] == ben and b[2] == ben
    assert tuple(db.con.execute("SELECT notiz, preis FROM anzeigen WHERE id='1'").fetchone()) == ("alte Notiz Müller 0171 1234567", 40000)
    assert db.nachgefasst("3", "Nachfrage", nutzer_id=carl) and bearbeitung(db, "3")[0] == carl
    assert len(db.con.execute("SELECT id FROM anzeigen").fetchall()) == 3


def test_t1_braucht_keine_eigene_migration(tmp_path):
    """Keine Migration in T1: die Tabelle ``bearbeitung`` aus Version 3 genügt (spätere Versionen, z. B. v4 der
    Ereignis-Grundlage aus PR #7, ändern sie nicht)."""
    pfad = tmp_path / "neu.sqlite"
    assert migriere(pfad)[-1] == AKTUELLE_VERSION
    con = sqlite3.connect(pfad)
    assert [r[1] for r in con.execute("PRAGMA table_info(bearbeitung)")] == ["anzeige_id", "bearbeiter_id", "uebernommen_am",
                                                                             "kontaktiert_von", "kontaktiert_am"]
    con.close()


# ======================================================================= HTTP
def starte(cfg, db):
    srv, _, _ = erstelle_server(cfg, db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server(cfg, db, importiert):
    srv = starte(cfg, db)
    yield srv
    srv.shutdown()
    srv.server_close()


def anmelden(server, name):
    return Client(server.server_address[1]).anmelden(name)


def lokal(server):
    c = Client(server.server_address[1])
    c.csrf = c("GET", "/api/ich")[1]["csrf"]
    return c


def ids_der_liste(client, filter_="bereit", n=3, extra=""):
    liste = client("GET", f"/api/fahrzeuge?filter={filter_}{extra}")[1]
    assert len(liste) >= n
    return [f["id"] for f in liste[:n]]


def test_http_ohne_nutzer_team_aus_und_verhalten_wie_bisher(server, db):
    c = lokal(server)
    status, t, _ = c("GET", "/api/team")
    assert status == 200 and t["aktiv"] is False and t["nutzer"] == [] and t["bearbeitung"] == {} and t["ohne_zuordnung"] == 0
    assert t["ich"] is None and t["reservierung_tage"] == 2 and t["stand"]
    a, b = ids_der_liste(c, n=2)
    status, antwort, _ = c("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert status == 400 and "Team" in antwort["fehler"]
    assert c("POST", f"/api/bearbeitung/{a}/abgeben", {})[0] == 400 and c("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": 1})[0] == 400
    # Status wie bisher; keine Team-Daten, kein Fehler 409, kein bearbeitung-Eintrag
    assert c("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Hallo", "betrag": 25000}) [:2] == (200, {"ok": True})
    assert c("POST", "/api/nachgefasst", {"id": a, "text": "Nachfrage"})[:2] == (200, {"ok": True})
    assert c("POST", "/api/status", {"id": "gibtsnicht", "status": "neu"})[0] == 404
    assert c("POST", "/api/status", {"id": a, "status": "unsinn"})[0] == 400
    assert c("POST", "/api/status", {"id": b, "status": "kontaktiert", "erzwingen": True})[0] == 200        # ohne Team ohne Wirkung
    assert db.con.execute("SELECT COUNT(*) FROM bearbeitung").fetchone()[0] == 0
    assert db.con.execute("SELECT status, nachfass_anzahl FROM anzeigen WHERE id=?", (a,)).fetchone()[:] == ("kontaktiert", 1)
    liste = c("GET", "/api/fahrzeuge?filter=alle")[1]
    assert liste and all(f["team"] is None for f in liste)
    assert c("GET", f"/api/fahrzeug/{a}")[1]["team"] is None
    heute = c("GET", "/api/heute")[1]
    assert heute["meine"] is None and heute["frei_bereit"] is None and heute["bereit"] >= 0
    assert c("GET", "/api/fahrzeuge?filter=alle&wer=alle")[0] == 200
    assert c("GET", "/api/fahrzeuge?filter=alle&wer=meine")[0] == 400 and c("GET", "/api/fahrzeuge?filter=alle&wer=frei")[0] == 400
    assert c("GET", "/api/fahrzeuge?wer=quatsch")[0] == 400
    ich = c("GET", "/api/ich")[1]
    assert ich["team"] is False and ich["nutzer"]["kuerzel"] is None


def test_http_uebernehmen_status_nachfassen_konflikt(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a = ids_der_liste(ben, n=1)[0]
    status, antwort, _ = ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert status == 200 and antwort["ok"] and antwort["team"]["zustand"] == "reserviert"
    assert antwort["team"]["bearbeiter"]["name"] == "Ben" and antwort["team"]["bearbeiter"]["kuerzel"] == "BE" and antwort["team"]["mein"]
    # Carl: Übernahme, Kontakt und Nachfassen scheitern, Datenbank bleibt unverändert
    status, antwort, _ = carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert status == 409 and antwort["fehler"].startswith("Reserviert von Ben (BE) seit ") and antwort["team"]["bearbeiter"]["name"] == "Ben"
    assert antwort["team"]["mein"] is False
    vorher_anz, vorher_bearb = anzeigen_zeile(db, a), bearbeitung(db, a)
    s, antwort, _ = carl("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Hallo von Carl"})
    assert s == 409 and "Ben (BE)" in antwort["fehler"] and antwort["team"]["zustand"] == "reserviert"
    assert carl("POST", "/api/nachgefasst", {"id": a, "text": "Nachfrage von Carl"})[0] == 409
    assert carl("POST", "/api/status", {"id": a, "status": "uninteressant"})[0] == 409
    assert anzeigen_zeile(db, a) == vorher_anz and bearbeitung(db, a) == vorher_bearb
    assert carl("POST", "/api/notiz", {"id": a, "notiz": "Notiz von Carl"})[0] == 200                  # Notizen bleiben frei
    assert db.con.execute("SELECT notiz FROM anzeigen WHERE id=?", (a,)).fetchone()[0] == "Notiz von Carl"
    # Anna (Inhaberin) kann ohne Erzwingen den Kontakt nicht über die Reservierung hinweg setzen, andere Status schon
    assert anna("POST", "/api/status", {"id": a, "status": "kontaktiert"})[0] == 409
    assert anna("POST", "/api/status", {"id": a, "status": "verhandlung"})[0] == 200 and bearbeitung(db, a) == vorher_bearb
    assert anna("POST", "/api/status", {"id": a, "status": "neu"})[0] == 200
    # Ben kontaktiert: kontaktiert_von = Ben
    s, antwort, _ = ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Hallo von Ben", "betrag": 20000})
    assert s == 200
    b = bearbeitung(db, a)
    assert b[0] == ben_id(team, "Ben") and b[2] == ben_id(team, "Ben") and b[3]
    t = ben("GET", f"/api/fahrzeug/{a}")[1]["team"]
    assert t["zustand"] == "kontaktiert" and t["kontaktiert_von"]["kuerzel"] == "BE" and t["laeuft_ab"] is None and t["mein"]
    # danach: Carl scheitert mit Hinweis auf bestätigten Kontakt, Abgabe nicht mehr möglich
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert s == 409 and "Bereits kontaktiert" in antwort["fehler"] and "Ben (BE)" in antwort["fehler"]
    assert carl("POST", f"/api/bearbeitung/{a}/abgeben", {})[0] == 403
    s, antwort, _ = ben("POST", f"/api/bearbeitung/{a}/abgeben", {})
    assert s == 409 and "bereits kontaktiert" in antwort["fehler"].lower() and "zuweisen" in antwort["fehler"]
    assert bearbeitung(db, a) == b
    # Zuweisen: Mitarbeiter 403, Inhaber 200; kontaktiert_von bleibt Ben
    assert carl("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": ben_id(team, "Carl")})[0] == 403
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": ben_id(team, "Carl")})
    assert s == 200 and antwort["team"]["bearbeiter"]["name"] == "Carl" and antwort["team"]["kontaktiert_von"]["name"] == "Ben"
    assert bearbeitung(db, a)[0] == ben_id(team, "Carl") and bearbeitung(db, a)[2] == ben_id(team, "Ben")
    assert ben("POST", "/api/nachgefasst", {"id": a, "text": "Ben darf nicht mehr"})[0] == 409
    assert carl("POST", "/api/nachgefasst", {"id": a, "text": "Carl fasst nach"})[0] == 200
    assert bearbeitung(db, a)[2] == ben_id(team, "Ben")                                                # erster Kontakt bleibt
    # Rückgängig durch den neuen Bearbeiter leert den Kontakt, Bearbeiter bleibt
    assert carl("POST", "/api/status", {"id": a, "status": "neu"})[0] == 200
    assert bearbeitung(db, a)[0] == ben_id(team, "Carl") and bearbeitung(db, a)[2] is None and bearbeitung(db, a)[3] is None


def ben_id(team, name):
    return team.ids[name]


def test_http_zuweisen_pruefungen_und_abgeben(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a, b = ids_der_liste(anna, n=2)
    assert anna("POST", f"/api/bearbeitung/{a}/zuweisen", {})[0] == 400
    assert anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": 9999})[0] == 400
    assert anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": "2"})[0] == 400
    team.nutzer_aktiv_setzen("Carl", False)
    assert anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 400      # deaktiviert
    team.nutzer_aktiv_setzen("Carl", True)
    carl = anmelden(server, "Carl")                                                                   # Deaktivieren beendet die Sitzung
    assert anna("POST", "/api/bearbeitung/gibtsnicht/zuweisen", {"nutzer_id": team.ids["Ben"]})[0] == 404
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": team.ids["Ben"]})
    assert s == 200 and antwort["team"]["bearbeiter"]["name"] == "Ben" and antwort["team"]["mein"] is False
    # abgeben: Fremder 403, Bearbeiter 200, doppelt abgeben bleibt 200, Inhaber gibt fremde zurück
    assert carl("POST", f"/api/bearbeitung/{a}/abgeben", {})[0] == 403
    s, antwort, _ = ben("POST", f"/api/bearbeitung/{a}/abgeben", {})
    assert s == 200 and antwort["team"]["zustand"] == "frei" and bearbeitung(db, a) is None
    assert ben("POST", f"/api/bearbeitung/{a}/abgeben", {})[0] == 200
    assert carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 200
    assert anna("POST", f"/api/bearbeitung/{b}/abgeben", {})[0] == 200 and bearbeitung(db, b) is None
    assert ben("POST", "/api/bearbeitung/gibtsnicht/abgeben", {})[0] == 404


def test_http_erzwingen_nur_inhaber(server, team, db, caplog):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a = ids_der_liste(anna, n=1)[0]
    assert ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    assert anna("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 409
    assert carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": True})[0] == 403
    assert carl("POST", "/api/status", {"id": a, "status": "kontaktiert", "erzwingen": True})[0] == 403
    assert bearbeitung(db, a)[0] == team.ids["Ben"]
    with caplog.at_level("INFO", logger="scout"):
        s, antwort, _ = anna("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": True})
        anna("POST", f"/api/bearbeitung/{a}/zuweisen", {"nutzer_id": team.ids["Carl"]})
    assert s == 200 and antwort["team"]["mein"] and bearbeitung(db, a)[0] == team.ids["Carl"]
    texte = [r.getMessage() for r in caplog.records]
    assert any("Erzwungene Übernahme" in t and a in t and "Ben" in t and "Anna" in t for t in texte), texte
    assert any("Zuweisung" in t and a in t and "Carl" in t and "Anna" in t for t in texte), texte
    # erzwungener Kontakt der Inhaberin über eine fremde Reservierung
    assert anna("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Chef", "erzwingen": True})[0] == 200
    assert bearbeitung(db, a)[0] == team.ids["Anna"] and bearbeitung(db, a)[2] == team.ids["Anna"]


def test_http_csrf_unbekannte_id_bindestrich_id(server, team, db):
    jetzt = datetime.now().isoformat(timespec="seconds")
    db.con.execute("INSERT INTO anzeigen (id, titel, preis, ort, marke, ez_jahr, km, zuletzt_gesehen, erstmals_gesehen, suche, url) "
                   "VALUES ('md-abc-123', 'Hymer B 544 Sondermodell', 38000, '70173 Stuttgart', 'Hymer', 2015, 90000, ?, ?, 'Import', 'http://x')",
                   (jetzt, jetzt))
    db.con.commit()                         # vor dem ersten Abruf (die Bewertung wird 30 s zwischengespeichert)
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    a = ids_der_liste(anna, n=1)[0]
    for aktion, daten in (("uebernehmen", {}), ("abgeben", {}), ("zuweisen", {"nutzer_id": team.ids["Ben"]})):
        assert anna("POST", f"/api/bearbeitung/{a}/{aktion}", daten, token=False)[0] == 403
    assert bearbeitung(db, a) is None
    assert Client(server.server_address[1])("POST", f"/api/bearbeitung/{a}/uebernehmen", {}, token=False)[0] == 401
    assert ben("POST", "/api/bearbeitung/gibtsnicht/uebernehmen", {})[0] == 404
    assert ben("POST", "/api/bearbeitung/gibts-nicht/uebernehmen", {})[0] == 404
    assert ben("GET", "/api/bearbeitung/x/uebernehmen")[0] == 404
    s, antwort, _ = ben("POST", "/api/bearbeitung/md-abc-123/uebernehmen", {})
    assert s == 200 and antwort["team"]["zustand"] == "reserviert" and bearbeitung(db, "md-abc-123")[0] == team.ids["Ben"]
    s, fz, _ = ben("GET", "/api/fahrzeug/md-abc-123")
    assert s == 200 and fz["team"]["zustand"] == "reserviert" and fz["team"]["mein"]
    assert anmelden(server, "Carl")("POST", "/api/bearbeitung/md-abc-123/uebernehmen", {})[0] == 409
    assert anmelden(server, "Carl")("POST", "/api/status", {"id": "md-abc-123", "status": "kontaktiert"})[0] == 409
    assert ben("POST", "/api/bearbeitung/md-abc-123/abgeben", {})[0] == 200


def test_http_wer_filter(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a, b, c, d = ids_der_liste(anna, "alle", n=4)
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})
    ben("POST", "/api/status", {"id": c, "status": "kontaktiert", "text": "x"})
    alle = {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert {a, b, c, d} <= alle
    standard = ben("GET", "/api/fahrzeuge?filter=alle&wer=alle")[1]
    assert {f["id"] for f in standard} == alle                                                       # alle = bisheriges Verhalten
    meine = {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle&wer=meine")[1]}
    assert meine == {a, c}
    frei = {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle&wer=frei")[1]}
    assert a not in frei and b not in frei and c not in frei and d in frei and frei == alle - {a, b, c}
    assert {f["id"] for f in carl("GET", "/api/fahrzeuge?filter=alle&wer=meine")[1]} == {b}
    assert ben("GET", "/api/fahrzeuge?filter=alle&wer=ALLE")[0] == 400
    # Filter kombinieren: arbeit + meine
    assert {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=arbeit&wer=meine")[1]} == {c}
    # abgegeben -> wieder frei
    ben("POST", f"/api/bearbeitung/{a}/abgeben", {})
    assert a in {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle&wer=frei")[1]}
    # Team-Objekt in der Liste
    fa = next(f for f in carl("GET", "/api/fahrzeuge?filter=alle")[1] if f["id"] == c)
    assert fa["team"]["zustand"] == "kontaktiert" and fa["team"]["bearbeiter"]["name"] == "Ben" and fa["team"]["mein"] is False
    # heute: meine / frei_bereit
    h = ben("GET", "/api/heute")[1]
    assert h["meine"] == 1 and isinstance(h["frei_bereit"], int)
    bereit_frei = sum(1 for f in ben("GET", "/api/fahrzeuge?filter=bereit&wer=frei")[1])
    assert h["frei_bereit"] == bereit_frei


def test_http_abgelaufen_inaktiv_und_tage_null(server, team, db):
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    a, b, c = ids_der_liste(ben, "alle", n=3)
    for x in (a, b, c):
        assert ben("POST", f"/api/bearbeitung/{x}/uebernehmen", {})[0] == 200
    alt = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    db.con.execute("UPDATE bearbeitung SET uebernommen_am=? WHERE anzeige_id IN (?,?)", (alt, a, b))
    db.con.commit()
    t = carl("GET", f"/api/fahrzeug/{a}")[1]["team"]
    assert t["zustand"] == "frei" and t["bearbeiter"] is None                                         # abgelaufen
    assert carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    # kontaktiert läuft nicht ab
    ben("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"})
    db.con.execute("UPDATE bearbeitung SET uebernommen_am=? WHERE anzeige_id=?", (alt, b))
    db.con.commit()
    assert carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 409
    # deaktivierter Bearbeiter: Reservierung gilt als frei
    team.nutzer_aktiv_setzen("Ben", False)
    assert carl("GET", f"/api/fahrzeug/{c}")[1]["team"]["zustand"] == "frei"
    assert carl("POST", f"/api/bearbeitung/{c}/uebernehmen", {})[0] == 200
    assert carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 200                           # Kontaktierer inaktiv: übernehmbar
    t = carl("GET", f"/api/fahrzeug/{b}")[1]["team"]
    assert t["kontaktiert_von"]["name"] == "Ben" and t["kontaktiert_von"]["aktiv"] is False and t["bearbeiter"]["name"] == "Carl"
    assert [n["aktiv"] for n in carl("GET", "/api/team")[1]["nutzer"] if n["name"] == "Ben"] == [False]


def test_http_reservierung_tage_null_laeuft_nie_ab(cfg, db, importiert, team):
    cfg["team"] = {"reservierung_tage": 0}
    srv = starte(cfg, db)
    try:
        ben, carl = anmelden(srv, "Ben"), anmelden(srv, "Carl")
        a = ids_der_liste(ben, "alle", n=1)[0]
        ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
        db.con.execute("UPDATE bearbeitung SET uebernommen_am='2020-01-01T00:00:00'")
        db.con.commit()
        t = carl("GET", f"/api/fahrzeug/{a}")[1]["team"]
        assert t["zustand"] == "reserviert" and t["laeuft_ab"] is None
        assert carl("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 409
        assert carl("GET", "/api/team")[1]["reservierung_tage"] == 0
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_kaputte_konfiguration_wird_beim_start_gemeldet(cfg, db):
    cfg["team"] = {"reservierung_tage": "zwei"}
    with pytest.raises(ValueError, match="reservierung_tage"):
        erstelle_server(cfg, db, BASIS, port=0)


def dublette_herstellen(db, n=2):
    """Macht die ersten n Inserate zu Dubletten desselben Fahrzeugs (gleiche Marke, EZ, Ort, km, Titel)."""
    ids = [r[0] for r in db.con.execute("SELECT id FROM anzeigen WHERE marke IS NOT NULL AND ez_jahr IS NOT NULL AND km IS NOT NULL "
                                        "AND ort IS NOT NULL ORDER BY id LIMIT ?", (n,))]
    erste = db.con.execute("SELECT titel, marke, ez_jahr, km, ort, preis FROM anzeigen WHERE id=?", (ids[0],)).fetchone()
    for x in ids[1:]:
        db.con.execute("UPDATE anzeigen SET titel=?, marke=?, ez_jahr=?, km=?, ort=?, preis=? WHERE id=?", (*tuple(erste), x))
    db.con.commit()
    return ids


def test_http_dublette_wirkt_auf_die_gruppe(server, team, db):
    a, b = dublette_herstellen(db)
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    assert ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    s, antwort, _ = carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})
    assert s == 409 and f"Dublette {a}" in antwort["fehler"]
    assert "Ben (BE)" in antwort["fehler"] and antwort["team"]["dublette_von"]["id"] == a
    assert bearbeitung(db, b) is None
    assert carl("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"})[0] == 409
    assert carl("POST", "/api/nachgefasst", {"id": b, "text": "x"})[0] == 409
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (b,)).fetchone()[0] == "neu" and bearbeitung(db, b) is None
    # Lesen: die Dublette erscheint nicht als frei, Ben sieht sie als eigene Gruppe
    liste = {f["id"]: f["team"] for f in carl("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert liste[b]["zustand"] == "frei" and liste[b]["dublette_von"]["bearbeiter"]["name"] == "Ben" and liste[b]["darf"]["uebernehmen"] is False
    assert b not in {f["id"] for f in carl("GET", "/api/fahrzeuge?filter=alle&wer=frei")[1]}
    assert b not in {f["id"] for f in ben("GET", "/api/fahrzeuge?filter=alle&wer=frei")[1]}          # auch für Ben nicht „frei“
    assert ben("GET", "/api/team")[1]["bearbeitung"][b]["dublette_von"]["mein"] is True
    assert ben("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 200                             # eigene Gruppe: kein Konflikt
    # Andere Status der Dublette (ohne Kontakt) bleiben für alle möglich
    assert carl("POST", "/api/status", {"id": b, "status": "uninteressant"})[0] == 409                # b gehört jetzt Ben
    ben("POST", f"/api/bearbeitung/{b}/abgeben", {})
    ben("POST", f"/api/bearbeitung/{a}/abgeben", {})
    assert carl("POST", f"/api/bearbeitung/{b}/uebernehmen", {})[0] == 200                            # freigegeben


def test_http_zwei_threads_gleichzeitig_genau_eine_200(server, team, db):
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    ids = ids_der_liste(ben, "alle", n=20)
    for ad_id in ids:
        ergebnis = _gleichzeitig([lambda ad_id=ad_id: ben("POST", f"/api/bearbeitung/{ad_id}/uebernehmen", {})[0],
                                  lambda ad_id=ad_id: carl("POST", f"/api/bearbeitung/{ad_id}/uebernehmen", {})[0]])
        assert sorted(ergebnis) == [200, 409], (ad_id, ergebnis)
    # und über den Kontakt-Weg: jedes Inserat hält jetzt einer von beiden, nur dieser darf kontaktieren
    for ad_id in ids[:10]:
        ergebnis = _gleichzeitig([lambda ad_id=ad_id: ben("POST", "/api/status", {"id": ad_id, "status": "kontaktiert", "text": "B"})[0],
                                  lambda ad_id=ad_id: carl("POST", "/api/status", {"id": ad_id, "status": "kontaktiert", "text": "C"})[0]])
        assert sorted(ergebnis) == [200, 409], ergebnis                                      # nur der Halter darf kontaktieren


def test_http_team_uebersicht_zaehler_und_bearbeitung(server, team, db):
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    a, b, c, d = ids_der_liste(anna, "alle", n=4)
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    carl("POST", "/api/status", {"id": b, "status": "kontaktiert", "text": "x"})
    db.con.execute("UPDATE anzeigen SET status='kontaktiert' WHERE id=?", (c,))                       # Altbestand
    db.con.commit()
    s, t, r = ben("GET", "/api/team")
    assert s == 200 and r.getheader("Cache-Control") == "no-store"
    assert t["aktiv"] and t["ich"] == {"id": team.ids["Ben"], "name": "Ben", "kuerzel": "BE", "aktiv": True, "rolle": "mitarbeiter"}
    assert [(n["name"], n["kuerzel"], n["aktiv"]) for n in t["nutzer"]] == [("Anna", "AN", True), ("Ben", "BE", True), ("Carl", "CA", True)]
    assert [z["name"] for z in t["zaehler"]] == ["Ben"]                                              # Mitarbeiter: nur die eigene Zeile (M5)
    assert t["zaehler"][0]["reserviert"] == 1 and t["zaehler"][0]["uebernommen_heute"] == 1 and t["zaehler"][0]["kuerzel"] == "BE"
    ta = anna("GET", "/api/team")[1]
    je = {z["name"]: z for z in ta["zaehler"]}                                                        # Inhaber: alle
    assert set(je) == {"Anna", "Ben", "Carl"}
    assert je["Ben"]["reserviert"] == 1 and je["Ben"]["uebernommen_heute"] == 1 and je["Carl"]["kontakte_heute"] == 1
    assert je["Carl"]["in_arbeit"] == 1 and je["Anna"]["reserviert"] == 0 and je["Ben"]["kuerzel"] == "BE"
    assert t["ohne_zuordnung"] == 1 and t["verwaist"] == 0 and t["reservierung_tage"] == 2
    assert set(t["bearbeitung"]) == {a, b, c} and d not in t["bearbeitung"]                          # nur nicht freie
    assert t["bearbeitung"][a]["zustand"] == "reserviert" and t["bearbeitung"][b]["zustand"] == "kontaktiert"
    assert t["bearbeitung"][c]["zustand"] == "ohne_zuordnung" and t["bearbeitung"][c]["bearbeiter"] is None
    # Zähler und Zustände stammen aus demselben Stand: Anzahl je Zustand stimmt überein
    zustaende = [o["zustand"] for o in t["bearbeitung"].values()]
    assert zustaende.count("reserviert") == sum(z["reserviert"] for z in ta["zaehler"])
    assert zustaende.count("ohne_zuordnung") == t["ohne_zuordnung"]
    # ohne Anmeldung: nichts
    assert Client(server.server_address[1])("GET", "/api/team")[0] == 401
    # Kürzel in /api/ich und /api/nutzer
    assert ben("GET", "/api/ich")[1]["nutzer"]["kuerzel"] == "BE" and anna("GET", "/api/ich")[1]["nutzer"]["kuerzel"] == "AN"
    assert {n["name"]: n["kuerzel"] for n in ben("GET", "/api/nutzer")[1]} == {"Anna": "AN", "Ben": "BE", "Carl": "CA"}


def test_http_kuerzel_bleiben_stabil_wenn_kollegen_dazukommen(server, team, db):
    ben = anmelden(server, "Ben")
    vorher = {n["name"]: n["kuerzel"] for n in ben("GET", "/api/nutzer")[1]}
    team.nutzer_anlegen("Bernd", "sicher1234")
    team.nutzer_anlegen("Anna Berg", "sicher1234")
    nachher = {n["name"]: n["kuerzel"] for n in ben("GET", "/api/nutzer")[1]}
    assert {k: nachher[k] for k in vorher} == vorher and nachher["Bernd"] == "BER" and nachher["Anna Berg"] == "AB"


def test_service_worker_speichert_team_stand_nicht_zwischen():
    """Positivliste (G0): nur Daten für die Arbeit vor Ort; Team-Stand und Personendaten nie im Speicher des Geräts."""
    sw = (BASIS / "wmscout" / "web" / "static" / "sw.js").read_text(encoding="utf-8")
    muster = [re.compile(m) for m in re.findall(r"/(\^.*?)/\.test\(url\.pathname\)", sw)]
    assert len(muster) == 4

    def lesbar(pfad):
        return any(m.search(pfad) for m in muster)
    for pfad in ("/m", "/static/mobil.js", "/manifest.webmanifest", "/fotos/3/a.jpg", "/api/besichtigung/3", "/api/fahrzeug/k-1", "/api/heute"):
        assert lesbar(pfad), pfad
    for pfad in ("/api/team", "/api/suchlauf", "/api/verkaufsanfrage/1", "/api/verkaufsanfragen", "/api/ankauf/1", "/api/ankaeufe",
                 "/api/kalkulation/1", "/anfrage-fotos/1/a.jpg", "/protokoll/1", "/api/haendler/fahrzeuge", "/api/auktion/1", "/mx"):
        assert not lesbar(pfad), pfad
    assert "antwort.status === 401" in sw and int(re.search(r"VERSION = .wm-scout-(\d+)", sw).group(1)) >= 7   # 7: Inserat einlesen (P2-05)


def test_zwischenspeicher_wird_von_uebernahme_nicht_verworfen_team_aber_frisch(server, team, db):
    """Team-Daten kommen je Anfrage frisch aus der Datenbank, auch wenn die Bewertung (30 s) zwischengespeichert ist."""
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    a = ids_der_liste(ben, "alle", n=1)[0]
    assert carl("GET", f"/api/fahrzeug/{a}")[1]["team"]["zustand"] == "frei"                         # füllt den Zwischenspeicher
    ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})
    assert carl("GET", f"/api/fahrzeug/{a}")[1]["team"]["zustand"] == "reserviert"
    ben("POST", f"/api/bearbeitung/{a}/abgeben", {})
    assert carl("GET", f"/api/fahrzeug/{a}")[1]["team"]["zustand"] == "frei"


# ======================================================================= CSV und Report
def test_csv_team_spalten_am_ende_ohne_team_leer(cfg, db, importiert, team, tmp_path):
    zeilen = bewerte_alle(cfg, db, BASIS)
    ohne = schreibe_ausgaben(cfg, zeilen, BASIS)
    with open(ohne["csv"], encoding="utf-8-sig", newline="") as f:
        z_ohne = list(csv.reader(f, delimiter=";"))
    assert z_ohne[0][-4:] == ["URL", "Bearbeiter", "Übernommen am", "Kontaktiert von"] and z_ohne[0][-5] == "Erstmals gesehen"
    assert all(len(r) == len(z_ohne[0]) for r in z_ohne) and all(r[-3:] == ["", "", ""] for r in z_ohne[1:])
    a, b = z_ohne[1][0], z_ohne[2][0]
    db.setze_status(a, "kontaktiert", text="x", nutzer_id=team.ids["Ben"])
    db.uebernimm(b, team.ids["Carl"], NEUN)
    sicht = lade_team_sicht(db, 0, jetzt=JETZT)
    mit = schreibe_ausgaben(cfg, bewerte_alle(cfg, db, BASIS), BASIS, team=sicht)
    with open(mit["csv"], encoding="utf-8-sig", newline="") as f:
        z_mit = {r[0]: r for r in csv.reader(f, delimiter=";")}
    assert z_mit[a][-3] == "Ben" and z_mit[a][-2].startswith("20") and z_mit[a][-1] == "Ben"
    assert z_mit[b][-3:] == ["Carl", NEUN, ""]
    nicht_beteiligt = [r for i, r in z_mit.items() if i not in (a, b, "ID")]
    assert nicht_beteiligt and all(r[-3:] == ["", "", ""] for r in nicht_beteiligt)
    assert {r[0] for r in z_ohne} == set(z_mit)                                                       # gleiche Inserate, nur Spalten dazu


def _ohne_zeit(html: str) -> str:
    return re.sub(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", "<ZEIT>", html)           # „Stand“ des Reports


def test_statischer_report_ohne_team_unveraendert(cfg, db, importiert, team):
    """Der HTML-Report kennt keine Team-Daten: gleiche Bytes (bis auf den Zeitstempel) ohne und mit Team-Sicht, auch wenn Inserate
    reserviert/kontaktiert sind – und jedes Inserat der Eingabe steht darin (Referenz: die bewerteten Zeilen, nicht der Renderer)."""
    zeilen = bewerte_alle(cfg, db, BASIS)
    ohne = Path(schreibe_ausgaben(cfg, zeilen, BASIS)["html"]).read_text(encoding="utf-8")
    assert set(schreibe_ausgaben(cfg, zeilen, BASIS)) == {"html", "csv", "zaehl"}
    a, b = zeilen[0]["a"]["id"], zeilen[1]["a"]["id"]
    db.setze_status(a, "kontaktiert", text="x", nutzer_id=team.ids["Ben"])
    db.uebernimm(b, team.ids["Carl"], NEUN)
    sicht = lade_team_sicht(db, 0, jetzt=JETZT)
    mit = Path(schreibe_ausgaben(cfg, zeilen, BASIS, team=sicht)["html"]).read_text(encoding="utf-8")          # dieselben Zeilen
    assert sicht.objekt(zeilen[0])["zustand"] == "kontaktiert" and sicht.objekt(zeilen[1])["zustand"] == "reserviert"
    assert _ohne_zeit(mit) == _ohne_zeit(ohne)
    for wort in ("Bearbeiter", "Übernommen", "uebernehmen", "Reserviert"):
        assert wort not in ohne and wort not in mit
    assert render_html(cfg, zeilen, BASIS)[0].count("<tr") == ohne.count("<tr") > 0
    assert len(zeilen) >= 20
    for z in zeilen:                                                    # jedes bewertete Inserat steht im Report (Titel maskiert HTML-Zeichen)
        assert z["a"]["url"] in ohne, z["a"]["id"]


def test_bewerte_alle_liefert_dubletten_ids(cfg, db, importiert):
    a, b = dublette_herstellen(db)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert zeilen[a]["dubletten_ids"] == [b] and zeilen[b]["dubletten_ids"] == [a]
    andere = [z for i, z in zeilen.items() if i not in (a, b)]
    assert andere and all(isinstance(z["dubletten_ids"], list) for z in andere)
