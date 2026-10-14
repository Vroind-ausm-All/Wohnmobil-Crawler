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
    status TEXT DEFAULT 'neu',      -- siehe STATUS, außerdem 'gelöscht' (Anzeige offline)
    notiz TEXT,
    bild TEXT, kontaktiert_am TEXT, anschreiben_text TEXT,
    preis_geaendert_am TEXT, nachgefasst_am TEXT, nachfass_anzahl INTEGER DEFAULT 0,
    angebot_betrag INTEGER, status_am TEXT,
    quelle TEXT                     -- Kennung der Datenquelle; NULL = kleinanzeigen (Daten vor Phase 1)
);
CREATE INDEX IF NOT EXISTS idx_zuletzt ON anzeigen(zuletzt_gesehen);
"""
# Spalten, die nach Version 1 dazugekommen sind (ältere Datenbanken werden beim Start ergänzt)
NEUE_SPALTEN = {"bild": "TEXT", "kontaktiert_am": "TEXT", "anschreiben_text": "TEXT", "preis_geaendert_am": "TEXT",
                "nachgefasst_am": "TEXT", "nachfass_anzahl": "INTEGER DEFAULT 0", "angebot_betrag": "INTEGER",
                "status_am": "TEXT", "quelle": "TEXT"}

# Ablauf eines Ankaufs (Schlüssel → Anzeige in der App)
STATUS = {"neu": "offen", "kontaktiert": "kontaktiert", "verhandlung": "in Verhandlung",
          "besichtigung": "Besichtigung", "gekauft": "gekauft", "abgesagt": "abgesagt",
          "uninteressant": "uninteressant"}

# `suche` von Inseraten aus gespeicherten Seiten: werden nie per Detailabruf nachgeladen (ADR-010)
IMPORT_SUCHE = "Import (gespeicherte Seite)"

# Herkunft der Fahrzeugart eines importierten Inserats, in `suche` kodiert (keine Schemaänderung):
#   „Import <Art> (bestätigt)“  Art stammt aus dem Art-Filter (art_s:) in der Haupttabelle einer Suchseite oder aus dem
#                               Feld „Art“ der Detailseite (die Detailseite hat Vorrang)
#   „Import <Art> (vorläufig)“  Art nur aus dem eigenen Titel bzw. einem Suchwort der Seite – Hinweis „nicht bestätigt“
#   IMPORT_SUCHE                Art unbekannt (oder widersprüchlich) – Hinweis „unbekannt“
#   „Import <Art>“              Altbestand früherer Zweigstände: gilt wie „vorläufig“
# Erkannt werden nur genau diese Muster; jede andere `suche` (auch „Importfahrzeuge …“) ist eine Crawler-Suche und
# bleibt unberührt. Bei nicht bestätigter Art wird trotzdem angeschrieben, die Zeile trägt aber einen Hinweis.
IMPORT_ARTEN = ("Teilintegrierter", "Integrierter", "Alkoven", "Kastenwagen", "Wohnwagen")
BESTAETIGT, VORLAEUFIG, UNBEKANNT = "bestaetigt", "vorlaeufig", "unbekannt"
_MARKE = {BESTAETIGT: " (bestätigt)", VORLAEUFIG: " (vorläufig)"}


def import_suche(art: str | None = None, status: str | None = None) -> str:
    """`suche`-Wert für ein importiertes Inserat; ohne Art oder Status `IMPORT_SUCHE` (unbekannt)."""
    if art not in IMPORT_ARTEN or status not in _MARKE:
        return IMPORT_SUCHE
    return f"Import {art}{_MARKE[status]}"


def import_art(suche: str | None) -> tuple[str | None, str | None]:
    """(Art, Herkunft) aus `suche`. Herkunft: BESTAETIGT, VORLAEUFIG, UNBEKANNT – oder None, wenn `suche` keine
    Import-Suche ist (Crawler). „Import <unbekannte Art> (bestätigt|vorläufig)“ gilt als UNBEKANNT."""
    if not suche:
        return None, None
    if suche == IMPORT_SUCHE:
        return None, UNBEKANNT
    if not suche.startswith("Import "):
        return None, None
    rest = suche[len("Import "):]
    for status, marke in _MARKE.items():
        if rest.endswith(marke):
            art = rest[:-len(marke)]
            return (art, status) if art in IMPORT_ARTEN else (None, UNBEKANNT)
    if rest in IMPORT_ARTEN:
        return rest, VORLAEUFIG                  # Altbestand ohne Markierung
    return None, None


# SQL-Gegenstück zu import_art() != (None, None): nur die exakten Muster, nicht jeder Name mit „Import“ am Anfang.
# GLOB statt LIKE: LIKE ignoriert die Groß-/Kleinschreibung, Python (startswith/endswith) nicht. In den Mustern stehen keine
# GLOB-Sonderzeichen außer dem gewollten „*“ (die Marken aus _MARKE enthalten nur Buchstaben, Leerzeichen und Klammern).
_IMPORT_SQL = ("(suche = ? OR suche IN ({arten}) OR suche GLOB 'Import * (bestätigt)' OR suche GLOB 'Import * (vorläufig)')"
               .format(arten=",".join("?" * len(IMPORT_ARTEN))))
_IMPORT_PARAMETER = (IMPORT_SUCHE, *(f"Import {a}" for a in IMPORT_ARTEN))

FELDER_UPDATE = ["url", "suche", "titel", "preis", "vb", "ort", "km", "ez_jahr", "marke",
                 "kurzbeschreibung", "gewerblich", "bild", "quelle"]


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
            if a.get("gewerblich") is None:          # „unbekannt“ (z. B. Detailseite ohne Hinweis) überschreibt nichts
                werte.pop("gewerblich", None)
            ergebnis = "bekannt"
            if a.get("preis") and alt["preis"] and a["preis"] < alt["preis"]:
                werte["preis_vorher"] = alt["preis"]
                werte["preis_geaendert_am"] = jetzt
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
        """Inserate für den Detailabruf – ohne solche aus gespeicherten Seiten (kein Netzabruf, ADR-010)."""
        return self.con.execute(
            f"SELECT * FROM anzeigen WHERE detail_geladen=0 AND NOT COALESCE({_IMPORT_SQL}, 0) "
            "ORDER BY erstmals_gesehen DESC LIMIT ?", (*_IMPORT_PARAMETER, limit)).fetchall()

    def detail_art(self, ad_id: str) -> str | None:
        """Feld „Art“ der gespeicherten Detailseite (None ohne Detailseite oder ohne Angabe)."""
        zeile = self.con.execute("SELECT art, detail_geladen FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        return zeile["art"] if zeile and zeile["detail_geladen"] and zeile["art"] else None

    def suche_zu(self, ad_id: str) -> str | None:
        zeile = self.con.execute("SELECT suche FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        return zeile["suche"] if zeile else None

    def aktive(self, tage: int = 21) -> list[sqlite3.Row]:
        grenze = (datetime.now() - timedelta(days=tage)).isoformat(timespec="seconds")
        return self.con.execute("SELECT * FROM anzeigen WHERE zuletzt_gesehen >= ?", (grenze,)).fetchall()

    def alle_mit_preis(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM anzeigen WHERE preis IS NOT NULL").fetchall()

    def letzter_lauf(self) -> datetime | None:
        """Zeitpunkt, zu dem zuletzt Anzeigen gesehen wurden (≈ letzter Suchlauf)."""
        wert = self.con.execute("SELECT MAX(zuletzt_gesehen) FROM anzeigen").fetchone()[0]
        return datetime.fromisoformat(wert) if wert else None

    def setze_status(self, ad_id: str, status: str, notiz: str | None = None, text: str | None = None,
                     betrag: int | None = None) -> bool:
        """Mit Text (= Anschreiben gesendet) werden Zeitpunkt, Text und Angebot gespeichert; 'neu' setzt zurück."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        sets, werte = ["status=?", "status_am=?", "notiz=COALESCE(?, notiz)"], [status, jetzt, notiz]
        if status == "kontaktiert" and text:
            sets += ["kontaktiert_am=?", "anschreiben_text=?", "angebot_betrag=?", "nachgefasst_am=NULL",
                     "nachfass_anzahl=0"]
            werte += [jetzt, text, betrag]
        elif status == "kontaktiert":
            sets.append("kontaktiert_am=COALESCE(kontaktiert_am, ?)")
            werte.append(jetzt)
        elif status == "neu":
            sets += ["kontaktiert_am=NULL", "nachgefasst_am=NULL", "nachfass_anzahl=0"]
        if betrag and not (status == "kontaktiert" and text):
            sets.append("angebot_betrag=?")
            werte.append(betrag)
        cur = self.con.execute(f"UPDATE anzeigen SET {', '.join(sets)} WHERE id=?", [*werte, ad_id])
        self.con.commit()
        return cur.rowcount > 0

    def nachgefasst(self, ad_id: str, text: str, betrag: int | None = None) -> bool:
        """Nachfass-Nachricht gesendet: Zeitpunkt merken, Text an den Verlauf anhängen."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        cur = self.con.execute(
            "UPDATE anzeigen SET nachgefasst_am=?, nachfass_anzahl=COALESCE(nachfass_anzahl, 0)+1, "
            "anschreiben_text=COALESCE(anschreiben_text || char(10) || char(10), '') || ? || char(10) || ?, "
            "angebot_betrag=COALESCE(?, angebot_betrag), "
            "status=CASE WHEN status IN ('neu', 'abgesagt') THEN 'kontaktiert' ELSE status END, "
            "kontaktiert_am=COALESCE(kontaktiert_am, ?) WHERE id=?",
            (jetzt, f"--- nachgefasst am {jetzt[:10]} ---", text, betrag, jetzt, ad_id))
        self.con.commit()
        return cur.rowcount > 0

    def setze_notiz(self, ad_id: str, notiz: str) -> bool:
        cur = self.con.execute("UPDATE anzeigen SET notiz=? WHERE id=?", (notiz, ad_id))
        self.con.commit()
        return cur.rowcount > 0
