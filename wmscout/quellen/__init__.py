"""Datenquellen. Neue Quelle: Klasse von `Quelle` ableiten und hier in QUELLEN eintragen (docs/QUELLEN.md)."""
from __future__ import annotations

from .basis import (ZUGRIFFSARTEN, Abruf, HttpFehler, Inserat, InseratNichtGefunden, NetzwerkFehler, Quelle,
                    QuelleGesperrt, QuellenFehler, Suchauftrag, Suchseite)
from .kleinanzeigen import KleinanzeigenQuelle

QUELLEN: dict[str, type[Quelle]] = {q.kennung: q for q in (KleinanzeigenQuelle,)}
STANDARD_QUELLE = "kleinanzeigen"


def erstelle_quelle(kennung: str, cfg: dict, abruf: Abruf | None = None) -> Quelle:
    try:
        klasse = QUELLEN[kennung]
    except KeyError:
        raise QuellenFehler(f"Unbekannte Quelle „{kennung}“ – verfügbar: {', '.join(sorted(QUELLEN))}") from None
    return klasse(cfg, abruf)


__all__ = ["QUELLEN", "STANDARD_QUELLE", "ZUGRIFFSARTEN", "Abruf", "HttpFehler", "Inserat", "InseratNichtGefunden",
           "NetzwerkFehler", "Quelle", "QuelleGesperrt", "QuellenFehler", "Suchauftrag", "Suchseite",
           "erstelle_quelle"]
