"""Handy-App: Anmeldung, Zugriffsschutz, Besichtigungs-Ablauf über die HTTP-Schnittstelle, WhatsApp."""
import base64
import http.client
import json
import threading

import pytest

from tests.daten import BASIS
from wmscout.app import erstelle_server
from wmscout.benachrichtigung import WhatsAppCloud, whatsapp_link, whatsapp_nummer
from wmscout.bewertung.besichtigung import berechne, lade_katalog
from wmscout.team import TeamSpeicher

JPEG = b"\xff\xd8\xff\xe0" + b"1" * 200
OEFFENTLICH = "buero-pc.tail1234.ts.net"


class Client:
    def __init__(self, port, host=None):
        self.port, self.host, self.cookie, self.csrf = port, host, None, None

    def __call__(self, methode, pfad, daten=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        kopf = {"Content-Type": "application/json", "Host": self.host or f"127.0.0.1:{self.port}"}
        if self.cookie:
            kopf["Cookie"] = self.cookie
        if token and self.csrf:
            kopf["X-Scout-Token"] = self.csrf
        c.request(methode, pfad, body=json.dumps(daten) if daten is not None else None, headers=kopf)
        r = c.getresponse()
        roh = r.read()
        if r.getheader("Set-Cookie", "").startswith("scout_sitzung="):
            self.cookie = r.getheader("Set-Cookie").split(";")[0]
        typ = r.getheader("Content-Type", "")
        return r.status, (json.loads(roh) if typ.startswith("application/json") else roh.decode("utf-8", "replace")), r

    def anmelden(self, name, passwort="sicher1234"):
        status, _, _ = self("POST", "/api/login", {"name": name, "passwort": passwort})
        assert status == 200
        self.csrf = self("GET", "/api/ich")[1]["csrf"]
        return self


@pytest.fixture
def server(cfg, db, importiert, tmp_path):
    cfg["app"]["oeffentliche_url"] = f"https://{OEFFENTLICH}"
    srv, _, _ = erstelle_server(cfg, db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def team(db, cfg):
    from pathlib import Path
    t = TeamSpeicher(db, Path(cfg["ausgabe"]["datenbank"]).parent / "fotos")
    t.nutzer_anlegen("Anna", "sicher1234", "inhaber", "+49 170 1111111")
    t.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter", "0171 2222222")
    t.nutzer_anlegen("Carl", "sicher1234", "mitarbeiter")
    return t


def test_ohne_nutzer_nur_lokal(server):
    port = server.server_address[1]
    assert Client(port)("GET", "/api/heute")[0] == 200                       # lokal wie bisher ohne Anmeldung
    status, daten, _ = Client(port, OEFFENTLICH)("GET", "/api/heute")
    assert status == 403 and "Nutzer" in daten["fehler"]                       # von außen erst mit Team-Zugängen
    assert Client(port, "boese.example")("GET", "/api/heute")[0] == 403


def test_anmeldung_und_schutz(server, team):
    port = server.server_address[1]
    gast = Client(port, OEFFENTLICH)
    assert gast("GET", "/api/heute")[0] == 401
    status, _, r = gast("GET", "/m")
    assert status == 303 and r.getheader("Location").startswith("/login")
    assert gast("GET", "/login")[0] == 200
    assert gast("GET", "/static/mobil.js")[0] == 200 and gast("GET", "/sw.js")[0] == 200
    assert gast("GET", "/static/../datenbank.py")[0] == 404
    assert gast("POST", "/api/login", {"name": "Anna", "passwort": "falsch"})[0] == 401

    anna = Client(port, OEFFENTLICH).anmelden("Anna")
    assert anna("GET", "/api/ich")[1]["nutzer"]["rolle"] == "inhaber"
    assert anna("GET", "/m")[0] == 200
    assert anna("POST", "/api/status", {"id": "x", "status": "neu"}, token=False)[0] == 403   # ohne CSRF-Token
    assert Client(port)("GET", "/api/heute")[0] == 401                       # mit Team auch lokal nur angemeldet
    anna("POST", "/api/logout", {})
    assert anna("GET", "/api/heute")[0] == 401


def test_besichtigung_ablauf(server, team, db):
    port = server.server_address[1]
    anna = Client(port, OEFFENTLICH).anmelden("Anna")
    liste = anna("GET", "/api/fahrzeuge?filter=bereit")[1]
    assert liste and all(f["bereit"] for f in liste)
    fz = anna("GET", f"/api/fahrzeug/{liste[0]['id']}")[1]
    assert fz["brief"] and "Vorbehaltlich" in fz["brief"]

    ben_id = next(n["id"] for n in team.nutzer_liste() if n["name"] == "Ben")
    status, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": fz["id"], "termin": "2026-10-20T10:30",
                                                     "adresse": "Hauptstr. 1, 70173 Stuttgart", "zustaendig_id": ben_id})
    assert status == 200 and b["zustaendig"]["name"] == "Ben"
    assert b["whatsapp"].startswith("https://wa.me/491712222222?text=") and "20.10.2026" in b["whatsapp"].replace("%20", " ")
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (fz["id"],)).fetchone()["status"] == "besichtigung"

    ben = Client(port, OEFFENTLICH).anmelden("Ben")
    assert [t["id"] for t in ben("GET", "/api/heute")[1]["termine"]] == [b["id"]]
    status, ics, r = ben("GET", f"/api/besichtigung/{b['id']}/ics")
    assert status == 200 and "DTSTART:20261020T103000" in ics and r.getheader("Content-Type").startswith("text/calendar")

    daten = {"pruefpunkte": {"fin": True, "papiere": True, "probefahrt": True, "heizung": True},
             "messungen": {"feuchtigkeit": [{"bereich": f"P{i}", "wert": 12} for i in range(7)] + [{"bereich": "Bad", "wert": 24}],
                           "reifen": [{"position": p, "dot": "1224"} for p in ("VL", "VR", "HL", "HR")]},
             "maengel": [{"key": "bremsen", "stufe": "mittel"}], "km_abgelesen": fz["km"]}
    status, antwort, _ = ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": daten})
    voll = ben("GET", f"/api/besichtigung/{b['id']}")[1]
    erwartet = berechne(lade_katalog(BASIS / "maengel.yaml"), daten, voll["basis"])
    assert status == 200 and antwort["ergebnis"] == json.loads(json.dumps(erwartet))     # Server rechnet verbindlich
    assert antwort["ergebnis"]["vollstaendig"] and antwort["ergebnis"]["summe_maengel"] == 1800 + 700

    carl = Client(port, OEFFENTLICH).anmelden("Carl")
    assert carl("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": daten})[0] == 403   # nicht zuständig

    bild = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    status, foto, _ = ben("POST", f"/api/besichtigung/{b['id']}/foto", {"bild": bild, "mangel_key": "bremsen"})
    assert status == 200 and foto["datei"].endswith(".jpg")
    assert ben("GET", f"/fotos/{b['id']}/{foto['datei']}")[0] == 200
    assert Client(port, OEFFENTLICH)("GET", f"/fotos/{b['id']}/{foto['datei']}")[0] in (303, 401)
    assert ben("POST", f"/api/besichtigung/{b['id']}/foto", {"bild": "data:image/gif;base64,R0lGODlh"})[0] == 400

    ohne_unterschrift = {"entscheidung": "gekauft", "endpreis": 25000, "verkaeufer": {"name": "Max Muster"}}
    status, fehler, _ = ben("POST", f"/api/besichtigung/{b['id']}/abschluss", ohne_unterschrift)
    assert status == 400 and "Unterschriften" in fehler["fehler"]
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nxx").decode()
    status, ende, _ = ben("POST", f"/api/besichtigung/{b['id']}/abschluss",
                          {**ohne_unterschrift, "unterschrift_verkaeufer": png, "unterschrift_ankaeufer": png})
    assert status == 200 and ende["protokoll"] == f"/protokoll/{b['id']}"
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (fz["id"],)).fetchone()["status"] == "gekauft"
    status, html, _ = ben("GET", ende["protokoll"])
    assert status == 200 and "Ankaufprotokoll" in html and "25.000 €" in html and "Max Muster" in html and foto["datei"] in html
    assert ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": daten})[0] == 409    # abgeschlossen


