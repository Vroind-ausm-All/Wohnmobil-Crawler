"""P3-02b (Oberfläche): Dublettenvorschläge entscheiden (Desktop) und Gruppe „Gleiches Fahrzeug“ anzeigen (Desktop-Fahrzeugfenster, Handy).

Geprüft werden ausgelieferte Seiten, statische Dateien und der Vertrag zwischen Skript und API (Feldnamen). Das Verhalten im Browser
(Bestätigungsabfrage, Entscheiden, Aufheben, Warnung) deckt der Klicktest ab, der nicht Teil von pytest ist.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.daten import BASIS
from tests.test_dubletten_entscheiden import team_api  # noqa: F401 – Fixture
from tests.test_team_bearbeitung import anmelden, lokal
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle

STATIC = BASIS / "wmscout" / "web" / "static"
NODE = shutil.which("node")
ELEMENTE = ('id="dub-knopf"', 'id="dubletten"', 'id="dubletten-box"', "data-dub-gruppe", '<script src="/static/dubletten.js">')


def _lies(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return re.sub(r'"\s*\+\s*"', "", re.sub(r"^/\*.*?\*/", "", _lies(name), count=1, flags=re.S))


@pytest.mark.parametrize("name", ["Anna", "Ben"], ids=["inhaber", "mitarbeiter"])
def test_desktop_hat_dublettenbereich_fuer_inhaber_und_mitarbeiter(team_api, name):
    html = anmelden(team_api, name)("GET", "/")[1]
    assert all(e in html for e in ELEMENTE)
    assert "Dublettenvorschläge" in html and 'href="/static/dubletten.css"' in html
    assert "⧉" in html                                                      # das bestehende Abzeichen bleibt


def test_desktop_ohne_team_hat_dublettenbereich(cfg, db, importiert):
    from tests.test_dubletten_vorschlaege import starte
    srv = starte(cfg, db)
    try:
        assert all(e in lokal(srv)("GET", "/")[1] for e in ELEMENTE)
    finally:
        srv.shutdown()


def test_desktop_datei_ohne_server_hat_keinen_dublettenbereich(cfg, db, importiert):
    html, _ = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    assert "dubletten.js" not in html and "dub-knopf" not in html and "data-dub-gruppe" not in html


@pytest.mark.parametrize("rolle, sichtbar", [("inhaber", True), ("mitarbeiter", True), ("haendler", False)], ids=["inhaber", "mitarbeiter", "haendler"])
def test_desktop_bereich_nur_fuer_inhaber_und_mitarbeiter(cfg, db, importiert, rolle, sichtbar):
    team_sicht = {"aktiv": True, "ich": {"id": 1, "name": "X", "kuerzel": "X", "rolle": rolle}, "nutzer": [], "zaehler": [],
                  "ohne_zuordnung": 0, "verwaist": 0, "bearbeitung": {}, "reservierung_tage": 2}
    html, _ = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS, app={"token": "t"}, team=team_sicht)
    assert all((e in html) is sichtbar for e in ELEMENTE)


def test_handy_zeigt_nur_an_und_hat_keine_entscheidungsknoepfe(team_api):
    c = anmelden(team_api, "Ben")
    html = c("GET", "/m")[1]
    assert "/static/dubletten.js" in html and "/static/dubletten.css" in html
    assert html.index("dubletten.js") < html.index("mobil.js")
    js = c("GET", "/static/mobil.js")[1]
    assert 'id="dub-gruppe"' in js and "dublettenAnzeigen" in js and "textDarf()" in js          # nur Inhaber und Mitarbeiter
    assert "verlauf: false" in js
    for verboten in ("/api/dubletten/bestaetigen", "/api/dubletten/ablehnen", "/api/dubletten/aufheben", "Dubletten.vorschlaege", "aufheben:"):
        assert verboten not in js


def test_skript_vertrag_mit_der_api(team_api):
    """Die vom Skript gelesenen Felder und Adressen gibt es in den Antworten des Servers."""
    js = _code("dubletten.js")
    anna = anmelden(team_api, "Anna")
    d = anna("GET", "/api/dubletten-vorschlaege")[1]
    v = d["vorschlaege"][0]
    for f in ("stufe", "gruende", "inserat_a", "inserat_b", "anzeigen_a", "anzeigen_b", "plattform_a", "plattform_b", "darf_bestaetigen", "darf_ablehnen"):
        assert f in v and f"v.{f}" in js, f
    for f in ("anzahl", "vorschlaege", "unvollstaendig", "hinweis"):
        assert f in d and f"d.{f}" in js, f
    for f in ("titel", "preis", "km", "ez_jahr", "ort", "url"):
        assert f in v["a"] and f"s.{f}" in js, f
    i1, i2 = v["inserat_a"], v["inserat_b"]
    antwort = anna("POST", "/api/dubletten/bestaetigen", {"a": i1, "b": i2})[1]
    st = anna("GET", f"/api/dubletten/entscheidungen?anzeige={v['anzeigen_a']}")[1]
    for f in ("gruppe", "fahrzeug_status", "entscheidungen", "darf_aufheben"):
        assert f in st and f"daten.{f}" in js, f
    for f in ("anzeigen_id", "plattform", "titel", "preis", "url"):
        assert f in st["gruppe"][0] and f"m.{f}" in js, f
    for f in ("id", "entscheidung", "status", "nutzer", "zeitpunkt", "aufhebbar", "blockiert_durch", "anzeige_a", "anzeige_b"):
        assert f in st["entscheidungen"][0] and f"e.{f}" in js, f
    assert "warnung" in js and set(antwort) >= {"ok", "entscheidung_id", "gruppe", "fahrzeug_status"}
    for pfad in ("/api/dubletten/bestaetigen", "/api/dubletten/ablehnen", "/api/dubletten/aufheben", "/api/dubletten-vorschlaege"):
        assert pfad in js or pfad.rsplit("/", 1)[-1] in js


def test_desktop_vorlage_ruft_aufheben_mit_entscheidung_id():
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "/api/dubletten/aufheben" in html and "{entscheidung_id: e.id}" in html and "Dubletten.aufhebenFrage(e)" in html
    assert "ladeTeam()" in html and "dubAktualisiert" in html                 # nach jeder Aktion: Team-Stand (⧉) und Hinweis „Liste aktualisieren“


def test_skript_bestaetigt_vor_jeder_entscheidung_und_zeigt_folgen():
    js = _code("dubletten.js")
    assert "if (!frage(" in js and js.count("entscheide(") >= 3
    assert "es wird nicht doppelt angeschrieben" in js
    assert "zählt nur einmal in der Vergleichsbasis" in js and "Sperre" in js and "aufgehoben" in js
    assert "Erst die spätere Zusammenführung" in js and "darf_aufheben" in js
    assert "Übereinstimmung: hoch" in js and "Übereinstimmung: mittel" in js and "Prozent" not in js and "konfidenz" not in js.lower()


def test_skript_gibt_fremde_daten_nur_als_text_aus_und_speichert_nichts():
    js = _code("dubletten.js")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js and "outerHTML" not in js
    assert "localStorage" not in js and "sessionStorage" not in js and "indexedDB" not in js
    assert "httpLink" in js and "noopener" in js and r"/^https?:\/\//i" in js
    assert "textContent" in js


def test_dublettenanzeige_in_mobil_js_ohne_innerhtml_fuer_fremddaten():
    js = _code("mobil.js")
    block = js[js.index("function dublettenAnzeigen"):js.index("function fahrzeug(")]
    assert "innerHTML" not in block and "appendChild(box)" in block


def test_service_worker_cached_dubletten_und_version_erhoeht():
    sw = _lies("sw.js")
    geruest = re.search(r"var GERUEST = \[(.*?)\]", sw, re.S).group(1)
    for datei in ("/static/dubletten.js", "/static/dubletten.css"):
        assert f"'{datei}'" in geruest
    for pfad in re.findall(r"'/static/([\w.-]+)'", geruest):
        assert (STATIC / pfad).is_file(), pfad
    assert int(re.search(r"VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 9
    assert "dubletten" not in re.search(r"var lesbar = (.*?);", sw, re.S).group(1)       # Entscheidungsdaten nie im Gerätespeicher


def test_skriptsyntax_dubletten():
    if not NODE:
        pytest.skip("node nicht installiert")
    for name in ("dubletten.js", "mobil.js"):
        r = subprocess.run([NODE, "--check", str(STATIC / name)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


def test_desktop_skriptsyntax(team_api, tmp_path):
    if not NODE:
        pytest.skip("node nicht installiert")
    html = anmelden(team_api, "Anna")("GET", "/")[1]
    datei = tmp_path / "seite.js"
    datei.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(datei)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
