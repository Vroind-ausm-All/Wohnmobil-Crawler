"""Bestätigte Angaben: Original erhalten, neue Imports sichtbar, Migration und Datenschutz."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from tests.daten import BASIS
from wmscout import datenrechte, feldbestaetigungen as fb, migrationen
from wmscout.bewertung.auswertung import bewerte_alle, vergleichsbasis_aus
from wmscout.datenbank import Datenbank

ANGEBOT = {"id": "12345678", "titel": "Knaus Sky TI 650 MEG Teilintegrierter", "preis": 35000, "km": 70000, "ez_jahr": 2018,
           "url": "https://www.kleinanzeigen.de/s-anzeige/knaus/12345678-220-1", "gewerblich": 0, "anbieter_herkunft": "anzeige",
           "ort": "74321 Bietigheim", "marke": "Knaus"}


@pytest.fixture
def angebot(db):
    db.speichere_treffer(ANGEBOT, "Teilintegrierter")
    return ANGEBOT["id"]


def test_bestaetigung_originalwerte_bleiben_und_rechner_verwendet_bestand(cfg, db, angebot):
    vor = dict(db.con.execute("SELECT * FROM anzeigen WHERE id=?", (angebot,)).fetchone())
    sicht = fb.bestaetigen(db, angebot, {"preis": 32000, "km": 71000, "modell": "Sky TI Sondermodell", "art": "Alkoven"}, 4)
    assert sicht["preis"]["extrahiert"] == 35000 and sicht["preis"]["wert"] == 32000
    assert sicht["preis"]["bestaetigt"] and sicht["preis"]["nutzer_id"] == 4
    assert not sicht["preis"]["konflikt"]
    assert dict(db.con.execute("SELECT * FROM anzeigen WHERE id=?", (angebot,)).fetchone()) == vor
    z = bewerte_alle(cfg, db, BASIS)[0]
    assert z["a"]["preis"] == 32000 and z["a"]["km"] == 71000
    assert z["a"]["modell"] == "Sky TI Sondermodell" and z["a"]["fahrzeug"] == "Knaus Sky TI Sondermodell"
    assert z["b"].art == "Alkoven"
    assert z["a"]["datenherkunft"]["preis"] == sicht["preis"]


def test_neuer_preis_ueberschreibt_nicht_wird_aber_widerspruch(cfg, db, angebot):
    fb.bestaetigen(db, angebot, {"preis": 32000})
    db.speichere_treffer({**ANGEBOT, "preis": 30000}, "Teilintegrierter")
    z = bewerte_alle(cfg, db, BASIS)[0]
    assert z["a"]["preis"] == 32000
    h = z["a"]["datenherkunft"]["preis"]
    assert h["extrahiert"] == 30000 and h["konflikt"] is True
    assert any(m["code"] == "bestaetigung_preis" for m in z["a"]["datenqualitaet"]["markierungen"])
    assert z["ankaufchance"]["belastbar"] is False and z["deal"]["priorisiert"] is False
    assert db.con.execute("SELECT preis FROM anzeigen WHERE id=?", (angebot,)).fetchone()[0] == 30000
    fb.bestaetigen(db, angebot, {"preis": 30000})
    assert fb.sicht(db, angebot)["preis"]["konflikt"] is False
    assert bewerte_alle(cfg, db, BASIS)[0]["a"]["preis"] == 30000


def test_markenwechsel_herkunft_zeigt_effektive_modellableitung(cfg, db, angebot):
    vorher = fb.sicht(db, angebot)["modell"]["extrahiert"]
    fb.bestaetigen(db, angebot, {"marke": "Hymer"})
    a = bewerte_alle(cfg, db, BASIS)[0]["a"]
    assert a["datenherkunft"]["modell"]["wert"] == a["modell"]
    assert a["datenherkunft"]["modell"]["extrahiert"] == vorher
    assert a["datenherkunft"]["modell"]["bestaetigt"] is False


@pytest.mark.parametrize("art", [None, "Sonstige"])
def test_bewusst_unbekannte_art_wird_nicht_aus_titel_bestaetigt(cfg, db, angebot, art):
    fb.bestaetigen(db, angebot, {"art": art})
    z = bewerte_alle(cfg, db, BASIS)[0]
    assert z["a"]["art"] == art and z["a"]["datenherkunft"]["art"]["wert"] == art
    assert z["b"].sicherheit in ("niedrig", "keine")
    assert any(m["code"] == "art_unbekannt" for m in z["a"]["datenqualitaet"]["markierungen"])


def test_bestaetigter_preis_ohne_importpreis_geht_in_vergleichsbasis(cfg, db, angebot):
    db.con.execute("UPDATE anzeigen SET preis=NULL WHERE id=?", (angebot,))
    db.con.commit()
    fb.bestaetigen(db, angebot, {"preis": 32000})
    assert vergleichsbasis_aus(db)[0]["preis"] == 32000
    assert bewerte_alle(cfg, db, BASIS)[0]["a"]["preis"] == 32000
    fb.bestaetigen(db, angebot, {"preis": None})
    assert vergleichsbasis_aus(db) == []
    assert bewerte_alle(cfg, db, BASIS)[0]["a"]["preis"] is None


def test_zuruecksetzen_nur_gewaehlte_felder_und_bewusst_unbekannt(db, angebot):
    fb.bestaetigen(db, angebot, {"preis": 31000, "km": None})
    sicht = fb.zuruecksetzen(db, angebot, ["preis"])
    assert sicht["preis"]["wert"] == 35000 and sicht["preis"]["bestaetigt"] is False
    assert sicht["km"]["wert"] is None and sicht["km"]["bestaetigt"] is True
    assert fb.lade(db, []) == {} and list(fb.lade(db, [angebot])) == [angebot]


@pytest.mark.parametrize("werte", [None, [], {}, {"quelle": "mobile.de"}, {"preis": True}, {"preis": "32000"}, {"km": -1},
                                   {"ez_jahr": 3000}, {"modell": "x" * 151}, {"ort": "Muster\nstraße"}, {"art": "erfunden"},
                                   {"preis": 32000, "km": -1}])
def test_ungueltige_werte_werden_atomisch_abgelehnt(db, angebot, werte):
    with pytest.raises(ValueError):
        fb.bestaetigen(db, angebot, werte)
    assert fb.lade(db) == {}


def test_unbekannte_id_und_unzulaessige_reset_felder(db):
    with pytest.raises(LookupError):
        fb.sicht(db, "unbekannt")
    with pytest.raises(LookupError):
        fb.bestaetigen(db, "unbekannt", {"preis": 30000})
    with pytest.raises(LookupError):
        fb.zuruecksetzen(db, "unbekannt", ["preis"])
    with pytest.raises(ValueError):
        fb.zuruecksetzen(db, "unbekannt", ["quelle"])


def test_anonymisieren_entfernt_freitext_bestaetigung(db, angebot, tmp_path):
    fb.bestaetigen(db, angebot, {"ort": "74321 Personenbezug", "modell": "privater Freitext"})
    datenrechte.inserat_anonymisieren(db, tmp_path, angebot)
    assert fb.lade(db) == {}


def _alte_bestaetigung(db, angebot):
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2020-01-01T00:00:00',details_json=NULL,notiz=NULL WHERE id=?", (angebot,))
    db.con.execute("UPDATE feldbestaetigungen SET bestaetigt_am='2020-01-01T00:00:00+00:00' WHERE anzeige_id=?", (angebot,))
    db.con.commit()


def test_frist_erfasst_bestaetigten_freitext_ohne_andere_personendaten(db, angebot, tmp_path):
    fb.bestaetigen(db, angebot, {"ort": "Teststraße 12 c/o Testperson"})
    _alte_bestaetigung(db, angebot)
    jetzt = datetime(2026, 11, 8)
    assert datenrechte.inserate_faellig(db, 6, jetzt) == [angebot]
    assert datenrechte.inserate_nach_frist(db, tmp_path, 6, jetzt) == [angebot]
    assert fb.lade(db) == {}
    assert datenrechte.inserate_faellig(db, 6, jetzt) == []


def test_neue_bestaetigung_ist_aktivitaet_und_nach_anonymisierung_wieder_faellig(db, angebot, tmp_path):
    fb.bestaetigen(db, angebot, {"modell": "Testperson"})
    _alte_bestaetigung(db, angebot)
    datenrechte.inserat_anonymisieren(db, tmp_path, angebot)
    assert "anonymisiert_am" in db.con.execute("SELECT details_json FROM anzeigen WHERE id=?", (angebot,)).fetchone()[0]
    fb.bestaetigen(db, angebot, {"ort": "Neuer Personenfreitext"})
    assert datenrechte.inserate_faellig(db, 6, datetime.now()) == []
    db.con.execute("UPDATE feldbestaetigungen SET bestaetigt_am='2020-01-01T00:00:00+00:00' WHERE anzeige_id=?", (angebot,))
    db.con.commit()
    assert datenrechte.inserate_nach_frist(db, tmp_path, 6, datetime(2026, 11, 8)) == [angebot]
    assert fb.lade(db) == {}


def test_frist_erfasst_originalsnapshot_auch_bei_bestaetigtem_null(db, angebot):
    fb.bestaetigen(db, angebot, {"ort": None})
    _alte_bestaetigung(db, angebot)
    assert datenrechte.inserate_faellig(db, 6, datetime(2026, 11, 8)) == [angebot]


def test_frist_bleibt_mit_altem_schema_ohne_bestaetigungstabelle_lesbar(db, angebot):
    db.con.execute("DROP TABLE feldbestaetigungen")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2020-01-01T00:00:00',notiz='Testperson' WHERE id=?", (angebot,))
    db.con.commit()
    assert datenrechte.inserate_faellig(db, 6, datetime(2026, 11, 8)) == [angebot]


def test_migration_v23_mit_altbestand_sichert_und_ist_idempotent(tmp_path):
    pfad = tmp_path / "alt.sqlite"
    db = Datenbank(str(pfad))
    db.speichere_treffer(ANGEBOT, "Teilintegrierter")
    db.con.execute("DROP TABLE feldbestaetigungen")
    db.con.execute("DELETE FROM schema_version WHERE version=24")
    db.con.execute("INSERT OR IGNORE INTO schema_version VALUES (23,'2026-11-08')")
    db.con.commit()
    db.con.close()
    assert migrationen.migriere(pfad, tmp_path / "sicherungen") == [24]
    kopien = list((tmp_path / "sicherungen").glob("*.sqlite"))
    assert len(kopien) == 1
    with sqlite3.connect(kopien[0]) as con:
        assert con.execute("SELECT preis FROM anzeigen WHERE id=?", (ANGEBOT["id"],)).fetchone() == (35000,)
        assert con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 23
    assert migrationen.migriere(pfad, tmp_path / "sicherungen") == []
    db = Datenbank(str(pfad))
    assert fb.lade(db) == {}
    assert db.con.execute("SELECT preis FROM anzeigen WHERE id=?", (ANGEBOT["id"],)).fetchone()[0] == 35000
    fb.bestaetigen(db, ANGEBOT["id"], {"preis": 33000})
    assert json.loads(db.con.execute("SELECT wert_json FROM feldbestaetigungen").fetchone()[0]) == 33000
    db.con.close()
