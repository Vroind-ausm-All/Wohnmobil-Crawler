"""Verkäufername für die persönliche Anrede – nur ein Profilname, keine Kontaktdaten (Datenschutz: README)."""
from __future__ import annotations

import re
import unicodedata

MAX_NAME = 50
# Erlaubt sind nur Buchstaben (auch Umlaute/Akzente), Leerzeichen, Bindestrich, Punkt und Apostroph – alles andere
# (Steuer-, Bidi- und Zero-Width-Zeichen, <>{}, Satz- und Sonderzeichen, Emojis) verwirft den Text (QA N6-2)
_ERLAUBT = re.compile(r"(?:[^\W\d_]|[ .'’-])+")
# Wörter, die in Anreden, Werbe- oder Hinweistexten statt eines Namens stehen („Hallo Herr“, „Kaufe Wohnmobile sofort“,
# „Telefon nur abends“). Nur ganze Wörter; bewusst ohne Wörter, die auch Vor- oder Nachnamen sind („Nur“, „Hey“,
# „Handel“, „Morgen“) und ohne Wortanfänge, die Nachnamen treffen („Kaufmann“ bleibt ein Name)
_FUELLWORT = re.compile(
    r"\b(?:hallo|hi|moin|servus|guten|abends|telefon\w*|tel|handy|mobil|whatsapp|sms|e?-?mail|anruf\w*"
    r"|(?:an|ver)?kauf(?:e|en|t)?|verkäufer\w*|privat\w*|wohnmobil\w*|womo\w*|wohnwagen\w*|camper\w*|caravan\w*"
    r"|reisemobil\w*|fahrzeug\w*|sofort|bitte|danke|gr[üu](?:ß|ss)e?|mfg|lg|vg|info\w*|team|gmbh|autohaus)\b", re.I)
# Angaben neben dem Namen im Verkäuferkasten, die kein Name sind (Typ, Badges, Bewertungen, Aktiv-seit-Zeile)
_KEIN_NAME = re.compile(
    r"^(?:(?:privater|gewerblicher|kommerzieller)\s+nutzer|nutzer|verkäufer|anbieter|händler|profil|anonym\w*|gast|privat"
    r"|gewerblich|pro|top|super|aktiv\s+seit\b.*|.*zufriedenheit.*|(?:besonders|sehr)\s+\w+|zuverlässig|freundlich"
    r"|verlässlich|neu|mitglied\b.*)$", re.I)
# Link- und Schaltflächentexte aus dem Verkäuferkasten („Alle Anzeigen“, „Profil ansehen“, „Folgen“, „Feedback geben“)
_NAVIGATION = re.compile(
    r"\b(?:anzeigen?|profil\w*|folg\w*|feedback|nachricht\w*|bewertung\w*|melden|teilen|merken|anrufen|kontakt\w*"
    r"|ansehen|anschauen|öffnen|schreiben|mehr|alle|weitere\w*|zeigen|shop|laden|login|anmelden|speichern|anbieter\w*)\b", re.I)

# Straßen-/Adresswörter ohne Hausnummer („Hauptstraße“, „Lindenstr.“, „Am Kirchplatz“); mit Hausnummer greift schon die Ziffernprüfung
_ADRESSE = re.compile(r"(?:\w*stra(?:ß|ss)e|\w*str\.?|\w{3,}(?:weg|platz|allee|gasse|ufer|damm|chaussee))(?!\w)", re.I)


def profilname(text) -> str | None:
    """Der Text, wenn er wie ein Profilname aussieht; sonst None (Kürzel „HW“, „Privater Nutzer“, „Aktiv seit …“,
    Badges, Bewertungszahlen, Adressen/Nummern – jede Ziffer verwirft den Text; andere Zeichen als Buchstaben,
    Leerzeichen, „-“, „.“ und „'“ ebenso; Anrede-, Werbe- und Füllwörter wie „Hallo“, „Telefon“, „Kaufe“)."""
    t = " ".join(unicodedata.normalize("NFC", str(text or "")).split())
    if not 2 <= len(t) <= MAX_NAME:
        return None
    if not _ERLAUBT.fullmatch(t):                                 # Zeichen-Whitelist (vor allen anderen Prüfungen)
        return None
    if _FUELLWORT.search(t):                                      # Anrede-/Füllwörter statt Name
        return None
    if not re.search(r"[^\W\d_]{2}", t):                       # mindestens zwei Buchstaben in Folge
        return None
    if " " not in t and len(t) <= 3 and t.isupper():             # Initialen im Profilbild
        return None
    if re.search(r"@|https?:|www\.|\d", t):                      # Mail, Adresse; Ziffern: Telefon-/Profilnummer, Hausnummer, Plz
        return None
    if _NAVIGATION.search(t):                                     # „Anzeigen des Anbieters“, „Profil ansehen“, „Folgen“
        return None
    if _ADRESSE.search(t):                                        # „Familie Müller Hauptstr.“, „Lindenstraße“
        return None
    return None if _KEIN_NAME.match(t) else t
