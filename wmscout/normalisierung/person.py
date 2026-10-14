"""Verkäufername für die persönliche Anrede – nur ein Profilname, keine Kontaktdaten (Datenschutz: README)."""
from __future__ import annotations

import re

MAX_NAME = 50
# Angaben neben dem Namen im Verkäuferkasten, die kein Name sind (Typ, Badges, Bewertungen, Aktiv-seit-Zeile)
_KEIN_NAME = re.compile(
    r"^(?:(?:privater|gewerblicher|kommerzieller)\s+nutzer|nutzer|verkäufer|anbieter|händler|profil|anonym\w*|gast|privat"
    r"|gewerblich|pro|top|super|aktiv\s+seit\b.*|.*zufriedenheit.*|(?:besonders|sehr)\s+\w+|zuverlässig|freundlich"
    r"|verlässlich|neu|mitglied\b.*)$", re.I)


def profilname(text) -> str | None:
    """Der Text, wenn er wie ein Profilname aussieht; sonst None (Kürzel „HW“, „Privater Nutzer“, „Aktiv seit …“,
    Badges, Bewertungszahlen, Adressen/Nummern)."""
    t = " ".join(str(text or "").split())
    if not 2 <= len(t) <= MAX_NAME:
        return None
    if not re.search(r"[^\W\d_]{2}", t):                       # mindestens zwei Buchstaben in Folge
        return None
    if " " not in t and len(t) <= 3 and t.isupper():             # Initialen im Profilbild
        return None
    if re.search(r"@|https?:|www\.|\d{5,}", t):                  # Mail, Adresse, Telefon-/Profilnummer
        return None
    return None if _KEIN_NAME.match(t) else t
