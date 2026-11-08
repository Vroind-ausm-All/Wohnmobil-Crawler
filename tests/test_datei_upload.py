"""Browser-Dateien: tatsächlicher HTTP-Import, Vorschau ohne Schreiben und begrenzte Parser.

HTML/EML sind nachgebildete vorhandene Fixtures, CSV ist ein bewusst zugeordnetes Nutzerformat.
Keine Aussage über aktuelle Live-Exports der Plattformen.
"""
from __future__ import annotations

import base64
import threading

import pytest
import requests

from tests.daten import BASIS
from tests.nachgebildet_mails import nachgebildet_ka_mail
from tests.test_handy import Client
from wmscout.app import erstelle_server
from wmscout.eingang.dateien import MAX_CSV_ZEILEN, entpacke, lese_datei
from wmscout.haendler import HaendlerSpeicher
from wmscout.team import TeamSpeicher

URL = "https://www.kleinanzeigen.de/s-anzeige/3900008888"
CSV = f"url;titel;preis;km;ez;anbieter;art;ort\n{URL};Hymer B 678;39.900;95.000;2017;privat;Integrierter;70173 Stuttgart\n"


def upload(name="angebote.csv", inhalt=CSV, **kw):
    roh = inhalt.encode() if isinstance(inhalt, str) else inhalt
    return {"name": name, "inhalt": base64.b64encode(roh).decode(), **kw}


