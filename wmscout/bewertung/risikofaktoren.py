"""Risikofaktoren je Inserat (P6-01, ADR-061): was vor einem Angebot zu prüfen ist – in einer Liste, damit die Ankaufsliste sie auf einen
Blick zeigt (Karte: die wichtigsten, Detail: alle). Nur Anzeige, keine Wirkung auf Score, Ampel oder Max-EK. Rein und quellenneutral.

Stufen: ``hoch`` (vor einem Angebot klären) und ``mittel`` (beachten). Reihenfolge: hohe zuerst, innerhalb der Stufe wie unten.
``karte`` = False, wenn die Karte denselben Punkt schon eigens zeigt (Mängelzeile, Hinweiszeile, Abzeichen) – das Detail zeigt alle.
Unvollständige Strukturen führen nie zu einer Ausnahme: ein Fehler hier legte die ganze Liste lahm (QA P6-01 B1).
"""
from __future__ import annotations

from ..normalisierung.qualitaet import UNPLAUSIBEL, WIDERSPRUCH
from .rechner import SCHWERER_MANGEL

HOCH, MITTEL = "hoch", "mittel"
LANGE_ONLINE_TAGE = 60          # länger online: oft ein Grund (Preis, Zustand) – im Gespräch klären
WEIT_EURO = 500                 # Abholung teurer als das: Aufwand einplanen
WEIT_KM = 400                   # ohne Abholkosten: Entfernung
EIGENE_ZEILE = {"maengel", "verfuegbarkeit", "ausland", "anbieter"}     # auf der Karte schon als Zeile oder Abzeichen (QA B2)


def _abholkosten(b) -> float | None:
    ab = getattr(b, "abholung", None)
    if not isinstance(ab, dict):
        return None
    euro = next((v.get("euro") for v in ab.get("varianten") or [] if isinstance(v, dict) and v.get("art") == ab.get("gewaehlt")), None)
    return float(euro) if isinstance(euro, (int, float)) else None


def _zahl(x) -> float:
    return float(x) if isinstance(x, (int, float)) else 0.0


def risikofaktoren(a: dict, b) -> list[dict]:
    """[{code, text, stufe}] – hohe zuerst. ``a`` Inserat in Rechner-Sicht (mit Verfügbarkeit, Anbieter, Datenqualität), ``b`` Bewertung."""
    erg: list[dict] = []

    def r(code: str, text: str, stufe: str):
        erg.append({"code": code, "text": text, "stufe": stufe, "karte": code not in EIGENE_ZEILE})

    s = getattr(b, "sicherheit", "keine")
    if s == "keine":
        r("bewertung", "keine belastbare Bewertung (Erstzulassung oder Marktdaten fehlen)", HOCH)
    elif s == "niedrig":
        r("bewertung", f"Bewertung unsicher ({getattr(b, 'vergleich_anzahl', '?')} Vergleiche)", HOCH)
    maengel = [m for m in getattr(b, "maengel", None) or [] if isinstance(m, dict)]
    schwer = [str(m.get("name") or "?") for m in maengel if _zahl(m.get("roh", m.get("wert"))) <= -SCHWERER_MANGEL]
    if schwer:
        r("maengel", "schwerer Mangel genannt: " + ", ".join(schwer), HOCH)
    elif maengel:
        r("maengel", "Mängel genannt: " + ", ".join(str(m.get("name") or "?") for m in maengel), MITTEL)
    if a.get("nicht_verfuegbar"):
        r("verfuegbarkeit", f"nicht mehr verfügbar ({a.get('verfuegbarkeit') or 'offline'})", HOCH)
    elif a.get("vermutlich_offline"):
        r("verfuegbarkeit", "vermutlich nicht mehr online", HOCH)
    elif a.get("verfuegbarkeit") == "reserviert":
        r("verfuegbarkeit", "reserviert", MITTEL)
    dq = a.get("datenqualitaet") or {}
    widersprueche = [m.get("text") or "" for m in dq.get("markierungen") or [] if isinstance(m, dict) and m.get("art") in (WIDERSPRUCH, UNPLAUSIBEL)]
    if widersprueche:
        r("daten", "Angaben widersprüchlich" + (": " + widersprueche[0] if widersprueche[0] else ""), HOCH)
    elif dq.get("stufe") == "schwach":
        r("daten", "Daten lückenhaft", MITTEL)
    if a.get("ausland"):
        r("ausland", f"Ausland ({a['ausland']}) – Abholung, Überführung und Zulassung", HOCH)
    else:
        kosten = _abholkosten(b)
        if kosten is not None and kosten > WEIT_EURO:
            r("abholung", f"Abholung aufwendig (ca. {round(kosten / 10) * 10:,.0f} €)".replace(",", "."), MITTEL)
        elif kosten is None and _zahl(a.get("entfernung_km")) > WEIT_KM:
            r("abholung", f"weit entfernt ({round(_zahl(a['entfernung_km'])):,} km)".replace(",", "."), MITTEL)
    typ = (a.get("anbieter") or {}).get("typ") if isinstance(a.get("anbieter"), dict) else None
    if typ == "unbekannt":
        r("anbieter", "Anbieter nicht sicher privat", MITTEL)
    elif typ == "gewerblich":
        r("anbieter", "gewerblicher Anbieter", MITTEL)
    if _zahl(a.get("tage_online")) > LANGE_ONLINE_TAGE:
        r("standzeit", f"seit {round(_zahl(a['tage_online']))} Tagen online – Grund erfragen", MITTEL)
    erg.sort(key=lambda x: x["stufe"] != HOCH)
    return erg
