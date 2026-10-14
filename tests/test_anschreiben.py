"""Anschreiben: Anrede mit Profilnamen, Marke/Modell höchstens einmal, keine unbestätigte Fahrzeugart im Brief (QA H2/H3)
und vorsichtige Rechnung bei unbekannter Art (Vorstufe auswertung.fuer_rechner/bewerte_anzeige, Rechner unverändert;
QA H3, H6-1, M6-1)."""
import copy
import json
from datetime import date

import pytest

from tests.daten import BASIS, lade_cfg
from wmscout.bewertung.anschreiben import (HINWEIS_ART_UNBEKANNT, HINWEIS_ART_VORLAEUFIG, Anschreiber, anrede_name,
                                           hinweis_art_unbekannt, hinweise, kontext)
from wmscout.bewertung.auswertung import bewerte_alle, bewerte_anzeige, fuer_rechner, kandidaten_arten, vergleichsbasis
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import IMPORT_SUCHE
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.normalisierung.person import profilname

CFG = lade_cfg()
EZ = date.today().year - 9
ARTWOERTER = ("Kastenwagen", "Teilintegrierte", "Integrierte", "Alkoven", "Wohnwagen")
EVEREST = "Everest Minicamp, Camper, Wohnwagen, Motocrosshänger"          # echter Titel aus dem QA-Befund H3

WW_HINWEIS = "Fahrzeugart unbekannt (vorsichtig gerechnet als Wohnwagen; Ampel höchstens gelb, Brief ohne Betrag) – bitte prüfen"


def knaus(**extra) -> dict:
    return ergaenze_fahrzeug({"id": "k", "suche": "Teilintegrierter", "titel": "Knaus Sky TI 650 MEG Platinum", "ez_jahr": EZ,
                              "km": 85000, "preis": 52000, "vb": True, "ort": "70173 Stuttgart",
                              "beschreibung": "Markise, Rückfahrkamera, Scheckheft", **extra})


def brief(a: dict, vergleich=()) -> str:
    cfg = copy.deepcopy(CFG)
    return Anschreiber(cfg, BASIS).text(a, Rechner(cfg).bewerte(fuer_rechner(a), [fuer_rechner(v) for v in vergleich]))


def mit_name(roh) -> dict:
    return {"details_json": json.dumps({"verkaeufer_name": roh})}


# ---------- Anrede (QA H2) ----------
@pytest.mark.parametrize("roh, erwartet", [
    ("anton", "Anton"),                          # einzelnes kleingeschriebenes Wort → großer Anfangsbuchstabe
    ("anna-lena", "Anna-Lena"),
    ("Hr Beispiel", "Herr Beispiel"), ("Hr. Beispiel", "Herr Beispiel"), ("hr beispiel", "Herr Beispiel"),
    ("fr-meier", "Frau Meier"), ("Fr.-Meier", "Frau Meier"), ("fam-muster", "Familie Muster"),   # QA N6-1, nicht „Frau -Meier“
    ("fam. muster", "Familie Muster"), ("José García", "José García"), ("O'Brien", "O'Brien"), ("O’Brien", "O’Brien"),
    ("Mu\u0308ller", "Müller"),                   # zerlegter Umlaut (NFD) → NFC
    ("Fr Meier", "Frau Meier"), ("Fr. Meier", "Frau Meier"), ("fam. schmidt", "Familie Schmidt"),
    ("Herr Müller", "Herr Müller"), ("Familie Schmidt", "Familie Schmidt"), ("Max Muster", "Max Muster"),
    ("max muster", "max muster"),                # mehrere Wörter: unverändert (kein Raten)
    ("ANTON", "ANTON"),                          # unverändert
    ("Frank", "Frank"), ("Herrmann", "Herrmann"),  # „Fr“/„Herr“ nur als eigenes Wort
    ("  anton  ", "Anton"),
])
def test_anrede_name_normalisierung(roh, erwartet):
    assert anrede_name(roh) == erwartet


