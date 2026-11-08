"""Einheitliche Schnittstelle für Push-Eingänge (ADR-035): der Nutzer liefert Daten, der Server ruft nichts ab.

`Eingang.lese(Rohdaten) -> Lesung` ist rein: keine Datenbank, kein Netz. Gespeichert wird allein über
`Importer.importiere(lesung, kanal)`. Die `Lesung` trägt neben den Inseraten auch die Herkunft der Fahrzeugart
(Art-Filter und Haupttabelle der Suchseite, ADR-020/021/022), damit jeder Kanal dieselben Regeln durchläuft.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domaene import KLEINANZEIGEN
from ..quellen.basis import Inserat
from .seiten import SuchseitenArt, erkenne_seite_mit_hinweisen, fahrzeugart_der_suchseite, haupttabelle_ids, plattform_der_seite

LESUNG_ARTEN = ("suche", "detail", "unbekannt", "detail_ohne_id")      # nur „suche“ und „detail“ werden gespeichert
STANDARD_KANAL_SEITEN = "manuell"                                      # bisheriger Wert für gespeicherte Seiten (beobachtungen.kanal)


@dataclass(frozen=True)
class Rohdaten:
    """Was ein Kanal geliefert hat (Datei, eingefügter Text, Nachricht) – unverändert, noch nicht gelesen."""

    inhalt: bytes
    name: str
    empfangen_am: datetime

    def __post_init__(self):
        if self.empfangen_am.tzinfo is None:
            raise ValueError("empfangen_am benötigt eine Zeitzone")


@dataclass
class Lesung:
    """Ergebnis von `Eingang.lese`.

    art: 'suche', 'detail' – oder 'unbekannt'/'detail_ohne_id' (nichts zu speichern; `hinweise` nennt den Grund).
    art_filter: Fahrzeugart-Angaben der Suchseite (bestätigter Filter bzw. vorläufiger Hinweis); None = keine.
    haupttreffer: Anzeigen-IDs, für die der Art-Filter gilt (nur die Haupttabelle); None = keine.
    plattform: Plattform der gelesenen Seite, soweit erkannt (für Meldungen).
    zeitpunkt: Zeitpunkt, zu dem das Angebot laut Kanal so aussah (E-Mail: Datum der Mail, sonst Dateizeit); None = jetzt. Der Importer
               übernimmt Preise aus einem Kanal mit Zeitpunkt nur, wenn er nicht älter ist als die letzte Beobachtung der Anzeige.
    nur_leere_felder: bereits gespeicherte Felder des Inserats bleiben (der Kanal liefert nur grobe, heuristisch gelesene Werte); leere
    werden gefüllt, der Preis läuft wie immer über Preis- und Beobachtungshistorie.
    preis_status: nur Text-Eingang: 'eingetragen' (vom Nutzer), 'text' (sicher erkannt), 'unsicher' oder 'fehlt' (dann ohne Preis)."""

    art: str
    inserate: list[Inserat] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    art_filter: SuchseitenArt | None = None
    haupttreffer: frozenset[str] | None = None
    plattform: str | None = None
    zeitpunkt: datetime | None = None
    nur_leere_felder: bool = False
    preis_status: str | None = None


@runtime_checkable
class Eingang(Protocol):
    kennung: str
    kanal: str

    def lese(self, roh: Rohdaten) -> Lesung:
        """Rohdaten → Lesung, ohne Datenbank und ohne Netz."""
        ...


class SeitenEingang:
    """Im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten (kapselt `erkenne_seite_mit_hinweisen`)."""

    kennung = "seiten"
    kanal = STANDARD_KANAL_SEITEN

    def lese(self, roh: Rohdaten) -> Lesung:
        html = roh.inhalt.decode("utf-8-sig", errors="replace")
        art, inserate, hinweise = erkenne_seite_mit_hinweisen(html)
        plattform = plattform_der_seite(html)
        # Art-Filter (art_s:) und Haupttabelle gibt es nur bei Kleinanzeigen; mobile.de nennt die Art je Treffer
        mit_filter = art == "suche" and plattform == KLEINANZEIGEN
        return Lesung(art, inserate, hinweise, fahrzeugart_der_suchseite(html) if mit_filter else None,
                      frozenset(haupttabelle_ids(html)) if mit_filter else None, plattform)
