"""Arbeiter für den Wettlauf über echte Prozesse (multiprocessing, spawn): importierbar, ohne pytest."""
from __future__ import annotations

from wmscout.bearbeitung import BearbeitungsKonflikt
from wmscout.datenbank import Datenbank


def arbeiter(pfad: str, nutzer_id: int, aufgaben: list, barriere, ergebnisse):
    """Je Aufgabe (art, anzeige_id, dubletten): an der Barriere gleichzeitig loslaufen, Ergebnis True/False/'konflikt'/'FEHLER …'."""
    db = Datenbank(pfad)
    erg = []
    for art, ad_id, dubletten in aufgaben:
        barriere.wait(60)
        try:
            if art == "u":
                r = db.uebernimm(ad_id, nutzer_id, "2026-10-14T09:00:00", "", False, dubletten)
            elif art == "k":
                r = db.setze_status(ad_id, "kontaktiert", text=f"T{nutzer_id}", nutzer_id=nutzer_id, dubletten=dubletten)
            else:
                r = db.setze_status(ad_id, "verhandlung", nutzer_id=nutzer_id, dubletten=dubletten)
        except BearbeitungsKonflikt:
            r = "konflikt"
        except Exception as e:  # noqa: BLE001 – wird vom Test als Fehler gemeldet
            r = f"FEHLER {type(e).__name__}: {e}"
        erg.append((r, db.con.in_transaction))
    ergebnisse.put((nutzer_id, erg))
