"""Entfernungen zwischen deutschen Postleitzahlen.

Koordinaten: PLZ-Mittelpunkte aus GeoNames (www.geonames.org), Lizenz CC BY 4.0 – siehe plz_de.csv.
Die Luftlinie wird mit einem Straßenfaktor auf eine typische Fahrstrecke hochgerechnet.
Orte im Ausland („SE-123 45 Ort“, „FR-75001 Paris“) haben keine deutsche PLZ: `plz_aus_text` liefert dafür nichts, `auslands_kuerzel` das Land.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

PLZ_DATEI = Path(__file__).with_name("plz_de.csv")
STRASSENFAKTOR = 1.25          # Fahrstrecke ≈ Luftlinie × 1,25 (Durchschnitt in Deutschland)
_koordinaten: dict[str, tuple[float, float]] | None = None
_mittel: dict[str, tuple[float, float]] | None = None          # Mittel je 3- und 2-stelligem Präfix (einmal berechnet, nicht je Abfrage)
INLAND = {"D", "DE", "DEU", "GER", "BRD"}
_LAENDERKUERZEL = re.compile(r"^\s*([A-Z]{1,3})\s*-\s*\d")        # „SE-123 45 Ort“, „NL-1234AB Ort“, „FR-75001 Paris“


def _lade() -> dict[str, tuple[float, float]]:
    global _koordinaten
    if _koordinaten is None:
        _koordinaten = {}
        for zeile in PLZ_DATEI.read_text(encoding="utf-8").splitlines():
            teile = zeile.split(",")
            if len(teile) == 3 and teile[0].isdigit():
                _koordinaten[teile[0]] = (float(teile[1]), float(teile[2]))
    return _koordinaten


def _lade_mittel() -> dict[str, tuple[float, float]]:
    global _mittel
    if _mittel is None:
        gruppen: dict[str, list[tuple[float, float]]] = {}
        for p, k in _lade().items():
            for stellen in (3, 2):
                gruppen.setdefault(p[:stellen], []).append(k)
        _mittel = {pre: (sum(k[0] for k in ks) / len(ks), sum(k[1] for k in ks) / len(ks)) for pre, ks in gruppen.items()}
    return _mittel


def auslands_kuerzel(text: str | None) -> str | None:
    """Länderkürzel vor der PLZ eines ausländischen Ortes („FR-75001 Paris“ → „FR“); None für deutsche Orte („D-70191 Stuttgart“,
    „70173 Stuttgart“) und Texte ohne Kürzel."""
    m = _LAENDERKUERZEL.match(text or "")
    return m.group(1) if m and m.group(1) not in INLAND else None


def plz_aus_text(text: str | None) -> str | None:
    """Deutsche PLZ (5 Ziffern) aus einem Ortstext; für Orte mit fremdem Länderkürzel None – eine fünfstellige Nummer dort ist keine
    deutsche PLZ (falsche Entfernung)."""
    if auslands_kuerzel(text):
        return None
    m = re.search(r"(?<!\d)(\d{5})(?!\d)", text or "")
    return m.group(1) if m else None


def plz_bekannt(plz: str | None) -> bool:
    """Liegt die PLZ exakt in der Tabelle vor (sonst ist ``koordinaten`` nur ein Näherungswert)?"""
    return bool(plz) and plz in _lade()


def plz_bereich_bekannt(praefix: str) -> bool:
    """Gibt es deutsche PLZ, die mit ``praefix`` (1 oder 2 Ziffern, z. B. „7“ oder „80“) beginnen?"""
    return bool(re.fullmatch(r"[0-9]{1,2}", praefix or "")) and any(p.startswith(praefix) for p in _lade_mittel())


def koordinaten(plz: str | None) -> tuple[float, float] | None:
    """Exakte PLZ, sonst Mittel der PLZ mit gleichen ersten drei bzw. zwei Ziffern (``plz_bekannt`` sagt, ob die PLZ exakt vorliegt).
    Ab zwei Stellen ergebnisgleich zur früheren Suche über die ganze Tabelle; eine einstellige PLZ liefert None (zu ungenau)."""
    if not plz:
        return None
    daten = _lade()
    if plz in daten:
        return daten[plz]
    mittel = _lade_mittel()
    return mittel.get(plz[:3]) or mittel.get(plz[:2])


def entfernung_km(plz_a: str | None, plz_b: str | None) -> int | None:
    """Geschätzte Fahrstrecke in km (oder None, wenn eine PLZ unbekannt ist)."""
    a, b = koordinaten(plz_a), koordinaten(plz_b)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)) * STRASSENFAKTOR)
