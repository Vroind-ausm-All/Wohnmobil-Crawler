"""P7-03 – Öffentliches Ankaufsportal (B4): eigener Server nur mit Formular, Statusseite, Impressum, Datenschutz; signierte Links,
Spamschutz, Löschen durch den Verkäufer, keine Team-Wege."""
from __future__ import annotations

import base64
import copy
import http.client
import json
import re
import threading

import pytest

from tests.test_verkauf import GUELTIG, JPEG
from wmscout.web import portal as pt
from wmscout.web.portal import PortalFehler, Signierer, erstelle_portal, startbereit

SCHLUESSEL = "t" * 40
BILD = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


class Uhr:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _cfg(cfg, **portal):
    c = copy.deepcopy(cfg)
    c["portal"] = {**(c.get("portal") or {}), "oeffentliche_url": "https://verkaufen.example.de",
                   "impressum": {"name": "Muster Wohnmobile GmbH", "anschrift": "Musterweg 1\n74354 Besigheim", "email": "info@example.de"},
                   **portal}
    return c


@pytest.fixture
def uhr():
    return Uhr()


@pytest.fixture
def portal(cfg, db, uhr):
    from tests.daten import BASIS
    srv = erstelle_portal(_cfg(cfg), db, BASIS, SCHLUESSEL, port=0, uhr=uhr)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def rufe(srv, methode, pfad, daten=None, host=None, kopf=None, roh=None):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = roh if roh is not None else (json.dumps(daten).encode() if daten is not None else None)
    k = {"Host": host or f"127.0.0.1:{port}", **({"Content-Type": "application/json"} if body is not None else {}), **(kopf or {})}
    c.request(methode, pfad, body=body, headers=k)
    r = c.getresponse()
    text = r.read().decode("utf-8", "replace")
    c.close()
    try:
        return r.status, json.loads(text), dict(r.getheaders())
    except ValueError:
        return r.status, text, dict(r.getheaders())


def formular(srv, uhr):
    html = rufe(srv, "GET", "/verkaufen")[1]
    token = json.loads(re.search(r"FORMULAR = (\"[^\"]*\");", html).group(1))
    uhr.t += 5                                                                   # Mindest-Ausfüllzeit vorbei
    return token


def anfrage(srv, uhr, **extra):
    return rufe(srv, "POST", "/api/portal/anfrage", {**GUELTIG, "formular": formular(srv, uhr), "feld_leer": "", **extra})


def foto(srv, upload, bild=BILD):
    return rufe(srv, "POST", "/api/portal/foto", {"bild": bild}, kopf={"X-Portal-Upload": upload} if upload else None)


def status_token(antwort):
    return antwort["status_link"].split("#", 1)[1]


# ---------------------------------------------------------------- 1. Start nur mit Freigabe und vollständiger Konfiguration
def test_startbereit_und_einstellungen(cfg, monkeypatch):
    monkeypatch.delenv(pt.UMGEBUNG_SCHLUESSEL, raising=False)
    gruende = startbereit(cfg, None)
    assert any("aktiv" in g for g in gruende) and any("oeffentliche_url" in g for g in gruende) and any("impressum" in g for g in gruende)
    assert any(pt.UMGEBUNG_SCHLUESSEL in g for g in gruende)
    assert startbereit(_cfg(cfg, aktiv=True, vertrauter_proxy=True), "kurz")
    assert startbereit(_cfg(cfg, aktiv=True, vertrauter_proxy=True), SCHLUESSEL) == []
    assert any("vertrauter_proxy" in g for g in startbereit(_cfg(cfg, aktiv=True), SCHLUESSEL))          # QA B5
    assert cfg["portal"]["aktiv"] is False                                     # ausgeliefert: aus
    with pytest.raises(PortalFehler, match="https"):
        pt.einstellungen(_cfg(cfg, oeffentliche_url="http://verkaufen.example.de"))
    with pytest.raises(PortalFehler, match="port"):
        pt.einstellungen(_cfg(cfg, port="8770"))
    with pytest.raises(PortalFehler, match="startet nicht"):
        pt.starte_portal(cfg, None, None)                                     # ohne Freigabe: kein Server, keine Datenbank nötig


