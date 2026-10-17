"""Eingang „Anzeige per URL + eingefügtem Text“ (P2-05, ADR-010/035): der Nutzer liefert Adresse und kopierten Anzeigentext.

Rein: kein Netz, keine Datenbank. Der Server ruft die Adresse NICHT ab – sie liefert nur Plattform und Anzeigen-ID (über die Helfer der
Parser) und die kanonische Detail-Adresse; alles Übrige stammt aus dem eingefügten Text. Gespeichert wird allein über
`Importer.importiere(lesung, "manuell")`.

Grundsätze:
* Adresse: nur http(s) auf Kleinanzeigen- und mobile.de-Hosts mit erkennbarer Anzeigen-ID (ASCII, ohne führende Null). Gespeichert wird
  nie die eingegebene Adresse, sondern die aus ID (und Titel-Slug) neu gebildete – Such-, Tracking- und Sitzungsparameter fallen weg.
* Datenschutz: Telefonnummern, E-Mail-Adressen, Links, Straßenangaben und erkennbare Namen (Label „Name:“, Grußformel mit Signatur,
  Verkäuferkasten, „Herr/Frau/Familie X“) werden VOR jeder Auswertung entfernt; aus dem Text bleibt nur die gekürzte Fahrzeugbeschreibung.
  Freie Namensnennung mitten im Fließtext erkennt das nicht (Restrisiko, docs/DATENRECHTE.md).
* Preis: lieber keiner als ein falscher. Sicher sind nur Beträge mit VB/VHB, mit Label „Preis“ oder allein in einer Zeile; sonst zählt ein
  einzelner Betrag als „geschätzt“, mehrere verschiedene ergeben keinen Preis (Hinweis mit den gefundenen Beträgen).
* Gesuche („Suche Wohnmobil …“, „Wir kaufen …“) werden nicht gespeichert.
* Die Fahrzeugart wird nie gesetzt (`Inserat.art` bleibt leer) – der Importer leitet höchstens eine VORLÄUFIGE Art aus dem Titel ab.
* Fehlende Felder sind kein Grund zur Ablehnung: Plattform und ID genügen; die Bewertung zeigt dann Unsicherheit (ohne Erstzulassung
  keine Beträge, P1-12). Bereits vorhandene Felder überschreibt der Text nicht (`Lesung.nur_leere_felder`), nur der Preis zählt neu.
* Laufzeit: alle Muster sind begrenzt (der Text darf 50 000 Zeichen lang sein, die Auswertung läuft unter der App-Sperre); die Feldsuche
  sieht je Zeile höchstens `MAX_ZEILE` Zeichen.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import NamedTuple
from urllib.parse import urlsplit

from ..domaene import KLEINANZEIGEN, MOBILEDE, VORLAEUFIG
from ..normalisierung.fahrzeug import ist_basismarke, marke_aus_text, normalisiere_marke
from ..quellen.basis import Inserat
from ..quellen.kleinanzeigen.adapter import anzeigen_id_aus_url
from ..quellen.kleinanzeigen.parser import BASIS as KLEINANZEIGEN_BASIS
from ..quellen.kleinanzeigen.parser import ort_aus_lokalitaet
from ..quellen.mobilede import anzeigen_id_aus_url as mobilede_id_aus_url
from ..quellen.mobilede import detail_url as mobilede_detail_url
from .basis import Lesung, Rohdaten
from .seiten import SuchseitenArt

KANAL = "manuell"
MAX_TEXT = 50_000                  # Zeichen des eingefügten Textes (die API lehnt mehr mit 400 ab)
MAX_URL = 2000
MAX_BESCHREIBUNG = 2000            # gespeicherte Fahrzeugbeschreibung
MAX_KURZ = 200
MAX_TITEL = 120
MAX_PREIS = 2_000_000              # eingetragener Preis (€)
MAX_ZEILE = 400                    # Zeichen je Zeile für die Feldsuche
MAX_ZEILEN = 400                   # Zeilen für die Feldsuche
ANBIETER = {"privat": False, "gewerblich": True}          # Nutzerangabe → Inserat.gewerblich; ohne Angabe None (unbekannt)

# ---------- Adresse ----------
_KLEINANZEIGEN_HOSTS = {"kleinanzeigen.de", "www.kleinanzeigen.de", "m.kleinanzeigen.de",
                        "ebay-kleinanzeigen.de", "www.ebay-kleinanzeigen.de", "m.ebay-kleinanzeigen.de"}
_KA_VOLL = re.compile(r"/s-anzeige/([A-Za-z0-9_-]{1,200})/([1-9]\d{5,}-\d+-\d+)/?", re.A)
_KA_KURZ = re.compile(r"/s-anzeige/([1-9]\d{5,})/?", re.A)
_UNSICHTBAR = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")
_STEUER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Adresse(NamedTuple):
    plattform: str
    anzeigen_id: str
    url: str                       # kanonische Detail-Adresse, aus der ID gebildet


def pruefe_adresse(url: str) -> tuple[Adresse | None, str | None]:
    """(Adresse, None) oder (None, Grund). Nur http(s), nur Kleinanzeigen/mobile.de, nur mit Anzeigen-ID in der Adresse.
    Unsichtbare Zeichen (Nullbreite Leerzeichen u. Ä.) am Rand fallen weg; Sonderzeichen in der Adresse und führende Nullen der ID
    werden abgelehnt (sonst gäbe es Phantomzeilen neben der echten Anzeige)."""
    url = _UNSICHTBAR.sub("", url or "").strip()
    if not url:
        return None, "Keine Adresse (URL) angegeben"
    if len(url) > MAX_URL:
        return None, f"Adresse zu lang (höchstens {MAX_URL} Zeichen)"
    if re.search(r"[\s\x00-\x1f\x7f]", url):
        return None, "Die Adresse enthält Leerzeichen oder Steuerzeichen – bitte nur die Adresse der Anzeige einfügen"
    if not url.isascii():
        return None, "Die Adresse enthält Sonderzeichen – bitte die Adresse unverändert aus der Adressleiste kopieren"
    try:
        teile = urlsplit(url)
        host, port = teile.hostname, teile.port
    except ValueError:
        return None, "Die Adresse ist ungültig"
    if teile.scheme.lower() not in ("http", "https"):
        return None, "Nur Adressen mit http:// oder https:// werden angenommen"
    if not host or teile.username is not None or teile.password is not None or port not in (None, 80, 443):
        return None, "Die Adresse ist ungültig"
    host = host.rstrip(".")                                  # „www.kleinanzeigen.de.“ ist derselbe Host
    if host in _KLEINANZEIGEN_HOSTS:
        plattform = KLEINANZEIGEN
    elif host == "mobile.de" or host.endswith(".mobile.de"):
        plattform = MOBILEDE
    else:
        return None, f"Plattform nicht unterstützt: nur Kleinanzeigen und mobile.de (Adresse zeigt auf „{host[:60]}“)"
    if plattform == KLEINANZEIGEN:
        if not teile.path.startswith("/s-anzeige/"):
            return None, "Das ist nicht die Adresse einer einzelnen Kleinanzeigen-Anzeige (…/s-anzeige/…/<Nummer>-…)"
        if voll := _KA_VOLL.fullmatch(teile.path):
            if ad_id := anzeigen_id_aus_url("/" + voll.group(2)):
                return Adresse(plattform, ad_id, f"{KLEINANZEIGEN_BASIS}/s-anzeige/{voll.group(1)}/{voll.group(2)}"), None
        elif kurz := _KA_KURZ.fullmatch(teile.path):
            return Adresse(plattform, kurz.group(1), f"{KLEINANZEIGEN_BASIS}/s-anzeige/{kurz.group(1)}"), None
    # ohne Fragment prüfen: eine ID hinter „#“ gehört nicht zur Adresse; mobile.de-IDs beginnen nie mit 0
    elif teile.path.endswith("/details.html") and (ad_id := mobilede_id_aus_url(f"https://{host}{teile.path}?{teile.query}")) \
            and not ad_id.removeprefix("md-").startswith("0"):
        return Adresse(plattform, ad_id, mobilede_detail_url(ad_id)), None
    return None, "Aus der Adresse ließ sich keine Anzeigen-ID ermitteln – bitte die Adresse der einzelnen Anzeige (nicht einer Suche) einfügen"


# ---------- Bereinigung (Datenschutz) ----------
_TRENNER = r"[\s./()-]"
# Alle Muster begrenzt (kein unbeschränktes Zurücklaufen bei langen Buchstaben- und Zahlenfolgen)
_EMAIL = re.compile(r"[\w.+-]{1,64}(?:\s?(?:@|[\[({]\s?at\s?[\])}])\s?|\s{1,2}at\s{1,2})[\w-]{1,63}"
                    r"(?:\s?(?:\.|[\[({]\s?(?:dot|punkt)\s?[\])}])\s?[\w-]{1,63}){1,5}", re.I)
_HANDLE = re.compile(r"(?<![\w@])@[\w.]{3,30}")
_SOCIAL = re.compile(r"\b(?:instagram|insta|facebook|tiktok|telegram|snapchat|threema|skype|youtube)\b\W{0,3}[\w.]{3,40}", re.I)
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,40}){0,3}\.(?:de|com|net|org|eu|at|ch|me|info)/\S*", re.I)
_TEL_LABEL = re.compile(r"\b(?:tel(?:efon)?(?:nummer|-?nr)?|handy(?:nummer)?|mobilnummer|whatsapp(?:-?nummer)?|fax|rufnummer)\b\.?\s{0,2}[:\-–]?\s{0,2}"
                        r"[+(]?\d[\d\s./()-]{3,30}\d", re.I)
_TEL_INTL = re.compile(rf"(?<![\w.,])(?:\+|00)\s?\d{{1,3}}{_TRENNER}{{0,3}}\d(?:{_TRENNER}{{0,3}}\d){{5,}}")
_TEL_NATIONAL = re.compile(rf"(?<![\w.,/+-])\(?0\d{{2,5}}\)?{_TRENNER}{{0,3}}\d(?:{_TRENNER}{{0,2}}\d){{3,}}")
# „49 171 1234567“ (Vorwahl ohne + oder 0): drei durch Leerzeichen getrennte Gruppen, die letzte mit mindestens 5 Ziffern, keine Jahreszahl als
# Gruppe, keine Einheit dahinter („03 2019 85000 km“, „699 232 290 cm“, „Multijet 130 150 160“ sind kein Telefon)
_TEL_GRUPPEN = re.compile(r"(?<![\w.,/+-])\d{2,3} \d{2,5} \d{5,}(?![\w.,]\d)(?! ?(?:km|tkm|€|eur|euro|ps|kw|kg|ccm|cm|mm)\b)", re.I)
_ID_ZEILE = re.compile(r"\b(?:anzeigen-?id|anzeige-?nr\.?|inseratsnummer|id)\s{0,2}[:#]?\s{0,2}\d{6,}", re.I)     # Anzeigen-ID: keine Telefonnummer
_ZIFFERN_LANG = re.compile(r"(?<!\w)\d{9,}(?!\w)")
_NAME_LABEL = re.compile(
    r"^\W{0,3}(?:name|vor-?\s?(?:und\s)?nachname|ansprechpartner(?:in)?|ihr ansprechpartner|kontaktperson|adresse|anschrift|wohnort|straße|strasse"
    r"|telefon|tel\.?|handy|fax|e-?mail|mail|whatsapp)\s{0,2}[:=]", re.I)
_GRUSS = re.compile(r"^\W{0,3}(?:mit\s+(?:(?:freundlichen|besten|herzlichen|lieben)\s+)?gr[üu](?:e|ß|ss)\w{0,6}"
                    r"|(?:freundliche|beste|liebe|herzliche|viele|schöne|sonnige)\s+gr[üu](?:e|ß|ss)\w{0,6}"
                    r"|gr[üu](?:e|ß|ss)\w{0,6}|hochachtungsvoll)\b", re.I)
_NAME_TOKEN = r"[A-ZÄÖÜ][\wäöüß.-]{1,30}"
# Abkürzungen (LG, VG, MfG) sind auch Marken und Kürzel („LG Fernseher“, „VG Kühlschrank“): nur als letzte Zeile des Textes
_GRUSS_KURZ = re.compile(rf"^\W{{0,3}}(?:lg|vg|mfg)\b[,!.]?(?:\s{{1,2}}{_NAME_TOKEN}(?:\s{_NAME_TOKEN})?)?\W{{0,3}}$", re.I)
_GRUSS_KURZ_BARE = re.compile(r"^\W{0,3}(?:lg|vg|mfg)\W{0,3}$", re.I)
_GRUSS_NAME = re.compile(rf"(?i:\b(?:gru(?:ß|ss)|gr(?:ü|ue)(?:ß|ss)e))[,\s]{{1,3}}{_NAME_TOKEN}(?:\s{_NAME_TOKEN})?\s{{0,3}}$")
_GRUSS_KURZ_NAME = re.compile(rf"(?:(?<=[.!?])|^)\s{{0,2}}(?i:\b(?:lg|vg|mfg))[,\s]{{1,3}}{_NAME_TOKEN}(?:\s{_NAME_TOKEN})?\s{{0,3}}$")
_TITEL = r"(?:(?:Dr|Prof|Dipl|Ing|med)\.?\s{1,2}){0,3}"
_NAME2 = rf"(?:\s{_NAME_TOKEN}(?=\s{{0,2}}(?:[,.;!]|$)))?"                       # zweiter Namensteil nur am Satzende
_VORSTELLUNG = re.compile(rf"(?i:\b(?:ich\s+hei(?:ß|ss)e|mein\s+name\s+ist|my\s+name\s+is|ansprechpartnerin?\s+ist))\s+{_NAME_TOKEN}(?:\s{_NAME_TOKEN})?")
_HERR_FRAU = re.compile(rf"\b(?:Herrn?|Frau|Hr\.|Fr\.|Familie|Fam\.)\s{{1,2}}{_TITEL}{_NAME_TOKEN}{_NAME2}")
_ROLLE_NAME = re.compile(rf"(?i:\b(?:vorbesitzer|verkäufer|ansprechpartner|inserent|besitzer|eigentümer)(?:in)?)\s{{0,2}}:?\s{{0,2}}"
                         rf"(?!Privat|Gewerblich|Händler|Pro\b){_TITEL}{_NAME_TOKEN}{_NAME2}")
_KONTAKT_NAME = re.compile(rf"(?i:\bkontakt)\s{{0,2}}[:=]\s{{0,2}}(?!Nachricht\b|Telefon\b|WhatsApp\b|Anruf\b|Mail\b|E-Mail\b|Chat\b)"
                           rf"{_TITEL}{_NAME_TOKEN}(?:\s{_NAME_TOKEN})?")
_ANBIETERZEILE = re.compile(r"^\W{0,3}(?:(?:privater|gewerblicher|kommerzieller)\s+nutzer|privatanbieter"
                            r"|private[rn]?\s+anbieter|gewerbliche[rn]?\s+anbieter)\b", re.I)
_PROFILZEILE = re.compile(r"^\W{0,3}(?:(?:aktiv|mitglied)\s+seit\b|nutzer-?id\b|profil\b)", re.I)
_STRASSE = re.compile(r"\b[\wäöüÄÖÜß-]{0,40}(?:stra(?:ß|ss)e|str\.?|weg|platz|allee|gasse|ufer|damm|chaussee|steig|pfad)\s{0,2}\d{1,4}\s?[a-z]?\b", re.I)
_KEINE_STRASSE_ENDE = ("sitzplatz", "schlafplatz", "stellplatz", "gurtplatz", "liegeplatz", "kopfplatz", "stauraumplatz", "bettplatz", "ersatzplatz")
# „Am Markt 3“, „Am Sonnenhang 5“ – nur mit Hausnummer vor Komma, Zeilenende oder PLZ („Im Wohnmobil 4 Schlafplätze“ ist keine Adresse)
_STRASSE_AM = re.compile(r"(?<!\w)(?:Am|An der|An den|Auf dem|Auf der|In der|Im|Zum|Zur|Beim|Unter den|Hinter dem)\s{1,2}[A-ZÄÖÜ][\wäöüß-]{2,30}"
                         r"\s{1,2}\d{1,4}\s?[a-z]?(?=\s{0,2}(?:[,;]|$|\d{5}))")
_KEINE_STRASSE_AM = {"heck", "bug", "wohnmobil", "fahrzeug", "bett", "dach", "motor", "rahmen", "fahrerhaus", "innenraum", "wagen", "gespann"}
_OBERFLAECHE = {"merken", "melden", "teilen", "nachricht schreiben", "nachricht", "anrufen", "anzeige melden", "anzeige teilen", "drucken",
                "zur merkliste hinzufügen", "telefonnummer anzeigen", "nachricht senden", "kontakt aufnehmen", "zum seitenanfang"}
# Ab hier beginnen Empfehlungen anderer Anzeigen – ihre Preise und Kilometer gehören nicht zu diesem Fahrzeug
_ENDE = re.compile(r"^\W{0,3}(?:ähnliche\s+(?:anzeigen|fahrzeuge|angebote|inserate)|weitere\s+anzeigen|andere\s+anzeigen"
                   r"|das\s+könnte\s+(?:dich|sie|euch)\s+(?:auch\s+)?interessieren|mehr\s+von\s+diesem\s+(?:anbieter|verkäufer|händler)"
                   r"|(?:weitere\s+)?anzeigen\s+(?:des|von\s+diesem)\s+(?:anbieters|verkäufers|händlers)"
                   r"|empfehlungen|sie\s+interessieren\s+sich\s+auch)\b", re.I)
_PLATZHALTER = re.compile(r"(?:\[[^\]]+\]\s*)+")


def _normalisiere(text: str) -> str:
    t = (text or "").encode("utf-8", "ignore").decode("utf-8")                       # einzelne Surrogate (kaputtes Unicode) fallen weg
    t = unicodedata.normalize("NFC", t).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u2028", "\n").replace("\u2029", "\n").replace("\x85", "\n").replace("\t", " ")
    if not t.isascii():                                                              # andere Ziffernschriften (２９８, ٢٢٢) → 0-9
        t = "".join(str(unicodedata.decimal(c)) if c.isdecimal() and not c.isascii() else c for c in t)
    return _STEUER.sub(" ", _UNSICHTBAR.sub("", t))


def _ist_telefon(gruppen: str) -> bool:
    teile = gruppen.split()
    return sum(len(g) for g in teile) >= 9 and not any(re.fullmatch(r"(?:19|20)\d\d", g) for g in teile)


def _namenszeile(zeile: str) -> bool:
    """Kurze Zeile, deren Wörter alle groß beginnen (ohne Ziffern, Geldbeträge, Platzhalter) – kommt nach Grußformeln als Unterschrift in Frage."""
    woerter = zeile.split()
    return 0 < len(zeile) <= 40 and len(woerter) <= 3 and all(w[0].isupper() for w in woerter) and not re.search(r"[\d€\[]", zeile)


def _ohne_strassen(zeile: str, zaehler: dict) -> str:
    def ersetze(m: re.Match) -> str:
        wort = m.group(0).split()[0].lower().rstrip(".")
        wort = re.sub(r"\d.*", "", wort)
        if wort == "platz" or wort.endswith(_KEINE_STRASSE_ENDE):
            return m.group(0)
        zaehler["adresse"] += 1
        return ""

    def ersetze_am(m: re.Match) -> str:
        if any(w.lower() in _KEINE_STRASSE_AM for w in m.group(0).split()[1:]):
            return m.group(0)
        zaehler["adresse"] += 1
        return ""

    zeile = _STRASSE_AM.sub(ersetze_am, _STRASSE.sub(ersetze, zeile))
    return re.sub(r"\s*,(?:\s*,)+", ",", zeile)


def bereinige(text: str) -> tuple[str, dict[str, int]]:
    """(bereinigter Text, entfernte Angaben je Art: telefon, email, link, name, adresse). Der Text endet vor Empfehlungen anderer Anzeigen.
    Entfernt werden Telefonnummern, E-Mail-Adressen, Links, Straßenangaben und Namen; übrig bleibt Fahrzeugtext."""
    zaehler = {"telefon": 0, "email": 0, "link": 0, "name": 0, "adresse": 0}
    t = _ID_ZEILE.sub("", _normalisiere(text))
    for muster, ersatz, art in ((_EMAIL, "[E-Mail entfernt]", "email"), (_HANDLE, "[Kontakt entfernt]", "email"), (_SOCIAL, "[Kontakt entfernt]", "email"),
                                (_URL, "[Link entfernt]", "link"),
                                (_TEL_LABEL, "[Telefon entfernt]", "telefon"), (_TEL_INTL, "[Telefon entfernt]", "telefon"),
                                (_TEL_NATIONAL, "[Telefon entfernt]", "telefon"), (_ZIFFERN_LANG, "[Telefon entfernt]", "telefon")):
        t, n = muster.subn(ersatz, t)
        zaehler[art] += n
    gruppen = []
    t = _TEL_GRUPPEN.sub(lambda m: gruppen.append(1) or "[Telefon entfernt]" if _ist_telefon(m.group(0)) else m.group(0), t)
    zaehler["telefon"] += len(gruppen)
    zeilen = [" ".join(z.split()) for z in t.split("\n")]
    ende = next((i for i, z in enumerate(zeilen) if _ENDE.match(z)), len(zeilen))
    zeilen, ergebnis, i = zeilen[:ende], [], 0
    folgend, danach = [""] * len(zeilen), ""                       # nächste nicht leere Zeile nach Zeile i (einmal berechnet: lange Texte)
    for n in range(len(zeilen) - 1, -1, -1):
        folgend[n] = danach
        danach = zeilen[n] or danach
    letzte = next((n for n in range(len(zeilen) - 1, -1, -1) if zeilen[n] and not _PLATZHALTER.fullmatch(zeilen[n])), -1)
    while i < len(zeilen):
        z = zeilen[i]
        folgende = folgend[i]
        if not z:
            ergebnis.append("")
        elif z.lower() in _OBERFLAECHE or _PROFILZEILE.match(z):
            pass
        elif _NAME_LABEL.match(z):
            zaehler["name"] += 1
        elif (_GRUSS.match(z) and len(z.split()) <= 6) or (i == letzte and _GRUSS_KURZ.match(z)) \
                or (_GRUSS_KURZ_BARE.match(z) and folgende and folgende == zeilen[letzte] and _namenszeile(folgende)):
            zaehler["name"] += 1
            if _GRUSS.match(z) or _GRUSS_KURZ_BARE.match(z):                      # die Unterschrift unter der Grußformel
                j = i + 1
                while j < len(zeilen) and not zeilen[j]:
                    j += 1
                if j < len(zeilen) and _namenszeile(zeilen[j]):
                    zaehler["name"] += 1
                    i = j
        elif _ANBIETERZEILE.match(folgende) and not _ANBIETERZEILE.match(z) and len(z) <= 50 and "€" not in z:
            zaehler["name"] += 1                                                  # Verkäuferkasten: Name steht über „Privater Nutzer“
        else:
            z, n1 = _VORSTELLUNG.subn("[Name entfernt]", z)
            z, n2 = _HERR_FRAU.subn("[Name entfernt]", z)
            z, n3 = _ROLLE_NAME.subn("[Name entfernt]", z)
            z, n6 = _KONTAKT_NAME.subn("[Name entfernt]", z)
            n3 += n6
            z, n4 = _GRUSS_NAME.subn("", z)
            if i == letzte:
                z, n5 = _GRUSS_KURZ_NAME.subn("", z)
                n4 += n5
            zaehler["name"] += n1 + n2 + n3 + n4
            if z := _ohne_strassen(z, zaehler).strip(" ,;"):
                ergebnis.append(z)
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ergebnis)).strip(), zaehler


# ---------- Felder aus dem Text ----------
_TAUSENDER = "[. \u00a0\u202f]"                     # 24.900 · 24 900 · 24 900 (geschütztes bzw. schmales Leerzeichen)
_ZAHL = rf"\d{{1,3}}(?:{_TAUSENDER}\d{{3}}){{1,2}}|\d{{1,9}}"
_NICHT_EINHEIT = r"(?!\s{0,2}(?:km|tkm|kg|ps|kw|cm|mm|ccm|t|l|m|%|jahre|std|stunden)\b)"          # „Preis: 85.000 km gelaufen“ ist kein Preis
_WAEHRUNG = r"(?:€|eur\b|euro\b)"
_BETRAG = re.compile(rf"(?<![\d.,])({_ZAHL})(?:,\d{{2}}\s{{0,2}}{_WAEHRUNG}|\s{{0,2}}{_WAEHRUNG}|,-)|€\s{{0,2}}({_ZAHL})(?![\d.,]\d)", re.I | re.A)
_NUR_PREIS = re.compile(rf"^\W{{0,3}}(?:(?:{_ZAHL})(?:,(?:-|\d{{2}}))?\s{{0,2}}{_WAEHRUNG}|€\s{{0,2}}(?:{_ZAHL})(?:,(?:-|\d{{2}}))?)"
                        r"\W{0,3}(?:vb|vhb)?\W{0,3}$", re.I | re.A)
_VB_VOR = re.compile(rf"\b(?:vb|vhb)\b[\s:=]{{0,3}}(?:preis[\s:=]{{0,2}})?(€\s{{0,2}})?({_ZAHL})(?![\d.,]\d){_NICHT_EINHEIT}", re.I | re.A)
_VB_NACH = re.compile(rf"(?<![\d.,])({_ZAHL})(?:,\d{{2}}|,-)?\s{{0,2}}({_WAEHRUNG})?\W{{0,3}}\b(?:vb|vhb|verhandlungsbasis)\b", re.I | re.A)
_LABEL = re.compile(rf"\b(?:kauf|fest|verkaufs|angebots|verhandlungs)?preis\b\W{{0,3}}(?:(?:vb|vhb)\W{{0,3}})?(€\s{{0,2}})?({_ZAHL})(?![\d.,]\d)"
                    rf"{_NICHT_EINHEIT}", re.I | re.A)
_VB = re.compile(r"\b(?:vb|vhb|verhandlungsbasis)\b", re.I)
# Kontext eines Betrags: im selben Satzteil davor bzw. unmittelbar danach – dann ist es kein Verkaufspreis
_KEIN_DAVOR = re.compile(r"neu(?:preis|wert)|ursprünglich|\bvorher\b|\bstatt\b|versand|anzahlung|kaution|miete|\brate\b|finanzier|nachlass|rabatt|zuzahl"
                         r"|steuer|mwst|ablöse|\baufpreis|zubehör|kosten|gebühr|reparatur|neukauf|investiert|ausgegeben|gekostet|wertverlust|tausch"
                         r"|gutachten|\bwert\b|\bab\b|inzahlung|sonderpreis|neuwagen|händlerpreis", re.I)
_KEIN_DANACH = re.compile(r"^\W{0,3}(?:unter\b|über\b|darunter|drunter|günstiger|billiger|teurer|mtl|monatl|/\s?monat|pro\s+monat|im\s+monat"
                          r"|p\.\s?m\b|rate|nachgerüst|eingebaut|verbaut|installiert|investiert"
                          r"|ausgegeben|bezahlt|gezahlt|gekostet|neu\b|wert\b|angebaut|montiert|erneuert|netto|anzahlung|kaution|pro\s+tag|/\s?tag|täglich)",
                          re.I)
_SATZTEIL = re.compile(r"[;!?,:\n]|(?<!\d)\.(?!\d)")
_KM_ZAHL = rf"\d{{1,3}}(?:{_TAUSENDER}\d{{3}}){{1,2}}|\d{{4,7}}"
_KM = re.compile(rf"(?<![\d.,])({_KM_ZAHL})\s{{0,2}}km\b", re.I | re.A)
_KM_LABEL = re.compile(rf"(?:kilometerstand|laufleistung|km-?\s?stand|gelaufene km|gefahrene km)\W{{0,12}}?({_ZAHL})(?:\s{{0,2}}(tkm|t\s?km|tsd\.?\s?km|km))?",
                       re.I | re.A)
_TKM = re.compile(r"(?<![\d.,])(\d{1,3})\s{0,2}(?:tkm|t\s?km|tsd\.?\s?km)\b", re.I | re.A)
_KEIN_KM = re.compile(r"garantie|inspektion|wartung|service|gewechselt|zahnriemen|reichweite|alle\s+\d|pro\s+(?:tag|jahr)|nächste"
                      r"|intervall|ölwechsel|reifen|bremsen|bis\s+\d", re.I)
_EZ_KURZ = re.compile(r"\bEZ\s{0,2}(?:\d{1,2}/)?((?:19|20)\d{2})(?!\d)", re.A)
_EZ_LANG = re.compile(r"erstzul(?:assung|\.)\W{0,4}(?:[a-zäö]{3,12}\.?\s{1,2})?(?:\d{1,2}[./]){0,2}((?:19|20)\d{2})(?!\d)", re.I | re.A)
_EZ_BAUJAHR = re.compile(r"\b(?:baujahr|bj\.?)\s{0,2}((?:19|20)\d{2})(?!\d)", re.I | re.A)
_PLZ_ZEILE = re.compile(r"^\W{0,3}(\d{5})\s+([A-ZÄÖÜ].{0,50})$", re.A)
_PLZ_ORT = re.compile(r"(?<![\w.,/+-])(\d{5})\s+([A-ZÄÖÜ][\wäöüÄÖÜß.-]{1,30})", re.A)
_KEIN_ORT = {"km", "kilometer", "euro", "vb", "vhb", "ps", "kw", "mal", "stück", "kg", "liter", "l", "tkm", "mm"}
_FAHRZEUGWORT = re.compile(r"wohnmobil|womo|reisemobil|camper|kastenwagen|alkoven|integriert|teilintegriert|wohnwagen|caravan|\bvan\b|\bbus\b|kasten",
                           re.I)
_NAVIGATION = {"kleinanzeigen", "anzeige", "zurück", "merkliste", "einloggen", "anmelden", "registrieren", "suche", "alle kategorien", "autos",
               "startseite", "beschreibung", "details", "ausstattung", "preis", "ort",
               "standort", "kategorie", "mobile.de", "inserieren", "hilfe", "menü", "menu"}
_GESUCH_VOR = re.compile(r"^\W{0,3}(?:(?:ich|wir)\s+(?:suchen?|kaufen?)|suche|suchen|gesucht|kaufe|ankauf|barankauf|sofortankauf)\b", re.I)
# nachgestellt: „Wohnmobil gesucht“, „Wohnmobilankauf“, „Kastenwagen Gesuch“
_GESUCH_NACH = re.compile(r"(?<![\w])(?:\w{0,25}ankauf|gesucht|gesuch|ankäufe)(?![\w])", re.I)
# „Wohnmobil kaufen – wir zahlen Höchstpreise“; rhetorisch: „Suche nach Abenteuer? Knaus Sky TI 650“
_GESUCH_ZAHLE = re.compile(r"\b(?:wir\s+zahlen|höchstpreis\w*|bestpreis\w*|bargeld|sofort\s+bar)\b", re.I)
_GESUCH_FRAGE = re.compile(r"^\W{0,3}suche\s+nach\b[^?]{0,80}\?", re.I)
_VERKAUFSSIGNAL = re.compile(r"\b(?:zu\s+verkaufen|verkaufe[n]?|zum\s+verkauf|biete|abzugeben|zu\s+verschenken|privatverkauf|k[äa]ufer|liebhaber"
                             r"|interessent\w*"
                             r"|(?:neuen?|neuer|liebevollen?)\s+besitzer|nachmieter|neuen?\s+halter|neues\s+zuhause"
                             r"|kein(?:e|en)?\s+(?:ankauf|gesuch|händler))\b", re.I)
_GESUCH_TAG = re.compile(r"^\W{0,3}(?:anzeigentyp\W{0,3})?gesuch\W{0,3}$", re.I)
_BESCHREIBUNG_KOPF = re.compile(r"^\W{0,3}beschreibung\W{0,3}$", re.I)
_BESCHREIBUNG_ENDE = re.compile(r"^\W{0,3}(?:anzeigen-?id|anzeige\s+melden|verkäufer|privater\s+nutzer|gewerblicher\s+nutzer|aufrufe)\b", re.I)


class Preis(NamedTuple):
    wert: int | None = None
    vb: bool = False
    betraege: tuple[int, ...] = ()           # Beträge im Text (ohne Jahreszahlen) – für den Hinweis, wenn kein Preis sicher erkennbar ist


def _zahl(text: str) -> int:
    return int(re.sub(r"[. \u00a0\u202f]", "", text))


def _in_euro(m: re.Match) -> int:
    return _zahl(next(g for g in m.groups() if g and g[0].isdigit()))


def _kontext_ok(zeile: str, start: int, ende: int) -> bool:
    """Kein Preis, wenn im selben Satzteil davor oder direkt danach Neupreis, Tausch, monatlich, nachgerüstet, „unter …“ steht."""
    davor = _SATZTEIL.split(zeile[max(0, start - 60):start])[-1]
    return not _KEIN_DAVOR.search(davor) and not _KEIN_DANACH.match(zeile[ende:ende + 30])


def _preis(zeilen: list[str]) -> Preis:
    """Nur ein SICHERER Preis wird gelesen: Betrag mit VB/VHB davor oder dahinter, mit Label „Preis“/„Kaufpreis“ oder allein in einer Zeile –
    jeweils genau ein Wert (mehrere verschiedene Werte ergeben keinen Preis). Beträge im Fließtext („Motor bei 2.500 € überholt“, „Restschuld
    15.000 €“) sind nie ein Preis; sie stehen nur im Hinweis. Beträge nach Neupreis, Tausch, Raten, nachgerüstet usw. zählen nie."""
    sicher: dict[int, bool] = {}                         # Wert → VB
    alle: dict[int, None] = {}                           # Beträge in Reihenfolge, ohne Doppelte
    for i, z in enumerate(zeilen[:150]):
        nur = _NUR_PREIS.match(z)
        vb_zeile = bool(_VB.search(z) or (nur and i + 1 < len(zeilen) and _VB.search(zeilen[i + 1])))
        for muster, klasse in ((_VB_VOR, "A"), (_VB_NACH, "A"), (_LABEL, "C")):
            for m in muster.finditer(z):
                wert = _in_euro(m)
                euro = bool(m.group(1) if muster is _VB_VOR or muster is _LABEL else m.group(2))
                if euro or not 1950 <= wert <= 2100:
                    alle[wert] = None
                if 500 <= wert <= 2_000_000 and (euro or wert >= 3000 or klasse == "C") and _kontext_ok(z, m.start(), m.end()):
                    sicher[wert] = sicher.get(wert, False) or klasse == "A" or vb_zeile
        for m in _BETRAG.finditer(z):
            wert = _in_euro(m)
            alle[wert] = None
            if nur and 500 <= wert <= 2_000_000 and _kontext_ok(z, m.start(), m.end()) and wert == _in_euro(next(_BETRAG.finditer(z))):
                sicher[wert] = sicher.get(wert, False) or vb_zeile
    betraege = tuple(b for b in alle if b >= 500)[:6]
    if len(sicher) == 1:
        wert, vb = next(iter(sicher.items()))
        return Preis(wert, vb, betraege)
    return Preis(None, False, betraege)


def _km(text: str, zeilen: list[str]) -> int | None:
    if m := _KM_LABEL.search(text):
        wert, einheit = _zahl(m.group(1)), (m.group(2) or "").lower()
        if einheit.startswith(("t", "tsd")):
            wert *= 1000
        if (einheit or wert >= 1000) and 0 <= wert <= 1_500_000:
            return wert
    for z in zeilen:
        if _KEIN_KM.search(z):
            continue
        if (m := _KM.search(z)) and 1000 <= (wert := _zahl(m.group(1))) <= 1_500_000:
            return wert
        if (m := _TKM.search(z)) and 1 <= int(m.group(1)) <= 1500:
            return int(m.group(1)) * 1000
    return None


def _ez(text: str, jahr: int) -> int | None:
    for muster in (_EZ_KURZ, _EZ_LANG, _EZ_BAUJAHR):
        for m in muster.finditer(text):
            if 1950 <= (wert := int(m.group(1))) <= jahr + 1:
                return wert
    return None


def _ort(zeilen: list[str], text: str) -> str | None:
    for z in zeilen[:40]:
        if (m := _PLZ_ZEILE.match(z)) and m.group(2).split()[0].lower().strip(".,") not in _KEIN_ORT:
            return ort_aus_lokalitaet(re.split(r"[•|,;]", f"{m.group(1)} {m.group(2)}")[0].strip())
    for m in _PLZ_ORT.finditer(text):
        if m.group(2).lower().strip(".,-") not in _KEIN_ORT:
            return f"{m.group(1)} {m.group(2).strip('.,-')}"
    return None


def _titel(zeilen: list[str]) -> str | None:
    """Erste Zeile am Textanfang, die nach Fahrzeugtitel aussieht (Fahrzeugwort oder bekannte Marke); sonst die erste brauchbare Zeile."""
    kandidaten = [z for z in zeilen[:15] if 6 <= len(z) <= 150 and z.lower() not in _NAVIGATION and not _NUR_PREIS.match(z)
                  and not re.fullmatch(r"[\d\s.,/€-]+", z) and not _PLATZHALTER.fullmatch(z) and not _GESUCH_TAG.match(z)]
    wahl = next((z for z in kandidaten if _FAHRZEUGWORT.search(z) or marke_aus_text(z)), None) or (kandidaten[0] if kandidaten else None)
    return wahl[:MAX_TITEL].strip() if wahl else None


def _kuerze(text: str, grenze: int) -> str:
    """Höchstens `grenze` Zeichen, an einer Wortgrenze und nicht mitten in einem Platzhalter „[… entfernt]“."""
    kurz = text[:grenze].rsplit(None, 1)[0] if len(text) > grenze else text
    return kurz[:kurz.rindex("[")].rstrip() if kurz.count("[") > kurz.count("]") else kurz


def _beschreibung(zeilen: list[str]) -> str:
    if (start := next((i for i, z in enumerate(zeilen) if _BESCHREIBUNG_KOPF.match(z)), None)) is not None:
        rest = zeilen[start + 1:]
        zeilen = rest[:next((i for i, z in enumerate(rest) if _BESCHREIBUNG_ENDE.match(z)), len(rest))] or zeilen
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(zeilen)).strip()
    return text if len(text) <= MAX_BESCHREIBUNG else _kuerze(text, MAX_BESCHREIBUNG) + " …"


def ist_gesuch(zeilen: list[str], titel: str | None = None) -> bool:
    """Gesuche und Ankaufsanzeigen: Tag „Gesuch“ in den ersten Zeilen, oder Titel/erste Zeile beginnt mit „Suche/Gesucht/Kaufe/Wir kaufen/Ankauf …“
    bzw. nennt „gesucht/Gesuch/Ankauf“ (auch nachgestellt: „Wohnmobil gesucht“, „Wohnmobil-Ankauf“) – jeweils mit Fahrzeug und ohne
    Verkaufssignal („zu verkaufen“, „Suche neuen Besitzer“). Spätere Zeilen („Suche auch Tausch …“, „Kaufe ggf. auch … in Zahlung“) zählen nicht."""
    kopf = [z[:MAX_ZEILE] for z in zeilen if z][:8]
    if any(_GESUCH_TAG.match(z) for z in kopf):
        return True
    for z in dict.fromkeys(([titel[:MAX_ZEILE]] if titel else []) + kopf[:1]):
        if _VERKAUFSSIGNAL.search(z) or _GESUCH_FRAGE.match(z) or not (_GESUCH_VOR.match(z) or _GESUCH_NACH.search(z) or _GESUCH_ZAHLE.search(z)):
            continue
        if _FAHRZEUGWORT.search(z) or marke_aus_text(z) or re.search(r"fahrzeug|\bauto|kfz|transporter", z, re.I):
            return True
    return False


# ---------- Lesung ----------
def _nicht_gespeichert(hinweis: str, plattform: str | None = None) -> Lesung:
    return Lesung("unbekannt", [], [hinweis], plattform=plattform)


def _euro_text(betraege) -> str:
    return ", ".join(f"{b:,}".replace(",", ".") + " €" for b in betraege)


def lese_text(url: str, text: str, anbieter: str | None, empfangen_am: datetime, preis: int | None = None, vb: bool | None = None) -> Lesung:
    """Adresse + eingefügter Text → Lesung (art 'detail' mit genau einem Inserat – oder 'unbekannt' mit Grund in `hinweise`).

    anbieter: 'privat', 'gewerblich' oder None/'' (unbekannt). preis/vb: vom Nutzer eingetragener Preis laut Anzeige (1..2 000 000 €) und
    Verhandlungsbasis; er hat Vorrang vor dem Text. Ohne ihn zählt nur ein sicher erkannter Textpreis (`Lesung.preis_status`: 'eingetragen',
    'text', 'unsicher' = Beträge gefunden, aber keiner sicher, 'fehlt'); sonst wird die Anzeige ohne Preis gespeichert und ein vorhandener Preis
    bleibt. ValueError bei ungültigen Werten."""
    if anbieter not in (None, "", *ANBIETER):
        raise ValueError(f"anbieter muss 'privat' oder 'gewerblich' sein, nicht {anbieter!r}")
    if preis is not None and (isinstance(preis, bool) or not isinstance(preis, int) or not 1 <= preis <= MAX_PREIS):
        raise ValueError(f"preis muss eine ganze Zahl von 1 bis {MAX_PREIS} sein")
    if vb is not None and not isinstance(vb, bool):
        raise ValueError("vb muss wahr oder falsch sein")
    adresse, grund = pruefe_adresse(url)
    if adresse is None:
        return _nicht_gespeichert(grund)
    if len(text or "") > MAX_TEXT:
        return _nicht_gespeichert(f"Text zu lang (höchstens {MAX_TEXT} Zeichen)", adresse.plattform)
    sauber, entfernt = bereinige(text)
    alle_zeilen = [z for z in sauber.split("\n") if z]
    if not any(not _PLATZHALTER.fullmatch(z) for z in alle_zeilen):                  # nur Platzhalter („[Telefon entfernt]“) übrig
        alle_zeilen = []
    if not alle_zeilen:
        return _nicht_gespeichert("Kein Anzeigentext eingefügt – bitte den Text der Anzeige kopieren und einfügen", adresse.plattform)
    zeilen = [z[:MAX_ZEILE] for z in alle_zeilen[:MAX_ZEILEN]]                       # Feldsuche: begrenzte Zeilen, begrenzte Anzahl
    feldtext = "\n".join(zeilen)
    titel = _titel(zeilen)
    if ist_gesuch(zeilen, titel):
        return _nicht_gespeichert("Das ist ein Gesuch bzw. eine Ankaufsanzeige („Suche …“, „Wir kaufen …“) – nicht gespeichert", adresse.plattform)

    jahr = empfangen_am.astimezone(timezone.utc).year
    text_preis = _preis(zeilen)
    km, ez = _km(feldtext, zeilen), _ez(feldtext, jahr)
    ort = _ort(zeilen, feldtext)
    marke = marke_aus_text(titel or "") or marke_aus_text(feldtext[:1500])
    beschreibung = _beschreibung(alle_zeilen)
    kurz = _kuerze(" ".join(beschreibung.split()), MAX_KURZ)
    if preis is not None:
        wert, ist_vb, status = preis, bool(vb), "eingetragen"
    else:
        wert, ist_vb = text_preis.wert, text_preis.vb or bool(vb) and text_preis.wert is not None
        status = "text" if wert is not None else "unsicher" if text_preis.betraege else "fehlt"
    inserat = Inserat(quelle=adresse.plattform, anzeigen_id=adresse.anzeigen_id, url=adresse.url,
                      titel=titel or f"Anzeige {adresse.anzeigen_id.removeprefix('md-')} (Titel fehlt)", preis=wert, vb=ist_vb, ort=ort, km=km,
                      ez_jahr=ez, marke=marke, kurzbeschreibung=kurz or None, beschreibung=beschreibung or None, gewerblich=ANBIETER.get(anbieter or ""))

    hinweise = []
    fehlt = [name for name, wert in (("Preis", wert), ("Kilometerstand", km), ("Erstzulassung", ez), ("PLZ/Ort", ort), ("Titel", titel)) if wert is None]
    if fehlt:
        hinweise.append(f"unvollständig: {', '.join(fehlt)} nicht im Text erkannt")
    if status == "unsicher":
        hinweise.append(f"Preis nicht sicher erkannt (Beträge im Text: {_euro_text(text_preis.betraege)}) "
                        "– bitte Preis im Formular eintragen und erneut einlesen")
    elif status == "fehlt":
        hinweise.append("Kein Preis im Text erkannt – bitte Preis im Formular eintragen und erneut einlesen")
    elif status == "eingetragen" and text_preis.wert is not None and text_preis.wert != preis:
        hinweise.append(f"Eingetragener Preis ({_euro_text([preis])}) weicht vom Preis im Text "
                        f"({_euro_text([text_preis.wert])}) ab – der eingetragene Preis gilt")
    if ez is None:
        hinweise.append("Ohne Erstzulassung zeigt die Bewertung keine Beträge – bitte den Text mit der Erstzulassung erneut einfügen")
    art, herkunft = SuchseitenArt().fuer_treffer(titel, kurz)
    hinweise.append(f"Fahrzeugart „{art}“ nur aus dem Titel abgeleitet (vorläufig, nicht bestätigt)" if art and herkunft == VORLAEUFIG
                    else "Fahrzeugart unbekannt")
    if anbieter not in ANBIETER:
        hinweise.append("Anbieter (privat/gewerblich) nicht angegeben – vor dem Anschreiben prüfen")
    if entfernt_text := ", ".join(f"{n} × {name}" for art_, name in (("telefon", "Telefonnummer"), ("email", "E-Mail/Kontakt"), ("link", "Link"),
                                                                 ("name", "Name/Namenszeile"), ("adresse", "Straßenangabe")) if (n := entfernt[art_])):
        hinweise.append(f"Aus Datenschutzgründen vor dem Speichern entfernt: {entfernt_text}")
    if beschreibung.endswith("…"):
        hinweise.append(f"Beschreibung auf {MAX_BESCHREIBUNG} Zeichen gekürzt")
    return Lesung("detail", [inserat], hinweise, plattform=adresse.plattform, nur_leere_felder=True, preis_status=status)


def widerspricht_marke(text_marke: str | None, gespeicherte_marke: str | None) -> bool:
    """Nennt der Text eine andere Marke als die gespeicherte Anzeige? Basisfahrzeuge (Fiat, Mercedes …) und „Weitere Marken“ zählen nicht
    als Widerspruch: ein Knaus auf Fiat-Basis trägt beide Namen."""
    a, b = normalisiere_marke(text_marke), normalisiere_marke(gespeicherte_marke)
    if not a or not b or ist_basismarke(a) or ist_basismarke(b) or {a.lower(), b.lower()} & {"weitere marken", "andere", "sonstige"}:
        return False
    return a.lower() != b.lower()


def ergebnis_der(stat: dict) -> str:
    """'neu', 'preis' (Preis gesenkt) oder 'bekannt' aus dem Zähler, den `Importer.importiere` liefert."""
    return "neu" if stat.get("neu") else "preis" if stat.get("preis") else "bekannt"


class TextEingang:
    """Eingang für Adresse + eingefügten Text. Rohdaten: JSON `{"url": …, "text": …, "anbieter": "privat"|"gewerblich"|null}` (UTF-8)."""

    kennung = "text"
    kanal = KANAL

    @staticmethod
    def rohdaten(url: str, text: str, anbieter: str | None = None, empfangen_am: datetime | None = None,
                 preis: int | None = None, vb: bool | None = None) -> Rohdaten:
        # ensure_ascii: auch einzelne Surrogate sind darstellbar
        inhalt = json.dumps({"url": url, "text": text, "anbieter": anbieter, "preis": preis, "vb": vb}).encode("ascii")
        return Rohdaten(inhalt, "text", empfangen_am or datetime.now(timezone.utc))

    def lese(self, roh: Rohdaten) -> Lesung:
        try:
            daten = json.loads(roh.inhalt.decode("utf-8"))
        except ValueError:
            return _nicht_gespeichert("Eingabe nicht lesbar")
        if not isinstance(daten, dict) or not isinstance(daten.get("url"), str) or not isinstance(daten.get("text"), str) \
                or not (daten.get("anbieter") is None or isinstance(daten["anbieter"], str)):
            return _nicht_gespeichert("Eingabe ungültig: Adresse und Text müssen Zeichenketten sein")
        try:
            return lese_text(daten["url"], daten["text"], daten.get("anbieter"), roh.empfangen_am, daten.get("preis"), daten.get("vb"))
        except ValueError as e:
            return _nicht_gespeichert(str(e))
