"""Deal-Score 0–100 (P5-07, ADR-060): wie lohnend ein Ankauf ist – aus benannten Bestandteilen, damit sichtbar ist, warum ein Fahrzeug
oben steht. Rein (ohne Netz und Datenbank), quellenneutral: liest nur Bewertung und Inserat in Rechner-Sicht.

Bestandteile (Gewichte in config.yaml → deal_score → gewichte, Summe beliebig – der Score wird auf 100 umgerechnet):
  Preisvorteil    Angebotspreis ÷ Max-EK: bis ``preis_voll_bei`` volle Punkte, ab ``preis_null_bei`` keine
  Datensicherheit Sicherheit der Bewertung (hoch / mittel / niedrig / manuell)
  Zustand         im Inserat genannte Mängel (voller Abzug laut Wertfaktoren, ab ``maengel_null_bei`` keine Punkte)
  Abholung        Abholkosten (P5-06) bzw. Entfernung; Ausland keine Punkte
  Frische         neu, gesenkt oder jetzt im Rahmen (P4-03), sonst nach Tagen online
  Verkäufer       privat (belegt) – gewerblich keine; offline, Dublette oder lückenhafte Daten halbieren

Kein Score ohne belastbare Bewertung (keine Erstzulassung, kein Preis, Max-EK 0) und bei vom Markt her gesperrten Inseraten (gewerblich,
verkauft/offline, Filter, Sperrbegriff, doppelt eingestellt): Sie sind keine Ankaufsgelegenheit. Ein Ankaufsstatus (Text kopiert,
kontaktiert, Besichtigung …) nimmt den Score nicht weg. Die Ampel bleibt daneben unverändert (Anschreiben, Filter).
"""
from __future__ import annotations

import math

MODELL = "D1"                 # bei jeder Änderung an Formeln oder Bestandteilen erhöhen (gespeicherte Bewertungen bleiben vergleichbar)
STANDARD = {
    "gewichte": {"preisvorteil": 40, "datensicherheit": 20, "zustand": 15, "abholung": 10, "frische": 10, "verkaeufer": 5},
    "schwelle": 70, "preis_voll_bei": 0.85, "preis_null_bei": 1.15, "maengel_null_bei": 0.25, "abholung_null_bei_euro": 1000,
    "entfernung_null_bei_km": 600,
}
NAMEN = {"preisvorteil": "Preisvorteil", "datensicherheit": "Datensicherheit", "zustand": "Zustand", "abholung": "Abholung",
         "frische": "Frische", "verkaeufer": "Verkäufer und Verfügbarkeit"}
SICHERHEIT = {"hoch": 1.0, "mittel": 0.6, "niedrig": 0.25, "manuell": 0.5}


def einstellungen(cfg: dict) -> dict:
    """``deal_score`` mit Standardwerten ergänzt und geprüft – Fehleingaben verständlich melden."""
    roh = cfg.get("deal_score") or {}
    pfad = "config.yaml: deal_score"
    if not isinstance(roh, dict):
        raise ValueError(f"{pfad} muss ein Abschnitt sein")
    if fremd := sorted(set(roh) - set(STANDARD)):
        raise ValueError(f"{pfad} → unbekannte Einträge {', '.join(map(str, fremd))} (Tippfehler?)")
    g = roh.get("gewichte") or {}
    if not isinstance(g, dict) or (fremd := sorted(set(g) - set(STANDARD["gewichte"]))):
        raise ValueError(f"{pfad} → gewichte: nur {', '.join(STANDARD['gewichte'])}" + (f" (unbekannt: {', '.join(map(str, fremd))})" if g else ""))
    erg = {**STANDARD, **{k: v for k, v in roh.items() if k != "gewichte"}, "gewichte": {**STANDARD["gewichte"], **g}}
    for k, w in [*erg["gewichte"].items(), *((k, erg[k]) for k in STANDARD if k != "gewichte")]:
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0:
            raise ValueError(f"{pfad} → {k}: Zahl ≥ 0 erwartet, nicht {w!r}")
    if not sum(erg["gewichte"].values()):
        raise ValueError(f"{pfad} → gewichte: mindestens ein Gewicht > 0")
    if not erg["preis_voll_bei"] < erg["preis_null_bei"]:
        raise ValueError(f"{pfad}: preis_voll_bei muss kleiner als preis_null_bei sein")
    if not 0 <= erg["schwelle"] <= 100:
        raise ValueError(f"{pfad} → schwelle: 0–100")
    for k in ("maengel_null_bei", "abholung_null_bei_euro", "entfernung_null_bei_km"):
        if erg[k] <= 0:
            raise ValueError(f"{pfad} → {k}: Zahl > 0")
    return erg