@pytest.mark.parametrize("roh", [
    None, "", "HW", "Privater Nutzer", "Herr", "Fr.", "Familie", "fr-", "camper77", 42, "a" * 60,
    # QA N6-2: Anrede-/Füllwörter statt Name
    "Hallo Herr", "Hallo", "Moin Moin", "Kaufe Wohnmobile sofort", "Telefon nur abends", "Verkauf privat", "Womo-Verkauf",
    "Grüße Max", "Handy bitte",
    # QA N6-2: Zeichen außerhalb der Whitelist (Bidi-, Zero-Width-, Steuerzeichen, Markup, Sonderzeichen)
    "\u202eMax", "Max\u202c", "Max\u200bMuster", "\ufeffAnna", "Max\x00", "Max\x1b[31m", "<img src=x onerror=alert(1)>",
    "<b>Max</b>", "{Max}", "{{ firma }}", "Max & Anna", "Max!", "Max😀", "Max, Anna", "Max_Muster", "Max/Anna",
])
def test_anrede_name_ohne_brauchbaren_namen(roh):
    assert anrede_name(roh) is None


def test_profilname_whitelist_laesst_echte_namen_durch():
    """Gegenprobe zu N6-2: Buchstaben mit Umlauten/Akzenten, Leerzeichen, „-“, „.“, „'“ bleiben; „Nur“ ist ein Vorname."""
    for name in ("Max Müller", "José García", "Anne-Marie", "O'Brien", "Hr. Beispiel", "Nur Yilmaz", "Ölçer", "Familie Schmidt",
                 "Herr Kaufmann", "Frau Hey", "Familie Handel", "Tobias Morgen", "Verena Kaufhold"):
        assert profilname(name) == name, name
    assert profilname("Max\u00a0Muster") == profilname("Max\tMuster") == "Max Muster"     # Leerraum wird vereinheitlicht


def test_anrede_im_brief_mit_und_ohne_name():
    assert brief(knaus(**mit_name("anton"))).startswith("Hallo Anton,\n\nich habe Ihr Inserat")
    assert brief(knaus(**mit_name("Hr Beispiel"))).startswith("Hallo Herr Beispiel,\n")
    assert brief(knaus()).startswith("Hallo,\n\nich habe Ihr Inserat")
    for kaputt in (None, "", "kein json", "[1]", "5", "null", '{"verkaeufer_name": null}', '{"verkaeufer_name": "HW"}',
                   '{"verkaeufer_name": ["Max"]}', '{"Art": "Alkoven"}'):
        a = {**knaus(), "details_json": kaputt}          # nach ergaenze_fahrzeug: das verträgt selbst kein Nicht-Objekt-JSON
        assert brief(a).startswith("Hallo,\n"), kaputt
        assert kontext(a, None, CFG)["name"] is None and kontext(a, None, CFG)["anrede"] == "Hallo,", kaputt


def test_anrede_im_nachfass_text():
    cfg = copy.deepcopy(CFG)
    a = knaus(**mit_name("Fr. Meier"), status="kontaktiert", kontaktiert_am="2026-10-01T10:00:00")
    text, _ = Anschreiber(cfg, BASIS).nachfass(a, Rechner(cfg).bewerte(a, []))
    assert text.startswith("Hallo Frau Meier,\n\nich hatte Ihnen am 01.10. wegen Ihres Inserats zum Knaus Sky TI 650 MEG")
    text, _ = Anschreiber(cfg, BASIS).nachfass({**a, "details_json": "{"}, Rechner(cfg).bewerte(a, []))
    assert text.startswith("Hallo,\n")


def test_nachfass_ohne_marke_und_modell_zu_ihrem_wohnmobil():
    """Ohne Marke/Modell heißt es „zu Ihrem Wohnmobil“, nicht „zum Wohnmobil“ (Vorlage nutzt zum_fahrzeug)."""
    cfg = copy.deepcopy(CFG)
    a = ergaenze_fahrzeug({"id": "o", "suche": "Sonstige", "titel": "Wohnmobil zu verkaufen", "ez_jahr": EZ, "km": 90000,
                           "preis": 40000, "ort": "70173 Stuttgart", "status": "kontaktiert", "kontaktiert_am": "2026-10-01T10:00:00"})
    assert not a["marke"] and not a["modell"]
    text, _ = Anschreiber(cfg, BASIS).nachfass(a, Rechner(cfg).bewerte(a, []))
    assert f"ich hatte Ihnen am 01.10. wegen Ihres Inserats zu Ihrem Wohnmobil (EZ {EZ}) geschrieben." in text
    assert "zum Wohnmobil" not in text


