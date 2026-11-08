"""Anzeigen in einer Benachrichtigungs-Mail finden und lesen – gemeinsame Logik für alle Plattformen (P2-06).

Festgemacht wird an den Anzeigen-Links: Aus jedem Link wird die Anzeigen-ID gelöst; Titel, Preis und Ort stammen aus dem Textblock
um den Link. Links werden nur lokal mit `urllib.parse` zerlegt (auch Weiterleitungs-/Tracking-Links: die Ziel-Adresse steckt in
einem Parameter und wird dort gelesen) und **nie abgerufen**. Übernommen wird nie der Link selbst, sondern die aus der ID neu
gebildete Detail-Adresse; Links auf fremde Hosts oder mit anderem Schema als http(s) werden verworfen (und gezählt).

Aufbau der Mails ist dem öffentlich bekannten Muster nachempfunden (Anzeigenblock je Treffer mit Bild, Titel, Preis, Ort und Link);
bestätigt ist er erst mit echten Mails (Abnahme F3, docs/QUELLEN.md). Bilder werden nicht übernommen (Tracking-Adressen).
"""
from __future__ import annotations

import html as html_modul
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import SplitResult, parse_qsl, unquote, urlsplit

from ...normalisierung.fahrzeug import marke_aus_text
from ...quellen.basis import Inserat
from ...quellen.kleinanzeigen.parser import ez_aus_text, km_aus_text
from ..basis import Lesung
from . import htmlbaum
from .nachricht import Mail

MAX_TREFFER = 200            # je Mail; mehr wird nicht gelesen (und gemeldet)
MAX_ZEILE_TEXT = 4500        # längere Textzeilen werden vor jeder Auswertung verworfen (Tracking-Links bleiben darunter) und gezählt
MAX_BLOCKZEILEN = 40         # Zeilen eines Anzeigenblocks, die ausgewertet werden
MAX_KANDIDATEN = 12          # Titelkandidaten je Anzeige
MAX_EBENEN = 8               # so weit darf der Textblock um einen Link nach oben wachsen
MAX_BLOCK_ZEICHEN = 1200     # größere Blöcke sind keine einzelne Anzeige mehr (Kopf-/Fußbereich der Mail)
MAX_EINBETTUNG = 2           # Tiefe verschachtelter Weiterleitungs-Links
LAYOUT_VERDAECHTIG = ("{name}-Mail erkannt, aber keine Anzeigenlinks gefunden – Layout verdächtig (oder eine Mail ohne Anzeigen, "
                      "z. B. Werbung)")

# unsichtbare und Richtungs-Steuerzeichen (Vorschautexte, Bidi-Tricks): Zero-Width, LRM/RLM, U+202A–202E, U+2060–2064, U+2066–2069, BOM, weiches Trennzeichen
_UNSICHTBAR = dict.fromkeys([*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A), 0x034F, 0xFEFF, 0x00AD])
_URL = re.compile(r"https?://[^\s<>\"'\[\]()]+", re.I)
_MARKDOWN_LINK = re.compile(r"\[([^\[\]\n]{0,300})\]\((https?://[^)\s]{1,2000})\)", re.I)
_TRENNER = re.compile(r"^[\s\-=_*~#•·+.]{3,}$")
_ZAHL = r"\d{1,3}(?:\.\d{3})+|\d+"
_VB = r"(?:vb|vhb|verhandlungsbasis)"
# Preis nur aus einer eigenen Preiszeile: nichts außer Betrag, „VB“ und einem Label wie „Preis:“
_PREISZEILE = re.compile(rf"^(?:(?:kauf)?preis:?\s*)?(?:{_VB}\s+)?(?:({_ZAHL})(?:,(?:\d{{1,2}}|-))?\s*(?:€|EUR)|(?:€|EUR)\s*({_ZAHL})(?:,\d{{1,2}})?)"
                         rf"(?:\s*{_VB}|\s*festpreis)?$", re.I)
