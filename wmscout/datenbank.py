"""SQLite-Speicher: merkt sich alle gesehenen Anzeigen, Preisänderungen und den Kontakt-Status."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .bearbeitung import IN_ARBEIT, BearbeitungsKonflikt
from .migrationen import NEUE_SPALTEN, migriere  # noqa: F401 – NEUE_SPALTEN bleibt hier importierbar (Kompatibilität)

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
    def __init__(self, pfad: str, sicherung_ordner: str | Path | None = None):
        """Öffnet die Datenbank; Schema und Version verwaltet ``migrationen.migriere`` (mit Sicherung vor jeder Migration).

        ``sicherung_ordner``: Standard ist ``sicherungen`` neben der Datenbank (``daten/sicherungen``).
        Wirft ``MigrationsFehler``, wenn die Datenbank neuer ist als dieser Code oder die Sicherung scheitert.
        """
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        migriere(pfad, sicherung_ordner)
        # check_same_thread=False: die App bedient Anfragen nacheinander in einem Server-Thread
        self.con = sqlite3.connect(pfad, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

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

    # ---------- Status und Nachfassen (mit Team: Übernahme und Status in EINER Transaktion) ----------
    @contextmanager
    def _exklusiv(self):
        """Schreibsperre vor dem ersten Lesen (BEGIN IMMEDIATE): prüfen und schreiben sind eine Einheit, auch gegen andere
        Verbindungen (Suchlauf, zweiter Prozess). Fehler und Konflikte rollen alles zurück."""
        if self.con.in_transaction:
            self.con.commit()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.con.rollback()
            raise
        self.con.commit()

    def setze_status(self, ad_id: str, status: str, notiz: str | None = None, text: str | None = None,
                     betrag: int | None = None, *, nutzer_id: int | None = None, grenze: str = "", erzwingen: bool = False,
                     inhaber: bool = False, dubletten=()) -> bool:
        """Mit Text (= Anschreiben gesendet) werden Zeitpunkt, Text und Angebot gespeichert; 'neu' setzt zurück.

        Ohne ``nutzer_id`` (Team aus) wie bisher. Mit ``nutzer_id``: 'kontaktiert' übernimmt das Inserat zuerst (wie
        ``uebernimm``) und trägt den ersten Kontakt ein; 'neu' leert den Kontakt (Bearbeiter bleibt); alle anderen Status
        verlangen: frei, eigene Reservierung oder ``inhaber``. Sonst ``BearbeitungsKonflikt`` – dann ist nichts geändert."""
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
        sql = f"UPDATE anzeigen SET {', '.join(sets)} WHERE id=?"
        if nutzer_id is None:
            cur = self.con.execute(sql, [*werte, ad_id])
            self.con.commit()
            return cur.rowcount > 0
        with self._exklusiv():
            if not self.con.execute("SELECT 1 FROM anzeigen WHERE id=?", (ad_id,)).fetchone():
                return False
            if status == "kontaktiert":
                if not self._uebernimm(ad_id, nutzer_id, jetzt, grenze, erzwingen, dubletten):
                    raise BearbeitungsKonflikt(ad_id)
            elif not inhaber and self._fremde_halter([ad_id], nutzer_id, grenze):
                raise BearbeitungsKonflikt(ad_id)
            cur = self.con.execute(sql, [*werte, ad_id])
            if status == "kontaktiert":
                self._trage_kontakt_ein(ad_id, nutzer_id, jetzt)
            elif status == "neu":
                self.con.execute("UPDATE bearbeitung SET kontaktiert_von=NULL, kontaktiert_am=NULL WHERE anzeige_id=?", (ad_id,))
            return cur.rowcount > 0

    def nachgefasst(self, ad_id: str, text: str, betrag: int | None = None, *, nutzer_id: int | None = None,
                    grenze: str = "", erzwingen: bool = False, dubletten=()) -> bool:
        """Nachfass-Nachricht gesendet: Zeitpunkt merken, Text an den Verlauf anhängen.
        Mit ``nutzer_id`` (Team) wie 'kontaktiert': erst Übernahme (sonst ``BearbeitungsKonflikt``), erster Kontakt eingetragen."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        sql = ("UPDATE anzeigen SET nachgefasst_am=?, nachfass_anzahl=COALESCE(nachfass_anzahl, 0)+1, "
               "anschreiben_text=COALESCE(anschreiben_text || char(10) || char(10), '') || ? || char(10) || ?, "
               "angebot_betrag=COALESCE(?, angebot_betrag), "
               "status=CASE WHEN status IN ('neu', 'abgesagt') THEN 'kontaktiert' ELSE status END, "
               "kontaktiert_am=COALESCE(kontaktiert_am, ?) WHERE id=?")
        werte = (jetzt, f"--- nachgefasst am {jetzt[:10]} ---", text, betrag, jetzt, ad_id)
        if nutzer_id is None:
            cur = self.con.execute(sql, werte)
            self.con.commit()
            return cur.rowcount > 0
        with self._exklusiv():
            if not self.con.execute("SELECT 1 FROM anzeigen WHERE id=?", (ad_id,)).fetchone():
                return False
            if not self._uebernimm(ad_id, nutzer_id, jetzt, grenze, erzwingen, dubletten):
                raise BearbeitungsKonflikt(ad_id)
            cur = self.con.execute(sql, werte)
            self._trage_kontakt_ein(ad_id, nutzer_id, jetzt)
            return cur.rowcount > 0

    def setze_notiz(self, ad_id: str, notiz: str) -> bool:
        cur = self.con.execute("UPDATE anzeigen SET notiz=? WHERE id=?", (notiz, ad_id))
        self.con.commit()
        return cur.rowcount > 0

    def status_von(self, ad_id: str) -> str | None:
        """Status des Inserats; ``None``, wenn es das Inserat nicht gibt."""
        zeile = self.con.execute("SELECT status FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        return (zeile["status"] or "neu") if zeile else None

    # ---------- Team: Übernahme, Abgabe, Zuweisung (Tabelle bearbeitung) ----------
    _UEBERNAHME = (
        "INSERT INTO bearbeitung(anzeige_id, bearbeiter_id, uebernommen_am) VALUES(:id, :nutzer, :jetzt) "
        "ON CONFLICT(anzeige_id) DO UPDATE SET bearbeiter_id=excluded.bearbeiter_id, uebernommen_am=excluded.uebernommen_am "
        "WHERE bearbeitung.bearbeiter_id IS NULL "
        "OR bearbeitung.bearbeiter_id=excluded.bearbeiter_id "
        "OR (bearbeitung.kontaktiert_von IS NULL AND bearbeitung.uebernommen_am < :grenze) "
        "OR bearbeitung.bearbeiter_id NOT IN (SELECT id FROM nutzer WHERE aktiv=1) "
        "OR :erzwingen")

    def _fremde_halter(self, ids, nutzer_id: int, grenze: str) -> sqlite3.Row | None:
        """Hält ein anderer aktiver Kollege eines dieser Inserate wirksam (Kontakt bestätigt oder Reservierung nicht abgelaufen)?"""
        ids = list(ids)
        if not ids:
            return None
        return self.con.execute(
            "SELECT b.anzeige_id, b.bearbeiter_id FROM bearbeitung b JOIN nutzer n ON n.id=b.bearbeiter_id AND n.aktiv=1 "
            f"WHERE b.anzeige_id IN ({','.join('?' * len(ids))}) AND b.bearbeiter_id<>? "
            "AND (b.kontaktiert_von IS NOT NULL OR b.uebernommen_am>=?) LIMIT 1", (*ids, nutzer_id, grenze)).fetchone()

    def _uebernimm(self, ad_id: str, nutzer_id: int, jetzt: str, grenze: str, erzwingen: bool, dubletten) -> bool:
        """Nur innerhalb von ``_exklusiv``: Dubletten prüfen (liest), dann EIN bedingtes UPSERT (rowcount 0 = Konflikt)."""
        if dubletten and not erzwingen and self._fremde_halter([d for d in dubletten if d != ad_id], nutzer_id, grenze):
            return False
        cur = self.con.execute(self._UEBERNAHME, {"id": ad_id, "nutzer": nutzer_id, "jetzt": jetzt, "grenze": grenze,
                                                  "erzwingen": int(bool(erzwingen))})
        return cur.rowcount > 0

    def _trage_kontakt_ein(self, ad_id: str, nutzer_id: int, jetzt: str):
        """Erster Kontakt: spätere Kontakte (Nachfassen, Zuweisung an andere) überschreiben ihn nicht."""
        self.con.execute("UPDATE bearbeitung SET kontaktiert_von=COALESCE(kontaktiert_von, ?), "
                         "kontaktiert_am=COALESCE(kontaktiert_am, ?) WHERE anzeige_id=?", (nutzer_id, jetzt, ad_id))

    def uebernimm(self, anzeige_id: str, nutzer_id: int, jetzt: str, grenze: str = "", erzwingen: bool = False,
                  dubletten=()) -> bool:
        """Inserat übernehmen (reservieren) oder die eigene Reservierung verlängern. ``False`` = Konflikt, nichts geändert.

        Gelingt, wenn niemand es hält, es schon dem Nutzer gehört, die Reservierung (``grenze`` = Zeitpunkt, vor dem sie als
        abgelaufen gilt; "" = nie) abgelaufen und noch nicht kontaktiert ist, der Bearbeiter deaktiviert ist oder ``erzwingen``.
        ``dubletten``: IDs derselben Fahrzeuggruppe; hält ein anderer aktiver Kollege eine davon, ist es ebenfalls ein Konflikt.
        Die Anzeige muss existieren (nicht geprüft, um keinen zweiten Zugriff zu brauchen)."""
        with self._exklusiv():
            return self._uebernimm(anzeige_id, nutzer_id, jetzt, grenze, erzwingen, dubletten)

    def gib_ab(self, anzeige_id: str, nutzer_id: int, inhaber: bool = False) -> bool:
        """Reservierung zurückgeben: nur ohne bestätigten Kontakt, nur Bearbeiter oder Inhaber. ``True`` = es wurde etwas freigegeben."""
        cur = self.con.execute("DELETE FROM bearbeitung WHERE anzeige_id=? AND kontaktiert_von IS NULL "
                               "AND (bearbeiter_id=? OR ?)", (anzeige_id, nutzer_id, int(bool(inhaber))))
        self.con.commit()
        return cur.rowcount > 0

    def weise_zu(self, anzeige_id: str, ziel_id: int, jetzt: str) -> None:
        """Inserat einem Kollegen zuweisen (Berechtigung „Inhaber“ prüft der Aufrufer). ``kontaktiert_von/_am`` bleiben."""
        self.con.execute(
            "INSERT INTO bearbeitung(anzeige_id, bearbeiter_id, uebernommen_am) VALUES(?,?,?) "
            "ON CONFLICT(anzeige_id) DO UPDATE SET bearbeiter_id=excluded.bearbeiter_id, uebernommen_am=excluded.uebernommen_am",
            (anzeige_id, ziel_id, jetzt))
        self.con.commit()

    def bearbeitung_aktiv(self) -> dict[str, dict]:
        """Alle Zeilen aus ``bearbeitung`` (ein SELECT) mit Flag ``bearbeiter_aktiv`` (Bearbeiter existiert und ist aktiv)."""
        return {r["anzeige_id"]: dict(r) for r in self.con.execute(
            "SELECT b.anzeige_id, b.bearbeiter_id, b.uebernommen_am, b.kontaktiert_von, b.kontaktiert_am, "
            "COALESCE(n.aktiv, 0) AS bearbeiter_aktiv FROM bearbeitung b LEFT JOIN nutzer n ON n.id=b.bearbeiter_id")}

    def team_zaehler(self, jetzt: datetime, grenze: str = "", aktiv_tage: int = 21) -> dict:
        """Zähler je aktivem Nutzer (reserviert, in_arbeit, kontakte_heute, uebernommen_heute) und Anzahl ohne Zuordnung.
        Nur Inserate, die in den letzten ``aktiv_tage`` Tagen gesehen wurden, zählen für reserviert/in_arbeit/ohne_zuordnung."""
        tag = jetzt.date().isoformat()
        seit = (jetzt - timedelta(days=aktiv_tage)).isoformat(timespec="seconds")
        arbeit = ",".join("?" * len(IN_ARBEIT))
        nutzer = [dict(r) for r in self.con.execute(
            "SELECT n.id AS nutzer_id, n.name, "
            "(SELECT COUNT(*) FROM bearbeitung b JOIN anzeigen a ON a.id=b.anzeige_id WHERE b.bearbeiter_id=n.id "
            " AND b.kontaktiert_von IS NULL AND b.uebernommen_am>=? AND a.zuletzt_gesehen>=?) AS reserviert, "
            f"(SELECT COUNT(*) FROM bearbeitung b JOIN anzeigen a ON a.id=b.anzeige_id WHERE b.bearbeiter_id=n.id "
            f" AND b.kontaktiert_von IS NOT NULL AND a.status IN ({arbeit}) AND a.zuletzt_gesehen>=?) AS in_arbeit, "
            "(SELECT COUNT(*) FROM bearbeitung b WHERE b.kontaktiert_von=n.id AND substr(b.kontaktiert_am,1,10)=?) AS kontakte_heute, "
            "(SELECT COUNT(*) FROM bearbeitung b WHERE b.bearbeiter_id=n.id AND substr(b.uebernommen_am,1,10)=?) AS uebernommen_heute "
            "FROM nutzer n WHERE n.aktiv=1 ORDER BY n.name",
            (grenze, seit, *IN_ARBEIT, seit, tag, tag))]
        ohne = self.con.execute(
            "SELECT COUNT(*) FROM anzeigen a LEFT JOIN bearbeitung b ON b.anzeige_id=a.id "
            "LEFT JOIN nutzer n ON n.id=b.bearbeiter_id AND n.aktiv=1 "
            f"WHERE a.zuletzt_gesehen>=? AND a.status IN ({arbeit}) AND b.kontaktiert_von IS NULL "
            "AND NOT (n.id IS NOT NULL AND b.uebernommen_am>=?)", (seit, *IN_ARBEIT, grenze)).fetchone()[0]
        return {"nutzer": nutzer, "ohne_zuordnung": ohne}
