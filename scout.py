#!/usr/bin/env python3
"""Wohnmobil-Scout – Kleinanzeigen-Crawler, Händler-EK-Rechner und Anschreiben.

  python scout.py app                       Browser-App: Wohnmobile anklicken und anschreiben
  python scout.py lauf                      Crawlen + bewerten + Report (+ Mail)
  python scout.py report                    Nur Report neu erzeugen (ohne Internet)
  python scout.py import [--ordner PFAD]    Im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten einlesen (ohne Internet)
  python scout.py import --mails [--ordner PFAD]   Suchagent-Benachrichtigungen (.eml in import/email/) einlesen (Eingang „email“, Standard aus)
  python scout.py quellen liste|an|aus [KENNUNG]   Pull-Quellen und Eingänge anzeigen; Quellen schalten (nur im Code freigegebene)
  python scout.py rechne --preis 32900 --ez 2016 --km 98000 --titel "Knaus Sky TI 650 MEG" [--anschreiben]
  python scout.py nutzer anlegen <Name> [--rolle inhaber]   Team-Zugang für Handy-App anlegen
  python scout.py sichern                   Datenbank (und Fotos) sichern -> daten/sicherungen
  python scout.py dubletten [--stufe hoch|mittel]   Offene Dublettenvorschläge anzeigen (nur lesen)
  python scout.py dubletten bestaetigen|ablehnen ID1 ID2 | aufheben NR   Dublette entscheiden (nur Einzelplatz)
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

if sys.version_info[:2] != (3, 13):
    print(f"Hinweis: Wohnmobil-Scout ist für Python 3.13 gedacht, verwendet wird {sys.version.split()[0]}.\n"
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
import logging.handlers
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from wmscout.ausgabe import schreibe_ausgaben
from wmscout.benachrichtigung import sende_mail
from wmscout.bewertung.anschreiben import Anschreiber, euro
from wmscout.bewertung.auswertung import bewerte_alle, bewerte_anzeige, dubletten_ids, vergleichsbasis_aus
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import STATUS, Datenbank, wal_aktiv
from wmscout.laufsperre import Laufsperre
from wmscout.eingang import import_ordner
from wmscout.eingang.email import mail_ordner
from wmscout.auktion import STATUS as AUKTION_STATUS
from wmscout.auktion import AuktionSpeicher
from wmscout import abdeckung, datenrechte, laufprotokoll, mandanten
from wmscout.bewertung import kalibrierung
from wmscout.audit import AuditSpeicher
from wmscout.nutzung import nutzung
from wmscout.deal import DealSpeicher
from wmscout.dubletten import MAX_LIMIT, STANDARD_LIMIT, pruefe_dubletten
from wmscout.haendler import STANDORT_STATUS, HaendlerSpeicher
from wmscout.importer import Importer
from wmscout.quellen import QUELLEN
from wmscout.schalter import (EingangDeaktiviert, QuelleNichtSchaltbar, bewerte_quelle, eingaenge, eingang_pruefen, pruefe_eingaenge,
                              quelle_zeile, setze_quelle)
from wmscout.migrationen import MigrationsFehler
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.normalisierung.qualitaet import je_quelle
from wmscout.sicherung import SicherungsFehler, einstellungen, sichere, sicherung_ordner, wiederherstellen
from wmscout.bearbeitung import BearbeitungsKonflikt, ablauf_grenze, reservierung_tage
from wmscout.team import EINLADUNG_TAGE, ROLLEN, TeamSpeicher, lade_team_sicht

BASIS = Path(__file__).resolve().parent


def _mischen(basis: dict, zusatz: dict) -> dict:
    for k, v in zusatz.items():
        basis[k] = _mischen(basis[k], v) if isinstance(v, dict) and isinstance(basis.get(k), dict) else v
    return basis


LOKAL_ABSCHNITTE: list[str] = []


def lade_config(pfad: str) -> dict:
    """``config.yaml`` und – falls vorhanden – ``config.local.yaml`` daneben (P1-09): eigene Einstellungen des Betriebs, die
    nicht ins Repository gehören (.gitignore). Abschnitte werden zusammengeführt, einzelne Werte und Listen ersetzt."""
    datei = BASIS / pfad
    with open(datei, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    lokal = datei.with_name(f"{datei.stem}.local{datei.suffix}")
    if lokal.is_file():
        with open(lokal, encoding="utf-8") as f:
            zusatz = yaml.safe_load(f) or {}
        if not isinstance(zusatz, dict):
            sys.exit(f"{lokal.name}: erwartet werden Abschnitte wie in {datei.name}")
        cfg = _mischen(cfg, zusatz)
        LOKAL_ABSCHNITTE[:] = sorted(zusatz)        # wird nach dem Einrichten des Protokolls gemeldet (nachvollziehbar)
    return cfg


def logging_einrichten(cfg: dict):
    ordner = BASIS / cfg["ausgabe"]["ordner"]
    ordner.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),        # Protokoll rotiert: höchstens 6 × 5 MB (G0)
                  logging.handlers.RotatingFileHandler(ordner / "scout.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")])
    if LOKAL_ABSCHNITTE:
        logging.getLogger("scout").info("config.local.yaml überlagert: %s", ", ".join(LOKAL_ABSCHNITTE))


def _team(cfg, db):
    """Team-Sicht für die CSV (Bearbeiter je Inserat); ``None`` ohne angelegte Nutzer."""
    return lade_team_sicht(db, reservierung_tage(cfg))


def cmd_lauf(cfg, db, args):
    sperre = Laufsperre(BASIS / cfg["ausgabe"]["datenbank"])
    if not sperre.erwerben():
        logging.warning("Suchlauf übersprungen: Es läuft bereits ein Suchlauf (App oder geplante Aufgabe).")
        return
    try:
        _lauf(cfg, db, sofort=args.sofort)
    finally:
        sperre.freigeben()


def _lauf(cfg, db, sofort: bool = False):
    start = datetime.now().isoformat(timespec="seconds")
    importer = Importer(cfg, db)
    # geplante Aufgabe/Kommandozeile: Intervalle je Quelle und Pause nach Sperre gelten, außer mit --sofort (P4-04)
    importer.ausloeser, importer.intervall_beachten = "cli", not sofort
    stat = importer.lauf(cfg["suchen"])
    datenrechte.frist_anwenden(db, cfg, BASIS, foto_ordner(cfg))
    logging.info("Crawl fertig: %d neu, %d Preissenkungen, %d bekannt, %d Detailseiten",
                 stat["neu"], stat["preis"], stat["bekannt"], stat["details"])
    for u in stat["uebersprungen"]:
        logging.info("Übersprungen: Quelle %s (%s) – kein Fehler; Übersicht: python scout.py quellen liste", u["quelle"], u["grund"])
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, fehler=stat["fehler"], team=_team(cfg, db))
    logging.info("Report: %s  (%s)", erg["html"], erg["zaehl"])
    sende_mail(cfg, zeilen, erg, seit=start)


def _anzahl(n: int, einzahl: str, mehrzahl: str) -> str:
    return f"{n} {einzahl if n == 1 else mehrzahl}"


def cmd_import_mails(cfg, db, args):
    """E-Mail-Suchbenachrichtigungen (.eml) aus import/email/ einlesen – ohne Internet, verlinkte Anzeigen werden nicht abgerufen (P2-06)."""
    try:
        eingang_pruefen(cfg, "email")
    except EingangDeaktiviert as e:
        print(e)                                    # nichts lesen, Ordner nicht anlegen, Dateien bleiben liegen
        return
    ordner = Path(args.ordner).expanduser().resolve() if args.ordner else mail_ordner(cfg, BASIS)
    if not ordner.is_dir():
        ordner.mkdir(parents=True, exist_ok=True)
        print(f"Ordner für Mails angelegt: {ordner}")
    print(f"E-Mail-Suchbenachrichtigungen einlesen aus: {ordner}")
    start = datetime.now().isoformat(timespec="seconds")
    importer = Importer(cfg, db)
    importer.ausloeser = "cli"
    stat = importer.importiere_mails(ordner)
    if not stat["dateien"]:
        print("Keine Mails gefunden (.eml).\n"
              "So geht's: Benachrichtigung des Suchagenten in Thunderbird (Datei → Speichern unter → .eml) bzw. im Webmail als .eml speichern "
              "und in diesen Ordner legen. Danach diesen Befehl erneut ausführen.")
    else:
        print(f"{_anzahl(stat['dateien'], 'Mail', 'Mails')} gelesen: {_anzahl(stat['suchseiten'], 'mit Anzeigen', 'mit Anzeigen')}, "
              f"{stat['unbekannt']} nicht erkannt, {stat['fehlerhaft']} nicht lesbar")
        print(f"Ergebnis: {_anzahl(stat['neu'], 'neue Anzeige', 'neue Anzeigen')}, "
              f"{_anzahl(stat['preis'], 'Preissenkung', 'Preissenkungen')}, {stat['bekannt']} schon bekannt")
        if stat["dateien"] > stat["unbekannt"] + stat["fehlerhaft"]:
            print(f"Eingelesene Mails liegen jetzt in: {ordner / 'eingelesen'}")
        if stat["unbekannt"]:
            print(f"Nicht erkannte Mails: {ordner / 'nicht_erkannt'}")
        if stat["fehlerhaft"]:
            print(f"Nicht lesbare Mails: {ordner / 'fehlerhaft'}")
        if stat["fehler"]:
            print("Bitte prüfen:\n" + "\n".join(f"  - {f}" for f in stat["fehler"]))
    if args.ordner:                                 # abweichender Ordner: die Standard-Frist (import/email) erreicht ihn nicht
        try:
            geloescht = datenrechte.mails_nach_frist(ordner, datenrechte.frist_aus(cfg))
        except ValueError:
            geloescht = 0
        if geloescht:
            print(f"Datenschutz-Frist: {_anzahl(geloescht, 'abgelegte Mail', 'abgelegte Mails')} in {ordner} gelöscht.")
    if (offen := datenrechte.mails_unverarbeitet_gemeldet(cfg, ordner)):
        print(f"Achtung: {_anzahl(offen, 'Mail liegt', 'Mails liegen')} seit über der Datenschutz-Frist unverarbeitet im Ordner – bitte einlesen oder löschen.")
    datenrechte.frist_anwenden(db, cfg, BASIS, foto_ordner(cfg))         # abgelegte Mails nach der Frist löschen (P2-06)
    if stat["dateien"]:
        zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
        erg = schreibe_ausgaben(cfg, zeilen, BASIS, team=_team(cfg, db))
        print(f"Report: {erg['html']}  ({erg['zaehl']})")


def cmd_import(cfg, db, args):
    if args.mails:
        return cmd_import_mails(cfg, db, args)
    try:
        eingang_pruefen(cfg, "seiten")
    except EingangDeaktiviert as e:
        print(e)                                    # nichts lesen, Import-Ordner nicht anlegen, Dateien bleiben liegen
        return
    ordner = Path(args.ordner).expanduser().resolve() if args.ordner else import_ordner(cfg)
    if not ordner.is_dir():
        ordner.mkdir(parents=True, exist_ok=True)
        print(f"Import-Ordner angelegt: {ordner}")
    print(f"Gespeicherte Seiten einlesen aus: {ordner}")
    start = datetime.now().isoformat(timespec="seconds")
    importer = Importer(cfg, db)
    importer.ausloeser = "cli"
    stat = importer.importiere_seiten(ordner)
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
    datenrechte.frist_anwenden(db, cfg, BASIS, foto_ordner(cfg))         # Verkäufernamen kommen über den Seitenimport (P1-14a)
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start=start)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, team=_team(cfg, db))
    print(f"Report: {erg['html']}  ({erg['zaehl']})")


def cmd_quellen(cfg, db, args):
    """Pull-Quellen (Suchlauf) und Eingänge anzeigen bzw. Quellen ein-/ausschalten (ADR-036).
    Die Freigabe steht im Code (Nutzungsrechte); `an` schaltet nur freigegebene Quellen. Eingänge werden in config.yaml geschaltet."""
    if args.aktion in ("an", "aus"):
        if not args.kennung:
            sys.exit(f"Kennung fehlt – Aufruf: python scout.py quellen {args.aktion} KENNUNG (verfügbar: {', '.join(sorted(QUELLEN))})")
        klasse = QUELLEN.get(args.kennung)
        if klasse is None:
            sys.exit(f"Unbekannte Quelle „{args.kennung}“ – verfügbar: {', '.join(sorted(QUELLEN))}")
        try:
            setze_quelle(db, klasse, args.aktion == "an")
        except QuelleNichtSchaltbar as e:
            sys.exit(f"Nicht geändert: {e}")
        print(f"Quelle {klasse.kennung}: {'eingeschaltet' if args.aktion == 'an' else 'ausgeschaltet'}")
        return
    if args.kennung:
        sys.exit("„quellen liste“ nimmt keine Kennung – zum Schalten: python scout.py quellen an|aus KENNUNG")
    print("Pull-Quellen (Suchlauf) – schalten: python scout.py quellen an|aus KENNUNG")
    print(f"  {'Kennung':<16}{'Zugriff':<9}{'Code-Freigabe':<15}{'Schalter':<16}Suchlauf")
    status = {q["kennung"]: q for q in laufprotokoll.uebersicht(db, cfg)["quellen"]}
    for kennung in sorted(QUELLEN):
        klasse = QUELLEN[kennung]
        zeile = quelle_zeile(db, kennung)
        laeuft, grund = bewerte_quelle(bool(klasse.freigegeben), zeile)
        schalter = "nicht entschieden" if zeile is None or (not zeile["freigegeben"] and not zeile["aktiv"]) else ("an" if zeile["aktiv"] else "aus")
        print(f"  {kennung:<16}{klasse.zugriffsart:<9}{'ja' if klasse.freigegeben else 'nein':<15}{schalter:<16}"
              f"{'läuft' if laeuft else 'übersprungen (' + grund + ')'}")
        q = status[kennung]                                  # Laufprotokoll (P4-04); ausführlich in der App unter /status
        if q["letzter_lauf"] or q["intervall_stunden"]:
            print(f"  {'':<16}letzter Lauf {(q['letzter_lauf'] or '–').replace('T', ' ')} ({q['letztes_ergebnis'] or '–'}), "
                  f"Fehler in Folge {q['fehler_in_folge']}, automatisch: {q['sperrgrund'] or 'sofort möglich'}")
            if q["letzter_fehler"]:
                print(f"  {'':<16}letzter Fehler: {q['letzter_fehler']}")
    print("\nEingänge – schalten in config.yaml bzw. config.local.yaml → eingaenge → <name> → aktiv: true|false")
    for name, an in eingaenge(cfg).items():
        print(f"  {name:<10}{'an' if an else 'aus'}")


def cmd_qualitaet(cfg, db, args):
    """Datenqualität je Quelle (P3-08, P2-10) über die aktuell bewerteten Inserate – nur lesen."""
    zeilen = bewerte_alle(cfg, db, BASIS)
    if not zeilen:
        print("Keine aktuellen Inserate.")
        return
    print(f"{'Quelle':<14}{'Anzahl':>7}{'Preis':>7}{'EZ':>6}{'km':>6}{'Ort':>6}{'Anbieter':>9}{'Ø Wert':>8}{'Widerspr.':>10}")
    for q in je_quelle(zeilen):
        print(f"{q['quelle']:<14}{q['anzahl']:>7}{q['preis']:>7.0%}{q['ez']:>6.0%}{q['km']:>6.0%}{q['ort']:>6.0%}{q['anbieter_bekannt']:>9.0%}"
              f"{q['mittel']:>8.0f}{q['mit_widerspruch']:>10}")
    schwach = [z for z in zeilen if z["a"]["datenqualitaet"]["stufe"] == "schwach"]
    print(f"\n{len(schwach)} von {len(zeilen)} Fahrzeugen mit schwacher Datenlage (Wert unter 50).")


def cmd_abdeckung(cfg, db, args):
    """Abdeckung und Suchlücken (P4-05) für die letzten ``--tage`` Tage – nur lesen. Ausführlich in der App unter /abdeckung."""
    try:
        tage = abdeckung.tage_aus(args.tage)
    except ValueError as e:
        sys.exit(str(e))
    m = abdeckung.messe(cfg, db, BASIS, tage)
    k = m["kennzahlen"]
    print(f"Abdeckung der letzten {tage} Tage")
    je_quelle = ", ".join(f"{q} {n}" for q, n in k["neue_inserate_je_quelle"].items())
    print(f"  Neue Inserate: {k['neue_inserate']}" + (f" ({je_quelle})" if je_quelle else "") +
          f" · unterschiedliche Fahrzeuge: {k['neue_fahrzeuge']} · relevante Privatangebote: {k['relevante_privatangebote']}"
          f" ({k['relevante_privatangebote_pro_tag']} pro Tag)")
    voll = "–" if k["anteil_vollstaendig"] is None else f"{k['anteil_vollstaendig']:.0%}"
    print(f"  Preisänderungen: {k['preisaenderungen']} · mit Dublette: {k['inserate_mit_dublette']} · nicht verfügbar: {k['nicht_verfuegbar']}"
          f" · vollständig beschrieben: {voll}")
    print("Zeitlücken je Plattform")
    for p, z in m["zeitluecken"].items():
        luecken = ", ".join(f"{lk['von']}–{lk['bis']} ({lk['tage']} Tage)" for lk in z["luecken"]) or "keine"
        print(f"  {p:<14}{z['tage_mit_eingang']:>3} von {tage} Tagen mit Eingang · letzter {z['letzter_eingang'] or '–'} · Lücken: {luecken}")
    print("Suchprofile")
    for p in m["profile"] or [{"name": "(kein aktives Profil)", "passt": 0, "unklar": 0, "hinweise": []}]:
        print(f"  {p['name']}: {p['passt']} passend, {p['unklar']} unklar" + "".join(f"\n    - {h}" for h in p["hinweise"]))
    g = m["gebietsluecken"]
    print(f"PLZ-Bereiche ohne neues Inserat ({len(g['ohne_inserat'])} von {len(g['ohne_inserat']) + len(g['je_bereich'])}): "
          + (", ".join(g["ohne_inserat"]) or "keine"))


def cmd_kalibrierung(cfg, db, args):
    """Kalibrierungsbericht (P5-01): Rechnung gegen tatsächliche Ankäufe – nur lesen, ändert keine Parameter. Fälle nachtragen: /kalibrierung."""
    faelle = kalibrierung.KalibrierungSpeicher(db).faelle(cfg)
    b = kalibrierung.bericht(faelle, cfg)
    print(f"Kalibrierung: {b['faelle']} Fälle, davon {b['verkauft']} verkauft – {b['belastbarkeit']}")

    def zeile(name, k, fmt):
        if k is None:
            print(f"  {name}: keine Fälle")
        else:
            print(f"  {name}: Median {fmt(k['median'])} (mittlere Hälfte {fmt(k['q1'])} bis {fmt(k['q3'])}, {k['n']} Fälle)")

    zeile("Kaufpreis gegenüber Max-EK", b["ek_zu_max_ek"], kalibrierung.prozent)
    zeile("Verkaufspreis gegenüber geplantem Händler-VK", b["vk_zu_plan"], kalibrierung.prozent)
    zeile("Ist- minus Plankosten", b["kosten_abweichung"], lambda x: f"{x:+,.0f} €".replace(",", ".").replace("-", "−"))
    zeile("Standzeit gegenüber Plan", b["standzeit_abweichung"], lambda x: f"{x:+.0f} Tage".replace("-", "−"))
    for h in b["hinweise"]:
        print(f"Hinweis: {h}")
    if not b["vorschlaege"]:
        print(f"Keine Vorschläge (ab {b['min_faelle']} verwertbaren Fällen und Abweichung über der Toleranz).")
    for v in b["vorschlaege"]:
        print(f"Vorschlag {v['parameter']}: {v['alt']} → {v['neu']} ({v['faelle']} Fälle) – {v['grund']}")
        if v["alternative"]:
            print(f"  {v['alternative']}")
        if v["warnung"]:
            print(f"  Achtung: {v['warnung']}")
    if b["vorschlaege"]:
        print("Nichts wurde geändert – Parameter bewusst in config.yaml nachstellen.")
    m = kalibrierung.KalibrierungSpeicher(db).marktbeobachtung(cfg)
    senkung = "–" if m["median"] is None else f"{m['median']:.0%}"
    print(f"Marktbeobachtung: {m['n']} verschwundene Privatinserate mit Preisverlauf, {m['mit_senkung']} gesenkt, Senkung im Median {senkung}"
          f" (Untergrenze für den Abschlag Angebot → Abschluss, derzeit {m['abschlag']:.0%})")
    if m["hinweis"]:
        print(f"Hinweis: {m['hinweis']}")


def cmd_report(cfg, db, args):
    zeilen = bewerte_alle(cfg, db, BASIS)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS, team=_team(cfg, db))
    print(f"Report: {erg['html']}\nCSV:    {erg['csv']}\n{erg['zaehl']}")


def cmd_rechne(cfg, db, args):
    a = ergaenze_fahrzeug({"id": "manuell", "preis": args.preis, "ez_jahr": args.ez, "km": args.km,
                           "marke": args.marke, "titel": args.titel or args.marke or "", "beschreibung": args.text,
                           "suche": args.art, "ort": args.ort, "vb": True})
    # gleiche Vergleichsbasis und Bewertung wie bewerte_alle (Rechner-Sicht, ohne ältere Dubletten; M6-2)
    vergleich = vergleichsbasis_aus(db)
    b = bewerte_anzeige(Rechner(cfg), a, vergleich, marktwert_manuell=args.marktwert)
    print(f"\nFahrzeug                 : {a['fahrzeug']} ({b.art}, EZ {a['ez_jahr'] or '?'}, "
          f"{a['km'] or '?'} km)")
    if b.modellwert:
        print(f"Referenzwert (Modell)    : {euro(b.modellwert)}   (km-Korrektur {b.km_korrektur:+.1%})")
    for n, w in b.wertfaktoren.items():
        print(f"  {n:<23}: {w:+.1%}")
    if b.sicherheit == "keine":
        print(f"  {b.vergleich_basis}\n  Keine Beträge – mit --marktwert einen eigenen Marktwert angeben (P1-12).")
        if args.anschreiben:
            print("\n--- Anschreiben ---\n" + Anschreiber(cfg, BASIS).text(a, b))
        return
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


def cmd_mandant(cfg, args):
    """Mandanten (G2): anlegen, auflisten, Nutzung je Mandant. Arbeiten in einem Mandanten: scout.py --mandant KENNUNG <befehl>."""
    if args.aktion == "anlegen":
        if not args.kennung or not args.url:
            sys.exit("Aufruf: python scout.py mandant anlegen KENNUNG --name \"Firma\" --url https://firma.example.de")
        ziel = mandanten.anlegen(cfg, BASIS, args.kennung, args.name or args.kennung, args.url)
        print(f"Mandant „{args.kennung}“ angelegt: {ziel}/mandant.yaml\n"
              f"Ersten Inhaber einladen (Link, Passwort setzt der Kunde selbst): python scout.py --mandant {args.kennung} nutzer einladen NAME --rolle inhaber")
        return
    liste = mandanten.alle(cfg, BASIS)
    for m in liste:
        k = m["mandant"]["kennung"]
        if args.aktion == "liste":
            print(f"{k:<16} {m['mandant']['name']:<28} {', '.join(sorted(mandanten.hosts(m)))}")
            continue
        db = Datenbank(str(BASIS / m["ausgabe"]["datenbank"]), str(sicherung_ordner(m, BASIS)), wal=wal_aktiv(m))
        try:
            n = nutzung(db, args.monat)
        finally:
            db.con.close()
        z = n["zaehler"]
        print(f"{k:<16} {n['monat']}  " + "  ".join(f"{name}={'–' if wert is None else wert}" for name, wert in z.items()))


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


def _neues_passwort(name: str) -> str:
    """Passwort nie als Kommandozeilen-Argument (stünde in der Prozessliste und im Verlauf, P1-09): Abfrage am Terminal oder –
    für Automatisierung – Umgebungsvariable SCOUT_NEUES_PASSWORT."""
    if os.environ.get("SCOUT_NEUES_PASSWORT"):
        print(f"Hinweis: Passwort für {name} aus SCOUT_NEUES_PASSWORT – Variable danach wieder entfernen", file=sys.stderr)
        return os.environ["SCOUT_NEUES_PASSWORT"]
    return _passwort_abfragen(name)


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
            team.nutzer_anlegen(args.name, _neues_passwort(args.name), args.rolle, args.telefon, standort_id)
        except Exception as e:  # noqa: BLE001 – verständliche Meldung statt Traceback
            sys.exit(f"Nicht angelegt: {e}")
        print(f"{args.name} angelegt ({ROLLEN[args.rolle]}). Ab jetzt ist für die App eine Anmeldung nötig.")
    elif args.aktion == "einladen":
        standort_id = None
        if args.standort:
            s = HaendlerSpeicher(db).standort_nach_name(args.standort)
            if not s:
                sys.exit(f"Standort „{args.standort}“ unbekannt (python scout.py standort liste)")
            standort_id = s["id"]
        try:
            _, token, rolle = team.einladen(args.name, args.rolle, args.telefon, standort_id, erneut=args.erneut)
        except Exception as e:  # noqa: BLE001 – verständliche Meldung statt Traceback
            sys.exit(f"Nicht eingeladen: {e}" + (" (mit --erneut bestätigen)" if "Erneut einladen?" in str(e) else ""))
        basis = ((cfg.get("app") or {}).get("oeffentliche_url") or f"http://127.0.0.1:{(cfg.get('app') or {}).get('port', 8765)}").rstrip("/")
        print(f"Einladung für {args.name} ({ROLLEN[rolle]}) – Link einmal gültig, {EINLADUNG_TAGE} Tage; über einen vertrauten Weg weitergeben:\n"
              f"{basis}/einladung#{token}\nDer Eingeladene legt dort sein Passwort selbst fest. Ab jetzt ist für die App eine Anmeldung nötig.")
    elif args.aktion == "passwort":
        ok = team.passwort_setzen(args.name, _neues_passwort(args.name))
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


def cmd_kalkulation(cfg, db, args):
    """Alle gespeicherten Kalkulationen aus ihrer eingefrorenen Eingabe nachrechnen (Phase E) – nur lesen."""
    p = DealSpeicher(db, cfg).pruefe_alle()
    if not p["ok"]:
        sys.exit(f"{len(p['abweichend'])} von {p['anzahl']} Kalkulationen weichen ab (Eingabe verändert oder andere Rechenversion): "
                 + ", ".join(map(str, p["abweichend"])))
    print(f"{p['anzahl']} gespeicherte Kalkulationen – alle identisch nachgerechnet.")


def cmd_anfrage(cfg, db, args):
    """Widerruf einer Verkaufsanfrage (Datenrechte, G0) – wie der Knopf des Inhabers in /anfragen."""
    r = db.con.execute("SELECT id FROM verkaufsanfragen WHERE referenz=?", (args.referenz.strip().upper(),)).fetchone()
    if not r:
        sys.exit(f"Anfrage „{args.referenz}“ unbekannt")
    if not args.bestaetigt:
        sys.exit("Löscht personenbezogene Daten unwiderruflich – zur Bestätigung --bestaetigt angeben")
    try:
        erg = datenrechte.widerruf(db, cfg, foto_ordner(cfg), r["id"], None)
    except ValueError as e:
        sys.exit(f"Nicht gelöscht: {e}")
    print(f"Widerruf ausgeführt: {erg['fotos']} Foto(s) gelöscht, {erg['besichtigungen']} Besichtigung(en) geschwärzt, "
          f"Verkäufer {'anonymisiert' if erg['verkaeufer_anonymisiert'] else 'bleibt (weitere Anfragen)'}.")


def cmd_inserat(cfg, db, args):
    """Personendaten aus Inseraten entfernen (P1-14a): einzeln oder alle ohne Kauf, die älter als N Monate sind."""
    if bool(args.id) == (args.aelter_als is not None):
        sys.exit("Entweder eine Inserat-ID oder --aelter-als MONATE angeben")
    if args.aelter_als is not None and args.aelter_als < 1:
        sys.exit("--aelter-als: mindestens 1 Monat")
    if not args.bestaetigt:
        sys.exit("Entfernt Verkäuferdaten (Profilname, Name im Anschreiben, Angaben im Protokoll) unwiderruflich – "
                 "zur Bestätigung --bestaetigt angeben")
    ausgabe = BASIS / cfg["ausgabe"]["ordner"]
    if args.id:
        try:
            erg = datenrechte.inserat_anonymisieren(db, ausgabe, args.id, foto_ordner(cfg))
        except LookupError as e:
            sys.exit(str(e))
        except ValueError as e:
            sys.exit(f"Nicht geändert: {e}")
        print(f"Inserat {args.id} anonymisiert ({'Name entfernt' if erg['name_entfernt'] else 'kein Name gespeichert'}, "
              f"{erg['besichtigungen']} Besichtigung(en) bereinigt, {erg['fotos']} Foto(s) gelöscht). Bericht aktualisiert sich beim nächsten Lauf/„report“.")
        return
    erledigt = datenrechte.inserate_nach_frist(db, ausgabe, args.aelter_als, foto_ordner=foto_ordner(cfg))
    print(f"{len(erledigt)} Inserat(e) ohne Kauf, älter als {args.aelter_als} Monate, anonymisiert.")


def cmd_audit(cfg, db, args):
    """Audit-Protokoll (G0b): wer hat wann Personendaten gelesen oder etwas geändert."""
    zeilen = AuditSpeicher(db).liste(tage=args.tage, nutzer=args.nutzer, objekt=args.objekt, limit=args.limit)
    for z in reversed(zeilen):
        print(f"{z['zeitpunkt']}  {z['nutzer'] or '–':<14} {z['aktion']:<7} {z['status']}  {z['methode']:<4} {z['pfad']}  "
              f"{z['objekt'] or ''}  {z['ip'] or ''}")
    print(f"{len(zeilen)} Einträge (letzte {args.tage} Tage)")


def cmd_nutzung(cfg, db, args):
    """Nutzungszähler (G1): Kennzahlen eines Monats aus den vorhandenen Daten – Grundlage für eine spätere Abrechnung."""
    try:
        n = nutzung(db, args.monat)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Nutzung {n['monat']}:")
    for name, wert in n["zaehler"].items():
        print(f"  {name.replace('_', ' '):<24} {'–' if wert is None else wert}")
    for z in n["je_nutzer"]:
        print(f"  · {z['nutzer']:<16} {z['rolle'] or '':<12} {z['zugriffe']} Zugriffe, {z['aenderungen']} Änderungen")


def cmd_dubletten_entscheiden(cfg, db, args):
    """Bestätigen, ablehnen oder aufheben per Kommandozeile (P3-02b) – nur im Einzelplatz (ohne angelegte Nutzer); im Team entscheidet die App
    mit Rechteprüfung und Protokoll. IDs: Anzeigen-IDs (bestaetigen, ablehnen) bzw. die Nummer der Entscheidung (aufheben)."""
    from wmscout.dubletten import DublettenFehler, DublettenKonflikt, bestaetige, hebe_auf, inserat_zu_anzeige, lehne_ab
    if TeamSpeicher(db, foto_ordner(cfg)).hat_nutzer():
        sys.exit("Mit angelegten Nutzern entscheidet die App (Rechte und Protokoll); die Kommandozeile gilt nur im Einzelplatz.")
    try:
        if args.aktion == "aufheben":
            if len(args.ids) != 1 or not re.fullmatch(r"[0-9]+", args.ids[0]):
                sys.exit("Aufheben: genau eine Entscheidungsnummer, z. B.: python scout.py dubletten aufheben 3")
            erg = hebe_auf(db, int(args.ids[0]))
            print(f"Entscheidung {erg['entscheidung_id']} aufgehoben" + (f"; zurückgehängt: {len(erg['zurueck'])} Inserat(e)" if erg["zurueck"] else "")
                  if erg["neu"] else f"Entscheidung {erg['entscheidung_id']} war schon aufgehoben")
            return
        if len(args.ids) != 2:
            sys.exit(f"{args.aktion.capitalize()}: genau zwei Anzeigen-IDs, z. B.: python scout.py dubletten {args.aktion} 123456 md-789")
        iids = [inserat_zu_anzeige(db, i) for i in args.ids]
        if None in iids:
            sys.exit(f"Anzeige {args.ids[iids.index(None)]} nicht gefunden")
        erg = (bestaetige if args.aktion == "bestaetigen" else lehne_ab)(db, iids[0], iids[1])
    except (DublettenFehler, DublettenKonflikt) as e:
        sys.exit(f"Nicht gespeichert: {e}")
    wort = "gleiches Fahrzeug" if args.aktion == "bestaetigen" else "verschiedene Fahrzeuge"
    print(f"Entscheidung {erg['entscheidung_id']}: {wort}" if erg["neu"] else "Schon so entschieden bzw. dasselbe Fahrzeug – nichts geändert")


def cmd_dubletten(cfg, db, args):
    """Offene Dublettenvorschläge (P3-02a) – nur lesen; zusammengeführt wird nichts. Mit ``bestaetigen``/``ablehnen``/``aufheben`` P3-02b."""
    if args.aktion:
        return cmd_dubletten_entscheiden(cfg, db, args)
    if not 1 <= args.limit <= MAX_LIMIT:
        sys.exit(f"--limit muss zwischen 1 und {MAX_LIMIT} liegen")
    erg = pruefe_dubletten(db)
    vorschlaege = [v for v in erg.vorschlaege if args.stufe in (None, v["stufe"])]
    for v in vorschlaege[:args.limit]:
        a, b = v["a"], v["b"]
        print(f"[{v['stufe']}] {a['plattform']}:{a['anzeigen_id']} ~ {b['plattform']}:{b['anzeigen_id']}  "
              f"({a['titel'] or '?'} | {b['titel'] or '?'})\n        " + "; ".join(v["gruende"]))
    print(f"{len(vorschlaege)} offene Vorschläge" + (f" (angezeigt: {args.limit})" if len(vorschlaege) > args.limit else "")
          + " – nur Vorschläge, es wurde nichts zusammengeführt.")
    if erg.hinweis:
        print(f"Hinweis: {erg.hinweis}")


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
    p.add_argument("--mandant", help="Befehl für diesen Mandanten ausführen (mandanten/<kennung>/, G2)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("app", help="Browser-App starten: anklicken, anschreiben, Status speichern")
    a.add_argument("--port", type=int, help="Standard: config.yaml → app → port (8765)")
    a.add_argument("--kein-browser", action="store_true", help="Browser nicht automatisch öffnen")
    a.add_argument("--mandanten", action="store_true", help="alle Mandanten aus mandanten/ bedienen (Hostname wählt den Mandanten)")
    a.add_argument("--lokal", help="mit --mandanten: dieser Mandant ist zusätzlich über 127.0.0.1 erreichbar")
    la = sub.add_parser("lauf", help="crawlen, bewerten, Report erzeugen")
    la.add_argument("--sofort", action="store_true",
                    help="Intervalle je Quelle und die Pause nach einer Sperre nicht abwarten (config.yaml → app)")
    sub.add_parser("report", help="Report aus vorhandenen Daten neu erzeugen")
    im = sub.add_parser("import", help="im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten einlesen (ohne Internet)")
    im.add_argument("--ordner", help="Ordner mit den gespeicherten Seiten bzw. (mit --mails) den .eml-Dateien "
                                     "(Standard: config.yaml → import → ordner bzw. dessen Unterordner email)")
    im.add_argument("--mails", action="store_true",
                    help="statt Seiten die Suchagent-Benachrichtigungen (.eml in import/email/) einlesen – Eingang „email“ muss eingeschaltet sein")
    qu = sub.add_parser("quellen", help="Pull-Quellen und Eingänge anzeigen; Quellen ein-/ausschalten (nur im Code freigegebene)")
    qu.add_argument("aktion", choices=["liste", "an", "aus"])
    qu.add_argument("kennung", nargs="?", help="Quelle für an/aus, z. B. kleinanzeigen")
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
    n.add_argument("aktion", choices=["anlegen", "einladen", "liste", "passwort", "sperren", "entsperren"],
                   help="einladen: Zugang mit Einmal-Link anlegen – das Passwort legt der Eingeladene selbst fest")
    n.add_argument("name", nargs="?")
    n.add_argument("--rolle", choices=list(ROLLEN), default="mitarbeiter")
    n.add_argument("--telefon", help="Handynummer international, z. B. +491701234567 (für WhatsApp)")
    n.add_argument("--standort", help="nur Rolle haendler: Name des Standorts (python scout.py standort anlegen …)")
    n.add_argument("--erneut", action="store_true", help="nur einladen: vorhandenen Zugang erneut einladen (Passwort wird beim Einlösen neu gesetzt)")
    st = sub.add_parser("standort", help="Standorte/Händler für das Händlerportal verwalten (prüfen = Zugang frei)")
    st.add_argument("aktion", choices=["anlegen", "liste", "pruefen", "sperren"])
    st.add_argument("name", nargs="?")
    st.add_argument("--plz")
    st.add_argument("--ort")
    au = sub.add_parser("auktion", help="Demo-Auktionen auflisten oder das Auktionsprotokoll prüfen")
    au.add_argument("aktion", choices=["liste", "pruefen"])
    an = sub.add_parser("anfrage", help="Verkaufsanfrage: Widerruf der Einwilligung ausführen (Daten löschen)")
    an.add_argument("aktion", choices=["widerruf"])
    an.add_argument("referenz", help="z. B. VA-2026-0001")
    an.add_argument("--bestaetigt", action="store_true", help="Löschen wirklich ausführen")
    ad = sub.add_parser("audit", help="Audit-Protokoll anzeigen: wer hat wann Personendaten gelesen oder etwas geändert")
    ad.add_argument("--tage", type=int, default=30)
    ad.add_argument("--nutzer")
    ad.add_argument("--objekt", help="z. B. anfrage:12, ankauf:3")
    ad.add_argument("--limit", type=int, default=500)
    nz = sub.add_parser("nutzung", help="Nutzungszähler eines Monats (Anfragen, Auktionen, Gebote, Ankäufe, Zugriffe, aktive Nutzer)")
    nz.add_argument("--monat", help="JJJJ-MM, Standard: laufender Monat")
    ins = sub.add_parser("inserat", help="Verkäuferdaten aus Inseraten entfernen (Datenschutz, P1-14a)")
    ins.add_argument("aktion", choices=["anonymisieren"])
    ins.add_argument("id", nargs="?", help="Inserat-ID (oder --aelter-als)")
    ins.add_argument("--aelter-als", type=int, help="alle Inserate ohne Kauf, letzte Aktivität älter als so viele Monate")
    ins.add_argument("--bestaetigt", action="store_true")
    md = sub.add_parser("mandant", help="Mandanten (mehrere Firmen) anlegen, auflisten, Nutzung je Mandant")
    md.add_argument("aktion", choices=["anlegen", "liste", "nutzung"])
    md.add_argument("kennung", nargs="?", help="nur anlegen: z. B. firma-b (a–z, 0–9, Bindestrich)")
    md.add_argument("--name")
    md.add_argument("--url", help="nur anlegen: eigene Adresse, z. B. https://firma-b.example.de")
    md.add_argument("--monat", help="nur nutzung: JJJJ-MM")
    ab = sub.add_parser("abdeckung", help="Abdeckung und Suchlücken: Kennzahlen, Tage ohne Eingang, PLZ-Bereiche und Suchprofile (nur lesen)")
    ab.add_argument("--tage", default="30", help="Zeitraum in Tagen (1–365, Standard 30)")
    sub.add_parser("kalibrierung", help="Kalibrierungsbericht: Kaufpreis/Max-EK, VK/Plan, Kosten, Standzeit und Vorschläge (nur lesen)")
    sub.add_parser("qualitaet", help="Datenqualität je Quelle: Anteil mit Preis/EZ/km/Ort/Anbieter, Ø-Wert, Widersprüche (nur lesen)")
    du = sub.add_parser("dubletten", help="offene Dublettenvorschläge auflisten (nur lesen) oder im Einzelplatz entscheiden: "
                                          "bestaetigen ID1 ID2 | ablehnen ID1 ID2 | aufheben NUMMER")
    du.add_argument("aktion", nargs="?", choices=["bestaetigen", "ablehnen", "aufheben"], help="ohne Angabe: Vorschläge auflisten")
    du.add_argument("ids", nargs="*", help="Anzeigen-IDs bzw. Nummer der Entscheidung")
    du.add_argument("--stufe", choices=["hoch", "mittel"], help="nur diese Stufe")
    du.add_argument("--limit", type=int, default=STANDARD_LIMIT, help=f"höchstens so viele anzeigen (1–{MAX_LIMIT})")
    ka = sub.add_parser("kalkulation", help="gespeicherte Kalkulationen (Gebote) nachrechnen")
    ka.add_argument("aktion", choices=["pruefen"])
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
    try:
        if args.cmd == "mandant" or (args.cmd == "app" and args.mandanten):
            logging_einrichten(cfg)
            if args.cmd == "mandant":
                return cmd_mandant(cfg, args)
            from wmscout.app import starte_mandanten
            return starte_mandanten(cfg, BASIS, port=args.port, lokal=args.lokal)
        if args.mandant:
            cfg = mandanten.mandant_cfg(cfg, BASIS, args.mandant)
    except (mandanten.MandantenFehler, MigrationsFehler) as e:
        sys.exit(f"Mandanten: {e}")
    logging_einrichten(cfg)
    # Sichern/Wiederherstellen arbeiten ohne Datenbank-Start (die Datenbank darf defekt oder neuer sein)
    if args.cmd == "sichern":
        return cmd_sichern(cfg, args)
    if args.cmd == "wiederherstellen":
        return cmd_wiederherstellen(cfg, args)
    try:
        reservierung_tage(cfg)              # ungültiges „team“ in config.yaml ebenso sofort melden
        einstellungen(cfg, BASIS)           # ungültiges „sicherung“ in config.yaml sofort melden, nicht erst bei der Sicherung
        datenrechte.frist_aus(cfg)          # ebenso „datenschutz“
        pruefe_eingaenge(cfg)               # und „eingaenge“ (P2-04)
        db = Datenbank(str(BASIS / cfg["ausgabe"]["datenbank"]), str(sicherung_ordner(cfg, BASIS)), wal=wal_aktiv(cfg))
    except (MigrationsFehler, ValueError, sqlite3.Error) as e:
        sys.exit(f"Datenbank-Start abgebrochen: {e}")
    {"app": cmd_app, "lauf": cmd_lauf, "report": cmd_report, "import": cmd_import, "quellen": cmd_quellen, "rechne": cmd_rechne,
     "nutzer": cmd_nutzer, "status": cmd_status, "standort": cmd_standort,
     "auktion": cmd_auktion, "kalkulation": cmd_kalkulation, "anfrage": cmd_anfrage, "audit": cmd_audit, "nutzung": cmd_nutzung,
     "inserat": cmd_inserat, "dubletten": cmd_dubletten, "qualitaet": cmd_qualitaet, "abdeckung": cmd_abdeckung,
     "kalibrierung": cmd_kalibrierung}[args.cmd](cfg, db, args)


if __name__ == "__main__":
    main()
