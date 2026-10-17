"""Datenrechte (Phase G0, ADR-030; P1-14a): Widerruf einer Verkaufsanfrage, Anonymisieren von Inseraten – für App und Kommandozeile.

Reihenfolge: offene Demo-Auktionen ohne Zuschlag beenden (Auktionsdaten enthalten keine Personendaten), dann
``VerkaufSpeicher.widerruf`` (anonymisieren, Freitexte und Fotos löschen). Ein Ankauf verhindert das Löschen (Aufbewahrung).
Verzeichnis der Daten und Fristen: docs/DATENRECHTE.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
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
    if "ankaeufe" in tabellen and db.con.execute("SELECT 1 FROM ankaeufe WHERE anfrage_id=?",
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


# ---------------------------------------------------------------- Inserate fremder Börsen (P1-14a, F10)
ERSATZ = "[Name entfernt]"


def inserat_anonymisieren(db: Datenbank, ausgabe_ordner: Path, anzeige_id: str) -> dict:
    """Personendaten eines Inserats entfernen: Profilname des Verkäufers (``details_json``), Name im gespeicherten
    Anschreibentext, Verkäuferangaben/Unterschriften/Adresse in Besichtigungen und die Anschreiben-Datei in ``ausgabe/``.
    Fahrzeugdaten, Preise, Status und Fahrzeugfotos bleiben (Marktbeobachtung). Gekaufte Fahrzeuge werden nicht angefasst
    (Aufbewahrung, ``ValueError``); unbekannte Inserate: ``LookupError``."""
    from .bewertung.anschreiben import anrede_name, verkaeufer_name
    con = db.con
    a = con.execute("SELECT * FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone()
    if not a:
        raise LookupError(f"Inserat {anzeige_id} unbekannt")
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if a["status"] == "gekauft" or ("ankaeufe" in tabellen and con.execute(
            "SELECT 1 FROM ankaeufe WHERE anzeige_id=?", (anzeige_id,)).fetchone()):
        raise ValueError(f"Inserat {anzeige_id} ist gekauft – Kaufunterlagen unterliegen der Aufbewahrung, nicht automatisch löschen")
    name = verkaeufer_name(dict(a))
    details = json.loads(a["details_json"] or "{}")
    details.pop("verkaeufer_name", None)
    details["anonymisiert_am"] = datetime.now().isoformat(timespec="seconds")
    text = a["anschreiben_text"]
    if text and name:
        for variante in {name, anrede_name(name) or name}:
            text = text.replace(variante, ERSATZ)
    besichtigungen = 0
    with db.transaktion():
        con.execute("UPDATE anzeigen SET details_json=?, anschreiben_text=? WHERE id=?",
                    (json.dumps(details, ensure_ascii=False), text, anzeige_id))
        for b in con.execute("SELECT id, basis_json, protokoll_json FROM besichtigungen WHERE anzeige_id=?", (anzeige_id,)).fetchall():
            protokoll = json.loads(b["protokoll_json"]) if b["protokoll_json"] else None
            if protokoll:
                for feld in ("verkaeufer", "unterschrift_verkaeufer", "unterschrift_ankaeufer", "bemerkung"):
                    protokoll.pop(feld, None)
            con.execute("UPDATE besichtigungen SET protokoll_json=?, adresse=NULL WHERE id=?",
                        (json.dumps(protokoll, ensure_ascii=False) if protokoll else None, b["id"]))
            besichtigungen += 1
    datei = Path(ausgabe_ordner) / "anschreiben" / f"{anzeige_id}.txt"
    if datei.is_file():
        datei.unlink()
    return {"anzeige_id": anzeige_id, "name_entfernt": bool(name), "besichtigungen": besichtigungen}


def inserate_nach_frist(db: Datenbank, ausgabe_ordner: Path, monate: int, jetzt: datetime | None = None) -> list[str]:
    """Alle Inserate ohne Kauf, deren letzte Aktivität (zuletzt gesehen, Status, Kontakt) älter als ``monate`` ist und die noch
    Personendaten tragen, anonymisieren. ``monate`` ≤ 0: nichts (Standard, bis der Betreiber Fristen festlegt)."""
    if not monate or monate <= 0:
        return []
    grenze = ((jetzt or datetime.now()) - timedelta(days=round(monate * 30.44))).isoformat(timespec="seconds")
    kandidaten = [r[0] for r in db.con.execute(
        "SELECT id FROM anzeigen WHERE COALESCE(status, 'neu') != 'gekauft' "
        "AND MAX(COALESCE(zuletzt_gesehen, ''), COALESCE(status_am, ''), COALESCE(kontaktiert_am, '')) < ? "
        "AND (details_json LIKE '%verkaeufer_name%' OR anschreiben_text IS NOT NULL OR id IN "
        "(SELECT anzeige_id FROM besichtigungen WHERE protokoll_json IS NOT NULL OR adresse IS NOT NULL)) "
        "AND COALESCE(details_json, '') NOT LIKE '%anonymisiert_am%'", (grenze,))]
    erledigt = []
    for anzeige_id in kandidaten:
        try:
            inserat_anonymisieren(db, ausgabe_ordner, anzeige_id)
            erledigt.append(anzeige_id)
        except ValueError:
            continue                                      # gekauft (Ankaufsvorgang) – Aufbewahrung
    return erledigt


def frist_aus(cfg: dict) -> int:
    """config.yaml → datenschutz → inserate_anonymisieren_nach_monaten (0 = aus)."""
    wert = (cfg.get("datenschutz") or {}).get("inserate_anonymisieren_nach_monaten", 0) or 0
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 0:
        raise ValueError("datenschutz → inserate_anonymisieren_nach_monaten: ganze Zahl ≥ 0 (0 = aus)")
    return wert
