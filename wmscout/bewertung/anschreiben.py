from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..datenbank import STATUS, UNBEKANNT, VORLAEUFIG, import_art
from ..normalisierung.fahrzeug import ART_PLURAL

AMPEL_RANG = {"gruen": 0, "gelb": 1, "rot": 2, "grau": 3}
ART_EINZAHL = {"Sonstige": "Wohnmobil"}
# Wertfaktoren, die für Pflege stehen → Formulierung im Anschreiben („Schön, dass Sie … erwähnen“)
PFLEGE = {"Scheckheft": "das Scheckheft", "Dichtigkeitsprüfung": "die Dichtigkeitsprüfungen",
          "Garagen-/Hallenplatz": "den Hallen- bzw. Garagenstellplatz"}

# Worauf es je nach Fahrzeugalter ankommt – fließt als Satz und Foto-Wunschliste ins Anschreiben
ALTERS_STUFEN = [
    # (bis Jahre, Stufe, Prüfpunkte-Satz, Unterlagen/Fotos)
    (3, "jung",
     "Bei einem so jungen Fahrzeug interessiert mich vor allem, ob die jährlichen Dichtigkeitsprüfungen "
     "gemacht wurden und ob noch Hersteller- bzw. Dichtigkeitsgarantie besteht.",
     ["Fahrzeugschein (persönliche Daten gern abdecken)", "Nachweise der Dichtigkeitsprüfungen",
      "Garantie- bzw. Kaufunterlagen"]),
    (9, "mittel",
     "Bei einem Wohnmobil aus {ez} schaue ich vor allem auf die Wartungsnachweise (inkl. Zahnriemen, falls fällig), "
     "die Dichtigkeitsprüfungen und den Zustand des Aufbaus.",
     ["Fahrzeugschein (persönliche Daten gern abdecken)", "Serviceheft bzw. Wartungsrechnungen",
      "Protokolle der Dichtigkeitsprüfungen"]),
    (15, "aelter",
     "Bei Baujahr {ez} kommt es mir vor allem auf einen trockenen Aufbau, das Reifenalter und eine gültige "
     "Gasprüfung an.",
     ["Fahrzeugschein (persönliche Daten gern abdecken)", "Serviceheft", "Innenraum mit Ecken, Fenstern und Dachluken",
      "Reifen mit DOT-Nummer"]),
    (99, "alt",
     "Bei einem {alter} Jahre alten Fahrzeug sind Aufbau (Feuchtigkeit), Rahmen und Unterboden, Reifenalter und "
     "Gasanlage die entscheidenden Punkte.",
     ["Fahrzeugschein (persönliche Daten gern abdecken)", "Unterboden und Rahmen",
      "Innenraum mit Ecken, Fenstern und Dachluken", "Reifen mit DOT-Nummer"]),
]


def euro(x) -> str:
    return f"{int(x):,} €".replace(",", ".") if x is not None else "–"


def tsd(x) -> str:
    return f"{int(x):,}".replace(",", ".")


def aufzaehlung(teile: list[str]) -> str:
    teile = [t for t in teile if t]
    if len(teile) <= 1:
        return "".join(teile)
    return ", ".join(teile[:-1]) + " und " + teile[-1]


def sperrgrund(a: dict, cfg: dict) -> str | None:
    """Warum diese Anzeige nicht angeschrieben werden soll (oder None)."""
    f = cfg["filter"]
    if a.get("gewerblich"):
        return "gewerblicher Anbieter"
    if a.get("status") not in (None, "neu"):
        return f"Status: {STATUS.get(a['status'], a['status'])}"
    if a.get("duplikat"):
        return a["duplikat"]
    p = a.get("preis")
    if not p:
        return "kein Preis"
    if p < f["preis_min"] or p > f["preis_max"]:
        return "Preis außerhalb Filter"
    if a.get("ez_jahr") and a["ez_jahr"] < f["ez_ab_jahr"]:
        return "EZ zu alt"
    if a.get("km") and a["km"] > f["km_max"]:
        return "zu viele km"
    if f.get("max_entfernung_km") and (a.get("entfernung_km") or 0) > f["max_entfernung_km"]:
        return f"zu weit entfernt ({a['entfernung_km']} km)"
    _, herkunft = import_art(a.get("suche"))
    if herkunft == VORLAEUFIG:
        return ("Fahrzeugart nicht bestätigt (aus Titel/Suchbegriff) – über den Art-Filter suchen oder "
                "Detailseite einlesen")
    if herkunft == UNBEKANNT:
        return "Fahrzeugart unbekannt – Detailseite der Anzeige speichern und einlesen"
    text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung")).lower()
    for begriff in f["sperrbegriffe"]:
        if re.search(r"(?<!\w)" + re.escape(begriff.lower()), text):
            return f"Sperrbegriff „{begriff}“"
    return None


