"""Besichtigung: Mängel und Messwerte → nachvollziehbarer Abzug und Endpreis-Vorschlag.

Verbindliche Rechnung (der Server rechnet immer nach). Die Handy-App rechnet offline mit derselben Logik
in JavaScript (wmscout/web/static/besichtigung.js); tests/test_besichtigung.py prüft, dass beide gleich rechnen.

  Summe Mängel   = Feuchtigkeit (je Bereich höchster Wert → Stufe → Kosten)
                 + Reifen älter als max_alter_jahre (je Reifen)
                 + Mehr-km gegenüber der Anzeige (Wertminderung)
                 + erfasste Mängel (Stufe, fester Betrag, Prozent vom Marktwert oder frei eingegeben)
  Gutschrift     = min(Summe Mängel, Reparaturrisiko-Pauschale × risiko_anrechnung)
  Netto-Abzug    = Summe Mängel − Gutschrift + manuelle Anpassung
  Abzug vom EK   = Netto-Abzug × 1,19 (§25a: Marge bleibt gleich) bzw. × 1,0
  Max-EK neu     = Max-EK − Abzug vom EK
  Vorschlag      = min(Angebot − Abzug vom EK, Max-EK neu), abgerundet, nie unter 0
"""
from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path

import yaml

STUFEN = ("leicht", "mittel", "schwer")


def lade_katalog(pfad: Path) -> dict:
    with open(pfad, encoding="utf-8") as f:
        return yaml.safe_load(f)


def mangel_index(katalog: dict) -> dict:
    return {m["key"]: {**m, "kategorie": k["name"]} for k in katalog["kategorien"] for m in k["maengel"]}


def _runde(x: float, auf: int = 10) -> int:
    """Kaufmännisch auf `auf` runden (wie Math.round in JS – .5 immer aufwärts)."""
    return int(math.floor(x / auf + 0.5) * auf)


def _zahl(x: float) -> str:
    """8.5 → „8,5“, 24.0 → „24“ (gleiche Darstellung wie in der App)."""
    return f"{x:g}".replace(".", ",")


def _als_zahl(wert) -> float | None:
    """Zahl aus Eingabe („17“, 17.5, „17,5“) oder None, wenn leer/ungültig."""
    if wert is None or isinstance(wert, bool) or str(wert).strip() == "":
        return None
    try:
        x = float(str(wert).replace(",", "."))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def dot_alter_jahre(dot: str, heute: date) -> float | None:
    """DOT „2318“ = 23. KW 2018 → Alter in Jahren (eine Nachkommastelle) oder None, wenn unlesbar."""
    m = re.fullmatch(r"\s*(\d{2})(\d{2})\s*", str(dot or ""))
    if not m:
        return None
    woche, jahr = int(m.group(1)), 2000 + int(m.group(2))
    if not 1 <= woche <= 53 or jahr > heute.year:
        return None
    tage = (heute - date.fromisocalendar(jahr, min(woche, 52), 1)).days
    return math.floor(max(0, tage) / 365.25 * 10 + 0.5) / 10


def feuchte_stufe(wert: float, stufen: list[dict]) -> str:
    for s in stufen:
        if wert <= s["bis"]:
            return s["stufe"]
    return stufen[-1]["stufe"]