_NUR_VB = re.compile(rf"^{_VB}$", re.I)
# Zeilen, die einen Preis in der Zeile danach entwerten: Neupreis, Rabatt, Miete, Rate …
_KEIN_PREIS = re.compile(r"neupreis|neuwert|\bnp\b|\buvp\b|listenpreis|\bstatt\b|\bvorher\b|früher|rabatt|nachlass|ersparnis|miete|mieten|vermiet|/\s*tag|"
                         r"pro\s+tag|\bmtl\b|monatlich|\brate\b|raten|anzahlung|kaution|ablöse|tausch", re.I)
_MIN_PREIS, _MAX_PREIS = 500, 2_000_000
_ORT = re.compile(r"^(?:DE-)?(\d{5})\s+([A-Za-zÄÖÜäöüß].{0,58})$")
_ORT_ENDE = re.compile(r"\s+[•·|]\s+")
_ANGABEN = re.compile(r"\b(?:\d[\d.]*\s*km|EZ\s*\d|kW|PS)\b")
_AUFFORDERUNG = re.compile(r"^(?:zur anzeige|zum (?:inserat|angebot|fahrzeug)|anzeige (?:ansehen|öffnen|anzeigen)|(?:jetzt |mehr )?ansehen|"
                           r"(?:mehr )?details|mehr (?:erfahren|anzeigen)|weiter|öffnen|hier klicken|jetzt (?:ansehen|öffnen))\b.{0,25}$", re.I)
# Gesuche und Ankaufsanzeigen – Regeln wie in eingang/text.py (P2-05); die Vereinheitlichung folgt als eigenes Paket (A1)
_GESUCH_VOR = re.compile(r"^\W{0,3}(?:(?:ich|wir)\s+(?:suchen?|kaufen?)|suche|suchen|gesucht|kaufe|ankauf|barankauf|sofortankauf)\b", re.I)
_GESUCH_NACH = re.compile(r"(?<![\w])(?:gesucht|gesuch|ankauf|ankäufe)(?![\w])", re.I)
_VERKAUFSSIGNAL = re.compile(r"\b(?:zu\s+verkaufen|verkaufe[n]?|zum\s+verkauf|biete|abzugeben|zu\s+verschenken|k[äa]ufer|besitzer|liebhaber|interessent\w*"
                             r"|nachmieter|neuen?\s+halter|neues\s+zuhause)\b", re.I)
# Kein Gesuch trotz „gesucht/Ankauf“: gesucht wird nicht das Fahrzeug selbst (Tausch, Ersatzteile, Zubehör) oder „Ankauf“ ist eine Eigenschaft des Angebots
_KEIN_GESUCH = re.compile(r"tausch|ersatzteil|zubeh|ersatz\b|zum\s+ankauf|ankauf\s+(?:durch|von|bei)|"
                          r"ankauf[\s-]*(?:check|pr[üu]fung|m[öo]glich|angebot|bewertung)", re.I)
_GESUCH_TAG = re.compile(r"^\W{0,3}(?:anzeigentyp\W{0,3})?gesuch\W{0,3}$", re.I)
_FAHRZEUGWORT = re.compile(r"wohnmobil|womo|reisemobil|camper|kastenwagen|alkoven|integriert|teilintegriert|wohnwagen|caravan|\bvan\b|\bbus\b|kasten"
                           r"|fahrzeug|\bauto|kfz|transporter", re.I)
_PLAKETTE = re.compile(r"^(?:neu|new|heute|gestern|gesuch|anzeige|foto|bild|\d+ (?:bilder|fotos))$", re.I)


@dataclass(frozen=True)
class Profil:
    """Was eine Plattform ausmacht: erlaubte Hosts, wie aus einem Link die ID wird, wie die Detail-Adresse aussieht."""

    kennung: str                                     # domaene.KLEINANZEIGEN / MOBILEDE
    name: str
    domains: tuple[str, ...]                         # erlaubte Hosts samt Subdomains (Absender-Domain gilt ebenso)
    anzeigen_id: Callable[[SplitResult], str | None]  # Link auf erlaubtem Host → Anzeigen-ID (mit Plattform-Präfix)
    detail_url: Callable[[str], str]
    anzeigen_muster: re.Pattern                      # sieht ein Link nach einer Anzeige aus? (nur für die Zählung verworfener Links)
    gesuche: bool = False                            # kennt die Plattform Gesuche?

    def host_passt(self, host: str | None) -> bool:
        host = (host or "").lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self.domains)


