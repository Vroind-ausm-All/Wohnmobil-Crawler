"""P4-02: Suchgebiete der Suchprofile (bundesweit, Umkreis um eine PLZ, PLZ-Bereiche) – Eingaben, Zuordnung, Speicher, API, Oberfläche
und Migration auf Schema v18. Alles offline."""

# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from tests.daten import BASIS
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql
from tests.test_migration import pruefsumme, versionen
from tests.test_suchprofile import baue_v16
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout import migrationen
from wmscout import suchprofile as sp
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.normalisierung.geo import entfernung_km
from wmscout.sicherung import sicherungen

JETZT = datetime(2026, 10, 24, 12, 0)
STATIC = BASIS / "wmscout" / "web" / "static"


def profil(**kw) -> dict:
    return sp.pruefe_profil({"name": "Süd", **kw}, JETZT)


def inserat(**kw) -> dict:
    return {"id": "a", "marke": "Knaus", "modell": "Sky TI", "fahrzeug": "Knaus Sky TI", "titel": "Knaus Sky TI 650", "preis": 40000,
            "ez_jahr": 2016, "km": 90000, "plz": "70176", "ausland": None, **kw}


# ---------------------------------------------------------------- 1. Eingaben
def test_gebiet_standard_bundesweit_und_nur_gewaehlte_angaben():
    p = profil()
    assert (p["gebiet"], p["gebiet_plz"], p["gebiet_radius_km"], p["gebiet_regionen"]) == ("bundesweit", None, None, [])
    p = profil(gebiet="bundesweit", gebiet_plz="70173", gebiet_radius_km=50, gebiet_regionen=["7"])     # fremde Angaben werden geleert
    assert (p["gebiet_plz"], p["gebiet_radius_km"], p["gebiet_regionen"]) == (None, None, [])
    p = profil(gebiet="umkreis", gebiet_plz=" 70173 ", gebiet_radius_km=150, gebiet_regionen=["8"])
    assert (p["gebiet"], p["gebiet_plz"], p["gebiet_radius_km"], p["gebiet_regionen"]) == ("umkreis", "70173", 150, [])
    p = profil(gebiet="regionen", gebiet_regionen=["80", " 7", "70", "81", "7"], gebiet_plz="70173")
    assert (p["gebiet_regionen"], p["gebiet_plz"]) == (["7", "80", "81"], None)                         # „70“ steckt in „7“


