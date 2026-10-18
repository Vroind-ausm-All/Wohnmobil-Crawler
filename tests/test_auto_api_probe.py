"""Offline-Vertragstests des deaktivierten Auto-API-Probeadapters."""
import pytest

from wmscout.quellen import QUELLEN
from wmscout.quellen.auto_api_probe import AutoApiQuelle, normalisiere_angebot
from wmscout.quellen.basis import QuellenFehler, Suchauftrag


class FakeClient:
    def __init__(self, antworten):
        self.antworten = iter(antworten)
        self.aufrufe = []

    def get_offers(self, plattform, page=1):
        self.aufrufe.append((plattform, page))
        return next(self.antworten)


def angebot(**extras):
    return {"id": "123", "url": "https://example.invalid/123", "title": "Knaus",
            "price": 39900, "mileage": 85000, "year": 2018, "is_private": True, **extras}


def test_kein_automatischer_zugriff_und_nicht_registriert():
    assert "auto_api_probe" not in QUELLEN
    assert AutoApiQuelle.freigegeben is False
    with pytest.raises(QuellenFehler, match="deaktiviert"):
        AutoApiQuelle({})


def test_mapping_synthetisch():
    i = normalisiere_angebot(angebot(), "mobilede")
    assert (i.quelle, i.anzeigen_id, i.preis, i.km, i.ez_jahr, i.gewerblich) == (
        "auto_api_mobilede", "auto_api_mobilede:123", 39900, 85000, 2018, False)
    assert normalisiere_angebot(angebot(), "autoscout24").anzeigen_id != i.anzeigen_id


def test_fehlende_felder_bleiben_unbekannt():
    i = normalisiere_angebot({"id": 1, "url": "https://example.invalid/1",
                             "price": "39,900", "mileage": -2, "year": 1800}, "mobilede")
    assert i.preis is None and i.km is None and i.ez_jahr is None and i.gewerblich is None


@pytest.mark.parametrize("item", [
    {"url": "https://example.invalid/1"},
    {"id": 1, "url": "javascript:alert(1)"},
    {"id": "", "url": "https://example.invalid/1"},
    [],
])
def test_ungueltige_inserate(item):
    with pytest.raises(QuellenFehler):
        normalisiere_angebot(item, "mobilede")


def test_paginierung_und_ende():
    client = FakeClient([{"offers": [angebot()]}, {"offers": []}])
    q = AutoApiQuelle({}, client=client)
    result = list(q.suche(Suchauftrag("TI", parameter={"plattform": "mobilede", "max_seiten": 3})))
    assert [len(s.inserate) for s in result] == [1, 0]
    assert client.aufrufe == [("mobilede", 1), ("mobilede", 2)]


@pytest.mark.parametrize("parameter", [
    {"plattform": "fremd"},
    {"plattform": "mobilede", "max_seiten": 0},
    {"plattform": "mobilede", "max_seiten": 4},
    {"plattform": "mobilede", "max_seiten": True},
])
def test_suchparameter_abgewiesen(parameter):
    with pytest.raises(QuellenFehler):
        list(AutoApiQuelle({}, client=FakeClient([])).suche(Suchauftrag("TI", parameter=parameter)))


def test_unbekanntes_schema_und_clientfehler():
    with pytest.raises(QuellenFehler, match="Antwortformat"):
        list(AutoApiQuelle({}, client=FakeClient([{"items": []}])).suche(
            Suchauftrag("TI", parameter={"plattform": "mobilede"})))
    with pytest.raises(QuellenFehler, match="Testclient-Fehler"):
        list(AutoApiQuelle({}, client=FakeClient([])).suche(
            Suchauftrag("TI", parameter={"plattform": "mobilede"})))
