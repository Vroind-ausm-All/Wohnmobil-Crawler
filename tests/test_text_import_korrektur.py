"""P2-05 Korrekturrunde nach QA: Preiserkennung (K1), Laufzeit (H1), Bereinigung (M1/M2), Gesuche (M3), IDs (M4), nur leere Felder (M5),
Preis-Schreibweisen (M6) und Randfälle der API (N1–N4).

Grenze: nachgebaute Texte; echte kopierte Anzeigen können anders aufgebaut sein.
"""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import time

import pytest

from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from tests.test_text_import import JETZT, KA_URL, MD_URL, post, speichere, zeile, zaehle
from wmscout.bewertung.rechner import Rechner
from wmscout.eingang import bereinige, lese_text, pruefe_adresse
from wmscout.eingang.text import TextEingang

FELDER = "\nEZ 03/2015\n80.000 km\n12345 Ort"


def preis_von(text):
    lesung = lese_text(KA_URL, text, None, JETZT)
    assert lesung.art == "detail", lesung.hinweise
    return lesung.inserate[0].preis, lesung


# ---------------------------------------------------------------- K1 Preis
@pytest.mark.parametrize("text, erwartet", [
    ("Verkaufe Hymer B 544 Teilintegrierter, Solaranlage und Markise für 6.500 € nachgerüstet, 34.900 VB. 12345 Ort", 34900),
    ("Hymer B 544 Teilintegrierter\nneue Reifen (900 €), TÜV neu, 24.900 VB", 24900),
    ("Hymer B 544 Teilintegrierter\nGutachten über 35.000 € liegt vor, VB 24.900", 24900),
    ("Hymer B 544\nNeupreis war 80.000 €, jetzt 24.900 € VB", 24900),
    ("Hymer B 544\nAnzahlung 3.000 €, Preis 24.900 €", 24900),
    ("Hymer B 544\nKaufpreis 24.900 €", 24900),
    ("Hymer B 544\nPreis 24.900", 24900),
    ("Hymer B 544\nPreis: 24.900,- €", 24900),
    ("Hymer B 544\nVB 24.900", 24900),
    ("Hymer B 544\n24900 VB", 24900),
    ("Hymer B 544\nFestpreis € 24.900", 24900),
    # kein sicherer Preis → keiner
    ("Hymer B 544\nTausch gegen PKW 15.000 € möglich", None),
    ("Hymer B 544\nAb 1.299 € mtl. finanzierbar", None),
    ("Hymer B 544\nAlternativ 399 € Rate pro Monat", None),
    ("Hymer B 544\nSolaranlage und Markise für 6.500 € nachgerüstet", None),
    ("Hymer B 544\nNeue Markise 3.000 €, Solar 2.500 €", None),
    ("Hymer B 544\nPreis 24.900 und Preis 22.000", None),                # widersprüchlich
    ("Hymer B 544\nNeupreis 80.000 €", None),
    ("Hymer B 544\nVerkaufe für 24.900 €.", None),                      # einzelner Betrag im Fließtext: nie ein Preis (nur der Nutzer trägt ihn ein)
])
def test_preis_lieber_keiner_als_ein_falscher(text, erwartet):
    preis, lesung = preis_von(text)
    assert preis == erwartet, (text, preis)
    if erwartet is None:
        assert any(h.startswith("unvollständig:") and "Preis" in h for h in lesung.hinweise)


def test_hinweise_zu_unsicheren_preisen():
    _, sicher = preis_von("Hymer B 544\nKaufpreis 24.900 €")
    assert not any("geschätzt" in h or "nicht sicher" in h for h in sicher.hinweise) and sicher.preis_status == "text"
    _, unsicher = preis_von("Hymer B 544\nNeue Markise 3.000 €, Solar 2.500 €")
    assert any("Preis nicht sicher erkannt (Beträge im Text: 3.000 €, 2.500 €) – bitte Preis im Formular eintragen und erneut einlesen" in h
               for h in unsicher.hinweise) and unsicher.preis_status == "unsicher"


def test_vb_wird_erkannt():
    assert lese_text(KA_URL, "Hymer B 544\n24.900 € VB", None, JETZT).inserate[0].vb is True
    assert lese_text(KA_URL, "Hymer B 544\n24.900 €", None, JETZT).inserate[0].vb is False
    assert lese_text(KA_URL, "Hymer B 544\nVB 24.900", None, JETZT).inserate[0].vb is True


