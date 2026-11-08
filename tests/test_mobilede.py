"""mobile.de: im Browser gespeicherte Such- und Anzeigenseiten (P2-05b, ADR-010) – erkennen, parsen, importieren, ohne Netzabruf.

Die Testseiten unter tests/seiten/mobilede/ sind dem Aufbau echter, vom Betreiber am 14.10.2026 gespeicherter Seiten nachgebaut
(Wohnmobil-Suche „alle“, „Privatanbieter“, „Firmenfahrzeuge“ und Anzeigenseiten): Struktur, `data-testid`-Attribute und Klassennamen
stimmen mit dem Original überein; ALLE Inhalte sind erfunden (IDs, Orte, PLZ, Titel, Namen, Bewertungen, Texte und jede Zahl:
Preise, km, EZ-Monate, kW, Längen, Gewichte, Halterzahl, HU, Farben, Schlafplätze) – keine Kombination entspricht einer echten
Anzeige, Skripte und Tracking sind entfernt. Telefonnummer „0170 0000000“, Anbietername und Straße in detailseite.html sind ebenfalls
erfunden; sie sind absichtlich in der Seite und dürfen nirgends ausgegeben werden (`test_datenschutz_*`).

Grenzen: Eine Anzeigenseite eines gewerblichen Anbieters lag nicht vor – der Test dafür (`test_anzeigenseite_gewerblich`) beruht auf
der Annahme, dass dort statt „Privatanbieter“ ein anderer Anbietertyp in `seller-title-address` steht. Gespeichert wurde in allen
Originalen als „Webseite, komplett“; „nur HTML“ wurde nicht geprüft.
"""
import json
import logging
import shutil
from datetime import date
from pathlib import Path

import pytest

from tests.test_handy import OEFFENTLICH, Client, server, team  # noqa: F401 – Fixtures des Handy-Tests
from tests.test_kleinanzeigen_echt import DETAIL_ID as KA_DETAIL_ID
from tests.test_seitenimport import KeinNetz
from wmscout.ausgabe import schreibe_ausgaben
from wmscout.bewertung.anschreiben import (HINWEIS_ANBIETER_UNBEKANNT, HINWEIS_ART_UNBEKANNT_ANFANG, HINWEIS_ART_VORLAEUFIG, HINWEIS_AUSLAND,
                                           hinweise)
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenbank import BESTAETIGT, IMPORT_SUCHE, Datenbank, import_art
from wmscout.eingang import erkenne_seite, erkenne_seite_mit_hinweisen, ist_mobilede_seite, plattform_der_seite
from wmscout.importer import Importer
from wmscout.quellen.basis import Inserat
from wmscout.quellen.mobilede import (ID_PRAEFIX, KENNUNG, anzeigen_id_aus_url, detail_url, parse_detailseite, parse_suchseite,
                                      parse_suchseite_mit_hinweisen)
from wmscout.quellen.mobilede.parser import _ort, _preis
from wmscout.web.api import fahrzeug_kurz

DATEN = Path(__file__).resolve().parent / "seiten" / "mobilede"
KA_DATEN = Path(__file__).resolve().parent / "seiten" / "kleinanzeigen"
DETAIL_ID = "md-3900000010"
N = "\u00a0"                       # geschütztes Leerzeichen, wie in den mobile.de-Seiten


