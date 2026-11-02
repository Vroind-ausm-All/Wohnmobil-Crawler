"""P7-04 – Serverbetrieb vorbereitet: Vorlagen für systemd, Caddy, Umgebung und config.local; Health-Check ``/gesund`` der Team-App."""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import shutil
import subprocess

import pytest
import yaml

from tests.daten import BASIS
from tests.test_team_bearbeitung import Client, anmelden, server  # noqa: F401 – Fixtures
from wmscout.audit import einordnen
from wmscout.team import TeamSpeicher

BETRIEB = BASIS / "betrieb"
UNITS = ("wohnmobil-scout-app.service", "wohnmobil-scout-portal.service", "wohnmobil-scout-sicherung.service", "wohnmobil-scout-sicherung.timer",
         "wohnmobil-scout-datenschutz.service", "wohnmobil-scout-datenschutz.timer")


def _abschnitte(text: str) -> dict[str, dict[str, list[str]]]:
    erg, aktuell = {}, None
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if m := re.fullmatch(r"\[(\w+)\]", zeile):
            aktuell = erg.setdefault(m.group(1), {})
            continue
        schluessel, wert = zeile.split("=", 1)
        aktuell.setdefault(schluessel, []).append(wert)
    return erg


# ---------------------------------------------------------------- Vorlagen
def test_systemd_dienste():
    for name in UNITS:
        assert (BETRIEB / "systemd" / name).is_file(), name
    app = _abschnitte((BETRIEB / "systemd" / UNITS[0]).read_text(encoding="utf-8"))
    portal = _abschnitte((BETRIEB / "systemd" / UNITS[1]).read_text(encoding="utf-8"))
    sicherung = _abschnitte((BETRIEB / "systemd" / UNITS[2]).read_text(encoding="utf-8"))
    assert app["Service"]["ExecStart"] == ["/opt/wohnmobil-scout/.venv/bin/python scout.py app --kein-browser"]
    assert portal["Service"]["ExecStart"] == ["/opt/wohnmobil-scout/.venv/bin/python scout.py portal"]
    assert sicherung["Service"]["ExecStart"] == ["/opt/wohnmobil-scout/.venv/bin/python scout.py sichern"]
    datenschutz = _abschnitte((BETRIEB / "systemd" / UNITS[4]).read_text(encoding="utf-8"))
    assert datenschutz["Service"]["ExecStart"] == ["/opt/wohnmobil-scout/.venv/bin/python scout.py datenschutz --ausfuehren --bestaetigt"]
    for d, import_noetig in ((app, True), (portal, False), (sicherung, False), (datenschutz, True)):
        s = d["Service"]
        assert s["User"] == ["scout"] and s["NoNewPrivileges"] == ["true"] and s["ProtectSystem"] == ["strict"] and s["UMask"] == ["0077"]
        pfade = s["ReadWritePaths"][0].split()
        assert {"/opt/wohnmobil-scout/daten", "/opt/wohnmobil-scout/ausgabe"} <= set(pfade)             # Datenbank, Fotos, Sicherungen, Log
        assert ("/opt/wohnmobil-scout/import" in pfade) == import_noetig                                  # Seiten/Mails (Import, Fristen)
    assert "/etc/wohnmobil-scout/umgebung" in portal["Service"]["EnvironmentFile"][0]
    assert portal["Unit"]["StartLimitBurst"] == ["5"]                                        # Fehlkonfiguration: kein Dauer-Neustart
    timer = _abschnitte((BETRIEB / "systemd" / UNITS[3]).read_text(encoding="utf-8"))
    assert timer["Timer"]["Persistent"] == ["true"] and timer["Install"]["WantedBy"] == ["timers.target"]


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze nicht vorhanden")
def test_systemd_syntax():
    """Nur Syntax: die ausführbare Datei unter /opt existiert in der Testumgebung nicht – diese Meldung ist erwartet."""
    for name in UNITS:
        r = subprocess.run(["systemd-analyze", "verify", "--man=no", str(BETRIEB / "systemd" / name)], capture_output=True, text=True,
                           timeout=60)
        meldungen = [z for z in (r.stderr + r.stdout).splitlines() if z.strip() and "is not executable" not in z]
        assert not meldungen, (name, meldungen)


