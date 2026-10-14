"""Anschreiben: Anrede mit Profilnamen, Marke/Modell höchstens einmal, keine unbestätigte Fahrzeugart im Brief (QA H2/H3)
und Rechnung mit „Sonstige“ bei unbekannter Art (Vorstufe auswertung.fuer_rechner, Rechner unverändert)."""
import copy
import json
from datetime import date

import pytest

from tests.daten import BASIS, lade_cfg
from wmscout.bewertung.anschreiben import (HINWEIS_ART_UNBEKANNT, HINWEIS_ART_VORLAEUFIG, Anschreiber, anrede_name, hinweise,
                                           kontext)
from wmscout.bewertung.auswertung import bewerte_alle, fuer_rechner
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import IMPORT_SUCHE
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug

CFG = lade_cfg()
EZ = date.today().year - 9
ARTWOERTER = ("Kastenwagen", "Teilintegrierte", "Integrierte", "Alkoven", "Wohnwagen")
EVEREST = "Everest Minicamp, Camper, Wohnwagen, Motocrosshänger"          # echter Titel aus dem QA-Befund H3


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
    ("volker", "Volker"),                        # einzelnes kleingeschriebenes Wort → großer Anfangsbuchstabe
    ("anna-lena", "Anna-Lena"),
    ("Hr Wie", "Herr Wie"), ("Hr. Wie", "Herr Wie"), ("hr wie", "Herr Wie"),
    ("Fr Meier", "Frau Meier"), ("Fr. Meier", "Frau Meier"), ("fam. schmidt", "Familie Schmidt"),
    ("Herr Müller", "Herr Müller"), ("Familie Schmidt", "Familie Schmidt"), ("Max Muster", "Max Muster"),
    ("max muster", "max muster"),                # mehrere Wörter: unverändert (kein Raten)
    ("VOLKER", "VOLKER"),                        # unverändert
    ("Frank", "Frank"), ("Herrmann", "Herrmann"),  # „Fr“/„Herr“ nur als eigenes Wort
    ("  volker  ", "Volker"),
])
def test_anrede_name_normalisierung(roh, erwartet):
    assert anrede_name(roh) == erwartet


@pytest.mark.parametrize("roh", [None, "", "HW", "Privater Nutzer", "Herr", "Fr.", "Familie", "camper77", 42, "a" * 60])
def test_anrede_name_ohne_brauchbaren_namen(roh):
    assert anrede_name(roh) is None


def test_anrede_im_brief_mit_und_ohne_name():
    assert brief(knaus(**mit_name("volker"))).startswith("Hallo Volker,\n\nich habe Ihr Inserat")
    assert brief(knaus(**mit_name("Hr Wie"))).startswith("Hallo Herr Wie,\n")
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


# ---------- Marke/Modell höchstens einmal ----------
def test_modell_hoechstens_einmal_danach_nur_marke():
    a = knaus()
    assert a["fahrzeug"] == "Knaus Sky TI 650 MEG"
    t = brief(a)
    assert t.count("Sky TI") == 1 and t.count("Knaus Sky TI 650 MEG") == 1          # nur in der Einleitung
    assert f"Ihr Inserat zum Knaus Sky TI 650 MEG (EZ {EZ}, rund 85.000 km)" in t
    assert "Ihr Knaus passt gut zu dem, was unsere Kunden suchen." in t
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
    assert HINWEIS_ART_UNBEKANNT == "Fahrzeugart unbekannt (gerechnet ohne Art) – bitte prüfen"
    assert HINWEIS_ART_VORLAEUFIG == "Fahrzeugart nicht bestätigt (gerechnet mit der vorläufigen Art) – bitte prüfen"
    assert hinweise(everest()) == [HINWEIS_ART_UNBEKANNT]
    assert hinweise(everest("Import Kastenwagen (vorläufig)")) == [HINWEIS_ART_VORLAEUFIG]


def test_bewerte_alle_rechnet_unbekannt_als_sonstige_und_schreibt_neutral(cfg, db):
    """Ende zu Ende über die Datenbank: Everest (unbekannt) → Sonstige, Kastenwagen (vorläufig) → Kastenwagen;
    beide mit Hinweis, Brief ohne Art, Anrede aus dem Profilnamen."""
    jahr = date.today().year - 10
    db.speichere_treffer({"id": "ev1", "titel": EVEREST, "preis": 30000, "km": 100000, "ez_jahr": jahr, "ort": "70173 Stuttgart"},
                         IMPORT_SUCHE)
    db.speichere_details("ev1", {"details": {"verkaeufer_name": "hr wie"}})
    db.speichere_treffer({"id": "kw1", "titel": "Kastenwagen gepflegt", "preis": 30000, "km": 100000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Import Kastenwagen (vorläufig)")
    zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    ev, kw = zeilen["ev1"], zeilen["kw1"]
    assert ev["b"].art == "Sonstige" and ev["hinweise"] == [HINWEIS_ART_UNBEKANNT] and ev["a"]["titel"] == EVEREST
    assert kw["b"].art == "Kastenwagen" and kw["hinweise"] == [HINWEIS_ART_VORLAEUFIG]
    assert ev["sperre"] is None and kw["sperre"] is None
    assert ev["brief"].startswith("Hallo Herr Wie,\n") and kw["brief"].startswith("Hallo,\n")
    for z in (ev, kw):
        for wort in ARTWOERTER:
            assert wort not in z["brief"], (z["a"]["id"], wort)
