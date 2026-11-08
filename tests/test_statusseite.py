"""P4-04: Laufprotokoll, Intervalle je Quelle, Pause nach Sperre, Statusseite – und Migration auf Schema v19. Alles offline."""

# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from tests.daten import AntwortAbruf, FakeAbruf, such_html
from tests.test_app_threads import _suchlauf
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_haendler import HaendlerSpeicher
from tests.test_migration import pruefsumme, versionen
from tests.test_suchgebiete import baue_v17
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from wmscout import laufprotokoll as lp
from wmscout import migrationen
from wmscout.importer import Importer
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.quellen.basis import QuelleGesperrt
from wmscout.sicherung import sicherungen
from wmscout.team import TeamSpeicher

JETZT = datetime(2026, 10, 24, 12, 0)
E = {"intervalle": {}, "pause_nach_sperre_stunden": 24}


def iso(**delta) -> str:
    return (JETZT - timedelta(**delta)).isoformat(timespec="seconds")


def lauf(start, ergebnis="ok", quelle="kleinanzeigen", ende=True, fehler=None, art="suchlauf"):
    je = {quelle: {"neu": 1, "preis": 0, "bekannt": 2, "ergebnis": ergebnis, **({"fehler": fehler} if fehler else {})}} if quelle else {}
    return {"art": art, "start": start, "ende": start if ende else None, "ergebnis": ergebnis, "je_quelle": je}


# ---------------------------------------------------------------- 1. Einstellungen
def test_einstellungen(caplog):
    assert lp.einstellungen({}, {"kleinanzeigen"}) == {"intervalle": {}, "pause_nach_sperre_stunden": 24}
    e = lp.einstellungen({"app": {"intervall_stunden_je_quelle": {"kleinanzeigen": 6, "mobile.de": 2.5}, "pause_nach_sperre_stunden": 0}},
                         {"kleinanzeigen", "mobile.de"})
    assert e == {"intervalle": {"kleinanzeigen": 6, "mobile.de": 2.5}, "pause_nach_sperre_stunden": 0}
    with caplog.at_level(logging.WARNING, logger="scout"):
        e = lp.einstellungen({"app": {"intervall_stunden_je_quelle": {"kleinanzeigen": "6", "ebay": 3, "x": True},
                                      "pause_nach_sperre_stunden": -1}}, {"kleinanzeigen", "x"})
        assert e == {"intervalle": {}, "pause_nach_sperre_stunden": 24}
        assert lp.einstellungen({"app": {"intervall_stunden_je_quelle": [6]}}, {"kleinanzeigen"})["intervalle"] == {}
    assert caplog.text.count("config.yaml: app ->") == 5
    assert lp.einstellungen({"app": {"intervall_stunden_je_quelle": {"kleinanzeigen": 0}}}, {"kleinanzeigen"})["intervalle"] == {}


# ---------------------------------------------------------------- 2. Quellenstatus (rein)
def test_status_ohne_laeufe():
    s = lp.quellen_status([], ["kleinanzeigen"], E, JETZT)["kleinanzeigen"]
    assert s == {"letzter_lauf": None, "letztes_ergebnis": None, "letzter_erfolg": None, "fehler_in_folge": 0, "letzter_fehler": None,
                 "pause_bis": None, "intervall_stunden": None, "naechster_auto": None}
    assert lp.sperrgrund(s, JETZT) is None


def test_fehler_in_folge_letzter_erfolg_und_fehlertext():
    laeufe = [lauf(iso(hours=1), "fehler", fehler="HTTP 500 bei https://x"), lauf(iso(hours=2), "fehler"), lauf(iso(hours=3), "ok"),
              lauf(iso(hours=4), "fehler", fehler="alt")]
    s = lp.quellen_status(laeufe, ["kleinanzeigen", "mobile.de"], E, JETZT)
    assert s["kleinanzeigen"]["fehler_in_folge"] == 2 and s["kleinanzeigen"]["letzter_erfolg"] == iso(hours=3)
    assert s["kleinanzeigen"]["letzter_fehler"] == "HTTP 500 bei https://x" and s["kleinanzeigen"]["letztes_ergebnis"] == "fehler"
    assert s["mobile.de"]["letzter_lauf"] is None                                          # Läufe anderer Quellen zählen nicht
    assert lp.quellen_status([lauf(iso(hours=1), "ok")], ["kleinanzeigen"], E, JETZT)["kleinanzeigen"]["letzter_fehler"] is None


