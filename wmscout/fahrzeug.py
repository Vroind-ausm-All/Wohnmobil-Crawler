"""Fahrzeug-Wissen: Marken, Modellreihen, Fahrzeugart – und daraus die Modellbezeichnung.

Die Modellerkennung arbeitet in drei Stufen:
  1. Feld „Modell“ aus der Detailseite (falls Kleinanzeigen es liefert)
  2. bekannte Modellreihe der Marke in Titel/Beschreibung (+ Grundriss, z. B. „650 MEG“)
  3. Heuristik: die Wörter nach dem Markennamen im Titel, bis ein Füllwort kommt
"""
from __future__ import annotations

import json
import re

from .geo import plz_aus_text

# Aufbauhersteller (Reihenfolge egal – längere Namen werden zuerst geprüft)
MARKEN = [
    "Adria", "Ahorn", "Benimar", "Bimobil", "Bürstner", "Carado", "Carthago", "Challenger", "Chausson",
    "Clever", "Concorde", "Crosscamp", "Dethleffs", "Elnagh", "Etrusco", "Eura Mobil", "Fendt", "Frankia",
    "Globecar", "Hobby", "Hymer", "Itineo", "Kabe", "Knaus", "Laika", "LMC", "Malibu", "McLouis", "Morelo",
    "Niesmann", "Pilote", "Pössl", "Rapido", "Rimor", "Roller Team", "Sun Living", "Sunlight", "Tabbert",
    "TEC", "Vantourer", "Weinsberg", "Westfalia",
]
# Basisfahrzeuge – nur Marke, wenn kein Aufbauhersteller genannt ist (z. B. VW California)
BASIS_MARKEN = ["Volkswagen", "Mercedes", "Fiat", "Ford", "Citroën", "Peugeot", "Renault", "Iveco", "MAN"]

ALIASE = {
    "buerstner": "Bürstner", "burstner": "Bürstner", "poessl": "Pössl", "possl": "Pössl",
    "vw": "Volkswagen", "mercedes-benz": "Mercedes", "citroen": "Citroën", "eura": "Eura Mobil",
    "euramobil": "Eura Mobil", "niesmann+bischoff": "Niesmann", "n+b": "Niesmann", "hymercar": "Hymer",
    "rollerteam": "Roller Team", "mc louis": "McLouis",
}