@dataclass
class LinkZaehler:
    """Verworfenes und Übergangenes einer Mail – als Mengen (Hash der Adresse bzw. ID), damit HTML- und Textteil nicht doppelt zählen."""

    fremd: set = field(default_factory=set)          # Anzeigen-Links auf fremdem Host (verworfen)
    unzulaessig: set = field(default_factory=set)    # Anzeigen-Adressen in Links mit anderem Schema als http(s) (verworfen)
    weitere: set = field(default_factory=set)        # IDs über der Obergrenze MAX_TREFFER (nicht gelesen)
    empfehlung: set = field(default_factory=set)     # IDs in Empfehlungsblöcken („Das könnte dich auch interessieren“, nicht übernommen)
    ueberlang: int = 0                               # Textzeilen über MAX_ZEILE_TEXT (verworfen)
    ohne_preis: int = 0                              # Treffer ohne eindeutige Preiszeile (Preis nicht übernommen)


@dataclass
class Rohtreffer:
    anzeigen_id: str
    titel_kandidaten: list[str] = field(default_factory=list)
    zeilen: list[str] = field(default_factory=list)
    bild_texte: list[str] = field(default_factory=list)     # Alternativtexte von Bildern: nur Notbehelf für den Titel
    bestimmt: bool = False                                  # Block ist schon bestimmt (auch wenn er leer blieb)


def _eingebettet(teile: SplitResult) -> list[str]:
    """Adressen, die in Parametern oder im Pfad eines Weiterleitungs-Links stecken (`…/redirect?url=https%3A%2F%2F…`)."""
    try:
        werte = [w for _, w in parse_qsl(teile.query, max_num_fields=50)]
    except ValueError:
        werte = []
    werte.append(unquote(teile.path))
    gefunden = []
    for wert in werte:
        for _ in range(2):                                       # doppelt kodierte Ziele
            if (stelle := re.search(r"https?:(?://|%2f%2f)", wert, re.I)):
                gefunden.append(unquote(wert[stelle.start():]))
                break
            wert = unquote(wert)
    return gefunden


def anzeigen_id_aus_link(href: str | None, profil: Profil, zaehler: LinkZaehler, tiefe: int = 0) -> str | None:
    """Anzeigen-ID aus einem Link – oder None. Der Link wird nur zerlegt, nie aufgerufen."""
    href = html_modul.unescape(href or "").translate(_UNSICHTBAR).strip()
    if not href or len(href) > 4000:
        return None
    try:
        teile = urlsplit(href)
        host = teile.hostname
    except ValueError:
        return None
    if teile.scheme.lower() not in ("http", "https"):
        if profil.anzeigen_muster.search(href):                 # z. B. javascript:window.open('…/s-anzeige/…')
            zaehler.unzulaessig.add(hash(href))
        return None
    if not profil.host_passt(host) or "\\" in teile.netloc:
        if profil.anzeigen_muster.search(href):
            zaehler.fremd.add(hash(href))
        return None
    if (anzeigen_id := profil.anzeigen_id(teile)):
        return anzeigen_id
    if tiefe < MAX_EINBETTUNG:
        for ziel in _eingebettet(teile):
            if (anzeigen_id := anzeigen_id_aus_link(ziel, profil, zaehler, tiefe + 1)):
                return anzeigen_id
    return None


# ---------- Textblöcke ----------
def _zeilen(text: str) -> list[str]:
    zeilen = (" ".join(z.translate(_UNSICHTBAR).split()) for z in re.split(r"[\r\n]+", text))
    return [z for z in zeilen if z and len(z) <= 1000][:MAX_BLOCKZEILEN]


