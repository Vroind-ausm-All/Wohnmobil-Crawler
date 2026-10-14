"""mobile.de: im Browser gespeicherte Such- und Anzeigenseiten (P2-05b, ADR-010) – erkennen, parsen, importieren, ohne Netzabruf.

Die Testseiten unter tests/seiten/mobilede/ sind aus echten, vom Betreiber am 14.10.2026 gespeicherten Seiten nachgebaut
(Wohnmobil-Suche „alle“, „Privatanbieter“, „Firmenfahrzeuge“ und drei Anzeigenseiten): Aufbau, `data-testid`-Attribute und
Klassennamen entsprechen dem Original, Inhalte (IDs, Orte, Titel, Texte, Zahlen) sind erfunden, Skripte und Tracking entfernt.

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

from tests.test_kleinanzeigen_echt import DETAIL_ID as KA_DETAIL_ID
from tests.test_seitenimport import KeinNetz
from wmscout.bewertung.anschreiben import HINWEIS_ART_UNBEKANNT_ANFANG, HINWEIS_ART_VORLAEUFIG
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenbank import IMPORT_SUCHE, Datenbank
from wmscout.eingang import erkenne_seite, ist_mobilede_seite, plattform_der_seite
from wmscout.importer import Importer
from wmscout.quellen.mobilede import ID_PRAEFIX, KENNUNG, anzeigen_id_aus_url, detail_url, parse_detailseite, parse_suchseite

DATEN = Path(__file__).resolve().parent / "seiten" / "mobilede"
KA_DATEN = Path(__file__).resolve().parent / "seiten" / "kleinanzeigen"
DETAIL_ID = "md-3900000010"


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
        "Beispiel-Camper Kastenwagen 2.0 TDI", 28000, True, "23456 Beispielstadt", 102000, 2016, "Kastenwagen", False)
    assert k["leistung"] == "80 kW (109 PS)" and k["details"] == {
        "laenge_mm": 5292, "zul_gesamtgewicht_kg": 3000, "kraftstoff": "Diesel", "kategorie": "Kastenwagen"}
    a = t["md-3900000012"]                                                    # privat, „Wohnmobil andere“ → keine Art, ohne Länge/Gewicht
    assert (a["art"], a["preis"], a["km"], a["ez_jahr"], a["gewerblich"], a["details"]["kategorie"]) == (
        None, 29500, 122000, 2015, False, "Wohnmobil andere")
    assert t["md-3900000013"]["art"] == "Teilintegrierter" and t["md-3900000014"]["art"] == "Alkoven"
    assert t["md-3900000015"]["art"] == "Integrierter" and t["md-390000019"]["art"] == "Wohnwagen"
    assert t["md-3900000013"]["vb"] is False and t["md-3900000013"]["marke"] is None
    assert parse_suchseite(such.replace("Beispiel Globetrotter T 11", "Dethleffs Globetrotter T 11"))[3]["marke"] == "Dethleffs"


def test_privat_gewerblich_und_zusatzangaben(such):
    t = nach_id(parse_suchseite(such))
    assert {i: x["gewerblich"] for i, x in t.items()} == {
        "md-390000019": True,          # Händler (Name, Ort, Sterne) – gesponserter Platz „Top of Page“
        "md-3900000011": False, "md-3900000012": False,
        "md-3900000013": True,         # Händler
        "md-3900000014": True,         # „Gewerbe“ (Filter „Firmenfahrzeuge“)
        "md-3900000015": False,        # privat, gesponserter Platz „Top in Kategorie“
        "md-3900000016": True}
    assert t["md-3900000014"]["details"]["mwst_ausweisbar"] is True and t["md-3900000014"]["preis"] == 39900   # Fußnote ¹ nicht im Preis
    assert t["md-3900000015"]["details"]["gesponsert"] is True and "gesponsert" not in t["md-3900000011"]["details"]
    assert t["md-3900000016"]["details"]["zustand"] == "Neufahrzeug" and t["md-3900000016"]["ez_jahr"] is None
    assert t["md-3900000016"]["km"] is None and t["md-3900000016"]["art"] == "Kastenwagen"
    # kein Händlername, keine Bewertung, kein Logo in den Daten
    gespeichert = json.dumps(list(t.values()), ensure_ascii=False)
    for fremd in ("Reisemobile GmbH", "Wohnwagenhandel", "Caravaning", "Sterne", "Logo"):
        assert fremd not in gespeichert


def test_auslandsort_bleibt_erhalten_ohne_deutsche_plz(such):
    assert nach_id(parse_suchseite(such))["md-3900000015"]["ort"] == "SE-437 41 Beispielstadt"


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
    assert {t["gewerblich"] for t in parse_suchseite(ohne_kasten)} == {None}
    assert {t["ort"] for t in parse_suchseite(ohne_kasten)} == {None}


def test_unbekannte_kategorie_ergibt_keine_art(such):
    t = nach_id(parse_suchseite(such.replace("Teilintegrierter •", "Pickup-Camper •")))
    assert t["md-3900000013"]["art"] is None and t["md-3900000013"]["details"].get("kategorie") is None


# ---------- Anzeigenseite ----------
def test_anzeigenseite_felder(detail):
    art, [i] = erkenne_seite(detail)
    assert art == "detail" and (i.quelle, i.anzeigen_id) == ("mobile.de", DETAIL_ID)
    assert i.url == "https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010"         # ohne vip=1/utm-Parameter
    assert (i.titel, i.preis, i.vb, i.ort, i.km, i.ez_jahr) == ("Beispiel Kastenwagen Hochdach", 22500, True, "12345 Beispielstadt", 132000, 2012)
    assert (i.art, i.marke, i.leistung, i.getriebe, i.gewerblich) == ("Kastenwagen", "Volkswagen", "103 kW (140 PS)", "Schaltgetriebe", False)
    assert i.beschreibung.startswith("Beispieltext: Kastenwagen") and "132.000 km" in i.beschreibung
    assert i.details["Kategorie"] == "Kastenwagen" and i.details["Schlafmöglichkeiten"] == "Festbett"
    assert i.details["Ausstattung"] == "ABS, Anhängerkupplung fest, Markise" and i.details["Anzahl Schlafplätze"] == "2"


def test_anzeigenseite_keine_personendaten(detail):
    _, [i] = erkenne_seite(detail)
    alles = json.dumps(i.als_datensatz(), ensure_ascii=False)
    for fremd in ("+49", "Tel", "Einblenden", "seller", "searchId", "Beispiel Karussell", "35.980"):
        assert fremd not in alles
    assert "verkaeufer_name" not in i.details                         # Privatanbieter haben auf mobile.de keinen Profilnamen


def test_anzeigenseite_kategorie_andere_ist_keine_art_und_aehnliche_zaehlen_nicht(detail):
    d = parse_detailseite(detail.replace("<dd class=\"_GxGsO\">Kastenwagen</dd>", "<dd class=\"_GxGsO\">Wohnmobil andere</dd>"))
    assert d["art"] is None and d["details"]["Kategorie"] == "Wohnmobil andere"


def test_anzeigenseite_json_ld_als_rueckfall(detail):
    ohne = (detail.replace('data-testid="vip-price-label"', 'data-testid="x"').replace('data-testid="vip-technical-data-box"', 'data-testid="x"')
            .replace('data-testid="vip-ad-title"', 'data-testid="x"'))
    d = parse_detailseite(ohne)
    assert (d["preis"], d["km"], d["titel"], d["marke"], d["art"]) == (22500, 132000, "Beispiel Kastenwagen Hochdach", "Volkswagen", "Kastenwagen")
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
        "mobile.de", 28000, 1, "23456 Beispielstadt", 102000, 2016, 0, 0)
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
            22500, 132000, 2012, "Volkswagen", "103 kW (140 PS)", "Schaltgetriebe")
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
    (ordner / "b.html").write_text(privat.replace(f"22.500{chr(160)}€", f"21.000{chr(160)}€"), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["neu"], stat["bekannt"], stat["preis"]) == (0, 2, 1)
    z = zeile(db, "md-3900000021")
    assert (z["preis"], z["preis_vorher"]) == (21000, 22500) and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 3


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
    for fremd in ("+49", "Tel.", "Einblenden", "searchId", "refId", "utm_", "Reisemobile GmbH", "Wohnwagenhandel", "Caravaning", "verkaeufer_name",
                  "Beispiel Karussell"):
        assert fremd not in inhalt, fremd


def test_bewertung_ohne_quellenlogik_gewerbliche_gesperrt_private_bewertet(cfg, db: Datenbank, ordner):
    kopiere(ordner, "suchseite.html", "suchseite_privat.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, Path(__file__).resolve().parent.parent)}
    assert len(zeilen) == 7 + 3
    for ad_id in ("md-390000019", "md-3900000013", "md-3900000014", "md-3900000016"):
        assert zeilen[ad_id]["sperre"] == "gewerblicher Anbieter" and not zeilen[ad_id]["bereit"]
    privat = zeilen["md-3900000021"]
    assert privat["sperre"] is None and privat["hinweise"] == [] and privat["b"].art == "Kastenwagen"       # bestätigte Art: kein Hinweis
    unbekannt = zeilen["md-3900000012"]
    assert unbekannt["sperre"] is None and unbekannt["hinweise"] and unbekannt["hinweise"][0].startswith(HINWEIS_ART_UNBEKANNT_ANFANG)
    assert HINWEIS_ART_VORLAEUFIG not in unbekannt["hinweise"]


def test_bewertung_gewerbliche_hinweislogik_unveraendert_fuer_sponsoren(cfg, db: Datenbank, ordner):
    """Auch ein gesponserter Platz ist ein normaler Datensatz: privat → bewertbar, gewerblich → gesperrt."""
    kopiere(ordner, "suchseite.html")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, Path(__file__).resolve().parent.parent)}
    assert zeilen["md-3900000015"]["sperre"] == "Preis außerhalb Filter"        # 130.000 € – privat, aber über der Preisgrenze
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