# Bekannte Modellreihen je Marke (Schreibweise so, wie sie im Anschreiben erscheinen soll)
MODELLE = {
    "Adria": ["Coral", "Matrix", "Sonic", "Twin", "Compact", "Coral XL"],
    "Benimar": ["Tessoro", "Mileo", "Sport", "Primero"],
    "Bürstner": ["Lyseo", "Ixeo", "Nexxo", "Travel Van", "Delfin", "Elegance", "Campeo", "Lineo", "Argos",
                 "Aviano", "Brevio", "Eliseo", "Copa", "City Car"],
    "Carado": ["T 132", "T 135", "T 337", "T 338", "T 447", "T 449", "A 461", "A 464", "V 600", "V 337",
               "CV 600", "CV 640", "Camper Van"],
    "Carthago": ["c-tourer", "chic c-line", "chic e-line", "chic s-plus", "c-compactline", "liner-for-two",
                 "highliner"],
    "Challenger": ["Mageo", "Graphite", "Genesis", "Sirius"],
    "Chausson": ["Flash", "Welcome", "Titanium", "Best of", "Exaltis", "Twist", "V 594", "V 697"],
    "Clever": ["Vario", "Tour", "Celebration", "Runner", "Move", "Drive"],
    "Concorde": ["Carver", "Charisma", "Credo", "Centurion", "Liner Plus", "Cruiser"],
    "Dethleffs": ["Trend", "Just", "Pulse", "Globebus", "Globetrotter", "Esprit", "Advantage", "Alpa",
                  "Magic Edition", "Globeline", "Camper", "Beduin"],
    "Elnagh": ["Baron", "T-Loft", "Magnum", "Duke"],
    "Etrusco": ["T 7400", "T 7300", "V 6600", "A 7300", "CV 600"],
    "Eura Mobil": ["Profila", "Integra", "Activa One", "Contura", "Terrestra", "Xtura", "Van"],
    "Frankia": ["Platin", "Titan", "Neo", "Yucon", "I-Line", "A-Line", "T-Line"],
    "Globecar": ["Campscout", "Roadscout", "Familyscout", "Globescout", "D-Line", "H-Line"],
    "Hobby": ["Optima", "Siesta", "Van", "Vantana", "Maxia", "Beachy"],
    "Hymer": ["B-Klasse", "B-Klasse MasterLine", "B-Klasse ModernComfort", "B-Klasse DynamicLine",
              "B-Klasse SupremeLine", "ML-T", "ML-I", "Exsis", "Tramp", "Free", "Grand Canyon", "Duomobil",
              "Van S", "Yosemite", "Ayers Rock", "Sydney", "Starline", "Camp", "Swing", "Eriba Car", "Venture S",
              "Hymercar", "Big Sky"],
    "Itineo": ["SB 700", "CS 660", "RF 700", "MC 660", "PB 740"],
    "Knaus": ["Sky TI", "Sky Wave", "Sky Traveller", "Sky I", "Van TI", "Van I", "Van Wave", "Live TI",
              "Live Wave", "Live I", "Live Traveller", "L!ve TI", "L!ve Wave", "Sun TI", "Sun I", "BoxStar",
              "BoxDrive", "BoxLife", "Tourer Van", "Tourer Cuv", "Platinum Selection", "Traveller"],
    "Laika": ["Kosmo", "Ecovip", "Rexosline", "Kreos"],
    "LMC": ["Cruiser", "Tourer", "Breezer", "Liberty", "Explorer", "Innovan"],
    "Malibu": ["Van", "Charming", "T 430", "T 440", "I 410", "I 440", "First Class", "Compact"],
    "McLouis": ["Tandy", "Glamys", "Nevis", "Sovereign", "Mc4", "Carat", "Fusion"],
    "Morelo": ["Home", "Palace", "Loft", "Empire", "Grand Empire"],
    "Niesmann": ["Arto", "Flair", "Smove", "iSmove", "Clou"],
    "Pilote": ["Pacific", "Galaxy", "Foxy Van", "Atlas", "Explorateur", "Aventura"],
    "Pössl": ["Summit", "Roadcruiser", "Roadcamp", "2Win", "2Win Plus", "D-Line", "Trenta", "Campster",
              "Roadstar", "Vanstar", "Summit Prime", "Summit Shine"],
    "Rapido": ["Serie M", "Serie C", "Serie 8", "Serie 6", "Distinction", "V 55", "V 62", "V 65", "V 68"],
    "Rimor": ["Seal", "Evo", "Kayak", "Katamarano", "Horus", "Europeo", "Superbrig"],
    "Roller Team": ["Kronos", "Zefiro", "Livingstone", "Pegaso", "Granduca", "Autoroller"],
    "Sun Living": ["S 70", "S 75", "A 70", "A 75", "V 60", "V 65", "Lido"],
    "Sunlight": ["T 60", "T 64", "T 65", "T 67", "T 68", "T 69", "A 68", "A 70", "A 72", "I 68", "I 69",
                 "V 60", "V 66", "Cliff", "Adventure Edition"],
    "Tabbert": ["Puccini", "Cellini", "Da Vinci", "Rossini", "Vivaldi", "Pep"],
    "TEC": ["Freetec", "Travel King", "Rotec"],
    "Vantourer": ["600", "630", "540", "600 L", "630 L"],
    "Weinsberg": ["CaraBus", "CaraCompact", "CaraSuite", "CaraHome", "CaraLoft", "CaraTour", "Pepper",
                  "X-Cursion", "CaraCore", "CaraOne"],
    "Westfalia": ["Club Joker", "Columbus", "Kepler", "Amundsen", "Sven Hedin", "Jules Verne", "Nugget",
                  "James Cook", "Meridian", "Berlingo"],
    "Volkswagen": ["Grand California", "California Ocean", "California Coast", "California Beach",
                   "California", "Multivan", "Crafter", "T6.1", "T6", "T5", "T4", "T3"],
    "Mercedes": ["Marco Polo", "Sprinter", "Vito", "V-Klasse"],
    "Ford": ["Nugget Plus", "Nugget", "Transit Custom", "Transit"],
}

