"""Offline-Test mit nachgebautem Kleinanzeigen-Markup.  Start:  python -m tests.test_offline"""
import copy
import http.client
import json
import random
import shutil
import tempfile
import threading
from datetime import date
from pathlib import Path

import yaml

from wmscout import crawler as crawler_mod
from wmscout.anschreiben import Anschreiber, euro
from wmscout.app import erstelle_server
from wmscout.crawler import Crawler, seiten_url
from wmscout.db import Datenbank
from wmscout.fahrzeug import ergaenze_fahrzeug, marke_aus_text, modell_aus_text
from wmscout.parser import parse_detailseite, parse_suchseite
from wmscout.rechner import Rechner
from wmscout.report import bewerte_alle, schreibe_ausgaben

BASIS = Path(__file__).resolve().parent.parent
random.seed(4)
MARKEN = ["Knaus", "Hymer", "Dethleffs", "Bürstner", "Pössl", "Weinsberg"]
CFG = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))


def tsd(x):
    return f"{x:,}".replace(",", ".")


def such_html(ads):
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
   <span class="simpletag">EZ 0{random.randint(1,9)}/{a['ez']}</span></p></div></div>
</article></li>""")
    return f"<html><body><ul id='srchrslt-adtable'>{''.join(teile)}</ul></body></html>"


def detail_html(a, marke_feld=None):
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


MODELL_NAMEN = {"Knaus": "Sky TI 650 MEG", "Hymer": "ML-T 570", "Dethleffs": "Trend T 7057 EB",
                "Bürstner": "Lyseo TD 728 G", "Pössl": "Summit 600", "Weinsberg": "CaraCompact 600 MEG"}


def baue_ads(n=60):
    ads = []
    for i in range(n):
        marke = random.choice(MARKEN)
        ez = random.randint(2008, 2022)
        km = random.randint(20, 180) * 1000
        basis = 85000 * (0.92 ** (2025 - ez)) - km * 0.08
        preis = int(basis * random.uniform(0.85, 1.2) / 100) * 100
        lang = "Gepflegtes Fahrzeug, scheckheftgepflegt, Nichtraucher, keine Feuchtigkeit."
        if i % 9 == 0:
            lang += " Keine Händleranfragen!"
        ads.append({"id": str(3500000000 + i), "slug": f"wohnmobil-{i}", "plz": "70173", "ort": "Stuttgart",
                    "titel": f"{marke} {MODELL_NAMEN[marke]} T{i}", "kurz": "Verkaufe unser Wohnmobil …",
                    "preis": preis, "ez": ez, "km": km, "marke": marke, "lang": lang})
    return ads


def test_fahrzeug():
    faelle = {
        "Fiat Ducato Knaus Sky Ti 650 MEG 2017": ("Knaus", "Sky TI 650 MEG"),
        "Hymer B 678 SL Scheckheft": ("Hymer", "B 678 SL"),
        "Sunlight T68 Teilintegriert EZ 2018": ("Sunlight", "T 68"),
        "VW California Ocean 2016 mit Aufstelldach": ("Volkswagen", "California Ocean"),
        "Poessl Summit 600 Plus": ("Pössl", "Summit 600"),
        "Wohnmobil Dethleffs Trend T 7057 EB": ("Dethleffs", "Trend T 7057 EB"),
        "Knaus Wohnmobil 2015": ("Knaus", None),
    }
    for titel, (marke, modell) in faelle.items():
        m = marke_aus_text(titel)
        assert m == marke, (titel, m)
        assert modell_aus_text(m, titel) == modell, (titel, modell_aus_text(m, titel))
    a = ergaenze_fahrzeug({"titel": "Wohnmobil zu verkaufen", "marke": "Fiat",
                           "beschreibung": "Wir verkaufen unseren Weinsberg CaraBus 600 MQ"})
    assert a["fahrzeug"] == "Weinsberg CaraBus 600 MQ", a


def test_rechner():
    cfg = copy.deepcopy(CFG)
    r = Rechner(cfg)
    ez = date.today().year - 8
    a = {"id": "x", "suche": "Teilintegrierter", "marke": "Knaus", "ez_jahr": ez, "km": 80000, "preis": 45000,
         "titel": "Knaus Sky TI 650", "beschreibung": "Markise, Solar, keine Feuchtigkeit, rostfrei"}

    # Wertfaktoren: verneinte Mängel zählen nicht, Ausstattung schon
    wf = r.wertfaktoren(a)
    assert set(wf) == {"Markise", "Solaranlage"}, wf
    for text, erwartet in [("Feuchtigkeit im Heck", {"Feuchtigkeit"}), ("feuchtigkeitsfrei", set()),
                           ("Feuchtigkeitsmessung ohne Befund", set()), ("keine Risse, Feuchtigkeit oder Rost", set()),
                           ("Kein Rost, aber Feuchtigkeit hinten", {"Feuchtigkeit"}), ("Rostschutz neu", set())]:
        assert set(r.wertfaktoren({"beschreibung": text})) == erwartet, (text, r.wertfaktoren({"beschreibung": text}))

    # Ohne Vergleiche: Referenzmodell, Sicherheit niedrig, Ampel wird trotzdem bestimmt
    b0 = r.bewerte(a, [])
    assert b0.sicherheit == "niedrig" and b0.vergleich_anzahl == 0 and b0.ampel in ("gruen", "gelb", "rot"), b0
    assert b0.marktwert_angebote == round(b0.modellwert / 50) * 50

    # Mit Vergleichen, die 20 % über dem Modell liegen: Schätzung wandert Richtung Markt (gewichtet n/(n+k))
    vergleich = []
    for i in range(20):
        b = {"id": f"v{i}", "suche": "Teilintegrierter", "marke": "Knaus" if i % 2 else "Hymer",
             "ez_jahr": ez + (i % 5) - 2, "km": 60000 + i * 3000, "titel": "Vergleich", "zuletzt_gesehen": "2999"}
        b["preis"] = int(r.modellwert(b)[0] * 1.2)
        vergleich.append(b)
    vergleich.append({**vergleich[0], "id": "ausreisser", "preis": 999999})
    b1 = Rechner(cfg).bewerte(a, vergleich)
    g = 20 / (20 + cfg["rechner"]["vergleich_gewicht_k"])
    assert b1.vergleich_anzahl == 20, b1.vergleich_anzahl                  # Ausreißer entfernt
    assert abs(b1.marktfaktor - (1 + 0.2 * g)) < 0.01, b1.marktfaktor
    assert b1.sicherheit == "hoch", b1.sicherheit

    # Fairness: Erstangebot nie über Wunschpreis, nie unter Untergrenze (außer Max-EK liegt darunter)
    for preis in (15000, 30000, 45000, 60000):
        for jahre in (2, 8, 15, 22):
            x = {**a, "id": f"f{preis}{jahre}", "preis": preis, "ez_jahr": date.today().year - jahre}
            b = Rechner(cfg).bewerte(x, vergleich)
            assert b.erstangebot <= preis, (preis, jahre, b)
            assert b.erstangebot <= b.max_ek, b
            boden = cfg["rechner"]["fair_untergrenze_privatwert"] * b.marktwert_privat
            assert b.erstangebot >= min(boden, b.max_ek, preis * 0.95) - 100, (preis, jahre, b.erstangebot, boden)

    # Ohne Erstzulassung: keine Bewertung, kein Betrag im Anschreiben
    ohne = {**a, "id": "ohne", "ez_jahr": None}
    b2 = r.bewerte(ohne, vergleich)
    assert b2.ampel == "grau" and b2.sicherheit == "keine", b2
    text = Anschreiber(cfg, BASIS).text(ergaenze_fahrzeug(ohne), b2)
    assert "€" not in text and "Erstzulassung" in text, text


def test_anschreiben():
    cfg = copy.deepcopy(CFG)
    ez = date.today().year - 9
    a = ergaenze_fahrzeug({"id": "y", "suche": "Teilintegrierter", "titel": "Knaus Sky TI 650 MEG Platinum",
                           "ez_jahr": ez, "km": 85000, "preis": 52000, "vb": True, "ort": "70173 Stuttgart",
                           "beschreibung": "Markise, Rückfahrkamera, Scheckheft"})
    b = Rechner(cfg).bewerte(a, [])
    t = Anschreiber(cfg, BASIS).text(a, b)
    for teil in (f"Knaus Sky TI 650 MEG (EZ {ez}, rund 85.000 km)", "Vorbehaltlich einer Besichtigung",
                 euro(b.erstangebot), "unverbindlich", "Markise und Rückfahrkamera", "das Scheckheft",
                 f"Wohnmobil aus {ez}", "Besichtigung in Stuttgart", "gewerblicher Ankäufer"):
        assert teil in t, (teil, t)
    if b.ampel != "gruen":
        assert "Wunschpreis von 52.000 €" in t, t
    jung = ergaenze_fahrzeug({**a, "id": "z", "ez_jahr": date.today().year - 2, "beschreibung": ""})
    assert "Herstellergarantie" in Anschreiber(cfg, BASIS).text(jung, Rechner(cfg).bewerte(jung, [])).replace(
        "Hersteller- bzw. Dichtigkeitsgarantie", "Herstellergarantie")


def test_app(cfg, db, ad_id):
    server, token = erstelle_server(cfg, db, BASIS, port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        def anfrage(methode, pfad, daten=None, kopf=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request(methode, pfad, body=json.dumps(daten) if daten is not None else None,
                      headers={"Content-Type": "application/json", **(kopf or {})})
            r = c.getresponse()
            return r.status, r.read().decode("utf-8")

        status, html = anfrage("GET", "/")
        assert status == 200 and "Wohnmobil-Scout" in html and token in html, status
        assert anfrage("POST", "/api/status", {"id": ad_id, "status": "kontaktiert"})[0] == 403
        assert anfrage("GET", "/", kopf={"Host": "boese.example:80"})[0] == 403
        status, _ = anfrage("POST", "/api/status", {"id": ad_id, "status": "kontaktiert", "text": "Hallo Test"},
                            {"X-Scout-Token": token})
        assert status == 200
        zeile = db.con.execute("SELECT status, anschreiben_text, kontaktiert_am FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        assert zeile["status"] == "kontaktiert" and zeile["anschreiben_text"] == "Hallo Test" and zeile["kontaktiert_am"]
        assert anfrage("POST", "/api/notiz", {"id": ad_id, "notiz": "Rückruf Fr"}, {"X-Scout-Token": token})[0] == 200
        assert anfrage("POST", "/api/status", {"id": ad_id, "status": "quatsch"}, {"X-Scout-Token": token})[0] == 400
        status, html = anfrage("GET", "/")
        assert "Hallo Test" in html and "Rückruf Fr" in html
        assert anfrage("POST", "/api/status", {"id": ad_id, "status": "neu"}, {"X-Scout-Token": token})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def main():
    # Einheiten-Tests
    assert seiten_url("https://x.de/s-wohnwagen-mobile/anbieter:privat/c220+a:b", 3) == \
        "https://x.de/s-wohnwagen-mobile/anbieter:privat/seite:3/c220+a:b"
    test_fahrzeug()
    test_rechner()
    test_anschreiben()

    ads = baue_ads()
    seiten = [ads[i:i + 25] for i in range(0, len(ads), 25)]
    p = parse_suchseite(such_html(seiten[0]))
    assert len(p) == 25 and p[0]["preis"] == ads[0]["preis"] and p[0]["ez_jahr"] == ads[0]["ez"], p[0]
    assert p[0]["bild"].endswith(f"{ads[0]['id']}.jpg"), p[0]["bild"]
    d = parse_detailseite(detail_html(ads[0]))
    assert d["km"] == ads[0]["km"] and d["marke"] == ads[0]["marke"] and d["ez_jahr"] == ads[0]["ez"], d
    d = parse_detailseite(detail_html({**ads[0], "titel": "Fiat Ducato Knaus Sky TI 650"}, marke_feld="Fiat"))
    assert d["marke"] == "Knaus", d["marke"]

    # End-to-End mit gefälschtem Netz
    tmp = Path(tempfile.mkdtemp())
    cfg = copy.deepcopy(CFG)
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
    assert all(not z["brief"] and not z["bereit"] for z in gesperrt)
    assert all(z["b"].vergleich_anzahl > 0 for z in zeilen), "Vergleichsbasis fehlt"
    assert all(z["a"]["modell"] for z in zeilen), [z["a"]["titel"] for z in zeilen if not z["a"]["modell"]]
    bereit = [z for z in zeilen if z["bereit"]]
    assert bereit and all(z["a"]["fahrzeug"] in z["brief"] and "Vorbehaltlich" in z["brief"] for z in bereit)
    assert len(list((tmp / "ausgabe" / "anschreiben").glob("*.txt"))) == len(bereit)
    print("OK", stat, erg["zaehl"])

    test_app(cfg, db, bereit[0]["a"]["id"])
    print("App-Server OK")

    beispiel = bereit[0]
    print("\n--- Beispiel-Anschreiben ---\n" + beispiel["brief"])
    ziel = BASIS / "tests" / "beispiel_report.html"
    shutil.copy(erg["html"], ziel)
    print("\nReport:", ziel)


if __name__ == "__main__":
    main()
