"""Kommandozeile scout.py (rechne, report, status) mit eigener Konfiguration im Temp-Ordner."""
import os
import subprocess
import sys
from datetime import date

import yaml

from tests.daten import BASIS
from wmscout.datenbank import IMPORT_SUCHE, Datenbank


def _scout(cfg, tmp_path, *argumente, umgebung: dict | None = None):
    pfad = tmp_path / "config.yaml"
    pfad.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return subprocess.run([sys.executable, str(BASIS / "scout.py"), "--config", str(pfad), *argumente],
                          capture_output=True, text=True, encoding="utf-8", cwd=BASIS, timeout=120,
                          env={**os.environ, **(umgebung or {})})


def test_rechne_mit_anschreiben(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "rechne", "--preis", "42900", "--ez", "2017", "--km", "85000",
               "--titel", "Knaus Sky TI 650 MEG", "--ort", "70173 Stuttgart", "--anschreiben")
    assert r.returncode == 0, r.stderr
    assert "MAX. EINKAUFSPREIS" in r.stdout and "Knaus Sky TI 650 MEG" in r.stdout and "Vorbehaltlich" in r.stdout


def test_report_und_status_bei_leerer_datenbank(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "report")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ausgabe" / "report.html").exists()
    r = _scout(cfg, tmp_path, "status", "123", "kontaktiert")
    assert r.returncode == 0 and "nicht gefunden" in r.stdout


def test_rechne_vergleicht_unbekannte_importe_in_rechner_sicht(cfg, tmp_path):
    """QA M6-2: `scout.py rechne` nutzt dieselbe Vergleichsbasis wie bewerte_alle. Zwei Importe mit unbekannter Art und
    „Camper“ im Titel stehen dort „ohne Art“ – sie zählen nicht als Kastenwagen-Vergleich; der Crawler-Kastenwagen schon."""
    jahr = date.today().year - 10
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    for kennung in ("u1", "u2"):
        db.speichere_treffer({"id": kennung, "titel": "Beispiel Camper 600", "preis": 30000, "km": 100000, "ez_jahr": jahr,
                              "ort": "70173 Stuttgart"}, IMPORT_SUCHE)
    db.speichere_treffer({"id": "k1", "titel": "Beispiel Kastenwagen 600", "preis": 30000, "km": 100000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Kastenwagen")
    db.con.close()
    r = _scout(cfg, tmp_path, "rechne", "--preis", "30000", "--ez", str(jahr), "--km", "100000", "--art", "Kastenwagen",
               "--titel", "Beispiel Kastenwagen 640")
    assert r.returncode == 0, r.stderr
    assert "Basis: 1 Vergleichsangebote Kastenwagen" in r.stdout, r.stdout


def test_config_local_ueberlagert(cfg, tmp_path):
    """P1-09: config.local.yaml neben config.yaml führt Abschnitte zusammen und ersetzt einzelne Werte."""
    import scout
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert scout.lade_config(str(tmp_path / "config.yaml")) == cfg
    (tmp_path / "config.local.yaml").write_text(yaml.safe_dump({"anschreiben": {"firma": "Eigene Firma"}, "suchen": []}), encoding="utf-8")
    c = scout.lade_config(str(tmp_path / "config.yaml"))
    assert c["anschreiben"]["firma"] == "Eigene Firma" and c["anschreiben"]["ort"] == cfg["anschreiben"]["ort"] and c["suchen"] == []
    assert c["rechner"] == cfg["rechner"]
    r = _scout(cfg, tmp_path, "rechne", "--preis", "39000", "--ez", "2016", "--km", "90000", "--titel", "Knaus Sky TI", "--anschreiben")
    assert r.returncode == 0 and "Eigene Firma" in r.stdout, r.stderr
    assert "config.local.yaml überlagert: anschreiben, suchen" in r.stdout                       # nachvollziehbar im Protokoll
    (tmp_path / "config.local.yaml").write_text("- nur eine Liste\n", encoding="utf-8")
    r = _scout(cfg, tmp_path, "rechne", "--preis", "39000", "--ez", "2016", "--km", "90000")
    assert r.returncode != 0 and "config.local.yaml" in r.stderr
