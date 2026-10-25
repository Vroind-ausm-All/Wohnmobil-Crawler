"""P4-05: Abdeckung und Suchlücken messen – Kennzahlen, Zeit-, Gebiets- und Profillücken, API, Seite, CLI. Nur lesen, alles offline."""

# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.daten import BASIS, FakeAbruf
from tests.test_haendler import HaendlerSpeicher
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from wmscout import abdeckung as ab
from wmscout import suchprofile as sp
from wmscout.importer import Importer
from wmscout.team import TeamSpeicher

JETZT = datetime(2026, 10, 24, 12, 0)


def z(id_, plz="70173", quelle="kleinanzeigen", art="Alkoven", gewerblich=0, sperre=None, dubletten=(), ausblenden=False, **a):
    return {"a": {"id": id_, "quelle": quelle, "plz": plz, "gewerblich": gewerblich, "preis": 30000, "ez_jahr": 2015, "km": 80000,
                  "marke": "Knaus", "modell": "Sky", "fahrzeug": "Knaus Sky", "titel": "Knaus Sky", **a},
            "b": SimpleNamespace(art=art), "sperre": sperre, "dubletten_ids": list(dubletten), "ausblenden": ausblenden}


# ---------------------------------------------------------------- 1. Eingaben
@pytest.mark.parametrize("wert, tage", [(None, 30), ("", 30), ("7", 7), (" 365 ", 365), (1, 1)])
def test_tage(wert, tage):
    assert ab.tage_aus(wert) == tage


@pytest.mark.parametrize("wert", ["0", "366", "x", "７", "1.5", "-3"])
def test_tage_ungueltig(wert):
    with pytest.raises(ValueError, match="1 bis 365"):
        ab.tage_aus(wert)
    with pytest.raises(ValueError, match="1 bis 90"):
        ab.tage_aus("91", ab.MAX_TAGE_APP)


def test_beginn_ab_mitternacht():
    assert ab.beginn(JETZT, 1) == datetime(2026, 10, 24) and ab.beginn(JETZT, 7) == datetime(2026, 10, 18)


# ---------------------------------------------------------------- 2. Kennzahlen (rein)
def test_kennzahlen():
    zeilen = [z("1"), z("2", dubletten=["3"]), z("3", dubletten=["2"], quelle="mobile.de"), z("4", gewerblich=1),
              z("5", sperre="zu weit entfernt"), z("6", nicht_verfuegbar=True), z("7", plz=None), z("8", gewerblich=None),
              z("9", art="Sonstige")]
    laeufe = [{"art": "suchlauf", "ergebnis": "ok"}, {"art": "suchlauf", "ergebnis": "gesperrt"}, {"art": "seiten", "ergebnis": "ok"}]
    k = ab.kennzahlen(zeilen, 7, preisaenderungen=4, laeufe=laeufe)
    assert k["neue_inserate"] == 9 and k["neue_inserate_je_quelle"] == {"kleinanzeigen": 8, "mobile.de": 1}
    assert k["neue_fahrzeuge"] == 8                                                     # 2 und 3 sind ein Fahrzeug
    assert k["relevante_privatangebote"] == 5 and k["relevante_privatangebote_pro_tag"] == 0.7   # 1, 2, 3, 7, 9
    assert (k["inserate_mit_dublette"], k["nicht_verfuegbar"], k["preisaenderungen"]) == (2, 1, 4)
    assert k["anteil_vollstaendig"] == round(6 / 9, 3)                                  # ohne 7 (PLZ), 8 (Anbieter), 9 (Art); 4 gewerblich zählt
    assert k["importerfolg"] == {"seiten": {"laeufe": 1, "ohne_fehler": 1, "quote": 1.0},
                                 "suchlauf": {"laeufe": 2, "ohne_fehler": 1, "quote": 0.5}}
    # QA B1: Bearbeitungsstatus senkt die Kennzahl nicht (Filter-Sperre ohne Status)
    kontaktiert = dict(z("10", sperre="Status: kontaktiert"), sperre_filter=None)
    gefiltert = dict(z("11", sperre="Status: kontaktiert"), sperre_filter="zu weit entfernt (500 km)")
    assert ab.kennzahlen([kontaktiert, gefiltert], 1, 0, [])["relevante_privatangebote"] == 1
    leer = ab.kennzahlen([], 30, 0, [])
    assert leer["anteil_vollstaendig"] is None and leer["neue_fahrzeuge"] == 0 and leer["importerfolg"] == {}


def test_fahrzeuge_zusammenhang_und_wiedereingestellt():
    # A~B und B~C (nicht transitiv erkannt) sind EIN Fahrzeug; D ist wieder eingestellt (Partner X ging vor dem Zeitraum ein)
    zeilen = [z("A", dubletten=["B"]), z("B", dubletten=["A", "C"]), z("C", dubletten=["B"]), z("D", dubletten=["X"]), z("E")]
    assert sorted(map(sorted, ab.fahrzeuge(zeilen))) == [["A", "B", "C"], ["D", "X"], ["E"]]
    assert ab.kennzahlen(zeilen, 7, 0, [])["neue_fahrzeuge"] == 2                        # A/B/C und E, nicht D


