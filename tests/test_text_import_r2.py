"""P2-05, zweite Korrekturrunde: kein Preis aus dem Fließtext (nur sicher erkannt oder vom Nutzer eingetragen, ADR-038), Tausenderleerzeichen,
Herkunft der Werte (Text über Text darf ersetzen, andere Kanäle bleiben geschützt), Kontakt-Namen, Einheiten hinter Labels, Preisänderung in der
Antwort und weitere Gesuch-Formen.

Grenze: nachgebaute Texte; echte kopierte Anzeigen können anders aufgebaut sein.
"""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_seitenimport import detailseite
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from tests.test_text_import import JETZT, KA_URL, post, speichere, zeile
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.rechner import Rechner
from wmscout.eingang import Rohdaten, SeitenEingang, bereinige, lese_text, widerspricht_marke
from wmscout.importer import Importer

FELDER = "\nEZ 03/2015\n80.000 km\n12345 Ort"
BASIS = Path(__file__).resolve().parent.parent
FLIESSTEXT_BETRAEGE = [
    "Motor bei 2.500 € überholt", "Restschuld 15.000 € bei der Bank", "Damals für 89.000 € gekauft", "UVP 79.900 €", "Marktwert 35.000 €",
    "Händler bietet 18.000 €", "Rechnungen über 12.000 € vorhanden", "Getriebe für 3.500 € überholt", "Neue Markise 2.300 €.",
    "Wir verkaufen für 24.900 € wegen Hausbau", "Verkaufe für 24.900 €", "Schmerzgrenze 22.000 €",
]


def url_von(a):
    return f"https://www.kleinanzeigen.de/s-anzeige/{a['slug']}/{a['id']}-220-1234"


# ---------------------------------------------------------------- R2-K1 kein Preis aus dem Fließtext
@pytest.mark.parametrize("satz", FLIESSTEXT_BETRAEGE)
def test_betrag_im_fliesstext_ist_nie_der_preis(satz):
    lesung = lese_text(KA_URL, "Hymer B 544 Teilintegrierter\n" + satz + FELDER, None, JETZT)
    assert lesung.inserate[0].preis is None and lesung.preis_status == "unsicher"
    assert any("Preis nicht sicher erkannt (Beträge im Text:" in h and "bitte Preis im Formular eintragen und erneut einlesen" in h for h in lesung.hinweise)


@pytest.mark.parametrize("satz", FLIESSTEXT_BETRAEGE)
def test_gecrawlter_preis_und_nachfass_bleiben_unberuehrt(cfg, db, ads, importiert, satz):
    a = ads[6]
    db.setze_status(a["id"], "kontaktiert", text="Hallo, ich biete Ihnen 14.000 € an", betrag=14000)
    vorher = dict(zeile(db, a["id"]))
    lesung, stat = speichere(cfg, db, url=url_von(a), text=f"{a['marke']} Wohnmobil\n{satz}\nEZ 2010")
    assert stat["preis"] == 0 and stat["neu"] == 0
    nachher = dict(zeile(db, a["id"]))
    for feld in ("preis", "preis_vorher", "preis_geaendert_am", "status", "angebot_betrag"):
        assert nachher[feld] == vorher[feld], feld
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == a["id"])
    assert z["a"]["preis"] == a["preis"] and "neuen Preis" not in (z.get("nachfass_text") or "")


def test_restschuld_wird_nie_zum_erstangebot(cfg, db):
    speichere(cfg, db, text="Hymer B 544 Teilintegrierter\nRestschuld 15.000 € bei der Bank" + FELDER)
    z = dict(zeile(db, "2987654321"))
    b = Rechner(cfg).bewerte(z, [])
    assert z["preis"] is None and b.ampel != "gruen" and b.erstangebot != 14400