def test_ausstattungsbetrag_wird_nie_zum_gruenen_erstangebot(cfg, db):
    """Vorher: 6.500 € Markise → Preis 6.500 → Ampel grün, Erstangebot 6.200 €."""
    r = Rechner(cfg)
    lesung, _ = speichere(cfg, db, text="Hymer B 544 Teilintegrierter, Solaranlage und Markise für 6.500 € nachgerüstet, 34.900 VB." + FELDER)
    z = dict(zeile(db, "2987654321"))
    assert z["preis"] == 34900
    assert r.bewerte(z, []).erstangebot != 6200
    db.con.execute("DELETE FROM anzeigen WHERE id='2987654321'")
    db.con.commit()
    speichere(cfg, db, text="Hymer B 544 Teilintegrierter, Solaranlage und Markise für 6.500 € nachgerüstet." + FELDER)
    z = dict(zeile(db, "2987654321"))
    b = r.bewerte(z, [])
    assert z["preis"] is None and b.ampel != "gruen" and b.erstangebot != 6200


# ---------------------------------------------------------------- H1 Laufzeit
BOESE = {
    "Zahlenkette": "Hymer\n1." + "111." * 12_495, "Zahlenkette2": "Hymer\n" + ("1" + ".111" * 12_499)[:49_990],
    "Erstzulassung": "Hymer\n" + "Erstzulassung" * 3800, "erstzulassung": "Hymer\n" + "erstzulassung" * 3800, "baujahr": "Hymer\n" + "baujahr" * 7000,
    "Bj": "Hymer\n" + "Bj." * 16000, "EZ": "Hymer\n" + ("EZ " + "a" * 100 + " ") * 480, "kilometerstand": "Hymer\n" + "kilometerstand" * 3500,
    "km stand": "Hymer\n" + "km stand " * 5000, "euro": "Hymer\n€ 1" + ".111" * 12_000, "tel": "Hymer\n" + "12 345" * 8000, "intl": "Hymer\n" + "+1 " * 16000,
    "email at": "Hymer\n" + "a at " * 10000, "strasse": "Hymer\n" + "a-" * 24000 + "straße 1", "am": "Hymer\n" + "Am Markt " * 5000,
    "herr": "Hymer\n" + "Frau Dr. " * 5000, "rolle": "Hymer\n" + "Verkäufer " * 5000, "preise": "Hymer\n" + "Preis 1.000 € VB\n" * 3000,
    "vb": "Hymer\n" + "vb 1" * 12000, "zeilen": "a\n" * 25000, "gesuch": "Suche " * 8000, "social": "Hymer\n" + "Insta " * 8000,
}


@pytest.mark.parametrize("name", sorted(BOESE))
def test_laufzeit_bei_50000_zeichen_unter_einer_sekunde(name):
    text = BOESE[name][:50_000]
    start = time.monotonic()
    lese_text(KA_URL, text, None, JETZT)
    assert time.monotonic() - start < 1, name


def test_fehler_in_der_auswertung_laesst_die_app_nutzbar(server, team, monkeypatch):
    k = server.RequestHandlerClass.kontext
    ben = anmelden(server, "Ben")
    monkeypatch.setattr(TextEingang, "lese", lambda self, roh: (_ for _ in ()).throw(RuntimeError("kaputt")))
    assert post(ben, url=KA_URL, text="x")[0] == 500
    assert ben("GET", "/api/ich")[0] == 200 and not k.sperre.locked()


# ---------------------------------------------------------------- M1 / M2 Bereinigung
@pytest.mark.parametrize("roh_text, weg", [
    ("Frau Dr. Schneider zeigt es Ihnen", "Schneider"), ("Herr Dr. Schulz zeigt es Ihnen", "Schulz"), ("Herr Prof. Dr. Brandt hilft", "Brandt"),
    ("Verkäufer Peter Müller", "Müller"), ("Verkäufer: Peter Müller", "Müller"), ("Ansprechpartner Hans Schulz", "Schulz"),
    ("Ansprechpartnerin Frau Weber erreichbar", "Weber"), ("Bahnhofstr 5", "Bahnhofstr"), ("Bahnhofstr. 5, 12345 Ort", "Bahnhofstr"),
    ("Am Markt 3", "Markt"), ("Am Sonnenhang 5, 12345 Ort", "Sonnenhang"), ("Standort: Auf dem Berg 12", "Berg"),
    ("Telefonnummer: 1234567", "1234567"), ("Handynummer 0176 123", "123"), ("max.mustermann at gmail.com", "gmail"),
    ("max.mustermann (at) gmail (punkt) com", "gmail"), ("Instagram: maxmuster_camper", "maxmuster_camper"), ("Facebook maxmuster.camper", "maxmuster"),
    ("Familie Müller verkauft", "Müller"), ("Fam. Schmidt", "Schmidt"), ("Ich heiße Peter Schmidt", "Schmidt"),
    ("Mit freundlichen Grüßen\nHans Meier", "Meier"), ("Wohnmobil\nLG Peter", "Peter"), ("Wohnmobil\nLG\nPeter", "Peter"),
    ("Tel: ０１７６ ９９８８７７６", "9988776"),                       # Ziffern in anderer Schrift
])
def test_bereinigung_schliesst_luecken(roh_text, weg):
    sauber, entfernt = bereinige("Hymer B 544 Teilintegrierter\n" + roh_text)
    assert weg not in sauber and "Hymer B 544" in sauber, sauber
    assert sum(entfernt.values()) >= 1


