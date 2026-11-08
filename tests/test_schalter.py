"""Quellen und Eingänge einzeln schaltbar (P2-04, ADR-036): übersprungen ≠ Fehler, Freigabe im Code, Schalter in Tabelle/config."""
import copy
import threading
from collections.abc import Iterator

import pytest
import yaml

import scout
from tests.daten import BASIS, FakeAbruf, such_html
from tests.test_cli import _scout
from tests.test_handy import Client
from wmscout import quellen
from wmscout.app import erstelle_server
from wmscout.importer import Importer
from wmscout.quellen import Inserat, Quelle, Suchauftrag, Suchseite
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle
from wmscout.schalter import (STANDARD_EINGAENGE, EingangDeaktiviert, QuelleNichtSchaltbar, bewerte_quelle, eingang_aktiv,
                              eingang_pruefen, eingaenge, quelle_zeile, setze_quelle)
from wmscout.team import TeamSpeicher


class FreieTestQuelle(Quelle):
    kennung = "test_frei"
    name = "Freie Testquelle"
    zugriffsart = "manuell"
    freigegeben = True
    aufrufe = 0

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        type(self).aufrufe += 1
        yield Suchseite(1, [Inserat(quelle=self.kennung, anzeigen_id="f1", url="https://example.org/f1", titel="Hymer B 678 SL",
                                    preis=39900, ez_jahr=2016, km=90000, ort="80331 München")])


SUCHE_FREI = [{"name": "Integrierter", "quelle": "test_frei"}]


@pytest.fixture
def frei(monkeypatch):
    FreieTestQuelle.aufrufe = 0
    monkeypatch.setitem(quellen.QUELLEN, FreieTestQuelle.kennung, FreieTestQuelle)
    return FreieTestQuelle


def echte_kleinanzeigen(monkeypatch):
    monkeypatch.setitem(quellen.QUELLEN, "kleinanzeigen", KleinanzeigenQuelle)     # statt der freigegebenen Testvariante der cfg-Fixture


# ---------- Pull-Quellen: Code-Freigabe + Schalter ----------
def test_standard_konfiguration_ueberspringt_kleinanzeigen_ohne_fehler_und_ohne_netz(cfg, db, ads, monkeypatch):
    echte_kleinanzeigen(monkeypatch)
    abruf = FakeAbruf(ads)
    stat = Importer(cfg, db, abruf=abruf).lauf(cfg["suchen"])
    assert stat["fehler"] is None                                  # kein Fehlertext (None = wie bisher „kein Fehler“)
    assert stat["uebersprungen"] == [{"quelle": "kleinanzeigen", "grund": "nicht freigegeben"}]   # eine Meldung je Quelle
    assert abruf.abrufe == [] and stat["neu"] == 0 and stat["details"] == 0


def test_mehrere_suchen_einer_quelle_eine_meldung(cfg, db, monkeypatch):
    echte_kleinanzeigen(monkeypatch)
    stat = Importer(cfg, db, abruf=FakeAbruf([])).lauf(cfg["suchen"] * 3)
    assert len(stat["uebersprungen"]) == 1


def test_freigegeben_ohne_tabellenzeile_laeuft(cfg, db, frei):
    assert quelle_zeile(db, "test_frei") is None
    stat = Importer(cfg, db).lauf(SUCHE_FREI)
    assert stat["neu"] == 1 and stat["fehler"] is None and stat["uebersprungen"] == [] and frei.aufrufe == 1


def test_freigegeben_aber_ausgeschaltet_wird_uebersprungen(cfg, db, frei):
    setze_quelle(db, frei, False)
    stat = Importer(cfg, db).lauf(SUCHE_FREI)
    assert stat["uebersprungen"] == [{"quelle": "test_frei", "grund": "deaktiviert"}]
    assert stat["fehler"] is None and stat["neu"] == 0 and frei.aufrufe == 0
    setze_quelle(db, frei, True)
    stat = Importer(cfg, db).lauf(SUCHE_FREI)
    assert stat["neu"] == 1 and stat["uebersprungen"] == [] and frei.aufrufe == 1


