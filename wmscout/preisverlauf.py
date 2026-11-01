"""Preisverlauf (P3-03): rein lesende Sicht auf ``preis_historie`` – chronologisch, mit Kanal, Zeitpunkt und Plattform.

Die Historie hängt am Inserat (``preis_historie.inserat_id``) und wandert beim Zusammenführen von Dubletten nicht mit: für ein Fahrzeug
werden die Verläufe aller seiner Inserate gelesen (``inserate.fahrzeug_id``) und gemeinsam sortiert. Preise verschiedener Plattformen
sind nicht untereinander vergleichbar – „vorher“, „aenderung“ und „differenz“ beziehen sich immer auf das vorige Preis-Ereignis desselben Inserats.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:                    # nur für Typen: die Bewertung importiert ``kurz`` ohne Datenbank und sqlite3 (P1-08)
    from .datenbank import Datenbank

_ZEIT_MIN = datetime.min.replace(tzinfo=timezone.utc)
# Abfrage in Teilen, damit der Test den Abfrageplan (Indizes) prüfen kann
SQL_VERLAUF = ("SELECT p.id, p.inserat_id, p.zeitpunkt, p.preis, p.kanal, i.plattform, i.anzeigen_id "
               "FROM preis_historie p JOIN inserate i ON i.id = p.inserat_id WHERE ")
BEDINGUNG_INSERAT, BEDINGUNG_FAHRZEUG = "i.id = ?", "i.fahrzeug_id = ?"


def _utc(text: str | None) -> datetime | None:
    """Gespeicherte Zeit nach UTC. Die Kanäle schreiben unterschiedlich (UTC mit Offset, Ereignis mit eigener Zone, Altbestand lokal ohne Zone):
    ohne Zone gilt die lokale Zeit wie in ``anzeigen``; auf die Sekunde gekürzt
    (Ereignisse tragen Mikrosekunden, die übrigen Kanäle nicht – sonst überholte ein Ereignis einen späteren Eintrag derselben Sekunde). Nicht lesbar: None."""
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).replace(microsecond=0) if text else None
    except (TypeError, ValueError):
        return None


def inserat_zu_anzeigen_id(db: Datenbank, anzeigen_id: str) -> int | None:
    """``inserate.id`` zu einer Anzeigen-ID der App (über ``anzeigen``, sonst über ``legacy_id``)."""
    from .dubletten import inserat_zu_anzeige
    iid = inserat_zu_anzeige(db, anzeigen_id)
    if iid is not None:
        return iid
    r = db.con.execute("SELECT id FROM inserate WHERE legacy_id = ?", (anzeigen_id,)).fetchone()
    return r[0] if r else None


def preisverlauf(db: Datenbank, anzeigen_id: str | None = None, *, fahrzeug_id: int | None = None) -> list[dict]:
    """Alle Preis-Ereignisse eines Inserats (``anzeigen_id``) oder – über alle seine Inserate – eines Fahrzeugs (``fahrzeug_id``), älteste zuerst.

    Genau eines von beiden angeben. ``LookupError``, wenn es das Inserat bzw. Fahrzeug nicht gibt (ein bekanntes Inserat ohne Preis: leere Liste).
    Je Eintrag: ``zeitpunkt`` (UTC, ISO; None wenn der gespeicherte Wert nicht lesbar ist, dann steht er in ``zeitpunkt_roh`` und der Eintrag am
    Anfang), ``preis``, ``kanal`` (suche, manuell, email, detail, api, stream, abgleich, migration), ``plattform``, ``anzeigen_id``, ``inserat_id``,
    ``vorher`` (voriger Preis dieses Inserats, None beim ersten), ``aenderung`` (``erstpreis``, ``gesenkt``, ``erhoeht``, ``gleich``) und ``differenz``.
    Gleiche Zeitpunkte (auf die Sekunde) behalten die Reihenfolge des Eintragens."""
    if (anzeigen_id is None) == (fahrzeug_id is None):
        raise ValueError("Genau eines von anzeigen_id und fahrzeug_id angeben")
    if anzeigen_id is not None:
        iid = inserat_zu_anzeigen_id(db, anzeigen_id)
        if iid is None:
            raise LookupError(f"Inserat {anzeigen_id} unbekannt")
        bedingung, wert = BEDINGUNG_INSERAT, iid
    else:
        if not db.con.execute("SELECT 1 FROM fahrzeuge WHERE id = ?", (fahrzeug_id,)).fetchone():
            raise LookupError(f"Fahrzeug {fahrzeug_id} unbekannt")
        bedingung, wert = BEDINGUNG_FAHRZEUG, fahrzeug_id
    return _ordne(db.con.execute(SQL_VERLAUF + bedingung, (wert,)).fetchall())


def _ordne(zeilen) -> list[dict]:
    geordnet = sorted(((_utc(z["zeitpunkt"]), z) for z in zeilen), key=lambda e: (e[0] or _ZEIT_MIN, e[1]["id"]))
    letzter: dict[int, int] = {}
    verlauf = []
    for zeit, z in geordnet:
        vorher = letzter.get(z["inserat_id"])
        letzter[z["inserat_id"]] = z["preis"]
        verlauf.append({
            "zeitpunkt": zeit.isoformat(timespec="seconds") if zeit else None, "zeitpunkt_roh": z["zeitpunkt"], "preis": z["preis"],
            "kanal": z["kanal"], "plattform": z["plattform"], "anzeigen_id": z["anzeigen_id"], "inserat_id": z["inserat_id"], "vorher": vorher,
            "aenderung": ("erstpreis" if vorher is None else "gesenkt" if z["preis"] < vorher else "erhoeht" if z["preis"] > vorher else "gleich"),
            "differenz": None if vorher is None else z["preis"] - vorher})
    return verlauf


# ---------------------------------------------------------------- Anzeige in der Liste (P6-02, ADR-062)
PUNKTE_MAX = 12                 # Detail: höchstens so viele Preisstände (die jüngsten), damit Karte und Fenster klein bleiben
SQL_ALLE = ("SELECT p.id, p.inserat_id, p.zeitpunkt, p.preis, p.kanal, i.plattform, i.anzeigen_id, a.id AS anzeige "
            "FROM preis_historie p JOIN inserate i ON i.id = p.inserat_id "
            "JOIN anzeigen a ON a.id = i.anzeigen_id AND COALESCE(NULLIF(a.quelle, ''), ?) = i.plattform")


def verlaeufe(db: Datenbank) -> dict[str, list[dict]]:
    """Preisverlauf aller Inserate mit Anzeige in einer Abfrage: Anzeigen-ID → Einträge wie ``preisverlauf`` (älteste zuerst)."""
    from .datenbank import STANDARD_PLATTFORM
    je: dict[str, list] = {}
    for z in db.con.execute(SQL_ALLE, (STANDARD_PLATTFORM,)):
        je.setdefault(z["anzeige"], []).append(z)
    return {aid: _ordne(zeilen) for aid, zeilen in je.items()}


def kurz(verlauf: list[dict] | None) -> dict | None:
    """Kurzfassung für Karte und Detail: nur echte Preisstände (Erstpreis und Änderungen, wiederholte gleiche Preise zählen nicht).
    ``erstpreis``, ``aktuell``, ``differenz`` (aktuell − erst), ``prozent`` (ganzzahlig), ``senkungen``, ``erhoehungen``, ``seit``, ``zuletzt``
    (UTC, ISO) und ``punkte`` [{zeitpunkt, preis, differenz}] (die jüngsten ``PUNKTE_MAX``, ``gekuerzt`` wenn mehr). None ohne Eintrag."""
    punkte = [e for e in verlauf or [] if e.get("aenderung") != "gleich" and isinstance(e.get("preis"), (int, float))]
    if not punkte:
        return None
    erst, aktuell = punkte[0]["preis"], punkte[-1]["preis"]
    return {"erstpreis": erst, "aktuell": aktuell, "differenz": aktuell - erst, "prozent": round(100 * (aktuell - erst) / erst) if erst else None,
            "senkungen": sum(e["aenderung"] == "gesenkt" for e in punkte), "erhoehungen": sum(e["aenderung"] == "erhoeht" for e in punkte),
            "seit": punkte[0]["zeitpunkt"], "zuletzt": punkte[-1]["zeitpunkt"], "gekuerzt": len(punkte) > PUNKTE_MAX,
            "punkte": [{"zeitpunkt": e["zeitpunkt"], "preis": e["preis"], "differenz": e["differenz"]} for e in punkte[-PUNKTE_MAX:]]}
