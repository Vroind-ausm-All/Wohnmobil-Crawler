"""E-Mail zerlegen (P2-06): .eml-Bytes → `Mail` mit Textteilen und den wenigen Metadaten, die zur Erkennung nötig sind.

Nur die Standardbibliothek (`email`, bewusst mit `policy.compat32`: Kopfzeilen bleiben unverarbeitete Zeichenketten, nichts wird
ungefragt dekodiert – mit `policy.default` kosten absichtlich riesige Kopfzeilen Minuten und Gigabytes). Vor dem Parsen werden Kopfbereich,
Zeilenlänge und die Zahl der MIME-Teile begrenzt (`MailFehler`). Gelesen werden ausschließlich die Teile text/plain und text/html; Anhänge
(auch weitergeleitete Mails als Anhang) werden ignoriert und nur gezählt. Von den Kopfzeilen bleiben die Domain des Absenders (nur zur
Erkennung der Plattform) und das Datum; Adressen von Absender und Empfänger werden weder gehalten noch gespeichert, der Betreff wird
nicht einmal dekodiert. Nichts hier ruft etwas ab.
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from functools import cached_property

MAX_BYTES = 5_000_000          # größere Mails werden nicht gelesen (Speicher, Laufzeit)
MAX_KOPF = 64_000              # Kopfbereich der Mail (bis zur ersten Leerzeile)
MAX_KOPFZEILE = 8_192          # einzelne Kopfzeile (auch in MIME-Teilen)
MAX_KOPFZEILEN = 300           # Kopfzeilen je Teil
MAX_GRENZEN = 500              # Zeilen, die mit „--“ beginnen (MIME-Grenzen): vorab gezählt, bevor geparst wird
MAX_TEILE = 200                # MIME-Teile, die gelesen werden
MAX_VERSCHACHTELUNG = 20       # verschachtelte multipart-Ebenen
ERSATZ_ZEICHENSATZ = "cp1252"  # unbekannter/fehlender Zeichensatz: Windows-1252 deckt auch ISO-8859-1 ab

_KOPF_ENDE = re.compile(rb"\r?\n\r?\n")


class MailFehler(ValueError):
    """Die Datei ist keine lesbare E-Mail (zu groß, keine Kopfzeilen, Binärdaten, absichtlich überladen …) – sie wird nicht eingelesen."""


@dataclass(frozen=True)
class Mail:
    """Was von einer E-Mail gelesen wurde. Absender- und Empfängeradresse und Betreff sind absichtlich nicht enthalten."""

    absender_domain: str | None          # z. B. „kleinanzeigen.de“ – nur zur Erkennung der Plattform
    datum: datetime | None               # mit Zeitzone (fehlt sie in der Mail, gilt UTC)
    text: str | None                     # alle text/plain-Teile, zusammengefügt
    html: str | None                     # alle text/html-Teile, zusammengefügt
    anhaenge: int = 0                    # ignorierte Anhänge
    hinweise: list[str] = field(default_factory=list)

    @cached_property
    def html_baum(self):
        """Gelesener HTML-Baum (`htmlbaum.Baum`) – je Mail nur einmal gebaut; `MailFehler`, wenn er zu tief oder zu groß ist."""
        from .htmlbaum import Baum, baue
        return baue(self.html) if self.html else Baum(None, [], None)


def _inhalt(teil) -> str:
    """Text eines Teils: quoted-printable/base64 löst `get_payload(decode=True)` auf. Fehlender, unbekannter oder falscher Zeichensatz → UTF-8,
    sonst Windows-1252."""
    roh = teil.get_payload(decode=True) or b""
    zeichensatz = teil.get_content_charset()
    for versuch in ([zeichensatz] if zeichensatz else []) + ["utf-8"]:
        try:
            return roh.decode(versuch)
        except (LookupError, UnicodeError, ValueError):
            continue
    return roh.decode(ERSATZ_ZEICHENSATZ, errors="replace")


def _absender_domain(nachricht) -> str | None:
    wert = nachricht.get("From")
    if wert is None:
        return None
    try:
        adresse = parseaddr(str(wert)[:MAX_KOPFZEILE])[1]
    except (ValueError, TypeError, RecursionError):
        return None
    domain = adresse.rpartition("@")[2] if "@" in adresse else ""
    return domain.lower().strip(".") or None


def _datum(nachricht, hinweise: list[str]) -> datetime | None:
    wert = nachricht.get("Date")
    if wert is None:
        return None
    try:
        datum = parsedate_to_datetime(str(wert)[:100])
    except (ValueError, TypeError, IndexError, OverflowError):
        hinweise.append("Datum der Mail nicht lesbar")
        return None
    return datum if datum.tzinfo else datum.replace(tzinfo=timezone.utc)


MIN_DATUM = datetime(2000, 1, 1, tzinfo=timezone.utc)


def plausibles_datum(datum: datetime | None, rueckfall: datetime) -> datetime:
    """Zeitpunkt einer Mail: ihr Datum – wenn es da ist, nach 2000 liegt und nicht in der Zukunft; sonst `rueckfall` (Dateizeit, selbst nie in der Zukunft)."""
    jetzt = datetime.now(timezone.utc) + timedelta(minutes=5)           # etwas Uhrenabweichung erlauben
    if datum is not None and MIN_DATUM <= datum <= jetzt:
        return datum
    return min(rueckfall, datetime.now(timezone.utc))


def mail_zeitpunkt(pfad: Path) -> datetime:
    """Zeitpunkt einer `.eml`-Datei vor dem Einlesen: Date-Kopf (billig: nur der Kopfbereich, mit den Grenzen von `zerlege`), sonst Dateizeit."""
    rueckfall = datetime.fromtimestamp(pfad.stat().st_mtime, timezone.utc)
    datum = None
    try:
        with pfad.open("rb") as f:
            kopf = f.read(MAX_KOPF + 4)
        ende = _KOPF_ENDE.search(kopf)
        if ende or len(kopf) <= MAX_KOPF:
            kopf = kopf[:ende.start()] if ende else kopf
            if len(kopf) <= MAX_KOPF and all(len(z) <= MAX_KOPFZEILE for z in kopf.splitlines()):
                datum = _datum(message_from_bytes(kopf, policy=policy.compat32), [])
    except (OSError, ValueError, RecursionError):
        datum = None
    return plausibles_datum(datum, rueckfall)


def _pruefe_vorab(roh: bytes) -> None:
    """Grenzen, bevor irgendetwas geparst wird."""
    if len(roh) > MAX_BYTES:
        raise MailFehler(f"Mail zu groß ({len(roh) / 1_000_000:.1f} MB, erlaubt sind {MAX_BYTES // 1_000_000} MB)")
    if b"\x00" in roh[:4096]:
        raise MailFehler("keine E-Mail (Binärdaten)")
    ende = _KOPF_ENDE.search(roh, 0, MAX_KOPF + 4)
    if not ende and len(roh) > MAX_KOPF:
        raise MailFehler(f"Kopfbereich der Mail zu groß (mehr als {MAX_KOPF // 1000} KB)")
    kopf = roh[:ende.start()] if ende else roh
    if len(kopf) > MAX_KOPF:
        raise MailFehler(f"Kopfbereich der Mail zu groß (mehr als {MAX_KOPF // 1000} KB)")
    if any(len(zeile) > MAX_KOPFZEILE for zeile in kopf.splitlines()):
        raise MailFehler(f"Kopfzeile zu lang (mehr als {MAX_KOPFZEILE // 1024} KB)")
    if roh.count(b"\n--") + roh.count(b"\r--") > MAX_GRENZEN:          # \r--: Mails mit alleinstehendem CR als Zeilenende
        raise MailFehler(f"zu viele MIME-Teile (mehr als {MAX_GRENZEN} Trennzeilen)")


def _pruefe_kopf(teil) -> None:
    kopf = teil.items()
    if len(kopf) > MAX_KOPFZEILEN or any(len(str(wert)) > MAX_KOPFZEILE for _, wert in kopf):
        raise MailFehler("Kopfzeilen eines Mail-Teils zu zahlreich oder zu lang")


def zerlege(roh: bytes) -> Mail:
    """.eml-Bytes → `Mail`. `MailFehler` bei zu großer Datei, Binärdaten, fehlenden Kopfzeilen oder absichtlich überladenen Mails."""
    _pruefe_vorab(roh)
    try:
        nachricht = message_from_bytes(roh, policy=policy.compat32)
        return _lies(nachricht)
    except RecursionError as e:
        raise MailFehler("Mail zu tief verschachtelt") from e


def _lies(nachricht) -> Mail:
    if not nachricht.keys():
        raise MailFehler("keine E-Mail (keine Kopfzeilen gefunden)")
    _pruefe_kopf(nachricht)
    hinweise: list[str] = []
    texte: dict[str, list[str]] = {"plain": [], "html": []}
    anhaenge = 0
    zu_lesen, gesehen = [(nachricht, 0)], 0
    while zu_lesen:
        teil, tiefe = zu_lesen.pop(0)
        gesehen += 1
        if gesehen > MAX_TEILE:
            hinweise.append(f"mehr als {MAX_TEILE} Mail-Teile – der Rest wurde nicht gelesen")
            break
        _pruefe_kopf(teil)
        if teil.get_content_type() == "message/rfc822":            # weitergeleitete Mail als Anhang: nicht hineinschauen
            anhaenge += 1
        elif teil.is_multipart():
            if tiefe >= MAX_VERSCHACHTELUNG:
                raise MailFehler(f"Mail mehr als {MAX_VERSCHACHTELUNG} Ebenen tief verschachtelt")
            zu_lesen = [(t, tiefe + 1) for t in teil.get_payload()] + zu_lesen
        elif teil.get_content_disposition() == "attachment" or teil.get_filename():
            anhaenge += 1
        elif teil.get_content_maintype() == "text" and teil.get_content_subtype() in texte:
            texte[teil.get_content_subtype()].append(_inhalt(teil))
        else:
            anhaenge += 1                                          # Bilder, Kalender … ohne Dateinamen
    return Mail(_absender_domain(nachricht), _datum(nachricht, hinweise), "\n\n".join(texte["plain"]) or None,
                "\n".join(texte["html"]) or None, anhaenge, hinweise)
