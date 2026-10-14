"""Import: führt Suchaufträge über die Quellen aus und schreibt die Inserate in die Datenbank.

Einzige Stelle, die Quellen und Datenbank verbindet. Ablauf eines Laufs:
  1. jede Suche (config.yaml → suchen) Seite für Seite abfragen – neueste zuerst; ist eine ganze Seite
     schon bekannt, lohnt es sich nicht, tiefer zu suchen
  2. Detailseiten für Inserate ohne Details nachladen (begrenzt pro Lauf)
  3. Auffälligkeiten (Layout geändert, Sperre, Netzwerk) als Fehlertext zurückgeben

Außerdem: `importiere_seiten()` liest im Browser gespeicherte Seiten aus dem Import-Ordner – ohne Netzabruf (ADR-010).
"""
from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

from .datenbank import BESTAETIGT, IMPORT_SUCHE, VORLAEUFIG, Datenbank, import_art, import_suche
from .eingang import (BegleitordnerFehler, SuchseitenArt, erkenne_seite, fahrzeugart_der_suchseite, haupttabelle_ids,
                      html_dateien, lies_html, verschiebe)
from .normalisierung.fahrzeug import art_schluessel
from .quellen import (STANDARD_QUELLE, Abruf, InseratNichtGefunden, NetzwerkFehler, Quelle, QuelleGesperrt,
                      QuellenFehler, Suchauftrag, erstelle_quelle)

log = logging.getLogger("scout")

LAYOUT_HINWEIS = ("{quelle}-Seite geladen, aber keine Anzeigen erkannt – vermutlich wurde das Seitenlayout "
                  "geändert. Die Seite liegt zur Analyse in {datei}; die Selektoren stehen im Parser der Quelle "
                  "(wmscout/quellen/{kennung}/parser.py).")


def _art(text: str | None) -> str | None:
    art = art_schluessel(text)
    return None if art == "Sonstige" else art


def _neue_suche(alt: str | None, art: str | None, herkunft: str | None) -> str:
    """Suche, unter der ein importiertes Inserat gespeichert wird (Herkunft der Art in `suche` kodiert).

    alt: bisherige Suche (None = neu). art/herkunft: Art und ihre Herkunft („bestaetigt“ = Art-Filter der Suchseite
    oder Feld „Art“ der Detailseite, „vorlaeufig“ = Titel/Suchwort, None = keine Art erkannt).
    Rangfolge bestätigt > vorläufig > unbekannt:
    * bestätigt wird nur durch eine neue bestätigte Art geändert;
    * eine vorläufige Art nimmt nur an, wer noch unbekannt ist; ein abweichender vorläufiger Wert macht das
      Inserat unbekannt (Widerspruch – das Ergebnis hängt so nicht von der Reihenfolge der Seiten ab);
    * „Import <Art>“ ohne Markierung (Altbestand) gilt als vorläufig; Crawler-Suchen bleiben unberührt."""
    alt_art, alt_herkunft = import_art(alt)
    if alt is not None and alt_herkunft is None:
        return alt                                           # Crawler-Suche
    if art and herkunft == BESTAETIGT:
        return import_suche(art, BESTAETIGT)
    if alt_herkunft == BESTAETIGT:
        return alt
    if art and herkunft == VORLAEUFIG:
        if alt_herkunft == VORLAEUFIG:
            return import_suche(art, VORLAEUFIG) if art == alt_art else IMPORT_SUCHE
        return import_suche(art, VORLAEUFIG)                 # bisher unbekannt oder neu
    return import_suche(alt_art, alt_herkunft) if alt_herkunft == VORLAEUFIG else IMPORT_SUCHE