def html_bloecke(baum: htmlbaum.Baum, profil: Profil, zaehler: LinkZaehler, budget: htmlbaum.Budget | None = None) -> list[Rohtreffer]:
    """Je Anzeigen-ID ein Textblock: der größte Umgebungsblock des Links, der keinen Link auf eine andere Anzeige enthält. Der Block wird je
    Anzeige einmal bestimmt (weitere Links derselben Anzeige liefern nur Titelkandidaten), alle Abfragen teilen sich das Budget.
    Links hinter einer Empfehlungs-Überschrift (`Baum.empfehlung_ab`) zählen nicht als Treffer."""
    budget = budget or htmlbaum.Budget()
    grenze = len(baum.links) if baum.empfehlung_ab is None else baum.empfehlung_ab
    anker = []
    for n, a in enumerate(baum.links):
        a.anzeigen_id = anzeigen_id_aus_link(a.attrs.get("href"), profil, zaehler)
        if a.anzeigen_id and n < grenze:
            anker.append(a)
    ids_cache: dict[int, set[str] | None] = {}

    def ids_in(knoten: htmlbaum.Knoten) -> set[str] | None:
        if id(knoten) not in ids_cache:
            ids_cache[id(knoten)] = htmlbaum.anzeigen_ids(knoten, budget)
        return ids_cache[id(knoten)]

    ergebnis: dict[str, Rohtreffer] = {}
    for a in anker:
        anzeigen_id = a.anzeigen_id
        if anzeigen_id not in ergebnis and len(ergebnis) >= MAX_TREFFER:
            zaehler.weitere.add(anzeigen_id)
            continue
        treffer = ergebnis.setdefault(anzeigen_id, Rohtreffer(anzeigen_id))
        text = htmlbaum.text(a, MAX_BLOCK_ZEICHEN, budget) or "" if len(treffer.titel_kandidaten) < MAX_KANDIDATEN else ""
        texte = _zeilen(text)                                   # umschließt der Link die ganze Karte, zählt die erste brauchbare Zeile
        treffer.titel_kandidaten.extend(texte)
        if not texte and len(treffer.bild_texte) < MAX_KANDIDATEN:
            treffer.bild_texte.extend(_zeilen(a.alt))
        if treffer.bestimmt:
            continue
        treffer.bestimmt = True
        knoten, zeilen_text = a, text
        for _ in range(MAX_EBENEN):
            eltern = knoten.eltern
            if eltern is None or eltern.name in ("body", "html", "#wurzel"):
                break
            ids = ids_in(eltern)
            if ids is None or ids - {anzeigen_id}:
                break
            if (t := htmlbaum.text(eltern, MAX_BLOCK_ZEICHEN, budget)) is None:
                break
            knoten, zeilen_text = eltern, t
        zeilen = _zeilen(zeilen_text)
        if knoten is a and a.eltern:                            # flaches Layout: Angaben stehen als Geschwister hinter dem Link
            for geschwister in a.eltern.kinder[a.index + 1:a.index + 13]:
                if geschwister.anzeigen_id or (ids := ids_in(geschwister)) is None or ids - {anzeigen_id}:
                    break
                zeilen += _zeilen(htmlbaum.text(geschwister, MAX_BLOCK_ZEICHEN, budget) or "")
        treffer.zeilen = zeilen[:MAX_BLOCKZEILEN]
    zaehler.empfehlung |= {a.anzeigen_id for a in baum.links[grenze:] if a.anzeigen_id} - set(ergebnis)
    return list(ergebnis.values())


def zaehle_text_links(text: str, profil: Profil, zaehler: LinkZaehler) -> None:
    """Nur zählen, was der Textteil an Links verwirft (der HTML-Teil lieferte die Treffer)."""
    for zeile in text.splitlines()[:50_000]:
        if len(zeile) <= MAX_ZEILE_TEXT:
            for u in _URL.findall(zeile)[:50]:
                anzeigen_id_aus_link(u.rstrip(".,;:!?"), profil, zaehler)