def kontext(a: dict, b, cfg: dict) -> dict:
    """Alle Felder für die Vorlage – passend zu Modell, Baujahr, Ausstattung und Bewertung."""
    c = cfg["anschreiben"]
    ez = a.get("ez_jahr")
    alter = date.today().year - ez if ez else None
    stufe, pruefpunkte, unterlagen = "unbekannt", "", ["Fahrzeugschein (persönliche Daten gern abdecken)",
                                                      "Serviceheft", "Aufbau innen"]
    if alter is not None:
        for bis, name, satz, liste in ALTERS_STUFEN:
            if alter <= bis:
                stufe, pruefpunkte, unterlagen = name, satz.format(ez=ez, alter=alter), liste
                break
    art = b.art if b else "Sonstige"
    jt = cfg["rechner"]["vergleich_jahre_toleranz"]
    if b and b.vergleich_anzahl and ez:
        preisbasis = (f"an vergleichbaren Angeboten ({ART_PLURAL.get(art, 'Wohnmobile')} der Baujahre "
                      f"{ez - jt}–{ez + jt})")
    elif ez:
        preisbasis = f"am aktuellen Marktniveau für {ART_PLURAL.get(art, 'Wohnmobile')} aus {ez}"
    else:
        preisbasis = "am aktuellen Marktniveau"
    ort = a.get("ort") or ""
    ausstattung = [n for n, w in (b.wertfaktoren if b else {}).items() if w > 0 and n not in PFLEGE and n != "Nichtraucher"]
    gepflegt = [satz for n, satz in PFLEGE.items() if b and (b.wertfaktoren or {}).get(n, 0) > 0]
    return dict(
        titel=a.get("titel") or "Ihr Wohnmobil", fahrzeug=a.get("fahrzeug") or "Wohnmobil",
        marke=a.get("marke"), modell=a.get("modell"), art=ART_EINZAHL.get(art, art),
        art_plural=ART_PLURAL.get(art, "Wohnmobile"), ez_jahr=ez, alter=alter, alters_stufe=stufe,
        km=a.get("km"), km_text=f"rund {tsd(round(a['km'], -3))} km" if a.get("km") else None,
        preis=a.get("preis"), vb=bool(a.get("vb")), ort_kurz=re.sub(r"^\d{5}\s*", "", ort) or "Ihrer Nähe",
        mit_angebot=bool(b and b.sicherheit != "keine" and b.erstangebot), erstangebot=b.erstangebot if b else None,
        max_ek=b.max_ek if b else None, ampel=b.ampel if b else "grau", preisbasis=preisbasis,
        pruefpunkte=pruefpunkte, unterlagen=aufzaehlung(unterlagen[:3]),
        ausstattung=aufzaehlung(ausstattung[:3]), gepflegt=aufzaehlung(gepflegt),
        firma=c["firma"], ansprechpartner=c["ansprechpartner"], telefon=c["telefon"], firmen_ort=c["ort"],
    )


def betrag_aus_text(text: str | None) -> int | None:
    """Angebotsbetrag aus einem gesendeten Anschreiben („… biete ich Ihnen … 32.300 € an“)."""
    treffer = re.findall(r"(\d{1,3}(?:\.\d{3})+|\d{4,6})\s*€\s+an\b", text or "")
    return int(treffer[-1].replace(".", "")) if treffer else None


def nachfass_kontext(a: dict, b, cfg: dict) -> dict:
    """Wie kontext(), plus Datum des Erstkontakts, Preissenkung und das jetzt passende Angebot."""
    k = kontext(a, b, cfg)
    kontaktiert = a.get("kontaktiert_am") or ""
    altes = a.get("angebot_betrag") or betrag_aus_text(a.get("anschreiben_text"))
    preis = a.get("preis")
    gesenkt = bool(a.get("preis_geaendert_am") and a["preis_geaendert_am"] > max(kontaktiert, a.get("nachgefasst_am") or ""))
    neu = b.erstangebot if b and b.sicherheit != "keine" else None
    if gesenkt and altes and preis and preis <= altes:
        fall, angebot = "zusage", preis
    elif altes and neu and neu > altes:
        fall, angebot = "erhoeht", neu
    elif altes or neu:
        fall, angebot = "steht", altes or neu
    else:
        fall, angebot = "ohne", None
    datum = f"{kontaktiert[8:10]}.{kontaktiert[5:7]}." if len(kontaktiert) >= 10 else None
    k.update(kontaktiert_datum=datum, preis_gesenkt=gesenkt, preis_vorher=a.get("preis_vorher"), angebot=angebot,
             fall=fall, nachfass_nr=(a.get("nachfass_anzahl") or 0) + 1)
    return k


class Anschreiber:
    def __init__(self, cfg: dict, basis: Path):
        self.gesamt_cfg = cfg
        self.cfg = cfg["anschreiben"]
        pfad = basis / self.cfg["vorlage"]
        nachfass_pfad = basis / (cfg.get("nachfassen") or {}).get("vorlage", "vorlagen/nachfassen.txt")
        env = Environment(loader=FileSystemLoader([str(pfad.parent), str(nachfass_pfad.parent)]),
                          undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False)
        env.filters["euro"] = euro
        env.filters["tsd"] = tsd
        self.vorlage = env.get_template(pfad.name)
        self.nachfass_vorlage = env.get_template(nachfass_pfad.name)

    def soll_schreiben(self, ampel: str) -> bool:
        return AMPEL_RANG.get(ampel, 3) <= AMPEL_RANG[self.cfg["ab_ampel"]]

    def text(self, a: dict, b) -> str:
        return self._aufraeumen(self.vorlage.render(**kontext(a, b, self.gesamt_cfg)))

    def nachfass(self, a: dict, b) -> tuple[str, int | None]:
        """(Nachfass-Text, darin genannter Betrag)"""
        k = nachfass_kontext(a, b, self.gesamt_cfg)
        return self._aufraeumen(self.nachfass_vorlage.render(**k)), k["angebot"]

    @staticmethod
    def _aufraeumen(t: str) -> str:
        t = re.sub(r"[ \t]+\n", "\n", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip()
