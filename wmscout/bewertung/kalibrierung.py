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
from .ergebnis import kosten_kapital
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
            # Plankosten ohne rechnerische Kapitalbindung (P5-05, QA B3) – sie wird nie als Ist-Kosten erfasst
            "kosten_plan": None if plan.get("kosten") is None else plan["kosten"] - (plan.get("kosten_kapital") or 0),
            "kosten": ist["kosten"] if verkauft and kosten else None,     # ohne Erfassung: unbekannt, nicht 0
            "standzeit_plan": plan.get("standzeit_tage"), "standzeit": ist["standzeit_tage"] if verkauft else None,
            "sicherheit": None, "nachgerechnet": False, "parameter": plan.get("parameter"), "abschlag_marke": plan.get("abschlag_marke") or 0.0}


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
            "kosten_plan": b.kosten - kosten_kapital(b.kosten_posten) if gerechnet else None,
            "kosten": f["kosten"] if f["verkauf_preis"] else None,
            "standzeit_plan": Rechner(cfg, stichtag).standzeit_monate() * 30, "standzeit": standzeit,
            "sicherheit": b.sicherheit, "nachgerechnet": True, "parameter": parameter(cfg), "abschlag_marke": b.abschlag_marke}


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
    # Fälle mit Abschlag für unbekannte Marke (P5-03) prüfen den Abschlag, nicht den Händleraufschlag (QA P5-03 B3)
    vk_faelle = [f for f in mit if f.get("vk") and f.get("vk_plan") and not f.get("abschlag_marke")]
    marke_faelle = [f for f in mit if f.get("vk") and f.get("vk_plan") and f.get("abschlag_marke")]
    if len(marke_faelle) >= MIN_FAELLE:
        jetzt_abschlag = float(cfg["rechner"].get("abschlag_marke_unbekannt", 0.05))
        abschlag = statistics.median(1 - (1 - f["abschlag_marke"]) * f["vk"] / f["vk_plan"] for f in marke_faelle)
        if abs((1 - abschlag) / (1 - jetzt_abschlag) - 1) > TOLERANZ_VK:
            vorschlaege.append({"parameter": "rechner.abschlag_marke_unbekannt", "alt": jetzt_abschlag, "neu": round(max(0.0, abschlag), 2),
                                "faelle": len(marke_faelle), "grund": "Fahrzeuge mit unbekannter Marke verkaufen sich im Median "
                                f"{prozent(statistics.median(f['vk'] / f['vk_plan'] for f in marke_faelle))} gegenüber dem Plan",
                                "alternative": None, "warnung": _warnung(abschlag, (0.0, 0.25))})
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


# ---------------------------------------------------------------- Marktbeobachtung (P5-04)
def preissenkungen(verlaeufe: list[tuple[int, int]], abschlag: float) -> dict:
    """Angebotspreise privater Inserate, die vom Markt verschwunden sind: (erster, letzter Preis) je Inserat. Echte Abschlusspreise liefert
    kein Portal – die Senkung bis zum Verschwinden ist nur eine **Untergrenze** für den Abschlag Angebot → Abschluss."""
    senkungen = [max(0.0, 1 - letzter / erster) for erster, letzter in verlaeufe if erster and letzter]
    n = len(senkungen)
    gesenkt = [x for x in senkungen if x > 0]
    erg = {"n": n, "mit_senkung": len(gesenkt), "median": round(statistics.median(senkungen), 3) if senkungen else None,
           "median_gesenkt": round(statistics.median(gesenkt), 3) if gesenkt else None, "abschlag": abschlag, "hinweis": None}
    if n < MIN_FAELLE:
        erg["hinweis"] = f"Zu wenige verschwundene Privatinserate mit Preisverlauf ({n}) – noch keine Aussage"
    elif erg["median"] > abschlag:
        erg["hinweis"] = (f"Private Inserate senkten bis zum Verschwinden im Median um {erg['median']:.0%} – mehr als der eingestellte Abschlag "
                          f"Angebot → Abschluss ({abschlag:.0%}); rechner.abschlag_angebot_auf_privatwert prüfen").replace("%", " %")
    return erg


def _eintrag(text: str) -> tuple[str, int, int]:
    """„zeitpunkt|id|preis“ aus der Abfrage → sortierbar nach Zeitpunkt, bei Gleichstand nach Eintragsreihenfolge."""
    zeit, nr, preis = text.rsplit("|", 2)
    return zeit, int(nr), int(preis)


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

    def marktbeobachtung(self, cfg: dict, jetzt: datetime | None = None) -> dict:
        """Private **Fahrzeuge**, deren Inserate alle vom Markt verschwunden sind (verkauft, offline oder vermutlich offline nach derselben
        Regel wie in der App, ``verfuegbarkeit.bewerte``): erster Preis über alle Inserate des Fahrzeugs gegen den letzten (nur lesen).
        Wieder eingestellte oder auf mehreren Plattformen inserierte Fahrzeuge zählen einmal; eines mit noch verfügbarem Inserat nicht
        (QA P5-04 B3)."""
        from ..datenbank import STANDARD_PLATTFORM
        from ..verfuegbarkeit import bewerte as verfuegbarkeit, offline_nach_tagen
        tage, jetzt = offline_nach_tagen(cfg), jetzt or datetime.now()
        zeilen = self.db.con.execute(
            """SELECT i.id, i.fahrzeug_id, i.verfuegbarkeit, i.zuletzt_bestaetigt, i.zuletzt_gesehen, a.status, a.gewerblich,
                      (SELECT p.zeitpunkt || '|' || p.id || '|' || p.preis FROM preis_historie p WHERE p.inserat_id = i.id ORDER BY p.zeitpunkt, p.id LIMIT 1),
                      (SELECT p.zeitpunkt || '|' || p.id || '|' || p.preis FROM preis_historie p WHERE p.inserat_id = i.id
                       ORDER BY p.zeitpunkt DESC, p.id DESC LIMIT 1)
               FROM inserate i LEFT JOIN anzeigen a ON i.plattform = COALESCE(NULLIF(a.quelle, ''), ?) AND i.anzeigen_id = a.id""",
            (STANDARD_PLATTFORM,)).fetchall()
        fahrzeuge: dict = {}
        for z in zeilen:
            fahrzeuge.setdefault(z[1] if z[1] is not None else f"i{z[0]}", []).append(z)
        verlaeufe = []
        for inserate in fahrzeuge.values():
            if any(z[6] != 0 for z in inserate):                       # gewerblich, unbekannt oder ohne Anzeige: nicht privat
                continue
            weg = [verfuegbarkeit(z[2], z[3], z[4], z[5], jetzt, tage) for z in inserate]
            if not all(v["nicht_verfuegbar"] or v["vermutlich_offline"] for v in weg):
                continue
            erste = [_eintrag(z[7]) for z in inserate if z[7]]
            letzte = [_eintrag(z[8]) for z in inserate if z[8]]
            if erste and letzte:
                verlaeufe.append((min(erste)[2], max(letzte)[2]))
        return preissenkungen(verlaeufe, float(cfg["rechner"]["abschlag_angebot_auf_privatwert"]))

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
