"""Audit-Protokoll (G0b, ADR-031): wer hat wann welche Personendaten gelesen oder etwas geändert.

Gespeichert werden nur Zeitpunkt, Nutzer, Rolle, IP, Methode, Pfad, Status und das betroffene Objekt – nie Inhalte der Anfrage,
Passwörter oder Kontaktdaten. Die Tabelle ist nur anfügbar (Trigger, Schema v10). Ohne angelegte Nutzer (Einzelplatz) wird
nichts protokolliert: dann gibt es niemanden, dessen Zugriffe zu unterscheiden wären.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timedelta

from .datenbank import Datenbank

# Lesende Zugriffe auf Personendaten von Verkäufern (Name, Kontakt, Anschrift, Unterschriften, Fotos, Vertrag)
_LESEN = (
    (re.compile(r"/api/verkaufsanfrage/(\d+)"), "anfrage"),
    (re.compile(r"/anfrage-fotos/(\d+)/.+"), "anfrage"),
    (re.compile(r"/api/besichtigung/(\d+)"), "besichtigung"),
    (re.compile(r"/protokoll/(\d+)"), "besichtigung"),
    (re.compile(r"/api/fahrzeug/anfrage-(\d+)"), "anfrage"),
    (re.compile(r"/fotos/(\d+)/.+"), "besichtigung"),
    (re.compile(r"/api/ankauf/(\d+)"), "ankauf"),
    (re.compile(r"/ankauf/(\d+)/vertrag"), "ankauf"),
    (re.compile(r"/ankauf-dokumente/(\d+)/.+"), "ankauf"),
    (re.compile(r"/api/audit"), "audit"),
)
_OBJEKT = re.compile(r"/(verkaufsanfrage|besichtigung|ankauf|auktion|anzeige|bearbeitung|nutzer|standorte|kalkulation)/([\w-]+)")


def einordnen(methode: str, pfad: str) -> tuple[str, str | None] | None:
    """(Aktion, Objekt) oder None, wenn der Zugriff nicht protokolliert wird. Jede Änderung (POST) zählt; gelesen nur Personendaten."""
    if methode == "POST":
        if pfad in ("/api/login", "/api/logout"):
            return pfad.rsplit("/", 1)[1], None
        m = _OBJEKT.search(pfad)
        return "aendern", (f"{m.group(1)}:{m.group(2)}" if m else None)
    if methode == "GET":
        for muster, art in _LESEN:
            if m := muster.fullmatch(pfad):
                return "lesen", (f"{art}:{m.group(1)}" if m.groups() else art)
    return None


class AuditSpeicher:
    """Eigene Verbindung: Ein Audit-Eintrag berührt nie die Transaktion der gemeinsamen App-Verbindung und wartet bei gesperrter
    Datenbank höchstens kurz (der Eintrag geht dann verloren und wird im Log vermerkt)."""

    def __init__(self, db: Datenbank, wartezeit: float = 3):
        pfad = db.con.execute("PRAGMA database_list").fetchone()[2]
        self.con = sqlite3.connect(pfad, check_same_thread=False, timeout=wartezeit, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self._sperre = threading.Lock()

    def schreibe(self, nutzer: dict | None, ip: str, methode: str, pfad: str, status: int, aktion: str, objekt: str | None,
                 name: str | None = None):
        """Ein Eintrag. ``name`` ersetzt den Nutzernamen bei der Anmeldung (Nutzer ist dann noch unbekannt)."""
        n = nutzer or {}
        with self._sperre:
            self.con.execute("INSERT INTO audit (zeitpunkt, nutzer_id, nutzer, rolle, ip, methode, pfad, status, aktion, objekt) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?)",          # autocommit: eine Anweisung, keine offene Transaktion
                             (datetime.now().isoformat(timespec="seconds"), n.get("id"), (name or n.get("name") or "")[:60] or None,
                              n.get("rolle"), ip[:64], methode, pfad[:200], int(status), aktion, objekt))

    def liste(self, *, tage: int = 30, nutzer: str | None = None, objekt: str | None = None, limit: int = 500) -> list[dict]:
        seit = (datetime.now() - timedelta(days=max(0, tage))).isoformat(timespec="seconds")
        sql, werte = "SELECT * FROM audit WHERE zeitpunkt >= ?", [seit]
        if nutzer:
            sql += " AND nutzer = ? COLLATE NOCASE"
            werte.append(nutzer)
        if objekt:
            sql += " AND objekt = ?"
            werte.append(objekt)
        sql += " ORDER BY id DESC LIMIT ?"
        werte.append(max(1, min(int(limit), 5000)))
        with self._sperre:
            return [dict(r) for r in self.con.execute(sql, werte)]