@pytest.mark.parametrize("text", [
    "LG Fernseher\nTruma Heizung", "VG Kühlschrank\nDometic Klima", "Ausstattung: LG Fernseher, VG Kühlschrank", "Gurtplatz 4", "Platz 4 Personen",
    "Sitzplatz 4 und Schlafplatz 4", "L/B/H 699 232 290 cm", "Multijet 130 150 160", "Maße 5 99 232 290 cm", "Firma: Hymer", "Händler: Hymer",
    "Mobil: Ja, Wohnmobil", "Im Wohnmobil 4 Schlafplätze", "Am Heck 2 Fahrräder", "Besitzer seit 2015", "Erstbesitzer, Nichtraucher", "Verkäufer privat",
    "Familienfahrzeug mit Stauraum", "Herr der Ringe Edition",
])
def test_bereinigung_laesst_fahrzeugtext_in_ruhe(text):
    sauber, entfernt = bereinige("Hymer B 544 Teilintegrierter\n" + text)
    assert sauber == "Hymer B 544 Teilintegrierter\n" + text and sum(entfernt.values()) == 0


def test_abkuerzung_als_gruss_nur_am_textende():
    assert bereinige("Hymer\nLG Peter")[0] == "Hymer"
    assert bereinige("Hymer\nLG Fernseher\nTruma")[0] == "Hymer\nLG Fernseher\nTruma"
    assert bereinige("Hymer, Nichtraucher. LG Peter")[0] == "Hymer, Nichtraucher."


# ---------------------------------------------------------------- M3 Gesuche
@pytest.mark.parametrize("text", [
    "Wohnmobil gesucht", "Hymer gesucht!", "Wohnmobil Ankauf – sofort Bargeld", "Wohnmobil-Ankauf zum Bestpreis", "Kastenwagen Gesuch",
    "Suche Wohnmobil bis 30.000 €", "Wir kaufen Ihr Wohnmobil", "Gesuch\nWohnmobil bis 30.000 €",
])
def test_gesuche_auch_nachgestellt(text):
    assert lese_text(KA_URL, text, None, JETZT).art == "unbekannt"


@pytest.mark.parametrize("text", [
    "Hymer B 544 zu verkaufen\n25.000 €\nSuche auch Tausch gegen kleineren Kastenwagen",
    "Hymer B 544 Teilintegrierter\n25.000 €\nKaufe ggf. auch Wohnwagen in Zahlung",
    "Hymer B 544 Teilintegrierter\n25.000 €\nIch suche kein Tausch, nur Verkauf",
    "Suche neuen Besitzer für Hymer B 544\n25.000 €", "Hymer B 544 – Verkaufe, Wohnmobil gesucht war das erste Fahrzeug nie",
])
def test_verkaufsanzeigen_mit_suche_im_text_sind_kein_gesuch(text):
    assert lese_text(KA_URL, text, None, JETZT).art == "detail"


# ---------------------------------------------------------------- M4 IDs
@pytest.mark.parametrize("url", [
    "https://www.kleinanzeigen.de/s-anzeige/x/２９８７６５４３２１-220-1234", "https://www.kleinanzeigen.de/s-anzeige/x/٢٩٨٧٦٥٤٣٢١-220-1234",
    "https://www.kleinanzeigen.de/s-anzeige/x/02987654321-220-1234", "https://www.kleinanzeigen.de/s-anzeige/02987654321",
    "https://suchen.mobile.de/fahrzeuge/details.html?id=0003900000010", "https://suchen.mobile.de/fahrzeuge/details.html?id=３９００００００１０",
    "https://www.kleinanzeigen.de/s-anzeige/schönes-wohnmobil/2987654321-220-1234",
])
def test_ids_nur_ascii_ohne_fuehrende_null(cfg, db, url):
    lesung = lese_text(url, "Hymer B 544\n24.900 €", None, JETZT)
    assert lesung.art == "unbekannt" and lesung.inserate == []
    assert zaehle(db, "anzeigen") == 0