def test_nutzerpreis_wird_gespeichert_und_erzeugt_preissenkung(server, team, db, ads):
    ben = anmelden(server, "Ben")
    a = ads[7]
    vorher = zeile(db, a["id"])["preis"]
    status, antwort, _ = post(ben, url=url_von(a), text=f"{a['marke']} Wohnmobil\nMotor bei 2.500 € überholt", preis=vorher - 1500, vb=True)
    assert status == 200 and antwort["ergebnis"] == "preis" and antwort["preis_status"] == "eingetragen"
    assert antwort["preis_vorher"] == vorher and antwort["preis_aenderung"] == "gesenkt"
    assert antwort["erkannt"]["preis"] == vorher - 1500 and antwort["erkannt"]["vb"] is True
    z = zeile(db, a["id"])
    assert (z["preis"], z["preis_vorher"], z["vb"]) == (vorher - 1500, vorher, 1)
    status, antwort, _ = post(ben, url=url_von(a), text=f"{a['marke']} Wohnmobil", preis=vorher + 500)
    assert status == 200 and antwort["ergebnis"] == "bekannt" and antwort["preis_aenderung"] == "gestiegen"
    assert antwort["preis_vorher"] == vorher - 1500 and antwort["erkannt"]["preis"] == vorher + 500


def test_ohne_sicheren_preis_wird_ohne_preis_gespeichert_und_nachgetragen(server, team, db):
    ben = anmelden(server, "Ben")
    text = "Hymer B 544 Teilintegrierter\nMotor bei 2.500 € überholt" + FELDER
    status, erst, _ = post(ben, url=KA_URL, text=text)
    assert status == 200 and erst["ergebnis"] == "neu" and erst["preis_status"] == "unsicher" and erst["erkannt"]["preis"] is None
    assert erst["preis_aenderung"] is None and zeile(db, "2987654321")["preis"] is None
    assert any("bitte Preis im Formular eintragen" in h for h in erst["hinweise"])
    status, zweit, _ = post(ben, url=KA_URL, text=text, preis=24900, vb=False)           # nur den Preis ergänzt, alles andere gleich
    assert status == 200 and zweit["preis_status"] == "eingetragen" and zweit["erkannt"]["preis"] == 24900
    assert zeile(db, "2987654321")["preis"] == 24900


def test_nutzerpreis_hat_vorrang_und_abweichung_wird_gemeldet():
    lesung = lese_text(KA_URL, "Hymer B 544\n24.900 € VB" + FELDER, None, JETZT, 23000, False)
    i = lesung.inserate[0]
    assert (i.preis, i.vb, lesung.preis_status) == (23000, False, "eingetragen")
    assert any("Eingetragener Preis (23.000 €) weicht vom Preis im Text (24.900 €) ab – der eingetragene Preis gilt" in h for h in lesung.hinweise)
    gleich = lese_text(KA_URL, "Hymer B 544\n24.900 € VB" + FELDER, None, JETZT, 24900, True)
    assert not any("weicht" in h for h in gleich.hinweise) and gleich.inserate[0].preis == 24900


@pytest.mark.parametrize("preis, vb", [("24900", None), (True, None), (0, None), (-5, None), (2_000_001, None), (1.5, None), ([1], None), ({"a": 1}, None),
                                       (24900, "ja"), (24900, 1), (None, [True])])
def test_api_preis_und_vb_streng_typgeprueft(server, team, db, preis, vb):
    ben = anmelden(server, "Ben")
    daten = {"url": KA_URL, "text": "Hymer B 544"}
    if preis is not None:
        daten["preis"] = preis
    if vb is not None:
        daten["vb"] = vb
    assert ben("POST", "/api/import/text", daten)[0] == 400
    assert zeile(db, "2987654321") is None
    assert ben("POST", "/api/import/text", {"url": KA_URL, "text": "Hymer B 544", "preis": None, "vb": None})[0] == 200


def test_kandidatenliste_im_hinweis_ohne_jahreszahlen():
    lesung = lese_text(KA_URL, "Hymer B 544 Teilintegrierter\nBj. 2019, VB 2019\nMarkise 2.500 €\nBaujahr 2018" + FELDER, None, JETZT)
    hinweis = next(h for h in lesung.hinweise if h.startswith("Preis nicht sicher erkannt"))
    assert "2.500 €" in hinweis and "2.019" not in hinweis and "2019" not in hinweis