def test_aktiv_in_tabelle_ersetzt_keine_code_freigabe(cfg, db, ads, monkeypatch):
    """aktiv=1 in der Tabelle (von Hand) gibt eine im Code gesperrte Quelle nicht frei (Regel 12)."""
    echte_kleinanzeigen(monkeypatch)
    db.con.execute("UPDATE quellen SET freigegeben=1, aktiv=1 WHERE kennung='kleinanzeigen'")
    db.con.commit()
    abruf = FakeAbruf(ads)
    stat = Importer(cfg, db, abruf=abruf).lauf(cfg["suchen"])
    assert stat["uebersprungen"] == [{"quelle": "kleinanzeigen", "grund": "nicht freigegeben"}] and abruf.abrufe == []


def test_andere_quellen_laufen_weiter(cfg, db, frei, ads, monkeypatch):
    echte_kleinanzeigen(monkeypatch)
    abruf = FakeAbruf(ads)
    stat = Importer(cfg, db, abruf=abruf).lauf(cfg["suchen"] + SUCHE_FREI)
    assert stat["neu"] == 1 and [u["quelle"] for u in stat["uebersprungen"]] == ["kleinanzeigen"] and abruf.abrufe == []


def test_seed_zeile_bedeutet_nicht_entschieden(db):
    """Die Migration legt kleinanzeigen mit 0/0 an: gilt wie „keine Zeile“ (Code entscheidet), nicht als „aus“."""
    assert dict(quelle_zeile(db, "kleinanzeigen")) == {"kennung": "kleinanzeigen", "zugriffsart": "web", "freigegeben": 0, "aktiv": 0}
    assert bewerte_quelle(True, quelle_zeile(db, "kleinanzeigen")) == (True, None)
    assert bewerte_quelle(False, quelle_zeile(db, "kleinanzeigen")) == (False, "nicht freigegeben")
    assert bewerte_quelle(True, {"freigegeben": 1, "aktiv": 0}) == (False, "deaktiviert")
    assert bewerte_quelle(True, {"freigegeben": 1, "aktiv": 1}) == (True, None)


def test_an_wird_fuer_nicht_freigegebene_quelle_verweigert(cfg, db):
    vorher = [tuple(z) for z in db.con.execute("SELECT * FROM quellen ORDER BY kennung")]
    with pytest.raises(QuelleNichtSchaltbar, match="nicht freigegeben"):
        setze_quelle(db, KleinanzeigenQuelle, True)
    assert [tuple(z) for z in db.con.execute("SELECT * FROM quellen ORDER BY kennung")] == vorher


def test_aus_fuer_nicht_freigegebene_quelle_wird_abgelehnt(cfg, db, monkeypatch):
    """F1: 0/0 wäre „nicht entschieden“ – eine spätere Code-Freigabe liefe ohne Zustimmung. Also ehrlich ablehnen."""
    echte_kleinanzeigen(monkeypatch)
    vorher = [tuple(z) for z in db.con.execute("SELECT * FROM quellen ORDER BY kennung")]
    with pytest.raises(QuelleNichtSchaltbar, match="läuft ohnehin nicht .*nichts gespeichert"):
        setze_quelle(db, KleinanzeigenQuelle, False)
    assert [tuple(z) for z in db.con.execute("SELECT * FROM quellen ORDER BY kennung")] == vorher


