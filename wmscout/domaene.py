"""Fachbegriffe ohne Datenbank (P1-08, ADR-015): Status eines Inserats und Herkunft der Fahrzeugart importierter Inserate.

Bewertung, Anschreiben und Oberfläche brauchen diese Begriffe, aber keine Datenbank – deshalb liegen sie hier und nicht in
``datenbank.py`` (das sie für bestehende Importe weiterhin bereitstellt).
"""
from __future__ import annotations


# Ablauf eines Ankaufs (Schlüssel → Anzeige in der App)
# „vorbereitet“ = Text kopiert/Anzeige geöffnet; erst „kontaktiert“ (Knopf „gesendet“) ist ein bestätigter Kontakt (ADR-012)
STATUS = {"neu": "offen", "vorbereitet": "Text kopiert", "kontaktiert": "kontaktiert", "verhandlung": "in Verhandlung",
          "besichtigung": "Besichtigung", "gekauft": "gekauft", "abgesagt": "abgesagt",
          "uninteressant": "uninteressant"}

# Rangfolge für den abgeleiteten Fahrzeugstatus (höher = weiter im Ankauf); gespeichert wird er nicht (ADR-039 Nr. 3)
_STATUS_RANG = {s: i for i, s in enumerate(("neu", "uninteressant", "abgesagt", "vorbereitet", "kontaktiert", "verhandlung", "besichtigung", "gekauft"))}


def fahrzeug_status(stati) -> str:
    """Status eines Fahrzeugs aus den Ankaufsstati seiner Inserate: gekauft > besichtigung > verhandlung > kontaktiert > vorbereitet >
    abgesagt > uninteressant > neu. ``None``/leer zählt als „neu“, unbekannte Werte werden ignoriert; ohne Inserate „neu“."""
    bekannt = [(s or "neu") for s in stati if (s or "neu") in _STATUS_RANG]
    return max(bekannt, key=_STATUS_RANG.__getitem__, default="neu")


# `suche` von Inseraten aus gespeicherten Seiten: werden nie per Detailabruf nachgeladen (ADR-010)
IMPORT_SUCHE = "Import (gespeicherte Seite)"

# Herkunft der Fahrzeugart eines importierten Inserats, in `suche` kodiert (keine Schemaänderung):
#   „Import <Art> (bestätigt)“  Art stammt aus dem Art-Filter (art_s:) in der Haupttabelle einer Suchseite oder aus dem
#                               Feld „Art“ der Detailseite (die Detailseite hat Vorrang)
#   „Import <Art> (vorläufig)“  Art nur aus dem eigenen Titel bzw. einem Suchwort der Seite – Hinweis „nicht bestätigt“
#   IMPORT_SUCHE                Art unbekannt (oder widersprüchlich) – Hinweis „unbekannt“
#   „Import <Art>“              Altbestand früherer Zweigstände: gilt wie „vorläufig“
# Erkannt werden nur genau diese Muster; jede andere `suche` (auch „Importfahrzeuge …“) ist eine Crawler-Suche und
# bleibt unberührt. Bei nicht bestätigter Art wird trotzdem angeschrieben, die Zeile trägt aber einen Hinweis.
IMPORT_ARTEN = ("Teilintegrierter", "Integrierter", "Alkoven", "Kastenwagen", "Wohnwagen")
BESTAETIGT, VORLAEUFIG, UNBEKANNT = "bestaetigt", "vorlaeufig", "unbekannt"
_MARKE = {BESTAETIGT: " (bestätigt)", VORLAEUFIG: " (vorläufig)"}


def import_suche(art: str | None = None, status: str | None = None) -> str:
    """`suche`-Wert für ein importiertes Inserat; ohne Art oder Status `IMPORT_SUCHE` (unbekannt)."""
    if art not in IMPORT_ARTEN or status not in _MARKE:
        return IMPORT_SUCHE
    return f"Import {art}{_MARKE[status]}"


def import_art(suche: str | None) -> tuple[str | None, str | None]:
    """(Art, Herkunft) aus `suche`. Herkunft: BESTAETIGT, VORLAEUFIG, UNBEKANNT – oder None, wenn `suche` keine
    Import-Suche ist (Crawler). „Import <unbekannte Art> (bestätigt|vorläufig)“ gilt als UNBEKANNT."""
    if not suche:
        return None, None
    if suche == IMPORT_SUCHE:
        return None, UNBEKANNT
    if not suche.startswith("Import "):
        return None, None
    rest = suche[len("Import "):]
    for status, marke in _MARKE.items():
        if rest.endswith(marke):
            art = rest[:-len(marke)]
            return (art, status) if art in IMPORT_ARTEN else (None, UNBEKANNT)
    if rest in IMPORT_ARTEN:
        return rest, VORLAEUFIG                  # Altbestand ohne Markierung
    return None, None


# ---------- Plattformen und Eingangskanäle (ADR-035) ----------
# Kanonische Plattform-IDs (`inserate.plattform`, `anzeigen.quelle`, `Inserat.quelle`). Anzeigen-IDs sind Primärschlüssel über alle
# Plattformen: Kleinanzeigen-IDs haben kein Präfix, die übrigen ein festes. autoscout24 ist nur vorgemerkt (kein Adapter, keine Freigabe).
KLEINANZEIGEN, MOBILEDE, AUTOSCOUT24 = "kleinanzeigen", "mobile.de", "autoscout24"
ID_PRAEFIX = {KLEINANZEIGEN: "", MOBILEDE: "md-", AUTOSCOUT24: "as-"}
PLATTFORMEN = tuple(ID_PRAEFIX)
PLATTFORM_TEXT = {KLEINANZEIGEN: "Kleinanzeigen", MOBILEDE: "mobile.de", AUTOSCOUT24: "AutoScout24"}     # Anzeigename (P6-01)
# Eingangskanäle von außen: „stream“/„api“ nur mit Quellenfreigabe, „email“/„manuell“ liefert der Nutzer selbst (Push). Intern
# schreibt der Suchlauf zusätzlich „suche“ (`beobachtungen.kanal`) und der v4-Abgleich „abgleich“ (`preis_historie.kanal`).
KANAELE = ("stream", "api", "email", "manuell")
PUSH_KANAELE = ("email", "manuell")


def pruefe_plattform(plattform: str) -> str:
    if plattform not in PLATTFORMEN:
        raise ValueError(f"Unbekannte Plattform: {plattform!r} (erlaubt: {', '.join(PLATTFORMEN)})")
    return plattform


def pruefe_kanal(kanal: str) -> str:
    if kanal not in KANAELE:
        raise ValueError(f"Unbekannter Eingangskanal: {kanal!r} (erlaubt: {', '.join(KANAELE)})")
    return kanal


def pruefe_anzeigen_id(plattform: str, anzeigen_id: str) -> str:
    """Die Anzeigen-ID muss zum Präfix der Plattform passen (sonst könnten Plattformen einander überschreiben)."""
    praefix = ID_PRAEFIX[pruefe_plattform(plattform)]
    fremd = [p for p in ID_PRAEFIX.values() if p and p != praefix]
    if not anzeigen_id or not anzeigen_id.startswith(praefix) or any(anzeigen_id.startswith(p) for p in fremd):
        raise ValueError(f"Anzeigen-ID {anzeigen_id!r} passt nicht zur Plattform {plattform}")
    return anzeigen_id
