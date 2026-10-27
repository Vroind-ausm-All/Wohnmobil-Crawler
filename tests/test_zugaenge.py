"""F4 – Einladungen (einfacher erster Login) und Händlerzugänge bei mobile.de/AutoScout24 (ADR-059): Schema v21, Einmal-Link, Seite,
Plattformdaten ohne Geheimnisse, Verbindungstest mit genau einer Anfrage, Rechte, Audit, Kommandozeile."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from tests.test_cli import _scout
from tests.test_handy import Client
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout import migrationen
from wmscout.datenbank import Datenbank
from tests.daten import BASIS
from wmscout.zugaenge import ZugangSpeicher, variable_vorschlag

BASIS_VORLAGEN = BASIS / "vorlagen"


class FakeAntwort:
    def __init__(self, status, daten=None):
        self.status_code, self._daten = status, daten

    def json(self):
        if self._daten is None:
            raise ValueError("kein JSON")
        return self._daten


class FakeSession:
    def __init__(self, *antworten):
        self.antworten, self.anfragen = list(antworten), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.anfragen.append({"url": url, "params": params, "headers": headers})
        return self.antworten.pop(0)


# ---------------------------------------------------------------- 1. Schema v21
def test_migration_v21_additiv_mit_sicherung(tmp_path, monkeypatch):
    pfad = tmp_path / "alt.sqlite"
    with monkeypatch.context() as m:
        m.setattr(migrationen, "AKTUELLE_VERSION", 20)
        migrationen.migriere(pfad, tmp_path / "s")
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO nutzer (name, passwort_hash, erstellt_am) VALUES ('Alt', 'x', 'x')")
    con.commit()
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == [21]
    assert [p for p in (tmp_path / "s").iterdir() if "vor-v21" in p.name]                       # Sicherung vor der Migration
    con = sqlite3.connect(pfad)
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"einladungen", "plattform_zugaenge"} <= tabellen and con.execute("SELECT name FROM nutzer").fetchone()[0] == "Alt"
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == []                                       # idempotent


# ---------------------------------------------------------------- 2. Einladungen
def test_einladung_einmal_gueltig(db, team):
    nid, token, rolle = team.einladen("Kunde", "inhaber")
    assert rolle == "inhaber"
    assert team.anmelden("Kunde", "irgendwas1") is None                                            # vorher keine Anmeldung möglich
    e = team.einladung(token)
    assert e["name"] == "Kunde" and e["rolle"] == "inhaber" and team.einladung("falsch") is None
    from wmscout.team import hash_passwort
    assert team.einladung_einloesen(token, hash_passwort("geheim123"))["nutzer_id"] == nid
    assert team.anmelden("Kunde", "geheim123") and team.einladung(token) is None                   # nur einmal
    assert db.con.execute("SELECT token_hash FROM einladungen").fetchone()[0] != token             # nur der Hash gespeichert


def test_einladung_abgelaufen_gesperrt_und_erneuert(db, team):
    _, alt, _ = team.einladen("Kunde")
    _, neu, _ = team.einladen("Kunde", erneut=True)
    assert team.einladung(alt) is None and team.einladung(neu)                                      # neue macht alte ungültig
    db.con.execute("UPDATE einladungen SET ablauf=?", ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),))
    db.con.commit()
    assert team.einladung(neu) is None
    _, wieder, _ = team.einladen("Kunde", erneut=True)
    team.nutzer_aktiv_setzen("Kunde", False)
    assert team.einladung(wieder) is None
    with pytest.raises(ValueError, match="gesperrt"):
        team.einladen("Kunde", erneut=True)


def test_einladung_ueber_die_app(server, team, db):
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    assert ben("POST", "/api/nutzer/einladen", {"name": "Kunde"})[0] == 403
    assert anna("POST", "/api/nutzer/einladen", {"name": "Kunde", "rolle": "haendler"})[0] == 400
    s, d, _ = anna("POST", "/api/nutzer/einladen", {"name": "Kunde", "rolle": "inhaber"})
    assert s == 200 and "/einladung#" in d["link"] and d["gueltig_tage"] == 7
    token = d["link"].split("#", 1)[1]
    gast = Client(server.server_address[1])
    s, html, _ = gast("GET", "/einladung")
    assert s == 200 and "Passwort setzen" in html and "no-referrer" in html
    assert gast("POST", "/api/einladung/pruefen", {"token": token})[1] == {"name": "Kunde", "rolle": "Inhaber"}
    assert gast("POST", "/api/einladung/pruefen", {"token": "falsch"})[0] == 410
    assert gast("POST", "/api/einladung", {"token": token, "passwort": "kurz"})[0] == 400
    s, d, _ = gast("POST", "/api/einladung", {"token": token, "passwort": "neues-passwort"})
    assert s == 200 and d["name"] == "Kunde" and gast("GET", "/api/ich")[1]["nutzer"]["name"] == "Kunde"      # gleich angemeldet
    assert gast("POST", "/api/einladung", {"token": token, "passwort": "neues-passwort"})[0] == 410
    assert Client(server.server_address[1]).anmelden("Kunde", "neues-passwort")
    zeilen = [dict(r) for r in db.con.execute("SELECT aktion, nutzer, pfad FROM audit WHERE pfad LIKE '/api/einladung%'")]
    assert {"aktion": "einladung", "nutzer": "Kunde", "pfad": "/api/einladung"} in zeilen
    assert not [z for z in zeilen if z["pfad"] == "/api/einladung/pruefen"]                         # nur gelesen: nicht protokolliert


def test_einladung_fehlversuche_gebremst(server, team):
    gast = Client(server.server_address[1])
    for _ in range(25):
        status = gast("POST", "/api/einladung", {"token": "x", "passwort": "lang-genug-1"})[0]
    assert status == 429


def test_cli_einladen(cfg, tmp_path):
    cfg["app"]["oeffentliche_url"] = "https://firma.example.de"
    r = _scout(cfg, tmp_path, "nutzer", "einladen", "Kunde", "--rolle", "inhaber")
    assert r.returncode == 0 and "https://firma.example.de/einladung#" in r.stdout, r.stderr
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    assert db.con.execute("SELECT rolle FROM nutzer WHERE name='Kunde'").fetchone()[0] == "inhaber"
    db.con.close()


# ---------------------------------------------------------------- 3. Händlerzugänge
def test_variable_und_speichern_ohne_geheimnis(cfg, db):
    assert variable_vorschlag(cfg, "mobilede") == "WMSCOUT_MOBILEDE_PASSWORT"
    assert variable_vorschlag({"mandant": {"kennung": "firma-b"}}, "mobilede") == "WMSCOUT_FIRMA_B_MOBILEDE_PASSWORT"
    z = ZugangSpeicher(db, cfg, umgebung={"WMSCOUT_MOBILEDE_PASSWORT": "streng-geheim"})
    erg = z.speichern("mobilede", {"haendlernummer": "123456", "api_benutzer": "dlr_123"}, None)
    assert erg["geheimnis_gesetzt"] is True and erg["abruf_freigegeben"] is False and erg["variable"] == "WMSCOUT_MOBILEDE_PASSWORT"
    assert "streng-geheim" not in str([dict(r) for r in db.con.execute("SELECT * FROM plattform_zugaenge")])
    as24 = z.speichern("autoscout24", {"haendlernummer": "A-77", "api_benutzer": "x", "geheimnis_variable": "WMSCOUT_X"}, None)
    assert as24["lesen"] is False and as24["api_benutzer"] is None and as24["geheimnis_gesetzt"] is None


@pytest.mark.parametrize("daten, teil", [
    ({"geheimnis_variable": "AWS_SECRET_ACCESS_KEY"}, "WMSCOUT_"), ({"geheimnis_variable": "WMSCOUT_x"}, "WMSCOUT_"),
    ({"haendlernummer": "12 34"}, "Händlernummer"), ({"api_benutzer": "a b"}, "API-Benutzer"),
])
def test_speichern_prueft(cfg, db, daten, teil):
    with pytest.raises(ValueError, match=teil):
        ZugangSpeicher(db, cfg, umgebung={}).speichern("mobilede", daten, None)
    with pytest.raises(LookupError):
        ZugangSpeicher(db, cfg, umgebung={}).speichern("ebay", {}, None)


def test_verbindungstest_eine_anfrage_ohne_inhalte(cfg, db):
    z = ZugangSpeicher(db, cfg, umgebung={})
    with pytest.raises(ValueError, match="API-Benutzer"):
        z.test_vorbereiten("mobilede")
    z.speichern("mobilede", {"api_benutzer": "dlr_123"}, None)
    with pytest.raises(ValueError, match="WMSCOUT_MOBILEDE_PASSWORT"):
        z.test_vorbereiten("mobilede")
    with pytest.raises(ValueError, match="keine Lese-Schnittstelle"):
        z.test_vorbereiten("autoscout24")
    z = ZugangSpeicher(db, cfg, umgebung={"WMSCOUT_MOBILEDE_PASSWORT": "pw"})
    t = z.test_vorbereiten("mobilede")
    assert t["kopf"]["Authorization"] == "Basic ZGxyXzEyMzpwdw==" and t["basis_url"].startswith("https://")
    s = FakeSession(FakeAntwort(200, {"ads": [{"title": "Hymer B 544, Max Mustermann"}], "total": 1}))
    erg = ZugangSpeicher.test_ausfuehren(t, session=s)
    assert erg["ok"] and erg["aufbau"] == ["ads", "total"] and erg["listen"] == {"ads": 1} and len(s.anfragen) == 1
    z.test_merken("mobilede", erg)
    zeile = dict(db.con.execute("SELECT * FROM plattform_zugaenge WHERE plattform='mobilede'").fetchone())
    assert zeile["letzter_test_ergebnis"].startswith("OK") and "Mustermann" not in str(zeile) and "Hymer" not in str(zeile)
    abgelehnt = ZugangSpeicher.test_ausfuehren(t, session=FakeSession(FakeAntwort(401)))
    assert not abgelehnt["ok"] and "401" in abgelehnt["text"] and "pw" not in abgelehnt["text"]


def test_zugaenge_ueber_die_app(server, team, monkeypatch):
    from wmscout.quellen import api_rahmen
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    assert ben("GET", "/api/zugaenge")[0] == 403 and ben("GET", "/zugaenge")[0] == 403
    s, html, _ = anna("GET", "/zugaenge")
    assert s == 200 and "Einladungslink erstellen" in html and "Händlerzugänge" in html
    assert anna("POST", "/api/zugaenge/mobilede", {"geheimnis_variable": "PATH"})[0] == 400
    s, d, _ = anna("POST", "/api/zugaenge/mobilede", {"haendlernummer": "123456", "api_benutzer": "dlr_123"})
    assert s == 200 and d["geheimnis_gesetzt"] is False
    assert anna("POST", "/api/zugaenge/mobilede/test", {})[0] == 400                                # Passwort fehlt auf dem Server
    monkeypatch.setenv("WMSCOUT_MOBILEDE_PASSWORT", "pw")
    sitzung = FakeSession(FakeAntwort(200, {"ads": []}))
    monkeypatch.setattr(api_rahmen.requests, "Session", lambda: sitzung)
    assert ben("POST", "/api/zugaenge/mobilede/test", {})[0] == 403
    s, d, _ = anna("POST", "/api/zugaenge/mobilede/test", {})
    assert s == 200 and d["ok"] and len(sitzung.anfragen) == 1
    assert sitzung.anfragen[0]["url"] == "https://services.mobile.de/search-api/search"
    liste = anna("GET", "/api/zugaenge")[1]["plattformen"]
    assert next(p for p in liste if p["plattform"] == "mobilede")["letzter_test_ergebnis"].startswith("OK")


# ---------------------------------------------------------------- 4. Korrekturrunde (QA F4)
def test_vorhandener_zugang_nur_ausdruecklich_und_mit_seiner_rolle(db, team, cfg, tmp_path):
    """B2: Eine Einladung übernimmt nie stillschweigend ein Konto mit anderer Rolle."""
    from wmscout.team import ZugangVorhanden
    with pytest.raises(ZugangVorhanden, match="gibt es schon"):
        team.einladen("Anna", "inhaber")
    with pytest.raises(ValueError, match="Rolle Inhaber, nicht Mitarbeiter"):
        team.einladen("Anna", "mitarbeiter", erneut=True)
    assert team.einladen("Anna", "inhaber", erneut=True)[2] == "inhaber"
    assert team.anmelden("Anna", "sicher1234")                                                       # altes Passwort bis zum Einlösen
    r = _scout(cfg, tmp_path, "nutzer", "einladen", "Anna", "--rolle", "inhaber")
    assert r.returncode != 0 and "--erneut" in r.stderr


def test_offene_einladung_kein_login_und_aufraeumen(db, team):
    """Bis zum Einlösen gibt es kein Passwort; eingelöste/abgelaufene Einladungen über 30 Tage werden aufgeräumt (B8, B10)."""
    team.einladen("Neu")
    assert team.login_daten("Neu")[0] is None and team.anmelden("Neu", "einladung-offen") is None
    alt = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    db.con.execute("UPDATE einladungen SET erstellt_am=?, eingeloest_am=?", (alt, alt))
    db.con.commit()
    team.einladen("Noch einer")
    assert db.con.execute("SELECT COUNT(*) FROM einladungen").fetchone()[0] == 1


def test_einzelplatz_erster_zugang_mit_hinweis(cfg, db):
    """B1: Ohne Nutzer lädt der lokale Inhaber ein – die Antwort sagt, dass ab jetzt eine Anmeldung nötig ist (Link nicht verlieren)."""
    from tests.test_team_bearbeitung import lokal, starte
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        s, d, _ = c("POST", "/api/nutzer/einladen", {"name": "Chef", "rolle": "inhaber"})
        assert s == 200 and d["erster_zugang"] is True and any("Anmeldung nötig" in h for h in d["hinweise"])
        assert any("oeffentliche_url" in h for h in d["hinweise"])
        assert c("GET", "/api/zugaenge")[0] == 401                                                   # ab jetzt Anmeldung nötig
        token = d["link"].split("#", 1)[1]
        assert c("POST", "/api/einladung", {"token": token, "passwort": "chef-passwort"})[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()
    html = (BASIS_VORLAGEN / "zugaenge.html").read_text(encoding="utf-8")
    assert "if(!d.erster_zugang) laden();" in html


def test_variable_nur_eigener_mandant(db, cfg):
    """B3: Mandant B darf die Variable von Mandant A nicht nennen (gemeinsame Umgebung des Servers)."""
    b = {**cfg, "mandant": {"kennung": "firma-b"}}
    z = ZugangSpeicher(db, b, umgebung={"WMSCOUT_FIRMA_A_MOBILEDE_PASSWORT": "a-geheim"})
    with pytest.raises(ValueError, match="WMSCOUT_FIRMA_B_"):
        z.speichern("mobilede", {"api_benutzer": "x", "geheimnis_variable": "WMSCOUT_FIRMA_A_MOBILEDE_PASSWORT"}, None)
    db.con.execute("INSERT INTO plattform_zugaenge (plattform, api_benutzer, geheimnis_variable, aktualisiert_am) "
                   "VALUES ('mobilede', 'x', 'WMSCOUT_FIRMA_A_MOBILEDE_PASSWORT', 'x')")                # z. B. früher gespeichert
    db.con.commit()
    eintrag = next(p for p in z.liste() if p["plattform"] == "mobilede")
    assert eintrag["variable"] == "WMSCOUT_FIRMA_B_MOBILEDE_PASSWORT" and eintrag["geheimnis_gesetzt"] is False
    with pytest.raises(ValueError, match="WMSCOUT_FIRMA_B_MOBILEDE_PASSWORT"):
        z.test_vorbereiten("mobilede")


def test_verbindungstest_bei_5xx_genau_eine_anfrage(cfg, db):
    """B4: auch bei 503 keine Wiederholung (und keine Wartezeit)."""
    z = ZugangSpeicher(db, cfg, umgebung={"WMSCOUT_MOBILEDE_PASSWORT": "pw"})
    z.speichern("mobilede", {"api_benutzer": "dlr"}, None)
    s = FakeSession(FakeAntwort(503), FakeAntwort(200, {}))
    erg = ZugangSpeicher.test_ausfuehren(z.test_vorbereiten("mobilede"), session=s)
    assert not erg["ok"] and "503" in erg["text"] and len(s.anfragen) == 1


def test_pruefen_gebremst_und_herkunft(server, team):
    """B6: auch die Prüfung des Codes ist gebremst und nur von der eigenen Seite."""
    gast = Client(server.server_address[1])
    status = [gast("POST", "/api/einladung/pruefen", {"token": f"x{i}"})[0] for i in range(25)]
    assert status[0] == 410 and status[-1] == 429
