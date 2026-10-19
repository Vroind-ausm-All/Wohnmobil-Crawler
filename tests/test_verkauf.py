"""Phase B – Verkäuferportal v1: Eingabeprüfung, Speicher (Schema v5), Bewertung/Spanne und API (ADR-025)."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import base64
import re
import shutil
import sqlite3
import subprocess

import pytest

from tests.test_team_bearbeitung import anmelden, lokal, server, team  # noqa: F401 – Fixtures
from wmscout import verkauf as vk
from wmscout.bewertung.rechner import Bewertung
from wmscout.verkauf import Eingabefehler, VerkaufSpeicher, pruefe_anfrage, spanne_fuer_verkaeufer

JPEG = b"\xff\xd8\xff\xe0" + b"7" * 300
GUELTIG = {"art": "Teilintegrierter", "marke": "Hymer", "modell": "B 678", "ez_jahr": "2016", "km": "85.000",
           "name": "Erika Beispiel", "telefon": "0170 0000000", "plz": "12345", "einwilligung": True,
           "maengel": ["feuchtigkeit"], "beschreibung": "Markise, Solar"}


def _bewertung(**kw) -> Bewertung:
    werte = {"marktwert_angebote": 41000, "vergleich_anzahl": 12, "vergleich_basis": "12 Angebote", "marktwert_privat": 38000,
             "haendler_vk": 45000, "kosten": 3000, "max_ek": 31000, "erstangebot": 28000, "sicherheit": "mittel",
             "spanne_von": 38250, "spanne_bis": 43800}
    return Bewertung(**{**werte, **kw})


CFG_SPANNE = {"verkaeuferportal": {"spanne_zeigen": True, "spanne_mindest_sicherheit": "mittel"}}


# ---------------------------------------------------------------- Fachlogik (ohne Netz und Datenbank)
def test_gueltige_anfrage_wird_bereinigt():
    a = pruefe_anfrage(GUELTIG, jahr=2026)
    assert (a["ez_jahr"], a["km"], a["preisvorstellung"], a["kanal"], a["maengel"]) == (2016, 85000, None, "formular", ["feuchtigkeit"])


def test_fehlende_pflichtangaben_werden_alle_gemeldet():
    with pytest.raises(Eingabefehler) as e:
        pruefe_anfrage({}, jahr=2026)
    text = " | ".join(e.value.fehler)
    for teil in ("Fahrzeugart", "Marke", "Erstzulassung", "Name", "Telefon oder E-Mail", "PLZ", "Einwilligung"):
        assert teil in text


@pytest.mark.parametrize("feld,wert,teil", [
    ("ez_jahr", "1850", "Erstzulassung"), ("ez_jahr", "2031", "Erstzulassung"), ("km", "-5", "Kilometerstand"),
    ("km", "viel", "Kilometerstand"), ("email", "keine-adresse", "E-Mail"), ("plz", "1234", "PLZ"),
    ("einwilligung", "true", "Einwilligung"), ("maengel", ["erfunden"], "Mangel"), ("kanal", "mail", "Eingangsweg"),
    ("art", "Pkw", "Fahrzeugart")])
def test_ungueltige_angaben(feld, wert, teil):
    with pytest.raises(Eingabefehler) as e:
        pruefe_anfrage({**GUELTIG, feld: wert}, jahr=2026)
    assert any(teil in f for f in e.value.fehler)


def test_email_statt_telefon_genuegt_und_preis_ist_freiwillig():
    a = pruefe_anfrage({**GUELTIG, "telefon": "", "email": "erika@beispiel.invalid", "preisvorstellung": "39.500 €"}, jahr=2026)
    assert a["telefon"] is None and a["preisvorstellung"] == 39500


def test_rechnersicht_nutzt_art_und_maengel_als_text():
    a = vk.als_fahrzeug({**pruefe_anfrage(GUELTIG, jahr=2026), "id": 7})
    assert a["suche"] == a["art"] == "Teilintegrierter" and a["id"] == "anfrage-7"
    assert "Feuchtigkeit" in a["kurzbeschreibung"] and a["marke"] == "Hymer" and a["gewerblich"] == 0


def test_spanne_nach_aussen_auf_1000_gerundet():
    assert spanne_fuer_verkaeufer(_bewertung(), CFG_SPANNE) == (38000, 44000)


@pytest.mark.parametrize("kw,cfg", [({"sicherheit": "niedrig"}, CFG_SPANNE), ({"sicherheit": "keine"}, CFG_SPANNE),
                                    ({"spanne_von": None}, CFG_SPANNE), ({}, {}),
                                    ({}, {"verkaeuferportal": {"spanne_zeigen": False}}),
                                    ({"sicherheit": "mittel"}, {"verkaeuferportal": {"spanne_zeigen": True, "spanne_mindest_sicherheit": "hoch"}})])
def test_keine_spanne_bei_unsicherer_datenlage_oder_abgeschaltet(kw, cfg):
    assert spanne_fuer_verkaeufer(_bewertung(**kw), cfg) is None


# ---------------------------------------------------------------- Speicher (Schema v5)
@pytest.fixture
def speicher(db, tmp_path):
    return VerkaufSpeicher(db, tmp_path / "fotos" / "anfragen")


def test_anlegen_mit_referenz_verkaeufer_und_verlauf(speicher, db):
    neu = speicher.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "test-1")
    assert re.fullmatch(r"VA-\d{4}-0001", neu["referenz"])
    a = speicher.lade(neu["id"])
    assert (a["name"], a["status"], a["einwilligung_version"], a["kanal"]) == ("Erika Beispiel", "eingegangen", "test-1", "formular")
    assert [v["ereignis"] for v in a["verlauf"]] == ["angelegt"]
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0          # getrennt von beobachteten Inseraten


def test_anlegen_ist_atomar(speicher, db, monkeypatch):
    def kaputt(*a, **k):
        raise sqlite3.OperationalError("simuliert")

    monkeypatch.setattr(speicher, "_verlauf", kaputt)
    with pytest.raises(sqlite3.OperationalError):
        speicher.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "x")
    assert db.con.execute("SELECT COUNT(*) FROM verkaeufer").fetchone()[0] == 0
    assert db.con.execute("SELECT COUNT(*) FROM verkaufsanfragen").fetchone()[0] == 0


def test_status_bearbeiter_notiz_mit_verlauf(speicher):
    aid = speicher.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "x")["id"]
    assert speicher.setze_status(aid, "in_pruefung", None) and speicher.setze_status(aid, "in_pruefung", None)
    assert speicher.setze_notiz(aid, "Rückruf Montag", None) and speicher.setze_bearbeiter(aid, 3, None)
    with pytest.raises(ValueError):
        speicher.setze_status(aid, "verschenkt", None)
    assert speicher.setze_status(999, "angebot", None) is False
    a = speicher.lade(aid)
    assert [v["ereignis"] for v in a["verlauf"]] == ["angelegt", "status", "notiz", "bearbeiter"]   # gleicher Status: kein Eintrag
    assert (a["status"], a["notiz"], a["bearbeiter_id"]) == ("in_pruefung", "Rückruf Montag", 3)


def test_fotos_nur_bilder_hoechstens_zwoelf_und_kein_fremder_pfad(speicher, monkeypatch):
    aid = speicher.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "x")["id"]
    with pytest.raises(ValueError, match="JPEG"):
        speicher.foto_speichern(aid, b"<html>", None)
    with pytest.raises(LookupError):
        speicher.foto_speichern(999, JPEG, None)
    monkeypatch.setattr(vk, "MAX_FOTOS", 2)
    namen = [speicher.foto_speichern(aid, JPEG, None)["datei"] for _ in range(2)]
    with pytest.raises(ValueError, match="Höchstens"):
        speicher.foto_speichern(aid, JPEG, None)
    assert speicher.foto_pfad(aid, namen[0]).read_bytes() == JPEG
    assert speicher.foto_pfad(aid, "../../anzeigen.sqlite") is None and speicher.foto_pfad(aid + 1, namen[0]) is None
    fremd = speicher.foto_ordner / str(aid) / "untergeschoben.jpg"         # liegt im Ordner, gehört aber nicht zur Anfrage
    fremd.write_bytes(JPEG)
    assert speicher.foto_pfad(aid, fremd.name) is None


# ---------------------------------------------------------------- API
def _js_ok(html, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node nicht installiert")
    datei = tmp_path / "s.js"
    datei.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
    r = subprocess.run([node, "--check", str(datei)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_seiten_werden_ausgeliefert(server, tmp_path):
    c = lokal(server)
    for pfad in ("/verkaufen", "/anfragen"):
        s, html, _ = c("GET", pfad)
        assert s == 200 and "<script>" in html
        _js_ok(html, tmp_path)


def test_anfrage_ueber_api_anlegen_bewerten_und_bearbeiten(server, db):
    c = lokal(server)
    s, d, _ = c("POST", "/api/verkaufsanfrage", {"marke": "Hymer"})
    assert s == 400 and "Fahrzeugart fehlt" in d["felder"]
    anzeigen_vorher = db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0]
    s, neu, _ = c("POST", "/api/verkaufsanfrage", {**GUELTIG, "kanal": "telefon"})
    assert s == 200 and neu["referenz"].startswith("VA-") and "spanne" in neu
    assert "max_ek" not in neu and "erstangebot" not in neu                       # dem Verkäufer nie Max-EK oder Angebot
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == anzeigen_vorher
    liste = c("GET", "/api/verkaufsanfragen")[1]
    assert [x["referenz"] for x in liste] == [neu["referenz"]] and "max_ek" in liste[0]["bewertung"]
    bild = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    s, foto, _ = c("POST", f"/api/verkaufsanfrage/{neu['id']}/foto", {"bild": bild})
    assert s == 200
    s, roh, r = c("GET", f"/anfrage-fotos/{neu['id']}/{foto['datei']}")
    assert s == 200 and r.getheader("Content-Type") == "image/jpeg"
    assert c("GET", f"/anfrage-fotos/{neu['id']}/fremd.jpg")[0] == 404
    assert c("POST", f"/api/verkaufsanfrage/{neu['id']}/status", {"status": "angebot"})[0] == 200
    assert c("POST", f"/api/verkaufsanfrage/{neu['id']}/status", {"status": "quatsch"})[0] == 400
    d = c("GET", f"/api/verkaufsanfrage/{neu['id']}")[1]
    assert d["status"] == "angebot" and d["kanal"] == "telefon" and d["maengel"][0]["key"] == "feuchtigkeit"
    assert [v["ereignis"] for v in d["verlauf"]] == ["angelegt", "foto", "status"] and "max_ek" in d["bewertung"]
    assert c("GET", "/api/verkaufsanfrage/999")[0] == 404
    assert c("GET", "/api/verkaufsanfragen?status=quatsch")[0] == 400


def test_im_team_nur_mit_anmeldung_und_bearbeiter_wird_gesetzt(server, team):
    from tests.test_handy import Client
    fremd = Client(server.server_address[1])
    assert fremd("GET", "/api/verkaufsanfragen")[0] == 401                         # personenbezogene Daten nur angemeldet
    assert fremd("POST", "/api/verkaufsanfrage", GUELTIG, token=False)[0] in (401, 403)
    ben = anmelden(server, "Ben")
    neu = ben("POST", "/api/verkaufsanfrage", GUELTIG)[1]
    assert ben("POST", f"/api/verkaufsanfrage/{neu['id']}/uebernehmen", {})[0] == 200
    d = ben("GET", f"/api/verkaufsanfrage/{neu['id']}")[1]
    assert d["bearbeiter"] == "Ben" and d["erfasst_von"] == team.ids["Ben"]
    assert ben("POST", f"/api/verkaufsanfrage/{neu['id']}/uebernehmen", {"abgeben": True})[0] == 200
    assert ben("GET", f"/api/verkaufsanfrage/{neu['id']}")[1]["bearbeiter_id"] is None
