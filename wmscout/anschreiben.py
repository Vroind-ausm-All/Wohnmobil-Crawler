from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

AMPEL_RANG = {"gruen": 0, "gelb": 1, "rot": 2, "grau": 3}


def euro(x) -> str:
    return f"{int(x):,} €".replace(",", ".") if x is not None else "–"


def sperrgrund(a: dict, cfg: dict) -> str | None:
    """Warum diese Anzeige nicht angeschrieben werden soll (oder None)."""
    f = cfg["filter"]
    if a.get("gewerblich"):
        return "gewerblicher Anbieter"
    if a.get("status") not in (None, "neu"):
        return f"Status: {a['status']}"
    p = a.get("preis")
    if not p:
        return "kein Preis"
    if p < f["preis_min"] or p > f["preis_max"]:
        return "Preis außerhalb Filter"
    if a.get("ez_jahr") and a["ez_jahr"] < f["ez_ab_jahr"]:
        return "EZ zu alt"
    if a.get("km") and a["km"] > f["km_max"]:
        return "zu viele km"
    text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung")).lower()
    for begriff in f["sperrbegriffe"]:
        if re.search(r"(?<!\w)" + re.escape(begriff.lower()), text):
            return f"Sperrbegriff „{begriff}“"
    return None


class Anschreiber:
    def __init__(self, cfg: dict, basis: Path):
        self.cfg = cfg["anschreiben"]
        pfad = basis / self.cfg["vorlage"]
        env = Environment(loader=FileSystemLoader(str(pfad.parent)), undefined=StrictUndefined,
                          trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False)
        env.filters["euro"] = euro
        self.vorlage = env.get_template(pfad.name)

    def soll_schreiben(self, ampel: str) -> bool:
        return AMPEL_RANG.get(ampel, 3) <= AMPEL_RANG[self.cfg["ab_ampel"]]

    def text(self, a: dict, b) -> str:
        ort = a.get("ort") or ""
        ort_kurz = re.sub(r"^\d{5}\s*", "", ort) or "Ihrer Nähe"
        t = self.vorlage.render(
            titel=a.get("titel") or "Ihr Wohnmobil", marke=a.get("marke"), ez_jahr=a.get("ez_jahr"),
            km=a.get("km"), preis=a.get("preis"), ort_kurz=ort_kurz, erstangebot=b.erstangebot,
            max_ek=b.max_ek, ampel=b.ampel, firma=self.cfg["firma"], ansprechpartner=self.cfg["ansprechpartner"],
            telefon=self.cfg["telefon"], firmen_ort=self.cfg["ort"],
        )
        return re.sub(r"\n{3,}", "\n\n", t).strip()
