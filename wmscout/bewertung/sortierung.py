"""Gemeinsame Sortierung für API, Desktop und Handy.

Die Ankaufchance ordnet nach belastbarer Datenlage und Verfügbarkeit, erst danach nach
dem bestehenden Deal-Score. Sie ändert weder Marktwertformel noch gespeicherte Scores.
JSON-Schlüssel vermeiden eine zweite, abweichende Bewertungslogik im Browser.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

MODI = ("chance", "preis", "preis_ab", "neu", "score", "potenzial", "km", "verh", "prio", "entf", "tage")
ALIASE = {"pot": "potenzial", "neueste": "neu"}


def _zahl(wert) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not math.isfinite(wert):
        return None
    return wert


def _nummer(wert, absteigend: bool = False) -> tuple:
    zahl = _zahl(wert)
    return (zahl is None, (-zahl if absteigend else zahl) if zahl is not None else 0)


def _zeit(wert) -> float | None:
    """Unbekannte/defekte Zeitpunkte bleiben unbekannt; lokale ISO-Zeiten deterministisch lesen."""
    try:
        datum = datetime.fromisoformat(wert)
        return datum.replace(tzinfo=datum.tzinfo or timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def ankaufchance(z: dict) -> dict:
    """Stufe (kleiner zuerst), Belastbarkeit und verständliche Gründe einer bewerteten Zeile.

    Stufen: 0 belastbares passendes Privatangebot, 1 sonstiges belastbares Angebot,
    2 Daten nachprüfen, 3 Verfügbarkeit nachprüfen, 4 bereits in Arbeit/gesperrt,
    5 nicht verfügbar oder erledigt. Gewerbliche bleiben sichtbar; sie bekommen nur
    nicht den Vorrang eines belegten Privatangebots. Gruppen werden vorab separat dedupliziert.
    """
    a, b = z["a"], z["b"]
    qualitaet = a.get("datenqualitaet") or {}
    markierungen = qualitaet.get("markierungen") or []
    negativ = []
    positiv = []
    preis = _zahl(a.get("preis"))
    km = _zahl(a.get("km"))
    if preis is None or preis <= 0:
        negativ.append("Kaufpreis fehlt oder ist nicht belastbar")
    if not a.get("ez_jahr"):
        negativ.append("Erstzulassung fehlt")
    if km is None:
        negativ.append("Kilometerstand fehlt")
    widerspruch = bool(qualitaet.get("widersprueche")) or any(m.get("art") in ("widerspruch", "unplausibel") for m in markierungen)
    if widerspruch:
        negativ.append("Widersprüchliche oder unplausible Angaben zuerst prüfen")
    if qualitaet.get("stufe") == "schwach":
        negativ.append("Daten sind lückenhaft")
    sicherheit = getattr(b, "sicherheit", "keine")
    if sicherheit not in ("hoch", "mittel", "manuell"):
        negativ.append(f"Marktwert unsicher ({sicherheit})")
    max_ek = _zahl(getattr(b, "max_ek", None))
    if max_ek is None or max_ek <= 0:
        negativ.append("Kein belastbarer Einkaufspreis")
    belastbar = not negativ
    if belastbar:
        positiv.append("Kernangaben vollständig und Bewertung nachvollziehbar")
    anbieter = a.get("anbieter") or {}
    privat = anbieter.get("typ") == "privat" and anbieter.get("belegt", False)
    if privat:
        positiv.append("Privatanbieter belegt")
    elif anbieter.get("typ") == "gewerblich":
        negativ.append("Gewerblicher Anbieter – Konditionen gesondert prüfen")
    else:
        negativ.append("Privatanbieter nicht belegt")
    stufe = 0 if belastbar and privat else 1 if belastbar else 2
    verh = _zahl(getattr(b, "verhaeltnis", None))
    if verh is not None and verh <= 1 and belastbar:
        positiv.append("Wunschpreis liegt im berechneten Einkaufsrahmen")
    elif verh is not None and verh > 1:
        negativ.append("Wunschpreis liegt über dem berechneten Max-EK")
        stufe = max(stufe, 1)
    if a.get("vermutlich_offline") or a.get("verfuegbarkeit") == "reserviert":
        stufe = max(stufe, 3)
        negativ.append("Verfügbarkeit erneut bestätigen")
    status = a.get("status") or "neu"
    if status not in ("neu", "vorbereitet"):
        stufe = max(stufe, 4)
        negativ.append("Bereits bearbeitet")
    sperre = z.get("sperre")
    # Gewerbliche Angebote sind in der bisherigen Anschreibefunktion gesperrt. Die
    # Sortierung schließt sie deshalb nicht aus; andere fachliche Sperren bleiben sichtbar.
    if sperre and not (anbieter.get("typ") == "gewerblich" and "gewerblich" in sperre.lower()):
        stufe = max(stufe, 4)
        negativ.append(str(sperre))
    if a.get("duplikat"):
        stufe = max(stufe, 4)
        negativ.append("Weiteres Inserat desselben Fahrzeugs")
    if a.get("nicht_verfuegbar") or z.get("ausblenden") or status in ("gekauft", "abgesagt", "uninteressant", "gelöscht"):
        stufe = 5
        negativ.append("Nicht verfügbar oder abgeschlossen")
    if (z.get("neuigkeit") or {}).get("senkung"):
        positiv.append("Preissenkung erkannt")
    return {"stufe": stufe, "belastbar": belastbar, "positiv": positiv, "negativ": negativ,
            "text": (positiv + negativ)[0] if positiv or negativ else "Angaben prüfen"}


def schluessel(z: dict, modus: str = "score") -> tuple:
    """Aufsteigend vergleichbarer Schlüssel. Fehlende Zahlen stets zuletzt, dann Datum und ID.

    Beim bestehenden Modus score bleiben Score absteigend und Preis/Max-EK aufsteigend
    die primären Kriterien. Neue Tie-Breaker verhindern abhängig vom Import wechselnde Reihenfolgen.
    """
    modus = ALIASE.get(modus, modus)
    if modus not in MODI:
        raise ValueError("Unbekannte Sortierung: " + str(modus))
    a, b = z["a"], z["b"]
    chance = z.get("ankaufchance") or ankaufchance(z)
    score = (*_nummer((z.get("deal") or {}).get("score"), True), *_nummer(getattr(b, "verhaeltnis", None)))
    neu = _nummer(_zeit(a.get("erstmals_gesehen")), True)
    tie = (*neu, str(a.get("id") or ""))
    if modus == "chance":
        return (chance["stufe"], *score, *tie)
    if modus == "score":
        return (*score, *tie)
    if modus == "neu":
        return tie
    if modus == "potenzial":
        wert = getattr(b, "potenzial", None) if chance["belastbar"] and chance["stufe"] < 3 else None
        return (*_nummer(wert, True), *tie)
    if modus == "prio":
        return (*_nummer((z.get("neuigkeit") or {}).get("stufe")), *score, *tie)
    werte = {"preis": a.get("preis"), "preis_ab": a.get("preis"), "km": a.get("km"),
             "verh": getattr(b, "verhaeltnis", None), "entf": a.get("entfernung_km"), "tage": a.get("tage_online")}
    return (*_nummer(werte[modus], modus in ("preis_ab", "tage")), *tie)


def sortierdaten(z: dict) -> dict:
    """JSON-kompatible Rangfolgen für dieselbe Sortierung im Browser (keine NaN/Infinity)."""
    return {modus: list(schluessel(z, modus)) for modus in MODI}
