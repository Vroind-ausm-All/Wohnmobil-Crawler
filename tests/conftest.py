from __future__ import annotations

import copy
import faulthandler
import os
import sys

import pytest

from tests.daten import SUCH_URL, FakeAbruf, baue_ads, lade_cfg
from wmscout.datenbank import Datenbank
from wmscout.importer import Importer
from wmscout import quellen
from wmscout.quellen.kleinanzeigen import KleinanzeigenQuelle

_CFG = lade_cfg()

# Hänger-Wächter: Ein Test, der länger als SCOUT_TEST_TIMEOUT Sekunden (Standard 300) läuft, schreibt die Stacktraces ALLER Threads
# und beendet den Testlauf mit Fehler – statt bis zur 6-Stunden-Grenze der CI zu hängen (Windows-CI seit PR #61). Ziel der Ausgabe:
# SCOUT_TEST_HAENGER_DATEI (die CI gibt sie im Fehlerfall aus), sonst die ursprüngliche Fehlerausgabe. 0 schaltet den Wächter ab.
_HAENGER_SEKUNDEN = int(os.environ.get("SCOUT_TEST_TIMEOUT", "300") or 0)
_HAENGER_ZIEL = open(os.environ["SCOUT_TEST_HAENGER_DATEI"], "w", encoding="utf-8") if os.environ.get("SCOUT_TEST_HAENGER_DATEI") \
    else sys.__stderr__


@pytest.fixture(autouse=True)
def _haenger_waechter(request):
    if _HAENGER_SEKUNDEN > 0:
        if _HAENGER_ZIEL is not sys.__stderr__:              # nur in der Datei: zuletzt gestarteter Test steht am Ende
            _HAENGER_ZIEL.write(f"läuft: {request.node.nodeid}\n")
            _HAENGER_ZIEL.flush()
        faulthandler.dump_traceback_later(_HAENGER_SEKUNDEN, exit=True, file=_HAENGER_ZIEL)
    yield
    if _HAENGER_SEKUNDEN > 0:
        faulthandler.cancel_dump_traceback_later()


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
    # nie den echten Import-Ordner des Projekts: die Aufbewahrungsfristen (F10) löschen dort abgelegte Seiten und Mails
    c["import"] = {**(c.get("import") or {}), "ordner": str(tmp_path / "import")}
    # ebenso nie den echten Sicherungsordner (Kommandozeilen-Tests laufen im Projektordner, QA F10 B2)
    c["sicherung"] = {**(c.get("sicherung") or {}), "ordner": str(tmp_path / "sicherungen")}
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


def pytest_sessionfinish(session, exitstatus):
    """Auch ein Hänger NACH dem letzten Test (z. B. ein Thread, der das Beenden blockiert) wird nach 120 s mit Stacktraces gemeldet."""
    if _HAENGER_SEKUNDEN > 0:
        if _HAENGER_ZIEL is not sys.__stderr__:
            _HAENGER_ZIEL.write(f"Sitzung beendet (Status {exitstatus}) – warte auf Prozessende\n")
            _HAENGER_ZIEL.flush()
        faulthandler.dump_traceback_later(120, exit=True, file=_HAENGER_ZIEL)
