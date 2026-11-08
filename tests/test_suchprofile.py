"""P4-01 (ADR-047): Suchprofile als Filter über eingegangene Daten und Abdeckungscheckliste je Plattform (Schema v17).

Geprüft: Eingabeprüfung, Zuordnung passt/unklar/nein je Kriterium, Abdeckung (fehlt/angelegt/prüfen/nicht lesbar), Speicher, API (Filter,
Pflege nur Inhaber, Händler gesperrt, Audit), Oberfläche und Migration gegen Altbestände. Alles offline; kein Profil ruft etwas ab.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from tests.daten import BASIS, FakeAbruf, baue_ads
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_migration import pruefsumme, versionen
from tests.test_team_bearbeitung import anmelden, lokal, server, starte  # noqa: F401 – Fixtures
from tests.test_vorfilter import baue_v15
from wmscout import migrationen
from wmscout import suchprofile as sp
from wmscout.audit import einordnen
from wmscout.haendler import HaendlerSpeicher
from wmscout.importer import Importer
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.sicherung import sicherungen
from wmscout.team import TeamSpeicher

JETZT = datetime(2026, 10, 24, 12, 0)
STATIC = BASIS / "wmscout" / "web" / "static"


def profil(**kw) -> dict:
    return sp.pruefe_profil({"name": "Knaus TI", **kw}, JETZT)


def inserat(**kw) -> dict:
    return {"id": "a", "marke": "Knaus", "modell": "Sky TI", "fahrzeug": "Knaus Sky TI", "titel": "Knaus Sky TI 650", "preis": 40000,
            "ez_jahr": 2016, "km": 90000, **kw}


# ---------------------------------------------------------------- 1. Eingaben
def test_profil_wird_normalisiert():
    p = profil(name="  Knaus   TI ", arten=["Alkoven", "Teilintegrierter", "Alkoven"], marken=["knaus", " Knaus", "Hymer"], modell="  Sky  TI ",
               preis_min=10000, preis_max=50000, ez_min=2010, ez_max=2020, km_max=150000, notiz="x")
    assert p == {"name": "Knaus TI", "aktiv": True, "arten": ["Teilintegrierter", "Alkoven"], "marken": ["Hymer", "Knaus"], "modell": "Sky TI",
                 "preis_min": 10000, "preis_max": 50000, "ez_min": 2010, "ez_max": 2020, "km_max": 150000, "notiz": "x",
                 "gebiet": "bundesweit", "gebiet_plz": None, "gebiet_radius_km": None, "gebiet_regionen": []}      # Suchgebiet: P4-02
    assert profil(preis_min="", modell="")["preis_min"] is None and profil()["arten"] == [] and profil(aktiv=False)["aktiv"] is False


@pytest.mark.parametrize("daten, fehler", [
    ({"name": ""}, "Name fehlt"), ({"name": "x" * 81}, "höchstens 80"), ({"name": 5}, "Text"),
    ({"name": "a", "arten": ["Bus"]}, "arten"), ({"name": "a", "arten": "Alkoven"}, "arten"),
    ({"name": "a", "marken": "Knaus"}, "marken"), ({"name": "a", "marken": [""]}, "marken"), ({"name": "a", "marken": ["x"] * 31}, "marken"),
    ({"name": "a", "preis_min": True}, "Preis von"), ({"name": "a", "preis_max": -1}, "Preis bis"), ({"name": "a", "preis_min": 1.5}, "Preis von"),
    ({"name": "a", "preis_min": 50000, "preis_max": 40000}, "„von“ ist größer"), ({"name": "a", "ez_min": 1950}, "EZ von"),
    ({"name": "a", "ez_max": 2028}, "EZ bis"), ({"name": "a", "ez_min": 2020, "ez_max": 2010}, "EZ"), ({"name": "a", "km_max": "viel"}, "km bis"),
    ({"name": "a", "aktiv": "ja"}, "aktiv"), ({"name": "a", "notiz": "x" * 501}, "Notiz"),
], ids=lambda x: str(x)[:40])
def test_ungueltige_profile(daten, fehler):
    with pytest.raises(sp.Eingabefehler, match=fehler):
        sp.pruefe_profil(daten, JETZT)
    with pytest.raises(sp.Eingabefehler):
        sp.pruefe_profil(["kein", "objekt"], JETZT)


def test_auftrag_pruefen():
    assert sp.pruefe_auftrag({"plattform": "mobile.de", "angelegt": True, "url": "https://suchen.mobile.de/x"}) == {
        "plattform": "mobile.de", "angelegt": True, "url": "https://suchen.mobile.de/x"}                     # ohne Notiz: bleibt erhalten
    assert sp.pruefe_auftrag({"plattform": "mobile.de", "notiz": " a "})["notiz"] == "a"
    for falsch in ({"plattform": "ebay"}, {"plattform": "mobile.de", "angelegt": "ja"}, {"plattform": "mobile.de", "url": "javascript:alert(1)"},
                   {"plattform": "mobile.de", "url": "ftp://x"}, {"plattform": "mobile.de", "url": "http://a b"},
                   {"plattform": "mobile.de", "url": "https://x\njavascript:"}, {"plattform": "autoscout24", "angelegt": True}, "x"):
        with pytest.raises(sp.Eingabefehler):
            sp.pruefe_auftrag(falsch)


# ---------------------------------------------------------------- 2. Zuordnung
def test_ohne_kriterien_passt_alles():
    assert sp.pruefe_inserat(profil(), inserat(), "Teilintegrierter") == ("passt", [])
    assert sp.pruefe_inserat(profil(), inserat(preis=None, marke=None), None) == ("passt", [])


@pytest.mark.parametrize("kw, a, art, urteil", [
    ({"arten": ["Alkoven"]}, {}, "Teilintegrierter", "nein"), ({"arten": ["Alkoven"]}, {}, "Sonstige", "unklar"),
    ({"arten": ["Alkoven"]}, {}, "Alkoven", "passt"),
    ({"marken": ["Hymer"]}, {}, "x", "nein"), ({"marken": ["knaus"]}, {}, "x", "passt"), ({"marken": ["Knaus"]}, {"marke": None}, "x", "unklar"),
    ({"modell": "sky ti"}, {}, "x", "passt"), ({"modell": "Van"}, {}, "x", "nein"),
    ({"modell": "ti"}, {"modell": "B 544", "fahrzeug": "Hymer B 544", "titel": "Hymer B 544 Automatik"}, "x", "nein"),
    ({"modell": "ti 650"}, {}, "x", "passt"),
    ({"preis_max": 39999}, {}, "x", "nein"), ({"preis_min": 40000, "preis_max": 40000}, {}, "x", "passt"), ({"preis_max": 1}, {"preis": None}, "x", "unklar"),
    ({"ez_min": 2017}, {}, "x", "nein"), ({"ez_max": 2016}, {}, "x", "passt"), ({"ez_min": 2010}, {"ez_jahr": None}, "x", "unklar"),
    ({"km_max": 89999}, {}, "x", "nein"), ({"km_max": 90000}, {}, "x", "passt"), ({"km_max": 1}, {"km": None}, "x", "unklar"),
    ({"km_max": 1, "marken": ["Hymer"]}, {"km": None}, "x", "nein"),                   # „nein“ schlägt „unklar“
    ({"preis_max": 50000}, {"preis": True}, "x", "unklar"),
], ids=lambda x: str(x)[:30])
def test_zuordnung(kw, a, art, urteil):
    ergebnis, gruende = sp.pruefe_inserat(profil(**kw), inserat(**a), art)
    assert ergebnis == urteil and (urteil == "passt") == (gruende == [])


# ---------------------------------------------------------------- 3. Abdeckung
def test_abdeckung_je_plattform():
    frisch, alt = (JETZT - timedelta(days=2)).isoformat(), (JETZT - timedelta(days=20)).isoformat()
    a = sp.abdeckung(profil(), {"kleinanzeigen": {"angelegt": 1, "url": "https://k.invalid"}, "mobile.de": {"angelegt": 1},
                               "autoscout24": {"angelegt": 1}}, {"kleinanzeigen": frisch, "mobile.de": alt}, JETZT)
    z = {x["plattform"]: x["zustand"] for x in a["plattformen"]}
    assert z == {"kleinanzeigen": "angelegt", "mobile.de": "pruefen", "autoscout24": "nicht_lesbar"} and a["quote"] == 1.0
    leer = sp.abdeckung(profil(), {}, {}, JETZT)
    assert {x["zustand"] for x in leer["plattformen"] if x["plattform"] != "autoscout24"} == {"fehlt"} and leer["quote"] == 0.0
    assert sp.abdeckung(profil(), {"mobile.de": {"angelegt": 1}}, {}, JETZT)["plattformen"][1]["zustand"] == "pruefen"   # nie ein Treffer


# ---------------------------------------------------------------- 4. Speicher
def test_speicher(db):
    s = sp.SuchprofilSpeicher(db)
    pid = s.anlegen(profil(marken=["Knaus"]))
    with pytest.raises(sp.Eingabefehler, match="gibt es schon"):
        s.anlegen(profil(name="knaus ti"))
    zweit = s.anlegen(profil(name="Hymer"))
    with pytest.raises(sp.Eingabefehler, match="gibt es schon"):
        s.aendern(zweit, profil(name="KNAUS TI"))
    assert s.aendern(pid, profil(marken=["Hymer"], aktiv=False)) and s.profil(pid)["marken"] == ["Hymer"] and s.profil(pid)["aktiv"] is False
    assert [p["name"] for p in s.liste()] == ["Hymer", "Knaus TI"] and [p["name"] for p in s.liste(nur_aktive=True)] == ["Hymer"]
    assert s.setze_auftrag(pid, sp.pruefe_auftrag({"plattform": "mobile.de", "angelegt": True}))
    assert s.setze_auftrag(pid, sp.pruefe_auftrag({"plattform": "mobile.de", "angelegt": False, "notiz": "pausiert"}))
    assert s.auftraege(pid)["mobile.de"]["angelegt"] == 0 and s.auftraege(pid)["mobile.de"]["notiz"] == "pausiert"
    assert s.setze_auftrag(pid, sp.pruefe_auftrag({"plattform": "mobile.de", "angelegt": True}))               # wie die Oberfläche: ohne Notiz
    assert s.auftraege(pid)["mobile.de"]["angelegt"] == 1 and s.auftraege(pid)["mobile.de"]["notiz"] == "pausiert"
    assert s.setze_auftrag(999, sp.pruefe_auftrag({"plattform": "mobile.de"})) is False
    assert s.loeschen(pid) and s.profil(pid) is None and s.auftraege(pid) == {} and s.loeschen(pid) is False


# ---------------------------------------------------------------- 5. API
def test_api_anlegen_filtern_checkliste_loeschen(server, db, importiert):
    c = lokal(server)
    alle = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
    marke = alle[0]["fahrzeug"].split()[0]
    s, d, _ = c("POST", "/api/suchprofile", {"name": "Test", "marken": [marke]})
    assert s == 200 and d["ok"]
    pid = d["id"]
    assert c("POST", "/api/suchprofile", {"name": "test"})[0] == 400                                 # Name doppelt
    assert c("POST", "/api/suchprofile", {"name": "x", "preis_min": "viel"})[0] == 400
    liste = c("GET", "/api/suchprofile")[1]
    (p,) = liste["profile"]
    erwartet = {f["id"] for f in alle if f["fahrzeug"].split()[0] == marke}
    assert p["treffer"]["passt"] == len(erwartet) > 0 and liste["darf_aendern"] is True and liste["mit_eingang"] == ["kleinanzeigen", "mobile.de"]
    assert {z["plattform"]: z["zustand"] for z in p["abdeckung"]["plattformen"]}["kleinanzeigen"] == "fehlt"
    gefiltert = c("GET", f"/api/fahrzeuge?filter=alle&verfuegbar=alle&profil={pid}")[1]
    assert {f["id"] for f in gefiltert} == erwartet and {f["profil_treffer"] for f in gefiltert} == {"passt"}
    assert c("GET", "/api/fahrzeuge?filter=alle&profil=999")[0] == 400 and c("GET", "/api/fahrzeuge?filter=alle&profil=abc")[0] == 400
    assert c("GET", "/api/fahrzeuge?filter=alle&profil=%C2%B2")[0] == 400                                     # „²“ ist isdigit(), aber keine Zahl
    assert c("GET", f"/api/suchprofil/{pid}/treffer")[1]["treffer"] == {f["id"]: "passt" for f in gefiltert}
    assert c("GET", "/api/suchprofil/999/treffer")[0] == 404
    assert c("POST", f"/api/suchprofil/{pid}/auftrag", {"plattform": "kleinanzeigen", "angelegt": True, "url": "https://www.kleinanzeigen.de/s-x"})[0] == 200
    p = c("GET", "/api/suchprofile")[1]["profile"][0]
    k = next(z for z in p["abdeckung"]["plattformen"] if z["plattform"] == "kleinanzeigen")
    assert k["angelegt"] and k["letzter_treffer"] and k["zustand"] == "angelegt" and p["abdeckung"]["quote"] == 0.5
    assert c("POST", f"/api/suchprofil/{pid}/auftrag", {"plattform": "kleinanzeigen", "url": "javascript:x"})[0] == 400
    assert c("POST", f"/api/suchprofil/{pid}", {"name": "Test", "marken": [marke], "km_max": 1})[0] == 200
    unklar_frei = c("GET", f"/api/fahrzeuge?filter=alle&verfuegbar=alle&profil={pid}&unklar=nein")[1]
    assert len(unklar_frei) <= len(c("GET", f"/api/fahrzeuge?filter=alle&verfuegbar=alle&profil={pid}")[1])
    assert c("POST", f"/api/suchprofil/{pid}/loeschen", {})[0] == 200
    assert c("POST", f"/api/suchprofil/{pid}", {"name": "x"})[0] == 404 and c("GET", "/api/suchprofile")[1]["profile"] == []
    assert einordnen("POST", f"/api/suchprofil/{pid}/auftrag") == ("aendern", f"suchprofil:{pid}")


def test_desktop_filter_ohne_200er_grenze(cfg, db):
    """Desktop-Liste zeigt alle Zeilen; der Filter darf nicht an der 200er-Grenze von /api/fahrzeuge enden (QA B1)."""
    cfg["crawler"].update(max_seiten_pro_suche=20, detailseiten_pro_lauf=300)
    Importer(cfg, db, abruf=FakeAbruf(baue_ads(260))).lauf(cfg["suchen"])
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        pid = c("POST", "/api/suchprofile", {"name": "Alle"})[1]["id"]
        assert len(c("GET", f"/api/fahrzeuge?filter=alle&verfuegbar=alle&profil={pid}")[1]) == 200
        assert len(c("GET", f"/api/suchprofil/{pid}/treffer")[1]["treffer"]) == 260
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_rechte(server, db, importiert, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    anna, ben, hugo = anmelden(server, "Anna"), anmelden(server, "Ben"), anmelden(server, "Hugo")
    assert anna("POST", "/api/suchprofile", {"name": "Alkoven"}, token=False)[0] == 403
    pid = anna("POST", "/api/suchprofile", {"name": "Alkoven", "arten": ["Alkoven"]})[1]["id"]
    s, d, _ = ben("GET", "/api/suchprofile")
    assert s == 200 and d["darf_aendern"] is False and len(d["profile"]) == 1
    assert ben("GET", f"/api/fahrzeuge?filter=alle&profil={pid}")[0] == 200
    for pfad in ("/api/suchprofile", f"/api/suchprofil/{pid}", f"/api/suchprofil/{pid}/auftrag", f"/api/suchprofil/{pid}/loeschen"):
        assert ben("POST", pfad, {"name": "x", "plattform": "mobile.de"})[0] == 403
        assert hugo("POST", pfad, {"name": "x", "plattform": "mobile.de"})[0] == 403
    assert hugo("GET", "/api/suchprofile")[0] == 403 and hugo("GET", f"/api/suchprofil/{pid}/treffer")[0] == 403
    assert ben("GET", f"/api/suchprofil/{pid}/treffer")[0] == 200
    db.con.commit()
    eintraege = [tuple(r) for r in db.con.execute("SELECT nutzer, objekt, status FROM audit WHERE pfad LIKE '/api/suchprofil%' AND methode='POST'")]
    assert ("Anna", None, 200) in eintraege and ("Ben", f"suchprofil:{pid}", 403) in eintraege


def test_profile_aendern_keine_bewertung(server, db, importiert):
    c = lokal(server)
    vorher = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
    c("POST", "/api/suchprofile", {"name": "Alles", "km_max": 1})
    assert c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1] == vorher


# ---------------------------------------------------------------- 6. Oberfläche
def test_oberflaeche_statisch():
    js, html, mobil = ((STATIC / "suchprofile.js").read_text(encoding="utf-8"), (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8"),
                       (STATIC / "mobil.js").read_text(encoding="utf-8"))
    assert "innerHTML" not in js and "textContent" in js and "^https?:" in js
    assert 'src="/static/suchprofile.js"' in html and "window.scoutProfilFilter" in html and 'id="suchprofile-box"' in html
    assert html.index('src="/static/suchprofile.js"') > html.index("var SCOUT =")                                  # nach dem Token
    assert "esc(p.name)" in mobil and "&profil=" in mobil
    assert int(re.search(r"var VERSION = 'wm-scout-(\d+)'", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 14


# ---------------------------------------------------------------- 7. Schema 17
def bis_17(monkeypatch):
    """Schritt 17 ist hier der letzte bekannte Schritt: die Tests prüfen ihn so, wie er zu seiner Zeit lief."""
    _alt_schritte(monkeypatch, 17)


def baue_v16(pfad, monkeypatch, tmp_path):
    baue_v15(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 16)
        assert migriere(pfad, tmp_path / "stand16") == [16]
    assert lese_version(pfad) == 16


TABELLEN = {"suchprofile", "suchauftraege"}


@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v16"])
def test_migration_auf_17_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_17(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v16":
        baue_v16(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    erledigt = migriere(pfad, ziel)
    assert erledigt[-1] == 17 and lese_version(pfad) == 17 and versionen(pfad)[-1] == 17
    neue = {t: v_ for t, v_ in vorher.items() if t != "fahrzeuge"}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    assert TABELLEN <= {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert _sql(pfad, "SELECT COUNT(*) FROM suchprofile") == [(0,)] and _sql(pfad, "PRAGMA integrity_check") == [("ok",)]
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v17" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_17_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_17(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v16(pfad, monkeypatch, tmp_path)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_17(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def test_fehler_im_schritt_17_rollt_zurueck_dann_gelingt_es(tmp_path, monkeypatch):
    bis_17(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v16(pfad, monkeypatch, tmp_path)
    vorher, echt = _abbild(pfad), migrationen._schritt_17

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 17, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 16 and _abbild(pfad) == vorher
    assert not TABELLEN & {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='table'")}
    monkeypatch.setitem(migrationen.SCHRITTE, 17, echt)
    assert migriere(pfad, ziel) == [17]


def test_neue_datenbank_hat_die_tabellen(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 17
    assert TABELLEN <= {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