def test_pause_nach_sperre_und_intervall():
    gesperrt = [lauf(iso(hours=2), "gesperrt", fehler="HTTP 429 – blockt")]
    s = lp.quellen_status(gesperrt, ["kleinanzeigen"], E, JETZT)["kleinanzeigen"]
    assert s["pause_bis"] == (JETZT + timedelta(hours=22)).isoformat(timespec="seconds") == s["naechster_auto"]
    assert lp.sperrgrund(s, JETZT).startswith("Pause nach Sperre der Quelle bis")
    assert lp.sperrgrund(s, JETZT + timedelta(hours=22)) is None                        # Pause vorbei
    assert lp.quellen_status(gesperrt, ["kleinanzeigen"], {**E, "pause_nach_sperre_stunden": 0}, JETZT)["kleinanzeigen"]["naechster_auto"] is None
    alt = [lauf(iso(hours=25), "gesperrt")]
    assert lp.quellen_status(alt, ["kleinanzeigen"], E, JETZT)["kleinanzeigen"]["naechster_auto"] is None
    e6 = {**E, "intervalle": {"kleinanzeigen": 6}}
    s = lp.quellen_status([lauf(iso(hours=2), "ok")], ["kleinanzeigen"], e6, JETZT)["kleinanzeigen"]
    assert s["naechster_auto"] == (JETZT + timedelta(hours=4)).isoformat(timespec="seconds") and s["intervall_stunden"] == 6
    assert lp.sperrgrund(s, JETZT).startswith("Intervall: frühestens wieder")
    assert lp.quellen_status([lauf(iso(hours=7), "ok")], ["kleinanzeigen"], e6, JETZT)["kleinanzeigen"]["naechster_auto"] is None
    # beides: der spätere Zeitpunkt zählt, der Grund nennt die Pause
    s = lp.quellen_status(gesperrt, ["kleinanzeigen"], e6, JETZT)["kleinanzeigen"]
    assert lp.sperrgrund(s, JETZT).startswith("Pause nach Sperre")


def test_verwaister_lauf_gilt_als_abgebrochen():
    offen = lauf(iso(hours=7), "laeuft", ende=False)
    assert lp.wirksames_ergebnis(offen, JETZT) == "abgebrochen"
    assert lp.wirksames_ergebnis(lauf(iso(hours=1), "laeuft", ende=False), JETZT) == "laeuft"
    s = lp.quellen_status([offen], ["kleinanzeigen"], E, JETZT)["kleinanzeigen"]
    assert s["letztes_ergebnis"] == "abgebrochen" and s["fehler_in_folge"] == 1


# ---------------------------------------------------------------- 3. Protokoll im Importer
def _laeufe(db, art=None):
    return lp.Laufprotokoll(db).letzte(art=art)


def test_suchlauf_wird_protokolliert(cfg, db, ads):
    stat = Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    (lf,) = _laeufe(db)
    assert (lf["art"], lf["ausloeser"], lf["ergebnis"]) == ("suchlauf", "manuell", "ok") and lf["ende"] >= lf["start"]
    assert (lf["neu"], lf["preis"], lf["bekannt"], lf["details"]) == (stat["neu"], stat["preis"], stat["bekannt"], stat["details"]) == (60, 0, 0, 60)
    assert lf["je_quelle"] == {"kleinanzeigen": {"neu": 60, "preis": 0, "bekannt": 0, "ergebnis": "ok"}} and lf["fehler"] is None


def test_sperre_wird_protokolliert_und_pausiert_nur_die_automatik(cfg, db, ads):
    imp = Importer(cfg, db, abruf=AntwortAbruf(QuelleGesperrt("HTTP 429 – Kleinanzeigen blockt gerade.")))
    stat = imp.lauf(cfg["suchen"])
    assert "429" in stat["fehler"]
    (lf,) = _laeufe(db)
    assert lf["ergebnis"] == "gesperrt" and lf["je_quelle"]["kleinanzeigen"]["ergebnis"] == "gesperrt" and "429" in lf["fehler"]
    # Automatik: übersprungen, ohne Abruf
    abrufe = []

    class Zaehler(FakeAbruf):
        def hole(self, url):
            abrufe.append(url)
            return super().hole(url)
    auto = Importer(cfg, db, abruf=Zaehler(ads))
    auto.ausloeser, auto.intervall_beachten = "auto", True
    stat = auto.lauf(cfg["suchen"])
    assert abrufe == [] and stat["neu"] == 0 and stat["uebersprungen"][0]["grund"].startswith("Pause nach Sperre")
    assert _laeufe(db)[0]["ausloeser"] == "auto" and _laeufe(db)[0]["uebersprungen"] == stat["uebersprungen"]
    # von Hand: läuft trotzdem
    hand = Importer(cfg, db, abruf=Zaehler(ads)).lauf(cfg["suchen"])
    assert hand["neu"] == 60 and abrufe


