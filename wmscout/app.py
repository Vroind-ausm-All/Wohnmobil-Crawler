"""Lokale Browser-App:  python scout.py app

Wohnmobil anklicken → Bewertung + fertiges Anschreiben; „✉ Anschreiben“ kopiert den Text, öffnet die
Anzeige und speichert den Status „kontaktiert“ (samt gesendetem Text) direkt in der Datenbank.
Solange die App läuft, sucht sie in einstellbaren Abständen selbst nach neuen Anzeigen (config.yaml → app).
Der Server lauscht nur auf 127.0.0.1 – er ist von anderen Rechnern aus nicht erreichbar.
"""
from __future__ import annotations

import contextlib
import logging
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from .ausgabe import schreibe_ausgaben
from .benachrichtigung import sende_mail
from .bewertung.neuigkeit import gesenkt_seit
from .bearbeitung import reservierung_tage
from .bewertung.auswertung import bewerte_alle
from .datenbank import Datenbank, wal_aktiv
from .laufsperre import Laufsperre
from .importer import Importer
from .sicherung import sicherung_ordner
from .team import lade_team_sicht
from .web.api import Kontext, bearbeite
from .web.sicherheit import SICHERHEITS_KOPF
from . import datenrechte, mandanten
from .sicherung import sicherung_ordner as _sicherung_ordner

log = logging.getLogger("scout")


class Suchlauf:
    """Crawl im Hintergrund – höchstens einer gleichzeitig, mit eigener DB-Verbindung."""

    def __init__(self, cfg: dict, db_pfad: str, basis: Path):
        self.cfg, self.db_pfad, self.basis = cfg, db_pfad, basis
        self.thread: threading.Thread | None = None
        self.letzter_start: str | None = None
        self.bei_ende: list = []           # Rückrufe mit den bewerteten Zeilen (Cache leeren, WhatsApp …)
        self.stand = {"laeuft": False, "meldung": "", "fehler": None, "ende": None, "neue_treffer": 0, "preissenkungen": 0,
                      "nachfassen": 0, "naechste_auto": None}
        stand = self.stand

        class Meldungen(logging.Handler):
            def emit(self, record):
                if stand["laeuft"]:
                    stand["meldung"] = record.getMessage()

        log.addHandler(Meldungen(logging.INFO))

    def oeffne_datenbank(self) -> Datenbank:
        """Eigene Verbindung; Sicherungsordner aus config.yaml (sicherung -> ordner), nicht der Standard neben der Datenbank."""
        return Datenbank(self.db_pfad, sicherung_ordner(self.cfg, self.basis), wal=wal_aktiv(self.cfg))

    def starte(self, ausloeser: str = "manuell") -> bool:
        """``ausloeser``: „manuell“ (Knopf) oder „auto“ (Auto-Suche: beachtet Intervalle je Quelle und die Pause nach einer Sperre, P4-04)."""
        if self.thread and self.thread.is_alive():
            return False
        sperre = Laufsperre(self.db_pfad)          # auch gegen „scout.py lauf“ aus der Aufgabenplanung (anderer Prozess)
        if not sperre.erwerben():
            self.stand.update(meldung="Es läuft bereits ein Suchlauf (z. B. geplante Aufgabe) – diesmal nicht gestartet.")
            return False
        self.letzter_start = datetime.now().isoformat(timespec="seconds")
        self.stand.update(laeuft=True, meldung="Suche startet …", fehler=None, ende=None)
        self.thread = threading.Thread(target=self._lauf, args=(sperre, ausloeser), daemon=True)
        try:
            self.thread.start()
        except BaseException:
            sperre.freigeben()
            self.stand.update(laeuft=False)
            raise
        return True

    def _lauf(self, sperre: Laufsperre | None = None, ausloeser: str = "manuell"):
        try:
            db = self.oeffne_datenbank()
            importer = Importer(self.cfg, db)
            importer.ausloeser, importer.intervall_beachten = ausloeser, ausloeser == "auto"
            stat = importer.lauf(self.cfg["suchen"])
            datenrechte.frist_anwenden(db, self.cfg, self.basis, (self.basis / self.db_pfad).parent / "fotos")
            # wie „python scout.py lauf“: Report/CSV/Anschreiben-Dateien aktualisieren, ggf. Mail
            zeilen = bewerte_alle(self.cfg, db, self.basis, lauf_start=self.letzter_start)
            sende_mail(self.cfg, zeilen, schreibe_ausgaben(self.cfg, zeilen, self.basis, fehler=stat["fehler"],
                                                team=lade_team_sicht(db, reservierung_tage(self.cfg))), seit=self.letzter_start)
            for rueckruf in self.bei_ende:
                try:
                    rueckruf(zeilen)
                except Exception:  # noqa: BLE001 – Benachrichtigungen dürfen den Lauf nicht stören
                    log.exception("Nachbearbeitung nach Suchlauf fehlgeschlagen")
            neue = sum(1 for z in zeilen if z["neu"] and z["bereit"])
            gesenkt = len(gesenkt_seit(zeilen, self.letzter_start))        # deutliche Preissenkungen in diesem Lauf (P4-03)
            uebersprungen = "".join(f" · übersprungen: {u['quelle']} ({u['grund']})" for u in stat.get("uebersprungen", []))
            self.stand.update(fehler=stat["fehler"], neue_treffer=neue, preissenkungen=gesenkt,
                              nachfassen=sum(1 for z in zeilen if z["nachfassen"]), meldung=(
                f"Fertig: {stat['neu']} neue Anzeigen, davon {neue} mit Anschreiben · {stat['preis']} Preissenkungen"
                f"{f', davon {gesenkt} deutlich' if gesenkt else ''}{uebersprungen}"))
        except Exception as e:  # noqa: BLE001 – Fehler in der Oberfläche anzeigen statt Thread sterben lassen
            log.exception("Suchlauf fehlgeschlagen")
            self.stand.update(fehler=str(e), meldung="Suchlauf fehlgeschlagen")
        finally:
            if sperre is not None:
                sperre.freigeben()
            self.stand.update(laeuft=False, ende=datetime.now().isoformat(timespec="seconds"))