# Wörter, an denen die Heuristik aufhört (Titel-Füllwörter, Ausstattung, Zustand)
FUELLWOERTER = {
    "wohnmobil", "reisemobil", "camper", "campervan", "womo", "wohnwagen", "teilintegriert", "teilintegrierter",
    "teilintegriertes", "teilintegrierte", "integriert", "integrierter", "vollintegriert", "vollintegrierter",
    "alkoven", "kastenwagen", "van", "mit", "und", "inkl", "inklusive", "top", "sehr", "gepflegt", "zustand",
    "tüv", "tuev", "hu", "neu", "vb", "ez", "bj", "baujahr", "km", "scheckheft", "automatik", "markise", "solar",
    "klima", "garage", "erstbesitz", "erste", "hand", "privat", "verkauf", "verkaufe", "zu", "verkaufen",
    "fiat", "ducato", "ford", "transit", "mercedes", "sprinter", "citroen", "citroën", "jumper", "peugeot",
    "boxer", "renault", "master", "iveco", "daily", "man", "tge", "für", "fuer", "personen", "pers",
    "schlafplätze", "sitzplätze", "einzelbetten", "queensbett", "hubbett", "festbett", "rentnerfahrzeug",
    "nichtraucher", "tierfrei", "wenig", "viel", "ausstattung", "voll", "vollausstattung", "lithium", "sat",
    "anhängerkupplung", "ahk", "euro", "diesel", "ps", "kw", "multijet", "aus", "von", "der", "die", "das",
}

ART_SCHLUESSEL = [  # (Suchbegriff in Suche/Art, Schlüssel) – erster Treffer gewinnt
    ("teilint", "Teilintegrierter"), ("vollint", "Integrierter"), ("integr", "Integrierter"),
    ("alkoven", "Alkoven"), ("kasten", "Kastenwagen"), ("camper", "Kastenwagen"), ("bus", "Kastenwagen"),
    ("wohnwagen", "Wohnwagen"), ("caravan", "Wohnwagen"),
]
ART_PLURAL = {
    "Teilintegrierter": "Teilintegrierte", "Integrierter": "Integrierte", "Alkoven": "Alkovenmobile",
    "Kastenwagen": "Kastenwagen", "Wohnwagen": "Wohnwagen", "Sonstige": "Wohnmobile",
}

_TRENNER = re.compile(r"[,;|!()/*+„“\"]|\s[-–]\s")
_GRUNDRISS = re.compile(r"^\s*((?:[A-Z]{1,3}\s?)?\d{2,4}(?:\s?[A-Z]{1,4}(?![a-zäöüß\d]))?)")


def _muster(name: str) -> re.Pattern:
    """Ganzes Wort/Wortgruppe, Leerzeichen und Bindestriche flexibel."""
    teile = [re.escape(t) for t in re.split(r"[\s-]+", name)]
    return re.compile(r"(?<![\w!])" + r"[\s-]*".join(teile) + r"(?![\w])", re.I)


_MODELL_MUSTER = {m: [(s, _muster(s)) for s in sorted(liste, key=len, reverse=True)] for m, liste in MODELLE.items()}
_ALIAS_MUSTER = [(ziel, _muster(a)) for a, ziel in ALIASE.items()]
_AUFBAU_MUSTER = [(m, _muster(m)) for m in MARKEN] + [(z, mu) for z, mu in _ALIAS_MUSTER if z not in BASIS_MARKEN]
_BASIS_MUSTER = [(m, _muster(m)) for m in BASIS_MARKEN] + [(z, mu) for z, mu in _ALIAS_MUSTER if z in BASIS_MARKEN]


