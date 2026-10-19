"""G2 (ADR-033): Mandanten – je Firma eigene Datenbank; der Hostname wählt den Mandanten, nichts ist übergreifend sichtbar."""
from __future__ import annotations

import copy
import threading
from pathlib import Path

import pytest
import yaml

from tests.test_cli import _scout
from tests.test_handy import Client
from wmscout import mandanten
from wmscout.app import erstelle_server_mandanten
from wmscout.verkauf import pruefe_anfrage


@pytest.fixture
def grund(cfg, tmp_path):
    c = copy.deepcopy(cfg)
    c["mandanten"] = {"ordner": str(tmp_path / "mandanten")}
    c.setdefault("app", {})["oeffentliche_url"] = "https://hauptfirma.test"
    c["whatsapp"] = {**(c.get("whatsapp") or {}), "aktiv": True}
    return c


def _zwei(grund, tmp_path):
    mandanten.anlegen(grund, tmp_path, "firma-a", "Firma A", "https://a.test")
    mandanten.anlegen(grund, tmp_path, "firma-b", "Firma B", "https://b.test/irgendwas")


# ---------------------------------------------------------------- Konfiguration
def test_konfiguration_pfade_fest_und_nichts_geerbt(grund, tmp_path):
    _zwei(grund, tmp_path)
    a = mandanten.mandant_cfg(grund, tmp_path, "firma-a")
    assert a["mandant"] == {"kennung": "firma-a", "name": "Firma A"} and a["anschreiben"]["firma"] == "Firma A"
    assert Path(a["ausgabe"]["datenbank"]) == tmp_path / "mandanten" / "firma-a" / "daten" / "anzeigen.sqlite"
    assert Path(a["sicherung"]["ordner"]).parts[-3:] == ("firma-a", "daten", "sicherungen")
    assert Path(a["import"]["ordner"]).parts[-2:] == ("firma-a", "import")
    assert mandanten.hosts(a) == {"a.test"} and a["whatsapp"]["aktiv"] is False                  # Adresse/WhatsApp nicht geerbt
    assert a["crawler"] == grund["crawler"]                                                     # sonst wie config.yaml
    assert [m["mandant"]["kennung"] for m in mandanten.alle(grund, tmp_path)] == ["firma-a", "firma-b"]
    pfad = tmp_path / "mandanten" / "firma-b" / "mandant.yaml"
    eigen = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    for verboten in ({"ausgabe": {"datenbank": "../firma-a/daten/anzeigen.sqlite"}}, {"sicherung": {"ordner": "/tmp"}}):
        pfad.write_text(yaml.safe_dump({**eigen, **verboten}), encoding="utf-8")
        with pytest.raises(mandanten.MandantenFehler, match="legt das Programm"):
            mandanten.mandant_cfg(grund, tmp_path, "firma-b")
    pfad.write_text(yaml.safe_dump({**eigen, "app": {"oeffentliche_url": "https://a.test"}}), encoding="utf-8")
    with pytest.raises(mandanten.MandantenFehler, match="nur einmal"):
        mandanten.alle(grund, tmp_path)
    pfad.write_text(yaml.safe_dump({"name": "B"}), encoding="utf-8")
    with pytest.raises(mandanten.MandantenFehler, match="keine Adresse"):
        mandanten.alle(grund, tmp_path)


def test_anlegen_und_kennung(grund, tmp_path):
    for falsch in ("A", "x", "../a", "firma_a", ""):
        with pytest.raises(mandanten.MandantenFehler, match="Kennung"):
            mandanten.anlegen(grund, tmp_path, falsch, "x", "https://x.test")
    with pytest.raises(mandanten.MandantenFehler, match="https"):
        mandanten.anlegen(grund, tmp_path, "firma-c", "C", "http://c.test")
    mandanten.anlegen(grund, tmp_path, "firma-c", "C", "https://c.test")
    with pytest.raises(mandanten.MandantenFehler, match="gibt es schon"):
        mandanten.anlegen(grund, tmp_path, "firma-c", "C", "https://c.test")
    with pytest.raises(mandanten.MandantenFehler, match="unbekannt"):
        mandanten.mandant_cfg(grund, tmp_path, "firma-x")
    (tmp_path / "mandanten" / "Ungueltig").mkdir()
    assert mandanten.kennungen(grund, tmp_path) == ["firma-c"]


# ---------------------------------------------------------------- Server
@pytest.fixture
def mserver(grund, tmp_path):
    _zwei(grund, tmp_path)
    srv = erstelle_server_mandanten(grund, tmp_path, port=0, lokal="firma-a")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ka, kb = srv.mandanten["firma-a"][0], srv.mandanten["firma-b"][0]
    ka.team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    kb.team.nutzer_anlegen("Bert", "sicher1234", "inhaber")
    yield srv
    srv.shutdown()
    srv.server_close()


