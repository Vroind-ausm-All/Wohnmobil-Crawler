"""Quellenunabhängige Inserat-Ereignisse. Keine Netzwerk- oder Datenbankzugriffe."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .domaene import pruefe_kanal, pruefe_plattform
from .quellen.basis import Inserat

EreignisTyp = Literal["neu", "geaendert", "geloescht"]
Eingangskanal = Literal["stream", "api", "email", "manuell"]          # = domaene.KANAELE


@dataclass(frozen=True)
class InseratEreignis:
    """Ein empfangenes Ereignis; Plattform und Eingangskanal sind unabhängig voneinander."""

    plattform: str
    anzeigen_id: str
    typ: EreignisTyp
    kanal: Eingangskanal
    empfangen_am: datetime
    inserat: Inserat | None = None
    ereignis_id: str | None = None

    def __post_init__(self):
        if not self.plattform.strip() or not self.anzeigen_id.strip():
            raise ValueError("Plattform und Anzeigen-ID dürfen nicht leer sein")
        if self.typ not in ("neu", "geaendert", "geloescht"):
            raise ValueError(f"Unbekannter Ereignistyp: {self.typ}")
        pruefe_kanal(self.kanal)
        if not isinstance(self.empfangen_am, datetime) or self.empfangen_am.tzinfo is None:
            raise ValueError("empfangen_am benötigt eine Zeitzone")
        if self.typ != "geloescht" and self.inserat is None:
            raise ValueError("Neue und geänderte Inserate benötigen Daten")
        if self.inserat is not None:
            if (self.inserat.quelle, self.inserat.anzeigen_id) != (self.plattform, self.anzeigen_id):
                raise ValueError("Inserat und Ereignis haben unterschiedliche Plattform-IDs")
            if self.inserat.preis is not None and self.inserat.preis < 0:
                raise ValueError("Ein Preis darf nicht negativ sein")
        pruefe_plattform(self.plattform)
        if self.ereignis_id is not None and not self.ereignis_id.strip():
            raise ValueError("ereignis_id darf nicht leer sein")
