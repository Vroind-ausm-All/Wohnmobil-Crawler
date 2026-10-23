"""HTML-Parser für Kleinanzeigen-Suchseiten und -Detailseiten.

Kleinanzeigen ändert gelegentlich sein Markup. Alle Selektoren stehen
deshalb gesammelt hier; bei Problemen nur diese Datei anpassen.

Unterstützte Layouts der Trefferliste:
  * neu (Stand 10/2026): `article[data-adid]` mit Tailwind-Klassen. Gelesen wird nach Struktur und Rolle
    (Titel = Link auf /s-anzeige/ in einer Überschrift, Preis = Absatz mit „€“, Ort = Text mit Postleitzahl,
    Tags = abgerundete `span`), nicht nach den langen Klassenketten.
  * alt: `article.aditem` mit `.aditem-main--…`-Klassen (bleibt als Rückfall erhalten).
Detailseite: `#viewad-…`-Elemente; die Merkmalsliste kennt beide Formen (Label/Wert als zwei `span`, bzw.
`.addetailslist--detail--value`).
"""
from __future__ import annotations

from ..basis import http_url

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ...anbieter import ANZEIGE, OHNE_KENNZEICHEN
from ...normalisierung.fahrzeug import ist_basismarke, marke_aus_text, normalisiere_marke
from ...normalisierung.person import profilname

BASIS = "https://www.kleinanzeigen.de"

_PLZ_ORT = re.compile(r"^\d{5}\s+\S")
_DATUM = re.compile(r"^(?:(?:Heute|Gestern),\s*\d{1,2}:\d{2}|\d{1,2}\.\d{1,2}\.\d{4})$")
_PREISZEILE = re.compile(r"^(?:(?:\d{1,3}(?:\.\d{3})+|\d+)\s*€(?:\s*VB)?|VB)$")
_EZ_TAG = re.compile(r"^EZ\s*\d{1,2}/(?:19|20)\d{2}$")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_ANZEIGEN_ID = re.compile(r"\b(\d{6,})\b")
_BUNDESLAENDER = ("Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
                  "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland",
                  "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen")


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
    """Liefert das Erstzulassungs-Jahr („EZ 03/2019“, „Erstzulassung Juli 2021“, „Erstzulassung: 2009“, „Bj. 2015“)."""
    m = re.search(r"\bEZ\s*(?:\d{1,2}/)?((?:19|20)\d{2})", text)
    if not m:
        m = re.search(r"Erstzulassung[:\s]*(?:\w+\s+|\d{1,2}[/.])?((?:19|20)\d{2})", text)
    if not m:
        m = re.search(r"\b(?:Bj\.?|Baujahr)\s*((?:19|20)\d{2})", text, re.I)
    return int(m.group(1)) if m else None


def _http_url(url: str | None) -> str | None:
    url = (url or "").strip()
    return url if url.startswith("http") and "placeholder" not in url else None


def bild_url(el) -> str | None:
    """Vorschaubild einer Trefferliste (Kleinanzeigen lädt Bilder teils erst per data-imgsrc, neu auch per srcset).

    Nur http(s)-Adressen: Gespeicherte Seiten verweisen auf lokale Dateien (…_files/…), die hier nichts nützen."""
    if not el:
        return None
    for kandidat in [el, *el.select("[data-imgsrc], img, source")]:
        for attr in ("data-imgsrc", "data-src", "src"):
            if url := _http_url(kandidat.get(attr)):
                return url
        for eintrag in (kandidat.get("srcset") or "").split(","):
            if url := _http_url(eintrag.strip().split(" ")[0] if eintrag.strip() else None):
                return url
    return None


# ---------- Trefferliste ----------
def _ld_bilder(soup) -> tuple[dict[str, dict], dict[str, dict]]:
    """Die ImageObject-Einträge aus `script[type=application/ld+json]`: (nach Bild-UUID, nach Titel)."""
    nach_uuid: dict[str, dict] = {}
    nach_titel: dict[str, dict] = {}
    for skript in soup.select('script[type="application/ld+json"]'):
        try:
            daten = json.loads(skript.string or skript.get_text() or "")
        except ValueError:
            continue
        for eintrag in daten if isinstance(daten, list) else [daten]:
            if not isinstance(eintrag, dict) or not _http_url(eintrag.get("contentUrl")):
                continue
            if (m := _UUID.search(eintrag["contentUrl"])):
                nach_uuid.setdefault(m.group(0).lower(), eintrag)
            nach_titel.setdefault(" ".join(str(eintrag.get("title", "")).split()), eintrag)
    return nach_uuid, nach_titel