def text_bloecke(text: str, profil: Profil, zaehler: LinkZaehler) -> list[Rohtreffer]:
    """Reiner Text: Absätze (Leerzeile oder Trennlinie) bilden die Blöcke; hat ein Absatz mehrere Links, gehören die Zeilen
    vor einem Link zu ihm. Ein Absatz, der nur aus dem Link besteht, übernimmt den Absatz davor. Hinter einer Empfehlungs-Überschrift
    werden keine Treffer mehr gelesen. Zeilen über MAX_ZEILE_TEXT werden vor jeder Auswertung verworfen und gezählt."""
    absaetze: list[list[tuple[str, list[str]]]] = [[]]
    empfehlung = False
    nach_empfehlung: set[str] = set()
    for roh in text.splitlines():
        if len(roh) > MAX_ZEILE_TEXT:
            zaehler.ueberlang += 1
            continue
        zeile = " ".join(roh.translate(_UNSICHTBAR).split())
        if not zeile or _TRENNER.match(zeile):
            if absaetze[-1]:
                absaetze.append([])
            continue
        if "](" in zeile and zeile.count("[") <= 50:                # Markdown-Link nur, wo einer sein kann (begrenzt den Regex-Aufwand)
            zeile = _MARKDOWN_LINK.sub(r"\1 \2", zeile)
        if len(zeile) <= 80 and htmlbaum.EMPFEHLUNG.match(zeile):
            empfehlung = True
        ids = [i for u in _URL.findall(zeile)[:50] if (i := anzeigen_id_aus_link(u.rstrip(".,;:!?"), profil, zaehler))]
        if empfehlung:
            nach_empfehlung.update(ids)
            continue
        ohne_url = " ".join(_URL.sub(" ", zeile).replace("<", " ").replace(">", " ").replace("[", " ").replace("]", " ").split())
        if len(ohne_url) > 1000:
            zaehler.ueberlang += 1
            ohne_url = ""
        absaetze[-1].append((ohne_url, ids))
    ergebnis: dict[str, Rohtreffer] = {}

    def eintrag(anzeigen_id: str) -> Rohtreffer | None:
        if anzeigen_id not in ergebnis and len(ergebnis) >= MAX_TREFFER:
            zaehler.weitere.add(anzeigen_id)
            return None
        return ergebnis.setdefault(anzeigen_id, Rohtreffer(anzeigen_id))

    davor: list[str] | None = None                              # Absatz ohne Link direkt vor dem aktuellen
    for absatz in absaetze:
        if not absatz:
            continue
        absatz_ids = {i for _, ids in absatz for i in ids}
        zeilen = [z for z, _ in absatz if z][:MAX_BLOCKZEILEN]
        if not absatz_ids:
            davor = zeilen
            continue
        if len(absatz_ids) == 1:
            anzeigen_id = next(iter(absatz_ids))
            if (treffer := eintrag(anzeigen_id)) and not treffer.zeilen:
                treffer.zeilen = zeilen or davor or []
        else:
            puffer: list[str] = []
            for zeile, ids in absatz:
                if zeile:
                    puffer.append(zeile)
                if ids:
                    if (treffer := eintrag(ids[0])) and not treffer.zeilen:
                        treffer.zeilen = puffer[-MAX_BLOCKZEILEN:]
                    puffer = []
        davor = None
    zaehler.empfehlung |= nach_empfehlung - set(ergebnis)
    return list(ergebnis.values())


# ---------- Felder ----------
def _preis(zeilen: list[str]) -> tuple[int | None, bool | None]:
    """(Preis, VB) – nur aus einer eigenen Preiszeile („38.500 €“, „38.500 € VB“, „VB 38.500 €“, „Preis: 38.500 €“). Betrag im Titel oder im Fließtext
    („2.000 € unter NP“), mehrere Beträge in einer Zeile, Durchgestrichenes (fällt schon beim Lesen weg), Neupreis/Miete/Raten davor,
    mehrere verschiedene Preiszeilen: kein Preis. VB ist nur bekannt, wenn es eine Preiszeile gibt (sonst None)."""
    if any(re.search(r"miete|mieten|vermiet|/\s*tag|pro\s+tag|\bmtl\b|monatlich", z, re.I) for z in zeilen[:12]):
        return None, None                                       # Mietangebot: der Betrag ist kein Kaufpreis
    preise: dict[int, bool] = {}
    for i, z in enumerate(zeilen):
        m = _PREISZEILE.match(z)
        if not m or (i and _KEIN_PREIS.search(zeilen[i - 1])):
            continue
        wert = int((m.group(1) or m.group(2)).replace(".", ""))
        if _MIN_PREIS <= wert <= _MAX_PREIS:
            vb = bool(re.search(_VB, z, re.I)) or (i + 1 < len(zeilen) and bool(_NUR_VB.match(zeilen[i + 1])))
            preise[wert] = preise.get(wert, False) or vb
    if len(preise) != 1:
        return None, None
    return next(iter(preise.items()))


