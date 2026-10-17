"""E-Mail-Eingang im Betrieb (P2-06 Teil 2): Schalter „email“, Kommandozeile (`import --mails`), App (/api/import/mails), Datenschutz-Frist.

Alle Mails sind NACHGEBILDET (tests/nachgebildet_mails.py); echte Mails sind die Abnahme (F3).
"""
import os
import threading
import time

import pytest
import yaml

from tests.daten import BASIS
from tests.nachgebildet_mails import nachgebildet_ka_mail, nachgebildet_md_mail, nachgebildet_mail
from tests.test_cli import _scout
from tests.test_handy import Client
from wmscout import datenrechte
from wmscout.app import erstelle_server
from wmscout.eingang.email import mail_ordner
from wmscout.importer import Importer
from wmscout.schalter import EINGANG_NAMEN, STANDARD_EINGAENGE, EingangDeaktiviert, eingang_aktiv
from wmscout.team import TeamSpeicher


@pytest.fixture
def mails(cfg, tmp_path):
    """Mail-Ordner (import/email) im Temp-Verzeichnis; Eingang noch aus (Standard)."""
    cfg["import"] = {"ordner": str(tmp_path / "import")}
    return mail_ordner(cfg)


def an(cfg):
    cfg["eingaenge"] = {"email": {"aktiv": True}}
    return cfg


def zaehle(db, tabelle="anzeigen"):
    return db.con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


# ---------- Schalter ----------
def test_eingang_email_ist_standardmaessig_aus_und_beschrieben(cfg):
    assert STANDARD_EINGAENGE["email"] is False and eingang_aktiv(cfg, "email") is False
    assert "folgt" not in EINGANG_NAMEN["email"] and "import/email" in EINGANG_NAMEN["email"]
    yaml_cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    assert yaml_cfg["eingaenge"]["email"] == {"aktiv": False}
    zeilen = (BASIS / "config.yaml").read_text(encoding="utf-8")
    assert "folgen mit P2-06" not in zeilen and "import --mails" in zeilen


def test_importer_liest_bei_abgeschaltetem_eingang_nichts(cfg, db, mails):
    mails.mkdir(parents=True)
    datei = mails / "m.eml"
    datei.write_bytes(nachgebildet_ka_mail())
    with pytest.raises(EingangDeaktiviert, match="abgeschaltet"):
        Importer(cfg, db).importiere_mails(mails)
    assert datei.is_file() and not (mails / "eingelesen").exists() and zaehle(db) == 0
    assert Importer(an(cfg), db).importiere_mails(mails)["neu"] == 3 and not datei.is_file()


# ---------- Kommandozeile ----------
def test_cli_import_mails_abgeschaltet_liest_nichts_und_legt_nichts_an(cfg, tmp_path, mails):
    r = _scout(cfg, tmp_path, "import", "--mails")
    assert r.returncode == 0, r.stderr
    assert "abgeschaltet" in r.stdout and "eingaenge" in r.stdout and "nichts gelesen" in r.stdout
    assert not mails.exists()                                           # Ordner nicht angelegt
    mails.mkdir(parents=True)
    (mails / "m.eml").write_bytes(nachgebildet_ka_mail())
    r = _scout(cfg, tmp_path, "import", "--mails")
    assert "abgeschaltet" in r.stdout and (mails / "m.eml").is_file() and not (mails / "eingelesen").exists()
    neu = tmp_path / "anderer"
    r = _scout(cfg, tmp_path, "import", "--mails", "--ordner", str(neu))
    assert r.returncode == 0 and not neu.exists()