def normalisiere_marke(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip()
    for m in MARKEN + BASIS_MARKEN:
        if m.lower() == n.lower():
            return m
    return ALIASE.get(n.lower(), n)


def ist_basismarke(marke: str | None) -> bool:
    return marke in BASIS_MARKEN


def _erste_marke(text: str, muster: list) -> str | None:
    treffer = [(t.start(), m) for m, mu in muster if (t := mu.search(text))]
    return min(treffer)[1] if treffer else None


def marke_aus_text(text: str) -> str | None:
    """Aufbauhersteller hat Vorrang vor dem Basisfahrzeug („Fiat Ducato Knaus …“ → Knaus)."""
    return _erste_marke(text, _AUFBAU_MUSTER) or _erste_marke(text, _BASIS_MUSTER)


def _grundriss(rest: str) -> str:
    m = _GRUNDRISS.match(rest)
    if not m:
        return ""
    gr = m.group(1).strip()
    zahl = re.search(r"\d+", gr).group(0)
    if re.fullmatch(r"(19|20)\d\d", zahl):              # Baujahr, kein Grundriss
        return ""
    if re.match(r"\s*(km|€|eur|ps|kw|tkm|tsd)\b", rest[m.end(1):], re.I):
        return ""
    return gr


def modell_aus_text(marke: str | None, titel: str, beschreibung: str = "", detail_modell: str | None = None) -> str | None:
    """Liefert z. B. „Sky TI 650 MEG“ (ohne Marke) oder None."""
    if detail_modell and not re.search(r"weitere|andere|sonstige|^\W*$", detail_modell, re.I):
        return detail_modell.strip()
    titel = titel or ""
    # 2. bekannte Modellreihe
    for quelle, min_laenge in ((titel, 1), ((beschreibung or "")[:600], 5)):
        for serie, mu in _MODELL_MUSTER.get(marke or "", []):
            # in der Beschreibung nur eindeutige Namen (nicht „Van“, „Free“, „Sport“ …)
            if len(serie) >= min_laenge and (m := mu.search(quelle)):
                gr = _grundriss(quelle[m.end():])
                return f"{serie} {gr}".strip() if not serie.endswith(gr) else serie
    # 3. Heuristik: Wörter hinter der Marke
    if not marke:
        return None
    treffer = [t for mu in [_muster(marke)] + [mu for z, mu in _ALIAS_MUSTER if z == marke] if (t := mu.search(titel))]
    if not treffer:
        return None
    m = min(treffer, key=lambda t: t.start())
    rest = _TRENNER.split(titel[m.end():], maxsplit=1)[0]
    woerter = []
    for w in rest.split():
        wl = w.lower().strip(".:-–")
        if (not wl or wl in FUELLWOERTER or re.fullmatch(r"(19|20)\d\d", wl) or re.search(r"\d\s*(km|€|ps|kw)", wl)
                or not re.search(r"\w", wl) or wl.endswith("km")):
            break
        woerter.append(w.strip(".:"))
        if len(woerter) == 4:
            break
    modell = " ".join(woerter).strip(" -–")
    return modell if len(modell) >= 2 else None


def art_schluessel(*quellen: str | None) -> str:
    """'Teilintegrierter', 'Integrierter', 'Alkoven', 'Kastenwagen', 'Wohnwagen' oder 'Sonstige'."""
    for q in quellen:
        ql = (q or "").lower()
        for begriff, schluessel in ART_SCHLUESSEL:
            if begriff in ql:
                return schluessel
    return "Sonstige"


def fahrzeug_bezeichnung(marke: str | None, modell: str | None) -> str:
    """Für Sätze wie „Ihr Inserat zum …“: 'Knaus Sky TI 650 MEG', 'Knaus-Wohnmobil' oder 'Wohnmobil'."""
    if marke and modell:
        return f"{marke} {modell}" if not modell.lower().startswith(marke.lower()) else modell
    if marke:
        return f"{marke}-Wohnmobil"
    return modell or "Wohnmobil"


def serie_aus_modell(marke: str | None, modell: str | None) -> str | None:
    """Modellreihe ohne Grundriss („Sky TI 650 MEG“ → „Sky TI“) – für genauere Vergleiche."""
    if not modell:
        return None
    for serie, mu in _MODELL_MUSTER.get(marke or "", []):
        if (m := mu.match(modell)) and m.start() == 0:
            return serie
    erstes = modell.split()[0]
    return None if erstes.isdigit() else erstes


def ergaenze_fahrzeug(a: dict) -> dict:
    """Setzt marke (normalisiert), modell, serie, fahrzeug („Knaus Sky TI 650 MEG“) und plz in einer Anzeige."""
    titel = a.get("titel") or ""
    text = " ".join(str(a.get(k) or "") for k in ("kurzbeschreibung", "beschreibung"))
    marke = normalisiere_marke(a.get("marke"))
    if not marke or ist_basismarke(marke) or marke.lower() in ("weitere marken", "andere", "sonstige"):
        marke = marke_aus_text(titel) or marke_aus_text(text) or (marke if ist_basismarke(marke) else None)
    try:
        details = json.loads(a.get("details_json") or "{}")
    except ValueError:
        details = {}
    modell = modell_aus_text(marke, titel, text, details.get("Modell"))
    a.update(marke=marke, modell=modell, serie=serie_aus_modell(marke, modell),
             fahrzeug=fahrzeug_bezeichnung(marke, modell), plz=plz_aus_text(a.get("ort")))
    return a
