from __future__ import annotations

import copy

import pytest

from tests.daten import SUCH_URL, FakeAbruf, baue_ads, lade_cfg
from wmscout.datenbank import Datenbank
from wmscout.importer import Importer
from wmscout import quellen
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle

_CFG = lade_cfg()


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> dict:
    """config.yaml, aber ohne Pausen und mit Ausgaben im Temp-Ordner."""
    # Offline-Fake als eigenständige freigegebene TEST-Quelle; produktiver Adapter bleibt gesperrt.
    class ErlaubteKleinanzeigenTestQuelle(KleinanzeigenQuelle):
        freigegeben = True

    monkeypatch.setitem(quellen.QUELLEN, "kleinanzeigen", ErlaubteKleinanzeigenTestQuelle)
    c = copy.deepcopy(_CFG)
    c["suchen"] = [{"name": "Teilintegrierter", "url": SUCH_URL}]
    c["crawler"].update(pause_min_sek=0, pause_max_sek=0, detailseiten_pro_lauf=100)
    c["ausgabe"]["ordner"] = str(tmp_path / "ausgabe")
    c["ausgabe"]["datenbank"] = str(tmp_path / "anzeigen.sqlite")
    return c


@pytest.fixture
def ads() -> list[dict]:
    return baue_ads()


@pytest.fixture
def db(cfg) -> Datenbank:
    return Datenbank(cfg["ausgabe"]["datenbank"])


@pytest.fixture
def importiert(cfg, db, ads):
    """Datenbank nach einem kompletten Suchlauf über 60 nachgebaute Kleinanzeigen-Inserate."""
    stat = Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    return stat
