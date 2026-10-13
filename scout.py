#!/usr/bin/env python3
"""Wohnmobil-Scout – Kleinanzeigen-Crawler, Händler-EK-Rechner und Anschreiben.

  python scout.py lauf                      Crawlen + bewerten + Report (+ Mail)
  python scout.py report                    Nur Report neu erzeugen (ohne Internet)
  python scout.py rechne --preis 32900 --ez 2016 --km 98000 [--marktwert 34000]
  python scout.py status <ID> kontaktiert   Status setzen (neu|kontaktiert|uninteressant|gekauft)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from wmscout.anschreiben import euro
from wmscout.crawler import Crawler
from wmscout.db import Datenbank
from wmscout.rechner import Rechner
from wmscout.report import bewerte_alle, schreibe_ausgaben, sende_mail

BASIS = Path(__file__).resolve().parent


def lade_config(pfad: str) -> dict:
    with open(BASIS / pfad, encoding="utf-8") as f:
        return yaml.safe_load(f)


def logging_einrichten(cfg: dict):
    ordner = BASIS / cfg["ausgabe"]["ordner"]
    ordner.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(ordner / "scout.log", encoding="utf-8")])


def cmd_lauf(cfg, db, args):
    start = datetime.now().isoformat(timespec="seconds")
    stat = Crawler(cfg, db).lauf(cfg["suchen"])
    logging.info("Crawl fertig: %d neu, %d Preissenkungen, %d bekannt, %d Detailseiten",
                 stat["neu"], stat["preis"], stat["bekannt"], stat["details"])
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, fehler=stat["fehler"])
    logging.info("Report: %s  (%s)", erg["html"], erg["zaehl"])
    sende_mail(cfg, zeilen, erg)


def cmd_report(cfg, db, args):
    zeilen = bewerte_alle(cfg, db, BASIS)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS)
    print(f"Report: {erg['html']}\nCSV:    {erg['csv']}\n{erg['zaehl']}")


def cmd_rechne(cfg, db, args):
    a = {"id": "manuell", "preis": args.preis, "ez_jahr": args.ez, "km": args.km, "marke": args.marke,
         "suche": args.art}
    vergleich = [dict(r) for r in db.alle_mit_preis()]
    b = Rechner(cfg).bewerte(a, vergleich, marktwert_manuell=args.marktwert)
    print(f"\nVergleichspreis Angebote : {euro(b.marktwert_angebote)}   ({b.vergleich_basis}, n={b.vergleich_anzahl})")
    print(f"Marktwert privat         : {euro(b.marktwert_privat)}")
    print(f"Händler-VK (Ziel)        : {euro(b.haendler_vk)}")
    for n, w in b.kosten_posten.items():
        print(f"  − {n:<22}: {euro(w)}")
    print(f"Ziel-Marge (netto)       : {euro(b.ziel_marge)}")
    print("-" * 46)
    print(f"MAX. EINKAUFSPREIS       : {euro(b.max_ek)}")
    print(f"Erstangebot              : {euro(b.erstangebot)}")
    if b.angebotspreis:
        print(f"Angebot / Max-EK         : {b.verhaeltnis:.0%}  → Ampel {b.ampel.upper()}")
        print(f"Gewinn bei Angebotspreis : {euro(b.potenzial)}")


def cmd_status(cfg, db, args):
    ok = db.setze_status(args.id, args.status, args.notiz)
    print("gespeichert" if ok else f"Anzeige {args.id} nicht gefunden")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lauf", help="crawlen, bewerten, Report erzeugen")
    sub.add_parser("report", help="Report aus vorhandenen Daten neu erzeugen")
    r = sub.add_parser("rechne", help="Einzelfahrzeug durchrechnen")
    r.add_argument("--preis", type=int, help="Angebotspreis des Verkäufers")
    r.add_argument("--ez", type=int, help="Erstzulassungsjahr")
    r.add_argument("--km", type=int)
    r.add_argument("--marke")
    r.add_argument("--art", default="Teilintegrierter", help="Name einer Suche aus config.yaml")
    r.add_argument("--marktwert", type=int, help="eigener Marktwert (z. B. aus mobile.de/DAT) statt Vergleich")
    s = sub.add_parser("status", help="Status einer Anzeige setzen")
    s.add_argument("id")
    s.add_argument("status", choices=["neu", "kontaktiert", "uninteressant", "gekauft"])
    s.add_argument("--notiz")
    args = p.parse_args()

    cfg = lade_config(args.config)
    logging_einrichten(cfg)
    db = Datenbank(str(BASIS / cfg["ausgabe"]["datenbank"]))
    {"lauf": cmd_lauf, "report": cmd_report, "rechne": cmd_rechne, "status": cmd_status}[args.cmd](cfg, db, args)


if __name__ == "__main__":
    main()
