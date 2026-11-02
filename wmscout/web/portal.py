"""Öffentliches Ankaufsportal (P7-03, B4, ADR-068):  python scout.py portal

Eigener Server-Prozess mit eigenem Port und NUR diesen Wegen: Formular „Wohnmobil verkaufen“, Statusseite des Verkäufers (mit
„Meine Daten löschen“), Impressum, Datenschutz und die nötigen statischen Dateien. Keine Anmeldung, kein Zugriff auf Ankaufsliste,
Team, Inserate oder andere Anfragen – die Team-App bleibt ein getrennter Prozess hinter Anmeldung. Gleiche Datenbank, gleicher
Schreibweg (``VerkaufSpeicher.anlegen``, Kanal immer „formular“).

Status- und Upload-Links sind signierte Tokens (HMAC-SHA256, Schlüssel nur aus der Umgebungsvariablen ``SCOUT_PORTAL_SCHLUESSEL``) –
keine Schemaänderung, nichts Geheimes in Datenbank oder Repository. Der Status-Token steht im #-Teil des Links und erreicht den
Server nie per GET (keine Tokens in Proxy-Logs). Schutz gegen Spam ohne Fremddienste: verstecktes Feld, signierte Mindest-Ausfüllzeit,
Grenzen je IP und gesamt (im Speicher), Größengrenzen, Host- und Herkunftsprüfung, nur JSON. Keine automatische Nachricht an den
Verkäufer (CLAUDE.md, Regel 10) – das Team meldet sich persönlich.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader

from .. import datenrechte
from .. import verkauf as vk
from ..datenbank import Datenbank
from ..verkauf import Eingabefehler, VerkaufSpeicher
from .api import MAX_FOTO, STATIC, _bild_bytes, Antwort
from .sicherheit import SICHERHEITS_KOPF

log = logging.getLogger("scout")

UMGEBUNG_SCHLUESSEL = "SCOUT_PORTAL_SCHLUESSEL"
MIN_SCHLUESSEL = 32
MAX_ANFRAGE_JSON = 20_000
STATISCH = {"mobil.css", "icon-192.png", "icon-512.png", "icon.svg"}        # Positivliste – keine Team-Skripte
# Was der Verkäufer über den Stand erfährt: knapp, ohne interne Begriffe, ohne Bearbeiter oder Beträge
STATUS_VERKAEUFER = {"eingegangen": "Eingegangen – wir prüfen Ihre Angaben und melden uns persönlich.",
                     "in_pruefung": "In Prüfung – wir bewerten Ihr Fahrzeug und melden uns persönlich.",
                     "angebot": "Wir haben Ihnen ein Angebot gemacht oder melden uns dazu in Kürze persönlich.",
                     "abgelehnt": "Abgeschlossen – derzeit kein Ankauf.",
                     "zurueckgezogen": "Zurückgezogen – Ihre persönlichen Angaben wurden gelöscht.",
                     "gekauft": "Angekauft – vielen Dank!"}
STANDARD = {"aktiv": False, "port": 8770, "oeffentliche_url": "", "vertrauter_proxy": False, "texte_geprueft": False,
            "status_tage": 365, "upload_minuten": 60, "min_sekunden": 3, "anfragen_je_ip_stunde": 5, "anfragen_je_stunde": 60,
            "abrufe_je_ip_minute": 60, "sendungen_je_ip_minute": 30, "fotos_je_stunde": 300, "impressum": {}}
IMPRESSUM_PFLICHT = ("name", "anschrift", "email")


class PortalFehler(ValueError):
    """Portal startet nicht (Konfiguration oder Schlüssel unvollständig) – mit verständlicher Meldung."""


def einstellungen(cfg: dict) -> dict:
    p = {**STANDARD, **(cfg.get("portal") or {})}
    p["impressum"] = {k: str(v).strip() for k, v in (p.get("impressum") or {}).items() if v not in (None, "")}
    for feld in ("port", "status_tage", "upload_minuten", "min_sekunden", "anfragen_je_ip_stunde", "anfragen_je_stunde", "abrufe_je_ip_minute",
                 "sendungen_je_ip_minute", "fotos_je_stunde"):
        wert = p[feld]
        if isinstance(wert, bool) or not isinstance(wert, int) or wert < 0 or (feld == "port" and not 0 <= wert <= 65535):
            raise PortalFehler(f"portal → {feld}: ganze Zahl ≥ 0 erwartet, nicht {wert!r}")
    url = str(p.get("oeffentliche_url") or "").strip().rstrip("/")
    if url and (urlparse(url).scheme != "https" or not urlparse(url).netloc):
        raise PortalFehler("portal → oeffentliche_url: vollständige https-Adresse, z. B. https://verkaufen.firma.de")
    p["oeffentliche_url"] = url
    return p


def startbereit(cfg: dict, schluessel: str | None) -> list[str]:
    """Gründe, warum das Portal nicht öffentlich starten darf (leer = startbereit)."""
    p, gruende = einstellungen(cfg), []
    if p["aktiv"] is not True:
        gruende.append("portal → aktiv ist nicht true (Freigabe durch den Betreiber)")
    if not p["oeffentliche_url"]:
        gruende.append("portal → oeffentliche_url fehlt (https-Adresse des Portals)")
    if p["vertrauter_proxy"] is not True:
        gruende.append("portal → vertrauter_proxy: true fehlt – öffentlich nur hinter dem eigenen Reverse-Proxy; sonst zählen alle Besucher "
                       "als eine Adresse und die Grenzen sperren das Portal für alle")
    fehlend = [f for f in IMPRESSUM_PFLICHT if not p["impressum"].get(f)]
    if fehlend:
        gruende.append("portal → impressum: " + ", ".join(fehlend) + " fehlt (Anbieterkennzeichnung)")
    if not schluessel or len(schluessel) < MIN_SCHLUESSEL:
        gruende.append(f"Umgebungsvariable {UMGEBUNG_SCHLUESSEL} fehlt oder ist kürzer als {MIN_SCHLUESSEL} Zeichen "
                       "(z. B. python -c \"import secrets; print(secrets.token_urlsafe(48))\")")
    return gruende


# ---------------------------------------------------------------- signierte Tokens (ohne Datenbank)
def _b64(roh: bytes) -> str:
    return base64.urlsafe_b64encode(roh).rstrip(b"=").decode("ascii")


class Signierer:
    """``<zweck-id>.<ablauf>.<signatur>``; die Signatur bindet Zweck, ID und Ablauf an den Schlüssel."""

    def __init__(self, schluessel: str, uhr=time.time):
        self.schluessel, self.uhr = schluessel.encode("utf-8"), uhr

    def _sig(self, zweck: str, wert: str, ablauf: int) -> str:
        return _b64(hmac.new(self.schluessel, f"{zweck}|{wert}|{ablauf}".encode(), hashlib.sha256).digest())

    def erstelle(self, zweck: str, wert: str | int, sekunden: int) -> str:
        ablauf = int(self.uhr()) + int(sekunden)
        return f"{wert}.{ablauf}.{self._sig(zweck, str(wert), ablauf)}"

    def pruefe(self, zweck: str, token) -> str | None:
        """Der signierte Wert oder None (falsch, abgelaufen, fremder Zweck)."""
        if not isinstance(token, str) or len(token) > 200 or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}\.[0-9]{1,12}\.[A-Za-z0-9_-]{43}", token):
            return None
        wert, ablauf, sig = token.split(".")
        if not hmac.compare_digest(sig, self._sig(zweck, wert, int(ablauf))) or int(ablauf) < self.uhr():
            return None
        return wert


class Bremse:
    """Höchstens ``grenze`` Ereignisse je Schlüssel im gleitenden Fenster – im Speicher, ein Neustart setzt zurück."""

    def __init__(self, grenze: int, fenster_sek: float, uhr=time.monotonic):
        self.grenze, self.fenster, self.uhr = grenze, fenster_sek, uhr
        self._d: dict[str, deque] = {}
        self._sperre = threading.Lock()
        self._aufgeraeumt = uhr()

    def erlaubt(self, schluessel: str) -> bool:
        if self.grenze <= 0:
            return True
        jetzt = self.uhr()
        with self._sperre:
            if jetzt - self._aufgeraeumt >= self.fenster:      # spätestens nach einem Fenster: alte Schlüssel (IP-Adressen) vergessen
                for k in [k for k, x in self._d.items() if not x or x[-1] <= jetzt - self.fenster]:
                    del self._d[k]
                self._aufgeraeumt = jetzt
            d = self._d.setdefault(schluessel, deque())
            while d and d[0] <= jetzt - self.fenster:
                d.popleft()
            if len(d) >= self.grenze:
                return False
            d.append(jetzt)
            return True

    def anzahl(self) -> int:
        return len(self._d)


# ---------------------------------------------------------------- Kontext und Anfragen
class PortalKontext:
    def __init__(self, cfg: dict, db: Datenbank, basis: Path, foto_ordner: Path, schluessel: str, uhr=time.time):
        self.cfg, self.db, self.basis, self.p = cfg, db, basis, einstellungen(cfg)
        self.foto_ordner = Path(foto_ordner)
        self.verkauf = VerkaufSpeicher(db, self.foto_ordner / "anfragen")      # wie die Team-App: im gesicherten Fotoordner
        self.signierer = Signierer(schluessel, uhr)
        self.formular = Signierer(secrets.token_urlsafe(32), uhr)            # Ausfüllzeit: je Prozess, muss nicht überdauern
        self.uhr = uhr
        self.ip_anfragen = Bremse(self.p["anfragen_je_ip_stunde"], 3600)
        self.alle_anfragen = Bremse(self.p["anfragen_je_stunde"], 3600)
        self.ip_abrufe = Bremse(self.p["abrufe_je_ip_minute"], 60)
        self.ip_sendungen = Bremse(self.p["sendungen_je_ip_minute"], 60)
        self.alle_fotos = Bremse(self.p["fotos_je_stunde"], 3600)
        self.sperre = threading.Lock()
        self.env = Environment(loader=FileSystemLoader(str(basis / "vorlagen")), autoescape=True)

    def herkuenfte(self, port: int) -> set[str]:
        h = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if self.p["oeffentliche_url"]:
            u = urlparse(self.p["oeffentliche_url"])
            h.add(f"{u.scheme}://{u.netloc}")
        return h

    def hosts(self, port: int) -> set[str]:
        h = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.p["oeffentliche_url"]:
            h.add(urlparse(self.p["oeffentliche_url"]).netloc)
        return h

    def basis_url(self) -> str:
        return self.p["oeffentliche_url"]

    def seite(self, vorlage: str, **kw) -> str:
        firma = self.cfg["anschreiben"]["firma"]
        return self.env.get_template(vorlage).render(firma=firma, impressum=self.p["impressum"], entwurf=self.p["texte_geprueft"] is not True,
                                                     **kw)


class PortalAnfrage:
    def __init__(self, handler, k: PortalKontext):
        self.h, self.k = handler, k
        self.pfad = urlparse(handler.path).path.rstrip("/") or "/"

    def senden(self, status: int, body: bytes, typ: str, kopf: dict | None = None):
        h = self.h
        h.send_response(status)
        for name, wert in {"Content-Type": typ, "Content-Length": str(len(body)), "Cache-Control": "no-store", **SICHERHEITS_KOPF,
                           **(kopf or {})}.items():
            h.send_header(name, wert)
        h.end_headers()
        h.wfile.write(body)

    def json(self, status: int, obj):
        self.senden(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def html(self, text: str, status: int = 200):
        self.senden(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def client_ip(self) -> str:
        weitergeleitet = self.h.headers.get("X-Forwarded-For")
        if self.k.p["vertrauter_proxy"] is True and weitergeleitet:
            return weitergeleitet.split(",")[-1].strip()
        return self.h.client_address[0]

    def pruefe_host(self):
        if (self.h.headers.get("Host") or "") not in self.k.hosts(self.h.server.server_address[1]):
            raise Antwort(403, "Dieser Hostname ist nicht freigegeben")

    # ----- GET
    def get(self):
        k, p = self.k, self.pfad
        if p.startswith("/static/"):
            name = p[len("/static/"):]
            if name not in STATISCH:
                raise Antwort(404, "nicht gefunden")
            typ = {"css": "text/css; charset=utf-8", "svg": "image/svg+xml", "png": "image/png"}[name.rsplit(".", 1)[-1]]
            return self.senden(200, (STATIC / name).read_bytes(), typ)
        if p == "/favicon.ico":
            return self.senden(200, (STATIC / "icon-192.png").read_bytes(), "image/png")
        if p == "/gesund":                               # Überwachung: ohne Bremse, ohne Daten
            with k.sperre:
                k.db.con.execute("SELECT 1 FROM schema_version LIMIT 1").fetchone()
            return self.json(200, {"ok": True})
        if not k.ip_abrufe.erlaubt(self.client_ip()):    # statische Dateien zählen nicht (B5)
            raise Antwort(429, "Zu viele Abrufe – bitte kurz warten")
        if p == "/":
            return self.senden(303, b"", "text/plain", {"Location": "/verkaufen"})
        if p == "/verkaufen":
            return self.html(k.seite("verkaufen.html", portal=True, token="", arten=vk.ARTEN, maengel=vk.MAENGEL, kanaele={},
                                     formular=k.formular.erstelle("formular", int(k.uhr()), 24 * 3600), ich=None, team=False))
        if p == "/status":
            return self.html(k.seite("portal_status.html"))
        if p in ("/impressum", "/datenschutz"):
            return self.html(k.seite(f"portal_{p[1:]}.html", status_tage=k.p["status_tage"],
                                     frist=(k.cfg.get("datenschutz") or {}).get("verkaufsanfragen_anonymisieren_nach_monaten")))
        raise Antwort(404, "nicht gefunden")

    # ----- POST
    def lies(self, grenze: int) -> dict:
        if (self.h.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise Antwort(415, "Nur JSON")
        herkunft = self.h.headers.get("Origin")
        if herkunft and herkunft.rstrip("/").lower() not in self.k.herkuenfte(self.h.server.server_address[1]):
            raise Antwort(403, "Fremde Herkunft")
        try:
            laenge = int(self.h.headers.get("Content-Length") or 0)
        except ValueError:
            raise Antwort(400, "ungültige Länge") from None
        if laenge < 0:
            raise Antwort(400, "ungültige Länge")
        if laenge > grenze:
            raise Antwort(413, "Anfrage zu groß")
        try:
            daten = json.loads(self.h.rfile.read(laenge) or b"{}")
        except (ValueError, RecursionError):
            raise Antwort(400, "ungültige Anfrage") from None
        if not isinstance(daten, dict):
            raise Antwort(400, "ungültige Anfrage")
        return daten

    def post(self):
        p = self.pfad
        if p not in ("/api/portal/anfrage", "/api/portal/foto", "/api/portal/status", "/api/portal/loeschen"):
            raise Antwort(404, "nicht gefunden")
        if not self.k.ip_sendungen.erlaubt(self.client_ip()):        # vor dem Lesen des Inhalts (B3)
            raise Antwort(429, "Zu viele Anfragen – bitte kurz warten")
        if p == "/api/portal/anfrage":
            return self.json(200, self.anfrage(self.lies(MAX_ANFRAGE_JSON)))
        if p == "/api/portal/foto":
            aid = self._anfrage_id("upload", self.h.headers.get("X-Portal-Upload"))   # Token vor dem Lesen von bis zu 12 MB prüfen
            if not self.k.alle_fotos.erlaubt("alle"):
                raise Antwort(429, "Gerade werden sehr viele Fotos übertragen – bitte später erneut versuchen")
            return self.json(200, self.foto(aid, self.lies(MAX_FOTO)))
        if p == "/api/portal/status":
            return self.json(200, self.status(self.lies(2_000)))
        if p == "/api/portal/loeschen":
            return self.json(200, self.loeschen(self.lies(2_000)))
        raise Antwort(404, "nicht gefunden")

    def anfrage(self, daten: dict) -> dict:
        k = self.k
        start = k.formular.pruefe("formular", daten.get("formular"))
        if start is None:
            raise Antwort(400, "Das Formular ist abgelaufen – bitte die Seite neu laden")
        if k.uhr() - int(start) < k.p["min_sekunden"]:
            raise Antwort(400, "Bitte die Angaben in Ruhe ausfüllen und erneut senden")
        if daten.get("feld_leer"):                      # verstecktes Feld: nur Programme füllen es – scheinbar erfolgreich, nichts gespeichert
            log.info("Portal: Anfrage mit ausgefülltem Prüffeld verworfen")
            return {"referenz": "VA-eingegangen", "status_link": None, "upload": None, "spanne": None}
        daten = {**daten, "kanal": "formular"}        # Eingangsweg setzt nie der Absender
        try:
            a = vk.pruefe_anfrage(daten)
        except Eingabefehler as e:
            raise Antwort(400, "Bitte prüfen: " + "; ".join(e.fehler), {"felder": e.fehler}) from e
        # erst gültige Anfragen zählen: Tippfehler sperren niemanden aus, gespeichert wird nur Gültiges
        if not k.ip_anfragen.erlaubt(self.client_ip()) or not k.alle_anfragen.erlaubt("alle"):
            raise Antwort(429, "Zu viele Anfragen in kurzer Zeit – bitte später erneut versuchen oder anrufen")
        version = str((k.cfg.get("verkaeuferportal") or {}).get("einwilligung_version") or "unbekannt")
        with k.sperre:
            neu = k.verkauf.anlegen(a, None, version)
            try:
                spanne = vk.spanne_fuer_verkaeufer(vk.bewerte(k.cfg, {**a, "id": neu["id"]}, vk.vergleich_aus(k.db)), k.cfg)
            except Exception:  # noqa: BLE001 – gespeichert ist gespeichert: kein 500, sonst sendet der Verkäufer doppelt (B8)
                log.exception("Portal: Spanne für %s nicht berechnet", neu["referenz"])
                spanne = None
        log.info("Portal: Verkaufsanfrage %s eingegangen", neu["referenz"])
        status = k.signierer.erstelle("status", neu["id"], k.p["status_tage"] * 86400)
        return {"referenz": neu["referenz"], "status_link": f"{k.basis_url()}/status#{status}",
                "upload": k.signierer.erstelle("upload", neu["id"], k.p["upload_minuten"] * 60), "spanne": spanne}

    def _anfrage_id(self, zweck: str, token) -> int:
        wert = self.k.signierer.pruefe(zweck, token)
        if wert is None or not wert.isdigit():
            raise Antwort(403, "Link ungültig oder abgelaufen")
        return int(wert)

    def foto(self, aid: int, daten: dict) -> dict:
        bild = _bild_bytes(str(daten.get("bild") or ""))
        with self.k.sperre:
            r = self.k.db.con.execute("SELECT status FROM verkaufsanfragen WHERE id=?", (aid,)).fetchone()
            if not r or r["status"] == "zurueckgezogen":
                raise Antwort(403, "Link ungültig oder abgelaufen")
            try:
                self.k.verkauf.foto_speichern(aid, bild, None)
            except LookupError as e:
                raise Antwort(404, str(e)) from e
            except ValueError as e:
                raise Antwort(400, str(e)) from e
        return {"ok": True}

    def status(self, daten: dict) -> dict:
        aid = self._anfrage_id("status", daten.get("token"))
        with self.k.sperre:
            r = self.k.db.con.execute(
                "SELECT referenz, status, marke, modell, ez_jahr, erstellt_am, aktualisiert_am, "
                "EXISTS(SELECT 1 FROM anfrage_verlauf v WHERE v.anfrage_id=a.id AND v.ereignis IN ('widerruf', 'frist')) AS geloescht, "
                "(SELECT COUNT(*) FROM anfrage_fotos f WHERE f.anfrage_id=a.id) AS fotos FROM verkaufsanfragen a WHERE id=?", (aid,)).fetchone()
        if not r:
            raise Antwort(404, "Anfrage nicht gefunden")
        return {"referenz": r["referenz"], "status": STATUS_VERKAEUFER.get(r["status"], "in Bearbeitung"),
                "fahrzeug": " ".join(str(x) for x in (r["marke"], r["modell"], f"EZ {r['ez_jahr']}" if r["ez_jahr"] else None) if x),
                "eingegangen": _datum(r["erstellt_am"]), "aktualisiert": _datum(r["aktualisiert_am"]), "fotos": r["fotos"],
                "geloescht": bool(r["geloescht"])}

    def loeschen(self, daten: dict) -> dict:
        """Widerruf durch den Verkäufer selbst – dieselbe Löschung wie durch den Inhaber (``datenrechte.widerruf``)."""
        aid = self._anfrage_id("status", daten.get("token"))
        if daten.get("bestaetigt") is not True:
            raise Antwort(400, "Bitte die Löschung bestätigen")
        with self.k.sperre:
            try:
                datenrechte.widerruf(self.k.db, self.k.cfg, self.k.foto_ordner, aid, None)
            except LookupError as e:
                raise Antwort(404, str(e)) from e
            except ValueError:
                raise Antwort(409, "Zu dieser Anfrage gibt es bereits einen Ankaufsvorgang – bitte melden Sie sich bei uns, "
                                   "wir klären die Löschung persönlich.") from None
        log.info("Portal: Verkäufer hat die Löschung der Anfrage %s ausgelöst", aid)
        return {"ok": True}


def _datum(wert: str | None) -> str | None:
    try:
        return datetime.fromisoformat(wert).strftime("%d.%m.%Y") if wert else None
    except ValueError:
        return None


def _aufraeumen(k: PortalKontext):
    """Offene Transaktion nur unter der Sperre zurückrollen – sonst träfe es die Transaktion einer anderen, gerade laufenden Anfrage
    auf der gemeinsamen Verbindung (QA B1). Mit der Sperre ist jede eigene Transaktion schon beendet (``transaktion()`` rollt selbst zurück)."""
    with k.sperre:
        if k.db.con.in_transaction:
            k.db.con.rollback()


def bearbeite_portal(handler, k: PortalKontext, methode: str):
    a = PortalAnfrage(handler, k)
    try:
        a.pruefe_host()                       # vor allem anderen, auch vor dem Lesen des Inhalts
        a.get() if methode == "GET" else a.post()
    except Antwort as e:
        a.json(e.status, {"fehler": e.fehler, **e.extra})
    except sqlite3.OperationalError as e:
        _aufraeumen(k)
        if "locked" not in str(e).lower() and "busy" not in str(e).lower():
            log.exception("Portal: Datenbankfehler bei %s %s", methode, a.pfad)
        a.json(503, {"fehler": "Kurz belegt – bitte gleich erneut versuchen"})
    except Exception:  # noqa: BLE001 – Server soll weiterlaufen, keine Details nach außen
        log.exception("Portal: Fehler bei %s %s", methode, a.pfad)
        _aufraeumen(k)
        a.json(500, {"fehler": "Interner Fehler – bitte später erneut versuchen"})


def baue_portal_handler(k: PortalKontext):
    class PortalHandler(BaseHTTPRequestHandler):
        server_version = "Ankaufsportal"
        sys_version = ""
        timeout = 30

        def log_message(self, fmt, *args):            # keine IP-Adressen ins Protokoll
            pass

        def do_GET(self):
            bearbeite_portal(self, k, "GET")

        def do_POST(self):
            bearbeite_portal(self, k, "POST")

    return PortalHandler


def erstelle_portal(cfg: dict, db: Datenbank, basis: Path, schluessel: str, port: int | None = None, uhr=time.time):
    """Lauscht nur auf 127.0.0.1 – öffentlich erreichbar allein über den HTTPS-Reverse-Proxy (docs/SERVERBETRIEB.md)."""
    from ..app import Server
    k = PortalKontext(cfg, db, basis, (basis / cfg["ausgabe"]["datenbank"]).parent / "fotos", schluessel, uhr)
    server = Server(("127.0.0.1", k.p["port"] if port is None else port), baue_portal_handler(k))
    server.kontext = k
    return server


def starte_portal(cfg: dict, db: Datenbank, basis: Path, port: int | None = None):
    schluessel = os.environ.get(UMGEBUNG_SCHLUESSEL)
    gruende = startbereit(cfg, schluessel)
    if gruende:
        raise PortalFehler("Das Ankaufsportal startet nicht:\n  - " + "\n  - ".join(gruende))
    server = erstelle_portal(cfg, db, basis, schluessel, port)
    print(f"Ankaufsportal auf 127.0.0.1:{server.server_address[1]} für {einstellungen(cfg)['oeffentliche_url']}   (Beenden: Strg+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()