def _linear(wert: float, voll: float, null: float) -> float:
    """1 bei ``voll``, 0 bei ``null`` (beide Richtungen), dazwischen linear."""
    if voll == null:
        return 1.0 if wert <= voll else 0.0
    return max(0.0, min(1.0, (null - wert) / (null - voll)))


def _prozent(x: float) -> str:
    return f"{abs(x):.0%}".replace("%", " %")


def _abholkosten(b) -> float | None:
    if getattr(b, "abholung", None):
        varianten = {v["art"]: v for v in b.abholung["varianten"]}
        return float(varianten[b.abholung["gewaehlt"]]["euro"])
    return None


def bestandteile(a: dict, b, neuigkeit: dict | None, e: dict) -> list[dict]:
    """Je Bestandteil {schluessel, name, anteil 0–1, text} – ohne Gewichte."""
    erg = []

    def teil(schluessel: str, anteil: float, text: str):
        erg.append({"schluessel": schluessel, "name": NAMEN[schluessel], "anteil": round(max(0.0, min(1.0, anteil)), 3), "text": text})

    r = a["preis"] / b.max_ek
    # ein Preisvorteil aus unsicherer Bewertung zählt weniger – sonst stünde ein Max-EK ohne Vergleiche oben (QA P5-07 B2)
    vertrauen = 0.5 + 0.5 * SICHERHEIT.get(b.sicherheit, 0.0)
    text = (f"Wunschpreis {_prozent(1 - r)} {'unter' if r <= 1 else 'über'} dem Max-EK" if abs(1 - r) >= 0.005 else "Wunschpreis gleich Max-EK")
    teil("preisvorteil", _linear(r, e["preis_voll_bei"], e["preis_null_bei"]) * vertrauen,
         text + ("" if vertrauen == 1 else f" (zählt zu {vertrauen:.0%}, Sicherheit {b.sicherheit})".replace("%", " %")))
    teil("datensicherheit", SICHERHEIT.get(b.sicherheit, 0.0), f"Sicherheit {b.sicherheit} ({b.vergleich_anzahl} Vergleiche)")
    abzug = sum(-m.get("roh", m["wert"]) for m in (b.maengel or []))
    teil("zustand", _linear(abzug, 0.0, e["maengel_null_bei"]),
         "keine Mängel genannt" if not b.maengel else "genannt: " + ", ".join(m["name"] for m in b.maengel))
    kosten = _abholkosten(b)
    if a.get("ausland"):
        teil("abholung", 0.0, "Ausland – Abholung und Zulassung aufwendig")
    elif kosten is not None:
        teil("abholung", _linear(kosten, 0.0, e["abholung_null_bei_euro"]), f"Abholung ca. {round(kosten / 10) * 10:,.0f} €".replace(",", "."))
    elif a.get("entfernung_km") is not None:
        teil("abholung", _linear(a["entfernung_km"], 0.0, e["entfernung_null_bei_km"]), f"{a['entfernung_km']:,} km entfernt".replace(",", "."))
    else:
        teil("abholung", 0.5, "Entfernung unbekannt")
    tage = a.get("tage_online") or 0
    if neuigkeit and neuigkeit.get("im_rahmen"):
        teil("frische", 1.0, "Preis gesenkt – jetzt im Rahmen")
    elif neuigkeit and neuigkeit.get("frisch"):
        teil("frische", 1.0, "frisch eingegangen")
    elif neuigkeit and neuigkeit.get("senkung"):
        teil("frische", 0.8, "Preis deutlich gesenkt")
    else:
        teil("frische", _linear(tage, 0, 120) * 0.5, "seit heute online" if not tage else f"seit {tage} Tag{'en' if tage != 1 else ''} online")
    anbieter = a.get("anbieter") or {}
    anteil = {"privat": 1.0 if anbieter.get("belegt") else 0.8, "unbekannt": 0.4}.get(anbieter.get("typ"), 0.0)
    texte = [anbieter.get("text") or "Anbieter unbekannt"]
    # verkauft/offline, gewerblich und doppelt eingestellt sind schon gesperrt (kein Score); hier zählen die weichen Fälle (QA B3)
    for bedingung, text in ((a.get("vermutlich_offline"), "vermutlich nicht mehr online"), (a.get("verfuegbarkeit") == "reserviert", "reserviert"),
                            ((a.get("datenqualitaet") or {}).get("stufe") == "schwach", "Daten lückenhaft")):
        if bedingung:
            anteil, texte = anteil / 2, [*texte, text]
    teil("verkaeufer", anteil, ", ".join(texte))
    return erg


