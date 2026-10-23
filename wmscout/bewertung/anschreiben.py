from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..domaene import STATUS, UNBEKANNT, VORLAEUFIG, import_art
from ..normalisierung.fahrzeug import ART_PLURAL, fahrzeug_bezeichnung
from ..normalisierung.person import profilname

AMPEL_RANG = {"gruen": 0, "gelb": 1, "rot": 2, "grau": 3}
ART_EINZAHL = {"Sonstige": "Wohnmobil"}
ART_DATIV = {"Teilintegrierter": "Teilintegrierten", "Integrierter": "Integrierten"}     # „zu Ihrem Teilintegrierten“
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


# Die Texte nennen, womit gerechnet wurde. Die vorläufige Art selbst steht in der Bewertung (b.art) direkt daneben.
# Bei unbekannter Art nennt der Text die Art, mit der vorsichtig gerechnet wurde; er beginnt immer gleich
# (HINWEIS_ART_UNBEKANNT_ANFANG), damit Report, Handy-App und Tests ihn wiedererkennen.
HINWEIS_ART_VORLAEUFIG = "Fahrzeugart nicht bestätigt (gerechnet mit der vorläufigen Art) – bitte prüfen"
HINWEIS_ART_UNBEKANNT = "Fahrzeugart unbekannt (gerechnet ohne Art; Ampel höchstens gelb, Brief ohne Betrag) – bitte prüfen"
HINWEIS_ART_UNBEKANNT_ANFANG = "Fahrzeugart unbekannt ("


def hinweis_art_unbekannt(art: str | None = None) -> str:
    """„… (vorsichtig gerechnet als Wohnwagen) …“ bzw. ohne Art (`Sonstige`/None) HINWEIS_ART_UNBEKANNT."""
    if art and art != "Sonstige":
        return f"Fahrzeugart unbekannt (vorsichtig gerechnet als {art}; Ampel höchstens gelb, Brief ohne Betrag) – bitte prüfen"
    return HINWEIS_ART_UNBEKANNT


HINWEIS_AUSLAND = "Ausland – Abholung, Überführung und Zulassung prüfen"
HINWEIS_ANBIETER_UNBEKANNT = "Anbieter unbekannt (privat oder gewerblich) – bitte vor dem Anschreiben prüfen"


def hinweis_ausland(land: str) -> str:
    return (f"{HINWEIS_AUSLAND} (Standort {land}; Entfernung und Transportkosten nicht berechnet – Ampel höchstens gelb, Brief ohne Betrag)")


def hinweise(a: dict, b=None) -> list[str]:
    """Hinweise zum Fahrzeug, die das Anschreiben NICHT sperren (Betreiberentscheidung 14.10.2026: möglichst jedes
    Wohnmobil anschreiben können). Bisher: Herkunft der Fahrzeugart bei importierten Seiten – ist sie nicht durch
    Art-Filter oder Detailseite bestätigt, steht sie nur im Titel bzw. fehlt, und die Bewertung rechnet mit der
    vorläufigen bzw. vorsichtig mit der Kandidaten-Art mit dem niedrigsten Max-EK (`b.art`, siehe
    auswertung.bewerte_anzeige). Crawler-Funde (Art aus der Suche) und bestätigte Arten tragen keinen Hinweis.
    Außerdem: Ort im Ausland (`a["ausland"]` – keine Entfernung, Transport ungewiss) und unbekannter Anbieter (`gewerblich` ist
    None, z. B. fehlender Anbieterkasten der Trefferliste) – beides sperrt nichts, steht aber sichtbar am Fahrzeug."""
    liste = []
    if a.get("verfuegbarkeit_hinweis"):                   # reserviert / vermutlich nicht mehr online (P3-04): sperrt nichts
        liste.append(a["verfuegbarkeit_hinweis"])
    _, herkunft = import_art(a.get("suche"))
    if herkunft == VORLAEUFIG:
        liste.append(HINWEIS_ART_VORLAEUFIG)
    elif herkunft == UNBEKANNT:
        liste.append(hinweis_art_unbekannt(b.art if b else None))
    if a.get("ausland"):
        liste.append(hinweis_ausland(a["ausland"]))
    if "gewerblich" in a and a["gewerblich"] is None:
        liste.append(HINWEIS_ANBIETER_UNBEKANNT)
    return liste


