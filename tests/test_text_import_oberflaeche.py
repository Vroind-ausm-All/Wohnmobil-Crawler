"""P2-05 (Oberfläche): Formular „Inserat einlesen (Link + Text)“ in Desktop- und Handy-App.

Geprüft werden ausgelieferte Seiten und statische Dateien (Elemente, Pflichthinweis, Grenzen wie im Server, Rollen, Service-Worker-Gerüst).
Das Verhalten im Browser (Absenden, Ergebnis, Fehler) deckt der Klicktest ab, der nicht Teil von pytest ist.
"""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.daten import BASIS
from tests.test_team_bearbeitung import anmelden, lokal, server, team  # noqa: F401 – Fixtures
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.eingang.text import MAX_TEXT, MAX_URL

STATIC = BASIS / "wmscout" / "web" / "static"
HINWEIS = ("Nur den Anzeigentext einfügen – keine Namen, Telefonnummern oder Adressen des Verkäufers. "
           "Kontaktdaten werden automatisch entfernt, Namen im Fließtext nicht immer.")
NODE = shutil.which("node")


def _lies(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Skript ohne Kopfkommentar und ohne Zeichenketten-Verkettung (lange Texte sind im Code auf mehrere Literale verteilt)."""
    return re.sub(r'"\s*\+\s*"', "", re.sub(r"^/\*.*?\*/", "", _lies(name), count=1, flags=re.S))


def test_desktop_app_hat_formular_und_knopf(server):
    status, html, _ = lokal(server)("GET", "/")
    assert status == 200
    assert 'id="textimport-knopf"' in html and "Inserat einlesen (Link + Text)" in html
    assert 'id="textimport"' in html and 'id="textimport-box"' in html
    assert '<script src="/static/textimport.js">' in html and 'href="/static/textimport.css"' in html
    assert "/api/import" in html and "Gespeicherte Seiten einlesen" in html          # der bisherige Import bleibt


def test_desktop_datei_ohne_server_hat_kein_formular(cfg, db, importiert):
    html, _ = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    assert "textimport" not in html


@pytest.mark.parametrize("rolle, sichtbar", [("inhaber", True), ("mitarbeiter", True), ("haendler", False)])
def test_desktop_formular_nur_fuer_inhaber_und_mitarbeiter(cfg, db, importiert, rolle, sichtbar):
    team_sicht = {"aktiv": True, "ich": {"id": 1, "name": "X", "kuerzel": "X", "rolle": rolle}, "nutzer": [], "zaehler": [],
                  "ohne_zuordnung": 0, "verwaist": 0, "bearbeitung": {}, "reservierung_tage": 2}
    html, _ = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS, app={"token": "t"}, team=team_sicht)
    assert ("textimport-knopf" in html) is sichtbar and ("textimport.js" in html) is sichtbar and ('id="textimport"' in html) is sichtbar


def test_desktop_mit_team_zeigt_formular_fuer_alle_teammitglieder(server, team):
    for name in ("Anna", "Ben"):
        assert 'id="textimport-knopf"' in anmelden(server, name)("GET", "/")[1]


def test_handy_app_laedt_formular_und_hat_einstieg(server):
    c = lokal(server)
    html = c("GET", "/m")[1]
    assert "/static/textimport.js" in html and "/static/textimport.css" in html
    assert html.index("textimport.js") < html.index("mobil.js")                       # Formular-Modul vor der App
    js = c("GET", "/static/mobil.js")[1]
    assert 'href="#/einlesen"' in js and 'teile[0] === "einlesen"' in js
    assert 'n.rolle === "inhaber" || n.rolle === "mitarbeiter"' in js                 # Standort-Zugänge sehen den Einstieg nicht
    assert c("GET", "/static/textimport.js")[0] == 200 and c("GET", "/static/textimport.css")[0] == 200


def test_formular_hinweis_grenzen_und_anbieterauswahl():
    js = _code("textimport.js")
    assert HINWEIS in js
    assert f"MAX_TEXT = {MAX_TEXT}" in js and f"MAX_URL = {MAX_URL}" in js            # clientseitig wie der Server (der bleibt maßgeblich)
    assert '["", "unbekannt"]' in js
    assert '["privat", "privat"]' in js and '["gewerblich", "gewerblich"]' in js
    assert "/api/import/text" in js and "anbieter: an || null" in js
    for stelle in ("aria-live", 'role: "alert"', "legend", 'el("label"'):
        assert stelle in js
    assert "Eingang ist abgeschaltet (Einstellungen)" in js


def test_formular_speichert_nichts_im_browser_und_setzt_keine_fremden_daten_in_html():
    js = _code("textimport.js")
    assert "localStorage" not in js and "sessionStorage" not in js and "indexedDB" not in js
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js
    assert "nurPfad" in js                      # Links nur zu Adressen dieser App


def test_service_worker_cached_formular_und_version_erhoeht():
    sw = _lies("sw.js")
    geruest = re.search(r"var GERUEST = \[(.*?)\]", sw, re.S).group(1)
    for datei in ("/static/textimport.js", "/static/textimport.css", "/static/mobil.js", "/static/mobil.css"):
        assert f"'{datei}'" in geruest
    for pfad in re.findall(r"'/static/([\w.-]+)'", geruest):
        assert (STATIC / pfad).is_file(), pfad
    assert int(re.search(r"VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 7


@pytest.mark.parametrize("name", ["textimport.js", "mobil.js"])
def test_skript_syntax(name):
    if not NODE:
        pytest.skip("node nicht installiert")
    r = subprocess.run([NODE, "--check", str(STATIC / name)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_desktop_skript_syntax(server, tmp_path):
    if not NODE:
        pytest.skip("node nicht installiert")
    html = lokal(server)("GET", "/")[1]
    datei = tmp_path / "seite.js"
    datei.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(datei)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
