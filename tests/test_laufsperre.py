"""P1-04: Laufsperre – höchstens ein Suchlauf je Datenbank, auch über Prozessgrenzen; Absturz gibt die Sperre frei."""
from __future__ import annotations

import multiprocessing
import subprocess
import sys

import pytest
import yaml

from tests import prozess_helfer
from tests.daten import BASIS
from wmscout import app as app_modul
from wmscout.datenbank import Datenbank
from wmscout.laufsperre import Laufsperre, sperrdatei
from wmscout.sicherung import SicherungsFehler, sichere, wiederherstellen


@pytest.fixture
def fremder_lauf(tmp_path):
    """Ein anderer Prozess hält die Laufsperre (wie „scout.py lauf“ aus der Aufgabenplanung)."""
    pfad = str(tmp_path / "anzeigen.sqlite")
    ctx = multiprocessing.get_context("spawn")
    bereit, ende = ctx.Event(), ctx.Event()
    p = ctx.Process(target=prozess_helfer.halte_laufsperre, args=(pfad, bereit, ende))
    p.start()
    assert bereit.wait(60), "Hilfsprozess hat die Sperre nicht bekommen"
    yield pfad, p, ende
    ende.set()
    p.join(30)
    if p.is_alive():
        p.kill()


def test_zweite_sperre_derselben_datenbank_scheitert_bis_zur_freigabe(tmp_path):
    a, b = Laufsperre(tmp_path / "x.sqlite"), Laufsperre(tmp_path / "x.sqlite")
    assert a.erwerben() and a.gehalten
    assert not b.erwerben() and not b.gehalten
    a.freigeben()
    assert b.erwerben()
    b.freigeben()
    assert Laufsperre(tmp_path / "andere.sqlite").erwerben()        # andere Datenbank: eigene Sperre
    assert sperrdatei(tmp_path / "x.sqlite").name == "x.sqlite.laufsperre"


def test_doppeltes_erwerben_mit_demselben_objekt_ist_ein_programmfehler(tmp_path):
    s = Laufsperre(tmp_path / "x.sqlite")
    assert s.erwerben()
    with pytest.raises(RuntimeError):
        s.erwerben()
    s.freigeben()
    s.freigeben()                                                     # doppelte Freigabe schadet nicht


def test_sperre_gilt_ueber_prozessgrenzen_und_absturz_gibt_sie_frei(tmp_path):
    pfad = str(tmp_path / "anzeigen.sqlite")
    ctx = multiprocessing.get_context("spawn")
    bereit = ctx.Event()
    prozess = ctx.Process(target=prozess_helfer.halte_laufsperre, args=(pfad, bereit, None))   # ohne Ende-Ereignis: Kill
    prozess.start()
    try:
        assert bereit.wait(60), "Hilfsprozess hat die Sperre nicht bekommen"
        assert not Laufsperre(pfad).erwerben()
    finally:
        prozess.kill()                                                # Absturz: keine Freigabe durch das Programm
        prozess.join(30)
    s = Laufsperre(pfad)
    assert s.erwerben()                                               # das Betriebssystem hat die Sperre freigegeben
    s.freigeben()


def test_app_suche_startet_nicht_neben_fremdem_lauf(cfg, fremder_lauf, monkeypatch):
    pfad, _, _ = fremder_lauf
    gestartet = []
    monkeypatch.setattr(app_modul.Suchlauf, "_lauf", lambda self, sperre=None: gestartet.append(1))
    lauf = app_modul.Suchlauf(cfg, pfad, BASIS)
    assert lauf.starte() is False
    assert gestartet == [] and lauf.thread is None and not lauf.stand["laeuft"]
    assert "bereits ein Suchlauf" in lauf.stand["meldung"]


def test_app_suche_gibt_die_sperre_auch_nach_einem_fehler_frei(cfg, monkeypatch):
    class Kaputt:
        def __init__(self, *a, **k):
            raise RuntimeError("Abbruch im Suchlauf")

    monkeypatch.setattr(app_modul, "Importer", Kaputt)
    lauf = app_modul.Suchlauf(cfg, cfg["ausgabe"]["datenbank"], BASIS)
    assert lauf.starte() is True
    lauf.thread.join(60)
    assert lauf.stand["fehler"] == "Abbruch im Suchlauf"
    s = Laufsperre(cfg["ausgabe"]["datenbank"])
    assert s.erwerben()                                               # freigegeben trotz Fehler
    s.freigeben()


def test_scout_lauf_ueberspringt_neben_fremdem_lauf(cfg, fremder_lauf, tmp_path):
    """Echter Aufruf von „scout.py lauf“ (wie die Aufgabenplanung): übersprungen, kein Abruf, Rückgabecode 0."""
    pfad, _, _ = fremder_lauf
    cfg["ausgabe"]["datenbank"] = pfad
    cfg["suchen"] = [{"name": "Teilintegrierter", "url": "http://127.0.0.1:9/nie-abgerufen"}]
    datei = tmp_path / "config.yaml"
    datei.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    r = subprocess.run([sys.executable, str(BASIS / "scout.py"), "--config", str(datei), "lauf"],
                       capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=BASIS)
    assert r.returncode == 0, r.stderr
    assert "Suchlauf übersprungen" in r.stderr + r.stdout
    assert "Crawl fertig" not in r.stderr + r.stdout and not list((tmp_path / "ausgabe").glob("*.html"))   # nicht begonnen


def test_wiederherstellung_wartet_nicht_auf_laufenden_suchlauf(tmp_path):
    pfad, ziel = tmp_path / "daten" / "anzeigen.sqlite", tmp_path / "sicherungen"
    db = Datenbank(str(pfad))
    db.speichere_treffer({"id": "a1", "url": "u", "titel": "Hymer", "preis": 30000}, "Alkoven")
    kopie = sichere(pfad, ziel)
    db.speichere_treffer({"id": "a2", "url": "u", "titel": "Knaus", "preis": 31000}, "Alkoven")
    db.con.close()
    lauf = Laufsperre(pfad)
    assert lauf.erwerben()
    try:
        with pytest.raises(SicherungsFehler, match="Suchlauf läuft"):
            wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
        assert not list(ziel.glob("*vor-wiederherstellung*"))           # nichts verändert, keine Zusatz-Sicherung
    finally:
        lauf.freigeben()
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
    s = Laufsperre(pfad)
    assert s.erwerben()                                               # die Wiederherstellung hat die Sperre wieder freigegeben
    s.freigeben()


def test_unbestaetigte_wiederherstellung_legt_keine_sperrdatei_an(tmp_path):
    pfad = tmp_path / "daten" / "anzeigen.sqlite"
    with pytest.raises(SicherungsFehler, match="bestaetigt"):
        wiederherstellen(tmp_path / "gibt-es-nicht.sqlite", pfad)
    assert not sperrdatei(pfad).exists()