def test_cli_import_mails_eingeschaltet(cfg, tmp_path, mails):
    r = _scout(an(cfg), tmp_path, "import", "--mails")
    assert r.returncode == 0, r.stderr
    assert "Keine Mails gefunden" in r.stdout and mails.is_dir()         # Standardordner wird bei Bedarf angelegt, Hilfe erscheint
    (mails / "a_ka.eml").write_bytes(nachgebildet_ka_mail())
    (mails / "b_md.eml").write_bytes(nachgebildet_md_mail())
    (mails / "c_kaputt.eml").write_bytes(b"\x00\x01")
    (mails / "d_fremd.eml").write_bytes(nachgebildet_mail("freund@example.org", "x", None, "Hallo").as_bytes())
    r = _scout(an(cfg), tmp_path, "import", "--mails")
    assert r.returncode == 0, r.stderr
    assert "4 Mails gelesen" in r.stdout and "1 nicht erkannt, 1 nicht lesbar" in r.stdout, r.stdout
    assert "5 neue Anzeigen" in r.stdout and "Report:" in r.stdout and "nicht_erkannt" in r.stdout and "fehlerhaft" in r.stdout
    assert (tmp_path / "ausgabe" / "report.html").exists()
    assert sorted(p.name for p in (mails / "fehlerhaft").iterdir()) == ["c_kaputt.eml"]
    assert sorted(p.name for p in (mails / "nicht_erkannt").iterdir()) == ["d_fremd.eml"]
    assert not list(mails.glob("*.eml"))


def test_cli_import_ohne_option_liest_weiter_nur_seiten(cfg, tmp_path, mails):
    mails.mkdir(parents=True)
    (mails / "m.eml").write_bytes(nachgebildet_ka_mail())
    r = _scout(an(cfg), tmp_path, "import", "--ordner", str(tmp_path / "seiten"))
    assert r.returncode == 0 and "Keine gespeicherten Seiten" in r.stdout and (mails / "m.eml").is_file()


def test_unverarbeitete_mails_ueber_der_frist_mit_konfigurierter_frist(cfg, mails):
    mails.mkdir(parents=True)
    alt = mails / "alt.eml"
    alt.write_bytes(b"x")
    os.utime(alt, (time.time() - 400 * 86400,) * 2)
    assert datenrechte.mails_unverarbeitet_gemeldet(cfg, mails) == 0                  # Standard: keine Frist
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 6}
    assert datenrechte.mails_unverarbeitet_gemeldet(cfg, mails) == 1 and alt.is_file()
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": "kaputt"}
    assert datenrechte.mails_unverarbeitet_gemeldet(cfg, mails) == 0                  # ungültige Konfiguration bricht die Meldung nicht ab


# ---------- App ----------
@pytest.fixture
def server(cfg, db, mails):
    srv, _, suchlauf = erstelle_server(cfg, db, BASIS, port=0)
    srv.suchlauf = suchlauf
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def lokaler_client(server):
    lokal = Client(server.server_address[1])
    lokal.csrf = lokal("GET", "/api/ich")[1]["csrf"]
    return lokal