class AutoSuche:
    """Startet den Suchlauf alle N Stunden (nur im eingestellten Zeitfenster), solange die App läuft."""

    def __init__(self, cfg: dict, suchlauf: Suchlauf):
        a = cfg.get("app") or {}
        self.stunden = float(a.get("auto_suche_stunden") or 0)
        self.von, self.bis = int(a.get("auto_suche_von", 7)), int(a.get("auto_suche_bis", 21))
        self.suchlauf = suchlauf
        self.halt = threading.Event()               # nur für Tests und geordnetes Beenden

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

    def _schritt(self, db: Datenbank) -> bool:
        """Ein Durchgang: nächsten Termin berechnen und anzeigen, bei Fälligkeit den Suchlauf starten."""
        ende = self.suchlauf.stand["ende"]
        letzter = max(filter(None, [db.letzter_lauf(), datetime.fromisoformat(ende) if ende else None]),
                      default=None)
        jetzt = datetime.now()
        faellig = self.naechste(letzter, jetzt)
        self.suchlauf.stand["naechste_auto"] = faellig.isoformat(timespec="minutes")
        if faellig <= jetzt and not self.suchlauf.stand["laeuft"] and self.suchlauf.starte("auto"):
            log.info("Automatische Suche startet")
            return True
        return False

    def _schleife(self):
        db = None
        while True:
            try:
                if db is None:
                    db = self.suchlauf.oeffne_datenbank()    # eigene Verbindung für diesen Thread
                self._schritt(db)
            except Exception:  # noqa: BLE001 – ein Fehler darf die Auto-Suche nicht dauerhaft beenden (P1-11b)
                log.exception("Automatische Suche: Durchgang fehlgeschlagen – nächster Versuch in einer Minute")
                with contextlib.suppress(Exception):     # Verbindung beim nächsten Durchgang neu öffnen
                    db.con.close()
                db = None
            if self.halt.wait(60):
                return


