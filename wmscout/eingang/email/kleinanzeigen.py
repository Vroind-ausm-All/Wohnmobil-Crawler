"""Kleinanzeigen-Suchagent-Mails (P2-06): Absender *.kleinanzeigen.de bzw. Links `…/s-anzeige/<slug>/<id>-<kat>-<region>`.

Annahme (nachgebildet, Abnahme mit echten Mails F3 steht aus): Jede Anzeige steht als eigener Block mit Titel, Preis und
„PLZ Ort“; die Links gehen direkt auf kleinanzeigen.de oder über einen Weiterleitungs-Link derselben Domain, der die Ziel-Adresse
in einem Parameter trägt. Undurchsichtige Tracking-Token ohne lesbare Ziel-Adresse werden nicht aufgelöst (kein Abruf).
"""
from __future__ import annotations

import re
from urllib.parse import SplitResult

from ...domaene import KLEINANZEIGEN
from ...quellen.kleinanzeigen.parser import BASIS
from ..basis import Lesung
from .nachricht import Mail
from .treffer import PlattformParser, Profil

DOMAINS = ("kleinanzeigen.de", "ebay-kleinanzeigen.de")
# /s-anzeige/<slug>/<id>-<kat>-<region> (mit Kategorie und Region) oder die kurze Form /s-anzeige/<id>; ID nur ASCII-Ziffern, ohne führende 0
_ANZEIGE = re.compile(r"^/s-anzeige/(?:[^/]+/([1-9][0-9]{5,})-[0-9]+-[0-9]+|([1-9][0-9]{5,}))/?$")


def _id(teile: SplitResult) -> str | None:
    m = _ANZEIGE.match(teile.path)
    return (m.group(1) or m.group(2)) if m else None


def detail_url(anzeigen_id: str) -> str:
    """Kurze Adresse der Anzeige, aus der ID gebildet (nie der Link aus der Mail)."""
    return f"{BASIS}/s-anzeige/{anzeigen_id}"


PROFIL = Profil(KLEINANZEIGEN, "Kleinanzeigen", DOMAINS, _id, detail_url, re.compile(r"/s-anzeige/", re.I), gesuche=True)
PARSER = PlattformParser(PROFIL)


def erkennt(mail: Mail) -> bool:
    return PARSER.erkennt(mail)


def lese(mail: Mail) -> Lesung:
    return PARSER.lese(mail)
