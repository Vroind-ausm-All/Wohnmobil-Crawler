"""Händlerzugänge der Firma bei mobile.de und AutoScout24 (F4, ADR-059) – zum Einpflegen durch den Inhaber, je Firma (Mandant).

Gespeichert werden nur Händlernummer, API-Benutzer und der NAME der Umgebungsvariable mit dem Passwort bzw. Schlüssel – Geheimnisse
stehen nie in Repository oder Datenbank (Regel 5). Der Name muss mit ``WMSCOUT_`` beginnen: So kann niemand über die Oberfläche eine
andere Umgebungsvariable des Servers an einen Anbieter schicken.

Daten abrufen bleibt gesperrt, bis die Nutzungsbedingungen geklärt sind (Regel 12): mobile.de vergibt die Search-API nur mit einem
API-Account über den Kundenservice, und die Bedingungen für Händler begrenzen das Speichern abgerufener Inserate (docs/SOURCES.md).
Der Verbindungstest schickt nur auf ausdrücklichen Klick genau EINE Anfrage, speichert keine Inserate und meldet nur Status und
Aufbau der Antwort – Grundlage für den Test mit echten Zugängen. AutoScout24 bietet nur eine Einstell-API (kein Lesen).
"""
from __future__ import annotations

import base64
import os
import re
from datetime import datetime

from .datenbank import Datenbank
from .quellen.api_rahmen import ApiAbruf
from .quellen.basis import QuellenFehler

PLATTFORMEN = {
    "mobilede": {
        "name": "mobile.de", "lesen": True,
        # Annahmen aus der öffentlichen Übersicht (services.mobile.de): REST, HTTP-Basic-Anmeldung, JSON über den Accept-Kopf.
        # Pfad und Kopf sind beim ersten Test mit echtem API-Account zu bestätigen (nicht gegen eine echte Antwort geprüft).
        "basis_url": "https://services.mobile.de", "test_pfad": "/search-api/search", "accept": "application/vnd.de.mobile.api+json",
        "hinweis": "Search-API: API-Account beim mobile.de-Kundenservice freischalten lassen – Benutzer und Passwort kommen von mobile.de. "
                   "Datenabruf erst nach Klärung der Bedingungen (u. a. Speicherdauer).",
    },
    "autoscout24": {
        "name": "AutoScout24", "lesen": False,
        "hinweis": "AutoScout24 bietet nur eine Schnittstelle zum Einstellen eigener Inserate, keine zum Lesen. Neue Angebote über "
                   "Suchaufträge per E-Mail einlesen.",
    },
}
VARIABLE = re.compile(r"WMSCOUT_[A-Z0-9_]{1,60}")
HAENDLERNUMMER = re.compile(r"[A-Za-z0-9-]{1,30}")
API_BENUTZER = re.compile(r"[\w.@+-]{1,80}")


def variable_praefix(cfg: dict) -> str:
    """Erlaubter Anfang des Variablennamens: im Mandantenbetrieb ``WMSCOUT_<KENNUNG>_`` – alle Mandanten teilen sich die Umgebung des
    Servers, ein Mandant darf nie die Variable eines anderen nennen (QA F4 B3)."""
    kennung = re.sub(r"[^A-Z0-9]", "_", str((cfg.get("mandant") or {}).get("kennung") or "").upper())
    return f"WMSCOUT_{kennung}_" if kennung else "WMSCOUT_"


def variable_vorschlag(cfg: dict, plattform: str) -> str:
    """``WMSCOUT_<MANDANT>_<PLATTFORM>_PASSWORT`` (im Einzelplatz ohne Mandant) – je Firma eine eigene Variable."""
    kennung = re.sub(r"[^A-Z0-9]", "_", str((cfg.get("mandant") or {}).get("kennung") or "").upper())
    return "_".join(t for t in ("WMSCOUT", kennung, plattform.upper(), "PASSWORT") if t)


