"""Deal Intelligence (Phase E, ADR-028): Gewinn und Max-EK für einen konkreten Gebotsbetrag – nachrechenbar.

Baut auf dem Rechner auf (Marktwert bleibt eigenständiges Modul) und ergänzt:

* **Szenarien** aus der Marktspanne: vorsichtig (unteres Ende), erwartet (Schätzung), günstig (oberes Ende) – je Händler-VK,
  Kosten, Zielmarge, Max-EK und Gewinn beim Gebot. Ohne Spanne (Datenlage „keine“/„manuell“) nur „erwartet“.
* **Provision** (Prozent vom Zuschlag, ``config.yaml`` → ``kalkulation``) als Kosten; der Max-EK enthält sie bereits.
* **Gebotskorridor**: „sicher bis“ = Max-EK vorsichtig, „Obergrenze“ = Max-EK erwartet; Ampel für den Betrag.
* **Risikowert** 0–100 aus Datenlage, Spannbreite, Mängeln, Alter, Laufleistung und Gebotshöhe – jeder Punkt mit Grund.

Nachrechenbar: ``eingabe`` friert alles ein, wovon das Ergebnis abhängt (Fahrzeug in Rechner-Sicht ohne PLZ/Ort, die
tatsächlich passenden Vergleichsangebote, wirksame Rechner- und Kalkulationsparameter, Stichtag, Entfernung, Betrag).
``rechne(eingabe)`` ist eine reine Funktion: dieselbe Eingabe ergibt mit derselben ``VERSION`` dasselbe Ergebnis.
Keine Netz- und Datenbankzugriffe, keine quellenspezifische Logik.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .auswertung import _sicht_als, bewerte_anzeige, fuer_rechner, kandidaten_arten
from .rechner import STANDARD_AEHNLICHKEIT, STANDARD_MARKTMODELL, Rechner, _runde, privatangebot

VERSION = "E3"          # bei jeder Änderung an Formeln erhöhen – ältere Kalkulationen gelten dann als „andere Version“ (E2: P5-02, E3: P5-03)
SZENARIEN = {"vorsichtig": "unteres Ende der Marktspanne", "erwartet": "Schätzung des Marktniveaus",
             "guenstig": "oberes Ende der Marktspanne"}
FAHRZEUG_FELDER = ("id", "suche", "art", "titel", "marke", "modell", "serie", "ez_jahr", "km", "preis", "kurzbeschreibung",
                   "beschreibung", "getriebe", "gewerblich", "ausland", "entfernung_km")
VERGLEICH_FELDER = ("id", "suche", "art", "titel", "marke", "modell", "serie", "ez_jahr", "km", "preis", "kurzbeschreibung",
                    "beschreibung", "getriebe", "gewerblich", "zuletzt_gesehen")
SICHERHEIT_PUNKTE = {"hoch": 5, "mittel": 15, "niedrig": 30, "manuell": 20, "keine": 60}


def einstellungen(cfg: dict) -> dict:
    roh = cfg.get("kalkulation") or {}
    p = roh.get("provision_prozent", 0.02)
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p < 0.5:
        raise ValueError(f"config.yaml: kalkulation -> provision_prozent muss zwischen 0 und 0.5 liegen (0.02 = 2 %), nicht {p!r}")
    return {"provision_prozent": float(p)}


def _kanonisch(obj) -> dict:
    """JSON-Rundreise: genau die Form, in der die Eingabe gespeichert und später wieder gelesen wird."""
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def eingabe_hash(e: dict) -> str:
    return hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _rechner_cfg(cfg: dict) -> dict:
    """Wirksame Rechner-Parameter inkl. eingebauter Standardwerte – sonst hinge das Nachrechnen an späteren Code-Standards."""
    r = dict(cfg["rechner"])
    r["marktmodell"] = {**STANDARD_MARKTMODELL, **(r.get("marktmodell") or {})}
    r["vergleich_aehnlichkeit"] = {**STANDARD_AEHNLICHKEIT, **(r.get("vergleich_aehnlichkeit") or {})}
    r.setdefault("abschlag_marke_unbekannt", 0.05)
    return r


def _sichten(fahrzeug: dict) -> list[dict]:
    sicht = fuer_rechner(fahrzeug)
    return [_sicht_als(sicht, k) for k in kandidaten_arten(fahrzeug)] or [sicht]


def vergleich_auszug(rechner: Rechner, fahrzeug: dict, vergleich: list[dict]) -> list[dict]:
    """Nur die Vergleichsangebote, die der Rechner für dieses Fahrzeug überhaupt berücksichtigen kann (gleiche Art, EZ- und
    km-Toleranz, Privatangebot mit Preis) – dieselben Filter wie ``Rechner.vergleiche``, damit das Ergebnis mit dem Auszug
    exakt dem mit der ganzen Datenbank entspricht. Nur die Felder, die der Rechner liest."""
    if not fahrzeug.get("ez_jahr"):
        return []
    c = rechner.c
    jt, kt = c["vergleich_jahre_toleranz"], c["vergleich_km_toleranz"]
    arten = {rechner.art(s) for s in _sichten(fahrzeug)}
    aus = []
    for b in vergleich:
        if not b.get("preis") or b["preis"] < 1000 or not privatangebot(b) or not b.get("ez_jahr"):
            continue
        if abs(b["ez_jahr"] - fahrzeug["ez_jahr"]) > jt or rechner.art(b) not in arten:
            continue
        if fahrzeug.get("km") and b.get("km") and abs(b["km"] - fahrzeug["km"]) > kt:
            continue
        aus.append({k: b[k] for k in VERGLEICH_FELDER if b.get(k) is not None})
    return aus


def eingabe(cfg: dict, fahrzeug: dict, vergleich: list[dict], *, betrag: int | None, stichtag: datetime, abholung: str) -> dict:
    """Alles, wovon das Ergebnis abhängt – kanonisch (so, wie es gespeichert wird). ``fahrzeug`` in Rechner-Sicht mit
    ``entfernung_km``; ``stichtag`` lokale Zeit (wie die Zeitstempel der Vergleichsangebote); ``abholung`` nur Beschriftung."""
    rc = _rechner_cfg(cfg)
    rechner = Rechner({"rechner": rc}, stichtag)
    return _kanonisch({"version": VERSION, "stichtag": stichtag.isoformat(timespec="seconds"), "betrag": betrag,
                       "abholung": abholung, "rechner": rc, "kalkulation": einstellungen(cfg),
                       "fahrzeug": {k: fahrzeug.get(k) for k in FAHRZEUG_FELDER},
                       "vergleich": vergleich_auszug(rechner, fahrzeug, vergleich)})


def _gewinn(rechner: Rechner, vk: float, kosten: float, ek: float, p: float) -> float:
    return rechner.gewinn_bei_ek(vk, kosten + ek * p, ek)


def _max_ek(rechner: Rechner, vk: int, kosten: int, marge: int, p: float) -> int:
    """Höchster EK (volle 100 €, abgerundet), bei dem nach Kosten und Provision noch die Zielmarge bleibt."""
    unten, oben = 0, int(vk)
    if _gewinn(rechner, vk, kosten, 0, p) < marge:
        return 0
    while oben - unten > 1:                    # Gewinn fällt mit steigendem EK – Bisektion auf ganze Euro
        mitte = (unten + oben) // 2
        unten, oben = (mitte, oben) if _gewinn(rechner, vk, kosten, mitte, p) >= marge else (unten, mitte)
    return unten // 100 * 100


def rechne(e: dict) -> dict:
    """Reine Funktion der Eingabe. Beträge gerundet (Max-EK auf 100 €, Gewinne auf 50 €) – keine falsche Genauigkeit."""
    rechner = Rechner({"rechner": e["rechner"]}, datetime.fromisoformat(e["stichtag"]))
    a, vergleich, p, betrag = dict(e["fahrzeug"]), e["vergleich"], e["kalkulation"]["provision_prozent"], e["betrag"]
    b = bewerte_anzeige(rechner, a, vergleich)
    if b.sicherheit == "keine" or not b.haendler_vk:
        return {"version": VERSION, "moeglich": False, "grund": "Keine Kalkulation möglich: " + b.vergleich_basis}
    niveaus = {"erwartet": None}
    if b.spanne_von and b.spanne_bis:
        niveaus = {"vorsichtig": b.spanne_von, "erwartet": None, "guenstig": b.spanne_bis}
    szenarien = {}
    for name, niveau in niveaus.items():
        s = b if niveau is None else bewerte_anzeige(rechner, a, vergleich, marktwert_manuell=niveau)
        z = {"marktniveau": s.marktwert_angebote, "haendler_vk": s.haendler_vk, "kosten": s.kosten, "ziel_marge": s.ziel_marge,
             "max_ek": _max_ek(rechner, s.haendler_vk, s.kosten, s.ziel_marge, p)}
        if betrag:
            z["provision"] = _runde(betrag * p, 10)
            z["gewinn"] = _runde(_gewinn(rechner, s.haendler_vk, s.kosten, betrag, p))
        szenarien[name] = z
    sicher, ober = szenarien.get("vorsichtig", szenarien["erwartet"])["max_ek"], szenarien["erwartet"]["max_ek"]
    ampel = None
    if betrag:
        ampel = "gruen" if betrag <= sicher else "gelb" if betrag <= ober else "rot"
    return {"version": VERSION, "moeglich": True, "betrag": betrag, "szenarien": szenarien, "abschlag_marke": b.abschlag_marke,
            "korridor": {"sicher_bis": sicher, "obergrenze": ober}, "ampel": ampel,
            "sicherheit": b.sicherheit, "spanne": [b.spanne_von, b.spanne_bis] if b.spanne_von else None,
            "risiko": _risiko(b, a, betrag, sicher, ober), "annahmen": _annahmen(e, b), "vergleich_basis": b.vergleich_basis}


def _risiko(b, a: dict, betrag: int | None, sicher: int, ober: int) -> dict:
    gruende = [(SICHERHEIT_PUNKTE.get(b.sicherheit, 30), f"Datenlage {b.sicherheit}")]
    if b.spanne_von and b.marktwert_angebote:
        breite = (b.spanne_bis - b.spanne_von) / b.marktwert_angebote
        gruende.append((min(20, round(breite * 50)), f"Marktspanne ±{breite / 2:.0%}"))
    maengel = [n for n, w in b.wertfaktoren.items() if w < 0]
    if maengel:
        gruende.append((min(24, 8 * len(maengel)), "Mängel: " + ", ".join(maengel)))
    if b.alter is not None and b.alter > 10:
        gruende.append((10 if b.alter > 15 else 5, f"Alter {b.alter} Jahre"))
    if (a.get("km") or 0) > 100000:
        gruende.append((10 if a["km"] > 150000 else 5, _eur(a["km"]).replace("€", "km")))
    if betrag and betrag > ober:
        gruende.append((15, "Gebot über der Obergrenze (Max-EK erwartet)"))
    elif betrag and betrag > sicher:
        gruende.append((5, "Gebot über „sicher bis“"))
    punkte = min(100, sum(p for p, _ in gruende))
    return {"punkte": punkte, "stufe": "gering" if punkte < 25 else "mittel" if punkte < 50 else "hoch",
            "gruende": [{"punkte": p, "grund": g} for p, g in gruende if p]}


def _eur(x: int) -> str:
    return f"{x:,} €".replace(",", ".")


def _annahmen(e: dict, b) -> list[str]:
    r = e["rechner"]
    steuer = "§25a UStG (Differenzbesteuerung, 19/119 auf die Marge)" if r["differenzbesteuerung"] else "Regelbesteuerung (19 %)"
    return [f"Stichtag {e['stichtag']}, Rechenstand {VERSION}",
            f"Abholung: {e['abholung']}" + (f", {e['fahrzeug']['entfernung_km']} km" if e["fahrzeug"].get("entfernung_km") is not None
                                            else ", Entfernung unbekannt (Transportpauschale)"),
            f"Marktwert privat = Marktniveau − {r['abschlag_angebot_auf_privatwert']:.0%}; Händler-VK = privat + {r['aufschlag_haendler_vk']:.0%}"
            + (f", davon − {b.abschlag_marke:.0%} für unbekannte Marke" if b.abschlag_marke else ""),
            "Kosten (erwartet): " + ", ".join(f"{n} {_eur(v)}" for n, v in b.kosten_posten.items()),
            f"Zielmarge {r['ziel_marge_prozent']:.0%} vom Händler-VK, mindestens {_eur(r['ziel_marge_min'])}",
            f"Provision {e['kalkulation']['provision_prozent']:.1%} vom Zuschlag (als Kosten, im Max-EK enthalten)",
            f"Steuer: {steuer} – fachliche Annahme, keine Steuerberatung",
            f"Vergleichsbasis: {b.vergleich_basis} ({len(e['vergleich'])} Angebote im Auszug)"]
