"""HTML-Parser für gespeicherte mobile.de-Suchseiten und -Anzeigenseiten (Stand 10/2026, Wohnmobil-Suche).

mobile.de rendert mit Next.js und CSS-Modulen: die Klassennamen (`_VdfyC`, `_CTFqZ` …) sind zufällige Hashes und
ändern sich mit jeder Auslieferung. Stabil sind die `data-testid`-Attribute – nach denen wird hier gelesen:

Trefferliste (`base-result-listing-N`; gesponserte Plätze: `tic-result-listing-N` „Top in Kategorie“ und
`top-result-listing-N` „Top of Page“, mit Abzeichen `sponsored-badge`):
  * `…-link` (href mit `details.html?id=<ID>`), `listing-title-card-view` (Titel), `price-label` (Preis; `price-vat-sup` =
    Fußnote „¹ MwSt. ausweisbar“), `price-negotiable` (Verhandlungsbasis),
  * `listing-details-attributes`: „Kastenwagen • 5.292 mm • Bis 3.000 kg • EZ 05/2012 • 132.000 km • 103 kW (140 PS) • Diesel“
    (Fahrzeugart zuerst, bei Neufahrzeugen steht davor der Zustand),
  * `seller-info`: erster Text „Privatanbieter“, „Gewerbe“ (Firmenfahrzeuge) oder der Händlername, dann „PLZ Ort“.
Anzeigenseite: `vip-ad-title`, `vip-price-label`, `main-price-area`, `vip-technical-data-box` (dt/dd-Paare, u. a. „Kategorie“),
`vip-fsbo-box` (nur bei Privatanbietern), `seller-title-address`, `vip-vehicle-description-text`; ergänzend JSON-LD (`Car`).

Personenbezogene Angaben (Telefonnummer, Händler- und Verkäufer-IDs, Händlername, Anschrift) werden nicht gelesen: Der
Seitenquelltext enthält sie (z. B. im eingebetteten RSC-Datenstrom), gespeichert wird davon nichts. Ein Profilname wie bei
Kleinanzeigen existiert bei Privatanbietern auf mobile.de nicht.
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from ...normalisierung.fahrzeug import ist_basismarke, marke_aus_text, normalisiere_marke

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
_ORT = re.compile(r"^(?:[A-Z]{1,3}-)?\d")        # „12345 Beispielstadt“, „DE-12345 Beispielstadt“, „SE-437 41 Beispielstadt“

# Kategorie („Fahrzeugtyp“) laut mobile.de → Fahrzeugart des Scouts. „Wohnmobil andere“ und „Andere“ sind keine Art.
KATEGORIEN = {
    "alkoven": "Alkoven", "integrierter": "Integrierter", "teilintegrierter": "Teilintegrierter",
    "kastenwagen": "Kastenwagen", "wohnwagen": "Wohnwagen",
}
_KEINE_ART = {"wohnmobil andere", "andere"}
_ZUSTAND = {"neufahrzeug", "vorführfahrzeug", "tageszulassung", "jahreswagen", "gebrauchtfahrzeug", "oldtimer"}
# JSON-LD `bodyType` – nur der eindeutig belegte Wert; alles andere bleibt ohne Art
_BODY_TYPE = {"VanMotorhome": "Kastenwagen"}


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
    return url if url.startswith("http") else None


def _bild(block) -> str | None:
    """Direkte Bildadresse; gespeicherte Seiten verweisen auf lokale Dateien (…_files/…), die nichts nützen."""
    for img in block.select("img"):
        for kandidat in [img.get("src")] + [e.strip().split(" ")[0] for e in (img.get("srcset") or "").split(",") if e.strip()]:
            if url := _http_url(kandidat):
                return url
    return None


# ---------- Trefferliste ----------
def _attribute(text: str) -> dict:
    """Zeile „Kastenwagen • … • EZ 05/2012 • 132.000 km • 103 kW (140 PS) • Diesel“ in Felder zerlegen."""
    felder: dict = {"details": {}}
    tokens = [" ".join(t.split()) for t in text.split("•") if t.strip()]
    nach_leistung = False
    for t in tokens:
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
        nach_leistung = False
    return felder


def _anbieter(block) -> tuple[bool | None, str | None]:
    """(gewerblich, Ort) aus `seller-info`: erster Text „Privatanbieter“ = privat, alles andere („Gewerbe“, Händlername) =
    gewerblich; ohne Kasten (None, None). Der Name eines Händlers wird nicht übernommen."""
    kasten = block.select_one("[data-testid=seller-info]")
    for el in (kasten.find_all(True) if kasten else []):
        spans = el.find_all("span", recursive=False)
        if len(spans) >= 2 and _text(spans[0]):
            return _text(spans[0]).lower() != "privatanbieter", _ort(_text(spans[1]))
    return None, None


def _parse_treffer(block, ohne_id: list) -> dict | None:
    link = block.select_one("a[href*='details.html']")
    ad_id = anzeigen_id_aus_url(link.get("href") if link else None)
    titel = _text(block.select_one("[data-testid=listing-title-card-view]"))
    if not ad_id:
        ohne_id.append(titel or "?")
        return None
    felder = _attribute(_text(block.select_one("[data-testid=listing-details-attributes]")))
    details = felder.pop("details")
    kategorie = felder.pop("kategorie", None)
    if kategorie:
        details["kategorie"] = kategorie
    if block.select_one("[data-testid=price-vat-sup]"):
        details["mwst_ausweisbar"] = True                     # Fußnote „¹ MwSt. ausweisbar“ (gewerbliche Anbieter)
    if block.select_one("[data-testid=sponsored-badge]"):
        details["gesponsert"] = True
    gewerblich, ort = _anbieter(block)
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
        "art": art_aus_kategorie(kategorie),
        "leistung": felder.get("leistung"),
        "bild": _bild(block),
        "gewerblich": gewerblich,
        "details": details,
    }


def parse_suchseite(html: str) -> list[dict]:
    """Treffer einer gespeicherten Suchseite (reguläre und gesponserte Plätze, je Anzeige einmal, in Seitenreihenfolge).
    Karussells („Highlights“, „Ähnliche Fahrzeuge“) sind keine Treffer. Treffer ohne Anzeigen-ID werden gezählt und
    protokolliert, nicht still verworfen."""
    soup = BeautifulSoup(html, "html.parser")
    ergebnisse, gesehen, ohne_id = [], set(), []
    for block in soup.find_all(attrs={"data-testid": _LISTING}):
        treffer = _parse_treffer(block, ohne_id)
        if treffer and treffer["id"] not in gesehen:
            gesehen.add(treffer["id"])
            ergebnisse.append(treffer)
    if ohne_id:
        log.warning("mobile.de-Suchseite: %d Treffer ohne Anzeigen-ID übersprungen (z. B. „%s“) – Seitenaufbau geändert?",
                    len(ohne_id), ohne_id[0])
    return ergebnisse


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


def parse_detailseite(html: str) -> dict:
    """Merkmale einer gespeicherten Anzeigenseite. Die Anzeigen-ID steht nicht im Text, sondern in der Adresse im Seitenkopf
    (siehe wmscout/eingang/seiten.py); `anzeigen_id` ist deshalb immer None."""
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
    if "MwSt. ausweisbar" in _text(soup.select_one("[data-testid=vip-price-box]")) + preis_bereich:
        daten["MwSt. ausweisbar"] = "ja"

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
    }
