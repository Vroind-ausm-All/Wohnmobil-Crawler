"""P5-07 – Deal-Score 0–100 mit benannten Bestandteilen und Bewertungsverlauf (ADR-060): Formel, Gewichte, kein Score bei Sperre oder
ohne Bewertung, Top-Deal, Schema v22, Verlauf nur bei Änderung, Oberfläche, API, CSV, Kommandozeile."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
import csv
import re
import sqlite3
from datetime import datetime

import pytest

from tests.daten import BASIS, lade_cfg
from tests.test_cli import _scout
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout import bewertungsverlauf, migrationen
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.deal_score import MODELL, STANDARD, deal_score, einstellungen, top_ausschluss
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import Datenbank

OKTOBER = datetime(2026, 10, 25, 12)
FZ = {"id": "x", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018, "km": 80000,
      "plz": "74321", "entfernung_km": 10}
VGL = [{"id": f"v{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": 46000 + i * 400,
        "zuletzt_gesehen": "2026-10-20T10:00:00"} for i in range(9)]
PRIVAT = {"typ": "privat", "herkunft": "anzeige", "belegt": True, "text": "privat (laut Anzeige)"}


def _fall(preis_faktor: float = 0.85, **extra):
    """Fahrzeug, Bewertung und Inserat zu einem Wunschpreis von ``preis_faktor`` × Max-EK."""
    r = Rechner(lade_cfg(), OKTOBER)
    max_ek = r.bewerte({**FZ, "preis": 30000, **extra}, VGL).max_ek
    a = {**FZ, "preis": round(max_ek * preis_faktor), "anbieter": PRIVAT, "tage_online": 3, **extra}
    return a, r.bewerte(a, VGL)                                      # Ampel passend zum Wunschpreis


def _teil(d, schluessel):
    return next(t for t in d["bestandteile"] if t["schluessel"] == schluessel)


# ---------------------------------------------------------------- 1. Einstellungen
def test_einstellungen_aus_config_und_standard():
    e = einstellungen(lade_cfg())
    assert e["gewichte"] == {"preisvorteil": 40, "datensicherheit": 20, "zustand": 15, "abholung": 10, "frische": 10, "verkaeufer": 5}
    assert e["schwelle"] == 70 and einstellungen({}) == STANDARD


@pytest.mark.parametrize("roh, teil", [
    ({"gewicht": {}}, "unbekannte Einträge"), ({"gewichte": {"preis": 10}}, "unbekannt: preis"), ({"gewichte": {"zustand": -1}}, "zustand"),
    ({"gewichte": dict.fromkeys(STANDARD["gewichte"], 0)}, "mindestens ein Gewicht"), ({"preis_voll_bei": 1.2}, "kleiner als"),
    ({"schwelle": 101}, "0–100"), ({"gewichte": {"preisvorteil": float("inf")}}, "preisvorteil"),
    ({"abholung_null_bei_euro": 0}, "abholung_null_bei_euro"), ({"schwelle": "70"}, "schwelle"), ("x", "Abschnitt"),
])
def test_fehleingaben(roh, teil):
    with pytest.raises(ValueError, match=teil):
        einstellungen({"deal_score": roh})


# ---------------------------------------------------------------- 2. Formel
def test_guter_deal_hoch_teurer_niedrig_summe_stimmt():
    gut = deal_score(*_fall(0.80), {"frisch": True}, None, lade_cfg())
    teuer = deal_score(*_fall(1.20), None, None, lade_cfg())
    assert gut["score"] >= 85 and teuer["score"] < gut["score"] - 30 and gut["modell"] == MODELL
    assert gut["score"] == round(sum(t["punkte"] for t in gut["bestandteile"]))
    assert {t["schluessel"] for t in gut["bestandteile"]} == set(STANDARD["gewichte"])
    assert sum(t["gewicht"] for t in gut["bestandteile"]) == pytest.approx(100)


@pytest.mark.parametrize("faktor, anteil", [(0.80, 1.0), (0.85, 1.0), (1.0, 0.5), (1.15, 0.0), (1.30, 0.0)])
def test_preisvorteil_linear(faktor, anteil):
    a, b = _fall(faktor)
    assert _teil(deal_score(a, b, None, None, lade_cfg()), "preisvorteil")["anteil"] == pytest.approx(anteil, abs=0.01)


def test_gewichte_relativ():
    cfg = lade_cfg()
    doppelt = copy.deepcopy(cfg)
    doppelt["deal_score"]["gewichte"] = {k: 2 * v for k, v in cfg["deal_score"]["gewichte"].items()}
    a, b = _fall(0.95)
    assert deal_score(a, b, None, None, cfg)["score"] == deal_score(a, b, None, None, doppelt)["score"]
    nur_preis = copy.deepcopy(cfg)
    nur_preis["deal_score"]["gewichte"] = {**dict.fromkeys(STANDARD["gewichte"], 0), "preisvorteil": 1}
    assert deal_score(*_fall(0.85), None, None, nur_preis)["score"] == 100


def test_zustand_abholung_frische_verkaeufer():
    cfg = lade_cfg()
    ohne = deal_score(*_fall(), None, None, cfg)
    motor = deal_score(*_fall(beschreibung="Motorschaden, Wasserschaden, Delamination"), None, None, cfg)
    assert _teil(ohne, "zustand")["anteil"] == 1.0 and _teil(motor, "zustand")["anteil"] == 0.0 and "Motorschaden" in _teil(motor, "zustand")["text"]
    assert _teil(deal_score(*_fall(ausland="FR"), None, None, cfg), "abholung")["anteil"] == 0.0
    assert _teil(deal_score(*_fall(entfernung_km=None, plz=None), None, None, cfg), "abholung")["anteil"] == 0.5
    weit = _teil(deal_score(*_fall(entfernung_km=600, plz="20095"), None, None, cfg), "abholung")
    assert weit["anteil"] < 0.5 and "Abholung ca." in weit["text"]
    assert _teil(deal_score(*_fall(), {"im_rahmen": True}, None, cfg), "frische")["anteil"] == 1.0
    assert _teil(deal_score(*_fall(), {"senkung": {"euro": 500}}, None, cfg), "frische")["anteil"] == 0.8
    assert _teil(deal_score(*_fall(tage_online=200), None, None, cfg), "frische")["anteil"] == 0.0
    assert _teil(ohne, "verkaeufer")["anteil"] == 1.0
    offline = _teil(deal_score(*_fall(vermutlich_offline=True, verfuegbarkeit="reserviert"), None, None, cfg), "verkaeufer")
    assert offline["anteil"] == 0.25 and "nicht mehr online" in offline["text"] and "reserviert" in offline["text"]
    unbekannt = {"typ": "unbekannt", "herkunft": None, "belegt": False, "text": "unbekannt"}
    assert _teil(deal_score(*_fall(anbieter=unbekannt), None, None, cfg), "verkaeufer")["anteil"] == 0.4


def test_kein_score_bei_sperre_oder_ohne_bewertung_und_top_deal():
    cfg = lade_cfg()
    a, b = _fall(0.80)
    assert deal_score(a, b, None, "gewerblicher Anbieter", cfg) == {"score": None, "priorisiert": False, "bestandteile": [], "modell": MODELL,
                                                                    "schwelle": 70, "grund": "gesperrt: gewerblicher Anbieter"}
    ohne = Rechner(cfg, OKTOBER).bewerte({**FZ, "ez_jahr": None, "preis": 30000}, VGL)
    assert deal_score({**a, "ez_jahr": None}, ohne, None, None, cfg)["score"] is None
    top = deal_score(a, b, {"frisch": True}, None, cfg)
    assert top["priorisiert"] is True
    for weg in ({"nicht_verfuegbar": True}, {"vermutlich_offline": True}, {"verfuegbarkeit": "reserviert"}, {"status": "vorbereitet"}):
        assert deal_score({**a, **weg}, b, {"frisch": True}, None, cfg)["priorisiert"] is False, weg
    unbekannt = {"typ": "unbekannt", "belegt": False, "text": "unbekannt"}
    assert deal_score({**a, "anbieter": unbekannt}, b, {"frisch": True}, None, cfg)["priorisiert"] is False


# ---------------------------------------------------------------- 3. Schema v22 und Verlauf
def test_migration_v22_additiv_nur_anfuegbar(tmp_path, monkeypatch):
    pfad = tmp_path / "alt.sqlite"
    with monkeypatch.context() as m:
        m.setattr(migrationen, "AKTUELLE_VERSION", 21)
        migrationen.migriere(pfad, tmp_path / "s")
    assert migrationen.migriere(pfad, tmp_path / "s") == [22]
    assert [p for p in (tmp_path / "s").iterdir() if "vor-v22" in p.name]
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO bewertungen (anzeige_id, zeitpunkt, modell_version, deal_score) VALUES ('a', 'z', 'E6/D1', 50)")
    con.commit()
    for sql in ("UPDATE bewertungen SET deal_score=1", "DELETE FROM bewertungen"):
        with pytest.raises(sqlite3.DatabaseError, match="nur anfügbar"):
            con.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO bewertungen (anzeige_id, zeitpunkt, modell_version, deal_score) VALUES ('a', 'z', 'x', 101)")
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == []


def test_verlauf_nur_bei_aenderung(cfg, db, importiert):
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert any(z["deal"]["score"] is not None for z in zeilen)
    n = bewertungsverlauf.merken(db, zeilen)
    assert n == len(zeilen) and bewertungsverlauf.merken(db, bewerte_alle(cfg, db, BASIS)) == 0      # unverändert: nichts Neues
    z = next(z for z in zeilen if z["deal"]["score"] is not None)
    db.con.execute("UPDATE anzeigen SET preis=preis-3000 WHERE id=?", (z["a"]["id"],))
    db.con.commit()
    assert bewertungsverlauf.merken(db, bewerte_alle(cfg, db, BASIS)) >= 1
    v = bewertungsverlauf.verlauf(db, z["a"]["id"])
    assert len(v) == 2 and v[0]["preis"] == z["a"]["preis"] - 3000 and v[0]["modell_version"] == bewertungsverlauf.MODELL_VERSION
    assert v[0]["komponenten"] and {"schluessel", "anteil", "punkte", "text"} <= set(v[0]["komponenten"][0])


def test_verlauf_ohne_tabelle(tmp_path):
    con = sqlite3.connect(tmp_path / "leer.sqlite")

    class Alt:
        pass
    alt = Alt()
    alt.con = con
    con.row_factory = sqlite3.Row
    assert bewertungsverlauf.merken(alt, []) == 0 and bewertungsverlauf.verlauf(alt, "x") == []


# ---------------------------------------------------------------- 4. Oberfläche, API, CSV, Kommandozeile
def test_desktop_und_api(server, db):
    c = lokal(server)
    html = c("GET", "/")[1]
    assert 'value="score"' in html and 'data-f="top"' in html and "data-score=" in html and "Deal " in html
    karte = re.search(r'data-score="(\d+)"', html)
    assert karte and 0 <= int(karte.group(1)) <= 100
    liste = c("GET", "/api/fahrzeuge?filter=alle")[1]
    mit = [f for f in liste if f["deal_score"] is not None]
    assert mit and all(0 <= f["deal_score"] <= 100 for f in mit) and all(isinstance(f["priorisiert"], bool) for f in liste)
    d = c("GET", f"/api/fahrzeug/{mit[0]['id']}")[1]
    assert d["deal"]["score"] == mit[0]["deal_score"] and len(d["deal"]["bestandteile"]) == 6 and d["deal_verlauf"] == []
    detail = re.search(rf'<section id="d{mit[0]["id"]}".*?</section>', html, re.S).group(0)
    assert "data-deal" in detail and "Preisvorteil" in detail and "die Ampel bleibt daneben" in detail


def test_csv_und_kommandozeile(cfg, tmp_path, importiert, db):
    db.con.close()
    r = _scout(cfg, tmp_path, "report")
    assert r.returncode == 0, r.stderr
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    n = db.con.execute("SELECT COUNT(*) FROM bewertungen").fetchone()[0]
    assert n > 0
    with open(tmp_path / "ausgabe" / "anzeigen_bewertet.csv", encoding="utf-8-sig", newline="") as f:
        reihen = list(csv.reader(f, delimiter=";"))
    i = reihen[0].index("Deal-Score")
    assert reihen[0][i + 1] == "Top-Deal" and any(r[i].isdigit() for r in reihen[1:])
    db.con.close()
    assert _scout(cfg, tmp_path, "report").returncode == 0
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    assert db.con.execute("SELECT COUNT(*) FROM bewertungen").fetchone()[0] == n            # zweiter Report ohne Änderung: nichts Neues
    db.con.close()
    cfg["deal_score"] = {"schwelle": 300}
    r = _scout(cfg, tmp_path, "report")
    assert r.returncode != 0 and "deal_score" in r.stderr


# ---------------------------------------------------------------- 5. Korrekturrunde (QA P5-07)
def test_ausland_und_unsichere_bewertung_kein_top_deal():
    """B1/B2: Ampel bei Ausland und unbekannter Art höchstens gelb, unsichere Bewertung – hoher Score, aber kein Top-Deal; der
    Preisvorteil aus unsicherer Bewertung zählt weniger."""
    cfg = lade_cfg()
    a, b = _fall(0.80)
    aus = deal_score({**a, "ausland": "FR"}, b, {"frisch": True}, None, cfg)
    assert aus["priorisiert"] is False and aus["kein_top"] == "Ausland"
    ohne_vgl = Rechner(cfg, OKTOBER).bewerte({**a, "id": "o"}, [])
    assert ohne_vgl.sicherheit == "niedrig"
    d = deal_score(a, ohne_vgl, {"frisch": True}, None, cfg)
    assert d["priorisiert"] is False
    assert top_ausschluss(a, ohne_vgl) in ("Bewertung zu unsicher (niedrig)", "Ampel nicht grün")
    voll = _teil(deal_score(a, b, None, None, cfg), "preisvorteil")
    unsicher = _teil(d, "preisvorteil")
    assert unsicher["anteil"] < voll["anteil"] and "zählt zu" in unsicher["text"]


def test_status_nimmt_score_nicht_weg(cfg, db, importiert):
    """B4: Text kopiert, kontaktiert … behalten ihren Score (Sortierung, Verlauf), sind aber kein Top-Deal mehr."""
    zeilen = bewerte_alle(cfg, db, BASIS)
    z = next(z for z in zeilen if z["deal"]["score"] is not None and not z["sperre"])
    db.setze_status(z["a"]["id"], "vorbereitet", text="Hallo")
    neu = next(x for x in bewerte_alle(cfg, db, BASIS) if x["a"]["id"] == z["a"]["id"])
    assert neu["sperre"] and neu["deal"]["score"] is not None and neu["deal"]["priorisiert"] is False


def test_verlauf_fehler_haelt_nichts_auf(cfg, db, importiert, caplog):
    """B5: Eine gesperrte Datenbank beim Verlauf bricht Report, Mail oder Import nicht ab."""
    zeilen = bewerte_alle(cfg, db, BASIS)
    echt = db.con

    class Gesperrt:
        def __getattr__(self, n):
            return getattr(echt, n)

        def executemany(self, *a):
            raise sqlite3.OperationalError("database is locked")
    db.con = Gesperrt()
    try:
        assert bewertungsverlauf.merken(db, zeilen) == 0 and "Bewertungsverlauf nicht gespeichert" in caplog.text
    finally:
        db.con = echt


def test_kleine_score_bewegung_keine_neue_zeile(cfg, db, importiert):
    """B6: Die täglich sinkende Frische erzeugt nicht jeden Tag eine Zeile – erst ab 3 Punkten Unterschied."""
    zeilen = bewerte_alle(cfg, db, BASIS)
    bewertungsverlauf.merken(db, zeilen)
    z = next(z for z in zeilen if z["deal"]["score"] is not None)
    for delta, neu in ((2, 0), (3, 1)):
        geaendert = {**z, "deal": {**z["deal"], "score": z["deal"]["score"] - delta}}
        assert bewertungsverlauf.merken(db, [geaendert]) == neu, delta