def test_aus_bleibt_nach_neuem_importer_deaktiviert_und_zugriffsart_wird_gesetzt(cfg, db, frei):
    db.con.execute("INSERT INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES ('test_frei', 'web', 0, 0)")
    db.con.commit()
    setze_quelle(db, frei, False)
    assert dict(quelle_zeile(db, "test_frei")) == {"kennung": "test_frei", "zugriffsart": "manuell", "freigegeben": 1, "aktiv": 0}
    for _ in range(2):                                              # auch ein neuer Importer (Neustart) ändert daran nichts
        assert Importer(cfg, db).lauf(SUCHE_FREI)["uebersprungen"] == [{"quelle": "test_frei", "grund": "deaktiviert"}]
    assert frei.aufrufe == 0


def test_detailabruf_bleibt_fuer_nicht_freigegebene_quelle_gesperrt(cfg, db, ads, monkeypatch):
    echte_kleinanzeigen(monkeypatch)
    abruf = FakeAbruf(ads)
    db.speichere_treffer({"id": ads[0]["id"], "quelle": "kleinanzeigen", "url": f"https://www.kleinanzeigen.de/s-anzeige/foo/{ads[0]['id']}-220-1",
                          "titel": "Beispiel"}, "Kastenwagen")
    importer = Importer(cfg, db, abruf=abruf)
    with pytest.raises(quellen.QuellenFehler, match="nicht freigegeben"):
        importer.details()
    stat = importer.lauf(cfg["suchen"])                            # der Suchlauf lässt die Zeile aus, ohne Fehler und ohne Netz
    assert stat["fehler"] is None and abruf.abrufe == []
    assert db.con.execute("SELECT detail_geladen FROM anzeigen").fetchone()[0] == 0


# ---------- CLI quellen ----------
def tabelle(db):
    return [tuple(z) for z in db.con.execute("SELECT * FROM quellen ORDER BY kennung")]


def test_cli_quellen_liste_und_verweigertes_an(cfg, tmp_path, db):
    db.con.close()
    r = _scout(cfg, tmp_path, "quellen", "liste")
    assert r.returncode == 0, r.stderr
    assert "kleinanzeigen" in r.stdout and "übersprungen (nicht freigegeben)" in r.stdout
    assert "seiten" in r.stdout and "email" in r.stdout and "config.local.yaml" in r.stdout
    vorher = tabelle(scout.Datenbank(str(tmp_path / "anzeigen.sqlite")))
    r = _scout(cfg, tmp_path, "quellen", "an", "kleinanzeigen")
    assert r.returncode != 0 and "nicht freigegeben" in r.stderr
    assert tabelle(scout.Datenbank(str(tmp_path / "anzeigen.sqlite"))) == vorher
    r = _scout(cfg, tmp_path, "quellen", "an", "gibtsnicht")
    assert r.returncode != 0 and "Unbekannte Quelle" in r.stderr


def test_cli_quellen_an_aus_fuer_freigegebene_quelle(cfg, db, frei, capsys, monkeypatch):
    import argparse
    args = lambda aktion, kennung=None: argparse.Namespace(aktion=aktion, kennung=kennung)     # noqa: E731
    scout.cmd_quellen(cfg, db, args("aus", "test_frei"))
    assert dict(quelle_zeile(db, "test_frei")) == {"kennung": "test_frei", "zugriffsart": "manuell", "freigegeben": 1, "aktiv": 0}
    assert Importer(cfg, db).lauf(SUCHE_FREI)["uebersprungen"][0]["grund"] == "deaktiviert"
    scout.cmd_quellen(cfg, db, args("liste"))
    assert "übersprungen (deaktiviert)" in capsys.readouterr().out
    scout.cmd_quellen(cfg, db, args("an", "test_frei"))
    assert quelle_zeile(db, "test_frei")["aktiv"] == 1 and Importer(cfg, db).lauf(SUCHE_FREI)["neu"] == 1
    echte_kleinanzeigen(monkeypatch)
    vorher = tabelle(db)
    with pytest.raises(SystemExit, match="nicht freigegeben"):
        scout.cmd_quellen(cfg, db, args("an", "kleinanzeigen"))
    assert tabelle(db) == vorher