def _ld_eintrag(art, titel: str, nach_uuid: dict, nach_titel: dict) -> dict:
    for bild in art.select("img, source"):
        for attr in ("src", "srcset"):
            if (m := _UUID.search(bild.get(attr) or "")) and m.group(0).lower() in nach_uuid:
                return nach_uuid[m.group(0).lower()]
    return nach_titel.get(titel, {})


def _preis_element(art):
    """Preis = Absatz, dessen ganzer Text ein Preis ist (ohne durchgestrichenen Altpreis)."""
    kandidaten = [p for p in art.find_all("p") if "line-through" not in " ".join(p.get("class", []))
                  and _PREISZEILE.match(_text(p))]
    return next((p for p in kandidaten if "text-title3" in " ".join(p.get("class", []))), None) or (
        kandidaten[0] if kandidaten else None)


def _parse_treffer_neu(art, ld: tuple[dict, dict]) -> dict | None:
    ueberschrift = next((h for h in art.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]) if _text(h)), None)
    link = next((a for a in art.select("a[href*='/s-anzeige/']") if _text(a)), None)
    # Titel = Link in der Überschrift; manchmal steht der Titel ohne Link in der Überschrift (span mit data-url)
    titel_el = (ueberschrift.select_one("a[href]") if ueberschrift else None) or ueberschrift or link
    href = art.get("data-href") or (link.get("href") if link else None) or (
        titel_el.get("data-url") if titel_el is not None else None)
    ad_id = art.get("data-adid")
    if not ad_id and href:
        m = re.search(r"/(\d{6,})-\d+-\d+", href)
        ad_id = m.group(1) if m else None
    if not ad_id or not href:
        return None

    titel = _text(titel_el)
    eintrag = _ld_eintrag(art, titel, *ld)
    titel = titel or " ".join(str(eintrag.get("title", "")).split())

    beschr_el = ueberschrift.find_next_sibling("p") if ueberschrift else None
    if beschr_el is None:
        beschr_el = next((p for p in art.select("p.text-onSurfaceSubdued") if not _PREISZEILE.match(_text(p))), None)
    beschreibung = _text(beschr_el) or " ".join(str(eintrag.get("description", "")).split())

    preis, vb = preis_aus_text(_text(_preis_element(art)))
    spans = art.find_all("span")
    tags = [_text(s) for s in spans if "rounded-xsmall" in " ".join(s.get("class", [])) or _EZ_TAG.match(_text(s))]
    texte = [_text(s) for s in spans]
    alles = f"{titel} {beschreibung} {' '.join(tags)}"
    # Gewerblich = PRO-Abzeichen bzw. Link auf das Händlerprofil; „TOP“ ist nur eine bezahlte Hervorhebung
    gewerblich = bool(art.select_one("a[href*='/pro/']")) or any(_text(el) == "PRO" for el in art.find_all(["div", "span", "a"]))

    return {
        "id": ad_id,
        "url": http_url(urljoin(BASIS, href)),
        "titel": titel,
        "preis": preis,
        "vb": vb,
        "ort": next((t for t in texte if _PLZ_ORT.match(t)), None),
        "datum": next((t for t in texte if _DATUM.match(t)), ""),
        "kurzbeschreibung": beschreibung,
        "km": km_aus_text(alles),
        "ez_jahr": ez_aus_text(alles),
        "marke": marke_aus_text(titel + " " + beschreibung),
        "bild": bild_url(art) or _http_url(eintrag.get("contentUrl")),
        "gewerblich": gewerblich,
        "anbieter_herkunft": ANZEIGE if gewerblich else OHNE_KENNZEICHEN,     # kein PRO-Kennzeichen ist kein Beleg für „privat“
        "ist_gesuch": any(t.lower() == "gesuch" for t in tags),
    }