def art_bestaetigt(a: dict) -> bool:
    """Darf der Brief die Fahrzeugart nennen? Nicht bei importierten Seiten mit vorläufiger oder unbekannter Art –
    lieber neutral „Wohnmobil“ als dem Verkäufer eine falsche Art zu schreiben."""
    return import_art(a.get("suche"))[1] not in (VORLAEUFIG, UNBEKANNT)


def verkaeufer_name(a: dict) -> str | None:
    """Profilname des Verkäufers für die persönliche Anrede (aus `details_json`, nur von Detailseiten) oder None.

    Suchseiten zeigen keinen Personennamen. Der Name wird nur zur Anrede gespeichert; Kürzel, Badges und Typ-Angaben
    („HW“, „Privater Nutzer“) liefert der Parser nie, sie werden hier zur Sicherheit noch einmal geprüft."""
    try:
        roh = json.loads(a.get("details_json") or "{}").get("verkaeufer_name")
    except (ValueError, AttributeError, TypeError):
        return None
    return profilname(roh) if isinstance(roh, str) else None      # keine Listen/Zahlen („['Max']“) als Anrede


# Titel nur als eigenes Wort: danach Punkt, Leerzeichen oder Bindestrich („fr-meier“ → „Frau Meier“, nicht „Frau -Meier“)
_ANREDE_TITEL = re.compile(r"(?i)(herr|hr|frau|fr|familie|fam)(?:[.\s-]+|$)(.*)$")
_TITEL_LANG = {"herr": "Herr", "hr": "Herr", "frau": "Frau", "fr": "Frau", "familie": "Familie", "fam": "Familie"}


def anrede_name(roh) -> str | None:
    """Profilname, vorsichtig für „Hallo <Name>,“ aufbereitet – oder None (dann „Hallo,“).

    „Hr“/„Hr.“ → „Herr“, „Fr“/„Fr.“ → „Frau“, „Fam.“ → „Familie“; ein einzelnes kleingeschriebenes Wort (auch nach
    dem Titel) bekommt einen großen Anfangsbuchstaben („anton“ → „Anton“, „hr beispiel“ → „Herr Beispiel“). Sonst bleibt der
    Name unverändert – kein Raten von Geschlecht oder Schreibweise. Spitznamen mit Ziffern („camper77“) und ein Titel
    ohne Namen („Herr“) ergeben keine Anrede."""
    name = profilname(roh) if isinstance(roh, str) else None
    if not name or re.search(r"\d", name):
        return None
    titel, rest = None, name
    if m := _ANREDE_TITEL.match(name):
        titel, rest = _TITEL_LANG[m.group(1).lower()], m.group(2).strip()
    if not rest:
        return None
    if " " not in rest and rest.islower():
        rest = "-".join(t[:1].upper() + t[1:] for t in rest.split("-"))
    return f"{titel} {rest}" if titel else rest


def sperrgrund(a: dict, cfg: dict) -> str | None:
    """Warum diese Anzeige nicht angeschrieben werden soll (oder None). Die Fahrzeugart sperrt nicht – siehe hinweise(). Verkaufte und
    nicht mehr online stehende Anzeigen sind gesperrt; „reserviert“ und „vermutlich offline“ nicht (nur Hinweis)."""
    f = cfg["filter"]
    if a.get("gewerblich"):
        return "gewerblicher Anbieter"
    if a.get("verfuegbarkeit_sperre"):                    # verkauft oder offline (auch Altbestand-Status „gelöscht“), P3-04
        return a["verfuegbarkeit_sperre"]
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
    if f.get("max_entfernung_km") and a.get("ausland"):
        return f"Ausland ({a['ausland']}) – Entfernung nicht berechenbar"
    text = " ".join(str(a.get(k) or "") for k in ("titel", "kurzbeschreibung", "beschreibung")).lower()
    for begriff in f["sperrbegriffe"]:
        if re.search(r"(?<!\w)" + re.escape(begriff.lower()), text):
            return f"Sperrbegriff „{begriff}“"
    return None


