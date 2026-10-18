"""P2-05 (Backend): Import per Adresse + eingefügtem Text – rein lesen (kein Netz, kein Serverabruf, ADR-010), einheitlich schreiben,
Datenschutz (Kontaktdaten, Namen, Straßen verlassen den Text nie), Gesuche und fremde Adressen nie speichern, Rechte je Rolle.

Grenze: Die Texte sind nachgebaut wie kopierte Anzeigenseiten; echte Texte können anders aufgebaut sein (Erkennung best effort).
"""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.test_team_bearbeitung import anmelden, lokal, server, team  # noqa: F401 – Fixtures
from wmscout.datenbank import BESTAETIGT, VORLAEUFIG, import_art
from wmscout.eingang import Eingang, Lesung, Rohdaten, SeitenEingang, TextEingang, bereinige, lese_text, pruefe_adresse
from wmscout.eingang.text import MAX_BESCHREIBUNG
from wmscout.domaene import PUSH_KANAELE
from wmscout.haendler import HaendlerSpeicher
from wmscout.importer import Importer
from wmscout.web.api import TEXT_IMPORT_ROLLEN

JETZT = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
KA_URL = "https://www.kleinanzeigen.de/s-anzeige/knaus-sky-ti-650-meg/2987654321-220-1234"
MD_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=3900000010"
MD_DATEI = Path(__file__).resolve().parent / "seiten" / "mobilede" / "detailseite.html"

KA_TEXT = """Kleinanzeigen
Knaus Sky TI 650 MEG Teilintegrierter Wohnmobil
24.900 € VB
12345 Beispielstadt
Details
Kilometerstand 85.000 km
Erstzulassung 03/2019
Beschreibung
Verkaufe unser gepflegtes Wohnmobil, Nichtraucher, TÜV neu. Neupreis war 80.000 €.
Besichtigung nach Absprache, Lindenweg 12, 12345 Beispielstadt.
Rufen Sie an: 0176 9988776 oder +49 176 5544332, mail: h.kowalski@web.de
Viele Grüße
Hans Kowalski
Hans Kowalski
Privater Nutzer
Aktiv seit 12.03.2021
Anzeigen-ID: 2987654321
Ähnliche Anzeigen
Hymer B 544 9.999 € 12.000 km EZ 2001
"""
MD_TEXT = """Knaus BoxStar 600 Kastenwagen
19.500 €
Kilometerstand 76.500 km
Erstzulassung 05/2018
80331 München
Gepflegter Camper, Erstbesitz.
"""
# Merkmale, die nirgends in der Datenbank stehen dürfen
GEHEIM = ("0176 9988776", "9988776", "5544332", "kowalski", "web.de", "Kowalski", "Lindenweg", "Aktiv seit")


class KeinNetz:
    """Abruf, der jeden Aufruf verweigert und mitzählt."""

    def __init__(self):
        self.abrufe = []

    def hole(self, url):
        self.abrufe.append(url)
        raise AssertionError(f"Netzabruf verboten: {url}")


def roh(url=KA_URL, text=KA_TEXT, anbieter="privat"):
    return TextEingang.rohdaten(url, text, anbieter, JETZT)


def speichere(cfg, db, url=KA_URL, text=KA_TEXT, anbieter="privat"):
    """Lesen und über den einzigen Schreibweg speichern; Rückgabe: (Lesung, Zähler)."""
    eingang = TextEingang()
    lesung = eingang.lese(roh(url, text, anbieter))
    return lesung, Importer(cfg, db, abruf=KeinNetz()).importiere(lesung, eingang.kanal)


def zeile(db, ad_id):
    return db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()


def zaehle(db, tabelle):
    return db.con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


