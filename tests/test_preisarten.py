"""P5-04 – Angebots- gegen Transaktionspreise, Händler- gegen Privatpreise (ADR-055): Händlermarkt als Obergrenze für den Händler-VK,
Marktbeobachtung der Preissenkungen bis zum Verschwinden (Untergrenze für den Abschlag Angebot → Abschluss), Kalkulation, Oberfläche."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.daten import BASIS, lade_cfg
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout.bewertung import kalibrierung as kal
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.rechner import Rechner, Vergleichsliste, haendlerangebot

STICHTAG = datetime(2026, 10, 25, 12)
FZ = {"id": "x", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018, "km": 80000,
      "preis": 40000}


def _v(i, preis, gewerblich=0, **k):
    return {"id": f"{'h' if gewerblich else 'p'}{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": preis,
            "gewerblich": gewerblich, "zuletzt_gesehen": "2026-10-20T10:00:00", **k}


def _privat(n=6, preis=48000):
    return [_v(i, preis + i * 300) for i in range(n)]


def _haendler(n, preis):
    return [_v(i, preis + i * 300, gewerblich=1) for i in range(n)]


@pytest.fixture
def r():
    return Rechner(lade_cfg(), STICHTAG)


# ---------------------------------------------------------------- 1. Händlerangebote getrennt
def test_haendlerangebot():
    assert haendlerangebot({"gewerblich": 1}) and haendlerangebot({"gewerblich": True})
    assert not haendlerangebot({"gewerblich": 0}) and not haendlerangebot({"gewerblich": None}) and not haendlerangebot({})


def test_privatmarkt_bleibt_ohne_haendler(r):
    """Händlerangebote verändern Marktwert und Marktwert privat nicht – sie sind nur die Obergrenze für den Händler-VK."""
    privat = _privat()
    mit = r.marktniveau(FZ, privat + _haendler(5, 30000))
    assert mit == r.marktniveau(FZ, privat)
    assert len(r.vergleiche(FZ, privat + _haendler(5, 30000), haendler=True)) == 5
    assert all(v[0] for v in r.vergleiche(FZ, privat + _haendler(5, 30000)))


def test_vorfilter_liefert_dasselbe(r):
    alle = _privat(12) + _haendler(9, 52000) + [_v(99, 50000, gewerblich=None)]
    for h in (False, True):
        assert r.vergleiche(FZ, Vergleichsliste(alle), haendler=h) == r.vergleiche(FZ, alle, haendler=h)


# ---------------------------------------------------------------- 2. Händlermarkt als Obergrenze
KNAPP = 50500          # Händler knapp über dem Privatmarkt (~48.200): eigener VK (privat × 0,93 × 1,10) läge darüber → Obergrenze


def test_haendlermarkt_erst_ab_mindestzahl(r):
    niveau = r.marktniveau(FZ, _privat())["niveau"]
    zwei = r.haendlermarkt(FZ, _privat() + _haendler(2, KNAPP), niveau)
    assert (zwei["n"], zwei["niveau"], zwei["deckel"]) == (2, None, None)
    drei = r.haendlermarkt(FZ, _privat() + _haendler(3, KNAPP), niveau)
    assert drei["n"] == 3 and drei["deckel"] == pytest.approx(drei["niveau"] * 0.95) and not drei["konflikt"]
    assert drei["deckel_unten"] <= drei["deckel"] <= drei["deckel_oben"]
    for aus in (False, 0, "nein", "aus"):                                                     # QA B5: Schalter streng
        cfg = lade_cfg()
        cfg["rechner"]["haendler_vk_deckel"] = aus
        h = Rechner(cfg, STICHTAG).haendlermarkt(FZ, _privat() + _haendler(3, KNAPP), niveau)
        assert h["niveau"] and h["deckel"] is None
    assert r.haendlermarkt({**FZ, "id": "ohne-ez", "ez_jahr": None}, _haendler(5, KNAPP), niveau)["n"] == 0


def test_haendler_knapp_ueber_privat_begrenzen_den_vk(r):
    ohne = r.bewerte(FZ, _privat())
    mit = r.bewerte(FZ, _privat() + _haendler(5, KNAPP))
    assert mit.vk_gedeckelt and mit.haendler_anzahl == 5 and mit.haendler_niveau % 500 == 0
    assert mit.haendler_vk < ohne.haendler_vk and mit.max_ek < ohne.max_ek and mit.marktwert_privat == ohne.marktwert_privat
    assert mit.haendler_vk >= mit.marktwert_privat                                            # nie unter den Marktwert privat
    assert mit.max_ek >= ohne.max_ek * 0.85                                                   # Begrenzung, kein Absturz
    assert "5 Händlerangebote (Niveau" in mit.vergleich_basis and "Händler-VK auf" in mit.vergleich_basis
    assert mit.max_ek_von <= mit.max_ek <= mit.max_ek_bis and mit.max_ek_bis - mit.max_ek_von >= 500
    assert ohne.sicherheit != "hoch" or mit.sicherheit == "mittel"                           # QA B2: Obergrenze → höchstens mittel


def test_teure_haendler_aendern_nichts(r):
    ohne = r.bewerte(FZ, _privat())
    mit = r.bewerte(FZ, _privat() + _haendler(5, 70000))
    assert not mit.vk_gedeckelt and mit.haendler_vk == ohne.haendler_vk and mit.max_ek == ohne.max_ek
    assert "5 Händlerangebote (Niveau" in mit.vergleich_basis and "begrenzt" not in mit.vergleich_basis
    wenige = r.bewerte(FZ, _privat() + _haendler(1, KNAPP))
    assert not wenige.vk_gedeckelt and wenige.haendler_niveau is None and "1 Händlerangebot (zu wenige" in wenige.vergleich_basis


@pytest.mark.parametrize("preis, text", [
    (1500, "weit unter dem Privatmarkt nicht gezählt"),       # Miete/Anzahlung/Rate
    (25000, "weit unter dem Privatmarkt nicht gezählt"),      # Lockangebote
    (42000, "Händler billiger als privat: Datenkonflikt"),    # unter dem Privatniveau, aber nicht absurd
])
def test_billige_haendlerangebote_druecken_den_max_ek_nicht(r, preis, text):
    """QA P5-04 B1: drei Miet-, Raten- oder Lockangebote dürfen den Max-EK nicht auf 0 oder −57 % drücken."""
    ohne = r.bewerte(FZ, _privat())
    mit = r.bewerte(FZ, _privat() + _haendler(3, preis))
    assert not mit.vk_gedeckelt and mit.max_ek == ohne.max_ek and mit.ampel == ohne.ampel and text in mit.vergleich_basis


# ---------------------------------------------------------------- 3. Kalkulation
def test_kalkulation_nachrechenbar_mit_haendlermarkt():
    cfg = lade_cfg()
    for schluessel in ("haendler_vk_deckel", "haendler_vergleich_min", "abschlag_haendler_angebot"):
        del cfg["rechner"][schluessel]
    alle = _privat() + [_v(i, KNAPP - 1500 + i * 1000, gewerblich=1) for i in range(5)]
    e = kalk.eingabe(cfg, {**FZ, "entfernung_km": 50}, alle, betrag=30000, stichtag=STICHTAG, abholung="Firmensitz")
    assert e["version"] == kalk.VERSION == "E4"
    assert (e["rechner"]["haendler_vk_deckel"], e["rechner"]["haendler_vergleich_min"], e["rechner"]["abschlag_haendler_angebot"]) == (True, 3, 0.05)
    assert sum(1 for v in e["vergleich"] if v["gewerblich"] == 1) == 5
    erg = kalk.rechne(e)
    assert erg["szenarien"]["erwartet"]["haendler_vk"] == Rechner(lade_cfg(), STICHTAG).bewerte({**FZ, "entfernung_km": 50}, alle).haendler_vk
    assert any("höchstens Händlermarkt (5 Händlerangebote" in z for z in erg["annahmen"])
    vk = {n: z["haendler_vk"] for n, z in erg["szenarien"].items()}
    assert vk["vorsichtig"] < vk["erwartet"] < vk["guenstig"]                                 # QA B2: Szenarien fallen nicht zusammen


# ---------------------------------------------------------------- 4. Marktbeobachtung
def test_preissenkungen_rein():
    assert kal.preissenkungen([(50000, 45000)] * 3, 0.07)["hinweis"].startswith("Zu wenige")
    erg = kal.preissenkungen([(50000, 45000), (40000, 40000), (30000, 27000), (60000, 60000), (50000, 40000), (0, 1), (None, 5)], 0.07)
    assert (erg["n"], erg["mit_senkung"], erg["median"], erg["median_gesenkt"]) == (5, 3, 0.1, 0.1)
    assert "im Median um 10 %" in erg["hinweis"] and "(7 %)" in erg["hinweis"]
    assert kal.preissenkungen([(50000, 49000)] * 6, 0.07)["hinweis"] is None                  # unter dem Abschlag: kein Hinweis
    assert kal.preissenkungen([(50000, 55000)] * 5, 0.07)["median"] == 0                      # Erhöhungen zählen als 0


def _inserat(db, i, preise, gewerblich=0, offline=True):
    for preis in preise:
        db.speichere_treffer({"id": f"m{i}", "titel": f"Knaus Sky TI {i}", "preis": preis, "km": 80000, "ez_jahr": 2018,
                              "ort": "70173 Stuttgart", "gewerblich": gewerblich}, "Teilintegrierter")
    if offline:
        db.con.execute("UPDATE inserate SET verfuegbarkeit='offline' WHERE anzeigen_id=?", (f"m{i}",))
    db.con.commit()


def test_marktbeobachtung_aus_der_datenbank(cfg, db):
    for i in range(5):
        _inserat(db, i, [50000, 45000] if i < 3 else [40000])
    _inserat(db, 10, [50000, 30000], gewerblich=1)                                           # Händler zählt nicht
    _inserat(db, 11, [50000, 30000], offline=False)                                          # noch aktiv: zählt nicht
    m = kal.KalibrierungSpeicher(db).marktbeobachtung(cfg)
    assert (m["n"], m["mit_senkung"], m["median"]) == (5, 3, 0.1) and m["hinweis"]
    spaeter = kal.KalibrierungSpeicher(db).marktbeobachtung(cfg, jetzt=datetime.now() + timedelta(days=400))
    assert spaeter["n"] == 6                                                                 # lange nicht gesehen gilt als verschwunden


def test_api_seite_cli(server, db, cfg, capsys):
    for i in range(5):
        _inserat(db, i, [50000, 45000])
    c = lokal(server)
    d = c("GET", "/api/kalibrierung")[1]
    assert d["markt"]["n"] == 5 and d["markt"]["median"] == 0.1
    assert "data-markt" in (BASIS / "vorlagen" / "kalibrierung.html").read_text(encoding="utf-8")
    import scout
    scout.cmd_kalibrierung(cfg, db, SimpleNamespace())
    aus = capsys.readouterr().out
    assert "Marktbeobachtung: 5 verschwundene Privatinserate mit Preisverlauf, 5 gesenkt, Senkung im Median 10%" in aus


def test_oberflaeche(server, db):
    jahr = date.today().year - 8
    for i in range(5):
        db.speichere_treffer({"id": f"p{i}", "titel": f"Knaus Sky TI privat {i}", "preis": 40000 + i * 300, "km": 60000 + i * 7000, "ez_jahr": jahr,
                              "ort": "70173 Stuttgart"}, "Teilintegrierter")
        db.speichere_treffer({"id": f"g{i}", "titel": f"Knaus Sky TI Händler {i}", "preis": 42000 + i * 300, "km": 63500 + i * 7000, "ez_jahr": jahr,
                              "ort": "70173 Stuttgart", "gewerblich": 1}, "Teilintegrierter")
    db.speichere_treffer({"id": "z1", "titel": "Knaus Sky TI privat", "preis": 30000, "km": 100000, "ez_jahr": jahr, "ort": "70173 Stuttgart"},
                         "Teilintegrierter")
    db.con.commit()
    c = lokal(server)
    d = c("GET", "/api/fahrzeug/z1")[1]["bewertung"]
    assert d["haendler_anzahl"] >= 3 and d["haendler_niveau"] and d["vk_gedeckelt"]
    html = c("GET", "/")[1]
    detail = re.search(r'<section id="dz1".*?</section>', html, re.S).group(0)
    assert "data-haendlermarkt" in detail and "Händler-VK darauf begrenzt" in detail and "begrenzt auf den Händlermarkt" in detail
    js = (BASIS / "wmscout" / "web" / "static" / "mobil.js").read_text(encoding="utf-8")
    sw = (BASIS / "wmscout" / "web" / "static" / "sw.js").read_text(encoding="utf-8")
    assert 'data-haendlermarkt=""' in js and int(re.search(r"var VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 18 and "18: " in sw


def test_marktbeobachtung_je_fahrzeug(cfg, db):
    """QA P5-04 B3: wieder eingestellt (altes Inserat offline, neues aktiv) zählt nicht; zwei verschwundene Inserate desselben Fahrzeugs
    einmal, mit dem ersten Preis des ersten und dem letzten Preis des letzten Inserats."""
    for i in range(5):
        _inserat(db, i, [50000, 50000])
    _inserat(db, 20, [50000, 46000])
    _inserat(db, 21, [44000], offline=False)                                                 # dasselbe Fahrzeug, noch aktiv
    _inserat(db, 30, [60000])
    _inserat(db, 31, [54000])                                                                # dasselbe Fahrzeug auf zweiter Plattform
    fid = {z[0]: z[1] for z in db.con.execute("SELECT anzeigen_id, fahrzeug_id FROM inserate")}
    db.con.execute("UPDATE inserate SET fahrzeug_id=? WHERE anzeigen_id='m21'", (fid["m20"],))
    db.con.execute("UPDATE inserate SET fahrzeug_id=? WHERE anzeigen_id='m31'", (fid["m30"],))
    db.con.commit()
    m = kal.KalibrierungSpeicher(db).marktbeobachtung(cfg)
    assert (m["n"], m["mit_senkung"], m["median_gesenkt"]) == (6, 1, 0.1)                    # 5 + Fahrzeug 30/31 (60.000 → 54.000)


def test_datenkonflikt_sichtbar(r):
    b = r.bewerte(FZ, _privat() + _haendler(3, 42000))
    assert b.haendler_konflikt and not b.vk_gedeckelt and b.haendler_niveau
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    js = (BASIS / "wmscout" / "web" / "static" / "mobil.js").read_text(encoding="utf-8")
    assert "b.haendler_konflikt" in html and "b.haendler_konflikt" in js