def test_api_mails_abgeschaltet_409(cfg, db, mails, tmp_path):
    mails.mkdir(parents=True)
    (mails / "m.eml").write_bytes(nachgebildet_ka_mail())
    srv, _, _ = erstelle_server(cfg, db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        lokal = lokaler_client(srv)
        status, daten, _ = lokal("POST", "/api/import/mails", {})
        assert status == 409 and daten["grund"] == "deaktiviert" and "abgeschaltet" in daten["fehler"] and "eingaenge" in daten["fehler"]
        assert (mails / "m.eml").is_file() and zaehle(db) == 0 and not (mails / "eingelesen").exists()
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_mails_eingeschaltet_rollen_und_grenzen(cfg, db, mails, tmp_path, monkeypatch):
    import wmscout.web.api as api
    an(cfg)
    srv, _, suchlauf = erstelle_server(cfg, db, BASIS, port=0)
    srv.suchlauf = suchlauf
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        lokal = lokaler_client(srv)
        status, daten, _ = lokal("POST", "/api/import/mails", {})            # leerer Ordner wird angelegt
        assert status == 200 and daten["dateien"] == 0 and mails.is_dir() and daten["unverarbeitet"] == 0

        fremd = tmp_path / "fremd"
        fremd.mkdir()
        (fremd / "x.eml").write_bytes(nachgebildet_ka_mail())
        (mails / "a.eml").write_bytes(nachgebildet_ka_mail())
        (mails / "b.eml").write_bytes(nachgebildet_md_mail())
        (mails / "c.eml").write_bytes(b"kaputt ohne kopf")
        assert lokal("POST", "/api/import/mails", {}, token=False)[0] == 403                     # ohne CSRF-Token
        suchlauf.stand["laeuft"] = True
        status, daten, _ = lokal("POST", "/api/import/mails", {})
        assert status == 409 and "Suchlauf" in daten["fehler"] and (mails / "a.eml").is_file()
        suchlauf.stand["laeuft"] = False
        monkeypatch.setattr(api, "MAX_IMPORT_DATEIEN", 2)
        status, daten, _ = lokal("POST", "/api/import/mails", {"ordner": str(fremd)})            # Pfad aus der Anfrage wird ignoriert
        assert status == 200 and (daten["dateien"], daten["neu"], daten["uebrig"]) == (2, 5, 1)
        assert (fremd / "x.eml").is_file() and zaehle(db) == 5
        monkeypatch.setattr(api, "MAX_IMPORT_DATEIEN", 25)
        status, daten, _ = lokal("POST", "/api/import/mails", {})
        assert status == 200 and (daten["dateien"], daten["fehlerhaft"], daten["neu"]) == (1, 1, 0)
        assert (mails / "fehlerhaft" / "c.eml").is_file()
        assert len(lokal("GET", "/api/fahrzeuge?filter=alle")[1]) == 5                          # Liste kennt die neuen Inserate

        # Rollen: nur der Inhaber (wie beim Seitenimport)
        speicher = TeamSpeicher(db, tmp_path / "fotos")
        speicher.nutzer_anlegen("Anna", "sicher1234", "inhaber")
        speicher.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
        assert Client(port)("POST", "/api/import/mails", {})[0] == 401
        assert Client(port).anmelden("Ben")("POST", "/api/import/mails", {})[0] == 403
        assert Client(port).anmelden("Anna")("POST", "/api/import/mails", {})[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_mails_meldet_unverarbeitete_ueber_der_frist(cfg, db, mails):
    import wmscout.web.api as api
    an(cfg)
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 6}
    mails.mkdir(parents=True)
    alt = mails / "alt.eml"
    alt.write_bytes(nachgebildet_ka_mail())
    os.utime(alt, (time.time() - 400 * 86400,) * 2)
    assert datenrechte.mails_unverarbeitet(mails, 6) == 1
    srv, _, _ = erstelle_server(cfg, db, BASIS, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        lokal = lokaler_client(srv)
        original = api.MAX_IMPORT_DATEIEN
        api.MAX_IMPORT_DATEIEN = 0                                      # nichts wird gelesen: die Mail bleibt liegen und wird gemeldet
        try:
            status, daten, _ = lokal("POST", "/api/import/mails", {})
        finally:
            api.MAX_IMPORT_DATEIEN = original
        assert status == 200 and daten["unverarbeitet"] == 1 and alt.is_file()
    finally:
        srv.shutdown()
        srv.server_close()


def test_knopf_erscheint_nur_bei_eingeschaltetem_eingang(cfg, db, mails):
    from wmscout.ausgabe import render_html
    ohne, _ = render_html(cfg, [], BASIS, app={"token": "t"})
    mit, _ = render_html(an(cfg), [], BASIS, app={"token": "t"})
    assert 'id="mails"' not in ohne and 'id="mails"' in mit and "/api/import/mails" in mit


# ---------- Frist-Aufruf ----------
def test_frist_anwenden_nach_cli_loescht_alte_abgelegte_mails(cfg, tmp_path, mails):
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 6}
    alt = mails / "eingelesen" / "2025-01-02" / "alt.eml"
    alt.parent.mkdir(parents=True)
    alt.write_bytes(b"x")
    os.utime(alt, (time.time() - 400 * 86400,) * 2)
    r = _scout(an(cfg), tmp_path, "import", "--mails")
    assert r.returncode == 0, r.stderr
    assert not alt.exists()
