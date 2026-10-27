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
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from jinja2 import Environment, FileSystemLoader

from ..ausgabe import render_html
from .. import verkauf as vk
from ..verkauf import Eingabefehler, VerkaufSpeicher
from ..haendler import STANDORT_STATUS, HaendlerSpeicher
from ..auktion import STANDARD as MINDESTPREIS_STANDARD
from ..auktion import AuktionSpeicher, AuktionsFehler
from .. import datenrechte
from ..schalter import EingangDeaktiviert, eingang_pruefen, pruefe_eingaenge
from ..audit import AuditSpeicher, einordnen
from ..nutzung import nutzung
from ..deal import DealSpeicher
from ..team import hash_passwort, pruefe_passwort
from .live import Ereignisse, art_fuer, sse_block
from .sicherheit import SICHERHEITS_KOPF, LoginBremse
from ..ankauf import DOKUMENTARTEN, AnkaufFehler, AnkaufSpeicher
from ..ankauf import STATUS as ANKAUF_STATUS
from ..bewertung.ergebnis import KOSTENARTEN
from ..team import HAENDLER
from ..bearbeitung import (IN_ARBEIT, OFFEN, VORBEREITET, BearbeitungsKonflikt, TeamSicht, ablauf_grenze, darf_erzwingen, darf_status,
                           darf_zuweisen, reservierung_tage)
from ..benachrichtigung import WhatsAppCloud, whatsapp_link
from ..bewertung.anschreiben import euro, tsd
from ..bewertung.auswertung import bewerte_alle, bewerte_anzeige, dubletten_ids
from ..verfuegbarkeit import fahrzeug_von, offline_nach_tagen
from ..anbieter import einstufung
from .. import kontakte
from .. import suchprofile as sp
from .. import laufprotokoll as lp
from .. import abdeckung
from ..zugaenge import PLATTFORMEN as ZUGANG_PLATTFORMEN
from ..zugaenge import ZugangSpeicher
from ..domaene import PLATTFORMEN
from ..normalisierung.qualitaet import je_quelle
from ..bewertung import kalibrierung as kal
from ..bewertung import kalkulation as kalk
from ..bewertung.besichtigung import berechne, lade_katalog
from ..datenbank import STATUS, Datenbank
from ..domaene import fahrzeug_status
from ..dubletten import (MAX_LIMIT, STANDARD_LIMIT, DublettenFehler, DublettenKonflikt, Ergebnis, bestaetige, darf_ablehnen, darf_aufheben,
                         darf_bestaetigen, entscheidungen_zu, gruppe, halter_der_gruppe, hebe_auf, inserat_zu_anzeige, lehne_ab, pruefe_dubletten)
from ..normalisierung.identitaet import REGEL_VERSION
from ..preisverlauf import inserat_zu_anzeigen_id, preisverlauf
from ..eingang import TextEingang, ergebnis_der, import_ordner, relativ_zum_projekt
from ..eingang.text import ANBIETER, MAX_PREIS, MAX_TEXT, MAX_URL, widerspricht_marke
from ..eingang.email import mail_ordner
from ..importer import Importer
from ..team import BESICHTIGUNG_STATUS, EINLADUNG_TAGE, LEERLAUF_STUNDEN, ROLLEN, TeamSpeicher, ZugangVorhanden

log = logging.getLogger("scout")
STATIC = Path(__file__).with_name("static")
COOKIE = "scout_sitzung"
OFFENE_PFADE = {"/login", "/api/login", "/einladung", "/api/einladung", "/api/einladung/pruefen", "/manifest.webmanifest", "/sw.js",
                "/favicon.ico"}
MAX_JSON = 1_000_000
MAX_FOTO = 12_000_000          # Base64-kodiert, entspricht ca. 8 MB Bild
MAX_IMPORT_DATEIEN = 25        # gespeicherte Seiten je Klick, der Rest beim nächsten Mal
MAX_IMPORT_SEKUNDEN = 20       # Zeitbudget je Klick (die Anfrage hält die Datenbanksperre)
TEXT_IMPORT_ROLLEN = ("inhaber", "mitarbeiter")     # Import per Adresse + Text: jedes Teammitglied, nie Standort-Zugänge (ADR-026)


# Maschinenlesbarer Grund einer Ablehnung (Feld ``grund`` in der JSON-Antwort), damit Oberflächen z. B. ein fehlendes CSRF-Token
# (neu laden, wiederholen) von einer fachlichen Ablehnung (nicht wiederholen) unterscheiden:
#   csrf      403  Token fehlt/veraltet (Server neu gestartet) – Token neu holen und einmal wiederholen ist sinnvoll
#   recht     403  fachlich nicht erlaubt (Erzwingen/Zuweisen nur Inhaber, fremde Besichtigung, fremdes Inserat abgeben)
#   zugriff   403  Hostname/Zugang nicht freigegeben
#   konflikt  409  Zustand passt nicht (Kollege hält das Inserat bzw. eine Dublette, Besichtigung abgeschlossen, Suchlauf läuft)
#   deaktiviert 409  Eingang ist in config.yaml abgeschaltet (eingaenge → … → aktiv) – nichts wurde gelesen
#   belegt    503  Datenbank kurz von einem anderen Vorgang gesperrt – später erneut versuchen
GRUENDE = {403: "recht", 409: "konflikt", 503: "belegt"}


# Unterschriften und Kontaktdaten des Verkäufers nur im Protokoll-Dokument (/protokoll/ID), nie in der Handy-API (P1-14b)
OHNE_GERAET = ("unterschrift_verkaeufer", "unterschrift_ankaeufer", "verkaeufer")
BETRAEGE = ("marktwert_privat", "haendler_vk", "kosten", "ziel_marge", "max_ek", "erstangebot", "max_ek_von", "max_ek_bis", "privat_von",
            "privat_bis")


def bewertung_json(b) -> dict:
    """Bewertung für die Oberfläche; ohne unabhängigen Marktwert (Sicherheit „keine“) Beträge als ``null`` statt 0 (P1-12)."""
    d = b.dict()
    if b.sicherheit == "keine":
        d.update(dict.fromkeys(BETRAEGE))
    return d


def sicheres_ziel(weiter: str | None, standard: str = "/m") -> str:
    """Ziel nach der Anmeldung (Q6): nur ein Pfad auf diesem Server. Abgelehnt werden fremde Adressen, „//…“, „/\\…“, Punkt-
    Segmente („/.//x“ würde der Browser zu „//x“ machen) und Steuerzeichen – dann gilt der Standard."""
    if not weiter or len(weiter) > 500 or not weiter.startswith("/") or "//" in weiter or "\\" in weiter:
        return standard
    if any(ord(c) < 33 or ord(c) == 127 for c in weiter):
        return standard
    pfad = urlparse(weiter)
    if pfad.scheme or pfad.netloc or any(teil in (".", "..") for teil in pfad.path.split("/")):
        return standard
    return weiter


class Antwort(Exception):
    """Beendet eine Anfrage mit HTTP-Status, JSON-Fehlertext und (für 403/409/503) einem ``grund``."""

    def __init__(self, status: int, fehler: str, extra: dict | None = None, grund: str | None = None):
        super().__init__(fehler)
        self.status, self.fehler, self.extra = status, fehler, extra or {}
        self.grund = grund or GRUENDE.get(status)


class Kontext:
    """Alles, was die Anfragen brauchen – einmal pro Server angelegt."""

    def __init__(self, cfg: dict, db: Datenbank, basis: Path, token: str, suchlauf, foto_ordner: Path):
        self.cfg, self.db, self.basis, self.token, self.suchlauf = cfg, db, basis, token, suchlauf
        app = cfg.get("app") or {}
        self.team = TeamSpeicher(db, foto_ordner, float(app.get("sitzung_leerlauf_stunden", LEERLAUF_STUNDEN) or 0))
        self.audit = AuditSpeicher(db)
        self.live = Ereignisse(int(app.get("live_max_je_nutzer", 4)), int(app.get("live_max_gesamt", 40)))
        self.live_lebensdauer, self.live_ping = 300.0, 15.0      # Sekunden; Tests verkürzen
        self.verkauf = VerkaufSpeicher(db, foto_ordner / "anfragen")     # im Fotoordner: mit gesichert
        self.haendler = HaendlerSpeicher(db)
        self.zugaenge = ZugangSpeicher(db, cfg)              # Händlerzugänge mobile.de/AutoScout24 (F4) – ohne Geheimnisse
        self.suchprofile = sp.SuchprofilSpeicher(db)
        self.kalibrierung = kal.KalibrierungSpeicher(db)
        self.auktion = AuktionSpeicher(db, cfg)             # ValueError bei falscher Konfiguration (Abschnitt auktion)
        self.bremse = LoginBremse(int(app.get("login_max_fehlversuche", 5)), int(app.get("login_max_fehlversuche_je_ip", 20)),
                                  int(app.get("login_sperre_minuten", 15)) * 60)
        self.vertrauter_proxy = app.get("vertrauter_proxy") is True     # nur dann X-Forwarded-For/-Proto auswerten
        self.nur_https = app.get("nur_https") is True                    # Cookie immer „Secure“ (Betrieb hinter HTTPS)
        self.deal = DealSpeicher(db, cfg)                   # ValueError bei falscher Konfiguration (Abschnitt kalkulation)
        self.ankauf = AnkaufSpeicher(db, cfg, foto_ordner / "ankaeufe")    # im Fotoordner: mit gesichert
        self.reservierung_tage = reservierung_tage(cfg)     # ValueError mit verständlicher Meldung bei falscher Konfiguration
        pruefe_eingaenge(cfg)                               # ebenso „eingaenge“ (Einzel- und Mandantenbetrieb, P2-04)
        self.katalog_pfad = basis / "maengel.yaml"
        self.sperre = threading.Lock()          # Datenbankzugriffe nacheinander, Netzwerk parallel
        self._zeilen: tuple[float, list[dict]] | None = None
        self._dubletten: tuple[tuple, float, dict[str, list[str]]] | None = None
        self._vorschlaege: tuple[int, float, Ergebnis] | None = None
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

    def abdeckung(self, tage: int) -> dict:
        """Messung (P4-05) bis zu 5 Minuten zwischenspeichern, solange sich der Bestand nicht ändert: sie bewertet alle Inserate des Zeitraums
        und läuft unter der Datenbanksperre der App."""
        stand = (tage, self.db.daten_version(), self.db.con.total_changes, datetime.now().date())
        gemerkt = getattr(self, "_abdeckung", None)
        if not gemerkt or gemerkt[0] != stand or time.monotonic() - gemerkt[1] > 300:
            gemerkt = (stand, time.monotonic(), abdeckung.messe(self.cfg, self.db, self.basis, tage))
            self._abdeckung = gemerkt
        return gemerkt[2]

    def dubletten_von(self, anzeige_id: str) -> list[str]:
        """IDs der Dubletten ohne die teure Bewertung (`bewerte_alle`). Eigener Zwischenspeicher: Statuswechsel und Reservierungen
        ändern die Gruppen nicht, deshalb verwirft ihn `veraendert()` NICHT. Neu berechnet wird bei Schreibzugriffen anderer
        Verbindungen (Suchlauf: `PRAGMA data_version`), bei `dubletten_verwerfen()` (Seitenimport über diese Verbindung) und nach 30 s."""
        schluessel = self.db.daten_version()
        if not self._dubletten or self._dubletten[0] != schluessel or time.monotonic() - self._dubletten[1] > 30:
            self._dubletten = (schluessel, time.monotonic(), dubletten_ids(self.db))
        return self._dubletten[2].get(anzeige_id, [])

    def dubletten_verwerfen(self):
        self._dubletten = None
        self._vorschlaege = None

    def dubletten_vorschlaege(self) -> Ergebnis:
        """Offene Dublettenvorschläge (P3-02a); wie `dubletten_von` zwischengespeichert (Datenbankstand, 30 s)."""
        schluessel = self.db.daten_version()
        if not self._vorschlaege or self._vorschlaege[0] != schluessel or time.monotonic() - self._vorschlaege[1] > 30:
            self._vorschlaege = (schluessel, time.monotonic(), pruefe_dubletten(self.db))
        return self._vorschlaege[2]

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


def fahrzeug_kurz(z: dict, team: dict | None = None) -> dict:
    a, b = z["a"], z["b"]
    return {"id": a["id"], "fahrzeug": a["fahrzeug"], "titel": a["titel"], "ort": a.get("ort"), "url": a["url"],
            "quelle": a.get("quelle") or "kleinanzeigen",
            "bild": a.get("bild"), "ez_jahr": a.get("ez_jahr"), "km": a.get("km"), "preis": a.get("preis"),
            "entfernung_km": a.get("entfernung_km"), "tage_online": a.get("tage_online"), "status": a.get("status") or "neu",
            "ampel": b.ampel, "erstangebot": b.erstangebot if b.sicherheit != "keine" else None,
            "brief_betrag": z.get("brief_betrag"),
            "max_ek": b.max_ek if b.sicherheit != "keine" else None, "bereit": z["bereit"], "nachfassen": z["nachfassen"],
            # Spannen und Mängelliste (P5-03): Max-EK von–bis (500 €), im Inserat genannte Mängel [{name, wert}]
            "max_ek_von": b.max_ek_von if b.sicherheit != "keine" else None, "max_ek_bis": b.max_ek_bis if b.sicherheit != "keine" else None,
            "maengel": b.maengel,
            "sperre": z["sperre"], "hinweise": z["hinweise"], "neu": z["neu"], "team": team,
            # frisch / Preis deutlich gesenkt / jetzt im Rahmen (P4-03): {stufe, text, frisch, senkung, im_rahmen} oder None
            "neuigkeit": z.get("neuigkeit"),
            # Verfügbarkeit des Inserats (Markt), getrennt vom Ankaufsstatus; „vermutlich offline“ ist abgeleitet, nicht gespeichert (P3-04)
            "verfuegbarkeit": a.get("verfuegbarkeit") or "unbekannt", "zuletzt_bestaetigt": a.get("zuletzt_bestaetigt"),
            "vermutlich_offline": bool(a.get("vermutlich_offline")), "verfuegbarkeit_text": a.get("verfuegbarkeit_text"),
            # Anbieterart mit Herkunft der Einstufung (P3-05): {typ, herkunft, belegt, text}
            "anbieter": a.get("anbieter") or einstufung(a.get("gewerblich"), a.get("anbieter_herkunft")),
            # Datenqualität des Fahrzeugs (P3-08): {wert 0–100, stufe, markierungen[{code, art, text}], widersprueche} – nur Anzeige
            "datenqualitaet": a.get("datenqualitaet")}


