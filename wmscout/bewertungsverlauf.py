"""Bewertungsverlauf (P5-07, ADR-060): nach Suchlauf, Import und Report wird je Inserat festgehalten, wie es bewertet wurde – aber nur,
wenn sich etwas Wesentliches geändert hat (Preis, Max-EK, Spanne, Sicherheit, Ampel, Rechenstand oder der Deal-Score um mindestens
``SCORE_SCHRITT`` Punkte). Zeitpunkte in Ortszeit wie die übrigen Zeitstempel der Inserate. So bleibt die Tabelle klein
und zeigt, wann ein Fahrzeug interessant wurde. Nur anfügbar (Trigger), keine Personendaten."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from .bewertung.deal_score import MODELL
from .bewertung.kalkulation import VERSION as RECHENSTAND
from .datenbank import Datenbank

MODELL_VERSION = f"{RECHENSTAND}/{MODELL}"        # Rechenstand der Bewertung und des Deal-Scores
_VERGLEICH = ("preis", "marktwert", "spanne_von", "spanne_bis", "max_ek", "sicherheit", "ampel", "modell_version")
SCORE_SCHRITT = 3            # kleinere Score-Bewegungen (z. B. täglich sinkende Frische) erzeugen keine neue Zeile (QA P5-07 B6)
log = logging.getLogger("scout")


def _eintrag(z: dict) -> dict:
    a, b, d = z["a"], z["b"], z.get("deal") or {}
    return {"anzeige_id": a["id"], "modell_version": MODELL_VERSION, "preis": a.get("preis"), "marktwert": b.marktwert_angebote,
            "spanne_von": b.spanne_von, "spanne_bis": b.spanne_bis, "max_ek": b.max_ek or None, "erstangebot": b.erstangebot or None,
            "sicherheit": b.sicherheit, "n_vergleich": b.vergleich_anzahl, "ampel": b.ampel, "deal_score": d.get("score"),
            "komponenten_json": json.dumps([{k: t[k] for k in ("schluessel", "anteil", "punkte", "text")} for t in d.get("bestandteile", [])],
                                           ensure_ascii=False)}


def _geaendert(alt: dict | None, neu: dict) -> bool:
    if not alt or any(alt[k] != neu[k] for k in _VERGLEICH):
        return True
    a, n = alt["deal_score"], neu["deal_score"]
    return (a is None) != (n is None) or (a is not None and abs(a - n) >= SCORE_SCHRITT)


def merken(db: Datenbank, zeilen: list[dict], jetzt: datetime | None = None) -> int:
    """Geänderte Bewertungen anfügen (eine Transaktion); Rückgabe: Anzahl neuer Einträge. Fehlt die Tabelle (ältere Datenbank), nichts.
    Ein Fehler (z. B. gesperrte Datenbank) wird protokolliert und hält Report, Mail oder Import nie auf (QA B5)."""
    try:
        return _merken(db, zeilen, jetzt)
    except sqlite3.Error:
        log.exception("Bewertungsverlauf nicht gespeichert")
        return 0


def _merken(db: Datenbank, zeilen: list[dict], jetzt: datetime | None) -> int:
    if not db.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bewertungen'").fetchone():
        return 0
    zeit = (jetzt or datetime.now()).isoformat(timespec="seconds")
    letzte = {r["anzeige_id"]: dict(r) for r in db.con.execute(
        "SELECT * FROM bewertungen WHERE id IN (SELECT MAX(id) FROM bewertungen GROUP BY anzeige_id)")}
    neu = []
    for z in zeilen:
        e = _eintrag(z)
        if _geaendert(letzte.get(e["anzeige_id"]), e):
            neu.append(e)
    if neu:
        spalten = ["anzeige_id", "zeitpunkt", *[k for k in neu[0] if k != "anzeige_id"]]
        with db.transaktion():
            db.con.executemany(f"INSERT INTO bewertungen ({', '.join(spalten)}) VALUES ({', '.join('?' * len(spalten))})",
                               [(e["anzeige_id"], zeit, *[e[k] for k in spalten[2:]]) for e in neu])
    return len(neu)


def verlauf(db: Datenbank, anzeige_id: str, limit: int = 20) -> list[dict]:
    """Die letzten Einträge eines Inserats, neueste zuerst."""
    if not db.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bewertungen'").fetchone():
        return []
    return [{**dict(r), "komponenten": json.loads(r["komponenten_json"])} for r in db.con.execute(
        "SELECT * FROM bewertungen WHERE anzeige_id=? ORDER BY id DESC LIMIT ?", (anzeige_id, limit))]