# ---------------------------------------------------------------- R2-H1 Tausendertrennung mit Leerzeichen
@pytest.mark.parametrize("sep", [" ", " ", " "])
@pytest.mark.parametrize("zeile_", ["{} € VB", "Preis: {} € VB", "Preis {} €", "VB {}", "{} € VB, Verhandlung möglich"])
def test_tausenderleerzeichen_ergibt_den_ganzen_preis(sep, zeile_):
    wert = "24" + sep + "900"
    lesung = lese_text(KA_URL, "Hymer B 544 Teilintegrierter\n" + zeile_.format(wert) + FELDER, None, JETZT)
    assert lesung.inserate[0].preis == 24900, (zeile_, sep)
    assert not any("900 €" in h and "24.900" not in h for h in lesung.hinweise)


@pytest.mark.parametrize("sep", [" ", " ", " "])
def test_tausenderleerzeichen_bei_kilometern(sep):
    assert lese_text(KA_URL, f"Hymer B 544\n24.900 €\nKilometerstand 85{sep}000 km\nEZ 2016", None, JETZT).inserate[0].km == 85000
    assert lese_text(KA_URL, f"Hymer B 544\n24.900 €\n85{sep}000 km\nEZ 2016", None, JETZT).inserate[0].km == 85000


# ---------------------------------------------------------------- R2-N2 Label ohne Einheit
@pytest.mark.parametrize("satz", ["Preis: 85.000 km gelaufen", "Preis: 3500 kg zGG", "Preis: VB 1.000 € unter Schwacke", "VB 2.000 € unter Händlerpreis",
                                  "Preis 2019 neu", "Preis: 2,5 t Achslast", "Preis 1.800 mm Höhe", "VB 130 PS"])
def test_label_mit_einheit_oder_unter_kontext_ist_kein_preis(satz):
    assert lese_text(KA_URL, "Hymer B 544\n" + satz, None, JETZT).inserate[0].preis is None


# ---------------------------------------------------------------- R2-M1 Kontakt
@pytest.mark.parametrize("text, weg", [("Kontakt: Peter Müller", "Müller"), ("Kontakt: Dr. Hans Schulz", "Schulz"),
                                       ("Zeiten flexibel. Kontakt: Anna Berger", "Berger")])
def test_kontakt_mit_namen_wird_entfernt(text, weg):
    sauber, entfernt = bereinige("Hymer B 544\n" + text)
    assert weg not in sauber and entfernt["name"] >= 1


@pytest.mark.parametrize("text", ["Kontakt: nur über Nachricht", "Kontakt bitte per Nachricht", "Kontakt: Nachricht genügt", "Kontakt per WhatsApp"])
def test_kontakt_ohne_namen_bleibt(text):
    assert bereinige("Hymer B 544\n" + text)[0] == "Hymer B 544\n" + text


# ---------------------------------------------------------------- R2-M2 Herkunft der Werte
def test_text_ueber_text_darf_korrigieren(cfg, db):
    speichere(cfg, db, text="Hymer B 544 Teilintegrierter\n24.900 €\nEZ 03/2001\n11.111 km\n11111 Falschort")
    assert db.ist_text_eigen("2987654321") is True
    speichere(cfg, db, text="Hymer B 544 Teilintegrierter korrigiert\n24.900 €\nEZ 03/2015\n85.000 km\n12345 Richtigort")
    z = dict(zeile(db, "2987654321"))
    assert (z["titel"], z["ez_jahr"], z["km"], z["ort"]) == ("Hymer B 544 Teilintegrierter korrigiert", 2015, 85000, "12345 Richtigort")
    assert db.ist_text_eigen("2987654321") is True


def test_seitenimport_und_crawler_bleiben_geschuetzt(cfg, db, ads):
    imp = Importer(cfg, db)
    imp.importiere(SeitenEingang().lese(Rohdaten(detailseite(ads[0]).encode(), "d.html", JETZT)), "manuell")
    assert db.ist_text_eigen(ads[0]["id"]) is False
    vorher = dict(zeile(db, ads[0]["id"]))
    speichere(cfg, db, url=url_von(ads[0]), text=f"{ads[0]['marke']} Anderer Titel Camper\nEZ 03/1999\n999 km\n99999 Fernort")
    nachher = dict(zeile(db, ads[0]["id"]))
    for feld in ("titel", "ez_jahr", "km", "beschreibung", "details_json"):
        assert nachher[feld] == vorher[feld], feld
    assert nachher["ort"] == (vorher["ort"] or "99999 Fernort")                    # nur Leeres wird gefüllt
    assert db.ist_text_eigen(ads[0]["id"]) is False


