"""Datenqualität (P3-08, ADR-046): Markierungen für fehlende, unplausible und widersprüchliche Angaben und ein Qualitätswert 0–100 je Fahrzeug.

Ohne Netz- und Datenbankzugriff, beim Lesen berechnet (nichts gespeichert – geänderte Regeln wirken sofort, nichts veraltet). Die Markierungen
ändern keine Bewertung, keine Ampel und keine Sperre; sie zeigen, wie belastbar die Angaben sind. Je Fahrzeug zählt eine Angabe als vorhanden,
wenn irgendein Inserat desselben Fahrzeugs sie hat; Widersprüche zwischen den Inseraten (km-Rückgang, abweichende Erstzulassung) kommen hinzu.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..domaene import UNBEKANNT, VORLAEUFIG, import_art
from .fahrzeug import ist_basismarke, marke_aus_text, normalisiere_marke

FEHLT, UNPLAUSIBEL, WIDERSPRUCH = "fehlt", "unplausibel", "widerspruch"
# Abzug vom Qualitätswert je Markierung; Widersprüche und Unplausibles wiegen wie eine fehlende Kernangabe
ABZUG = {"preis_fehlt": 25, "ez_fehlt": 25, "km_fehlt": 15, "ort_fehlt": 10, "marke_fehlt": 10, "art_unbekannt": 10, "art_vorlaeufig": 5,
         "anbieter_unbekannt": 5}
ABZUG_SONST = 20
GUT, MITTEL, SCHWACH = "gut", "mittel", "schwach"

PREIS_MIN, PREIS_MAX = 1000, 750_000                      # oben: auch gebrauchte Luxus-Liner liegen darunter
EZ_MIN = 1960
KM_MAX, KM_PRO_JAHR_MAX, KM_RUECKGANG_TOLERANZ = 1_000_000, 60_000, 1000

_BAUJAHR = re.compile(r"\b(?:Baujahr|Bj\.?)\s*:?\s*((?:19|20)\d{2})\b", re.I)
_MONAT = r"(?:Jan(?:uar)?|Feb(?:ruar)?|März|Mär|Apr(?:il)?|Mai|Juni?|Juli?|Aug(?:ust)?|Sep(?:tember)?|Okt(?:ober)?|Nov(?:ember)?|Dez(?:ember)?)\.?"
# „EZ 03/2019“, „Erstzulassung: Juli 2021“, „EZ 15.03.2017“, „EZ ca. 2015“ – kein beliebiges Wort dazwischen („Erstzulassung Basisfahrzeug 2017“)
_EZ_TEXT = re.compile(rf"\b(?:EZ|Erstzulassung)\s*:?\s*(?:ca\.?\s*|{_MONAT}\s+|\d{{1,2}}[/.](?:\d{{1,2}}[/.])?)?((?:19|20)\d{{2}})\b", re.I)
_KM_TEXT = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*km\b", re.I)


def _m(code: str, art: str, text: str) -> dict:
    return {"code": code, "art": art, "text": text}


def _tsd(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _ganzzahl(wert) -> int | None:
    """Ganze Zahl oder None (bool, Kommazahlen mit Nachkommastellen und andere Texte gelten als nicht angegeben)."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, int):
        return wert
    if isinstance(wert, float) and wert.is_integer():
        return int(wert)
    if isinstance(wert, str) and wert.strip().isdigit():
        return int(wert.strip())
    return None