def test_nachfass_angebot_steht_mit_leerzeile_vor_dem_schluss():
    """QA N6-5: Im Fall „steht“ fehlte die Leerzeile vor „Wenn es für Sie passt“ (Zeilenumbruch nach {% endif %} entfernt)."""
    cfg = copy.deepcopy(CFG)
    a = knaus(status="kontaktiert", kontaktiert_am="2026-10-01T10:00:00", angebot_betrag=45000)     # über dem neuen Erstangebot
    for extra in ({}, {"preis": 50000, "preis_geaendert_am": "2026-10-05T10:00:00"}):
        x = {**a, **extra}
        text, betrag = Anschreiber(cfg, BASIS).nachfass(x, Rechner(cfg).bewerte(x, []))
        assert betrag == 45000 and "Mein Angebot über 45.000 €" in text
        assert "steht weiterhin." + (" Vielleicht kommen wir ja zusammen." if extra else "") + "\n\nWenn es für Sie passt:" in text
        assert "\n\n\n" not in text


# ---------- Marke/Modell höchstens einmal ----------
def test_modell_hoechstens_einmal_danach_nur_marke():
    a = knaus()
    assert a["fahrzeug"] == "Knaus Sky TI 650 MEG"
    t = brief(a)
    assert t.count("Sky TI") == 1 and t.count("Knaus Sky TI 650 MEG") == 1          # nur in der Einleitung
    assert f"Ihr Inserat zum Knaus Sky TI 650 MEG (EZ {EZ}, rund 85.000 km)" in t
    assert "Ihr Teilintegrierter von Knaus passt gut zu dem, was unsere Kunden suchen." in t
    assert f"gepflegtes Fahrzeug.\n\nBei einem Wohnmobil aus {EZ}" in t                  # eigener Absatz für die Prüfpunkte
    # Pflichtinhalte bleiben
    for teil in ("gewerblicher Ankäufer (Muster Reisemobile GmbH, Stuttgart)", "Vorbehaltlich einer Besichtigung",
                 "unverbindlich", "Fahrzeugschein", "Viele Grüße\nMax Mustermann", "Markise und Rückfahrkamera"):
        assert teil in t, teil


def test_ohne_marke_und_modell_neutral_oder_bestaetigte_art():
    ohne = ergaenze_fahrzeug({"id": "o", "suche": "Teilintegrierter", "titel": "Wohnmobil zu verkaufen", "ez_jahr": EZ,
                              "km": 90000, "preis": 40000, "ort": "70173 Stuttgart"})
    assert not ohne["marke"] and not ohne["modell"]
    t = brief(ohne)                                                         # Crawler-Fund: Art aus der Suche gilt
    assert "Ihr Inserat zu Ihrem Teilintegrierten (EZ" in t and "Ihr Teilintegrierter passt gut" in t
    t = brief({**ohne, "suche": "Sonstige"})
    assert "Ihr Inserat zu Ihrem Wohnmobil (EZ" in t and "Ihr Wohnmobil passt gut" in t


