"""Import: führt Suchaufträge über die Quellen aus und schreibt die Inserate in die Datenbank.

Einzige Stelle, die Quellen und Datenbank verbindet. Ablauf eines Laufs:
  1. jede Suche (config.yaml → suchen) Seite für Seite abfragen – neueste zuerst; ist eine ganze Seite
     schon bekannt, lohnt es sich nicht, tiefer zu suchen
  2. Detailseiten für Inserate ohne Details nachladen (begrenzt pro Lauf)
  3. Auffälligkeiten (Layout geändert, Sperre, Netzwerk) als Fehlertext zurückgeben

Außerdem: `importiere()` ist der einzige Schreibweg für Push-Eingänge (Lesung → Datenbank, ADR-035); `importiere_seiten()`
liest im Browser gespeicherte Seiten (Kleinanzeigen, mobile.de) aus dem Import-Ordner – ohne Netzabruf (ADR-010).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Collection
from datetime import date, datetime, timezone
from pathlib import Path

from .datenbank import BESTAETIGT, IMPORT_SUCHE, VORLAEUFIG, Datenbank, import_art, import_suche
from .domaene import PUSH_KANAELE, pruefe_anzeigen_id, pruefe_kanal
from .eingang import BegleitordnerFehler, Lesung, Rohdaten, SeitenEingang, SuchseitenArt, html_dateien, lies_html, verschiebe
from .ereignisse import InseratEreignis
from .ereignis_speicher import EreignisSpeicher
from .normalisierung.fahrzeug import art_schluessel
from .quellen import (STANDARD_QUELLE, Abruf, InseratNichtGefunden, NetzwerkFehler, Quelle, QuelleGesperrt,
                      QuellenFehler, Suchauftrag, erstelle_quelle)
from .quellen.basis import ART_QUELLE_KATEGORIE

log = logging.getLogger("scout")

LAYOUT_HINWEIS = ("{quelle}-Seite geladen, aber keine Anzeigen erkannt – vermutlich wurde das Seitenlayout "
                  "geändert. Die Seite liegt zur Analyse in {datei}; die Selektoren stehen im Parser der Quelle "
                  "(wmscout/quellen/{kennung}/parser.py).")


def _art(text: str | None) -> str | None:
    art = art_schluessel(text)
    return None if art == "Sonstige" else art


DETAIL_OHNE_ID = {
    "mobile.de": ("Anzeigenseite ohne Adresse der Anzeige (Anzeigen-ID nicht ermittelbar) – bitte die Anzeige noch einmal als "
                  "„Webseite, komplett“ speichern (so lagen alle geprüften mobile.de-Seiten vor; „nur HTML“ wurde nicht geprüft); "
                  "Datei verschoben nach nicht_erkannt/"),
}
DETAIL_OHNE_ID_STANDARD = ("Anzeigenseite ohne Adresse der Anzeige (Anzeigen-ID nicht ermittelbar) – bitte die Anzeige noch "
                           "einmal als „Webseite, nur HTML“ speichern; Datei verschoben nach nicht_erkannt/")


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
                raise QuellenFehler(f"Quelle {q.name} nicht freigegeben ({q.zugriffsart}). {q.hinweis}")
            self._quellen[kennung] = q
        return self._quellen[kennung]

    def importiere_ereignis(self, ereignis: InseratEreignis) -> str:
        """Ein normalisiertes Ereignis ohne Portalabruf in Schema v4 einlesen."""
        return EreignisSpeicher(self.db).verarbeite(ereignis)

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
        """Liest Such- und Detailseiten von Kleinanzeigen und mobile.de, die der Nutzer im Browser gespeichert hat, aus
        `ordner` (nicht rekursiv; beide Plattformen im selben Ordner).

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
        eingang = SeitenEingang()

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
                lesung = eingang.lese(Rohdaten(html.encode("utf-8"), datei.name, datetime.now(timezone.utc)))
                if lesung.art in ("unbekannt", "detail_ohne_id"):
                    verschiebe(datei, ordner / "nicht_erkannt")
                    stat["unbekannt"] += 1
                    if lesung.art == "detail_ohne_id":
                        grund = DETAIL_OHNE_ID.get(lesung.plattform, DETAIL_OHNE_ID_STANDARD)
                    elif lesung.hinweise:
                        grund = f"{'; '.join(lesung.hinweise)} – verschoben nach nicht_erkannt/"
                    else:
                        grund = "keine Kleinanzeigen- oder mobile.de-Such- oder Detailseite erkannt – verschoben nach nicht_erkannt/"
                    melde(f"{datei.name}: {grund}")
                    continue
                for h in lesung.hinweise:                                 # übersprungene Treffer, fehlende Anbieterkästen …
                    stat["fehler"].append(f"{datei.name}: {h}")
                self.importiere(lesung, eingang.kanal, stat)
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

    def importiere(self, lesung: Lesung, kanal: str, stat: dict | None = None) -> dict:
        """Einziger Schreibweg für Push-Eingänge (ADR-035): speichert eine `Lesung` über den Kanal `kanal` ('manuell', 'email').

        Prüft Kanal, Plattform und Anzeigen-ID, bevor etwas geschrieben wird (ValueError). Gespeichert wird immer über
        `speichere_treffer` mit den Regeln zur Fahrzeugart und zu „gewerblich“ von `_speichere_seite` – nie über den
        `EreignisSpeicher` (der gilt nur für api/stream, `importiere_ereignis`). Nicht speicherbare Lesungen ('unbekannt',
        'detail_ohne_id') behandelt der Aufrufer. `stat` (optional) wird fortlaufend ergänzt, auch wenn mittendrin ein Fehler
        auftritt. Rückgabe: Zähler suchseiten, detailseiten, neu, preis, bekannt, details."""
        if pruefe_kanal(kanal) not in PUSH_KANAELE:
            raise ValueError(f"Eingangskanal {kanal!r} ist kein Push-Eingang (erlaubt: {', '.join(PUSH_KANAELE)})")
        if lesung.art not in ("suche", "detail"):
            raise ValueError(f"Lesung der Art {lesung.art!r} ist nicht speicherbar")
        for inserat in lesung.inserate:
            pruefe_anzeigen_id(inserat.quelle, inserat.anzeigen_id)
        if stat is None:
            stat = {}
        for schluessel in ("suchseiten", "detailseiten", "neu", "preis", "bekannt", "details"):
            stat.setdefault(schluessel, 0)
        self._speichere_seite(lesung.art, lesung.inserate, stat, lesung.art_filter, lesung.haupttreffer, kanal)
        return stat

    def _speichere_seite(self, art: str, inserate: list, stat: dict, seitenart: SuchseitenArt | None = None,
                         haupttreffer: Collection[str] | None = None, kanal: str = "manuell"):
        """Speichert die Inserate einer Such- oder Detailseite (ungeprüft; Eintritt von außen ist `importiere`).

        Importierte Inserate bekommen die Suche „Import <Art> (bestätigt|vorläufig)“ bzw. `IMPORT_SUCHE` (Art unbekannt);
        die Herkunft steuert den Hinweis am Fahrzeug (`bewertung.anschreiben.hinweise`), sperrt aber nichts.
        Bestätigt ist nur die Art aus dem Art-Filter der Suchseite (`SuchseitenArt.filter`) – und nur für Treffer der
        Haupttabelle (`haupttreffer`, ohne Angabe: keiner; „Weitere Ergebnisse in anderen Orten“ erfüllen den Filter nicht) – oder das Feld
        „Art“ einer Detailseite oder – bei mobile.de – der Treffer selbst (Kategorie je Treffer; „Wohnmobil andere“ ist
        keine Art). Die Detailseite ist konkreter und hat Vorrang vor dem Filter, in jeder Reihenfolge der
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
            elif (d.get("details") or {}).get("art_quelle") == ART_QUELLE_KATEGORIE and (neue_art := _art(d.get("art"))):
                herkunft = BESTAETIGT                           # Kategorie des Treffers selbst (mobile.de nennt sie je Treffer)
            else:
                # Treffer außerhalb der Haupttabelle: wie eine Seite ohne Filter und ohne Hinweis
                eigene = seitenart if d["id"] in (haupttreffer or ()) else SuchseitenArt()
                neue_art, herkunft = eigene.fuer_treffer(d.get("titel"), d.get("kurzbeschreibung"))
            suche = _neue_suche(self.db.suche_zu(d["id"]), neue_art, herkunft)
            if art == "detail" and not d.get("gewerblich") and self.db.gewerblich_zu(d["id"]):
                d["gewerblich"] = None            # kein Hinweis auf der Detailseite ≠ „privat“: gewerblicher Listenwert bleibt
            stat[self.db.speichere_treffer(d, suche, kanal=kanal)] += 1
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
