"""P6-05 – Kennzahlen-Ansicht (ADR-065): Ankaufstrichter, Bewertungslage, Zusammenführung mit der Abdeckungsmessung, API, Seite, Links;
keine Preise, keine falsche Genauigkeit bei wenigen Fällen."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from tests.daten import BASIS
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout import kennzahlen as kz
from wmscout import verhandlung as vh
from wmscout.team import TeamSpeicher
from wmscout.web.api import _haendler_erlaubt

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"
SEIT = datetime(2026, 10, 1)


# ---------------------------------------------------------------- 1. Trichter (rein)
def test_trichter_zaehlt_erste_kontakte_im_zeitraum():
    erste = {f"k{i}": f"2026-10-{10 + i:02d}T10:00:00" for i in range(6)} | {"alt": "2026-09-20T10:00:00"}
    antworten = {"k0": ["2026-10-11T10:00:00"], "k1": ["2026-10-09T10:00:00", "2026-10-13T22:00:00"], "k2": ["2026-10-01T00:00:00"],
                 "alt": ["2026-10-02T10:00:00"]}
    t = kz.trichter(erste, antworten, besichtigt={"k0", "k1", "alt"}, gekauft={"k0"}, seit=SEIT)
    assert (t["kontaktiert"], t["beantwortet"], t["besichtigt"], t["gekauft"]) == (6, 2, 2, 1)       # „alt“ zählt nicht, k2 antwortete vorher
    assert (t["antwortquote"], t["besichtigungsquote"], t["ankaufsquote"]) == (0.333, 0.333, 0.167)
    assert t["antwortzeit_tage"] is None and t["antwortzeit_faelle"] == 2                           # unter 5 Fällen kein Median


def test_trichter_wenige_faelle_und_median():
    assert kz.trichter({"a": "2026-10-05T10:00:00"}, {"a": ["2026-10-06T10:00:00"]}, {"a"}, {"a"}, SEIT)["antwortquote"] is None
    erste = {f"k{i}": "2026-10-05T10:00:00" for i in range(5)}
    antworten = {f"k{i}": [f"2026-10-{6 + i:02d}T10:00:00"] for i in range(5)}             # 1, 2, 3, 4, 5 Tage
    t = kz.trichter(erste, antworten, set(), set(), SEIT)
    assert t["antwortzeit_tage"] == 3.0 and t["antwortquote"] == 1.0 and t["ankaufsquote"] == 0.0
    mit_zone = kz.trichter({"z": "2026-10-05T10:00:00+00:00"}, {"z": ["2026-10-06T10:00:00+00:00"]}, set(), set(), SEIT)
    assert mit_zone["beantwortet"] == 1


# ---------------------------------------------------------------- 2. Bewertungslage (rein)
def _z(i, sicherheit="hoch", von=40000, bis=44000, mw=42000, top=False, ausblenden=False, dub=(), ampel="gruen"):
    b = SimpleNamespace(sicherheit=sicherheit, spanne_von=von, spanne_bis=bis, marktwert_angebote=mw, ampel=ampel)
    return {"a": {"id": i}, "b": b, "deal": {"priorisiert": top}, "ausblenden": ausblenden, "dubletten_ids": list(dub)}


def test_bewertungslage():
    zeilen = [_z(f"z{i}", bis=40000 + 840 * (i + 1)) for i in range(5)] + [_z("t1", top=True, dub=["t2"]), _z("t2", top=True, dub=["t1"]),
                                                                       _z("k", sicherheit="keine", ampel="grau"), _z("weg", ausblenden=True, top=True)]
    w = kz.bewertungslage(zeilen)
    assert w["inserate"] == 8 and w["fahrzeuge"] == 7 and w["priorisiert_inserate"] == 2 and w["priorisiert_fahrzeuge"] == 1
    assert w["unsicherheit_faelle"] == 7 and w["unsicherheit_median"] == 0.08                       # ohne „keine“, ohne Ausgeblendete
    assert w["sicherheit"] == {"hoch": 7, "keine": 1} and w["ampel"] == {"gruen": 7, "grau": 1}
    assert kz.bewertungslage(zeilen[:3])["unsicherheit_median"] is None


# ---------------------------------------------------------------- 3. Mit Datenbank, API, Seite
def _ankaufsgeschehen(db, tmp_path, ids):
    jetzt = datetime.now()
    for i in ids[:6]:
        db.setze_status(i, "kontaktiert", text="Hallo")
    for i in ids[:3]:
        vh.eintragen(db, i, vh.pruefe({"art": "antwort", "text": "Herr Muster 0170", "betrag": 33333}), None, jetzt + timedelta(hours=1))
    t = TeamSpeicher(db, tmp_path / "fotos")
    bid = t.besichtigung_anlegen(ids[0], {"fahrzeug": "Knaus"}, None, None, None, None)
    t.besichtigung_abschliessen(bid, {"vereinbart": True}, 31234)
    t.besichtigung_anlegen(ids[1], {"fahrzeug": "Knaus"}, None, None, None, None)


def test_api_und_seite(server, db, tmp_path):
    ids = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 6")]
    _ankaufsgeschehen(db, tmp_path, ids)
    c = lokal(server)
    s, m, _ = c("GET", "/api/kennzahlen?tage=30")
    assert s == 200 and m["tage"] == 30
    t = m["trichter"]
    assert (t["kontaktiert"], t["beantwortet"], t["besichtigt"], t["gekauft"]) == (6, 3, 2, 1) and t["antwortquote"] == 0.5
    assert m["im_zeitraum"]["kontakte"] == 6 and m["im_zeitraum"]["antworten"] == 3 and m["im_zeitraum"]["besichtigungen"] == 2
    assert m["eingang"]["neue_inserate"] >= 1 and "importerfolg" in m["eingang"] and m["bewertung"]["inserate"] >= 1
    roh = repr(m)
    assert "31234" not in roh and "33333" not in roh and "Muster" not in roh                       # keine Preise, keine Personendaten
    assert c("GET", "/api/kennzahlen?tage=0")[0] == 400 and c("GET", "/api/kennzahlen?tage=500")[0] == 400
    s, html, _ = c("GET", "/kennzahlen?tage=7")
    assert s == 200 and "<h1>Kennzahlen</h1>" in html and 'aria-current="page">7 Tage' in html
    assert re.search(r'data-t="kontaktiert"><b>6</b>', html) and "Antwort erhalten · 50 %" in html and "nicht messbar" in html
    assert "zu wenige Fälle" in html and "31.234" not in html and "31234" not in html


def test_rechte_und_links():
    assert not _haendler_erlaubt("/kennzahlen") and not _haendler_erlaubt("/api/kennzahlen")       # Standort-Zugänge: 403 (Positivliste)
    vorlagen = BASIS / "vorlagen"
    for datei in ("report.html", "status.html", "abdeckung.html"):
        assert 'href="/kennzahlen' in (vorlagen / datei).read_text(encoding="utf-8"), datei
    assert 'href="/kennzahlen"' in (STATIC / "mobil.js").read_text(encoding="utf-8")
    assert int(re.search(r"wm-scout-(\d+)", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 23
    css = (vorlagen / "kennzahlen.html").read_text(encoding="utf-8").split("<style>")[1].split("</style>")[0]
    assert "{#" not in css                                                                            # kein Jinja-Kommentar im CSS


# ---------------------------------------------------------------- 4. Korrekturrunde (QA P6-05)
def _mini(cfg, db):
    from tests.test_dubletten_vorschlaege import treffer
    for i in ("p1", "p2", "p3"):
        db.speichere_treffer(treffer(i, ort=f"7017{i[-1]} Stuttgart", km=80000 + 20000 * int(i[-1])), "Alkoven")
    return {"kennzahlen": {}}


def test_storno_dubletten_abgebrochen_ohne_tabellen(cfg, db, tmp_path):
    """B1 Storno ist kein Ankauf; B2 bestätigte Dubletten zählen als ein Fahrzeug (Antwort an der Dublette zählt); B4 Verkäufer statt
    Kontakte; B6 abgebrochene Besichtigung zählt nicht; ohne Tabellen `verhandlung`/`ankaeufe` (Altbestand) keine Ausnahme."""
    from tests.test_dubletten_vorschlaege import inserat_id
    from wmscout.dubletten import bestaetige
    leer = _mini(cfg, db)
    bestaetige(db, inserat_id(db, "p1"), inserat_id(db, "p2"), None)
    db.setze_status("p1", "kontaktiert", text="Hallo")
    db.setze_status("p2", "kontaktiert", text="Hallo")
    vh.eintragen(db, "p2", vh.pruefe({"art": "antwort", "text": "ja"}), None, datetime.now() + timedelta(hours=1))
    db.setze_status("p3", "kontaktiert", text="Hallo")
    t = TeamSpeicher(db, tmp_path / "fotos")
    bid = t.besichtigung_anlegen("p1", {"fahrzeug": "Knaus"}, None, None, None, None)
    t.besichtigung_abschliessen(bid, {}, 30000)
    db.con.execute("INSERT INTO ankaeufe (herkunft, anzeige_id, besichtigung_id, status, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('anzeige', 'p1', ?, 'storniert', 30000, '{}', ?)", (bid, datetime.now().isoformat(timespec="seconds")))
    abgebrochen = t.besichtigung_anlegen("p3", {"fahrzeug": "Knaus"}, None, None, None, None)
    t.besichtigung_abschliessen(abgebrochen, {}, None, status="abgebrochen")
    db.con.commit()
    m = kz.messe(cfg, db, leer, [], 30)
    tr = m["trichter"]
    assert (tr["kontaktiert"], tr["beantwortet"], tr["besichtigt"], tr["gekauft"]) == (2, 1, 1, 0)
    assert m["im_zeitraum"]["kontaktierte"] == 2 and m["im_zeitraum"]["kontakte"] == 3 and m["im_zeitraum"]["besichtigungen"] == 1
    assert m["im_zeitraum"]["ankaeufe"] == 0
    db.con.execute("DROP TABLE verhandlung")
    db.con.execute("DROP TABLE ankaeufe")
    db.con.commit()
    alt = kz.messe(cfg, db, leer, [], 30)["trichter"]
    assert alt["beantwortet"] == 0 and alt["gekauft"] == 1                                  # ohne Vorgangstabelle zählt der Altweg


def test_seite_wenige_faelle_als_n_von_m(server, db):
    c = lokal(server)
    html = c("GET", "/kennzahlen?tage=1")[1]
    assert "Besichtigung angelegt" in html and "Kontaktierte Verkäufer" in html and "Mail-Datum schon als" in html
    # Eingangsanteile bei kleiner Basis als „n von m“ statt Prozent (B3)
    zeile = re.search(r"Läufe ohne Fehler \((\w+)\)</td><td class=\"z\">([^<]*)</td>", html)
    assert zeile and re.fullmatch(r"\d von \d", zeile.group(2)), zeile and zeile.group(0)
