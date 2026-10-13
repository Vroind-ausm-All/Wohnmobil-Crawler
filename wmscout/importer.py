"""Import: führt Suchaufträge über die Quellen aus und schreibt die Inserate in die Datenbank.

Einzige Stelle, die Quellen und Datenbank verbindet. Ablauf eines Laufs:
  1. jede Suche (config.yaml → suchen) Seite für Seite abfragen – neueste zuerst; ist eine ganze Seite
     schon bekannt, lohnt es sich nicht, tiefer zu suchen
  2. Detailseiten für Inserate ohne Details nachladen (begrenzt pro Lauf)
  3. Auffälligkeiten (Layout geändert, Sperre, Netzwerk) als Fehlertext zurückgeben
"""
from __future__ import annotations

import logging
from pathlib import Path

from .datenbank import Datenbank
from .quellen import (STANDARD_QUELLE, Abruf, InseratNichtGefunden, NetzwerkFehler, Quelle, QuelleGesperrt,
                      QuellenFehler, Suchauftrag, erstelle_quelle)

log = logging.getLogger("scout")

LAYOUT_HINWEIS = ("{quelle}-Seite geladen, aber keine Anzeigen erkannt – vermutlich wurde das Seitenlayout "
                  "geändert. Die Seite liegt zur Analyse in {datei}; die Selektoren stehen im Parser der Quelle "
                  "(wmscout/quellen/{kennung}/parser.py).")


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