def pruefe_inserat(a: dict, jetzt: datetime) -> list[dict]:
    """Markierungen eines Inserats (Dict mit den Spalten von ``anzeigen``, nach ``ergaenze_fahrzeug``: ``marke``, ``plz``, ``ausland``)."""
    erg = []
    preis, ez, km = _ganzzahl(a.get("preis")), _ganzzahl(a.get("ez_jahr")), _ganzzahl(a.get("km"))
    # --- fehlt
    if preis is None:
        erg.append(_m("preis_fehlt", FEHLT, "Preis fehlt"))
    if ez is None:
        erg.append(_m("ez_fehlt", FEHLT, "Erstzulassung fehlt – keine belastbare Bewertung"))
    if km is None:
        erg.append(_m("km_fehlt", FEHLT, "Kilometerstand fehlt"))
    if not a.get("plz") and not a.get("ausland"):
        erg.append(_m("ort_fehlt", FEHLT, "PLZ/Ort fehlt – keine Entfernung"))
    if not a.get("marke"):
        erg.append(_m("marke_fehlt", FEHLT, "Marke nicht erkannt"))
    herkunft = import_art(a.get("suche"))[1]
    if herkunft == UNBEKANNT:
        erg.append(_m("art_unbekannt", FEHLT, "Fahrzeugart unbekannt"))
    elif herkunft == VORLAEUFIG:
        erg.append(_m("art_vorlaeufig", FEHLT, "Fahrzeugart nur aus dem Titel (vorläufig)"))
    if "gewerblich" in a and a["gewerblich"] is None:
        erg.append(_m("anbieter_unbekannt", FEHLT, "Anbieter (privat/gewerblich) unbekannt"))
    # --- unplausibel
    if preis is not None and preis < PREIS_MIN:
        erg.append(_m("preis_platzhalter", UNPLAUSIBEL, f"Preis {_tsd(preis)} € – vermutlich Platzhalter oder Tippfehler"))
    elif preis is not None and preis > PREIS_MAX:
        erg.append(_m("preis_hoch", UNPLAUSIBEL, f"Preis {_tsd(preis)} € – unplausibel hoch"))
    if ez is not None and ez > jetzt.year:
        erg.append(_m("ez_zukunft", UNPLAUSIBEL, f"Erstzulassung {ez} liegt in der Zukunft"))
    elif ez is not None and ez < EZ_MIN:
        erg.append(_m("ez_alt", UNPLAUSIBEL, f"Erstzulassung {ez} – unplausibel alt"))
    if km is not None:
        alter = max(1, jetzt.year - ez) if ez is not None and EZ_MIN <= ez <= jetzt.year else None
        if km > KM_MAX:
            erg.append(_m("km_hoch", UNPLAUSIBEL, f"{_tsd(km)} km – unplausibel hoch"))
        elif alter and km > KM_PRO_JAHR_MAX * alter:
            erg.append(_m("km_hoch", UNPLAUSIBEL, f"{_tsd(km)} km bei {alter} Jahren – Tippfehler?"))
        elif alter and alter >= 3 and km < 1000:
            erg.append(_m("km_niedrig", UNPLAUSIBEL, f"nur {_tsd(km)} km bei {alter} Jahren – evtl. in Tausend angegeben"))
    # --- Widersprüche im Inserat
    text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung"))
    if ez is not None:
        baujahre = {int(j) for j in _BAUJAHR.findall(text)}
        if baujahre and max(baujahre) > ez + 1:                       # ein Jahr Abstand ist oft das Modelljahr, kein Widerspruch
            erg.append(_m("ez_vor_baujahr", WIDERSPRUCH, f"Erstzulassung {ez} vor dem genannten Baujahr {max(baujahre)}"))
        ez_text = {int(j) for j in _EZ_TEXT.findall(text)} - {ez}
        if ez_text:
            erg.append(_m("ez_text", WIDERSPRUCH, f"Text nennt Erstzulassung {min(ez_text)}, Angabe {ez}"))
    if km is not None:
        # nur der Titel: in Beschreibungen stehen oft andere Strecken („5.000 km seit Inspektion“, „Reichweite 1500 km“)
        km_text = [int(k.replace(".", "")) for k in _KM_TEXT.findall(str(a.get("titel") or ""))]
        abweichend = [k for k in km_text if abs(k - km) > max(5000, km * 0.1)]
        if km_text and len(abweichend) == len(km_text):
            erg.append(_m("km_text", WIDERSPRUCH, f"Text nennt {_tsd(abweichend[0])} km, Angabe {_tsd(km)} km"))
    titel_marke, marke = normalisiere_marke(marke_aus_text(a.get("titel") or "")), normalisiere_marke(a.get("marke"))
    if titel_marke and marke and not ist_basismarke(titel_marke) and not ist_basismarke(marke) and titel_marke.lower() != marke.lower():
        erg.append(_m("marke_titel", WIDERSPRUCH, f"Titel nennt {titel_marke}, Angabe {marke}"))
    return erg