def betrag_im_brief(a: dict, b) -> int | None:
    """Der Betrag, den der Brief nennt – oder None, wenn er keinen nennt. Eine Regel für Brief, Nachfass-Text und den
    beim Kontakt gespeicherten `angebot_betrag` (QA Q2-H1). F14: bei unbekannter Fahrzeugart (Import) kein Betrag, er
    könnte z. B. für einen Wohnwagen viel zu hoch sein."""
    if not (b and b.sicherheit != "keine" and b.erstangebot):
        return None
    if import_art(a.get("suche"))[1] == UNBEKANNT:
        return None
    if a.get("ausland"):                         # Ausland: Transportkosten nicht berechnet → kein Betrag (ADR-022)
        return None
    return b.erstangebot


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
    # Nicht bestätigte Art (Import) wird im Brief nicht genannt – auch nicht in der Preisbasis
    art = (b.art if b else "Sonstige") if art_bestaetigt(a) else "Sonstige"
    art_einzahl, art_plural = ART_EINZAHL.get(art, art), ART_PLURAL.get(art, "Wohnmobile")
    jt = cfg["rechner"]["vergleich_jahre_toleranz"]
    if b and b.vergleich_anzahl and ez:
        preisbasis = f"an vergleichbaren Angeboten ({art_plural} der Baujahre {ez - jt}–{ez + jt})"
    elif ez:
        preisbasis = f"am aktuellen Marktniveau für {art_plural} aus {ez}"
    else:
        preisbasis = "am aktuellen Marktniveau"
    ort = a.get("ort") or ""
    ausstattung = [n for n, w in (b.wertfaktoren if b else {}).items() if w > 0 and n not in PFLEGE and n != "Nichtraucher"]
    gepflegt = [satz for n, satz in PFLEGE.items() if b and (b.wertfaktoren or {}).get(n, 0) > 0]
    marke, modell = a.get("marke"), a.get("modell")
    fahrzeug = a.get("fahrzeug") or fahrzeug_bezeichnung(marke, modell)
    # Marke + Modell höchstens einmal (Einleitung); danach „Ihr <Art> von <Marke>“ – erkannte Modelle sind nicht immer
    # richtig, und „Ihr Hobby“/„Ihr Fiat“ allein wäre doppeldeutig (Marke = Wort bzw. Basisfahrzeug, QA N6-3)
    zum_fahrzeug = f"zum {fahrzeug}" if marke or modell else f"zu Ihrem {ART_DATIV.get(art, art_einzahl)}"
    name = anrede_name(verkaeufer_name(a))
    return dict(
        anrede=f"Hallo {name}," if name else "Hallo,", name=name,
        titel=a.get("titel") or "Ihr Wohnmobil", fahrzeug=fahrzeug, zum_fahrzeug=zum_fahrzeug,
        ihr_fahrzeug=f"Ihr {art_einzahl} von {marke}" if marke else f"Ihr {art_einzahl}",
        marke=marke, modell=modell, art=art_einzahl, art_plural=art_plural,
        ez_jahr=ez, alter=alter, alters_stufe=stufe,
        km=a.get("km"), km_text=f"rund {tsd(round(a['km'], -3))} km" if a.get("km") else None,
        preis=a.get("preis"), vb=bool(a.get("vb")),
        ort_kurz=re.sub(r"^(?:[A-Z]{1,3}-\d[\d ]*[A-Z]{0,2}|\d[\d ]*)(?:\s+|$)", "", ort) or "Ihrer Nähe",
        mit_angebot=betrag_im_brief(a, b) is not None,
        erstangebot=b.erstangebot if b else None,
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
    neu = betrag_im_brief(a, b)                  # nennt der Brief keinen Betrag, „steht“ auch keiner (Q2-H1)
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