def test_pause_haelt_auch_nach_vielen_uebersprungenen_laeufen(cfg, db, ads):
    """QA B1: Die Pause wird über ein Zeitfenster ausgewertet, nicht über die letzten n Zeilen."""
    Importer(cfg, db, abruf=AntwortAbruf(QuelleGesperrt("HTTP 429 – blockt"))).lauf(cfg["suchen"])
    jetzt = datetime.now()
    db.con.executemany("INSERT INTO suchlaeufe (art, ausloeser, start, ende, ergebnis) VALUES ('suchlauf', 'auto', ?, ?, 'ok')",
                       [((jetzt + timedelta(seconds=i)).isoformat(timespec="seconds"),) * 2 for i in range(250)])
    db.con.commit()
    auto = Importer(cfg, db, abruf=AntwortAbruf(AssertionError("Abruf trotz Pause!")))
    auto.intervall_beachten = True
    assert auto.lauf(cfg["suchen"])["uebersprungen"][0]["grund"].startswith("Pause nach Sperre")
    # Pause abgelaufen: die alte Sperre liegt außerhalb des Fensters
    db.con.execute("UPDATE suchlaeufe SET start=?, ende=? WHERE ergebnis='gesperrt'", ((jetzt - timedelta(hours=25)).isoformat(),) * 2)
    db.con.commit()
    auto = Importer(cfg, db, abruf=FakeAbruf(ads))
    auto.intervall_beachten = True
    assert auto.lauf(cfg["suchen"])["uebersprungen"] == []


def test_layout_warnung_zaehlt_als_fehler_der_quelle(cfg, db):
    """QA B2: Seite geladen, aber nichts erkannt – die Quelle liefert vermutlich nichts mehr; das muss als Fehler in Folge zählen."""
    leer = AntwortAbruf("<html><body>" + "x" * 25000 + "</body></html>")
    for _ in range(3):
        Importer(cfg, db, abruf=leer).lauf(cfg["suchen"])
    q = lp.quellen_status(_laeufe(db), ["kleinanzeigen"], E, datetime.now())["kleinanzeigen"]
    assert q["fehler_in_folge"] == 3 and q["letztes_ergebnis"] == "fehler" and "kleinanzeigen" in q["letzter_fehler"].lower()
    assert any("3 Läufe in Folge mit Fehler" in w for w in lp.uebersicht(db, cfg)["warnungen"])


def test_beschaedigter_eintrag_stoert_nicht(cfg, db, ads, caplog):
    db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start, ende, ergebnis, je_quelle, uebersprungen) "
                   "VALUES ('suchlauf', 'auto', ?, ?, 'ok', '{kaputt', '42')", (datetime.now().isoformat(timespec="seconds"),) * 2)
    db.con.commit()
    with caplog.at_level(logging.WARNING, logger="scout"):
        auto = Importer(cfg, db, abruf=FakeAbruf(ads))
        auto.intervall_beachten = True
        assert auto.lauf(cfg["suchen"])["neu"] == 60
        u = lp.uebersicht(db, cfg)
    assert "beschädigt" in caplog.text and u["laeufe"][1]["je_quelle"] == {} and u["laeufe"][1]["uebersprungen"] == []


