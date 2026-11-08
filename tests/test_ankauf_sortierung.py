"""CampRCrawlR: synthetische Regressionen für faire, gemeinsame Rangfolgen und alte Inserate."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.daten import BASIS
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.deal_score import top_ausschluss
from wmscout.bewertung.sortierung import MODI, ankaufchance, schluessel, sortierdaten


def fall(kennung="1", preis=30000, score=80, **extra):
    a = {"id": kennung, "preis": preis, "km": 70000, "ez_jahr": 2018, "status": "neu",
         "anbieter": {"typ": "privat", "belegt": True}, "erstmals_gesehen": "2026-11-08T10:00:00",
         "datenqualitaet": {"stufe": "gut", "widersprueche": 0, "markierungen": []}, **extra}
    return {"a": a, "b": SimpleNamespace(verhaeltnis=.8, potenzial=9000, max_ek=38000, sicherheit="mittel", ampel="gruen"),
            "deal": {"score": score, "priorisiert": True}, "sperre": None, "ausblenden": False, "bereit": True}


def ids(zeilen, modus):
    return [z["a"]["id"] for z in sorted(zeilen, key=lambda z: schluessel(z, modus))]


def test_fehlende_werte_numerisch_immer_am_ende():
    ohne = fall("ohne", None, None, km=None)
    ohne["b"].potenzial = None
    klein, gross = fall("klein", 20000, 60, km=10000), fall("gross", 50000, 90, km=90000)
    klein["b"].potenzial, gross["b"].potenzial = 5000, 10000
    assert ids([ohne, gross, klein], "preis") == ["klein", "gross", "ohne"]
    assert ids([ohne, klein, gross], "preis_ab") == ["gross", "klein", "ohne"]
    assert ids([ohne, gross, klein], "km") == ["klein", "gross", "ohne"]
    assert ids([ohne, klein, gross], "score") == ["gross", "klein", "ohne"]
    assert ids([ohne, klein, gross], "potenzial") == ["gross", "klein", "ohne"]


def test_ankaufchance_privathaendler_unbekannt_und_scheingewinn():
    privat = fall("privat", score=60)
    haendler = fall("haendler", score=None, anbieter={"typ": "gewerblich", "belegt": True})
    haendler["sperre"] = "gewerblicher Anbieter"
    unbekannt = fall("unbekannt", score=50, anbieter={"typ": "unbekannt", "belegt": False})
    lueckenhaft = fall("luecke", score=100, km=None)
    lueckenhaft["b"].potenzial = 999999
    reihenfolge = ids([lueckenhaft, unbekannt, haendler, privat], "chance")
    assert reihenfolge[0] == "privat" and reihenfolge[-1] == "luecke"
    assert "haendler" in reihenfolge
    assert ids([lueckenhaft, privat], "potenzial") == ["privat", "luecke"]
    assert any("Kilometerstand" in g for g in ankaufchance(lueckenhaft)["negativ"])
    assert "Privatanbieter belegt" in ankaufchance(privat)["positiv"]


def test_veraltet_widerspruch_dublette_nicht_vor_belastbaren_angeboten():
    gut = fall("gut", score=50)
    alt = fall("alt", score=100, vermutlich_offline=True)
    konflikt = fall("konflikt", score=100, datenqualitaet={"stufe": "gut", "widersprueche": 1})
    dublette = fall("dublette", score=100, duplikat="doppelt eingestellt")
    offline = fall("offline", score=100, nicht_verfuegbar=True)
    assert ids([offline, alt, konflikt, dublette, gut], "chance") == ["gut", "konflikt", "alt", "dublette", "offline"]
    assert ankaufchance(konflikt)["belastbar"] is False
    assert top_ausschluss(konflikt["a"], konflikt["b"]) == "widersprüchliche oder unplausible Angaben"
    assert top_ausschluss(fall(km=None)["a"], gut["b"]) == "Daten unvollständig"


def test_preissenkung_neuigkeit_und_bestehende_score_reihenfolge():
    alt, gesenkt = fall("alt", preis=45000, score=30), fall("gesenkt", preis=30000, score=85)
    gesenkt["neuigkeit"] = {"senkung": {"euro": 15000}, "stufe": 0}
    assert ids([alt, gesenkt], "score") == ["gesenkt", "alt"]
    assert "Preissenkung erkannt" in ankaufchance(gesenkt)["positiv"]
    assert ids([alt, gesenkt], "prio") == ["gesenkt", "alt"]


def test_gleichstand_stabil_datum_id_und_defekte_daten():
    a, b, neu = fall("a"), fall("b"), fall("neu", erstmals_gesehen="2026-11-09T10:00:00")
    defekt = fall("defekt", erstmals_gesehen="unbekannt")
    for modus in MODI:
        assert ids([b, defekt, neu, a], modus) == ids([a, neu, b, defekt], modus)
    assert ids([a, defekt, b, neu], "neu") == ["neu", "a", "b", "defekt"]
    assert json.loads(json.dumps(sortierdaten(defekt), allow_nan=False))["neu"][-1] == "defekt"
    a["a"]["preis"] = float("nan")
    assert ids([a, b], "preis") == ["b", "a"]
    with pytest.raises(ValueError, match="Sortierung"):
        schluessel(a, "erfunden")


def test_schluessel_fuer_browser_ohne_aenderung_der_eingaben():
    zeile = fall()
    vorher = copy.deepcopy(zeile)
    daten = sortierdaten(zeile)
    assert set(daten) == set(MODI)
    assert all(tuple(daten[m]) == schluessel(zeile, m) for m in MODI)
    assert zeile == vorher
    assert schluessel(zeile, "pot") == schluessel(zeile, "potenzial")


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js nicht installiert")
def test_javascript_sortiert_echte_report_funktion_wie_python():
    """Führt die echte Browser-Sortierfunktion mit Karten aus, nicht eine Testkopie des Algorithmus."""
    html = (BASIS / "vorlagen/report.html").read_text(encoding="utf-8")
    funktion = html.split("  function sortiere(){", 1)[1].split("  document.querySelectorAll('.bar button[data-f]')", 1)[0]
    funktion = "function sortiere(){" + funktion
    gut = fall("gut", score=60)
    haendler = fall("haendler", score=None, anbieter={"typ": "gewerblich", "belegt": True})
    fehlt = fall("fehlt", None, score=None, km=None)
    alt = fall("alt", score=95, vermutlich_offline=True, erstmals_gesehen="2026-08-01")
    konflikt = fall("konflikt", score=99, datenqualitaet={"widersprueche": 1})
    senkung = fall("senkung", preis=20000, score=85)
    senkung["neuigkeit"] = {"senkung": {"euro": 5000}, "stufe": 0}
    dublette = fall("dublette", score=98, duplikat="doppelt eingestellt")
    unbekannt = fall("unbekannt", score=80, anbieter={"typ": "unbekannt", "belegt": False})
    gleich_a, gleich_b = fall("gleich-a"), fall("gleich-b")
    liste = [fehlt, dublette, unbekannt, gleich_b, haendler, senkung, alt, konflikt, gleich_a, gut]
    daten = [{"id": z["a"]["id"], "sortierung": json.dumps(sortierdaten(z))} for z in liste]
    skript = ("const fs=require('fs'), d=JSON.parse(fs.readFileSync(0,'utf8')); let modus, result={};"
              "const document={getElementById: id => ({value: modus})};"
              "const liste={insertBefore:()=>{}}; let karten;" + funktion
              + "for(modus of d.modi){karten=d.daten.map(dataset=>({dataset})); sortiere();"
              "result[modus]=karten.map(k=>k.dataset.id);} console.log(JSON.stringify(result));")
    r = subprocess.run(["node", "-e", skript], input=json.dumps({"daten": daten, "modi": list(MODI)}),
                       text=True, capture_output=True, timeout=15)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {m: ids(liste, m) for m in MODI}
    assert "z.ankaufchance.text" in html and "data-chance" in html


def test_alte_inserate_bleiben_mit_verfuegbarkeitsmarkierung_sichtbar(cfg, db):
    alt = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    db.speichere_treffer({"id": "alt", "titel": "Knaus Sky TI", "url": "https://www.kleinanzeigen.de/s-anzeige/alt/123-220-1",
                         "preis": 30000, "ez_jahr": 2018, "km": 70000, "gewerblich": 0, "ort": "74321 Bietigheim"}, "Teilintegrierter")
    db.con.execute("UPDATE anzeigen SET erstmals_gesehen=?, zuletzt_gesehen=? WHERE id='alt'", (alt, alt))
    db.con.execute("UPDATE inserate SET zuletzt_bestaetigt=?", (alt,))
    db.con.commit()
    assert db.aktive() == []                 # alte API für bewusst zeitbegrenzte Abfragen bleibt
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert len(zeilen) == 1 and zeilen[0]["a"]["id"] == "alt"
    assert zeilen[0]["a"]["vermutlich_offline"] is True
    assert zeilen[0]["ausblenden"] is False
    assert zeilen[0]["ankaufchance"]["stufe"] >= 3
    assert "sortierung" in zeilen[0]
