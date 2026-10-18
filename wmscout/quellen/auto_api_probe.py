"""Isolierter Auto-API-Probeadapter – nicht produktiv registriert.

Das tatsächliche Antwortschema für Wohnmobile ist noch nicht validiert.
Kein Netzwerkzugriff ohne injizierten Testclient; keine neuen Abhängigkeiten.
"""
from __future__ import annotations

from collections.abc import Iterator

from .basis import Inserat, Quelle, QuellenFehler, Suchauftrag, Suchseite, http_url


def _zahl(wert) -> int | None:
    if isinstance(wert, bool) or wert is None:
        return None
    if isinstance(wert, int):
        return wert if wert >= 0 else None
    if isinstance(wert, str) and wert.strip().isdigit():
        return int(wert.strip())
    return None


def normalisiere_angebot(angebot: dict, plattform: str) -> Inserat:
    """Konservatives Mapping für synthetische API-Testantworten."""
    if not isinstance(angebot, dict):
        raise QuellenFehler("Auto API: Eintrag muss ein Objekt sein")
    original_id = angebot.get("id")
    url = http_url(angebot.get("url"))
    if original_id is None or isinstance(original_id, bool) or not str(original_id).strip() or not url:
        raise QuellenFehler("Auto API: Inserat ohne gültige ID/URL")
    if plattform not in ("mobilede", "autoscout24"):
        raise QuellenFehler("Auto API: unbekannte Plattform")
    preis = _zahl(angebot.get("price"))
    km = _zahl(angebot.get("mileage"))
    jahr = _zahl(angebot.get("year"))
    if jahr is not None and not 1900 <= jahr <= 2100:
        jahr = None
    privat = angebot.get("is_private")
    return Inserat(
        quelle=f"auto_api_{plattform}",
        anzeigen_id=f"auto_api_{plattform}:{str(original_id).strip()}",
        url=url,
        titel=angebot.get("title") if isinstance(angebot.get("title"), str) else None,
        preis=preis,
        km=km,
        ez_jahr=jahr,
        marke=angebot.get("brand") if isinstance(angebot.get("brand"), str) else None,
        ort=angebot.get("location") if isinstance(angebot.get("location"), str) else None,
        gewerblich=not privat if isinstance(privat, bool) else None,
    )


class AutoApiQuelle(Quelle):
    """Explizit injizierter Testclient; nicht in QUELLEN registrieren."""

    kennung = "auto_api_probe"
    name = "Auto API (Testadapter)"
    zugriffsart = "api"
    freigegeben = False
    hinweis = "Nicht produktiv: Rechte und Wohnmobil-Feldschema ungeprüft"

    def __init__(self, cfg: dict, abruf=None, *, client=None):
        super().__init__(cfg, abruf)
        if client is None:
            raise QuellenFehler("Auto API: deaktiviert; nur Testclient zulässig")
        self.client = client

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        plattform = auftrag.parameter.get("plattform")
        if plattform not in ("mobilede", "autoscout24"):
            raise QuellenFehler("Auto API: Plattform muss mobilede oder autoscout24 sein")
        max_seiten = auftrag.parameter.get("max_seiten", 1)
        if isinstance(max_seiten, bool) or not isinstance(max_seiten, int) or not 1 <= max_seiten <= 3:
            raise QuellenFehler("Auto API: max_seiten muss zwischen 1 und 3 liegen")
        for seite in range(1, max_seiten + 1):
            try:
                antwort = self.client.get_offers(plattform, page=seite)
            except Exception as exc:
                raise QuellenFehler(f"Auto API: Testclient-Fehler ({type(exc).__name__})") from exc
            if not isinstance(antwort, dict) or not isinstance(antwort.get("offers"), list):
                raise QuellenFehler("Auto API: unbekanntes Antwortformat (erwartet offers-Liste)")
            daten = [normalisiere_angebot(x, plattform) for x in antwort["offers"]]
            yield Suchseite(nummer=seite, inserate=daten)
            # meta.next_page ist laut offizieller Client-README dokumentiert.
            meta = antwort.get("meta")
            if not daten or (isinstance(meta, dict) and meta.get("next_page") is None and "next_page" in meta):
                return
