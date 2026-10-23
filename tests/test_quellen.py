"""Quellen-Interface, Kleinanzeigen-Adapter/Parser und Fehlerverhalten des Importers."""
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.daten import AntwortAbruf, FakeAbruf, detail_html, such_html
from wmscout import quellen
from wmscout.importer import Importer
from wmscout.quellen import (QUELLEN, ZUGRIFFSARTEN, Inserat, NetzwerkFehler, Quelle, QuellenFehler, Suchauftrag,
                             Suchseite, erstelle_quelle)
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle, seiten_url
from wmscout.quellen.kleinanzeigen.parser import parse_detailseite, parse_suchseite


# ---------- Vertrag: jede registrierte Quelle ----------
@pytest.mark.parametrize("klasse", list(QUELLEN.values()), ids=list(QUELLEN))
def test_vertrag_jeder_quelle(klasse, cfg):
    assert klasse.kennung and klasse.name
    assert klasse.zugriffsart in ZUGRIFFSARTEN
    assert isinstance(klasse.freigegeben, bool)
    if not klasse.freigegeben:
        assert klasse.hinweis, "nicht freigegebene Quellen brauchen einen Hinweis"
    q = erstelle_quelle(klasse.kennung, cfg, AntwortAbruf("<html></html>"))
    assert isinstance(q, Quelle)


def test_kleinanzeigen_ist_nicht_freigegeben():
    assert KleinanzeigenQuelle.zugriffsart == "web" and KleinanzeigenQuelle.freigegeben is False


def test_unbekannte_quelle(cfg):
    with pytest.raises(QuellenFehler, match="Unbekannte Quelle"):
        erstelle_quelle("gibtsnicht", cfg)


# ---------- Kleinanzeigen ----------
def test_seiten_url():
    assert seiten_url("https://x.de/s-wohnwagen-mobile/anbieter:privat/c220+a:b", 3) == \
        "https://x.de/s-wohnwagen-mobile/anbieter:privat/seite:3/c220+a:b"
    assert seiten_url("https://x.de/a/seite:4/c220", 1) == "https://x.de/a/c220"


def test_parser(ads):
    p = parse_suchseite(such_html(ads[:25]))
    assert len(p) == 25 and p[0]["preis"] == ads[0]["preis"] and p[0]["ez_jahr"] == ads[0]["ez"]
    assert p[0]["bild"].endswith(f"{ads[0]['id']}.jpg")
    d = parse_detailseite(detail_html(ads[0]))
    assert (d["km"], d["marke"], d["ez_jahr"]) == (ads[0]["km"], ads[0]["marke"], ads[0]["ez"])
    d = parse_detailseite(detail_html({**ads[0], "titel": "Fiat Ducato Knaus Sky TI 650"}, marke_feld="Fiat"))
    assert d["marke"] == "Knaus"                              # Aufbauhersteller vor Basisfahrzeug


def test_adapter_liefert_inserate(cfg, ads):
    q = KleinanzeigenQuelle(cfg, FakeAbruf(ads))
    seiten = list(q.suche(Suchauftrag(name="Teilintegrierter", url="https://www.kleinanzeigen.de/s/c220")))
    assert [len(s.inserate) for s in seiten] == [25, 25, 10, 0]
    i = seiten[0].inserate[0]
    assert isinstance(i, Inserat) and i.quelle == "kleinanzeigen" and i.anzeigen_id == ads[0]["id"]
    d = q.details(i.url)
    assert d.km == ads[0]["km"] and d.anzeigen_id == ads[0]["id"]


def test_suchauftrag_aus_config():
    a = Suchauftrag.aus_config({"name": "Alkoven", "url": "https://x/c220", "preis_max": 40000})
    assert a.quelle == "kleinanzeigen" and a.parameter == {"preis_max": 40000}


# ---------- Fehlerverhalten ----------
def test_layout_waechter(cfg, db):
    seite = "<html><body>" + "<div class='neues-design'>Anzeige</div>" * 2000 + "</body></html>"
    stat = Importer(cfg, db, abruf=AntwortAbruf(seite)).lauf(cfg["suchen"])
    assert stat["fehler"] and "Seitenlayout" in stat["fehler"]
    assert (Path(cfg["ausgabe"]["ordner"]) / "diagnose_suchseite.html").exists()


def test_captcha_bricht_sauber_ab(cfg, db):
    stat = Importer(cfg, db, abruf=AntwortAbruf("<html>Bitte lösen Sie das Captcha</html>")).lauf(cfg["suchen"])
    assert "Captcha" in stat["fehler"] and stat["neu"] == 0


def test_netzwerkfehler_bricht_sauber_ab(cfg, db):
    stat = Importer(cfg, db, abruf=AntwortAbruf(NetzwerkFehler("Netzwerkfehler: Zeitüberschreitung"))).lauf(cfg["suchen"])
    assert stat["fehler"].startswith("Netzwerkfehler")


def test_geloeschtes_inserat(cfg, db, ads):
    stat = Importer(cfg, db, abruf=FakeAbruf(ads, fehlend={ads[3]["id"]})).lauf(cfg["suchen"])
    assert stat["fehler"] is None and stat["details"] == 60
    # P3-04: nicht mehr vorhanden = Verfügbarkeit „offline“ am Inserat; der Ankaufsstatus bleibt, wie er war (kein „gelöscht“ mehr)
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (ads[3]["id"],)).fetchone()["status"] in (None, "neu")
    assert db.con.execute("SELECT verfuegbarkeit FROM inserate WHERE anzeigen_id=?", (ads[3]["id"],)).fetchone()["verfuegbarkeit"] == "offline"


# ---------- neue Quelle über das Interface ----------
class ManuelleTestQuelle(Quelle):
    kennung = "test_manuell"
    name = "Testquelle"
    zugriffsart = "manuell"
    freigegeben = True

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        yield Suchseite(1, [Inserat(quelle=self.kennung, anzeigen_id="m1", url="https://example.org/m1",
                                    titel="Hymer B 678 SL", preis=39900, ez_jahr=2016, km=90000, ort="80331 München")])


def test_neue_quelle_wird_importiert(cfg, db, monkeypatch):
    monkeypatch.setitem(quellen.QUELLEN, ManuelleTestQuelle.kennung, ManuelleTestQuelle)
    stat = Importer(cfg, db).lauf([{"name": "Integrierter", "quelle": "test_manuell"}])
    assert stat["neu"] == 1 and stat["fehler"] is None
    zeile = db.con.execute("SELECT * FROM anzeigen WHERE id='m1'").fetchone()
    assert zeile["titel"] == "Hymer B 678 SL" and zeile["suche"] == "Integrierter" and zeile["preis"] == 39900
    assert zeile["quelle"] == "test_manuell" and zeile["detail_geladen"] == 1   # keine Details → nicht erneut versucht