def test_intervall_je_quelle(cfg, db, ads):
    cfg["app"]["intervall_stunden_je_quelle"] = {"kleinanzeigen": 6}
    Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    auto = Importer(cfg, db, abruf=AntwortAbruf(AssertionError("kein Abruf im Intervall")))
    auto.intervall_beachten = True
    stat = auto.lauf(cfg["suchen"])
    assert stat["uebersprungen"][0]["grund"].startswith("Intervall: frühestens wieder") and stat["details"] == 0
    db.con.execute("UPDATE suchlaeufe SET start=?", ((datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds"),))
    db.con.commit()
    auto = Importer(cfg, db, abruf=FakeAbruf(ads))
    auto.intervall_beachten = True
    stat = auto.lauf(cfg["suchen"])
    assert stat["uebersprungen"] == [] and stat["bekannt"] > 0                           # Intervall vorbei: Quelle läuft wieder


def test_unerwarteter_fehler_wird_als_abgebrochen_protokolliert(cfg, db):
    with pytest.raises(ZeroDivisionError):
        Importer(cfg, db, abruf=AntwortAbruf(ZeroDivisionError("kaputt"))).lauf(cfg["suchen"])
    (lf,) = _laeufe(db)
    assert lf["ergebnis"] == "abgebrochen" and lf["fehler"] == "ZeroDivisionError: kaputt"


def test_protokoll_scheitert_nie_den_lauf(cfg, db, ads, caplog):
    db.con.execute("DROP TABLE suchlaeufe")
    db.con.commit()
    with caplog.at_level(logging.ERROR, logger="scout"):
        assert Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])["neu"] == 60
    assert "Laufprotokoll" in caplog.text


def test_seitenimport_wird_protokolliert(cfg, db, ads, tmp_path):
    ordner = tmp_path / "import"
    ordner.mkdir()
    imp = Importer(cfg, db)
    imp.importiere_seiten(ordner)
    assert _laeufe(db) == []                                                            # keine Dateien: kein Eintrag
    (ordner / "s.html").write_text(such_html(ads[:3]), encoding="utf-8")
    (ordner / "x.html").write_text(such_html([dict(ads[4], id="md-999")]), encoding="utf-8")      # fehlerhaft
    imp.ausloeser = "cli"
    stat = imp.importiere_seiten(ordner)
    (lf,) = _laeufe(db)
    assert (lf["art"], lf["ausloeser"], lf["ergebnis"], lf["dateien"], lf["neu"]) == ("seiten", "cli", "fehler", 2, 3) == (
        "seiten", "cli", "fehler", stat["dateien"], stat["neu"])
    assert "passt nicht zur Plattform" in lf["fehler"]


def test_alte_eintraege_werden_aufgeraeumt(cfg, db):
    db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start, ergebnis) VALUES ('suchlauf', 'auto', '2020-01-01T00:00:00', 'ok')")
    db.con.commit()
    lp.Laufprotokoll(db).beginne("suchlauf", "manuell")
    assert [r[0] for r in db.con.execute("SELECT start FROM suchlaeufe")] != ["2020-01-01T00:00:00"]
    assert db.con.execute("SELECT COUNT(*) FROM suchlaeufe WHERE start < '2021'").fetchone()[0] == 0


def test_app_suchlauf_automatisch(cfg, ads, monkeypatch):
    s = _suchlauf(cfg, ads, monkeypatch)
    assert s.starte("auto")
    s.thread.join(120)
    from wmscout.datenbank import Datenbank
    (lf,) = _laeufe(Datenbank(cfg["ausgabe"]["datenbank"]))
    assert lf["ausloeser"] == "auto" and lf["ergebnis"] == "ok"


def test_cli_lauf_beachtet_intervalle_ausser_mit_sofort(cfg, db, monkeypatch):
    import scout
    gesehen = []

    class Imp:
        def __init__(self, c, d):
            self.ausloeser, self.intervall_beachten = None, None

        def lauf(self, suchen):
            gesehen.append((self.ausloeser, self.intervall_beachten))
            return {"neu": 0, "preis": 0, "bekannt": 0, "details": 0, "fehler": None, "uebersprungen": []}
    monkeypatch.setattr(scout, "Importer", Imp)
    monkeypatch.setattr(scout, "sende_mail", lambda *a, **k: None)
    scout._lauf(cfg, db)
    scout._lauf(cfg, db, sofort=True)
    assert gesehen == [("cli", True), ("cli", False)]


