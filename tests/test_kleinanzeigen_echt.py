"""Kleinanzeigen-Seiten im neuen Layout (P2-05, Teil 2): Testdaten stammen aus echten, vom Betreiber am 13.10.2026 im
Browser gespeicherten Seiten (anonymisiert und gekürzt, siehe tests/seiten/kleinanzeigen/).

Grenze: Die Dateien sind ein Ausschnitt (6 Treffer, 1 Anzeigenseite). Andere Kategorien/Sonderfälle der Live-Seite
(z. B. Neufahrzeug-Karussells, Werbeblöcke) sind hier nicht abgedeckt.
"""
import re
import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from tests.daten import detail_html
from tests.test_seitenimport import KeinNetz
from wmscout.datenbank import Datenbank
from wmscout.eingang import erkenne_seite, fahrzeugart_der_suchseite
from wmscout.importer import Importer
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle
from wmscout.quellen.kleinanzeigen.parser import ez_aus_text, parse_detailseite, parse_suchseite

DATEN = Path(__file__).resolve().parent / "seiten" / "kleinanzeigen"
TEST_BILD = "https://img.kleinanzeigen.de/api/v1/prod-ads/images/test.jpg"
DETAIL_ID = "3445014229"
AEHNLICH = ("3360314517", "3107636982")           # „ähnliche Anzeigen“ auf der Detailseite