def test_signierer_und_bremse(uhr):
    s = Signierer(SCHLUESSEL, uhr)
    t = s.erstelle("status", 7, 60)
    assert s.pruefe("status", t) == "7" and s.pruefe("upload", t) is None                  # Zweck gebunden
    assert Signierer("x" * 40, uhr).pruefe("status", t) is None                            # anderer Schlüssel
    wert, ablauf, sig = t.split(".")
    assert s.pruefe("status", f"8.{ablauf}.{sig}") is None and s.pruefe("status", f"7.{int(ablauf) + 1}.{sig}") is None
    assert s.pruefe("status", None) is None and s.pruefe("status", "x" * 300) is None
    uhr.t += 61
    assert s.pruefe("status", t) is None                                                   # abgelaufen
    b = pt.Bremse(2, 60, uhr=uhr)
    assert [b.erlaubt("a"), b.erlaubt("a"), b.erlaubt("a"), b.erlaubt("b")] == [True, True, False, True]
    uhr.t += 61
    assert b.erlaubt("a") and pt.Bremse(0, 60).erlaubt("a")


# ---------------------------------------------------------------- 2. Nur Portal-Wege
def test_nur_portal_wege(portal):
    assert rufe(portal, "GET", "/")[0] == 303 and rufe(portal, "GET", "/")[2]["Location"] == "/verkaufen"
    status, html, kopf = rufe(portal, "GET", "/verkaufen")
    assert status == 200 and kopf["X-Frame-Options"] == "DENY" and "Content-Security-Policy" in kopf
    assert 'href="/anfragen"' not in html and "Ankaufsliste" not in html and 'name="kanal"' not in html and "PORTAL = true" in html
    assert 'name="feld_leer"' in html and 'href="/impressum"' in html and 'href="/datenschutz"' in html and "data-entwurf" in html
    for pfad in ("/anfragen", "/api/verkaufsanfragen", "/api/fahrzeuge", "/login", "/m", "/kennzahlen", "/static/mobil.js", "/static/../config.yaml",
                 "/sw.js", "/api/ich"):
        assert rufe(portal, "GET", pfad)[0] == 404, pfad
    for pfad in ("/api/verkaufsanfrage", "/api/login", "/api/status"):
        assert rufe(portal, "POST", pfad, {})[0] == 404, pfad
    assert rufe(portal, "GET", "/static/mobil.css")[0] == 200 and rufe(portal, "GET", "/gesund")[1] == {"ok": True}
    assert rufe(portal, "GET", "/verkaufen", host="boese.example")[0] == 403
    assert rufe(portal, "GET", "/verkaufen", host="verkaufen.example.de")[0] == 200
    impressum = rufe(portal, "GET", "/impressum")[1]
    assert "Muster Wohnmobile GmbH" in impressum and "74354 Besigheim" in impressum and "§ 5 DDG" in impressum
    ds = rufe(portal, "GET", "/datenschutz")[1]
    assert "Art. 6 Abs. 1 lit. a DSGVO" in ds and "keine Cookies" in ds and "vom Betreiber zu ergänzen" in ds
    assert "noindex" in rufe(portal, "GET", "/status")[1]


def test_team_formular_unveraendert(cfg, db):
    from tests.daten import BASIS
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(BASIS / "vorlagen")), autoescape=True)
    html = env.get_template("verkaufen.html").render(firma="F", token="abc", arten=["Alkoven"], maengel={}, kanaele={"telefon": "Telefon"},
                                                     status={}, ich={"id": 1}, team=True)
    assert 'href="/anfragen"' in html and 'name="kanal"' in html and 'name="feld_leer"' not in html and "PORTAL = false" in html


