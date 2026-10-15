"""SQLite-Speicher: merkt sich alle gesehenen Anzeigen, Preisänderungen und den Kontakt-Status."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bearbeitung import IN_ARBEIT, BearbeitungsKonflikt
from .migrationen import NEUE_SPALTEN, migriere  # noqa: F401 – NEUE_SPALTEN bleibt hier importierbar (Kompatibilität)

log = logging.getLogger(__name__)
# Sekunden, die ein Zugriff auf eine von anderen gesperrte Datenbank wartet. Mit WAL warten nur noch Schreibende aufeinander
# (kurze Transaktionen); 10 s überbrücken auch einen langsamen Datenträger, ohne die App merklich hängen zu lassen.
STANDARD_WARTEZEIT = 10.0

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


STANDARD_PLATTFORM = "kleinanzeigen"          # ``anzeigen.quelle`` leer = Altbestand vor Mehrquellen


def inhalt_hash(signatur: tuple) -> str:
    """Fingerabdruck eines Inseratsstands für ``beobachtungen.inhalt_hash`` (gleich für Suche und Ereigniseingang)."""
    return hashlib.sha256(json.dumps(signatur, ensure_ascii=False).encode("utf-8")).hexdigest()


def jetzt_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wal_aktiv(cfg: dict) -> bool:
    """``ausgabe.wal`` aus config.yaml (Standard ``true``); nur echte Wahrheitswerte, damit „nein“ nicht als wahr gilt."""
    wert = (cfg.get("ausgabe") or {}).get("wal", True)
    if not isinstance(wert, bool):
        raise ValueError(f"config.yaml: ausgabe -> wal muss true oder false sein, nicht {wert!r}")
    return wert


class Datenbank:
    def __init__(self, pfad: str, sicherung_ordner: str | Path | None = None, timeout: float = STANDARD_WARTEZEIT, wal: bool = True):
        """Öffnet die Datenbank; Schema und Version verwaltet ``migrationen.migriere`` (mit Sicherung vor jeder Migration).

        ``sicherung_ordner``: Standard ist ``sicherungen`` neben der Datenbank (``daten/sicherungen``).
        Wirft ``MigrationsFehler``, wenn die Datenbank neuer ist als dieser Code oder die Sicherung scheitert.
        ``timeout``: Sekunden, die ein Zugriff auf eine von anderen gesperrte Datenbank wartet (SQLite ``busy_timeout``).
        ``wal``: Journalmodus WAL (``config.yaml`` -> ``ausgabe.wal``); ``False`` für Datenbanken auf Netzlaufwerken.
        """
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
        migriere(pfad, sicherung_ordner)
        # check_same_thread=False: die App bedient Anfragen nacheinander in einem Server-Thread
        self.con = sqlite3.connect(pfad, check_same_thread=False, timeout=timeout)
        self.con.row_factory = sqlite3.Row
        self._tiefe = 0          # >0: innerhalb von ``transaktion()`` – verschachtelte Schreibblöcke committen nicht selbst
        self.journal_modus = self._setze_journal(wal)
        try:
            self.gleiche_v4_ab()
        except sqlite3.OperationalError as e:      # z. B. gesperrt: rein ergänzend, holt der nächste Start nach
            log.warning("v4-Abgleich übersprungen (%s); er wird beim nächsten Öffnen nachgeholt.", e)

    def _setze_journal(self, wal: bool) -> str:
        """WAL: Lesende (App, Bericht, Sicherung) und ein Schreibender (Suchlauf, Ereigniseingang) blockieren einander nicht;
        nur Schreibende warten weiter aufeinander (``timeout``). Der Modus steht in der Datei und gilt für alle Verbindungen.
        Gelingt die Umstellung nicht (Datenbank gerade von anderen geöffnet, Dateisystem ohne WAL), bleibt der bisherige
        Modus – mit Warnung, ohne Abbruch. Rückgabe: tatsächlicher Modus (``wal``, ``delete``, bei ``:memory:`` ``memory``)."""
        ziel = "wal" if wal else "delete"
        try:
            modus = self.con.execute(f"PRAGMA journal_mode={ziel}").fetchone()[0]
        except sqlite3.OperationalError as e:
            modus = self.con.execute("PRAGMA journal_mode").fetchone()[0]
            log.warning("Journalmodus %s nicht gesetzt (%s); bleibt %s.", ziel, e, modus)
            return modus
        if modus not in (ziel, "memory"):
            log.warning("Journalmodus %s nicht möglich; die Datenbank bleibt im Modus %s.", ziel, modus)
        return modus

    def speichere_treffer(self, a: dict, suche: str, kanal: str = "suche") -> str:
        """Fügt ein oder aktualisiert. Rückgabe: 'neu', 'preis' (Preis gesenkt) oder 'bekannt'.

        In derselben Transaktion wird der Treffer in die v4-Tabellen gespiegelt (``spiegle_inserat``), damit Ereigniseingang,
        Preisverlauf und App dieselben Fahrzeuge kennen. ``kanal``: 'suche' (Suchlauf) oder 'manuell' (eingelesene Seite)."""
        with self._exklusiv():
            ergebnis = self.schreibe_anzeige(a, suche)
            self.spiegle_inserat(a, kanal)
        return ergebnis

    def schreibe_anzeige(self, a: dict, suche: str) -> str:
        """Nur Tabelle ``anzeigen``, ohne eigenes Commit (Teil einer Transaktion des Aufrufers)."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        alt = self.con.execute("SELECT preis FROM anzeigen WHERE id=?", (a["id"],)).fetchone()
        werte = {k: a.get(k) for k in FELDER_UPDATE}
        werte["suche"] = suche
        werte["vb"] = int(bool(a.get("vb")))
        # Ausdrücklich None (`Inserat.gewerblich`: Anbieter unbekannt, z. B. Anbieterkasten der Trefferliste fehlt) wird NULL, nicht
        # „privat“ (0) – sonst würde ein Händler ungeprüft wie ein Privatverkäufer behandelt; `anschreiben.hinweise` weist darauf hin.
        # Fehlt der Schlüssel ganz (Aufrufer ohne Anbieterangabe), bleibt es wie bisher 0.
        werte["gewerblich"] = None if "gewerblich" in a and a["gewerblich"] is None else int(bool(a.get("gewerblich")))
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
        return ergebnis

    def spiegle_inserat(self, a: dict, kanal: str) -> int:
        """v4-Gegenstück eines ``anzeigen``-Datensatzes (ohne eigenes Commit). Schlüssel ist (Plattform, Anzeigen-ID); ein zuerst
        über den Ereigniseingang angelegtes Inserat wird verknüpft (``legacy_id``) statt verdoppelt. Gesehen in Suche oder
        Seite heißt verfügbar. ``beobachtungen`` und ``preis_historie`` erhalten nur Änderungen. Rückgabe: ``inserate.id``."""
        plattform, ad_id, jetzt = a.get("quelle") or STANDARD_PLATTFORM, a["id"], jetzt_utc()
        alt = self.con.execute("SELECT * FROM inserate WHERE plattform=? AND anzeigen_id=?", (plattform, ad_id)).fetchone()
        url = a.get("url") or (alt["url"] if alt else None)
        titel = a.get("titel") or (alt["titel"] if alt else None)
        preis = a.get("preis") if a.get("preis") is not None else (alt["preis"] if alt else None)
        signatur = (url, titel, preis, "aktiv")
        if alt is None:
            self.con.execute(
                """INSERT INTO inserate (plattform, anzeigen_id, legacy_id, url, titel, preis, verfuegbarkeit,
                   erstmals_gesehen, zuletzt_gesehen)
                   VALUES (?, ?, CASE WHEN EXISTS (SELECT 1 FROM inserate WHERE legacy_id=?) THEN NULL ELSE ? END, ?, ?, ?, 'aktiv', ?, ?)""",
                (plattform, ad_id, ad_id, ad_id, url, titel, preis, jetzt, jetzt))
            inserat_id, typ = self.con.execute("SELECT last_insert_rowid()").fetchone()[0], "neu"
        else:
            inserat_id = alt["id"]
            typ = None if (alt["url"], alt["titel"], alt["preis"], alt["verfuegbarkeit"]) == signatur else "geaendert"
            self.con.execute("UPDATE inserate SET url=?, titel=?, preis=?, verfuegbarkeit='aktiv', zuletzt_gesehen=? WHERE id=?",
                             (url, titel, preis, jetzt, inserat_id))
            self.verknuepfe_inserat(inserat_id, ad_id)
        if typ:
            self.con.execute(
                """INSERT INTO beobachtungen (inserat_id, plattform, kanal, ereignis_typ, ereignis_id, zeitpunkt, preis, inhalt_hash)
                   VALUES (?, ?, ?, ?, NULL, ?, ?, ?)""", (inserat_id, plattform, kanal, typ, jetzt, preis, inhalt_hash(signatur)))
            if preis is not None and (alt is None or alt["preis"] != preis):
                self.con.execute("INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?, ?, ?, ?)",
                                 (inserat_id, jetzt, preis, kanal))
        return inserat_id

    def verknuepfe_inserat(self, inserat_id: int, ad_id: str):
        """``legacy_id`` setzen, sofern noch frei (dieselbe Anzeigen-ID auf zwei Plattformen: nur die erste wird verknüpft)."""
        self.con.execute("UPDATE inserate SET legacy_id=? WHERE id=? AND legacy_id IS NULL "
                         "AND NOT EXISTS (SELECT 1 FROM inserate WHERE legacy_id=?)", (ad_id, inserat_id, ad_id))

    def gleiche_v4_ab(self) -> int:
        """Rein ergänzender Abgleich beim Öffnen: ``anzeigen``-Zeilen ohne v4-Gegenstück (z. B. zwischen Schema v4 und diesem Stand
        gespeichert) werden angelegt bzw. verknüpft, mit erstem Preis (Kanal 'abgleich'). Ändert und löscht nichts Bestehendes;
        idempotent. Rückgabe: Anzahl neu angelegter Inserate."""
        offen = ("SELECT a.* FROM anzeigen a WHERE NOT EXISTS (SELECT 1 FROM inserate i WHERE i.legacy_id = a.id) "
                 "AND NOT EXISTS (SELECT 1 FROM inserate i WHERE i.plattform = COALESCE(NULLIF(a.quelle, ''), ?) AND i.anzeigen_id = a.id "
                 "AND i.legacy_id IS NOT NULL)")
        if self.con.execute(f"SELECT EXISTS ({offen})", (STANDARD_PLATTFORM,)).fetchone()[0] == 0:
            return 0
        neu = 0
        with self._exklusiv():
            for z in self.con.execute(offen, (STANDARD_PLATTFORM,)).fetchall():
                plattform = z["quelle"] or STANDARD_PLATTFORM
                alt = self.con.execute("SELECT id FROM inserate WHERE plattform=? AND anzeigen_id=?", (plattform, z["id"])).fetchone()
                if alt:
                    self.verknuepfe_inserat(alt["id"], z["id"])
                    continue
                cur = self.con.execute(
                    """INSERT INTO inserate (plattform, anzeigen_id, legacy_id, url, titel, preis, verfuegbarkeit,
                       erstmals_gesehen, zuletzt_gesehen)
                       VALUES (?, ?, CASE WHEN EXISTS (SELECT 1 FROM inserate WHERE legacy_id=?) THEN NULL ELSE ? END,
                               ?, ?, ?, 'unbekannt', ?, ?)""",
                    (plattform, z["id"], z["id"], z["id"], z["url"], z["titel"], z["preis"],
                     z["erstmals_gesehen"] or "", z["zuletzt_gesehen"] or ""))
                if z["preis"] is not None:
                    self.con.execute("INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?, ?, ?, 'abgleich')",
                                     (cur.lastrowid, z["zuletzt_gesehen"] or jetzt_utc(), z["preis"]))
                neu += 1
        if neu:
            log.info("v4-Abgleich: %d Inserate aus „anzeigen“ ergänzt.", neu)
        return neu

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

    def gewerblich_zu(self, ad_id: str) -> int | None:
        """Gespeicherter Anbietertyp (1 gewerblich, 0 privat); None, wenn die Anzeige neu oder der Anbieter unbekannt ist."""
        zeile = self.con.execute("SELECT gewerblich FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        return zeile["gewerblich"] if zeile else None

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
        Verbindungen (Suchlauf, zweiter Prozess). Fehler und Konflikte rollen alles zurück.

        Verschachtelt (innerhalb von ``transaktion()``) gehört die Transaktion dem äußeren Block: kein eigener Beginn, kein Commit,
        kein Rollback – ein Fehler läuft nach außen und macht dort ALLES rückgängig."""
        if self._tiefe:
            yield
            return
        if self.con.in_transaction:
            self.con.commit()
        self.con.execute("BEGIN IMMEDIATE")
        self._tiefe += 1
        try:
            yield
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise
        finally:
            self._tiefe -= 1

    @contextmanager
    def _schreiben(self):
        """Einfacher Schreibzugriff: Commit am Ende, bei jedem Fehler (z. B. „database is locked“) Rollback – auf der gemeinsamen
        App-Verbindung darf nie eine offene Transaktion zurückbleiben (sie würde die Datenbank für andere Verbindungen sperren).
        Innerhalb von ``transaktion()`` committet erst der äußere Block."""
        if self._tiefe:
            yield
            return
        try:
            yield
        except BaseException:
            self.con.rollback()
            raise
        self.con.commit()

    def transaktion(self):
        """Mehrere Schreibzugriffe (auch anderer Klassen auf dieser Verbindung, z. B. ``TeamSpeicher``) als EINE Transaktion:
        entweder alles oder – bei Konflikt, Fehler oder „database is locked“ – nichts."""
        return self._exklusiv()

    @property
    def in_transaktion(self) -> bool:
        return self._tiefe > 0

    def daten_version(self) -> int:
        """``PRAGMA data_version``: ändert sich, wenn eine ANDERE Verbindung (z. B. der Suchlauf) die Datenbank geschrieben hat."""
        return self.con.execute("PRAGMA data_version").fetchone()[0]

    def setze_status(self, ad_id: str, status: str, notiz: str | None = None, text: str | None = None,
                     betrag: int | None = None, *, nutzer_id: int | None = None, grenze: str = "", erzwingen: bool = False,
                     inhaber: bool = False, dubletten=()) -> bool:
        """Mit Text (= Anschreiben gesendet) werden Zeitpunkt, Text und Angebot gespeichert; 'neu' setzt zurück.

        Ohne ``nutzer_id`` (Team aus) wie bisher. Mit ``nutzer_id``: 'kontaktiert', 'verhandlung' und 'besichtigung' (alle
        ``IN_ARBEIT``; sie setzen einen Kontakt voraus) übernehmen das Inserat zuerst (wie ``uebernimm``, inkl. Dubletten) und
        tragen den ersten Kontakt ein – sonst bliebe ein so bearbeitetes Inserat „ohne Zuordnung“ und ein Kollege könnte es
        erneut kontaktieren. Ausnahme: ``inhaber`` (Inhaber oder zugewiesener Besichtiger) ändert 'verhandlung'/'besichtigung'
        eines von einem Kollegen gehaltenen Inserats, ohne es zu übernehmen – außer mit ``erzwingen``, das übernimmt wirklich.
        'neu' leert den Kontakt (Bearbeiter bleibt); alle anderen Status verlangen: frei, eigene Reservierung oder ``inhaber``.
        Sonst ``BearbeitungsKonflikt`` – dann ist nichts geändert."""
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
            with self._schreiben():
                cur = self.con.execute(sql, [*werte, ad_id])
            return cur.rowcount > 0
        with self._exklusiv():
            if not self.con.execute("SELECT 1 FROM anzeigen WHERE id=?", (ad_id,)).fetchone():
                return False
            uebernehmen = status in IN_ARBEIT
            if uebernehmen and status != "kontaktiert" and inhaber and not erzwingen \
                    and self._fremde_halter([ad_id], nutzer_id, grenze):
                uebernehmen = False                                 # fremdes Inserat: Status ändern, Bearbeiter bleibt (nicht bei Erzwingen)
            if uebernehmen:
                if not self._uebernimm(ad_id, nutzer_id, jetzt, grenze, erzwingen, dubletten):
                    raise BearbeitungsKonflikt(ad_id)
            elif status not in IN_ARBEIT and not inhaber and self._fremde_halter([ad_id], nutzer_id, grenze):
                raise BearbeitungsKonflikt(ad_id)
            cur = self.con.execute(sql, [*werte, ad_id])
            if uebernehmen:
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
            with self._schreiben():
                cur = self.con.execute(sql, werte)
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
        with self._schreiben():
            cur = self.con.execute("UPDATE anzeigen SET notiz=? WHERE id=?", (notiz, ad_id))
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
        "OR (bearbeitung.kontaktiert_von IS NULL AND COALESCE(bearbeitung.uebernommen_am, '') < :grenze) "
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
            "AND (b.kontaktiert_von IS NOT NULL OR COALESCE(b.uebernommen_am, '')>=?) LIMIT 1", (*ids, nutzer_id, grenze)).fetchone()

    def _kontaktierte_dublette_anderer(self, ids, ziel_id: int) -> str | None:
        """ID einer Dublette, die ein anderer aktiver Kollege als ``ziel_id`` bearbeitet und bereits kontaktiert hat (sonst None).
        Sie lässt sich nicht stillschweigend mitnehmen: erst dort zuweisen."""
        ids = list(ids)
        if not ids:
            return None
        r = self.con.execute(
            "SELECT b.anzeige_id FROM bearbeitung b JOIN nutzer n ON n.id=b.bearbeiter_id AND n.aktiv=1 "
            f"WHERE b.anzeige_id IN ({','.join('?' * len(ids))}) AND b.bearbeiter_id<>? AND b.kontaktiert_von IS NOT NULL LIMIT 1",
            (*ids, ziel_id)).fetchone()
        return r[0] if r else None

    def _uebertrage_reservierungen(self, ids, ziel_id: int, jetzt: str, grenze: str):
        """Wirksame, noch nicht kontaktierte Reservierungen anderer Kollegen auf den Dubletten gehen auf ``ziel_id`` über – sonst
        blockieren sich die Gruppe und der neue Bearbeiter gegenseitig (er hält A, der Alte noch B)."""
        ids = list(ids)
        if ids:
            self.con.execute(
                "UPDATE bearbeitung SET bearbeiter_id=?, uebernommen_am=? "
                f"WHERE anzeige_id IN ({','.join('?' * len(ids))}) AND kontaktiert_von IS NULL AND bearbeiter_id<>? "
                "AND bearbeiter_id IN (SELECT id FROM nutzer WHERE aktiv=1) AND COALESCE(uebernommen_am, '')>=?",
                (ziel_id, jetzt, *ids, ziel_id, grenze))

    def _uebernimm(self, ad_id: str, nutzer_id: int, jetzt: str, grenze: str, erzwingen: bool, dubletten) -> bool:
        """Nur innerhalb von ``_exklusiv``: Dubletten prüfen (liest), dann EIN bedingtes UPSERT (rowcount 0 = Konflikt).
        Mit ``erzwingen`` wandern nicht kontaktierte Reservierungen der Dubletten auf den Übernehmer; eine kontaktierte Dublette
        eines anderen verhindert es (False)."""
        andere = [d for d in dubletten if d != ad_id]
        if andere:
            if not erzwingen and self._fremde_halter(andere, nutzer_id, grenze):
                return False
            if erzwingen and self._kontaktierte_dublette_anderer(andere, nutzer_id):
                return False
        cur = self.con.execute(self._UEBERNAHME, {"id": ad_id, "nutzer": nutzer_id, "jetzt": jetzt, "grenze": grenze,
                                                  "erzwingen": int(bool(erzwingen))})
        if cur.rowcount > 0 and erzwingen:
            self._uebertrage_reservierungen(andere, nutzer_id, jetzt, grenze)
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
        with self._schreiben():
            cur = self.con.execute("DELETE FROM bearbeitung WHERE anzeige_id=? AND kontaktiert_von IS NULL "
                                   "AND (bearbeiter_id=? OR ?)", (anzeige_id, nutzer_id, int(bool(inhaber))))
        return cur.rowcount > 0

    def weise_zu(self, anzeige_id: str, ziel_id: int, jetzt: str, dubletten=(), grenze: str = "") -> None:
        """Inserat einem Kollegen zuweisen (Berechtigung „Inhaber“ prüft der Aufrufer). ``kontaktiert_von/_am`` bleiben.

        ``dubletten``: nicht kontaktierte Reservierungen der Gruppe gehen mit auf ``ziel_id`` über (``grenze`` wie bei
        ``uebernimm``); hat ein anderer Kollege eine Dublette bereits kontaktiert, ``BearbeitungsKonflikt`` mit deren ID und
        nichts geändert – erst dort zuweisen."""
        andere = [d for d in dubletten if d != anzeige_id]
        with self._exklusiv():
            d = self._kontaktierte_dublette_anderer(andere, ziel_id)
            if d:
                raise BearbeitungsKonflikt(d)
            self.con.execute(
                "INSERT INTO bearbeitung(anzeige_id, bearbeiter_id, uebernommen_am) VALUES(?,?,?) "
                "ON CONFLICT(anzeige_id) DO UPDATE SET bearbeiter_id=excluded.bearbeiter_id, uebernommen_am=excluded.uebernommen_am",
                (anzeige_id, ziel_id, jetzt))
            self._uebertrage_reservierungen(andere, ziel_id, jetzt, grenze)

    def bearbeitung_aktiv(self) -> dict[str, dict]:
        """Alle Zeilen aus ``bearbeitung`` (ein SELECT) mit Flag ``bearbeiter_aktiv`` (Bearbeiter existiert und ist aktiv)."""
        return {r["anzeige_id"]: dict(r) for r in self.con.execute(
            "SELECT b.anzeige_id, b.bearbeiter_id, b.uebernommen_am, b.kontaktiert_von, b.kontaktiert_am, "
            "COALESCE(n.aktiv, 0) AS bearbeiter_aktiv FROM bearbeitung b LEFT JOIN nutzer n ON n.id=b.bearbeiter_id")}

    def team_zaehler(self, jetzt: datetime, grenze: str = "", aktiv_tage: int = 21) -> dict:
        """Zähler je aktivem Nutzer (reserviert, in_arbeit, kontakte_heute, uebernommen_heute) sowie ``ohne_zuordnung`` (in Arbeit,
        nie zugeordnet) und ``verwaist`` (kontaktiert, Bearbeiter deaktiviert). Nur Inserate, die in den letzten ``aktiv_tage`` Tagen
        gesehen wurden, zählen für reserviert/in_arbeit/ohne_zuordnung/verwaist."""
        tag = jetzt.date().isoformat()
        seit = (jetzt - timedelta(days=aktiv_tage)).isoformat(timespec="seconds")
        arbeit = ",".join("?" * len(IN_ARBEIT))
        nutzer = [dict(r) for r in self.con.execute(
            "SELECT n.id AS nutzer_id, n.name, "
            "(SELECT COUNT(*) FROM bearbeitung b JOIN anzeigen a ON a.id=b.anzeige_id WHERE b.bearbeiter_id=n.id "
            " AND b.kontaktiert_von IS NULL AND COALESCE(b.uebernommen_am, '')>=? AND a.zuletzt_gesehen>=?) AS reserviert, "
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
            "AND NOT (n.id IS NOT NULL AND COALESCE(b.uebernommen_am, '')>=?)", (seit, *IN_ARBEIT, grenze)).fetchone()[0]
        # kontaktiert, aber der Bearbeiter ist deaktiviert (oder fehlt): fällt sonst aus allen Zählern, ist aber übernehmbar
        verwaist = self.con.execute(
            "SELECT COUNT(*) FROM anzeigen a JOIN bearbeitung b ON b.anzeige_id=a.id "
            "LEFT JOIN nutzer n ON n.id=b.bearbeiter_id AND n.aktiv=1 "
            f"WHERE a.zuletzt_gesehen>=? AND a.status IN ({arbeit}) AND b.kontaktiert_von IS NOT NULL AND n.id IS NULL",
            (seit, *IN_ARBEIT)).fetchone()[0]
        return {"nutzer": nutzer, "ohne_zuordnung": ohne, "verwaist": verwaist}
