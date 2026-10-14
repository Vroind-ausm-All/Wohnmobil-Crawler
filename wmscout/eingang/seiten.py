"""Im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten (Strg+S) erkennen – ohne jeden Netzabruf (ADR-010).

Der Nutzer ruft Such- oder Detailseiten selbst auf und speichert sie als „Webseite, nur HTML“ oder „komplett“
in den Import-Ordner (config.yaml → import → ordner). Hier wird nur erkannt, was in der Datei steht; die
Selektoren stehen unverändert im Parser der Quelle (wmscout/quellen/kleinanzeigen/parser.py bzw. mobilede/parser.py).
Die Plattform erkennt man am Seitenkopf (canonical/og:url/Speichervermerk, bei mobile.de zusätzlich og:site_name);
Kleinanzeigen wird nur erkannt, wenn die Seite nicht von mobile.de stammt.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, SoupStrainer

from ..normalisierung.fahrzeug import art_schluessel, arten_im_text
from ..quellen.basis import Inserat
from ..quellen.kleinanzeigen.adapter import anzeigen_id_aus_url
from ..quellen.kleinanzeigen.parser import BASIS, name_in_details, parse_detailseite, parse_suchseite
from ..quellen.mobilede import KENNUNG as MOBILEDE
from ..quellen.mobilede import anzeigen_id_aus_url as mobilede_id_aus_url
from ..quellen.mobilede import detail_url as mobilede_detail_url
from ..quellen.mobilede import parse_detailseite as mobilede_detailseite
from ..quellen.mobilede import parse_suchseite_mit_hinweisen as mobilede_suchseite

QUELLE = "kleinanzeigen"
HTML_ENDUNGEN = {".html", ".htm"}
BEGLEITORDNER = ("_files", "-Dateien")           # „Webseite, komplett“ legt Bilder/Skripte daneben ab
PROJEKT = Path(__file__).resolve().parent.parent.parent
# Browser vermerken beim Speichern die Herkunft, z. B. <!-- saved from url=(0071)https://… -->
_GESPEICHERT_VON = re.compile(r"<!--\s*saved from url=\(\d+\)\s*(\S+?)\s*-->", re.I)
MAX_DATEIGROESSE = 20_000_000                    # größere Dateien werden nicht gelesen (Speicher, Laufzeit unter Sperre)
# Kleinanzeigen-Suchadressen: …/s-wohnwagen-mobile/teilintegrierter/… bzw. …c220+wohnwagen_mobile.art_s:teilintegrierter
# Nur als eigener Parametername (nicht „aufbauart_s:“ o. Ä.): davor kein Wortzeichen, also z. B. nach „.“, „+“ oder „/“
_ART_S = re.compile(r"(?<!\w)art_s:([\w,-]+)", re.I)
_KATEGORIE = re.compile(r"/s-wohnwagen-mobile/([^/?#]+)", re.I)
# Allgemeine Kategorietitel nennen „Wohnwagen“ und „Wohnmobile“, sagen aber nichts über die Fahrzeugart
_ALLGEMEIN = re.compile(r"wohn(?:wagen|mobile?)\s*(?:&|und|/)\s*(?:wohn)?(?:wagen|mobile?)", re.I)
# Merkmale, die nur eine einzelne Anzeigenseite hat (dieselben Elemente, die parse_detailseite ausliest)
_ANZEIGEN_MERKMAL = re.compile(r"""id\s*=\s*["']?viewad-(?:title|price)\b""", re.I)
# mobile.de: Host der Seitenadresse im Kopf; die Suchseiten haben weder canonical noch og:url, aber og:site_name
_MOBILEDE_HOST = re.compile(r"^https?://(?:[\w-]+\.)*mobile\.de(?=[/:?#]|$)", re.I)
_MOBILEDE_SITE = {"mobile.de", "mobile_de"}
_MOBILEDE_ANZEIGE = re.compile(r"""data-testid\s*=\s*["']?vip-ad-title\b""", re.I)


class BegleitordnerFehler(OSError):
    """Die Datei ist verschoben, der zugehörige Begleitordner (<name>_files) aber nicht."""