def test_caddy_vorlage():
    text = (BETRIEB / "Caddyfile").read_text(encoding="utf-8")
    aktiv = "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))
    assert "reverse_proxy 127.0.0.1:8770" in aktiv and "Strict-Transport-Security" in aktiv and "max_size 15MB" in aktiv
    assert "ip_mask" in aktiv and "request>headers delete" in aktiv and "roll_disabled" in aktiv     # ohne volle IP, ohne Kopfzeilen (Upload-Token)
    rot = (BETRIEB / "logrotate-caddy-portal").read_text(encoding="utf-8")
    assert "/var/log/caddy/portal.log" in rot and "daily" in rot and "maxage 14" in rot
    assert "8765" not in aktiv                                                               # Team-App standardmäßig nicht öffentlich
    assert "#\treverse_proxy 127.0.0.1:8765" in text and "flush_interval -1" in text         # Variante B vorbereitet (SSE ohne Puffer)
    assert aktiv.count("{") == aktiv.count("}")


def test_keine_geheimnisse_in_vorlagen():
    for zeile in (BETRIEB / "umgebung.beispiel").read_text(encoding="utf-8").splitlines():
        if zeile and not zeile.startswith("#"):
            name, wert = zeile.split("=", 1)
            assert re.fullmatch(r"SCOUT_[A-Z_]+", name) and wert == "", zeile
    namen = {z.split("=")[0] for z in (BETRIEB / "umgebung.beispiel").read_text(encoding="utf-8").splitlines() if z and z[0] != "#"}
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    assert {cfg["email"]["passwort_env"], cfg["whatsapp"]["token_env"], "SCOUT_PORTAL_SCHLUESSEL"} <= namen
    lokal = yaml.safe_load((BETRIEB / "config.local.beispiel.yaml").read_text(encoding="utf-8"))
    assert lokal["portal"]["aktiv"] is False and lokal["portal"]["texte_geprueft"] is False and lokal["app"]["nur_https"] is True
    roh = (BETRIEB / "config.local.beispiel.yaml").read_text(encoding="utf-8").lower()
    assert "passwort:" not in roh and "token:" not in roh and "schluessel:" not in roh


def test_anleitung_verweist_auf_vorlagen():
    doku = (BASIS / "docs" / "SERVERBETRIEB.md").read_text(encoding="utf-8")
    for datei in ("Caddyfile", "umgebung.beispiel", "config.local.beispiel.yaml", *UNITS[:3]):
        assert datei.split(".")[0] in doku, datei
    assert "Nicht geprüft" in doku and "chmod 600" in doku and "/gesund" in doku and "nie als root" in doku
    assert not re.search(r"(?<!scout\.venv/bin/python )(?<!python )`scout\.py (sichern|wiederherstellen|audit|datenschutz)", doku)  # QA B1


# ---------------------------------------------------------------- Health-Check der Team-App
def test_gesund_ohne_anmeldung_ohne_daten(server, db, tmp_path):
    c = Client(server.server_address[1])
    status, antwort, _ = c("GET", "/gesund")
    assert status == 200 and antwort == {"ok": True}                    # Einzelplatz ohne Nutzer, lokal
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    db.con.commit()
    status, antwort, _ = Client(server.server_address[1])("GET", "/gesund")
    assert status == 200 and antwort == {"ok": True}                    # mit Team: ohne Anmeldung erreichbar, ohne Inhalte
    assert Client(server.server_address[1])("GET", "/api/fahrzeuge")[0] == 401
    assert einordnen("GET", "/gesund") is None                          # kein Audit-Eintrag je Abfrage
    assert anmelden(server, "Anna")("GET", "/gesund")[0] == 200


def test_gesund_host_proxy_und_defekte_datenbank(cfg, db, importiert):
    """Fremder Host 403; ohne Nutzer über einen Proxy 403 (wie dokumentiert); ohne schema_version kein 200."""
    import http.client
    from tests.test_team_bearbeitung import starte
    srv = starte(cfg, db)
    port = srv.server_address[1]
    try:
        def abruf(kopf):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/gesund", headers={"Host": f"127.0.0.1:{port}", **kopf})
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, body
        assert abruf({"Host": "boese.example"})[0] == 403
        assert abruf({"X-Forwarded-For": "1.2.3.4"})[0] == 403
        db.con.execute("ALTER TABLE schema_version RENAME TO schema_version_weg")
        db.con.commit()
        status, body = abruf({})
        assert status == 500 and b"ok" not in body
    finally:
        srv.shutdown()
        srv.server_close()
