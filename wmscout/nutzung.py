"""Nutzungszähler (G1, ADR-032): Was wurde in einem Monat getan? Grundlage für eine spätere, optionale Abrechnung – selbst keine.

Gezählt wird aus den vorhandenen Tabellen (keine eigene Zähltabelle, kein Schreibzugriff): Was dort steht, ist die Wahrheit;
ein Zähler daneben könnte auseinanderlaufen. Zugriffe und aktive Nutzer kommen aus dem Audit-Protokoll (erst ab Schema v10).
Zeiten in UTC-Spalten (``*_utc``) werden als UTC gezählt, alle anderen als lokale Zeit – Abweichungen am Monatsrand sind möglich.
"""
from __future__ import annotations

import re
from datetime import date

from .datenbank import Datenbank

# Kennzahl → (Tabelle, Zeitspalte, Zusatzbedingung)
ZAEHLER = {
    "verkaufsanfragen": ("verkaufsanfragen", "erstellt_am", ""),
    "auktionen": ("auktionen", "start_utc", ""),
    "gebote": ("gebote", "zeitpunkt_utc", ""),
    "kalkulationen": ("kalkulationen", "zeitpunkt_utc", ""),
    "besichtigungen": ("besichtigungen", "erstellt_am", ""),
    "ankaeufe": ("ankaeufe", "erstellt_am", ""),
    "verkaeufe": ("ankaeufe", "verkauft_am", ""),
    "anmeldungen": ("audit", "zeitpunkt", "aktion='login' AND status=200"),
    "zugriffe_personendaten": ("audit", "zeitpunkt", "aktion='lesen' AND status=200"),
    "aenderungen": ("audit", "zeitpunkt", "aktion='aendern' AND status<400"),
}


def monat_grenzen(monat: str | None) -> tuple[str, str, str]:
    """'2026-10' → ('2026-10', '2026-10-01', '2026-11-01'); ohne Angabe der laufende Monat."""
    if not monat:
        monat = date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", monat):
        raise ValueError("Monat im Format JJJJ-MM angeben, z. B. 2026-10")
    j, m = int(monat[:4]), int(monat[5:])
    folge = f"{j + (m == 12):04d}-{m % 12 + 1:02d}"
    return monat, f"{monat}-01", f"{folge}-01"


def nutzung(db: Datenbank, monat: str | None = None) -> dict:
    monat, von, bis = monat_grenzen(monat)
    tabellen = {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    werte = {}
    for name, (tabelle, spalte, bedingung) in ZAEHLER.items():
        if tabelle not in tabellen:
            werte[name] = None                     # ältere Datenbank ohne diese Tabelle: nicht „0“, sondern unbekannt
            continue
        sql = f"SELECT COUNT(*) FROM {tabelle} WHERE {spalte} >= ? AND {spalte} < ?" + (f" AND {bedingung}" if bedingung else "")
        werte[name] = db.con.execute(sql, (von, bis)).fetchone()[0]
    je_nutzer = []
    if "audit" in tabellen:
        je_nutzer = [dict(r) for r in db.con.execute(
            "SELECT nutzer, rolle, COUNT(*) AS zugriffe, SUM(aktion='aendern') AS aenderungen, MAX(zeitpunkt) AS zuletzt FROM audit "
            "WHERE zeitpunkt >= ? AND zeitpunkt < ? AND nutzer_id IS NOT NULL GROUP BY nutzer_id ORDER BY zugriffe DESC", (von, bis))]
    werte["aktive_nutzer"] = len(je_nutzer) if "audit" in tabellen else None
    return {"monat": monat, "von": von, "bis": bis, "zaehler": werte, "je_nutzer": je_nutzer}