def berechne(katalog: dict, daten: dict, basis: dict, heute: date | None = None) -> dict:
    """daten: Eingaben der Besichtigung · basis: Werte aus der Bewertung des Inserats."""
    heute = heute or date.today()
    g, mess = katalog["grundsaetze"], katalog["messungen"]
    index = mangel_index(katalog)
    posten: list[dict] = []
    hinweise: list[str] = []
    ko: list[str] = []
    marktwert = basis.get("marktwert_privat") or 0
    messungen = daten.get("messungen") or {}

    # --- Feuchtigkeit: höchster Wert je Bereich ---
    fm = mess["feuchtigkeit"]
    bereiche: dict[str, float] = {}
    punkte = []
    for p in messungen.get("feuchtigkeit") or []:
        wert = _als_zahl(p.get("wert"))
        if wert is None:
            if str(p.get("wert") or "").strip():
                hinweise.append(f"Messwert „{p.get('wert')}“ ungültig – ignoriert")
            continue
        punkte.append(p)
        name = str(p.get("bereich") or "").strip() or "ohne Bereich"
        bereiche[name] = max(bereiche.get(name, 0.0), wert)
    for name in sorted(bereiche):
        stufe = feuchte_stufe(bereiche[name], fm["stufen"])
        if stufe != "ok":
            posten.append({"quelle": "messung", "name": f"Feuchtigkeit {name} ({_zahl(bereiche[name])} %)", "stufe": stufe,
                           "betrag": _runde(fm["kosten_je_bereich"][stufe])})

    # --- Reifen ---
    rm = mess["reifen"]
    reifen = [r for r in messungen.get("reifen") or [] if str(r.get("dot") or "").strip()]
    for r in reifen:
        alter = dot_alter_jahre(r["dot"], heute)
        pos = str(r.get("position") or "").strip() or "Reifen"
        if alter is None:
            hinweise.append(f"DOT „{r['dot']}“ ({pos}) nicht lesbar – vierstellig eingeben, z. B. 2318")
        elif alter > rm["max_alter_jahre"]:
            posten.append({"quelle": "messung", "name": f"Reifen {pos} {_zahl(alter)} Jahre alt", "stufe": None,
                           "betrag": _runde(rm["kosten_je_reifen"])})

    # --- km-Stand ---
    km = mess["km"]
    abgelesen, inseriert = _als_zahl(daten.get("km_abgelesen")), _als_zahl(basis.get("km_anzeige"))
    if abgelesen and inseriert:
        mehr = int(abgelesen - inseriert)
        if mehr > km["toleranz_km"]:
            posten.append({"quelle": "messung", "name": f"{mehr:,} km mehr als in der Anzeige".replace(",", "."),
                           "stufe": None, "betrag": _runde(marktwert * km["prozent_je_10000_km"] * mehr / 10000)})

    # --- erfasste Mängel ---
    for m in daten.get("maengel") or []:
        k = index.get(m.get("key"))
        if not k:
            hinweise.append(f"Unbekannter Mangel „{m.get('key')}“ ignoriert")
            continue
        stufe = m.get("stufe") if "stufen" in k else None
        eingabe = _als_zahl(m.get("betrag"))
        if eingabe is not None:                                     # manuell überschrieben oder freier Mangel
            betrag = eingabe
        elif str(m.get("betrag") or "").strip():
            hinweise.append(f"{k['name']}: Betrag „{m.get('betrag')}“ ungültig")
            continue
        elif "stufen" in k:
            if stufe not in k["stufen"]:
                hinweise.append(f"{k['name']}: Schweregrad fehlt")
                continue
            betrag = k["stufen"][stufe]
        elif "betrag" in k:
            betrag = k["betrag"]
        elif "prozent" in k:
            betrag = marktwert * k["prozent"]
        else:
            hinweise.append(f"{k['name']}: Betrag fehlt")
            continue
        name = str(m.get("name") or "").strip() if k.get("frei") else k["name"]
        posten.append({"quelle": "mangel", "key": k["key"], "name": name or k["name"], "stufe": stufe,
                       "betrag": _runde(betrag), "notiz": m.get("notiz") or ""})
        if k.get("ko") or (k.get("ko_ab") and stufe and STUFEN.index(stufe) >= STUFEN.index(k["ko_ab"])):
            ko.append(k["name"])

    # --- Summen ---
    summe = sum(p["betrag"] for p in posten)
    gutschrift = _runde(min(summe, (basis.get("reparaturrisiko") or 0) * g["risiko_anrechnung"]))
    anpassung = _runde(_als_zahl((daten.get("anpassung") or {}).get("betrag")) or 0)
    netto = summe - gutschrift + anpassung
    faktor = 1.19 if basis.get("differenzbesteuerung", True) is not False else 1.0
    ek_abzug = _runde(netto * faktor)
    max_ek = basis.get("max_ek") or 0
    max_ek_neu = max_ek - ek_abzug
    angebot = basis.get("angebot") or 0
    r = g["rundung_vorschlag"]
    vorschlag = max(0, math.floor(min(angebot - ek_abzug, max_ek_neu) / r) * r)

    # --- Vollständigkeit (Pflichtpunkte) ---
    abgehakt = daten.get("pruefpunkte") or {}
    fehlend = []
    for p in katalog["pruefpunkte"]:
        if not p.get("pflicht"):
            continue
        if p.get("messung") == "feuchtigkeit" and len(punkte) < fm["mindest_messpunkte"]:
            fehlend.append(f"{p['name']} (mind. {fm['mindest_messpunkte']} Messpunkte, erfasst {len(punkte)})")
        elif p.get("messung") == "reifen" and len(reifen) < rm["mindest_reifen"]:
            fehlend.append(f"{p['name']} (mind. {rm['mindest_reifen']}, erfasst {len(reifen)})")
        elif not p.get("messung") and not abgehakt.get(p["key"]):
            fehlend.append(p["name"])

    return {
        "posten": posten, "summe_maengel": summe, "risiko_gutschrift": gutschrift, "anpassung": anpassung,
        "netto_abzug": netto, "ek_faktor": faktor, "ek_abzug": ek_abzug, "max_ek": max_ek, "max_ek_neu": max_ek_neu,
        "angebot": angebot, "vorschlag": vorschlag, "ko": ko, "fehlende_pflicht": fehlend,
        "vollstaendig": not fehlend, "hinweise": hinweise,
    }