def import_ordner(cfg: dict) -> Path:
    """Import-Ordner laut config.yaml (Standard „import“, relativ zum Projektordner)."""
    ordner = Path(str((cfg.get("import") or {}).get("ordner") or "import")).expanduser()
    return (ordner if ordner.is_absolute() else PROJEKT / ordner).resolve()


def html_dateien(ordner: Path) -> list[Path]:
    """HTML-Dateien direkt im Ordner (nicht rekursiv), alphabetisch; andere Dateien bleiben unberührt."""
    if not ordner.is_dir():
        return []
    return sorted((p for p in ordner.iterdir() if p.is_file() and p.suffix.lower() in HTML_ENDUNGEN),
                  key=lambda p: p.name.lower())


def relativ_zum_projekt(pfad: Path) -> str:
    """Pfad relativ zum Projektordner, wenn er darin liegt – sonst unverändert (absolut)."""
    try:
        return str(pfad.relative_to(PROJEKT))
    except ValueError:
        return str(pfad)


def lies_html(pfad: Path) -> str:
    groesse = pfad.stat().st_size
    if groesse > MAX_DATEIGROESSE:
        raise ValueError(f"Datei zu groß ({groesse / 1_000_000:.0f} MB, erlaubt sind {MAX_DATEIGROESSE // 1_000_000} MB)")
    return pfad.read_bytes().decode("utf-8-sig", errors="replace")


def _kopf(html: str) -> str:
    unten = html.lower()
    for marke in ("</head>", "<body"):          # ohne Kopf nur bis zum Inhalt – Links darin gehören nicht zur Seite selbst
        if (ende := unten.find(marke)) >= 0:
            return html[:ende]
    return html[:100_000]


_KOPF_ENDE = re.compile(r"</head\s*>|<body[\s>/]", re.I)
_SEITENANFANG = re.compile(r"<(?:html|head|body)[\s>/]", re.I)


def _strenger_kopf(html: str) -> str | None:
    """Text bis zum Ende des <head> (bzw. bis <body>); None, wenn die Seite weder das eine noch das andere hat.
    Die Fahrzeugart darf nur aus dem Kopf der Seite stammen – nie aus einem Link irgendwo im Seitentext."""
    return html[:m.start()] if (m := _KOPF_ENDE.search(html)) else None


def _gespeichert_von(html: str) -> str | None:
    """Adresse aus dem Speichervermerk des Browsers – der steht ganz am Anfang, vor <html>/<head>/<body>."""
    vorn = html[:5000]
    if m := _SEITENANFANG.search(vorn):
        vorn = vorn[:m.start()]
    return m.group(1) if (m := _GESPEICHERT_VON.search(vorn)) else None


def _detail_kennung(html: str) -> tuple[str | None, str | None, bool]:
    """(Anzeigen-ID, URL, sicher). Sicher = aus canonical/og:url/Speichervermerk, sonst aus einem Link im Kopf."""
    kopf = BeautifulSoup(_strenger_kopf(html) or "", "html.parser", parse_only=SoupStrainer(["link", "meta", "a"]))
    kandidaten = []
    if el := kopf.find(["link", "meta"], rel="canonical"):      # Kleinanzeigen schreibt es teils als <meta rel=…>
        kandidaten.append(el.get("href"))
    if el := kopf.find("meta", attrs={"property": "og:url"}):
        kandidaten.append(el.get("content"))
    if gespeichert := _gespeichert_von(html):
        kandidaten.append(gespeichert)
    weitere = [tag.get(attr) for tag in kopf.find_all(["link", "meta", "a"]) for attr in ("href", "content")]
    for sicher, urls in ((True, kandidaten), (False, weitere)):
        for url in urls:
            if url and "/s-anzeige/" in url and (ad_id := anzeigen_id_aus_url(url)):
                return ad_id, urljoin(BASIS, url.strip()), sicher
    return None, None, False


def _detail_inserat(ad_id: str, url: str, d: dict) -> Inserat | None:
    if not d.get("titel") and not d.get("details"):          # Leer-Prüfung VOR dem Namen: ein Kontaktkasten allein macht keine Anzeige
        return None
    d = {k: v for k, v in name_in_details(dict(d)).items() if k != "anzeigen_id"}   # Name nur zur Anrede, sonst keine Personendaten
    return Inserat(quelle=QUELLE, anzeigen_id=ad_id, url=url, **d)


