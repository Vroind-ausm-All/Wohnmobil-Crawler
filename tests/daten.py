"""Testdaten: nachgebautes Kleinanzeigen-Markup und ein Abruf ohne Netzwerk."""
from __future__ import annotations

import random
from pathlib import Path

import yaml

from wmscout.quellen import HttpFehler

BASIS = Path(__file__).resolve().parent.parent
MARKEN = ["Knaus", "Hymer", "Dethleffs", "Bürstner", "Pössl", "Weinsberg"]
ORTE = ["70173 Stuttgart", "80331 München", "10115 Berlin", "50667 Köln", "73728 Esslingen"]
MODELL_NAMEN = {"Knaus": "Sky TI 650 MEG", "Hymer": "ML-T 570", "Dethleffs": "Trend T 7057 EB",
                "Bürstner": "Lyseo TD 728 G", "Pössl": "Summit 600", "Weinsberg": "CaraCompact 600 MEG"}
SUCH_URL = "https://www.kleinanzeigen.de/s-wohnwagen-mobile/c220"


def lade_cfg() -> dict:
    return yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))


def tsd(x):
    return f"{x:,}".replace(",", ".")


def baue_ads(n: int = 60, seed: int = 4) -> list[dict]:
    rng = random.Random(seed)
    ads = []
    for i in range(n):
        marke = rng.choice(MARKEN)
        ez = rng.randint(2008, 2022)
        km = rng.randint(20, 180) * 1000
        basis = 85000 * (0.92 ** (2025 - ez)) - km * 0.08
        preis = int(basis * rng.uniform(0.85, 1.2) / 100) * 100
        lang = "Gepflegtes Fahrzeug, scheckheftgepflegt, Nichtraucher, keine Feuchtigkeit."
        if i % 9 == 0:
            lang += " Keine Händleranfragen!"
        plz, ort = rng.choice(ORTE).split(" ", 1)
        ads.append({"id": str(3500000000 + i), "slug": f"wohnmobil-{i}", "plz": plz, "ort": ort,
                    "titel": f"{marke} {MODELL_NAMEN[marke]} T{i}", "kurz": "Verkaufe unser Wohnmobil …",
                    "preis": preis, "ez": ez, "monat": rng.randint(1, 9), "km": km, "marke": marke, "lang": lang})
    return ads


def such_html(ads: list[dict]) -> str:
    teile = []
    for a in ads:
        teile.append(f"""
<li class="ad-listitem"><article class="aditem" data-adid="{a['id']}" data-href="/s-anzeige/{a['slug']}/{a['id']}-220-1234">
 <div class="aditem-image"><a href="/s-anzeige/{a['slug']}/{a['id']}-220-1234">
   <div class="imagebox srpimagebox" data-imgsrc="https://img.kleinanzeigen.de/api/v1/prod-ads/images/{a['id']}.jpg"></div></a></div>
 <div class="aditem-main"><div class="aditem-main--top">
   <div class="aditem-main--top--left"><i></i> {a['plz']} {a['ort']}</div>
   <div class="aditem-main--top--right">Heute, 10:12</div></div>
 <div class="aditem-main--middle">
   <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/{a['slug']}/{a['id']}-220-1234">{a['titel']}</a></h2>
   <p class="aditem-main--middle--description">{a['kurz']}</p>
   <div class="aditem-main--middle--price-shipping">
     <p class="aditem-main--middle--price-shipping--price">{tsd(a['preis'])} € VB</p></div></div>
 <div class="aditem-main--bottom"><p class="text-module-end">
   <span class="simpletag">EZ 0{a['monat']}/{a['ez']}</span></p></div></div>
</article></li>""")
    return f"<html><body><ul id='srchrslt-adtable'>{''.join(teile)}</ul></body></html>"


def detail_html(a: dict, marke_feld: str | None = None) -> str:
    return f"""<html><body>
<h1 id="viewad-title">{a['titel']}</h1>
<h2 id="viewad-price">{tsd(a['preis'])} € VB</h2>
<div id="viewad-details"><ul class="addetailslist">
 <li class="addetailslist--detail">Marke<span class="addetailslist--detail--value">{marke_feld or a['marke']}</span></li>
 <li class="addetailslist--detail">Kilometerstand<span class="addetailslist--detail--value">{tsd(a['km'])} km</span></li>
 <li class="addetailslist--detail">Erstzulassung<span class="addetailslist--detail--value">Mai {a['ez']}</span></li>
 <li class="addetailslist--detail">Art<span class="addetailslist--detail--value">Teilintegrierter</span></li>
</ul></div>
<p id="viewad-description-text">{a['lang']}</p>
<div id="viewad-contact"><span class="userprofile-vip">Privater Nutzer</span></div>
</body></html>"""


class FakeAbruf:
    """Beantwortet Such- und Detail-URLs aus den Testdaten. `fehlend`: IDs, die mit HTTP 404 antworten."""

    def __init__(self, ads: list[dict], seitengroesse: int = 25, fehlend: set[str] | None = None):
        self.ads = {a["id"]: a for a in ads}
        self.seiten = [ads[i:i + seitengroesse] for i in range(0, len(ads), seitengroesse)]
        self.fehlend = fehlend or set()
        self.abrufe: list[str] = []

    def hole(self, url: str) -> str:
        self.abrufe.append(url)
        if "/s-anzeige/" in url:
            ad_id = url.rsplit("/", 1)[1].split("-")[0]
            if ad_id in self.fehlend:
                raise HttpFehler(404, url)
            return detail_html(self.ads[ad_id])
        n = int(url.split("seite:")[1].split("/")[0]) if "seite:" in url else 1
        return such_html(self.seiten[n - 1]) if n <= len(self.seiten) else "<html></html>"


class AntwortAbruf:
    """Liefert für jede URL dieselbe Antwort bzw. wirft dieselbe Ausnahme."""

    def __init__(self, antwort: str | Exception):
        self.antwort = antwort

    def hole(self, url: str) -> str:
        if isinstance(self.antwort, Exception):
            raise self.antwort
        return self.antwort
