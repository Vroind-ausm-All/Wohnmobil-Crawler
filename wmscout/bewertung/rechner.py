"""Händler-Einkaufspreis-Rechner mit fairer Marktwert-Schätzung.

Alle Parameter stehen in config.yaml → rechner.

1. Referenzwert (Modell)  = Neupreis heute (Art × Markenklasse) × Restwert(Alter)
                            × km-Faktor (Laufleistung im Vergleich zum Alter) × Wertfaktoren (Ausstattung/Mängel)
2. Marktniveau            = Referenzwert × Marktfaktor
     Marktfaktor          = gewichteter Median von (Preis ÷ Referenzwert) vergleichbarer Privatangebote
                            (gleiche Art, EZ ± Toleranz, ähnliche km), nach Ähnlichkeit gewichtet (P5-02, ADR-053):
                            gleiches Modell > gleiche Modellreihe > gleiche Marke > gleiche Markenklasse > andere,
                            dazu Fahrzeugklasse (Länge, Basisfahrzeug), Baujahr-, km-Abstand und Alter der Anzeige.
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

from ..normalisierung.fahrzeug import MARKEN, art_schluessel, basisfahrzeug_aus_text, ist_basismarke, ist_werks_camper, laenge_aus_text

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
# Ähnlichkeit der Vergleichsangebote (P5-02, ADR-053); config.yaml → rechner.vergleich_aehnlichkeit überschreibt einzelne Werte
STANDARD_AEHNLICHKEIT = {
    "modell": 2.5,             # gleiche Marke und gleiches Modell samt Grundriss („Sky TI 650 MEG“)
    "reihe": 1.8,              # gleiche Marke und Modellreihe („Sky TI“)
    "marke": 1.0,              # gleiche Marke
    "klasse": 0.7,             # andere Marke derselben Markenklasse (Premium/Gehoben/Mittel/Einstieg)
    "andere": 0.5,             # andere Marke, Marke unbekannt oder nur das Basisfahrzeug (Fiat, Mercedes …)
    "laenge_pro_meter": 0.4,   # je Meter Längenunterschied −40 % (nur wenn beide Längen bekannt) …
    "laenge_min": 0.4,         # … aber höchstens auf 40 %
    "basis_anders": 0.8,       # anderes Basisfahrzeug (nur wenn beide bekannt)
    "anteil_max": 0.25,        # kein einzelnes Angebot trägt mehr als 25 % des Gesamtgewichts (bei weniger als 4 Vergleichen: alle gleich)
}
STUFEN = {"modell": ("gleiches Modell", "gleiches Modell"), "reihe": ("gleiche Modellreihe", "gleiche Modellreihe"),
          "marke": ("gleiche Marke", "gleiche Marke"), "klasse": ("gleiche Markenklasse", "gleiche Markenklasse"),
          "andere": ("andere Marke", "andere Marken")}
_AUFBAU_MARKEN = {m.lower() for m in MARKEN}


def gedeckelt(gewichte: list[float], anteil: float) -> list[float]:
    """Gewichte so begrenzen, dass keines mehr als ``anteil`` der Summe trägt (bei n < 1/anteil: alle gleich). Die größten werden auf
    einen gemeinsamen Wert gesetzt, die übrigen bleiben – so kann ein einzelnes sehr ähnliches Angebot den Markt nicht überstimmen."""
    n = len(gewichte)
    if not n:
        return []
    anteil = max(anteil, 1 / n)
    absteigend = sorted(range(n), key=lambda i: -gewichte[i])
    rest = sum(gewichte)
    for k in range(n):                             # k größte gedeckelt: x = anteil · (k·x + Rest) → x = anteil · Rest / (1 − k·anteil)
        x = anteil * rest / (1 - k * anteil) if k * anteil < 1 else float("inf")
        if gewichte[absteigend[k]] <= x:
            erg = list(gewichte)
            for i in absteigend[:k]:
                erg[i] = x
            return erg
        rest -= gewichte[absteigend[k]]
    return [1.0] * n
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
    vergleich_marke: int = 0                # davon gleiche Marke (Modell, Modellreihe oder nur Marke)
    vergleich_stufen: dict = field(default_factory=dict)    # Anzahl je Ähnlichkeitsstufe (P5-02)
    fahrzeugklasse: dict = field(default_factory=dict)      # erkannte Länge / Basisfahrzeug dieses Fahrzeugs
    # P5-03 (ADR-054): Spannen statt Punktwerte, Abschlag bei unbekannter Marke, Mängelliste
    max_ek_von: int | None = None           # Max-EK am unteren / oberen Ende der Marktspanne (auf 500 € gerundet)
    max_ek_bis: int | None = None
    privat_von: int | None = None           # Marktwert privat als Spanne (auf 500 € gerundet)
    privat_bis: int | None = None
    abschlag_marke: float = 0.0             # Abschlag auf den Händler-VK, weil die Aufbaumarke unbekannt ist
    maengel: list = field(default_factory=list)              # [{name, wert}] im Inserat genannte Mängel (negative Wertfaktoren)
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


def _nach_aussen(von: float, bis: float, auf: int = 500) -> tuple[int, int]:
    """Untere Grenze ab-, obere aufrunden (mindestens eine Stufe breit, außer beide 0)."""
    unten, oben = int(von // auf * auf), int(-(-bis // auf) * auf)
    return unten, max(oben, unten + auf) if oben else 0


def _maengel(wertfaktoren: dict) -> list[dict]:
    """Im Inserat genannte Mängel (negative Wertfaktoren), der schwerste zuerst."""
    return [{"name": n, "wert": w} for n, w in sorted(wertfaktoren.items(), key=lambda x: (x[1], x[0])) if w < 0]


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



def privatangebot(b: dict) -> bool:
    """Gehört ``b`` in die Vergleichsbasis „Marktwert privat“? Gewerbliche und Angebote mit unbekanntem Anbieter (Schlüssel ``gewerblich`` mit
    None) nicht. Fehlt der Schlüssel ganz (gespeicherte Kalkulations-Eingaben, die unbekannte Werte weglassen; ältere Aufrufer), gilt wie
    bisher „privat“ – so rechnen alte Kalkulationen unverändert nach."""
    return not b.get("gewerblich") and not ("gewerblich" in b and b["gewerblich"] is None)


class Vergleichsliste(list):
    """Vergleichsangebote mit Vorfilter (P3-07, R12): einmal je Liste nach (Fahrzeugart, Erstzulassungsjahr) einsortiert – nur Angebote, die die
    datenabhängigen Bedingungen von ``Rechner.vergleiche`` überhaupt erfüllen können (Preis ab 1.000 €, Privatangebot, Jahr bekannt). ``kandidaten``
    liefert die Angebote des Jahresfensters in der ursprünglichen Reihenfolge; ``vergleiche`` prüft sie danach vollständig wie bisher – das Ergebnis
    ist identisch, nur ohne den Durchlauf über alle Inserate je bewerteter Anzeige. Ein Jahr, das keine ganze Zahl ist (z. B. 2015.5 oder Text),
    landet in einer Restliste, die immer mitgeprüft wird. Jede Änderung der Liste verwirft den Index; Änderungen an den Einträgen selbst nicht –
    die Einträge nach dem Anlegen nicht verändern."""

    _index: dict | None = None
    _rest: list = []

    def kandidaten(self, art: str, ez_jahr: int, toleranz: int) -> list[dict]:
        if self._index is None:
            index: dict[tuple, list] = {}
            rest = []
            for pos, b in enumerate(self):
                if b.get("preis") and b["preis"] >= 1000 and privatangebot(b) and b.get("ez_jahr"):
                    j = b["ez_jahr"]
                    if isinstance(j, int) or (isinstance(j, float) and j.is_integer()):
                        index.setdefault((art_schluessel(b.get("suche"), b.get("art"), b.get("titel")), int(j)), []).append((pos, b))
                    else:
                        rest.append((pos, b))
            self._index, self._rest = index, rest
        treffer = [t for j in range(ez_jahr - toleranz, ez_jahr + toleranz + 1) for t in self._index.get((art, j), ())] + self._rest
        return [b for _, b in sorted(treffer, key=lambda t: t[0])]

    def _veraendert(name):                                     # jede Änderung der Liste verwirft den Index
        def methode(self, *a, **k):
            self._index = None
            return getattr(list, name)(self, *a, **k)
        methode.__name__ = name
        return methode

    for _name in ("__setitem__", "__delitem__", "__iadd__", "__imul__", "append", "extend", "insert", "pop", "remove", "sort", "reverse", "clear"):
        locals()[_name] = _veraendert(_name)
    del _name, _veraendert


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
        self.marken_klasse = {m.lower(): k["name"] for k in self.mm["markenklassen"] for m in k["marken"]}
        self.ae = {**STANDARD_AEHNLICHKEIT, **(self.c.get("vergleich_aehnlichkeit") or {})}
        self.heute = stichtag.date() if stichtag else date.today()
        self._cache: dict[str, tuple] = {}
        self._klassen: dict[str, dict] = {}

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

    def fahrzeugklasse(self, a: dict) -> dict:
        """Länge (m) und Basisfahrzeug aus Titel und Beschreibung – gecacht je Anzeige wie der Referenzwert."""
        schluessel = a.get("id")
        if schluessel and schluessel != "manuell" and schluessel in self._klassen:
            return self._klassen[schluessel]
        text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung"))
        erg = {"laenge": laenge_aus_text(text), "basis": basisfahrzeug_aus_text(text)}
        if schluessel and schluessel != "manuell":
            self._klassen[schluessel] = erg
        return erg

    def klasse_der_marke(self, marke: str) -> str | None:
        """Markenklasse aus ``marktmodell.markenklassen``; bekannte Aufbauhersteller ohne Eintrag (Faktor 1,0) bilden die Klasse „Mittel“."""
        return self.marken_klasse.get(marke) or ("Mittel" if marke in _AUFBAU_MARKEN else None)

    def aehnlichkeit(self, a: dict, b: dict) -> tuple[float, str]:
        """(Gewicht, Stufe) aus Marke/Modellreihe/Modell und Fahrzeugklasse; Baujahr, km und Anzeigenalter kommen in ``vergleiche`` dazu."""
        marke = "" if self.marke_unbekannt(a) else (a.get("marke") or "").lower()   # Fiat/Ducato sagt nichts über den Aufbau
        gleich = bool(marke) and (b.get("marke") or "").lower() == marke
        if gleich:
            modell, serie = (a.get("modell") or "").lower(), (a.get("serie") or "").lower()
            if modell and modell != serie and (b.get("modell") or "").lower() == modell:          # nur mit Grundriss „gleiches Modell“
                stufe = "modell"
            elif serie and (b.get("serie") or "").lower() == serie:
                stufe = "reihe"
            else:
                stufe = "marke"
        else:
            klasse = self.klasse_der_marke(marke)
            stufe = "klasse" if klasse and self.klasse_der_marke((b.get("marke") or "").lower()) == klasse else "andere"
        g = self.ae[stufe]
        ka, kb = self.fahrzeugklasse(a), self.fahrzeugklasse(b)
        if ka["laenge"] and kb["laenge"]:
            g *= max(self.ae["laenge_min"], 1 - self.ae["laenge_pro_meter"] * abs(ka["laenge"] - kb["laenge"]))
        if ka["basis"] and kb["basis"] and ka["basis"] != kb["basis"]:
            g *= self.ae["basis_anders"]
        return g, stufe

    # ---------- Vergleichsbasis ----------
    # Nur Privatangebote; ein Angebot mit unbekanntem Anbieter (``gewerblich`` ausdrücklich None) zählt nicht als privat (P2-05d, ADR-043)
    def vergleiche(self, a: dict, alle: list[dict]) -> list[tuple[float, float, bool, str]]:
        """[(Preis ÷ Referenzwert, Gewicht, gleiche Marke, Ähnlichkeitsstufe)] für vergleichbare Angebote."""
        jt, kt = self.c["vergleich_jahre_toleranz"], self.c["vergleich_km_toleranz"]
        art = self.art(a)
        alt_grenze = ((self.stichtag or datetime.now()) - timedelta(days=180)).isoformat(timespec="seconds")
        if isinstance(alle, Vergleichsliste) and isinstance(a.get("ez_jahr"), int) and isinstance(jt, int):
            alle = alle.kandidaten(art, a["ez_jahr"], jt)                  # Vorfilter; die Prüfungen unten bleiben vollständig
        erg = []
        for b in alle:
            if b.get("id") == a.get("id") or not b.get("preis") or b["preis"] < 1000 or not privatangebot(b):
                continue
            if not b.get("ez_jahr") or abs(b["ez_jahr"] - a["ez_jahr"]) > jt or self.art(b) != art:
                continue
            dkm = abs(b["km"] - a["km"]) if a.get("km") and b.get("km") else None
            if dkm is not None and dkm > kt:
                continue
            ref = self.modellwert(b)[0]
            if not ref:
                continue
            g, stufe = self.aehnlichkeit(a, b)
            g /= 1 + 0.5 * abs(b["ez_jahr"] - a["ez_jahr"])
            if dkm is not None:
                g /= 1 + dkm / kt
            if (b.get("zuletzt_gesehen") or "9") < alt_grenze:
                g *= 0.5                     # alte Anzeigen spiegeln den aktuellen Markt schlechter
            erg.append((b["preis"] / ref, g, stufe in ("modell", "reihe", "marke"), stufe))
        if len(erg) >= 5:                    # Ausreißer (Tippfehler, Fantasiepreise) nach Tukey entfernen
            ungewichtet = [(r, 1) for r, *_ in erg]
            q1, q3 = gewichtetes_quantil(ungewichtet, .25), gewichtetes_quantil(ungewichtet, .75)
            iqr = max(q3 - q1, 0.05 * gewichtetes_quantil(ungewichtet, .5))   # Mindestbreite bei sehr einheitlichen Preisen
            erg = [e for e in erg if q1 - 1.5 * iqr <= e[0] <= q3 + 1.5 * iqr]
        gewichte = gedeckelt([e[1] for e in erg], self.ae["anteil_max"])   # QA P5-02 B1: kein Einzelangebot überstimmt den Markt
        return [(e[0], g, *e[2:]) for e, g in zip(erg, gewichte, strict=True)]

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
                "art": self.art(a), "alter": self.alter(a), "klasse": {k: v for k, v in self.fahrzeugklasse(a).items() if v}}
        if not ref:
            return {**info, "niveau": a.get("preis"), "n": 0, "n_marke": 0, "stufen": {}, "faktor": None, "gewicht": 0.0,
                    "sicherheit": "keine", "spanne": None,
                    "basis": "Erstzulassung fehlt – keine unabhängige Bewertung, daher keine Beträge (Marktwert manuell eingeben)"}
        vgl = self.vergleiche(a, alle)
        n, n_marke = len(vgl), sum(1 for v in vgl if v[2])
        stufen = {s: c for s in STUFEN if (c := sum(1 for v in vgl if v[3] == s))}
        u = self.mm["unsicherheit_ohne_vergleich"]
        g = n / (n + self.c.get("vergleich_gewicht_k", 4))
        if n:
            paare = [(r, w) for r, w, *_ in vgl]
            m = gewichtetes_quantil(paare, .5)
            gleich_gewichtet = [(r, 1) for r, _ in paare]       # Streuung ungewichtet als Untergrenze: Gewichte dürfen die Sicherheit nicht heben
            streu = max((gewichtetes_quantil(p, .75) - gewichtetes_quantil(p, .25)) / 2 / gewichtetes_quantil(p, .5)
                        for p in (paare, gleich_gewichtet)) if n >= 3 else u
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
            teile = ", ".join(f"{c} {STUFEN[s][c != 1]}" for s, c in stufen.items())
            basis = (f"{n} Vergleichsangebote {info['art']}, EZ ± {self.c['vergleich_jahre_toleranz']} J."
                     f" ({teile}; ähnlichere zählen mehr) · Markt {g:.0%} / Referenzmodell {1 - g:.0%}")
        else:
            basis = "noch keine Vergleichsangebote – Referenzmodell (Neupreis × Restwert), bitte gegenprüfen"
        if info["klasse"]:
            k = info["klasse"]
            basis += " · Fahrzeugklasse: " + ", ".join(
                ([f"{k['laenge']:.2f} m".replace(".", ",")] if "laenge" in k else []) + ([k["basis"]] if "basis" in k else []))
        return {**info, "niveau": niveau, "n": n, "n_marke": n_marke, "stufen": stufen, "faktor": round(faktor, 3), "gewicht": round(g, 2),
                "sicherheit": sicherheit, "spanne": (niveau * (1 - s), niveau * (1 + s)), "basis": basis}

    # ---------- Hauptrechnung ----------
    def bewerte(self, a: dict, alle: list[dict] | None = None, marktwert_manuell: int | None = None) -> Bewertung:
        mn = self.marktniveau(a, alle or [])
        if marktwert_manuell:
            mn.update(niveau=marktwert_manuell, n=0, n_marke=0, stufen={}, gewicht=0.0, sicherheit="manuell", spanne=None,
                      basis="manuell eingegebener Marktwert")
        if mn["sicherheit"] == "keine":
            # P1-12: ohne Erstzulassung gibt es keinen unabhängigen Marktwert. Max-EK und Erstangebot aus dem Angebotspreis
            # des Verkäufers zu rechnen, hieße seinen Wunschpreis zu bestätigen – daher keine Beträge, bis ein Marktwert vorliegt.
            return Bewertung(None, 0, mn["basis"], 0, 0, 0, angebotspreis=a.get("preis"), sicherheit="keine", art=mn["art"],
                             wertfaktoren=mn["wertfaktoren"], maengel=_maengel(self.wertfaktoren(a)))   # Mängel auch ohne Beträge
        if not mn["niveau"]:
            return Bewertung(None, 0, "kein Preis", 0, 0, 0, angebotspreis=a.get("preis"))

        k = self.kette(a, mn["niveau"])
        mw_privat, vk, posten, kosten, marge, max_ek = k["mw_privat"], k["vk"], k["posten"], k["kosten"], k["marge"], k["max_ek"]

        erst, fair_hinweis = self.erstangebot(max_ek, mw_privat, a.get("preis"))

        b = Bewertung(
            marktwert_angebote=_runde(mn["niveau"]), vergleich_anzahl=mn["n"], vergleich_basis=mn["basis"],
            marktwert_privat=_runde(mw_privat), haendler_vk=_runde(vk, 100), kosten=_runde(kosten),
            kosten_posten=posten, ziel_marge=_runde(marge), max_ek=_runde(max_ek, 100),
            erstangebot=_runde(erst, 100), angebotspreis=a.get("preis"),
            modellwert=mn["modellwert"], marktfaktor=mn["faktor"], markt_gewicht=mn["gewicht"],
            vergleich_marke=mn["n_marke"], vergleich_stufen=mn["stufen"], fahrzeugklasse=mn["klasse"], wertfaktoren=mn["wertfaktoren"],
            km_korrektur=round(mn["km_korrektur"], 3),
            sicherheit=mn["sicherheit"], art=mn["art"], alter=mn["alter"], fair_hinweis=fair_hinweis,
        )
        b.abschlag_marke = k["abschlag"]
        b.maengel = _maengel(mn["wertfaktoren"])
        if mn["spanne"]:
            b.spanne_von, b.spanne_bis = _runde(mn["spanne"][0], 100), _runde(mn["spanne"][1], 100)
            unten, oben = self.kette(a, mn["spanne"][0]), self.kette(a, mn["spanne"][1])
            # Spannen auf 500 € nach außen gerundet – umschließen den Punktwert immer, keine falsche Genauigkeit (P5-03, QA B2);
            # Punktwerte bleiben für Ampel und Brief
            b.max_ek_von, b.max_ek_bis = _nach_aussen(unten["max_ek"], oben["max_ek"])
            b.privat_von, b.privat_bis = _nach_aussen(unten["mw_privat"], oben["mw_privat"])
        if b.marktwert_privat:
            b.fair_anteil = round(b.erstangebot / b.marktwert_privat, 3)
            b.max_anteil = round(b.max_ek / b.marktwert_privat, 3)
        if b.angebotspreis and b.max_ek and b.sicherheit != "keine":
            b.verhaeltnis = round(b.angebotspreis / b.max_ek, 3)
            amp = self.c["ampel"]
            b.ampel = "gruen" if b.verhaeltnis <= amp["gruen_bis"] else "gelb" if b.verhaeltnis <= amp["gelb_bis"] else "rot"
            b.potenzial = _runde(self.gewinn_bei_ek(vk, kosten, b.angebotspreis))
        return b

    def marke_unbekannt(self, a: dict) -> bool:
        """Keine Aufbaumarke erkennbar – nur „Wohnmobil“ oder nur das Basisfahrzeug (Fiat, Mercedes …); Werks-Camper (VW California,
        Mercedes Marco Polo, Ford Nugget) haben eine Marke."""
        return not a.get("marke") or (ist_basismarke(a.get("marke")) and not ist_werks_camper(a.get("marke"), a.get("modell")))

    def kette(self, a: dict, niveau: float) -> dict:
        """Marktniveau → Marktwert privat → Händler-VK (abzüglich Abschlag bei unbekannter Marke) → Kosten, Marge, Max-EK (ungerundet)."""
        mw_privat = niveau * (1 - self.c["abschlag_angebot_auf_privatwert"])
        abschlag = float(self.c.get("abschlag_marke_unbekannt", 0.05)) if self.marke_unbekannt(a) else 0.0
        vk = mw_privat * (1 + self.c["aufschlag_haendler_vk"]) * (1 - abschlag)
        posten = self.kosten(a, vk)
        kosten = sum(posten.values())
        marge = max(vk * self.c["ziel_marge_prozent"], self.c["ziel_marge_min"])
        max_ek = vk - (marge + kosten) * 1.19 if self.c["differenzbesteuerung"] else vk / 1.19 - kosten - marge
        return {"mw_privat": mw_privat, "vk": vk, "posten": posten, "kosten": kosten, "marge": marge, "max_ek": max(0, max_ek),
                "abschlag": abschlag}

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
