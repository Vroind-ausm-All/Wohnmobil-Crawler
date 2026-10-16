"""Live-Aktualisierung per Server-Sent Events (G1, ADR-032).

Der Server meldet nur, *dass* sich etwas geändert hat (Art, bei Team-Zugängen auch die ID) – nie Inhalte. Jede Seite lädt danach
über ihre gewohnten, rechtegeprüften Routen nach. Damit kann ein Ereignis keine Daten an Unbefugte geben, und ohne SSE (Proxy puffert,
Verbindung weg) bleibt das bisherige Abfragen in Abständen als Rückfall bestehen.

Alles im Speicher des Servers: kein zusätzlicher Dienst, kein Datenbankzugriff. Je Verbindung ein Thread des ThreadingHTTPServer;
deshalb Obergrenzen je Nutzer und insgesamt sowie eine begrenzte Lebensdauer (danach verbindet der Browser selbst neu und die
Anmeldung wird erneut geprüft).
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque

# POST-Pfad → Art des Ereignisses (erste Übereinstimmung zählt). Händler erhalten nur „auktion“ – ohne ID.
_ARTEN = (
    (re.compile(r"/api/haendler/auktion/(\d+)/"), "auktion"),
    (re.compile(r"/api/auktion/(\d+)/"), "auktion"),
    (re.compile(r"/api/verkaufsanfrage/(\d+)/auktion"), "auktion"),
    (re.compile(r"/api/verkaufsanfrage/(\d+)"), "anfrage"),
    (re.compile(r"/api/verkaufsanfrage$"), "anfrage"),
    (re.compile(r"/api/ankauf/(\d+)/"), "ankauf"),
    (re.compile(r"/api/besichtigung/(\d+)/abschluss"), "ankauf"),
    (re.compile(r"/api/besichtigung"), "besichtigung"),
    (re.compile(r"/api/(bearbeitung|status|notiz|nachfassen|angebot)"), "team"),
)
HAENDLER_ARTEN = {"auktion"}


def art_fuer(pfad: str) -> tuple[str, int | None] | None:
    for muster, art in _ARTEN:
        if m := muster.match(pfad):
            return art, (int(m.group(1)) if m.groups() and m.group(1) and m.group(1).isdigit() else None)
    return None


class Ereignisse:
    def __init__(self, max_je_nutzer: int = 4, max_gesamt: int = 40, puffer: int = 500, uhr=time.monotonic):
        self.max_je_nutzer, self.max_gesamt, self.uhr = max_je_nutzer, max_gesamt, uhr
        self._bedingung = threading.Condition()
        self._liste: deque[tuple[int, str, int | None]] = deque(maxlen=puffer)
        self.stand = 0
        self._offen: dict = {}

    # ---------- melden ----------
    def melde(self, art: str, objekt_id: int | None = None):
        with self._bedingung:
            self.stand += 1
            self._liste.append((self.stand, art, objekt_id))
            self._bedingung.notify_all()

    def seit(self, stand: int, haendler: bool) -> tuple[list[dict], bool, int]:
        """Ereignisse nach ``stand`` (für die Rolle gefiltert), ob dazwischen etwas aus dem Puffer gefallen ist (dann: alles neu
        laden) und der neueste Stand – auch wenn kein Ereignis für diese Rolle dabei war."""
        with self._bedingung:
            luecke = bool(self._liste) and stand < self._liste[0][0] - 1
            neu, aktuell = [e for e in self._liste if e[0] > stand], self.stand
        if haendler:
            return [{"stand": s, "art": a} for s, a, _ in neu if a in HAENDLER_ARTEN], luecke, aktuell
        return [{"stand": s, "art": a, "id": i} for s, a, i in neu], luecke, aktuell

    def warte(self, stand: int, sekunden: float) -> bool:
        with self._bedingung:
            return self._bedingung.wait_for(lambda: self.stand > stand, timeout=sekunden)

    # ---------- Verbindungen begrenzen ----------
    def oeffnen(self, nutzer_schluessel) -> bool:
        with self._bedingung:
            if sum(self._offen.values()) >= self.max_gesamt or self._offen.get(nutzer_schluessel, 0) >= self.max_je_nutzer:
                return False
            self._offen[nutzer_schluessel] = self._offen.get(nutzer_schluessel, 0) + 1
            return True

    def schliessen(self, nutzer_schluessel):
        with self._bedingung:
            n = self._offen.get(nutzer_schluessel, 0) - 1
            if n > 0:
                self._offen[nutzer_schluessel] = n
            else:
                self._offen.pop(nutzer_schluessel, None)

    def offen(self) -> int:
        with self._bedingung:
            return sum(self._offen.values())


def sse_block(ereignis: dict | None = None, kommentar: str | None = None, retry_ms: int | None = None) -> bytes:
    zeilen = []
    if retry_ms:
        zeilen.append(f"retry: {int(retry_ms)}")
    if kommentar:
        zeilen.append(f": {kommentar}")
    if ereignis is not None:
        if "stand" in ereignis:
            zeilen.append(f"id: {int(ereignis['stand'])}")
        zeilen.append("event: aenderung")
        zeilen.append("data: " + json.dumps(ereignis, ensure_ascii=False))
    return ("\n".join(zeilen) + "\n\n").encode("utf-8")