# ---------- Eingänge (config) ----------
def test_eingaenge_standardwerte_und_hilfsfunktion():
    assert STANDARD_EINGAENGE == {"seiten": True, "text": True, "email": False}
    assert eingaenge({}) == STANDARD_EINGAENGE and eingaenge({"eingaenge": None}) == STANDARD_EINGAENGE
    assert eingang_aktiv({}, "seiten") and eingang_aktiv({}, "text") and not eingang_aktiv({}, "email")
    cfg = {"eingaenge": {"seiten": {"aktiv": False}, "email": {"aktiv": True}, "text": None}}
    assert not eingang_aktiv(cfg, "seiten") and eingang_aktiv(cfg, "email") and eingang_aktiv(cfg, "text")
    with pytest.raises(EingangDeaktiviert, match="config"):
        eingang_pruefen(cfg, "seiten")
    with pytest.raises(ValueError, match="Unbekannter Eingang"):
        eingang_aktiv({}, "fax")


@pytest.mark.parametrize("kaputt", [
    {"seiten": {"aktiv": "ja"}}, {"seiten": {"aktiv": 1}}, {"seiten": True}, {"seiten": {"an": True}}, {"fax": {"aktiv": True}}, ["seiten"],
])
def test_eingaenge_ungueltig(kaputt):
    with pytest.raises(ValueError, match="eingaenge"):
        eingaenge({"eingaenge": kaputt})


def test_cli_ungueltige_eingaenge_melden_beim_start(cfg, tmp_path):
    for kaputt in ({"seiten": {"aktiv": "vielleicht"}}, {"fax": {"aktiv": True}}):
        r = _scout({**cfg, "eingaenge": kaputt}, tmp_path, "report")
        assert r.returncode != 0 and "eingaenge" in r.stderr, r.stderr
    assert not (tmp_path / "ausgabe" / "report.html").exists()


# ---------- Eingang seiten: Importer, CLI, API ----------
def seitendatei(ordner, ads):
    datei = ordner / "suche.html"
    datei.write_text(such_html(ads[:4]), encoding="utf-8")
    return datei


@pytest.fixture
def ordner(cfg, tmp_path):
    o = tmp_path / "import"
    o.mkdir()
    cfg["import"] = {"ordner": str(o)}
    return o


def aus(cfg):
    cfg["eingaenge"] = {"seiten": {"aktiv": False}}
    return cfg


def test_importer_liest_bei_abgeschaltetem_eingang_nichts(cfg, db, ordner, ads):
    datei = seitendatei(ordner, ads)
    with pytest.raises(EingangDeaktiviert):
        Importer(aus(cfg), db).importiere_seiten(ordner)
    assert datei.is_file() and not (ordner / "eingelesen").exists()
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0
    cfg["eingaenge"] = {"seiten": {"aktiv": True}}
    assert Importer(cfg, db).importiere_seiten(ordner)["neu"] == 4 and not datei.is_file()


def test_cli_import_abgeschaltet_und_eingeschaltet(cfg, tmp_path, ordner, ads):
    datei = seitendatei(ordner, ads)
    r = _scout(aus(cfg), tmp_path, "import", "--ordner", str(ordner))
    assert r.returncode == 0, r.stderr
    assert "abgeschaltet" in r.stdout and "eingaenge" in r.stdout and "nichts gelesen" in r.stdout
    assert datei.is_file() and not (ordner / "eingelesen").exists() and "Gespeicherte Seiten einlesen" not in r.stdout
    neuer = tmp_path / "neu"
    r = _scout(aus(cfg), tmp_path, "import", "--ordner", str(neuer))
    assert r.returncode == 0 and not neuer.exists()                 # auch der Ordner wird nicht angelegt
    r = _scout({**cfg, "eingaenge": {"seiten": {"aktiv": True}}}, tmp_path, "import", "--ordner", str(ordner))
    assert r.returncode == 0, r.stderr
    assert "4 neue Anzeigen" in r.stdout and not datei.is_file()