@pytest.mark.parametrize("daten, fehler", [
    ({"gebiet": "land"}, "gebiet"), ({"gebiet": False}, "gebiet"), ({"gebiet": 0}, "gebiet"), ({"gebiet": []}, "gebiet"),
    ({"gebiet": "umkreis", "gebiet_plz": "７０１７３", "gebiet_radius_km": 50}, "PLZ"),                     # Vollbreiten-Ziffern
    ({"gebiet": "regionen", "gebiet_regionen": ["７"]}, "Unbekannt"), ({"gebiet": "regionen", "gebiet_regionen": ["7", ""]}, "leer"),
    ({"gebiet": "umkreis", "gebiet_radius_km": 50}, "PLZ"),
    ({"gebiet": "umkreis", "gebiet_plz": "7017", "gebiet_radius_km": 50}, "PLZ"),
    ({"gebiet": "umkreis", "gebiet_plz": "99999", "gebiet_radius_km": 50}, "PLZ"),                     # nur genähert, nicht exakt bekannt
    ({"gebiet": "umkreis", "gebiet_plz": 70173, "gebiet_radius_km": 50}, "PLZ"),
    ({"gebiet": "umkreis", "gebiet_plz": "70173"}, "km"), ({"gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 0}, "km"),
    ({"gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 1001}, "km"),
    ({"gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": "50"}, "km"),
    ({"gebiet": "regionen"}, "PLZ-Bereiche"), ({"gebiet": "regionen", "gebiet_regionen": []}, "PLZ-Bereiche"),
    ({"gebiet": "regionen", "gebiet_regionen": "7"}, "PLZ-Bereiche"), ({"gebiet": "regionen", "gebiet_regionen": [7]}, "PLZ-Bereiche"),
    ({"gebiet": "regionen", "gebiet_regionen": ["00"]}, "Unbekannt"), ({"gebiet": "regionen", "gebiet_regionen": ["123"]}, "Unbekannt"),
    ({"gebiet": "regionen", "gebiet_regionen": ["7a"]}, "Unbekannt"), ({"gebiet": "regionen", "gebiet_regionen": [" "]}, "leer"),
    ({"gebiet": "regionen", "gebiet_regionen": ["1"] * 51}, "PLZ-Bereiche"),
])
def test_gebiet_ungueltig(daten, fehler):
    with pytest.raises(sp.Eingabefehler, match=fehler):
        profil(**daten)


def test_lange_falsche_eingaben_kurze_meldung():
    with pytest.raises(sp.Eingabefehler) as fehler:
        profil(gebiet="regionen", gebiet_regionen=[str(i) + "x" * 10000 for i in range(50)])
    assert len(str(fehler.value)) < 200


def test_gebiet_text():
    assert sp.gebiet_text(profil()) == "bundesweit"
    assert sp.gebiet_text({"gebiet": "umkreis", "gebiet_plz": None, "gebiet_radius_km": None}) == "Umkreis (unvollständig)"
    assert sp.gebiet_text({"gebiet": "regionen", "gebiet_regionen": []}) == "PLZ-Bereiche (unvollständig)"
    assert sp.gebiet_text(profil(gebiet="umkreis", gebiet_plz="70173", gebiet_radius_km=80)) == "80 km um 70173"
    assert sp.gebiet_text(profil(gebiet="regionen", gebiet_regionen=["80", "7"])) == "PLZ 7…, 80…"


# ---------------------------------------------------------------- 2. Zuordnung
UMKREIS = {"gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 100}
REGION = {"gebiet": "regionen", "gebiet_regionen": ["7", "88"]}


@pytest.mark.parametrize("kw, a, urteil", [
    ({}, {"plz": "80331"}, "passt"), ({}, {"plz": None, "ausland": "FR"}, "passt"), ({}, {"plz": None}, "passt"),   # bundesweit: wie bisher
    (UMKREIS, {}, "passt"), (UMKREIS, {"plz": "80331"}, "nein"), (UMKREIS, {"plz": None}, "unklar"),
    (UMKREIS, {"plz": None, "ausland": "FR"}, "nein"), (UMKREIS, {"plz": "72072"}, "passt"),               # Tübingen ≈ 45 km
    (UMKREIS, {"plz": "70998"}, "passt"),                                                                  # nicht exakt: Näherung über „709“
    (REGION, {}, "passt"), (REGION, {"plz": "88045"}, "passt"), (REGION, {"plz": "80331"}, "nein"), (REGION, {"plz": "08523"}, "nein"),
    (REGION, {"plz": None}, "unklar"), (REGION, {"plz": None, "ausland": "AT"}, "nein"),
    ({**UMKREIS, "preis_max": 1}, {"plz": None}, "nein"),                                                  # „nein“ schlägt „unklar“
    ({**UMKREIS, "preis_max": 1}, {"plz": "80331"}, "nein"), ({**REGION, "km_max": 1}, {"km": None}, "unklar"),
])
def test_zuordnung_mit_gebiet(kw, a, urteil):
    ergebnis, gruende = sp.pruefe_inserat(profil(**kw), inserat(**a), "Teilintegrierter")
    assert ergebnis == urteil and (urteil == "passt") == (gruende == [])


def test_genaeherte_plz_knapp_ausserhalb_bleibt_unklar():
    # 74999 steht nicht in der Tabelle (Näherung über „749“, ≈ 74 km); 73099 ist exakt bekannt (≈ 39 km)
    assert sp.pruefe_inserat(profil(**{**UMKREIS, "gebiet_radius_km": 70}), inserat(plz="74999"), None) == (
        "unklar", [f"ca. {entfernung_km('70173', '74999')} km entfernt (PLZ nur genähert)"])
    assert sp.pruefe_inserat(profil(**{**UMKREIS, "gebiet_radius_km": 50}), inserat(plz="74999"), None)[0] == "nein"     # > 20 km darüber
    assert sp.pruefe_inserat(profil(**{**UMKREIS, "gebiet_radius_km": 30}), inserat(plz="73099"), None)[0] == "nein"     # exakt: keine Toleranz
    unvollstaendig = {"gebiet": "umkreis", "gebiet_plz": None, "gebiet_radius_km": None}                                # z. B. Handeingriff
    assert sp.pruefe_inserat({**profil(), **unvollstaendig}, inserat(), None) == ("unklar", ["Entfernung unbekannt"])


def test_umkreis_grenze_und_gruende():
    km = entfernung_km("70173", "72072")
    assert sp.pruefe_inserat(profil(**{**UMKREIS, "gebiet_radius_km": km}), inserat(plz="72072"), None)[0] == "passt"
    urteil, gruende = sp.pruefe_inserat(profil(**{**UMKREIS, "gebiet_radius_km": km - 1}), inserat(plz="72072"), None)
    assert urteil == "nein" and gruende == [f"{km} km entfernt"]
    assert sp.pruefe_inserat(profil(**UMKREIS), inserat(plz=None, ausland="FR"), None)[1] == ["Ort im Ausland (FR)"]
    assert sp.pruefe_inserat(profil(**REGION), inserat(plz="80331"), None)[1] == ["PLZ 80331 außerhalb"]
    assert sp.pruefe_inserat(profil(**REGION), inserat(plz=None), None)[1] == ["Ort unbekannt"]


# ---------------------------------------------------------------- 3. Speicher
def test_speicher_gebiet(db):
    s = sp.SuchprofilSpeicher(db)
    pid = s.anlegen(profil(**UMKREIS))
    p = s.profil(pid)
    assert (p["gebiet"], p["gebiet_plz"], p["gebiet_radius_km"], p["gebiet_regionen"]) == ("umkreis", "70173", 100, [])
    assert s.aendern(pid, profil(**REGION))
    p = s.profil(pid)
    assert (p["gebiet"], p["gebiet_plz"], p["gebiet_radius_km"], p["gebiet_regionen"]) == ("regionen", None, None, ["7", "88"])
    assert s.liste()[0]["gebiet_regionen"] == ["7", "88"]


# ---------------------------------------------------------------- 4. API
def test_api_umkreis_filtert_wie_die_entfernung(server, db, importiert, ads):
    c = lokal(server)
    alle = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
    s, d, _ = c("POST", "/api/suchprofile", {"name": "Nah", "gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 100})
    assert s == 200
    pid = d["id"]
    treffer = c("GET", f"/api/suchprofil/{pid}/treffer")[1]["treffer"]
    # Mittelpunkt = Standort der Tests: Treffer sind genau die Fahrzeuge mit angezeigter Entfernung bis 100 km
    assert set(treffer) == {f["id"] for f in alle if f["entfernung_km"] is not None and f["entfernung_km"] <= 100}
    assert 0 < len(treffer) < len(alle) and set(treffer.values()) == {"passt"}
    liste = c("GET", "/api/suchprofile")[1]
    assert liste["gebiete"] == ["bundesweit", "umkreis", "regionen"] and liste["standort_plz"] == "70173"
    assert liste["profile"][0]["gebiet_text"] == "100 km um 70173"
    assert c("POST", "/api/suchprofile", {"name": "x", "gebiet": "umkreis", "gebiet_plz": "12"})[0] == 400
    assert c("POST", f"/api/suchprofil/{pid}", {"name": "Nah", "gebiet": "regionen", "gebiet_regionen": ["8"]})[0] == 200
    treffer = c("GET", f"/api/suchprofil/{pid}/treffer")[1]["treffer"]
    assert set(treffer) == {a["id"] for a in ads if a["plz"].startswith("8")} != set()


def test_api_gebiet_keine_wirkung_auf_bewertung(server, db, importiert):
    c = lokal(server)
    vorher = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1]
    c("POST", "/api/suchprofile", {"name": "Weit weg", "gebiet": "regionen", "gebiet_regionen": ["0"]})
    assert c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")[1] == vorher


# ---------------------------------------------------------------- 5. Oberfläche
def test_oberflaeche_statisch():
    js, html = (STATIC / "suchprofile.js").read_text(encoding="utf-8"), (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert 'name: "gebiet"' in js and "gebiet_radius_km" in js and "gebiet_regionen" in js and "stand.standort_plz" in js
    assert "p.gebiet_text" in js and "innerHTML" not in js
    assert 'if (gs.value !== "umkreis") { gr.value = ""' in js                         # verstecktes Radiusfeld wird nicht geprüft
    assert 'gp.disabled = gr.disabled = !stand.darf_aendern || gs.value !== "umkreis"' in js   # sonst blockiert die Browserprüfung
    assert ".sp-feld[hidden]{display:none}" in html                                   # sonst hebt display:flex das hidden-Attribut auf


# ---------------------------------------------------------------- 6. Schema 18
def bis_18(monkeypatch):
    _alt_schritte(monkeypatch, 18)


def baue_v17(pfad, monkeypatch, tmp_path, mit_profil=True):
    baue_v16(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 17)
        assert migriere(pfad, tmp_path / "stand17") == [17]
    if mit_profil:
        con = sqlite3.connect(pfad)
        con.execute("INSERT INTO suchprofile (name, arten, marken, km_max, erstellt_am, geaendert_am) VALUES ('Alt', '[\"Alkoven\"]', '[]', "
                    "150000, '2026-10-24T08:00:00', '2026-10-24T08:00:00')")
        con.execute("INSERT INTO suchauftraege (profil_id, plattform, angelegt, geaendert_am) VALUES (1, 'mobile.de', 1, '2026-10-24T08:00:00')")
        con.commit()
        con.close()
    assert lese_version(pfad) == 17


GEBIET_SPALTEN = {"gebiet", "gebiet_plz", "gebiet_radius_km", "gebiet_regionen"}


def test_migration_auf_18_ohne_datenverlust(tmp_path, monkeypatch):
    bis_18(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    baue_v17(pfad, monkeypatch, tmp_path)
    vorher = _abbild(pfad)
    assert migriere(pfad, ziel) == [18] and lese_version(pfad) == 18 and versionen(pfad)[-1] == 18
    neue = {t: v_ for t, v_ in vorher.items() if t not in ("fahrzeuge", "suchprofile")}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    zeile = _sql(pfad, "SELECT name, arten, km_max, gebiet, gebiet_plz, gebiet_radius_km, gebiet_regionen FROM suchprofile")
    assert zeile == [("Alt", '["Alkoven"]', 150000, "bundesweit", None, None, "[]")]                   # Altbestand filtert unverändert
    assert _sql(pfad, "SELECT profil_id, plattform, angelegt FROM suchauftraege") == [(1, "mobile.de", 1)]
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)]
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v18" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == 17 and _abbild(kopien[0]) == vorher


@pytest.mark.parametrize("art", ["v1", "v16"])
def test_migration_aelterer_bestaende_bis_18(tmp_path, monkeypatch, art):
    bis_18(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v16":
        baue_v16(pfad, monkeypatch, tmp_path)
    else:
        from tests.test_fahrzeuge import baue
        baue(art, pfad, monkeypatch)
    assert migriere(pfad, ziel)[-1] == 18
    assert GEBIET_SPALTEN <= {r[1] for r in _sql(pfad, "PRAGMA table_info(suchprofile)")}


def test_schritt_18_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_18(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v17(pfad, monkeypatch, tmp_path)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_18(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def test_fehler_im_schritt_18_rollt_zurueck_dann_gelingt_es(tmp_path, monkeypatch):
    bis_18(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v17(pfad, monkeypatch, tmp_path)
    vorher, echt = _abbild(pfad), migrationen._schritt_18

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 18, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 17 and _abbild(pfad) == vorher
    assert not GEBIET_SPALTEN & {r[1] for r in _sql(pfad, "PRAGMA table_info(suchprofile)")}
    monkeypatch.setitem(migrationen.SCHRITTE, 18, echt)
    assert migriere(pfad, ziel) == [18]


def test_neue_datenbank_hat_die_spalten(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 18
    assert GEBIET_SPALTEN <= {r[1] for r in db.con.execute("PRAGMA table_info(suchprofile)")}
