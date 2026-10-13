"""HTML-Parser für Kleinanzeigen-Suchseiten und -Detailseiten.

Kleinanzeigen ändert gelegentlich sein Markup. Alle Selektoren stehen
deshalb gesammelt hier; bei Problemen nur diese Datei anpassen.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASIS = "https://www.kleinanzeigen.de"

MARKEN = [
    "Adria", "Bürstner", "Carado", "Carthago", "Chausson", "Challenger", "Concorde",
    "Dethleffs", "Eura Mobil", "Fendt", "Fiat", "Ford", "Frankia", "Globecar",
    "Hobby", "Hymer", "Knaus", "Laika", "LMC", "Malibu", "McLouis", "Mercedes",
    "Morelo", "Niesmann", "Pilote", "Pössl", "Rapido", "Rimor", "Roller Team",
    "Sunlight", "Tabbert", "TEC", "Volkswagen", "VW", "Weinsberg", "Westfalia",
    "Clever", "Vantourer", "Sun Living", "Benimar", "Itineo", "Elnagh", "Etrusco",
]


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def preis_aus_text(text: str) -> tuple[int | None, bool]:
    """'24.900 € VB' -> (24900, True); 'VB' -> (None, True)."""
    vb = "VB" in text
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)\s*€", text)
    return (int(m.group(1).replace(".", "")) if m else None), vb


def km_aus_text(text: str) -> int | None:
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,6})\s*km\b", text, re.I)
    return int(m.group(1).replace(".", "")) if m else None


def ez_aus_text(text: str) -> int | None:
    """Liefert das Erstzulassungs-Jahr."""
    m = re.search(r"\bEZ\s*(?:\d{1,2}/)?((?:19|20)\d{2})", text)
    if not m:
        m = re.search(r"Erstzulassung\s*(?:\w+\s+|\d{1,2}/)?((?:19|20)\d{2})", text)
    if not m:
        m = re.search(r"\b(?:Bj\.?|Baujahr)\s*((?:19|20)\d{2})", text, re.I)
    return int(m.group(1)) if m else None


def marke_aus_text(text: str) -> str | None:
    t = text.lower()
    for marke in MARKEN:
        if re.search(r"\b" + re.escape(marke.lower()) + r"\b", t):
            return "Volkswagen" if marke == "VW" else marke
    return None


def parse_suchseite(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    ergebnisse = []
    for art in soup.select("article.aditem"):
        ad_id = art.get("data-adid")
        href = art.get("data-href")
        titel_el = art.select_one("h2 a, .text-module-begin a, a.ellipsis")
        if not href and titel_el:
            href = titel_el.get("href")
        if not ad_id and href:
            m = re.search(r"/(\d{6,})-\d+-\d+", href)
            ad_id = m.group(1) if m else None
        if not ad_id or not href:
            continue

        preis_el = art.select_one(".aditem-main--middle--price-shipping--price, .aditem-main--middle--price")
        preis, vb = preis_aus_text(_text(preis_el))
        tags = " ".join(_text(t) for t in art.select(".simpletag, .text-module-end, .aditem-main--middle--tags"))
        beschreibung = _text(art.select_one(".aditem-main--middle--description"))
        titel = _text(titel_el)
        alles = f"{titel} {beschreibung} {tags}"
        gewerblich = bool(art.select_one("a[href*='/pro/'], .badge-hint-pro-small-srp")) or "PRO" in _text(
            art.select_one(".aditem-main--bottom"))

        ergebnisse.append({
            "id": ad_id,
            "url": urljoin(BASIS, href),
            "titel": titel,
            "preis": preis,
            "vb": vb,
            "ort": _text(art.select_one(".aditem-main--top--left")),
            "datum": _text(art.select_one(".aditem-main--top--right")),
            "kurzbeschreibung": beschreibung,
            "km": km_aus_text(alles),
            "ez_jahr": ez_aus_text(alles),
            "marke": marke_aus_text(titel + " " + beschreibung),
            "gewerblich": gewerblich,
            "ist_gesuch": "Gesuch" in _text(art),
        })
    return ergebnisse


def parse_detailseite(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    details: dict[str, str] = {}
    for li in soup.select(".addetailslist--detail, #viewad-details li"):
        wert_el = li.select_one(".addetailslist--detail--value")
        wert = _text(wert_el)
        label = _text(li)
        if wert:
            label = label.replace(wert, "").strip()
        if label:
            details[label.rstrip(":")] = wert

    beschreibung = _text(soup.select_one("#viewad-description-text, [itemprop=description]"))
    titel = _text(soup.select_one("#viewad-title, h1"))
    preis, vb = preis_aus_text(_text(soup.select_one("#viewad-price, [itemprop=price]")))
    verkaeufer_box = _text(soup.select_one("#viewad-contact, .userprofile-vip, #viewad-profile-box"))

    def detail(*namen):
        for n in namen:
            for k, v in details.items():
                if k.lower().startswith(n.lower()):
                    return v
        return ""

    alles = " ".join([titel, beschreibung] + [f"{k} {v}" for k, v in details.items()])
    km = km_aus_text(detail("Kilometerstand")) or km_aus_text(alles)
    ez = ez_aus_text("Erstzulassung " + detail("Erstzulassung")) or ez_aus_text(alles)
    marke = detail("Marke") or marke_aus_text(titel + " " + beschreibung)
    if marke and marke.lower() in ("weitere marken", "andere"):
        marke = marke_aus_text(titel + " " + beschreibung)

    return {
        "titel": titel or None,
        "preis": preis,
        "vb": vb,
        "beschreibung": beschreibung,
        "km": km,
        "ez_jahr": ez,
        "marke": marke or None,
        "art": detail("Art") or None,
        "leistung": detail("Leistung") or None,
        "getriebe": detail("Getriebe") or None,
        "verkaeufer_name": _text(soup.select_one(".userprofile-vip a, .userprofile-vip")) or None,
        "gewerblich": "gewerblich" in verkaeufer_box.lower() or bool(soup.select_one("a[href*='/pro/']")),
        "details": details,
    }
