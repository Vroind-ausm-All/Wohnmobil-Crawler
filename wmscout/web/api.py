"""HTTP-Schnittstelle der App: Desktop-Liste (/), Handy-App (/m), JSON-API, Fotos, Protokoll, Kalender.

Zugriffsschutz:
  * Ohne angelegte Nutzer: wie bisher nur vom PC selbst (Host 127.0.0.1/localhost), keine Anmeldung.
  * Sobald ein Nutzer existiert (`scout.py nutzer anlegen`): Anmeldung für alles außer Login und statische Dateien.
  * Zugriff über andere Hostnamen (z. B. Tailscale) nur, wenn freigegeben UND Nutzer angelegt sind.
  * Ändernde Anfragen brauchen zusätzlich den Header X-Scout-Token (Schutz gegen fremde Webseiten).
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from jinja2 import Environment, FileSystemLoader

from ..ausgabe import render_html
from ..benachrichtigung import WhatsAppCloud, whatsapp_link
from ..bewertung.anschreiben import euro, tsd
from ..bewertung.auswertung import bewerte_alle
from ..bewertung.besichtigung import berechne, lade_katalog
from ..datenbank import STATUS, Datenbank
from ..eingang import import_ordner, relativ_zum_projekt
from ..importer import Importer
from ..team import BESICHTIGUNG_STATUS, ROLLEN, TeamSpeicher

log = logging.getLogger("scout")
STATIC = Path(__file__).with_name("static")
COOKIE = "scout_sitzung"
OFFENE_PFADE = {"/login", "/api/login", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}
MAX_JSON = 1_000_000
MAX_FOTO = 12_000_000          # Base64-kodiert, entspricht ca. 8 MB Bild
MAX_IMPORT_DATEIEN = 25        # gespeicherte Seiten je Klick, der Rest beim nächsten Mal
MAX_IMPORT_SEKUNDEN = 20       # Zeitbudget je Klick (die Anfrage hält die Datenbanksperre)


class Antwort(Exception):
    """Beendet eine Anfrage mit HTTP-Status und JSON-Fehlertext."""

    def __init__(self, status: int, fehler: str):
        super().__init__(fehler)
        self.status, self.fehler = status, fehler


class Kontext:
    """Alles, was die Anfragen brauchen – einmal pro Server angelegt."""

    def __init__(self, cfg: dict, db: Datenbank, basis: Path, token: str, suchlauf, foto_ordner: Path):
        self.cfg, self.db, self.basis, self.token, self.suchlauf = cfg, db, basis, token, suchlauf
        self.team = TeamSpeicher(db, foto_ordner)
        self.katalog_pfad = basis / "maengel.yaml"
        self.sperre = threading.Lock()          # Datenbankzugriffe nacheinander, Netzwerk parallel
        self._zeilen: tuple[float, list[dict]] | None = None
        self.whatsapp = WhatsAppCloud(cfg)
        self.env = Environment(loader=FileSystemLoader(str(basis / "vorlagen")), autoescape=True)
        self.env.filters["euro"] = euro
        self.env.filters["tsd"] = tsd

    # Bewertung aller Inserate ist teuer → 30 s zwischenspeichern, bei Änderungen verwerfen
    def zeilen(self) -> list[dict]:
        if not self._zeilen or time.monotonic() - self._zeilen[0] > 30:
            seit = self.suchlauf.letzter_start or (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
            self._zeilen = (time.monotonic(), bewerte_alle(self.cfg, self.db, self.basis, lauf_start=seit))
        return self._zeilen[1]

    def veraendert(self):
        self._zeilen = None

    def zeile(self, anzeige_id: str) -> dict:
        for z in self.zeilen():
            if z["a"]["id"] == anzeige_id:
                return z
        raise Antwort(404, "Inserat nicht (mehr) aktiv")

    def katalog(self) -> dict:
        return lade_katalog(self.katalog_pfad)

    def erlaubte_hosts(self, port: int) -> set[str]:
        a = self.cfg.get("app") or {}
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if a.get("oeffentliche_url"):
            hosts.add(urlparse(a["oeffentliche_url"]).netloc)
        hosts.update(a.get("erlaubte_hosts") or [])
        return hosts

    def app_link(self, pfad: str) -> str | None:
        url = ((self.cfg.get("app") or {}).get("oeffentliche_url") or "").rstrip("/")
        return f"{url}{pfad}" if url else None


# ---------------------------------------------------------------- Hilfen
def basis_fuer(z: dict, cfg: dict) -> dict:
    """Bewertungsgrundlage, die beim Anlegen einer Besichtigung eingefroren wird."""
    a, b = z["a"], z["b"]
    risiko = sum(v for k, v in b.kosten_posten.items() if k.startswith("Reparaturrisiko"))
    return {
        "anzeige_id": a["id"], "fahrzeug": a["fahrzeug"], "titel": a["titel"], "url": a["url"], "ort": a.get("ort"),
        "ez_jahr": a.get("ez_jahr"), "km_anzeige": a.get("km"), "preis": a.get("preis"), "art": b.art,
        "angebot": a.get("angebot_betrag") or b.erstangebot, "max_ek": b.max_ek, "marktwert_privat": b.marktwert_privat,
        "haendler_vk": b.haendler_vk, "reparaturrisiko": risiko,
        "differenzbesteuerung": bool(cfg["rechner"]["differenzbesteuerung"]), "eingefroren_am": datetime.now().isoformat(timespec="seconds"),
    }


def fahrzeug_kurz(z: dict) -> dict:
    a, b = z["a"], z["b"]
    return {"id": a["id"], "fahrzeug": a["fahrzeug"], "titel": a["titel"], "ort": a.get("ort"), "url": a["url"],
            "quelle": a.get("quelle") or "kleinanzeigen",
            "bild": a.get("bild"), "ez_jahr": a.get("ez_jahr"), "km": a.get("km"), "preis": a.get("preis"),
            "entfernung_km": a.get("entfernung_km"), "tage_online": a.get("tage_online"), "status": a.get("status") or "neu",
            "ampel": b.ampel, "erstangebot": b.erstangebot if b.sicherheit != "keine" else None,
            "max_ek": b.max_ek if b.sicherheit != "keine" else None, "bereit": z["bereit"], "nachfassen": z["nachfassen"],
            "sperre": z["sperre"], "hinweise": z["hinweise"], "neu": z["neu"]}


def ics(b: dict, cfg: dict, link: str | None) -> str:
    start = datetime.fromisoformat(b["termin"])
    ende = start + timedelta(hours=1)

    def esc(t: str) -> str:
        return (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    beschreibung = f"Inserat: {b['basis'].get('url', '')}\nWunschpreis {euro(b['basis'].get('preis'))}, " \
                   f"vorbehaltliches Angebot {euro(b['basis'].get('angebot'))}" + (f"\nApp: {link}" if link else "")
    zeilen = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Wohnmobil-Scout//DE", "BEGIN:VEVENT",
              f"UID:besichtigung-{b['id']}@wohnmobil-scout", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
              f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{ende:%Y%m%dT%H%M%S}",
              f"SUMMARY:{esc('Besichtigung ' + b['basis'].get('fahrzeug', ''))}",
              f"LOCATION:{esc(b.get('adresse') or b['basis'].get('ort') or '')}",
              f"DESCRIPTION:{esc(beschreibung)}", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(zeilen) + "\r\n"


def termin_text(b: dict, link: str | None) -> str:
    t = datetime.fromisoformat(b["termin"]).strftime("%d.%m.%Y um %H:%M Uhr") if b.get("termin") else "Termin offen"
    teile = [f"Besichtigung {b['basis'].get('fahrzeug', '')}", t, b.get("adresse") or b["basis"].get("ort") or "",
             f"Inserat: {b['basis'].get('url', '')}"]
    if link:
        teile.append(f"In der App: {link}")
    return "\n".join(p for p in teile if p)


def karten_link(adresse: str | None) -> str | None:
    return f"https://www.google.com/maps/search/?api=1&query={quote(adresse)}" if adresse else None


def _bild_bytes(daten_url: str) -> bytes:
    roh = daten_url.split(",", 1)[1] if daten_url.startswith("data:") else daten_url
    try:
        return base64.b64decode(roh, validate=True)
    except (binascii.Error, ValueError) as e:
        raise Antwort(400, "Bild ist nicht lesbar") from e


# ---------------------------------------------------------------- Router
class Anfrage:
    def __init__(self, handler, k: Kontext):
        self.h, self.k = handler, k
        url = urlparse(handler.path)
        self.pfad, self.query = url.path.rstrip("/") or "/", parse_qs(url.query)
        cookie = SimpleCookie(handler.headers.get("Cookie") or "")
        self.sitzung = cookie[COOKIE].value if COOKIE in cookie else None
        self.nutzer: dict | None = None
        self.verzoegern = False          # nach Fehlanmeldung – außerhalb der Sperre warten

    # ----- Antworten
    def senden(self, status: int, body: bytes, typ: str, kopf: dict | None = None):
        h = self.h
        h.send_response(status)
        h.send_header("Content-Type", typ)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("Referrer-Policy", "no-referrer")
        for k, v in (kopf or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(body)

    def json(self, status: int, obj, kopf: dict | None = None):
        self.senden(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                    "application/json; charset=utf-8", kopf)

    def html(self, text: str, status: int = 200):
        self.senden(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def weiterleiten(self, ziel: str):
        self.senden(303, b"", "text/plain", {"Location": ziel})

    # ----- Zugriff
    def pruefe_zugriff(self, aendernd: bool):
        port = self.h.server.server_address[1]
        host = self.h.headers.get("Host") or ""
        lokal = host in (f"127.0.0.1:{port}", f"localhost:{port}")
        if host not in self.k.erlaubte_hosts(port):
            raise Antwort(403, "Dieser Hostname ist nicht freigegeben (config.yaml → app → oeffentliche_url)")
        team = self.k.team.hat_nutzer()
        if not team:
            if not lokal:
                raise Antwort(403, "Zugriff von außen erst, wenn Nutzer angelegt sind: python scout.py nutzer anlegen …")
            self.nutzer = {"id": None, "name": "lokal", "rolle": "inhaber", "telefon": None}
        else:
            self.nutzer = self.k.team.nutzer_zu_token(self.sitzung)
        if self.pfad in OFFENE_PFADE or self.pfad.startswith("/static/"):
            return
        if not self.nutzer:
            raise Antwort(401, "Bitte anmelden")
        if aendernd and self.h.headers.get("X-Scout-Token") != self.k.token:
            raise Antwort(403, "Zugriff verweigert – Seite bitte neu laden")

    def darf_besichtigung(self, b: dict) -> bool:
        return self.nutzer["rolle"] == "inhaber" or b["zustaendig_id"] in (None, self.nutzer["id"])

    def besichtigung(self, bid: str, schreiben: bool = False) -> dict:
        b = self.k.team.besichtigung(int(bid))
        if not b:
            raise Antwort(404, "Besichtigung nicht gefunden")
        if schreiben and not self.darf_besichtigung(b):
            raise Antwort(403, "Diese Besichtigung ist einem anderen Mitarbeiter zugewiesen")
        return b

    # ----- statische Dateien (ohne Sperre)
    def statisch(self) -> bool:
        name = {"/sw.js": "sw.js", "/manifest.webmanifest": "manifest.webmanifest",
                "/favicon.ico": "icon-192.png"}.get(self.pfad)
        if not name and self.pfad.startswith("/static/"):
            name = self.pfad[len("/static/"):]
        if not name:
            return False
        if not re.fullmatch(r"[\w.-]+", name) or not (STATIC / name).is_file():
            self.json(404, {"fehler": "nicht gefunden"})
            return True
        typ = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
               "webmanifest": "application/manifest+json", "svg": "image/svg+xml"}.get(
            name.rsplit(".", 1)[-1], mimetypes.guess_type(name)[0] or "application/octet-stream")
        kopf = {"Service-Worker-Allowed": "/"} if name == "sw.js" else None
        self.senden(200, (STATIC / name).read_bytes(), typ, kopf)
        return True

    # ----- GET
    def get(self):
        k, p = self.k, self.pfad
        if p == "/login":
            return self.html(k.env.get_template("login.html").render(firma=k.cfg["anschreiben"]["firma"]))
        if p == "/":
            zeilen = k.zeilen()
            html, _ = render_html(k.cfg, zeilen, k.basis, fehler=k.suchlauf.stand["fehler"], app={"token": k.token})
            return self.html(html)
        if p == "/m":
            return self.html(k.env.get_template("mobil.html").render(firma=k.cfg["anschreiben"]["firma"]))
        if p == "/api/ich":
            return self.json(200, {"nutzer": self.nutzer, "csrf": k.token, "team": k.team.hat_nutzer(),
                                   "rollen": ROLLEN, "status": STATUS, "besichtigung_status": BESICHTIGUNG_STATUS,
                                   "firma": {x: k.cfg["anschreiben"].get(x) for x in
                                             ("firma", "ansprechpartner", "telefon", "ort")},
                                   "differenzbesteuerung": bool(k.cfg["rechner"]["differenzbesteuerung"])})
        if p == "/api/suchlauf":
            return self.json(200, k.suchlauf.stand)
        if p == "/api/nutzer":
            return self.json(200, k.team.nutzer_liste())
        if p == "/api/katalog":
            return self.json(200, k.katalog())
        if p == "/api/heute":
            return self.json(200, self.heute())
        if p == "/api/fahrzeuge":
            return self.json(200, self.fahrzeuge())
        if m := re.fullmatch(r"/api/fahrzeug/([\w-]+)", p):
            return self.json(200, self.fahrzeug(m.group(1)))
        if m := re.fullmatch(r"/api/besichtigung/(\d+)", p):
            return self.json(200, self.besichtigung_voll(self.besichtigung(m.group(1))))
        if m := re.fullmatch(r"/api/besichtigung/(\d+)/ics", p):
            b = self.besichtigung(m.group(1))
            if not b.get("termin"):
                raise Antwort(400, "Kein Termin eingetragen")
            return self.senden(200, ics(b, k.cfg, k.app_link(f"/m#/besichtigung/{b['id']}")).encode("utf-8"),
                               "text/calendar; charset=utf-8",
                               {"Content-Disposition": f'attachment; filename="besichtigung-{b["id"]}.ics"'})
        if m := re.fullmatch(r"/fotos/(\d+)/([\w.-]+)", p):
            pfad = k.team.foto_pfad(int(m.group(1)), m.group(2))
            if not pfad:
                raise Antwort(404, "Foto nicht gefunden")
            return self.senden(200, pfad.read_bytes(), mimetypes.guess_type(pfad.name)[0] or "image/jpeg")
        if m := re.fullmatch(r"/protokoll/(\d+)", p):
            return self.html(self.protokoll(self.besichtigung(m.group(1))))
        raise Antwort(404, "nicht gefunden")

    def heute(self) -> dict:
        k, ich = self.k, self.nutzer
        eigene = ich["rolle"] != "inhaber" and ich["id"]
        termine = k.team.besichtigungen(zustaendig_id=ich["id"] if eigene else None)
        zeilen = k.zeilen()
        return {
            "termine": [self.besichtigung_kurz(b) for b in termine],
            "bereit": sum(1 for z in zeilen if z["bereit"] and (z["a"].get("status") or "neu") == "neu"),
            "nachfassen": sum(1 for z in zeilen if z["nachfassen"]),
            "arbeit": sum(1 for z in zeilen if z["a"].get("status") in ("kontaktiert", "verhandlung", "besichtigung")),
            "suchlauf": k.suchlauf.stand,
        }

    def fahrzeuge(self) -> list[dict]:
        f = (self.query.get("filter") or ["bereit"])[0]
        q = (self.query.get("q") or [""])[0].lower().split()
        auswahl = []
        for z in self.k.zeilen():
            s = z["a"].get("status") or "neu"
            ok = {"bereit": z["bereit"] and s == "neu", "nachfassen": bool(z["nachfassen"]),
                  "arbeit": s in ("kontaktiert", "verhandlung", "besichtigung"), "alle": True}.get(f, False)
            text = f"{z['a']['fahrzeug']} {z['a']['titel']} {z['a'].get('ort') or ''}".lower()
            if ok and all(w in text for w in q):
                auswahl.append(z)
        auswahl.sort(key=lambda z: z["b"].verhaeltnis or 99)
        return [fahrzeug_kurz(z) for z in auswahl[:200]]

    def fahrzeug(self, anzeige_id: str) -> dict:
        z = self.k.zeile(anzeige_id)
        return {**fahrzeug_kurz(z), "bewertung": z["b"].dict(), "brief": z["brief"], "nachfass_text": z["nachfass_text"],
                "nachfass_betrag": z["nachfass_betrag"], "anschreiben_text": z["a"].get("anschreiben_text"),
                "notiz": z["a"].get("notiz"), "besichtigungen": [self.besichtigung_kurz(b) for b in
                                                                 self.k.team.besichtigungen(offen=False, anzeige_id=anzeige_id)]}

    def besichtigung_kurz(self, b: dict) -> dict:
        link = self.k.app_link(f"/m#/besichtigung/{b['id']}")
        return {"id": b["id"], "anzeige_id": b["anzeige_id"], "status": b["status"], "termin": b["termin"],
                "adresse": b["adresse"], "zustaendig": b["zustaendig"], "fahrzeug": b["basis"].get("fahrzeug"),
                "bild": None, "endpreis": b["endpreis"], "karte": karten_link(b.get("adresse") or b["basis"].get("ort")),
                "whatsapp": whatsapp_link(termin_text(b, link), (b["zustaendig"] or {}).get("telefon")),
                "darf_bearbeiten": self.darf_besichtigung(b)}

    def besichtigung_voll(self, b: dict) -> dict:
        e = berechne(self.k.katalog(), b["daten"] or {}, b["basis"])
        return {**self.besichtigung_kurz(b), "basis": b["basis"], "daten": b["daten"], "ergebnis": e,
                "protokoll": b["protokoll"], "version": b["version"], "fotos": self.k.team.fotos(b["id"])}

    def protokoll(self, b: dict) -> str:
        e = b["ergebnis"] or berechne(self.k.katalog(), b["daten"] or {}, b["basis"])
        return self.k.env.get_template("protokoll.html").render(
            b=b, e=e, d=b["daten"] or {}, p=b["protokoll"] or {}, fotos=self.k.team.fotos(b["id"]),
            firma=self.k.cfg["anschreiben"], katalog=self.k.katalog(), jetzt=datetime.now())

    # ----- POST
    def post(self, daten: dict):
        k, p = self.k, self.pfad
        text = str(daten["text"])[:5000] if daten.get("text") else None
        betrag = daten.get("betrag") if isinstance(daten.get("betrag"), int) else None
        if p == "/api/login":
            token = k.team.anmelden(str(daten.get("name") or ""), str(daten.get("passwort") or ""))
            if not token:
                self.verzoegern = True                        # Raten verlangsamen (ohne andere zu blockieren)
                raise Antwort(401, "Name oder Passwort falsch")
            sicher = "; Secure" if self.h.headers.get("X-Forwarded-Proto") == "https" else ""
            return self.json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                                                               f"Max-Age={30 * 86400}{sicher}"})
        if p == "/api/logout":
            if self.sitzung:
                k.team.abmelden(self.sitzung)
            return self.json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"})
        if p == "/api/status":
            if daten.get("status") not in STATUS:
                raise Antwort(400, "unbekannter Status")
            ok = k.db.setze_status(str(daten.get("id")), daten["status"], text=text, betrag=betrag)
            k.veraendert()
            return self.json(200 if ok else 404, {"ok": ok})
        if p == "/api/nachgefasst":
            ok = bool(text) and k.db.nachgefasst(str(daten.get("id")), text, betrag)
            k.veraendert()
            return self.json(200 if ok else 400, {"ok": ok})
        if p == "/api/notiz":
            ok = k.db.setze_notiz(str(daten.get("id")), str(daten.get("notiz") or "")[:2000])
            k.veraendert()
            return self.json(200 if ok else 404, {"ok": ok})
        if p == "/api/suchlauf":
            return self.json(200, {"gestartet": k.suchlauf.starte(), **k.suchlauf.stand})
        if p == "/api/import":
            return self.json(200, self.seiten_einlesen())
        if p == "/api/besichtigung":
            return self.json(200, self.besichtigung_anlegen(daten))
        if m := re.fullmatch(r"/api/besichtigung/(\d+)/(planen|speichern|foto|abschluss)", p):
            b = self.besichtigung(m.group(1), schreiben=True)
            return self.json(200, getattr(self, f"b_{m.group(2)}")(b, daten))
        raise Antwort(404, "nicht gefunden")

    def seiten_einlesen(self) -> dict:
        """Gespeicherte Seiten aus dem konfigurierten Import-Ordner – nie ein Pfad aus der Anfrage, kein Netzabruf."""
        k = self.k
        if k.suchlauf.stand["laeuft"]:
            raise Antwort(409, "Gerade läuft ein Suchlauf – bitte danach einlesen")
        ordner = import_ordner(k.cfg)
        ordner.mkdir(parents=True, exist_ok=True)
        stat = Importer(k.cfg, k.db).importiere_seiten(ordner, max_dateien=MAX_IMPORT_DATEIEN,
                                                             max_sekunden=MAX_IMPORT_SEKUNDEN)
        k.veraendert()
        return {**stat, "ordner": relativ_zum_projekt(ordner)}

    def _termin(self, wert) -> str | None:
        if not wert:
            return None
        try:
            return datetime.fromisoformat(str(wert)).isoformat(timespec="minutes")
        except ValueError as e:
            raise Antwort(400, "Termin bitte als Datum und Uhrzeit angeben") from e

    def _zustaendig(self, wert) -> int | None:
        if wert in (None, ""):
            return self.nutzer["id"]
        if not self.k.team.nutzer(int(wert)):
            raise Antwort(400, "Mitarbeiter nicht gefunden")
        return int(wert)

    def besichtigung_anlegen(self, daten: dict) -> dict:
        k = self.k
        z = k.zeile(str(daten.get("anzeige_id")))
        bid = k.team.besichtigung_anlegen(z["a"]["id"], basis_fuer(z, k.cfg), self._termin(daten.get("termin")),
                                          (daten.get("adresse") or "").strip() or None,
                                          self._zustaendig(daten.get("zustaendig_id")), self.nutzer["id"])
        if (z["a"].get("status") or "neu") in ("neu", "kontaktiert", "verhandlung"):
            k.db.setze_status(z["a"]["id"], "besichtigung")
            k.veraendert()
        b = k.team.besichtigung(bid)
        self._zuweisung_melden(b)
        return self.besichtigung_kurz(b)

    def _zuweisung_melden(self, b: dict):
        z = b["zustaendig"]
        if z and z["id"] != self.nutzer["id"] and z.get("telefon"):
            termin = datetime.fromisoformat(b["termin"]).strftime("%d.%m. %H:%M") if b.get("termin") else "offen"
            self.k.whatsapp.sende(z["telefon"], self.k.cfg.get("whatsapp", {}).get("vorlage_zuweisung"),
                                  [b["basis"].get("fahrzeug", ""), termin, b.get("adresse") or b["basis"].get("ort") or ""])

    def b_planen(self, b: dict, daten: dict) -> dict:
        self.k.team.besichtigung_planen(b["id"], self._termin(daten.get("termin")),
                                        (daten.get("adresse") or "").strip() or None,
                                        self._zustaendig(daten.get("zustaendig_id")))
        neu = self.k.team.besichtigung(b["id"])
        if neu["zustaendig_id"] != b["zustaendig_id"]:
            self._zuweisung_melden(neu)
        return self.besichtigung_kurz(neu)

    def b_speichern(self, b: dict, daten: dict) -> dict:
        if b["status"] in ("abgeschlossen", "abgebrochen"):
            raise Antwort(409, "Besichtigung ist bereits abgeschlossen")
        eingaben = daten.get("daten")
        if not isinstance(eingaben, dict):
            raise Antwort(400, "daten fehlen")
        ergebnis = berechne(self.k.katalog(), eingaben, b["basis"])        # verbindlich: Server rechnet nach
        version = self.k.team.besichtigung_speichern(b["id"], eingaben, ergebnis)
        konflikt = isinstance(daten.get("version"), int) and daten["version"] != b["version"]
        return {"ergebnis": ergebnis, "version": version, "konflikt": konflikt}

    def b_foto(self, b: dict, daten: dict) -> dict:
        try:
            return self.k.team.foto_speichern(b["id"], _bild_bytes(str(daten.get("bild") or "")),
                                              daten.get("mangel_key") or None, self.nutzer["id"])
        except ValueError as e:
            raise Antwort(400, str(e)) from e

    def b_abschluss(self, b: dict, daten: dict) -> dict:
        if b["status"] in ("abgeschlossen", "abgebrochen"):
            raise Antwort(409, "Besichtigung ist bereits abgeschlossen")
        entscheidung = daten.get("entscheidung")
        if entscheidung not in ("gekauft", "abgelehnt", "offen", "abgebrochen"):
            raise Antwort(400, "Entscheidung fehlt (gekauft, abgelehnt, offen oder abgebrochen)")
        e = berechne(self.k.katalog(), b["daten"] or {}, b["basis"])
        if entscheidung == "gekauft":
            if not e["vollstaendig"] and not (daten.get("begruendung_unvollstaendig") or "").strip():
                raise Antwort(400, "Pflichtpunkte fehlen: " + "; ".join(e["fehlende_pflicht"]))
            if not isinstance(daten.get("endpreis"), int) or daten["endpreis"] <= 0:
                raise Antwort(400, "Vereinbarten Kaufpreis eintragen")
            for feld in ("unterschrift_verkaeufer", "unterschrift_ankaeufer"):
                if not str(daten.get(feld) or "").startswith("data:image/png;base64,"):
                    raise Antwort(400, "Beide Unterschriften fehlen")
        protokoll = {k: daten.get(k) for k in ("entscheidung", "endpreis", "verkaeufer", "bemerkung",
                                               "begruendung_unvollstaendig")}
        for feld in ("unterschrift_verkaeufer", "unterschrift_ankaeufer"):      # nur echte PNG-Bilder übernehmen
            wert = str(daten.get(feld) or "")
            protokoll[feld] = wert if re.fullmatch(r"data:image/png;base64,[A-Za-z0-9+/=]+", wert) else None
        protokoll.update(abgeschlossen_am=datetime.now().isoformat(timespec="minutes"), ergebnis=e,
                         abgeschlossen_von=self.nutzer["name"])
        endpreis = daten.get("endpreis") if entscheidung == "gekauft" else None
        status = "abgebrochen" if entscheidung == "abgebrochen" else "abgeschlossen"
        self.k.team.besichtigung_abschliessen(b["id"], protokoll, endpreis, status)
        ad_status = {"gekauft": "gekauft", "abgelehnt": "abgesagt", "offen": "verhandlung"}.get(entscheidung)
        if ad_status:
            self.k.db.setze_status(b["anzeige_id"], ad_status, betrag=endpreis)
            self.k.veraendert()
        return {"ok": True, "protokoll": f"/protokoll/{b['id']}"}


def bearbeite(handler, k: Kontext, methode: str):
    a = Anfrage(handler, k)
    try:
        if methode == "GET" and a.statisch():
            return
        daten = {}
        if methode == "POST":
            laenge = int(handler.headers.get("Content-Length") or 0)
            if laenge > (MAX_FOTO if a.pfad.endswith("/foto") else MAX_JSON):
                raise Antwort(413, "Anfrage zu groß")
            roh = handler.rfile.read(laenge) if laenge else b""      # Übertragung ohne Sperre
            try:
                daten = json.loads(roh) if roh else {}
            except ValueError as e:
                raise Antwort(400, "ungültige Anfrage") from e
            if not isinstance(daten, dict):
                raise Antwort(400, "ungültige Anfrage")
        with k.sperre:
            a.pruefe_zugriff(aendernd=methode == "POST" and a.pfad != "/api/login")
            a.get() if methode == "GET" else a.post(daten)
    except Antwort as e:
        if a.verzoegern:
            time.sleep(1)
        if e.status == 401 and methode == "GET" and not a.pfad.startswith("/api/"):
            return a.weiterleiten("/login?weiter=" + quote(handler.path))
        a.json(e.status, {"fehler": e.fehler})
    except Exception:  # noqa: BLE001 – Server soll bei einem Fehler weiterlaufen
        log.exception("Fehler bei %s %s", methode, handler.path)
        a.json(500, {"fehler": "Interner Fehler – Details in ausgabe/scout.log"})