@pytest.mark.parametrize("titel, suche, erwartet", [
    ("Hobby 440 SF De Luxe", "Wohnwagen", "Ihr Wohnwagen von Hobby passt gut"),          # nicht „Ihr Hobby passt gut“
    ("Hobby 440 SF De Luxe", IMPORT_SUCHE, "Ihr Wohnmobil von Hobby passt gut"),         # Art unbekannt → neutral
    ("Fiat Ducato Wohnmobil", "Sonstige", "Ihr Wohnmobil von Fiat passt gut"),           # Basismarke: nicht „Ihr Fiat“
    ("Knaus Sky TI 650 MEG", "Teilintegrierter", "Ihr Teilintegrierter von Knaus passt gut"),
])
def test_ihr_fahrzeug_markenneutral(titel, suche, erwartet):
    """QA N6-3: „Ihr <Marke> passt gut …“ ist doppeldeutig („Ihr Hobby“) bzw. meint das Basisfahrzeug („Ihr Fiat“);
    einheitlich für alle Marken heißt es „Ihr <Art> von <Marke>“, ohne bestätigte Art „Ihr Wohnmobil von <Marke>“."""
    a = ergaenze_fahrzeug({"id": "m", "suche": suche, "titel": titel, "ez_jahr": EZ, "km": 90000, "preis": 20000,
                           "ort": "70173 Stuttgart"})
    t = brief(a)
    assert erwartet in t
    assert f"Ihr {a['marke']} " not in t and f"Ihr {a['marke']}," not in t


# ---------- Keine unbestätigte Fahrzeugart im Brief (QA H3, Text) ----------
def kastenwagen(i: int, suche: str) -> dict:
    return ergaenze_fahrzeug({"id": f"kw{i}", "suche": suche, "titel": "Kastenwagen gepflegt", "ez_jahr": EZ + i % 3 - 1,
                              "km": 80000 + i % 6 * 2000, "preis": 30000 + i % 6 * 500, "ort": "70173 Stuttgart",
                              "zuletzt_gesehen": "2999"})


@pytest.mark.parametrize("suche", ["Import Kastenwagen (vorläufig)", "Import Kastenwagen", IMPORT_SUCHE])
def test_keine_art_im_brief_bei_vorlaeufig_oder_unbekannt(suche):
    vergleich = [kastenwagen(i, suche) for i in range(6)]
    a = kastenwagen(99, suche)
    assert not a["marke"]
    b = Rechner(copy.deepcopy(CFG)).bewerte(fuer_rechner(a), [fuer_rechner(v) for v in vergleich])
    assert b.vergleich_anzahl > 0                                           # Preisbasis „an vergleichbaren Angeboten (…)“
    assert b.art == ("Sonstige" if suche == IMPORT_SUCHE else "Kastenwagen")  # vorläufig: gerechnet wird mit der Art
    t = Anschreiber(copy.deepcopy(CFG), BASIS).text(a, b)
    for wort in ARTWOERTER:
        assert wort not in t, (suche, wort)
    assert "Ihr Inserat zu Ihrem Wohnmobil (EZ" in t and "Ihr Wohnmobil passt gut" in t
    if suche == IMPORT_SUCHE:                                                   # F14: unbekannte Art → Brief ohne Betrag
        assert "€ an" not in t and "(Wohnmobile der Baujahre" not in t and "konkretes Angebot" in t
    else:
        assert "(Wohnmobile der Baujahre" in t


def test_bestaetigte_art_steht_im_brief():
    """Gegenprobe zum Test davor: dieselben Daten mit bestätigter Art nennen die Art."""
    suche = "Import Kastenwagen (bestätigt)"
    t = brief(kastenwagen(99, suche), [kastenwagen(i, suche) for i in range(6)])
    assert "Ihr Inserat zu Ihrem Kastenwagen (EZ" in t and "(Kastenwagen der Baujahre" in t


# ---------- Rechnung bei unbekannter Art (QA H3, Rechnung) ----------
def everest(suche=IMPORT_SUCHE, **extra) -> dict:
    return {"id": "ev", "suche": suche, "titel": EVEREST, "ez_jahr": date.today().year - 10, "km": 100000, "preis": 30000,
            **extra}