def pruefe_fahrzeug(a: dict, andere: list[dict], jetzt: datetime, eigene: list[dict] | None = None, vorab=None) -> dict:
    """Qualität des Fahrzeugs hinter ``a`` (``andere`` = übrige Inserate desselben Fahrzeugs): ``wert`` 0–100, ``stufe`` und ``markierungen``.
    Eine fehlende Angabe zählt nicht, wenn ein anderes Inserat sie hat; dazu Widersprüche zwischen den Inseraten. ``eigene``: schon berechnete
    ``pruefe_inserat(a)``; ``vorab(b)``: liefert ``pruefe_inserat(b)`` aus einem Zwischenspeicher (sonst wird je Aufruf neu gerechnet)."""
    eigene = list(pruefe_inserat(a, jetzt) if eigene is None else eigene)
    if andere:
        markierungen = vorab or (lambda b: pruefe_inserat(b, jetzt))
        vorhanden = {m["code"] for m in eigene if m["art"] == FEHLT} - set.intersection(
            *({m["code"] for m in markierungen(b) if m["art"] == FEHLT} for b in andere))
        eigene = [m for m in eigene if m["code"] not in vorhanden]
        km, erst = _ganzzahl(a.get("km")), a.get("erstmals_gesehen") or ""
        frueher = [b for b in andere if _ganzzahl(b.get("km")) is not None and b.get("erstmals_gesehen") and erst and b["erstmals_gesehen"] < erst]
        if km is not None and frueher:
            hoechst = max(frueher, key=lambda b: _ganzzahl(b.get("km")))
            if _ganzzahl(hoechst["km"]) - km > KM_RUECKGANG_TOLERANZ:
                eigene.append(_m("km_rueckgang", WIDERSPRUCH, f"Kilometerstand {_tsd(km)} km niedriger als in der älteren Anzeige {hoechst['id']} "
                                                            f"({_tsd(_ganzzahl(hoechst['km']))} km)"))
        jahre = {j for j in (_ganzzahl(x.get("ez_jahr")) for x in [a, *andere]) if j is not None}
        if len(jahre) > 1:
            eigene.append(_m("ez_abweichend", WIDERSPRUCH,
                             f"Inserate desselben Fahrzeugs nennen verschiedene Erstzulassungen ({', '.join(map(str, sorted(jahre)))})"))
    wert = max(0, 100 - sum(ABZUG.get(m["code"], ABZUG_SONST) for m in eigene))
    return {"wert": wert, "stufe": GUT if wert >= 80 else MITTEL if wert >= 50 else SCHWACH, "markierungen": eigene,
            "widersprueche": sum(m["art"] != FEHLT for m in eigene)}


def je_quelle(zeilen: list[dict]) -> list[dict]:
    """Datenqualität je Quelle über bewertete Zeilen (``a`` mit ``datenqualitaet`` und ``datenqualitaet_inserat``, P2-10): Anzahl, Anteil der Inserate
    mit Preis/EZ/km/Ort/bekanntem Anbieter (je Inserat, nicht je Fahrzeug), mittlerer Qualitätswert und Zahl der Fahrzeuge mit Widerspruch oder
    unplausibler Angabe."""
    gruppen: dict[str, list[dict]] = {}
    for z in zeilen:
        gruppen.setdefault(z["a"].get("quelle") or "kleinanzeigen", []).append(z["a"])
    erg = []
    for quelle, liste in sorted(gruppen.items()):
        n = len(liste)

        def anteil(code: str, liste=liste, n=n) -> float:
            return round(sum(code not in {m["code"] for m in a.get("datenqualitaet_inserat") or ()} for a in liste) / n, 3)
        erg.append({"quelle": quelle, "anzahl": n, "preis": anteil("preis_fehlt"), "ez": anteil("ez_fehlt"), "km": anteil("km_fehlt"),
                    "ort": anteil("ort_fehlt"), "anbieter_bekannt": anteil("anbieter_unbekannt"),
                    "mittel": round(sum(a["datenqualitaet"]["wert"] for a in liste) / n, 1),
                    "mit_widerspruch": sum(bool(a["datenqualitaet"]["widersprueche"]) for a in liste)})
    return erg