def test_spaetere_andere_kanaele_nehmen_dem_text_den_schutz_weg(cfg, db, ads):
    a = ads[1]
    speichere(cfg, db, url=url_von(a), text=f"{a['marke']} Alter Text\n{a['preis']} € VB\nEZ 03/2001\n11.111 km")
    assert db.ist_text_eigen(a["id"]) is True
    db.speichere_treffer({"id": a["id"], "url": url_von(a), "titel": "Titel vom Suchlauf", "preis": a["preis"], "quelle": "kleinanzeigen"}, "Teilintegrierter")
    assert db.ist_text_eigen(a["id"]) is False
    speichere(cfg, db, url=url_von(a), text=f"{a['marke']} Wieder ein Text\nEZ 03/1990\n222 km")
    z = zeile(db, a["id"])
    assert z["titel"] == "Titel vom Suchlauf" and z["ez_jahr"] == 2001 and z["km"] == 11111


def test_marke_im_text_widerspricht_der_gespeicherten_anzeige(server, team, db, ads):
    ben = anmelden(server, "Ben")
    a = ads[2]
    vorher = zeile(db, a["id"])["preis"]
    andere = "Dethleffs" if a["marke"] != "Dethleffs" else "Hymer"
    text = f"{andere} Trend T 7057\n{vorher - 3000} € VB\nEZ 2016"
    status, antwort, _ = post(ben, url=url_von(a), text=text)
    assert status == 200 and antwort["ergebnis"] == "bekannt" and antwort["preis_status"] == "unsicher"
    assert any(h.startswith("Text passt offenbar nicht zur gespeicherten Anzeige (Marke ") for h in antwort["hinweise"])
    assert zeile(db, a["id"])["preis"] == vorher and antwort["preis_aenderung"] == "unveraendert"
    status, antwort, _ = post(ben, url=url_von(a), text=text, preis=vorher - 3000)               # ausdrücklich eingetragen: gilt
    assert status == 200 and antwort["ergebnis"] == "preis" and zeile(db, a["id"])["preis"] == vorher - 3000


def test_widerspricht_marke_nur_bei_echtem_widerspruch():
    assert widerspricht_marke("Hymer", "Knaus") and widerspricht_marke("hymer", "KNAUS")
    assert not widerspricht_marke("Knaus", "knaus") and not widerspricht_marke("Knaus", "Fiat") and not widerspricht_marke("Fiat", "Knaus")
    assert not widerspricht_marke(None, "Knaus") and not widerspricht_marke("Knaus", None) and not widerspricht_marke("Hymer", "Weitere Marken")


# ---------------------------------------------------------------- R2-N5 Gesuche
@pytest.mark.parametrize("text", ["Wohnmobilankauf", "Wohnmobil kaufen – wir zahlen Höchstpreise", "Wir kaufen Wohnmobile – auch Besitzer mit Kredit",
                                  "Wir kaufen Wohnmobile – auch defekte", "Camperankauf deutschlandweit"])
def test_weitere_gesuch_formen(text):
    assert lese_text(KA_URL, text + "\nEZ 2010", None, JETZT).art == "unbekannt"


@pytest.mark.parametrize("text", ["Suche nach Abenteuer? Knaus Sky TI 650", "Pössl Summit 600 – kein Ankauf, Privatverkauf",
                                  "Hymer B 544 sucht neuen Besitzer", "Wohnmobil Ankaufstest bestanden, Hymer B 544"])
def test_verkaufsanzeigen_mit_gesuchsvokabeln_bleiben(text):
    assert lese_text(KA_URL, text + "\nEZ 2010", None, JETZT).art == "detail"