def test_unbekannte_art_rechnet_als_sonstige_nicht_nach_titel():
    """Rechenweg (config.yaml → rechner.marktmodell): Alter 10 J. → Restwert 0,52; km 100.000 = 10 J. × 10.000 üblich →
    km-Korrektur 0; Marke unbekannt → Faktor 1,0; keine Wertfaktoren.
      Titel-Art (alt):   „camper“ → Kastenwagen: 62.000 × 0,52 = 32.240 → gerundet auf 50 € = 32.250
      Vorstufe (neu):    Sonstige:               65.000 × 0,52 = 33.800"""
    a = everest()
    alt = Rechner(copy.deepcopy(CFG)).bewerte(a, [])                       # Rechner direkt: erster Art-Begriff im Titel
    assert alt.art == "Kastenwagen" and alt.modellwert == 32250
    neu = Rechner(copy.deepcopy(CFG)).bewerte(fuer_rechner(a), [])
    assert neu.art == "Sonstige" and neu.modellwert == 33800 and neu.wertfaktoren == {}
    assert a["titel"] == EVEREST and a["suche"] == IMPORT_SUCHE            # Original bleibt unverändert (Anzeige im Report)
    # unbekannte Art auch bei Detailangabe „Art“ außerhalb der bekannten Arten
    assert Rechner(copy.deepcopy(CFG)).bewerte(fuer_rechner(everest("Import Quatsch (bestätigt)", art="Kastenwagen")), []).art == "Sonstige"


def test_vorstufe_laesst_vorlaeufige_und_crawler_arten_unveraendert():
    for suche in ("Import Kastenwagen (vorläufig)", "Import Kastenwagen", "Import Kastenwagen (bestätigt)", "Kastenwagen", None):
        a = everest(suche)
        assert fuer_rechner(a) is a, suche
    assert Rechner(copy.deepcopy(CFG)).bewerte(fuer_rechner(everest("Import Alkoven (vorläufig)")), []).art == "Alkoven"


def test_vorstufe_behaelt_wertfaktoren_aus_dem_titel():
    """Ausstattung/Mängel im Titel zählen weiter, obwohl der Titel für die Art nicht mehr herangezogen wird."""
    a = everest(titel="Camper mit Markise und Solar, Feuchtigkeit im Heck", kurzbeschreibung="Rückfahrkamera")
    r = Rechner(copy.deepcopy(CFG))
    assert set(r.wertfaktoren(fuer_rechner(a))) == set(r.wertfaktoren(a)) == {"Markise", "Solaranlage", "Rückfahrkamera",
                                                                              "Feuchtigkeit"}


def test_hinweistext_nennt_womit_gerechnet_wurde():
    assert HINWEIS_ART_UNBEKANNT == "Fahrzeugart unbekannt (gerechnet ohne Art; Ampel höchstens gelb, Brief ohne Betrag) – bitte prüfen"
    assert HINWEIS_ART_VORLAEUFIG == "Fahrzeugart nicht bestätigt (gerechnet mit der vorläufigen Art) – bitte prüfen"
    assert hinweise(everest()) == [HINWEIS_ART_UNBEKANNT]
    assert hinweise(everest("Import Kastenwagen (vorläufig)")) == [HINWEIS_ART_VORLAEUFIG]


