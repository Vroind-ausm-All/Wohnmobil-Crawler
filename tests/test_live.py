"""G1 (ADR-032): Live-Aktualisierung per Server-Sent Events und Nutzungszähler."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import http.client
import json
import queue
import threading
import time

import pytest

from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_cli import _scout
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.nutzung import monat_grenzen, nutzung
from wmscout.web.live import Ereignisse, art_fuer, sse_block


# ---------------------------------------------------------------- rein
def test_ereignisse_filter_luecke_und_grenzen():
    e = Ereignisse(max_je_nutzer=2, max_gesamt=3, puffer=3)
    e.melde("anfrage", 7)
    e.melde("auktion", 3)
    neu, luecke, aktuell = e.seit(0, haendler=False)
    assert [(x["art"], x["id"]) for x in neu] == [("anfrage", 7), ("auktion", 3)] and not luecke and aktuell == 2
    neu, _, aktuell = e.seit(0, haendler=True)
    assert neu == [{"stand": 2, "art": "auktion"}] and aktuell == 2                       # Händler: nur Auktionen, ohne ID
    for _ in range(5):
        e.melde("team")
    assert e.seit(1, False)[1] is True and e.seit(e.stand, False) == ([], False, 7)       # aus dem Puffer gefallen → alles neu
    assert e.warte(e.stand, 0.05) is False
    threading.Timer(0.05, e.melde, ("team",)).start()
    assert e.warte(e.stand, 2) is True
    assert e.oeffnen(1) and e.oeffnen(1) and not e.oeffnen(1) and e.oeffnen(2) and not e.oeffnen(3)
    e.schliessen(1)
    assert e.oeffnen(3) and e.offen() == 3


def test_art_und_format():
    assert art_fuer("/api/haendler/auktion/4/gebot") == ("auktion", 4)
    assert art_fuer("/api/verkaufsanfrage/9/auktion") == ("auktion", 9)
    assert art_fuer("/api/verkaufsanfrage/9/notiz") == ("anfrage", 9)
    assert art_fuer("/api/ankauf/2/kosten") == ("ankauf", 2) and art_fuer("/api/besichtigung/5/abschluss") == ("ankauf", 5)
    assert art_fuer("/api/bearbeitung/x/uebernehmen") == ("team", None) and art_fuer("/api/login") is None
    b = sse_block({"stand": 3, "art": "anfrage", "id": 9}).decode()
    assert b == 'id: 3\nevent: aenderung\ndata: {"stand": 3, "art": "anfrage", "id": 9}\n\n'
    assert sse_block(kommentar="ping") == b": ping\n\n"


# ---------------------------------------------------------------- HTTP
class Strom:
    """Liest einen SSE-Strom im Hintergrund; ``ereignisse`` sammelt die data-Zeilen."""

    def __init__(self, server, client, letzte_id=None):
        self.c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        kopf = {"Host": f"127.0.0.1:{server.server_address[1]}", "Cookie": client.cookie or ""}
        if letzte_id is not None:
            kopf["Last-Event-ID"] = str(letzte_id)
        self.c.request("GET", "/api/ereignisse", headers=kopf)
        self.r = self.c.getresponse()
        self.ereignisse: queue.Queue = queue.Queue()
        if self.r.status == 200:
            threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self):
        try:
            for zeile in self.r:
                if zeile.startswith(b"data: "):
                    self.ereignisse.put(json.loads(zeile[6:]))
        except (OSError, ValueError):
            pass

    def naechstes(self, sek=3):
        return self.ereignisse.get(timeout=sek)

    def leer(self, sek=0.5) -> bool:
        try:
            self.ereignisse.get(timeout=sek)
            return False
        except queue.Empty:
            return True

    def zu(self):
        self.c.close()


def test_sse_meldet_aenderungen_nach_rolle(markt, server):
    k = server.RequestHandlerClass.kontext
    k.live_ping = 0.2
    anna, ben, hugo, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["anfrage"]
    sb, sh = Strom(server, ben), Strom(server, hugo)
    assert sb.r.status == 200 and sb.r.getheader("Content-Type").startswith("text/event-stream")
    assert sb.r.getheader("X-Accel-Buffering") == "no" and "frame-ancestors" in sb.r.getheader("Content-Security-Policy")
    time.sleep(0.3)
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "geheim"})
    e = sb.naechstes()
    assert (e["art"], e["id"]) == ("anfrage", anfrage) and "geheim" not in json.dumps(e)
    assert sh.leer()                                                                      # Händler sieht Anfragen nicht
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 20000})
    assert sb.naechstes()["art"] == "auktion"
    assert sh.naechstes() == {"stand": e["stand"] + 1, "art": "auktion"}                   # ohne ID
    assert hugo("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "x"})[0] == 403  # abgelehnt → kein Ereignis
    assert sb.leer()
    # Wiederaufnahme: verpasstes Ereignis wird nachgeliefert
    sb.zu()
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "x"})
    s2 = Strom(server, ben, letzte_id=e["stand"] + 1)
    assert s2.naechstes()["stand"] == e["stand"] + 2
    s2.zu()
    sh.zu()


def test_sse_nur_angemeldet_und_begrenzt(markt, server):
    from tests.test_handy import Client
    k = server.RequestHandlerClass.kontext
    k.live.max_je_nutzer, k.live_lebensdauer, k.live_ping = 1, 1.0, 0.2
    fremd = Strom(server, Client(server.server_address[1]))
    assert fremd.r.status == 401
    erst = Strom(server, markt["ben"])
    assert erst.r.status == 200
    zweit = Strom(server, markt["ben"])
    assert zweit.r.status == 429
    ende = time.monotonic() + 3
    while k.live.offen() and time.monotonic() < ende:
        time.sleep(0.05)
    assert k.live.offen() == 0                                                            # Lebensdauer abgelaufen: Platz frei
    for s in (fremd, erst, zweit):
        s.zu()


# ---------------------------------------------------------------- Nutzungszähler
def test_nutzung_zaehlt_aus_vorhandenen_daten(markt, db):
    anna, ben, hugo, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["anfrage"]
    auk = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 20000})[1]["id"]
    hugo("POST", f"/api/haendler/auktion/{auk}/gebot", {"betrag": 20000, "wiederholungs_id": "nutzung-001"})
    ben("GET", f"/api/verkaufsanfrage/{anfrage}")
    n = nutzung(db)
    z = n["zaehler"]
    assert (z["verkaufsanfragen"], z["auktionen"], z["gebote"], z["kalkulationen"]) == (1, 1, 1, 1)
    assert z["anmeldungen"] == 4 and z["zugriffe_personendaten"] >= 1 and z["aenderungen"] >= 3 and z["aktive_nutzer"] == 3
    assert {x["nutzer"] for x in n["je_nutzer"]} == {"Anna", "Ben", "Hugo"}
    assert nutzung(db, "2001-01")["zaehler"]["gebote"] == 0
    assert anna("GET", "/api/nutzung")[1]["zaehler"]["gebote"] == 1
    assert ben("GET", "/api/nutzung")[0] == 403 and hugo("GET", "/api/nutzung")[0] == 403
    assert anna("GET", "/api/nutzung?monat=2026-13")[0] == 400


def test_monat_grenzen():
    assert monat_grenzen("2026-12") == ("2026-12", "2026-12-01", "2027-01-01")
    assert monat_grenzen("2026-01")[2] == "2026-02-01"
    with pytest.raises(ValueError):
        monat_grenzen("10/2026")


def test_cli_nutzung(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "nutzung", "--monat", "2026-10")
    assert r.returncode == 0 and "Nutzung 2026-10" in r.stdout and "verkaufsanfragen" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "nutzung", "--monat", "Oktober")
    assert r.returncode != 0 and "JJJJ-MM" in r.stderr
