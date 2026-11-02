"""P7-02 – Verkaufsanfragen im Dashboard: Meldung „Verkaufsanfrage“ (ohne Personendaten, Link zur Anfragenseite), Kachel „Verkaufsanfragen
offen“, Anfragen-Trichter in den Kennzahlen, Handy-App."""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from tests.daten import BASIS
from tests.test_haendler import HaendlerSpeicher
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from tests.test_verkauf import GUELTIG
from wmscout import kennzahlen as kz
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.meldungen import meldungen
from wmscout.team import TeamSpeicher
from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"
JETZT = datetime(2026, 11, 2, 12)


def _v(i, status="eingegangen", erstellt="2026-11-02T08:00:00", **kw):
    return {"id": i, "referenz": f"WM-{i:04d}", "marke": "Hymer", "modell": "B 678", "ez_jahr": 2016, "km": 85000, "preisvorstellung": 39500,
            "status": status, "erstellt_am": erstellt, "bearbeiter_id": None, **kw}


# ---------------------------------------------------------------- 1. Meldung (rein)
def test_meldung_verkaufsanfrage():
    m = meldungen([], JETZT, None, [_v(1), _v(2, erstellt="2026-10-30T08:00:00"), _v(3, status="in_pruefung"), _v(4, marke=None, modell=None,
                                                                                                                ez_jahr=None, km=None,
                                                                                                                preisvorstellung=None)])
    assert [(x["id"], x["dringend"]) for x in m] == [("anfrage-2", True), ("anfrage-1", False), ("anfrage-4", False)]   # dringend zuerst
    alt = m[0]
    assert alt["art_text"] == "Verkaufsanfrage" and alt["link"] == "/anfragen#2" and alt["fahrzeug"] == "Hymer B 678"
    assert alt["text"] == "WM-0002 EZ 2016 · 85.000 km · Preisvorstellung 39.500 € – unbearbeitet seit 3 Tagen"
    assert m[2]["fahrzeug"] == "Wohnmobil" and "ohne Fahrzeugangaben" in m[2]["text"]
    assert "name" not in alt and meldungen([], JETZT) == [] and meldungen([], JETZT, None, None) == []


# ---------------------------------------------------------------- 2. Mit Datenbank: API, Dashboard, Kennzahlen
def _anfragen(db, tmp_path, n=2):
    sp = VerkaufSpeicher(db, tmp_path / "anfrage-fotos")
    return [sp.anlegen(pruefe_anfrage(GUELTIG, jahr=2026), None, "test-1")["id"] for _ in range(n)], sp


def test_api_meldungen_und_rechte(server, db, tmp_path):
    ids, _ = _anfragen(db, tmp_path)
    c = lokal(server)
    m = [x for x in c("GET", "/api/meldungen")[1]["meldungen"] if x["art"] == "anfrage"]
    assert {x["id"] for x in m} == {f"anfrage-{i}" for i in ids} and all(x["link"].startswith("/anfragen#") for x in m)
    assert "Erika" not in repr(m) and "0170" not in repr(m)                                    # keine Personendaten
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    assert anmelden(server, "Hugo")("GET", "/api/meldungen")[0] == 403
    html = anmelden(server, "Anna")("GET", "/")[1]
    assert "data-kpi-anfragen" in html and "Verkaufsanfragen offen (2 neu, 0 in Prüfung, 0 mit Angebot)" in html
    assert re.search(r'<a class="btn" href="/anfragen#\d+" data-meldung-link>öffnen</a>', html)


def test_bericht_ohne_anfragen(cfg, db, tmp_path):
    _anfragen(db, tmp_path)
    html = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)[0]                     # statischer Bericht: ohne Anfragen
    assert "data-kpi-anfragen" not in html and 'data-meldung="anfrage"' not in html


def test_kennzahlen_anfragen_trichter(cfg, db, tmp_path):
    ids, sp = _anfragen(db, tmp_path, 6)
    sp.setze_status(ids[0], "angebot", None)
    sp.setze_status(ids[0], "abgelehnt", None)                                               # Angebot laut Verlauf, danach abgelehnt
    sp.setze_status(ids[1], "gekauft", None)
    sp.setze_status(ids[2], "zurueckgezogen", None)
    TeamSpeicher(db, tmp_path / "fotos").besichtigung_anlegen(f"anfrage-{ids[1]}", {"fahrzeug": "Hymer"}, None, None, None, None)
    db.con.commit()
    a = kz.messe(cfg, db, {"kennzahlen": {}}, [], 30)["anfragen"]
    assert (a["eingegangen"], a["offen"], a["angebot"], a["besichtigt"], a["gekauft"]) == (6, 3, 2, 1, 1)
    assert (a["abgelehnt"], a["zurueckgezogen"], a["angebotsquote"], a["ankaufsquote"]) == (1, 1, 0.333, 0.167)
    db.con.execute("UPDATE verkaufsanfragen SET erstellt_am=?", ((datetime.now() - timedelta(days=60)).isoformat(timespec="seconds"),))
    db.con.commit()
    assert kz.messe(cfg, db, {"kennzahlen": {}}, [], 30)["anfragen"]["eingegangen"] == 0      # außerhalb des Zeitraums