def test_bewerte_alle_rechnet_unbekannt_vorsichtig_und_schreibt_neutral(cfg, db):
    """Ende zu Ende über die Datenbank: Everest (unbekannt) → vorsichtig als Wohnwagen (niedrigster Max-EK der
    Kandidaten ohne Art, Kastenwagen, Wohnwagen), Kastenwagen (vorläufig) → Kastenwagen; beide mit Hinweis, Brief ohne
    Art, Anrede aus dem Profilnamen.
    Rechenweg Everest (Alter 10 J. → Restwert 0,52; km-Korrektur 0; keine Marke, keine Wertfaktoren):
      ohne Art:     65.000 × 0,52 = 33.800, kein Vergleich (kw1 ist Kastenwagen)
      Kastenwagen:  62.000 × 0,52 = 32.240; 1 Vergleich kw1: 30.000 / 32.240 = 0,9305; Gewicht 1/(1+4) = 0,2
                    → Faktor 0,2 × 0,9305 + 0,8 = 0,9861 → 31.792 → 31.800
      Wohnwagen:    30.000 × 0,52 = 15.600, kein Vergleich → niedrigster Marktwert und damit niedrigster Max-EK"""
    jahr = date.today().year - 10
    db.speichere_treffer({"id": "ev1", "titel": EVEREST, "preis": 30000, "km": 100000, "ez_jahr": jahr, "ort": "70173 Stuttgart"},
                         IMPORT_SUCHE)
    db.speichere_details("ev1", {"details": {"verkaeufer_name": "hr beispiel"}})
    db.speichere_treffer({"id": "kw1", "titel": "Kastenwagen gepflegt", "preis": 30000, "km": 100000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Import Kastenwagen (vorläufig)")
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    ev, kw = zeilen["ev1"], zeilen["kw1"]
    assert ev["b"].art == "Wohnwagen" and ev["b"].marktwert_angebote == 15600 and ev["b"].vergleich_anzahl == 0
    assert ev["hinweise"] == [WW_HINWEIS] and ev["a"]["titel"] == EVEREST
    assert "niedrigster Max-EK aus ohne Art, Kastenwagen, Wohnwagen" in ev["b"].vergleich_basis
    assert kw["b"].art == "Kastenwagen" and kw["hinweise"] == [HINWEIS_ART_VORLAEUFIG]
    assert ev["sperre"] is None and kw["sperre"] is None
    assert ev["brief"].startswith("Hallo Herr Beispiel,\n") and kw["brief"].startswith("Hallo,\n")
    for z in (ev, kw):
        for wort in ARTWOERTER:
            assert wort not in z["brief"], (z["a"]["id"], wort)


# ---------- Vorsichtige Rechnung bei unbekannter Art (QA H6-1) ----------
def imp(i, titel, preis, suche=IMPORT_SUCHE) -> dict:
    """Anzeige ohne Marke, 10 Jahre alt, 100.000 km (km-Korrektur 0, Restwert 0,52), frisch gesehen (volles Gewicht)."""
    return ergaenze_fahrzeug({"id": f"i{i}", "suche": suche, "titel": titel, "ez_jahr": date.today().year - 10, "km": 100000,
                              "preis": preis, "ort": "70173 Stuttgart", "zuletzt_gesehen": "2999"})


def test_kandidaten_arten():
    assert kandidaten_arten(imp(1, EVEREST, 1)) == ["Sonstige", "Kastenwagen", "Wohnwagen"]
    assert kandidaten_arten(imp(1, "Beispiel 450", 1) | {"kurzbeschreibung": "Verkaufe unseren Wohnwagen"}) == ["Sonstige", "Wohnwagen"]
    assert kandidaten_arten(imp(1, "Beispiel 450", 1)) == ["Sonstige"]
    for suche in ("Import Kastenwagen (vorläufig)", "Import Kastenwagen (bestätigt)", "Kastenwagen", None):
        assert kandidaten_arten(imp(1, EVEREST, 1, suche)) == [], suche          # nur bei UNBEKANNTER Art


def test_unbekannte_art_nimmt_niedrigsten_max_ek_und_sicherheit_hoechstens_niedrig():
    """Nachbau des echten Falls „Wohnwagen .Bürstner premio life …“, 18.500 €, Art unbekannt (QA H6-1): als „Sonstige“
    gerechnet kam Max-EK weit über dem Preis mit Sicherheit „hoch“ heraus (Rang 3 von 51).
    Rechenweg (Alter 10 J. → Restwert 0,52; km-Korrektur 0; keine Marke/Wertfaktoren; Gewicht Markt g = n/(n+4)):
      ohne Art:  Referenz 65.000 × 0,52 = 33.800; 10 Vergleiche „ohne Art“ zu je 33.800 € → Verhältnis 1,0, Streuung 0
                 g = 10/14 = 0,714 → Niveau 33.800; s = 0,286 × 0,15 = 0,043 → Spanne 32.351–35.249 → 32.400–35.200
                 n = 10 ≥ 8 und s ≤ 0,12 → Rechner: Sicherheit „hoch“
      Wohnwagen: Referenz 30.000 × 0,52 = 15.600; 3 Wohnwagen (Crawler) zu je 15.600 € → Verhältnis 1,0
                 g = 3/7 = 0,429 → Niveau 15.600; s = 0,571 × 0,15 = 0,086 → Spanne 14.263–16.937 → 14.300–16.900
      → genommen: Wohnwagen (niedrigerer Max-EK), Sicherheit „niedrig“, Spanne über beide: 14.300–35.200"""
    cfg = copy.deepcopy(CFG)
    alle = ([imp(i, "Beispiel 450", 33800) for i in range(10)] + [imp(20 + i, "Beispiel 450", 15600, "Wohnwagen") for i in range(3)])
    a = imp(99, "Wohnwagen .Beispiel premio life TS", 18500)
    vergleich = vergleichsbasis(alle)
    alt = Rechner(cfg).bewerte(fuer_rechner(a), vergleich)                 # nur „ohne Art“ (Stand vor H6-1)
    assert (alt.art, alt.marktwert_angebote, alt.vergleich_anzahl, alt.sicherheit) == ("Sonstige", 33800, 10, "hoch")
    assert (alt.spanne_von, alt.spanne_bis) == (32400, 35200)
    als_ww = Rechner(cfg).bewerte({**fuer_rechner(a), "art": "Wohnwagen", "id": "x"}, vergleich)
    assert (als_ww.marktwert_angebote, als_ww.vergleich_anzahl, als_ww.spanne_von, als_ww.spanne_bis) == (15600, 3, 14300, 16900)

    b = bewerte_anzeige(Rechner(cfg), a, vergleich)
    assert b.art == "Wohnwagen" and b.max_ek == als_ww.max_ek < alt.max_ek and b.marktwert_angebote == 15600
    assert b.sicherheit == "niedrig"
    assert (b.spanne_von, b.spanne_bis) == (14300, 35200)
    assert b.ampel == als_ww.ampel and b.verhaeltnis == als_ww.verhaeltnis and b.erstangebot == als_ww.erstangebot
    assert hinweise(a, b) == [hinweis_art_unbekannt("Wohnwagen")] == [WW_HINWEIS]
    # Brief: Art weiterhin nicht genannt
    t = Anschreiber(cfg, BASIS).text(a, b)
    for wort in ARTWOERTER:
        assert wort not in t, wort


def test_unbekannte_art_ohne_kandidat_rechnet_ohne_art_mit_niedriger_sicherheit():
    """Kein Art-Begriff im Text → nur „ohne Art“; Max-EK wie bisher, aber Sicherheit höchstens „niedrig“."""
    cfg = copy.deepcopy(CFG)
    vergleich = vergleichsbasis([imp(i, "Beispiel 450", 33800) for i in range(10)])
    a = imp(99, "Beispiel 600 gepflegt", 30000)
    alt = Rechner(cfg).bewerte(fuer_rechner(a), vergleich)
    b = bewerte_anzeige(Rechner(cfg), a, vergleich)
    assert alt.sicherheit == "hoch" and b.sicherheit == "niedrig"
    assert (b.art, b.max_ek, b.erstangebot, b.ampel, b.spanne_von, b.spanne_bis, b.vergleich_basis) == \
        (alt.art, alt.max_ek, alt.erstangebot, alt.ampel, alt.spanne_von, alt.spanne_bis, alt.vergleich_basis)
    assert hinweise(a, b) == [HINWEIS_ART_UNBEKANNT]
    # ohne EZ: „keine“ bleibt „keine“ (kein Angebot), auch mit mehreren Kandidaten
    ohne_ez = {**imp(98, EVEREST, 30000), "ez_jahr": None}
    assert bewerte_anzeige(Rechner(cfg), ohne_ez, vergleich).sicherheit == "keine"
    # bestätigte/vorläufige Arten und Crawler-Funde: unverändert der Rechner
    for suche in ("Import Wohnwagen (bestätigt)", "Import Wohnwagen (vorläufig)", "Wohnwagen"):
        x = imp(97, "Wohnwagen Beispiel", 18500, suche)
        assert bewerte_anzeige(Rechner(cfg), x, vergleich) == Rechner(cfg).bewerte(x, vergleich), suche


def test_unbekannte_importe_vergleichen_sich_in_rechner_sicht(cfg, db):
    """QA M6-1: Zwei unbekannte Importe vergleichen sich in `bewerte_alle` gegenseitig – die Vergleichsliste muss dieselbe
    Sicht haben wie die bewertete Anzeige („ohne Art“), sonst stünde B über „Camper“ im Titel als Kastenwagen darin.
    Rechenweg A (Alter 10 J., Restwert 0,52, km-Korrektur 0; Kandidaten ohne Art und Kastenwagen):
      ohne Art:    Referenz 33.800; Vergleich B (ohne Art): 10.000 / 33.800 = 0,2959; g = 1/5 = 0,2
                   → Faktor 0,2 × 0,2959 + 0,8 = 0,8592 → 29.040 → 29.050
      Kastenwagen: Referenz 62.000 × 0,52 = 32.240, kein Vergleich (B steht „ohne Art“ in der Liste)
      → genommen: ohne Art (niedriger), 1 Vergleich.
    Mit B in Titel-Sicht wäre es umgekehrt: ohne Art 33.800 (kein Vergleich), Kastenwagen mit B → < 32.240."""
    jahr = date.today().year - 10
    for kennung, preis in (("a", 30000), ("b", 10000)):
        db.speichere_treffer({"id": kennung, "titel": "Beispiel Camper 600", "preis": preis, "km": 100000, "ez_jahr": jahr,
                              "ort": "70173 Stuttgart"}, IMPORT_SUCHE)
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}["a"]
    assert (z["b"].art, z["b"].vergleich_anzahl, z["b"].marktwert_angebote) == ("Sonstige", 1, 29050)
    assert z["hinweise"] == [HINWEIS_ART_UNBEKANNT]


def test_f14_unbekannte_art_ampel_hoechstens_gelb_und_brief_ohne_betrag():
    """Betreiberentscheidung F14 (14.10.2026): Wohnwagen ohne Art-Wort im Text werden als „Sonstige“ gerechnet und wären
    sonst grün mit konkretem Betrag. Bei unbekannter Art daher Ampel höchstens „gelb“ und kein Betrag im Brief."""
    cfg = copy.deepcopy(CFG)
    alle = [imp(i, "Beispiel 450", 33800) for i in range(10)]
    a = imp(99, "Beispiel Südwind 580", 12000)                                 # kein Art-Wort, Preis weit unter Markt
    vergleich = vergleichsbasis(alle)
    ohne_deckel = Rechner(cfg).bewerte(fuer_rechner(a), vergleich)
    assert ohne_deckel.ampel == "gruen" and ohne_deckel.erstangebot             # ohne F14 grün mit Angebot
    b = bewerte_anzeige(Rechner(cfg), a, vergleich)
    assert b.ampel == "gelb" and b.max_ek == ohne_deckel.max_ek
    t = Anschreiber(cfg, BASIS).text(a, b)
    assert "€ an" not in t and f"{b.erstangebot:,}".replace(",", ".") not in t and "konkretes Angebot" in t
    assert "Brief ohne Betrag" in hinweise(a, b)[0]
    # Gegenprobe: bestätigte Art bleibt grün und nennt den Betrag
    best = {**a, "suche": "Import Teilintegrierter (bestätigt)", "art": "Teilintegrierter"}
    bb = bewerte_anzeige(Rechner(cfg), best, vergleich)
    tb = Anschreiber(cfg, BASIS).text(best, bb)
    assert bb.ampel == "gruen" and "€ an" in tb


def test_f14_rot_und_grau_bleiben_unveraendert():
    cfg = copy.deepcopy(CFG)
    alle = [imp(i, "Beispiel 450", 33800) for i in range(10)]
    a = imp(99, "Beispiel Südwind 580", 90000)                                  # weit über Markt
    b = bewerte_anzeige(Rechner(cfg), a, vergleichsbasis(alle))
    assert b.ampel == "rot"
