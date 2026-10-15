"""T2 Team-Oberfläche (Desktop) und P1-06 „gesendet ✓“ (ADR-012): Kontakt gilt erst nach Bestätigung."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.daten import BASIS
from tests.test_team_bearbeitung import anmelden, anzeige_ids, bearbeitung, lokal, server, team  # noqa: F401 – Fixtures
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle

NODE = shutil.which("node")


def _skript(html: str) -> str:
    return re.findall(r"<script>(.*?)</script>", html, re.S)[-1]


def _js_ok(html: str, tmp_path):
    """Syntaxprüfung des ausgelieferten Skripts mit Node (falls installiert; die CI hat Node)."""
    if not NODE:
        pytest.skip("node nicht installiert")
    datei = tmp_path / "seite.js"
    datei.write_text(_skript(html), encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(datei)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def _status(db, ad_id):
    return tuple(db.con.execute("SELECT status, kontaktiert_am, anschreiben_text FROM anzeigen WHERE id=?", (ad_id,)).fetchone())


def test_seite_mit_team_zeigt_badges_zaehler_und_filter(server, team, db, tmp_path):
    ben = anmelden(server, "Ben")
    a = anzeige_ids(db, 1)[0]
    assert ben("POST", f"/api/bearbeitung/{a}/uebernehmen", {})[0] == 200
    carl = anmelden(server, "Carl")
    status, html, _ = carl("GET", "/")
    assert status == 200
    assert 'id="zaehler"' in html and 'data-wer="meine"' in html and 'data-teamaktion="uebernehmen" hidden>' in html
    karte = re.search(rf'<article[^>]*data-id="{a}"[^>]*>', html, re.S).group(0)
    assert 'data-zustand="reserviert"' in karte and 'data-mein="0"' in karte and 'data-frei="0"' in karte
    assert '"aktiv": true' in _skript(html)
    assert 'data-teamaktion="erzwingen" hidden>' not in html and "<select data-zuweisen" not in html   # nur der Inhaber erzwingt/weist zu
    _js_ok(html, tmp_path)
    inhaberin = anmelden(server, "Anna")
    html = inhaberin("GET", "/")[1]
    assert 'data-teamaktion="erzwingen" hidden>' in html and "<select data-zuweisen" in html
    _js_ok(html, tmp_path)


def test_seite_ohne_nutzer_hat_keine_team_elemente(server, tmp_path):
    html = lokal(server)("GET", "/")[1]
    assert 'data-wer="' not in html and 'id="zaehler"' not in html and 'data-teamaktion="uebernehmen" hidden>' not in html
    assert "var TEAM = null;" in html and "data-gesendet hidden" in html           # „gesendet ✓“ gibt es auch ohne Team
    _js_ok(html, tmp_path)


def test_statische_datei_ohne_team(cfg, db, importiert, tmp_path):
    html, _ = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    assert 'data-wer="' not in html and "var TEAM = null;" in html
    _js_ok(html, tmp_path)


def test_text_kopiert_ist_noch_kein_kontakt(server, team, db):
    ben = anmelden(server, "Ben")
    a = anzeige_ids(db, 1)[0]
    s, d, _ = ben("POST", "/api/status", {"id": a, "status": "vorbereitet", "text": "Hallo", "betrag": 30000})
    assert s == 200, d
    assert _status(db, a) == ("vorbereitet", None, "Hallo")
    b = bearbeitung(db, a)
    assert b[0] == team.ids["Ben"] and b[2] is None                       # reserviert, aber kein bestätigter Kontakt
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert"})[0] == 200   # Knopf „gesendet ✓“
    status, kontaktiert_am, text = _status(db, a)
    assert status == "kontaktiert" and kontaktiert_am and text == "Hallo"
    assert bearbeitung(db, a)[2] == team.ids["Ben"]


def test_kollege_kann_nicht_parallel_vorbereiten(server, team, db):
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    a = anzeige_ids(db, 1)[0]
    assert ben("POST", "/api/status", {"id": a, "status": "vorbereitet", "text": "Hallo"})[0] == 200
    s, d, _ = carl("POST", "/api/status", {"id": a, "status": "vorbereitet", "text": "Hallo von Carl"})
    assert s == 409 and d["grund"] == "konflikt"
    assert d["team"]["zustand"] == "reserviert" and d["team"]["bearbeiter"]["name"] == "Ben"
    assert _status(db, a)[2] == "Hallo"                                     # nichts überschrieben


def test_veraltete_seite_setzt_bestaetigten_kontakt_nicht_zurueck(server, db):
    c = lokal(server)
    a = anzeige_ids(db, 1)[0]
    assert c("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Hallo"})[0] == 200
    s, d, _ = c("POST", "/api/status", {"id": a, "status": "vorbereitet", "text": "Neu"})
    assert s == 409 and "neu laden" in d["fehler"]
    assert _status(db, a)[0] == "kontaktiert"


def test_nachfassen_bei_offenem_inserat_ist_nur_vorbereitet(db, importiert):
    a = anzeige_ids(db, 1)[0]
    assert db.nachgefasst(a, "Nachfrage")
    assert _status(db, a)[:2] == ("vorbereitet", None)
    db.setze_status(a, "kontaktiert")
    assert db.nachgefasst(a, "Zweite Nachfrage")
    assert _status(db, a)[0] == "kontaktiert"


def test_abgesagter_vorgang_bleibt_beim_nachfassen_abgesagt(db, importiert):
    a = anzeige_ids(db, 1)[0]
    db.setze_status(a, "abgesagt")
    db.nachgefasst(a, "Doch noch Interesse?")
    assert _status(db, a)[0] == "abgesagt"