def test_kennzahlen_seite_und_handy():
    html = (BASIS / "vorlagen" / "kennzahlen.html").read_text(encoding="utf-8")
    assert 'id="anfragen-trichter"' in html and 'href="/anfragen"' in html
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    regex = re.search(r"m\.link && /(.+?)/\.test\(m\.link\) \? esc\(m\.link\)", js).group(1)      # nur Pfade dieses Servers (QA B5)
    for gut in ("/anfragen#7", "/anfragen"):
        assert re.fullmatch(regex, gut), gut
    for boese in ("//16909060", "//intranet/x", "javascript:alert(1)", "https://boese.example", "/a b"):
        assert not re.fullmatch(regex, boese), boese
    assert int(re.search(r"wm-scout-(\d+)", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 24


# ---------------------------------------------------------------- 3. Korrekturrunde (QA P7-02)
def test_kachel_status_mitarbeiter_und_frist(server, db, tmp_path):
    """Kachel zählt neu/in Prüfung/Angebot, nicht abgelehnt/gekauft; Mitarbeiter sehen Meldungen ohne Verkäuferdaten; fristgelöschte oder
    widerrufene Anfragen fallen aus Meldungen und Kachel (B7); Felder genau die Fahrzeugangaben (B4)."""
    ids, sp = _anfragen(db, tmp_path, 6)
    sp.setze_status(ids[1], "in_pruefung", None)
    sp.setze_status(ids[2], "angebot", None)
    sp.setze_status(ids[3], "abgelehnt", None)
    sp.setze_status(ids[4], "gekauft", None)
    sp.widerruf(ids[5], None, grund="frist")
    sp.setze_status(ids[5], "eingegangen", None)                              # auch wenn der Status danach wieder „eingegangen“ wäre
    assert {a["id"] for a in sp.offene_kurz()} == set(ids[:3])
    assert set(sp.offene_kurz()[0]) == {"id", "referenz", "marke", "modell", "ez_jahr", "km", "preisvorstellung", "status", "erstellt_am",
                                        "bearbeiter_id"}
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    db.con.commit()
    ben = anmelden(server, "Ben")
    m = [x for x in ben("GET", "/api/meldungen")[1]["meldungen"] if x["art"] == "anfrage"]
    assert [x["id"] for x in m] == [f"anfrage-{ids[0]}"]
    roh = repr(m)
    assert all(t not in roh for t in ("Erika", "0170", "12345", "@"))
    html = ben("GET", "/")[1]
    assert "Verkaufsanfragen offen (1 neu, 1 in Prüfung, 1 mit Angebot)" in html and ">Verkaufsanfrage</span>" in html


def test_trichter_storno_und_abgebrochen(cfg, db, tmp_path):
    ids, sp = _anfragen(db, tmp_path, 5)
    t = TeamSpeicher(db, tmp_path / "fotos")
    abgebrochen = t.besichtigung_anlegen(f"anfrage-{ids[0]}", {"fahrzeug": "Hymer"}, None, None, None, None)
    t.besichtigung_abschliessen(abgebrochen, {}, None, status="abgebrochen")
    bid = t.besichtigung_anlegen(f"anfrage-{ids[1]}", {"fahrzeug": "Hymer"}, None, None, None, None)
    db.con.execute("INSERT INTO ankaeufe (herkunft, anfrage_id, besichtigung_id, status, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('anfrage', ?, ?, 'storniert', 30000, '{}', ?)", (ids[1], bid, datetime.now().isoformat(timespec="seconds")))
    bid2 = t.besichtigung_anlegen(f"anfrage-{ids[2]}", {"fahrzeug": "Hymer"}, None, None, None, None)
    db.con.execute("INSERT INTO ankaeufe (herkunft, anfrage_id, besichtigung_id, status, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('anfrage', ?, ?, 'gekauft', 30000, '{}', ?)", (ids[2], bid2, datetime.now().isoformat(timespec="seconds")))
    db.con.commit()
    a = kz.messe(cfg, db, {"kennzahlen": {}}, [], 30)["anfragen"]
    assert (a["besichtigt"], a["gekauft"], a["angebot"]) == (2, 1, 1)          # abgebrochen zählt nicht, Storno nicht; Ankauf zählt als Angebot (B6)
