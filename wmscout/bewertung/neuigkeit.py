"""Neuigkeiten je Inserat: frisch eingegangen, Preis deutlich gesenkt, durch die Senkung jetzt im Rahmen (P4-03, ADR-049).

Rein (ohne Datenbank und Netz): Grundlage sind ``erstmals_gesehen``, ``preis``, ``preis_vorher`` und ``preis_geaendert_am`` der Tabelle
``anzeigen`` (die Senkung erkennt schon der Import) sowie die fertige Bewertung. Ergebnis ist eine Rangstufe für „Neuigkeiten zuerst“
und ein kurzer Text – die Bewertung, die Ampel und das Anschreiben ändern sich dadurch nicht.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .anschreiben import euro

log = logging.getLogger("scout")

# Stufen: kleiner = wichtiger
IM_RAHMEN, FRISCH_BEREIT, GESENKT, FRISCH = 1, 2, 3, 4
TEXTE = {IM_RAHMEN: "Preis gesenkt – jetzt im Rahmen", FRISCH_BEREIT: "neu, Anschreiben bereit", GESENKT: "Preis gesenkt", FRISCH: "neu eingegangen"}
# Nur offene Inserate: an kontaktierten Fahrzeugen meldet sich eine Preissenkung über „Nachfassen“
OFFENE_STATUS = (None, "neu", "vorbereitet")
STANDARD = {"frisch_stunden": 48, "senkung_tage": 14, "senkung_min_prozent": 3, "senkung_min_euro": 500}
GRENZEN = {"frisch_stunden": (1, 24 * 60), "senkung_tage": (1, 365), "senkung_min_prozent": (0, 100), "senkung_min_euro": (0, 1_000_000)}


def einstellungen(cfg: dict | None) -> dict:
    """``neuigkeiten`` aus config.yaml; jeder unbrauchbare Wert ergibt den Standard (die Anzeige darf an einer Fehleingabe nicht scheitern)."""
    abschnitt = (cfg or {}).get("neuigkeiten")
    abschnitt = abschnitt if isinstance(abschnitt, dict) else {}
    erg = {}
    for name, standard in STANDARD.items():
        wert, (unten, oben) = abschnitt.get(name, standard), GRENZEN[name]
        if isinstance(wert, bool) or not isinstance(wert, int) or not unten <= wert <= oben:
            log.warning("config.yaml: neuigkeiten -> %s muss eine ganze Zahl von %d bis %d sein, nicht %r – es gilt %d", name, unten, oben, wert, standard)
            wert = standard
        erg[name] = wert
    return erg


def _zeit(iso) -> datetime | None:
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None) if isinstance(iso, str) and iso else None
    except ValueError:
        return None


def senkung(a: dict, jetzt: datetime, e: dict, nur_deutlich: bool = True) -> dict | None:
    """Letzte Preissenkung, wenn sie innerhalb von ``senkung_tage`` lag, der Preis noch darunter liegt und sie deutlich ist (mindestens
    ``senkung_min_prozent`` Prozent **oder** ``senkung_min_euro`` Euro; ``nur_deutlich=False``: jede). Sonst None."""
    vorher, preis, am = a.get("preis_vorher"), a.get("preis"), _zeit(a.get("preis_geaendert_am"))
    if not (isinstance(vorher, int) and isinstance(preis, int) and am) or isinstance(vorher, bool) or not 0 < preis < vorher:
        return None
    if am < jetzt - timedelta(days=e["senkung_tage"]) or am > jetzt + timedelta(minutes=5):
        return None
    differenz = vorher - preis
    prozent = differenz * 100 / vorher
    if nur_deutlich and prozent < e["senkung_min_prozent"] and differenz < e["senkung_min_euro"]:
        return None
    return {"von": vorher, "auf": preis, "euro": differenz, "prozent": round(prozent, 1), "am": a["preis_geaendert_am"]}


def neuigkeit(a: dict, b, bereit: bool, ausblenden: bool, jetzt: datetime, e: dict, sperre: str | None = None) -> dict | None:
    """Rangstufe und Text eines offenen, sichtbaren, nicht gesperrten Inserats (``b``: Bewertung mit ``max_ek`` und ``sicherheit``) oder None.
    Gesperrt (gewerblich, doppelt eingestellt, Ausschlussbegriff, außerhalb des Filters …) ist keine Ankaufsgelegenheit – auch nicht nach
    einer Senkung. *Im Rahmen*: eine Senkung – auch eine kleine – hat den Preis von über auf höchstens den Max-EK gebracht (nur bei
    belastbarer Bewertung)."""
    if ausblenden or sperre or a.get("status") not in OFFENE_STATUS:
        return None
    s = senkung(a, jetzt, e)
    roh = s or senkung(a, jetzt, e, nur_deutlich=False)
    erst = _zeit(a.get("erstmals_gesehen"))
    frisch = bool(erst and jetzt - timedelta(hours=e["frisch_stunden"]) <= erst <= jetzt + timedelta(minutes=5))
    max_ek = b.max_ek if getattr(b, "sicherheit", "keine") != "keine" else None
    im_rahmen = bool(roh and max_ek and roh["auf"] <= max_ek < roh["von"])
    if im_rahmen:
        s = roh
    if im_rahmen:
        stufe = IM_RAHMEN
    elif frisch and bereit:
        stufe = FRISCH_BEREIT
    elif s:
        stufe = GESENKT
    elif frisch:
        stufe = FRISCH
    else:
        return None
    text = TEXTE[stufe]
    if s:
        text += f" (−{euro(s['euro'])}, {s['am'][8:10]}.{s['am'][5:7]}.)"
    return {"stufe": stufe, "text": text, "frisch": frisch, "senkung": s, "im_rahmen": im_rahmen}


def gesenkt_seit(zeilen: list[dict], seit: str | None) -> list[dict]:
    """Zeilen mit gemeldeter Senkung ab ``seit`` (ISO, lokal) – für Hinweis und Mail nach einem Suchlauf; ohne ``seit`` keine. Mehrere
    Inserate desselben Fahrzeugs (``dubletten_ids``) zählen einmal: gemeldet wird das wichtigste."""
    if not seit:
        return []
    treffer = sorted((z for z in zeilen if (z.get("neuigkeit") or {}).get("senkung") and z["neuigkeit"]["senkung"]["am"] >= seit),
                     key=lambda z: (z["neuigkeit"].get("stufe", 9), (z.get("a") or {}).get("preis") or 0))
    erg, gesehen = [], set()
    for z in treffer:
        fahrzeug = {(z.get("a") or {}).get("id"), *z.get("dubletten_ids", ())} - {None}
        if fahrzeug and fahrzeug & gesehen:
            continue
        gesehen |= fahrzeug
        erg.append(z)
    return erg
