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


# Speicher-Wächter: Seit PR #61 bleibt auf Windows (und vereinzelt Linux) der ganze CI-Runner stehen – weder Zeitgrenzen noch der
# Hänger-Wächter greifen, das Protokoll fehlt. Verdacht: ein Test frisst den Arbeitsspeicher. Übersteigt der eigene Prozess
# SCOUT_TEST_MAX_MB (Standard 4000), schreibt der Wächter Test und Stacktraces und beendet den Lauf, bevor der Runner erstickt.
_MAX_MB = int(os.environ.get("SCOUT_TEST_MAX_MB", "4000") or 0)
_LAUFENDER_TEST = ["(vor dem ersten Test)"]
_CAPTURE: list = []          # pytest-Ausgabefang; vor der Meldung abschalten, sonst landet sie im verworfenen Puffer des Tests


def _speicher_mb() -> float | None:
    """Arbeitsspeicher (RSS) des eigenen Prozesses in MB; None, wenn auf diesem System nicht messbar."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Zaehler(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                                   "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            z = Zaehler()
            z.cb = ctypes.sizeof(z)
            psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Zaehler), wintypes.DWORD]
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(z), z.cb):
                return None
            return max(z.WorkingSetSize, z.PagefileUsage) / 2**20
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except (OSError, ValueError, AttributeError):
        return None


def _speicher_waechter():
    import threading
    import time

    def pruefe():
        while True:
            mb = _speicher_mb()
            if mb is None:
                return
            if mb > _MAX_MB:
                try:
                    for capman in _CAPTURE:
                        capman.suspend_global_capture(in_=False)
                except Exception:  # noqa: BLE001 – der Lauf endet ohnehin, Meldung notfalls nur in die Datei
                    pass
                for ziel in {_HAENGER_ZIEL, sys.__stderr__}:
                    try:
                        ziel.write(f"\nSpeichergrenze: {mb:.0f} MB > {_MAX_MB} MB in {_LAUFENDER_TEST[0]}\n")
                        ziel.flush()
                        faulthandler.dump_traceback(file=ziel, all_threads=True)
                        ziel.flush()
                    except (OSError, ValueError):
                        pass
                os._exit(3)
            time.sleep(0.2)

    if _MAX_MB > 0 and _speicher_mb() is not None:
        threading.Thread(target=pruefe, name="speicher-waechter", daemon=True).start()


_MAX_TEST_ID = 1000


def pytest_collection_modifyitems(items):
    """Test-IDs bleiben kurz. Eine 6,7 MB lange ID (Parameter als ID, test_datei_upload) legte die CI-Runner lahm: pytest -v schreibt
    sie als eine Zeile ins Protokoll, und pytest setzt sie in die Umgebungsvariable PYTEST_CURRENT_TEST (unter Windows höchstens
    32767 Zeichen). Lange Parameter brauchen deshalb ``ids=``."""
    lang = [item.nodeid[:120] + "…" for item in items if len(item.nodeid) > _MAX_TEST_ID]
    if lang:
        raise pytest.UsageError(f"Test-ID länger als {_MAX_TEST_ID} Zeichen – bitte ids= setzen: " + "; ".join(lang))


def pytest_configure(config):
    capman = config.pluginmanager.getplugin("capturemanager")
    if capman:
        _CAPTURE.append(capman)
    _speicher_waechter()


@pytest.fixture(autouse=True)
def _haenger_waechter(request):
    _LAUFENDER_TEST[0] = request.node.nodeid
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
