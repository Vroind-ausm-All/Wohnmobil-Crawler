"""P5-01 – Kalibrierung des Rechners mit tatsächlichen Ankäufen (ADR-052): Eingabeprüfung, Fälle aus Ankäufen und Nachträgen, Bericht mit
Vorschlägen (erst ab genug Fällen, nie automatisch), Speicher, API mit Rechten, Seite, CLI und Schema v20."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.daten import lade_cfg
from tests.test_ankauf import _kauf
from tests.test_haendler import HaendlerSpeicher
from tests.test_migration import pruefsumme, versionen
from tests.test_statusseite import baue_v18
from tests.test_team_bearbeitung import anmelden, lokal, server, team  # noqa: F401 – Fixtures
from wmscout import migrationen
from wmscout.bewertung import kalibrierung as kal
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.sicherung import sicherungen
from wmscout.team import TeamSpeicher

HEUTE = date(2026, 10, 25)
FALL = {"fahrzeug": "Knaus Sky TI 650", "marke": "knaus", "art": "Teilintegrierter", "ez_jahr": 2018, "km": 80000, "plz": "80331",
        "ankauf_am": "2025-10-25", "ankauf_preis": 34000}
P = kal.parameter(lade_cfg())
PLAN = {"haendler_vk": 40000, "kosten": 4000, "max_ek": 28000, "gewinn": 5000, "standzeit_tage": 90, "differenzbesteuerung": True}


# ---------------------------------------------------------------- 1. Eingabe
def test_pruefe_fall_gueltig():
    f = kal.pruefe_fall({**FALL, "notiz": "  mit   Markise ", "verkauf_am": "2026-01-24", "verkauf_preis": 50000, "kosten": 0}, HEUTE)
    assert f["marke"] == "Knaus" and f["notiz"] == "mit Markise" and f["kosten"] == 0 and f["modell"] is None
    assert set(f) == set(kal.KalibrierungSpeicher._SPALTEN)
    assert kal.pruefe_fall({"art": "Alkoven", "ez_jahr": 2010, "ankauf_am": "2026-10-25", "ankauf_preis": 1, "plz": ""}, HEUTE)["plz"] is None


@pytest.mark.parametrize("aenderung, text", [
    ({"art": "Boot"}, "art"),
    ({"ez_jahr": None}, "EZ fehlt"),
    ({"ez_jahr": "2018"}, "EZ muss"),
    ({"ez_jahr": True}, "EZ muss"),
    ({"ez_jahr": 2028}, "EZ muss"),
    ({"ankauf_preis": 0}, "Kaufpreis"),
    ({"ankauf_preis": 1.5}, "Kaufpreis"),
    ({"ankauf_preis": None}, "Kaufpreis fehlt"),
    ({"ankauf_am": "2026-10-26"}, "Kaufdatum"),
    ({"ankauf_am": "25.10.2025"}, "Kaufdatum"),
    ({"ankauf_am": "1999-12-31"}, "Kaufdatum"),
    ({"ankauf_am": "2016-01-01"}, "vor der Erstzulassung"),
    ({"plz": "99999"}, "PLZ"),
    ({"plz": 80331}, "PLZ muss Text"),
    ({"km": -1}, "km"),
    ({"verkauf_am": "2026-01-01"}, "zusammen"),
    ({"verkauf_preis": 40000}, "zusammen"),
    ({"verkauf_am": "2025-10-24", "verkauf_preis": 40000}, "vor dem Kaufdatum"),
    ({"notiz": "x" * 301}, "Notiz"),
    ({"fahrzeug": "x" * 81}, "Fahrzeug"),
])
def test_pruefe_fall_ungueltig(aenderung, text):
    with pytest.raises(kal.Eingabefehler, match=text):
        kal.pruefe_fall({**FALL, **aenderung}, HEUTE)


def test_pruefe_fall_kein_objekt():
    with pytest.raises(kal.Eingabefehler):
        kal.pruefe_fall(["x"], HEUTE)


# ---------------------------------------------------------------- 2. Fälle
def _ankauf(status="verkauft", **extra):
    return {"id": 7, "referenz": "AK-7", "status": status, "kaufpreis": 27000, "plan_json": json.dumps(PLAN), "uebergabe_am": "2026-01-01",
            "verkauft_am": "2026-05-01", "vk_preis": 42000, "erstellt_am": "2025-12-30T10:00:00", **extra}


def test_fall_aus_ankauf():
    kosten = [{"art": "aufbereitung", "betrag": 3000}, {"art": "transport", "betrag": 1500}]
    f = kal.fall_aus_ankauf(_ankauf(), kosten)
    assert (f["ref"], f["datum"], f["ek"], f["max_ek"], f["vk_plan"], f["vk"]) == ("AK-7", "2025-12-30", 27000, 28000, 40000, 42000)
    assert (f["kosten_plan"], f["kosten"], f["standzeit_plan"], f["standzeit"], f["nachgerechnet"]) == (4000, 4500, 90, 120, False)
    offen = kal.fall_aus_ankauf(_ankauf("uebergeben", vk_preis=None, verkauft_am=None), kosten)
    assert offen["vk"] is None and offen["kosten"] is None and offen["standzeit"] is None and offen["ek"] == 27000
    assert kal.fall_aus_ankauf(_ankauf("storniert"), kosten) is None
    assert kal.fall_aus_ankauf(_ankauf(), [])["kosten"] is None          # verkauft ohne erfasste Kosten: unbekannt, nicht 0 (QA B4)
    assert f["parameter"] is None and kal.fall_aus_ankauf(_ankauf(plan_json=json.dumps({**PLAN, "parameter": P})), kosten)["parameter"] == P


def test_fall_aus_manuell_zum_kaufdatum(cfg):
    f = {**kal.pruefe_fall({**FALL, "verkauf_am": "2026-01-24", "verkauf_preis": 50000, "kosten": 5000}, HEUTE), "id": 3}
    m = kal.fall_aus_manuell(f, cfg)
    assert m["ref"] == "M-3" and m["quelle"] == "manuell" and m["nachgerechnet"] and m["sicherheit"] == "niedrig"
    assert m["standzeit"] == 91 and m["standzeit_plan"] == (3 + 2) * 30 and m["kosten"] == 5000          # Kauf im Oktober: +2 Monate (P5-05)
    assert m["max_ek"] > 0 and m["vk_plan"] > m["max_ek"] and m["kosten_plan"] > 0
    spaeter = kal.fall_aus_manuell({**f, "ankauf_am": "2026-10-25"}, cfg)            # ein Jahr älter → weniger wert
    assert spaeter["vk_plan"] < m["vk_plan"]
    ohne_verkauf = kal.fall_aus_manuell({**f, "verkauf_am": None, "verkauf_preis": None}, cfg)
    assert ohne_verkauf["kosten"] is None and ohne_verkauf["standzeit"] is None and ohne_verkauf["vk"] is None
    assert m["parameter"] == kal.parameter(cfg)
    alt = kal.fall_aus_manuell({**f, "ankauf_am": "2019-06-01"}, cfg)          # weit zurück: deutlich jüngeres Fahrzeug, höherer Plan
    assert alt["vk_plan"] > 1.2 * spaeter["vk_plan"] and alt["max_ek"] > m["max_ek"]


def test_fall_aus_manuell_ohne_heutige_vergleichsangebote(db, cfg, importiert):
    """QA B1: heutige Angebote eines EZ-Jahrgangs wären für ein früheres Kaufdatum zu alt bewertet – nachgerechnet wird nur mit dem Modell."""
    s = kal.KalibrierungSpeicher(db)
    fid = s.anlegen(kal.pruefe_fall({**FALL, "ankauf_am": "2019-06-01"}, HEUTE), None)
    gespeichert = {**s.manuelle()[0]}
    assert [x for x in s.faelle(cfg) if x["ref"] == f"M-{fid}"] == [kal.fall_aus_manuell(gespeichert, cfg)]


def test_parameter_beim_ankauf_gespeichert(server, team, db, cfg):
    anna = anmelden(server, "Anna")
    fz = anna("GET", "/api/fahrzeuge?filter=bereit")[1][0]
    b = anna("POST", "/api/besichtigung", {"anzeige_id": fz["id"]})[1]
    aid = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf(18000))[1]["ankauf"]
    plan = json.loads(db.con.execute("SELECT plan_json FROM ankaeufe WHERE id=?", (aid,)).fetchone()[0])
    assert plan["parameter"] == kal.parameter(cfg) and anna("GET", f"/api/ankauf/{aid}")[1]["vergleich"]["plan"]["parameter"] == plan["parameter"]
    f = kal.KalibrierungSpeicher(db).faelle(cfg)
    assert len(f) == 1 and f[0]["parameter"] == plan["parameter"] and f[0]["ek"] == 18000


# ---------------------------------------------------------------- 3. Bericht
def _fall(ek=30000, max_ek=30000, vk=None, vk_plan=40000, kosten=None, kosten_plan=4000, standzeit=None, nachgerechnet=False, parameter=P):
    return {"quelle": "manuell" if nachgerechnet else "ankauf", "ref": "x", "datum": "2026-01-01", "ek": ek, "max_ek": max_ek, "vk_plan": vk_plan,
            "vk": vk, "kosten_plan": kosten_plan, "kosten": kosten, "standzeit_plan": 90, "standzeit": standzeit, "sicherheit": None,
            "nachgerechnet": nachgerechnet, "parameter": parameter}


def test_kennzahl_und_belastbarkeit():
    assert kal.kennzahl([]) is None
    assert kal.kennzahl([1, 2, 3, 4, 5]) == {"n": 5, "median": 3, "q1": 2, "q3": 4}
    assert kal.kennzahl([-400, -400, -400, 0, 0, 0])["median"] == -200            # gerade Anzahl: Mittel der beiden mittleren (QA B3)
    assert kal.kennzahl([7]) == {"n": 1, "median": 7, "q1": 7, "q3": 7}
    assert [kal.prozent(x) for x in (0.94, 1.0, 1.104)] == ["−6 %", "±0 %", "+10 %"]
    assert [kal.belastbarkeit(n) for n in (0, 2, 3, 4, 5, 9, 10)] == [
        "zu wenige Fälle – keine Aussage", "zu wenige Fälle – keine Aussage", "erste Hinweise – noch keine Vorschläge",
        "erste Hinweise – noch keine Vorschläge", "Vorschläge mit Vorsicht", "Vorschläge mit Vorsicht", "belastbar genug für Vorschläge"]


def test_bericht_ohne_faelle(cfg):
    b = kal.bericht([], cfg)
    assert b["faelle"] == 0 and b["vk_zu_plan"] is None and b["vorschlaege"] == [] and b["hinweise"] == []
    assert b["belastbarkeit"].startswith("zu wenige")


def test_bericht_vier_faelle_keine_vorschlaege(cfg):
    b = kal.bericht([_fall(vk=36000, kosten=5000, standzeit=200) for _ in range(4)], cfg)
    assert b["vk_zu_plan"]["median"] == 0.9 and b["vorschlaege"] == [] and b["belastbarkeit"].startswith("erste Hinweise")


def test_bericht_vorschlaege_ab_fuenf_faellen(cfg):
    r = cfg["rechner"]
    faelle = [_fall(ek=31000 + i * 100, vk=36000, kosten=5000, standzeit=150) for i in range(5)] + [_fall(ek=20000)]
    b = kal.bericht(faelle, cfg)
    assert b["faelle"] == 6 and b["verkauft"] == 5 and b["ueber_max_ek"] == 5 and b["ek_zu_max_ek"]["n"] == 6
    assert b["vk_zu_plan"] == {"n": 5, "median": 0.9, "q1": 0.9, "q3": 0.9} and b["kosten_abweichung"]["median"] == 1000
    vs = {v["parameter"]: v for v in b["vorschlaege"]}
    assert vs["rechner.aufschlag_haendler_vk"]["alt"] == r["aufschlag_haendler_vk"]
    a = vs["rechner.aufschlag_haendler_vk"]
    assert a["neu"] == round((1 + r["aufschlag_haendler_vk"]) * 0.9 - 1, 2) == -0.01 and "außerhalb des üblichen Bereichs" in a["warnung"]
    assert "−10 %" in a["grund"] and "abschlag_angebot_auf_privatwert von 0.07 auf 0.16" in a["alternative"]
    assert vs["rechner.kosten.aufbereitung"]["neu"] == r["kosten"]["aufbereitung"] + 1000 and "+1.000 €" in vs["rechner.kosten.aufbereitung"]["grund"]
    assert vs["rechner.kosten.aufbereitung"]["warnung"] is None
    assert vs["rechner.kosten.standzeit_monate"]["neu"] == r["kosten"]["standzeit_monate"] + 2
    assert any("über dem Max-EK" in h for h in b["hinweise"]) and b["belastbarkeit"] == "Vorschläge mit Vorsicht"
    assert all(v["faelle"] == 5 for v in b["vorschlaege"])


def test_bericht_innerhalb_toleranz_und_hinweis_nachgerechnet(cfg):
    faelle = [_fall(ek=28000, vk=41000, kosten=4200, standzeit=100, nachgerechnet=i % 2 == 0) for i in range(10)]
    b = kal.bericht(faelle, cfg)
    assert b["vorschlaege"] == [] and b["belastbarkeit"] == "belastbar genug für Vorschläge"
    assert b["hinweise"] == ["Nachgetragene Fälle sind nur mit dem Marktmodell zum Kaufdatum nachgerechnet (ohne Vergleichsangebote von damals)"]


def test_vorschlag_nach_uebernahme_nicht_erneut(cfg):
    """QA B2: der Plan der App-Ankäufe bleibt eingefroren – gerechnet wird relativ zum gespeicherten Parameterstand."""
    faelle = [_fall(vk=44000 + i * 100, kosten=5000, standzeit=150) for i in range(6)]
    vs = {v["parameter"]: v["neu"] for v in kal.bericht(faelle, cfg)["vorschlaege"]}
    assert set(vs) == {"rechner.aufschlag_haendler_vk", "rechner.kosten.aufbereitung", "rechner.kosten.standzeit_monate"}
    cfg["rechner"]["aufschlag_haendler_vk"] = vs["rechner.aufschlag_haendler_vk"]
    cfg["rechner"]["kosten"]["aufbereitung"] = vs["rechner.kosten.aufbereitung"]
    cfg["rechner"]["kosten"]["standzeit_monate"] = vs["rechner.kosten.standzeit_monate"]
    assert kal.bericht(faelle, cfg)["vorschlaege"] == []


def test_ohne_parameterstand_nicht_in_vorschlaegen(cfg):
    b = kal.bericht([_fall(vk=30000, kosten=9000, standzeit=400, parameter=None) for _ in range(6)], cfg)
    assert b["vorschlaege"] == [] and b["vk_zu_plan"]["n"] == 6
    assert any(h.startswith("6 Ankauf/Ankäufe ohne gespeicherten Parameterstand") for h in b["hinweise"])


def test_runden_und_max_ek_null(cfg):
    p = {**P, "standzeit_monate": 3}
    b = kal.bericht([_fall(standzeit=135, parameter=p) for _ in range(5)], cfg)        # 90 + 45 Tage = 4,5 Monate → 5 (QA B6)
    assert [v["neu"] for v in b["vorschlaege"]] == [5]
    b = kal.bericht([_fall(ek=20000, max_ek=0), _fall()], cfg)                           # Rechner riet ab (QA B8)
    assert b["ueber_max_ek"] == 1 and b["ek_zu_max_ek"]["n"] == 1 and any("Max-EK 0" in h for h in b["hinweise"])


def test_bericht_aendert_die_konfiguration_nicht(cfg):
    import copy
    vorher = copy.deepcopy(cfg)
    kal.bericht([_fall(vk=30000, kosten=9000, standzeit=400) for _ in range(8)], cfg)
    assert cfg == vorher


# ---------------------------------------------------------------- 4. Speicher
def _ankauf_eintragen(db, status="verkauft", kaufpreis=27000, vk=42000):
    aid = db.con.execute(
        "INSERT INTO ankaeufe (referenz, herkunft, besichtigung_id, status, kaufpreis, plan_json, uebergabe_am, verkauft_am, vk_preis, erstellt_am) "
        "VALUES (?, 'anzeige', (SELECT COALESCE(MAX(besichtigung_id), 0) + 1 FROM ankaeufe), ?, ?, ?, '2026-01-01', ?, ?, '2025-12-30T10:00:00')",
        (f"AK-{status}", status, kaufpreis, json.dumps(PLAN), "2026-05-01" if vk else None, vk)).lastrowid
    db.con.execute("INSERT INTO ankauf_kosten (ankauf_id, art, betrag, datum, erstellt_am) VALUES (?, 'aufbereitung', 3000, '2026-02-01', '2026-02-01')",
                   (aid,))
    db.con.commit()
    return aid


def test_speicher(db, cfg):
    s = kal.KalibrierungSpeicher(db)
    assert s.manuelle() == [] and s.faelle(cfg) == []
    _ankauf_eintragen(db)
    _ankauf_eintragen(db, "storniert")
    fid = s.anlegen(kal.pruefe_fall(FALL, HEUTE), 5)
    zweiter = s.anlegen(kal.pruefe_fall({**FALL, "ankauf_am": "2026-03-01"}, HEUTE), None)
    m = s.manuelle()
    assert [x["id"] for x in m] == [zweiter, fid] and m[1]["erfasst_von"] == 5 and m[1]["marke"] == "Knaus" and m[1]["erfasst_am"]
    faelle = s.faelle(cfg)
    assert [f["ref"] for f in faelle] == ["AK-verkauft", f"M-{zweiter}", f"M-{fid}"] and faelle[0]["kosten"] == 3000
    assert s.loeschen(fid) and not s.loeschen(fid) and len(s.manuelle()) == 1
    with pytest.raises(sqlite3.IntegrityError):
        s.anlegen({**kal.pruefe_fall(FALL, HEUTE), "ankauf_preis": 0}, None)               # Tabelle prüft selbst
    assert len(s.manuelle()) == 1


def test_faelle_aendern_keine_bewertung(db, cfg, importiert):
    from tests.daten import BASIS
    from wmscout.bewertung.auswertung import bewerte_alle
    vorher = [(z["a"]["id"], z["b"].max_ek) for z in bewerte_alle(cfg, db, BASIS)]
    s = kal.KalibrierungSpeicher(db)
    s.anlegen(kal.pruefe_fall(FALL, HEUTE), None)
    kal.bericht(s.faelle(cfg), cfg)
    assert [(z["a"]["id"], z["b"].max_ek) for z in bewerte_alle(cfg, db, BASIS)] == vorher


# ---------------------------------------------------------------- 5. API, Seite, CLI
def test_api_einzelplatz(server, db):
    c = lokal(server)
    s, d, _ = c("GET", "/api/kalibrierung")
    assert s == 200 and d["faelle"] == [] and d["bericht"]["faelle"] == 0 and d["manuelle"] == []
    assert c("POST", "/api/kalibrierung", FALL, token=False)[0] == 403
    s, d, _ = c("POST", "/api/kalibrierung", {**FALL, "notiz": "<img src=x onerror=alert(1)>"})
    assert s == 200 and d["ok"]
    fid = d["id"]
    s, d, _ = c("POST", "/api/kalibrierung", {**FALL, "ankauf_preis": "34000"})
    assert s == 400 and "Kaufpreis" in d["fehler"]
    assert c("POST", "/api/kalibrierung", {**FALL, "art": "Boot"})[0] == 400
    d = c("GET", "/api/kalibrierung")[1]
    assert [f["ref"] for f in d["faelle"]] == [f"M-{fid}"] and d["manuelle"][0]["notiz"].startswith("<img")
    assert d["bericht"]["hinweise"] and d["faelle"][0]["max_ek"] > 0
    s, html, _ = c("GET", "/kalibrierung")
    assert s == 200 and "Kalibrierung des Rechners" in html and "<option>Teilintegrierter</option>" in html and "|safe" not in html
    assert c("POST", f"/api/kalibrierung/{fid}/loeschen", {})[1] == {"ok": True, "id": fid}
    assert c("POST", f"/api/kalibrierung/{fid}/loeschen", {})[0] == 404
    assert c("POST", "/api/kalibrierung/abc/loeschen", {})[0] == 404
    assert c("GET", "/api/kalibrierung")[1]["manuelle"] == []


def test_api_rechte(server, db, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    anna, ben, hugo = anmelden(server, "Anna"), anmelden(server, "Ben"), anmelden(server, "Hugo")
    s, d, _ = anna("POST", "/api/kalibrierung", FALL)
    assert s == 200
    fid = d["id"]
    assert kal.KalibrierungSpeicher(db).manuelle()[0]["erfasst_von"] == team.nutzer_liste()[0]["id"]
    for c in (ben, hugo):
        assert c("GET", "/api/kalibrierung")[0] == 403 and c("GET", "/kalibrierung")[0] == 403
        assert c("POST", "/api/kalibrierung", FALL)[0] == 403 and c("POST", f"/api/kalibrierung/{fid}/loeschen", {})[0] == 403
    assert anna("GET", "/api/kalibrierung")[0] == 200 and len(kal.KalibrierungSpeicher(db).manuelle()) == 1
    assert 'href="/kalibrierung"' in anna("GET", "/ankaeufe")[1] and 'href="/kalibrierung"' not in ben("GET", "/ankaeufe")[1]
    db.con.commit()
    eintraege = [tuple(r) for r in db.con.execute("SELECT nutzer, objekt, status FROM audit WHERE pfad LIKE '/api/kalibrierung%' AND methode='POST'")]
    assert ("Anna", None, 200) in eintraege and ("Ben", f"kalibrierung:{fid}", 403) in eintraege


def test_cli(cfg, db, capsys):
    import scout
    scout.cmd_kalibrierung(cfg, db, None)
    aus = capsys.readouterr().out
    assert "Kalibrierung: 0 Fälle, davon 0 verkauft – zu wenige Fälle" in aus and "Kaufpreis gegenüber Max-EK: keine Fälle" in aus
    assert "Keine Vorschläge" in aus
    s = kal.KalibrierungSpeicher(db)
    for i in range(5):
        s.anlegen(kal.pruefe_fall({**FALL, "verkauf_am": "2026-01-24", "verkauf_preis": 30000 + i, "kosten": 9000}, HEUTE), None)
    scout.cmd_kalibrierung(cfg, db, None)
    aus = capsys.readouterr().out
    assert "Kalibrierung: 5 Fälle, davon 5 verkauft" in aus and "Vorschlag rechner.aufschlag_haendler_vk" in aus
    assert "Vorschlag rechner.kosten.aufbereitung" in aus and "Nichts wurde geändert" in aus and "Hinweis: Nachgetragene Fälle" in aus


# ---------------------------------------------------------------- 6. Schema 20
def bis_20(monkeypatch):
    _alt_schritte(monkeypatch, 20)


def baue_v19(pfad, monkeypatch, tmp_path):
    baue_v18(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 19)
        assert migriere(pfad, tmp_path / "stand19") == [19]
    assert lese_version(pfad) == 19


@pytest.mark.parametrize("art", ["v1", "v19"])
def test_migration_auf_20_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_20(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v19":
        baue_v19(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    assert migriere(pfad, ziel)[-1] == 20 and lese_version(pfad) == 20 and versionen(pfad)[-1] == 20
    neue = {t: v_ for t, v_ in vorher.items() if t not in ("fahrzeuge", "suchprofile")}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    assert _sql(pfad, "SELECT COUNT(*) FROM kalibrierung_faelle") == [(0,)] and _sql(pfad, "PRAGMA integrity_check") == [("ok",)]
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v20" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_20_zweite_ausfuehrung_und_rollback(tmp_path, monkeypatch):
    bis_20(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v19(pfad, monkeypatch, tmp_path)
    vorher, echt = _abbild(pfad), migrationen._schritt_20

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")
    monkeypatch.setitem(migrationen.SCHRITTE, 20, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 19 and _abbild(pfad) == vorher
    assert "kalibrierung_faelle" not in {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='table'")}
    monkeypatch.setitem(migrationen.SCHRITTE, 20, echt)
    assert migriere(pfad, ziel) == [20]
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_20(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def test_neue_datenbank_hat_die_tabelle(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) == migrationen.AKTUELLE_VERSION >= 20
    assert "kalibrierung_faelle" in {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
