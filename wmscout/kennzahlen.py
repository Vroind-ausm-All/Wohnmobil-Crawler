"""Kennzahlen-Ansicht (P6-05, ADR-065): die Erfolgskennzahlen aus ``docs/ROADMAP.md`` an einer Stelle – Eingang (aus der Abdeckungsmessung,
P4-05), Bewertung des aktuellen Bestands und der Ankaufstrichter im Zeitraum (bestätigte Kontakte → Antworten → Besichtigungen → Ankäufe).

Nur lesen, keine Wirkung auf Bewertung oder Suche, keine Personendaten und keine Kauf- oder Verkaufspreise (die stehen in der Kalibrierung,
nur für den Inhaber). Quoten und Mediane erst ab ``MIN_FAELLE`` Fällen – darunter „zu wenige Fälle“ statt falscher Genauigkeit.
Oben die Fachlogik ohne Datenbank, unten das Einsammeln der Daten.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median

from .abdeckung import beginn, fahrzeuge

MIN_FAELLE = 5


def _anteil(teil: int, ganz: int) -> float | None:
    return round(teil / ganz, 3) if ganz >= MIN_FAELLE else None


def _zeit(iso) -> datetime | None:
    try:
        t = datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t and t.tzinfo else t


def bewertungslage(zeilen: list[dict]) -> dict:
    """Aktueller Bestand (sichtbare Inserate): Marktwertunsicherheit (Median der relativen Spannenbreite), Sicherheit, Ampel und priorisierte
    Ankaufsangebote – Fahrzeuge mit Dubletten einmal gezählt."""
    sichtbar = [z for z in zeilen if not z.get("ausblenden")]
    breiten = [(z["b"].spanne_bis - z["b"].spanne_von) / z["b"].marktwert_angebote for z in sichtbar
               if getattr(z["b"], "sicherheit", "keine") != "keine" and getattr(z["b"], "marktwert_angebote", None)
               and getattr(z["b"], "spanne_bis", None) is not None and getattr(z["b"], "spanne_von", None) is not None]
    top = [z for z in sichtbar if (z.get("deal") or {}).get("priorisiert")]
    sicherheit: dict[str, int] = {}
    ampel: dict[str, int] = {}
    for z in sichtbar:
        sicherheit[getattr(z["b"], "sicherheit", "keine")] = sicherheit.get(getattr(z["b"], "sicherheit", "keine"), 0) + 1
        ampel[z["b"].ampel] = ampel.get(z["b"].ampel, 0) + 1
    return {"inserate": len(sichtbar), "fahrzeuge": len(fahrzeuge(sichtbar)),
            "unsicherheit_median": round(median(breiten), 2) if len(breiten) >= MIN_FAELLE else None, "unsicherheit_faelle": len(breiten),
            "priorisiert_inserate": len(top), "priorisiert_fahrzeuge": len(fahrzeuge(top)),
            "sicherheit": {s: sicherheit.get(s, 0) for s in ("hoch", "mittel", "niedrig", "keine", "manuell") if sicherheit.get(s)},
            "ampel": {a: ampel.get(a, 0) for a in ("gruen", "gelb", "rot", "grau") if ampel.get(a)}}


def trichter(erste_kontakte: dict[str, str], antworten: dict[str, list[str]], besichtigt: set[str], gekauft: set[str],
             seit: datetime) -> dict:
    """Ankaufstrichter über die Fahrzeuge (bzw. Inserate ohne Fahrzeuggruppe), deren **erster** bestätigter Kontakt im Zeitraum liegt
    (``erste_kontakte``: Schlüssel → Zeitpunkt). ``antworten``: Schlüssel → Zeitpunkte der eingetragenen Antworten (jederzeit),
    ``besichtigt``/``gekauft``: Schlüssel mit (nicht abgebrochener) Besichtigung bzw. Ankauf (jederzeit).
    Antwortzeit = erste Antwort nach dem ersten Kontakt, als Median in Tagen (eine Nachkommastelle)."""
    kontaktiert = {i: t for i, t in erste_kontakte.items() if (_zeit(t) or datetime.min) >= seit}
    zeiten = []
    beantwortet = set()
    for i, t in kontaktiert.items():
        nach = sorted(a for a in antworten.get(i, ()) if a >= t)
        if nach:
            beantwortet.add(i)
            k, a = _zeit(t), _zeit(nach[0])
            if k and a:
                zeiten.append((a - k).total_seconds() / 86400)
    n = len(kontaktiert)
    bes = besichtigt & set(kontaktiert)
    kauf = gekauft & set(kontaktiert)
    return {"kontaktiert": n, "beantwortet": len(beantwortet), "besichtigt": len(bes), "gekauft": len(kauf),
            "antwortquote": _anteil(len(beantwortet), n), "besichtigungsquote": _anteil(len(bes), n), "ankaufsquote": _anteil(len(kauf), n),
            "antwortzeit_tage": round(median(zeiten), 1) if len(zeiten) >= MIN_FAELLE else None, "antwortzeit_faelle": len(zeiten)}


def auswerten(abdeckung_erg: dict, zeilen: list[dict], trichter_erg: dict, im_zeitraum: dict, jetzt: datetime, tage: int) -> dict:
    """Alles zusammen. ``abdeckung_erg``: Ergebnis von ``abdeckung.messe`` für denselben Zeitraum; ``im_zeitraum``: Ereignisse im Zeitraum
    (bestätigte Kontakte, Antworten, Besichtigungen, Ankäufe – unabhängig vom Kontaktzeitpunkt)."""
    return {"tage": tage, "von": beginn(jetzt, tage).isoformat(timespec="seconds"), "bis": jetzt.isoformat(timespec="seconds"),
            "eingang": abdeckung_erg["kennzahlen"], "bewertung": bewertungslage(zeilen), "trichter": trichter_erg, "im_zeitraum": im_zeitraum,
            "min_faelle": MIN_FAELLE}


# ---------------------------------------------------------------- Daten einsammeln
def _tabellen(db) -> set[str]:
    return {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def messe(cfg: dict, db, abdeckung_erg: dict, zeilen: list[dict], tage: int, jetzt: datetime | None = None) -> dict:
    """Zeitraum ``tage`` bis ``jetzt`` (nur lesen). ``zeilen``: die aktuell bewerteten Inserate der App; ``abdeckung_erg`` aus der
    (zwischengespeicherten) Abdeckungsmessung desselben Zeitraums."""
    jetzt = jetzt or datetime.now()
    seit = beginn(jetzt, tage)
    seit_iso = seit.isoformat(timespec="seconds")
    t = _tabellen(db)
    # je Fahrzeug (bestätigte Dubletten zusammen, wie Kontaktverlauf und Verhandlung im Detail; QA B2), sonst je Inserat
    from .datenbank import STANDARD_PLATTFORM
    fahrzeug = {r[0]: f"f{r[1]}" for r in db.con.execute(
        "SELECT a.id, i.fahrzeug_id FROM anzeigen a JOIN inserate i ON i.plattform = COALESCE(NULLIF(a.quelle, ''), ?) AND i.anzeigen_id = a.id "
        "WHERE i.fahrzeug_id IS NOT NULL", (STANDARD_PLATTFORM,))} if "inserate" in t else {}

    def schluessel(anzeige_id: str) -> str:
        return fahrzeug.get(anzeige_id, anzeige_id)
    erste: dict[str, str] = {}
    if "kontakte" in t:
        for i, am in db.con.execute("SELECT anzeige_id, MIN(bestaetigt_am) FROM kontakte WHERE bestaetigt_am IS NOT NULL GROUP BY anzeige_id"):
            s = schluessel(i)
            erste[s] = min(erste.get(s, am), am)
    antworten: dict[str, list[str]] = {}
    if "verhandlung" in t:
        for i, z in db.con.execute("SELECT anzeige_id, zeitpunkt FROM verhandlung WHERE art='antwort'"):
            antworten.setdefault(schluessel(i), []).append(z)
    besichtigt = {schluessel(r[0]) for r in db.con.execute(
        "SELECT DISTINCT anzeige_id FROM besichtigungen WHERE anzeige_id IS NOT NULL AND status <> 'abgebrochen'")}
    # Ankauf = Ankaufsvorgang (Phase F, nicht storniert) oder – älter, ohne Ankaufsvorgang – abgeschlossene Besichtigung mit Endpreis;
    # eine Besichtigung mit storniertem Vorgang ist kein Ankauf (QA B1)
    ohne_vorgang = " AND id NOT IN (SELECT besichtigung_id FROM ankaeufe)" if "ankaeufe" in t else ""
    gekauft = {schluessel(r[0]) for r in db.con.execute("SELECT anzeige_id FROM besichtigungen WHERE anzeige_id IS NOT NULL "
                                                         "AND status='abgeschlossen' AND endpreis IS NOT NULL" + ohne_vorgang)}
    if "ankaeufe" in t:
        gekauft |= {schluessel(r[0]) for r in db.con.execute("SELECT anzeige_id FROM ankaeufe WHERE anzeige_id IS NOT NULL AND status <> 'storniert'")}
    im = {
        "kontakte": db.con.execute("SELECT COUNT(*) FROM kontakte WHERE bestaetigt_am >= ?", (seit_iso,)).fetchone()[0] if "kontakte" in t else 0,
        "kontaktierte": len({schluessel(r[0]) for r in db.con.execute("SELECT DISTINCT anzeige_id FROM kontakte WHERE bestaetigt_am >= ?",
                                                                       (seit_iso,))}) if "kontakte" in t else 0,
        "antworten": db.con.execute("SELECT COUNT(*) FROM verhandlung WHERE art='antwort' AND zeitpunkt >= ?", (seit_iso,)).fetchone()[0]
        if "verhandlung" in t else 0,
        "besichtigungen": db.con.execute("SELECT COUNT(*) FROM besichtigungen WHERE COALESCE(erstellt_am, '') >= ? AND status <> 'abgebrochen'",
                                         (seit_iso,)).fetchone()[0],
        "ankaeufe": db.con.execute("SELECT COUNT(*) FROM ankaeufe WHERE status <> 'storniert' AND erstellt_am >= ?", (seit_iso,)).fetchone()[0]
        if "ankaeufe" in t else 0,
    }
    return auswerten(abdeckung_erg, zeilen, trichter(erste, antworten, besichtigt, gekauft, seit), im, jetzt, tage)
