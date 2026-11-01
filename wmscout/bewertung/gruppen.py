"""Dublettengruppen in der Ankaufsliste (P6-02, ADR-062): die Inserate desselben Fahrzeugs je Zeile (``dubletten_ids`` = Heuristik ∪
bestätigte Gruppe, ohne „verschieden“-Paare – eine Stufe, keine Hülle über Heuristik-Ketten, ADR-040) und die Auswahl für die Ansicht
„gleiches Fahrzeug nur einmal“. Nur Anzeige; Sperren, Bewertung und Team-Wirkung bleiben, wie sie sind. Rein, ohne Datenbank.
"""
from __future__ import annotations

from ..domaene import PLATTFORM_TEXT

STANDARD_QUELLE = "kleinanzeigen"
VERWORFEN = ("abgesagt", "uninteressant")       # erledigt, keine offene Arbeit – nicht vor ein frisches Inserat stellen (QA B3)


def mitglied(b: dict, bestaetigt: bool, verlauf: dict | None) -> dict:
    """Ein anderes Inserat der Gruppe, wie Karte und Detail es zeigen."""
    q = b.get("quelle") or STANDARD_QUELLE
    return {"id": b["id"], "quelle": q, "quelle_text": PLATTFORM_TEXT.get(q, q), "titel": b.get("titel"), "preis": b.get("preis"),
            "url": b.get("url"), "status": b.get("status") or "neu", "verfuegbarkeit_text": b.get("verfuegbarkeit_text"),
            "nicht_verfuegbar": bool(b.get("nicht_verfuegbar")), "bestaetigt": bestaetigt, "preisverlauf": verlauf}


def in_arbeit(a: dict) -> bool:
    """Offene Ankaufsarbeit: Status außer neu/abgesagt/uninteressant oder Reservierung, Besichtigung, Ankauf (``hat_arbeit``)."""
    return a.get("status") not in (None, "neu", *VERWORFEN) or bool(a.get("hat_arbeit"))


def _rang(z: dict) -> tuple:
    """Wer eine Gruppe vertritt: sichtbar vor ausgeblendet, offene Arbeit zuerst, verworfene zuletzt, dann Deal-Score, Preis ÷ Max-EK, ID."""
    a, s = z["a"], (z.get("deal") or {}).get("score")
    return (bool(z.get("ausblenden")), not in_arbeit(a), a.get("status") in VERWORFEN, s is None, -(s or 0),
            getattr(z["b"], "verhaeltnis", None) or 99, str(a["id"]))


def ordne(zeilen: list[dict]) -> None:
    """Setzt je Zeile ``gruppe_rang`` (Reihenfolge über alle Zeilen, 0 = zuerst gezeigt) und ``gruppe_arbeit`` (nie ausblenden)."""
    for i, z in enumerate(sorted(zeilen, key=_rang)):
        z["gruppe_rang"], z["gruppe_arbeit"] = i, in_arbeit(z["a"])


def nur_einmal(kandidaten: list[dict]) -> set[str]:
    """IDs der Zeilen, die „gleiches Fahrzeug nur einmal“ zeigt – unter den bereits gefilterten ``kandidaten``. Nach Rang: eine Zeile
    entfällt nur, wenn schon eine **gezeigte** Zeile in ihren ``dubletten_ids`` steht; Zeilen mit offener Arbeit entfallen nie (QA B2).
    So bleibt in einer Kette A~B~C (A und C verschieden) C sichtbar, wenn B wegen A entfällt (QA B1)."""
    gezeigt: set[str] = set()
    for z in sorted(kandidaten, key=lambda z: z.get("gruppe_rang", 0)):
        i = z["a"]["id"]
        if z.get("gruppe_arbeit") or not gezeigt.intersection(z.get("dubletten_ids") or ()):
            gezeigt.add(i)
    return gezeigt