def test_api_import_abgeschaltet_409(cfg, db, ordner, ads, tmp_path):
    datei = seitendatei(ordner, ads)
    srv, _, _ = erstelle_server(aus(cfg), db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        lokal = Client(port)
        lokal.csrf = lokal("GET", "/api/ich")[1]["csrf"]
        status, daten, _ = lokal("POST", "/api/import", {})
        assert status == 409 and daten["grund"] == "deaktiviert" and "abgeschaltet" in daten["fehler"] and "eingaenge" in daten["fehler"]
        assert datei.is_file() and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0
        TeamSpeicher(db, tmp_path / "fotos").nutzer_anlegen("Anna", "sicher1234", "inhaber")
        assert Client(port).anmelden("Anna")("POST", "/api/import", {})[0] == 409
        assert datei.is_file()
    finally:
        srv.shutdown()
        srv.server_close()
    cfg2 = copy.deepcopy(cfg)
    cfg2["eingaenge"] = {"seiten": {"aktiv": True}}
    srv, _, _ = erstelle_server(cfg2, db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, daten, _ = Client(srv.server_address[1]).anmelden("Anna")("POST", "/api/import", {})
        assert status == 200 and daten["neu"] == 4 and not datei.is_file()
    finally:
        srv.shutdown()
        srv.server_close()


def test_config_yaml_enthaelt_eingaenge_mit_standardwerten():
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    assert eingaenge(cfg) == STANDARD_EINGAENGE and cfg["eingaenge"]["email"] == {"aktiv": False}


def test_app_suchlauf_meldet_uebersprungene_quelle_ohne_fehler(cfg, ads, monkeypatch):
    from wmscout import app as app_modul
    echte_kleinanzeigen(monkeypatch)
    abruf = FakeAbruf(ads)
    monkeypatch.setattr(app_modul, "Importer", lambda c, db: Importer(c, db, abruf=abruf))
    lauf = app_modul.Suchlauf(cfg, cfg["ausgabe"]["datenbank"], BASIS)
    assert lauf.starte() is True
    lauf.thread.join(120)
    assert not lauf.stand["fehler"] and not lauf.stand["laeuft"] and abruf.abrufe == []
    assert lauf.stand["meldung"] == "Fertig: 0 neue Anzeigen, davon 0 mit Anschreiben · 0 Preissenkungen · übersprungen: kleinanzeigen (nicht freigegeben)"


# ---------- Detailabruf: gesperrte Quellen blockieren das LIMIT nicht (F3) ----------
class GesperrteTestQuelle(FreieTestQuelle):
    kennung = "test_gesperrt"
    name = "Gesperrte Testquelle"
    freigegeben = False


def _zeile(db, ad_id, quelle, wann):
    db.speichere_treffer({"id": ad_id, "quelle": quelle, "url": f"https://example.org/{ad_id}", "titel": "Beispiel"}, "Kastenwagen")
    db.con.execute("UPDATE anzeigen SET erstmals_gesehen=? WHERE id=?", (wann, ad_id))
    db.con.commit()


def test_details_gesperrte_zeilen_ohne_details_werden_nicht_gezaehlt_und_nicht_abgerufen(cfg, db, ads, monkeypatch):
    echte_kleinanzeigen(monkeypatch)
    _zeile(db, "k1", "kleinanzeigen", "2026-10-01T10:00:00")
    abruf = FakeAbruf(ads)
    stat = Importer(cfg, db, abruf=abruf).lauf([])
    assert stat["details"] == 0 and stat["fehler"] is None and abruf.abrufe == []
    assert db.con.execute("SELECT detail_geladen FROM anzeigen WHERE id='k1'").fetchone()[0] == 0


def test_details_aeltere_zeile_laufender_quelle_wird_trotz_neuerer_gesperrter_zeilen_bearbeitet(cfg, db, frei, monkeypatch):
    monkeypatch.setitem(quellen.QUELLEN, GesperrteTestQuelle.kennung, GesperrteTestQuelle)
    cfg["crawler"]["detailseiten_pro_lauf"] = 3
    _zeile(db, "alt", "test_frei", "2026-10-01T10:00:00")
    for n in range(5):                                              # mehr neuere gesperrte Zeilen als das Limit
        _zeile(db, f"g{n}", "test_gesperrt", f"2026-10-02T10:00:0{n}")
    stat = Importer(cfg, db).lauf([])
    assert stat["details"] == 1 and stat["fehler"] is None            # nur die tatsächlich bearbeitete Zeile
    assert db.con.execute("SELECT detail_geladen FROM anzeigen WHERE id='alt'").fetchone()[0] == 1
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen WHERE id LIKE 'g%' AND detail_geladen=0").fetchone()[0] == 5


def test_ohne_details_leere_quelle_zaehlt_als_standard_quelle(db):
    _zeile(db, "n1", "kleinanzeigen", "2026-10-01T10:00:00")
    db.con.execute("UPDATE anzeigen SET quelle=NULL WHERE id='n1'")
    db.con.commit()
    assert [r["id"] for r in db.ohne_details(10, {"kleinanzeigen"})] == ["n1"] and db.ohne_details(10, {"test_frei"}) == []
    assert db.ohne_details(10, set()) == []


# ---------- Ereigniseingang api/stream: Code-Freigabe der Klasse zählt zusätzlich (F4) ----------
def _ereignis(plattform):
    from datetime import datetime, timezone
    from wmscout.ereignisse import InseratEreignis
    i = Inserat(quelle=plattform, anzeigen_id="123", url="https://beispiel.invalid/123", titel="Knaus Sky TI", preis=34000, ez_jahr=2018, km=70000)
    return InseratEreignis(plattform, "123", "neu", "api", datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc), i)


def test_ereigniseingang_verlangt_auch_die_code_freigabe_der_klasse(cfg, db, monkeypatch):
    from wmscout.ereignis_speicher import QuelleNichtFreigegeben
    db.con.execute("UPDATE quellen SET zugriffsart='api', freigegeben=1, aktiv=1 WHERE kennung='kleinanzeigen'")   # Tabelle allein genügt nicht
    db.con.commit()
    echte_kleinanzeigen(monkeypatch)
    with pytest.raises(QuelleNichtFreigegeben):
        Importer(cfg, db).importiere_ereignis(_ereignis("kleinanzeigen"))
    assert db.con.execute("SELECT COUNT(*) FROM inserate").fetchone()[0] == 0
    monkeypatch.undo()                                                # cfg-Fixture hatte die Klasse freigegeben
    monkeypatch.setitem(quellen.QUELLEN, "kleinanzeigen", type("Frei", (KleinanzeigenQuelle,), {"freigegeben": True}))
    assert Importer(cfg, db).importiere_ereignis(_ereignis("kleinanzeigen")) == "neu"


# ---------- CLI: Argumentfehler (F9) ----------
def test_cli_quellen_argumentfehler(cfg, tmp_path, db):
    db.con.close()
    for aktion in ("an", "aus"):
        r = _scout(cfg, tmp_path, "quellen", aktion)
        assert r.returncode != 0 and "Kennung fehlt" in r.stderr and "kleinanzeigen" in r.stderr
    r = _scout(cfg, tmp_path, "quellen", "liste", "kleinanzeigen")
    assert r.returncode != 0 and "keine Kennung" in r.stderr
    r = _scout(cfg, tmp_path, "quellen", "aus", "kleinanzeigen")      # F1 über die Kommandozeile
    assert r.returncode != 0 and "läuft ohnehin nicht" in r.stderr and "nichts gespeichert" in r.stderr