def baue_handler(k: Kontext | None = None, waehle=None):
    """Einzelbetrieb: ein Kontext. Mandanten (G2): ``waehle(host) -> Kontext | None`` – allein der Hostname entscheidet."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "WohnmobilScout"
        sys_version = ""                 # keine Python-Version im Server-Kopf (G0)
        timeout = 30                     # langsame/hängende Verbindungen nach 30 s schließen (Slowloris, G0)

        def log_message(self, fmt, *args):
            log.debug("app: " + fmt, *args)

        def _kontext(self) -> Kontext | None:
            if waehle is None:
                return k
            gewaehlt = waehle((self.headers.get("Host") or "").strip().lower())
            if gewaehlt is None:            # unbekannter Hostname: Inhalt nicht lesen, keine Mandanten verraten
                body = b'{"fehler": "Dieser Hostname ist nicht freigegeben"}'
                self.send_response(403)
                for name, wert in {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body)),
                                   "Cache-Control": "no-store", **SICHERHEITS_KOPF}.items():
                    self.send_header(name, wert)
                self.end_headers()
                self.wfile.write(body)
            return gewaehlt

        def do_GET(self):
            if kx := self._kontext():
                bearbeite(self, kx, "GET")

        def do_POST(self):
            if kx := self._kontext():
                bearbeite(self, kx, "POST")

    Handler.kontext = k                  # für Diagnose und Tests (z. B. Live-Verbindungen zählen)
    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """Abgebrochene Verbindungen (Gegenseite schließt nach früher 400/403/413) sind kein Serverfehler."""
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def erstelle_server(cfg: dict, db: Datenbank, basis: Path, port: int = 8765) -> tuple[HTTPServer, str, Suchlauf]:
    """Lauscht nur auf 127.0.0.1. Handys erreichen die App über `tailscale serve` (HTTPS), siehe docs/HANDY-APP.md."""
    k, suchlauf = _kontext(cfg, db, basis)
    server = Server(("127.0.0.1", port), baue_handler(k))
    return server, k.token, suchlauf


def _kontext(cfg: dict, db: Datenbank, basis: Path) -> tuple[Kontext, Suchlauf]:
    db_pfad = basis / cfg["ausgabe"]["datenbank"]
    suchlauf = Suchlauf(cfg, str(db_pfad), basis)
    k = Kontext(cfg, db, basis, secrets.token_urlsafe(18), suchlauf, db_pfad.parent / "fotos")
    suchlauf.bei_ende.append(lambda zeilen: (k.veraendert(), k.whatsapp.neue_treffer(zeilen), k.live.melde("suchlauf")))
    datenrechte.frist_anwenden(db, cfg, basis, db_pfad.parent / "fotos")      # auch ohne Suchlauf/Import (P1-14a)
    return k, suchlauf


def erstelle_server_mandanten(grund_cfg: dict, basis: Path, port: int = 8765, lokal: str | None = None) -> HTTPServer:
    """Mandantenbetrieb (G2, ADR-033): je Mandant eigene Datenbank, eigener Kontext (Sperre, Live, Audit, Suchlauf). Der Hostname
    der Anfrage wählt den Mandanten; 127.0.0.1/localhost nur, wenn ``lokal`` einen Mandanten benennt. ``MandantenFehler``,
    wenn die Mandanten nicht eindeutig sind – dann startet nichts."""
    liste = mandanten.alle(grund_cfg, basis)
    if lokal and lokal not in {c["mandant"]["kennung"] for c in liste}:
        raise mandanten.MandantenFehler(f"--lokal {lokal}: kein solcher Mandant")
    nach_host: dict[str, Kontext] = {}
    kontexte: dict[str, tuple[Kontext, Suchlauf]] = {}
    for cfg in liste:
        db = Datenbank(str(basis / cfg["ausgabe"]["datenbank"]), str(_sicherung_ordner(cfg, basis)), wal=wal_aktiv(cfg))
        k, suchlauf = _kontext(cfg, db, basis)
        kennung = cfg["mandant"]["kennung"]
        kontexte[kennung] = (k, suchlauf)
        for h in mandanten.hosts(cfg):
            nach_host[h] = k
    server = Server(("127.0.0.1", port), baue_handler(waehle=nach_host.get))
    if lokal:                                    # erst nach dem Binden: tatsächlicher Port (auch bei Port 0)
        p = server.server_address[1]
        nach_host[f"127.0.0.1:{p}"] = nach_host[f"localhost:{p}"] = kontexte[lokal][0]
    server.mandanten = kontexte
    return server


def starte_mandanten(grund_cfg: dict, basis: Path, port: int | None = None, lokal: str | None = None):
    port = port or (grund_cfg.get("app") or {}).get("port", 8765)
    try:
        server = erstelle_server_mandanten(grund_cfg, basis, port, lokal)
    except OSError:
        print(f"Port {port} ist belegt – läuft die App schon? Sonst: python scout.py app --mandanten --port {port + 1}")
        return
    print(f"Wohnmobil-Scout (Mandantenbetrieb) auf 127.0.0.1:{port}   (Beenden: Strg+C)")
    for kennung, (k, suchlauf) in server.mandanten.items():
        auto = AutoSuche(k.cfg, suchlauf)
        print(f"  {kennung:<16} {k.cfg['mandant']['name']:<28} {', '.join(sorted(mandanten.hosts(k.cfg)))}"
              + (f"  · Auto-Suche alle {auto.stunden:g} h" if auto.stunden > 0 else ""))
        auto.starte()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()


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
