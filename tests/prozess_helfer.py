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


def schreiber(pfad: str, nr: int, anzahl: int, barriere, ergebnisse):
    """Schreibt ``anzahl`` Treffer, nachdem alle Prozesse an der Barriere stehen; meldet (nr, 'ok') oder (nr, 'FEHLER …')."""
    db = Datenbank(pfad)
    try:
        barriere.wait(60)
        for i in range(anzahl):
            db.speichere_treffer({"id": f"q{nr}-{i}", "url": f"u{nr}-{i}", "titel": "Hymer", "preis": 25000}, "Alkoven")
        ergebnisse.put((nr, "ok"))
    except Exception as e:  # noqa: BLE001 – wird vom Test als Fehler gemeldet
        ergebnisse.put((nr, f"FEHLER {type(e).__name__}: {e}"))
    finally:
        db.con.close()


def halte_laufsperre(db_pfad: str, bereit, ende):
    """Hält die Laufsperre wie ein laufender „scout.py lauf“, bis ``ende`` gesetzt wird. ``ende=None``: bis der Test den
    Prozess beendet (Absturz) – ein Event, auf das ein getöteter Prozess wartet, bliebe für immer gesperrt."""
    import time

    from wmscout.laufsperre import Laufsperre
    sperre = Laufsperre(db_pfad)
    if sperre.erwerben():
        bereit.set()
    if ende is None:
        time.sleep(120)
    else:
        ende.wait(120)
    sperre.freigeben()


def bieter(pfad: str, nr: int, auktion_id: int, standort_id: int, nutzer_id: int, betraege: list, barriere, ergebnisse):
    """Bietet je Runde ``betraege[i]``, nachdem alle Bieter an der Barriere stehen; meldet (nr, [gebot_id | 'abgelehnt' | 'FEHLER …'])."""
    from wmscout.auktion import AuktionSpeicher, AuktionsFehler
    db = Datenbank(pfad)
    speicher = AuktionSpeicher(db, {})
    erg = []
    for runde, betrag in enumerate(betraege):
        barriere.wait(60)
        try:
            erg.append(speicher.gebot_abgeben(auktion_id, standort_id, nutzer_id, betrag, f"runde-{runde}-bieter-{nr}")["gebot_id"])
        except AuktionsFehler:
            erg.append("abgelehnt")
        except Exception as e:  # noqa: BLE001 – wird vom Test als Fehler gemeldet
            erg.append(f"FEHLER {type(e).__name__}: {e}")
        erg[-1] = (erg[-1], db.con.in_transaction)
    db.con.close()
    ergebnisse.put((nr, erg))