def test_unicode_ziffern_im_text_werden_gelesen_und_kontaktdaten_bleiben_draussen(cfg, db):
    i = lese_text(KA_URL, "Hymer B 544\n２４.９００ € VB\nEZ ２０１９, ８５.０００ km\nTel ０１７６ ９９８８７７６", None, JETZT).inserate[0]
    assert (i.preis, i.ez_jahr, i.km) == (24900, 2019, 85000) and "9988776" not in str(i)


# ---------------------------------------------------------------- M5 nur leere Felder
def test_text_import_ueberschreibt_vorhandene_felder_nicht(cfg, db, ads, importiert):
    a = ads[3]
    ad_id = a["id"]
    vorher = dict(zeile(db, ad_id))
    assert vorher["beschreibung"] and vorher["titel"] and vorher["marke"] and vorher["detail_geladen"] == 1
    url = f"https://www.kleinanzeigen.de/s-anzeige/{a['slug']}/{ad_id}-220-1234"
    text = f"Anderer Titel Camper Kastenwagen\n{a['preis'] - 1000} € VB\nEZ 01/2001\n11.111 km\n99999 Fernort\nKurzer Text."
    lesung, stat = speichere(cfg, db, url=url, text=text)
    assert lesung.nur_leere_felder is True
    assert stat["neu"] == 0 and stat["preis"] == 1                           # die Preissenkung wird weiter erkannt
    nachher = dict(zeile(db, ad_id))
    for feld in ("titel", "beschreibung", "marke", "km", "ez_jahr", "ort", "url", "details_json", "kurzbeschreibung", "detail_geladen", "art", "suche"):
        assert nachher[feld] == vorher[feld], feld
    assert nachher["preis"] == a["preis"] - 1000 and nachher["preis_vorher"] == a["preis"]
    historie = [r[0] for r in db.con.execute(
        "SELECT p.preis FROM preis_historie p JOIN inserate i ON i.id=p.inserat_id WHERE i.anzeigen_id=? ORDER BY p.id", (ad_id,))]
    assert historie[-2:] == [a["preis"], a["preis"] - 1000]


def test_text_import_fuellt_leere_felder_und_ersatztitel(cfg, db, ads, importiert):
    """Geschützte Zeile (Suchlauf): nur Leeres wird gefüllt."""
    a = ads[4]
    db.con.execute("UPDATE anzeigen SET km=NULL, ort=NULL, titel='Anzeige 1 (Titel fehlt)' WHERE id=?", (a["id"],))
    db.con.commit()
    vorher = dict(zeile(db, a["id"]))
    url = f"https://www.kleinanzeigen.de/s-anzeige/{a['slug']}/{a['id']}-220-1234"
    speichere(cfg, db, url=url, text="Hymer Neuer Titel Teilintegrierter\n24.900 € VB\nEZ 01/2001\n11.111 km\n99999 Fernort")
    z = dict(zeile(db, a["id"]))
    assert (z["titel"], z["km"], z["ort"]) == ("Hymer Neuer Titel Teilintegrierter", 11111, "99999 Fernort")
    assert z["ez_jahr"] == vorher["ez_jahr"] and z["marke"] == vorher["marke"] and z["beschreibung"] == vorher["beschreibung"]


def test_andere_kanaele_ueberschreiben_weiter(cfg, db, ads):
    """Gegenprobe: ohne nur_leere_felder (gespeicherte Seite, Suchlauf) gilt wie bisher der neue Wert."""
    from wmscout.eingang import Rohdaten, SeitenEingang
    from wmscout.importer import Importer
    from tests.test_seitenimport import detailseite
    imp = Importer(cfg, db)
    imp.importiere(SeitenEingang().lese(Rohdaten(detailseite(ads[0]).encode(), "d.html", JETZT)), "manuell")
    db.con.execute("UPDATE anzeigen SET titel='Alt', km=1 WHERE id=?", (ads[0]["id"],))
    db.con.commit()
    imp.importiere(SeitenEingang().lese(Rohdaten(detailseite(ads[0]).encode(), "d.html", JETZT)), "manuell")
    z = zeile(db, ads[0]["id"])
    assert z["titel"] != "Alt" and z["km"] != 1


