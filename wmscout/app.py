"""Lokale Browser-App:  python scout.py app

Wohnmobil anklicken → Bewertung + fertiges Anschreiben; „✉ Anschreiben“ kopiert den Text, öffnet die
Anzeige und speichert den Status „kontaktiert“ (samt gesendetem Text) direkt in der Datenbank.
Der Server lauscht nur auf 127.0.0.1 – er ist von anderen Rechnern aus nicht erreichbar.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .crawler import Crawler
from .db import Datenbank
from .report import bewerte_alle, render_html

log = logging.getLogger("scout")
STATUS = {"neu", "kontaktiert", "uninteressant", "gekauft"}


class Suchlauf:
    """Crawl im Hintergrund – höchstens einer gleichzeitig, mit eigener DB-Verbindung."""

    def __init__(self, cfg: dict, db_pfad: str):
        self.cfg, self.db_pfad = cfg, db_pfad
        self.thread: threading.Thread | None = None
        self.letzter_start: str | None = None
        self.stand = {"laeuft": False, "meldung": "", "fehler": None, "ende": None}
        stand = self.stand

        class Meldungen(logging.Handler):
            def emit(self, record):
                if stand["laeuft"]:
                    stand["meldung"] = record.getMessage()

        log.addHandler(Meldungen(logging.INFO))

    def starte(self) -> bool:
        if self.thread and self.thread.is_alive():
            return False
        self.letzter_start = datetime.now().isoformat(timespec="seconds")
        self.stand.update(laeuft=True, meldung="Suche startet …", fehler=None, ende=None)
        self.thread = threading.Thread(target=self._lauf, daemon=True)
        self.thread.start()
        return True

    def _lauf(self):
        try:
            stat = Crawler(self.cfg, Datenbank(self.db_pfad)).lauf(self.cfg["suchen"])
            self.stand.update(fehler=stat["fehler"], meldung=(
                f"Fertig: {stat['neu']} neu, {stat['preis']} Preissenkungen, {stat['details']} Detailseiten"))
        except Exception as e:  # noqa: BLE001 – Fehler in der Oberfläche anzeigen statt Thread sterben lassen
            log.exception("Suchlauf fehlgeschlagen")
            self.stand.update(fehler=str(e), meldung="Suchlauf fehlgeschlagen")
        finally:
            self.stand.update(laeuft=False, ende=datetime.now().isoformat(timespec="seconds"))


def baue_handler(cfg: dict, db: Datenbank, basis: Path, token: str, suchlauf: Suchlauf):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WohnmobilScout"

        def log_message(self, fmt, *args):
            log.debug("app: " + fmt, *args)

        def _antwort(self, code: int, body: bytes, typ: str):
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._antwort(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            # Schutz gegen DNS-Rebinding: nur Aufrufe über die lokale Adresse
            port = self.server.server_address[1]
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"fehler": "nur lokal erreichbar"})
            pfad = urlparse(self.path).path
            if pfad in ("/", "/index.html"):
                seit = suchlauf.letzter_start or (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
                zeilen = bewerte_alle(cfg, db, basis, lauf_start=seit)
                html, _ = render_html(cfg, zeilen, basis, fehler=suchlauf.stand["fehler"], app={"token": token})
                return self._antwort(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if pfad == "/api/suchlauf":
                return self._json(200, suchlauf.stand)
            return self._json(404, {"fehler": "nicht gefunden"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Scout-Token") != token:
                return self._json(403, {"fehler": "Zugriff verweigert – Seite bitte neu laden"})
            try:
                laenge = int(self.headers.get("Content-Length") or 0)
                daten = json.loads(self.rfile.read(laenge)) if laenge else {}
            except ValueError:
                return self._json(400, {"fehler": "ungültige Anfrage"})
            pfad = urlparse(self.path).path
            if pfad == "/api/status":
                if daten.get("status") not in STATUS:
                    return self._json(400, {"fehler": "unbekannter Status"})
                text = daten.get("text")
                ok = db.setze_status(str(daten.get("id")), daten["status"], text=str(text)[:5000] if text else None)
                return self._json(200 if ok else 404, {"ok": ok})
            if pfad == "/api/notiz":
                ok = db.setze_notiz(str(daten.get("id")), str(daten.get("notiz") or "")[:2000])
                return self._json(200 if ok else 404, {"ok": ok})
            if pfad == "/api/suchlauf":
                return self._json(200, {"gestartet": suchlauf.starte(), **suchlauf.stand})
            return self._json(404, {"fehler": "nicht gefunden"})

    return Handler


def erstelle_server(cfg: dict, db: Datenbank, basis: Path, port: int = 8765) -> tuple[HTTPServer, str]:
    token = secrets.token_urlsafe(18)
    suchlauf = Suchlauf(cfg, str(basis / cfg["ausgabe"]["datenbank"]))
    server = HTTPServer(("127.0.0.1", port), baue_handler(cfg, db, basis, token, suchlauf))
    return server, token


def starte(cfg: dict, db: Datenbank, basis: Path, port: int = 8765, browser: bool = True):
    try:
        server, _ = erstelle_server(cfg, db, basis, port)
    except OSError:
        print(f"Port {port} ist belegt – läuft die App schon? Sonst: python scout.py app --port {port + 1}")
        return
    url = f"http://127.0.0.1:{port}/"
    print(f"Wohnmobil-Scout läuft auf {url}   (Beenden: Strg+C)")
    if browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()
