"""Kontakte als Ereignisse (P3-06, ADR-044): jedes Anschreiben und jedes Nachfassen ist eine Zeile in ``kontakte`` – erst „vorbereitet“
(Text kopiert), dann „bestätigt“ (gesendet, ADR-012). Nur anfügen; ein Kontakt wird nie gelöscht, nur bestätigt.

Ohne Netz- und Datenbankzugriff: Begriffe, Prüfung des Kanals und die Anzeigeform. Das Schreiben steht in ``Datenbank``.
"""

from __future__ import annotations

ANSCHREIBEN, NACHFASSEN = "anschreiben", "nachfassen"
ARTEN = {ANSCHREIBEN: "Anschreiben", NACHFASSEN: "Nachfassen"}

# Kanal, über den die Nachricht ging. Der Ablauf „Text kopieren → Anzeige öffnen → senden“ ist immer die Plattform der Anzeige.
PLATTFORM, UNBEKANNT = "plattform", "unbekannt"
KANAELE = {PLATTFORM: "Nachricht über die Plattform", "telefon": "Telefon", "email": "E-Mail", "whatsapp": "WhatsApp",
           "persoenlich": "persönlich", UNBEKANNT: "unbekannt"}

APP, ALTBESTAND = "app", "altbestand"     # Herkunft der Zeile: in der App erfasst oder bei der Migration aus alten Feldern übernommen


def pruefe_kanal(kanal) -> str | None:
    """Kanal aus einer Anfrage: None (nicht angegeben) oder ein bekannter Schlüssel; sonst ``ValueError``."""
    if kanal is None or kanal == "":
        return None
    if not isinstance(kanal, str) or kanal not in KANAELE:
        raise ValueError(f"kanal muss einer von {', '.join(KANAELE)} sein")
    return kanal


def _zeit(iso: str | None) -> str | None:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]} {iso[11:16]}".rstrip() if iso and len(iso) >= 10 else None


def als_json(z: dict, namen: dict[int, str] | None = None) -> dict:
    """Anzeigeform einer Zeile (``sqlite3.Row``/Dict). ``namen``: Nutzer-ID → Name (Team); ohne Team bleiben die Namen leer."""
    namen = namen or {}
    bestaetigt, verworfen = bool(z["bestaetigt_am"]), bool(z["verworfen_am"])
    if verworfen and not bestaetigt:
        zustand = "verworfen (nicht gesendet)"
    elif z["herkunft"] == ALTBESTAND:
        zustand = "aus der Zeit vor der Bestätigungspflicht übernommen" if bestaetigt else "Text kopiert (übernommen), nicht bestätigt"
    else:
        zustand = "gesendet" if bestaetigt else "Text kopiert, noch nicht als gesendet bestätigt"
    return {"id": z["id"], "anzeige_id": z["anzeige_id"], "art": z["art"], "art_text": ARTEN.get(z["art"], z["art"]),
            "kanal": z["kanal"], "kanal_text": KANAELE.get(z["kanal"], z["kanal"]), "betrag": z["betrag"],
            "vorbereitet_am": z["vorbereitet_am"], "bestaetigt_am": z["bestaetigt_am"], "bestaetigt": bestaetigt, "verworfen": verworfen,
            "herkunft": z["herkunft"], "zustand": zustand, "zeit_text": _zeit(z["bestaetigt_am"] or z["vorbereitet_am"]),
            "vorbereitet_von": namen.get(z["nutzer_id"]), "bestaetigt_von": namen.get(z["bestaetigt_von"]), "text": z["text"]}