def test_hostname_waehlt_mandanten_und_trennt_alles(mserver, tmp_path):
    port = mserver.server_address[1]
    ka, kb = mserver.mandanten["firma-a"][0], mserver.mandanten["firma-b"][0]
    anna = Client(port, host="a.test").anmelden("Anna")
    bert = Client(port, host="b.test").anmelden("Bert")
    assert Client(port, host="b.test")("POST", "/api/login", {"name": "Anna", "passwort": "sicher1234"})[0] == 401
    fremd = Client(port, host="b.test")
    fremd.cookie = anna.cookie                                                                  # Sitzung von A an B
    assert fremd("GET", "/api/ich")[0] == 401
    daten = pruefe_anfrage({"art": "Alkoven", "marke": "Knaus", "ez_jahr": "2014", "km": "90000", "preisvorstellung": "31000",
                            "name": "Erika Beispiel", "telefon": "0170 0000000", "plz": "10115", "einwilligung": True}, jahr=2026)
    s, a, _ = anna("POST", "/api/verkaufsanfrage", {**daten, "einwilligung": True, "kanal": "telefon"})
    assert s == 200
    assert len(anna("GET", "/api/verkaufsanfragen")[1]) == 1 and bert("GET", "/api/verkaufsanfragen")[1] == []
    assert bert("GET", f"/api/verkaufsanfrage/{a['id']}")[0] == 404
    # eigene Dateien je Mandant
    pa = ka.db.con.execute("PRAGMA database_list").fetchone()[2]
    pb = kb.db.con.execute("PRAGMA database_list").fetchone()[2]
    assert Path(pa).parts[-3:-1] == ("firma-a", "daten") and Path(pb).parts[-3:-1] == ("firma-b", "daten")
    # Audit, Live und Nutzung je Mandant
    assert ka.db.con.execute("SELECT COUNT(*) FROM audit WHERE nutzer='Anna'").fetchone()[0] >= 2
    assert kb.db.con.execute("SELECT COUNT(*) FROM audit WHERE nutzer='Anna'").fetchone()[0] == 1            # nur der Fehlversuch
    assert ka.live.stand >= 1 and kb.live.stand == 0
    assert anna("GET", "/api/nutzung")[1]["zaehler"]["verkaufsanfragen"] == 1
    assert bert("GET", "/api/nutzung")[1]["zaehler"]["verkaufsanfragen"] == 0


def test_unbekannter_host_und_lokal(mserver):
    port = mserver.server_address[1]
    s, f, r = Client(port, host="c.test")("GET", "/api/ich")
    assert s == 403 and "firma" not in str(f) and r.getheader("X-Frame-Options") == "DENY"
    assert Client(port, host="c.test")("POST", "/api/login", {"name": "Anna", "passwort": "sicher1234"})[0] == 403
    assert Client(port)("POST", "/api/login", {"name": "Anna", "passwort": "sicher1234"})[0] == 200          # 127.0.0.1 → lokal = A
    assert Client(port)("POST", "/api/login", {"name": "Bert", "passwort": "sicher1234"})[0] == 401


def test_ohne_lokal_kein_zugriff_ueber_127(grund, tmp_path):
    _zwei(grund, tmp_path)
    with pytest.raises(mandanten.MandantenFehler, match="kein solcher"):
        erstelle_server_mandanten(grund, tmp_path, port=0, lokal="firma-x")
    srv = erstelle_server_mandanten(grund, tmp_path, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert Client(srv.server_address[1])("GET", "/api/ich")[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_cli_mandanten(grund, tmp_path):
    r = _scout(grund, tmp_path, "mandant", "anlegen", "firma-a", "--name", "Firma A", "--url", "https://a.test")
    assert r.returncode == 0 and "angelegt" in r.stdout, r.stderr
    r = _scout(grund, tmp_path, "--mandant", "firma-a", "nutzer", "anlegen", "Anna", "--rolle", "inhaber", "--passwort", "sicher1234")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "mandanten" / "firma-a" / "daten" / "anzeigen.sqlite").is_file()
    r = _scout(grund, tmp_path, "mandant", "liste")
    assert r.returncode == 0 and "firma-a" in r.stdout and "a.test" in r.stdout
    r = _scout(grund, tmp_path, "mandant", "nutzung", "--monat", "2026-10")
    assert r.returncode == 0 and "firma-a" in r.stdout and "verkaufsanfragen=0" in r.stdout, r.stderr
    r = _scout(grund, tmp_path, "--mandant", "firma-x", "nutzung")
    assert r.returncode != 0 and "unbekannt" in r.stderr