def test_abschluss_verlangt_pflichtpunkte(server, team):
    port = server.server_address[1]
    anna = Client(port, OEFFENTLICH).anmelden("Anna")
    fz = anna("GET", "/api/fahrzeuge?filter=bereit")[1][1]
    b = anna("POST", "/api/besichtigung", {"anzeige_id": fz["id"]})[1]
    png = "data:image/png;base64,iVBORw0KGgo="
    kauf = {"entscheidung": "gekauft", "endpreis": 20000, "unterschrift_verkaeufer": png, "unterschrift_ankaeufer": png}
    status, fehler, _ = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", kauf)
    assert status == 400 and "Pflichtpunkte fehlen" in fehler["fehler"]
    assert anna("POST", f"/api/besichtigung/{b['id']}/abschluss", {**kauf, "begruendung_unvollstaendig": "Regen"})[0] == 200


def test_whatsapp():
    assert whatsapp_nummer("+49 170 1111111") == "491701111111"
    assert whatsapp_nummer("0171-2222222") == "491712222222" and whatsapp_nummer("0043 664 123456") == "43664123456"
    assert whatsapp_nummer("") is None and whatsapp_link("Hallo Welt").startswith("https://wa.me/?text=Hallo%20Welt")

    class FakeSitzung:
        def __init__(self):
            self.gesendet = []

        def post(self, url, json, timeout, headers):
            self.gesendet.append((url, json, headers))
            return type("R", (), {"status_code": 200, "text": "{}"})()

    cfg = {"whatsapp": {"aktiv": True, "phone_number_id": "123", "token_env": "TEST_WA_TOKEN", "api_version": "v23.0",
                        "vorlage_neue_treffer": "neue_treffer", "empfaenger_treffer": ["+491701111111"]}}
    sitzung = FakeSitzung()
    wa = WhatsAppCloud(cfg, sitzung)
    assert not wa.bereit                                                       # Token fehlt → nichts senden
    import os
    os.environ["TEST_WA_TOKEN"] = "geheim"
    try:
        assert wa.sende("+49 171 2222222", "besichtigung_zugewiesen", ["Knaus", "20.10. 10:30", "Stuttgart"])
        url, nachricht, kopf = sitzung.gesendet[0]
        assert url == "https://graph.facebook.com/v23.0/123/messages" and kopf["Authorization"] == "Bearer geheim"
        assert nachricht["to"] == "491712222222" and nachricht["template"]["name"] == "besichtigung_zugewiesen"
        assert [p["text"] for p in nachricht["template"]["components"][0]["parameters"]] == ["Knaus", "20.10. 10:30", "Stuttgart"]
    finally:
        del os.environ["TEST_WA_TOKEN"]
