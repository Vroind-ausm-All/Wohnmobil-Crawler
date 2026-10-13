"""Höflicher HTTP-Abruf für Web-Quellen: Pausen zwischen Abrufen, wenige Wiederholungen bei
Serverfehlern und sofortiger Abbruch bei Sperre. Schutzmechanismen werden nie umgangen."""
from __future__ import annotations

import random
import time

import requests

from .quellen.basis import HttpFehler, NetzwerkFehler, QuelleGesperrt


class HoeflicherAbruf:
    def __init__(self, cfg_crawler: dict, quelle_name: str = "Die Quelle"):
        self.cfg = cfg_crawler
        self.quelle_name = quelle_name
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.cfg["user_agent"],
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
        self.erster_abruf = True

    def hole(self, url: str) -> str:
        """Text der Seite. Wirft QuelleGesperrt (403/429), HttpFehler (z. B. 404) oder NetzwerkFehler."""
        if not self.erster_abruf:
            time.sleep(random.uniform(self.cfg["pause_min_sek"], self.cfg["pause_max_sek"]))
        self.erster_abruf = False
        try:
            for versuch in range(3):
                r = self.session.get(url, timeout=self.cfg["timeout_sek"])
                if r.status_code in (403, 429):
                    raise QuelleGesperrt(f"HTTP {r.status_code} – {self.quelle_name} blockt gerade. "
                                         "Später erneut versuchen.")
                if r.status_code >= 500 and versuch < 2:
                    time.sleep(20 * (versuch + 1))
                    continue
                if r.status_code >= 400:
                    raise HttpFehler(r.status_code, url)
                return r.text
        except requests.RequestException as e:
            raise NetzwerkFehler(f"Netzwerkfehler: {e}") from e
        raise HttpFehler(r.status_code, url)