def _parse_treffer_alt(art) -> dict | None:
    ad_id = art.get("data-adid")
    href = art.get("data-href")
    titel_el = art.select_one("h2 a, .text-module-begin a, a.ellipsis")
    if not href and titel_el:
        href = titel_el.get("href")
    if not ad_id and href:
        m = re.search(r"/(\d{6,})-\d+-\d+", href)
        ad_id = m.group(1) if m else None
    if not ad_id or not href:
        return None

    preis_el = art.select_one(".aditem-main--middle--price-shipping--price, .aditem-main--middle--price")
    preis, vb = preis_aus_text(_text(preis_el))
    tags = " ".join(_text(t) for t in art.select(".simpletag, .text-module-end, .aditem-main--middle--tags"))
    beschreibung = _text(art.select_one(".aditem-main--middle--description"))
    titel = _text(titel_el)
    alles = f"{titel} {beschreibung} {tags}"
    gewerblich = bool(art.select_one("a[href*='/pro/'], .badge-hint-pro-small-srp")) or "PRO" in _text(
        art.select_one(".aditem-main--bottom"))

    return {
        "id": ad_id,
        "url": http_url(urljoin(BASIS, href)),
        "titel": titel,
        "preis": preis,
        "vb": vb,
        "ort": _text(art.select_one(".aditem-main--top--left")),
        "datum": _text(art.select_one(".aditem-main--top--right")),
        "kurzbeschreibung": beschreibung,
        "km": km_aus_text(alles),
        "ez_jahr": ez_aus_text(alles),
        "marke": marke_aus_text(titel + " " + beschreibung),
        "bild": bild_url(art.select_one(".aditem-image, .imagebox")),
        "gewerblich": gewerblich,
        "anbieter_herkunft": ANZEIGE if gewerblich else OHNE_KENNZEICHEN,
        "ist_gesuch": "Gesuch" in _text(art),
    }


