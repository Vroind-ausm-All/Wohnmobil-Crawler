"""Datenrechte (Phase G0, ADR-030): Widerruf einer Verkaufsanfrage – gemeinsam für App und Kommandozeile.

Reihenfolge: offene Demo-Auktionen ohne Zuschlag beenden (Auktionsdaten enthalten keine Personendaten), dann
``VerkaufSpeicher.widerruf`` (anonymisieren, Freitexte und Fotos löschen). Ein Ankauf verhindert das Löschen (Aufbewahrung).
Verzeichnis der Daten und Fristen: docs/DATENRECHTE.md.
"""
from __future__ import annotations

from pathlib import Path

from .auktion import AuktionSpeicher
from .datenbank import Datenbank
from .verkauf import VerkaufSpeicher


def widerruf(db: Datenbank, cfg: dict, foto_ordner: Path, anfrage_id: int, nutzer_id: int | None) -> dict:
    """``ValueError`` bei bestehendem Ankauf (nichts geändert), ``LookupError`` wenn es die Anfrage nicht gibt."""
    verkauf = VerkaufSpeicher(db, Path(foto_ordner) / "anfragen")
    if not verkauf.lade(anfrage_id):
        raise LookupError("Anfrage nicht gefunden")
    tabellen = {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "ankaeufe" in tabellen and db.con.execute("SELECT 1 FROM ankaeufe WHERE anfrage_id=? AND status != 'storniert'",
                                                 (anfrage_id,)).fetchone():
        raise ValueError("Für diese Anfrage gibt es einen Ankaufsvorgang – Kaufunterlagen unterliegen der Aufbewahrungspflicht; "
                         "nicht automatisch löschen, Einzelfall klären")
    auktion = AuktionSpeicher(db, cfg)
    for a in auktion.fuer_anfrage(anfrage_id):
        if a["status"] == "laeuft":
            auktion.abbrechen(a["id"], nutzer_id, "Widerruf des Verkäufers")
        elif a["status"] == "beendet":
            auktion.entscheiden(a["id"], nutzer_id, False)
    return verkauf.widerruf(anfrage_id, nutzer_id)
