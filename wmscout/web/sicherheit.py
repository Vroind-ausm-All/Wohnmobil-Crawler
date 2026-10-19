"""Härtung der Web-App (Phase G0, ADR-030): Bremse gegen Passwort-Raten, Sicherheits-Header, Herkunftsprüfung.

Alles ohne zusätzliche Dienste und im Speicher des laufenden Servers (ein Neustart setzt die Bremse zurück – für den
Pilotbetrieb gehören zusätzlich Ratenlimits in den Reverse-Proxy, docs/PILOTBETRIEB.md).
"""
from __future__ import annotations

import threading
import time
from collections import deque

# Inline-Skripte der Vorlagen sind noch nötig ('unsafe-inline'); dennoch verhindert die Richtlinie Einbetten in fremde Seiten,
# Plugins, fremde Formularziele, <base>-Umleitung und das Nachladen fremder Skripte/Verbindungen.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
SICHERHEITS_KOPF = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer", "Permissions-Policy": "geolocation=(), microphone=()",
                    "Cross-Origin-Opener-Policy": "same-origin"}


class LoginBremse:
    """Fehlversuche je (IP, Name) und je IP in einem Zeitfenster; ab der Grenze wird bis zum Ablauf des ältesten Versuchs
    gesperrt (429). Je Paar statt je Name: ein Angreifer kann so nicht den Zugang eines Kollegen von dessen Gerät aus sperren."""

    def __init__(self, max_je_name: int = 5, max_je_ip: int = 20, fenster_sek: int = 900, uhr=time.monotonic):
        self.max_name, self.max_ip, self.fenster, self.uhr = max_je_name, max_je_ip, fenster_sek, uhr
        self._fehler: dict[tuple, deque] = {}
        self._sperre = threading.Lock()

    def _aufraeumen(self, schluessel: tuple, jetzt: float) -> deque:
        d = self._fehler.setdefault(schluessel, deque())
        while d and d[0] <= jetzt - self.fenster:
            d.popleft()
        return d

    def wartezeit(self, ip: str, name: str) -> int:
        """Sekunden bis zum nächsten erlaubten Versuch (0 = jetzt erlaubt)."""
        jetzt = self.uhr()
        with self._sperre:
            warten = 0.0
            for schluessel, grenze in ((("ip", ip), self.max_ip), (("name", ip, name.strip().lower()), self.max_name)):
                d = self._aufraeumen(schluessel, jetzt)
                if len(d) >= grenze:
                    warten = max(warten, d[0] + self.fenster - jetzt)
            return int(warten + 0.999)

    def fehlschlag(self, ip: str, name: str):
        jetzt = self.uhr()
        with self._sperre:
            for schluessel in (("ip", ip), ("name", ip, name.strip().lower())):
                self._aufraeumen(schluessel, jetzt).append(jetzt)
            if len(self._fehler) > 10_000:           # Speicher begrenzen: leere Einträge verwerfen
                for k in [k for k, d in self._fehler.items() if not d]:
                    del self._fehler[k]

    def erfolg(self, ip: str, name: str):
        with self._sperre:
            self._fehler.pop(("name", ip, name.strip().lower()), None)