@pytest.fixture(scope="module")
def such():
    return (DATEN / "suchseite.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail():
    return (DATEN / "detailseite.html").read_text(encoding="utf-8")


def nach_id(treffer):
    return {t["id"]: t for t in treffer}


# ---------- Trefferliste ----------
def test_suchseite_alle_artikel_mit_pflichtfeldern(such):
    treffer = parse_suchseite(such)
    artikel = BeautifulSoup(such, "html.parser").select("article[data-adid]")
    assert len(artikel) == 6 and [t["id"] for t in treffer] == [a["data-adid"] for a in artikel]
    for t in treffer:
        assert t["url"].startswith("https://www.kleinanzeigen.de/s-anzeige/") and t["id"] in t["url"]
        assert t["titel"] and t["preis"] and re.match(r"^\d{5} \S", t["ort"])
        assert t["bild"] == TEST_BILD                       # direkte http-Adresse bzw. Rückfall auf ld+json
        assert t["ist_gesuch"] is False


def test_suchseite_felder_im_einzelnen(such):
    t = nach_id(parse_suchseite(such))
    pro_und_top = t["3539214061"]
    assert (pro_und_top["preis"], pro_und_top["vb"], pro_und_top["ez_jahr"]) == (63990, False, 2025)
    assert pro_und_top["gewerblich"] is True and pro_und_top["ort"] == "34346 Hann. Münden"

    top = t["3523850073"]                                   # nur „TOP“ (bezahlte Hervorhebung) – kein Händlerhinweis
    assert top["gewerblich"] is False
    assert (top["preis"], top["vb"]) == (34999, True)       # nicht der durchgestrichene Altpreis 37.500 €
    assert (top["ez_jahr"], top["km"], top["ort"]) == (2012, 98004, "40764 Langenfeld")
    assert top["marke"] == "Knaus"

    pro = t["3538135814"]
    assert pro["gewerblich"] is True and pro["ez_jahr"] == 2021 and pro["marke"] == "Sunlight"
    assert pro["datum"] == "Heute, 21:16"

    privat = t["3540264391"]
    assert privat["gewerblich"] is False and privat["ez_jahr"] == 2026 and privat["preis"] == 58498
    assert t["3533351185"]["km"] == 4000

    ohne_link = t["3540255999"]                             # Titel ohne Link (span in der Überschrift)
    assert ohne_link["titel"].startswith("Eurom Klima Anlage") and ohne_link["preis"] == 200
    assert ohne_link["ez_jahr"] is None and ohne_link["gewerblich"] is False
    assert "3540255999" in ohne_link["url"]


def test_suchseite_bild_nur_http_und_ld_json_rueckfall(such):
    # lokale Bilddatei (Browser-Speicherung) wird nicht übernommen; ld+json liefert die Adresse
    ohne_ld = re.sub(r'<script type="application/ld\+json">.*?</script>', "", such, flags=re.S)
    bilder = {t["id"]: t["bild"] for t in parse_suchseite(ohne_ld)}
    assert bilder["3539214061"] == TEST_BILD                # hier steht eine http-Adresse im Bild
    assert bilder["3523850073"] is None                     # nur lokaler Pfad, kein Rückfall mehr
    assert parse_suchseite(such)[1]["bild"] == TEST_BILD


def test_ld_json_zuordnung_ueber_bild_uuid():
    html = """<html><body><article data-adid="3500000001" data-href="/s-anzeige/x/3500000001-220-1">
      <img src="seite_files/11111111-2222-3333-4444-555555555555_002_ab.avif" alt="x">
      <h3><a href="/s-anzeige/x/3500000001-220-1">Gleicher Titel</a></h3><p>Text</p>
      <div class="flex"><p class="text-title3">1.000 €</p></div><span>10115 Berlin</span></article>
      <article data-adid="3500000002" data-href="/s-anzeige/y/3500000002-220-1">
      <img src="seite_files/66666666-7777-8888-9999-000000000000_002_ab.avif" alt="y">
      <h3><a href="/s-anzeige/y/3500000002-220-1">Gleicher Titel</a></h3><p>Text</p>
      <div class="flex"><p class="text-title3">2.000 €</p></div><span>10115 Berlin</span></article>
      <script type="application/ld+json">{"title":"Gleicher Titel","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/66/66666666-7777-8888-9999-000000000000?rule=x","@type":"ImageObject"}</script>
      <script type="application/ld+json">{"title":"Gleicher Titel","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/11/11111111-2222-3333-4444-555555555555?rule=x","@type":"ImageObject"}</script>
      <script type="application/ld+json">kaputt {</script></body></html>"""
    bilder = {t["id"]: t["bild"] for t in parse_suchseite(html)}
    assert bilder["3500000001"].endswith("11111111-2222-3333-4444-555555555555?rule=x")
    assert bilder["3500000002"].endswith("66666666-7777-8888-9999-000000000000?rule=x")


def test_gesuch_tag_wird_erkannt(such):
    gesuch = such.replace("EZ 08/2012", "Gesuch", 1)
    t = nach_id(parse_suchseite(gesuch))
    assert t["3523850073"]["ist_gesuch"] is True and t["3539214061"]["ist_gesuch"] is False
    art, inserate = erkenne_seite(gesuch)
    assert art == "suche" and len(inserate) == 5 and "3523850073" not in {i.anzeigen_id for i in inserate}


def test_ez_aus_text_formen():
    assert ez_aus_text("Erstzulassung Juli 2021") == 2021
    assert ez_aus_text("Erstzulassung März 2019") == 2019
    assert ez_aus_text("Erstzulassung: 2009 Kraftstoff: Benzin") == 2009
    assert ez_aus_text("Erstzulassung 07/2021") == 2021
    assert ez_aus_text("EZ 03/2019") == 2019
    assert ez_aus_text("Zulassung ohne Jahr") is None


# ---------- Anzeigenseite ----------
def test_detailseite_felder(detail):
    d = parse_detailseite(detail)
    assert d["titel"] == "Sunlight Cliff 640 Adventure Edition | Klima | Bikegarage | 1. Hd"
    assert (d["preis"], d["vb"]) == (49590, True)
    assert (d["km"], d["ez_jahr"], d["marke"], d["art"]) == (30750, 2021, "Sunlight", "Kastenwagen")
    assert d["anzeigen_id"] == DETAIL_ID
    assert d["gewerblich"] is False                         # „Privater Nutzer“; PRO-Links gibt es nur bei ähnlichen Anzeigen
    assert d["ort"] == "72581 Dettingen an der Erms"        # ohne Bundesland, wie in der Trefferliste
    assert d["details"] == {"Art": "Kastenwagen", "Marke": "Sunlight", "Kilometerstand": "30.750 km",
                            "Erstzulassung": "Juli 2021"}
    assert "Bikeenthusiasten" in d["beschreibung"]


def test_detailseite_gewerblich_nur_aus_verkaeuferbereich(detail):
    haendler = detail.replace("Privater Nutzer", "Gewerblicher Nutzer")
    assert parse_detailseite(haendler)["gewerblich"] is True
    pro_aehnlich = detail.replace("</section>", '<article data-adid="3500000009"><a href="/pro/x">PRO</a></article></section>')
    assert parse_detailseite(pro_aehnlich)["gewerblich"] is False
    pro_verkaeufer = detail.replace("</body>", '<a href="https://www.kleinanzeigen.de/pro/shop">Shop</a></body>')
    assert parse_detailseite(pro_verkaeufer)["gewerblich"] is True


def test_altes_detailformat_hat_keine_anzeigen_id(ads):
    d = parse_detailseite(detail_html(ads[0]))
    assert d["anzeigen_id"] is None and d["km"] == ads[0]["km"]


def test_erkennung_detailseite_nur_die_eigene_anzeige(detail):
    art, inserate = erkenne_seite(detail)
    assert art == "detail" and [i.anzeigen_id for i in inserate] == [DETAIL_ID]
    i = inserate[0]
    assert i.url == ("https://www.kleinanzeigen.de/s-anzeige/sunlight-cliff-640-adventure-edition-klima-bikegarage-1-hd/"
                     f"{DETAIL_ID}-220-7998")
    assert (i.preis, i.km, i.ez_jahr, i.marke, i.art, i.gewerblich) == (49590, 30750, 2021, "Sunlight", "Kastenwagen", False)


def test_detailseite_ohne_canonical_nutzt_anzeigen_id_kasten(detail):
    ohne_meta = re.sub(r'<meta rel="canonical"[^>]*>', "", detail)
    # Die Seite selbst nennt ihre Adresse noch in einem Link/JSON-Block – der gehört zur ID und wird genommen
    art, inserate = erkenne_seite(ohne_meta)
    assert art == "detail" and inserate[0].anzeigen_id == DETAIL_ID
    assert inserate[0].url.endswith(f"/{DETAIL_ID}-220-7998")
    # Ganz ohne Adresse: Ersatz-URL aus der ID
    ohne_alles = re.sub(r"<script[^>]*>.*?</script>", "", ohne_meta, flags=re.S)
    art, inserate = erkenne_seite(ohne_alles)
    assert art == "detail" and inserate[0].anzeigen_id == DETAIL_ID
    assert inserate[0].url == f"https://www.kleinanzeigen.de/s-anzeige/{DETAIL_ID}"
    # Weder Adresse noch ID-Kasten: bleibt „detail_ohne_id“
    ohne_id = re.sub(r'<div[^>]*id="viewad-ad-id-box".*?</div></div>', "", ohne_alles, flags=re.S)
    assert erkenne_seite(ohne_id) == ("detail_ohne_id", [])


def test_adapter_details_mit_neuem_feld(cfg, detail):
    class Abruf:
        def hole(self, url):
            return detail

    q = KleinanzeigenQuelle(cfg, Abruf())
    i = q.details(f"https://www.kleinanzeigen.de/s-anzeige/x/{DETAIL_ID}-220-7998")
    assert i.anzeigen_id == DETAIL_ID and i.km == 30750 and i.ez_jahr == 2021
    assert q.details("https://www.kleinanzeigen.de/s-anzeige/x").anzeigen_id == DETAIL_ID   # URL ohne ID → Kasten


# ---------- Fahrzeugart der Suchseite (echte canonical-Adressen) ----------
@pytest.mark.parametrize("canonical, erwartet", [
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/teilintegriert/k0c220", "Teilintegrierter"),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/kastenwagen/k0c220", "Kastenwagen"),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/camper/k0c220", "Kastenwagen"),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/campingbus/k0c220", "Kastenwagen"),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/alkoven/k0c220", "Alkoven"),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/reisemobil/k0c220", None),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/hymer/k0c220", None),
    ("https://www.kleinanzeigen.de/s-knaus/k0", None),
    ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/70191/wohnmobil/k0c220l9293", None),
    ("https://www.kleinanzeigen.de/s-70191/sortierung:entfernung/anbieter:privat/wohnmobil-640/k0l9293r1000", None),
])
def test_fahrzeugart_aus_echten_canonical_adressen(canonical, erwartet):
    html = (f'<html><head><title>Treffer | kleinanzeigen.de</title><link href="{canonical}" rel="canonical"/>'
            '<meta content="https://www.kleinanzeigen.de/s-suchen.html" property="og:url"/></head><body></body></html>')
    assert fahrzeugart_der_suchseite(html) == erwartet