def _url_zur_id(html: str, ad_id: str) -> str:
    """Adresse der eigenen Anzeige: ein Link im Seitentext mit genau dieser ID (Teilen-, Melde-, Login-Links),
    sonst die kurze Form …/s-anzeige/<id>."""
    if m := re.search(rf"/s-anzeige/[\w-]+/{re.escape(ad_id)}-\d+-\d+", html):
        return urljoin(BASIS, m.group(0))
    return f"{BASIS}/s-anzeige/{ad_id}"


class SuchseitenArt(NamedTuple):
    """Was eine gespeicherte Suchseite über die Fahrzeugart ihrer Treffer verrät – getrennt nach Verlässlichkeit.

    filter: Art aus einem echten Art-Filter der Suchadresse (`art_s:<wert>`) – alle Treffer haben diese Art.
    hinweis: Art aus dem Suchwort im Pfad bzw. aus dem Seitentitel – eine Freitextsuche (`…/camper/k0c220`), die
             auch andere Fahrzeugarten liefert; gilt nur vorläufig und nur für Treffer ohne widersprechende Art."""
    filter: str | None = None
    hinweis: str | None = None

    def fuer_treffer(self, titel: str | None, kurzbeschreibung: str | None = None) -> tuple[str | None, str | None]:
        """(Art, Herkunft) eines Treffers; Herkunft „bestaetigt“, „vorlaeufig“ oder – ohne Art – (None, None).

        bestätigt nur durch den Art-Filter der Seite. Vorläufig (Hinweis „nicht bestätigt“): (1) die Art aus dem eigenen Titel,
        wenn der Titel GENAU EINE Art nennt (alle Suchbegriffe geprüft, nicht nur der erste Treffer) und die
        Kurzbeschreibung keine andere nennt; (2) sonst der Hinweis der Seite, wenn weder Titel noch Kurzbeschreibung
        eine andere Art nennen. Alles andere (mehrere Arten, Widerspruch) bleibt unbekannt."""
        if self.filter:
            return self.filter, "bestaetigt"
        im_titel, in_kurz = arten_im_text(titel), arten_im_text(kurzbeschreibung)
        if len(im_titel) == 1 and in_kurz <= im_titel:
            return next(iter(im_titel)), "vorlaeufig"
        if self.hinweis and (im_titel | in_kurz) <= {self.hinweis}:
            return self.hinweis, "vorlaeufig"
        return None, None


def _art(text: str) -> str | None:
    art = art_schluessel(text)
    return None if art == "Sonstige" else art


def fahrzeugart_der_suchseite(html: str) -> SuchseitenArt:
    """Fahrzeugart-Angaben einer gespeicherten Suchseite (aus canonical-/og:url-/„saved from“-Adresse und <title>).

    Zuverlässig ist nur ein Art-Filter in der Adresse (`art_s:<wert>`). Das Suchwort im Pfad (`/camper/k0c220` ist
    eine Freitextsuche) und der Seitentitel sind nur ein Hinweis. „Sonstige“/„andere“ gilt als nicht erkannt.
    canonical, og:url und Titel zählen nur aus dem <head>; eine Seite ohne Kopf liefert daraus nichts."""
    kopf_html = _strenger_kopf(html)
    kopf = BeautifulSoup(kopf_html or "", "html.parser", parse_only=SoupStrainer(["link", "meta", "title"]))
    urls = []
    if el := kopf.find(["link", "meta"], rel="canonical"):
        urls.append(el.get("href"))
    if el := kopf.find("meta", attrs={"property": "og:url"}):
        urls.append(el.get("content"))
    urls.append(_gespeichert_von(html))
    urls = [u for u in urls if u]
    werte = [t for u in urls for w in _ART_S.findall(u) for t in w.split(",")]
    filter_arten = {a for t in werte if (a := _art(t))}
    if len(filter_arten) > 1 or any(not _art(t) for t in werte):
        return SuchseitenArt()                 # mehrere Arten oder „andere“ gewählt: Suchwort/Titel sagen nichts mehr
    if filter_arten:
        return SuchseitenArt(filter=next(iter(filter_arten)))
    for url in urls:
        for teil in _KATEGORIE.findall(url):
            if art := _art(teil):
                return SuchseitenArt(hinweis=art)
    if (titel := kopf.find("title")) and (text := _ALLGEMEIN.sub(" ", titel.get_text(" ", strip=True))):
        return SuchseitenArt(hinweis=_art(text))
    return SuchseitenArt()


