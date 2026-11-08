"""Vom Team bestätigte Fahrzeugdaten, getrennt von den unveränderten Importangaben.

Neue Imports überschreiben diese Angaben nicht. Weicht ein neuer Import seit der
Bestätigung ab, wird der Konflikt sichtbar und verhindert einen Top-Deal.
Die Quellenidentität bleibt unveränderbar; niemand bestätigt eine andere Plattform.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .domaene import BESTAETIGT, IMPORT_ARTEN, import_suche
from .normalisierung.fahrzeug import art_schluessel, ergaenze_fahrzeug, fahrzeug_bezeichnung, serie_aus_modell

FELDER = ("preis", "ez_jahr", "km", "marke", "modell", "ort", "art")


def _roh(a: dict) -> dict:
    a = ergaenze_fahrzeug(dict(a))
    a["art"] = art_schluessel(a.get("suche"), a.get("art"), a.get("titel"))
    return a


def _pruefe(feld, wert):
    if feld not in FELDER:
        raise ValueError("Nicht bestätigbares Feld: " + str(feld))
    if wert is None:
        return None
    grenzen = {"preis": (1, 10_000_000), "ez_jahr": (1960, datetime.now().year), "km": (0, 1_000_000)}
    if feld in grenzen:
        unten, oben = grenzen[feld]
        if isinstance(wert, bool) or not isinstance(wert, int) or not unten <= wert <= oben:
            raise ValueError(f"{feld}: ganze Zahl zwischen {unten} und {oben} erwartet")
        return wert
    if not isinstance(wert, str) or not wert.strip() or len(wert) > 150 or any(ord(c) < 32 for c in wert):
        raise ValueError(f"{feld}: Text mit 1–150 Zeichen ohne Steuerzeichen erwartet")
    wert = wert.strip()
    if feld == "art" and wert not in (*IMPORT_ARTEN, "Sonstige"):
        raise ValueError("Unbekannte Fahrzeugart")
    return wert


def lade(db, ids=None) -> dict[str, dict]:
    """Bestätigungen je Anzeigen-ID; keine Rohwerte oder Kundentexte in Protokolle schreiben."""
    if ids is None:
        zeilen = db.con.execute("SELECT * FROM feldbestaetigungen").fetchall()
    else:
        ids = sorted(set(ids))
        zeilen = []
        for start in range(0, len(ids), 500):
            teil = ids[start:start + 500]
            zeilen.extend(db.con.execute(f"SELECT * FROM feldbestaetigungen WHERE anzeige_id IN ({','.join('?' * len(teil))})", teil))
    erg = {}
    for z in zeilen:
        erg.setdefault(z["anzeige_id"], {})[z["feld"]] = {"wert": json.loads(z["wert_json"]), "extrahiert": json.loads(z["extrahiert_json"]),
                                                        "bestaetigt_am": z["bestaetigt_am"], "nutzer_id": z["nutzer_id"]}
    return erg


def anwenden(a: dict, bestaetigungen: dict | None = None) -> dict:
    """Effektive, normalisierte Rechner-/UI-Sicht samt Originalwerten je Feld.

    ``datenherkunft`` kennzeichnet nur vom Team bestätigte Werte als bestätigt.
    Ein strukturierter Import ist damit nicht automatisch eine menschliche Prüfung.
    """
    roh = _roh(a)
    erg = dict(roh)
    bestaetigungen = bestaetigungen or {}
    herkunft = {}
    for feld in FELDER:
        b = bestaetigungen.get(feld)
        original = roh.get(feld)
        wirksam = b["wert"] if b else original
        konflikt = bool(b and original != b["extrahiert"] and original != wirksam)
        herkunft[feld] = {"extrahiert": original, "wert": wirksam, "quelle": roh.get("quelle") or "kleinanzeigen",
                          "bestaetigt": bool(b), "bestaetigt_am": b["bestaetigt_am"] if b else None,
                          "nutzer_id": b["nutzer_id"] if b else None, "konflikt": konflikt,
                          "status": "widerspruechlich" if konflikt else "bestaetigt" if b else
                          "unvollstaendig" if original in (None, "", "Sonstige") else "extrahiert"}
        if b:
            erg[feld] = wirksam
    if "art" in bestaetigungen:
        erg["suche"] = import_suche(erg.get("art"), BESTAETIGT if erg.get("art") not in (None, "Sonstige") else None)
    # Erkennung nach bestätigter Marke/Ort erneut ausführen; ein bestätigtes Modell
    # (auch bewusst unbekannt) hat abschließend Vorrang vor der Titelheuristik.
    erg = ergaenze_fahrzeug(erg)
    for feld in ("marke", "modell"):
        if feld in bestaetigungen:
            erg[feld] = bestaetigungen[feld]["wert"]
    erg["serie"] = serie_aus_modell(erg.get("marke"), erg.get("modell"))
    erg["fahrzeug"] = fahrzeug_bezeichnung(erg.get("marke"), erg.get("modell"))
    for feld, h in herkunft.items():
        h["wert"] = erg.get(feld)       # abhängige Normalisierung (z. B. Modell nach Markenwechsel) nachvollziehbar halten
    erg["datenherkunft"] = herkunft
    return erg


def sicht(db, anzeige_id: str) -> dict:
    a = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone()
    if a is None:
        raise LookupError("Anzeige nicht gefunden")
    return anwenden(dict(a), lade(db, [anzeige_id]).get(anzeige_id))["datenherkunft"]


def bestaetigen(db, anzeige_id: str, werte: dict, nutzer_id: int | None = None) -> dict:
    if not isinstance(werte, dict) or not werte or len(werte) > len(FELDER):
        raise ValueError("Mindestens eine Fahrzeugangabe zur Bestätigung erwartet")
    werte = {feld: _pruefe(feld, wert) for feld, wert in werte.items()}
    with db.transaktion():
        a = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone()
        if a is None:
            raise LookupError("Anzeige nicht gefunden")
        roh = _roh(dict(a))
        jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for feld, wert in werte.items():
            db.con.execute("""INSERT INTO feldbestaetigungen (anzeige_id,feld,wert_json,extrahiert_json,bestaetigt_am,nutzer_id)
                              VALUES (?,?,?,?,?,?) ON CONFLICT(anzeige_id,feld) DO UPDATE SET wert_json=excluded.wert_json,
                              extrahiert_json=excluded.extrahiert_json,bestaetigt_am=excluded.bestaetigt_am,nutzer_id=excluded.nutzer_id""",
                           (anzeige_id, feld, json.dumps(wert, ensure_ascii=False), json.dumps(roh.get(feld), ensure_ascii=False), jetzt, nutzer_id))
    return sicht(db, anzeige_id)


def zuruecksetzen(db, anzeige_id: str, felder: list) -> dict:
    if not isinstance(felder, list) or not felder or any(not isinstance(f, str) or f not in FELDER for f in felder):
        raise ValueError("Gültige Feldnamen zum Zurücksetzen erwartet")
    with db.transaktion():
        if db.con.execute("SELECT 1 FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone() is None:
            raise LookupError("Anzeige nicht gefunden")
        for feld in felder:
            db.con.execute("DELETE FROM feldbestaetigungen WHERE anzeige_id=? AND feld=?", (anzeige_id, feld))
    return sicht(db, anzeige_id)