def _ort(zeilen: list[str]) -> str | None:
    for zeile in zeilen:
        if (m := _ORT.match(zeile)):
            return f"{m.group(1)} {_ORT_ENDE.split(m.group(2))[0].strip()}"
    return None


def _titel(zeilen: list[str], kandidaten: list[str], bild_texte: list[str]) -> str | None:
    def brauchbar(t: str) -> bool:
        return (any(c.isalpha() for c in t) and len(t) <= 200 and not _AUFFORDERUNG.match(t) and not _PLAKETTE.match(t)
                and not _PREISZEILE.match(t) and not _ORT.match(t))

    for t in kandidaten:
        if brauchbar(t):
            return t
    for t in zeilen:
        if brauchbar(t) and not _ANGABEN.search(t) and "€" not in t:
            return t
    return next((t for t in bild_texte if brauchbar(t)), None)


def ist_gesuch(zeilen: list[str], titel: str | None) -> bool:
    """Gesuche und Ankaufsanzeigen: Tag „Gesuch“ in den ersten Zeilen, oder Titel/erste Zeile beginnt mit „Suche/Gesucht/Kaufe/Wir kaufen/Ankauf …“ bzw.
    nennt „gesucht/Gesuch/Ankauf“ (auch nachgestellt) – jeweils mit Fahrzeug und ohne Verkaufssignal („zu verkaufen“, „Suche neuen Besitzer“)."""
    kopf = zeilen[:8]
    if any(_GESUCH_TAG.match(z) for z in kopf):
        return True
    for z in dict.fromkeys(([titel] if titel else []) + kopf[:1]):
        if _VERKAUFSSIGNAL.search(z) or _KEIN_GESUCH.search(z) or not (_GESUCH_VOR.match(z) or _GESUCH_NACH.search(z)):
            continue
        if _FAHRZEUGWORT.search(z) or marke_aus_text(z):
            return True
    return False


def baue_inserat(profil: Profil, roh: Rohtreffer, mail: Mail, zaehler: LinkZaehler | None = None) -> Inserat:
    """Rohtreffer → `Inserat`. Anbieter bleibt unbekannt (gewerblich None), die Fahrzeugart wird beim Speichern höchstens vorläufig aus dem Titel.
    Preis und VB nur aus einer eindeutigen Preiszeile (sonst None – lieber kein Preis als ein falscher)."""
    titel = _titel(roh.zeilen, roh.titel_kandidaten, roh.bild_texte)
    preis, vb = _preis(roh.zeilen)
    if preis is None and zaehler is not None:
        zaehler.ohne_preis += 1
    text = " ".join(roh.zeilen)
    details = {"mail_datum": mail.datum.isoformat(timespec="seconds")} if mail.datum else {}
    return Inserat(quelle=profil.kennung, anzeigen_id=roh.anzeigen_id, url=profil.detail_url(roh.anzeigen_id), titel=titel, preis=preis,
                   vb=vb, ort=_ort(roh.zeilen), km=km_aus_text(text), ez_jahr=ez_aus_text(text), marke=marke_aus_text(titel or ""),
                   gewerblich=None, ist_gesuch=profil.gesuche and ist_gesuch(roh.zeilen, titel), details=details)