def alle_texte(db) -> str:
    """Jeder Wert jeder Tabelle der Datenbank als ein Text – nichts Geheimes darf darin vorkommen."""
    tabellen = [r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return "\n".join(" | ".join(str(v) for v in z) for t in tabellen for z in db.con.execute(f"SELECT * FROM {t}"))


# ---------------------------------------------------------------- Vertrag und Felder
def test_texteingang_erfuellt_vertrag():
    eingang = TextEingang()
    assert isinstance(eingang, Eingang) and (eingang.kennung, eingang.kanal) == ("text", "manuell") and eingang.kanal in PUSH_KANAELE
    assert isinstance(eingang.lese(roh()), Lesung)


def test_kleinanzeigen_felder_und_kanonische_adresse(monkeypatch):
    def gesperrt(*a, **k):
        raise AssertionError("Netzzugriff beim Lesen")

    monkeypatch.setattr(socket, "socket", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)
    lesung = TextEingang().lese(roh(KA_URL + "?utm_source=x&ref=y#bild", KA_TEXT, "privat"))
    assert lesung.art == "detail" and lesung.plattform == "kleinanzeigen" and len(lesung.inserate) == 1
    i = lesung.inserate[0]
    assert (i.quelle, i.anzeigen_id, i.url) == ("kleinanzeigen", "2987654321", KA_URL)       # ohne Such-/Tracking-Parameter
    assert (i.titel, i.preis, i.vb, i.km, i.ez_jahr, i.ort, i.marke) == (
        "Knaus Sky TI 650 MEG Teilintegrierter Wohnmobil", 24900, True, 85000, 2019, "12345 Beispielstadt", "Knaus")
    assert i.gewerblich is False and i.art is None and i.ist_gesuch is False and i.details == {}
    assert "Neupreis" in i.beschreibung and "Hymer" not in i.beschreibung             # Text endet vor „Ähnliche Anzeigen“
    assert lesung.art_filter is None and lesung.haupttreffer is None
    assert any("vorläufig, nicht bestätigt" in h for h in lesung.hinweise)


def test_mobilede_adresse_und_felder():
    lesung = lese_text(MD_URL + "&searchId=abc&utm_source=mail&vc=Motorhome", MD_TEXT, None, JETZT)
    i = lesung.inserate[0]
    assert (lesung.plattform, i.quelle, i.anzeigen_id, i.url) == ("mobile.de", "mobile.de", "md-3900000010", MD_URL)
    assert (i.preis, i.km, i.ez_jahr, i.ort, i.marke, i.gewerblich) == (19500, 76500, 2018, "80331 München", "Knaus", None)
    assert any("Anbieter" in h and "nicht angegeben" in h for h in lesung.hinweise)


@pytest.mark.parametrize("text", [
    "Knaus Sky TI 650 MEG\n24.900 €\nEZ 03/2019\n85.000 km\n12345 Ort",
    "Knaus Sky TI 650 MEG\nPreis: 24.900,- €\nErstzulassung: 12.03.2019\nKilometerstand: 85000\n12345 Ort",
    "Knaus Sky TI 650 MEG\n€ 24.900\nBaujahr 2019\n85 tkm\n12345 Ort",
])
def test_schreibweisen_von_preis_ez_km(text):
    i = lese_text(KA_URL, text, None, JETZT).inserate[0]
    assert (i.preis, i.ez_jahr, i.km, i.ort) == (24900, 2019, 85000, "12345 Ort")


def test_fliesstext_ohne_eurozeichen():
    i = lese_text(KA_URL, "Verkaufe Hymer B 584, Bj 2014, 75.000 km, 29500 VB, Standort 70173 Stuttgart. Nichtraucher.", None, JETZT).inserate[0]
    assert (i.preis, i.vb, i.ez_jahr, i.km, i.ort, i.marke) == (29500, True, 2014, 75000, "70173 Stuttgart", "Hymer")


def test_neupreis_garantie_und_unplausibles_zaehlen_nicht():
    text = "Hymer B 544\nNeupreis 89.000 €\nGarantie bis 100.000 km\n18.500 €\nEZ 2012\n95.000 km\nErstzulassung 1850"
    i = lese_text(KA_URL, text, None, JETZT).inserate[0]
    assert (i.preis, i.km, i.ez_jahr) == (18500, 95000, 2012)
    assert lese_text(KA_URL, "Hymer B 544\nEZ 2090\n18.500 €", None, JETZT).inserate[0].ez_jahr is None       # Zukunft: unplausibel


def test_unvollstaendig_ist_speicherbar_mit_hinweis(cfg, db):
    lesung, stat = speichere(cfg, db, text="Hymer Camper schnell zu verkaufen", anbieter=None)
    assert lesung.art == "detail" and stat["neu"] == 1
    i = lesung.inserate[0]
    assert (i.preis, i.km, i.ez_jahr, i.ort) == (None, None, None, None)
    assert any(h.startswith("unvollständig:") and "Preis" in h and "Erstzulassung" in h for h in lesung.hinweise)
    assert any("keine Beträge" in h for h in lesung.hinweise)
    z = zeile(db, "2987654321")
    assert z["ez_jahr"] is None and z["preis"] is None and z["gewerblich"] is None
    assert Importer(cfg, db).importiere(lesung, "manuell")["bekannt"] == 1


def test_text_ohne_ez_zeigt_keine_betraege(cfg, db):
    from wmscout.bewertung.rechner import Rechner
    lesung, _ = speichere(cfg, db, text="Hymer Teilintegrierter\n29.000 €\n90.000 km\n12345 Ort")
    z = dict(zeile(db, "2987654321"))
    assert Rechner(cfg).bewerte(z, []).sicherheit == "keine"          # P1-12: ohne Erstzulassung keine Beträge


def test_anbieter_wird_uebernommen_sonst_unbekannt(cfg, db):
    for anbieter, erwartet in (("privat", 0), ("gewerblich", 1), (None, None), ("", None)):
        db.con.execute("DELETE FROM anzeigen WHERE id='2987654321'")
        db.con.commit()
        speichere(cfg, db, anbieter=anbieter)
        assert zeile(db, "2987654321")["gewerblich"] == erwartet, anbieter
    with pytest.raises(ValueError, match="anbieter"):
        lese_text(KA_URL, KA_TEXT, "vielleicht", JETZT)


def test_rohdaten_fehlerhaft_ist_unbekannt_nie_exception():
    e = TextEingang()
    for inhalt in (b"keine json", b"[]", b'{"url": 1, "text": "x"}', b'{"url": "u", "text": "x", "anbieter": 3}', b"\xff\xfe"):
        lesung = e.lese(Rohdaten(inhalt, "text", JETZT))
        assert lesung.art == "unbekannt" and lesung.inserate == [] and lesung.hinweise
    assert e.lese(roh(anbieter="vielleicht")).art == "unbekannt"


# ---------------------------------------------------------------- Speichern über den einzigen Schreibweg
def test_speichern_kanal_manuell_und_art_vorlaeufig(cfg, db):
    lesung, stat = speichere(cfg, db)
    assert stat["neu"] == 1 and stat["detailseiten"] == 1 and stat["details"] == 1
    z = zeile(db, "2987654321")
    assert (z["preis"], z["km"], z["ez_jahr"], z["ort"], z["gewerblich"], z["quelle"], z["url"]) == (
        24900, 85000, 2019, "12345 Beispielstadt", 0, "kleinanzeigen", KA_URL)
    assert import_art(z["suche"]) == ("Teilintegrierter", VORLAEUFIG)                      # nie bestätigt
    assert z["art"] is None and z["detail_geladen"] == 0 and "Max" not in (z["beschreibung"] or "")
    kanaele = {r[0] for r in db.con.execute("SELECT kanal FROM beobachtungen b JOIN inserate i ON i.id=b.inserat_id WHERE i.anzeigen_id='2987654321'")}
    assert kanaele == {"manuell"}
    historie = db.con.execute("SELECT p.kanal FROM preis_historie p JOIN inserate i ON i.id=p.inserat_id WHERE i.anzeigen_id='2987654321'").fetchall()
    assert [h[0] for h in historie] == ["manuell"]


@pytest.mark.parametrize("text", [
    "Wohnmobil zu verkaufen\n20.000 €\nArt: Kastenwagen\nKategorie Alkoven",              # Art im Text ohne Titelwort
    "Hymer Alkoven oder Kastenwagen?\n20.000 €",                                          # mehrdeutiger Titel
    "Knaus Teilintegrierter\n20.000 €\nIntegrierter Aufbau",                              # Widerspruch
])
def test_art_wird_nie_bestaetigt(cfg, db, text):
    lesung, _ = speichere(cfg, db, text=text)
    assert lesung.inserate[0].art is None
    art, herkunft = import_art(zeile(db, "2987654321")["suche"])
    assert herkunft != BESTAETIGT


def test_bestaetigte_art_einer_gespeicherten_seite_bleibt(cfg, db):
    from wmscout.eingang import SeitenEingang
    seite = SeitenEingang().lese(Rohdaten(MD_DATEI.read_bytes(), "d.html", JETZT))
    Importer(cfg, db).importiere(seite, "manuell")
    vorher = zeile(db, "md-3900000010")
    assert import_art(vorher["suche"]) == ("Kastenwagen", BESTAETIGT)
    details_vorher = vorher["details_json"]
    assert details_vorher and details_vorher != "{}"
    lesung, stat = speichere(cfg, db, url=MD_URL + "&searchId=1&utm_medium=x", text=MD_TEXT.replace("Kastenwagen", "Alkoven"))
    assert stat["neu"] == 0 and zaehle(db, "anzeigen") == 1 and zaehle(db, "inserate") == 1      # dieselbe Zeile, kein Duplikat
    nachher = zeile(db, "md-3900000010")
    assert import_art(nachher["suche"]) == ("Kastenwagen", BESTAETIGT)
    assert nachher["details_json"] == details_vorher                  # der Text ohne Merkmalsliste löscht die Merkmale der Seite nicht
    assert nachher["url"] == MD_URL and nachher["preis"] == 19500    # der neuere Preis aus dem Text gilt


def test_mobilede_text_zuerst_dann_seite_ist_eine_zeile(cfg, db):
    speichere(cfg, db, url=MD_URL, text=MD_TEXT)
    Importer(cfg, db).importiere(SeitenEingang().lese(Rohdaten(MD_DATEI.read_bytes(), "d.html", JETZT)), "manuell")
    assert zaehle(db, "anzeigen") == 1 and zaehle(db, "inserate") == 1
    assert import_art(zeile(db, "md-3900000010")["suche"]) == ("Kastenwagen", BESTAETIGT)


def test_niedrigerer_preis_ist_preissenkung(cfg, db):
    _, erst = speichere(cfg, db)
    assert erst["neu"] == 1
    _, gleich = speichere(cfg, db)
    assert gleich["bekannt"] == 1 and gleich["preis"] == 0
    _, billiger = speichere(cfg, db, text=KA_TEXT.replace("24.900 €", "22.500 €"))
    assert billiger["preis"] == 1 and billiger["neu"] == 0
    z = zeile(db, "2987654321")
    assert (z["preis"], z["preis_vorher"]) == (22500, 24900)
    preise = [r[0] for r in db.con.execute(
        "SELECT p.preis FROM preis_historie p JOIN inserate i ON i.id=p.inserat_id WHERE i.anzeigen_id='2987654321' ORDER BY p.id")]
    assert preise == [24900, 22500]
    _, teurer = speichere(cfg, db, text=KA_TEXT.replace("24.900 €", "26.000 €"))
    assert teurer["preis"] == 0 and zeile(db, "2987654321")["preis_vorher"] == 24900


def test_kein_netzaufruf_beim_lesen_und_speichern(cfg, db, monkeypatch):
    def gesperrt(*a, **k):
        raise AssertionError("Netzzugriff")

    monkeypatch.setattr(socket, "socket", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)
    netz = KeinNetz()
    eingang = TextEingang()
    for url, text in ((KA_URL, KA_TEXT), (MD_URL, MD_TEXT)):
        Importer(cfg, db, abruf=netz).importiere(eingang.lese(roh(url, text)), "manuell")
    assert netz.abrufe == [] and zaehle(db, "anzeigen") == 2


# ---------------------------------------------------------------- Nichts speichern
SCHLECHTE_URLS = [
    "javascript:alert(1)", "ftp://www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234", "data:text/html,<b>x</b>", "file:///etc/passwd",
    "https://evil.example/s-anzeige/x/2987654321-220-1234", "https://www.kleinanzeigen.de.evil.example/s-anzeige/x/2987654321-220-1234",
    "https://evil.example/?u=www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234", "https://notmobile.de/fahrzeuge/details.html?id=3900000010",
    "https://www.kleinanzeigen.de@evil.example/s-anzeige/x/2987654321-220-1234", "https://user@www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234",
    "https://www.kleinanzeigen.de:8443/s-anzeige/x/2987654321-220-1234", "https://evil.example\\@www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234",
    "https://www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234/zusatz", "https://www.kleinanzeigen.de/s-anzeige/x/2987654321", "https://www.autoscout24.de/angebote/knaus-123456789",
    "https://www.kleinanzeigen.de/s-wohnwagen-mobile/c220", "https://www.kleinanzeigen.de/s-anzeige/x/abc",
    "https://suchen.mobile.de/fahrzeuge/search.html?id=3900000010", "https://suchen.mobile.de/fahrzeuge/details.html?x=1#id=3900000010",
    "https://suchen.mobile.de/fahrzeuge/details.html", "https://www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234 evil", "", "   ",
    "www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234", "https://", "http://[::1", "https://www.kleinanzeigen.de/s-anzeige/x/2987654321-220-1234\n",
]


@pytest.mark.parametrize("url", SCHLECHTE_URLS)
def test_fremde_und_unbrauchbare_adressen_werden_nicht_gespeichert(cfg, db, url):
    if url.endswith("\n"):
        url = url + "x"                      # eingebetteter Zeilenumbruch (nicht nur Rand, den der Nutzer-Einfügevorgang mitbringt)
    lesung = lese_text(url, KA_TEXT, "privat", JETZT)
    assert lesung.art == "unbekannt" and lesung.inserate == [] and lesung.hinweise
    with pytest.raises(ValueError):
        Importer(cfg, db).importiere(lesung, "manuell")
    assert (zaehle(db, "anzeigen"), zaehle(db, "inserate"), zaehle(db, "beobachtungen"), zaehle(db, "preis_historie")) == (0, 0, 0, 0)


def test_id_kommt_aus_dem_letzten_pfadteil_nicht_aus_dem_titel_slug():
    assert pruefe_adresse("https://www.kleinanzeigen.de/s-anzeige/123456-1-1/9999999999-220-1234")[0].anzeigen_id == "9999999999"


def test_adresse_mit_rand_und_kurzform_wird_normalisiert():
    assert pruefe_adresse(f"  {KA_URL}  ")[0].url == KA_URL
    kurz = pruefe_adresse("https://m.kleinanzeigen.de/s-anzeige/2987654321?x=1")[0]
    assert (kurz.anzeigen_id, kurz.url) == ("2987654321", "https://www.kleinanzeigen.de/s-anzeige/2987654321")
    md = pruefe_adresse("http://www.mobile.de/fahrzeuge/details.html?vc=Motorhome&id=3900000010&utm_campaign=z")[0]
    assert (md.anzeigen_id, md.url) == ("md-3900000010", MD_URL)


@pytest.mark.parametrize("text", [
    "Suche Wohnmobil bis 30.000 €\nNur von privat, gerne mit Gasprüfung",
    "Gesuch\nKnaus Sky TI gesucht",
    "Wir kaufen Ihr Wohnmobil sofort\nBarankauf bundesweit",
    "Ich suche einen Kastenwagen, EZ ab 2015\n25.000 €",
    "Gesucht: Hymer B-Klasse\nBudget 40.000 €",
    "Ankauf von Wohnmobilen und Caravans aller Art\nFaire Preise",
])
def test_gesuche_werden_nicht_gespeichert(cfg, db, text):
    lesung = lese_text(KA_URL, text, "privat", JETZT)
    assert lesung.art == "unbekannt" and lesung.inserate == [] and "Gesuch" in lesung.hinweise[0]
    with pytest.raises(ValueError):
        Importer(cfg, db).importiere(lesung, "manuell")
    assert zaehle(db, "anzeigen") == 0


@pytest.mark.parametrize("text", [
    "Suche neuen Besitzer für Hymer B 544\n20.000 €\nEZ 2012",
    "Kaufen Sie dieses Wohnmobil, Hymer B 544\n20.000 €",
    "Hymer B 544 Teilintegrierter\n20.000 €\nIch suche keinen Tausch, nur Verkauf.\nSuche ist beendet.",
])
def test_verkaufsanzeigen_mit_suche_im_wortlaut_bleiben_erhalten(text):
    assert lese_text(KA_URL, text, None, JETZT).art == "detail"


def test_leerer_oder_zu_langer_text_wird_nicht_gespeichert():
    for text in ("", "   \n\n ", "x" * 50_001):
        lesung = lese_text(KA_URL, text, None, JETZT)
        assert lesung.art == "unbekannt" and lesung.inserate == [] and lesung.hinweise
    assert lese_text(KA_URL, "0176 9988776", None, JETZT).art == "unbekannt"          # nur Kontaktdaten: nach der Bereinigung nichts übrig


# ---------------------------------------------------------------- Datenschutz
def test_kontaktdaten_und_namen_stehen_nirgends_in_der_datenbank(cfg, db):
    lesung, _ = speichere(cfg, db)
    inhalt = alle_texte(db)
    for geheim in GEHEIM:
        assert geheim not in inhalt, geheim
    for geheim in GEHEIM:
        for i in lesung.inserate:
            assert geheim not in repr(i)
    assert any("Datenschutz" in h and "Telefonnummer" in h for h in lesung.hinweise)
    assert "Verkaufe unser gepflegtes Wohnmobil" in zeile(db, "2987654321")["beschreibung"]          # Fahrzeugtext bleibt


@pytest.mark.parametrize("roh_text, bleibt_nicht", [
    ("Tel: 0171-1234567", "1234567"), ("Tel 0171 / 12 34 567", "34 567"), ("+49 (0) 171 1234567", "1234567"), ("(+49) 171 12345678", "12345678"),
    ("0049 171 1234567", "1234567"), ("WhatsApp 017612345678", "17612345678"), ("030 12345678", "12345678"), ("089/123456", "123456"),
    ("Ruf an unter 49 171 1234567", "1234567"), ("0711-123456-0", "123456"), ("01512 3456789", "3456789"),
    ("max@web.de", "web.de"), ("max (at) web (punkt) de", "web"), ("Insta @maxmuster", "maxmuster"), ("www.web.de/x", "web.de"),
    ("Hauptstr. 5", "Hauptstr"), ("Lindenallee 12a, 12345 Ort", "Lindenallee"), ("Name: Peter Schmidt", "Schmidt"),
    ("Ansprechpartner: Frau Weber", "Weber"), ("Ich heiße Peter Schmidt und verkaufe", "Schmidt"), ("Herr Müller zeigt es Ihnen", "Müller"),
    ("Mit freundlichen Grüßen\nHans Meier", "Meier"), ("LG Peter", "Peter"), ("zum Beispiel\nBeste Grüße\nAnna Berger", "Berger"),
])
def test_bereinigung_entfernt_kontaktdaten(roh_text, bleibt_nicht):
    sauber, _ = bereinige("Hymer B 544 Teilintegrierter\n" + roh_text)
    assert bleibt_nicht not in sauber and "Hymer B 544" in sauber


def test_bereinigung_laesst_fahrzeugdaten_in_ruhe():
    text = "85.000 km EZ 03/2019 24.900 € 140 PS 2.287 ccm 3.500 kg 7,40 m Sitzplatz 4 Personen, Schlafplatz 4, TÜV 06/2027, FIN WDB9066331S123456"
    sauber, entfernt = bereinige(text)
    assert sauber == text and sum(entfernt.values()) == 0


def test_beschreibung_wird_gekuerzt_und_ist_nie_laenger_als_erlaubt(cfg, db):
    lang = "Sehr gepflegtes Fahrzeug mit viel Zubehör. " * 200
    lesung, _ = speichere(cfg, db, text="Hymer B 544\n20.000 €\n" + lang)
    i = lesung.inserate[0]
    assert len(i.beschreibung) <= MAX_BESCHREIBUNG + 2 and i.beschreibung.endswith("…") and len(i.kurzbeschreibung) <= 200
    assert any("gekürzt" in h for h in lesung.hinweise)
    assert len(zeile(db, "2987654321")["beschreibung"]) <= MAX_BESCHREIBUNG + 2


def test_lange_eingaben_bleiben_schnell():
    import time
    URL = KA_URL
    for boese in ("a" * 50_000, "a." * 25_000, "0" * 50_000, "1 " * 25_000, "a@" * 25_000, "\n" * 50_000, "-" * 50_000, "0 1" * 16_000,
                  "Straße " * 7_000, "+4 " * 16_000, "Wohnmobil-" * 5_000):
        start = time.monotonic()
        lese_text(URL, boese, None, JETZT)
        assert time.monotonic() - start < 3, boese[:12]


# ---------------------------------------------------------------- API
def post(client, **daten):
    return client("POST", "/api/import/text", daten)


def test_api_mitarbeiter_darf_importieren(server, team, db):
    ben = anmelden(server, "Ben")                                              # Mitarbeiter
    status, antwort, _ = post(ben, url=KA_URL + "?utm=1", text=KA_TEXT, anbieter="privat")
    assert status == 200
    assert antwort["ergebnis"] == "neu" and antwort["gespeichert"] is True and antwort["anzeige_id"] == "2987654321"
    assert antwort["fahrzeug_url"] == "/m#/fahrzeug/2987654321" and antwort["plattform"] == "kleinanzeigen"
    assert antwort["erkannt"] == {"titel": "Knaus Sky TI 650 MEG Teilintegrierter Wohnmobil", "preis": 24900, "vb": True, "km": 85000,
                                  "ez_jahr": 2019, "ort": "12345 Beispielstadt", "marke": "Knaus", "gewerblich": False}
    assert any("vorläufig" in h for h in antwort["hinweise"])
    assert zeile(db, "2987654321")["url"] == KA_URL
    status, antwort, _ = post(ben, url=KA_URL, text=KA_TEXT.replace("24.900 €", "23.000 €"))
    assert status == 200 and antwort["ergebnis"] == "preis"
    assert post(ben, url=KA_URL, text=KA_TEXT.replace("24.900 €", "23.000 €"))[1]["ergebnis"] == "bekannt"
    status, fahrzeug, _ = ben("GET", "/api/fahrzeug/2987654321")                # erscheint für das Team in der App
    assert status == 200 and fahrzeug["id"] == "2987654321"
    assert "9988776" not in str(fahrzeug) and "Kowalski" not in str(fahrzeug)


def test_api_inhaber_darf_und_mobilede(server, team, db):
    anna = anmelden(server, "Anna")
    status, antwort, _ = post(anna, url=MD_URL + "&searchId=9", text=MD_TEXT)
    assert status == 200 and antwort["anzeige_id"] == "md-3900000010" and antwort["fahrzeug_url"] == "/m#/fahrzeug/md-3900000010"
    assert zeile(db, "md-3900000010")["quelle"] == "mobile.de"


def test_api_standort_zugang_bekommt_403(server, team, db):
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale Nord", "20095", "Hamburg")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    hugo = anmelden(server, "Hugo")
    vorher = zaehle(db, "anzeigen")
    status, antwort, _ = post(hugo, url=KA_URL, text=KA_TEXT)
    assert status == 403 and antwort["grund"] == "recht"
    assert zaehle(db, "anzeigen") == vorher and zeile(db, "2987654321") is None
    assert TEXT_IMPORT_ROLLEN == ("inhaber", "mitarbeiter")


def test_api_ohne_anmeldung_csrf_und_host(server, team, db):
    from tests.test_handy import Client
    port = server.server_address[1]
    assert post(Client(port), url=KA_URL, text=KA_TEXT)[0] == 401                  # Team-Modus: auch lokal nur angemeldet
    ben = anmelden(server, "Ben")
    assert ben("POST", "/api/import/text", {"url": KA_URL, "text": KA_TEXT}, token=False)[0] == 403       # ohne CSRF-Token
    assert Client(port, "boese.example")("POST", "/api/import/text", {"url": KA_URL, "text": KA_TEXT})[0] == 403    # fremder Hostname
    assert zeile(db, "2987654321") is None


def test_api_ohne_team_lokal_wie_seitenimport(server, db):
    c = lokal(server)
    status, antwort, _ = post(c, url=KA_URL, text=KA_TEXT)
    assert status == 200 and antwort["ergebnis"] == "neu"
    assert c("POST", "/api/import/text", {"url": KA_URL, "text": KA_TEXT}, token=False)[0] == 403         # CSRF auch lokal


def test_api_grenzen_und_ungueltige_eingaben(server, team, db):
    ben = anmelden(server, "Ben")
    assert post(ben, url=KA_URL, text="x" * 50_001)[0] == 400
    assert post(ben, url=KA_URL.replace("2987654321", "2987654322"), text="x" * 50_000)[0] == 200      # genau am Limit ist erlaubt
    assert post(ben, url=KA_URL + "?" + "a" * 2000, text=KA_TEXT)[0] == 400
    assert post(ben, url=KA_URL, text=KA_TEXT, anbieter="vielleicht")[0] == 400
    assert post(ben, url=KA_URL)[0] == 400 and post(ben, text=KA_TEXT)[0] == 400
    assert post(ben, url=5, text=KA_TEXT)[0] == 400 and post(ben, url=KA_URL, text=["x"])[0] == 400
    assert ben("POST", "/api/import/text", [1, 2])[0] == 400
    assert zeile(db, "2987654321") is None


def test_api_nicht_speicherbares_gibt_422_mit_hinweis(server, team, db):
    ben = anmelden(server, "Ben")
    vorher = zaehle(db, "anzeigen")
    for url, text, stichwort in (("https://evil.example/s-anzeige/x/2987654321-220-1234", KA_TEXT, "Plattform nicht unterstützt"),
                                 ("javascript:alert(1)", KA_TEXT, "http"),
                                 (KA_URL, "Suche Wohnmobil bis 20.000 €", "Gesuch"),
                                 ("https://www.kleinanzeigen.de/s-wohnwagen-mobile/c220", KA_TEXT, "einzelne")):
        status, antwort, _ = post(ben, url=url, text=text)
        assert status == 422 and antwort["ergebnis"] == "nicht_gespeichert" and antwort["gespeichert"] is False, url
        assert stichwort in antwort["fehler"] and antwort["hinweise"][0] == antwort["fehler"]
    assert zaehle(db, "anzeigen") == vorher


def test_api_schalter_abgeschaltet_gibt_409(cfg, server, team, db):
    ben = anmelden(server, "Ben")
    cfg["eingaenge"] = {"text": {"aktiv": False}}
    status, antwort, _ = post(ben, url=KA_URL, text=KA_TEXT)
    assert status == 409 and antwort["grund"] == "deaktiviert" and zeile(db, "2987654321") is None
    cfg["eingaenge"] = {"text": {"aktiv": True}}
    assert post(ben, url=KA_URL, text=KA_TEXT)[0] == 200
    cfg["eingaenge"] = {"text": None}                                             # leerer Abschnitt in der YAML-Datei: weiter aktiv
    assert post(ben, url=KA_URL, text=KA_TEXT)[0] == 200


def test_api_audit_eintrag_ohne_inhalte(server, team, db):
    ben = anmelden(server, "Ben")
    post(ben, url=KA_URL, text=KA_TEXT)
    eintraege = [dict(r) for r in db.con.execute("SELECT * FROM audit WHERE pfad='/api/import/text'")]
    assert len(eintraege) == 1 and eintraege[0]["nutzer"] == "Ben" and eintraege[0]["aktion"] == "aendern" and eintraege[0]["status"] == 200
    assert "Kowalski" not in str(eintraege) and "9988776" not in str(eintraege)
    assert "Kowalski" not in alle_texte(db)


def test_api_live_ereignis_wird_gemeldet(server, team):
    k = server.RequestHandlerClass.kontext
    ben = anmelden(server, "Ben")
    stand = k.live.stand
    assert post(ben, url=KA_URL, text=KA_TEXT)[0] == 200
    neu, _, _ = k.live.seit(stand, haendler=False)
    assert [e["art"] for e in neu] == ["team"]
    assert post(ben, url="javascript:alert(1)", text=KA_TEXT)[0] == 422                  # nichts gespeichert → kein Ereignis
    assert k.live.seit(stand, haendler=False)[0] == neu
