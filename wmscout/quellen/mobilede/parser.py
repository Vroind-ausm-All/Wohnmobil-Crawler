"""HTML-Parser für gespeicherte mobile.de-Suchseiten und -Anzeigenseiten (Stand 10/2026, Wohnmobil-Suche).

mobile.de rendert mit Next.js und CSS-Modulen: die Klassennamen (`_VdfyC`, `_CTFqZ` …) sind zufällige Hashes und
ändern sich mit jeder Auslieferung. Stabil sind die `data-testid`-Attribute – nach denen wird hier gelesen:

Trefferliste (`base-result-listing-N`; gesponserte Plätze: `tic-result-listing-N` „Top in Kategorie“ und
`top-result-listing-N` „Top of Page“, mit Abzeichen `sponsored-badge`):
  * `…-link` (href mit `details.html?id=<ID>`), `listing-title-card-view` (Titel), `price-label` (Preis; `price-vat-sup` =
    Fußnote „¹ MwSt. ausweisbar“), `price-negotiable` (Verhandlungsbasis),
  * `listing-details-attributes`: „Kastenwagen • 5.941 mm • Bis 3.300 kg • EZ 11/2015 • 87.350 km • 96 kW (131 PS) • Diesel“
    (Fahrzeugart zuerst, bei Neufahrzeugen steht davor der Zustand),
  * `seller-info`: erster Text „Privatanbieter“, „Gewerbe“ (Firmenfahrzeuge) oder der Händlername, dann „PLZ Ort“.
  * Fahrzeugklasse: Parameter `vc=` im Link (`Motorhome`, auch für Wohnwagen) bzw. Präfix der Filter-`data-testid`
    (`Motorhome-seller_type-filter-…`); Treffer anderer Klassen (Pkw: `vc=Car`, Kategorie „Limousine“ …) werden übersprungen.
Anzeigenseite: `vip-ad-title`, `vip-price-label`, `main-price-area`, `vip-technical-data-box` (dt/dd-Paare, u. a. „Kategorie“),
`vip-fsbo-box` (nur bei Privatanbietern), `seller-title-address`, `vip-vehicle-description-text`; ergänzend JSON-LD (`Car`,
`bodyType` „VanMotorhome“/„MotorHomesAndOther“). Als Wohnmobil gilt die Anzeige nur mit bekannter Kategorie bzw. Wohnmobil-`bodyType`.

Personenbezogene Angaben (Telefonnummer, Händler- und Verkäufer-IDs, Händlername, Anschrift) werden nicht gelesen: Der
Seitenquelltext enthält sie (z. B. im eingebetteten RSC-Datenstrom), gespeichert wird davon nichts. Ein Profilname wie bei
Kleinanzeigen existiert bei Privatanbietern auf mobile.de nicht.
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from ...anbieter import ANZEIGE
from ...normalisierung.fahrzeug import ist_basismarke, marke_aus_text, normalisiere_marke
from ..basis import ART_QUELLE_KATEGORIE

log = logging.getLogger("scout")

KENNUNG = "mobile.de"
ID_PRAEFIX = "md-"                      # Anzeigen-IDs sind Primärschlüssel über alle Quellen: Präfix verhindert Kollisionen
BASIS = "https://suchen.mobile.de"

_ID_IN_URL = re.compile(r"/details\.html\?(?:[^#]*&)?id=(\d{5,})(?!\d)", re.I)
_ZAHL = r"\d{1,3}(?:\.\d{3})+|\d+"
_PREIS = re.compile(rf"({_ZAHL})\s*€")
_KM = re.compile(rf"^({_ZAHL})\s*km$", re.I)
_EZ = re.compile(r"^EZ\s+(?:\d{1,2}/)?((?:19|20)\d{2})$")
_EZ_FELD = re.compile(r"(?:\d{1,2}/)?((?:19|20)\d{2})")
_LEISTUNG = re.compile(r"^\d+\s*kW\b")
_MASS = re.compile(rf"^({_ZAHL})\s*mm$", re.I)
_GEWICHT = re.compile(rf"^Bis\s+({_ZAHL})\s*kg$", re.I)
_LISTING = re.compile(r"^(base|tic|top)-result-listing-\d+$")
# „12345 Beispielstadt“, „DE-12345 Beispielstadt“, „SE-123 45 Beispielstadt“, „NL-1234AB Beispielstadt“ – Händler-Stichworte wie „4x4 Allrad“ nicht
_ORT = re.compile(r"^(?:[A-Z]{1,3}-)?\d{3,5}(?:\s?\d{2})?[A-Z]{0,2}\s+\S")
_KLASSE = re.compile(r"[?&;]vc=([A-Za-z]+)")
_KLASSE_WOHNMOBIL = "motorhome"

# Kategorie („Fahrzeugtyp“) laut mobile.de → Fahrzeugart des Scouts. „Wohnmobil andere“ und „Andere“ sind keine Art.
KATEGORIEN = {
    "alkoven": "Alkoven", "integrierter": "Integrierter", "teilintegrierter": "Teilintegrierter",
    "kastenwagen": "Kastenwagen", "wohnwagen": "Wohnwagen",
}
_KEINE_ART = {"wohnmobil andere", "andere"}
# Kategorien der Pkw-Suche (und anderer Klassen): nie ein Wohnmobil, auch wenn ein Widerspruch in der Seite stünde
_FREMDE_KATEGORIEN = {"limousine", "kombi", "kleinwagen", "cabrio", "cabrio/roadster", "coupé", "sportwagen/coupé",
                      "suv/geländewagen/pickup", "van/kleinbus", "kleinbus", "geländewagen", "pickup", "motorrad", "lkw"}
_ZUSTAND = {"neufahrzeug", "vorführfahrzeug", "tageszulassung", "jahreswagen", "gebrauchtfahrzeug", "oldtimer"}
# JSON-LD `bodyType` – nur der eindeutig belegte Wert; alles andere bleibt ohne Art
_BODY_TYPE = {"VanMotorhome": "Kastenwagen"}
_BODY_WOHNMOBIL = ("motorhome", "caravan", "camper")           # „VanMotorhome“, „MotorHomesAndOther“


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def anzeigen_id_aus_url(url: str | None) -> str | None:
    """'https://suchen.mobile.de/fahrzeuge/details.html?id=39000000&…' → 'md-39000000' (sonst None)."""
    m = _ID_IN_URL.search((url or "").replace("&amp;", "&"))
    return ID_PRAEFIX + m.group(1) if m else None


def detail_url(anzeigen_id: str) -> str:
    """Kurze Adresse der Anzeige ohne Such- und Tracking-Parameter (searchId, refId, utm_*)."""
    return f"{BASIS}/fahrzeuge/details.html?id={anzeigen_id.removeprefix(ID_PRAEFIX)}"


def _zahl(text: str) -> int:
    return int(text.replace(".", ""))


def _preis(text: str) -> int | None:
    m = _PREIS.search(text)
    return _zahl(m.group(1)) if m else None


def _ort(text: str | None) -> str | None:
    """'DE-12345 Beispielstadt' → '12345 Beispielstadt'; Auslandsorte behalten ihr Länderkürzel (keine deutsche PLZ)."""
    t = " ".join((text or "").split()).removeprefix("DE-")
    return t if _ORT.match(t) else None


def art_aus_kategorie(text: str | None) -> str | None:
    """Fahrzeugart aus der mobile.de-Kategorie, nur bei exakter Übereinstimmung („Wohnmobil andere“ → None)."""
    return KATEGORIEN.get(" ".join((text or "").split()).lower())


def _http_url(url: str | None) -> str | None:
    url = (url or "").strip()
    return url if re.match(r"https?://\S", url, re.I) else None


def _bild(block) -> str | None:
    """Direkte Bildadresse; gespeicherte Seiten verweisen auf lokale Dateien (…_files/…), die nichts nützen."""
    for img in block.select("img"):
        for kandidat in [img.get("src")] + [e.strip().split(" ")[0] for e in (img.get("srcset") or "").split(",") if e.strip()]:
            if url := _http_url(kandidat):
                return url
    return None


# ---------- Trefferliste ----------
def _attribute(text: str) -> dict:
    """Zeile „Kastenwagen • … • EZ 11/2015 • 87.350 km • 96 kW (131 PS) • Diesel“ in Felder zerlegen."""
    felder: dict = {"details": {}}
    tokens = [" ".join(t.split()) for t in text.split("•") if t.strip()]
    nach_leistung = False
    for n, t in enumerate(tokens):
        if (m := _EZ.match(t)):
            felder["ez_jahr"] = int(m.group(1))
        elif (m := _KM.match(t)):
            felder["km"] = _zahl(m.group(1))
        elif _LEISTUNG.match(t):
            felder["leistung"], nach_leistung = t, True
            continue
        elif (m := _MASS.match(t)):
            felder["details"]["laenge_mm"] = _zahl(m.group(1))
        elif (m := _GEWICHT.match(t)):
            felder["details"]["zul_gesamtgewicht_kg"] = _zahl(m.group(1))
        elif t.lower() in _ZUSTAND:
            felder["details"]["zustand"] = t
        elif t.lower() in KATEGORIEN or t.lower() in _KEINE_ART:
            felder.setdefault("kategorie", t)
        elif nach_leistung and "kraftstoff" not in felder["details"]:
            felder["details"]["kraftstoff"] = t
        elif n < 2 and "kategorie_roh" not in felder:
            felder["kategorie_roh"] = t                         # unbekannte Kategorie (Pkw: „Limousine“) – nur zur Klassenprüfung
        nach_leistung = False
    return felder


def ist_wohnmobil_klasse(klasse: str | None, kategorie: str | None) -> bool:
    """Gehört ein Treffer zur Wohnmobil-Suche (Wohnmobile und Wohnwagen)? `klasse` = Fahrzeugklasse (`vc=` im Link bzw. Präfix der
    Filter-Testids der Seite), `kategorie` = erster Eintrag der Attributzeile. Mit Klasse entscheidet sie (nur „Motorhome“), außer die
    Kategorie ist eindeutig fremd; ohne Klasse zählt nur eine bekannte Kategorie (inkl. „Wohnmobil andere“)."""
    k = " ".join((kategorie or "").split()).lower()
    bekannt = k in KATEGORIEN or k in _KEINE_ART
    if klasse:
        return klasse.lower() == _KLASSE_WOHNMOBIL and k not in _FREMDE_KATEGORIEN
    return bekannt


def _anbieter(block) -> tuple[bool | None, str | None]:
    """(gewerblich, Ort) aus `seller-info`: erster Text „Privatanbieter“ = privat, alles andere („Gewerbe“, Händlername) =
    gewerblich; ohne Kasten (None, None). Der Name eines Händlers wird nicht übernommen."""
    kasten = block.select_one("[data-testid=seller-info]")
    for el in (kasten.find_all(True) if kasten else []):
        spans = el.find_all("span", recursive=False)
        if len(spans) >= 2 and _text(spans[0]):
            return _text(spans[0]).lower() != "privatanbieter", _ort(_text(spans[1]))
    return None, None


def _fahrzeugklasse(link) -> str | None:
    """Fahrzeugklasse aus dem Link des Treffers (`vc=Motorhome`; `vc=Car` bei Pkw)."""
    m = _KLASSE.search((link.get("href") if link else "").replace("&amp;", "&"))
    return m.group(1) if m else None


def _seitenklasse(soup) -> str | None:
    """Fahrzeugklasse der ganzen Suchseite aus dem Präfix der Filter-Testids („Motorhome-seller_type-filter-…“)."""
    el = soup.find(attrs={"data-testid": re.compile(r"^[A-Za-z]+-seller_type-filter")})
    return el["data-testid"].split("-", 1)[0] if el else None


def _parse_treffer(block, ohne_id: list, fremd: dict, ohne_anbieter: list, seitenklasse: str | None = None) -> dict | None:
    link = block.select_one("a[href*='details.html']")
    ad_id = anzeigen_id_aus_url(link.get("href") if link else None)
    titel = _text(block.select_one("[data-testid=listing-title-card-view]"))
    if not ad_id:
        ohne_id.append(titel or "?")
        return None
    felder = _attribute(_text(block.select_one("[data-testid=listing-details-attributes]")))
    details = felder.pop("details")
    kategorie = felder.pop("kategorie", None)
    klasse = _fahrzeugklasse(link) or seitenklasse
    if not ist_wohnmobil_klasse(klasse, kategorie or felder.get("kategorie_roh")):
        fremd[ad_id] = kategorie or felder.get("kategorie_roh") or klasse or "?"
        return None
    if kategorie:
        details["kategorie"] = kategorie
    art = art_aus_kategorie(kategorie)
    if art:
        details["art_quelle"] = ART_QUELLE_KATEGORIE                # bestätigt die Art beim Import (importer._speichere_seite)
    if block.select_one("[data-testid=price-vat-sup]"):
        details["mwst_ausweisbar"] = True                     # Fußnote „¹ MwSt. ausweisbar“ (gewerbliche Anbieter)
    if block.select_one("[data-testid=sponsored-badge]"):
        details["gesponsert"] = True
    gewerblich, ort = _anbieter(block)
    if gewerblich is None:
        ohne_anbieter.append(ad_id)
    if gewerblich is None and block.select_one("[data-testid=price-vat-sup]"):
        gewerblich = True                                         # ohne Anbieterkasten: „MwSt. ausweisbar“ gibt es nur bei Gewerblichen
    return {
        "id": ad_id,
        "url": detail_url(ad_id),
        "titel": titel,
        "preis": _preis(_text(block.select_one("[data-testid=price-label]"))),      # „39.900 € ¹“: Fußnote stört nicht
        "vb": block.select_one("[data-testid=price-negotiable]") is not None,
        "ort": ort,
        "km": felder.get("km"),
        "ez_jahr": felder.get("ez_jahr"),
        "marke": marke_aus_text(titel),
        "art": art,
        "leistung": felder.get("leistung"),
        "bild": _bild(block),
        "gewerblich": gewerblich,
        "anbieter_herkunft": None if gewerblich is None else ANZEIGE,     # Anbieterkasten bzw. „MwSt. ausweisbar“
        "details": details,
    }


def parse_suchseite(html: str) -> list[dict]:
    """Treffer einer gespeicherten Suchseite (siehe `parse_suchseite_mit_hinweisen`)."""
    return parse_suchseite_mit_hinweisen(html)[0]


def parse_suchseite_mit_hinweisen(html: str) -> tuple[list[dict], list[str]]:
    """(Treffer, Hinweise) einer gespeicherten Suchseite: reguläre und gesponserte Plätze, je Anzeige einmal, in Seitenreihenfolge.
    Karussells („Highlights“, „Ähnliche Fahrzeuge“) sind keine Treffer. Nichts wird still verworfen – die Hinweise (und das Log) nennen
      * Treffer ohne Anzeigen-ID,
      * Treffer anderer Fahrzeugklassen (Pkw …): nur Wohnmobile und Wohnwagen werden übernommen (`ist_wohnmobil_klasse`),
      * fehlende Anbieterkästen (Anbieter unbekannt; mehr als die Hälfte der Treffer: Seitenlayout vermutlich geändert)."""
    soup = BeautifulSoup(html, "html.parser")
    seitenklasse = _seitenklasse(soup)
    ergebnisse, gesehen, ohne_id, fremd, ohne_anbieter = [], set(), [], {}, []
    for block in soup.find_all(attrs={"data-testid": _LISTING}):
        treffer = _parse_treffer(block, ohne_id, fremd, ohne_anbieter, seitenklasse)
        if treffer and treffer["id"] not in gesehen:
            gesehen.add(treffer["id"])
            ergebnisse.append(treffer)
    hinweise = []
    if ohne_id:
        hinweise.append(f"mobile.de-Suchseite: {len(ohne_id)} Treffer ohne Anzeigen-ID übersprungen (z. B. „{ohne_id[0]}“) – "
                        "Seitenaufbau geändert?")
    if fremd:
        beispiel = next(iter(fremd.values()))
        hinweise.append(f"mobile.de-Suchseite: {len(fremd)} Treffer ohne Wohnmobil-Kategorie übersprungen (z. B. „{beispiel}“) – "
                        "eingelesen werden nur Wohnmobile und Wohnwagen")
    ohne = len(set(ohne_anbieter))
    if ohne:
        gesamt = len(ergebnisse)
        if ohne * 2 > gesamt:
            hinweise.append(f"mobile.de-Suchseite: bei {ohne} von {gesamt} Treffern fehlt der Anbieterkasten (seller-info) – vermutlich "
                            "wurde das Seitenlayout geändert; Anbieter und Ort sind unbekannt (Selektoren: "
                            "wmscout/quellen/mobilede/parser.py)")
        else:
            hinweise.append(f"mobile.de-Suchseite: bei {ohne} von {gesamt} Treffern fehlt der Anbieterkasten – Anbieter (privat/gewerblich) "
                            "unbekannt, Hinweis am Fahrzeug")
    for h in hinweise:
        log.warning(h)
    return ergebnisse, hinweise


# ---------- Anzeigenseite ----------
def _ld_car(soup) -> dict:
    """Der JSON-LD-Eintrag `Car` (Name, Marke, Preis, Kilometer, bodyType) – Rückfall, falls das Markup nicht trägt."""
    for skript in soup.select('script[type="application/ld+json"]'):
        try:
            daten = json.loads(skript.string or skript.get_text() or "")
        except ValueError:
            continue
        for eintrag in daten if isinstance(daten, list) else [daten]:
            if isinstance(eintrag, dict) and eintrag.get("@type") == "Car":
                return eintrag
    return {}


def _technische_daten(soup) -> dict[str, str]:
    """Label → Wert aus `vip-technical-data-box` (Paare dt/dd), plus „Ausstattung“."""
    daten: dict[str, str] = {}
    box = soup.select_one("[data-testid=vip-technical-data-box]")
    for dt in box.find_all("dt") if box else []:
        dd = dt.find_next_sibling("dd")
        if _text(dt) and dd is not None:
            daten[_text(dt)] = _text(dd)
    if ausstattung := [_text(li) for li in soup.select("[data-testid=vip-features-list] li")]:
        daten["Ausstattung"] = ", ".join(a for a in ausstattung if a)
    return daten


def _anbieter_detail(soup) -> tuple[bool | None, str | None]:
    """(gewerblich, Ort) einer Anzeigenseite. Privat: Kasten `vip-fsbo-box` bzw. Kopfzeile „Privatanbieter“ in
    `seller-title-address`; steht dort etwas anderes, gilt der Anbieter als gewerblich; ohne beides (None, Ort)."""
    kopf = soup.select_one("[data-testid=seller-title-address]")
    kinder = kopf.find_all("div", recursive=False) if kopf else []
    typ = _text(kinder[0]).lower() if kinder else ""
    ort = _ort(_text(soup.select_one("[data-testid=vip-fsbo-box-seller-address2]")) or (_text(kinder[1]) if len(kinder) > 1 else ""))
    if soup.select_one("[data-testid=vip-fsbo-box]") is not None or typ == "privatanbieter":
        return False, ort
    return (True if typ else None), ort


def _detail_klasse(daten: dict, ld: dict) -> tuple[bool, str | None]:
    """(Wohnmobil/Wohnwagen?, Kategorie bzw. Karosserie als Text). Die Kategorie der Technischen Daten entscheidet: bekannt (inkl.
    „Wohnmobil andere“) = ja, bekannt fremd („Limousine“) = nein; eine unbekannte Kategorie nur mit Wohnmobil-`bodyType` im JSON-LD.
    Ohne Kategorie zählt allein der `bodyType`; ohne beides ist die Klasse nicht ermittelbar (= nein)."""
    kategorie = " ".join(str(daten.get("Kategorie") or "").split())
    body = str(ld.get("bodyType") or "")
    body_ok = any(w in body.lower() for w in _BODY_WOHNMOBIL)
    if kategorie:
        k = kategorie.lower()
        if k in KATEGORIEN or k in _KEINE_ART:
            return True, kategorie
        return (body_ok and k not in _FREMDE_KATEGORIEN), kategorie
    return body_ok, body or None


def parse_detailseite(html: str) -> dict:
    """Merkmale einer gespeicherten Anzeigenseite. Die Anzeigen-ID steht nicht im Text, sondern in der Adresse im Seitenkopf
    (siehe wmscout/eingang/seiten.py); `anzeigen_id` ist deshalb immer None. `wohnmobil` (bool) und `klasse_text` sagen, ob die
    Anzeige ein Wohnmobil/Wohnwagen ist (`_detail_klasse`); beide Felder gehören nicht ins `Inserat`."""
    soup = BeautifulSoup(html, "html.parser")
    daten = _technische_daten(soup)
    ld = _ld_car(soup)

    titel = _text(soup.select_one("[data-testid=vip-ad-title]")) or " ".join(str(ld.get("name") or "").split())
    beschreibung = _text(soup.select_one("[data-testid=vip-vehicle-description-text]"))
    preis_bereich = _text(soup.select_one("[data-testid=main-price-area]"))
    ld_preis = ld["offers"].get("price") if isinstance(ld.get("offers"), dict) else None
    preis = _preis(_text(soup.select_one("[data-testid=vip-price-label]"))) or (
        int(ld_preis) if isinstance(ld_preis, (int, float)) else None)
    km_feld = re.match(rf"^({_ZAHL})\s*km$", daten.get("Kilometerstand", ""), re.I)
    km = _zahl(km_feld.group(1)) if km_feld else None
    if km is None and isinstance(ld.get("mileageFromOdometer"), dict):
        wert = ld["mileageFromOdometer"].get("value")
        km = int(wert) if isinstance(wert, (int, float)) else None
    ez = _EZ_FELD.search(daten.get("Erstzulassung", "")) or _EZ_FELD.search(daten.get("Baujahr", ""))
    marke = normalisiere_marke((ld.get("brand") or {}).get("name") if isinstance(ld.get("brand"), dict) else None)
    if not marke or ist_basismarke(marke):                    # Aufbauhersteller aus dem Titel schlägt das Basisfahrzeug
        marke = marke_aus_text(titel) or marke_aus_text(beschreibung) or marke
    art = art_aus_kategorie(daten.get("Kategorie")) or (_BODY_TYPE.get(ld.get("bodyType")) if not daten.get("Kategorie") else None)
    gewerblich, ort = _anbieter_detail(soup)
    wohnmobil, klasse_text = _detail_klasse(daten, ld)
    if "MwSt. ausweisbar" in _text(soup.select_one("[data-testid=vip-price-box]")) + preis_bereich:
        daten["MwSt. ausweisbar"] = "ja"
        if gewerblich is None:
            gewerblich = True                                     # ohne Anbieterangabe: „MwSt. ausweisbar“ gibt es nur bei Gewerblichen

    return {
        "anzeigen_id": None,
        "titel": titel or None,
        "preis": preis,
        "vb": "Verhandlungsbasis" in preis_bereich,
        "ort": ort,
        "beschreibung": beschreibung,
        "km": km,
        "ez_jahr": int(ez.group(1)) if ez else None,
        "marke": marke or None,
        "art": art,
        "leistung": daten.get("Leistung") or None,
        "getriebe": daten.get("Getriebe") or None,
        "gewerblich": gewerblich,
        "details": daten,
        "wohnmobil": wohnmobil,
        "klasse_text": klasse_text,
    }