@pytest.fixture(scope="module")
def such():
    return (DATEN / "suchseite.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def privat():
    return (DATEN / "suchseite_privat.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail():
    return (DATEN / "detailseite.html").read_text(encoding="utf-8")


@pytest.fixture
def ordner(cfg, tmp_path):
    o = tmp_path / "import"
    o.mkdir()
    cfg["import"] = {"ordner": str(o)}
    return o


def nach_id(treffer):
    return {t["id"]: t for t in treffer}


def zeile(db, ad_id):
    return db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()


# ---------- Erkennung ----------
def test_plattform_und_seitenart_der_testseiten(such, privat, detail):
    assert [plattform_der_seite(h) for h in (such, privat, detail)] == [KENNUNG] * 3
    assert [erkenne_seite(h)[0] for h in (such, privat, detail)] == ["suche", "suche", "detail"]


def test_kleinanzeigen_wird_weiter_als_kleinanzeigen_erkannt():
    for datei, art in (("suchseite.html", "suche"), ("detailseite.html", "detail")):
        html = (KA_DATEN / datei).read_text(encoding="utf-8")
        assert not ist_mobilede_seite(html) and plattform_der_seite(html) == "kleinanzeigen"
        assert erkenne_seite(html)[0] == art and {i.quelle for i in erkenne_seite(html)[1]} == {"kleinanzeigen"}


def test_suchseite_ohne_canonical_wird_ueber_og_site_name_erkannt(such):
    kopf = such[:such.index("</head>")]
    assert "canonical" not in kopf and 'property="og:url"' not in kopf and "saved from" not in such[:2000]
    assert 'property="og:site_name" content="mobile_de"' in kopf and ist_mobilede_seite(such)


@pytest.mark.parametrize("kopf, erwartet", [
    ('<link rel="canonical" href="https://suchen.mobile.de/fahrzeuge/details.html?id=1234567">', True),
    ('<meta property="og:url" content="https://www.mobile.de/auto/x">', True),
    ('<meta property="og:site_name" content="mobile.de">', True),
    ('<meta property="og:site_name" content="Kleinanzeigen">', False),
    ('<link rel="canonical" href="https://www.kleinanzeigen.de/s-anzeige/x/1234567-220-1">', False),
    ('<link rel="canonical" href="https://www.evil-mobile.de.example.com/x">', False),     # nur der Host zählt, nicht ein Teilstring
    ('<link rel="canonical" href="https://notmobile.de/x">', False),
])
def test_erkennung_nur_aus_dem_kopf(kopf, erwartet):
    assert ist_mobilede_seite(f"<html><head>{kopf}</head><body></body></html>") is erwartet


def test_link_im_seitentext_macht_keine_mobilede_seite():
    html = ('<html><head><link rel="canonical" href="https://www.kleinanzeigen.de/s-anzeige/x/1234567-220-1"></head>'
            '<body><a href="https://suchen.mobile.de/fahrzeuge/details.html?id=39000000">mobile.de</a></body></html>')
    assert not ist_mobilede_seite(html)


def test_speichervermerk_des_browsers_genuegt():
    html = ("<!-- saved from url=(0070)https://suchen.mobile.de/fahrzeuge/details.html?id=3900000077&vip=1 -->\n"
            "<html><head></head><body></body></html>")
    assert ist_mobilede_seite(html)
    assert erkenne_seite(html) == ("unbekannt", [])                  # Adresse ohne Anzeigeninhalt: nichts zu lesen


def test_fremde_seite_von_mobilede_ist_unbekannt():
    html = '<html><head><meta property="og:site_name" content="mobile.de"></head><body><h1>Parkplatz</h1></body></html>'
    assert erkenne_seite(html) == ("unbekannt", [])


def test_anzeigenseite_ohne_adresse_ist_detail_ohne_id(detail):
    ohne = detail.replace('<link rel="canonical"', '<link rel="x-canonical"').replace('<meta property="og:url"', '<meta property="x-og:url"')
    assert erkenne_seite(ohne) == ("detail_ohne_id", [])


def test_anzeigen_id_aus_adresse():
    assert anzeigen_id_aus_url("https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010&vip=1") == "md-3900000010"
    assert anzeigen_id_aus_url("https://suchen.mobile.de/fahrzeuge/details.html?vc=Motorhome&amp;id=390000019&amp;st=FSBO") == "md-390000019"
    assert anzeigen_id_aus_url("https://suchen.mobile.de/fahrzeuge/search.html?id=3900000010") is None
    assert anzeigen_id_aus_url("https://suchen.mobile.de/fahrzeuge/details.html?id=12") is None
    assert anzeigen_id_aus_url(None) is None
    assert detail_url("md-3900000010") == "https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010"


# ---------- Trefferliste ----------
def test_suchseite_treffer_und_reihenfolge(such):
    treffer = parse_suchseite(such)
    # 8 Blöcke im Dokument: ein gesponserter Platz doppelt (gleiche Anzeige) → 7 Treffer; das Karussell „Ähnliche Fahrzeuge“ zählt nicht
    assert [t["id"] for t in treffer] == ["md-390000019", "md-3900000011", "md-3900000012", "md-3900000013", "md-3900000014",
                                           "md-3900000015", "md-3900000016"]
    assert len({t["id"] for t in treffer}) == len(treffer)
    for t in treffer:
        assert t["url"] == f"https://suchen.mobile.de/fahrzeuge/details.html?id={t['id'].removeprefix(ID_PRAEFIX)}"
        assert "searchId" not in t["url"] and "refId" not in t["url"] and t["titel"] and t["preis"] and t["ort"]


def test_suchseite_felder_je_treffer(such):
    t = nach_id(parse_suchseite(such))
    k = t["md-3900000011"]                                                    # privat, Kastenwagen, VB
    assert (k["titel"], k["preis"], k["vb"], k["ort"], k["km"], k["ez_jahr"], k["art"], k["gewerblich"]) == (
        "Beispiel-Camper Kastenwagen 2.0 TDI", 26400, True, "23456 Beispielstadt", 87350, 2015, "Kastenwagen", False)
    assert k["leistung"] == "96 kW (131 PS)" and k["details"] == {
        "laenge_mm": 5941, "zul_gesamtgewicht_kg": 3300, "kraftstoff": "Diesel", "kategorie": "Kastenwagen", "art_quelle": "kategorie"}
    a = t["md-3900000012"]                                                    # privat, „Wohnmobil andere“ → keine Art, ohne Länge/Gewicht
    assert (a["art"], a["preis"], a["km"], a["ez_jahr"], a["gewerblich"], a["details"]["kategorie"]) == (
        None, 27900, 141250, 2014, False, "Wohnmobil andere")
    assert t["md-3900000013"]["art"] == "Teilintegrierter" and t["md-3900000014"]["art"] == "Alkoven"
    assert t["md-3900000015"]["art"] == "Integrierter" and t["md-390000019"]["art"] == "Wohnwagen"
    assert t["md-3900000013"]["vb"] is False and t["md-3900000013"]["marke"] is None
    assert parse_suchseite(such.replace("Beispiel Wandermobil T 11", "Dethleffs Wandermobil T 11"))[3]["marke"] == "Dethleffs"


def test_privat_gewerblich_und_zusatzangaben(such):
    t = nach_id(parse_suchseite(such))
    assert {i: x["gewerblich"] for i, x in t.items()} == {
        "md-390000019": True,          # Händler (Name, Ort, Sterne) – gesponserter Platz „Top of Page“
        "md-3900000011": False, "md-3900000012": False,
        "md-3900000013": True,         # Händler
        "md-3900000014": True,         # „Gewerbe“ (Filter „Firmenfahrzeuge“)
        "md-3900000015": False,        # privat, gesponserter Platz „Top in Kategorie“
        "md-3900000016": True}
    assert t["md-3900000014"]["details"]["mwst_ausweisbar"] is True and t["md-3900000014"]["preis"] == 44250   # Fußnote ¹ nicht im Preis
    assert t["md-3900000015"]["details"]["gesponsert"] is True and "gesponsert" not in t["md-3900000011"]["details"]
    assert t["md-3900000016"]["details"]["zustand"] == "Neufahrzeug" and t["md-3900000016"]["ez_jahr"] is None
    assert t["md-3900000016"]["km"] is None and t["md-3900000016"]["art"] == "Kastenwagen"
    # kein Händlername, keine Bewertung, kein Logo in den Daten
    gespeichert = json.dumps(list(t.values()), ensure_ascii=False)
    for fremd in ("Mobilhaus GmbH", "Campinghof", "Freizeitfahrzeuge", "Sterne", "Logo"):
        assert fremd not in gespeichert


def test_auslandsort_bleibt_erhalten_ohne_deutsche_plz(such):
    assert nach_id(parse_suchseite(such))["md-3900000015"]["ort"] == "SE-123 45 Beispielstadt"


def test_suchseite_mit_privatfilter(privat):
    assert 'data-testid="Motorhome-seller_type-filter-FSBO-radio" type="radio" checked' in privat
    treffer = parse_suchseite(privat)
    assert [t["gewerblich"] for t in treffer] == [False, False, False]
    assert [t["art"] for t in treffer] == ["Kastenwagen", "Teilintegrierter", None]
    assert [t["marke"] for t in treffer] == [None, "Hobby", None]


def test_treffer_ohne_anzeigen_id_werden_gezaehlt_und_protokolliert(such, caplog):
    kaputt = such.replace("details.html?id=3900000012", "details.html?kein=3900000012")
    with caplog.at_level(logging.WARNING, logger="scout"):
        treffer = parse_suchseite(kaputt)
    assert "md-3900000012" not in {t["id"] for t in treffer} and len(treffer) == 6
    assert any("1 Treffer ohne Anzeigen-ID" in m and "Beispiel Bulli" in m for m in caplog.messages)


def test_unbekannter_anbietertyp_im_kasten_ist_gewerblich_kasten_fehlt_unbekannt(such):
    ohne_kasten = such.replace('data-testid="seller-info"', 'data-testid="x-info"')
    treffer = nach_id(parse_suchseite(ohne_kasten))
    # ohne Kasten: unbekannt (None); nur die Fußnote „MwSt. ausweisbar“ (price-vat-sup) ist ein Rückfallsignal für gewerblich
    assert {i: t["gewerblich"] for i, t in treffer.items()} == {
        "md-390000019": None, "md-3900000011": None, "md-3900000012": None, "md-3900000013": None, "md-3900000014": True,
        "md-3900000015": None, "md-3900000016": True}
    assert {t["ort"] for t in treffer.values()} == {None}


def test_unbekannte_kategorie_ergibt_keine_art(such):
    t = nach_id(parse_suchseite(such.replace("Teilintegrierter •", "Pickup-Camper •")))
    assert t["md-3900000013"]["art"] is None and t["md-3900000013"]["details"].get("kategorie") is None


# ---------- Anzeigenseite ----------
def test_anzeigenseite_felder(detail):
    art, [i] = erkenne_seite(detail)
    assert art == "detail" and (i.quelle, i.anzeigen_id) == ("mobile.de", DETAIL_ID)
    assert i.url == "https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010"         # ohne vip=1/utm-Parameter
    assert (i.titel, i.preis, i.vb, i.ort, i.km, i.ez_jahr) == ("Beispiel Kastenwagen Hochdach", 24800, True, "12345 Beispielstadt", 96300, 2013)
    assert (i.art, i.marke, i.leistung, i.getriebe, i.gewerblich) == ("Kastenwagen", "Fiat", "96 kW (131 PS)", "Automatik", False)
    assert i.beschreibung.startswith("Beispieltext: Kastenwagen") and "96.300 km" in i.beschreibung
    assert i.details["Kategorie"] == "Kastenwagen" and i.details["Schlafmöglichkeiten"] == "Hubbett"
    assert i.details["Ausstattung"] == "ABS, Fahrradträger, Solaranlage" and i.details["Anzahl Schlafplätze"] == "3"


def test_anzeigenseite_keine_personendaten(detail):
    _, [i] = erkenne_seite(detail)
    alles = json.dumps(i.als_datensatz(), ensure_ascii=False)
    for fremd in ("+49", "Tel", "Einblenden", "seller", "searchId", "Beispiel Karussell", "31.440", "0170", "Musterhandel", "Erfundene Stra", "0000000000"):
        assert fremd not in alles
    assert "verkaeufer_name" not in i.details                         # Privatanbieter haben auf mobile.de keinen Profilnamen


def test_anzeigenseite_kategorie_andere_ist_keine_art_und_aehnliche_zaehlen_nicht(detail):
    d = parse_detailseite(detail.replace("<dd class=\"_GxGsO\">Kastenwagen</dd>", "<dd class=\"_GxGsO\">Wohnmobil andere</dd>"))
    assert d["art"] is None and d["details"]["Kategorie"] == "Wohnmobil andere"


def test_anzeigenseite_json_ld_als_rueckfall(detail):
    ohne = (detail.replace('data-testid="vip-price-label"', 'data-testid="x"').replace('data-testid="vip-technical-data-box"', 'data-testid="x"')
            .replace('data-testid="vip-ad-title"', 'data-testid="x"'))
    d = parse_detailseite(ohne)
    assert (d["preis"], d["km"], d["titel"], d["marke"], d["art"]) == (24800, 96300, "Beispiel Kastenwagen Hochdach", "Fiat", "Kastenwagen")
    assert d["ez_jahr"] is None and list(d["details"]) == ["Ausstattung"]          # nur die Ausstattungsliste hängt nicht an den Technischen Daten


def test_anzeigenseite_gewerblich(detail):
    """Annahme (kein Original vorhanden): bei gewerblichen Anbietern steht in `seller-title-address` ein anderer Typ als „Privatanbieter“,
    und der Kasten `vip-fsbo-box` fehlt."""
    anfang, rest = detail.split('<article class="_nQzmW _GExzu" data-testid="vip-fsbo-box"')
    fsbo_ende = rest.index("</article>") + len("</article>")
    handler = (anfang + rest[fsbo_ende:]).replace('<div class="_XwWly _OyeyS">Privatanbieter</div>', '<div class="_XwWly _OyeyS">Gewerbe</div>')
    d = parse_detailseite(handler)
    assert d["gewerblich"] is True and d["ort"] == "12345 Beispielstadt"
    ohne_angabe = handler.replace('data-testid="seller-title-address"', 'data-testid="x"')
    assert parse_detailseite(ohne_angabe)["gewerblich"] is None and parse_detailseite(ohne_angabe)["ort"] is None


# ---------- Import ----------
def kopiere(ordner, *namen):
    for n in namen:
        shutil.copy(DATEN / n, ordner / n)


def test_import_suchseite_in_temp_db(cfg, db: Datenbank, ordner):
    kopiere(ordner, "suchseite.html")
    netz = KeinNetz()
    stat = Importer(cfg, db, abruf=netz).importiere_seiten(ordner)
    assert stat == {"dateien": 1, "suchseiten": 1, "detailseiten": 0, "unbekannt": 0, "fehlerhaft": 0, "neu": 7, "preis": 0,
                    "bekannt": 0, "details": 0, "fehler": [], "uebrig": 0}
    assert netz.abrufe == [] and not (ordner / "suchseite.html").exists()
    assert (ordner / "eingelesen" / date.today().isoformat() / "suchseite.html").is_file()
    z = zeile(db, "md-3900000011")
    assert (z["quelle"], z["preis"], z["vb"], z["ort"], z["km"], z["ez_jahr"], z["gewerblich"], z["detail_geladen"]) == (
        "mobile.de", 26400, 1, "23456 Beispielstadt", 87350, 2015, 0, 0)
    assert z["url"] == "https://suchen.mobile.de/fahrzeuge/details.html?id=3900000011"
    assert {r["id"]: r["gewerblich"] for r in db.con.execute("SELECT id, gewerblich FROM anzeigen")} == {
        "md-390000019": 1, "md-3900000011": 0, "md-3900000012": 0, "md-3900000013": 1, "md-3900000014": 1, "md-3900000015": 0, "md-3900000016": 1}
    assert db.ohne_details(10) == []                                  # nichts wird nachgeladen (ADR-010)


def test_art_herkunft_kategorie_des_treffers_ist_bestaetigt(cfg, db: Datenbank, ordner):
    kopiere(ordner, "suchseite.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    suche = {r["id"]: r["suche"] for r in db.con.execute("SELECT id, suche FROM anzeigen")}
    assert suche["md-3900000011"] == "Import Kastenwagen (bestätigt)"
    assert suche["md-3900000013"] == "Import Teilintegrierter (bestätigt)"
    assert suche["md-3900000014"] == "Import Alkoven (bestätigt)"
    assert suche["md-3900000015"] == "Import Integrierter (bestätigt)" and suche["md-390000019"] == "Import Wohnwagen (bestätigt)"
    # „Wohnmobil andere“ nennt keine Art; der Titel („Bulli“) auch nicht → unbekannt, mit Hinweis
    assert suche["md-3900000012"] == IMPORT_SUCHE


def test_kategorie_andere_mit_art_wort_im_titel_ist_nur_vorlaeufig(cfg, db: Datenbank, ordner, privat):
    (ordner / "p.html").write_text(privat.replace("Beispiel Wohnmobil Selbstausbau", "Beispiel Camper Selbstausbau"), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, "md-3900000023")["suche"] == "Import Kastenwagen (vorläufig)"           # Art aus dem Titel, nicht bestätigt
    assert zeile(db, "md-3900000021")["suche"] == "Import Kastenwagen (bestätigt)"


def test_import_anzeigenseite_ergaenzt_treffer_und_hat_vorrang(cfg, db: Datenbank, ordner, privat, detail):
    # derselbe Anzeigen-ID: Trefferliste sagt „Teilintegrierter“, die Anzeigenseite „Kastenwagen“ → die Anzeigenseite gewinnt, in jeder Reihenfolge
    liste = privat.replace("3900000021", "3900000010").replace("Kastenwagen •", "Teilintegrierter •", 1)
    assert nach_id(parse_suchseite(liste))["md-3900000010"]["art"] == "Teilintegrierter"
    for reihenfolge in (("liste.html", "anzeige.html"), ("anzeige.html", "liste.html")):
        db.con.execute("DELETE FROM anzeigen")
        for n in reihenfolge:
            (ordner / n).write_text(liste if n == "liste.html" else detail, encoding="utf-8")
            Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
        z = zeile(db, DETAIL_ID)
        assert z["suche"] == "Import Kastenwagen (bestätigt)" and z["detail_geladen"] == 1 and z["art"] == "Kastenwagen", reihenfolge
        assert (z["preis"], z["km"], z["ez_jahr"], z["marke"], z["leistung"], z["getriebe"]) == (
            24800, 96300, 2013, "Fiat", "96 kW (131 PS)", "Automatik")
        assert json.loads(z["details_json"])["Kategorie"] == "Kastenwagen"
        assert db.con.execute("SELECT COUNT(*) FROM anzeigen WHERE id=?", (DETAIL_ID,)).fetchone()[0] == 1


def test_import_anzeigenseite_privat_ueberschreibt_listenwert_nicht_mit_privat(cfg, db: Datenbank, ordner, such, detail):
    """Steht dieselbe Anzeige in der Liste als gewerblich, setzt die Anzeigenseite sie nicht auf „privat“ zurück (wie bei Kleinanzeigen)."""
    liste = such.replace("3900000014", "3900000010")
    (ordner / "liste.html").write_text(liste, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, DETAIL_ID)["gewerblich"] == 1
    (ordner / "anzeige.html").write_text(detail, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, DETAIL_ID)["gewerblich"] == 1


def test_erneuter_import_erzeugt_keine_dubletten_und_erkennt_preissenkung(cfg, db: Datenbank, ordner, privat):
    (ordner / "a.html").write_text(privat, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    (ordner / "b.html").write_text(privat.replace(f"24.800{chr(160)}€", f"22.700{chr(160)}€"), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["neu"], stat["bekannt"], stat["preis"]) == (0, 2, 1)
    z = zeile(db, "md-3900000021")
    assert (z["preis"], z["preis_vorher"]) == (22700, 24800) and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 3


def test_gemischter_ordner_kleinanzeigen_und_mobilede(cfg, db: Datenbank, ordner):
    shutil.copy(KA_DATEN / "suchseite.html", ordner / "ka_suche.html")
    shutil.copy(KA_DATEN / "detailseite.html", ordner / "ka_detail.html")
    kopiere(ordner, "suchseite.html", "suchseite_privat.html", "detailseite.html")
    (ordner / "wetter.html").write_text("<html><body>Wetter</body></html>", encoding="utf-8")
    netz = KeinNetz()
    stat = Importer(cfg, db, abruf=netz).importiere_seiten(ordner)
    assert netz.abrufe == []
    assert (stat["dateien"], stat["suchseiten"], stat["detailseiten"], stat["unbekannt"], stat["fehlerhaft"]) == (6, 3, 2, 1, 0)
    assert len(stat["fehler"]) == 1 and "Kleinanzeigen- oder mobile.de-Such- oder Detailseite" in stat["fehler"][0]
    quellen = {r["quelle"]: r["n"] for r in db.con.execute("SELECT quelle, COUNT(*) n FROM anzeigen GROUP BY quelle")}
    assert quellen == {"kleinanzeigen": 7, "mobile.de": 7 + 3 + 1}
    # Kleinanzeigen-Ablauf unverändert: Art aus dem Suchwort der Seite bleibt vorläufig, die Anzeigenseite bestätigt
    ka = zeile(db, KA_DETAIL_ID)
    assert ka["quelle"] == "kleinanzeigen" and ka["suche"] == "Import Kastenwagen (bestätigt)"
    # dieselbe Roh-Nummer 3900000010 auf beiden Plattformen: zwei getrennte Datensätze, kein Überschreiben
    assert KA_DETAIL_ID == "3900000010" and zeile(db, DETAIL_ID)["quelle"] == "mobile.de" and zeile(db, DETAIL_ID)["id"] != KA_DETAIL_ID
    assert (ordner / "nicht_erkannt" / "wetter.html").is_file()


def test_import_speichert_keine_personendaten(cfg, db: Datenbank, ordner):
    kopiere(ordner, "suchseite.html", "suchseite_privat.html", "detailseite.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    inhalt = json.dumps([dict(r) for r in db.con.execute("SELECT * FROM anzeigen")], ensure_ascii=False)
    for fremd in ("+49", "Tel.", "Einblenden", "searchId", "refId", "utm_", "Mobilhaus GmbH", "Campinghof", "Freizeitfahrzeuge", "verkaeufer_name",
                  "Beispiel Karussell", "0170", "Musterhandel", "Erfundene Stra"):
        assert fremd not in inhalt, fremd


def test_bewertung_ohne_quellenlogik_gewerbliche_gesperrt_private_bewertet(cfg, db: Datenbank, ordner):
    kopiere(ordner, "suchseite.html", "suchseite_privat.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, Path(__file__).resolve().parent.parent)}
    assert len(zeilen) == 7 + 3
    for ad_id in ("md-390000019", "md-3900000013", "md-3900000014", "md-3900000016"):
        assert zeilen[ad_id]["sperre"] == "gewerblicher Anbieter" and not zeilen[ad_id]["bereit"]
    privat = zeilen["md-3900000021"]
    art_hinweise = [h for h in privat["hinweise"] if not h.startswith("Marke unbekannt")]                    # Marke: P5-03, eigene Tests
    assert privat["sperre"] is None and art_hinweise == [] and privat["b"].art == "Kastenwagen"            # bestätigte Art: kein Hinweis
    unbekannt = zeilen["md-3900000012"]
    assert unbekannt["sperre"] is None and unbekannt["hinweise"] and unbekannt["hinweise"][0].startswith(HINWEIS_ART_UNBEKANNT_ANFANG)
    assert HINWEIS_ART_VORLAEUFIG not in unbekannt["hinweise"]


def test_bewertung_gewerbliche_hinweislogik_unveraendert_fuer_sponsoren(cfg, db: Datenbank, ordner):
    """Auch ein gesponserter Platz ist ein normaler Datensatz: privat → bewertbar, gewerblich → gesperrt."""
    kopiere(ordner, "suchseite.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, Path(__file__).resolve().parent.parent)}
    assert zeilen["md-3900000015"]["sperre"] == "Preis außerhalb Filter"        # 135.000 € – privat, aber über der Preisgrenze
    assert zeilen["md-390000019"]["sperre"] == "gewerblicher Anbieter"


def test_datei_nur_mit_mobilede_text_im_body_ist_nicht_erkannt(cfg, db: Datenbank, ordner):
    (ordner / "x.html").write_text('<html><head><title>Notiz</title></head><body><a href="https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010">'
                                   "Link</a></body></html>", encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["unbekannt"], stat["neu"]) == (1, 0) and (ordner / "nicht_erkannt" / "x.html").is_file()


def test_suchwort_im_seitentitel_ist_bei_mobilede_kein_art_hinweis(cfg, db: Datenbank, ordner, such):
    """Der Titel-Hinweis („…Alkoven…“) gehört zur Kleinanzeigen-Logik; bei mobile.de zählt nur die Kategorie des Treffers."""
    (ordner / "s.html").write_text(such.replace("Wohnmobil-Suche bei mobile.de", "Alkoven-Suche bei mobile.de", 1), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, "md-3900000012")["suche"] == IMPORT_SUCHE                       # „Wohnmobil andere“ bleibt unbekannt
    assert zeile(db, "md-3900000011")["suche"] == "Import Kastenwagen (bestätigt)"


# ---------- H1: Anzeigen-IDs mit Bindestrich („md-…“) in der Handy-App / HTTP-Schnittstelle ----------
@pytest.fixture
def md_server(server, cfg, db: Datenbank, ordner, privat, such):  # noqa: F811 – server: Fixture aus test_handy
    for name, html in (("privat.html", privat), ("such.html", such)):
        (ordner / name).write_text(html, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    return server


def test_handy_api_mit_bindestrich_id(md_server, team, db: Datenbank):  # noqa: F811
    port = md_server.server_address[1]
    anna = Client(port, OEFFENTLICH).anmelden("Anna")
    ad_id = "md-3900000021"
    status, fz, _ = anna("GET", f"/api/fahrzeug/{ad_id}")
    assert status == 200 and fz["id"] == ad_id and fz["quelle"] == "mobile.de" and fz["bewertung"] and fz["brief"]
    assert ad_id in {f["id"] for f in anna("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert anna("GET", "/api/fahrzeug/md-9999999999")[2].status == 404 and "aktiv" in anna("GET", "/api/fahrzeug/md-9999999999")[1]["fehler"]
    assert "nicht gefunden" in anna("GET", "/api/fahrzeug/md-1/../x")[1]["fehler"]            # kein Pfad-Trick durch den Bindestrich

    assert anna("POST", "/api/notiz", {"id": ad_id, "notiz": "Anruf folgt"})[0] == 200
    assert anna("GET", f"/api/fahrzeug/{ad_id}")[1]["notiz"] == "Anruf folgt"
    assert anna("POST", "/api/status", {"id": ad_id, "status": "kontaktiert", "text": fz["brief"]})[0] == 200
    assert anna("GET", f"/api/fahrzeug/{ad_id}")[1]["status"] == "kontaktiert"

    status, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": ad_id, "termin": "2026-10-20T10:30", "adresse": "Beispielweg 1, 12345 Beispielstadt"})
    assert status == 200 and b["fahrzeug"]
    voll = anna("GET", f"/api/besichtigung/{b['id']}")[1]
    assert voll["anzeige_id"] == ad_id and anna("GET", f"/api/fahrzeug/{ad_id}")[1]["besichtigungen"][0]["id"] == b["id"]
    assert db.con.execute("SELECT anzeige_id FROM besichtigungen").fetchone()["anzeige_id"] == ad_id
    status, html, _ = anna("GET", "/")
    assert status == 200 and f'data-id="{ad_id}"' in html and 'data-quelle="mobile.de"' in html           # Desktop-Report


def test_handy_api_zeigt_ausland_hinweis(md_server, team):  # noqa: F811
    anna = Client(md_server.server_address[1], OEFFENTLICH).anmelden("Anna")
    fz = anna("GET", "/api/fahrzeug/md-3900000015")[1]                      # „SE-123 45 Beispielstadt“
    assert fz["entfernung_km"] is None and fz["hinweise"][0].startswith(HINWEIS_AUSLAND) and fz["ort"] == "SE-123 45 Beispielstadt"


def test_fahrzeug_route_erlaubt_bindestrich():
    api = (Path(__file__).resolve().parent.parent / "wmscout" / "web" / "api.py").read_text(encoding="utf-8")
    assert r'"/api/fahrzeug/([\w-]+)"' in api


# ---------- M1: nur Wohnmobile und Wohnwagen ----------
def als_pkw_suche(such: str) -> str:
    s = such.replace("vc=Motorhome", "vc=Car").replace("Motorhome-seller_type", "Car-seller_type")
    for kat in ("Kastenwagen", "Teilintegrierter", "Alkoven", "Integrierter", "Wohnwagen", "Wohnmobil andere"):
        s = s.replace(f"{kat} •", "Limousine •")
    return s


def test_pkw_suchseite_ist_nicht_erkannt_mit_meldung(cfg, db: Datenbank, ordner, such):
    pkw = als_pkw_suche(such)
    assert parse_suchseite(pkw) == []
    art, inserate, hinweise_ = erkenne_seite_mit_hinweisen(pkw)
    assert (art, inserate) == ("unbekannt", []) and erkenne_seite(pkw) == ("unbekannt", [])
    assert "keine Wohnmobil-/Wohnwagen-Suche" in hinweise_[0] and "Limousine" in hinweise_[0]
    (ordner / "pkw.html").write_text(pkw, encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["unbekannt"], stat["suchseiten"], stat["neu"]) == (1, 0, 0) and (ordner / "nicht_erkannt" / "pkw.html").is_file()
    assert len(stat["fehler"]) == 1 and "Limousine" in stat["fehler"][0] and "nicht_erkannt" in stat["fehler"][0]
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0


@pytest.mark.parametrize("aenderung", [
    lambda s: s.replace("vc=Motorhome", "vc=Car"),                                              # Klasse im Link
    lambda s: s.replace("vc=Motorhome", "vc=Car").replace("Motorhome-seller_type", "Car-seller_type"),
    lambda s: s.replace("vc=Motorhome", "").replace("Motorhome-seller_type", "Car-seller_type"),   # nur der Filter der Seite nennt die Klasse
    lambda s: s.replace("Kastenwagen •", "Limousine •").replace("Teilintegrierter •", "Kombi •").replace("Alkoven •", "Limousine •")
               .replace("Integrierter •", "Kleinwagen •").replace("Wohnwagen •", "Limousine •").replace("Wohnmobil andere •", "Limousine •"),
    lambda s: s.replace("&amp;vc=Motorhome", "").replace("Motorhome-seller_type", "x").replace("Kastenwagen •", "Pickup-Camper •")
               .replace("Teilintegrierter •", "Pickup-Camper •").replace("Alkoven •", "Pickup-Camper •").replace("Integrierter •", "Pickup-Camper •")
               .replace("Wohnwagen •", "Pickup-Camper •").replace("Wohnmobil andere •", "Pickup-Camper •"),   # ohne Klasse: unbekannte Kategorie
])
def test_fremde_klasse_oder_kategorie_wird_nicht_uebernommen(such, aenderung):
    treffer, hinweise_ = parse_suchseite_mit_hinweisen(aenderung(such))
    assert treffer == [] and any("ohne Wohnmobil-Kategorie" in h for h in hinweise_)


def test_ohne_klassenangabe_zaehlt_die_bekannte_kategorie(such):
    ohne = such.replace("&amp;vc=Motorhome", "").replace("Motorhome-seller_type", "x")
    assert "vc=" not in ohne and len(parse_suchseite(ohne)) == 7                                 # alle Kategorien der Liste, auch „Wohnmobil andere“


def test_gemischte_seite_uebernimmt_nur_wohnmobile_und_meldet_den_rest(cfg, db: Datenbank, ordner, such):
    gemischt = such.replace("id=3900000014&amp;vc=Motorhome", "id=3900000014&amp;vc=Car").replace("Alkoven •", "Limousine •")
    treffer, hinweise_ = parse_suchseite_mit_hinweisen(gemischt)
    assert len(treffer) == 6 and "md-3900000014" not in {t["id"] for t in treffer}
    assert len(hinweise_) == 1 and "1 Treffer ohne Wohnmobil-Kategorie" in hinweise_[0] and "Limousine" in hinweise_[0]
    (ordner / "g.html").write_text(gemischt, encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["suchseiten"], stat["neu"], stat["unbekannt"]) == (1, 6, 0)
    assert len(stat["fehler"]) == 1 and "g.html" in stat["fehler"][0] and "Limousine" in stat["fehler"][0]
    assert zeile(db, "md-3900000014") is None


def pkw_detail(detail: str) -> str:
    return detail.replace('<dd class="_GxGsO">Kastenwagen</dd>', '<dd class="_GxGsO">Limousine</dd>').replace('"bodyType":"VanMotorhome"', '"bodyType":"Sedan"')


def test_pkw_anzeigenseite_ist_nicht_erkannt(cfg, db: Datenbank, ordner, detail):
    pkw = pkw_detail(detail)
    d = parse_detailseite(pkw)
    assert d["wohnmobil"] is False and d["klasse_text"] == "Limousine"
    art, inserate, hinweise_ = erkenne_seite_mit_hinweisen(pkw)
    assert (art, inserate) == ("unbekannt", []) and "kein Wohnmobil/Wohnwagen" in hinweise_[0] and "Limousine" in hinweise_[0]
    (ordner / "pkw.html").write_text(pkw, encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["unbekannt"], stat["detailseiten"], stat["neu"]) == (1, 0, 0) and (ordner / "nicht_erkannt" / "pkw.html").is_file()
    assert "Limousine" in stat["fehler"][0] and zeile(db, DETAIL_ID) is None


@pytest.mark.parametrize("html_aenderung, erwartet", [
    (lambda d: d, True),                                                                                  # Original: Kastenwagen
    (lambda d: d.replace('<dd class="_GxGsO">Kastenwagen</dd>', '<dd class="_GxGsO">Wohnmobil andere</dd>'), True),
    (lambda d: d.replace('<dd class="_GxGsO">Kastenwagen</dd>', '<dd class="_GxGsO">Pickup-Camper</dd>'), True),   # neue Kategorie + Wohnmobil-bodyType
    (lambda d: d.replace('<dd class="_GxGsO">Kastenwagen</dd>', '<dd class="_GxGsO">Pickup-Camper</dd>').replace("VanMotorhome", "Sedan"), False),
    (lambda d: d.replace('<dd class="_GxGsO">Kastenwagen</dd>', '<dd class="_GxGsO">Limousine</dd>'), False),    # Widerspruch: Kategorie fremd
    (lambda d: d.replace('data-testid="category-item"', 'data-testid="x"').replace("Kategorie", "Merkmal"), True),   # ohne Kategorie: bodyType
    (lambda d: d.replace('data-testid="category-item"', 'data-testid="x"').replace("Kategorie", "Merkmal").replace("VanMotorhome", "Sedan"), False),
    (lambda d: d.replace('data-testid="category-item"', 'data-testid="x"').replace("Kategorie", "Merkmal").replace(',"bodyType":"VanMotorhome"', ""), False),
])
def test_anzeigenseite_klasse(detail, html_aenderung, erwartet):
    assert parse_detailseite(html_aenderung(detail))["wohnmobil"] is erwartet
    art, inserate, hinweise_ = erkenne_seite_mit_hinweisen(html_aenderung(detail))
    assert (art == "detail") is erwartet and bool(inserate) is erwartet and bool(hinweise_) is (not erwartet)


def test_anzeigenseite_ohne_klasse_meldet_nicht_erkennbar(detail):
    ohne = detail.replace('data-testid="category-item"', 'data-testid="x"').replace("Kategorie", "Merkmal").replace(',"bodyType":"VanMotorhome"', "")
    assert "nicht erkennbar" in erkenne_seite_mit_hinweisen(ohne)[2][0]


# ---------- M2: unbekannter Anbieter ----------
def ohne_anbieterkasten(such: str, nur: str | None = None) -> str:
    if nur is None:
        return such.replace('data-testid="seller-info"', 'data-testid="x-info"')
    kopf, rest = such.split(f"id={nur}&amp;", 1)
    return kopf + f"id={nur}&amp;" + rest.replace('data-testid="seller-info"', 'data-testid="x-info"', 1)


def test_fehlende_anbieterkaesten_werden_gezaehlt_ab_haelfte_layout_warnung(such, caplog):
    with caplog.at_level(logging.WARNING, logger="scout"):
        treffer, hinweise_ = parse_suchseite_mit_hinweisen(ohne_anbieterkasten(such))
    assert len(treffer) == 7 and len(hinweise_) == 1 and "7 von 7" in hinweise_[0] and "Seitenlayout" in hinweise_[0]
    assert any("Seitenlayout" in m for m in caplog.messages)
    treffer, hinweise_ = parse_suchseite_mit_hinweisen(ohne_anbieterkasten(such, "3900000011"))
    assert len(hinweise_) == 1 and "1 von 7" in hinweise_[0] and "Seitenlayout" not in hinweise_[0] and "unbekannt" in hinweise_[0]
    assert parse_suchseite_mit_hinweisen(such)[1] == []


def test_unbekannter_anbieter_wird_als_unbekannt_gespeichert_nicht_als_privat(cfg, db: Datenbank, ordner, such):
    (ordner / "s.html").write_text(ohne_anbieterkasten(such, "3900000011"), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["neu"] == 7 and len(stat["fehler"]) == 1 and "s.html" in stat["fehler"][0] and "1 von 7" in stat["fehler"][0]
    assert zeile(db, "md-3900000011")["gewerblich"] is None                       # unbekannt, nicht 0 (privat)
    assert zeile(db, "md-3900000012")["gewerblich"] == 0 and zeile(db, "md-3900000013")["gewerblich"] == 1
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, Path(__file__).resolve().parent.parent)}
    z = zeilen["md-3900000011"]
    assert HINWEIS_ANBIETER_UNBEKANNT in z["hinweise"] and z["sperre"] is None            # sichtbarer Hinweis, aber nicht gesperrt
    assert HINWEIS_ANBIETER_UNBEKANNT not in zeilen["md-3900000012"]["hinweise"]            # bekannter privater Anbieter: kein Hinweis
    assert HINWEIS_ANBIETER_UNBEKANNT not in hinweise({**z["a"], "gewerblich": 0})


def test_ueber_haelfte_ohne_anbieterkasten_meldet_layout_und_kein_treffer_gilt_als_privat(cfg, db: Datenbank, ordner, such):
    (ordner / "s.html").write_text(ohne_anbieterkasten(such), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert len(stat["fehler"]) == 1 and "7 von 7" in stat["fehler"][0] and "Seitenlayout" in stat["fehler"][0]
    zeilen = {r["id"]: r["gewerblich"] for r in db.con.execute("SELECT id, gewerblich FROM anzeigen")}
    # Rückfallsignal „MwSt. ausweisbar“ (price-vat-sup) → gewerblich; alle übrigen unbekannt (NULL), keiner „privat“ (0)
    assert zeilen["md-3900000014"] == 1 and zeilen["md-3900000016"] == 1
    assert [i for i, g in zeilen.items() if g == 0] == [] and sum(g is None for g in zeilen.values()) == 5


def test_unbekannt_wird_spaeter_durch_bekannten_wert_ersetzt_gewerblich_nie_zurueckgesetzt(cfg, db: Datenbank, ordner, such, detail):
    (ordner / "a.html").write_text(ohne_anbieterkasten(such), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, "md-3900000011")["gewerblich"] is None
    (ordner / "b.html").write_text(such, encoding="utf-8")                                    # dieselbe Suche, jetzt mit Anbieterkasten
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, "md-3900000011")["gewerblich"] == 0 and zeile(db, "md-3900000013")["gewerblich"] == 1
    (ordner / "c.html").write_text(ohne_anbieterkasten(such), encoding="utf-8")                # später wieder ohne Kasten: überschreibt nichts
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, "md-3900000011")["gewerblich"] == 0 and zeile(db, "md-3900000013")["gewerblich"] == 1


def test_anzeigenseite_gewerblich_unbekannt_neu_null_bekannt_privat_null(cfg, db: Datenbank, ordner, detail):
    ohne_angabe = (detail.replace('data-testid="seller-title-address"', 'data-testid="x"').replace('data-testid="vip-fsbo-box"', 'data-testid="y"')
                   .replace("Privatanbieter", "Angebot"))
    assert parse_detailseite(ohne_angabe)["gewerblich"] is None
    (ordner / "u.html").write_text(ohne_angabe, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, DETAIL_ID)["gewerblich"] is None                                         # Detailseite ohne Angabe: unbekannt
    (ordner / "p.html").write_text(detail, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, DETAIL_ID)["gewerblich"] == 0                                            # ausdrücklich „Privatanbieter“: privat
    db.con.execute("DELETE FROM anzeigen")
    (ordner / "p2.html").write_text(detail, encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, DETAIL_ID)["gewerblich"] == 0                                            # neue Anzeige nur aus der Detailseite: privat


def test_mwst_signal_ist_nur_rueckfall_der_anbieterkasten_gewinnt(such):
    treffer = nach_id(parse_suchseite(such))
    assert treffer["md-3900000014"]["gewerblich"] is True
    html = such.replace(f">26.400{N}€</span>", f'>26.400{N}€</span><sup data-testid="price-vat-sup">¹</sup>')
    privat_mit_fussnote = nach_id(parse_suchseite(html))["md-3900000011"]
    assert privat_mit_fussnote["details"]["mwst_ausweisbar"] is True and privat_mit_fussnote["gewerblich"] is False      # Kasten „Privatanbieter“ gilt


# ---------- N2 / Ort ----------
@pytest.mark.parametrize("text, erwartet", [
    ("12345 Beispielstadt", "12345 Beispielstadt"), ("DE-12345 Beispielstadt", "12345 Beispielstadt"),
    ("SE-123 45 Beispielstadt", "SE-123 45 Beispielstadt"), ("NL-1234AB Beispieldorf", "NL-1234AB Beispieldorf"),
    ("FR-75001 Paris", "FR-75001 Paris"),
    ("4x4 Allrad", None), ("TEMPOMAT/1.HAND", None), ("12345", None), ("", None), (None, None), ("Beispielstadt", None),
    ("1.HAND", None), ("2 Betten", None),
])
def test_ort_streng(text, erwartet):
    assert _ort(text) == erwartet


def test_ort_wird_nicht_aus_haendler_stichworten_gelesen(such):
    html = such.replace("ABS/MARKISE", "4x4 Allrad").replace("SOLAR/2.HAND", "2000 Euro Rabatt")
    t = nach_id(parse_suchseite(html))
    assert t["md-3900000013"]["ort"] == "45678 Beispielstadt" and t["md-3900000013"]["gewerblich"] is True
    # steht ein Stichwort statt des Ortes im Anbieterkasten, ist der Ort unbekannt – nicht das Stichwort
    kaputt = such.replace('<span class="_AZddu">45678 Beispielstadt</span>', '<span class="_AZddu">4x4 Allrad</span>')
    assert nach_id(parse_suchseite(kaputt))["md-3900000013"]["ort"] is None


# ---------- N3: Art nur mit ausdrücklichem Kennzeichen bestätigt ----------
def speichere(cfg, db, inserat: Inserat) -> str:
    stat = {"suchseiten": 0, "detailseiten": 0, "neu": 0, "preis": 0, "bekannt": 0, "details": 0}
    Importer(cfg, db)._speichere_seite("suche", [inserat], stat)
    return db.suche_zu(inserat.anzeigen_id)


def test_art_ohne_kennzeichen_ist_nicht_bestaetigt(cfg, db: Datenbank):
    ohne = Inserat(quelle="neu", anzeigen_id="n1", url="u", titel="Beispiel Wohnmobil", art="Alkoven")           # Art vorhanden, aber ohne Kennzeichen
    assert speichere(cfg, db, ohne) == IMPORT_SUCHE and import_art(db.suche_zu("n1"))[1] != BESTAETIGT
    mit = Inserat(quelle="neu", anzeigen_id="n2", url="u", titel="Beispiel Wohnmobil", art="Alkoven", details={"art_quelle": "kategorie"})
    assert speichere(cfg, db, mit) == "Import Alkoven (bestätigt)"
    falsch = Inserat(quelle="neu", anzeigen_id="n3", url="u", titel="Beispiel Wohnmobil", art="Alkoven", details={"art_quelle": "titel"})
    assert import_art(speichere(cfg, db, falsch))[1] != BESTAETIGT
    ohne_art = Inserat(quelle="neu", anzeigen_id="n4", url="u", titel="Beispiel Wohnmobil", details={"art_quelle": "kategorie"})
    assert speichere(cfg, db, ohne_art) == IMPORT_SUCHE


def test_parser_setzt_kennzeichen_nur_mit_art(such):
    t = nach_id(parse_suchseite(such))
    assert t["md-3900000011"]["details"]["art_quelle"] == "kategorie" and t["md-3900000013"]["details"]["art_quelle"] == "kategorie"
    assert "art_quelle" not in t["md-3900000012"]["details"] and t["md-3900000012"]["art"] is None            # „Wohnmobil andere“


# ---------- N6 ----------
def test_detail_ohne_id_meldung_je_plattform(cfg, db: Datenbank, ordner, detail):
    ohne = detail.replace('<link rel="canonical"', '<link rel="x-canonical"').replace('<meta property="og:url"', '<meta property="x-og:url"')
    (ordner / "md.html").write_text(ohne, encoding="utf-8")
    (ordner / "ka.html").write_text('<html><head><title>x</title></head><body><h1 id="viewad-title">Beispiel</h1></body></html>', encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    meldungen = {m.split(":")[0]: m for m in stat["fehler"]}
    assert "„Webseite, komplett“" in meldungen["md.html"] and "nur HTML" not in meldungen["md.html"].split("komplett")[0]
    assert "„Webseite, nur HTML“" in meldungen["ka.html"] and "komplett" not in meldungen["ka.html"]


# ---------- Bild, erster Preis, erste Kategorie ----------
BILD_TAG = '<img alt="" class="_hGVTo" data-nimg="fill" data-testid="base-result-listing-1-image-large" decoding="async" loading="lazy"/>'


def test_bild_nur_http_adressen(such):
    assert BILD_TAG in such and nach_id(parse_suchseite(such))["md-3900000011"]["bild"] is None
    for bild in ("seite_files/a.jpg", "./seite_files/a.jpg", "file:///tmp/a.jpg", "data:image/gif;base64,AAAA", "httpbild/a.jpg", "http:a.jpg", ""):
        html = such.replace(BILD_TAG, BILD_TAG.replace("<img ", f'<img src="{bild}" '))
        assert nach_id(parse_suchseite(html))["md-3900000011"]["bild"] is None, bild
    for bild in ("https://img.beispiel.example/a.jpg", "http://img.beispiel.example/a.jpg"):
        html = such.replace(BILD_TAG, BILD_TAG.replace("<img ", f'<img src="{bild}" '))
        assert nach_id(parse_suchseite(html))["md-3900000011"]["bild"] == bild
    attribute = 'src="seite_files/a.jpg" srcset="seite_files/a.jpg 1x, https://img.beispiel.example/b.jpg 2x" '
    srcset = such.replace(BILD_TAG, BILD_TAG.replace("<img ", f"<img {attribute}"))
    assert nach_id(parse_suchseite(srcset))["md-3900000011"]["bild"] == "https://img.beispiel.example/b.jpg"


def test_erster_preis_zaehlt(such):
    assert _preis(f"26.400{N}€ 31.000{N}€") == 26400 and _preis(f"39.900{N}€ ¹") == 39900 and _preis("auf Anfrage") is None
    html = such.replace(f">26.400{N}€</span>", f">26.400{N}€ <s>31.000{N}€</s></span>")
    assert html != such and nach_id(parse_suchseite(html))["md-3900000011"]["preis"] == 26400
    detail_zwei = f"<div data-testid=\"vip-price-label\">12.000{N}€ 15.000{N}€</div>"
    assert parse_detailseite(f"<html><body>{detail_zwei}</body></html>")["preis"] == 12000


def test_erste_kategorie_zaehlt(such):
    html = such.replace("Kastenwagen • 5.941", "Kastenwagen • Wohnwagen • 5.941")
    k = nach_id(parse_suchseite(html))["md-3900000011"]
    assert k["art"] == "Kastenwagen" and k["details"]["kategorie"] == "Kastenwagen"
    umgekehrt = such.replace("Kastenwagen • 5.941", "Wohnwagen • Kastenwagen • 5.941")
    assert nach_id(parse_suchseite(umgekehrt))["md-3900000011"]["art"] == "Wohnwagen"


# ---------- Datenschutz auf Report-, CSV-, API- und Datenbankebene ----------
FREMDE_DATEN = ("0170 0000000", "01700000000", "0170", "+491700000000", "Musterhandel", "Erfundene Stra", "0000000000", "sellerId",
                "Campinghof", "Mobilhaus", "Freizeitfahrzeuge", "Sterne", "seller_info")


def test_datenschutz_keine_telefonnummer_keine_anbieternamen_in_ausgaben(cfg, db: Datenbank, ordner, caplog):
    assert "0170 0000000" in (DATEN / "detailseite.html").read_text(encoding="utf-8")           # die erfundenen Daten sind wirklich in der Seite
    kopiere(ordner, "suchseite.html", "suchseite_privat.html", "detailseite.html")
    basis = Path(__file__).resolve().parent.parent
    with caplog.at_level(logging.DEBUG, logger="scout"):
        stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = bewerte_alle(cfg, db, basis)
    erg = schreibe_ausgaben(cfg, zeilen, basis)
    ausgabe = Path(erg["html"]).parent
    api = json.dumps([{**fahrzeug_kurz(z), "bewertung": z["b"].dict(), "brief": z["brief"], "nachfass_text": z["nachfass_text"],
                       "a": {k: v for k, v in z["a"].items()}} for z in zeilen], ensure_ascii=False, default=str)
    texte = {"datenbank": "\n".join(db.con.iterdump()), "api": api, "log": "\n".join(caplog.messages), "stat": json.dumps(stat, ensure_ascii=False)}
    for datei in ausgabe.rglob("*"):                                    # Report (HTML), CSV, Anschreiben-Textdateien
        if datei.is_file():
            texte[f"ausgabe/{datei.name}"] = datei.read_text(encoding="utf-8-sig", errors="replace")
    assert {"ausgabe/anzeigen_bewertet.csv"} <= set(texte) and any(n.endswith(".html") for n in texte)
    for name, text in texte.items():
        for fremd in FREMDE_DATEN:
            assert fremd not in text, (name, fremd)
