"""Händler-Einkaufspreis-Rechner mit fairer Marktwert-Schätzung.

Alle Parameter stehen in config.yaml → rechner.

1. Referenzwert (Modell)  = Neupreis heute (Art × Markenklasse) × Restwert(Alter)
                            × km-Faktor (Laufleistung im Vergleich zum Alter) × Wertfaktoren (Ausstattung/Mängel)
2. Marktniveau            = Referenzwert × Marktfaktor
     Marktfaktor          = gewichteter Median von (Preis ÷ Referenzwert) vergleichbarer Privatangebote
                            (gleiche Art, EZ ± Toleranz, ähnliche km; gleiche Marke zählt doppelt).
                            Jeder Vergleich wird so auf Alter, km und Ausstattung DIESES Fahrzeugs
                            umgerechnet. Bei wenigen Vergleichen wird zum Referenzwert hin gemittelt:
                            Gewicht Markt = n / (n + k).
3. Marktwert privat       = Marktniveau × (1 − Abschlag Angebot→Abschluss)
   Händler-VK             = Marktwert privat × (1 + Händleraufschlag)
   Kosten                 = Aufbereitung + HU/Gas + Transport + Standzeit
                            + Gewährleistungsrücklage (% vom VK) + Reparaturrisiko (Alter, km)
   Ziel-Marge             = max(Marge % × VK, Mindestmarge)
4. §25a (Differenzbesteuerung):  Gewinn = (VK − EK) × 100/119 − Kosten
        → Max-EK = VK − (Marge + Kosten) × 1,19
   Regelbesteuerung:             Gewinn = VK / 1,19 − EK − Kosten
        → Max-EK = VK / 1,19 − Kosten − Marge
5. Erstangebot            = Max-EK × Erstangebot-Faktor, aber mindestens Fair-Untergrenze × Marktwert privat
                            (höchstens Max-EK) – damit kein Verkäufer ein Lockangebot bekommt.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from ..normalisierung.fahrzeug import art_schluessel

# Fallbacks, falls config.yaml (ältere Version) den Abschnitt nicht enthält
STANDARD_MARKTMODELL = {
    "neupreis_art": {"Kastenwagen": 62000, "Teilintegrierter": 82000, "Alkoven": 76000, "Integrierter": 118000,
                     "Wohnwagen": 30000, "Sonstige": 65000},
    "markenklassen": [
        {"name": "Premium", "faktor": 1.35, "marken": ["Carthago", "Concorde", "Morelo", "Niesmann", "Frankia"]},
        {"name": "Gehoben", "faktor": 1.12, "marken": ["Hymer", "Rapido", "Malibu", "Eura Mobil", "Laika", "Westfalia",
                                                        "Volkswagen", "Bimobil", "Kabe"]},
        {"name": "Einstieg", "faktor": 0.90, "marken": ["Sunlight", "Carado", "McLouis", "Rimor", "Roller Team",
                                                         "Elnagh", "Benimar", "Sun Living", "Etrusco", "Ahorn",
                                                         "Weinsberg"]},
    ],
    "restwert": {0: 0.88, 1: 0.83, 2: 0.78, 3: 0.74, 5: 0.67, 7: 0.61, 10: 0.52, 12: 0.46, 15: 0.38, 20: 0.27,
                 25: 0.19, 30: 0.14},
    "km_pro_jahr_ueblich": 10000,
    "km_abschlag_pro_10000": 0.015,
    "km_zuschlag_pro_10000": 0.01,
    "km_korrektur_max": 0.12,
    "unsicherheit_ohne_vergleich": 0.15,
}
NEGATION_DAVOR = re.compile(r"\b(?:kein\w*|ohne|nicht|nie|null|frei von)\b(?P<luecke>[^.!?\n]{0,40})$", re.I)
NEGATION_DANACH = re.compile(r"^\w*frei\b|^\s*[:=\-–]?\s*(?:kein\w*|ohne|nicht vorhanden|nein\b|0\s*%)", re.I)


@dataclass
class Bewertung:
    marktwert_angebote: int | None          # geschätztes Marktniveau (Angebotspreise)
    vergleich_anzahl: int
    vergleich_basis: str
    marktwert_privat: int
    haendler_vk: int
    kosten: int
    kosten_posten: dict = field(default_factory=dict)
    ziel_marge: int = 0
    max_ek: int = 0
    erstangebot: int = 0
    angebotspreis: int | None = None
    verhaeltnis: float | None = None
    ampel: str = "grau"
    potenzial: int | None = None            # Gewinn, wenn zum Angebotspreis gekauft würde
    # Transparenz für eine faire Bewertung
    modellwert: int | None = None           # Referenzwert ohne Marktdaten
    marktfaktor: float | None = None        # Markt ÷ Referenz (1,00 = Referenz)
    markt_gewicht: float = 0.0              # Anteil der Vergleichsangebote an der Schätzung
    vergleich_marke: int = 0                # davon gleiche Marke
    wertfaktoren: dict = field(default_factory=dict)
    km_korrektur: float = 0.0
    sicherheit: str = "keine"               # hoch | mittel | niedrig | manuell | keine
    spanne_von: int | None = None           # plausible Spanne des Marktniveaus
    spanne_bis: int | None = None
    fair_anteil: float | None = None        # Erstangebot ÷ Marktwert privat
    max_anteil: float | None = None         # Max-EK ÷ Marktwert privat
    fair_hinweis: str | None = None
    art: str = "Sonstige"
    alter: int | None = None

    def dict(self):
        return asdict(self)


def _runde(x: float, auf: int = 50) -> int:
    return int(round(x / auf) * auf)


def interpoliere(tabelle: dict, x: float) -> float:
    punkte = sorted((float(k), float(v)) for k, v in tabelle.items())
    if x <= punkte[0][0]:
        return punkte[0][1]
    for (x0, y0), (x1, y1) in zip(punkte, punkte[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    # über das Tabellenende hinaus mit der letzten Steigung, aber nie unter 5 %
    (x0, y0), (x1, y1) = punkte[-2], punkte[-1]
    return max(0.05, y1 + (y1 - y0) * (x - x1) / (x1 - x0))


def gewichtetes_quantil(werte: list[tuple[float, float]], q: float) -> float:
    """werte = [(wert, gewicht)]"""
    werte = sorted(werte)
    gesamt = sum(g for _, g in werte)
    lauf = 0.0
    for w, g in werte:
        lauf += g
        if lauf >= q * gesamt:
            return w
    return werte[-1][0]


class Rechner:
    def __init__(self, cfg: dict, stichtag: datetime | None = None):
        """``stichtag`` (lokale Zeit): Alter und „alte Anzeige“ relativ zu diesem Zeitpunkt statt zu jetzt – damit eine gespeicherte
        Kalkulation später exakt nachgerechnet werden kann (Phase E, ``kalkulation``). Ohne Stichtag unverändert „heute“."""
        self.c = cfg["rechner"]
        self.stichtag = stichtag
        self.mm = {**STANDARD_MARKTMODELL, **(self.c.get("marktmodell") or {})}
        wf = self.c.get("wertfaktoren") or {}
        self.wf_max_plus = wf.get("max_plus", 0.06)
        self.wf_max_minus = wf.get("max_minus", 0.15)
        self.wf_liste = [(e["name"], float(e["wert"]), re.compile(r"(?<!\w)(?:" + e["muster"] + ")", re.I))
                         for e in wf.get("liste", [])]
        self.marken_faktor = {m.lower(): k["faktor"] for k in self.mm["markenklassen"] for m in k["marken"]}
        self.heute = stichtag.date() if stichtag else date.today()
        self._cache: dict[str, tuple] = {}

    # ---------- Bausteine ----------
    def art(self, a: dict) -> str:
        return art_schluessel(a.get("suche"), a.get("art"), a.get("titel"))

    def alter(self, a: dict) -> int | None:
        return max(0, self.heute.year - a["ez_jahr"]) if a.get("ez_jahr") else None

    def km_korrektur(self, km: int | None, alter: int) -> float:
        """+/− Anteil: weniger km als für das Alter üblich erhöht den Wert, mehr senkt ihn."""
        if not km:
            return 0.0
        erwartet = max(1, alter) * self.mm["km_pro_jahr_ueblich"]
        diff = (km - erwartet) / 10000
        k = -diff * (self.mm["km_abschlag_pro_10000"] if diff > 0 else self.mm["km_zuschlag_pro_10000"])
        grenze = self.mm["km_korrektur_max"]
        return max(-grenze, min(grenze, k))

    def wertfaktoren(self, a: dict) -> dict:
        """Ausstattung (+) und genannte Mängel (−) aus Titel/Beschreibung; verneinte Nennungen zählen nicht."""
        text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung", "getriebe"))
        gefunden = {}
        for name, wert, muster in self.wf_liste:
            for m in muster.finditer(text):
                davor = NEGATION_DAVOR.search(text[max(0, m.start() - 60):m.start()])
                # Eine Verneinung gilt bis zum Satzende – bei Ausstattung (+) nur bis zum nächsten Komma:
                # „keine Risse, Feuchtigkeit oder Rost“ (alles verneint) vs. „keine Feuchtigkeit, Scheckheft“
                if davor and not re.search(r"aber|jedoch|leider|allerdings" + (r"|[,;]" if wert > 0 else ""),
                                           davor.group("luecke"), re.I):
                    continue                  # „keine Feuchtigkeit“, „ohne Rost“
                if NEGATION_DANACH.search(text[m.end():m.end() + 20]):
                    continue                  # „feuchtigkeitsfrei“, „Rost: keiner“
                gefunden[name] = wert
                break
        plus = sum(w for w in gefunden.values() if w > 0)
        minus = sum(w for w in gefunden.values() if w < 0)
        # Deckelung anteilig, damit die Summe die Grenzen nicht überschreitet
        fp = min(1.0, self.wf_max_plus / plus) if plus else 1
        fm = min(1.0, self.wf_max_minus / -minus) if minus else 1
        return {n: round(w * (fp if w > 0 else fm), 4) for n, w in gefunden.items()}

    def modellwert(self, a: dict) -> tuple[float | None, float, dict]:
        """(Referenzwert, km-Korrektur, Wertfaktoren) – gecacht je Anzeige."""
        schluessel = a.get("id")
        if schluessel and schluessel != "manuell" and schluessel in self._cache:
            return self._cache[schluessel]
        alter = self.alter(a)
        if alter is None:
            erg = (None, 0.0, {})
        else:
            neu = self.mm["neupreis_art"].get(self.art(a), self.mm["neupreis_art"].get("Sonstige", 65000))
            neu *= self.marken_faktor.get((a.get("marke") or "").lower(), 1.0)
            kmk = self.km_korrektur(a.get("km"), alter)
            wf = self.wertfaktoren(a)
            wert = neu * interpoliere(self.mm["restwert"], alter) * (1 + kmk) * (1 + sum(wf.values()))
            erg = (wert, kmk, wf)
        if schluessel and schluessel != "manuell":
            self._cache[schluessel] = erg
        return erg

    # ---------- Vergleichsbasis ----------
    def vergleiche(self, a: dict, alle: list[dict]) -> list[tuple[float, float, bool]]:
        """[(Preis ÷ Referenzwert, Gewicht, gleiche Marke)] für vergleichbare Angebote."""
        jt, kt = self.c["vergleich_jahre_toleranz"], self.c["vergleich_km_toleranz"]
        art, marke, serie = self.art(a), (a.get("marke") or "").lower(), (a.get("serie") or "").lower()
        alt_grenze = ((self.stichtag or datetime.now()) - timedelta(days=180)).isoformat(timespec="seconds")
        erg = []
        for b in alle:
            if b.get("id") == a.get("id") or not b.get("preis") or b["preis"] < 1000 or b.get("gewerblich"):
                continue
            if not b.get("ez_jahr") or abs(b["ez_jahr"] - a["ez_jahr"]) > jt or self.art(b) != art:
                continue
            dkm = abs(b["km"] - a["km"]) if a.get("km") and b.get("km") else None
            if dkm is not None and dkm > kt:
                continue
            ref = self.modellwert(b)[0]
            if not ref:
                continue
            gleich = bool(marke) and (b.get("marke") or "").lower() == marke
            g = (1.0 if gleich else 0.5) / (1 + 0.5 * abs(b["ez_jahr"] - a["ez_jahr"]))
            if gleich and serie and (b.get("serie") or "").lower() == serie:
                g *= 1.5                     # gleiche Modellreihe (z. B. „Sky TI“) ist der beste Vergleich
            if dkm is not None:
                g /= 1 + dkm / kt
            if (b.get("zuletzt_gesehen") or "9") < alt_grenze:
                g *= 0.5                     # alte Anzeigen spiegeln den aktuellen Markt schlechter
            erg.append((b["preis"] / ref, g, gleich))
        if len(erg) >= 5:                    # Ausreißer (Tippfehler, Fantasiepreise) nach Tukey entfernen
            ungewichtet = [(r, 1) for r, _, _ in erg]
            q1, q3 = gewichtetes_quantil(ungewichtet, .25), gewichtetes_quantil(ungewichtet, .75)
            iqr = max(q3 - q1, 0.05 * gewichtetes_quantil(ungewichtet, .5))   # Mindestbreite bei sehr einheitlichen Preisen
            erg = [e for e in erg if q1 - 1.5 * iqr <= e[0] <= q3 + 1.5 * iqr]
        return erg

    # ---------- Kosten ----------
    def transport(self, a: dict) -> float:
        """Abholung nach Entfernung (Grundpauschale + €/km), ohne bekannte Entfernung die Pauschale."""
        k = self.c["kosten"]
        km = a.get("entfernung_km")
        if km is None or "transport_pro_km" not in k:
            return k["transport_pauschal"]
        return k.get("transport_grundpauschale", 0) + km * k["transport_pro_km"]

    def kosten(self, a: dict, vk: float) -> dict:
        k = self.c["kosten"]
        posten = {
            "Aufbereitung": k["aufbereitung"],
            "HU / Gasprüfung": k["hu_gasprüfung"],
            (f"Abholung ({a['entfernung_km']} km)" if a.get("entfernung_km") is not None else "Transport"):
                self.transport(a),
            "Standkosten": k["standkosten_pro_monat"] * k["standzeit_monate"],
            "Gewährleistungsrücklage": vk * k["gewährleistung_rücklage_prozent"],
        }
        alter = self.alter(a)
        alter = 12 if alter is None else alter
        for stufe in k["reparatur_risiko"]:
            if alter <= stufe["bis_jahre"]:
                posten[f"Reparaturrisiko ({alter} J.)"] = stufe["betrag"]
                break
        if a.get("km") and a["km"] > k["km_zuschlag_ab"]:
            posten["km-Zuschlag"] = (a["km"] - k["km_zuschlag_ab"]) / 10000 * k["km_zuschlag_pro_10000"]
        return {n: _runde(v, 10) for n, v in posten.items()}

    # ---------- Marktniveau ----------
    def marktniveau(self, a: dict, alle: list[dict]) -> dict:
        ref, kmk, wf = self.modellwert(a)
        info = {"modellwert": _runde(ref) if ref else None, "km_korrektur": kmk, "wertfaktoren": wf,
                "art": self.art(a), "alter": self.alter(a)}
        if not ref:
            return {**info, "niveau": a.get("preis"), "n": 0, "n_marke": 0, "faktor": None, "gewicht": 0.0,
                    "sicherheit": "keine", "spanne": None,
                    "basis": "Erstzulassung fehlt – keine unabhängige Bewertung, daher keine Beträge (Marktwert manuell eingeben)"}
        vgl = self.vergleiche(a, alle)
        n, n_marke = len(vgl), sum(1 for v in vgl if v[2])
        u = self.mm["unsicherheit_ohne_vergleich"]
        g = n / (n + self.c.get("vergleich_gewicht_k", 4))
        if n:
            paare = [(r, w) for r, w, _ in vgl]
            m = gewichtetes_quantil(paare, .5)
            streu = (gewichtetes_quantil(paare, .75) - gewichtetes_quantil(paare, .25)) / 2 / m if n >= 3 else u
        else:
            m, streu = 1.0, u
        faktor = g * m + (1 - g) * 1.0
        niveau = ref * faktor
        s = g * streu + (1 - g) * u
        if n >= max(8, self.c["vergleich_min_anzahl"]) and s <= 0.12:
            sicherheit = "hoch"
        elif n >= self.c["vergleich_min_anzahl"]:
            sicherheit = "mittel"
        else:
            sicherheit = "niedrig"
        if n:
            basis = (f"{n} Vergleichsangebote {info['art']}, EZ ± {self.c['vergleich_jahre_toleranz']} J."
                     f" ({n_marke} gleiche Marke) · Markt {g:.0%} / Referenzmodell {1 - g:.0%}")
        else:
            basis = "noch keine Vergleichsangebote – Referenzmodell (Neupreis × Restwert), bitte gegenprüfen"
        return {**info, "niveau": niveau, "n": n, "n_marke": n_marke, "faktor": round(faktor, 3), "gewicht": round(g, 2),
                "sicherheit": sicherheit, "spanne": (niveau * (1 - s), niveau * (1 + s)), "basis": basis}

    # ---------- Hauptrechnung ----------
    def bewerte(self, a: dict, alle: list[dict] | None = None, marktwert_manuell: int | None = None) -> Bewertung:
        mn = self.marktniveau(a, alle or [])
        if marktwert_manuell:
            mn.update(niveau=marktwert_manuell, n=0, n_marke=0, gewicht=0.0, sicherheit="manuell", spanne=None,
                      basis="manuell eingegebener Marktwert")
        if mn["sicherheit"] == "keine":
            # P1-12: ohne Erstzulassung gibt es keinen unabhängigen Marktwert. Max-EK und Erstangebot aus dem Angebotspreis
            # des Verkäufers zu rechnen, hieße seinen Wunschpreis zu bestätigen – daher keine Beträge, bis ein Marktwert vorliegt.
            return Bewertung(None, 0, mn["basis"], 0, 0, 0, angebotspreis=a.get("preis"), sicherheit="keine", art=mn["art"],
                             wertfaktoren=mn["wertfaktoren"])
        if not mn["niveau"]:
            return Bewertung(None, 0, "kein Preis", 0, 0, 0, angebotspreis=a.get("preis"))

        mw_privat = mn["niveau"] * (1 - self.c["abschlag_angebot_auf_privatwert"])
        vk = mw_privat * (1 + self.c["aufschlag_haendler_vk"])
        posten = self.kosten(a, vk)
        kosten = sum(posten.values())
        marge = max(vk * self.c["ziel_marge_prozent"], self.c["ziel_marge_min"])

        if self.c["differenzbesteuerung"]:
            max_ek = vk - (marge + kosten) * 1.19
        else:
            max_ek = vk / 1.19 - kosten - marge
        max_ek = max(0, max_ek)

        erst, fair_hinweis = self.erstangebot(max_ek, mw_privat, a.get("preis"))

        b = Bewertung(
            marktwert_angebote=_runde(mn["niveau"]), vergleich_anzahl=mn["n"], vergleich_basis=mn["basis"],
            marktwert_privat=_runde(mw_privat), haendler_vk=_runde(vk, 100), kosten=_runde(kosten),
            kosten_posten=posten, ziel_marge=_runde(marge), max_ek=_runde(max_ek, 100),
            erstangebot=_runde(erst, 100), angebotspreis=a.get("preis"),
            modellwert=mn["modellwert"], marktfaktor=mn["faktor"], markt_gewicht=mn["gewicht"],
            vergleich_marke=mn["n_marke"], wertfaktoren=mn["wertfaktoren"], km_korrektur=round(mn["km_korrektur"], 3),
            sicherheit=mn["sicherheit"], art=mn["art"], alter=mn["alter"], fair_hinweis=fair_hinweis,
        )
        if mn["spanne"]:
            b.spanne_von, b.spanne_bis = _runde(mn["spanne"][0], 100), _runde(mn["spanne"][1], 100)
        if b.marktwert_privat:
            b.fair_anteil = round(b.erstangebot / b.marktwert_privat, 3)
            b.max_anteil = round(b.max_ek / b.marktwert_privat, 3)
        if b.angebotspreis and b.max_ek and b.sicherheit != "keine":
            b.verhaeltnis = round(b.angebotspreis / b.max_ek, 3)
            amp = self.c["ampel"]
            b.ampel = "gruen" if b.verhaeltnis <= amp["gruen_bis"] else "gelb" if b.verhaeltnis <= amp["gelb_bis"] else "rot"
            b.potenzial = _runde(self.gewinn_bei_ek(vk, kosten, b.angebotspreis))
        return b

    def erstangebot(self, max_ek: float, mw_privat: float, wunschpreis: int | None) -> tuple[float, str | None]:
        """Verhandlungsspielraum ja, Lockangebot nein – und nie mehr als der Verkäufer verlangt."""
        faktor = self.c["erstangebot_faktor"]
        anteil = self.c.get("fair_untergrenze_privatwert", 0)
        erst, hinweis = max_ek * faktor, None
        if erst < mw_privat * anteil:
            erst = min(mw_privat * anteil, max_ek)
            hinweis = (f"Erstangebot auf die Fair-Untergrenze ({anteil:.0%} vom Marktwert privat) angehoben"
                       if erst < max_ek else
                       "Max-EK liegt unter der Fair-Untergrenze – Erstangebot = Max-EK, kein Verhandlungsspielraum "
                       "(Fixkosten wiegen bei diesem Preisniveau schwer)")
        if wunschpreis and erst > wunschpreis:
            erst, hinweis = wunschpreis * faktor ** 0.5, None
            if wunschpreis < mw_privat * 0.85:
                hinweis = (f"Wunschpreis liegt {1 - wunschpreis / mw_privat:.0%} unter dem geschätzten Marktwert privat – "
                           "Zustand und Angaben besonders genau prüfen (oder schnell sein)")
        return erst, hinweis

    def gewinn_bei_ek(self, vk: float, kosten: float, ek: float) -> float:
        if self.c["differenzbesteuerung"]:
            return (vk - ek) * 100 / 119 - kosten if vk > ek else vk - ek - kosten
        return vk / 1.19 - ek - kosten
