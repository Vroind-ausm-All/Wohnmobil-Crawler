"""P7-01 – Nacharbeiten aus Phase 5/6 (P5-06b, P6-01b, P6-02b, P6-03b, P6-05b): Abholung in der Handy-App, Route erst nach /api/ich,
Preisverlauf nur für benötigte Inserate, Filterzähler als Fahrzeuge, Kontaktlage je Fahrzeug, Audit-Objekt, Notiz nach Anonymisierung
wieder fällig, Rechte der Kennzahlen."""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import inserat_id, treffer
from tests.test_haendler import HaendlerSpeicher
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from wmscout import preisverlauf as pv
from wmscout import verhandlung as vh
from wmscout.audit import einordnen
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenrechte import inserat_anonymisieren, inserate_faellig
from wmscout.dubletten import bestaetige
from wmscout.team import TeamSpeicher

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"


# ---------------------------------------------------------------- P5-06b, P6-01b: Handy-App
def test_handy_abholung_und_route_nach_ich():
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    assert "function abholZeile" in js and "abholZeile(b) +" in js and "✓ gerechnet" in js and 'esc(v.ab)' in js
    assert re.search(r"function route\(\) \{\s*if \(!S\.ich\) return;", js)                # Hash-Wechsel vor /api/ich: kein Fehler
    assert int(re.search(r"wm-scout-(\d+)", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 24


# ---------------------------------------------------------------- P6-02b: Preisverlauf und Zähler
def test_verlaeufe_nur_fuer_ids_in_bloecken(db, monkeypatch):
    for i in ("p1", "p2", "p3"):
        db.speichere_treffer(treffer(i, ort=f"7017{i[-1]} Stuttgart", km=80000 + 20000 * int(i[-1])), "Alkoven")
    db.speichere_treffer(treffer("p1", preis=38000, ort="70171 Stuttgart", km=100000), "Alkoven")
    alle = pv.verlaeufe(db)
    monkeypatch.setattr(pv, "BLOCK", 1)                                                   # Blockgrenze wirkt
    teil = pv.verlaeufe(db, {"p1", "p3", "gibtsnicht"})
    assert set(teil) == {"p1", "p3"} and teil["p1"] == alle["p1"] and pv.verlaeufe(db, set()) == {}


def test_filterzaehler_als_fahrzeuge(cfg, db):
    for i in ("p1", "p2"):                                                                # gleiches Fahrzeug, zweimal frisch eingestellt
        db.speichere_treffer(treffer(i), "Alkoven")
    db.speichere_treffer(treffer("x1", titel="Hymer B 544", marke="Hymer", ez_jahr=2012, ort="80331 München"), "Alkoven")
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert {z["a"]["id"]: z["dubletten_ids"] for z in zeilen}["p1"] == ["p2"]
    html = render_html(cfg, zeilen, BASIS)[0]
    zahl = re.search(r'data-zahl data-inserate="(\d+)" data-fahrzeuge="(\d+)">\((\d+)\)', html.split('data-f="neuigkeiten"')[1])
    assert zahl and (int(zahl.group(1)), int(zahl.group(2))) == (3, 2)
    assert "einmal.checked ? s.dataset.fahrzeuge : s.dataset.inserate" in html


# ---------------------------------------------------------------- P6-03b: Kontaktlage je Fahrzeug, Audit, Frist
def _paar(db):
    db.speichere_treffer(treffer("p1"), "Alkoven")
    db.speichere_treffer(treffer("p2", ort="80331 München", km=91000), "Alkoven")
    bestaetige(db, inserat_id(db, "p1"), inserat_id(db, "p2"), None)


def test_kontaktlage_je_fahrzeug(cfg, db):
    _paar(db)
    db.setze_status("p1", "kontaktiert", text="Hallo")
    vh.eintragen(db, "p2", vh.pruefe({"art": "antwort", "text": "ja", "betrag": 38000}), None, datetime.now() + timedelta(minutes=1))
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert z["p1"]["kontakt"]["stufe"] == "antwort" and z["p2"]["kontakt"]["stufe"] == "antwort"       # Antwort an der Dublette zählt
    assert vh.zusammen([None, {"kontakt_am": "a", "eintraege": 1}, {"kontakt_am": "b", "eintraege": 2,
                                                                     "besichtigung": {"status": "abgeschlossen", "termin": None}}]) == {
        "eintraege": 3, "vorbereitet": False, "kontakt_am": "b", "besichtigung": {"status": "abgeschlossen", "termin": None}}
    assert vh.zusammen([]) == {} and vh.zusammen([None]) == {}


def test_audit_objekt_fuer_notiz_und_verhandlung(server, db, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    db.con.commit()
    anna = anmelden(server, "Anna")
    aid = db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 1").fetchone()[0]
    assert anna("POST", "/api/notiz", {"id": aid, "notiz": "Rückruf"})[0] == 200
    assert anna("POST", "/api/verhandlung", {"id": aid, "art": "notiz", "text": "x"})[0] == 200
    assert anna("GET", f"/api/verhandlung/{aid}")[0] == 200
    zeilen = db.con.execute("SELECT methode, pfad, aktion, objekt FROM audit WHERE pfad LIKE '/api/notiz%' OR pfad LIKE '/api/verhandlung%' "
                            "ORDER BY id").fetchall()
    assert [tuple(z) for z in zeilen] == [("POST", "/api/notiz", "aendern", f"anzeige:{aid}"),
                                          ("POST", "/api/verhandlung", "aendern", f"anzeige:{aid}"),
                                          ("GET", f"/api/verhandlung/{aid}", "lesen", f"anzeige:{aid}")]
    assert einordnen("GET", "/api/verhandlung/abc") == ("lesen", "anzeige:abc")


def test_notiz_nach_anonymisierung_wieder_faellig(db, tmp_path):
    db.speichere_treffer(treffer("q1", ort="80331 München", km=150000), "Alkoven")
    alt = (datetime.now() - timedelta(days=800)).isoformat(timespec="seconds")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, notiz='Name Erika' WHERE id='q1'", (alt,))
    db.con.commit()
    assert "q1" in inserate_faellig(db, 12)
    inserat_anonymisieren(db, tmp_path, "q1")
    assert "q1" not in inserate_faellig(db, 12)
    db.con.execute("UPDATE anzeigen SET notiz='Herr Muster 0170' WHERE id='q1'")             # danach wieder Personendaten eingetragen
    db.con.commit()
    assert "q1" in inserate_faellig(db, 12)
    inserat_anonymisieren(db, tmp_path, "q1")
    assert "q1" not in inserate_faellig(db, 12)                                              # kein Dauer-„fällig“ (Kontakttexte bleiben)


# ---------------------------------------------------------------- P6-05b: Rechte der Kennzahlen per HTTP
def test_kennzahlen_rechte_http(server, db, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    ben = anmelden(server, "Ben")
    assert ben("GET", "/api/kennzahlen?tage=7")[0] == 200 and ben("GET", "/kennzahlen")[0] == 200
    hugo = anmelden(server, "Hugo")
    assert hugo("GET", "/api/kennzahlen")[0] == 403 and hugo("GET", "/kennzahlen")[0] == 403
    html = ben("GET", "/kennzahlen")[1]
    assert "Mail-Datum schon als „erstmals gesehen“" in html


# ---------------------------------------------------------------- Korrekturrunde (QA P7-01)
def test_ankauf_in_arbeit_je_fahrzeug_und_gekauft_beendet(cfg, db):
    """B2: dasselbe Fahrzeug steht einmal unter „Ankauf in Arbeit“; B3: gekauft an einem Inserat beendet den Vorgang auch an der Dublette."""
    _paar(db)
    db.setze_status("p1", "kontaktiert", text="Hallo")
    html = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)[0]
    bereich = re.search(r'<section class="kasten" id="ankauf-arbeit".*?</section>', html, re.S).group(0)
    assert len(re.findall(r'data-pipeline="', bereich)) == 1 and 'wartet auf Antwort: 1' in bereich
    db.setze_status("p1", "gekauft")
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert not (z["p1"]["kontakt"] or {}).get("stufe") and not (z["p2"]["kontakt"] or {}).get("stufe")
    assert 'id="ankauf-arbeit"' not in render_html(cfg, list(z.values()), BASIS)[0]


def test_audit_fahrzeug_lesen_und_id_geprueft(server, db, tmp_path):
    from wmscout.web.api import audit_anzeige
    assert audit_anzeige("p1") == "anzeige:p1" and audit_anzeige("Herr Muster 0170") is None and audit_anzeige(None) is None
    assert einordnen("GET", "/api/fahrzeug/p1") == ("lesen", "anzeige:p1") and einordnen("GET", "/api/kontakte/p1") == ("lesen", "anzeige:p1")
    assert einordnen("GET", "/api/fahrzeug/anfrage-7") == ("lesen", "anfrage:7")              # Anfragen bleiben Anfragen
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    db.con.commit()
    anna = anmelden(server, "Anna")
    assert anna("POST", "/api/notiz", {"id": "Herr Muster 0170", "notiz": "x"})[0] == 404
    assert db.con.execute("SELECT objekt FROM audit WHERE pfad='/api/notiz'").fetchone()[0] is None


def test_leere_notiz_nach_anonymisierung_nicht_faellig(db, tmp_path):
    db.speichere_treffer(treffer("q1", ort="80331 München", km=150000), "Alkoven")
    alt = (datetime.now() - timedelta(days=800)).isoformat(timespec="seconds")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, notiz='Name Erika' WHERE id='q1'", (alt,))
    db.con.commit()
    inserat_anonymisieren(db, tmp_path, "q1")
    db.setze_notiz("q1", "  ")
    assert "q1" not in inserate_faellig(db, 12)