# ---------------------------------------------------------------- 3. Anfrage, Fotos, Status, Löschen
def test_anfrage_fotos_status_und_loeschen(portal, db, uhr):
    status, a, _ = anfrage(portal, uhr, kanal="telefon")
    assert status == 200 and a["referenz"].startswith("VA-") and a["status_link"].startswith("https://verkaufen.example.de/status#")
    r = db.con.execute("SELECT v.id, v.kanal, v.erfasst_von, k.name FROM verkaufsanfragen v JOIN verkaeufer k ON k.id=v.verkaeufer_id").fetchone()
    assert (r["kanal"], r["erfasst_von"], r["name"]) == ("formular", None, "Erika Beispiel")   # Eingangsweg setzt nie der Absender
    assert foto(portal, a["upload"])[0] == 200
    assert foto(portal, status_token(a))[0] == 403                                                             # Status-Token lädt nichts hoch
    assert foto(portal, None)[0] == 403
    st = rufe(portal, "POST", "/api/portal/status", {"token": status_token(a)})[1]
    assert st["referenz"] == a["referenz"] and st["fotos"] == 1 and st["geloescht"] is False and "prüfen" in st["status"]
    assert all(x not in json.dumps(st) for x in ("Erika", "0170", "12345", "bearbeiter"))                    # keine Personen- oder Teamdaten
    assert rufe(portal, "POST", "/api/portal/status", {"token": a["upload"]})[0] == 403
    assert rufe(portal, "POST", "/api/portal/loeschen", {"token": status_token(a)})[0] == 400                 # ohne Bestätigung
    assert rufe(portal, "POST", "/api/portal/loeschen", {"token": status_token(a), "bestaetigt": True})[1] == {"ok": True}
    st = rufe(portal, "POST", "/api/portal/status", {"token": status_token(a)})[1]
    assert st["geloescht"] is True and "gelöscht" in st["status"]
    k = db.con.execute("SELECT k.name, k.telefon, v.status FROM verkaufsanfragen v JOIN verkaeufer k ON k.id=v.verkaeufer_id").fetchone()
    assert tuple(k) == ("(gelöscht)", "(gelöscht)", "zurueckgezogen")
    assert db.con.execute("SELECT COUNT(*) FROM anfrage_fotos").fetchone()[0] == 0
    assert foto(portal, a["upload"])[0] == 403                                                                 # nach Widerruf keine Fotos
    uhr.t += 3601
    assert foto(portal, a["upload"])[0] == 403                                                                 # Upload-Link abgelaufen


def test_loeschen_mit_ankauf_verweigert(portal, db, uhr):
    a = anfrage(portal, uhr)[1]
    aid = db.con.execute("SELECT id FROM verkaufsanfragen").fetchone()[0]
    from wmscout.team import TeamSpeicher
    bid = TeamSpeicher(db, portal.kontext.foto_ordner).besichtigung_anlegen(f"anfrage-{aid}", {"fahrzeug": "Hymer"}, None, None, None, None)
    db.con.execute("INSERT INTO ankaeufe (herkunft, anfrage_id, besichtigung_id, status, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('anfrage', ?, ?, 'gekauft', 30000, '{}', '2026-11-02T10:00:00')", (aid, bid))
    db.con.commit()
    status, antwort, _ = rufe(portal, "POST", "/api/portal/loeschen", {"token": status_token(a), "bestaetigt": True})
    assert status == 409 and "persönlich" in antwort["fehler"]
    assert db.con.execute("SELECT name FROM verkaeufer").fetchone()[0] == "Erika Beispiel"


