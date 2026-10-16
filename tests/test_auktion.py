"""Phase D – Demo-Auktionen (ADR-027): Zustandsmaschine, atomare Gebote, Verlängerung, Mindestpreis, Protokoll, Zugriffsschutz."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import multiprocessing
import re
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from tests import prozess_helfer
from tests.test_cli import _scout
from tests.test_haendler import MIT_WEITERGABE
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.auktion import AuktionSpeicher, AuktionsFehler, einstellungen, zeit
from wmscout.datenbank import Datenbank
from wmscout.haendler import HaendlerSpeicher
from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage

T0 = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


def _aufbau(db, tmp_path, standorte=3):
    """Freigegebene Anfrage (Preisvorstellung 39.500 €) und ``standorte`` geprüfte Standorte."""
    vk, hs = VerkaufSpeicher(db, tmp_path / "fotos"), HaendlerSpeicher(db)
    anfrage = vk.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["id"]
    vk.setze_freigabe(anfrage, True, None)
    sids = [hs.standort_anlegen(f"Filiale {i}") for i in range(standorte)]
    for sid in sids:
        hs.setze_standort_status(sid, "geprueft", None)
    return vk, anfrage, sids


@pytest.fixture
def auk(db, tmp_path):
    vk, anfrage, sids = _aufbau(db, tmp_path)
    a = AuktionSpeicher(db, {})
    return {"a": a, "vk": vk, "anfrage": anfrage, "sids": sids, "db": db}


def _gebot(a, aid, sid, betrag, wid=None, jetzt=T0 + timedelta(hours=1)):
    return a.gebot_abgeben(aid, sid, 100 + sid, betrag, wid or f"id-{sid}-{betrag}-xx", jetzt=jetzt)


# ---------------------------------------------------------------- Konfiguration und Anlegen
def test_einstellungen_standard_und_unsinn():
    assert einstellungen({}) == {"laufzeit_stunden": 24, "laufzeit_min_stunden": 1, "laufzeit_max_stunden": 168, "schritt": 100,
                                 "verlaengerung_minuten": 2, "startpreis_anteil": 0.7}
    for falsch in ({"schritt": True}, {"schritt": 0}, {"schritt": 50.5}, {"laufzeit_stunden": 500}, {"startpreis_anteil": 2},
                   {"verlaengerung_minuten": "zwei"}):
        with pytest.raises(ValueError, match="auktion"):
            einstellungen({"auktion": falsch})


def test_anlegen_mit_standardwerten_nur_freigegeben_und_nur_einmal(auk, tmp_path):
    a, vk, anfrage = auk["a"], auk["vk"], auk["anfrage"]
    ohne = vk.anlegen(pruefe_anfrage({**MIT_WEITERGABE, "weitergabe": False}, jahr=2026), None, "x")["id"]
    with pytest.raises(AuktionsFehler, match="Freigabe"):
        a.anlegen(ohne, 1, jetzt=T0)
    aid = a.anlegen(anfrage, 1, jetzt=T0)
    x = a.lade(aid, jetzt=T0)
    assert (x["startpreis"], x["mindestpreis"], x["schritt"]) == (27600, 39500, 100)    # 70 % abgerundet auf 100 €, Mindestpreis = Wunsch
    assert (x["start_utc"], x["ende_utc"], x["status"], x["demo"]) == ("2026-10-16T10:00:00Z", "2026-10-17T10:00:00Z", "laeuft", True)
    with pytest.raises(AuktionsFehler, match="schon"):
        a.anlegen(anfrage, 1, jetzt=T0)
    with pytest.raises(sqlite3.IntegrityError):              # zweite Sicherung: Index in der Datenbank
        with auk["db"].transaktion():
            auk["db"].con.execute("INSERT INTO auktionen (anfrage_id, startpreis, schritt, start_utc, ende_utc) VALUES (?,?,?,?,?)",
                                  (anfrage, 1, 1, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
    for falsch in ({"laufzeit_stunden": 0}, {"laufzeit_stunden": 169}, {"startpreis": 1.5}, {"startpreis": "100"}, {"mindestpreis": True}):
        with pytest.raises(AuktionsFehler):
            a.anlegen(ohne, 1, jetzt=T0, **falsch)
    assert [v["neu"] for v in vk.lade(anfrage)["verlauf"] if v["ereignis"] == "auktion"][0].startswith("Demo-Auktion gestartet")


def test_ohne_preisvorstellung_startpreis_pflicht_und_ohne_mindestpreis(db, tmp_path):
    vk, anfrage, _ = _aufbau(db, tmp_path, 1)
    db.con.execute("UPDATE verkaufsanfragen SET preisvorstellung=NULL WHERE id=?", (anfrage,))
    db.con.commit()
    a = AuktionSpeicher(db, {})
    with pytest.raises(AuktionsFehler, match="Startpreis"):
        a.anlegen(anfrage, 1, jetzt=T0)
    x = a.lade(a.anlegen(anfrage, 1, startpreis=5000, jetzt=T0), jetzt=T0)
    assert x["mindestpreis"] is None and x["mindestpreis_erreicht"] is None


# ---------------------------------------------------------------- Gebote
def test_gebotsregeln_schritt_selbstueberbieten_ganzzahl(auk):
    a, s1, s2, s3 = auk["a"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, jetzt=T0)
    with pytest.raises(AuktionsFehler, match="Mindestgebot ist jetzt 27600"):
        _gebot(a, aid, s1, 27599)
    _gebot(a, aid, s1, 27600)
    with pytest.raises(AuktionsFehler, match="bereits das Höchstgebot"):
        _gebot(a, aid, s1, 40000)                                       # wer führt, überbietet sich nicht selbst
    with pytest.raises(AuktionsFehler) as fehler:
        _gebot(a, aid, s2, 27650)
    assert fehler.value.extra == {"mindestgebot": 27700}
    for falsch in (27700.0, "27700", True, None, -5, 10_000_001):
        with pytest.raises(AuktionsFehler):
            _gebot(a, aid, s2, falsch)
    _gebot(a, aid, s2, 27700)
    _gebot(a, aid, s3, 30000)
    assert [g["betrag"] for g in a.lade(aid, jetzt=T0)["gebote"]] == [30000, 27700, 27600]
    with pytest.raises(sqlite3.IntegrityError):                          # zweite Sicherung: gleicher Betrag zweimal unmöglich
        with auk["db"].transaktion():
            auk["db"].con.execute("INSERT INTO gebote (auktion_id, standort_id, nutzer_id, betrag, zeitpunkt_utc, wiederholungs_id) "
                                  "VALUES (?,?,?,?,?,?)", (aid, s1, 1, 30000, "x", "abcdefgh"))


def test_wiederholungs_id_zaehlt_nur_einmal(auk):
    a, s1, s2, _ = auk["a"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, jetzt=T0)
    erst = _gebot(a, aid, s1, 28000, "netz-weg-1234")
    noch = _gebot(a, aid, s1, 28000, "netz-weg-1234")
    assert erst["wiederholt"] is False and noch["wiederholt"] is True and noch["gebot_id"] == erst["gebot_id"]
    with pytest.raises(AuktionsFehler, match="anderen Gebot"):
        _gebot(a, aid, s1, 29000, "netz-weg-1234")
    with pytest.raises(AuktionsFehler, match="Wiederholungs-ID"):
        _gebot(a, aid, s2, 29000, "kurz")
    assert len(a.lade(aid, jetzt=T0)["gebote"]) == 1 and a.pruefe_protokoll()["ok"]


def test_gebot_in_den_letzten_minuten_verlaengert(auk):
    a, s1, s2, _ = auk["a"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, laufzeit_stunden=1, jetzt=T0)
    assert _gebot(a, aid, s1, 30000, jetzt=T0 + timedelta(minutes=57))["verlaengert"] is False      # 3 Minuten vor Schluss
    r = _gebot(a, aid, s2, 30100, jetzt=T0 + timedelta(minutes=59, seconds=30))                   # 30 s vor Schluss
    assert r["verlaengert"] and r["ende_utc"] == "2026-10-16T11:01:30Z"
    _gebot(a, aid, s1, 30200, jetzt=T0 + timedelta(minutes=61))                                   # nach altem Ende, vor neuem
    with pytest.raises(AuktionsFehler, match="beendet"):
        _gebot(a, aid, s2, 30300, jetzt=T0 + timedelta(minutes=63, seconds=1))
    x = a.lade(aid, jetzt=T0 + timedelta(minutes=64))
    assert x["status"] == "beendet" and x["hoechstgebot"] == 30200 and x["ende_utc"] == "2026-10-16T11:03:00Z"


def test_nach_ende_kein_gebot_auch_wenn_der_abschluss_noch_aussteht(auk, monkeypatch):
    """Zweite Sicherung: Auch wenn der Abschluss beim Zugriff nicht lief (z. B. Datenbank kurz belegt), zählt kein Gebot nach dem Ende."""
    a, s1 = auk["a"], auk["sids"][0]
    aid = a.anlegen(auk["anfrage"], 1, laufzeit_stunden=1, jetzt=T0)
    monkeypatch.setattr(a, "abschliessen_faellige", lambda jetzt=None: 0)
    with pytest.raises(AuktionsFehler, match="beendet"):
        _gebot(a, aid, s1, 30000, jetzt=T0 + timedelta(hours=1))
    assert a.lade(aid, jetzt=T0)["gebote"] == []


def test_abschluss_bei_zugriff_idempotent_und_ergebnisse(auk, tmp_path):
    a, vk, s1 = auk["a"], auk["vk"], auk["sids"][0]
    aid = a.anlegen(auk["anfrage"], 1, laufzeit_stunden=2, jetzt=T0)
    _gebot(a, aid, s1, 30000)
    assert a.abschliessen_faellige(T0 + timedelta(hours=1)) == 0
    assert a.abschliessen_faellige(T0 + timedelta(hours=2)) == 1 and a.abschliessen_faellige(T0 + timedelta(hours=3)) == 0
    x = a.lade(aid, jetzt=T0 + timedelta(hours=3))
    assert (x["status"], x["ergebnis"], x["mindestpreis_erreicht"]) == ("beendet", "unter_mindestpreis", False)
    assert [e["ereignis"] for e in x["protokoll"]] == ["gestartet", "gebot", "beendet"]
    # zweite Anfrage: kein Gebot → kein Zuschlag möglich
    zweite = vk.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["id"]
    vk.setze_freigabe(zweite, True, None)
    leer = a.anlegen(zweite, 1, laufzeit_stunden=1, jetzt=T0)
    assert a.lade(leer, jetzt=T0 + timedelta(hours=2))["ergebnis"] == "kein_gebot"
    with pytest.raises(AuktionsFehler, match="Ohne Gebot"):
        a.entscheiden(leer, 1, True, jetzt=T0 + timedelta(hours=2))
    a.entscheiden(leer, 1, False, jetzt=T0 + timedelta(hours=2))
    assert a.lade(leer)["status"] == "abgelehnt"
    a.anlegen(zweite, 1, jetzt=T0 + timedelta(hours=3))                  # nach „kein Zuschlag“ neue Auktion möglich


def test_zuschlag_nur_nach_ende_einmal_und_danach_keine_neue_auktion(auk):
    a, s1, s2, _ = auk["a"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, laufzeit_stunden=1, jetzt=T0)
    _gebot(a, aid, s1, 39000, jetzt=T0 + timedelta(minutes=10))
    _gebot(a, aid, s2, 39500, jetzt=T0 + timedelta(minutes=20))
    with pytest.raises(AuktionsFehler, match="nach dem Ende"):
        a.entscheiden(aid, 1, True, jetzt=T0 + timedelta(minutes=30))
    nach = T0 + timedelta(hours=2)
    a.entscheiden(aid, 1, True, jetzt=nach)
    with pytest.raises(AuktionsFehler, match="nur einmal"):
        a.entscheiden(aid, 1, False, jetzt=nach)
    with pytest.raises(AuktionsFehler, match="laufende"):
        a.abbrechen(aid, 1, jetzt=nach)
    with pytest.raises(AuktionsFehler, match="zugeschlagene"):
        a.anlegen(auk["anfrage"], 1, jetzt=nach)
    x = a.lade(aid, jetzt=nach)
    assert (x["status"], x["ergebnis"], x["fuehrend"]) == ("zugeschlagen", "mindestpreis_erreicht", "Filiale 1")
    sicht = {s: a.fuer_standort(s, jetzt=nach) for s in (s1, s2)}
    assert sicht[s2][0]["zuschlag_fuer_dich"] is True and sicht[s1][0]["zuschlag_fuer_dich"] is False
    assert [v["neu"] for v in auk["vk"].lade(auk["anfrage"])["verlauf"] if v["ereignis"] == "auktion"][-1].startswith("Demo-Zuschlag bestätigt: Filiale 1")


def test_abbruch_und_keine_gebote_nach_entzug_der_freigabe_oder_sperre(auk):
    a, vk, hs, s1, s2, _ = auk["a"], auk["vk"], HaendlerSpeicher(auk["db"]), *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, jetzt=T0)
    hs.setze_standort_status(s1, "gesperrt", None)
    with pytest.raises(AuktionsFehler, match="geprüfte") as fehler:
        _gebot(a, aid, s1, 30000)
    assert fehler.value.status == 403
    vk.setze_freigabe(auk["anfrage"], False, None)
    with pytest.raises(AuktionsFehler, match="nicht mehr freigegeben"):
        _gebot(a, aid, s2, 30000)
    assert a.fuer_standort(s2, jetzt=T0) == []                          # ohne Freigabe auch nicht sichtbar
    a.abbrechen(aid, 1, "Verkäufer hat anders verkauft", jetzt=T0)
    assert a.lade(aid)["status"] == "abgebrochen" and a.lade(aid)["grund"] == "Verkäufer hat anders verkauft"


def test_bietersicht_ohne_mindestpreis_und_ohne_andere_standorte(auk):
    a, s1, s2, _ = auk["a"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, jetzt=T0)
    _gebot(a, aid, s1, 40000)
    sicht = a.fuer_standort(s2, jetzt=T0 + timedelta(hours=1))
    assert len(sicht) == 1
    text = str(sicht)
    assert "39500" not in text and "Filiale" not in text and "mindestpreis'" not in text and "gebote'" not in text
    assert sicht[0]["mindestpreis_erreicht"] is True and sicht[0]["du_fuehrst"] is False and sicht[0]["naechstes_mindestgebot"] == 40100
    assert sicht[0]["bieten_moeglich"] and sicht[0]["rest_sek"] == 23 * 3600
    assert a.fuer_standort(s1, jetzt=T0)[0]["du_fuehrst"] and not a.fuer_standort(s1, jetzt=T0)[0]["bieten_moeglich"]
    assert not a.fuer_standort(0, jetzt=T0)[0]["bieten_moeglich"]          # Team-Vorschau bietet nicht


# ---------------------------------------------------------------- Protokoll
def test_protokoll_ist_nur_anfuegbar_und_manipulation_faellt_auf(auk):
    a, db, s1, s2, _ = auk["a"], auk["db"], *auk["sids"]
    aid = a.anlegen(auk["anfrage"], 1, jetzt=T0)
    _gebot(a, aid, s1, 30000)
    _gebot(a, aid, s2, 31000)
    p = a.pruefe_protokoll()
    assert p["ok"] and p["eintraege"] == 3 and len(p["letzter_hash"]) == 64
    for sql in ("UPDATE gebote SET betrag=99999", "DELETE FROM gebote", "UPDATE auktion_protokoll SET ereignis='x'",
                "DELETE FROM auktion_protokoll WHERE id=2"):
        with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
            db.con.execute(sql)
        db.con.rollback()
    # wer die Trigger entfernt (Schreibzugriff auf die Datei), fällt bei der Prüfung auf
    db.con.executescript("DROP TRIGGER gebote_kein_update; UPDATE gebote SET betrag=99999 WHERE betrag=31000;")
    assert a.pruefe_protokoll()["fehler"] == [f"Gebot {db.con.execute('SELECT MAX(id) FROM gebote').fetchone()[0]} passt nicht zum Protokoll"]
    db.con.executescript("DROP TRIGGER auktion_protokoll_kein_update; UPDATE auktion_protokoll SET daten_json='{}' WHERE id=1;")
    assert "Eintrag 1: Inhalt verändert" in a.pruefe_protokoll()["fehler"]
    db.con.executescript("DROP TRIGGER auktion_protokoll_kein_delete; DELETE FROM auktion_protokoll WHERE id=2;")
    fehler = a.pruefe_protokoll()["fehler"]
    assert "Eintrag 2 fehlt (nächster ist 3)" in fehler and "Eintrag 3: Verkettung gebrochen" in fehler


# ---------------------------------------------------------------- Gleichzeitigkeit
def test_gleichzeitige_gebote_in_threads_genau_ein_hoechstgebot(auk, cfg):
    """Viele Verbindungen bieten gleichzeitig denselben Betrag: genau eines gewinnt je Runde."""
    a0, aid = auk["a"], auk["a"].anlegen(auk["anfrage"], 1)
    sids, runden, fehler = auk["sids"], 6, []
    start = threading.Barrier(len(sids))
    ergebnis = {sid: [] for sid in sids}

    def bieter(sid):
        db = Datenbank(cfg["ausgabe"]["datenbank"])
        a = AuktionSpeicher(db, {})
        try:
            for r in range(runden):
                start.wait(30)
                try:
                    ergebnis[sid].append(a.gebot_abgeben(aid, sid, sid, 27600 + 100 * r, f"t-{sid}-{r}-xxxx")["gebot_id"])
                except AuktionsFehler:
                    ergebnis[sid].append(None)
        except Exception as e:  # noqa: BLE001
            fehler.append(e)
        finally:
            db.con.close()

    t = [threading.Thread(target=bieter, args=(s,)) for s in sids]
    for x in t:
        x.start()
    for x in t:
        x.join(60)
    assert not fehler
    for r in range(runden):
        assert sum(ergebnis[s][r] is not None for s in sids) == 1, r
    gebote = a0.lade(aid)["gebote"]
    assert [g["betrag"] for g in gebote] == [27600 + 100 * r for r in reversed(range(runden))]
    assert all(x["standort_id"] != y["standort_id"] for x, y in zip(gebote, gebote[1:], strict=False))
    assert a0.pruefe_protokoll()["ok"]


def test_getrennte_prozesse_bieten_gleichzeitig_genau_ein_gueltiges_ergebnis(tmp_path):
    """Echte Prozesse (spawn) wie mehrere App-Instanzen: je Runde bieten alle denselben Betrag zur selben Zeit."""
    pfad = str(tmp_path / "a.sqlite")
    db = Datenbank(pfad)
    _, anfrage, sids = _aufbau(db, tmp_path, 4)
    aid = AuktionSpeicher(db, {}).anlegen(anfrage, 1)
    db.con.close()
    runden = 8
    betraege = [27600 + 100 * r for r in range(runden)]
    ctx = multiprocessing.get_context("spawn")
    barriere, ergebnisse = ctx.Barrier(len(sids)), ctx.Queue()
    prozesse = [ctx.Process(target=prozess_helfer.bieter, args=(pfad, nr, aid, sid, 200 + nr, betraege, barriere, ergebnisse))
                for nr, sid in enumerate(sids)]
    for p in prozesse:
        p.start()
    meldungen = dict(ergebnisse.get(timeout=180) for _ in prozesse)
    for p in prozesse:
        p.join(30)
    alle = [m for erg in meldungen.values() for m in erg]
    assert not [m for m in alle if str(m[0]).startswith("FEHLER")] and not any(offen for _, offen in alle)
    for r in range(runden):
        assert sum(isinstance(meldungen[nr][r][0], int) for nr in meldungen) == 1, f"Runde {r}: {[meldungen[n][r] for n in meldungen]}"
    db = Datenbank(pfad)
    a = AuktionSpeicher(db, {})
    gebote = a.lade(aid)["gebote"]
    assert [g["betrag"] for g in gebote] == list(reversed(betraege)) and a.pruefe_protokoll()["ok"]
    assert db.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.con.close()


# ---------------------------------------------------------------- API
@pytest.fixture
def markt(server, team, db, tmp_path):
    """Anna (Inhaberin), Ben (Team); Standorte Nord (Hugo) und Süd (Ida) geprüft; eine freigegebene Anfrage."""
    hs = HaendlerSpeicher(db)
    sids = [hs.standort_anlegen(n) for n in ("Filiale Nord", "Filiale Süd")]
    for sid in sids:
        hs.setze_standort_status(sid, "geprueft", None)
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sids[0])
    team.nutzer_anlegen("Ida", "sicher1234", "haendler", standort_id=sids[1])
    anna = anmelden(server, "Anna")
    anfrage = anna("POST", "/api/verkaufsanfrage", MIT_WEITERGABE)[1]["id"]
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/freigabe", {"freigeben": True})
    return {"anna": anna, "ben": anmelden(server, "Ben"), "hugo": anmelden(server, "Hugo"), "ida": anmelden(server, "Ida"),
            "anfrage": anfrage, "sids": sids}


def test_api_ablauf_inhaber_startet_haendler_bieten_inhaber_entscheidet(markt, db, tmp_path):
    anna, ben, hugo, ida, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["ida"], markt["anfrage"]
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {})[0] == 403          # nur Inhaber
    assert hugo("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {})[0] == 403
    s, d, _ = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 30000, "mindestpreis": None, "laufzeit_stunden": 2})
    assert s == 200
    aid = d["id"]
    assert anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {})[0] == 409
    s, liste, _ = hugo("GET", "/api/haendler/auktionen")
    assert s == 200 and [x["id"] for x in liste] == [aid] and liste[0]["naechstes_mindestgebot"] == 30000
    assert hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30000})[0] == 400              # ohne Wiederholungs-ID
    s, d, _ = hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30000, "wiederholungs_id": "abc123def456"})
    assert s == 200 and d["wiederholt"] is False
    assert hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30000, "wiederholungs_id": "abc123def456"})[1]["wiederholt"]
    s, d, _ = ida("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30050, "wiederholungs_id": "ida-0000001"})
    assert s == 409 and d["mindestgebot"] == 30100
    assert ida("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30100, "wiederholungs_id": "ida-0000002"})[0] == 200
    assert ben("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 40000, "wiederholungs_id": "ben-0000001"})[0] == 403
    assert hugo("GET", f"/api/auktion/{aid}")[0] == 403                                   # Gesamtsicht nur Team
    s, x, _ = ben("GET", f"/api/auktion/{aid}")
    assert s == 200 and [g["standort"] for g in x["gebote"]] == ["Filiale Süd", "Filiale Nord"] and x["pruefung"]["ok"]
    assert [e["ereignis"] for e in x["protokoll"]] == ["gestartet", "gebot", "gebot"]
    assert anna("GET", f"/api/verkaufsanfrage/{anfrage}")[1]["auktionen"][0]["hoechstgebot"] == 30100
    assert anna("POST", f"/api/auktion/{aid}/zuschlag", {})[0] == 409                     # läuft noch
    vorbei = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.con.execute("UPDATE auktionen SET start_utc=?, ende_utc=? WHERE id=?", (zeit(vorbei - timedelta(hours=2)), zeit(vorbei), aid))
    db.con.commit()                                                                      # Ablauf vorziehen statt warten
    assert hugo("GET", "/api/haendler/auktionen")[1][0]["status"] == "beendet"            # Abschluss beim Zugriff
    assert ben("POST", f"/api/auktion/{aid}/zuschlag", {})[0] == 403
    assert anna("POST", f"/api/auktion/{aid}/zuschlag", {})[0] == 200
    assert ida("GET", "/api/haendler/auktionen")[1][0]["zuschlag_fuer_dich"] is True
    assert hugo("GET", "/api/haendler/auktionen")[1][0]["zuschlag_fuer_dich"] is False
    node = shutil.which("node")
    if node:
        for pfad, wer in (("/haendler", hugo), ("/anfragen", anna)):
            html = wer("GET", pfad)[1]
            datei = tmp_path / "s.js"
            datei.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
            assert subprocess.run([node, "--check", str(datei)], capture_output=True, timeout=60).returncode == 0, pfad


def test_api_abbrechen_und_ungepruefter_standort(markt, db):
    anna, hugo, anfrage = markt["anna"], markt["hugo"], markt["anfrage"]
    aid = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {})[1]["id"]
    HaendlerSpeicher(db).setze_standort_status(markt["sids"][0], "offen", None)
    assert hugo("GET", "/api/haendler/auktionen")[0] == 403
    assert hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 30000, "wiederholungs_id": "hugo-000001"})[0] == 403
    assert markt["ben"]("POST", f"/api/auktion/{aid}/abbrechen", {})[0] == 403
    assert anna("POST", f"/api/auktion/{aid}/abbrechen", {"grund": "Test"})[0] == 200
    assert anna("POST", f"/api/auktion/{aid}/abbrechen", {})[0] == 409
    assert anna("POST", "/api/auktion/999/zuschlag", {})[0] == 404


def test_cli_auktion_liste_und_pruefen(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    _, anfrage, sids = _aufbau(db, tmp_path, 2)
    a = AuktionSpeicher(db, {})
    aid = a.anlegen(anfrage, 1)
    a.gebot_abgeben(aid, sids[0], 1, 30000, "cli-test-0001")
    db.con.close()
    r = _scout(cfg, tmp_path, "auktion", "liste")
    assert r.returncode == 0 and "läuft" in r.stdout and "30000" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "auktion", "pruefen")
    assert r.returncode == 0 and "2 Protokolleinträge" in r.stdout and "unverändert" in r.stdout, r.stderr
    con = sqlite3.connect(cfg["ausgabe"]["datenbank"])
    con.executescript("DROP TRIGGER auktion_protokoll_kein_update; UPDATE auktion_protokoll SET zeitpunkt_utc='2020-01-01T00:00:00Z' WHERE id=1;")
    con.close()
    r = _scout(cfg, tmp_path, "auktion", "pruefen")
    assert r.returncode != 0 and "BESCHÄDIGT" in r.stderr and "Eintrag 1: Inhalt verändert" in r.stderr


def test_migration_v6_altbestand_auf_v7_mit_sicherung(tmp_path, monkeypatch):
    """v6 mit Anfrage und Standort: v7 legt nur neue Tabellen an, sichert vorher, ändert nichts Bestehendes, ist idempotent."""
    from wmscout import migrationen
    pfad = tmp_path / "alt.sqlite"
    with monkeypatch.context() as m:
        m.setattr(migrationen, "AKTUELLE_VERSION", 6)
        m.setattr(migrationen, "SCHRITTE", {v: f for v, f in migrationen.SCHRITTE.items() if v <= 6})
        db = Datenbank(str(pfad), wal=False)
        _aufbau(db, tmp_path, 2)
        assert "auktionen" not in {r[0] for r in db.con.execute("SELECT name FROM sqlite_master")}
        db.con.close()
    con = sqlite3.connect(pfad)
    vorher = {t: con.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in ("verkaufsanfragen", "standorte")}
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == list(range(7, migrationen.AKTUELLE_VERSION + 1))
    assert [p.name for p in (tmp_path / "s").iterdir() if f"vor-v{migrationen.AKTUELLE_VERSION}" in p.name]
    assert migrationen.migriere(pfad, tmp_path / "s") == []
    con = sqlite3.connect(pfad)
    assert {t: con.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in vorher} == vorher
    assert {"auktionen", "gebote", "auktion_protokoll"} <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