# ---------- Parser ----------
class PlattformParser:
    """Erkennt und liest die Benachrichtigungs-Mails einer Plattform (die Module kleinanzeigen/mobilede binden ihr Profil daran)."""

    def __init__(self, profil: Profil):
        self.profil = profil

    def absender_passt(self, mail: Mail) -> bool:
        return self.profil.host_passt(mail.absender_domain)

    def anzahl_links(self, mail: Mail) -> int:
        """Anzahl verschiedener Anzeigen, auf die die Mail verlinkt (nur Links, keine Blöcke)."""
        z = LinkZaehler()
        gefunden: set[str] = set()
        if mail.html:
            gefunden |= {i for a in mail.html_baum.links if (i := anzeigen_id_aus_link(a.attrs.get("href"), self.profil, z))}
        if mail.text:
            for zeile in mail.text.splitlines()[:50_000]:
                if len(zeile) <= MAX_ZEILE_TEXT:
                    gefunden |= {i for u in _URL.findall(zeile)[:50] if (i := anzeigen_id_aus_link(u.rstrip(".,;:!?"), self.profil, z))}
        return len(gefunden)

    def erkennt(self, mail: Mail) -> bool:
        """Absender-Domain der Plattform – oder (z. B. weitergeleitete Mail) Links auf Anzeigen dieser Plattform."""
        return self.absender_passt(mail) or self.anzahl_links(mail) > 0

    def lese(self, mail: Mail) -> Lesung:
        profil = self.profil
        zaehler, bloecke = LinkZaehler(), []
        if mail.html:
            bloecke = html_bloecke(mail.html_baum, profil, zaehler)
        if mail.text:
            if bloecke:
                zaehle_text_links(mail.text, profil, zaehler)       # der Textteil wiederholt den HTML-Teil, verworfene Links zählen trotzdem
            else:
                bloecke = text_bloecke(mail.text, profil, zaehler)
        hinweise = list(mail.hinweise)
        if zaehler.unzulaessig:
            hinweise.append(f"{len(zaehler.unzulaessig)} Link(s) mit unzulässigem Schema (nicht http/https) verworfen")
        if zaehler.fremd:
            hinweise.append(f"{len(zaehler.fremd)} Anzeigenlink(s) auf fremden Hosts verworfen")
        if zaehler.weitere:
            hinweise.append(f"{len(zaehler.weitere)} weitere Anzeigen nicht gelesen (mehr als {MAX_TREFFER} je Mail)")
        if zaehler.empfehlung:
            hinweise.append(f"{len(zaehler.empfehlung)} Anzeige(n) im Empfehlungsblock („Ähnliche Anzeigen“ o. Ä.) übergangen")
        if zaehler.ueberlang:
            hinweise.append(f"{zaehler.ueberlang} überlange Textzeile(n) nicht gelesen")
        inserate = [baue_inserat(profil, b, mail, zaehler) for b in bloecke]
        gesuche = sum(i.ist_gesuch for i in inserate)
        if gesuche:
            hinweise.append(f"{gesuche} Gesuch(e)/Ankaufsanzeige(n) übersprungen")
        inserate = [i for i in inserate if not i.ist_gesuch]
        if not bloecke:
            return Lesung("unbekannt", [], [LAYOUT_VERDAECHTIG.format(name=profil.name), *hinweise], plattform=profil.kennung)
        if not inserate:
            return Lesung("unbekannt", [], [f"{profil.name}-Mail enthält nur Gesuche – nichts zu speichern", *hinweise], plattform=profil.kennung)
        if zaehler.ohne_preis:
            hinweise.append(f"{zaehler.ohne_preis} Treffer ohne eindeutige Preiszeile – Preis nicht übernommen")
        q = datenqualitaet(inserate)
        if q["preis"] < 0.5 or q["titel"] < 0.5:
            hinweise.append(f"Layout teilweise verdächtig: nur {q['preis']:.0%} der Treffer mit Preis, {q['titel']:.0%} mit Titel")
        return Lesung("suche", inserate, hinweise, plattform=profil.kennung)


def datenqualitaet(inserate: list[Inserat]) -> dict[str, float]:
    """Anteil der Inserate mit Titel, Preis, Erstzulassung, km, Ort (PLZ) und bekanntem Anbietertyp (0.0–1.0)."""
    n = len(inserate) or 1
    return {"titel": sum(bool(i.titel) for i in inserate) / n, "preis": sum(i.preis is not None for i in inserate) / n,
            "ez": sum(i.ez_jahr is not None for i in inserate) / n, "km": sum(i.km is not None for i in inserate) / n,
            "plz": sum(bool(i.ort) for i in inserate) / n, "anbieter_bekannt": sum(i.gewerblich is not None for i in inserate) / n}