# ---------------------------------------------------------------- 4. Spamschutz und Eingangsprüfung
def test_spamschutz(cfg, db, uhr, portal):
    token = formular(portal, uhr)
    uhr.t -= 4                                                                   # zu schnell abgeschickt
    assert rufe(portal, "POST", "/api/portal/anfrage", {**GUELTIG, "formular": token})[0] == 400
    assert rufe(portal, "POST", "/api/portal/anfrage", {**GUELTIG, "formular": "gefaelscht"})[0] == 400
    uhr.t += 25 * 3600
    assert rufe(portal, "POST", "/api/portal/anfrage", {**GUELTIG, "formular": token})[0] == 400              # Formular abgelaufen
    status, a, _ = anfrage(portal, uhr, feld_leer="https://spam.example")                                   # verstecktes Feld
    assert status == 200 and a["status_link"] is None and a["upload"] is None
    assert db.con.execute("SELECT COUNT(*) FROM verkaufsanfragen").fetchone()[0] == 0
    assert rufe(portal, "POST", "/api/portal/anfrage", roh=b"art=x", kopf={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    assert rufe(portal, "POST", "/api/portal/anfrage", {**GUELTIG}, kopf={"Origin": "https://boese.example"})[0] == 403
    assert rufe(portal, "POST", "/api/portal/anfrage", roh=b"x" * (pt.MAX_ANFRAGE_JSON + 1))[0] == 413
    status, antwort, _ = anfrage(portal, uhr, einwilligung=False)
    assert status == 400 and "Einwilligung" in antwort["fehler"]
    assert [anfrage(portal, uhr)[0] for _ in range(6)] == [200] * 5 + [429]                                 # je IP und Stunde
    uhr.t += 3601
    assert db.con.execute("SELECT COUNT(*) FROM verkaufsanfragen").fetchone()[0] == 5


def test_proxy_ip_nur_wenn_vertraut(cfg, db, uhr):
    from tests.daten import BASIS
    for vertraut, erwartet in ((False, [200, 429, 429]), (True, [200, 200, 429])):
        srv = erstelle_portal(_cfg(cfg, anfragen_je_ip_stunde=1, vertrauter_proxy=vertraut), db, BASIS, SCHLUESSEL, port=0, uhr=uhr)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ergebnis = [rufe(srv, "POST", "/api/portal/anfrage", {**GUELTIG, "formular": formular(srv, uhr)}, kopf={"X-Forwarded-For": ip})[0]
                        for ip in ("1.1.1.1", "2.2.2.2", "2.2.2.2")]
        finally:
            srv.shutdown()
            srv.server_close()
        assert ergebnis == erwartet, vertraut


def test_korrekturrunde_qa(cfg, db, uhr, portal, monkeypatch):
    """QA P7-03: Nicht-ASCII-Token und tiefe Verschachtelung → 4xx statt 500 (B2); Origin mit Schema (B7); Fotos über das Portal höchstens 12,
    Upload für fremde ID (B3); Bewertung wirft → trotzdem gespeichert (B8); Listen nicht als Text (B10)."""
    assert rufe(portal, "POST", "/api/portal/status", {"token": "1.1." + "ä" * 43})[0] == 403
    assert rufe(portal, "POST", "/api/portal/anfrage", roh=b"[" * 15000)[0] == 400
    assert rufe(portal, "POST", "/api/portal/status", {"token": "x"}, kopf={"Origin": "http://verkaufen.example.de"})[0] == 403
    assert rufe(portal, "POST", "/api/portal/status", {"token": "x"}, kopf={"Origin": "https://verkaufen.example.de"})[0] == 403  # Token, nicht Herkunft
    a = anfrage(portal, uhr, marke="Hymer", modell={"x": 1})[1]
    assert db.con.execute("SELECT modell FROM verkaufsanfragen").fetchone()[0] is None
    assert [foto(portal, a["upload"])[0] for _ in range(13)] == [200] * 12 + [400]
    fremd = portal.kontext.signierer.erstelle("upload", 999, 60)
    assert foto(portal, fremd)[0] == 403
    monkeypatch.setattr(pt.vk, "bewerte", lambda *x: 1 / 0)
    status, b, _ = anfrage(portal, uhr)
    assert status == 200 and b["spanne"] is None and b["status_link"]
    assert db.con.execute("SELECT COUNT(*) FROM verkaufsanfragen").fetchone()[0] == 2


def test_bremse_vergisst_und_post_grenze(cfg, db, uhr):
    b = pt.Bremse(5, 60, uhr=uhr)
    for i in range(1000):
        b.erlaubt(f"ip{i}")
    uhr.t += 61
    b.erlaubt("neu")
    assert b.anzahl() == 1                                                                 # IP-Adressen nach einem Fenster vergessen (B4)
    from tests.daten import BASIS
    srv = erstelle_portal(_cfg(cfg, sendungen_je_ip_minute=3), db, BASIS, SCHLUESSEL, port=0, uhr=uhr)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        codes = [rufe(srv, "POST", "/api/portal/status", {"token": "x"})[0] for _ in range(4)]
        assert codes == [403, 403, 403, 429]                                               # vor dem Lesen des Inhalts (B3)
        assert [rufe(srv, "GET", "/static/mobil.css")[0] for _ in range(70)].count(200) == 70     # statische Dateien zählen nicht (B5)
    finally:
        srv.shutdown()
        srv.server_close()


def test_impressum_ohne_entwurf_und_cli(cfg, db, monkeypatch):
    from tests.daten import BASIS
    srv = erstelle_portal(_cfg(cfg, texte_geprueft=True), db, BASIS, SCHLUESSEL, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert "data-entwurf" not in rufe(srv, "GET", "/impressum")[1]
    finally:
        srv.shutdown()
        srv.server_close()
    import scout
    monkeypatch.delenv(pt.UMGEBUNG_SCHLUESSEL, raising=False)
    with pytest.raises(SystemExit, match="aktiv"):
        scout.cmd_portal(cfg, db, type("A", (), {"port": None})())
