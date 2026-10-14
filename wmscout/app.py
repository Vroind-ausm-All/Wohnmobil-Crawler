"""Lokale Browser-App:  python scout.py app

Wohnmobil anklicken → Bewertung + fertiges Anschreiben; „✉ Anschreiben“ kopiert den Text, öffnet die
Anzeige und speichert den Status „kontaktiert“ (samt gesendetem Text) direkt in der Datenbank.
Solange die App läuft, sucht sie in einstellbaren Abständen selbst nach neuen Anzeigen (config.yaml → app).
Der Server lauscht nur auf 127.0.0.1 – er ist von anderen Rechnern aus nicht erreichbar.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from .ausgabe import schreibe_ausgaben
from .benachrichtigung import sende_mail
from .bearbeitung import reservierung_tage
from .bewertung.auswertung import bewerte_alle
from .datenbank import Datenbank
from .importer import Importer
from .sicherung import sicherung_ordner
from .team import lade_team_sicht
from .web.api import Kontext, bearbeite

log = logging.getLogger("scout")


class Suchlauf:
    """Crawl im Hintergrund – höchstens einer gleichzeitig, mit eigener DB-Verbindung."""

    def __init__(self, cfg: dict, db_pfad: str, basis: Path):
        self.cfg, self.db_pfad, self.basis = cfg, db_pfad, basis
        self.thread: threading.Thread | None = None
        self.letzter_start: str | None = None
        self.bei_ende: list = []           # Rückrufe mit den bewerteten Zeilen (Cache leeren, WhatsApp …)
        self.stand = {"laeuft": False, "meldung": "", "fehler": None, "ende": None, "neue_treffer": 0,
                      "nachfassen": 0, "naechste_auto": None}
        stand = self.stand

        class Meldungen(logging.Handler):
            def emit(self, record):
                if stand["laeuft"]:
                    stand["meldung"] = record.getMessage()

        log.addHandler(Meldungen(logging.INFO))

    def oeffne_datenbank(self) -> Datenbank:
        """Eigene Verbindung; Sicherungsordner aus config.yaml (sicherung -> ordner), nicht der Standard neben der Datenbank."""
        return Datenbank(self.db_pfad, sicherung_ordner(self.cfg, self.basis))

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
            db = self.oeffne_datenbank()
            stat = Importer(self.cfg, db).lauf(self.cfg["suchen"])
            # wie „python scout.py lauf“: Report/CSV/Anschreiben-Dateien aktualisieren, ggf. Mail
            zeilen = bewerte_alle(self.cfg, db, self.basis, lauf_start=self.letzter_start)
            sende_mail(self.cfg, zeilen, schreibe_ausgaben(self.cfg, zeilen, self.basis, fehler=stat["fehler"],
                                                team=lade_team_sicht(db, reservierung_tage(self.cfg))))
            for rueckruf in self.bei_ende:
                try:
                    rueckruf(zeilen)
                except Exception:  # noqa: BLE001 – Benachrichtigungen dürfen den Lauf nicht stören
                    log.exception("Nachbearbeitung nach Suchlauf fehlgeschlagen")
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
        db = self.suchlauf.oeffne_datenbank()       # eigene Verbindung für diesen Thread
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


def baue_handler(k: Kontext):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WohnmobilScout"

        def log_message(self, fmt, *args):
            log.debug("app: " + fmt, *args)

        def do_GET(self):
            bearbeite(self, k, "GET")

        def do_POST(self):
            bearbeite(self, k, "POST")

    return Handler


def erstelle_server(cfg: dict, db: Datenbank, basis: Path, port: int = 8765) -> tuple[HTTPServer, str, Suchlauf]:
    """Lauscht nur auf 127.0.0.1. Handys erreichen die App über `tailscale serve` (HTTPS), siehe docs/HANDY-APP.md."""
    token = secrets.token_urlsafe(18)
    db_pfad = basis / cfg["ausgabe"]["datenbank"]
    suchlauf = Suchlauf(cfg, str(db_pfad), basis)
    k = Kontext(cfg, db, basis, token, suchlauf, db_pfad.parent / "fotos")
    suchlauf.bei_ende.append(lambda zeilen: (k.veraendert(), k.whatsapp.neue_treffer(zeilen)))
    server = ThreadingHTTPServer(("127.0.0.1", port), baue_handler(k))
    server.daemon_threads = True
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
    oeffentlich = (cfg.get("app") or {}).get("oeffentliche_url")
    if oeffentlich:
        print(f"Handy-App fürs Team: {oeffentlich.rstrip('/')}/m")
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
