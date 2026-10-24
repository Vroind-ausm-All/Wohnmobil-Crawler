"""P3-08 (ADR-046): Markierungen für fehlende, unplausible und widersprüchliche Angaben, Qualitätswert je Fahrzeug, Auswertung je Quelle (P2-10).

Geprüft: jede Regel mit Positiv- und Negativfall, Fahrzeugsicht über mehrere Inserate (fehlende Angabe anderswo vorhanden, km-Rückgang, abweichende
EZ), keine Wirkung auf Bewertung/Sperre/Brief, API, CSV, CLI und Oberfläche. Alles offline.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from tests.daten import BASIS
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from wmscout.ausgabe import render_html, schreibe_ausgaben
from wmscout.bewertung import auswertung
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.domaene import IMPORT_SUCHE
from wmscout.haendler import HaendlerSpeicher
from wmscout.normalisierung import qualitaet as q
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.team import TeamSpeicher

JETZT = datetime(2026, 10, 23, 12, 0)
STATIC = BASIS / "wmscout" / "web" / "static"


def inserat(**kw) -> dict:
    """Vollständiges, stimmiges Inserat; ``kw`` ändert einzelne Felder (None = fehlt)."""
    a = {"id": "x1", "titel": "Knaus Sky TI 650 MEG", "kurzbeschreibung": "gepflegt, Markise", "beschreibung": "", "marke": "Knaus", "preis": 39900,
         "ez_jahr": 2016, "km": 90000, "ort": "70173 Stuttgart", "suche": "Teilintegrierter", "gewerblich": 0,
         "erstmals_gesehen": "2026-10-01T10:00:00"}
    a.update(kw)
    return ergaenze_fahrzeug(a)


def codes(a: dict) -> set[str]:
    return {m["code"] for m in q.pruefe_inserat(a, JETZT)}


# ---------------------------------------------------------------- 1. Regeln je Inserat
def test_vollstaendig_und_stimmig_ohne_markierung():
    assert q.pruefe_inserat(inserat(), JETZT) == []
    assert q.pruefe_fahrzeug(inserat(), [], JETZT) == {"wert": 100, "stufe": "gut", "markierungen": [], "widersprueche": 0}


@pytest.mark.parametrize("feld, code", [("preis", "preis_fehlt"), ("ez_jahr", "ez_fehlt"), ("km", "km_fehlt"), ("ort", "ort_fehlt"),
                                        ("gewerblich", "anbieter_unbekannt")])
def test_fehlende_angaben(feld, code):
    assert codes(inserat(**{feld: None})) == {code}


def test_marke_fehlt_art_unbekannt_vorlaeufig_und_ausland():
    assert "marke_fehlt" in codes(inserat(marke=None, titel="Wohnmobil gepflegt", kurzbeschreibung=""))
    assert "art_unbekannt" in codes(inserat(suche=IMPORT_SUCHE))
    assert "art_vorlaeufig" in codes(inserat(suche="Import Teilintegrierter (vorläufig)"))
    assert "ort_fehlt" not in codes(inserat(ort="FR-75001 Paris"))                                     # Ausland: keine PLZ erwartet
    a = inserat()
    del a["gewerblich"]
    assert "anbieter_unbekannt" not in codes(a)                                                       # ohne Schlüssel wie bisher privat


@pytest.mark.parametrize("kw, code", [
    ({"preis": 1}, "preis_platzhalter"), ({"preis": 999}, "preis_platzhalter"), ({"preis": 800_000}, "preis_hoch"),
    ({"ez_jahr": 2027}, "ez_zukunft"), ({"ez_jahr": 1955}, "ez_alt"),
    ({"km": 1_200_000}, "km_hoch"), ({"ez_jahr": 2024, "km": 400_000}, "km_hoch"), ({"km": 400}, "km_niedrig"),
], ids=lambda x: str(x))
def test_unplausible_angaben(kw, code):
    m = [x for x in q.pruefe_inserat(inserat(**kw), JETZT) if x["code"] == code]
    assert m and m[0]["art"] == "unplausibel"


@pytest.mark.parametrize("kw", [{"preis": 1000}, {"preis": 450_000}, {"preis": 750_000}, {"ez_jahr": 2026, "km": 5000}, {"ez_jahr": 1960},
                                {"km": 999_999, "ez_jahr": 2000},
                                {"ez_jahr": 2025, "km": 500}, {"km": 1000}], ids=lambda x: str(x))
def test_grenzwerte_sind_plausibel(kw):
    assert not [x for x in q.pruefe_inserat(inserat(**kw), JETZT) if x["art"] == "unplausibel"]


@pytest.mark.parametrize("kw, code", [
    ({"kurzbeschreibung": "Baujahr 2018, gepflegt"}, "ez_vor_baujahr"),
    ({"kurzbeschreibung": "Bj. 2019"}, "ez_vor_baujahr"),
    ({"titel": "Knaus Sky TI EZ 2014"}, "ez_text"),
    ({"beschreibung": "Erstzulassung: 03/2019"}, "ez_text"),
    ({"beschreibung": "EZ 15.03.2018"}, "ez_text"),
    ({"beschreibung": "Erstzulassung Juli 2019"}, "ez_text"),
    ({"beschreibung": "EZ ca. 2014"}, "ez_text"),
    ({"titel": "Knaus Sky TI 150.000 km"}, "km_text"),
    ({"titel": "Hymer B 544 Alkoven"}, "marke_titel"),
], ids=lambda x: str(x))
def test_widersprueche_im_inserat(kw, code):
    m = [x for x in q.pruefe_inserat(inserat(**kw), JETZT) if x["code"] == code]
    assert m and m[0]["art"] == "widerspruch", q.pruefe_inserat(inserat(**kw), JETZT)


@pytest.mark.parametrize("kw", [
    {"kurzbeschreibung": "Baujahr 2015, EZ 2016"},                                        # Baujahr vor EZ: normal
    {"titel": "Knaus Sky TI EZ 2016"}, {"titel": "Knaus Sky TI 92.000 km"},              # gleich bzw. innerhalb der Toleranz
    {"titel": "Fiat Ducato Knaus Sky TI"},                                                 # Basisfahrzeug ist kein Widerspruch
    {"titel": "Knaus Sky TI 650", "kurzbeschreibung": "90.000 km, 5.000 km seit Service"},  # irgendein km-Wert passt
    {"kurzbeschreibung": "5.000 km seit Inspektion"}, {"kurzbeschreibung": "Gasflaschen reichen 1500 km"},   # QA B1: nur der Titel zählt
    {"kurzbeschreibung": "Baujahr 2017 (Modelljahr)"},                                     # QA B2: ein Jahr nach EZ = Modelljahr
    {"beschreibung": "Erstzulassung Basisfahrzeug 2014, Aufbau 2016"}, {"beschreibung": "EZ und TÜV 2027"},   # QA B3
], ids=lambda x: str(x))
def test_keine_falschen_widersprueche(kw):
    assert not [x for x in q.pruefe_inserat(inserat(**kw), JETZT) if x["art"] == "widerspruch"]


# ---------------------------------------------------------------- 2. Fahrzeug über mehrere Inserate
def test_fehlende_angabe_im_anderen_inserat_zaehlt_nicht():
    a, b = inserat(km=None), inserat(id="x2", km=91000)
    assert q.pruefe_fahrzeug(a, [], JETZT)["wert"] == 85
    assert q.pruefe_fahrzeug(a, [b], JETZT)["markierungen"] == []


def test_km_rueckgang_und_abweichende_ez():
    alt = inserat(id="alt", km=120_000, erstmals_gesehen="2026-08-01T10:00:00")
    neu = inserat(id="neu", km=90_000, erstmals_gesehen="2026-10-01T10:00:00", ez_jahr=2017)
    r = q.pruefe_fahrzeug(neu, [alt], JETZT)
    assert {m["code"] for m in r["markierungen"]} == {"km_rueckgang", "ez_abweichend"} and r["widersprueche"] == 2
    assert "alt" in next(m for m in r["markierungen"] if m["code"] == "km_rueckgang")["text"]
    assert "km_rueckgang" not in {m["code"] for m in q.pruefe_fahrzeug(alt, [neu], JETZT)["markierungen"]}   # älteres Inserat: kein Rückgang
    gleich = inserat(id="alt", km=90_500, erstmals_gesehen="2026-08-01T10:00:00")
    assert not q.pruefe_fahrzeug(inserat(), [gleich], JETZT)["markierungen"]                              # Toleranz 1.000 km


def test_ohne_datum_kein_km_rueckgang_und_zahlen_als_text():
    """QA B5/B7: Inserate ohne „erstmals gesehen“ werden nicht verglichen; Zahlen als Text gelten, Kommazahlen/bool nicht."""
    ohne = inserat(id="ohne", km=120_000, erstmals_gesehen=None)
    assert not q.pruefe_fahrzeug(inserat(km=90_000), [ohne], JETZT)["markierungen"]
    assert not q.pruefe_fahrzeug(inserat(km=90_000, erstmals_gesehen=None), [inserat(id="b", km=120_000)], JETZT)["markierungen"]
    assert codes(inserat(preis="39900", km=" 90000 ")) == set()
    assert codes(inserat(km=90000.5)) == {"km_fehlt"} and codes(inserat(ez_jahr=True)) == {"ez_fehlt"}


def test_markierungen_je_inserat_nur_einmal_berechnet(cfg, db, importiert, monkeypatch):
    """QA B4: bei Gruppen kein quadratischer Aufwand – jedes Inserat wird je Lauf höchstens einmal geprüft."""
    aufrufe = []
    echt = auswertung.pruefe_inserat
    monkeypatch.setattr(auswertung, "pruefe_inserat", lambda a, j: aufrufe.append(a["id"]) or echt(a, j))
    ids = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 6")]
    from wmscout.dubletten import bestaetige
    for x in ids[1:]:
        bestaetige(db, db.con.execute("SELECT id FROM inserate WHERE anzeigen_id=?", (ids[0],)).fetchone()[0],
                   db.con.execute("SELECT id FROM inserate WHERE anzeigen_id=?", (x,)).fetchone()[0], None)
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert len(aufrufe) == len(set(aufrufe)) <= len(zeilen) + 6
    assert any(z["dubletten_ids"] for z in zeilen)


def test_markierungstexte_werden_escaped(cfg, db, importiert):
    ad = db.con.execute("SELECT MIN(id) FROM anzeigen").fetchone()[0]
    db.con.execute("UPDATE anzeigen SET marke='<script>x</script>', titel='Hymer <img src=x onerror=alert(1)> B 544' WHERE id=?", (ad,))
    db.con.commit()
    zeilen = bewerte_alle(cfg, db, BASIS)
    html = render_html(cfg, zeilen, BASIS)
    assert "<script>x</script>" not in html and "<img src=x" not in html


def test_wert_und_stufen():
    assert q.pruefe_fahrzeug(inserat(gewerblich=None), [], JETZT)["stufe"] == "gut"                     # 95
    assert q.pruefe_fahrzeug(inserat(km=None, ort=None), [], JETZT)["stufe"] == "mittel"               # 75
    r = q.pruefe_fahrzeug(inserat(preis=None, ez_jahr=None, km=None, ort=None, gewerblich=None, suche=IMPORT_SUCHE), [], JETZT)
    assert r["stufe"] == "schwach" and r["wert"] == 10
    r = q.pruefe_fahrzeug(inserat(preis=1, ez_jahr=None, km=None, ort=None, gewerblich=None, suche=IMPORT_SUCHE, titel="Hymer B 544 Alkoven"), [], JETZT)
    assert r["wert"] == 0                                                                                 # nie negativ


# ---------------------------------------------------------------- 3. Einbindung: Anzeige, keine Wirkung
def test_jede_zeile_hat_datenqualitaet_und_nichts_aendert_sich(cfg, db, importiert, monkeypatch):
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert zeilen and all(z["a"]["datenqualitaet"]["stufe"] in ("gut", "mittel", "schwach") for z in zeilen)
    monkeypatch.setattr(auswertung, "pruefe_inserat", lambda a, j: [q._m("preis_fehlt", "fehlt", "x")] * 9)
    monkeypatch.setattr(auswertung, "pruefe_fahrzeug", lambda a, b, j, e, **k: {"wert": 0, "stufe": "schwach", "markierungen": e, "widersprueche": 0})
    anders = bewerte_alle(cfg, db, BASIS)
    for z1, z2 in zip(zeilen, anders, strict=True):
        assert asdict(z1["b"]) == asdict(z2["b"]) and (z1["sperre"], z1["brief"], z1["bereit"], z1["hinweise"]) == (
            z2["sperre"], z2["brief"], z2["bereit"], z2["hinweise"])


def test_je_quelle(cfg, db, importiert):
    db.con.execute("UPDATE anzeigen SET km=NULL WHERE rowid % 2 = 0")
    db.con.commit()
    zeilen = bewerte_alle(cfg, db, BASIS)
    (k,) = q.je_quelle(zeilen)
    assert k["quelle"] == "kleinanzeigen" and k["anzahl"] == len(zeilen) and 0.3 < k["km"] < 0.7 and k["preis"] == 1.0
    assert 0 <= k["mittel"] <= 100 and k["mit_widerspruch"] >= 0
    for z in zeilen[:3]:
        z["a"]["quelle"] = "mobile.de"
    assert [x["quelle"] for x in q.je_quelle(zeilen)] == ["kleinanzeigen", "mobile.de"]


def test_api_csv_cli(server, cfg, db, importiert, tmp_path, capsys):
    db.con.execute("UPDATE anzeigen SET preis=1 WHERE id=(SELECT MIN(id) FROM anzeigen)")
    db.con.commit()
    c = lokal(server)
    liste = c("GET", "/api/fahrzeuge?filter=alle")[1]
    assert all({"wert", "stufe", "markierungen", "widersprueche"} <= set(f["datenqualitaet"]) for f in liste)
    ad = db.con.execute("SELECT MIN(id) FROM anzeigen").fetchone()[0]
    d = c("GET", f"/api/fahrzeug/{ad}")[1]["datenqualitaet"]
    assert "preis_platzhalter" in {m["code"] for m in d["markierungen"]} and d["wert"] <= 80
    s, j, _ = c("GET", "/api/datenqualitaet")
    assert s == 200 and j["quellen"][0]["quelle"] == "kleinanzeigen" and "datenqualitaet_inserat" not in str(liste)
    schreibe_ausgaben(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    zeilen = list(csv.reader((Path(cfg["ausgabe"]["ordner"]) / "anzeigen_bewertet.csv").open(encoding="utf-8-sig"), delimiter=";"))
    i = zeilen[0].index("Datenqualität")
    assert zeilen[0][i + 1] == "Datenmarkierungen" and zeilen[0][i - 1] == "Anbieter-Herkunft"
    werte = {z[0]: (z[i], z[i + 1]) for z in zeilen[1:]}
    assert "Platzhalter" in werte[ad][1] and int(werte[ad][0]) <= 80
    import scout
    scout.cmd_qualitaet(cfg, db, None)
    aus = capsys.readouterr().out
    assert "kleinanzeigen" in aus and "schwacher Datenlage" in aus


def test_api_rechte(server, cfg, db, importiert, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    assert anmelden(server, "Ben")("GET", "/api/datenqualitaet")[0] == 200
    assert anmelden(server, "Hugo")("GET", "/api/datenqualitaet")[0] == 403


def test_oberflaeche_statisch():
    js, html = (STATIC / "mobil.js").read_text(encoding="utf-8"), (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "function dqKarte" in js and "esc(m.text)" in js and "dqTag(f)" in js
    assert "data-dq-wert" in html and "Daten lückenhaft" in html and "|safe" not in html.split("data-dq-wert")[1][:600]
    assert "wm-scout-13" in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_leere_eingaben():
    assert q.je_quelle([]) == []
    assert copy.deepcopy(q.pruefe_fahrzeug(inserat(), [], JETZT))["wert"] == 100
