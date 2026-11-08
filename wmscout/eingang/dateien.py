"""Browser-Uploads ohne Ablage, Netzabruf oder Ausführung des Inhalts.

CSV ist ein vom Nutzer zugeordnetes Tabellenformat, kein behaupteter Plattformexport.
Die Plattform/Identität kommt ausschließlich aus den bereits unterstützten Anzeigenlinks.
Alle Lesungen durchlaufen anschließend Importer.importiere wie Seiten und eingefügter Text.
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePath

from .basis import Lesung, Rohdaten, SeitenEingang
from .email import MailEingang, MailFehler
from .text import MAX_PREIS, MAX_TEXT, TextEingang, bereinige

MAX_DATEI_BYTES = 5_000_000
MAX_UPLOAD_JSON = 7_000_000
MAX_CSV_ZEILEN = 500
MAX_CSV_SEKUNDEN = 10
FELDER = {"url": "Inseratlink (Pflicht)", "titel": "Titel", "preis": "Kaufpreis in Euro", "km": "Kilometerstand",
          "ez_jahr": "Erstzulassung (Jahr)", "ort": "PLZ und Ort", "anbieter": "Privat / gewerblich / unbekannt",
          "art": "Fahrzeugart", "beschreibung": "Beschreibung"}
ALIASE = {"url": ("url", "link", "inseratlink", "anzeigenlink", "adresse"), "titel": ("titel", "title", "fahrzeug"),
          "preis": ("preis", "price", "kaufpreis", "angebotspreis"), "km": ("km", "kilometer", "kilometerstand", "mileage"),
          "ez_jahr": ("ez", "ez_jahr", "erstzulassung", "baujahr", "jahr"), "ort": ("ort", "standort", "location"),
          "anbieter": ("anbieter", "verkaeufer", "verkäufer", "verkäuferart", "seller"), "art": ("art", "fahrzeugart", "typ"),
          "beschreibung": ("beschreibung", "text", "description", "ausstattung")}


@dataclass
class DateiLesung:
    eingang: str
    kanal: str
    lesungen: list[Lesung] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)
    gesamt: int = 0
    uebersprungen: int = 0
    spalten: list[str] = field(default_factory=list)
    zuordnung: dict[str, str] = field(default_factory=dict)

    def vorschau(self) -> dict:
        zeilen = []
        for lesung in self.lesungen:
            for a in lesung.inserate:
                zeilen.append({"id": a.anzeigen_id, "url": a.url, "titel": a.titel, "preis": a.preis, "km": a.km,
                               "ez_jahr": a.ez_jahr, "ort": a.ort, "art": a.art, "gewerblich": a.gewerblich,
                               "anbieter": "unbekannt" if a.gewerblich is None else "gewerblich" if a.gewerblich else "privat",
                               "fehler": "; ".join(lesung.hinweise),
                               "plattform": a.quelle, "hinweise": lesung.hinweise})
        return {"vorschau": zeilen[:20], "gesamt": self.gesamt, "erkannt": len(zeilen), "fehler": self.fehler[:30],
                "fehlerhaft": len(self.fehler), "uebersprungen": self.uebersprungen, "spalten": self.spalten,
                "zuordnung": self.zuordnung, "felder": FELDER}


def entpacke(daten: dict) -> tuple[str, bytes, str]:
    name, inhalt = daten.get("name"), daten.get("inhalt")
    if not isinstance(name, str) or not name or len(name) > 180 or any(ord(c) < 32 for c in name) \
            or "/" in name or "\\" in name or ":" in name or name in (".", ".."):
        raise ValueError("Dateiname ungültig – bitte eine einzelne HTML-, CSV- oder EML-Datei auswählen")
    endung = PurePath(name).suffix.lower()
    if endung not in (".html", ".htm", ".csv", ".eml"):
        raise ValueError("Unterstützt werden .html, .htm, .csv und .eml (keine Archive)")
    if not isinstance(inhalt, str) or len(inhalt) > (MAX_DATEI_BYTES + 2) // 3 * 4:
        raise ValueError("Datei fehlt oder ist größer als 5 MB")
    try:
        roh = base64.b64decode(inhalt, validate=True)
    except (ValueError, binascii.Error) as e:
        raise ValueError("Datei ist nicht lesbar (ungültige Übertragung)") from e
    if not roh or len(roh) > MAX_DATEI_BYTES:
        raise ValueError("Datei ist leer oder größer als 5 MB")
    if b"\x00" in roh:
        raise ValueError("Binärdatei nicht unterstützt – CSV bitte als UTF-8 speichern")
    return name, roh, endung


def _zahl(text: str, feld: str, jahr: int) -> int | None:
    text = text.strip()
    if not text:
        return None
    text = re.sub(r"\s*(?:€|EUR|km)\s*$", "", text, flags=re.I).replace("\u00a0", " ")
    if feld == "ez_jahr":
        if re.fullmatch(r"(?:0?[1-9]|1[0-2])[/.-]\d{4}", text):
            text = text[-4:]
        if not re.fullmatch(r"\d{4}", text) or not 1900 <= int(text) <= jahr + 1:
            raise ValueError("Erstzulassung erwartet ein plausibles Jahr, z. B. 2018")
        return int(text)
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:[. ]\d{3})+)(?:,00)?", text):
        raise ValueError(f"{FELDER[feld]} ist keine eindeutige ganze Zahl")
    wert = int(text.removesuffix(",00").replace(".", "").replace(" ", ""))
    if not (1 if feld == "preis" else 0) <= wert <= (MAX_PREIS if feld == "preis" else 2_000_000):
        raise ValueError(f"{FELDER[feld]} liegt außerhalb des unterstützten Bereichs")
    return wert


def _csv(roh: bytes, zuordnung, jetzt: datetime) -> DateiLesung:
    beginn = time.monotonic()
    try:
        text = roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = roh.decode("cp1252")                 # üblicher Excel-Export; UTF-8 wird bevorzugt
    if not text.strip():
        raise ValueError("CSV ist leer – eine Kopfzeile und mindestens ein Angebot werden benötigt")
    try:
        dialect = csv.Sniffer().sniff(text[:16384], delimiters=",;\t")
    except csv.Error:
        class Ersatz(csv.excel):
            delimiter = ";" if ";" in text.splitlines()[0] else ","
        dialect = Ersatz
    try:
        rows = csv.reader(io.StringIO(text), dialect, strict=True)
        spalten = [s.strip() for s in next(rows)]
        if not spalten or len(spalten) > 40 or any(not s or len(s) > 100 for s in spalten) or len(set(spalten)) != len(spalten):
            raise ValueError("CSV benötigt eindeutige Spaltennamen in der ersten Zeile (höchstens 40 Spalten)")
        if zuordnung is None or zuordnung == {}:
            zuordnung = {feld: next((s for s in spalten if s.lower() in aliases), "") for feld, aliases in ALIASE.items()}
        if not isinstance(zuordnung, dict) or set(zuordnung) - set(FELDER) or any(
                not isinstance(s, str) or s and s not in spalten for s in zuordnung.values()):
            raise ValueError("Feldzuordnung enthält unbekannte Felder oder Spalten")
        belegt = [s for s in zuordnung.values() if s]
        if len(set(belegt)) != len(belegt):
            raise ValueError("Eine CSV-Spalte darf nur einem Feld zugeordnet werden")
        erg = DateiLesung("text", "manuell", spalten=spalten, zuordnung=zuordnung)
        for zeile, row in enumerate(rows, 2):
            if time.monotonic() - beginn > MAX_CSV_SEKUNDEN:
                raise ValueError("CSV benötigt zu lange zum Lesen – bitte in kleinere Dateien aufteilen")
            if not any(s.strip() for s in row):
                continue
            erg.gesamt += 1
            if erg.gesamt > MAX_CSV_ZEILEN:
                raise ValueError(f"CSV enthält mehr als {MAX_CSV_ZEILEN} Angebote – bitte aufteilen")
            try:
                if len(row) != len(spalten) or any(len(s) > MAX_TEXT for s in row):
                    raise ValueError("Spaltenzahl stimmt nicht oder ein Feld ist zu lang")
                z = dict(zip(spalten, row, strict=True))
                d = {feld: z.get(zuordnung.get(feld), "").strip() for feld in FELDER}
                if not d["url"]:
                    raise ValueError("Bitte eine Spalte mit Inseratlinks zuordnen")
                anbieter = {"privat": "privat", "private": "privat", "privatanbieter": "privat", "gewerblich": "gewerblich",
                            "händler": "gewerblich", "haendler": "gewerblich", "dealer": "gewerblich", "unbekannt": None, "": None}
                if d["anbieter"].lower() not in anbieter:
                    raise ValueError("Anbieter muss privat, gewerblich oder unbekannt sein")
                preis, km, ez = (_zahl(d[f], f, jetzt.year) for f in ("preis", "km", "ez_jahr"))
                eingang = TextEingang()
                inhalt = "\n".join(x for x in (d["titel"], d["beschreibung"],
                                              f"Kilometerstand: {km} km" if km is not None else "",
                                              f"Erstzulassung: {ez}" if ez else "", f"Ort: {d['ort']}" if d["ort"] else "") if x)
                if not inhalt:
                    raise ValueError("Mindestens Titel oder Beschreibung zuordnen")
                lesung = eingang.lese(eingang.rohdaten(d["url"], inhalt, anbieter[d["anbieter"].lower()], jetzt, preis=preis))
                if lesung.art != "detail":
                    if any("Gesuch bzw. eine Ankaufsanzeige" in h for h in lesung.hinweise):
                        erg.uebersprungen += 1
                        continue
                    raise ValueError(lesung.hinweise[0])
                a = lesung.inserate[0]
                # Explizite Spalten haben Vorrang vor Heuristiken im Beschreibungstext. Fehlend bleibt unbekannt.
                for feld, wert in (("km", km), ("ez_jahr", ez)):
                    if d[feld]:
                        setattr(a, feld, wert)
                if d["art"]:
                    a.art = bereinige(d["art"])[0][:100]
                if d["ort"]:
                    a.ort = bereinige(d["ort"])[0][:200]
                # Die Textheuristik kann explizite CSV-Spalten noch nicht kennen. Ihre Hinweise auf diese Felder neu ableiten.
                lesung.hinweise = [h for h in lesung.hinweise if not h.startswith("unvollständig:")
                                  and not (a.art and h.startswith("Fahrzeugart"))]
                fehlend = [name for name, wert in (("Preis", a.preis), ("Kilometerstand", a.km), ("Erstzulassung", a.ez_jahr),
                                                   ("PLZ/Ort", a.ort), ("Titel", a.titel)) if wert in (None, "")]
                if fehlend:
                    lesung.hinweise.insert(0, "unvollständig: " + ", ".join(fehlend))
                if a.art:
                    lesung.hinweise.append(f"Fahrzeugart „{a.art}“ aus zugeordneter CSV-Spalte – vor dem Kauf prüfen")
                a.details["datenherkunft"] = "CSV (vom Nutzer zugeordnete Spalten)"
                erg.lesungen.append(lesung)
            except ValueError as e:
                erg.fehler.append(f"Zeile {zeile}: {e}")
        return erg
    except (csv.Error, StopIteration) as e:
        raise ValueError("CSV ist nicht lesbar – bitte mit Kopfzeile und einheitlichem Trennzeichen speichern") from e


def lese_datei(name: str, roh: bytes, endung: str, zuordnung=None) -> DateiLesung:
    jetzt = datetime.now(timezone.utc)
    if endung == ".csv":
        return _csv(roh, zuordnung, jetzt)
    eingang = MailEingang() if endung == ".eml" else SeitenEingang()
    try:
        lesung = eingang.lese(Rohdaten(roh, name, jetzt))
    except MailFehler as e:
        raise ValueError(str(e)) from e
    erg = DateiLesung(eingang.kennung, eingang.kanal, gesamt=len(lesung.inserate))
    erg.uebersprungen = sum(bool(a.ist_gesuch) for a in lesung.inserate)
    lesung.inserate = [a for a in lesung.inserate if not a.ist_gesuch]
    if lesung.art not in ("suche", "detail") or not lesung.inserate:
        if not erg.uebersprungen:
            erg.fehler = list(lesung.hinweise) or ["Keine unterstützten Angebote erkannt"]
    else:
        erg.lesungen.append(lesung)
    return erg
