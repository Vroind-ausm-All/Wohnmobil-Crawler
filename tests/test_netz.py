"""P1-11a: Höflicher HTTP-Abruf – Sperre (403/429/Captcha) beendet den Lauf sofort, 5xx wird zweimal wiederholt, Pausen
zwischen Abrufen. Session und Pausen sind ersetzt: kein Netz, keine Wartezeit."""
from __future__ import annotations

import pytest
import requests

from wmscout import netz
from wmscout.quellen.basis import HttpFehler, NetzwerkFehler, QuelleGesperrt
from wmscout.quellen.kleinanzeigen.adapter import KleinanzeigenQuelle

CRAWLER = {"user_agent": "WohnmobilScout/Test", "pause_min_sek": 4, "pause_max_sek": 9, "timeout_sek": 25}


class Antwort:
    def __init__(self, status: int, text: str = ""):
        self.status_code, self.text = status, text


class Sitzung:
    """Gibt die vorbereiteten Antworten der Reihe nach zurück (Ausnahme-Objekte werden geworfen)."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[tuple[str, float]] = []

    def get(self, url, timeout):
        self.aufrufe.append((url, timeout))
        a = self.antworten.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


@pytest.fixture
def pausen(monkeypatch):
    liste: list[float] = []
    monkeypatch.setattr(netz.time, "sleep", liste.append)
    monkeypatch.setattr(netz.random, "uniform", lambda a, b: (a + b) / 2)
    return liste


def _abruf(*antworten) -> netz.HoeflicherAbruf:
    a = netz.HoeflicherAbruf(CRAWLER, "Testquelle")
    a.session = Sitzung(*antworten)
    return a


def test_kopfzeilen_ehrlich():
    a = netz.HoeflicherAbruf(CRAWLER, "Testquelle")
    assert a.session.headers["User-Agent"] == "WohnmobilScout/Test"           # kein vorgetäuschter Browser
    assert a.session.headers["Accept-Language"].startswith("de-DE")


def test_erfolg_und_pause_erst_ab_zweitem_abruf(pausen):
    a = _abruf(Antwort(200, "eins"), Antwort(200, "zwei"))
    assert a.hole("https://x.test/1") == "eins" and pausen == []
    assert a.hole("https://x.test/2") == "zwei" and pausen == [6.5]           # zufällig zwischen pause_min und pause_max
    assert [t for _, t in a.session.aufrufe] == [25, 25]


@pytest.mark.parametrize("status", [403, 429])
def test_sperre_bricht_sofort_ab_ohne_wiederholung(pausen, status):
    a = _abruf(Antwort(status), Antwort(200, "dürfte nie geholt werden"))
    with pytest.raises(QuelleGesperrt, match=f"HTTP {status} – Testquelle blockt"):
        a.hole("https://x.test/")
    assert len(a.session.aufrufe) == 1 and pausen == []


def test_serverfehler_zweimal_wiederholt_dann_erfolg(pausen):
    a = _abruf(Antwort(503), Antwort(500), Antwort(200, "ok"))
    assert a.hole("https://x.test/") == "ok"
    assert len(a.session.aufrufe) == 3 and pausen == [20, 40]


def test_serverfehler_dreimal_gibt_auf(pausen):
    a = _abruf(Antwort(502), Antwort(502), Antwort(502), Antwort(200))
    with pytest.raises(HttpFehler) as e:
        a.hole("https://x.test/")
    assert e.value.status == 502 and len(a.session.aufrufe) == 3 and pausen == [20, 40]


def test_404_ohne_wiederholung(pausen):
    a = _abruf(Antwort(404), Antwort(200))
    with pytest.raises(HttpFehler) as e:
        a.hole("https://x.test/weg")
    assert (e.value.status, e.value.url, len(a.session.aufrufe)) == (404, "https://x.test/weg", 1)


def test_netzwerkfehler_wird_quellenfehler(pausen):
    a = _abruf(requests.ConnectionError("keine Verbindung"))
    with pytest.raises(NetzwerkFehler, match="keine Verbindung"):
        a.hole("https://x.test/")
    a = _abruf(Antwort(500), requests.Timeout("zu langsam"))
    with pytest.raises(NetzwerkFehler, match="zu langsam"):
        a.hole("https://x.test/")


def test_captcha_seite_sperrt_die_quelle(cfg, pausen):
    q = KleinanzeigenQuelle(cfg, _abruf(Antwort(200, "<html><div id='captcha'>Bitte bestätigen</div></html>")))
    with pytest.raises(QuelleGesperrt, match="Captcha"):
        q._hole("https://x.test/")
    q = KleinanzeigenQuelle(cfg, _abruf(Antwort(200, "<article class='aditem'>Captcha-Wohnmobil</article>")))
    assert "aditem" in q._hole("https://x.test/")                              # Wort „Captcha“ in einer Anzeige ist keine Sperre
