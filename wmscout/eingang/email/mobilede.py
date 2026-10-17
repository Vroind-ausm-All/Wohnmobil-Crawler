"""mobile.de-Suchagent-Mails (P2-06): Absender *.mobile.de bzw. Links `…/details.html?id=<id>`.

Annahme (nachgebildet, Abnahme mit echten Mails F3 steht aus): Jedes Fahrzeug steht als eigener Block mit Titel, Preis, einer
Angabenzeile („EZ 05/2015 • 80.000 km • …“) und „PLZ Ort“; die Links gehen direkt auf mobile.de oder über einen Weiterleitungs-Link
derselben Domain mit lesbarer Ziel-Adresse. Die ID kommt aus `quellen.mobilede.anzeigen_id_aus_url` (Präfix `md-`, dieselbe ID wie beim
Seitenimport). Die Fahrzeugklasse (Wohnmobil/Pkw) nennt eine Mail nicht verlässlich – sie wird nicht geraten, die Art bleibt höchstens vorläufig.
"""
from __future__ import annotations

import re
from urllib.parse import SplitResult, urlunsplit

from ...domaene import MOBILEDE
from ...quellen.mobilede import anzeigen_id_aus_url, detail_url
from ..basis import Lesung
from .nachricht import Mail
from .treffer import PlattformParser, Profil

DOMAINS = ("mobile.de",)


_ID = re.compile(r"md-[1-9][0-9]{4,}")        # nur ASCII-Ziffern, keine führende 0 (anzeigen_id_aus_url nimmt auch andere Ziffernschriften)


def _id(teile: SplitResult) -> str | None:
    anzeigen_id = anzeigen_id_aus_url(urlunsplit(teile)) if teile.path.endswith("/details.html") else None
    return anzeigen_id if anzeigen_id and _ID.fullmatch(anzeigen_id) else None


PROFIL = Profil(MOBILEDE, "mobile.de", DOMAINS, _id, detail_url, re.compile(r"details\.html", re.I))
PARSER = PlattformParser(PROFIL)


def erkennt(mail: Mail) -> bool:
    return PARSER.erkennt(mail)


def lese(mail: Mail) -> Lesung:
    return PARSER.lese(mail)