# ---------------------------------------------------------------- 3. Zeitlücken (rein)
def test_zeitluecken():
    heute = date(2026, 10, 24)
    tag = lambda n: heute - timedelta(days=n)                                           # noqa: E731
    eingang = {"kleinanzeigen": {tag(0), tag(1), tag(5), tag(9)}, "mobile.de": set()}
    erg = ab.zeitluecken(eingang, ["kleinanzeigen", "mobile.de", "autoscout24"], heute, 10)
    k = erg["kleinanzeigen"]
    assert (k["tage_mit_eingang"], k["tage_ohne_eingang"], k["letzter_eingang"]) == (4, 6, "2026-10-24")
    assert k["luecken"] == [{"von": "2026-10-16", "bis": "2026-10-18", "tage": 3}, {"von": "2026-10-20", "bis": "2026-10-22", "tage": 3}]
    assert erg["mobile.de"]["luecken"] == [{"von": "2026-10-15", "bis": "2026-10-24", "tage": 10}] and erg["mobile.de"]["letzter_eingang"] is None
    # einzelne fehlende Tage sind keine Lücke; die Lücke am Ende reicht bis heute
    erg = ab.zeitluecken({"x": {tag(1), tag(3)}}, ["x"], heute, 4)["x"]
    assert erg["luecken"] == [] and erg["tage_ohne_eingang"] == 2
    erg = ab.zeitluecken({"x": {tag(3)}}, ["x"], heute, 4)["x"]
    assert erg["luecken"] == [{"von": "2026-10-22", "bis": "2026-10-24", "tage": 3}]


# ---------------------------------------------------------------- 4. Gebiets- und Profillücken (rein)
def test_gebietsluecken():
    g = ab.gebietsluecken([z("1", plz="70173"), z("2", plz="70176"), z("3", plz="80331"), z("4", plz=None), z("5", plz=None, ausland="FR")])
    assert g["je_bereich"] == {"70": 2, "80": 1} and g["ohne_plz"] == 1 and g["ausland"] == 1
    assert "70" not in g["ohne_inserat"] and "01" in g["ohne_inserat"] and len(g["ohne_inserat"]) == 94
    assert g["anteil_bereiche_mit_inserat"] == round(2 / 96, 3)


def _profil(**kw):
    return {"id": 1, **sp.pruefe_profil({"name": "Süd", **kw}, JETZT)}


def test_profilluecken():
    zeilen = [z("1", plz="70173"), z("2", plz="70176", dubletten=["3"]), z("3", plz="70199", dubletten=["2"], quelle="mobile.de"),
              z("4", art="Kastenwagen"), z("5", plz="80331"), z("6", ausblenden=True)]
    auftraege = {"kleinanzeigen": {"angelegt": 1}, "mobile.de": {"angelegt": 0}}
    p = ab.profilluecken(_profil(arten=["Alkoven", "Integrierter"], gebiet="regionen", gebiet_regionen=["7", "9"]), auftraege, zeilen)
    assert (p["passt"], p["fahrzeuge"], p["unklar"]) == (3, 2, 0) and p["je_plattform"] == {"kleinanzeigen": 2, "mobile.de": 1}
    assert p["arten_ohne_treffer"] == ["Integrierter"] and p["regionen_ohne_treffer"] == ["9"]
    assert p["hinweise"] == ["mobile.de: kein Suchauftrag angelegt", "ohne passendes Inserat: Integrierter",
                             "PLZ-Bereiche ohne passendes Inserat: 9…"]
    # Auftrag angelegt, aber nichts eingegangen; hoher Anteil „unklar“
    ohne_plz = [z(str(i), plz=None) for i in range(4)]
    p = ab.profilluecken(_profil(gebiet="umkreis", gebiet_plz="70173", gebiet_radius_km=50),
                         {"kleinanzeigen": {"angelegt": 1}, "mobile.de": {"angelegt": 1}}, ohne_plz)
    assert p["unklar"] == 4 and p["anteil_unklar"] == 1.0
    assert "kleinanzeigen: Suchauftrag angelegt, aber im Zeitraum kein passendes Inserat eingegangen" in p["hinweise"]
    assert any("100 % der Treffer sind „unklar“" in h for h in p["hinweise"])