class Importer:
    def __init__(self, cfg: dict, db: Datenbank, abruf: Abruf | None = None):
        """abruf: gemeinsamer Abruf für alle Quellen (Tests); sonst nutzt jede Quelle ihren eigenen."""
        self.cfg = cfg
        self.db = db
        self.abruf = abruf
        self._quellen: dict[str, Quelle] = {}
        ordner = Path(cfg.get("ausgabe", {}).get("ordner", "ausgabe"))
        self.diagnose_ordner = ordner if ordner.is_absolute() else Path(__file__).resolve().parent.parent / ordner
        self.layout_warnung: str | None = None

    def quelle(self, kennung: str) -> Quelle:
        if kennung not in self._quellen:
            q = erstelle_quelle(kennung, self.cfg, self.abruf)
            if not q.freigegeben:
                log.warning("Quelle %s ist nicht vom Anbieter freigegeben (%s). %s", q.name, q.zugriffsart, q.hinweis)
            self._quellen[kennung] = q
        return self._quellen[kennung]

    # ---------- Suche ----------
    def suche(self, auftrag: Suchauftrag) -> dict:
        stat = {"neu": 0, "preis": 0, "bekannt": 0}
        quelle = self.quelle(auftrag.quelle)
        for seite in quelle.suche(auftrag):
            log.info("  %s – Seite %d: %d Anzeigen", auftrag.name, seite.nummer, len(seite.inserate))
            if seite.layout_verdacht:
                self._layout_problem(quelle, "diagnose_suchseite.html", seite.rohdaten or "")
            if not seite.inserate:
                break
            nur_bekannte = True
            for inserat in seite.inserate:
                if inserat.ist_gesuch:
                    continue
                ergebnis = self.db.speichere_treffer(inserat.als_datensatz(), auftrag.name)
                stat[ergebnis] += 1
                if ergebnis != "bekannt":
                    nur_bekannte = False
            # Sortierung "neueste zuerst": ganze Seite bekannt -> tiefer suchen lohnt nicht
            if nur_bekannte and seite.nummer >= 2:
                break
        return stat

    def _layout_problem(self, quelle: Quelle, dateiname: str, rohdaten: str):
        datei = self.diagnose_ordner / dateiname
        try:
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_text(rohdaten, encoding="utf-8")
        except OSError:
            pass
        self.layout_warnung = LAYOUT_HINWEIS.format(quelle=quelle.name, datei=datei, kennung=quelle.kennung)
        log.warning(self.layout_warnung)

    # ---------- Details ----------
    def details(self) -> int:
        offen = self.db.ohne_details(self.cfg["crawler"]["detailseiten_pro_lauf"])
        leer = 0
        for i, zeile in enumerate(offen, 1):
            kennung = zeile["quelle"] if "quelle" in zeile.keys() and zeile["quelle"] else STANDARD_QUELLE
            quelle = self.quelle(kennung)
            if not quelle.unterstuetzt_details:
                self.db.speichere_details(zeile["id"], {})       # nichts nachzuladen – Platz freigeben
                continue
            try:
                inserat = quelle.details(zeile["url"])
                if not inserat.titel and not inserat.details:
                    leer += 1
                    if leer == 5 and leer == i:       # die ersten fünf Detailseiten alle leer
                        self._layout_problem(quelle, "diagnose_detailseite.html",
                                             getattr(quelle, "letzte_rohdaten", None) or "")
                self.db.speichere_details(zeile["id"], inserat.als_datensatz())
            except InseratNichtGefunden:
                if zeile["status"] in (None, "neu"):      # Ankaufs-Status (kontaktiert …) nicht überschreiben
                    self.db.setze_status(zeile["id"], "gelöscht")
                self.db.speichere_details(zeile["id"], {})
            except (QuelleGesperrt, NetzwerkFehler):
                raise
            except QuellenFehler as e:
                log.warning("Detailseite %s: %s", zeile["url"], e)
            if i % 10 == 0:
                log.info("  Detailseiten: %d/%d", i, len(offen))
        return len(offen)

    # ---------- Gespeicherte Seiten (ohne Netz) ----------
    def importiere_seiten(self, ordner: Path, max_dateien: int | None = None, max_sekunden: float | None = None) -> dict:
        """Liest Such- und Detailseiten, die der Nutzer im Browser gespeichert hat, aus `ordner` (nicht rekursiv).

        Benutzt weder `self.abruf` noch eine Quelle – es wird nur ausgewertet, was in den Dateien steht.
        Eingelesene Dateien wandern nach <ordner>/eingelesen/<Datum>/, nicht erkannte nach <ordner>/nicht_erkannt/.
        max_dateien / max_sekunden begrenzen einen Durchgang (mindestens eine Datei wird gelesen); der Rest wird
        in `uebrig` gezählt und beim nächsten Durchgang gelesen. `fehlerhaft` = Dateien, die nicht gelesen werden
        konnten (bleiben liegen).
        """
        stat = {"dateien": 0, "suchseiten": 0, "detailseiten": 0, "unbekannt": 0, "fehlerhaft": 0, "neu": 0,
                "preis": 0, "bekannt": 0, "details": 0, "fehler": [], "uebrig": 0}
        dateien = html_dateien(ordner)
        if max_dateien is not None and len(dateien) > max_dateien:
            dateien, stat["uebrig"] = dateien[:max_dateien], len(dateien) - max_dateien
        eingelesen = ordner / "eingelesen" / date.today().isoformat()
        start = time.monotonic()

        def melde(text: str):
            log.warning("Gespeicherte Seite %s", text)
            stat["fehler"].append(text)

        for n, datei in enumerate(dateien):
            if max_sekunden is not None and n and time.monotonic() - start > max_sekunden:
                stat["uebrig"] += len(dateien) - n
                break
            stat["dateien"] += 1
            try:
                html = lies_html(datei)
                art, inserate = erkenne_seite(html)
                if art in ("unbekannt", "detail_ohne_id"):
                    verschiebe(datei, ordner / "nicht_erkannt")
                    stat["unbekannt"] += 1
                    melde(f"{datei.name}: " + (
                        "Anzeigenseite ohne Adresse der Anzeige (Anzeigen-ID nicht ermittelbar) – bitte die Anzeige noch "
                        "einmal als „Webseite, nur HTML“ speichern; Datei verschoben nach nicht_erkannt/"
                        if art == "detail_ohne_id" else
                        "keine Kleinanzeigen-Such- oder Detailseite erkannt – verschoben nach nicht_erkannt/"))
                    continue
                suchseite = art == "suche"
                self._speichere_seite(art, inserate, stat, fahrzeugart_der_suchseite(html) if suchseite else None,
                                      haupttabelle_ids(html) if suchseite else None)
            except Exception as e:  # noqa: BLE001 – eine kaputte Datei darf die übrigen nicht aufhalten
                stat["fehlerhaft"] += 1
                melde(f"{datei.name}: nicht eingelesen ({e}) – Datei bleibt liegen")
                continue
            try:
                verschiebe(datei, eingelesen)
            except BegleitordnerFehler as e:
                melde(f"{datei.name}: eingelesen und verschoben, aber {e} – bitte von Hand aufräumen")
            except OSError as e:
                melde(f"{datei.name}: eingelesen, aber nicht verschoben ({e}) – Datei liegt noch im Import-Ordner "
                      "(wird beim nächsten Mal ohne Dubletten erneut gelesen)")
        log.info("Gespeicherte Seiten: %d Dateien (%d Suche, %d Detail, %d nicht erkannt, %d fehlerhaft) – %d neu, "
                 "%d Preissenkungen, %d bekannt", stat["dateien"], stat["suchseiten"], stat["detailseiten"],
                 stat["unbekannt"], stat["fehlerhaft"], stat["neu"], stat["preis"], stat["bekannt"])
        return stat

    def _speichere_seite(self, art: str, inserate: list, stat: dict, seitenart: SuchseitenArt | None = None,
                         haupttreffer: set[str] | None = None):
        """Speichert die Inserate einer Such- oder Detailseite.

        Importierte Inserate bekommen die Suche „Import <Art> (bestätigt|vorläufig)“ bzw. `IMPORT_SUCHE` (Art unbekannt);
        die Herkunft steuert den Hinweis am Fahrzeug (`bewertung.anschreiben.hinweise`), sperrt aber nichts.
        Bestätigt ist nur die Art aus dem Art-Filter der Suchseite (`SuchseitenArt.filter`) – und nur für Treffer der
        Haupttabelle (`haupttreffer`, ohne Angabe: keiner; „Weitere Ergebnisse in anderen Orten“ erfüllen den Filter nicht) – oder das Feld
        „Art“ einer Detailseite. Die Detailseite ist konkreter und hat Vorrang vor dem Filter, in jeder Reihenfolge der
        Seiten. Art aus dem eigenen Titel oder einem Suchwort ist vorläufig (`SuchseitenArt.fuer_treffer`).
        Siehe `_neue_suche` für das Überschreiben."""
        if art == "suche":
            stat["suchseiten"] += 1
        else:
            stat["detailseiten"] += 1
        seitenart = seitenart or SuchseitenArt()
        for inserat in inserate:
            d = inserat.als_datensatz()
            if art == "detail":
                if neue_art := _art(d.get("art")):
                    herkunft = BESTAETIGT                       # Feld „Art“ der Anzeige selbst
                else:
                    neue_art, herkunft = SuchseitenArt().fuer_treffer(d.get("titel"), d.get("kurzbeschreibung"))
            elif neue_art := _art(self.db.detail_art(d["id"])):
                herkunft = BESTAETIGT                           # schon eingelesene Anzeigenseite geht dem Filter vor
            else:
                # Treffer außerhalb der Haupttabelle: wie eine Seite ohne Filter und ohne Hinweis
                eigene = seitenart if d["id"] in (haupttreffer or ()) else SuchseitenArt()
                neue_art, herkunft = eigene.fuer_treffer(d.get("titel"), d.get("kurzbeschreibung"))
            suche = _neue_suche(self.db.suche_zu(d["id"]), neue_art, herkunft)
            if art == "detail" and not d.get("gewerblich"):
                d["gewerblich"] = None            # kein Hinweis auf der Detailseite ≠ „privat“: Suchlistenwert bleibt
            stat[self.db.speichere_treffer(d, suche)] += 1
            if art == "detail":
                self.db.speichere_details(d["id"], d)
                stat["details"] += 1

    # ---------- Lauf ----------
    def lauf(self, suchen: list[dict]) -> dict:
        gesamt = {"neu": 0, "preis": 0, "bekannt": 0, "details": 0, "fehler": None}
        self.layout_warnung = None
        try:
            for eintrag in suchen:
                auftrag = Suchauftrag.aus_config(eintrag)
                log.info("Suche: %s", auftrag.name)
                for k, v in self.suche(auftrag).items():
                    gesamt[k] += v
            gesamt["details"] = self.details()
            gesamt["fehler"] = self.layout_warnung
        except QuelleGesperrt as e:
            log.error(str(e))
            gesamt["fehler"] = str(e)
        except QuellenFehler as e:
            log.error("%s", e)
            gesamt["fehler"] = str(e)
        return gesamt