# ---------------------------------------------------------------- N: API-Randfälle
def test_api_ungueltige_typen_und_zeichen_geben_400(server, team, db):
    ben = anmelden(server, "Ben")
    for anbieter in (["privat"], {"a": 1}, 5, True):
        assert post(ben, url=KA_URL, text="Hymer", anbieter=anbieter)[0] == 400, anbieter
    for url, text in ((KA_URL, "Hymer \ud800 Wohnmobil"), ("https://www.kleinanzeigen.de/s-anzeige/x/\ud800", "Hymer")):
        status, antwort, _ = post(ben, url=url, text=text)
        assert status == 400 and "ungültige Zeichen" in antwort["fehler"]
    assert zeile(db, "2987654321") is None


def test_riesenzahlen_geben_keine_python_interna(server, team, db):
    ben = anmelden(server, "Ben")
    for text in ("Hymer B 544\n" + "9" * 5000 + " €", "Hymer B 544\n" + "1" * 5000 + " km\nEZ 2019", "Hymer B 544\nKilometerstand " + "7" * 5000 + " km"):
        status, antwort, _ = post(ben, url=KA_URL, text=text)
        assert status in (200, 422) and "limit" not in str(antwort).lower() and "digits" not in str(antwort).lower(), text[:30]
    assert lese_text(KA_URL, "Hymer\n" + "9" * 5000 + " €", None, JETZT).inserate[0].preis is None


def test_api_gibt_den_gespeicherten_anbieter_zurueck(server, team, db):
    ben = anmelden(server, "Ben")
    text = "Hymer B 544 Teilintegrierter\n24.900 €" + FELDER
    status, erst, _ = post(ben, url=KA_URL, text=text, anbieter="gewerblich")
    assert status == 200 and erst["erkannt"]["gewerblich"] is True
    status, zweit, _ = post(ben, url=KA_URL, text=text, anbieter="privat")
    assert status == 200 and zweit["erkannt"]["gewerblich"] is True
    assert any("Früher als gewerblich erkannt – Angabe „privat“ nicht übernommen" in h for h in zweit["hinweise"])
    assert zeile(db, "2987654321")["gewerblich"] == 1


def test_api_hinweis_wenn_vorhandene_angaben_bleiben(server, team, db, ads):
    ben = anmelden(server, "Ben")
    a = ads[5]
    vorher = dict(zeile(db, a["id"]))
    url = f"https://www.kleinanzeigen.de/s-anzeige/{a['slug']}/{a['id']}-220-1234"
    text = f"{a['marke']} Anderer Titel\n{a['preis'] - 1000} € VB\nEZ 03/2001\n99.000 km\n12345 Ort"
    status, antwort, _ = post(ben, url=url, text=text)
    assert status == 200 and antwort["ergebnis"] == "preis" and antwort["erkannt"]["km"] == vorher["km"]
    assert antwort["erkannt"]["preis"] == a["preis"] - 1000
    assert any("bleiben bestehen" in h for h in antwort["hinweise"])


def test_adresse_unsichtbare_zeichen_und_schlusspunkt():
    for url in (KA_URL + "​", "​" + KA_URL + " ", KA_URL.replace("kleinanzeigen.de", "kleinanzeigen.de."), KA_URL + "﻿",
                "https://www.kleinanzeigen.de​/s-anzeige/x/2987654321-220-1234"):
        adresse, grund = pruefe_adresse(url)
        assert adresse is not None and adresse.anzeigen_id == "2987654321", (url, grund)
    assert pruefe_adresse(MD_URL.replace("mobile.de", "mobile.de."))[0].anzeigen_id == "md-3900000010"
    assert pruefe_adresse("https://suchen.mobile.de/auto-inserat/knaus-boxstar/3900000010.html")[0] is None          # Form unbelegt: nicht erraten


def test_api_schalter_nutzt_den_zentralen_pruefer(cfg, server, team, db):
    ben = anmelden(server, "Ben")
    cfg["eingaenge"] = {"text": {"aktiv": False}}
    status, antwort, _ = post(ben, url=KA_URL, text="Hymer")
    assert status == 409 and antwort["grund"] == "deaktiviert" and "abgeschaltet" in antwort["fehler"] and zeile(db, "2987654321") is None
