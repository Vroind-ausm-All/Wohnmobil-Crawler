"""Kommandozeile scout.py (rechne, report, status) mit eigener Konfiguration im Temp-Ordner."""
import subprocess
import sys

import yaml

from tests.daten import BASIS


def _scout(cfg, tmp_path, *argumente):
    pfad = tmp_path / "config.yaml"
    pfad.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return subprocess.run([sys.executable, str(BASIS / "scout.py"), "--config", str(pfad), *argumente],
                          capture_output=True, text=True, encoding="utf-8", cwd=BASIS, timeout=120)


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
