"""P6-02 – Dublettengruppen und Preisverläufe in der Ankaufsliste (ADR-062): Kurzfassung des Preisverlaufs, Gruppen über Heuristik und
bestätigte Entscheidungen (transitiv), Vertreter für „gleiches Fahrzeug nur einmal“, Desktop, API und Handy-App."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import inserat_id, treffer
from tests.test_team_bearbeitung import lokal, starte
from wmscout import preisverlauf as pv
from wmscout.ausgabe import datum_lokal, euro_diff, render_html
from wmscout.bewertung import gruppen
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.dubletten import bestaetige

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"


def _e(preis, aenderung, zeit="2026-10-01T10:00:00+00:00", diff=None):
    return {"zeitpunkt": zeit, "preis": preis, "aenderung": aenderung, "differenz": diff}


# ---------------------------------------------------------------- 1. Kurzfassung Preisverlauf (rein)
def test_kurz_ohne_eintrag_und_nur_erstpreis():
    assert pv.kurz(None) is None and pv.kurz([]) is None
    k = pv.kurz([_e(40000, "erstpreis"), _e(40000, "gleich")])
    assert (k["erstpreis"], k["aktuell"], k["differenz"], k["prozent"], k["senkungen"], k["erhoehungen"]) == (40000, 40000, 0, 0, 0, 0)
    assert len(k["punkte"]) == 1                                                       # wiederholt gleicher Preis ist kein Preisstand


def test_kurz_zaehlt_aenderungen_rundet_prozent():
    k = pv.kurz([_e(40000, "erstpreis", "2026-09-01T08:00:00+00:00"), _e(38500, "gesenkt", diff=-1500), _e(38500, "gleich"),
                 _e(39000, "erhoeht", diff=500), _e(37900, "gesenkt", "2026-10-20T08:00:00+00:00", diff=-1100)])
    assert (k["erstpreis"], k["aktuell"], k["differenz"], k["prozent"]) == (40000, 37900, -2100, -5)       # −5,25 % → ganzzahlig
    assert (k["senkungen"], k["erhoehungen"], k["seit"][:10], k["zuletzt"][:10]) == (2, 1, "2026-09-01", "2026-10-20")
    assert [p["preis"] for p in k["punkte"]] == [40000, 38500, 39000, 37900] and k["gekuerzt"] is False


def test_kurz_kuerzt_auf_die_juengsten_preisstaende():
    v = [_e(50000, "erstpreis")] + [_e(50000 - 100 * i, "gesenkt", diff=-100) for i in range(1, 20)]
    k = pv.kurz(v)
    assert k["gekuerzt"] and len(k["punkte"]) == pv.PUNKTE_MAX and k["punkte"][-1]["preis"] == 48100 and k["erstpreis"] == 50000
    assert pv.kurz([{"aenderung": "erstpreis", "preis": None, "zeitpunkt": None}]) is None


def test_filter_euro_diff_und_datum():
    assert (euro_diff(-3500), euro_diff(500), euro_diff(0), euro_diff(None)) == ("−3.500 €", "+500 €", "±0 €", "–")
    assert re.fullmatch(r"\d\d\.10\.2026", datum_lokal("2026-10-15T12:00:00+00:00")) and datum_lokal("kaputt") == "–" and datum_lokal(None) == "–"


# ---------------------------------------------------------------- 2. Gruppen und Vertreter (rein)
def _z(i, dub=(), score=None, status=None, ausblenden=False, verh=0.9, arbeit=False):
    return {"a": {"id": i, "status": status, "hat_arbeit": arbeit}, "b": SimpleNamespace(verhaeltnis=verh), "dubletten_ids": list(dub),
            "deal": {"score": score}, "ausblenden": ausblenden}


def test_vertreter_reihenfolge():
    """Sichtbar vor ausgeblendet, offene Arbeit zuerst, verworfene zuletzt, dann Deal-Score (ohne Score zuletzt), Preis ÷ Max-EK."""
    zeilen = [_z("a", score=90, ausblenden=True), _z("b", score=30, status="kontaktiert"), _z("c", score=70), _z("d"), _z("e", score=70, verh=0.8),
              _z("f", score=99, status="uninteressant"), _z("g", score=10, arbeit=True)]
    gruppen.ordne(zeilen)
    assert [z["a"]["id"] for z in sorted(zeilen, key=lambda z: z["gruppe_rang"])] == ["b", "g", "e", "c", "d", "f", "a"]
    assert {z["a"]["id"]: z["gruppe_arbeit"] for z in zeilen} == {"a": False, "b": True, "c": False, "d": False, "e": False, "f": False, "g": True}


def test_nur_einmal_eine_stufe_keine_kette():
    """QA B1: Kette A~B~C (A und C ausdrücklich verschieden, also nicht in den dubletten_ids): B entfällt wegen A, C bleibt sichtbar."""
    zeilen = [_z("a", ["b"], 90), _z("b", ["a", "c"], 60), _z("c", ["b"], 40), _z("d", [], 10)]
    gruppen.ordne(zeilen)
    assert gruppen.nur_einmal(zeilen) == {"a", "c", "d"}
    assert gruppen.nur_einmal([z for z in zeilen if z["a"]["id"] != "a"]) == {"b", "d"}          # ohne A (gefiltert) vertritt B


def test_nur_einmal_versteckt_keine_arbeit():
    """QA B2: zwei Mitglieder mit Arbeit – beide bleiben; ein unbearbeitetes drittes entfällt."""
    zeilen = [_z("a", ["b", "c"], 50, status="kontaktiert"), _z("b", ["a", "c"], 40, arbeit=True), _z("c", ["a", "b"], 95)]
    gruppen.ordne(zeilen)
    assert gruppen.nur_einmal(zeilen) == {"a", "b"}


# ---------------------------------------------------------------- 3. Mit Datenbank: Bewertung, API, Oberflächen
@pytest.fixture
def gruppe_db(cfg, db):
    db.speichere_treffer(treffer("p1"), "Alkoven")
    db.speichere_treffer(treffer("p2", ort="80331 München", km=91000, url="javascript:alert(1)"), "Alkoven")
    db.speichere_treffer(treffer("p3", preis=41000, titel="Knaus Sky TI 650 MEG <b>x</b>"), "Alkoven")
    db.speichere_treffer(treffer("x1", titel="Hymer B 544", marke="Hymer", ez_jahr=2012), "Alkoven")
    for preis in (38500, 38500, 37900):
        db.speichere_treffer(treffer("p1", preis=preis), "Alkoven")
    bestaetige(db, inserat_id(db, "p1"), inserat_id(db, "p2"), None)
    return db


def test_bewertung_liefert_gruppe_und_preisverlauf(cfg, gruppe_db):
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, gruppe_db, BASIS)}
    assert sorted(x["gruppe_rang"] for x in z.values()) == [0, 1, 2, 3] and z["p1"]["fahrzeug_status"] == "neu"
    assert {(m["id"], m["bestaetigt"]) for m in z["p1"]["gruppe"]} == {("p2", True), ("p3", False)}
    assert {(m["id"], m["bestaetigt"]) for m in z["p3"]["gruppe"]} == {("p1", False), ("p2", False)}
    assert z["x1"]["gruppe"] == [] and z["p1"]["gruppe"][0]["quelle_text"] == "Kleinanzeigen"
    p = z["p1"]["preisverlauf"]
    assert (p["erstpreis"], p["aktuell"], p["senkungen"], p["differenz"]) == (40000, 37900, 2, -2100)
    m3 = next(m for m in z["p1"]["gruppe"] if m["id"] == "p3")
    assert m3["preis"] == 41000 and m3["preisverlauf"]["senkungen"] == 0 and m3["status"] == "neu"


def test_api_felder_und_einmal(cfg, gruppe_db):
    srv = starte(cfg, gruppe_db)
    try:
        c = lokal(srv)
        alle = c("GET", "/api/fahrzeuge?filter=alle")[1]
        einmal = c("GET", "/api/fahrzeuge?filter=alle&einmal=ja")[1]
        ids = [f["id"] for f in alle]
        assert {"p1", "p2", "p3", "x1"} <= set(ids)
        gruppe = [f for f in einmal if f["id"] in ("p1", "p2", "p3")]
        zeilen = {z["a"]["id"]: z for z in bewerte_alle(cfg, gruppe_db, BASIS)}
        vertreter = min(("p1", "p2", "p3"), key=lambda i: zeilen[i]["gruppe_rang"])
        assert [f["id"] for f in gruppe] == [vertreter] and "x1" in [f["id"] for f in einmal]
        assert len(einmal) == len(alle) - 2
        f1 = next(f for f in alle if f["id"] == "p1")
        assert len(f1["gruppe"]) == 2 and f1["preisverlauf"]["aktuell"] == 37900 and f1["fahrzeug_status"] == "neu"
        # nach einem Filter vertritt der beste der verbliebenen: p2 steht als einziges in München
        such = c("GET", "/api/fahrzeuge?filter=alle&einmal=ja&q=m%C3%BCnchen")[1]
        assert [f["id"] for f in such if f["id"] in ("p1", "p2", "p3")] == ["p2"]
        # Arbeit wird nie versteckt (QA B2)
        assert c("POST", "/api/status", {"id": "p3", "status": "kontaktiert", "text": "Hallo"})[0] == 200
        assert c("POST", "/api/status", {"id": "p2", "status": "verhandlung", "text": "Hallo", "betrag": 30000})[0] == 200
        arbeit = c("GET", "/api/fahrzeuge?filter=arbeit&einmal=ja")[1]
        assert {"p2", "p3"} <= {f["id"] for f in arbeit}
        assert next(f for f in arbeit if f["id"] == "p3")["fahrzeug_status"] == "verhandlung"
        assert c("GET", "/api/fahrzeuge?filter=alle&einmal=vielleicht")[0] == 400
        d = c("GET", "/api/fahrzeug/p1")[1]
        assert d["preisverlauf"]["senkungen"] == 2 and {m["id"] for m in d["gruppe"]} == {"p2", "p3"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_desktop_karte_detail_und_escaping(cfg, gruppe_db):
    html = render_html(cfg, bewerte_alle(cfg, gruppe_db, BASIS), BASIS)[0]
    assert 'id="einmal" checked' in html and "einmal.checked" in html and 'data-dub="p2 p3"' in html and "data-grang=" in html and "data-garbeit=" in html
    assert "⧉ 3 Inserate" in html and "data-gruppe-tag" in html
    karte = re.search(r'<article[^>]*data-id="p1".*?</article>', html, re.S).group(0)
    assert "data-preisverlauf" in karte and "40.000 € → 37.900 € (−2.100 €, 2× gesenkt)" in karte
    detail = re.search(r'<section id="dp1".*?</section>', html, re.S).group(0)
    assert "data-preisverlauf-detail" in detail and "Erstpreis" in detail and "−600 €" in detail
    assert "data-gruppe-detail" in detail and "Gleiches Fahrzeug – 2 weitere Inserate" in detail
    assert "Fahrzeugstatus (höchster aller Inserate): offen" in detail and "bestätigt" in detail and "vermutet" in detail
    assert 'data-gruppe-oeffnen="p2"' in detail and 'href="javascript:' not in html                         # nur http(s) als Link
    assert "<b>x</b>" not in html                                                                            # Titel escaped
    vorlage = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "Object.assign({}, d, {gruppe: []})" in vorlage                      # Entscheidungsbox (App) zeigt die Mitglieder nicht doppelt
    assert "(−2.100 €, −5 %)" in detail                                                 # echtes Minuszeichen auch bei Prozent
    # Wechsel zu einem anderen Inserat der Gruppe ohne dlg.close() – dessen verzögertes close-Ereignis leerte das Fenster (Klicktest)
    assert "if(!dlg.open) dlg.showModal();" in vorlage and "dlg.close(); oeffne(" not in vorlage


def test_handy_app_statisch():
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    for teil in ("function gruppeTag", "function preisZeile", "function preisverlaufKarte", "function gruppeKarte", 'id="einmal"',
                 '"&einmal=" + (S.einmal === false ? "nein" : "ja")', "preisverlaufKarte(f) + gruppeKarte(f)", "gruppeTag(f)", "preisZeile(f)"):
        assert teil in js, teil
    assert "dublettenAnzeigen" not in js and "/api/dubletten" not in js and 'link(m.url) !== "#"' in js and "f.fahrzeug_status" in js
    css = (STATIC / "mobil.css").read_text(encoding="utf-8")
    assert ".tag.dub" in css and "table.verlauf" in css
    assert int(re.search(r"wm-scout-(\d+)", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 20


def test_verlaeufe_gleich_preisverlauf_je_inserat(cfg, db):
    """Die Abfrage für alle liefert je Inserat dasselbe wie ``preisverlauf`` – auch für andere Quellen und Altbestand mit leerer Quelle."""
    db.speichere_treffer(treffer("k1"), "Alkoven")
    db.speichere_treffer({**treffer("md-1"), "quelle": "mobile.de"}, "Alkoven")
    db.speichere_treffer({**treffer("md-1"), "quelle": "mobile.de", "preis": 39000}, "Alkoven")
    db.speichere_treffer(treffer("k1", preis=38000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET quelle='' WHERE id='k1'")
    db.con.commit()
    alle = pv.verlaeufe(db)
    for i in ("k1", "md-1"):
        assert alle[i] == pv.preisverlauf(db, i) and len(alle[i]) == 2, i
