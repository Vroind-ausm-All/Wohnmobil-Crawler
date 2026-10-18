"""Einheitliche Schnittstelle für Datenquellen (Marktplätze, APIs, Feeds, manueller Import).

Eine Quelle kennt weder Datenbank noch Bewertung. Sie liefert nur `Inserat`-Objekte;
der `Importer` (wmscout/importer.py) speichert sie. Anleitung für neue Quellen: docs/QUELLEN.md
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import ClassVar, Protocol

# Wie eine Quelle angebunden ist – bestimmt auch, was rechtlich zu prüfen ist
ZUGRIFFSARTEN = {
    "api": "offizielle Programmierschnittstelle des Anbieters",
    "feed": "vom Anbieter freigegebener Datenexport (CSV/XML/JSON)",
    "web": "Abruf öffentlicher Webseiten",
    "manuell": "Daten werden vom Nutzer eingegeben oder hochgeladen",
}


# `Inserat.details["art_quelle"]`: Die Fahrzeugart dieses Treffers stammt aus dessen eigener Kategorie, die die Quelle selbst bestätigt
# (nur dann gilt sie beim Import als „bestätigt“; eine Art aus anderer Herkunft ohne dieses Kennzeichen bleibt vorläufig)
ART_QUELLE_KATEGORIE = "kategorie"


def http_url(url: str | None) -> str | None:
    """Nur ``http(s)://``-Adressen – ``javascript:`` oder ``data:`` aus einer (manipulierten) Seite landen nie als Link in der App."""
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else None


class QuellenFehler(Exception):
    """Basis für alle Fehler einer Quelle – der Importer fängt sie je Quelle ab."""


class QuelleGesperrt(QuellenFehler):
    """Die Quelle verweigert den Zugriff (HTTP 403/429, Captcha). Niemals umgehen – Lauf beenden."""


class InseratNichtGefunden(QuellenFehler):
    """Das Inserat existiert nicht mehr (z. B. HTTP 404/410)."""


class NetzwerkFehler(QuellenFehler):
    """Keine Verbindung, Zeitüberschreitung o. Ä. – der Lauf dieser Quelle wird beendet."""


class HttpFehler(QuellenFehler):
    """Unerwarteter HTTP-Status (nach Wiederholungen)."""

    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} bei {url}")
        self.status = status
        self.url = url


class Abruf(Protocol):
    """Holt eine URL als Text. Produktiv: netz.HoeflicherAbruf; in Tests ein Fake ohne Netzwerk."""

    def hole(self, url: str) -> str: ...


@dataclass
class Inserat:
    """Ein Angebot, so wie es eine Quelle liefert – bereits in einheitlichen Einheiten (€, km, Jahr)."""

    quelle: str                          # Kennung der Quelle, z. B. "kleinanzeigen"
    anzeigen_id: str                     # ID des Inserats auf der Plattform
    url: str
    titel: str | None = None
    preis: int | None = None             # Euro, ganze Zahl
    vb: bool | None = False              # Verhandlungsbasis (None = unbekannt: überschreibt beim Update nichts)
    ort: str | None = None               # „70173 Stuttgart“
    km: int | None = None
    ez_jahr: int | None = None
    marke: str | None = None
    art: str | None = None               # Fahrzeugart laut Quelle, z. B. „Teilintegrierter“
    leistung: str | None = None
    getriebe: str | None = None
    kurzbeschreibung: str | None = None
    beschreibung: str | None = None
    bild: str | None = None
    gewerblich: bool | None = None       # None = unbekannt
    ist_gesuch: bool = False             # Gesuche („Suche Wohnmobil …“) werden nicht gespeichert
    details: dict = field(default_factory=dict)   # weitere Felder der Quelle (Rohwerte)
    datum: str | None = None             # Einstelldatum laut Quelle (Rohtext)

    def als_datensatz(self) -> dict:
        """Felder für die Datenbank (Phase 1: Tabelle `anzeigen`, Schlüssel = Anzeigen-ID)."""
        d = asdict(self)
        d["id"] = d.pop("anzeigen_id")
        return d


@dataclass
class Suchauftrag:
    """Eine konfigurierte Suche (config.yaml → suchen)."""

    name: str                            # Anzeigename, wird als `suche` gespeichert (dient auch als Fahrzeugart)
    quelle: str = "kleinanzeigen"
    url: str | None = None               # bei Web-Quellen: fertige Such-URL
    parameter: dict = field(default_factory=dict)   # bei API/Feed-Quellen: Filter (ab Phase 3: Suchprofile)

    @classmethod
    def aus_config(cls, eintrag: dict) -> Suchauftrag:
        bekannt = {"name", "quelle", "url"}
        return cls(name=eintrag["name"], quelle=eintrag.get("quelle", "kleinanzeigen"), url=eintrag.get("url"),
                   parameter={k: v for k, v in eintrag.items() if k not in bekannt})


@dataclass
class Suchseite:
    """Eine Ergebnisseite. `layout_verdacht`: Seite hatte Inhalt, aber es wurde nichts erkannt."""

    nummer: int
    inserate: list[Inserat]
    layout_verdacht: bool = False
    rohdaten: str | None = None          # nur zur Diagnose bei Layout-Verdacht


class Quelle(ABC):
    """Basisklasse für alle Datenquellen.

    Pflicht: `kennung`, `name`, `zugriffsart`, `freigegeben`, `suche()`.
    Optional: `details()` (dann `unterstuetzt_details = True`).
    """

    kennung: ClassVar[str]
    name: ClassVar[str]
    zugriffsart: ClassVar[str]
    freigegeben: ClassVar[bool]          # True nur bei API/Feed mit Vertrag bzw. ausdrücklicher Erlaubnis
    hinweis: ClassVar[str] = ""          # z. B. Hinweis auf Nutzungsbedingungen
    unterstuetzt_details: ClassVar[bool] = False

    def __init__(self, cfg: dict, abruf: Abruf | None = None):
        self.cfg = cfg
        self.abruf = abruf

    @abstractmethod
    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        """Liefert Ergebnisseiten, neueste Inserate zuerst. Der Importer darf jederzeit abbrechen."""

    def details(self, url: str) -> Inserat:
        """Lädt die Detailansicht eines Inserats. Wirft InseratNichtGefunden, wenn es weg ist."""
        raise NotImplementedError(f"Quelle {self.kennung} liefert keine Detailseiten")
