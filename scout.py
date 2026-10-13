#!/usr/bin/env python3
"""Wohnmobil-Scout – Kleinanzeigen-Crawler, Händler-EK-Rechner und Anschreiben.

  python scout.py app                       Browser-App: Wohnmobile anklicken und anschreiben
  python scout.py lauf                      Crawlen + bewerten + Report (+ Mail)
  python scout.py report                    Nur Report neu erzeugen (ohne Internet)
  python scout.py rechne --preis 32900 --ez 2016 --km 98000 --titel "Knaus Sky TI 650 MEG" [--anschreiben]
  python scout.py status <ID> kontaktiert   Status setzen (neu|kontaktiert|verhandlung|besichtigung|gekauft|abgesagt|uninteressant)
"""
from __future__ import annotations

import sys
from importlib.util import find_spec

# Windows: umgeleitete Ausgabe (Pipe, Aufgabenplanung) wäre sonst cp1252 und scheitert an „−“, „✓“ usw.
for _strom in (sys.stdout, sys.stderr):
    if hasattr(_strom, "reconfigure"):
        _strom.reconfigure(encoding="utf-8", errors="replace")

if not (3, 10) <= sys.version_info[:2] <= (3, 13):
    print(f"Hinweis: Wohnmobil-Scout ist für Python 3.10–3.13 gedacht, verwendet wird {sys.version.split()[0]}.\n"
          "Unter Windows bitte über app.bat starten – das richtet automatisch eine passende Umgebung (.venv) ein.",
          file=sys.stderr)
_fehlt = [paket for paket, modul in (("requests", "requests"), ("beautifulsoup4", "bs4"), ("PyYAML", "yaml"),
                                     ("Jinja2", "jinja2")) if find_spec(modul) is None]
if _fehlt:
    sys.exit(f"Fehlende Python-Pakete: {', '.join(_fehlt)}\n"
             "Windows: bitte das Programm per Doppelklick auf app.bat starten (installiert alles in .venv).\n"
             "macOS/Linux: ./start.sh (richtet .venv automatisch ein)")

import argparse
import logging
from datetime import datetime
from pathlib import Path

import yaml

from wmscout.ausgabe import schreibe_ausgaben
from wmscout.benachrichtigung import sende_mail
from wmscout.bewertung.anschreiben import Anschreiber, euro
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import STATUS, Datenbank
from wmscout.importer import Importer
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug

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
    stat = Importer(cfg, db).lauf(cfg["suchen"])
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
    a = ergaenze_fahrzeug({"id": "manuell", "preis": args.preis, "ez_jahr": args.ez, "km": args.km,
                           "marke": args.marke, "titel": args.titel or args.marke or "", "beschreibung": args.text,
                           "suche": args.art, "ort": args.ort, "vb": True})
    vergleich = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    b = Rechner(cfg).bewerte(a, vergleich, marktwert_manuell=args.marktwert)
    print(f"\nFahrzeug                 : {a['fahrzeug']} ({b.art}, EZ {a['ez_jahr'] or '?'}, "
          f"{a['km'] or '?'} km)")
    if b.modellwert:
        print(f"Referenzwert (Modell)    : {euro(b.modellwert)}   (km-Korrektur {b.km_korrektur:+.1%})")
    for n, w in b.wertfaktoren.items():
        print(f"  {n:<23}: {w:+.1%}")
    print(f"Marktniveau Angebote     : {euro(b.marktwert_angebote)}   Sicherheit {b.sicherheit}"
          + (f", plausibel {euro(b.spanne_von)} – {euro(b.spanne_bis)}" if b.spanne_von else ""))
    print(f"  Basis: {b.vergleich_basis}")
    print(f"Marktwert privat         : {euro(b.marktwert_privat)}")
    print(f"Händler-VK (Ziel)        : {euro(b.haendler_vk)}")
    for n, w in b.kosten_posten.items():
        print(f"  − {n:<22}: {euro(w)}")
    print(f"Ziel-Marge (netto)       : {euro(b.ziel_marge)}")
    print("-" * 46)
    print(f"MAX. EINKAUFSPREIS       : {euro(b.max_ek)}")
    print(f"Erstangebot              : {euro(b.erstangebot)}")
    if b.fair_anteil:
        print(f"Fair-Check               : Erstangebot {b.fair_anteil:.0%}, Max-EK {b.max_anteil:.0%} vom Marktwert privat")
    if b.fair_hinweis:
        print(f"  Hinweis: {b.fair_hinweis}")
    if b.angebotspreis and b.verhaeltnis:
        print(f"Angebot / Max-EK         : {b.verhaeltnis:.0%}  → Ampel {b.ampel.upper()}")
        print(f"Gewinn bei Angebotspreis : {euro(b.potenzial)}")
    if args.anschreiben:
        print("\n--- Anschreiben ---\n" + Anschreiber(cfg, BASIS).text(a, b))


def cmd_app(cfg, db, args):
    from wmscout.app import starte
    starte(cfg, db, BASIS, port=args.port, browser=not args.kein_browser)


def cmd_status(cfg, db, args):
    ok = db.setze_status(args.id, args.status, args.notiz)
    print("gespeichert" if ok else f"Anzeige {args.id} nicht gefunden")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("app", help="Browser-App starten: anklicken, anschreiben, Status speichern")
    a.add_argument("--port", type=int, help="Standard: config.yaml → app → port (8765)")
    a.add_argument("--kein-browser", action="store_true", help="Browser nicht automatisch öffnen")
    sub.add_parser("lauf", help="crawlen, bewerten, Report erzeugen")
    sub.add_parser("report", help="Report aus vorhandenen Daten neu erzeugen")
    r = sub.add_parser("rechne", help="Einzelfahrzeug durchrechnen")
    r.add_argument("--preis", type=int, help="Angebotspreis des Verkäufers")
    r.add_argument("--ez", type=int, help="Erstzulassungsjahr")
    r.add_argument("--km", type=int)
    r.add_argument("--marke")
    r.add_argument("--titel", help='Anzeigentitel/Modell, z. B. "Knaus Sky TI 650 MEG" (erkennt Marke + Modell)')
    r.add_argument("--text", help="Beschreibung (Ausstattung/Mängel fließen in die Bewertung ein)")
    r.add_argument("--art", default="Teilintegrierter", help="Kastenwagen, Teilintegrierter, Alkoven, Integrierter …")
    r.add_argument("--ort", help="Standort des Fahrzeugs (für das Anschreiben)")
    r.add_argument("--marktwert", type=int, help="eigener Marktwert (z. B. aus mobile.de/DAT) statt Vergleich")
    r.add_argument("--anschreiben", action="store_true", help="passendes Anschreiben mit ausgeben")
    s = sub.add_parser("status", help="Status einer Anzeige setzen")
    s.add_argument("id")
    s.add_argument("status", choices=list(STATUS))
    s.add_argument("--notiz")
    args = p.parse_args()

    cfg = lade_config(args.config)
    logging_einrichten(cfg)
    db = Datenbank(str(BASIS / cfg["ausgabe"]["datenbank"]))
    {"app": cmd_app, "lauf": cmd_lauf, "report": cmd_report, "rechne": cmd_rechne,
     "status": cmd_status}[args.cmd](cfg, db, args)


if __name__ == "__main__":
    main()
