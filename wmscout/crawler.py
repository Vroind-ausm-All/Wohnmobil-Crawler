"""Lädt Such- und Detailseiten – langsam und höflich, mit Pausen und Abbruch bei Sperre."""
from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

import requests

from .db import Datenbank
from .parser import parse_detailseite, parse_suchseite

log = logging.getLogger("scout")


class Gesperrt(Exception):
    pass


LAYOUT_HINWEIS = ("Kleinanzeigen-Seite geladen, aber keine Anzeigen erkannt – vermutlich wurde das Seitenlayout "
                  "geändert. Die Seite liegt zur Analyse in {datei}; die Selektoren stehen in wmscout/parser.py.")


def seiten_url(url: str, seite: int) -> str:
    """Setzt 'seite:N/' vor das letzte Pfadsegment (das mit c220...)."""
    url = re.sub(r"/seite:\d+", "", url)
    if seite <= 1:
        return url
    kopf, _, letztes = url.rpartition("/")
    return f"{kopf}/seite:{seite}/{letztes}"


class Crawler:
    def __init__(self, cfg: dict, db: Datenbank):
        self.cfg = cfg["crawler"]
        self.db = db
        ordner = Path(cfg.get("ausgabe", {}).get("ordner", "ausgabe"))
        self.diagnose_ordner = ordner if ordner.is_absolute() else Path(__file__).resolve().parent.parent / ordner
        self.layout_warnung: str | None = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.cfg["user_agent"],
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
        self.erster_abruf = True

    def _hole(self, url: str) -> str:
        if not self.erster_abruf:
            time.sleep(random.uniform(self.cfg["pause_min_sek"], self.cfg["pause_max_sek"]))
        self.erster_abruf = False
        for versuch in range(3):
            r = self.session.get(url, timeout=self.cfg["timeout_sek"])
            if r.status_code in (403, 429):
                raise Gesperrt(f"HTTP {r.status_code} – Kleinanzeigen blockt gerade. Später erneut versuchen.")
            if r.status_code >= 500:
                time.sleep(20 * (versuch + 1))
                continue
            r.raise_for_status()
            if "captcha" in r.text.lower()[:20000] and "aditem" not in r.text:
                raise Gesperrt("Captcha-Seite erhalten – Lauf abgebrochen.")
            return r.text
        r.raise_for_status()
        return r.text

    def suche(self, name: str, url: str) -> dict:
        stat = {"neu": 0, "preis": 0, "bekannt": 0}
        for seite in range(1, self.cfg["max_seiten_pro_suche"] + 1):
            html = self._hole(seiten_url(url, seite))
            treffer = parse_suchseite(html)
            log.info("  %s – Seite %d: %d Anzeigen", name, seite, len(treffer))
            if not treffer:
                if seite == 1 and len(html) > 20000:      # volle Seite, aber nichts erkannt
                    self._layout_problem("diagnose_suchseite.html", html)
                break
            nur_bekannte = True
            for t in treffer:
                if t["ist_gesuch"]:
                    continue
                ergebnis = self.db.speichere_treffer(t, name)
                stat[ergebnis] += 1
                if ergebnis != "bekannt":
                    nur_bekannte = False
            # Sortierung "neueste zuerst": ganze Seite bekannt -> tiefer suchen lohnt nicht
            if nur_bekannte and seite >= 2:
                break
        return stat

    def _layout_problem(self, dateiname: str, html: str):
        datei = self.diagnose_ordner / dateiname
        try:
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_text(html, encoding="utf-8")
        except OSError:
            pass
        self.layout_warnung = LAYOUT_HINWEIS.format(datei=datei)
        log.warning(self.layout_warnung)

    def details(self) -> int:
        offen = self.db.ohne_details(self.cfg["detailseiten_pro_lauf"])
        leer = 0
        for i, zeile in enumerate(offen, 1):
            try:
                html = self._hole(zeile["url"])
                d = parse_detailseite(html)
                if not d.get("titel") and not d.get("details"):
                    leer += 1
                    if leer == 5 and leer == i:       # die ersten fünf Detailseiten alle leer
                        self._layout_problem("diagnose_detailseite.html", html)
                self.db.speichere_details(zeile["id"], d)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (404, 410):
                    if zeile["status"] in (None, "neu"):      # Ankaufs-Status (kontaktiert …) nicht überschreiben
                        self.db.setze_status(zeile["id"], "gelöscht")
                    self.db.speichere_details(zeile["id"], {})
                else:
                    log.warning("Detailseite %s: %s", zeile["url"], e)
            if i % 10 == 0:
                log.info("  Detailseiten: %d/%d", i, len(offen))
        return len(offen)

    def lauf(self, suchen: list[dict]) -> dict:
        gesamt = {"neu": 0, "preis": 0, "bekannt": 0, "details": 0, "fehler": None}
        self.layout_warnung = None
        try:
            for s in suchen:
                log.info("Suche: %s", s["name"])
                for k, v in self.suche(s["name"], s["url"]).items():
                    gesamt[k] += v
            gesamt["details"] = self.details()
            gesamt["fehler"] = self.layout_warnung
        except Gesperrt as e:
            log.error(str(e))
            gesamt["fehler"] = str(e)
        except requests.RequestException as e:
            log.error("Netzwerkfehler: %s", e)
            gesamt["fehler"] = str(e)
        return gesamt
