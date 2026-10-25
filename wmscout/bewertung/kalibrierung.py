"""Kalibrierung des Rechners mit tatsächlichen Ankäufen (P5-01, ADR-052) – Bericht und Vorschläge, keine automatische Änderung.

Fälle kommen aus zwei Quellen:

* **Ankäufe der App** (``ankaeufe``): Plan beim Kauf eingefroren (Händler-VK, Kosten, Max-EK), Ist aus Kaufpreis, erfassten Kosten,
  Verkaufspreis und Standzeit (``ergebnis.vergleich``).
* **Manuell erfasste frühere Ankäufe** (``kalibrierung_faelle``, Schema v20): Fahrzeugdaten und tatsächlicher Kaufpreis, optional
  Verkaufspreis, Ist-Kosten und Daten. Der Rechner rechnet sie zum Kaufdatum **nur mit dem Marktmodell** nach – Vergleichsangebote von
  damals fehlen, und heutige Angebote eines EZ-Jahrgangs wären für ein früheres Kaufdatum zu alt bewertet (QA P5-01 B1).

Vorschläge rechnen je Fall relativ zu den Parametern, mit denen er geplant wurde (``plan["parameter"]`` beim Ankauf, aktuelle
``config.yaml`` bei nachgerechneten Fällen) – so schlägt der nächste Bericht eine übernommene Korrektur nicht noch einmal vor.

Der Bericht zeigt Kaufpreis ÷ Max-EK, Verkaufspreis ÷ geplanter Händler-VK, Ist- minus Plankosten und Standzeit (Median, Quartile, Anzahl).
Vorschläge für ``config.yaml`` gibt es erst ab ``MIN_FAELLE`` verwertbaren Fällen und einer Abweichung über der Toleranz – der Betreiber
stellt die Parameter bewusst nach. Oben die Fachlogik ohne Datenbank, unten der Speicher.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime

from ..normalisierung.fahrzeug import normalisiere_marke
from ..normalisierung.geo import entfernung_km, plz_bekannt
from .ergebnis import vergleich as plan_ist_vergleich
from .rechner import Rechner

ARTEN = ("Teilintegrierter", "Integrierter", "Alkoven", "Kastenwagen", "Wohnwagen", "Sonstige")
MIN_FAELLE = 5                                   # ab so vielen verwertbaren Fällen gibt es Vorschläge
TOLERANZ_VK, TOLERANZ_KOSTEN, TOLERANZ_STANDZEIT = 0.05, 300, 30
MAX_BETRAG, MAX_TEXT, MAX_NOTIZ = 2_000_000, 80, 300
UEBLICH_AUFSCHLAG, UEBLICH_ABSCHLAG = (0.0, 0.30), (0.0, 0.25)      # außerhalb: Vorschlag mit Warnung (Daten prüfen)


class Eingabefehler(ValueError):
    """Ungültige Angabe eines manuellen Falls (Text für den Nutzer)."""


def _text(daten: dict, feld: str, laenge: int, name: str) -> str | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        return None
    if not isinstance(wert, str):
        raise Eingabefehler(f"{name} muss Text sein")
    wert = " ".join(wert.split())
    if len(wert) > laenge:
        raise Eingabefehler(f"{name} höchstens {laenge} Zeichen")
    return wert or None


def _zahl(daten: dict, feld: str, unten: int, oben: int, name: str, pflicht: bool = False) -> int | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        if pflicht:
            raise Eingabefehler(f"{name} fehlt")
        return None
    if isinstance(wert, bool) or not isinstance(wert, int) or not unten <= wert <= oben:
        raise Eingabefehler(f"{name} muss eine ganze Zahl von {unten} bis {oben} sein")
    return wert


def _datum(daten: dict, feld: str, name: str, heute: date, pflicht: bool = False) -> str | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        if pflicht:
            raise Eingabefehler(f"{name} fehlt")
        return None
    try:
        d = date.fromisoformat(wert) if isinstance(wert, str) and len(wert) == 10 else None
    except ValueError:
        d = None
    if d is None or not date(2000, 1, 1) <= d <= heute:
        raise Eingabefehler(f"{name}: Datum JJJJ-MM-TT zwischen 2000 und heute")
    return d.isoformat()


def pruefe_fall(daten: dict, heute: date) -> dict:
    """Eingabe → gespeicherte Form; ``Eingabefehler`` mit verständlichem Text. Keine Verkäuferdaten vorgesehen."""
    if not isinstance(daten, dict):
        raise Eingabefehler("Fall muss ein Objekt sein")
    art = daten.get("art")
    if art not in ARTEN:
        raise Eingabefehler(f"art: eine von {', '.join(ARTEN)}")
    plz = _text(daten, "plz", 5, "PLZ")
    if plz is not None and not plz_bekannt(plz):
        raise Eingabefehler("PLZ: bekannte fünfstellige deutsche PLZ")
    marke = _text(daten, "marke", MAX_TEXT, "Marke")
    f = {"fahrzeug": _text(daten, "fahrzeug", MAX_TEXT, "Fahrzeug"), "marke": (normalisiere_marke(marke) or marke) if marke else None,
         "modell": _text(daten, "modell", MAX_TEXT, "Modell"), "art": art,
         "ez_jahr": _zahl(daten, "ez_jahr", 1960, heute.year + 1, "EZ", pflicht=True), "km": _zahl(daten, "km", 0, MAX_BETRAG, "km"),
         "plz": plz, "angebotspreis": _zahl(daten, "angebotspreis", 1, MAX_BETRAG, "Angebotspreis"),
         "ankauf_am": _datum(daten, "ankauf_am", "Kaufdatum", heute, pflicht=True),
         "ankauf_preis": _zahl(daten, "ankauf_preis", 1, MAX_BETRAG, "Kaufpreis", pflicht=True),
         "kosten": _zahl(daten, "kosten", 0, MAX_BETRAG, "Ist-Kosten"),
         "verkauf_am": _datum(daten, "verkauf_am", "Verkaufsdatum", heute),
         "verkauf_preis": _zahl(daten, "verkauf_preis", 1, MAX_BETRAG, "Verkaufspreis"),
         "notiz": _text(daten, "notiz", MAX_NOTIZ, "Notiz")}
    if (f["verkauf_am"] is None) != (f["verkauf_preis"] is None):
        raise Eingabefehler("Verkauf: Datum und Preis zusammen angeben (oder beides leer)")
    if f["verkauf_am"] and f["verkauf_am"] < f["ankauf_am"]:
        raise Eingabefehler("Verkaufsdatum liegt vor dem Kaufdatum")
    if int(f["ankauf_am"][:4]) < f["ez_jahr"] - 1:
        raise Eingabefehler("Kaufdatum liegt vor der Erstzulassung")
    return f


def parameter(cfg: dict) -> dict:
    """Stand der kalibrierten Parameter – wird beim Ankauf im Plan mitgespeichert."""
    r = cfg["rechner"]
    return {"aufschlag_haendler_vk": float(r["aufschlag_haendler_vk"]), "abschlag_angebot_auf_privatwert": float(r["abschlag_angebot_auf_privatwert"]),
            "aufbereitung": int(r["kosten"]["aufbereitung"]), "standzeit_monate": int(r["kosten"].get("standzeit_monate", 3))}


# ---------------------------------------------------------------- Fälle vereinheitlichen
def fall_aus_ankauf(ankauf: dict, kosten: list[dict]) -> dict | None:
    """Ankauf der App (stornierte zählen nicht). Kosten und Standzeit erst nach dem Verkauf (vorher unvollständig)."""
    if ankauf["status"] == "storniert":
        return None
    v = plan_ist_vergleich(json.loads(ankauf["plan_json"]), ankauf, kosten)
    plan, ist, verkauft = v["plan"], v["ist"], ankauf["status"] == "verkauft"
    return {"quelle": "ankauf", "ref": ankauf.get("referenz") or f"#{ankauf['id']}", "datum": (ankauf.get("erstellt_am") or "")[:10],
            "ek": ankauf["kaufpreis"], "max_ek": plan.get("max_ek"), "vk_plan": plan.get("haendler_vk"), "vk": ist["vk"],
            "kosten_plan": plan.get("kosten"), "kosten": ist["kosten"] if verkauft and kosten else None,     # ohne Erfassung: unbekannt, nicht 0
            "standzeit_plan": plan.get("standzeit_tage"), "standzeit": ist["standzeit_tage"] if verkauft else None,
            "sicherheit": None, "nachgerechnet": False, "parameter": plan.get("parameter")}


def fall_aus_manuell(f: dict, cfg: dict) -> dict:
    """Manueller Fall, vom Rechner zum Kaufdatum (12 Uhr) nur mit dem Marktmodell nachgerechnet (ohne Vergleichsangebote)."""
    standort = str(cfg["anschreiben"].get("plz") or "") or None
    a = {"id": f"kalibrierung-{f.get('id')}", "suche": f["art"], "art": f["art"], "marke": f["marke"], "modell": f["modell"],
         "titel": f["fahrzeug"] or " ".join(x for x in (f["marke"], f["modell"]) if x) or f["art"], "ez_jahr": f["ez_jahr"], "km": f["km"],
         "preis": f["angebotspreis"], "plz": f["plz"], "entfernung_km": entfernung_km(standort, f["plz"]) if f["plz"] else None}
    stichtag = datetime.combine(date.fromisoformat(f["ankauf_am"]), datetime.min.time()).replace(hour=12)
    b = Rechner(cfg, stichtag).bewerte(a, [])
    standzeit = (date.fromisoformat(f["verkauf_am"]) - date.fromisoformat(f["ankauf_am"])).days if f["verkauf_am"] else None
    gerechnet = bool(b.haendler_vk)                  # Max-EK 0 bleibt 0 (Rechner rät vom Kauf ab), nur ohne Marktwert None
    return {"quelle": "manuell", "ref": f"M-{f.get('id')}", "datum": f["ankauf_am"], "ek": f["ankauf_preis"],
            "max_ek": b.max_ek if gerechnet else None, "vk_plan": b.haendler_vk if gerechnet else None, "vk": f["verkauf_preis"],
            "kosten_plan": b.kosten if gerechnet else None, "kosten": f["kosten"] if f["verkauf_preis"] else None,
            "standzeit_plan": int(cfg["rechner"]["kosten"].get("standzeit_monate", 3)) * 30, "standzeit": standzeit,
            "sicherheit": b.sicherheit, "nachgerechnet": True, "parameter": parameter(cfg)}


# ---------------------------------------------------------------- Bericht
def kennzahl(werte: list[float]) -> dict | None:
    """Median und Quartile mit Interpolation (bei gerader Anzahl Mittel der beiden mittleren Werte)."""
    if not werte:
        return None
    q1, _, q3 = statistics.quantiles(werte, n=4, method="inclusive") if len(werte) > 1 else (werte[0],) * 3
    return {"n": len(werte), "median": round(statistics.median(werte), 3), "q1": round(q1, 3), "q3": round(q3, 3)}


def belastbarkeit(n: int) -> str:
    if n < 3:
        return "zu wenige Fälle – keine Aussage"
    if n < MIN_FAELLE:
        return "erste Hinweise – noch keine Vorschläge"
    return "belastbar genug für Vorschläge" if n >= 10 else "Vorschläge mit Vorsicht"


def prozent(x: float) -> str:
    """Abweichung als deutscher Prozenttext, z. B. 0.94 → „−6 %“."""
    p = round((x - 1) * 100)
    return f"{'+' if p > 0 else '−' if p < 0 else '±'}{abs(p)} %"


def _euro(x: float) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else '±'}{abs(round(x)):,} €".replace(",", ".")


def _runde_halb_auf(x: float) -> int:
    return math.floor(x + 0.5)


def _warnung(wert: float, bereich: tuple[float, float]) -> str | None:
    if bereich[0] <= wert <= bereich[1]:
        return None
    return f"außerhalb des üblichen Bereichs ({bereich[0]:.0%}–{bereich[1]:.0%}) – Fälle prüfen, nicht ungeprüft übernehmen".replace("%", " %")


def bericht(faelle: list[dict], cfg: dict) -> dict:
    """Kennzahlen über alle Fälle und Vorschläge für ``config.yaml``. Vorschläge nur aus Fällen mit bekanntem Parameterstand, je Fall
    relativ zu diesem Stand (``parameter``) – übernommene Korrekturen werden nicht erneut vorgeschlagen."""
    jetzt = parameter(cfg)
    ek = kennzahl([f["ek"] / f["max_ek"] for f in faelle if f.get("max_ek")])
    vk = kennzahl([f["vk"] / f["vk_plan"] for f in faelle if f.get("vk") and f.get("vk_plan")])
    kosten = kennzahl([f["kosten"] - f["kosten_plan"] for f in faelle if f.get("kosten") is not None and f.get("kosten_plan") is not None])
    standzeit = kennzahl([f["standzeit"] - f["standzeit_plan"] for f in faelle if f.get("standzeit") is not None and f.get("standzeit_plan")])
    mit = [f for f in faelle if f.get("parameter")]
    vorschlaege = []
    vk_faelle = [f for f in mit if f.get("vk") and f.get("vk_plan")]
    if len(vk_faelle) >= MIN_FAELLE:
        aufschlag = statistics.median((1 + f["parameter"]["aufschlag_haendler_vk"]) * f["vk"] / f["vk_plan"] - 1 for f in vk_faelle)
        if abs((1 + aufschlag) / (1 + jetzt["aufschlag_haendler_vk"]) - 1) > TOLERANZ_VK:
            abschlag = round(statistics.median(1 - (1 - f["parameter"]["abschlag_angebot_auf_privatwert"]) * f["vk"] / f["vk_plan"]
                                               for f in vk_faelle), 2)
            m = statistics.median(f["vk"] / f["vk_plan"] for f in vk_faelle)
            vorschlaege.append({
                "parameter": "rechner.aufschlag_haendler_vk", "alt": jetzt["aufschlag_haendler_vk"], "neu": round(aufschlag, 2),
                "faelle": len(vk_faelle), "grund": f"Verkaufspreise liegen im Median {prozent(m)} beim geplanten Händler-VK",
                "alternative": f"oder rechner.abschlag_angebot_auf_privatwert von {jetzt['abschlag_angebot_auf_privatwert']} auf {abschlag} "
                               "(wenn schon der Marktwert privat danebenliegt – wirkt auch auf Erstangebot und Fair-Untergrenze)"
                               + (f"; dieser Wert liegt {_warnung(abschlag, UEBLICH_ABSCHLAG)}" if _warnung(abschlag, UEBLICH_ABSCHLAG) else ""),
                "warnung": _warnung(round(aufschlag, 2), UEBLICH_AUFSCHLAG)})
    k_faelle = [f for f in mit if f.get("kosten") is not None and f.get("kosten_plan") is not None]
    if len(k_faelle) >= MIN_FAELLE:
        aufbereitung = statistics.median(f["parameter"]["aufbereitung"] + f["kosten"] - f["kosten_plan"] for f in k_faelle)
        if abs(aufbereitung - jetzt["aufbereitung"]) > TOLERANZ_KOSTEN:
            neu = max(0, _runde_halb_auf(aufbereitung / 50) * 50)
            vorschlaege.append({"parameter": "rechner.kosten.aufbereitung", "alt": jetzt["aufbereitung"], "neu": neu, "faelle": len(k_faelle),
                                "grund": f"Ist-Kosten liegen im Median {_euro(aufbereitung - jetzt['aufbereitung'])} beim Plan",
                                "alternative": "oder die Abweichung auf die Posten verteilen, die sie verursachen (Reparatur, Transport, HU/Gas)",
                                "warnung": "Ist-Kosten liegen unter null – Erfassung prüfen" if aufbereitung < 0 else None})
    s_faelle = [f for f in mit if f.get("standzeit") is not None and f.get("standzeit_plan")]
    if len(s_faelle) >= MIN_FAELLE:
        tage = statistics.median(f["parameter"]["standzeit_monate"] * 30 + f["standzeit"] - f["standzeit_plan"] for f in s_faelle)
        neu = max(1, _runde_halb_auf(tage / 30))
        if abs(tage - jetzt["standzeit_monate"] * 30) > TOLERANZ_STANDZEIT and neu != jetzt["standzeit_monate"]:
            vorschlaege.append({"parameter": "rechner.kosten.standzeit_monate", "alt": jetzt["standzeit_monate"], "neu": neu, "faelle": len(s_faelle),
                                "grund": f"Standzeit im Median {tage - jetzt['standzeit_monate'] * 30:+.0f} Tage gegenüber dem Plan".replace("-", "−"),
                                "alternative": None, "warnung": None})
    hinweise = []
    if ek and ek["median"] > 1:
        hinweise.append(f"Gekauft wird im Median {prozent(ek['median'])} gegenüber dem Max-EK – die Ziel-Marge wird dann nicht erreicht")
    if abgeraten := sum(1 for f in faelle if f.get("max_ek") == 0):
        hinweise.append(f"{abgeraten}× gekauft, obwohl der Rechner Max-EK 0 ergab (vom Kauf abgeraten) – nicht in „Kaufpreis gegenüber Max-EK“")
    if any(f["nachgerechnet"] for f in faelle):
        hinweise.append("Nachgetragene Fälle sind nur mit dem Marktmodell zum Kaufdatum nachgerechnet (ohne Vergleichsangebote von damals)")
    if ohne := sum(1 for f in faelle if not f.get("parameter")):
        hinweise.append(f"{ohne} Ankauf/Ankäufe ohne gespeicherten Parameterstand (vor P5-01 oder ohne Bewertung geplant) – in den Kennzahlen, "
                        "nicht in den Vorschlägen")
    verwertbar = max((k["n"] for k in (ek, vk, kosten, standzeit) if k), default=0)
    return {"faelle": len(faelle), "verkauft": sum(1 for f in faelle if f.get("vk")), "ek_zu_max_ek": ek,
            "ueber_max_ek": sum(1 for f in faelle if f.get("max_ek") is not None and f["ek"] > f["max_ek"]), "vk_zu_plan": vk,
            "kosten_abweichung": kosten, "standzeit_abweichung": standzeit, "belastbarkeit": belastbarkeit(verwertbar),
            "vorschlaege": vorschlaege, "hinweise": hinweise, "min_faelle": MIN_FAELLE}


# ---------------------------------------------------------------- Speicher
class KalibrierungSpeicher:
    """Tabelle ``kalibrierung_faelle`` (Schema v20) und das Einsammeln aller Fälle."""

    def __init__(self, db):
        self.db = db

    _SPALTEN = ("fahrzeug", "marke", "modell", "art", "ez_jahr", "km", "plz", "angebotspreis", "ankauf_am", "ankauf_preis", "kosten",
                "verkauf_am", "verkauf_preis", "notiz")

    def manuelle(self) -> list[dict]:
        return [dict(z) for z in self.db.con.execute("SELECT * FROM kalibrierung_faelle ORDER BY ankauf_am DESC, id DESC")]

    def anlegen(self, f: dict, nutzer_id: int | None) -> int:
        with self.db.transaktion():
            return self.db.con.execute(
                f"INSERT INTO kalibrierung_faelle ({', '.join(self._SPALTEN)}, erfasst_am, erfasst_von) "
                f"VALUES ({', '.join('?' * (len(self._SPALTEN) + 2))})",
                [*(f[s] for s in self._SPALTEN), datetime.now().isoformat(timespec="seconds"), nutzer_id]).lastrowid

    def loeschen(self, fall_id: int) -> bool:
        with self.db.transaktion():
            return self.db.con.execute("DELETE FROM kalibrierung_faelle WHERE id=?", (fall_id,)).rowcount > 0

    def faelle(self, cfg: dict) -> list[dict]:
        """Ankäufe der App und nachgerechnete manuelle Fälle (nur lesen)."""
        erg = []
        for a in self.db.con.execute("SELECT * FROM ankaeufe ORDER BY id"):
            a = dict(a)
            kosten = [dict(k) for k in self.db.con.execute("SELECT * FROM ankauf_kosten WHERE ankauf_id=? ORDER BY id", (a["id"],))]
            if (f := fall_aus_ankauf(a, kosten)) is not None:
                erg.append(f)
        erg.extend(fall_aus_manuell(f, cfg) for f in self.manuelle())
        return erg