# ---------------------------------------------------------------- 4. Übersicht, API, Seite
def test_uebersicht_und_warnungen(cfg, db):
    for i in range(3):
        db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start, ende, ergebnis, fehler, je_quelle) VALUES (?, 'auto', ?, ?, 'fehler', ?, ?)",
                       ("suchlauf", iso(hours=i + 1), iso(hours=i + 1), "HTTP 500", '{"kleinanzeigen": {"ergebnis": "fehler", "fehler": "HTTP 500"}}'))
    db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start, ergebnis) VALUES ('mails', 'manuell', ?, 'laeuft')",
                   (iso(days=400 - 399, hours=10),))
    db.con.commit()
    u = lp.uebersicht(db, cfg, JETZT)
    (q,) = [q for q in u["quellen"] if q["kennung"] == "kleinanzeigen"]
    assert q["laeuft"] and q["suchen"] == 1 and q["fehler_in_folge"] == 3 and q["letzter_fehler"] == "HTTP 500"
    assert any("3 Läufe in Folge mit Fehler" in w for w in u["warnungen"]) and any("abgebrochen" in w for w in u["warnungen"])
    assert {e["name"]: e["protokolliert"] for e in u["eingaenge"]} == {"seiten": True, "text": False, "email": True}
    assert next(e for e in u["eingaenge"] if e["name"] == "email")["letztes_ergebnis"] == "abgebrochen"


def test_api_und_seite(server, db, cfg, tmp_path):
    db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start, ende, ergebnis, fehler, je_quelle) VALUES "
                   "('suchlauf', 'manuell', ?, ?, 'fehler', '<script>alert(1)</script>', '{\"kleinanzeigen\": {\"ergebnis\": \"fehler\"}}')",
                   (datetime.now().isoformat(timespec="seconds"),) * 2)
    db.con.commit()
    c = lokal(server)
    s, d, _ = c("GET", "/api/status")
    assert s == 200 and d["laeufe"][0]["fehler"] == "<script>alert(1)</script>" and "suchlauf" in d and d["quellen"]
    s, html, _ = c("GET", "/status")
    assert s == 200 and 'data-quelle="kleinanzeigen"' in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert" not in html
    assert 'data-lauf="' in html
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    ben = anmelden(server, "Ben")
    assert ben("GET", "/api/status")[0] == 200 and ben("GET", "/status")[0] == 200
    hugo = anmelden(server, "Hugo")
    assert hugo("GET", "/api/status")[0] == 403 and hugo("GET", "/status")[0] == 403


def test_oberflaeche_statisch():
    from tests.daten import BASIS
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    js = (BASIS / "wmscout" / "web" / "static" / "mobil.js").read_text(encoding="utf-8")
    status = (BASIS / "vorlagen" / "status.html").read_text(encoding="utf-8")
    assert 'href="/status"' in html and 'href="/status"' in js and "|safe" not in status and "<script" not in status
    sw = (BASIS / "wmscout" / "web" / "static" / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"var VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 16 and "16: " in sw


# ---------------------------------------------------------------- 5. Schema 19
def bis_19(monkeypatch):
    _alt_schritte(monkeypatch, 19)


def baue_v18(pfad, monkeypatch, tmp_path):
    baue_v17(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 18)
        assert migriere(pfad, tmp_path / "stand18") == [18]
    assert lese_version(pfad) == 18


@pytest.mark.parametrize("art", ["v1", "v18"])
def test_migration_auf_19_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_19(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v18":
        baue_v18(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    assert migriere(pfad, ziel)[-1] == 19 and lese_version(pfad) == 19 and versionen(pfad)[-1] == 19
    neue = {t: v_ for t, v_ in vorher.items() if t not in ("fahrzeuge", "suchprofile")}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    assert _sql(pfad, "SELECT COUNT(*) FROM suchlaeufe") == [(0,)] and _sql(pfad, "PRAGMA integrity_check") == [("ok",)]
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v19" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_19_zweite_ausfuehrung_und_rollback(tmp_path, monkeypatch):
    bis_19(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v18(pfad, monkeypatch, tmp_path)
    vorher, echt = _abbild(pfad), migrationen._schritt_19

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")
    monkeypatch.setitem(migrationen.SCHRITTE, 19, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 18 and _abbild(pfad) == vorher
    assert "suchlaeufe" not in {r[0] for r in _sql(pfad, "SELECT name FROM sqlite_master WHERE type='table'")}
    monkeypatch.setitem(migrationen.SCHRITTE, 19, echt)
    assert migriere(pfad, ziel) == [19]
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    schema = _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_19(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def test_neue_datenbank_hat_die_tabelle(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 19
    assert "suchlaeufe" in {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
