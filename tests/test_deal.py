"""Phase E – Deal Intelligence (ADR-028): Gewinn und Max-EK zum Gebot, nachrechenbar, mit Annahmen und Unsicherheit."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime

import pytest

from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_cli import _scout
from tests.test_haendler import MIT_WEITERGABE
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout import verkauf as vk
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.rechner import Rechner
from wmscout.deal import DealSpeicher
from wmscout.normalisierung.geo import entfernung_km
from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage

STICHTAG = datetime(2025, 3, 1, 12, 0)          # bewusst nicht heute: ein ignorierter Stichtag fiele sonst nicht auf
TI_2018 = {**MIT_WEITERGABE, "art": "Teilintegrierter", "ez_jahr": "2018", "km": "60000", "plz": "10115"}


@pytest.fixture
def anfrage(importiert, db, tmp_path):
    """Anfrage gegen die Vergleichsdaten des Testsuchlaufs (60 nachgebaute Inserate)."""
    v = VerkaufSpeicher(db, tmp_path / "fotos")
    return v.anlegen(pruefe_anfrage(TI_2018, jahr=2026), None, "x")["id"], v


def _eingabe(cfg, db, anfrage_id, betrag=30000, vergleich=None, km=320):
    f = vk.als_fahrzeug(VerkaufSpeicher(db, "x").lade(anfrage_id))
    f["entfernung_km"] = km
    return kalk.eingabe(cfg, f, vk.vergleich_aus(db) if vergleich is None else vergleich, betrag=betrag, stichtag=STICHTAG,
                        abholung="Test")


# ---------------------------------------------------------------- Rechenkern
def test_auszug_rechnet_genau_wie_die_ganze_datenbank(cfg, db, anfrage, monkeypatch):
    e = _eingabe(cfg, db, anfrage[0])
    assert 0 < len(e["vergleich"]) < len(vk.vergleich_aus(db))
    voll = kalk.rechne(e)
    monkeypatch.setattr(kalk, "vergleich_auszug", lambda rechner, fahrzeug, vergleich: list(vergleich))
    alle = _eingabe(cfg, db, anfrage[0])
    assert len(alle["vergleich"]) == len(vk.vergleich_aus(db))
    assert kalk.rechne(alle)["szenarien"] == voll["szenarien"] and kalk.rechne(alle)["risiko"] == voll["risiko"]


def test_nachrechnen_haengt_nicht_an_config_datenbank_oder_heute(cfg, db, anfrage):
    e = _eingabe(cfg, db, anfrage[0])
    gespeichert = json.loads(json.dumps(e))
    erg = kalk.rechne(e)
    cfg["rechner"]["kosten"]["aufbereitung"] = 5000                    # spätere Konfigurationsänderung …
    db.con.execute("UPDATE anzeigen SET preis = preis * 2")              # … und neue Marktdaten
    db.con.commit()
    assert kalk.rechne(gespeichert) == erg                               # wirken nicht auf die gespeicherte Kalkulation
    assert kalk.rechne(_eingabe(cfg, db, anfrage[0])) != erg             # wohl aber auf eine neue
    assert erg["annahmen"][0] == "Stichtag 2025-03-01T12:00:00, Rechenstand E1"


def test_max_ek_und_gewinn_mit_provision(cfg, db, anfrage):
    cfg["kalkulation"] = {"provision_prozent": 0}
    ohne = kalk.rechne(_eingabe(cfg, db, anfrage[0], km=entfernung_km(cfg["anschreiben"]["plz"], "10115")))
    b = vk.bewerte(cfg, VerkaufSpeicher(db, "x").lade(anfrage[0]), vk.vergleich_aus(db), Rechner(cfg, STICHTAG))
    assert ohne["szenarien"]["erwartet"]["max_ek"] in (b.max_ek, b.max_ek - 100)   # wie der Rechner, auf 100 € abgerundet
    cfg["kalkulation"] = {"provision_prozent": 0.02}
    e = _eingabe(cfg, db, anfrage[0])
    erg = kalk.rechne(e)
    s, r = erg["szenarien"]["erwartet"], Rechner({"rechner": e["rechner"]}, STICHTAG)
    gewinn = lambda ek: r.gewinn_bei_ek(s["haendler_vk"], s["kosten"] + ek * 0.02, ek)  # noqa: E731
    assert gewinn(s["max_ek"]) >= s["ziel_marge"] > gewinn(s["max_ek"] + 100)
    assert s["max_ek"] < ohne["szenarien"]["erwartet"]["max_ek"] and s["provision"] == 600
    assert abs(s["gewinn"] - ((s["haendler_vk"] - 30000) * 100 / 119 - s["kosten"] - 600)) <= 25
    v, g = erg["szenarien"]["vorsichtig"], erg["szenarien"]["guenstig"]
    assert v["max_ek"] <= s["max_ek"] <= g["max_ek"] and v["gewinn"] <= s["gewinn"] <= g["gewinn"]
    assert erg["korridor"] == {"sicher_bis": v["max_ek"], "obergrenze": s["max_ek"]}


def test_ampel_risiko_und_annahmen(cfg, db, anfrage):
    k = kalk.rechne(_eingabe(cfg, db, anfrage[0], betrag=None))["korridor"]
    assert kalk.rechne(_eingabe(cfg, db, anfrage[0], betrag=k["sicher_bis"]))["ampel"] == "gruen"
    assert kalk.rechne(_eingabe(cfg, db, anfrage[0], betrag=k["obergrenze"]))["ampel"] == "gelb"
    hoch = kalk.rechne(_eingabe(cfg, db, anfrage[0], betrag=k["obergrenze"] + 100))
    assert hoch["ampel"] == "rot"
    gruende = [g["grund"] for g in hoch["risiko"]["gruende"]]
    assert "Gebot über der Obergrenze (Max-EK erwartet)" in gruende and any(g.startswith("Mängel: Feuchtigkeit") for g in gruende)
    assert hoch["risiko"]["punkte"] == sum(g["punkte"] for g in hoch["risiko"]["gruende"])
    text = " ".join(hoch["annahmen"])
    assert "Provision 2.0% vom Zuschlag" in text and "§25a" in text and "320 km" in text and "keine Steuerberatung" in text


def test_ohne_erstzulassung_keine_kalkulation_und_ohne_spanne_nur_erwartet(cfg, db, anfrage):
    e = _eingabe(cfg, db, anfrage[0])
    e["fahrzeug"]["ez_jahr"] = None
    erg = kalk.rechne(e)
    assert erg["moeglich"] is False and erg["grund"].startswith("Keine Kalkulation möglich")
    leer = _eingabe(cfg, db, anfrage[0], vergleich=[])
    assert kalk.rechne(leer)["sicherheit"] == "niedrig"                  # Referenzmodell – mit Spanne, also drei Szenarien
    for falsch in ({"provision_prozent": -0.1}, {"provision_prozent": 0.5}, {"provision_prozent": "2%"}, {"provision_prozent": True}):
        with pytest.raises(ValueError, match="provision_prozent"):
            kalk.einstellungen({"kalkulation": falsch})


def test_rechner_stichtag_aendert_ohne_angabe_nichts(cfg):
    a = {"id": "x", "art": "Alkoven", "suche": "Alkoven", "ez_jahr": 2016, "km": 80000, "preis": 30000}
    assert Rechner(cfg).alter(a) == datetime.now().year - 2016
    assert Rechner(cfg, datetime(2030, 1, 1)).alter(a) == 14


def test_verkaufsanfrage_behaelt_ihre_plz_fuer_die_entfernung(cfg, db, anfrage):
    """Vorher überschrieb ``ergaenze_fahrzeug`` die PLZ mit der aus dem Ort (leer) – Transport immer pauschal."""
    a = VerkaufSpeicher(db, "x").lade(anfrage[0])
    assert vk.als_fahrzeug(a)["plz"] == "10115"
    b = vk.bewerte(cfg, a, vk.vergleich_aus(db))
    assert any(n.startswith("Abholung (") for n in b.kosten_posten)


# ---------------------------------------------------------------- Speicher, API
def test_standortsicht_gerundete_entfernung_und_speichern_nachrechnen(cfg, db, anfrage):
    from wmscout.haendler import HaendlerSpeicher
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale Nord", "20095", "Hamburg")
    d = DealSpeicher(db, cfg)
    e, erg = d.berechne(anfrage[0], 30000, sid)
    assert e["abholung"] == "ab Standort Filiale Nord" and e["fahrzeug"]["entfernung_km"] % 10 == 0
    assert "plz" not in e["fahrzeug"] and "ort" not in e["fahrzeug"] and "Erika" not in json.dumps(e)
    kid = d.speichern(e, erg, anlass="gespeichert", anfrage_id=anfrage[0], standort_id=sid)
    x = d.lade(kid)
    assert x["nachrechnung"] == {"gleich": True, "hash_ok": True, "version_gleich": True} and x["standort"] == "Filiale Nord"
    assert d.liste(anfrage[0])[0]["id"] == kid and d.pruefe_alle() == {"anzahl": 1, "ok": True, "abweichend": []}


def test_gespeicherte_kalkulation_ist_nur_anfuegbar_und_manipulation_faellt_auf(cfg, db, anfrage):
    d = DealSpeicher(db, cfg)
    kid = d.speichern(*d.berechne(anfrage[0], 30000), anlass="gespeichert", anfrage_id=anfrage[0])
    for sql in ("UPDATE kalkulationen SET betrag=1", "DELETE FROM kalkulationen"):
        with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
            db.con.execute(sql)
        db.con.rollback()
    db.con.executescript("DROP TRIGGER kalkulationen_kein_update;")
    roh = db.con.execute("SELECT eingabe_json, ergebnis_json FROM kalkulationen WHERE id=?", (kid,)).fetchone()
    db.con.execute("UPDATE kalkulationen SET ergebnis_json=? WHERE id=?", (roh[1].replace('"ampel":"', '"ampel":"x'), kid))
    db.con.commit()
    assert d.lade(kid)["nachrechnung"] == {"gleich": False, "hash_ok": True, "version_gleich": True}
    db.con.execute("UPDATE kalkulationen SET ergebnis_json=?, eingabe_json=? WHERE id=?",
                   (roh[1], roh[0].replace('"betrag":30000', '"betrag":20000'), kid))
    db.con.commit()
    assert d.lade(kid)["nachrechnung"]["hash_ok"] is False and d.pruefe_alle()["abweichend"] == [kid]


def test_neue_rechenversion_wird_als_solche_erkannt(cfg, db, anfrage, monkeypatch):
    d = DealSpeicher(db, cfg)
    kid = d.speichern(*d.berechne(anfrage[0], 30000), anlass="gespeichert", anfrage_id=anfrage[0])
    monkeypatch.setattr(kalk, "VERSION", "E2")
    assert d.lade(kid)["nachrechnung"] == {"gleich": False, "hash_ok": True, "version_gleich": False}


def test_api_haendler_sieht_kalkulation_am_gebot_und_gebot_speichert_sie(markt, db, tmp_path):
    anna, ben, hugo, ida, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["ida"], markt["anfrage"]
    aid = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 20000})[1]["id"]
    s, d, _ = hugo("GET", f"/api/haendler/auktion/{aid}/kalkulation?betrag=20000")
    assert s == 200 and d["ergebnis"]["moeglich"] and len(d["eingabe_hash"]) == 12
    assert "ab Standort Filiale Nord" in " ".join(d["ergebnis"]["annahmen"]) and "Erika" not in json.dumps(d)
    assert hugo("GET", f"/api/haendler/auktion/{aid}/kalkulation?betrag=abc")[0] == 400
    assert hugo("GET", f"/api/haendler/auktion/{aid}/kalkulation?betrag=1.5")[0] == 400
    assert hugo("GET", "/api/haendler/auktion/999/kalkulation?betrag=1")[0] == 404
    s, g, _ = hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 20000, "wiederholungs_id": "hugo-kalk-01"})
    assert s == 200 and g["kalkulation_id"]
    wiederholt = hugo("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 20000, "wiederholungs_id": "hugo-kalk-01"})[1]
    assert wiederholt["wiederholt"] and "kalkulation_id" not in wiederholt
    assert ida("POST", f"/api/haendler/auktion/{aid}/gebot", {"betrag": 20050, "wiederholungs_id": "ida-kalk-001"})[0] == 409
    zeilen = db.con.execute("SELECT anlass, gebot_id, standort_id, betrag FROM kalkulationen").fetchall()
    assert [tuple(z) for z in zeilen] == [("gebot", g["gebot_id"], markt["sids"][0], 20000)]   # abgelehntes Gebot: keine Kalkulation
    assert hugo("GET", f"/api/kalkulation/{g['kalkulation_id']}")[0] == 403                   # Gesamtsicht nur Team
    s, x, _ = ben("GET", f"/api/kalkulation/{g['kalkulation_id']}")
    assert s == 200 and x["nachrechnung"]["gleich"] and x["standort"] == "Filiale Nord" and x["anlass"] == "gebot"
    detail = anna("GET", f"/api/verkaufsanfrage/{anfrage}")[1]
    assert [k["id"] for k in detail["kalkulationen"]] == [g["kalkulation_id"]]
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/freigabe", {"freigeben": False})
    assert ida("GET", f"/api/haendler/auktion/{aid}/kalkulation?betrag=21000")[0] == 404           # nicht mehr freigegeben
    node = shutil.which("node")
    if node:
        for pfad, wer in (("/haendler", hugo), ("/anfragen", anna)):
            datei = tmp_path / "s.js"
            datei.write_text(re.findall(r"<script>(.*?)</script>", wer("GET", pfad)[1], re.S)[-1], encoding="utf-8")
            assert subprocess.run([node, "--check", str(datei)], capture_output=True, timeout=60).returncode == 0, pfad


def test_api_team_rechnet_und_speichert(markt, db):
    ben, hugo, anfrage = markt["ben"], markt["hugo"], markt["anfrage"]
    s, d, _ = ben("GET", f"/api/verkaufsanfrage/{anfrage}/kalkulation?betrag=25000")
    assert s == 200 and "ab Firmensitz" in " ".join(d["ergebnis"]["annahmen"])
    assert ben("GET", f"/api/verkaufsanfrage/{anfrage}/kalkulation?betrag=25000&standort={markt['sids'][1]}")[1]["ergebnis"]["annahmen"][1] \
        .startswith("Abholung: ab Standort Filiale Süd")
    assert ben("GET", f"/api/verkaufsanfrage/{anfrage}/kalkulation?standort=999")[0] == 400
    assert ben("GET", "/api/verkaufsanfrage/999/kalkulation")[0] == 404
    assert hugo("GET", f"/api/verkaufsanfrage/{anfrage}/kalkulation?betrag=1")[0] == 403              # Händler: Positivliste
    s, d, _ = ben("POST", f"/api/verkaufsanfrage/{anfrage}/kalkulation", {"betrag": 25000})
    assert s == 200 and DealSpeicher(db, {"kalkulation": {}}).lade(d["id"])["nachrechnung"]["gleich"]
    for falsch in ({"betrag": "25000"}, {"betrag": 25000.0}, {"betrag": True}, {"betrag": 1, "standort_id": 999}):
        assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/kalkulation", falsch)[0] == 400


def test_cli_kalkulation_pruefen(cfg, db, anfrage, tmp_path):
    d = DealSpeicher(db, cfg)
    kid = d.speichern(*d.berechne(anfrage[0], 30000), anlass="gespeichert", anfrage_id=anfrage[0])
    r = _scout(cfg, tmp_path, "kalkulation", "pruefen")
    assert r.returncode == 0 and "1 gespeicherte Kalkulationen – alle identisch" in r.stdout, r.stderr
    db.con.executescript("DROP TRIGGER kalkulationen_kein_update;")
    db.con.execute("UPDATE kalkulationen SET ergebnis_json='{}' WHERE id=?", (kid,))
    db.con.commit()
    r = _scout(cfg, tmp_path, "kalkulation", "pruefen")
    assert r.returncode != 0 and "weichen ab" in r.stderr and str(kid) in r.stderr
