"""SQLite-Speicher: merkt sich alle gesehenen Anzeigen, Preisänderungen und den Kontakt-Status."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS anzeigen (
    id TEXT PRIMARY KEY,
    url TEXT, suche TEXT, titel TEXT, preis INTEGER, vb INTEGER,
    ort TEXT, km INTEGER, ez_jahr INTEGER, marke TEXT, art TEXT,
    leistung TEXT, getriebe TEXT, kurzbeschreibung TEXT, beschreibung TEXT,
    gewerblich INTEGER DEFAULT 0, details_json TEXT,
    detail_geladen INTEGER DEFAULT 0,
    erstmals_gesehen TEXT, zuletzt_gesehen TEXT,
    preis_vorher INTEGER,
    status TEXT DEFAULT 'neu',      -- neu | kontaktiert | uninteressant | gekauft | gelöscht
    notiz TEXT,
    bild TEXT, kontaktiert_am TEXT, anschreiben_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_zuletzt ON anzeigen(zuletzt_gesehen);
"""
# Spalten, die nach Version 1 dazugekommen sind (ältere Datenbanken werden beim Start ergänzt)
NEUE_SPALTEN = {"bild": "TEXT", "kontaktiert_am": "TEXT", "anschreiben_text": "TEXT"}

FELDER_UPDATE = ["url", "suche", "titel", "preis", "vb", "ort", "km", "ez_jahr", "marke",
                 "kurzbeschreibung", "gewerblich", "bild"]


class Datenbank:
    def __init__(self, pfad: str):
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: die App bedient Anfragen nacheinander in einem Server-Thread
        self.con = sqlite3.connect(pfad, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        vorhanden = {r["name"] for r in self.con.execute("PRAGMA table_info(anzeigen)")}
        for spalte, typ in NEUE_SPALTEN.items():
            if spalte not in vorhanden:
                self.con.execute(f"ALTER TABLE anzeigen ADD COLUMN {spalte} {typ}")
        self.con.commit()

    def speichere_treffer(self, a: dict, suche: str) -> str:
        """Fügt ein oder aktualisiert. Rückgabe: 'neu', 'preis' (Preis gesenkt) oder 'bekannt'."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        alt = self.con.execute("SELECT preis FROM anzeigen WHERE id=?", (a["id"],)).fetchone()
        werte = {k: a.get(k) for k in FELDER_UPDATE}
        werte["suche"] = suche
        werte["vb"] = int(bool(a.get("vb")))
        werte["gewerblich"] = int(bool(a.get("gewerblich")))
        if alt is None:
            spalten = ["id", *werte, "erstmals_gesehen", "zuletzt_gesehen"]
            self.con.execute(
                f"INSERT INTO anzeigen ({','.join(spalten)}) VALUES ({','.join('?' * len(spalten))})",
                [a["id"], *werte.values(), jetzt, jetzt])
            ergebnis = "neu"
        else:
            # Werte aus der Detailseite nicht mit leeren Listenwerten überschreiben
            werte = {k: v for k, v in werte.items() if v not in (None, "")}
            ergebnis = "bekannt"
            if a.get("preis") and alt["preis"] and a["preis"] < alt["preis"]:
                werte["preis_vorher"] = alt["preis"]
                ergebnis = "preis"
            sets = ", ".join(f"{k}=?" for k in werte) + ", zuletzt_gesehen=?"
            self.con.execute(f"UPDATE anzeigen SET {sets} WHERE id=?", [*werte.values(), jetzt, a["id"]])
        self.con.commit()
        return ergebnis

    def speichere_details(self, ad_id: str, d: dict):
        felder = {k: d.get(k) for k in ("titel", "preis", "km", "ez_jahr", "marke", "art", "leistung",
                                         "getriebe", "beschreibung")}
        felder = {k: v for k, v in felder.items() if v not in (None, "")}
        if d.get("gewerblich"):
            felder["gewerblich"] = 1
        felder["details_json"] = json.dumps(d.get("details", {}), ensure_ascii=False)
        felder["detail_geladen"] = 1
        sets = ", ".join(f"{k}=?" for k in felder)
        self.con.execute(f"UPDATE anzeigen SET {sets} WHERE id=?", [*felder.values(), ad_id])
        self.con.commit()

    def ohne_details(self, limit: int) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM anzeigen WHERE detail_geladen=0 ORDER BY erstmals_gesehen DESC LIMIT ?",
            (limit,)).fetchall()

    def aktive(self, tage: int = 21) -> list[sqlite3.Row]:
        grenze = (datetime.now() - timedelta(days=tage)).isoformat(timespec="seconds")
        return self.con.execute("SELECT * FROM anzeigen WHERE zuletzt_gesehen >= ?", (grenze,)).fetchall()

    def alle_mit_preis(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM anzeigen WHERE preis IS NOT NULL").fetchall()

    def setze_status(self, ad_id: str, status: str, notiz: str | None = None, text: str | None = None) -> bool:
        """Bei 'kontaktiert' werden Zeitpunkt und gesendeter Text gespeichert, bei 'neu' zurückgesetzt."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        if status == "kontaktiert":
            sql, werte = ("UPDATE anzeigen SET status=?, notiz=COALESCE(?, notiz), kontaktiert_am=?, "
                          "anschreiben_text=COALESCE(?, anschreiben_text) WHERE id=?", (status, notiz, jetzt, text, ad_id))
        elif status == "neu":
            sql, werte = ("UPDATE anzeigen SET status=?, notiz=COALESCE(?, notiz), kontaktiert_am=NULL WHERE id=?",
                          (status, notiz, ad_id))
        else:
            sql, werte = "UPDATE anzeigen SET status=?, notiz=COALESCE(?, notiz) WHERE id=?", (status, notiz, ad_id)
        cur = self.con.execute(sql, werte)
        self.con.commit()
        return cur.rowcount > 0

    def setze_notiz(self, ad_id: str, notiz: str) -> bool:
        cur = self.con.execute("UPDATE anzeigen SET notiz=? WHERE id=?", (notiz, ad_id))
        self.con.commit()
        return cur.rowcount > 0
