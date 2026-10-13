"""Im Browser gespeicherte Kleinanzeigen-Seiten (Strg+S) erkennen – ohne jeden Netzabruf (ADR-010).

Der Nutzer ruft Such- oder Detailseiten selbst auf und speichert sie als „Webseite, nur HTML“ oder „komplett“
in den Import-Ordner (config.yaml → import → ordner). Hier wird nur erkannt, was in der Datei steht; die
Selektoren stehen unverändert im Parser der Quelle (wmscout/quellen/kleinanzeigen/parser.py).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, SoupStrainer

from ..quellen.basis import Inserat
from ..quellen.kleinanzeigen.adapter import anzeigen_id_aus_url
from ..quellen.kleinanzeigen.parser import BASIS, parse_detailseite, parse_suchseite

QUELLE = "kleinanzeigen"
HTML_ENDUNGEN = {".html", ".htm"}
BEGLEITORDNER = ("_files", "-Dateien")           # „Webseite, komplett“ legt Bilder/Skripte daneben ab
PROJEKT = Path(__file__).resolve().parent.parent.parent
# Browser vermerken beim Speichern die Herkunft, z. B. <!-- saved from url=(0071)https://… -->
_GESPEICHERT_VON = re.compile(r"<!--\s*saved from url=\(\d+\)\s*(\S+?)\s*-->", re.I)


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


def lies_html(pfad: Path) -> str:
    return pfad.read_bytes().decode("utf-8-sig", errors="replace")


def _kopf(html: str) -> str:
    ende = html.lower().find("</head>")
    return html[:ende] if ende >= 0 else html[:100_000]


def _detail_kennung(html: str) -> tuple[str | None, str | None, bool]:
    """(Anzeigen-ID, URL, sicher). Sicher = aus canonical/og:url/Speichervermerk, sonst aus einem Link im Kopf."""
    kopf = BeautifulSoup(_kopf(html), "html.parser", parse_only=SoupStrainer(["link", "meta", "a"]))
    kandidaten = []
    if el := kopf.find("link", rel="canonical"):
        kandidaten.append(el.get("href"))
    if el := kopf.find("meta", attrs={"property": "og:url"}):
        kandidaten.append(el.get("content"))
    if m := _GESPEICHERT_VON.search(html[:5000]):
        kandidaten.append(m.group(1))
    weitere = [tag.get(attr) for tag in kopf.find_all(["link", "meta", "a"]) for attr in ("href", "content")]
    for sicher, urls in ((True, kandidaten), (False, weitere)):
        for url in urls:
            if url and "/s-anzeige/" in url and (ad_id := anzeigen_id_aus_url(url)):
                return ad_id, urljoin(BASIS, url.strip()), sicher
    return None, None, False


def _detail_inserat(html: str, ad_id: str, url: str) -> Inserat | None:
    d = parse_detailseite(html)
    d.pop("verkaeufer_name", None)                # Personendaten nicht speichern (wie beim Abruf)
    if not d.get("titel") and not d.get("details"):
        return None
    return Inserat(quelle=QUELLE, anzeigen_id=ad_id, url=url, **d)


def erkenne_seite(html: str) -> tuple[str, list[Inserat]]:
    """Art der Seite ('suche', 'detail', 'unbekannt') und die erkannten Inserate (ohne Gesuche)."""
    ad_id, url, sicher = _detail_kennung(html)
    # Detailseiten können unten „ähnliche Anzeigen“ enthalten – eine eindeutige Inserats-URL geht deshalb vor
    if ad_id and sicher and (inserat := _detail_inserat(html, ad_id, url)):
        return "detail", [inserat]
    treffer = [Inserat(quelle=QUELLE, anzeigen_id=t.pop("id"), **t) for t in parse_suchseite(html)]
    if treffer:
        return "suche", [i for i in treffer if not i.ist_gesuch]
    if ad_id and (inserat := _detail_inserat(html, ad_id, url)):
        return "detail", [inserat]
    return "unbekannt", []


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
            shutil.move(str(begleiter), str(ziel / f"{name}{s}"))
    return neu
