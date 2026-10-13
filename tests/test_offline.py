"""Offline-Test mit nachgebautem Kleinanzeigen-Markup.  Start:  python -m tests.test_offline"""
import random
import shutil
import tempfile
from pathlib import Path

import yaml

from wmscout import crawler as crawler_mod
from wmscout.crawler import Crawler, seiten_url
from wmscout.db import Datenbank
from wmscout.parser import parse_detailseite, parse_suchseite
from wmscout.report import bewerte_alle, schreibe_ausgaben

BASIS = Path(__file__).resolve().parent.parent
random.seed(4)
MARKEN = ["Knaus", "Hymer", "Dethleffs", "Bürstner", "Pössl", "Weinsberg"]


def tsd(x):
    return f"{x:,}".replace(",", ".")


def such_html(ads):
    teile = []
    for a in ads:
        teile.append(f"""
<li class="ad-listitem"><article class="aditem" data-adid="{a['id']}" data-href="/s-anzeige/{a['slug']}/{a['id']}-220-1234">
 <div class="aditem-main"><div class="aditem-main--top">
   <div class="aditem-main--top--left"><i></i> {a['plz']} {a['ort']}</div>
   <div class="aditem-main--top--right">Heute, 10:12</div></div>
 <div class="aditem-main--middle">
   <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/{a['slug']}/{a['id']}-220-1234">{a['titel']}</a></h2>
   <p class="aditem-main--middle--description">{a['kurz']}</p>
   <div class="aditem-main--middle--price-shipping">
     <p class="aditem-main--middle--price-shipping--price">{tsd(a['preis'])} € VB</p></div></div>
 <div class="aditem-main--bottom"><p class="text-module-end">
   <span class="simpletag">EZ 0{random.randint(1,9)}/{a['ez']}</span></p></div></div>
</article></li>""")
    return f"<html><body><ul id='srchrslt-adtable'>{''.join(teile)}</ul></body></html>"


def detail_html(a):
    return f"""<html><body>
<h1 id="viewad-title">{a['titel']}</h1>
<h2 id="viewad-price">{tsd(a['preis'])} € VB</h2>
<div id="viewad-details"><ul class="addetailslist">
 <li class="addetailslist--detail">Marke<span class="addetailslist--detail--value">{a['marke']}</span></li>
 <li class="addetailslist--detail">Kilometerstand<span class="addetailslist--detail--value">{tsd(a['km'])} km</span></li>
 <li class="addetailslist--detail">Erstzulassung<span class="addetailslist--detail--value">Mai {a['ez']}</span></li>
 <li class="addetailslist--detail">Art<span class="addetailslist--detail--value">Teilintegrierter</span></li>
</ul></div>
<p id="viewad-description-text">{a['lang']}</p>
<div id="viewad-contact"><span class="userprofile-vip">Privater Nutzer</span></div>
</body></html>"""


def baue_ads(n=60):
    ads = []
    for i in range(n):
        marke = random.choice(MARKEN)
        ez = random.randint(2008, 2022)
        km = random.randint(20, 180) * 1000
        basis = 85000 * (0.92 ** (2025 - ez)) - km * 0.08
        preis = int(basis * random.uniform(0.85, 1.2) / 100) * 100
        lang = "Gepflegtes Fahrzeug, scheckheftgepflegt, Nichtraucher."
        if i % 9 == 0:
            lang += " Keine Händleranfragen!"
        ads.append({"id": str(3500000000 + i), "slug": f"wohnmobil-{i}", "plz": "70173", "ort": "Stuttgart",
                    "titel": f"{marke} Teilintegrierter T{i}", "kurz": "Verkaufe unser Wohnmobil …",
                    "preis": preis, "ez": ez, "km": km, "marke": marke, "lang": lang})
    return ads


def main():
    # Einheiten-Tests
    assert seiten_url("https://x.de/s-wohnwagen-mobile/anbieter:privat/c220+a:b", 3) == \
        "https://x.de/s-wohnwagen-mobile/anbieter:privat/seite:3/c220+a:b"
    ads = baue_ads()
    seiten = [ads[i:i + 25] for i in range(0, len(ads), 25)]
    p = parse_suchseite(such_html(seiten[0]))
    assert len(p) == 25 and p[0]["preis"] == ads[0]["preis"] and p[0]["ez_jahr"] == ads[0]["ez"], p[0]
    d = parse_detailseite(detail_html(ads[0]))
    assert d["km"] == ads[0]["km"] and d["marke"] == ads[0]["marke"] and d["ez_jahr"] == ads[0]["ez"], d

    # End-to-End mit gefälschtem Netz
    tmp = Path(tempfile.mkdtemp())
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    cfg["suchen"] = [{"name": "Teilintegrierter", "url": "https://www.kleinanzeigen.de/s-wohnwagen-mobile/c220"}]
    cfg["crawler"].update(pause_min_sek=0, pause_max_sek=0, detailseiten_pro_lauf=100)
    cfg["ausgabe"]["ordner"] = str(tmp / "ausgabe")
    db = Datenbank(str(tmp / "t.sqlite"))
    nach_id = {a["id"]: a for a in ads}

    def falsch_hole(self, url):
        if "/s-anzeige/" in url:
            return detail_html(nach_id[url.rsplit("/", 1)[1].split("-")[0]])
        n = int(url.split("seite:")[1].split("/")[0]) if "seite:" in url else 1
        return such_html(seiten[n - 1]) if n <= len(seiten) else "<html></html>"

    crawler_mod.Crawler._hole = falsch_hole
    stat = Crawler(cfg, db).lauf(cfg["suchen"])
    assert stat["neu"] == 60 and stat["details"] == 60, stat
    zeilen = bewerte_alle(cfg, db, BASIS, lauf_start="2000")
    erg = schreibe_ausgaben(cfg, zeilen, BASIS)
    gesperrt = [z for z in zeilen if z["sperre"] and "Sperrbegriff" in z["sperre"]]
    assert len(gesperrt) == 7, len(gesperrt)
    assert all(not z["brief"] for z in gesperrt)
    print("OK", stat, erg["zaehl"])
    beispiel = next(z for z in zeilen if z["brief"])
    print("\n--- Beispiel-Anschreiben ---\n" + beispiel["brief"])
    ziel = BASIS / "tests" / "beispiel_report.html"
    shutil.copy(erg["html"], ziel)
    print("\nReport:", ziel)


if __name__ == "__main__":
    main()