def ics(b: dict, cfg: dict, link: str | None) -> str:
    start = datetime.fromisoformat(b["termin"])
    ende = start + timedelta(hours=1)

    def esc(t: str) -> str:
        return (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\r", "\n") \
            .replace("\n", "\\n")                         # nacktes \r (Q15) wie Zeilenumbruch behandeln

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


def _haendler_erlaubt(pfad: str) -> bool:
    return pfad in ("/", "/m", "/haendler", "/api/ich", "/api/logout", "/api/ereignisse") or pfad.startswith(("/api/haendler/", "/haendler-fotos/"))


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
        self.status: int | None = None   # gesendeter Status (Audit-Protokoll)
        self.puffer: tuple | None = None   # Antwort erst nach dem Audit-Eintrag senden (bearbeite)
        self.puffern = False
        self.audit_name: str | None = None

    # ----- Antworten
    def senden(self, status: int, body: bytes, typ: str, kopf: dict | None = None):
        self.status = status
        if self.puffern:
            self.puffer = (status, body, typ, kopf)
            return
        self.schreiben(status, body, typ, kopf)

    def schreiben(self, status: int, body: bytes, typ: str, kopf: dict | None = None):
        h = self.h
        h.send_response(status)
        h.send_header("Content-Type", typ)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        for k, v in {**SICHERHEITS_KOPF, **(kopf or {})}.items():
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
    def client_ip(self) -> str:
        """Absender; hinter einem ausdrücklich vertrauten Reverse-Proxy dessen letzter X-Forwarded-For-Eintrag."""
        weitergeleitet = self.h.headers.get("X-Forwarded-For")
        if self.k.vertrauter_proxy and weitergeleitet:
            return weitergeleitet.split(",")[-1].strip()
        return self.h.client_address[0]

    def pruefe_host(self):
        """Vor allem anderen (auch vor dem Lesen des Inhalts): nur freigegebene Hostnamen."""
        if (self.h.headers.get("Host") or "") not in self.k.erlaubte_hosts(self.h.server.server_address[1]):
            raise Antwort(403, "Dieser Hostname ist nicht freigegeben (config.yaml → app → oeffentliche_url)", grund="zugriff")

    def ist_lokal(self) -> bool:
        """Wirklich dieser Rechner: Host-Kopf UND Absender Loopback UND keine Proxy-Kopfzeilen – ein Reverse-Proxy mit
        Standard-Host (nginx ``proxy_pass http://127.0.0.1:8765``) macht so niemanden ohne Anmeldung zum Inhaber."""
        port = self.h.server.server_address[1]
        return (self.h.headers.get("Host") or "") in (f"127.0.0.1:{port}", f"localhost:{port}") \
            and self.h.client_address[0] in ("127.0.0.1", "::1") \
            and not any(self.h.headers.get(k) for k in ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded"))

    def pruefe_zugriff(self, aendernd: bool):
        self.pruefe_host()
        lokal = self.ist_lokal()
        team = self.k.team.hat_nutzer()
        if not team:
            if not lokal:
                raise Antwort(403, "Zugriff von außen erst, wenn Nutzer angelegt sind: python scout.py nutzer anlegen …", grund="zugriff")
            self.nutzer = {"id": None, "name": "lokal", "rolle": "inhaber", "telefon": None}
        else:
            self.nutzer = self.k.team.nutzer_zu_token(self.sitzung)
        if self.pfad in OFFENE_PFADE or self.pfad.startswith("/static/"):
            return
        if not self.nutzer:
            raise Antwort(401, "Bitte anmelden")
        if self.nutzer.get("rolle") == HAENDLER and not _haendler_erlaubt(self.pfad):
            # Positivliste (ADR-026): Standort-Zugänge sehen nie Ankaufsliste, Team, Besichtigungen oder Kontaktdaten
            raise Antwort(403, "Dieser Bereich ist für Standort-Zugänge nicht freigegeben", grund="recht")
        if aendernd and self.h.headers.get("X-Scout-Token") != self.k.token:
            raise Antwort(403, "Zugriff verweigert – Seite bitte neu laden", grund="csrf")

    @property
    def team_aktiv(self) -> bool:
        """Team-Funktionen gelten nur mit angelegten Nutzern (ohne: anonymer „lokal“-Nutzer ohne ID, alles wie bisher)."""
        return bool(self.nutzer) and self.nutzer["id"] is not None

    def team_sicht(self) -> TeamSicht | None:
        """Frischer Stand aus der Datenbank (zwei SELECTs) – nie aus dem 30-s-Zwischenspeicher der Bewertung."""
        return self.k.team.sicht(self.k.reservierung_tage, self.nutzer) if self.team_aktiv else None

    def jetzt_grenze(self) -> tuple[str, str]:
        jetzt = datetime.now()
        return jetzt.isoformat(timespec="seconds"), ablauf_grenze(jetzt, self.k.reservierung_tage)

    def team_parameter(self, daten: dict, anzeige_id: str) -> dict:
        """Zusätzliche Argumente für ``setze_status``/``nachgefasst`` im Team; ohne Team leer (= bisheriges Verhalten)."""
        if not self.team_aktiv:
            return {}
        erzwingen = self.erzwingen_gewuenscht(daten)
        _, grenze = self.jetzt_grenze()
        return {"nutzer_id": self.nutzer["id"], "grenze": grenze, "erzwingen": erzwingen,
                "dubletten": self.k.dubletten_von(anzeige_id), "inhaber": self.nutzer["rolle"] == "inhaber"}

    def erzwingen_gewuenscht(self, daten: dict) -> bool:
        """Nur das JSON-Literal ``true`` erzwingt (nicht "false", 1 oder "ja"); 403 für Nicht-Inhaber."""
        erzwingen = daten.get("erzwingen") is True
        if erzwingen and not darf_erzwingen(self.nutzer["rolle"]):
            raise Antwort(403, "Erzwingen ist dem Inhaber vorbehalten")
        return erzwingen

    def vorheriger_halter(self, anzeige_id: str, team: dict):
        """Wer hält das Inserat (oder eine Dublette) jetzt noch – nur bei Erzwingen gebraucht (für das Protokoll)."""
        return self.team_sicht().fremder_halter(anzeige_id, team["dubletten"]) if team.get("erzwingen") else None

    def logge_erzwingen(self, anzeige_id: str, vorher):
        """Erzwungene Übernahme ins Protokoll – nur, wenn sich der Halter tatsächlich geändert hat (``vorher`` = (Inserat, Nutzer) des
        bisherigen Halters, siehe ``vorheriger_halter``). Ein Statuswechsel ohne Übernahme (Besichtigung auf abgeschlossenem Inserat)
        ändert ihn nicht und wird deshalb nicht als „erzwungen“ gemeldet."""
        if not vorher:
            return
        sicht = self.team_sicht()
        if sicht.halter(vorher[0]) != vorher[1]:
            log.info("Erzwungene Übernahme: Anzeige %s von %s durch %s", anzeige_id, (sicht.person(vorher[1]) or {}).get("name"),
                     self.nutzer["name"])

    def konflikt(self, anzeige_id: str, dubletten=(), *, ziel_id: int | None = None, gruppe: bool = False) -> Antwort:
        """409 mit verständlichem Text und dem aktuellen Team-Stand des Inserats.

        ``gruppe``: Zuweisen/Erzwingen (an ``ziel_id``, sonst an den Anfragenden) scheiterte an einer bereits kontaktierten
        Dublette eines anderen – dann sagt der Text, wo zuerst zugewiesen werden muss."""
        sicht = self.team_sicht()
        status = self.k.db.status_von(anzeige_id)
        ziel = ziel_id if ziel_id is not None else self.nutzer["id"]
        if gruppe and sicht.kontaktierte_dublette(anzeige_id, dubletten, ziel):
            text = sicht.zuweisung_konflikt_text(anzeige_id, dubletten, ziel)
        else:
            text = sicht.konflikt_text(anzeige_id, dubletten)
        return Antwort(409, text, {"team": sicht.objekt_id(anzeige_id, status, dubletten)})

    def ist_inhaber_oder_bearbeiter(self, anzeige_id: str, sicht: TeamSicht | None = None) -> bool:
        """Inhaber oder wirksamer Bearbeiter des Inserats – nur sie dürfen im Team die Zuständigkeit für eine Besichtigung vergeben.
        Ohne Team (Einzelplatz, Nutzer „lokal“) immer ``True``. Wer das Inserat nicht hält (frei, abgelaufen, Kollege), darf sich
        nicht selbst eintragen: Die Ausnahme beim Abschluss (``b_abschluss``) beruht darauf, dass die Zuständigkeit legitim vergeben wurde."""
        if not self.team_aktiv or self.nutzer["rolle"] == "inhaber":
            return True
        if anzeige_id.startswith("anfrage-"):           # Besichtigung einer Verkaufsanfrage: deren Bearbeiter statt Inserats-Halter
            r = self.k.db.con.execute("SELECT bearbeiter_id FROM verkaufsanfragen WHERE id=?", (anzeige_id[8:],)).fetchone()
            return bool(r) and r[0] == self.nutzer["id"]
        sicht = sicht or self.team_sicht()
        return sicht.halter(anzeige_id) == self.nutzer["id"]

    def darf_besichtigung(self, b: dict, sicht: TeamSicht | None = None) -> bool:
        """Schreiben (planen, speichern, Foto, Abschluss): Inhaber, Bearbeiter des Inserats oder eingetragener Zuständiger. Eine
        Besichtigung ohne Zuständigen (Altbestand) auf einem Inserat, das ein Kollege hält, ist für Mitarbeiter nur lesbar."""
        return b["zustaendig_id"] == self.nutzer["id"] or self.ist_inhaber_oder_bearbeiter(b["anzeige_id"], sicht)

    def besichtigung(self, bid: str, schreiben: bool = False) -> dict:
        b = self.k.team.besichtigung(int(bid))
        if not b:
            raise Antwort(404, "Besichtigung nicht gefunden")
        if schreiben and not self.darf_besichtigung(b):
            raise Antwort(403, "Diese Besichtigung darf nur der Zuständige, der Bearbeiter des Inserats oder der Inhaber ändern")
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
            ziel = sicheres_ziel((self.query.get("weiter") or [None])[0])
            return self.html(k.env.get_template("login.html").render(firma=k.cfg["anschreiben"]["firma"], ziel=ziel))
        if p == "/einladung":                             # F4: Token steht im #-Teil des Links – er erreicht den Server nie per GET
            return self.html(k.env.get_template("einladung.html").render(firma=k.cfg["anschreiben"]["firma"]))
        if p in ("/zugaenge", "/api/zugaenge"):            # F4: Zugänge einladen, Händlerzugänge der Plattformen – nur der Inhaber
            self.nur_inhaber()
            if p == "/zugaenge":
                return self.html(k.env.get_template("zugaenge.html").render(firma=k.cfg["anschreiben"]["firma"], token=k.token,
                                                                            rollen={r: ROLLEN[r] for r in ("inhaber", "mitarbeiter")}))
            return self.json(200, {"plattformen": k.zugaenge.liste(), "nutzer": k.team.nutzer_liste(nur_aktive=False)})
        if self.nutzer.get("rolle") == HAENDLER and p in ("/", "/m"):
            return self.weiterleiten("/haendler")
        if p == "/":
            zeilen = k.zeilen()
            team = self.team_uebersicht() if self.team_aktiv else None
            html, _ = render_html(k.cfg, zeilen, k.basis, fehler=k.suchlauf.stand["fehler"], app={"token": k.token}, team=team)
            return self.html(html)
        if p == "/m":
            return self.html(k.env.get_template("mobil.html").render(firma=k.cfg["anschreiben"]["firma"]))
        if p == "/api/ich":
            return self.json(200, {"nutzer": self.ich_mit_kuerzel(), "csrf": k.token, "team": k.team.hat_nutzer(),
                                   "rollen": ROLLEN, "status": STATUS, "besichtigung_status": BESICHTIGUNG_STATUS,
                                   "firma": {x: k.cfg["anschreiben"].get(x) for x in
                                             ("firma", "ansprechpartner", "telefon", "ort")},
                                   "differenzbesteuerung": bool(k.cfg["rechner"]["differenzbesteuerung"])})
        if p == "/api/suchlauf":
            return self.json(200, k.suchlauf.stand)
        if p == "/api/nutzer":
            return self.json(200, k.team.nutzer_mit_kuerzel())
        if p == "/api/team":
            return self.json(200, self.team_uebersicht())
        if p == "/api/katalog":
            return self.json(200, k.katalog())
        if p == "/api/heute":
            return self.json(200, self.heute())
        if p == "/api/dubletten-vorschlaege":
            if self.nutzer.get("rolle") not in TEXT_IMPORT_ROLLEN:       # Inhaber und Mitarbeiter; Standort-Zugänge nie
                raise Antwort(403, "Nur für Inhaber und Mitarbeiter", grund="recht")
            limit = (self.query.get("limit") or [str(STANDARD_LIMIT)])[0]
            if not limit.isdigit() or not 1 <= int(limit) <= MAX_LIMIT:
                raise Antwort(400, f"limit muss zwischen 1 und {MAX_LIMIT} liegen")
            erg = k.dubletten_vorschlaege()
            darf = {"darf_bestaetigen": darf_bestaetigen(self.nutzer.get("rolle")), "darf_ablehnen": darf_ablehnen(self.nutzer.get("rolle"))}
            return self.json(200, {"vorschlaege": [{**v, **darf} for v in erg.vorschlaege[:int(limit)]], "anzahl": len(erg.vorschlaege), "limit": int(limit),
                                   "unvollstaendig": bool(erg.gekuerzt), "hinweis": erg.hinweis, "regel_version": REGEL_VERSION})
        if p == "/api/dubletten/entscheidungen":
            return self.json(200, self.dubletten_entscheidungen((self.query.get("anzeige") or [""])[0]))
        if p == "/api/preisverlauf":
            return self.json(200, self.preisverlauf_antwort((self.query.get("anzeige") or [""])[0], (self.query.get("umfang") or ["inserat"])[0]))
        if p == "/api/fahrzeuge":
            return self.json(200, self.fahrzeuge())
        if m := re.fullmatch(r"/api/fahrzeug/([\w-]+)", p):
            return self.json(200, self.fahrzeug(m.group(1)))
        if p == "/api/suchprofile":
            return self.json(200, self.suchprofile())
        if m := re.fullmatch(r"/api/suchprofil/([0-9]{1,9})/treffer", p):
            # Desktop-Filter: alle Treffer ohne die 200er-Grenze von /api/fahrzeuge (die Desktop-Liste zeigt alle Zeilen)
            if (profil := k.suchprofile.profil(int(m.group(1)))) is None:
                raise Antwort(404, "Suchprofil nicht gefunden")
            return self.json(200, {"treffer": self._profil_treffer(profil, k.zeilen())})
        if p == "/api/datenqualitaet":
            return self.json(200, {"quellen": je_quelle(k.zeilen())})
        if m := re.fullmatch(r"/api/kontakte/([\w-]+)", p):
            if k.db.status_von(m.group(1)) is None:
                raise Antwort(404, "Anzeige nicht gefunden")
            return self.json(200, self.kontakte(m.group(1)))
        if m := re.fullmatch(r"/api/besichtigung/(\d+)", p):
            b = self.besichtigung(m.group(1))
            # abgeschlossene Besichtigungen braucht niemand offline – nicht im Speicher des Geräts ablegen (P1-14b)
            return self.json(200, self.besichtigung_voll(b), {"X-Scout-Offline": "nein"} if b["status"] in ("abgeschlossen", "abgebrochen") else None)
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
        if p in ("/haendler", "/standorte"):
            if p == "/standorte":
                self.nur_inhaber()
            return self.html(k.env.get_template(p[1:] + ".html").render(
                firma=k.cfg["anschreiben"]["firma"], token=k.token, ich=self.nutzer, haendler=self.nutzer.get("rolle") == HAENDLER,
                standort=k.haendler.standort(self.nutzer.get("standort_id")), standort_status=STANDORT_STATUS))
        if p == "/api/haendler/fahrzeuge":
            return self.json(200, k.haendler.sichtbare(self.standort_freigeschaltet()))
        if p == "/api/haendler/auktionen":
            return self.json(200, k.auktion.fuer_standort(self.standort_freigeschaltet()))
        if m := re.fullmatch(r"/api/auktion/(\d+)", p):
            return self.json(200, {**k.auktion.lade(int(m.group(1))), "pruefung": k.auktion.pruefe_protokoll()})
        if m := re.fullmatch(r"/api/haendler/auktion/(\d+)/kalkulation", p):
            standort = self.standort_freigeschaltet()
            a = k.auktion.lade(int(m.group(1)))
            if a["status"] != "laeuft" or not k.haendler.sichtbar(a["anfrage_id"], standort):
                raise Antwort(404, "Auktion nicht (mehr) offen")
            e, erg = k.deal.berechne(a["anfrage_id"], self.betrag_aus_query(), standort)
            return self.json(200, {"ergebnis": erg, "eingabe_hash": kalk.eingabe_hash(e)[:12]})
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/kalkulation", p):
            standort = (self.query.get("standort") or ["0"])[0]
            if not standort.isdigit() or (int(standort) and not k.haendler.standort(int(standort))):
                raise Antwort(400, "Standort ungültig")
            try:
                e, erg = k.deal.berechne(int(m.group(1)), self.betrag_aus_query(), int(standort))
            except LookupError as fehler:
                raise Antwort(404, str(fehler)) from fehler
            return self.json(200, {"ergebnis": erg, "eingabe_hash": kalk.eingabe_hash(e)[:12]})
        if p == "/api/status":                             # Statusseite (P4-04): Quellen, Eingänge, Läufe, Fehler – ohne Personendaten
            return self.json(200, {**lp.uebersicht(k.db, k.cfg), "suchlauf": k.suchlauf.stand})
        if p in ("/api/abdeckung", "/abdeckung"):           # Abdeckung und Suchlücken (P4-05): nur lesen, ohne Personendaten
            try:
                tage = abdeckung.tage_aus((self.query.get("tage") or [""])[0], abdeckung.MAX_TAGE_APP)
            except ValueError as e:
                raise Antwort(400, str(e)) from e
            erg = k.abdeckung(tage)
            if p == "/api/abdeckung":
                return self.json(200, erg)
            return self.html(k.env.get_template("abdeckung.html").render(firma=k.cfg["anschreiben"]["firma"], m=erg))
        if p in ("/api/kalibrierung", "/kalibrierung"):     # Kalibrierung (P5-01): Kaufpreise und Vorschläge – im Team nur der Inhaber
            if self.team_aktiv:
                self.nur_inhaber()
            if p == "/kalibrierung":
                return self.html(k.env.get_template("kalibrierung.html").render(
                    firma=k.cfg["anschreiben"]["firma"], token=k.token, arten=kal.ARTEN, min_faelle=kal.MIN_FAELLE))
            faelle = k.kalibrierung.faelle(k.cfg)
            return self.json(200, {"bericht": kal.bericht(faelle, k.cfg), "faelle": faelle, "manuelle": k.kalibrierung.manuelle(),
                                   "markt": k.kalibrierung.marktbeobachtung(k.cfg)})
        if p == "/status":
            return self.html(k.env.get_template("status.html").render(
                firma=k.cfg["anschreiben"]["firma"], s=lp.uebersicht(k.db, k.cfg), suchlauf=k.suchlauf.stand, arten=lp.ARTEN,
                ausloeser=lp.AUSLOESER, ergebnisse=lp.ERGEBNISSE))
        if p == "/ankaeufe":
            return self.html(k.env.get_template("ankaeufe.html").render(
                firma=k.cfg["anschreiben"]["firma"], token=k.token, ich=self.nutzer, kostenarten=KOSTENARTEN, status=ANKAUF_STATUS,
                dokumentarten=DOKUMENTARTEN))
        if p == "/api/ankaeufe":
            return self.json(200, k.ankauf.liste())
        if m := re.fullmatch(r"/api/ankauf/(\d+)", p):
            return self.json(200, k.ankauf.lade(int(m.group(1))))
        if m := re.fullmatch(r"/ankauf/(\d+)/vertrag", p):
            a = k.ankauf.lade(int(m.group(1)))
            b = k.team.besichtigung(a["besichtigung_id"])
            e = b["ergebnis"] or berechne(k.katalog(), b["daten"] or {}, b["basis"])
            return self.html(k.env.get_template("vertrag.html").render(a=a, b=b, e=e, d=b["daten"] or {}, firma=k.cfg["anschreiben"],
                                                                         jetzt=datetime.now()))
        if m := re.fullmatch(r"/ankauf-dokumente/(\d+)/([\w.-]+)", p):
            pfad = k.ankauf.dokument_pfad(int(m.group(1)), m.group(2))
            if not pfad:
                raise Antwort(404, "Dokument nicht gefunden")
            # Hochgeladene Dateien nie als aktive Seite der App: PDF nur als Download, alles in einer Sandbox (G0b)
            kopf = {"Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'"}
            if pfad.suffix.lower() == ".pdf":
                kopf["Content-Disposition"] = f'attachment; filename="{pfad.name}"'
            return self.senden(200, pfad.read_bytes(), mimetypes.guess_type(pfad.name)[0] or "application/octet-stream", kopf)
        if p == "/api/nutzung":
            self.nur_inhaber()
            try:
                return self.json(200, nutzung(k.db, (self.query.get("monat") or [None])[0]))
            except ValueError as e:
                raise Antwort(400, str(e)) from e
        if p == "/api/audit":
            self.nur_inhaber()
            q = {k2: (v[0] if v else None) for k2, v in self.query.items()}
            try:
                tage, limit = int(q.get("tage") or 30), int(q.get("limit") or 500)
            except ValueError as e:
                raise Antwort(400, "tage und limit müssen Zahlen sein") from e
            return self.json(200, k.audit.liste(tage=tage, nutzer=q.get("nutzer"), objekt=q.get("objekt"), limit=limit))
        if m := re.fullmatch(r"/api/kalkulation/(\d+)", p):
            x = k.deal.lade(int(m.group(1)))
            if not x:
                raise Antwort(404, "Kalkulation nicht gefunden")
            return self.json(200, x)
        if m := re.fullmatch(r"/api/haendler/fahrzeug/(\d+)", p):
            f = k.haendler.sichtbar(int(m.group(1)), self.standort_freigeschaltet())
            if not f:
                raise Antwort(404, "Nicht (mehr) freigegeben")
            return self.json(200, f)
        if m := re.fullmatch(r"/haendler-fotos/(\d+)/([\w.-]+)", p):
            f = k.haendler.sichtbar(int(m.group(1)), self.standort_freigeschaltet())
            pfad = k.verkauf.foto_pfad(int(m.group(1)), m.group(2)) if f and m.group(2) in f["fotos"] else None
            if not pfad:
                raise Antwort(404, "Foto nicht gefunden")
            return self.senden(200, pfad.read_bytes(), mimetypes.guess_type(pfad.name)[0] or "image/jpeg")
        if p == "/api/standorte":
            self.nur_inhaber()
            return self.json(200, {"standorte": k.haendler.standorte(),
                                   "nutzer": [n for n in k.team.nutzer_liste(nur_aktive=False, auch_haendler=True) if n["rolle"] == HAENDLER]})
        if p in ("/verkaufen", "/anfragen"):
            return self.html(k.env.get_template(p[1:] + ".html").render(
                firma=k.cfg["anschreiben"]["firma"], token=k.token, arten=vk.ARTEN, maengel=vk.MAENGEL, kanaele=vk.KANAELE,
                status=vk.STATUS, ich=self.nutzer, team=self.team_aktiv))
        if p == "/api/verkaufsanfragen":
            return self.json(200, self.verkaufsanfragen())
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)", p):
            return self.json(200, self.verkaufsanfrage(int(m.group(1))))
        if m := re.fullmatch(r"/anfrage-fotos/(\d+)/([\w.-]+)", p):
            pfad = k.verkauf.foto_pfad(int(m.group(1)), m.group(2))
            if not pfad:
                raise Antwort(404, "Foto nicht gefunden")
            return self.senden(200, pfad.read_bytes(), mimetypes.guess_type(pfad.name)[0] or "image/jpeg")
        raise Antwort(404, "nicht gefunden")

    # ----- Besichtigung und Abwicklung (Phase F)
    def anfrage_besichtigung(self, anfrage_id: int, daten: dict) -> dict:
        """Handy-Besichtigung für eine offene Verkaufsanfrage – anlegen dürfen Inhaber und Bearbeiter der Anfrage (wie bei Inseraten
        der Halter). Je Anfrage höchstens eine offene Besichtigung."""
        k = self.k
        a = k.verkauf.lade(anfrage_id)
        if not a:
            raise Antwort(404, "Anfrage nicht gefunden")
        if a["status"] not in vk.OFFEN:
            raise Antwort(409, f"Anfrage ist „{vk.STATUS[a['status']]}“ – Besichtigung nur für offene Anfragen")
        if not self.ist_inhaber_oder_bearbeiter(f"anfrage-{anfrage_id}"):
            raise Antwort(403, "Besichtigungen einer Anfrage planen nur ihr Bearbeiter oder der Inhaber – bitte zuerst übernehmen")
        termin, adresse = self._termin(daten.get("termin")), (daten.get("adresse") or "").strip()[:200] or None
        zustaendig = self._zustaendig(daten.get("zustaendig_id"))
        try:
            basis = k.ankauf.basis_fuer_anfrage(anfrage_id)
        except AnkaufFehler as e:
            raise Antwort(e.status, str(e)) from e
        with k.db.transaktion():
            if k.db.con.execute("SELECT 1 FROM besichtigungen WHERE anfrage_id=? AND status IN ('geplant', 'laeuft')", (anfrage_id,)).fetchone():
                raise Antwort(409, "Für diese Anfrage ist schon eine Besichtigung geplant")
            bid = k.team.besichtigung_anlegen(f"anfrage-{anfrage_id}", basis, termin, adresse, zustaendig, self.nutzer["id"], anfrage_id)
            k.verkauf._verlauf(anfrage_id, self.nutzer["id"], "besichtigung", None, f"#{bid} geplant")
        b = k.team.besichtigung(bid)
        self._zuweisung_melden(b)
        return self.besichtigung_kurz(b)

    def darf_ankauf(self, a: dict) -> bool:
        """Schritte eines Vorgangs (Vertrag, Übergabe, Kosten, Verkauf, Dokumente): Inhaber, Zuständiger der Besichtigung oder
        Bearbeiter der Anfrage bzw. des Inserats (G0b) – wie beim Schreiben der Besichtigung selbst."""
        b = self.k.team.besichtigung(a["besichtigung_id"])
        return bool(b) and self.darf_besichtigung(b)

    def ankauf_schritt(self, aid: int, art: str, daten: dict) -> dict:
        k, nid = self.k, self.nutzer["id"]
        if not self.darf_ankauf(k.ankauf.lade(aid)):      # AnkaufFehler 404, wenn es den Vorgang nicht gibt
            raise Antwort(403, "Diesen Ankauf bearbeiten nur der Zuständige der Besichtigung, der Bearbeiter oder der Inhaber",
                          grund="recht")
        if art == "vertrag":
            k.ankauf.vertrag_bestaetigen(aid, nid)
        elif art == "uebergabe":
            k.ankauf.uebergabe(aid, daten.get("uebergabe_am"), daten.get("zahlung_am"), daten.get("km"), nid)
        elif art == "kosten":
            return {"id": k.ankauf.kosten_erfassen(aid, str(daten.get("art") or ""), daten.get("betrag"), daten.get("notiz"),
                                                  daten.get("datum"), nid)}
        elif art == "verkauf":
            k.ankauf.verkaufen(aid, daten.get("vk_preis"), daten.get("verkauft_am"), nid)
        elif art == "storno":
            self.nur_inhaber()
            k.ankauf.stornieren(aid, str(daten.get("grund") or ""), nid)
        else:
            return k.ankauf.dokument_speichern(aid, str(daten.get("art") or ""), _bild_bytes(str(daten.get("datei") or "")), nid)
        log.info("Ankauf %s: %s durch %s", aid, art, self.nutzer["name"])
        return {"ok": True}

    def anfrage_widerruf(self, anfrage_id: int) -> dict:
        """Widerruf der Einwilligung (G0, ``datenrechte.widerruf``) – nur der Inhaber."""
        try:
            erg = datenrechte.widerruf(self.k.db, self.k.cfg, self.k.verkauf.foto_ordner.parent, anfrage_id, self.nutzer["id"])
        except LookupError as e:
            raise Antwort(404, str(e)) from e
        except ValueError as e:
            raise Antwort(409, str(e)) from e
        log.info("Widerruf für Anfrage %s ausgeführt durch %s", anfrage_id, self.nutzer["name"])
        return {"ok": True, **erg}

    # ----- Einladungen und Händlerzugänge (F4, ADR-059)
    def nutzer_einladen(self, daten: dict) -> dict:
        """Team-Zugang (Inhaber oder Mitarbeiter) anlegen oder erneut einladen; der Link geht nur an den Inhaber zurück, der ihn weitergibt."""
        name, rolle = str(daten.get("name") or "").strip()[:60], str(daten.get("rolle") or "mitarbeiter")
        telefon = str(daten.get("telefon") or "").strip()[:40] or None
        if not name:
            raise Antwort(400, "Name fehlt")
        if rolle not in ("inhaber", "mitarbeiter"):
            raise Antwort(400, "Rolle: Inhaber oder Mitarbeiter (Standort-Zugänge über die Kommandozeile mit --standort)")
        erster = not self.team_aktiv                        # Einzelplatz ohne Nutzer: danach ist eine Anmeldung nötig (QA B1)
        try:
            _, token, rolle = self.k.team.einladen(name, rolle, telefon, erstellt_von=self.nutzer["id"], erneut=daten.get("erneut") is True)
        except ZugangVorhanden as e:
            raise Antwort(409, str(e), {"vorhanden": True}) from e
        except ValueError as e:
            raise Antwort(400, str(e)) from e
        https = self.k.nur_https or (self.k.vertrauter_proxy and self.h.headers.get("X-Forwarded-Proto") == "https")
        basis = self.k.app_link("") or f"{'https' if https else 'http'}://{self.h.headers.get('Host') or '127.0.0.1'}"
        hinweise = []
        if erster:
            hinweise.append("Ab jetzt ist für die App eine Anmeldung nötig – den Link jetzt selbst öffnen (oder sicher weitergeben) und das "
                            "Passwort setzen, sonst bleibt nur die Kommandozeile.")
        if not self.k.app_link(""):
            hinweise.append("Ohne öffentliche Adresse (config.yaml → app → oeffentliche_url) funktioniert der Link nur auf diesem Rechner.")
        log.info("Einladung für %s angelegt durch %s", name, self.nutzer.get("name"))
        return {"name": name, "rolle": ROLLEN.get(rolle, rolle), "link": f"{basis}/einladung#{token}", "gueltig_tage": EINLADUNG_TAGE,
                "erster_zugang": erster, "hinweise": hinweise}

    def _herkunft_pruefen(self, was: str):
        if not (self.h.headers.get("Content-Type") or "").startswith("application/json"):
            raise Antwort(415, f"{was} nur als JSON")
        if self.h.headers.get("Sec-Fetch-Site") == "cross-site":
            raise Antwort(403, f"{was} von fremden Seiten nicht erlaubt", grund="csrf")
        herkunft = self.h.headers.get("Origin")
        if herkunft and urlparse(herkunft).netloc not in self.k.erlaubte_hosts(self.h.server.server_address[1]):
            raise Antwort(403, f"{was} von fremden Seiten nicht erlaubt", grund="csrf")

    def _mit_sitzung(self, daten: dict, token: str):
        https = self.k.nur_https or (self.k.vertrauter_proxy and self.h.headers.get("X-Forwarded-Proto") == "https")
        return self.json(200, daten, {"Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                                                    f"Max-Age={30 * 86400}{'; Secure' if https else ''}"})

    def einladung_einloesen(self, daten: dict):
        """Passwort selbst setzen und gleich angemeldet sein (F4) – wie die Anmeldung: Bremse je IP, Hash ohne globale Sperre."""
        k = self.k
        self._herkunft_pruefen("Einladung")
        token, passwort, ip = str(daten.get("token") or "")[:100], str(daten.get("passwort") or ""), self.client_ip()
        if warten := k.bremse.wartezeit(ip, "(einladung)"):
            raise Antwort(429, f"Zu viele Fehlversuche – bitte in {max(1, warten // 60)} Minute(n) erneut versuchen", {"warten_sek": warten})
        if not 8 <= len(passwort) <= 200:
            raise Antwort(400, "Passwort: mindestens 8 Zeichen")
        with k.sperre:
            gueltig = k.team.einladung(token)
        if not gueltig:
            k.bremse.fehlschlag(ip, "(einladung)")
            raise Antwort(410, "Einladung ungültig, abgelaufen oder schon eingelöst – bitte eine neue anfordern")
        neu = hash_passwort(passwort)                                   # teuer – bewusst ohne Sperre
        with k.sperre:
            e = k.team.einladung_einloesen(token, neu)
            if not e:
                raise Antwort(410, "Einladung ungültig, abgelaufen oder schon eingelöst – bitte eine neue anfordern")
            sitzung = k.team.sitzung_anlegen(e["nutzer_id"])
        self.audit_name = e["name"]
        log.info("Einladung eingelöst: %s von %s", e["name"][:40], ip)
        return self._mit_sitzung({"ok": True, "name": e["name"]}, sitzung)

    def zugang_testen(self, plattform: str):
        """Verbindungstest (F4): Rechte und Daten unter der Sperre prüfen, die eine Anfrage an den Anbieter ohne Sperre, Ergebnis wieder
        unter der Sperre merken – ein langsamer Anbieter blockiert die App nicht."""
        k = self.k
        with k.sperre:
            self.pruefe_zugriff(aendernd=True)
            self.nur_inhaber()
            try:
                vorbereitet = k.zugaenge.test_vorbereiten(plattform)
            except LookupError as e:
                raise Antwort(404, str(e)) from e
            except ValueError as e:
                raise Antwort(400, str(e)) from e
        ergebnis = ZugangSpeicher.test_ausfuehren(vorbereitet)
        with k.sperre:
            k.zugaenge.test_merken(plattform, ergebnis)
        log.info("Verbindungstest %s durch %s: %s", ZUGANG_PLATTFORMEN[plattform]["name"], self.nutzer.get("name"), "ok" if ergebnis["ok"] else "Fehler")
        return self.json(200, ergebnis)

    # ----- Anmeldung (G0: Bremse je IP und Name, scrypt außerhalb der globalen Sperre, Herkunftsprüfung)
    def login(self, daten: dict):
        k = self.k
        self._herkunft_pruefen("Anmeldung")
        name, passwort, ip = str(daten.get("name") or "")[:100], str(daten.get("passwort") or ""), self.client_ip()
        self.audit_name = name
        warten = k.bremse.wartezeit(ip, name)
        if warten:
            log.warning("Anmeldung gebremst: %r von %s (%s s)", name[:40], ip, warten)
            raise Antwort(429, f"Zu viele Fehlversuche – bitte in {max(1, warten // 60)} Minute(n) erneut versuchen",
                          {"warten_sek": warten})
        with k.sperre:
            nid, gespeichert = k.team.login_daten(name)
        if not pruefe_passwort(passwort, gespeichert) or nid is None:      # teuer – bewusst ohne Sperre
            k.bremse.fehlschlag(ip, name)
            log.warning("Fehlgeschlagene Anmeldung: %r von %s", name[:40], ip)
            time.sleep(1)
            raise Antwort(401, "Name oder Passwort falsch")
        with k.sperre:
            token = k.team.sitzung_anlegen(nid)
        k.bremse.erfolg(ip, name)
        log.info("Anmeldung: %s von %s", name[:40], ip)
        return self._mit_sitzung({"ok": True}, token)

    # ----- Deal Intelligence (Phase E)
    def betrag_aus_query(self) -> int | None:
        wert = ((self.query.get("betrag") or [""])[0]).strip()
        if not wert:
            return None
        if not wert.isdigit() or not 0 < int(wert) <= 10_000_000:
            raise Antwort(400, "Betrag muss ein ganzer Euro-Betrag sein")
        return int(wert)

    def gebot_mit_kalkulation(self, auktion_id: int, standort: int, daten: dict) -> dict:
        """Gebot und die dabei gezeigte Kalkulation in EINER Transaktion: jedes angenommene Gebot hat seine nachrechenbare Kalkulation.
        Die Kalkulation wird vorher (ohne Schreibsperre) gerechnet; scheitert sie, zählt das Gebot trotzdem (Protokoll im Log)."""
        k, betrag = self.k, daten.get("betrag")
        anfrage_id = k.auktion.lade(auktion_id)["anfrage_id"]           # AuktionsFehler 404, wenn es die Auktion nicht gibt
        kalkulation = None
        if isinstance(betrag, int) and not isinstance(betrag, bool) and 0 < betrag <= 10_000_000:
            try:
                kalkulation = k.deal.berechne(anfrage_id, betrag, standort)
            except Exception:  # noqa: BLE001 – die Kalkulation ist Hilfe, kein Teil der Gebotsregeln
                log.exception("Kalkulation zum Gebot auf Auktion %s fehlgeschlagen", auktion_id)
        with k.db.transaktion():
            erg = k.auktion.gebot_abgeben(auktion_id, standort, self.nutzer["id"], betrag, daten.get("wiederholungs_id"))
            if not erg["wiederholt"] and kalkulation:
                erg["kalkulation_id"] = k.deal.speichern(*kalkulation, anlass="gebot", anfrage_id=anfrage_id, auktion_id=auktion_id,
                                                         gebot_id=erg["gebot_id"], standort_id=standort, nutzer_id=self.nutzer["id"])
        return erg

    # ----- Händlerportal (Phase C)
    def nur_inhaber(self):
        if self.nutzer.get("rolle") != "inhaber":
            raise Antwort(403, "Nur für den Inhaber", grund="recht")

    def standort_freigeschaltet(self) -> int:
        """Standort-ID eines Händler-Zugangs – nur, wenn der Standort geprüft ist (bei JEDER Anfrage neu, Sperre wirkt sofort).
        Team-Mitglieder bekommen die Vorschau (0 = kein Standort, kein Interesse)."""
        if self.nutzer.get("rolle") != HAENDLER:
            return 0
        if not self.k.haendler.ist_freigeschaltet(self.nutzer):
            raise Antwort(403, "Ihr Standort ist noch nicht geprüft oder gesperrt – Zugang erst nach Prüfung durch den Inhaber", grund="recht")
        return self.nutzer["standort_id"]

    # ----- Verkäuferportal (Phase B)
    def _bewertung_kurz(self, b) -> dict:
        keine = b.sicherheit == "keine"
        return {"ampel": b.ampel, "sicherheit": b.sicherheit, "marktwert": None if keine else b.marktwert_angebote,
                "max_ek": None if keine else b.max_ek, "erstangebot": None if keine else b.erstangebot,
                "spanne_von": b.spanne_von, "spanne_bis": b.spanne_bis, "art": b.art, "abschlag_marke": b.abschlag_marke}

    def _nutzer_namen(self) -> dict:
        return {n["id"]: n["name"] for n in self.k.team.nutzer_mit_kuerzel(False)} if self.team_aktiv else {}

    def verkaufsanfragen(self) -> list[dict]:
        k = self.k
        status = (self.query.get("status") or [None])[0] or None
        try:
            liste = k.verkauf.liste(status)
        except ValueError as e:
            raise Antwort(400, str(e)) from e
        vergleich, rechner, namen = vk.vergleich_aus(k.db), vk.Rechner(k.cfg), self._nutzer_namen()
        return [{**{x: a[x] for x in ("id", "referenz", "kanal", "art", "marke", "modell", "ez_jahr", "km", "preisvorstellung",
                                         "status", "erstellt_am", "name", "plz", "ort", "fotos_anzahl", "bearbeiter_id")},
                 "bearbeiter": namen.get(a["bearbeiter_id"]), "bewertung": self._bewertung_kurz(vk.bewerte(k.cfg, a, vergleich, rechner))}
                for a in liste]

    def verkaufsanfrage(self, anfrage_id: int) -> dict:
        k = self.k
        a = k.verkauf.lade(anfrage_id)
        if not a:
            raise Antwort(404, "Anfrage nicht gefunden")
        b = vk.bewerte(k.cfg, a, vk.vergleich_aus(k.db))
        namen = self._nutzer_namen()
        a["maengel"] = [{"key": m, "text": vk.MAENGEL.get(m, m)} for m in json.loads(a["maengel"] or "[]")]
        a["bearbeiter"] = namen.get(a["bearbeiter_id"])
        for v in a["verlauf"]:
            v["nutzer"] = namen.get(v["nutzer_id"])
        return {**a, "bewertung": {**bewertung_json(b), **self._bewertung_kurz(b)}, "spanne_verkaeufer": vk.spanne_fuer_verkaeufer(b, k.cfg),
                "interessen": k.verkauf.interessen(anfrage_id), "auktionen": k.auktion.fuer_anfrage(anfrage_id),
                "kalkulationen": k.deal.liste(anfrage_id), "ankaeufe": k.ankauf.zu_anfrage(anfrage_id),
                "besichtigungen": [self.besichtigung_kurz(b) for b in k.team.besichtigungen(offen=False, anzeige_id=f"anfrage-{anfrage_id}")]}

    def ich_mit_kuerzel(self) -> dict:
        if not self.team_aktiv:
            return {**self.nutzer, "kuerzel": None}
        return {**self.nutzer, "kuerzel": next((n["kuerzel"] for n in self.k.team.nutzer_mit_kuerzel(False)
                                                if n["id"] == self.nutzer["id"]), None)}

    def team_uebersicht(self) -> dict:
        """Wer arbeitet woran? ``bearbeitung`` enthält nur Inserate mit Zustand ≠ frei oder mit belegter Dublette
        (fehlende Einträge = frei). Zähler und Zustände kommen aus demselben Stand."""
        k, sicht = self.k, self.team_sicht()
        stand = datetime.now().isoformat(timespec="seconds")
        if not sicht:
            return {"aktiv": False, "ich": None, "nutzer": [], "zaehler": [], "ohne_zuordnung": 0, "verwaist": 0, "bearbeitung": {},
                    "reservierung_tage": k.reservierung_tage, "stand": stand}
        zaehler = k.db.team_zaehler(sicht.jetzt, sicht.grenze)
        # Leistungszähler sind personenbezogen: Mitarbeiter sehen nur die eigene Zeile, der Inhaber alle. Die Bearbeiter-Kürzel an den
        # Fahrzeugen (``bearbeitung``) bleiben für alle sichtbar – sie verhindern den Doppelkontakt.
        sichtbar = [z for z in zaehler["nutzer"] if self.nutzer["rolle"] == "inhaber" or z["nutzer_id"] == self.nutzer["id"]]
        nutzer = [{"id": n["id"], "name": n["name"], "kuerzel": sicht.kuerzel[n["id"]], "aktiv": bool(n["aktiv"]), "rolle": n["rolle"]}
                  for n in sicht.nutzer.values()]
        # ``status`` (additiv): Oberflächen zeigen damit Statuswechsel der Kollegen ohne Neuladen
        objekte = {z["a"]["id"]: {**sicht.objekt(z), "status": z["a"].get("status") or "neu"} for z in k.zeilen()}
        return {"aktiv": True, "ich": {**sicht.person(self.nutzer["id"]), "rolle": self.nutzer["rolle"]},
                "nutzer": nutzer,
                "zaehler": [{**z, "kuerzel": sicht.kuerzel[z["nutzer_id"]]} for z in sichtbar],
                "ohne_zuordnung": zaehler["ohne_zuordnung"], "verwaist": zaehler["verwaist"],
                "bearbeitung": {i: o for i, o in objekte.items() if not sicht.ist_triviale_sicht(o)},
                "reservierung_tage": k.reservierung_tage, "stand": stand}

    def heute(self) -> dict:
        k, ich = self.k, self.nutzer
        eigene = ich["rolle"] != "inhaber" and ich["id"]
        termine = k.team.besichtigungen(zustaendig_id=ich["id"] if eigene else None)
        zeilen = k.zeilen()
        sicht = self.team_sicht()
        teams = [(z, sicht.objekt(z)) for z in zeilen] if sicht else []
        return {
            "meine": sum(1 for z, t in teams if t["mein"] and (z["a"].get("status") or "neu") in OFFEN) if sicht else None,
            "frei_bereit": sum(1 for z, t in teams if z["bereit"] and (z["a"].get("status") or "neu") == "neu"
                               and sicht.ist_frei(t)) if sicht else None,
            "termine": [self.besichtigung_kurz(b, sicht) for b in termine],
            "bereit": sum(1 for z in zeilen if z["bereit"] and (z["a"].get("status") or "neu") == "neu"),
            "nachfassen": sum(1 for z in zeilen if z["nachfassen"]),
            "arbeit": sum(1 for z in zeilen if z["a"].get("status") in IN_ARBEIT),
            "neuigkeiten": sum(1 for z in zeilen if z.get("neuigkeit")),
            "suchlauf": k.suchlauf.stand,
        }

    # ---------------------------------------------------------------- Suchprofile (P4-01)
    def _profil_treffer(self, profil: dict, zeilen: list[dict]) -> dict[str, str]:
        """Anzeigen-ID → „passt“/„unklar“ für alle eingegangenen Inserate, die zum Profil passen (könnten)."""
        erg = {}
        for z in zeilen:
            urteil, _ = sp.pruefe_inserat(profil, z["a"], z["b"].art)
            if urteil != sp.NEIN:
                erg[z["a"]["id"]] = urteil
        return erg

    def suchprofile(self) -> dict:
        """Alle Profile mit Trefferzahlen (ohne ausgeblendete Inserate) und Abdeckungscheckliste je Plattform."""
        k, jetzt = self.k, datetime.now()
        zeilen = [z for z in k.zeilen() if not z["ausblenden"]]
        nach_id = {z["a"]["id"]: z for z in zeilen}
        profile = []
        for p in k.suchprofile.liste():
            treffer = self._profil_treffer(p, zeilen)
            letzte: dict[str, str | None] = {}
            for ad_id in (i for i, u in treffer.items() if u == sp.PASST):       # „letzter passender Treffer“: nur sicher passende
                a = nach_id[ad_id]["a"]
                quelle = a.get("quelle") or "kleinanzeigen"
                letzte[quelle] = max(letzte.get(quelle) or "", a.get("erstmals_gesehen") or "") or None
            profile.append({**p, "gebiet_text": sp.gebiet_text(p),
                            "treffer": {"passt": sum(v == sp.PASST for v in treffer.values()), "unklar": sum(v == sp.UNKLAR for v in treffer.values())},
                            "abdeckung": sp.abdeckung(p, k.suchprofile.auftraege(p["id"]), letzte, jetzt)})
        return {"profile": profile, "arten": list(sp.ARTEN), "plattformen": list(PLATTFORMEN), "mit_eingang": list(sp.MIT_EINGANG),
                "gebiete": list(sp.GEBIETE), "standort_plz": str(k.cfg["anschreiben"].get("plz") or "") or None,
                "darf_aendern": not self.team_aktiv or self.nutzer.get("rolle") == "inhaber"}

    def suchprofil_aendern(self, pfad: str, daten: dict) -> dict:
        """Anlegen, Ändern, Löschen, Checkliste – im Team nur der Inhaber (wie Suchläufe, P1-15); protokolliert (Audit)."""
        k = self.k
        if self.team_aktiv:
            self.nur_inhaber()
        try:
            if pfad == "/api/suchprofile":
                return {"ok": True, "id": k.suchprofile.anlegen(sp.pruefe_profil(daten, datetime.now()))}
            profil_id = int(pfad.split("/")[3])
            if k.suchprofile.profil(profil_id) is None:
                raise Antwort(404, "Suchprofil nicht gefunden")
            if pfad.endswith("/loeschen"):
                k.suchprofile.loeschen(profil_id)
            elif pfad.endswith("/auftrag"):
                k.suchprofile.setze_auftrag(profil_id, sp.pruefe_auftrag(daten))
            else:
                k.suchprofile.aendern(profil_id, sp.pruefe_profil(daten, datetime.now()))
        except sp.Eingabefehler as e:
            raise Antwort(400, str(e)) from e
        return {"ok": True, "id": profil_id}

    def kalibrierung_aendern(self, pfad: str, daten: dict) -> dict:
        """Manuellen Kalibrierungsfall anlegen oder löschen – im Team nur der Inhaber; protokolliert (Audit). Ändert keine Parameter."""
        k = self.k
        if self.team_aktiv:
            self.nur_inhaber()
        if pfad == "/api/kalibrierung":
            try:
                f = kal.pruefe_fall(daten, datetime.now().date())
            except kal.Eingabefehler as e:
                raise Antwort(400, str(e)) from e
            return {"ok": True, "id": k.kalibrierung.anlegen(f, self.nutzer.get("id"))}
        fall_id = int(pfad.split("/")[3])
        if not k.kalibrierung.loeschen(fall_id):
            raise Antwort(404, "Fall nicht gefunden")
        return {"ok": True, "id": fall_id}

    def fahrzeuge(self) -> list[dict]:
        f = (self.query.get("filter") or ["bereit"])[0]
        q = (self.query.get("q") or [""])[0].lower().split()
        wer = (self.query.get("wer") or ["alle"])[0]
        if wer not in ("alle", "meine", "frei"):
            raise Antwort(400, "wer muss alle, meine oder frei sein")
        verfuegbar = (self.query.get("verfuegbar") or ["standard"])[0]
        if verfuegbar not in ("standard", "alle", "nur"):
            raise Antwort(400, "verfuegbar muss standard, alle oder nur sein")
        sicht = self.team_sicht()
        if wer != "alle" and not sicht:
            raise Antwort(400, "Team nicht aktiv (keine Nutzer angelegt) – „wer“ gibt es nur im Team")
        profil_treffer = None
        if (profil_param := (self.query.get("profil") or [""])[0]):          # Suchprofil als Filter über eingegangene Daten (P4-01)
            profil = self.k.suchprofile.profil(int(profil_param)) if re.fullmatch(r"[0-9]{1,9}", profil_param) else None
            if profil is None:
                raise Antwort(400, "profil: unbekanntes Suchprofil")
            profil_treffer = self._profil_treffer(profil, self.k.zeilen())
            if (self.query.get("unklar") or ["ja"])[0] == "nein":
                profil_treffer = {i: u for i, u in profil_treffer.items() if u == sp.PASST}
        auswahl = []
        for z in self.k.zeilen():
            if profil_treffer is not None and z["a"]["id"] not in profil_treffer:
                continue
            # standard: verkaufte/offline Anzeigen ohne Ankaufsarbeit ausgeblendet; nur: alle nicht verfügbaren; alle: nichts ausgeblendet
            if (verfuegbar == "standard" and z["ausblenden"]) or (verfuegbar == "nur" and z["a"].get("nicht_verfuegbar")):
                continue
            s = z["a"].get("status") or "neu"
            t = sicht.objekt(z) if sicht else None
            if (wer == "meine" and not t["mein"]) or (wer == "frei" and not sicht.ist_frei(t)):
                continue
            # „Text kopiert“ bleibt unter „Anschreiben bereit“, bis „gesendet ✓“ bestätigt ist (ADR-012)
            ok = {"bereit": (z["bereit"] and s == "neu") or s == VORBEREITET, "nachfassen": bool(z["nachfassen"]),
                  "arbeit": s in IN_ARBEIT, "offen": s in OFFEN, "alle": True, "neuigkeiten": bool(z.get("neuigkeit"))}.get(f, False)
            text = f"{z['a']['fahrzeug']} {z['a']['titel']} {z['a'].get('ort') or ''}".lower()
            if ok and all(w in text for w in q):
                auswahl.append((z, t))
        auswahl.sort(key=lambda zt: zt[0]["b"].verhaeltnis or 99)
        if f == "neuigkeiten":                              # wichtigste zuerst: jetzt im Rahmen, neu und bereit, gesenkt, neu (P4-03)
            auswahl.sort(key=lambda zt: zt[0]["neuigkeit"]["stufe"])
        if profil_treffer is not None:
            return [{**fahrzeug_kurz(z, t), "profil_treffer": profil_treffer[z["a"]["id"]]} for z, t in auswahl[:200]]
        return [fahrzeug_kurz(z, t) for z, t in auswahl[:200]]

    def fahrzeug(self, anzeige_id: str) -> dict:
        z = self.k.zeile(anzeige_id)
        sicht = self.team_sicht()
        return {**fahrzeug_kurz(z, sicht.objekt(z) if sicht else None), "bewertung": bewertung_json(z["b"]), "brief": z["brief"],
                "nachfass_text": z["nachfass_text"],
                "nachfass_betrag": z["nachfass_betrag"], "anschreiben_text": z["a"].get("anschreiben_text"),
                "notiz": z["a"].get("notiz"), "besichtigungen": [self.besichtigung_kurz(b, sicht) for b in
                                                                 self.k.team.besichtigungen(offen=False, anzeige_id=anzeige_id)],
                "verfuegbarkeit_fahrzeug": self.verfuegbarkeit_fahrzeug(anzeige_id), "kontakte": self.kontakte(anzeige_id)}

    def kontakte(self, anzeige_id: str) -> list[dict]:
        """Kontaktverlauf der Anzeige und ihres Fahrzeugs (P3-06): vorbereitete und bestätigte Anschreiben und Nachfassen, älteste zuerst."""
        namen = {n["id"]: n["name"] for n in self.k.team.nutzer_liste(nur_aktive=False)} if self.team_aktiv else {}
        return [kontakte.als_json(z, namen) for z in self.k.db.kontakte_zu(anzeige_id)]

    @staticmethod
    def kanal(daten: dict) -> str | None:
        try:
            return kontakte.pruefe_kanal(daten.get("kanal"))
        except ValueError as e:
            raise Antwort(400, str(e)) from e

    def kontakt_bestaetigen(self, kontakt_id: int, kanal: str | None, daten: dict) -> dict:
        """„gesendet ✓“ für ein vorbereitetes Nachfassen. Das Anschreiben bestätigt „gesendet ✓“ über den Status (Reservierung, ADR-012).
        Im Team: wer es vorbereitet hat oder der Inhaber. War das Inserat noch nicht kontaktiert, ist es der erste Kontakt: dann über den Status
        „kontaktiert“ (Kontaktzeitpunkt, Team-Zuordnung, Konfliktprüfung wie bei „gesendet ✓“)."""
        k = self.k
        z = k.db.kontakt(kontakt_id)
        if z is None:
            raise Antwort(404, "Kontakt nicht gefunden")
        if z["art"] != kontakte.NACHFASSEN:
            raise Antwort(409, "Ein Anschreiben wird mit „gesendet ✓“ am Fahrzeug bestätigt")
        if self.team_aktiv and self.nutzer.get("rolle") != "inhaber" and z["nutzer_id"] not in (None, self.nutzer.get("id")):
            raise Antwort(403, "Nur wer das Nachfassen vorbereitet hat (oder der Inhaber) bestätigt es", grund="recht")
        if z["verworfen_am"]:
            raise Antwort(409, "Dieses Nachfassen wurde verworfen (nicht gesendet) – bitte neu kopieren")
        ad_id = z["anzeige_id"]
        erster = not z["bestaetigt_am"] and not k.db.con.execute("SELECT kontaktiert_am FROM anzeigen WHERE id=?", (ad_id,)).fetchone()[0]
        if erster:
            team = self.team_parameter(daten, ad_id)
            vorher = self.vorheriger_halter(ad_id, team)
            try:
                k.db.setze_status(ad_id, "kontaktiert", kanal=kanal, kontakt_id=kontakt_id, **team)
            except BearbeitungsKonflikt:
                raise self.konflikt(ad_id, team.get("dubletten", ()), gruppe=team.get("erzwingen")) from None
            self.logge_erzwingen(ad_id, vorher)
        else:
            k.db.bestaetige_kontakt(kontakt_id, self.nutzer.get("id") if self.team_aktiv else None, kanal)
        k.veraendert()
        namen = {n["id"]: n["name"] for n in k.team.nutzer_liste(nur_aktive=False)} if self.team_aktiv else {}
        return {"ok": True, "kontakt": kontakte.als_json(k.db.kontakt(kontakt_id), namen)}

    def verfuegbarkeit_fahrzeug(self, anzeige_id: str) -> dict | None:
        """Abgeleitete Verfügbarkeit des Fahrzeugs über alle seine Inserate (bestätigte Dubletten, P3-02b/P3-04); None ohne v4-Gegenstück."""
        db = self.k.db
        fid = db.fahrzeug_id_zu(anzeige_id)
        if fid is None:
            return None
        return fahrzeug_von(db.con, fid, datetime.now(), offline_nach_tagen(self.k.cfg))

    def besichtigung_kurz(self, b: dict, sicht: TeamSicht | None = None) -> dict:
        link = self.k.app_link(f"/m#/besichtigung/{b['id']}")
        return {"id": b["id"], "anzeige_id": b["anzeige_id"], "status": b["status"], "termin": b["termin"],
                "adresse": b["adresse"], "zustaendig": b["zustaendig"], "fahrzeug": b["basis"].get("fahrzeug"),
                "bild": None, "endpreis": b["endpreis"], "karte": karten_link(b.get("adresse") or b["basis"].get("ort")),
                "whatsapp": whatsapp_link(termin_text(b, link), (b["zustaendig"] or {}).get("telefon")),
                "darf_bearbeiten": self.darf_besichtigung(b, sicht)}

    def besichtigung_voll(self, b: dict) -> dict:
        e = berechne(self.k.katalog(), b["daten"] or {}, b["basis"])
        return {**self.besichtigung_kurz(b), "basis": b["basis"], "daten": b["daten"], "ergebnis": e,
                "protokoll": {k_: v for k_, v in b["protokoll"].items() if k_ not in OHNE_GERAET} if b["protokoll"] else None,
                "version": b["version"], "fotos": self.k.team.fotos(b["id"])}

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
        if p == "/api/logout":
            if self.sitzung:
                k.team.abmelden(self.sitzung)
            return self.json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"})
        if p == "/api/status":
            if daten.get("status") not in STATUS:
                raise Antwort(400, "unbekannter Status")
            kanal = self.kanal(daten)
            ad_id = str(daten.get("id"))
            if self.team_aktiv and self.nutzer["rolle"] != "inhaber" and "gekauft" in (daten["status"], k.db.status_von(ad_id)):
                # P1-15: ein Kauf entsteht über den Abschluss der Besichtigung (mit Protokoll) – direkt nur durch den Inhaber;
                # ebenso nimmt nur er einen Kauf wieder zurück
                raise Antwort(403, "Status „gekauft“ setzt oder ändert der Inhaber – oder der Abschluss der Besichtigung", grund="recht")
            aktuell = k.db.status_von(ad_id) if daten["status"] == VORBEREITET else None
            if aktuell in (*IN_ARBEIT, "gekauft") and aktuell != VORBEREITET:
                # veraltete Seite: „Text kopiert“ darf einen schon bestätigten Kontakt oder Kauf nicht zurücksetzen
                raise Antwort(409, f"Status ist bereits „{STATUS[aktuell]}“ – bitte Seite neu laden, nicht senden")
            team = self.team_parameter(daten, ad_id)
            uebernimmt = daten["status"] in IN_ARBEIT
            vorher = self.vorheriger_halter(ad_id, team) if uebernimmt else None
            try:
                ok = k.db.setze_status(ad_id, daten["status"], text=text, betrag=betrag, kanal=kanal, **team)
            except BearbeitungsKonflikt:
                raise self.konflikt(ad_id, team["dubletten"] if uebernimmt else (), gruppe=team["erzwingen"]) from None
            self.logge_erzwingen(ad_id, vorher)
            k.veraendert()
            return self.json(200 if ok else 404, {"ok": ok})
        if p == "/api/nachgefasst":
            ad_id, kanal = str(daten.get("id")), self.kanal(daten)
            team = {k_: v for k_, v in self.team_parameter(daten, ad_id).items() if k_ != "inhaber"}
            vorher = self.vorheriger_halter(ad_id, team) if text else None
            try:
                ok = bool(text) and k.db.nachgefasst(ad_id, text, betrag, kanal=kanal, **team)
            except BearbeitungsKonflikt:
                raise self.konflikt(ad_id, team["dubletten"], gruppe=team["erzwingen"]) from None
            if ok:
                self.logge_erzwingen(ad_id, vorher)
            k.veraendert()
            return self.json(200 if ok else 400, {"ok": ok})
        if m := re.fullmatch(r"/api/bearbeitung/([\w-]+)/(uebernehmen|abgeben|zuweisen)", p):
            return self.json(200, getattr(self, f"bearbeitung_{m.group(2)}")(m.group(1), daten))
        if p == "/api/suchprofile" or re.fullmatch(r"/api/suchprofil/\d+(?:/loeschen|/auftrag)?", p):
            return self.json(200, self.suchprofil_aendern(p, daten))
        if p == "/api/kalibrierung" or re.fullmatch(r"/api/kalibrierung/[0-9]{1,9}/loeschen", p):
            return self.json(200, self.kalibrierung_aendern(p, daten))
        if m := re.fullmatch(r"/api/kontakt/(\d+)/bestaetigen", p):
            return self.json(200, self.kontakt_bestaetigen(int(m.group(1)), self.kanal(daten), daten))
        if p == "/api/notiz":
            ok = k.db.setze_notiz(str(daten.get("id")), str(daten.get("notiz") or "")[:2000])
            k.veraendert()
            return self.json(200 if ok else 404, {"ok": ok})
        if m := re.fullmatch(r"/api/anzeige/([\w-]+)/anbieter", p):
            # Korrektur der Anbieterart durch das Team (P3-05): ersetzt jede Einstufung, Herkunft „vom Team angegeben“; protokolliert (Audit)
            wert = daten.get("anbieter")
            if wert not in (None, "", *ANBIETER):
                raise Antwort(400, "anbieter muss „privat“, „gewerblich“ oder leer (unbekannt) sein")
            gewerblich = ANBIETER.get(wert or "")
            if not k.db.setze_anbieter(m.group(1), gewerblich):
                raise Antwort(404, "Anzeige nicht gefunden")
            k.veraendert()
            log.info("Anbieter von Anzeige %s auf „%s“ gesetzt (%s)", m.group(1), wert or "unbekannt", self.nutzer.get("name"))
            return self.json(200, {"ok": True, "anbieter": einstufung(gewerblich, "korrektur")})
        if p == "/api/suchlauf":
            if self.team_aktiv:
                self.nur_inhaber()                     # P1-15: Suchläufe und Import steuert der Inhaber
            return self.json(200, {"gestartet": k.suchlauf.starte(), **k.suchlauf.stand})
        if p == "/api/import":
            if self.team_aktiv:
                self.nur_inhaber()
            return self.json(200, self.seiten_einlesen())
        if p == "/api/import/mails":
            if self.team_aktiv:
                self.nur_inhaber()                     # wie der Seitenimport (P1-15)
            return self.json(200, self.mails_einlesen())
        if p == "/api/import/text":
            return self.json(200, self.text_einlesen(daten))
        if m := re.fullmatch(r"/api/dubletten/(bestaetigen|ablehnen|aufheben)", p):
            return self.json(200, self.dublette_entscheiden(m.group(1), daten))
        if p == "/api/besichtigung":
            return self.json(200, self.besichtigung_anlegen(daten))
        if p == "/api/verkaufsanfrage":
            return self.json(200, self.verkaufsanfrage_anlegen(daten))
        if m := re.fullmatch(r"/api/haendler/fahrzeug/(\d+)/interesse", p):
            standort = self.standort_freigeschaltet()
            if not standort:
                raise Antwort(403, "Interesse melden nur mit Standort-Zugang", grund="recht")
            if not k.haendler.interesse_melden(int(m.group(1)), standort, self.nutzer["id"]):
                raise Antwort(404, "Nicht (mehr) freigegeben")
            return self.json(200, {"ok": True})
        if m := re.fullmatch(r"/api/haendler/auktion/(\d+)/gebot", p):
            standort = self.standort_freigeschaltet()
            if not standort:
                raise Antwort(403, "Bieten nur mit Standort-Zugang", grund="recht")
            erg = self.gebot_mit_kalkulation(int(m.group(1)), standort, daten)
            if not erg["wiederholt"]:
                log.info("Demo-Gebot %s € auf Auktion %s durch %s", erg["betrag"], m.group(1), self.nutzer["name"])
            return self.json(200, erg)
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/kalkulation", p):
            betrag, standort = daten.get("betrag"), daten.get("standort_id") or 0
            if (betrag is not None and (isinstance(betrag, bool) or not isinstance(betrag, int) or not 0 < betrag <= 10_000_000)) \
                    or isinstance(standort, bool) or not isinstance(standort, int) or (standort and not k.haendler.standort(standort)):
                raise Antwort(400, "Betrag oder Standort ungültig")
            try:
                e, erg = k.deal.berechne(int(m.group(1)), betrag, standort)
            except LookupError as fehler:
                raise Antwort(404, str(fehler)) from fehler
            kid = k.deal.speichern(e, erg, anlass="gespeichert", anfrage_id=int(m.group(1)), standort_id=standort, nutzer_id=self.nutzer["id"])
            return self.json(200, {"id": kid})
        if p == "/api/einladung/pruefen":                  # F4: Name zur Einladung anzeigen (offen, nur mit gültigem Token, gebremst)
            self._herkunft_pruefen("Einladung")
            ip = self.client_ip()
            if warten := k.bremse.wartezeit(ip, "(einladung)"):
                raise Antwort(429, f"Zu viele Fehlversuche – bitte in {max(1, warten // 60)} Minute(n) erneut versuchen", {"warten_sek": warten})
            e = k.team.einladung(str(daten.get("token") or "")[:100]) if k.team.hat_nutzer() else None
            if not e:
                k.bremse.fehlschlag(ip, "(einladung)")
                raise Antwort(410, "Einladung ungültig, abgelaufen oder schon eingelöst – bitte eine neue anfordern")
            return self.json(200, {"name": e["name"], "rolle": ROLLEN.get(e["rolle"], e["rolle"])})
        if p == "/api/nutzer/einladen":                    # F4: Zugang anlegen bzw. erneut einladen – Link zum Weitergeben
            self.nur_inhaber()
            return self.json(200, self.nutzer_einladen(daten))
        if m := re.fullmatch(r"/api/zugaenge/(\w+)", p):
            self.nur_inhaber()
            try:
                return self.json(200, k.zugaenge.speichern(m.group(1), daten, self.nutzer["id"]))
            except LookupError as e:
                raise Antwort(404, str(e)) from e
            except ValueError as e:
                raise Antwort(400, str(e)) from e
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/widerruf", p):
            self.nur_inhaber()
            return self.json(200, self.anfrage_widerruf(int(m.group(1))))
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/besichtigung", p):
            return self.json(200, self.anfrage_besichtigung(int(m.group(1)), daten))
        if m := re.fullmatch(r"/api/ankauf/(\d+)/(vertrag|uebergabe|kosten|verkauf|storno|dokument)", p):
            return self.json(200, self.ankauf_schritt(int(m.group(1)), m.group(2), daten))
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/auktion", p):
            self.nur_inhaber()
            aid = k.auktion.anlegen(int(m.group(1)), self.nutzer["id"], startpreis=daten.get("startpreis"),
                                    mindestpreis=daten["mindestpreis"] if "mindestpreis" in daten else MINDESTPREIS_STANDARD,
                                    laufzeit_stunden=daten.get("laufzeit_stunden"))
            log.info("Demo-Auktion %s für Anfrage %s gestartet durch %s", aid, m.group(1), self.nutzer["name"])
            return self.json(200, {"id": aid})
        if m := re.fullmatch(r"/api/auktion/(\d+)/(abbrechen|zuschlag|ablehnen)", p):
            self.nur_inhaber()
            aid = int(m.group(1))
            if m.group(2) == "abbrechen":
                k.auktion.abbrechen(aid, self.nutzer["id"], str(daten.get("grund") or ""))
            else:
                k.auktion.entscheiden(aid, self.nutzer["id"], m.group(2) == "zuschlag")
            log.info("Demo-Auktion %s: %s durch %s", aid, m.group(2), self.nutzer["name"])
            return self.json(200, {"ok": True})
        if p == "/api/standorte":
            self.nur_inhaber()
            try:
                return self.json(200, {"id": k.haendler.standort_anlegen(str(daten.get("name") or ""), daten.get("plz"), daten.get("ort"))})
            except ValueError as e:
                raise Antwort(400, str(e)) from e
            except sqlite3.IntegrityError as e:
                raise Antwort(409, "Diesen Standort gibt es schon") from e
        if m := re.fullmatch(r"/api/standorte/(\d+)/status", p):
            self.nur_inhaber()
            try:
                ok = k.haendler.setze_standort_status(int(m.group(1)), str(daten.get("status")), self.nutzer["id"])
            except ValueError as e:
                raise Antwort(400, str(e)) from e
            if not ok:
                raise Antwort(404, "Standort nicht gefunden")
            log.info("Standort %s: Status %s durch %s", m.group(1), daten.get("status"), self.nutzer["name"])
            return self.json(200, {"ok": True})
        if m := re.fullmatch(r"/api/verkaufsanfrage/(\d+)/(status|notiz|uebernehmen|foto|freigabe)", p):
            return self.json(200, self.verkaufsanfrage_aendern(int(m.group(1)), m.group(2), daten))
        if m := re.fullmatch(r"/api/besichtigung/(\d+)/(planen|speichern|foto|abschluss)", p):
            b = self.besichtigung(m.group(1), schreiben=True)
            return self.json(200, getattr(self, f"b_{m.group(2)}")(b, daten))
        raise Antwort(404, "nicht gefunden")

    # ----- Team: Übernehmen, Abgeben, Zuweisen
    def _team_anzeige(self, anzeige_id: str) -> str:
        """Status des Inserats; 400 ohne Team, 404 bei unbekannter Anzeige."""
        if not self.team_aktiv:
            raise Antwort(400, "Team nicht aktiv – es sind keine Nutzer angelegt (python scout.py nutzer anlegen …)")
        status = self.k.db.status_von(anzeige_id)
        if status is None:
            raise Antwort(404, "Inserat nicht gefunden")
        return status

    def _team_antwort(self, anzeige_id: str, status: str) -> dict:
        return {"ok": True, "team": self.team_sicht().objekt_id(anzeige_id, status, self.k.dubletten_von(anzeige_id))}

    def bearbeitung_uebernehmen(self, anzeige_id: str, daten: dict) -> dict:
        status = self._team_anzeige(anzeige_id)
        erzwingen = self.erzwingen_gewuenscht(daten)
        dubletten = self.k.dubletten_von(anzeige_id)
        vorher = self.team_sicht().fremder_halter(anzeige_id, dubletten) if erzwingen else None
        jetzt, grenze = self.jetzt_grenze()
        if not self.k.db.uebernimm(anzeige_id, self.nutzer["id"], jetzt, grenze, erzwingen, dubletten):
            raise self.konflikt(anzeige_id, dubletten, gruppe=erzwingen)
        self.logge_erzwingen(anzeige_id, vorher)
        return self._team_antwort(anzeige_id, status)

    def bearbeitung_abgeben(self, anzeige_id: str, daten: dict) -> dict:
        status = self._team_anzeige(anzeige_id)
        sicht = self.team_sicht()
        zeile = sicht.zeilen.get(anzeige_id)
        inhaber = self.nutzer["rolle"] == "inhaber"
        h = sicht.halter(anzeige_id)
        if h is not None and h != self.nutzer["id"] and not inhaber:        # Fremdes gibt nur der Inhaber ab
            raise Antwort(403, "Nur der Bearbeiter oder der Inhaber kann ein Inserat abgeben")
        if zeile and zeile.get("kontaktiert_von"):
            raise Antwort(409, "Bereits kontaktiert – der Inhaber kann das Inserat zuweisen",
                          {"team": sicht.objekt_id(anzeige_id, status)})
        self.k.db.gib_ab(anzeige_id, self.nutzer["id"], inhaber)
        return self._team_antwort(anzeige_id, status)

    def bearbeitung_zuweisen(self, anzeige_id: str, daten: dict) -> dict:
        status = self._team_anzeige(anzeige_id)
        if not darf_zuweisen(self.nutzer["rolle"]):
            raise Antwort(403, "Zuweisen ist dem Inhaber vorbehalten")
        ziel = daten.get("nutzer_id")
        n = self.k.team.nutzer(ziel) if isinstance(ziel, int) and not isinstance(ziel, bool) else None
        if not n or not n["aktiv"]:
            raise Antwort(400, "nutzer_id fehlt oder der Mitarbeiter ist unbekannt bzw. deaktiviert")
        jetzt, grenze = self.jetzt_grenze()
        dubletten = self.k.dubletten_von(anzeige_id)
        try:
            self.k.db.weise_zu(anzeige_id, n["id"], jetzt, dubletten, grenze)
        except BearbeitungsKonflikt:
            raise self.konflikt(anzeige_id, dubletten, ziel_id=n["id"], gruppe=True) from None
        log.info("Zuweisung: Anzeige %s an %s durch %s", anzeige_id, n["name"], self.nutzer["name"])
        return self._team_antwort(anzeige_id, status)

    def verkaufsanfrage_anlegen(self, daten: dict) -> dict:
        """Anfrage anlegen (Formular in der App; Telefon/vor Ort durch Mitarbeiter). Antwort mit Referenz und – nur bei sicherer
        Datenlage – grober Spanne für den Verkäufer; nie Max-EK oder Angebot."""
        k = self.k
        try:
            a = vk.pruefe_anfrage(daten)
        except Eingabefehler as e:
            raise Antwort(400, "Bitte prüfen: " + "; ".join(e.fehler), {"felder": e.fehler}) from e
        version = str((k.cfg.get("verkaeuferportal") or {}).get("einwilligung_version") or "unbekannt")
        neu = k.verkauf.anlegen(a, self.nutzer["id"], version)
        b = vk.bewerte(k.cfg, {**a, "id": neu["id"]}, vk.vergleich_aus(k.db))
        log.info("Verkaufsanfrage %s angelegt (%s) durch %s", neu["referenz"], a["kanal"], self.nutzer["name"])
        return {**neu, "spanne": vk.spanne_fuer_verkaeufer(b, k.cfg)}

    def verkaufsanfrage_aendern(self, anfrage_id: int, art: str, daten: dict) -> dict:
        """Ändern nur durch den Bearbeiter, bei freier Anfrage durch jeden im Team (Übernehmen macht zum Bearbeiter), immer durch den
        Inhaber. Prüfung und Änderung in EINER Transaktion – zwei Kollegen können eine freie Anfrage nicht gleichzeitig übernehmen."""
        with self.k.db.transaktion():
            self._anfrage_recht(anfrage_id, art, daten)
            return self._verkaufsanfrage_aendern(anfrage_id, art, daten)

    def _anfrage_recht(self, anfrage_id: int, art: str, daten: dict):
        if art == "freigabe" or not self.team_aktiv or self.nutzer["rolle"] == "inhaber":
            return
        r = self.k.db.con.execute("SELECT v.bearbeiter_id, n.name FROM verkaufsanfragen v LEFT JOIN nutzer n ON n.id=v.bearbeiter_id "
                                  "WHERE v.id=?", (anfrage_id,)).fetchone()
        if not r:
            raise Antwort(404, "Anfrage nicht gefunden")
        abgeben = art == "uebernehmen" and daten.get("abgeben") is True
        if (r["bearbeiter_id"] and r["bearbeiter_id"] != self.nutzer["id"]) or (abgeben and r["bearbeiter_id"] != self.nutzer["id"]):
            raise Antwort(403, f"Diese Anfrage bearbeitet {r['name'] or 'niemand'} – ändern oder übernehmen kann sie nur der Bearbeiter "
                               "oder der Inhaber", grund="recht")

    def _verkaufsanfrage_aendern(self, anfrage_id: int, art: str, daten: dict) -> dict:
        k, nid = self.k, self.nutzer["id"]
        try:
            if art == "status":
                ok = k.verkauf.setze_status(anfrage_id, str(daten.get("status")), nid)
            elif art == "notiz":
                ok = k.verkauf.setze_notiz(anfrage_id, str(daten.get("notiz") or ""), nid)
            elif art == "uebernehmen":
                ok = k.verkauf.setze_bearbeiter(anfrage_id, None if daten.get("abgeben") is True else nid, nid)
            elif art == "freigabe":
                self.nur_inhaber()
                ok = k.verkauf.setze_freigabe(anfrage_id, daten.get("freigeben") is True, nid)
            else:
                return k.verkauf.foto_speichern(anfrage_id, _bild_bytes(str(daten.get("bild") or "")), nid)
        except LookupError as e:
            raise Antwort(404, str(e)) from e
        except ValueError as e:
            raise Antwort(400, str(e)) from e
        if not ok:
            raise Antwort(404, "Anfrage nicht gefunden")
        return {"ok": True}

    def dubletten_stand(self, inserat_id: int) -> dict:
        """Gruppe (Inserate desselben Fahrzeugs), abgeleiteter Fahrzeugstatus und Entscheidungen zu einem Inserat."""
        k = self.k
        mitglieder = gruppe(k.db, inserat_id)
        return {"inserat_id": inserat_id, "gruppe": mitglieder, "fahrzeug_status": fahrzeug_status(m["status"] for m in mitglieder),
                "entscheidungen": entscheidungen_zu(k.db, *(m["inserat_id"] for m in mitglieder))}

    def dubletten_entscheidungen(self, anzeige_id: str) -> dict:
        """Entscheidungen und Gruppe zu einer Anzeige (``?anzeige=<Anzeigen-ID>``); Inhaber und Mitarbeiter."""
        if self.nutzer.get("rolle") not in TEXT_IMPORT_ROLLEN:
            raise Antwort(403, "Nur für Inhaber und Mitarbeiter", grund="recht")
        iid = inserat_zu_anzeige(self.k.db, anzeige_id) if anzeige_id else None
        if iid is None:
            raise Antwort(404, "Inserat nicht gefunden")
        rolle = self.nutzer.get("rolle")
        return {"anzeige": anzeige_id, **self.dubletten_stand(iid), "darf_bestaetigen": darf_bestaetigen(rolle),
                "darf_ablehnen": darf_ablehnen(rolle), "darf_aufheben": darf_aufheben(rolle)}

    def preisverlauf_antwort(self, anzeige_id: str, umfang: str) -> dict:
        """Preisverlauf einer Anzeige (``?anzeige=<Anzeigen-ID>``), chronologisch mit Kanal und Zeitpunkt (P3-03); nur lesend, Inhaber und Mitarbeiter.
        ``umfang=inserat`` (Standard): nur dieses Inserat; ``umfang=fahrzeug``: alle Inserate desselben Fahrzeugs (bestätigte Dubletten) gemeinsam."""
        if self.nutzer.get("rolle") not in TEXT_IMPORT_ROLLEN:
            raise Antwort(403, "Nur für Inhaber und Mitarbeiter", grund="recht")
        if umfang not in ("inserat", "fahrzeug"):
            raise Antwort(400, "umfang muss inserat oder fahrzeug sein")
        db = self.k.db
        iid = inserat_zu_anzeigen_id(db, anzeige_id) if anzeige_id else None
        if iid is None:
            raise Antwort(404, "Inserat nicht gefunden")
        fid = db.con.execute("SELECT fahrzeug_id FROM inserate WHERE id = ?", (iid,)).fetchone()[0]
        if umfang == "fahrzeug" and fid is not None:
            verlauf = preisverlauf(db, fahrzeug_id=fid)
            inserate = [{"anzeigen_id": r["anzeigen_id"], "plattform": r["plattform"]} for r in db.inserate_von_fahrzeug(fid)]
        else:
            verlauf = preisverlauf(db, anzeige_id)
            inserate = [{"anzeigen_id": r["anzeigen_id"], "plattform": r["plattform"]} for r in db.con.execute(
                "SELECT anzeigen_id, plattform FROM inserate WHERE id = ?", (iid,))]
        return {"anzeige": anzeige_id, "umfang": umfang, "inserat_id": iid, "fahrzeug_id": fid, "inserate": inserate, "anzahl": len(verlauf),
                "verlauf": verlauf}

    def dublette_entscheiden(self, aktion: str, daten: dict) -> dict:
        """Bestätigen („gleich“), Ablehnen („verschieden“) und Aufheben einer Dublettenentscheidung (P3-02b, ADR-040). Rechte:
        bestätigen Inhaber und Mitarbeiter, ablehnen und aufheben nur der Inhaber (403 „recht“); Widerspruch zum Stand 409 „konflikt“;
        unbekannte oder unsinnige IDs 400. Danach sind Bewertung und Team-Sperre sofort neu (Zwischenspeicher verworfen)."""
        k, rolle, nutzer_id = self.k, self.nutzer.get("rolle"), self.nutzer.get("id")
        if not {"bestaetigen": darf_bestaetigen, "ablehnen": darf_ablehnen, "aufheben": darf_aufheben}[aktion](rolle):
            raise Antwort(403, "Diese Entscheidung trifft der Inhaber" if aktion != "bestaetigen" else "Nur für Inhaber und Mitarbeiter", grund="recht")
        try:
            if aktion == "aufheben":
                erg = hebe_auf(k.db, daten.get("entscheidung_id"), nutzer_id)
                zeile = k.db.con.execute("SELECT inserat_a FROM dubletten_entscheidungen WHERE id = ?", (erg["entscheidung_id"],)).fetchone()
                iid = zeile[0]
            else:
                erg = (bestaetige if aktion == "bestaetigen" else lehne_ab)(k.db, daten.get("a"), daten.get("b"), nutzer_id)
                iid = min(daten["a"], daten["b"])
        except DublettenFehler as e:
            raise Antwort(400, str(e)) from e
        except DublettenKonflikt as e:
            raise Antwort(409, str(e)) from e
        finally:
            k.veraendert()
            k.dubletten_verwerfen()
        antwort = {"ok": True, **erg, **self.dubletten_stand(iid)}
        if aktion == "bestaetigen":
            _, grenze = self.jetzt_grenze()
            halter = halter_der_gruppe(k.db, [m["anzeigen_id"] for m in antwort["gruppe"]], grenze)
            if len({h["bearbeiter_id"] for h in halter}) > 1:
                antwort["warnung"] = {"grund": "verschiedene_halter", "halter": halter,
                                      "text": "Inserate dieser Gruppe werden von verschiedenen Kollegen gehalten – Reservierungen wurden nicht übertragen"}
        return antwort

    def seiten_einlesen(self) -> dict:
        """Gespeicherte Seiten aus dem konfigurierten Import-Ordner – nie ein Pfad aus der Anfrage, kein Netzabruf."""
        k = self.k
        if k.suchlauf.stand["laeuft"]:
            raise Antwort(409, "Gerade läuft ein Suchlauf – bitte danach einlesen")
        try:
            eingang_pruefen(k.cfg, "seiten")                 # abgeschaltet: nichts lesen, Ordner nicht anlegen (ADR-036)
        except EingangDeaktiviert as e:
            raise Antwort(409, str(e), grund="deaktiviert") from e
        ordner = import_ordner(k.cfg)
        ordner.mkdir(parents=True, exist_ok=True)
        stat = Importer(k.cfg, k.db).importiere_seiten(ordner, max_dateien=MAX_IMPORT_DATEIEN,
                                                             max_sekunden=MAX_IMPORT_SEKUNDEN)
        datenrechte.frist_anwenden(k.db, k.cfg, k.basis, k.team.foto_ordner)   # Verkäufernamen kommen über den Seitenimport
        k.veraendert()
        k.dubletten_verwerfen()
        return {**stat, "ordner": relativ_zum_projekt(ordner)}

    def mails_einlesen(self) -> dict:
        """E-Mail-Suchbenachrichtigungen (.eml) aus dem konfigurierten Mail-Ordner – nie ein Pfad aus der Anfrage, kein Netzabruf (P2-06)."""
        k = self.k
        if k.suchlauf.stand["laeuft"]:
            raise Antwort(409, "Gerade läuft ein Suchlauf – bitte danach einlesen")
        try:
            eingang_pruefen(k.cfg, "email")                  # abgeschaltet (Standard): nichts lesen, Ordner nicht anlegen (ADR-036)
        except EingangDeaktiviert as e:
            raise Antwort(409, str(e), grund="deaktiviert") from e
        ordner = mail_ordner(k.cfg, k.basis)
        ordner.mkdir(parents=True, exist_ok=True)
        stat = Importer(k.cfg, k.db).importiere_mails(ordner, max_dateien=MAX_IMPORT_DATEIEN, max_sekunden=MAX_IMPORT_SEKUNDEN)
        offen = datenrechte.mails_unverarbeitet_gemeldet(k.cfg, ordner)
        datenrechte.frist_anwenden(k.db, k.cfg, k.basis, k.team.foto_ordner)     # abgelegte Mails nach der Frist löschen
        k.veraendert()
        k.dubletten_verwerfen()
        return {**stat, "ordner": relativ_zum_projekt(ordner), "unverarbeitet": offen}

    def text_einlesen(self, daten: dict) -> dict:
        """Eine Anzeige aus Adresse + eingefügtem Text (P2-05). Die Adresse wird nie abgerufen (ADR-010): sie liefert nur Plattform und
        Anzeigen-ID. Gelesen wird mit `TextEingang` (rein, höchstens etwa eine halbe Sekunde), gespeichert allein über `Importer.importiere`
        (Kanal „manuell“). Gespeichert wird nur ein sicher erkannter oder vom Nutzer eingetragener Preis (ADR-038); Angaben, die aus einem
        anderen Kanal stammen, bleiben bestehen."""
        k = self.k
        if self.team_aktiv and self.nutzer.get("rolle") not in TEXT_IMPORT_ROLLEN:
            raise Antwort(403, "Anzeigen einlesen dürfen nur Inhaber und Mitarbeiter", grund="recht")
        try:
            eingang_pruefen(k.cfg, "text")
        except EingangDeaktiviert as e:
            raise Antwort(409, str(e), grund="deaktiviert") from e
        url, text, anbieter = daten.get("url"), daten.get("text"), daten.get("anbieter")
        preis, vb = daten.get("preis"), daten.get("vb")
        if not isinstance(url, str) or not isinstance(text, str) or not (anbieter is None or isinstance(anbieter, str)):
            raise Antwort(400, "Adresse (url), Anzeigentext (text) und Anbieter (anbieter) werden als Text erwartet")
        if preis is not None and (isinstance(preis, bool) or not isinstance(preis, int) or not 1 <= preis <= MAX_PREIS):
            raise Antwort(400, f"Der Preis (preis) muss eine ganze Zahl von 1 bis {MAX_PREIS} sein oder fehlen")
        if vb is not None and not isinstance(vb, bool):
            raise Antwort(400, "VB (vb) muss wahr oder falsch sein")
        if len(url) > MAX_URL or len(text) > MAX_TEXT:
            raise Antwort(400, f"Adresse höchstens {MAX_URL}, Text höchstens {MAX_TEXT} Zeichen")
        try:
            (url + text).encode("utf-8")
        except UnicodeEncodeError as e:
            raise Antwort(400, "Adresse oder Text enthalten ungültige Zeichen") from e
        if anbieter == "":
            anbieter = None
        elif anbieter is not None and anbieter not in ANBIETER:
            raise Antwort(400, "anbieter muss „privat“, „gewerblich“ oder leer sein")
        eingang = TextEingang()
        lesung = eingang.lese(eingang.rohdaten(url, text, anbieter, preis=preis, vb=vb))
        if lesung.art != "detail":
            raise Antwort(422, lesung.hinweise[0], {"ergebnis": "nicht_gespeichert", "gespeichert": False, "hinweise": lesung.hinweise})
        inserat, hinweise = lesung.inserate[0], list(lesung.hinweise)
        alt = k.db.con.execute("SELECT preis, marke FROM anzeigen WHERE id=?", (inserat.anzeigen_id,)).fetchone()
        if alt is not None and not k.db.ist_text_eigen(inserat.anzeigen_id) and lesung.preis_status != "eingetragen" \
                and widerspricht_marke(inserat.marke, alt["marke"]):
            # der Text gehört offenbar zu einer anderen Anzeige als die gespeicherte: keinen Preis daraus übernehmen
            inserat.preis, inserat.vb, lesung.preis_status = None, False, "unsicher"
            hinweise.append(f"Text passt offenbar nicht zur gespeicherten Anzeige (Marke {inserat.marke} statt {alt['marke']}) – Preis nicht übernommen")
        try:
            ergebnis = ergebnis_der(Importer(k.cfg, k.db).importiere(lesung, eingang.kanal))
        except ValueError as e:
            raise Antwort(400, str(e)) from e
        k.veraendert()
        k.dubletten_verwerfen()
        z = k.db.con.execute("SELECT titel, preis, vb, km, ez_jahr, ort, marke, gewerblich FROM anzeigen WHERE id=?", (inserat.anzeigen_id,)).fetchone()
        erkannt = {"titel": z["titel"], "preis": z["preis"], "vb": bool(z["vb"]), "km": z["km"], "ez_jahr": z["ez_jahr"], "ort": z["ort"],
                   "marke": z["marke"], "gewerblich": None if z["gewerblich"] is None else bool(z["gewerblich"])}
        vorher = alt["preis"] if alt is not None else None
        aenderung = None if vorher is None or z["preis"] is None else ("gesenkt" if z["preis"] < vorher else
                                                                      "gestiegen" if z["preis"] > vorher else "unveraendert")
        if anbieter == "privat" and erkannt["gewerblich"]:
            hinweise.append("Früher als gewerblich erkannt – Angabe „privat“ nicht übernommen")
        if ergebnis != "neu":
            anders = [name for feld, name in (("titel", "Titel"), ("km", "Kilometerstand"), ("ez_jahr", "Erstzulassung"), ("ort", "Ort"), ("marke", "Marke"))
                      if getattr(inserat, feld) not in (None, "") and getattr(inserat, feld) != z[feld] and z[feld] not in (None, "")]
            if anders:
                hinweise.append(f"Bereits gespeicherte Angaben bleiben bestehen ({', '.join(anders)}); der Text ergänzte nur Fehlendes und den Preis")
        log.info("Anzeige %s (%s) per Adresse + Text eingelesen: %s, Preis %s (%s)", inserat.anzeigen_id, lesung.plattform, ergebnis,
                 lesung.preis_status, self.nutzer.get("name"))
        return {"ergebnis": ergebnis, "gespeichert": True, "anzeige_id": inserat.anzeigen_id, "plattform": lesung.plattform,
                "fahrzeug_url": f"/m#/fahrzeug/{quote(inserat.anzeigen_id)}", "hinweise": hinweise, "erkannt": erkannt,
                "preis_status": lesung.preis_status, "preis_vorher": vorher, "preis_aenderung": aenderung}

    def _termin(self, wert) -> str | None:
        if not wert:
            return None
        try:
            return datetime.fromisoformat(str(wert)).isoformat(timespec="minutes")
        except ValueError as e:
            raise Antwort(400, "Termin bitte als Datum und Uhrzeit angeben") from e

    def _zustaendig(self, wert) -> int | None:
        """Besichtiger beim Anlegen: leer = der Anlegende. Ob er die Zuständigkeit vergeben darf, prüft ``besichtigung_anlegen``."""
        if wert in (None, ""):
            return self.nutzer["id"]
        try:
            ziel = int(wert)
        except (TypeError, ValueError):
            raise Antwort(400, "Mitarbeiter nicht gefunden") from None
        if not self.k.team.nutzer(ziel):
            raise Antwort(400, "Mitarbeiter nicht gefunden")
        return ziel

    def _zustaendig_planen(self, b: dict, wert) -> int | None:
        """Besichtiger beim Planen. Leer = unverändert (nie stillschweigend der Aufrufer); nur Inhaber und Bearbeiter des Inserats
        dürfen die Zuständigkeit setzen oder ändern – ein Mitarbeiter kann sich auf fremden Inseraten nicht selbst eintragen (403).
        Eine noch leere Zuständigkeit (Altbestand) übernimmt ein berechtigter Aufrufer selbst."""
        berechtigt = self.ist_inhaber_oder_bearbeiter(b["anzeige_id"])
        if wert in (None, ""):
            return self.nutzer["id"] if b["zustaendig_id"] is None and berechtigt else b["zustaendig_id"]
        ziel = self._zustaendig(wert)
        if ziel != b["zustaendig_id"] and not berechtigt:
            raise Antwort(403, "Die Zuständigkeit für eine Besichtigung vergeben nur der Bearbeiter des Inserats oder der Inhaber")
        return ziel

    def besichtigung_anlegen(self, daten: dict) -> dict:
        """Besichtigung anlegen. Im Team ist das wie ein Kontakt: ein Kollege hält das Inserat → 409; ist es frei, übernimmt der
        Anlegende es (samt Dubletten) in derselben Transaktion wie den Status „Besichtigung“. Die Besichtigungs-Rolle
        (``zustaendig_id``, Besichtiger) bleibt davon getrennt: Der Inhaber kann einem Kollegen eine Besichtigung zuweisen, ohne die
        Bearbeitung zu ändern."""
        k = self.k
        z = k.zeile(str(daten.get("anzeige_id")))
        ad_id = z["a"]["id"]
        termin, adresse = self._termin(daten.get("termin")), str(daten.get("adresse") or "").strip()[:200] or None
        zustaendig = self._zustaendig(daten.get("zustaendig_id"))              # prüfen, bevor etwas geändert wird (400)
        if z["b"].sicherheit == "keine":
            # P1-12: ohne Erstzulassung kein Marktwert – die Besichtigung braucht einen manuell angegebenen (Angebotsniveau)
            mw = daten.get("marktwert")
            if isinstance(mw, bool) or not isinstance(mw, int) or not 1000 <= mw <= 1_000_000:
                raise Antwort(409, "Erstzulassung fehlt – ohne Marktwert keine Beträge. Bitte einen Marktwert (Angebotsniveau in €) "
                                   "angeben, z. B. aus mobile.de oder DAT.", grund="marktwert")
            z = {**z, "b": bewerte_anzeige(vk.Rechner(k.cfg), z["a"], [], marktwert_manuell=mw)}
        basis = basis_fuer(z, k.cfg)
        if z["b"].sicherheit == "manuell":
            basis["marktwert_manuell"] = z["b"].marktwert_angebote
        status = k.db.status_von(ad_id) or "neu"
        # Status/Übernahme und Besichtigungsdatensatz in EINER Transaktion: bei Konflikt, Fehler oder „database is locked“ bleibt
        # beides unverändert (nie ein Status „Besichtigung“ ohne Besichtigung).
        if self.team_aktiv:
            team = self.team_parameter(daten, ad_id)
            vorher = self.vorheriger_halter(ad_id, team)
            try:
                with k.db.transaktion():
                    if status == "neu" or status in IN_ARBEIT:
                        k.db.setze_status(ad_id, "besichtigung", **team)        # danach hält der Anlegende das Inserat (oder ist Inhaber)
                    elif not darf_status(self.team_sicht().halter(ad_id), self.nutzer["id"], self.nutzer["rolle"]):
                        raise BearbeitungsKonflikt(ad_id)                      # abgeschlossenes Inserat eines Kollegen
                    elif not self.ist_inhaber_oder_bearbeiter(ad_id):
                        raise Antwort(403, "Besichtigung auf einem abgeschlossenen Inserat nur durch den Bearbeiter oder den Inhaber – "
                                           "bitte das Inserat zuerst übernehmen")
                    bid = k.team.besichtigung_anlegen(ad_id, basis, termin, adresse, zustaendig, self.nutzer["id"])
            except BearbeitungsKonflikt:
                raise self.konflikt(ad_id, team["dubletten"] if status == "neu" or status in IN_ARBEIT else (), gruppe=team["erzwingen"]) from None
            self.logge_erzwingen(ad_id, vorher)
        else:
            with k.db.transaktion():
                if status in ("neu", "vorbereitet", "kontaktiert", "verhandlung"):
                    k.db.setze_status(ad_id, "besichtigung")
                bid = k.team.besichtigung_anlegen(ad_id, basis, termin, adresse, zustaendig, self.nutzer["id"])
        k.veraendert()
        b = k.team.besichtigung(bid)
        self._zuweisung_melden(b)
        return self.besichtigung_kurz(b)

    def _zuweisung_melden(self, b: dict):
        z = b["zustaendig"]
        if z and z["id"] != self.nutzer["id"] and z.get("telefon"):
            termin = datetime.fromisoformat(b["termin"]).strftime("%d.%m. %H:%M") if b.get("termin") else "offen"
            self.k.whatsapp.sende_im_hintergrund(z["telefon"], self.k.cfg.get("whatsapp", {}).get("vorlage_zuweisung"),
                                  [b["basis"].get("fahrzeug", ""), termin, b.get("adresse") or b["basis"].get("ort") or ""])

    def b_planen(self, b: dict, daten: dict) -> dict:
        if b["status"] in ("abgeschlossen", "abgebrochen"):
            raise Antwort(409, "Besichtigung ist bereits abgeschlossen – Planen nicht mehr möglich")
        termin, adresse = self._termin(daten.get("termin")), str(daten.get("adresse") or "").strip()[:200] or None
        self.k.team.besichtigung_planen(b["id"], termin, adresse, self._zustaendig_planen(b, daten.get("zustaendig_id")))
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
        erwartet = daten.get("version")
        if erwartet is not None and (isinstance(erwartet, bool) or not isinstance(erwartet, int)):
            raise Antwort(400, "version muss eine Zahl sein")
        ergebnis = berechne(self.k.katalog(), eingaben, b["basis"])        # verbindlich: Server rechnet nach
        version = self.k.team.besichtigung_speichern(b["id"], eingaben, ergebnis, erwartet)
        if version is None:                       # P1-07: inzwischen von jemand anderem gespeichert (oder abgeschlossen)
            aktuell = self.k.team.besichtigung(b["id"])
            raise Antwort(409, "Diese Besichtigung wurde inzwischen auf einem anderen Gerät gespeichert", grund="version",
                          extra={"version": aktuell["version"], "daten": aktuell["daten"], "status": aktuell["status"]})
        return {"ergebnis": ergebnis, "version": version, "konflikt": False}

    def b_foto(self, b: dict, daten: dict) -> dict:
        if daten.get("mangel_key") is not None and not isinstance(daten["mangel_key"], str):
            raise Antwort(400, "mangel_key muss Text sein")
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
        vorbereitet = self.ankauf_vorbereiten(b, endpreis) if endpreis else None
        if b.get("anfrage_id"):
            return self.anfrage_abschliessen(b, protokoll, endpreis, status, entscheidung, vorbereitet)
        ad_status = {"gekauft": "gekauft", "abgelehnt": "abgesagt", "offen": "verhandlung"}.get(entscheidung)
        team = self.team_parameter({}, b["anzeige_id"]) if ad_status else {}
        if team:
            # Inhaber und der eingetragene Besichtiger dürfen den Status eines Inserats ändern, das ein Kollege bearbeitet, ohne die
            # Bearbeitung zu übernehmen. Die Zuständigkeit kann sich ein Mitarbeiter nicht selbst geben (``_zustaendig_planen``,
            # ``besichtigung_anlegen``): sie stammt vom Inhaber oder vom Bearbeiter des Inserats. Der Bearbeiter selbst braucht keine Ausnahme.
            team["inhaber"] = team["inhaber"] or b["zustaendig_id"] == self.nutzer["id"]
        # Inserat-Status (kann im Team 409 ergeben) und Protokoll in EINER Transaktion – nie halb gespeichert
        try:
            with self.k.db.transaktion():
                if ad_status:
                    self.k.db.setze_status(b["anzeige_id"], ad_status, betrag=endpreis, **team)
                self.k.team.besichtigung_abschliessen(b["id"], protokoll, endpreis, status)
                ankauf = self.k.ankauf.anlegen({**b, "protokoll": protokoll}, endpreis, vorbereitet, self.nutzer["id"]) if vorbereitet else None
        except BearbeitungsKonflikt:
            raise self.konflikt(b["anzeige_id"], team["dubletten"] if ad_status in IN_ARBEIT else ()) from None
        self.k.veraendert()
        return {"ok": True, "protokoll": f"/protokoll/{b['id']}", "ankauf": ankauf}

    def ankauf_vorbereiten(self, b: dict, kaufpreis: int) -> dict:
        """Plan für den Ankaufsvorgang vor der Schreibsperre rechnen; scheitert die Rechnung, gilt die eingefrorene Grundlage."""
        bewertung = None
        if not b.get("anfrage_id"):
            try:
                z = self.k.zeile(b["anzeige_id"])
                bewertung = z["b"]
                mw = (b.get("basis") or {}).get("marktwert_manuell")
                if mw:                            # ohne EZ: wie beim Anlegen mit dem manuellen Marktwert (P1-12)
                    bewertung = bewerte_anzeige(vk.Rechner(self.k.cfg), z["a"], [], marktwert_manuell=mw)
            except Exception:  # noqa: BLE001 – Inserat nicht mehr in der Bewertung: Grundlage der Besichtigung genügt
                bewertung = None
        try:
            return self.k.ankauf.plan_vorbereiten(b, kaufpreis, bewertung)
        except Exception:  # noqa: BLE001 – ohne Plan kein Abbruch des Kaufs; Vergleich dann nur gegen die Grundlage
            log.exception("Plan für Ankauf aus Besichtigung %s nicht berechenbar", b["id"])
            from ..bewertung.ergebnis import plan_aus_basis
            return {"herkunft": "anfrage" if b.get("anfrage_id") else "anzeige", "zuschlag": None, "kalkulation": None,
                    "plan": plan_aus_basis(b["basis"], standzeit_tage=90)}

    def anfrage_abschliessen(self, b: dict, protokoll: dict, endpreis: int | None, status: str, entscheidung: str, vorbereitet) -> dict:
        """Abschluss einer Anfrage-Besichtigung: Status der Anfrage, Protokoll und (bei „gekauft“) Ankaufsvorgang in EINER Transaktion."""
        neu = {"gekauft": "gekauft", "abgelehnt": "abgelehnt", "offen": "angebot"}.get(entscheidung)
        with self.k.db.transaktion():
            if neu:
                self.k.verkauf.setze_status(b["anfrage_id"], neu, self.nutzer["id"])
            self.k.team.besichtigung_abschliessen(b["id"], protokoll, endpreis, status)
            ankauf = self.k.ankauf.anlegen({**b, "protokoll": protokoll}, endpreis, vorbereitet, self.nutzer["id"]) if vorbereitet else None
        return {"ok": True, "protokoll": f"/protokoll/{b['id']}", "ankauf": ankauf}


def ist_gesperrt(fehler: sqlite3.OperationalError) -> bool:
    """„database is locked“ / „database table is locked“ / „busy“: ein anderer Vorgang schreibt gerade."""
    text = str(fehler).lower()
    return "locked" in text or "busy" in text


def bearbeite(handler, k: Kontext, methode: str):
    a = Anfrage(handler, k)
    if methode == "GET" and a.pfad == "/api/ereignisse":
        return _ereignisse(a, handler, k)
    a.puffern = True                    # Reihenfolge: erst Audit-Eintrag festschreiben, dann antworten (kein Wettlauf danach)
    try:
        _bearbeite(a, handler, k, methode)
    finally:
        _protokolliere(a, k, methode)
        if methode == "POST" and a.status and a.status < 400 and (art := art_fuer(a.pfad)):
            k.live.melde(*art)
        if a.puffer:
            a.schreiben(*a.puffer)


def _ereignisse(a: Anfrage, handler, k: Kontext):
    """Server-Sent Events (G1): nach Anmeldung und Rechteprüfung ohne globale Sperre offen halten; nur „etwas hat sich geändert“."""
    try:
        with k.sperre:
            a.pruefe_zugriff(aendernd=False)
    except Antwort as e:
        return a.json(e.status, {"fehler": e.fehler, **({"grund": e.grund} if e.grund else {})})
    schluessel = a.nutzer.get("id") or "lokal"
    if not k.live.oeffnen(schluessel):
        return a.json(429, {"fehler": "Zu viele Live-Verbindungen – die Seite fragt stattdessen in Abständen ab"})
    try:
        haendler = a.nutzer.get("rolle") == HAENDLER
        try:
            stand = int(handler.headers.get("Last-Event-ID") or -1)
        except ValueError:
            stand = -1
        if stand < 0 or stand > k.live.stand:          # erste Verbindung oder Server neu gestartet: ab jetzt
            stand = k.live.stand
        handler.send_response(200)
        for name, wert in {"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store",
                           "X-Accel-Buffering": "no", **SICHERHEITS_KOPF}.items():
            handler.send_header(name, wert)
        handler.end_headers()
        handler.wfile.write(sse_block(kommentar="verbunden", retry_ms=5000))
        handler.wfile.flush()
        ende = time.monotonic() + k.live_lebensdauer
        while time.monotonic() < ende:
            neu, luecke, aktuell = k.live.seit(stand, haendler)
            if luecke:
                neu = [{"stand": aktuell, "art": "alles"}]
            for e in neu:
                handler.wfile.write(sse_block(e))
            if neu:
                handler.wfile.flush()
            stand = aktuell
            if not k.live.warte(stand, min(k.live_ping, max(0.0, ende - time.monotonic()))):
                handler.wfile.write(sse_block(kommentar="ping"))
                handler.wfile.flush()
    except (ConnectionError, OSError):
        pass                                          # Browser weg – er verbindet sich bei Bedarf selbst neu
    finally:
        k.live.schliessen(schluessel)


def _protokolliere(a: Anfrage, k: Kontext, methode: str):
    """Audit-Eintrag vor dem Senden der (zwischengespeicherten) Antwort, außerhalb der Sperre und jeder App-Transaktion, über eine
    eigene Verbindung – auch abgelehnte Zugriffe (401/403) werden festgehalten. Bei „Datenbank belegt“ (503) entfällt er.
    Ein Fehler hier darf die (schon gesendete) Antwort nicht beeinflussen."""
    art = einordnen(methode, a.pfad) if a.status and a.status != 503 else None
    if not art:
        return
    try:
        with k.sperre:
            team = k.team.hat_nutzer()
        if team:
            k.audit.schreibe(a.nutzer if a.nutzer and a.nutzer.get("id") else None, a.client_ip(), methode, a.pfad, a.status,
                             art[0], art[1], a.audit_name)
    except Exception:  # noqa: BLE001
        log.exception("Audit-Eintrag fehlgeschlagen: %s %s", methode, a.pfad)


def _bearbeite(a: Anfrage, handler, k: Kontext, methode: str):
    try:
        if methode == "GET" and a.statisch():
            return
        daten = {}
        a.pruefe_host()                        # vor dem Lesen des Inhalts: fremde Hosts bekommen nicht einmal das zu sehen
        if methode == "POST":
            try:
                laenge = int(handler.headers.get("Content-Length") or 0)
            except ValueError:
                raise Antwort(400, "ungültige Länge") from None
            if laenge < 0:
                raise Antwort(400, "ungültige Länge")
            if laenge > (MAX_FOTO if a.pfad.endswith(("/foto", "/dokument")) else MAX_JSON):
                raise Antwort(413, "Anfrage zu groß")
            roh = handler.rfile.read(laenge) if laenge else b""      # Übertragung ohne Sperre
            try:
                daten = json.loads(roh) if roh else {}
            except ValueError as e:
                raise Antwort(400, "ungültige Anfrage") from e
            if not isinstance(daten, dict):
                raise Antwort(400, "ungültige Anfrage")
            if a.pfad == "/api/login":
                return a.login(daten)              # eigene Sperrführung (scrypt ohne globale Sperre)
            if a.pfad == "/api/einladung":
                return a.einladung_einloesen(daten)                # ebenso (F4)
            if m := re.fullmatch(r"/api/zugaenge/(\w+)/test", a.pfad):
                return a.zugang_testen(m.group(1))                 # Anfrage an den Anbieter ohne globale Sperre (F4)
        with k.sperre:
            try:
                a.pruefe_zugriff(aendernd=methode == "POST" and a.pfad != "/api/login")
                a.get() if methode == "GET" else a.post(daten)
            except BaseException:
                # innerhalb der Sperre: auf der gemeinsamen Verbindung bleibt nach einem Fehler nie eine Transaktion offen
                # (sie würde die Datenbank für den Suchlauf und andere Prozesse sperren)
                if k.db.con.in_transaction:
                    k.db.con.rollback()
                raise
    except Antwort as e:
        if a.verzoegern:
            time.sleep(1)
        if e.status == 401 and methode == "GET" and not a.pfad.startswith("/api/"):
            return a.weiterleiten("/login?weiter=" + quote(handler.path))
        a.json(e.status, {"fehler": e.fehler, **({"grund": e.grund} if e.grund else {}), **e.extra})
    except (AuktionsFehler, AnkaufFehler) as e:
        grund = GRUENDE.get(e.status)
        a.json(e.status, {"fehler": str(e), **({"grund": grund} if grund else {}), **getattr(e, "extra", {})})
    except sqlite3.OperationalError as e:
        if not ist_gesperrt(e):
            log.exception("Fehler bei %s %s", methode, handler.path)
            return a.json(500, {"fehler": "Interner Fehler – Details in ausgabe/scout.log"})
        log.warning("Datenbank belegt bei %s %s: %s", methode, handler.path, e)
        a.json(503, {"fehler": "Datenbank kurz belegt – bitte erneut versuchen", "grund": "belegt"}, {"Retry-After": "2"})
    except Exception:  # noqa: BLE001 – Server soll bei einem Fehler weiterlaufen
        log.exception("Fehler bei %s %s", methode, handler.path)
        a.json(500, {"fehler": "Interner Fehler – Details in ausgabe/scout.log"})