# ---------------------------------------------------------------- 5. Messen über die Datenbank
def test_messen_ende_zu_ende_und_nur_lesen(cfg, db, ads):
    Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    alt = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    db.con.execute("UPDATE anzeigen SET erstmals_gesehen=? WHERE id IN (?, ?)", (alt, ads[0]["id"], ads[1]["id"]))
    db.con.commit()
    billiger = copy.deepcopy(ads)
    billiger[5]["preis"] -= 1000
    Importer(cfg, db, abruf=FakeAbruf(billiger)).lauf(cfg["suchen"])
    sp.SuchprofilSpeicher(db).anlegen(sp.pruefe_profil({"name": "Alle"}, datetime.now()))
    db.con.commit()
    vorher = db.con.total_changes
    m = ab.messe(cfg, db, BASIS, 30)
    assert db.con.total_changes == vorher                                               # nur lesen
    k = m["kennzahlen"]
    assert k["neue_inserate"] == 58 and k["neue_inserate_je_quelle"] == {"kleinanzeigen": 58}     # zwei liegen vor dem Zeitraum
    assert k["preisaenderungen"] == 1 and k["importerfolg"]["suchlauf"] == {"laeufe": 2, "ohne_fehler": 2, "quote": 1.0}
    assert 0 < k["neue_fahrzeuge"] <= 58 and k["relevante_privatangebote"] > 0
    heute = datetime.now().date().isoformat()
    assert m["zeitluecken"]["kleinanzeigen"]["letzter_eingang"] == heute and m["zeitluecken"]["kleinanzeigen"]["tage_mit_eingang"] == 1
    assert m["zeitluecken"]["mobile.de"]["tage_mit_eingang"] == 0
    (p,) = m["profile"]
    assert p["name"] == "Alle" and p["passt"] + p["unklar"] > 0 and "kleinanzeigen: kein Suchauftrag angelegt" in p["hinweise"]
    assert sum(m["gebietsluecken"]["je_bereich"].values()) > 0
    assert ab.messe(cfg, db, BASIS, 7)["kennzahlen"]["neue_inserate"] == 58
    # nur neue/geänderte Inserate zählen als Eingang: Detailabruf und „gelöscht“ an einem anderen Tag nicht (QA B4)
    gestern = (datetime.now() - timedelta(days=1)).astimezone().isoformat(timespec="seconds")
    iid = db.con.execute("SELECT id FROM inserate LIMIT 1").fetchone()[0]
    for kanal, typ in (("detail", "geaendert"), ("suche", "geloescht"), ("email", "neu")):
        db.con.execute("INSERT INTO beobachtungen (inserat_id, plattform, kanal, ereignis_typ, zeitpunkt, inhalt_hash) VALUES (?, ?, ?, ?, ?, 'x')",
                       (iid, "mobile.de" if kanal == "email" else "kleinanzeigen", kanal, typ, gestern))
    db.con.commit()
    z_ = ab.messe(cfg, db, BASIS, 30)["zeitluecken"]
    assert z_["kleinanzeigen"]["tage_mit_eingang"] == 1 and z_["mobile.de"]["tage_mit_eingang"] == 1


# ---------------------------------------------------------------- 6. API, Seite, CLI
def test_api_seite_rechte(server, db, importiert, tmp_path):
    sp.SuchprofilSpeicher(db).anlegen(sp.pruefe_profil({"name": "<img src=x onerror=alert(1)>"}, datetime.now()))
    db.con.commit()
    c = lokal(server)
    s, d, _ = c("GET", "/api/abdeckung?tage=7")
    assert s == 200 and d["tage"] == 7 and d["kennzahlen"]["neue_inserate"] == 60 and d["profile"][0]["name"].startswith("<img")
    assert c("GET", "/api/abdeckung?tage=0")[0] == 400 and c("GET", "/abdeckung?tage=abc")[0] == 400
    assert c("GET", "/api/abdeckung?tage=91")[0] == 400 and c("GET", "/api/abdeckung?tage=90")[0] == 200     # App: höchstens 90
    s, html, _ = c("GET", "/abdeckung")
    assert s == 200 and 'data-k="neue_inserate">60<' in html and "&lt;img src=x" in html and "<img src=x" not in html
    assert 'data-plattform="kleinanzeigen"' in html and 'id="ohne-inserat"' in html
    assert 'href="/abdeckung"' in c("GET", "/status")[1]
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    assert anmelden(server, "Ben")("GET", "/api/abdeckung")[0] == 200
    hugo = anmelden(server, "Hugo")
    assert hugo("GET", "/api/abdeckung")[0] == 403 and hugo("GET", "/abdeckung")[0] == 403


def test_cli(cfg, db, importiert, capsys):
    import scout
    scout.cmd_abdeckung(cfg, db, SimpleNamespace(tage="14"))
    aus = capsys.readouterr().out
    assert "Abdeckung der letzten 14 Tage" in aus and "Neue Inserate: 60 (kleinanzeigen 60)" in aus and "PLZ-Bereiche ohne neues Inserat" in aus
    with pytest.raises(SystemExit, match="1 bis 365"):
        scout.cmd_abdeckung(cfg, db, SimpleNamespace(tage="0"))


def test_app_speichert_die_messung_zwischen(cfg, db, importiert, monkeypatch):
    from wmscout.web.api import Kontext
    aufrufe = []
    echt = ab.messe
    monkeypatch.setattr(ab, "messe", lambda *a, **k: aufrufe.append(a[-1]) or echt(*a, **k))
    k = Kontext.__new__(Kontext)
    k.cfg, k.db, k.basis = cfg, db, BASIS
    erst = k.abdeckung(30)
    assert k.abdeckung(30) is erst and aufrufe == [30]
    k.abdeckung(7)
    db.con.execute("UPDATE anzeigen SET notiz='x' WHERE rowid=1")                     # Bestand geändert: neu messen
    db.con.commit()
    k.abdeckung(7)
    assert aufrufe == [30, 7, 7]
