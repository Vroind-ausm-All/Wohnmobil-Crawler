"""E-Mail-Suchbenachrichtigungen als Eingangskanal (P2-06, ADR-010/035/037).

Der Nutzer speichert die Benachrichtigungs-Mails seiner Suchagenten als `.eml` im Ordner `import/email/`. Gelesen wird nur, was in
der Mail steht: Links werden zerlegt, aber nie abgerufen, die verlinkten Anzeigen nicht nachgeladen. Gespeichert wird allein über
`Importer.importiere(lesung, "email")`; `Importer.importiere_mails` ist die Dateischleife dazu.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..basis import Lesung, Rohdaten
from ..seiten import import_ordner
from . import kleinanzeigen, mobilede
from .nachricht import MAX_BYTES, Mail, MailFehler, mail_zeitpunkt, plausibles_datum, zerlege
from .treffer import PlattformParser, datenqualitaet

EML_ENDUNGEN = {".eml"}
UNTERORDNER = "email"
PARSER: tuple[PlattformParser, ...] = (kleinanzeigen.PARSER, mobilede.PARSER)


def mail_ordner(cfg: dict, basis: Path | None = None) -> Path:
    """Ablage der Mails: Unterordner `email` des Import-Ordners (config.yaml → import → ordner), also `import/email/`; relativ zu `basis`
    (Standard: Projektordner). Eine Funktion für Einlesen und Datenschutz-Frist."""
    return import_ordner(cfg, basis) / UNTERORDNER


def eml_dateien(ordner: Path) -> list[Path]:
    """`.eml`-Dateien direkt im Ordner (nicht rekursiv, keine Verknüpfungen), alphabetisch; andere Dateien bleiben unberührt."""
    if not ordner.is_dir():
        return []
    return sorted((p for p in ordner.iterdir() if p.suffix.lower() in EML_ENDUNGEN and p.is_file() and not p.is_symlink()),
                  key=lambda p: p.name.lower())


def verschiebe_mail(datei: Path, ziel: Path) -> Path:
    """Verschiebt eine `.eml` (ohne Begleitordner) nach `ziel`, bei Namenskonflikt als `name_2.eml`, und setzt die Änderungszeit auf „jetzt“
    (ab hier zählt die Datenschutz-Frist). Überschreibt und löscht nichts."""
    ziel.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        neu = ziel / (datei.name if n == 1 else f"{datei.stem}_{n}{datei.suffix}")
        if not (neu.exists() or neu.is_symlink()):
            break
        n += 1
    shutil.move(str(datei), str(neu))
    try:
        os.utime(neu)
    except OSError:
        pass
    return neu


class MailEingang:
    """E-Mail-Suchbenachrichtigungen (Kleinanzeigen, mobile.de): wählt den passenden Plattform-Parser. Ohne Datenbank, ohne Netz."""

    kennung = "email"
    kanal = "email"

    def lese(self, roh: Rohdaten) -> Lesung:
        """`MailFehler` bei zu großer oder unlesbarer Datei; eine Mail ohne bekannte Plattform ergibt die Lesung 'unbekannt'."""
        mail = zerlege(roh.inhalt)
        kandidaten = [(not p.absender_passt(mail), -p.anzahl_links(mail), n, p) for n, p in enumerate(PARSER)]
        kandidaten = [k for k in kandidaten if not k[0] or k[1] < 0]       # Absender passt oder Links vorhanden
        if not kandidaten:
            return Lesung("unbekannt", [], ["keine Kleinanzeigen- oder mobile.de-Benachrichtigung erkannt (weder Absender noch Anzeigenlinks)"])
        kandidaten.sort(key=lambda k: k[:3])
        if len(kandidaten) > 1 and kandidaten[0][:2] == kandidaten[1][:2]:
            return Lesung("unbekannt", [], ["Mail verweist gleichermaßen auf mehrere Plattformen – nicht eindeutig zuzuordnen"])
        lesung = kandidaten[0][3].lese(mail)
        lesung.zeitpunkt = plausibles_datum(mail.datum, roh.empfangen_am)      # Date-Kopf, sonst Dateizeit (K1: Alter des Preises)
        return lesung


__all__ = ["EML_ENDUNGEN", "MAX_BYTES", "Mail", "MailEingang", "MailFehler", "PARSER", "datenqualitaet", "eml_dateien", "mail_ordner",
           "mail_zeitpunkt", "plausibles_datum", "verschiebe_mail", "zerlege"]