def haupttabelle_ids(html: str) -> set[str]:
    """Anzeigen-IDs der Trefferliste `#srchrslt-adtable`. Nur diese Treffer erfüllen den Filter der Suchadresse;
    „Weitere Ergebnisse in anderen Orten“ (`#srchrslt-adtable-altads`) und alles außerhalb gehören nicht dazu."""
    teil = BeautifulSoup(html, "html.parser", parse_only=SoupStrainer(id="srchrslt-adtable"))
    return {t["id"] for t in parse_suchseite(str(teil))} if teil.contents else set()


def _seitenadressen(html: str) -> list[str]:
    """Adressen aus dem Seitenkopf: canonical, og:url und der Speichervermerk des Browsers (nur aus dem <head>)."""
    kopf = BeautifulSoup(_strenger_kopf(html) or "", "html.parser", parse_only=SoupStrainer(["link", "meta"]))
    urls = []
    if el := kopf.find(["link", "meta"], rel="canonical"):
        urls.append(el.get("href"))
    if el := kopf.find("meta", attrs={"property": "og:url"}):
        urls.append(el.get("content"))
    urls.append(_gespeichert_von(html))
    return [u.strip() for u in urls if u]


def ist_mobilede_seite(html: str) -> bool:
    """Stammt die Datei von mobile.de? Nur der Kopf zählt: Adresse (canonical/og:url/Speichervermerk) auf *.mobile.de oder
    `og:site_name` „mobile.de“/„mobile_de“ (die Suchseiten haben weder canonical noch og:url). Links im Seitentext zählen nicht."""
    if any(_MOBILEDE_HOST.match(u) for u in _seitenadressen(html)):
        return True
    kopf = BeautifulSoup(_strenger_kopf(html) or "", "html.parser", parse_only=SoupStrainer("meta"))
    site = kopf.find("meta", attrs={"property": "og:site_name"})
    return bool(site) and (site.get("content") or "").strip().lower() in _MOBILEDE_SITE


def plattform_der_seite(html: str) -> str:
    """'mobile.de' oder 'kleinanzeigen' (alles, was nicht eindeutig von mobile.de kommt)."""
    return MOBILEDE if ist_mobilede_seite(html) else QUELLE


def _erkenne_mobilede(html: str) -> tuple[str, list[Inserat], list[str]]:
    """Wie `erkenne_seite_mit_hinweisen`, für mobile.de: Anzeigenseite = Adresse `details.html?id=…` im Kopf (oder erkennbarer
    Anzeigentitel); Suchseite = Trefferblöcke `*-result-listing-N`. Die „ähnlichen Fahrzeuge“ einer Anzeigenseite sind keine Treffer.
    Nur Wohnmobile und Wohnwagen: eine Pkw-Anzeige oder -Suche ist „unbekannt“, der Hinweis sagt warum."""
    ad_id = next((i for u in _seitenadressen(html) if (i := mobilede_id_aus_url(u))), None)
    if ad_id:
        d = mobilede_detailseite(html)
        if d.get("titel") or d.get("details"):
            d.pop("anzeigen_id", None)
            wohnmobil, klasse = d.pop("wohnmobil", False), d.pop("klasse_text", None)
            if not wohnmobil:
                return "unbekannt", [], [f"mobile.de-Anzeige ist kein Wohnmobil/Wohnwagen (Kategorie: „{klasse}“)" if klasse else
                                         "mobile.de-Anzeige: Fahrzeugklasse (Wohnmobil/Wohnwagen) nicht erkennbar"]
            return "detail", [Inserat(quelle=MOBILEDE, anzeigen_id=ad_id, url=mobilede_detail_url(ad_id), **d)], []
    elif _MOBILEDE_ANZEIGE.search(html):
        return "detail_ohne_id", [], []
    roh, hinweise = mobilede_suchseite(html)
    treffer = [Inserat(quelle=MOBILEDE, anzeigen_id=t.pop("id"), **t) for t in roh]
    if not treffer and any("ohne Wohnmobil-Kategorie" in h for h in hinweise):
        hinweise = [h.replace("mobile.de-Suchseite:", "mobile.de-Seite ist keine Wohnmobil-/Wohnwagen-Suche –", 1) for h in hinweise]
    return ("suche", treffer, hinweise) if treffer else ("unbekannt", [], hinweise)