class ZugangSpeicher:
    def __init__(self, db: Datenbank, cfg: dict, umgebung=None):
        self.db, self.con, self.cfg = db, db.con, cfg
        self.umgebung = os.environ if umgebung is None else umgebung

    def _zeile(self, plattform: str) -> dict:
        r = self.con.execute("SELECT * FROM plattform_zugaenge WHERE plattform=?", (plattform,)).fetchone()
        return dict(r) if r else {}

    def liste(self) -> list[dict]:
        """Je Plattform: gespeicherte Angaben, Variable (gespeichert oder Vorschlag), ob das Geheimnis auf dem Server gesetzt ist – nie
        der Wert selbst."""
        erg = []
        for kennung, p in PLATTFORMEN.items():
            z = self._zeile(kennung)
            variable = z.get("geheimnis_variable") or variable_vorschlag(self.cfg, kennung)
            if not variable.startswith(variable_praefix(self.cfg)):
                variable = variable_vorschlag(self.cfg, kennung)          # gespeicherter fremder Name gilt nicht
            erg.append({"plattform": kennung, "name": p["name"], "lesen": p["lesen"], "hinweis": p["hinweis"],
                        "haendlernummer": z.get("haendlernummer"), "api_benutzer": z.get("api_benutzer"), "variable": variable,
                        "geheimnis_gesetzt": bool(str(self.umgebung.get(variable, "")).strip()) if p["lesen"] else None,
                        "abruf_freigegeben": False, "letzter_test_am": z.get("letzter_test_am"),
                        "letzter_test_ergebnis": z.get("letzter_test_ergebnis"), "aktualisiert_am": z.get("aktualisiert_am")})
        return erg

    def speichern(self, plattform: str, daten: dict, nutzer_id: int | None) -> dict:
        """Händlernummer, API-Benutzer und Variablenname prüfen und speichern (leere Felder = nicht angegeben). ``ValueError`` mit
        verständlicher Meldung; ``LookupError`` bei unbekannter Plattform."""
        if plattform not in PLATTFORMEN:
            raise LookupError("Plattform unbekannt")
        werte = {}
        for feld, muster, text in (("haendlernummer", HAENDLERNUMMER, "Händlernummer: Buchstaben, Ziffern, Bindestrich (höchstens 30)"),
                                   ("api_benutzer", API_BENUTZER, "API-Benutzer: Buchstaben, Ziffern und . @ + - _ (höchstens 80)"),
                                   ("geheimnis_variable", VARIABLE, "Variable: WMSCOUT_ und danach nur A–Z, 0–9, _ (z. B. WMSCOUT_MOBILEDE_PASSWORT)")):
            wert = str(daten.get(feld) or "").strip()
            if wert and not muster.fullmatch(wert):
                raise ValueError(text)
            werte[feld] = wert or None
        if werte["geheimnis_variable"] and not werte["geheimnis_variable"].startswith(variable_praefix(self.cfg)):
            raise ValueError(f"Variable muss mit {variable_praefix(self.cfg)} beginnen (eigene Firma)")
        if not PLATTFORMEN[plattform]["lesen"]:
            werte["api_benutzer"] = werte["geheimnis_variable"] = None          # ohne Lese-Schnittstelle nichts dafür speichern
        with self.db.transaktion():
            self.con.execute(
                "INSERT INTO plattform_zugaenge (plattform, haendlernummer, api_benutzer, geheimnis_variable, aktualisiert_am, aktualisiert_von) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(plattform) DO UPDATE SET haendlernummer=excluded.haendlernummer, "
                "api_benutzer=excluded.api_benutzer, geheimnis_variable=excluded.geheimnis_variable, aktualisiert_am=excluded.aktualisiert_am, "
                "aktualisiert_von=excluded.aktualisiert_von",
                (plattform, werte["haendlernummer"], werte["api_benutzer"], werte["geheimnis_variable"],
                 datetime.now().isoformat(timespec="seconds"), nutzer_id))
        return next(z for z in self.liste() if z["plattform"] == plattform)

    def test_vorbereiten(self, plattform: str) -> dict:
        """Alles für den Verbindungstest (unter der Sperre lesen, Anfrage danach ohne Sperre). ``ValueError``, wenn etwas fehlt."""
        if plattform not in PLATTFORMEN:
            raise LookupError("Plattform unbekannt")
        p = PLATTFORMEN[plattform]
        if not p["lesen"]:
            raise ValueError(f"{p['name']} hat keine Lese-Schnittstelle – kein Verbindungstest möglich")
        z = next(x for x in self.liste() if x["plattform"] == plattform)
        if not z["api_benutzer"]:
            raise ValueError("Zuerst den API-Benutzer eintragen und speichern")
        geheimnis = str(self.umgebung.get(z["variable"], "")).strip()
        if not geheimnis:
            raise ValueError(f"Passwort fehlt auf dem Server: Umgebungsvariable {z['variable']} setzen (nie in config.yaml) und die App neu starten")
        anmeldung = base64.b64encode(f"{z['api_benutzer']}:{geheimnis}".encode()).decode("ascii")
        return {"plattform": plattform, "name": p["name"], "basis_url": p["basis_url"], "pfad": p["test_pfad"],
                "kopf": {"Authorization": f"Basic {anmeldung}", "Accept": p["accept"], "User-Agent": "Wohnmobil-Scout (Verbindungstest)"}}

    @staticmethod
    def test_ausfuehren(t: dict, session=None) -> dict:
        """Genau EINE Anfrage; zurück nur Status und Aufbau (Schlüssel der obersten Ebene, Anzahl Einträge) – keine Inhalte."""
        abruf = ApiAbruf(t["basis_url"], t["kopf"], max_abrufe=1, pause_sek=0, timeout_sek=20, name=f"{t['name']} (Verbindungstest)",
                         session=session, versuche=1)                  # auch bei 5xx keine Wiederholung (QA B4)
        try:
            antwort = abruf.hole_json(t["pfad"])
        except QuellenFehler as e:                         # 401/403/429, HTTP-Fehler, Netz, kein JSON – nie wiederholen
            return {"ok": False, "text": str(e)[:300]}
        aufbau = sorted(antwort)[:20] if isinstance(antwort, dict) else []
        listen = {k: len(v) for k, v in antwort.items() if isinstance(v, list)} if isinstance(antwort, dict) else {}
        return {"ok": True, "text": "Verbindung hergestellt – Antwort angenommen (Aufbau siehe unten, Inhalte nicht gespeichert)",
                "aufbau": aufbau, "listen": listen}

    def test_merken(self, plattform: str, ergebnis: dict):
        text = ("OK: " if ergebnis["ok"] else "Fehler: ") + ergebnis["text"]
        if ergebnis.get("aufbau"):
            text += " · Schlüssel: " + ", ".join(ergebnis["aufbau"])
        with self.db.transaktion():
            self.con.execute("UPDATE plattform_zugaenge SET letzter_test_am=?, letzter_test_ergebnis=? WHERE plattform=?",
                             (datetime.now().isoformat(timespec="seconds"), text[:500], plattform))
