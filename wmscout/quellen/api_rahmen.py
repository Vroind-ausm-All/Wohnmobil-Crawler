"""Rahmen für offizielle Programmierschnittstellen (Phase G0, ADR-030) – noch ohne freigegebene Quelle.

Ein API-Adapter erbt von ``ApiQuelle`` und liefert nur ``Inserat``-Objekte wie jede andere Quelle. Der Rahmen erzwingt, was
die Projektregeln verlangen, bevor überhaupt eine Anfrage hinausgeht:

* **Freigabe:** ``freigegeben = False`` bis ein Vertrag oder eine schriftliche Erlaubnis des Anbieters vorliegt (Regel 12);
  eine nicht freigegebene API-Quelle lässt sich nicht einmal erzeugen.
* **Zugangsdaten** nur aus Umgebungsvariablen (Name in ``zugang_variable``), nie aus ``config.yaml`` oder dem Repository (Regel 5).
* **Nur HTTPS**, feste Basis-Adresse der Klasse; Pfade aus Antworten werden nie als neue Adresse übernommen.
* **Kontingent** je Lauf (``config.yaml`` → ``api_quellen.<kennung>.max_abrufe_je_lauf``, Standard 50) und Mindestpause.
* **Abbruch statt Umgehung** bei 401/403/429 und bei erschöpftem Kontingent: ``QuelleGesperrt``, keine Wiederholung,
  kein Wechsel von Zugang oder Adresse (Regel 11). Nur 5xx wird zweimal mit Pause wiederholt.
"""
from __future__ import annotations

import os
import time
from abc import abstractmethod
from collections.abc import Iterator
from typing import ClassVar

import requests

from .basis import HttpFehler, Inserat, NetzwerkFehler, Quelle, QuelleGesperrt, QuellenFehler, Suchauftrag, Suchseite

STANDARD_KONTINGENT = 50
STANDARD_PAUSE_SEK = 1.0


class ApiAbruf:
    """JSON-Abruf gegen eine feste HTTPS-Basis mit Kontingent – ``session`` austauschbar für Tests (ohne Netz)."""

    def __init__(self, basis_url: str, kopfzeilen: dict, *, max_abrufe: int, pause_sek: float, timeout_sek: float = 20,
                 name: str = "Die API", session=None, schlafen=time.sleep, versuche: int = 3):
        if not basis_url.startswith("https://"):
            raise QuellenFehler(f"{name}: nur HTTPS-Adressen sind erlaubt")
        self.basis, self.kopf, self.name = basis_url.rstrip("/"), kopfzeilen, name
        self.max_abrufe, self.pause, self.timeout = max_abrufe, pause_sek, timeout_sek
        self.session, self.schlafen = session or requests.Session(), schlafen
        self.abrufe = 0
        self.versuche = max(1, versuche)          # Anfragen je Abruf (5xx wird bis dahin mit Pause wiederholt)

    def hole_json(self, pfad: str, parameter: dict | None = None) -> dict:
        if not pfad.startswith("/") or pfad.startswith("//") or "://" in pfad or ".." in pfad:
            raise QuellenFehler(f"{self.name}: ungültiger Pfad {pfad!r}")
        if self.abrufe >= self.max_abrufe:
            raise QuelleGesperrt(f"{self.name}: Kontingent von {self.max_abrufe} Abrufen je Lauf erreicht – Lauf beendet")
        if self.abrufe:
            self.schlafen(self.pause)
        self.abrufe += 1
        url = self.basis + pfad
        try:
            for versuch in range(self.versuche):
                r = self.session.get(url, params=parameter or {}, headers=self.kopf, timeout=self.timeout)
                if r.status_code in (401, 403, 429):
                    raise QuelleGesperrt(f"HTTP {r.status_code} – {self.name} verweigert den Zugriff (Zugang, Rechte oder Kontingent "
                                         "beim Anbieter prüfen). Keine Wiederholung.")
                if r.status_code >= 500 and versuch < self.versuche - 1:
                    self.schlafen(10 * (versuch + 1))
                    continue
                if r.status_code >= 400:
                    raise HttpFehler(r.status_code, url)
                try:
                    return r.json()
                except ValueError as e:
                    raise QuellenFehler(f"{self.name}: Antwort ist kein JSON") from e
        except requests.RequestException as e:
            raise NetzwerkFehler(f"{self.name}: Netzwerkfehler: {e}") from e
        raise HttpFehler(r.status_code, url)


class ApiQuelle(Quelle):
    """Basis für API-Adapter. Pflicht in der Unterklasse: ``kennung``, ``name``, ``basis_url``, ``zugang_variable``,
    ``kopfzeilen()``, ``suchparameter()``, ``inserate_aus()``; optional ``seiten_pfad``."""

    zugriffsart: ClassVar[str] = "api"
    freigegeben: ClassVar[bool] = False
    basis_url: ClassVar[str]
    zugang_variable: ClassVar[str]           # Name der Umgebungsvariable mit dem API-Schlüssel
    seiten_pfad: ClassVar[str] = "/search"
    max_seiten: ClassVar[int] = 10

    def __init__(self, cfg: dict, abruf=None, session=None):
        super().__init__(cfg, abruf)
        if not self.freigegeben:
            raise QuellenFehler(f"Quelle {self.name} ist nicht freigegeben (API ohne Vertrag/Erlaubnis) – Regel 12")
        schluessel = os.environ.get(self.zugang_variable, "").strip()
        if not schluessel:
            raise QuellenFehler(f"Quelle {self.name}: Zugangsdaten fehlen – Umgebungsvariable {self.zugang_variable} setzen "
                                "(nie in config.yaml)")
        c = ((cfg.get("api_quellen") or {}).get(self.kennung)) or {}
        self.api = abruf or ApiAbruf(self.basis_url, self.kopfzeilen(schluessel), name=self.name, session=session,
                                     max_abrufe=int(c.get("max_abrufe_je_lauf", STANDARD_KONTINGENT)),
                                     pause_sek=float(c.get("pause_sek", STANDARD_PAUSE_SEK)))

    @abstractmethod
    def kopfzeilen(self, schluessel: str) -> dict:
        """HTTP-Kopfzeilen mit den Zugangsdaten, wie der Anbieter sie verlangt."""

    @abstractmethod
    def suchparameter(self, auftrag: Suchauftrag, seite: int) -> dict:
        """Abfrageparameter aus ``auftrag.parameter`` (Art, Preis, EZ …) für die angegebene Seite (ab 1)."""

    @abstractmethod
    def inserate_aus(self, antwort: dict) -> list[Inserat]:
        """Treffer einer Antwortseite als ``Inserat``-Objekte – nur Felder, die der Vertrag zu speichern erlaubt."""

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        for nr in range(1, self.max_seiten + 1):
            treffer = self.inserate_aus(self.api.hole_json(self.seiten_pfad, self.suchparameter(auftrag, nr)))
            yield Suchseite(nr, treffer)
            if not treffer:
                return