def erkenne_seite(html: str) -> tuple[str, list[Inserat]]:
    """Art der Seite und die erkannten Inserate (ohne Gesuche); Hinweise siehe `erkenne_seite_mit_hinweisen`."""
    art, inserate, _ = erkenne_seite_mit_hinweisen(html)
    return art, inserate


def erkenne_seite_mit_hinweisen(html: str) -> tuple[str, list[Inserat], list[str]]:
    """Art der Seite, die erkannten Inserate (ohne Gesuche) und Hinweise für den Nutzer (z. B. übersprungene Treffer, fehlende
    Anbieterkästen bei mobile.de; leer bei Kleinanzeigen).

    Art: 'suche', 'detail', 'unbekannt' oder 'detail_ohne_id' (Anzeigenseite, aber ohne ermittelbare Anzeigen-ID).
    Seiten von mobile.de (Kopf, siehe `ist_mobilede_seite`) liest `_erkenne_mobilede`; alles andere gilt als Kleinanzeigen."""
    if ist_mobilede_seite(html):
        return _erkenne_mobilede(html)
    ad_id, url, sicher = _detail_kennung(html)
    # Detailseiten können unten „ähnliche Anzeigen“ enthalten – eine eindeutige Inserats-URL geht deshalb vor
    if ad_id and sicher and (inserat := _detail_inserat(ad_id, url, parse_detailseite(html))):
        return "detail", [inserat], []
    if _ANZEIGEN_MERKMAL.search(html):
        # Strukturell eine Anzeigenseite: nie als Suchseite lesen (die „ähnlichen Anzeigen“ wären sonst die Treffer)
        d = parse_detailseite(html)
        if box_id := d.get("anzeigen_id"):               # Kasten „Anzeigen-ID“ der Seite selbst
            if box_id != ad_id:
                ad_id, url = box_id, _url_zur_id(html, box_id)
        if ad_id and (inserat := _detail_inserat(ad_id, url, d)):
            return "detail", [inserat], []
        return "detail_ohne_id", [], []
    treffer = [Inserat(quelle=QUELLE, anzeigen_id=t.pop("id"), **t) for t in parse_suchseite(html)]
    if treffer:
        return "suche", [i for i in treffer if not i.ist_gesuch], []
    if ad_id and (inserat := _detail_inserat(ad_id, url, parse_detailseite(html))):
        return "detail", [inserat], []
    return "unbekannt", [], []


def _freier_name(ziel: Path, stamm: str, endung: str) -> str:
    """'seite.html' oder bei Namenskonflikt 'seite_2.html', 'seite_3.html' … (auch Begleitordner frei)."""
    n = 1
    while True:
        name = stamm if n == 1 else f"{stamm}_{n}"
        belegt = (ziel / f"{name}{endung}").exists() or any((ziel / f"{name}{s}").exists() for s in BEGLEITORDNER)
        if not belegt:
            return name
        n += 1


def verschiebe(datei: Path, ziel: Path) -> Path:
    """Verschiebt die Datei samt Begleitordner (<name>_files / <name>-Dateien) nach `ziel`. Löscht nichts."""
    ziel.mkdir(parents=True, exist_ok=True)
    name = _freier_name(ziel, datei.stem, datei.suffix)
    neu = ziel / f"{name}{datei.suffix}"
    shutil.move(str(datei), str(neu))
    for s in BEGLEITORDNER:
        begleiter = datei.with_name(f"{datei.stem}{s}")
        if begleiter.is_dir():
            try:
                shutil.move(str(begleiter), str(ziel / f"{name}{s}"))
            except OSError as e:
                raise BegleitordnerFehler(f"Begleitordner {begleiter.name} nicht verschoben: {e}") from e
    return neu
