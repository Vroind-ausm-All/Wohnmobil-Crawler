"""Phase G0 – Härtung nach der Sicherheitsprüfung (ADR-030). Jeder Test belegt einen Befund (H1–H3, M4, M5, M9, M10, M11,
N12–N15, N18, N19) am laufenden Testserver oder an der reinen Funktion."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import http.client
import json
import socket
import struct
import time
import zlib

from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.benachrichtigung import _maskiert
from wmscout.quellen.basis import http_url
from wmscout.team import ohne_metadaten
from wmscout.web import api
from wmscout.web.sicherheit import LoginBremse


def roh(server, methode, pfad, body=b"", kopf=None):
    port = server.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(methode, pfad, body=body, headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **(kopf or {})})
    r = c.getresponse()
    return r.status, r.read(), r


# ---------------------------------------------------------------- H1: Länge und Host vor dem Lesen
def test_negative_oder_kaputte_laenge_wird_sofort_abgelehnt(server):
    port = server.server_address[1]
    for laenge in (b"-1", b"abc"):
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Length: %s\r\n\r\n" % (port, laenge))
        start = time.monotonic()
        antwort = s.recv(200)
        s.close()
        assert antwort.startswith(b"HTTP/1.0 400") and time.monotonic() - start < 2, antwort


def test_fremder_host_liest_den_inhalt_gar_nicht(server):
    s = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5)
    s.sendall(b"POST /api/login HTTP/1.1\r\nHost: evil.example\r\nContent-Length: 100000\r\n\r\n")   # Inhalt kommt nie
    start = time.monotonic()
    antwort = s.recv(200)
    s.close()
    assert antwort.startswith(b"HTTP/1.0 403") and time.monotonic() - start < 2


# ---------------------------------------------------------------- H2: Bremse, Herkunft, Zeitverhalten
def test_login_bremse_je_ip_und_name():
    uhr = [0.0]
    b = LoginBremse(max_je_name=3, max_je_ip=5, fenster_sek=60, uhr=lambda: uhr[0])
    for _ in range(3):
        assert b.wartezeit("1.1.1.1", "Anna") == 0
        b.fehlschlag("1.1.1.1", "Anna")
    assert b.wartezeit("1.1.1.1", "anna ") == 60                       # Name ohne Groß/Klein und Leerzeichen
    assert b.wartezeit("2.2.2.2", "Anna") == 0                          # andere Geräte sperrt ein Angreifer nicht
    b.fehlschlag("1.1.1.1", "Ben")
    b.fehlschlag("1.1.1.1", "Carl")
    assert b.wartezeit("1.1.1.1", "Dora") == 60                         # Grenze je IP
    uhr[0] = 61
    assert b.wartezeit("1.1.1.1", "Anna") == 0                          # Fenster abgelaufen
    for _ in range(2):
        b.fehlschlag("3.3.3.3", "Ben")
    b.erfolg("3.3.3.3", "Ben")                                           # Erfolg setzt den Namen zurück, die IP-Zählung bleibt
    b.fehlschlag("3.3.3.3", "Ben")
    b.fehlschlag("3.3.3.3", "Ben")
    assert b.wartezeit("3.3.3.3", "Ben") == 0


def test_login_sperrt_nach_fehlversuchen_auch_mit_richtigem_passwort(server, team, monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda _s: None)
    login = {"name": "Ben", "passwort": "falsch"}
    for _ in range(5):
        assert roh(server, "POST", "/api/login", json.dumps(login))[0] == 401
    s, body, r = roh(server, "POST", "/api/login", json.dumps({"name": "Ben", "passwort": "sicher1234"}))
    assert s == 429 and json.loads(body)["warten_sek"] > 0
    assert roh(server, "POST", "/api/login", json.dumps({"name": "Carl", "passwort": "sicher1234"}))[0] == 200   # anderer Name


def test_login_nur_json_und_nicht_von_fremden_seiten(server, team):
    gut = json.dumps({"name": "Anna", "passwort": "sicher1234"})
    assert roh(server, "POST", "/api/login", gut, {"Content-Type": "text/plain"})[0] == 415
    assert roh(server, "POST", "/api/login", gut, {"Origin": "https://evil.example"})[0] == 403
    assert roh(server, "POST", "/api/login", gut, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    port = server.server_address[1]
    assert roh(server, "POST", "/api/login", gut, {"Origin": f"http://127.0.0.1:{port}"})[0] == 200


def test_unbekannter_name_prueft_ebenfalls_einen_hash(team):
    nid, h = team.login_daten("gibt-es-nicht")
    assert nid is None and h.startswith("scrypt$") and team.anmelden("gibt-es-nicht", "x") is None
    assert team.anmelden("Anna", "sicher1234")


# ---------------------------------------------------------------- H3: fremde Verkaufsanfragen
def test_mitarbeiter_aendert_keine_anfrage_eines_kollegen(markt, db):
    anna, ben, anfrage = markt["anna"], markt["ben"], markt["anfrage"]
    carl = anmelden_carl(markt)
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/uebernehmen", {})[0] == 200
    for art, daten in (("uebernehmen", {}), ("status", {"status": "angebot"}), ("notiz", {"notiz": "x"}),
                       ("uebernehmen", {"abgeben": True})):
        s, d, _ = carl("POST", f"/api/verkaufsanfrage/{anfrage}/{art}", daten)
        assert s == 403 and "Ben" in d["fehler"], art
    assert carl("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[0] in (403, 404)            # (Phase F: 403)
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/status", {"status": "in_pruefung"})[0] == 200    # Bearbeiter darf
    assert anna("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "Inhaber darf"})[0] == 200
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/uebernehmen", {"abgeben": True})[0] == 200
    assert carl("POST", f"/api/verkaufsanfrage/{anfrage}/uebernehmen", {})[0] == 200                     # jetzt frei
    assert db.con.execute("SELECT n.name FROM verkaufsanfragen v JOIN nutzer n ON n.id=v.bearbeiter_id WHERE v.id=?",
                          (anfrage,)).fetchone()[0] == "Carl"


def anmelden_carl(markt):
    from tests.test_handy import Client
    port = int(markt["anna"].port)
    return Client(port).anmelden("Carl")


# ---------------------------------------------------------------- M4, M5, M10, M11, N18: Weiterleitung, Kopf, lokal
def test_sicherheits_kopf_und_server_kennung(server, team):
    s, _, r = roh(server, "GET", "/login")
    assert s == 200 and "frame-ancestors 'none'" in r.getheader("Content-Security-Policy") and r.getheader("X-Frame-Options") == "DENY"
    assert "Python" not in (r.getheader("Server") or "")
    from wmscout.app import baue_handler
    assert baue_handler(None).timeout == 30


def test_login_weiterleitung_nur_auf_eigene_seiten(server):
    html = roh(server, "GET", "/login")[1].decode()
    assert "u.origin === location.origin" in html and "weiter.charAt(0)" not in html


def test_ohne_nutzer_ist_ein_proxy_nicht_lokal(server):
    assert roh(server, "GET", "/api/ich")[0] == 200                                        # wirklich lokal
    for kopf in ({"X-Forwarded-For": "203.0.113.5"}, {"Forwarded": "for=203.0.113.5"}, {"X-Forwarded-Proto": "https"}):
        s, body, _ = roh(server, "GET", "/api/ich", kopf=kopf)
        assert s == 403 and "Zugriff von außen" in json.loads(body)["fehler"], kopf


def test_cookie_secure_nur_bei_https_einstellung(server, team):
    _, _, r = roh(server, "POST", "/api/login", json.dumps({"name": "Anna", "passwort": "sicher1234"}), {"X-Forwarded-Proto": "https"})
    assert "Secure" not in r.getheader("Set-Cookie")                                        # Kopf allein genügt nicht


def test_cookie_secure_mit_nur_https(cfg, db, importiert, team):
    from tests.test_team_bearbeitung import starte
    cfg["app"]["nur_https"] = True
    srv = starte(cfg, db)
    try:
        _, _, r = roh(srv, "POST", "/api/login", json.dumps({"name": "Anna", "passwort": "sicher1234"}))
        assert r.getheader("Set-Cookie").endswith("; Secure")
    finally:
        srv.shutdown()
        srv.server_close()


def test_whatsapp_nummer_im_protokoll_maskiert():
    assert _maskiert("+491701234567") == "+491…67" and _maskiert("123") == "…"


# ---------------------------------------------------------------- N12, N15, N19
def test_nur_http_links_aus_seiten():
    from tests.daten import baue_ads, such_html
    from wmscout.quellen.kleinanzeigen.parser import parse_suchseite
    assert http_url("javascript:alert(1)") is None and http_url(" https://x.de/a ") == "https://x.de/a" and http_url(None) is None
    a = baue_ads(1)[0]
    html = such_html([a]).replace(f"/s-anzeige/{a['slug']}/{a['id']}-220-1234", "javascript:alert(document.domain)")
    treffer = parse_suchseite(html)
    assert treffer and all(not (t.get("url") or "").lower().startswith("javascript") for t in treffer)


def _jpeg_mit_exif() -> bytes:
    exif = b"Exif\x00\x00" + b"GPS-DATEN" * 4
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    com = b"\xff\xfe" + struct.pack(">H", 9) + b"Kamera"
    return b"\xff\xd8" + app0 + app1 + com + b"\xff\xda\x00\x08BILDDATEN\xff\xd9"


def _png_mit_exif() -> bytes:
    def chunk(typ, daten):
        return struct.pack(">I", len(daten)) + typ + daten + struct.pack(">I", zlib.crc32(typ + daten))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\x00" * 13) + chunk(b"eXIf", b"GPS-DATEN") + chunk(b"tEXt", b"Autor\x00Erika") \
        + chunk(b"IDAT", b"BILD") + chunk(b"IEND", b"")


def test_metadaten_werden_entfernt_bilddaten_bleiben():
    j = ohne_metadaten(_jpeg_mit_exif())
    assert b"GPS-DATEN" not in j and b"Kamera" not in j and b"JFIF" in j and j.endswith(b"BILDDATEN\xff\xd9")
    p = ohne_metadaten(_png_mit_exif())
    assert b"GPS-DATEN" not in p and b"Erika" not in p and b"IHDR" in p and b"IDAT" in p and p.endswith(b"IEND\xae\x42\x60\x82")
    assert ohne_metadaten(b"RIFF....WEBP") == b"RIFF....WEBP"


def test_hochgeladenes_foto_ohne_exif_gespeichert(markt, db):
    import base64
    from pathlib import Path
    anna, anfrage = markt["anna"], markt["anfrage"]
    datei = anna("POST", f"/api/verkaufsanfrage/{anfrage}/foto",
                 {"bild": "data:image/jpeg;base64," + base64.b64encode(_jpeg_mit_exif()).decode()})[1]["datei"]
    pfad = Path(db.con.execute("PRAGMA database_list").fetchone()[2]).parent / "fotos" / "anfragen" / str(anfrage) / datei
    assert b"GPS-DATEN" not in pfad.read_bytes() and b"BILDDATEN" in pfad.read_bytes()


def test_mangel_key_muss_text_sein(server, team):
    anna = anmelden(server, "Anna")
    fz = anna("GET", "/api/fahrzeuge?filter=bereit")[1][0]
    b = anna("POST", "/api/besichtigung", {"anzeige_id": fz["id"], "adresse": "x" * 1000})[1]
    assert len(anna("GET", f"/api/besichtigung/{b['id']}")[1]["adresse"]) == 200
    assert anna("POST", f"/api/besichtigung/{b['id']}/foto", {"bild": "x", "mangel_key": {"a": 1}})[0] == 400