@pytest.fixture
def app(cfg, db):
    server, token, suchlauf = erstelle_server(cfg, db, BASIS, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(server.server_address[1])
    client.csrf = token
    yield client, suchlauf
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_csv_vorschau_schreibt_nichts_und_import_preissenkung_dubletten(app, db, monkeypatch):
    def kein_netz(*args, **kwargs):
        raise AssertionError("Import darf keine Netzverbindung öffnen")
    monkeypatch.setattr(requests.sessions.Session, "request", kein_netz)
    client, _ = app
    status, d, _ = client("POST", "/api/import/datei", upload(vorschau=True, zuordnung={}))
    assert status == 200 and not d["gespeichert"] and d["erkannt"] == 1
    assert d["vorschau"][0]["preis"] == 39900 and d["vorschau"][0]["anbieter"] == "privat"
    assert "Fahrzeugart unbekannt" not in d["vorschau"][0]["fehler"]
    assert "Integrierter" in d["vorschau"][0]["fehler"]
    assert not db.con.execute("SELECT 1 FROM anzeigen").fetchone()
    assert not db.con.execute("SELECT 1 FROM suchlaeufe").fetchone()
    for preis, erwartet in (("39.900", (1, 0, 0)), ("37.900", (0, 1, 0)), ("37.900", (0, 0, 1))):
        status, d, _ = client("POST", "/api/import/datei", upload(inhalt=CSV.replace("39.900", preis)))
        assert status == 200, d
        assert (d["neu"], d["aktualisiert"], d["uebersprungen"]) == erwartet
    a = db.con.execute("SELECT * FROM anzeigen").fetchone()
    assert a["titel"] == "Hymer B 678" and a["preis"] == 37900 and a["preis_vorher"] == 39900
    assert a["gewerblich"] == 0 and a["km"] == 95000 and a["ez_jahr"] == 2017 and a["art"] == "Integrierter"
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1
    assert db.con.execute("SELECT COUNT(*) FROM preis_historie").fetchone()[0] >= 2
    assert client("GET", "/api/status")[1]["letzter_erfolgreicher_import"]
    status, rows, _ = client("GET", "/api/fahrzeuge?filter=alle&sort=chance")
    assert status == 200 and rows[0]["sortierung"] and rows[0]["ankaufchance"]


def test_csv_feldzuordnung_unbekannte_werte_und_fehler_isoliert(app, db):
    client, _ = app
    csv = f"Adresse;Bezeichnung;Betrag;Verkäufer\n{URL};Hymer B 678;;\nhttps://evil.example/ad;Falsch;1000;privat\n"
    status, d, _ = client("POST", "/api/import/datei", upload(inhalt=csv, zuordnung={
        "url": "Adresse", "titel": "Bezeichnung", "preis": "Betrag", "anbieter": "Verkäufer"}))
    assert status == 200 and d["neu"] == 1 and d["fehlerhaft"] == 1 and "Zeile 3" in d["fehler"][0]
    a = db.con.execute("SELECT preis,km,gewerblich FROM anzeigen").fetchone()
    assert tuple(a) == (None, None, None)
    assert client("GET", "/api/status")[1]["letzter_erfolgreicher_import"] is None


def test_html_datei_ohne_rohablage(app, cfg, db):
    client, _ = app
    html = (BASIS / "tests/seiten/kleinanzeigen/detailseite.html").read_bytes()
    status, d, _ = client("POST", "/api/import/datei", upload("anzeige.html", html))
    assert status == 200 and d["neu"] == 1, d
    a = db.con.execute("SELECT preis,titel FROM anzeigen").fetchone()
    assert a["preis"] == 47300 and "Sunlight" in a["titel"]
    from pathlib import Path
    assert not Path(cfg["import"]["ordner"]).exists()


def test_eml_nur_bei_aktivem_eingang(app, cfg, db):
    client, _ = app
    daten = upload("suche.eml", nachgebildet_ka_mail())
    assert client("POST", "/api/import/datei", daten)[0] == 409
    cfg["eingaenge"]["email"]["aktiv"] = True
    status, d, _ = client("POST", "/api/import/datei", daten)
    assert status == 200 and d["neu"] == 3, d
    assert db.con.execute("SELECT DISTINCT kanal FROM beobachtungen").fetchone()[0] == "email"


@pytest.mark.parametrize("name", ["../x.html", "a\\x.csv", "C:x.csv", "x.zip", "x.svg", "a\x00.html", ""])
def test_dateinamen_und_formate_abgelehnt(name):
    with pytest.raises(ValueError):
        entpacke(upload(name))


@pytest.mark.parametrize("inhalt", ["%%", "", base64.b64encode(b"abc\x00").decode(), "a" * 6_666_672])
def test_ungueltige_uebertragung_und_groesse(inhalt):
    with pytest.raises(ValueError):
        entpacke({"name": "x.csv", "inhalt": inhalt})


@pytest.mark.parametrize("text", ["url;url\na;b", "a;b\n1;2;3", "url;titel;preis\n" + URL + ";Hymer;Rate 499 EUR"])
def test_ungueltige_csv_struktur_oder_unsicherer_preis(text):
    try:
        d = lese_datei("x.csv", text.encode(), ".csv")
        assert d.fehler and not d.lesungen
    except ValueError:
        pass


def test_csv_limit_und_mehrdeutige_zuordnung():
    with pytest.raises(ValueError, match="mehr als"):
        lese_datei("x.csv", ("url;titel\n" + (URL + ";Hymer\n") * (MAX_CSV_ZEILEN + 1)).encode(), ".csv")
    with pytest.raises(ValueError, match="nur einem Feld"):
        lese_datei("x.csv", CSV.encode(), ".csv", {"url": "url", "titel": "url"})


def test_csrf_rollen_und_laufkonflikt(app, db, cfg):
    client, lauf = app
    assert client("POST", "/api/import/datei", upload(), token=False)[0] == 403
    lauf.stand["laeuft"] = True
    assert client("POST", "/api/import/datei", upload())[0] == 409
    lauf.stand["laeuft"] = False
    cfg["eingaenge"]["text"]["aktiv"] = False
    assert client("POST", "/api/import/datei", upload())[0] == 409
    cfg["eingaenge"]["text"]["aktiv"] = True
    team = TeamSpeicher(db, "unbenutzt")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    assert client("POST", "/api/import/datei", upload())[0] == 401
    client.anmelden("Ben")
    assert client("POST", "/api/import/datei", upload())[0] == 200


def test_suchvorschau_radius_ohne_profil_speicherung(app, db):
    client, _ = app
    assert client("POST", "/api/import/datei", upload())[0] == 200
    profil = {"name": "Aktuelle Suche", "aktiv": True, "arten": ["Integrierter"], "marken": ["Hymer"],
              "gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 50}
    status, d, _ = client("POST", "/api/suche/vorschau", profil)
    assert status == 200 and d["treffer"] == {"3900008888": "passt"}, d
    assert not db.con.execute("SELECT 1 FROM suchprofile").fetchone()
    assert client("POST", "/api/suche/vorschau", {**profil, "gebiet_plz": "00000"})[0] == 400
    assert client("POST", "/api/suche/vorschau", profil, token=False)[0] == 403
    assert client("GET", "/api/fahrzeuge?sort=unbekannt")[0] == 400


def test_csv_leer_gesuch_und_html_titel(app, db):
    c, _ = app
    assert c("POST", "/api/import/datei", upload(inhalt=b"\xef\xbb\xbf"))[0] == 400
    assert c("POST", "/api/import/datei", upload(inhalt=" \n\r\n"))[0] == 400
    status, d, _ = c("POST", "/api/import/datei", upload(inhalt=CSV.replace("Hymer B 678", "Suche Wohnmobil")))
    assert status == 200 and d["uebersprungen"] == 1 and not d["ids"] and not d["neu"]
    assert not db.con.execute("SELECT 1 FROM anzeigen").fetchone()
    status, d, _ = c("POST", "/api/import/datei", upload(inhalt=CSV.replace("Hymer B 678", '<script>alert(1)</script> Hymer'), vorschau=True))
    assert status == 200 and d["erkannt"] == 1


def test_angaben_get_bestaetigung_importkonflikt_reset(app, db):
    c, _ = app
    assert c("POST", "/api/import/datei", upload())[0] == 200
    path = "/api/fahrzeug/3900008888/angaben"
    assert c("GET", path)[1]["felder"]["preis"]["extrahiert"] == 39900
    status, d, _ = c("POST", path, {"werte": {"preis": 35000, "km": 94000}})
    assert status == 200 and d["felder"]["preis"]["bestaetigt"]
    assert db.con.execute("SELECT preis FROM anzeigen").fetchone()[0] == 39900
    assert c("GET", "/api/fahrzeug/3900008888")[1]["preis"] == 35000
    assert c("POST", "/api/import/datei", upload(inhalt=CSV.replace("39.900", "37.900")))[0] == 200
    assert c("GET", path)[1]["felder"]["preis"]["konflikt"]
    assert c("POST", path, {"zuruecksetzen": ["preis"]})[1]["felder"]["preis"]["wert"] == 37900
    assert c("POST", path, {"werte": {"preis": True}})[0] == 400
    assert c("POST", path, {"werte": {"quelle": "falsch"}})[0] == 400
    assert c("POST", path, {"werte": {"preis": 1}}, token=False)[0] == 403
    assert c("GET", "/api/fahrzeug/9999999/angaben")[0] == 404


def test_angaben_reservierung_und_haendler_verbot(app, db):
    c, _ = app
    assert c("POST", "/api/import/datei", upload())[0] == 200
    team = TeamSpeicher(db, "unbenutzt")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    standort = HaendlerSpeicher(db).standort_anlegen("Filiale")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=standort)
    c.anmelden("Anna")
    assert c("POST", "/api/bearbeitung/3900008888/uebernehmen", {})[0] == 200
    c.anmelden("Ben")
    path = "/api/fahrzeug/3900008888/angaben"
    assert c("POST", path, {"werte": {"km": 12345}})[0] == 409
    assert c("POST", path, {"werte": {"km": 12345}, "erzwingen": True})[0] == 403
    c.anmelden("Hugo")
    assert c("POST", path, {"werte": {"km": 12345}})[0] == 403
    assert c("GET", path)[0] == 403
    assert c("POST", "/api/import/datei", upload())[0] == 403
    assert c("POST", "/api/suche/vorschau", {"name": "Suche"})[0] == 403


def test_vertragsentwurf_ohne_kauf_und_kontakte_nur_server(app, db):
    c, _ = app
    assert c("POST", "/api/import/datei", upload())[0] == 200
    status, b, _ = c("POST", "/api/besichtigung", {"anzeige_id": "3900008888"})
    assert status == 200, b
    path = f"/api/besichtigung/{b['id']}"
    draft = f"/besichtigung/{b['id']}/vertragsentwurf"
    vorher = tuple(db.con.execute("SELECT * FROM besichtigungen").fetchone())
    status, html, response = c("GET", draft)
    assert status == 200 and "Unverbindlicher Entwurf" in html and "Noch zu erfassen" in html
    assert response.getheader("Cache-Control") == "no-store"
    assert tuple(db.con.execute("SELECT * FROM besichtigungen").fetchone()) == vorher
    version = c("GET", path)[1]["version"]
    werte = {"name": "<script>Testname</script>", "anschrift": "Musterstraße 5, 70173 Stuttgart", "telefon": "0123 456",
             "email": "test@example.org", "preis": 32000}
    assert c("POST", path + "/vertragsdaten", {"werte": werte, "version": version}, token=False)[0] == 403
    status, d, _ = c("POST", path + "/vertragsdaten", {"werte": werte, "version": version})
    assert status == 200, d
    assert db.con.execute("SELECT status FROM besichtigungen").fetchone()[0] == "geplant"
    assert c("POST", path + "/vertragsdaten", {"werte": werte, "version": version})[0] == 409
    mobile = c("GET", path)[1]
    assert "vertragsdaten" not in (mobile["daten"] or {}) and "test@example.org" not in str(mobile)
    status, d, _ = c("POST", path + "/speichern", {"daten": {"fahrzeug": {"fin": "TEST12345678900001"}, "km_abgelesen": 94000},
                                                    "version": mobile["version"]})
    assert status == 200, d
    status, html, _ = c("GET", draft)
    assert status == 200 and "TEST12345678900001" in html and "test@example.org" in html and "32.000" in html
    assert "&lt;script&gt;Testname&lt;/script&gt;" in html and "<script>Testname" not in html
    assert not db.con.execute("SELECT 1 FROM ankaeufe").fetchone()
    assert c("POST", path + "/speichern", {"daten": {"vertragsdaten": werte}})[0] == 400
    assert c("GET", "/besichtigung/999999/vertragsentwurf")[0] == 404


def test_vertragsentwurf_rechte(app, db):
    c, _ = app
    assert c("POST", "/api/import/datei", upload())[0] == 200
    team = TeamSpeicher(db, "unbenutzt")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    c.anmelden("Anna")
    b = c("POST", "/api/besichtigung", {"anzeige_id": "3900008888"})[1]
    path = f"/api/besichtigung/{b['id']}"
    version = c("GET", path)[1]["version"]
    c.anmelden("Ben")
    assert c("POST", path + "/vertragsdaten", {"werte": {"name": "Unbefugt"}, "version": version})[0] == 403
    c.anmelden("Hugo")
    assert c("GET", f"/besichtigung/{b['id']}/vertragsentwurf")[0] == 403
    assert c("POST", path + "/vertragsdaten", {"werte": {}, "version": version})[0] == 403
