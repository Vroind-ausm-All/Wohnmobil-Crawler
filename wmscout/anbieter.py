"""Anbieterart (privat / gewerblich / unbekannt) mit Herkunft der Einstufung (P3-05, ADR-043).

Gespeichert wird am Inserat (``anzeigen.gewerblich`` 0/1/NULL wie bisher, dazu ``anzeigen.anbieter_herkunft``). Die Herkunft sagt, worauf
die Einstufung beruht, und bestimmt, welche spätere Angabe sie ersetzen darf – ohne Netz- und Datenbankzugriff testbar.

Herkünfte, stärkste zuerst:

* ``korrektur`` – vom Team in der App festgelegt (auch „unbekannt“). Ändert nur eine weitere Korrektur – und ein neuer Händlerbeleg ein „unbekannt“.
* ``nutzer`` – beim Text-Import vom Team ausgewählt.
* ``anzeige`` – ausdrücklich in der Anzeige: PRO-Kennzeichen bzw. Händlerprofil, Verkäuferkasten („Privater Nutzer“, „Privatanbieter“,
  „Gewerblicher Nutzer“), „MwSt. ausweisbar“.
* ``suchfilter`` – Treffer einer Suche, deren Adresse nur Privatanbieter liefert (Kleinanzeigen ``anbieter:privat``) und ohne Händlerkennzeichen.
* ``ohne_kennzeichen`` – nur „kein Händlerkennzeichen gefunden“ (Trefferliste ohne Filter, Detailseite ohne Verkäuferangabe). Schwach.
* ``altbestand`` – vor Schema v14 gespeichert, Herkunft nicht mehr feststellbar (Betreiberfrage F6: bleibt wie bisher privat bzw. gewerblich).

Regeln (``uebernehmen``) für alles, was ein Import liefert: „Unbekannt“ ersetzt nie etwas. Aus „gewerblich“ wird nie automatisch „privat“
(fehlendes Kennzeichen ist kein Beleg; auch eine Nutzerangabe im Text-Import nicht – wie bisher). Ein Händlerbeleg („gewerblich“) ersetzt jedes
„privat“ – lieber zu vorsichtig. Sonst ersetzt eine neue Angabe die gespeicherte, wenn ihre Herkunft mindestens so stark ist. Eine Korrektur
in der App bleibt gegen jeden Import stehen; nur ein Händlerbeleg ändert ein vom Team gesetztes „unbekannt“.
"""

from __future__ import annotations

KORREKTUR, NUTZER, ANZEIGE, SUCHFILTER, OHNE_KENNZEICHEN, ALTBESTAND = "korrektur", "nutzer", "anzeige", "suchfilter", "ohne_kennzeichen", "altbestand"
RANG = {ALTBESTAND: 0, OHNE_KENNZEICHEN: 1, SUCHFILTER: 2, ANZEIGE: 3, NUTZER: 4, KORREKTUR: 5}
HERKUNFT_TEXT = {KORREKTUR: "vom Team korrigiert", NUTZER: "beim Einlesen vom Team angegeben", ANZEIGE: "laut Anzeige",
                 SUCHFILTER: "Suche nur Privatanbieter", OHNE_KENNZEICHEN: "kein Händlerkennzeichen gefunden",
                 ALTBESTAND: "Altbestand, Herkunft nicht erfasst"}
BELEGT = {KORREKTUR, NUTZER, ANZEIGE, SUCHFILTER}  # Einstufungen mit positivem Beleg; die übrigen sind Vermutungen
_NUR_INTERN = {KORREKTUR, ALTBESTAND}             # vergibt nur die App bzw. die Migration, nie eine Quelle

PRIVAT, GEWERBLICH, UNBEKANNT = "privat", "gewerblich", "unbekannt"
TYP_TEXT = {PRIVAT: "privat", GEWERBLICH: "gewerblich", UNBEKANNT: "Anbieter unbekannt"}
# Adresse einer Suche, die nur Privatanbieter liefert (Kleinanzeigen-Filter im Pfad, z. B. „/anbieter:privat/“)
PRIVAT_FILTER = "/anbieter:privat"


def typ(gewerblich) -> str:
    """0/False → privat, 1/True → gewerblich, None → unbekannt."""
    return UNBEKANNT if gewerblich is None else GEWERBLICH if gewerblich else PRIVAT


def herkunft_fuer(gewerblich, herkunft: str | None) -> str | None:
    """Wirksame Herkunft einer neuen Angabe: None bei unbekanntem Anbieter; ohne (bekannte) Herkunftsangabe der Quelle gilt „gewerblich“ als
    Angabe der Anzeige (ein Kennzeichen wurde gefunden) und „privat“ nur als ``ohne_kennzeichen`` – lieber zu schwach als zu stark."""
    if gewerblich is None:
        return None
    if herkunft in RANG and herkunft not in _NUR_INTERN:
        return herkunft
    return ANZEIGE if gewerblich else OHNE_KENNZEICHEN


def uebernehmen(alt_gewerblich, alt_herkunft: str | None, neu_gewerblich, neu_herkunft: str | None, korrektur: bool = False) -> bool:
    """Ersetzt die neue Angabe (``neu_*``, Herkunft wie von ``herkunft_fuer``) die gespeicherte (``alt_*``)? Siehe Modulbeschreibung."""
    if korrektur:
        return True
    if neu_gewerblich is None or neu_herkunft not in RANG:
        return False
    if alt_herkunft == KORREKTUR:                 # Entscheidung des Teams: nur ein Händlerbeleg ändert ein festgelegtes „unbekannt“
        return alt_gewerblich is None and bool(neu_gewerblich)
    if alt_gewerblich is None:
        return True
    if alt_gewerblich and not neu_gewerblich:
        return False
    if neu_gewerblich and not alt_gewerblich:     # Händlerbeleg schlägt jedes „privat“ (auch die Auswahl beim Text-Import)
        return True
    return RANG[neu_herkunft] >= RANG.get(alt_herkunft, RANG[ALTBESTAND])


def einstufung(gewerblich, herkunft: str | None) -> dict:
    """Anzeige- und API-Form: ``typ`` (privat/gewerblich/unbekannt), ``herkunft`` (Schlüssel oder None), ``belegt`` und ``text``."""
    t = typ(gewerblich)
    if t == UNBEKANNT:
        if herkunft == KORREKTUR:
            return {"typ": t, "herkunft": KORREKTUR, "belegt": False, "text": f"{TYP_TEXT[t]} ({HERKUNFT_TEXT[KORREKTUR]})"}
        return {"typ": t, "herkunft": None, "belegt": False, "text": TYP_TEXT[t]}
    h = herkunft if herkunft in RANG else ALTBESTAND
    return {"typ": t, "herkunft": h, "belegt": h in BELEGT, "text": f"{TYP_TEXT[t]} ({HERKUNFT_TEXT[h]})"}
