"""Lokale Browser-App:  python scout.py app

Wohnmobil anklicken → Bewertung + fertiges Anschreiben; „✉ Anschreiben“ kopiert den Text, öffnet die
Anzeige und speichert den Status „kontaktiert“ (samt gesendetem Text) direkt in der Datenbank.
Solange die App läuft, sucht sie in einstellbaren Abständen selbst nach neuen Anzeigen (config.yaml → app).
Der Server lauscht nur auf 127.0.0.1 – er ist von anderen Rechnern aus nicht erreichbar.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .crawler import Crawler
from .db import STATUS, Datenbank
from .report import bewerte_alle, render_html, schreibe_ausgaben, sende_mail

log = logging.getLogger("scout")


class Suchlauf:
    """Crawl im Hintergrund – höchstens einer gleichzeitig, mit eigener DB-Verbindung."""

    def __init__(self, cfg: dict, db_pfad: str, basis: Path):
        self.cfg, self.db_pfad, self.basis = cfg, db_pfad, basis
        self.thread: threading.Thread | None = None
        self.letzter_start: str | None = None
        self.stand = {"laeuft": False, "meldung": "", "fehler": None, "ende": None, "neue_treffer": 0,
                      "nachfassen": 0, "naechste_auto": None}
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
            db = Datenbank(self.db_pfad)
            stat = Crawler(self.cfg, db).lauf(self.cfg["suchen"])
            # wie „python scout.py lauf“: Report/CSV/Anschreiben-Dateien aktualisieren, ggf. Mail
            zeilen = bewerte_alle(self.cfg, db, self.basis, lauf_start=self.letzter_start)
            sende_mail(self.cfg, zeilen, schreibe_ausgaben(self.cfg, zeilen, self.basis, fehler=stat["fehler"]))
            neue = sum(1 for z in zeilen if z["neu"] and z["bereit"])
            self.stand.update(fehler=stat["fehler"], neue_treffer=neue,
                              nachfassen=sum(1 for z in zeilen if z["nachfassen"]), meldung=(
                f"Fertig: {stat['neu']} neue Anzeigen, davon {neue} mit Anschreiben · {stat['preis']} Preissenkungen"))
        except Exception as e:  # noqa: BLE001 – Fehler in der Oberfläche anzeigen statt Thread sterben lassen
            log.exception("Suchlauf fehlgeschlagen")
            self.stand.update(fehler=str(e), meldung="Suchlauf fehlgeschlagen")
        finally:
            self.stand.update(laeuft=False, ende=datetime.now().isoformat(timespec="seconds"))


class AutoSuche:
    """Startet den Suchlauf alle N Stunden (nur im eingestellten Zeitfenster), solange die App läuft."""

    def __init__(self, cfg: dict, suchlauf: Suchlauf):
        a = cfg.get("app") or {}
        self.stunden = float(a.get("auto_suche_stunden") or 0)
        self.von, self.bis = int(a.get("auto_suche_von", 7)), int(a.get("auto_suche_bis", 21))
        self.suchlauf = suchlauf

    def naechste(self, letzter: datetime | None, jetzt: datetime) -> datetime:
        t = max(jetzt, letzter + timedelta(hours=self.stunden)) if letzter else jetzt
        if t.hour < self.von:
            t = t.replace(hour=self.von, minute=0, second=0)
        elif t.hour >= self.bis:
            t = (t + timedelta(days=1)).replace(hour=self.von, minute=0, second=0)
        return t

    def starte(self):
        if self.stunden > 0:
            threading.Thread(target=self._schleife, daemon=True).start()

    def _schleife(self):
        db = Datenbank(self.suchlauf.db_pfad)       # eigene Verbindung für diesen Thread
        while True:
            ende = self.suchlauf.stand["ende"]
            letzter = max(filter(None, [db.letzter_lauf(), datetime.fromisoformat(ende) if ende else None]),
                          default=None)
            jetzt = datetime.now()
            faellig = self.naechste(letzter, jetzt)
            self.suchlauf.stand["naechste_auto"] = faellig.isoformat(timespec="minutes")
            if faellig <= jetzt and not self.suchlauf.stand["laeuft"]:
                log.info("Automatische Suche startet")
                self.suchlauf.starte()
            time.sleep(60)


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
            text = str(daten["text"])[:5000] if daten.get("text") else None
            betrag = daten.get("betrag") if isinstance(daten.get("betrag"), int) else None
            if pfad == "/api/status":
                if daten.get("status") not in STATUS:
                    return self._json(400, {"fehler": "unbekannter Status"})
                ok = db.setze_status(str(daten.get("id")), daten["status"], text=text, betrag=betrag)
                return self._json(200 if ok else 404, {"ok": ok})
            if pfad == "/api/nachgefasst":
                ok = bool(text) and db.nachgefasst(str(daten.get("id")), text, betrag)
                return self._json(200 if ok else 400, {"ok": ok})
            if pfad == "/api/notiz":
                ok = db.setze_notiz(str(daten.get("id")), str(daten.get("notiz") or "")[:2000])
                return self._json(200 if ok else 404, {"ok": ok})
            if pfad == "/api/suchlauf":
                return self._json(200, {"gestartet": suchlauf.starte(), **suchlauf.stand})
            return self._json(404, {"fehler": "nicht gefunden"})

    return Handler


def erstelle_server(cfg: dict, db: Datenbank, basis: Path, port: int = 8765) -> tuple[HTTPServer, str, Suchlauf]:
    token = secrets.token_urlsafe(18)
    suchlauf = Suchlauf(cfg, str(basis / cfg["ausgabe"]["datenbank"]), basis)
    server = HTTPServer(("127.0.0.1", port), baue_handler(cfg, db, basis, token, suchlauf))
    return server, token, suchlauf


def starte(cfg: dict, db: Datenbank, basis: Path, port: int | None = None, browser: bool = True):
    port = port or (cfg.get("app") or {}).get("port", 8765)
    try:
        server, _, suchlauf = erstelle_server(cfg, db, basis, port)
    except OSError:
        print(f"Port {port} ist belegt – läuft die App schon? Sonst: python scout.py app --port {port + 1}")
        return
    url = f"http://127.0.0.1:{port}/"
    print(f"Wohnmobil-Scout läuft auf {url}   (Beenden: Strg+C)")
    auto = AutoSuche(cfg, suchlauf)
    if auto.stunden > 0:
        print(f"Automatische Suche alle {auto.stunden:g} Stunden zwischen {auto.von} und {auto.bis} Uhr.")
    auto.starte()
    if browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()
