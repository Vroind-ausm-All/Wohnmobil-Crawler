"""Verkäufername für die persönliche Anrede – nur ein Profilname, keine Kontaktdaten (Datenschutz: README)."""
from __future__ import annotations

import re

MAX_NAME = 50
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
    Badges, Bewertungszahlen, Adressen/Nummern – jede Ziffer verwirft den Text)."""
    t = " ".join(str(text or "").split())
    if not 2 <= len(t) <= MAX_NAME:
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
