"""P1-12 (Q1, KRITISCH): Ohne Erstzulassung gibt es keinen unabhängigen Marktwert – also keine Beträge aus dem Angebotspreis.
Max-EK und Erstangebot erst mit manuell angegebenem Marktwert; Invariante Erstangebot ≤ Max-EK ≤ Händler-VK."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import csv
import itertools

from scout import BASIS
from tests.test_cli import _scout
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.ausgabe import schreibe_ausgaben
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.rechner import Rechner

OHNE_EZ = {"id": "x1", "titel": "Knaus Sun Ti", "marke": "Knaus", "preis": 39000, "km": 90000, "suche": "Teilintegrierter"}


def test_ohne_ez_keine_betraege_mit_marktwert_schon(cfg):
    r = Rechner(cfg)
    b = r.bewerte(dict(OHNE_EZ), [])
    assert (b.sicherheit, b.ampel, b.marktwert_angebote) == ("keine", "grau", None)
    assert (b.max_ek, b.erstangebot, b.haendler_vk, b.marktwert_privat, b.potenzial, b.verhaeltnis) == (0, 0, 0, 0, None, None)
    assert "Erstzulassung fehlt" in b.vergleich_basis and "manuell" in b.vergleich_basis
    m = r.bewerte(dict(OHNE_EZ), [], marktwert_manuell=42000)
    assert m.sicherheit == "manuell" and 0 < m.erstangebot <= m.max_ek <= m.haendler_vk


def test_invariante_erstangebot_max_ek_vk(cfg):
    r = Rechner(cfg)
    for ez, km, preis, art in itertools.product((2008, 2015, 2022), (20000, 150000), (8000, 30000, 70000, 140000),
                                                ("Kastenwagen", "Teilintegrierter", "Alkoven", "Integrierter")):
        b = r.bewerte({"id": f"i{ez}{km}{preis}{art}", "titel": f"Wohnmobil {art}", "preis": preis, "ez_jahr": ez, "km": km,
                       "suche": art}, [])
        assert 0 <= b.erstangebot <= b.max_ek <= b.haendler_vk, (ez, km, preis, art, b.erstangebot, b.max_ek, b.haendler_vk)


def test_csv_und_api_ohne_betraege_besichtigung_nur_mit_marktwert(cfg, db, importiert, server, team):
    ziel = db.con.execute("SELECT id FROM anzeigen WHERE ez_jahr IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]
    db.con.execute("UPDATE anzeigen SET ez_jahr=NULL WHERE id=?", (ziel,))
    db.con.commit()
    zeilen = bewerte_alle(cfg, db, BASIS)
    pfad = schreibe_ausgaben(cfg, zeilen, BASIS)["csv"]
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        z = list(csv.reader(f, delimiter=";"))
    kopf, zeile = z[0], next(r for r in z if r[0] == ziel)
    for spalte in ("Marktwert privat", "Händler-VK", "Kosten", "Ziel-Marge", "Max-EK", "Erstangebot", "Gewinn bei Angebotspreis"):
        assert zeile[kopf.index(spalte)] == "", spalte
    assert zeile[kopf.index("Sicherheit")] == "keine"
    ben = anmelden(server, "Ben")
    f = ben("GET", f"/api/fahrzeug/{ziel}")[1]
    assert f["bewertung"]["sicherheit"] == "keine" and not f["bewertung"]["max_ek"]
    s, fehler, _ = ben("POST", "/api/besichtigung", {"anzeige_id": ziel})
    assert s == 409 and fehler["grund"] == "marktwert"
    assert ben("POST", "/api/besichtigung", {"anzeige_id": ziel, "marktwert": "viel"})[0] == 409
    s, b, _ = ben("POST", "/api/besichtigung", {"anzeige_id": ziel, "marktwert": 36000})
    assert s == 200
    basis = ben("GET", f"/api/besichtigung/{b['id']}")[1]["basis"]
    assert basis["marktwert_manuell"] == 36000 and 0 < basis["angebot"] <= basis["max_ek"] <= basis["haendler_vk"]


def test_cli_rechne_ohne_ez(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "rechne", "--preis", "39000", "--km", "90000", "--titel", "Knaus Sun Ti", "--anschreiben")
    assert r.returncode == 0, r.stderr
    assert "Keine Beträge" in r.stdout and "MAX. EINKAUFSPREIS" not in r.stdout and "39.000" not in r.stdout.split("Anschreiben")[1]
    r = _scout(cfg, tmp_path, "rechne", "--preis", "39000", "--km", "90000", "--titel", "Knaus Sun Ti", "--marktwert", "42000")
    assert r.returncode == 0 and "MAX. EINKAUFSPREIS" in r.stdout, r.stderr
