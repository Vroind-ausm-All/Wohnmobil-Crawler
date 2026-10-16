#!/usr/bin/env python3
"""Wohnmobil-Scout – Kleinanzeigen-Crawler, Händler-EK-Rechner und Anschreiben.

  python scout.py app                       Browser-App: Wohnmobile anklicken und anschreiben
  python scout.py lauf                      Crawlen + bewerten + Report (+ Mail)
  python scout.py report                    Nur Report neu erzeugen (ohne Internet)
  python scout.py import [--ordner PFAD]    Im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten einlesen (ohne Internet)
  python scout.py rechne --preis 32900 --ez 2016 --km 98000 --titel "Knaus Sky TI 650 MEG" [--anschreiben]
  python scout.py nutzer anlegen <Name> [--rolle inhaber]   Team-Zugang für Handy-App anlegen
  python scout.py sichern                   Datenbank (und Fotos) sichern -> daten/sicherungen
  python scout.py wiederherstellen <Datei> --bestaetigt [--ohne-fotos]   Sicherung zurückspielen (App und Suchlauf vorher beenden)
  python scout.py status <ID> kontaktiert [--nutzer NAME]   Status setzen (neu|kontaktiert|verhandlung|besichtigung|gekauft|abgesagt|
                                            uninteressant|vorbereitet); mit --nutzer im Team für diesen Mitarbeiter (sonst „ohne Zuordnung“)
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
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from wmscout.ausgabe import schreibe_ausgaben
from wmscout.benachrichtigung import sende_mail
from wmscout.bewertung.anschreiben import Anschreiber, euro
from wmscout.bewertung.auswertung import bewerte_alle, bewerte_anzeige, dubletten_ids, vergleichsbasis
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import STATUS, Datenbank, wal_aktiv
from wmscout.laufsperre import Laufsperre
from wmscout.eingang import import_ordner
from wmscout.auktion import STATUS as AUKTION_STATUS
from wmscout.auktion import AuktionSpeicher
from wmscout.haendler import STANDORT_STATUS, HaendlerSpeicher
from wmscout.importer import Importer
from wmscout.migrationen import MigrationsFehler
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.sicherung import SicherungsFehler, einstellungen, sichere, sicherung_ordner, wiederherstellen
from wmscout.bearbeitung import BearbeitungsKonflikt, ablauf_grenze, reservierung_tage
from wmscout.team import ROLLEN, TeamSpeicher, lade_team_sicht

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


def _team(cfg, db):
    """Team-Sicht für die CSV (Bearbeiter je Inserat); ``None`` ohne angelegte Nutzer."""
    return lade_team_sicht(db, reservierung_tage(cfg))


def cmd_lauf(cfg, db, args):
    sperre = Laufsperre(BASIS / cfg["ausgabe"]["datenbank"])
    if not sperre.erwerben():
        logging.warning("Suchlauf übersprungen: Es läuft bereits ein Suchlauf (App oder geplante Aufgabe).")
        return
    try:
        _lauf(cfg, db)
    finally:
        sperre.freigeben()


def _lauf(cfg, db):
    start = datetime.now().isoformat(timespec="seconds")
    stat = Importer(cfg, db).lauf(cfg["suchen"])
    logging.info("Crawl fertig: %d neu, %d Preissenkungen, %d bekannt, %d Detailseiten",
                 stat["neu"], stat["preis"], stat["bekannt"], stat["details"])
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, fehler=stat["fehler"], team=_team(cfg, db))
    logging.info("Report: %s  (%s)", erg["html"], erg["zaehl"])
    sende_mail(cfg, zeilen, erg)


def _anzahl(n: int, einzahl: str, mehrzahl: str) -> str:
    return f"{n} {einzahl if n == 1 else mehrzahl}"


def cmd_import(cfg, db, args):
    ordner = Path(args.ordner).expanduser().resolve() if args.ordner else import_ordner(cfg)
    if not ordner.is_dir():
        ordner.mkdir(parents=True, exist_ok=True)
        print(f"Import-Ordner angelegt: {ordner}")
    print(f"Gespeicherte Seiten einlesen aus: {ordner}")
    start = datetime.now().isoformat(timespec="seconds")
    stat = Importer(cfg, db).importiere_seiten(ordner)
    if not stat["dateien"]:
        print("Keine gespeicherten Seiten gefunden (.html/.htm).\n"
              "So geht's: Suchergebnis- oder Anzeigenseite in Kleinanzeigen oder mobile.de öffnen, Strg+S drücken und in diesen Ordner "
              "speichern (Kleinanzeigen: „Webseite, nur HTML“; mobile.de: „Webseite, komplett“). Danach diesen Befehl erneut ausführen.")
        return
    print(f"{_anzahl(stat['dateien'], 'Datei', 'Dateien')} gelesen: {_anzahl(stat['suchseiten'], 'Suchseite', 'Suchseiten')}, "
          f"{_anzahl(stat['detailseiten'], 'Detailseite', 'Detailseiten')}, {stat['unbekannt']} nicht erkannt")
    print(f"Ergebnis: {_anzahl(stat['neu'], 'neue Anzeige', 'neue Anzeigen')}, "
          f"{_anzahl(stat['preis'], 'Preissenkung', 'Preissenkungen')}, {stat['bekannt']} schon bekannt, "
          f"{stat['details']} mit Details")
    if stat["dateien"] > stat["unbekannt"]:
        print(f"Eingelesene Dateien liegen jetzt in: {ordner / 'eingelesen'}")
    if stat["fehler"]:
        print("Bitte prüfen:\n" + "\n".join(f"  - {f}" for f in stat["fehler"]))
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, team=_team(cfg, db))
    print(f"Report: {erg['html']}  ({erg['zaehl']})")


def cmd_report(cfg, db, args):
    zeilen = bewerte_alle(cfg, db, BASIS)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, team=_team(cfg, db))
    print(f"Report: {erg['html']}\nCSV:    {erg['csv']}\n{erg['zaehl']}")


def cmd_rechne(cfg, db, args):
    a = ergaenze_fahrzeug({"id": "manuell", "preis": args.preis, "ez_jahr": args.ez, "km": args.km,
                           "marke": args.marke, "titel": args.titel or args.marke or "", "beschreibung": args.text,
                           "suche": args.art, "ort": args.ort, "vb": True})
    # gleiche Vergleichsbasis und Bewertung wie bewerte_alle (Rechner-Sicht, ohne ältere Dubletten; M6-2)
    vergleich = vergleichsbasis([ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()])
    b = bewerte_anzeige(Rechner(cfg), a, vergleich, marktwert_manuell=args.marktwert)
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


def foto_ordner(cfg) -> Path:
    return (BASIS / cfg["ausgabe"]["datenbank"]).parent / "fotos"


def cmd_sichern(cfg, args):
    db_pfad = BASIS / cfg["ausgabe"]["datenbank"]
    try:
        ordner, behalten = einstellungen(cfg, BASIS)
        ziel = sichere(db_pfad, ordner, foto_ordner(cfg), behalten)
    except (SicherungsFehler, MigrationsFehler, ValueError, sqlite3.Error, OSError) as e:
        sys.exit(f"Sicherung fehlgeschlagen: {e}")
    print(f"Sicherung angelegt und geprüft: {ziel}")
    if ziel.with_name(ziel.name[:-len('.sqlite')] + ".fotos.zip").exists():
        print("Fotos gesichert in:             " + ziel.with_name(ziel.name[:-len('.sqlite')] + ".fotos.zip").name)


def cmd_wiederherstellen(cfg, args):
    quelle = Path(args.datei)
    try:
        ordner, behalten = einstellungen(cfg, BASIS)
        if not quelle.is_file() and (ordner / args.datei).is_file():
            quelle = ordner / args.datei
        erg = wiederherstellen(quelle, BASIS / cfg["ausgabe"]["datenbank"], args.bestaetigt, ordner, foto_ordner(cfg), behalten,
                              mit_fotos=not args.ohne_fotos)
    except (SicherungsFehler, MigrationsFehler, ValueError, sqlite3.Error, OSError) as e:
        sys.exit(f"Wiederherstellung fehlgeschlagen: {e}")
    print(f"Wiederhergestellt aus {quelle}.")
    if erg.sicherung_vorher:
        print(f"Stand davor gesichert in: {erg.sicherung_vorher}")
    if args.ohne_fotos:
        print("Nur die Datenbank wurde zurückgespielt; der Fotoordner blieb unverändert.")
    if erg.fotos_wiederhergestellt:
        print("Fotos wiederhergestellt." + (f" Bisherige Fotos liegen unverändert in: {erg.alter_fotoordner}" if erg.alter_fotoordner else ""))
    print("Beim nächsten Start wird die Datenbank bei Bedarf auf die aktuelle Version gebracht (mit eigener Sicherung).")


def _passwort_abfragen(name: str) -> str:
    import getpass
    while True:
        pw = getpass.getpass(f"Passwort für {name} (mind. 8 Zeichen): ")
        if len(pw) < 8:
            print("Zu kurz.")
        elif pw != getpass.getpass("Wiederholen: "):
            print("Stimmt nicht überein.")
        else:
            return pw


def cmd_nutzer(cfg, db, args):
    team = TeamSpeicher(db, foto_ordner(cfg))
    if args.aktion == "liste":
        for n in team.nutzer_liste(nur_aktive=False, auch_haendler=True):
            print(f"{n['name']:<20} {ROLLEN[n['rolle']]:<12} {n['telefon'] or '':<16} {'aktiv' if n['aktiv'] else 'gesperrt'}")
        return
    if not args.name:
        sys.exit("Bitte einen Namen angeben, z. B.: python scout.py nutzer anlegen Max")
    if args.aktion == "anlegen":
        standort_id = None
        if args.standort:
            s = HaendlerSpeicher(db).standort_nach_name(args.standort)
            if not s:
                sys.exit(f"Standort „{args.standort}“ unbekannt (python scout.py standort liste)")
            standort_id = s["id"]
        try:
            team.nutzer_anlegen(args.name, args.passwort or _passwort_abfragen(args.name), args.rolle, args.telefon, standort_id)
        except Exception as e:  # noqa: BLE001 – verständliche Meldung statt Traceback
            sys.exit(f"Nicht angelegt: {e}")
        print(f"{args.name} angelegt ({ROLLEN[args.rolle]}). Ab jetzt ist für die App eine Anmeldung nötig.")
    elif args.aktion == "passwort":
        ok = team.passwort_setzen(args.name, args.passwort or _passwort_abfragen(args.name))
        print("Passwort geändert – bestehende Anmeldungen wurden beendet." if ok else f"{args.name} nicht gefunden")
    elif args.aktion in ("sperren", "entsperren"):
        ok = team.nutzer_aktiv_setzen(args.name, args.aktion == "entsperren")
        print("gespeichert" if ok else f"{args.name} nicht gefunden")


def cmd_standort(cfg, db, args):
    h = HaendlerSpeicher(db)
    if args.aktion == "liste":
        for s in h.standorte():
            print(f"{s['name']:<24} {STANDORT_STATUS[s['status']]:<12} {s['plz'] or '':<6} {s['ort'] or '':<20} {s['nutzer']} Zugang/Zugänge")
        return
    if not args.name:
        sys.exit("Bitte den Namen des Standorts angeben, z. B.: python scout.py standort anlegen \"Filiale Nord\"")
    if args.aktion == "anlegen":
        try:
            h.standort_anlegen(args.name, args.plz, args.ort)
        except (ValueError, sqlite3.IntegrityError) as e:
            sys.exit(f"Nicht angelegt: {e}")
        print(f"Standort {args.name} angelegt (zur Prüfung). Freischalten: python scout.py standort pruefen \"{args.name}\"")
        return
    s = h.standort_nach_name(args.name)
    if not s:
        sys.exit(f"Standort „{args.name}“ unbekannt")
    h.setze_standort_status(s["id"], "geprueft" if args.aktion == "pruefen" else "gesperrt", None)
    print("geprüft – Zugang frei" if args.aktion == "pruefen" else "gesperrt – Zugang sofort beendet")


def cmd_auktion(cfg, db, args):
    """Demo-Auktionen nur ansehen und das Protokoll prüfen – starten, bieten und entscheiden nur in der App."""
    a = AuktionSpeicher(db, cfg)
    a.abschliessen_faellige()
    if args.aktion == "liste":
        for r in db.con.execute("SELECT a.id, v.referenz, a.status, a.ende_utc, (SELECT MAX(betrag) FROM gebote g WHERE g.auktion_id=a.id) "
                                "FROM auktionen a JOIN verkaufsanfragen v ON v.id=a.anfrage_id ORDER BY a.id"):
            print(f"{r[0]:>4} {r[1]:<14} {AUKTION_STATUS[r[2]]:<30} Ende {r[3]}  Höchstgebot {r[4] or '–'}")
        return
    p = a.pruefe_protokoll()
    print(f"{p['eintraege']} Protokolleinträge, letzter Hash {p['letzter_hash']}")
    if not p["ok"]:
        sys.exit("PROTOKOLL BESCHÄDIGT:\n  " + "\n  ".join(p["fehler"]))
    print("Protokoll unverändert (Kette und Gebote stimmen überein). Letzten Hash notieren, um späteres Abschneiden zu erkennen.")


def cmd_status(cfg, db, args):
    """Ohne ``--nutzer`` wie bisher: kein Eintrag in `bearbeitung`, ein kontaktiertes Inserat gilt im Team als „ohne Zuordnung“.
    Mit ``--nutzer`` gilt die Team-Regel wie in der App (Übernahme, Konflikt mit Kollegen, Kontakt durch wen)."""
    team_args = {}
    if args.nutzer:
        n = next((x for x in TeamSpeicher(db, foto_ordner(cfg)).nutzer_liste() if x["name"] == args.nutzer.strip()), None)
        if not n:
            sys.exit(f"Nutzer „{args.nutzer}“ nicht gefunden oder gesperrt (python scout.py nutzer liste)")
        tage = reservierung_tage(cfg)
        team_args = {"nutzer_id": n["id"], "grenze": ablauf_grenze(datetime.now(), tage), "inhaber": n["rolle"] == "inhaber",
                     "dubletten": dubletten_ids(db).get(args.id, ())}
    try:
        ok = db.setze_status(args.id, args.status, args.notiz, **team_args)
    except BearbeitungsKonflikt:
        sicht = lade_team_sicht(db, tage, {"id": n["id"], "rolle": n["rolle"]})
        sys.exit(f"Nicht gespeichert: {sicht.konflikt_text(args.id, team_args['dubletten'])}")
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
    im = sub.add_parser("import", help="im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten einlesen (ohne Internet)")
    im.add_argument("--ordner", help="Ordner mit den gespeicherten Seiten (Standard: config.yaml → import → ordner)")
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
    n = sub.add_parser("nutzer", help="Team-Zugänge für die Handy-App verwalten")
    n.add_argument("aktion", choices=["anlegen", "liste", "passwort", "sperren", "entsperren"])
    n.add_argument("name", nargs="?")
    n.add_argument("--rolle", choices=list(ROLLEN), default="mitarbeiter")
    n.add_argument("--telefon", help="Handynummer international, z. B. +491701234567 (für WhatsApp)")
    n.add_argument("--standort", help="nur Rolle haendler: Name des Standorts (python scout.py standort anlegen …)")
    n.add_argument("--passwort", help=argparse.SUPPRESS)      # nur für Tests/Automatisierung
    st = sub.add_parser("standort", help="Standorte/Händler für das Händlerportal verwalten (prüfen = Zugang frei)")
    st.add_argument("aktion", choices=["anlegen", "liste", "pruefen", "sperren"])
    st.add_argument("name", nargs="?")
    st.add_argument("--plz")
    st.add_argument("--ort")
    au = sub.add_parser("auktion", help="Demo-Auktionen auflisten oder das Auktionsprotokoll prüfen")
    au.add_argument("aktion", choices=["liste", "pruefen"])
    s = sub.add_parser("status", help="Status einer Anzeige setzen")
    s.add_argument("id")
    s.add_argument("status", choices=list(STATUS))
    s.add_argument("--notiz")
    s.add_argument("--nutzer", help="Mitarbeiter, in dessen Namen der Status gesetzt wird (Team: Reservierung/Kontakt eintragen). "
                                    "Ohne diese Option wird kein Bearbeiter eingetragen: „kontaktiert“ gilt dann als „ohne Zuordnung“")
    sub.add_parser("sichern", help="Datenbank und Fotos sichern (Ordner: config.yaml -> sicherung)")
    w = sub.add_parser("wiederherstellen", help="Sicherung zurückspielen (App und Suchlauf vorher beenden)")
    w.add_argument("datei", help="Sicherungsdatei (.sqlite), auch nur der Dateiname aus dem Sicherungsordner")
    w.add_argument("--bestaetigt", action="store_true", help="bestätigt: App und Suchlauf sind beendet")
    w.add_argument("--ohne-fotos", action="store_true",
                   help="nur die Datenbank zurückspielen, Fotoordner unverändert lassen (z. B. bei beschädigtem Foto-Archiv)")
    args = p.parse_args()

    cfg = lade_config(args.config)
    logging_einrichten(cfg)
    # Sichern/Wiederherstellen arbeiten ohne Datenbank-Start (die Datenbank darf defekt oder neuer sein)
    if args.cmd == "sichern":
        return cmd_sichern(cfg, args)
    if args.cmd == "wiederherstellen":
        return cmd_wiederherstellen(cfg, args)
    try:
        reservierung_tage(cfg)              # ungültiges „team“ in config.yaml ebenso sofort melden
        einstellungen(cfg, BASIS)           # ungültiges „sicherung“ in config.yaml sofort melden, nicht erst bei der Sicherung
        db = Datenbank(str(BASIS / cfg["ausgabe"]["datenbank"]), str(sicherung_ordner(cfg, BASIS)), wal=wal_aktiv(cfg))
    except (MigrationsFehler, ValueError, sqlite3.Error) as e:
        sys.exit(f"Datenbank-Start abgebrochen: {e}")
    {"app": cmd_app, "lauf": cmd_lauf, "report": cmd_report, "import": cmd_import, "rechne": cmd_rechne,
     "nutzer": cmd_nutzer, "status": cmd_status, "standort": cmd_standort,
     "auktion": cmd_auktion}[args.cmd](cfg, db, args)


if __name__ == "__main__":
    main()
