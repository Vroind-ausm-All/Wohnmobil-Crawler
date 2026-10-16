"""Phase C – Händlerportal v1 für eigene Standorte (ADR-026): Zugriffsschutz, Freigabe (Verkäufer + Inhaber), Anonymisierung."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import base64
import re
import shutil
import subprocess

import pytest

from tests.test_cli import _scout
from tests.test_handy import Client
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from tests.test_verkauf import GUELTIG, JPEG
from wmscout.datenbank import Datenbank
from wmscout.haendler import HaendlerSpeicher, anonym, ohne_kontakt, plz_bereich
from wmscout.team import TeamSpeicher, lade_team_sicht
from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage

MIT_WEITERGABE = {**GUELTIG, "weitergabe": True, "preisvorstellung": "39500",
                  "beschreibung": "Markise. Rückruf unter 0170 1234567 oder erika@beispiel.invalid, Bilder www.beispiel.invalid/x"}


# ---------------------------------------------------------------- Fachlogik
def test_plz_bereich_und_kontaktdaten_im_freitext_werden_entfernt():
    assert plz_bereich("12345") == "12xxx" and plz_bereich(None) is None and plz_bereich("x") is None
    text = ohne_kontakt(MIT_WEITERGABE["beschreibung"])
    assert "1234567" not in text and "@" not in text and "www." not in text and "Markise" in text


def test_anonyme_sicht_ist_eine_positivliste():
    a = {**pruefe_anfrage(MIT_WEITERGABE, jahr=2026), "id": 1, "referenz": "VA-2026-0001", "freigegeben_am": "2026-10-16T10:00:00",
         "maengel": '["feuchtigkeit"]', "ort": "Musterstadt"}
    sicht = anonym(a, [{"datei": "a.jpg"}])
    assert set(sicht) == {"id", "referenz", "art", "marke", "modell", "ez_jahr", "km", "preisvorstellung", "beschreibung", "maengel",
                          "region", "freigegeben_am", "fotos"}
    assert sicht["region"] == "12xxx" and sicht["preisvorstellung"] == 39500 and "Erika" not in str(sicht) and "Musterstadt" not in str(sicht)


# ---------------------------------------------------------------- Speicher
@pytest.fixture
def speicher(db, tmp_path):
    return VerkaufSpeicher(db, tmp_path / "fotos" / "anfragen"), HaendlerSpeicher(db)


def test_freigabe_nur_mit_zustimmung_des_verkaeufers_und_nur_offen(speicher):
    vk, hs = speicher
    ohne = vk.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "x")["id"]
    mit = vk.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["id"]
    with pytest.raises(ValueError, match="nicht zugestimmt"):
        vk.setze_freigabe(ohne, True, None)
    assert vk.setze_freigabe(mit, True, None)
    sid = hs.standort_anlegen("Filiale Nord", "20095", "Hamburg")
    assert [f["id"] for f in hs.sichtbare(sid)] == [mit]
    vk.setze_status(mit, "abgelehnt", None)
    assert hs.sichtbare(sid) == [] and hs.sichtbar(mit, sid) is None             # abgeschlossen: nicht mehr sichtbar
    with pytest.raises(ValueError, match="nur offene"):
        vk.setze_freigabe(mit, True, None)                                    # Status ist „abgelehnt“
    vk.setze_status(mit, "in_pruefung", None)
    assert vk.setze_freigabe(mit, False, None) and hs.sichtbare(sid) == []
    assert [v["neu"] for v in vk.lade(mit)["verlauf"] if v["ereignis"] == "freigabe"] == ["freigegeben", "zurückgenommen"]


def test_interesse_einmal_je_standort_und_nur_fuer_sichtbares(speicher, db):
    vk, hs = speicher
    aid = vk.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["id"]
    sid = hs.standort_anlegen("Filiale Süd")
    assert hs.interesse_melden(aid, sid, 1) is False                              # noch nicht freigegeben
    vk.setze_freigabe(aid, True, None)
    assert hs.interesse_melden(aid, sid, 1) and hs.interesse_melden(aid, sid, 1)
    assert [i["standort"] for i in vk.interessen(aid)] == ["Filiale Süd"]
    assert hs.sichtbar(aid, sid)["interesse"] is True


def test_haendler_braucht_standort_und_erscheint_nicht_im_team(db, tmp_path):
    t, hs = TeamSpeicher(db, tmp_path / "f"), HaendlerSpeicher(db)
    sid = hs.standort_anlegen("Filiale West")
    with pytest.raises(ValueError, match="Standort"):
        t.nutzer_anlegen("Hugo", "sicher1234", "haendler")
    with pytest.raises(ValueError, match="Standort"):
        t.nutzer_anlegen("Mia", "sicher1234", "mitarbeiter", standort_id=sid)
    t.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    t.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    assert [n["name"] for n in t.nutzer_liste()] == ["Anna"]
    assert sorted(n["name"] for n in t.nutzer_liste(auch_haendler=True)) == ["Anna", "Hugo"]
    assert [n["name"] for n in lade_team_sicht(db, 2).nutzer.values()] == ["Anna"]
    from datetime import datetime
    assert [z["name"] for z in db.team_zaehler(datetime.now())["nutzer"]] == ["Anna"]


# ---------------------------------------------------------------- API
@pytest.fixture
def portal(server, team, db):
    """Team (Anna Inhaberin, Ben, Carl) + Standort „Filiale Nord“ (noch offen) mit Zugang Hugo; zwei Anfragen."""
    hs = HaendlerSpeicher(db)
    sid = hs.standort_anlegen("Filiale Nord", "20095", "Hamburg")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    anna = anmelden(server, "Anna")
    ohne = anna("POST", "/api/verkaufsanfrage", GUELTIG)[1]["id"]
    mit = anna("POST", "/api/verkaufsanfrage", MIT_WEITERGABE)[1]["id"]
    bild = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    foto = anna("POST", f"/api/verkaufsanfrage/{mit}/foto", {"bild": bild})[1]["datei"]
    return {"sid": sid, "anna": anna, "hugo": anmelden(server, "Hugo"), "ben": anmelden(server, "Ben"), "ohne": ohne, "mit": mit, "foto": foto}


def test_haendler_kommt_nur_ins_haendlerportal(portal):
    hugo = portal["hugo"]
    s, _, r = hugo("GET", "/")
    assert s == 303 and r.getheader("Location") == "/haendler"
    for pfad in ("/api/verkaufsanfragen", f"/api/verkaufsanfrage/{portal['mit']}", "/anfragen", "/verkaufen", "/standorte",
                 "/api/fahrzeuge", "/api/team", "/api/heute", "/api/nutzer", "/api/standorte",
                 f"/anfrage-fotos/{portal['mit']}/{portal['foto']}"):
        assert hugo("GET", pfad)[0] == 403, pfad
    for pfad, daten in (("/api/status", {"id": "x", "status": "neu"}), ("/api/verkaufsanfrage", GUELTIG),
                        (f"/api/verkaufsanfrage/{portal['mit']}/freigabe", {"freigeben": True}), ("/api/standorte", {"name": "X"})):
        assert hugo("POST", pfad, daten)[0] == 403, pfad
    assert hugo("GET", "/haendler")[0] == 200 and hugo("GET", "/api/ich")[0] == 200


def test_ungepruefter_standort_sieht_nichts_gesperrter_sofort_nichts_mehr(portal):
    anna, hugo, mit = portal["anna"], portal["hugo"], portal["mit"]
    assert anna("POST", f"/api/verkaufsanfrage/{mit}/freigabe", {"freigeben": True})[0] == 200
    s, d, _ = hugo("GET", "/api/haendler/fahrzeuge")
    assert s == 403 and "nicht geprüft" in d["fehler"]
    assert hugo("GET", f"/haendler-fotos/{mit}/{portal['foto']}")[0] == 403
    assert anna("POST", f"/api/standorte/{portal['sid']}/status", {"status": "geprueft"})[0] == 200
    assert [f["id"] for f in hugo("GET", "/api/haendler/fahrzeuge")[1]] == [mit]
    assert anna("POST", f"/api/standorte/{portal['sid']}/status", {"status": "gesperrt"})[0] == 200
    assert hugo("GET", "/api/haendler/fahrzeuge")[0] == 403


def test_freigabe_nur_durch_inhaber_und_nur_mit_zustimmung(portal):
    anna, ben = portal["anna"], portal["ben"]
    assert ben("POST", f"/api/verkaufsanfrage/{portal['mit']}/freigabe", {"freigeben": True})[0] == 403
    s, d, _ = anna("POST", f"/api/verkaufsanfrage/{portal['ohne']}/freigabe", {"freigeben": True})
    assert s == 400 and "nicht zugestimmt" in d["fehler"]


def test_haendler_sieht_anonymisiert_mit_preis_und_meldet_interesse(portal):
    anna, hugo, mit = portal["anna"], portal["hugo"], portal["mit"]
    anna("POST", f"/api/verkaufsanfrage/{mit}/freigabe", {"freigeben": True})
    anna("POST", f"/api/standorte/{portal['sid']}/status", {"status": "geprueft"})
    liste = hugo("GET", "/api/haendler/fahrzeuge")[1]
    assert len(liste) == 1                                                        # die Anfrage ohne Zustimmung fehlt
    f = liste[0]
    roh = str(f)
    for geheim in ("Erika", "0170", "beispiel.invalid", "12345", "max_ek", "erstangebot", "telefon", "email", "name"):
        assert geheim not in roh, geheim
    assert f["region"] == "12xxx" and f["preisvorstellung"] == 39500 and f["fotos"] == [portal["foto"]]
    s, roh_bild, _ = hugo("GET", f"/haendler-fotos/{mit}/{portal['foto']}")
    assert s == 200
    assert hugo("GET", f"/haendler-fotos/{portal['ohne']}/{portal['foto']}")[0] == 404
    assert hugo("POST", f"/api/haendler/fahrzeug/{mit}/interesse", {})[0] == 200
    assert hugo("GET", f"/api/haendler/fahrzeug/{mit}")[1]["interesse"] is True
    d = anna("GET", f"/api/verkaufsanfrage/{mit}")[1]
    assert [i["standort"] for i in d["interessen"]] == ["Filiale Nord"] and "interesse" in [v["ereignis"] for v in d["verlauf"]]
    anna("POST", f"/api/verkaufsanfrage/{mit}/status", {"status": "gekauft"})
    assert hugo("GET", f"/api/haendler/fahrzeug/{mit}")[0] == 404
    assert hugo("POST", f"/api/haendler/fahrzeug/{mit}/interesse", {})[0] == 404


def test_team_sieht_vorschau_ohne_interesse_und_standorte_nur_inhaber(portal, tmp_path):
    anna, ben, mit = portal["anna"], portal["ben"], portal["mit"]
    anna("POST", f"/api/verkaufsanfrage/{mit}/freigabe", {"freigeben": True})
    assert [f["id"] for f in ben("GET", "/api/haendler/fahrzeuge")[1]] == [mit]
    assert ben("POST", f"/api/haendler/fahrzeug/{mit}/interesse", {})[0] == 403
    assert ben("GET", "/standorte")[0] == 403 and ben("GET", "/api/standorte")[0] == 403
    s, d, _ = anna("GET", "/api/standorte")
    assert s == 200 and [x["name"] for x in d["standorte"]] == ["Filiale Nord"] and [n["name"] for n in d["nutzer"]] == ["Hugo"]
    assert anna("POST", "/api/standorte", {"name": "Filiale Nord"})[0] == 409
    assert anna("POST", f"/api/standorte/{portal['sid']}/status", {"status": "quatsch"})[0] == 400
    node = shutil.which("node")
    if node:
        for pfad, wer in (("/haendler", portal["hugo"]), ("/standorte", anna)):
            html = wer("GET", pfad)[1]
            datei = tmp_path / "s.js"
            datei.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
            assert subprocess.run([node, "--check", str(datei)], capture_output=True, timeout=60).returncode == 0, pfad


def test_ohne_anmeldung_kein_zugang(server, team):
    c = Client(server.server_address[1])
    assert c("GET", "/api/haendler/fahrzeuge")[0] == 401
    s, _, r = c("GET", "/haendler-fotos/1/a.jpg")                                # Seiten/Dateien: Weiterleitung zur Anmeldung
    assert s == 303 and r.getheader("Location").startswith("/login")


def test_cli_standort_und_haendlerzugang(cfg, tmp_path):
    Datenbank(cfg["ausgabe"]["datenbank"]).con.close()
    assert _scout(cfg, tmp_path, "standort", "anlegen", "Filiale Ost", "--plz", "01067").returncode == 0
    r = _scout(cfg, tmp_path, "nutzer", "anlegen", "Hugo", "--rolle", "haendler", "--standort", "Unbekannt", "--passwort", "sicher1234")
    assert r.returncode != 0 and "unbekannt" in r.stderr
    r = _scout(cfg, tmp_path, "nutzer", "anlegen", "Hugo", "--rolle", "haendler", "--standort", "Filiale Ost", "--passwort", "sicher1234")
    assert r.returncode == 0, r.stderr
    assert _scout(cfg, tmp_path, "standort", "pruefen", "Filiale Ost").returncode == 0
    r = _scout(cfg, tmp_path, "standort", "liste")
    assert "Filiale Ost" in r.stdout and "geprüft" in r.stdout and "1 Zugang" in r.stdout
    assert "Hugo" in _scout(cfg, tmp_path, "nutzer", "liste").stdout