def parse_suchseite(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    ld = None
    ergebnisse = []
    for art in soup.select("article[data-adid], article.aditem"):
        if art.select_one(".aditem-main") or "aditem" in art.get("class", []):
            treffer = _parse_treffer_alt(art)
        else:
            ld = ld or _ld_bilder(soup)
            treffer = _parse_treffer_neu(art, ld)
        if treffer:
            ergebnisse.append(treffer)
    return ergebnisse


# ---------- Detailseite ----------
def ort_aus_lokalitaet(text: str) -> str | None:
    """'71111 Baden-Württemberg - Beispielstadt' -> '71111 Beispielstadt' (wie in der Trefferliste)."""
    text = " ".join(text.split())
    for land in _BUNDESLAENDER:
        text = re.sub(rf"^(\d{{5}})\s+{re.escape(land)}\s+-\s+", r"\1 ", text)
    return text or None


def _merkmale(soup) -> dict[str, str]:
    """Label → Wert aus der Merkmalsliste (zwei `span` je `li`, älter: `.addetailslist--detail--value`)."""
    details: dict[str, str] = {}
    for li in soup.select(".addetailslist--detail, #viewad-details li"):
        wert_el = li.select_one(".addetailslist--detail--value")
        if wert_el is not None:
            wert = _text(wert_el)
            label = _text(li)
            if wert:
                label = label.replace(wert, "").strip()
        else:
            spans = li.find_all("span", recursive=False)
            if len(spans) >= 2:
                label, wert = _text(spans[0]), _text(spans[1])
            else:
                label, wert = _text(li), ""
        if label:
            details[label.rstrip(":")] = wert
    return details


def _erster_text(soup, *selektoren: str) -> str:
    """Text des ersten Selektors, der ein Element mit Text liefert (`meta itemprop=…` hat keinen und wird übergangen)."""
    for selektor in selektoren:
        for el in soup.select(selektor):
            if text := _text(el):
                return text
    return ""


def _verkaeufer_name(soup) -> str | None:
    """Profilname aus dem Verkäuferkasten `#viewad-contact`: bevorzugt `aria-label="Profil von <Name>"`, sonst der Link
    auf das Profil (`userId=`; der Kürzel-Link „HW“ fällt durch die Namensprüfung); älteres Layout: `.userprofile-vip a`.
    Ohne Treffer None – „Privater Nutzer“, Badges und „Aktiv seit …“ sind keine Namen."""
    kasten = soup.select_one("#viewad-contact")
    kandidaten = []
    if kasten is not None:
        kandidaten += [a["aria-label"][len("Profil von "):] for a in kasten.select("a[aria-label]")
                       if a["aria-label"].lower().startswith("profil von ")]
        kandidaten += [_text(a) for a in kasten.select("a[href*='userId=']")]
    kandidaten += [_text(a) for a in soup.select(".userprofile-vip a")]
    return next((n for k in kandidaten if (n := profilname(k))), None)


def name_in_details(d: dict) -> dict:
    """Entfernt `verkaeufer_name` aus dem Ergebnis von parse_detailseite() und legt ihn – als einziges Personenfeld –
    in `details` ab (landet in `details_json`; keine Telefonnummern, Profil-IDs oder Adressen)."""
    name = d.pop("verkaeufer_name", None)
    if name:
        d["details"] = {**d.get("details", {}), "verkaeufer_name": name}
    return d


# Wendungen des Verkäuferkastens für Privatanbieter – nicht jedes „privat“ (ein Händlername wie „Privat-Camper-Center“ ist kein Beleg)
_PRIVAT_KASTEN = re.compile(r"\bprivate[rn]?\s+(?:nutzer|anbieter)\b|\bprivatanbieter\b", re.I)


def parse_detailseite(html: str) -> dict:
    """Merkmale einer Anzeigenseite. Zusätzlich `anzeigen_id` (aus dem Kasten „Anzeigen-ID“) und `ort`."""
    soup = BeautifulSoup(html, "html.parser")
    details = _merkmale(soup)

    beschreibung = _erster_text(soup, "#viewad-description-text", "[itemprop=description]")
    titel = _erster_text(soup, "#viewad-title", "h1")
    preis, vb = preis_aus_text(_erster_text(soup, "#viewad-price", "[itemprop=price]"))
    verkaeufer_box = _text(soup.select_one("#viewad-contact, .userprofile-vip, #viewad-profile-box"))
    id_treffer = _ANZEIGEN_ID.search(_text(soup.select_one("#viewad-ad-id-box")))

    def detail(*namen):
        for n in namen:
            for k, v in details.items():
                if k.lower().startswith(n.lower()):
                    return v
        return ""

    alles = " ".join([titel, beschreibung] + [f"{k} {v}" for k, v in details.items()])
    km = km_aus_text(detail("Kilometerstand")) or km_aus_text(alles)
    ez = ez_aus_text("Erstzulassung " + detail("Erstzulassung")) or ez_aus_text(alles)
    # Aufbauhersteller aus dem Text schlägt Basisfahrzeug/„Weitere Marken“ aus dem Feld
    marke = normalisiere_marke(detail("Marke"))
    if not marke or ist_basismarke(marke) or marke.lower() in ("weitere marken", "andere", "sonstige"):
        marke = marke_aus_text(titel) or marke_aus_text(beschreibung) or (marke if ist_basismarke(marke) else None)

    # Händlerhinweis nur aus dem Verkäuferbereich – „ähnliche Anzeigen“ unten auf der Seite können PRO-Links tragen
    pro_link = any(not a.find_parent("article") for a in soup.select("a[href*='/pro/']"))
    gewerblich = "gewerblich" in verkaeufer_box.lower() or pro_link
    # „Privater Nutzer“ im Verkäuferkasten ist eine Angabe der Anzeige; ohne Kasten bleibt „privat“ nur eine Vermutung
    herkunft = ANZEIGE if gewerblich or _PRIVAT_KASTEN.search(verkaeufer_box) else OHNE_KENNZEICHEN

    return {
        "anzeigen_id": id_treffer.group(1) if id_treffer else None,
        "titel": titel or None,
        "preis": preis,
        "vb": vb,
        "ort": ort_aus_lokalitaet(_erster_text(soup, "#viewad-locality", "[itemprop=addressLocality]")),
        "beschreibung": beschreibung,
        "km": km,
        "ez_jahr": ez,
        "marke": marke or None,
        "art": detail("Art") or None,
        "leistung": detail("Leistung") or None,
        "getriebe": detail("Getriebe") or None,
        "verkaeufer_name": _verkaeufer_name(soup),
        "gewerblich": gewerblich,
        "anbieter_herkunft": herkunft,
        "details": details,
    }
