"""Gleiches Fahrzeug? Vergleich zweier Inserate nach nachvollziehbaren Regeln (P3-02a, ohne Datenbank und Netz).

Das Ergebnis ist ein VORSCHLAG mit Stufe („hoch“/„mittel“/``None``) und kurzen Gründen – keine Wahrscheinlichkeit. Zusammengeführt
wird nie automatisch (ADR-039). Verglichen werden nur Fahrzeugmerkmale; Verkäufername, Telefon und FIN gehören bewusst nicht dazu.
Die Zeilen sind Dicts wie in ``bewertung.auswertung.finde_duplikate`` (nach ``ergaenze_fahrzeug``: marke, serie, plz).

Stufen:
  hoch    Marke, Erstzulassung, Modellreihe (beide bekannt), PLZ gleich; km im Rahmen; Titel ähnlich ODER Preis nah beieinander
  mittel  heutiges Kriterium von ``finde_duplikate`` (Marke, EZ, PLZ gleich; km im Rahmen; Modellreihe nicht widersprüchlich)
          ODER wie „hoch“, aber PLZ verschieden und höchstens ``MAX_ENTFERNUNG_KM`` auseinander
  None    sonst; bei einem Widerspruch (andere Marke, EZ-Abstand > 1, verschiedene Modellreihe, abweichende Modellnummer im Titel,
          bekannt verschiedene Fahrzeugart, km-Rückgang) stehen sie in ``widersprueche``
Waren beide Inserate lange gleichzeitig online, ist höchstens „mittel“ möglich (ein Händler kann mehrere gleiche Modelle anbieten).
Regel 2: Modellnummer-/Art-Widerspruch und Gleichzeitigkeit (B1/B3 der QA); ``finde_duplikate`` ignoriert beides, ein Paar daraus ist
deshalb mindestens „mittel“, AUSSER es hat einen Modellnummer- oder Art-Widerspruch.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from functools import lru_cache

from .fahrzeug import art_schluessel
from .geo import entfernung_km, plz_bekannt

REGEL_VERSION = 2
KM_RAHMEN = 3000               # wie finde_duplikate; ein Rückgang darüber widerspricht (Tacho zurück = anderes Fahrzeug)
MAX_ENTFERNUNG_KM = 30
PREIS_ANTEIL = 0.15
TITEL_AEHNLICH = 0.8
GLEICHZEITIG_TAGE = 1          # so lange beide Inserate zugleich online waren, gelten sie höchstens als „mittel“
MAX_PAARE_JE_BLOCK = 2000      # Obergrenze geprüfter Paare je Block (Worst Case: tausende gleiche Fahrzeuge)


@dataclass(frozen=True)
class Vergleich:
    konfidenz: str | None                       # 'hoch' | 'mittel' | None
    gruende: list[str] = field(default_factory=list)
    widersprueche: list[str] = field(default_factory=list)


def _marke(z: dict) -> str:
    return (z.get("marke") or "").lower()


def _titel_norm(titel: str | None) -> str:
    return " ".join(re.findall(r"\w+", (titel or "").lower()))


_PREIS = re.compile(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\s*(?:€|eur\b|euro\b|km\b|tkm\b|tsd\b|ps\b|kw\b|kg\b|ccm\b|cm\b|l\b|liter\b|vb\b|vhb\b|,-)"
                    r"|\b(?:preis|vb|vhb|fp|nur|für|fuer)\s*:?\s*\d+", re.I)
_NUMMER = re.compile(r"(?<![\d,.])(\d{3,4})(?![\d])")


@lru_cache(maxsize=100_000)
def modellnummern(titel: str | None) -> frozenset[str]:
    """3–4-stellige Zahlen im Titel, die wie Modell-/Grundrissnummern aussehen („Sky TI 650 MEG“, „Summit 600“) – ohne Jahreszahlen
    (1950–2039), Preise („39.900“, „35000 €“) und Angaben mit Einheit („90000 km“, „140 PS“). PLZ (5-stellig) zählen nie."""
    text = _PREIS.sub(" ", titel or "")
    return frozenset(n for n in _NUMMER.findall(text) if not (len(n) == 4 and 1950 <= int(n) <= 2039))


def titel_aehnlich(a: str | None, b: str | None) -> bool:
    x, y = _titel_norm(a), _titel_norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    s = SequenceMatcher(None, x, y, autojunk=False)
    return s.real_quick_ratio() >= TITEL_AEHNLICH and s.quick_ratio() >= TITEL_AEHNLICH and s.ratio() >= TITEL_AEHNLICH


def preis_nah(a: dict, b: dict) -> bool:
    """Beide Preise bekannt (1 € ist ein Platzhalter, kein Preis) und höchstens 15 % auseinander."""
    pa, pb = a.get("preis"), b.get("preis")
    if not pa or not pb or pa <= 1 or pb <= 1:
        return False
    return abs(pa - pb) <= PREIS_ANTEIL * max(pa, pb)


def _juenger(a: dict, b: dict) -> tuple[dict, dict] | None:
    """(älteres, jüngeres) Inserat nach erstmals_gesehen; ``None`` ohne verwertbare Zeitpunkte oder bei Gleichstand."""
    ea, eb = a.get("erstmals_gesehen") or "", b.get("erstmals_gesehen") or ""
    if not ea or not eb or ea == eb:
        return None
    return (a, b) if ea < eb else (b, a)


def _online(z: dict) -> tuple[datetime, datetime] | None:
    try:
        return datetime.fromisoformat(z["erstmals_gesehen"]), datetime.fromisoformat(z["zuletzt_gesehen"])
    except (KeyError, TypeError, ValueError):
        return None


def gleichzeitig_online(a: dict, b: dict) -> bool:
    """Beide Inserate waren länger als ``GLEICHZEITIG_TAGE`` Tag(e) zugleich online (erstmals_gesehen … zuletzt_gesehen)."""
    oa, ob = _online(a), _online(b)
    if not oa or not ob:
        return False
    try:
        ueberlappung = min(oa[1], ob[1]) - max(oa[0], ob[0])
    except TypeError:                       # gemischte Zeitzonen
        return False
    return ueberlappung.total_seconds() > GLEICHZEITIG_TAGE * 86400


def _widersprueche(a: dict, b: dict) -> list[str]:
    w = []
    if _marke(a) and _marke(b) and _marke(a) != _marke(b):
        w.append(f"andere Marke ({a['marke']} / {b['marke']})")
    if a.get("ez_jahr") and b.get("ez_jahr") and abs(a["ez_jahr"] - b["ez_jahr"]) > 1:
        w.append(f"Erstzulassung weicht ab ({a['ez_jahr']} / {b['ez_jahr']})")
    if a.get("serie") and b.get("serie") and a["serie"] != b["serie"]:
        w.append(f"andere Modellreihe ({a['serie']} / {b['serie']})")
    na, nb = modellnummern(a.get("titel")), modellnummern(b.get("titel"))
    if na and nb and na.isdisjoint(nb):
        w.append(f"abweichende Modellnummer ({'/'.join(sorted(na))} / {'/'.join(sorted(nb))})")
    if a.get("art") and b.get("art") and "Sonstige" not in (art_schluessel(a["art"]), art_schluessel(b["art"])) \
            and art_schluessel(a["art"]) != art_schluessel(b["art"]):
        w.append(f"andere Fahrzeugart ({a['art']} / {b['art']})")
    if a.get("km") and b.get("km") and (reihe := _juenger(a, b)) and reihe[1]["km"] < reihe[0]["km"] - KM_RAHMEN:
        w.append(f"Kilometerstand beim jüngeren Inserat deutlich niedriger ({reihe[0]['km']:,} → {reihe[1]['km']:,} km)".replace(",", "."))
    return w


def vergleiche(a: dict, b: dict) -> Vergleich:
    """Vergleicht zwei Zeilen (siehe Modulkopf). Symmetrisch bis auf die Reihenfolge der Gründe."""
    widersprueche = _widersprueche(a, b)
    if widersprueche:
        return Vergleich(None, [], widersprueche)
    # Voraussetzungen des heutigen Kriteriums: alle vier Angaben auf beiden Seiten, Marke und EZ gleich, km im Rahmen
    if not all(z.get(k) for z in (a, b) for k in ("marke", "ez_jahr", "km", "plz")):
        return Vergleich(None)
    if _marke(a) != _marke(b) or a["ez_jahr"] != b["ez_jahr"] or abs(a["km"] - b["km"]) > KM_RAHMEN:
        return Vergleich(None)
    gruende = [f"gleiche Marke ({a['marke']})", f"gleiche Erstzulassung ({a['ez_jahr']})",
               f"Kilometerstand im Rahmen ({a['km']:,} / {b['km']:,} km)".replace(",", ".")]
    reihe_bekannt = bool(a.get("serie")) and bool(b.get("serie"))      # (verschiedene Reihen sind oben schon ausgeschieden)
    if reihe_bekannt:
        gruende.append(f"gleiche Modellreihe ({a['serie']})")
    ergaenzung = []
    if preis_nah(a, b):
        ergaenzung.append("Preis nah beieinander")
    elif reihe_bekannt and titel_aehnlich(a.get("titel"), b.get("titel")):      # teuer: nur, wenn sie die Stufe noch ändern kann
        ergaenzung.append("Titel ähnlich")
    stark = reihe_bekannt and bool(ergaenzung)
    gleichzeitig = ["beide gleichzeitig online"] if gleichzeitig_online(a, b) else []
    if a["plz"] == b["plz"]:
        stufe = "hoch" if stark and not gleichzeitig else "mittel"
        return Vergleich(stufe, [*gruende, f"gleiche PLZ ({a['plz']})", *ergaenzung, *gleichzeitig])
    if stark:
        d = entfernung_km(a["plz"], b["plz"])
        if d is not None and d <= MAX_ENTFERNUNG_KM:
            genau = plz_bekannt(a["plz"]) and plz_bekannt(b["plz"])
            ort = (f"PLZ {a['plz']} / {b['plz']} höchstens {MAX_ENTFERNUNG_KM} km auseinander" if genau else
                   f"PLZ {a['plz']} / {b['plz']} ungefähr höchstens {MAX_ENTFERNUNG_KM} km auseinander (Lage geschätzt)")
            return Vergleich("mittel", [*gruende, ort, *ergaenzung, *gleichzeitig])
    return Vergleich(None)


def bloecke(zeilen: list[dict]) -> list[list[dict]]:
    """Blöcke für den paarweisen Vergleich: je Marke und Erstzulassung E alle Zeilen mit EZ E oder E+1 (nur Zeilen mit Marke, EZ,
    km und PLZ – ohne diese Angaben kann ``vergleiche`` nichts vorschlagen). Benachbarte Blöcke überlappen; ``kandidatenpaare``
    vermeidet doppelte Paare. So wächst der Aufwand nicht quadratisch mit allen Inseraten."""
    je_marke: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for z in zeilen:
        if z.get("marke") and z.get("ez_jahr") and z.get("km") and z.get("plz"):
            je_marke[_marke(z)][z["ez_jahr"]].append(z)
    ergebnis = []
    for jahre in je_marke.values():
        for e in sorted(jahre):
            ergebnis.append(jahre[e] + jahre.get(e + 1, []))
    return ergebnis


def kandidatenpaare(zeilen: list[dict], max_je_block: int = MAX_PAARE_JE_BLOCK, gekuerzt: list[str] | None = None) -> Iterator[tuple[dict, dict]]:
    """Jedes Paar höchstens einmal, nur innerhalb der Blöcke und nur mit km-Abstand bis ``KM_RAHMEN`` (Zeilen nach km sortiert,
    gleitendes Fenster). Zeilen mit gleicher ``id`` werden nicht mit sich selbst gepaart.

    Je Block werden höchstens ``max_je_block`` Paare im km-Fenster betrachtet (sonst wächst der Aufwand bei tausenden gleichen
    Fahrzeugen quadratisch); ein gekürzter Block steht als „Marke EZ“ in ``gekuerzt`` – dort wurde NICHT vollständig geprüft."""
    for block in bloecke(zeilen):
        e0 = min(z["ez_jahr"] for z in block)
        sortiert = sorted(block, key=lambda z: z["km"])
        betrachtet, voll = 0, False
        for i, a in enumerate(sortiert):
            for b in sortiert[i + 1:]:
                if b["km"] - a["km"] > KM_RAHMEN:
                    break
                betrachtet += 1
                if betrachtet > max_je_block:
                    voll = True
                    break
                # Paar (E, E) liegt in zwei Blöcken (E und E-1): nur im Block ausgeben, dessen Basisjahr es ist
                if min(a["ez_jahr"], b["ez_jahr"]) == e0 and a is not b and a.get("id") != b.get("id"):
                    yield a, b
            if voll:
                if gekuerzt is not None:
                    gekuerzt.append(f"{sortiert[0]['marke']} {e0}")
                break
