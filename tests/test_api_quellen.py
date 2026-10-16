"""Phase G0 – Rahmen für offizielle APIs (ADR-030): Freigabe, Zugangsdaten nur per Umgebungsvariable, HTTPS, Kontingent,
Abbruch statt Umgehung. Ohne Netz: eine Fake-Session spielt die Antworten."""
from __future__ import annotations

import pytest

from wmscout.quellen import api
from wmscout.quellen.basis import HttpFehler, Inserat, QuelleGesperrt, QuellenFehler, Suchauftrag


class Antwort:
    def __init__(self, status, daten=None):
        self.status_code, self.daten = status, daten

    def json(self):
        if self.daten is None:
            raise ValueError("kein JSON")
        return self.daten


class Session:
    def __init__(self, antworten):
        self.antworten, self.aufrufe = list(antworten), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.aufrufe.append((url, dict(params or {}), dict(headers or {})))
        return self.antworten.pop(0)


class BeispielApiQuelle(api.ApiQuelle):
    kennung, name, basis_url, zugang_variable = "test_api", "Test-API", "https://api.beispiel.invalid/v1", "WMSCOUT_TEST_API_KEY"
    freigegeben = True

    def kopfzeilen(self, schluessel):
        return {"Authorization": f"Bearer {schluessel}"}

    def suchparameter(self, auftrag, seite):
        return {"kategorie": auftrag.parameter.get("art"), "seite": seite}

    def inserate_aus(self, antwort):
        return [Inserat("test_api", str(t["id"]), f"https://beispiel.invalid/{t['id']}", preis=t["preis"]) for t in antwort["treffer"]]


def _quelle(monkeypatch, antworten, cfg=None):
    monkeypatch.setenv("WMSCOUT_TEST_API_KEY", "geheim-123")
    s = Session(antworten)
    q = BeispielApiQuelle(cfg or {"api_quellen": {"test_api": {"max_abrufe_je_lauf": 3, "pause_sek": 0}}}, session=s)
    q.api.schlafen = lambda _s: None
    return q, s


def test_nicht_freigegeben_oder_ohne_zugang_wird_gar_nicht_erst_erzeugt(monkeypatch):
    class Gesperrt(BeispielApiQuelle):
        freigegeben = False
    with pytest.raises(QuellenFehler, match="nicht freigegeben"):
        Gesperrt({})
    monkeypatch.delenv("WMSCOUT_TEST_API_KEY", raising=False)
    with pytest.raises(QuellenFehler, match="Umgebungsvariable WMSCOUT_TEST_API_KEY"):
        BeispielApiQuelle({})
    assert api.ApiQuelle.freigegeben is False and api.ApiQuelle.zugriffsart == "api"


def test_suche_blaettert_bis_leer_und_schluessel_nur_im_kopf(monkeypatch):
    q, s = _quelle(monkeypatch, [Antwort(200, {"treffer": [{"id": 1, "preis": 30000}]}), Antwort(200, {"treffer": []})])
    seiten = list(q.suche(Suchauftrag("Alkoven", quelle="test_api", parameter={"art": "Alkoven"})))
    assert [len(x.inserate) for x in seiten] == [1, 0] and seiten[0].inserate[0].preis == 30000
    assert [a[1] for a in s.aufrufe] == [{"kategorie": "Alkoven", "seite": 1}, {"kategorie": "Alkoven", "seite": 2}]
    assert all(a[0] == "https://api.beispiel.invalid/v1/search" and a[2]["Authorization"] == "Bearer geheim-123" for a in s.aufrufe)
    assert all("geheim" not in str(a[1]) for a in s.aufrufe)                      # nie in der Adresse


@pytest.mark.parametrize("status", [401, 403, 429])
def test_sperre_bricht_ab_ohne_wiederholung(monkeypatch, status):
    q, s = _quelle(monkeypatch, [Antwort(status), Antwort(200, {"treffer": []})])
    with pytest.raises(QuelleGesperrt, match="Keine Wiederholung"):
        list(q.suche(Suchauftrag("x", quelle="test_api")))
    assert len(s.aufrufe) == 1


def test_kontingent_serverfehler_und_kaputte_antwort(monkeypatch):
    voll = [Antwort(200, {"treffer": [{"id": i, "preis": 1}]}) for i in range(5)]
    q, s = _quelle(monkeypatch, voll)
    with pytest.raises(QuelleGesperrt, match="Kontingent von 3"):
        list(q.suche(Suchauftrag("x", quelle="test_api")))
    assert len(s.aufrufe) == 3
    q, s = _quelle(monkeypatch, [Antwort(502), Antwort(503), Antwort(200, {"treffer": []})])
    assert [len(x.inserate) for x in q.suche(Suchauftrag("x", quelle="test_api"))] == [0] and len(s.aufrufe) == 3
    q, _ = _quelle(monkeypatch, [Antwort(404)])
    with pytest.raises(HttpFehler):
        list(q.suche(Suchauftrag("x", quelle="test_api")))
    q, _ = _quelle(monkeypatch, [Antwort(200, None)])
    with pytest.raises(QuellenFehler, match="kein JSON"):
        list(q.suche(Suchauftrag("x", quelle="test_api")))


def test_nur_https_und_keine_fremden_pfade():
    with pytest.raises(QuellenFehler, match="HTTPS"):
        api.ApiAbruf("http://api.beispiel.invalid", {}, max_abrufe=1, pause_sek=0)
    a = api.ApiAbruf("https://api.beispiel.invalid", {}, max_abrufe=5, pause_sek=0, session=Session([]))
    for pfad in ("https://anderer.invalid/x", "suche", "/../admin", "//anderer.invalid/x"):
        with pytest.raises(QuellenFehler, match="ungültiger Pfad"):
            a.hole_json(pfad)