def deal_score(a: dict, b, neuigkeit: dict | None, sperre: str | None, cfg: dict, e: dict | None = None) -> dict:
    """{score (0–100 oder None), priorisiert, grund (ohne Score), bestandteile [{…, gewicht, punkte}], modell}."""
    e = e or einstellungen(cfg)
    leer = {"score": None, "priorisiert": False, "bestandteile": [], "modell": MODELL, "schwelle": e["schwelle"]}
    if sperre:
        return {**leer, "grund": f"gesperrt: {sperre}"}
    if getattr(b, "sicherheit", "keine") == "keine" or not getattr(b, "max_ek", 0) or not a.get("preis"):
        return {**leer, "grund": "keine belastbare Bewertung (Erstzulassung, Preis oder Marktwert fehlt)"}
    summe = sum(e["gewichte"].values())
    teile = []
    for t in bestandteile(a, b, neuigkeit, e):
        gewicht = e["gewichte"][t["schluessel"]] * 100 / summe
        teile.append({**t, "gewicht": round(gewicht, 1), "punkte": round(gewicht * t["anteil"], 1)})
    score = round(sum(t["punkte"] for t in teile))
    return {**leer, "score": score, "priorisiert": score >= e["schwelle"] and not top_ausschluss(a, b), "bestandteile": teile,
            "kein_top": top_ausschluss(a, b) if score >= e["schwelle"] else None, "grund": None}


def top_ausschluss(a: dict, b) -> str | None:
    """Warum ein hoher Score trotzdem kein Top-Deal ist (QA P5-07 B1–B4): nur offene, private, verfügbare Inserate mit grüner Ampel und
    belastbarer Bewertung – die Ampel ist bei Ausland und unbekannter Art bewusst höchstens gelb."""
    if a.get("status") not in (None, "neu"):
        return "schon in Bearbeitung"
    if (a.get("anbieter") or {}).get("typ") != "privat":
        return "Anbieter nicht als privat erkannt"
    if a.get("nicht_verfuegbar") or a.get("vermutlich_offline") or a.get("verfuegbarkeit") == "reserviert":
        return "nicht sicher verfügbar"
    if a.get("ausland"):
        return "Ausland"
    if b.sicherheit not in ("hoch", "mittel", "manuell"):
        return f"Bewertung zu unsicher ({b.sicherheit})"
    if b.ampel != "gruen":
        return "Ampel nicht grün"
    return None
