"""Quelle Kleinanzeigen: Such- und Detailseiten per höflichem Web-Abruf.

Achtung: Die Nutzungsbedingungen von Kleinanzeigen untersagen automatisiertes Auslesen. Die Quelle ist deshalb
als nicht freigegeben gekennzeichnet; die Nutzung liegt in der Verantwortung des Betreibers (siehe README).
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from ...netz import HoeflicherAbruf
from ..basis import (Abruf, HttpFehler, Inserat, InseratNichtGefunden, Quelle, QuelleGesperrt, Suchauftrag,
                     Suchseite)
from .parser import name_in_details, parse_detailseite, parse_suchseite


def seiten_url(url: str, seite: int) -> str:
    """Setzt 'seite:N/' vor das letzte Pfadsegment (das mit c220...)."""
    url = re.sub(r"/seite:\d+", "", url)
    if seite <= 1:
        return url
    kopf, _, letztes = url.rpartition("/")
    return f"{kopf}/seite:{seite}/{letztes}"


def anzeigen_id_aus_url(url: str) -> str | None:
    m = re.search(r"/(\d{6,})-\d+-\d+", url or "")
    return m.group(1) if m else None


class KleinanzeigenQuelle(Quelle):
    kennung = "kleinanzeigen"
    name = "Kleinanzeigen"
    zugriffsart = "web"
    freigegeben = False
    hinweis = ("Die Nutzungsbedingungen von Kleinanzeigen untersagen automatisiertes Auslesen – "
               "Nutzung auf eigene Verantwortung.")
    unterstuetzt_details = True

    def __init__(self, cfg: dict, abruf: Abruf | None = None):
        super().__init__(cfg, abruf or HoeflicherAbruf(cfg["crawler"], self.name))
        self.max_seiten = cfg["crawler"]["max_seiten_pro_suche"]
        self.letzte_rohdaten: str | None = None      # nur zur Diagnose

    def _hole(self, url: str) -> str:
        text = self.abruf.hole(url)
        if "captcha" in text.lower()[:20000] and "aditem" not in text:
            raise QuelleGesperrt("Captcha-Seite erhalten – Lauf abgebrochen.")
        self.letzte_rohdaten = text
        return text

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        for nummer in range(1, self.max_seiten + 1):
            html = self._hole(seiten_url(auftrag.url, nummer))
            treffer = [Inserat(quelle=self.kennung, anzeigen_id=t.pop("id"), **t) for t in parse_suchseite(html)]
            verdacht = not treffer and nummer == 1 and len(html) > 20000   # volle Seite, aber nichts erkannt
            yield Suchseite(nummer, treffer, layout_verdacht=verdacht, rohdaten=html if verdacht else None)
            if not treffer:
                return

    def details(self, url: str) -> Inserat:
        try:
            html = self._hole(url)
        except HttpFehler as e:
            if e.status in (404, 410):
                raise InseratNichtGefunden(url) from e
            raise
        d = parse_detailseite(html)
        name_in_details(d)
        id_aus_seite = d.pop("anzeigen_id", None)         # Kasten „Anzeigen-ID“ – nur Ersatz, die URL gilt zuerst
        return Inserat(quelle=self.kennung, anzeigen_id=anzeigen_id_aus_url(url) or id_aus_seite or "", url=url, **d)
