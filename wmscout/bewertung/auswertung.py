"""Bewertet alle aktiven Inserate: Entfernung, Dubletten, Marktwert, Anschreiben, Nachfassen."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..datenbank import STATUS, Datenbank
from ..normalisierung.fahrzeug import ergaenze_fahrzeug
from ..normalisierung.geo import entfernung_km
from .anschreiben import Anschreiber, euro, sperrgrund
from .rechner import Rechner


BEARBEITET = {"kontaktiert", "verhandlung", "besichtigung", "gekauft", "abgesagt", "uninteressant"}


def finde_duplikate(alle: list[dict]) -> dict[str, list[dict]]:
    """id → andere Anzeigen desselben Fahrzeugs (gleiche Marke, EZ, PLZ, Modellreihe, km ± 3.000).

    Typisch: Verkäufer löscht die Anzeige und stellt sie neu ein, oder inseriert doppelt."""
    gruppen = defaultdict(list)
    for a in alle:
        if a.get("marke") and a.get("ez_jahr") and a.get("km") and a.get("plz"):
            gruppen[(a["marke"].lower(), a["ez_jahr"], a["plz"])].append(a)
    duplikate = {}
    for liste in gruppen.values():
        for a in liste if len(liste) > 1 else []:
            andere = [b for b in liste if b["id"] != a["id"] and abs(b["km"] - a["km"]) <= 3000
                      and (not a.get("serie") or not b.get("serie") or a["serie"] == b["serie"])]
            if andere:
                duplikate[a["id"]] = andere
    return duplikate


def _datum(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}." if iso and len(iso) >= 10 else "?"


def nachfass_grund(a: dict, cfg: dict, jetzt: datetime) -> str | None:
    """Warum jetzt nachgefasst werden sollte (oder None)."""
    nf = cfg.get("nachfassen") or {}
    letzter = max(a.get("kontaktiert_am") or "", a.get("nachgefasst_am") or "")
    if a.get("status") not in ("kontaktiert", "verhandlung", "abgesagt") or not letzter:
        return None
    if a.get("preis_geaendert_am") and a["preis_geaendert_am"] > letzter:
        return f"Preis gesenkt auf {euro(a['preis'])}"
    tage = (jetzt - datetime.fromisoformat(letzter)).days
    if (a["status"] == "kontaktiert" and tage >= nf.get("nach_tagen", 3)
            and (a.get("nachfass_anzahl") or 0) < nf.get("max_anzahl", 1)):
        return f"seit {tage} Tagen keine Antwort"
    return None


def bewerte_alle(cfg: dict, db: Datenbank, basis: Path, lauf_start: str | None = None) -> list[dict]:
    rechner, schreiber = Rechner(cfg), Anschreiber(cfg, basis)
    jetzt = datetime.now()
    standort = str(cfg["anschreiben"].get("plz") or "") or None
    alle = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    duplikate = finde_duplikate(alle)
    # Vergleichsbasis: von mehrfach eingestellten Fahrzeugen nur die aktuellste Anzeige
    vergleich = [a for a in alle if not any((b.get("zuletzt_gesehen") or "", b["id"]) > (a.get("zuletzt_gesehen") or "", a["id"])
                                            for b in duplikate.get(a["id"], []))]
    zeilen = []
    for r in db.aktive():
        a = ergaenze_fahrzeug(dict(r))
        if a.get("status") == "gelöscht":
            continue
        a["entfernung_km"] = entfernung_km(standort, a.get("plz"))
        andere = duplikate.get(a["id"], [])
        seit = min([a.get("erstmals_gesehen") or jetzt.isoformat()] + [b.get("erstmals_gesehen") or "9" for b in andere])
        a["tage_online"] = max(0, (jetzt - datetime.fromisoformat(seit)).days)
        a["neu_eingestellt"] = any((b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "") for b in andere)
        bearbeitet = [b for b in andere if b.get("status") in BEARBEITET]
        live_aelter = [b for b in andere if b.get("status") in (None, "neu")
                       and (b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "")
                       and (b.get("zuletzt_gesehen") or "") >= (a.get("zuletzt_gesehen") or "")[:10]]
        if bearbeitet:
            b0 = bearbeitet[0]
            a["duplikat"] = (f"gleiches Fahrzeug schon bearbeitet: Anzeige {b0['id']} "
                             f"({STATUS.get(b0['status'], b0['status'])} am {_datum(b0.get('status_am') or b0.get('kontaktiert_am'))})")
        elif live_aelter:
            a["duplikat"] = f"doppelt eingestellt – ältere Anzeige {live_aelter[0]['id']} ist noch online"
        b = rechner.bewerte(a, vergleich)
        sperre = sperrgrund(a, cfg)
        # Text gibt es für jede nicht gesperrte Anzeige; „bereit“ sind nur die, deren Ampel passt
        brief = schreiber.text(a, b) if not sperre else None
        grund = nachfass_grund(a, cfg, jetzt)
        nachfass_text, nachfass_betrag = schreiber.nachfass(a, b) if grund else (None, None)
        if cfg["rechner"]["differenzbesteuerung"]:
            ust = (b.haendler_vk - b.max_ek) * 19 / 119
        else:
            ust = b.haendler_vk - b.haendler_vk / 1.19
        zeilen.append({
            "a": a, "b": b, "sperre": sperre, "brief": brief, "ust": round(ust / 10) * 10,
            "bereit": bool(brief) and schreiber.soll_schreiben(b.ampel),
            "neu": bool(lauf_start and (a.get("erstmals_gesehen") or "") >= lauf_start),
            "nachfassen": grund, "nachfass_text": nachfass_text, "nachfass_betrag": nachfass_betrag,
        })
    return zeilen