def test_fahrzeugart_der_testsuchseite(such):
    assert fahrzeugart_der_suchseite(such) == "Teilintegrierter"


# ---------- Import ----------
@pytest.fixture
def ordner(cfg, tmp_path):
    o = tmp_path / "import"
    o.mkdir()
    cfg["import"] = {"ordner": str(o)}
    return o


def test_import_beider_seiten(cfg, db: Datenbank, ordner):
    shutil.copy(DATEN / "suchseite.html", ordner / "suchseite.html")
    shutil.copy(DATEN / "detailseite.html", ordner / "detailseite.html")
    netz = KeinNetz()
    stat = Importer(cfg, db, abruf=netz).importiere_seiten(ordner)
    assert stat["fehler"] == [] and netz.abrufe == []
    assert (stat["dateien"], stat["suchseiten"], stat["detailseiten"], stat["unbekannt"], stat["fehlerhaft"]) == (2, 1, 1, 0, 0)
    assert (stat["neu"], stat["details"]) == (7, 1)
    assert not (ordner / "nicht_erkannt").exists()

    zeilen = {z["id"]: z for z in db.con.execute("SELECT * FROM anzeigen")}
    assert len(zeilen) == 7                                  # 6 Treffer + die Anzeige selbst
    assert not set(AEHNLICH) & set(zeilen)                   # „ähnliche Anzeigen“ der Detailseite werden nicht importiert
    for ad_id, z in zeilen.items():
        if ad_id != DETAIL_ID:
            assert z["suche"] == "Import Teilintegrierter" and z["detail_geladen"] == 0 and z["bild"] == TEST_BILD
    assert zeilen["3539214061"]["gewerblich"] == 1 and zeilen["3523850073"]["gewerblich"] == 0
    d = zeilen[DETAIL_ID]
    assert d["detail_geladen"] == 1 and d["suche"].startswith("Import")
    assert (d["preis"], d["km"], d["ez_jahr"], d["marke"], d["art"]) == (49590, 30750, 2021, "Sunlight", "Kastenwagen")
    assert d["ort"] == "72581 Dettingen an der Erms" and d["vb"] == 1


def test_import_detailseite_ergaenzt_bekanntes_inserat(cfg, db: Datenbank, ordner, such, detail):
    # dieselbe Anzeige zuerst aus einer Trefferliste, dann als Anzeigenseite → ein Datensatz, Details ergänzt
    liste = such.replace("3523850073", DETAIL_ID)
    (ordner / "liste.html").write_text(liste, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    (ordner / "anzeige.html").write_text(detail, encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["detailseiten"], stat["neu"], stat["bekannt"]) == (1, 0, 1)
    z = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (DETAIL_ID,)).fetchone()
    assert z["suche"] == "Import Teilintegrierter" and z["detail_geladen"] == 1 and z["km"] == 30750
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 6
