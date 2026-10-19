"""Phase F – Besichtigung und Abwicklung (ADR-029): Handy-Besichtigung für Verkaufsanfragen, Ankaufsvorgang bis zum Verkauf,
nachvollziehbarer Weg vom Gebot zum Ankauf, Ergebnisvergleich Plan gegen Ist."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import base64
import re
import shutil
import sqlite3
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.auktion import zeit
from wmscout.bewertung import ergebnis
from wmscout.bewertung.rechner import _runde
from wmscout.datenbank import Datenbank

PNG = "data:image/png;base64,iVBORw0KGgo="
PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n%Test\n").decode()
HEUTE = date.today().isoformat()
GESTERN = (date.today() - timedelta(days=1)).isoformat()


def _kauf(preis=25000, **extra):
    return {"entscheidung": "gekauft", "endpreis": preis, "begruendung_unvollstaendig": "Test", "unterschrift_verkaeufer": PNG,
            "unterschrift_ankaeufer": PNG, "verkaeufer": {"name": "Erika Beispiel", "anschrift": "Musterweg 1", "telefon": "0170 0000000",
                                                         "eigentum_frei": True, "unfall": "keine bekannt"}, **extra}


# ---------------------------------------------------------------- Ergebnisvergleich (rein)
PLAN = {"quelle": "Test", "kalkulation_id": 1, "haendler_vk": 40000, "kosten": 4000, "provision": 0, "ziel_marge": 4800, "max_ek": 28000,
        "gewinn": 5000, "vk_spanne": [36000, 44000], "standzeit_tage": 90, "differenzbesteuerung": True}


def test_vergleich_vor_und_nach_dem_verkauf():
    a = {"kaufpreis": 29000, "status": "uebergeben", "uebergabe_am": "2026-01-01", "verkauft_am": None, "vk_preis": None}
    kosten = [{"art": "aufbereitung", "betrag": 1200}, {"art": "transport", "betrag": 400}, {"art": "aufbereitung", "betrag": -200}]
    v = ergebnis.vergleich(PLAN, a, kosten, heute=date(2026, 2, 15))
    assert v["ist"]["kosten"] == 1400 and v["ist"]["kosten_je_art"] == {"aufbereitung": 1000, "transport": 400}
    assert v["ist"]["vorlaeufig"] and v["ist"]["gewinn"] == _runde((40000 - 29000) * 100 / 119 - 1400) and v["ist"]["standzeit_tage"] == 45
    assert v["abweichung"]["unter_max_ek"] == -1000 and v["abweichung"]["vk"] is None
    assert "Kaufpreis lag 1.000 € über dem Max-EK" in v["hinweise"] and any("vorläufig" in h for h in v["hinweise"])
    verkauft = {**a, "status": "verkauft", "vk_preis": 46000, "verkauft_am": "2026-05-01"}
    v = ergebnis.vergleich(PLAN, verkauft, kosten)
    assert not v["ist"]["vorlaeufig"] and v["abweichung"]["vk"] == 6000 and v["abweichung"]["vk_prozent"] == 15.0
    assert v["ist"]["standzeit_tage"] == 120 and v["abweichung"]["standzeit_tage"] == 30 and v["abweichung"]["kosten"] == -2600
    assert "Verkaufspreis außerhalb der geplanten Spanne – Marktwert-Schätzung prüfen" in v["hinweise"]
    regel = ergebnis.vergleich({**PLAN, "differenzbesteuerung": False}, verkauft, kosten)
    assert regel["ist"]["gewinn"] == _runde(46000 / 1.19 - 29000 - 1400) and regel["ist"]["gewinn"] % 50 == 0
    u = ergebnis.uebersicht([(verkauft, v), (a, ergebnis.vergleich(PLAN, a, kosten))])
    assert (u["verkauft"], u["im_bestand"], u["vk_abweichung_prozent"], u["kapital_im_bestand"]) == (1, 1, 15.0, 29000 + 1400)


# ---------------------------------------------------------------- Ablauf Verkaufsanfrage ohne Auktion
def test_anfrage_besichtigung_bis_verkauf(markt, db, tmp_path):
    anna, ben, hugo, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["anfrage"]
    assert hugo("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[0] == 403          # Händler: Positivliste
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[0] == 403           # nicht Bearbeiter der Anfrage
    s, b, _ = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {"termin": "2026-10-20T10:00", "zustaendig_id": team_id(db, "Ben")})
    assert s == 200 and b["anzeige_id"] == f"anfrage-{anfrage}" and b["zustaendig"]["name"] == "Ben"
    assert anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[0] == 409          # nur eine offene
    voll = ben("GET", f"/api/besichtigung/{b['id']}")[1]
    assert voll["basis"]["referenz"].startswith("VA-") and voll["basis"]["url"] is None and voll["basis"]["verkaeufer"]["name"] == "Erika Beispiel"
    assert voll["basis"]["zuschlag"] is None and voll["basis"]["angebot"] > 0
    assert any(t["id"] == b["id"] for t in ben("GET", "/api/heute")[1]["termine"])           # erscheint in der Handy-App
    s, ende, _ = ben("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf())                  # Besichtiger darf abschließen
    assert s == 200 and ende["ankauf"]
    aid = ende["ankauf"]
    detail = anna("GET", f"/api/verkaufsanfrage/{anfrage}")[1]
    assert detail["status"] == "gekauft" and [k["id"] for k in detail["ankaeufe"]] == [aid]
    a = anna("GET", f"/api/ankauf/{aid}")[1]
    assert (a["herkunft"], a["status"], a["kaufpreis"], a["auktion_id"]) == ("anfrage", "gekauft", 25000, None)
    plan = a["vergleich"]["plan"]
    assert plan["kalkulation_id"] == a["kalkulation_id"] and plan["provision"] == 0                   # ohne Auktion keine Provision
    assert anna("GET", f"/api/kalkulation/{a['kalkulation_id']}")[1]["nachrechnung"]["gleich"]
    assert [w["schritt"] for w in a["weg"]][:3] == ["Verkaufsanfrage", "Kalkulation zum Kaufpreis", "Besichtigung und Kaufprotokoll"]
    # Vertrag → Übergabe → Kosten → Verkauf
    assert ben("POST", f"/api/ankauf/{aid}/uebergabe", {"uebergabe_am": HEUTE, "zahlung_am": HEUTE})[0] == 409   # Vertrag fehlt
    s, html, _ = anna("GET", f"/ankauf/{aid}/vertrag")
    assert s == 200 and "MUSTER ohne Rechtsgewähr" in html and "Erika Beispiel" in html and "25.000 €" in html
    assert ben("POST", f"/api/ankauf/{aid}/vertrag", {})[0] == 200 and ben("POST", f"/api/ankauf/{aid}/vertrag", {})[0] == 409
    zukunft = (date.today() + timedelta(days=2)).isoformat()
    assert ben("POST", f"/api/ankauf/{aid}/uebergabe", {"uebergabe_am": zukunft, "zahlung_am": HEUTE})[0] == 400
    assert ben("POST", f"/api/ankauf/{aid}/uebergabe", {"uebergabe_am": "gestern", "zahlung_am": HEUTE})[0] == 400
    assert ben("POST", f"/api/ankauf/{aid}/uebergabe", {"uebergabe_am": HEUTE, "zahlung_am": HEUTE, "km": 91000})[0] == 200
    assert ben("POST", f"/api/ankauf/{aid}/kosten", {"art": "aufbereitung", "betrag": 800, "datum": HEUTE})[0] == 200
    assert ben("POST", f"/api/ankauf/{aid}/kosten", {"art": "aufbereitung", "betrag": -100, "datum": HEUTE, "notiz": "Gutschrift"})[0] == 200
    for falsch in ({"art": "xyz", "betrag": 1, "datum": HEUTE}, {"art": "transport", "betrag": 0, "datum": HEUTE},
                   {"art": "transport", "betrag": 1.5, "datum": HEUTE}, {"art": "transport", "betrag": "5", "datum": HEUTE}):
        assert ben("POST", f"/api/ankauf/{aid}/kosten", falsch)[0] == 400
    assert ben("POST", f"/api/ankauf/{aid}/verkauf", {"vk_preis": 38000, "verkauft_am": GESTERN})[0] == 400       # vor der Übergabe
    assert ben("POST", f"/api/ankauf/{aid}/verkauf", {"vk_preis": 38000, "verkauft_am": HEUTE})[0] == 200
    a = anna("GET", f"/api/ankauf/{aid}")[1]
    i = a["vergleich"]["ist"]
    assert a["status"] == "verkauft" and i["kosten"] == 700 and i["vk"] == 38000 and not i["vorlaeufig"]
    assert i["gewinn"] == _runde((38000 - 25000) * 100 / 119 - 700) and i["standzeit_tage"] == 0
    assert all(w["erledigt"] for w in a["weg"]) and [x["ereignis"] for x in a["verlauf"]] == \
        ["gekauft", "vertrag", "uebergeben", "kosten", "kosten", "verkauft"]
    liste = anna("GET", "/api/ankaeufe")[1]
    assert liste["uebersicht"]["verkauft"] == 1 and liste["vorgaenge"][0]["gewinn"] == i["gewinn"]
    assert anna("POST", f"/api/ankauf/{aid}/storno", {"grund": "x"})[0] == 409                      # nach Übergabe kein Storno
    for sql in ("UPDATE ankauf_kosten SET betrag=1", "DELETE FROM ankauf_verlauf"):
        with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
            db.con.execute(sql)
        db.con.rollback()
    node = shutil.which("node")
    if node:
        datei = tmp_path / "s.js"
        datei.write_text(re.findall(r"<script>(.*?)</script>", anna("GET", "/ankaeufe")[1], re.S)[-1], encoding="utf-8")
        assert subprocess.run([node, "--check", str(datei)], capture_output=True, timeout=60).returncode == 0


def team_id(db, name):
    return db.con.execute("SELECT id FROM nutzer WHERE name=?", (name,)).fetchone()[0]


def test_mitarbeiter_braucht_bearbeitung_storno_nur_inhaber_dokumente(markt, db):
    anna, ben, anfrage = markt["anna"], markt["ben"], markt["anfrage"]
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/uebernehmen", {})[0] == 200
    s, b, _ = ben("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})
    assert s == 200 and b["zustaendig"]["name"] == "Ben"
    aid = ben("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf(20000))[1]["ankauf"]
    s, d, _ = ben("POST", f"/api/ankauf/{aid}/dokument", {"art": "vertrag", "datei": PDF})
    assert s == 200 and d["datei"].endswith(".pdf")
    assert ben("GET", f"/ankauf-dokumente/{aid}/{d['datei']}")[0] == 200
    assert ben("GET", f"/ankauf-dokumente/{aid}/..%2Fx.pdf")[0] == 404 and ben("GET", f"/ankauf-dokumente/{aid}/fremd.pdf")[0] == 404
    assert markt["hugo"]("GET", f"/ankauf-dokumente/{aid}/{d['datei']}")[0] == 403
    text = "data:text/plain;base64," + base64.b64encode(b"hallo").decode()
    assert ben("POST", f"/api/ankauf/{aid}/dokument", {"art": "vertrag", "datei": text})[0] == 400
    assert ben("POST", f"/api/ankauf/{aid}/dokument", {"art": "rechnung", "datei": PDF})[0] == 400
    assert ben("POST", f"/api/ankauf/{aid}/storno", {"grund": "Verkäufer tritt zurück"})[0] == 403
    assert anna("POST", f"/api/ankauf/{aid}/storno", {})[0] == 400
    assert anna("POST", f"/api/ankauf/{aid}/storno", {"grund": "Verkäufer tritt zurück"})[0] == 200
    a = anna("GET", f"/api/ankauf/{aid}")[1]
    assert a["status"] == "storniert" and a["weg"][-1]["schritt"] == "Storniert" and a["weg"][-1]["erledigt"]
    assert ben("POST", f"/api/ankauf/{aid}/kosten", {"art": "transport", "betrag": 100, "datum": HEUTE})[0] == 409


def test_anfrage_abgelehnt_ohne_ankauf_und_geschlossene_anfrage(markt, db):
    anna, anfrage = markt["anna"], markt["anfrage"]
    b = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[1]
    s, ende, _ = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", {"entscheidung": "abgelehnt"})
    assert s == 200 and ende["ankauf"] is None
    assert anna("GET", f"/api/verkaufsanfrage/{anfrage}")[1]["status"] == "abgelehnt"
    assert db.con.execute("SELECT COUNT(*) FROM ankaeufe").fetchone()[0] == 0
    assert anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[0] == 409                # nicht mehr offen


# ---------------------------------------------------------------- Weg vom Gebot zum Ankauf
def test_weg_vom_gebot_zum_ankauf(markt, db):
    anna, hugo, anfrage = markt["anna"], markt["hugo"], markt["anfrage"]
    auk = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 20000})[1]["id"]
    g = hugo("POST", f"/api/haendler/auktion/{auk}/gebot", {"betrag": 21000, "wiederholungs_id": "weg-gebot-01"})[1]
    vorbei = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.con.execute("UPDATE auktionen SET start_utc=?, ende_utc=? WHERE id=?", (zeit(vorbei - timedelta(hours=2)), zeit(vorbei), auk))
    db.con.commit()
    assert anna("POST", f"/api/auktion/{auk}/zuschlag", {})[0] == 200
    b = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[1]
    basis = anna("GET", f"/api/besichtigung/{b['id']}")[1]["basis"]
    assert basis["angebot"] == 21000 and basis["zuschlag"]["standort"] == "Filiale Nord" and basis["zuschlag"]["kalkulation_id"] == g["kalkulation_id"]
    aid = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf(20500))[1]["ankauf"]
    a = anna("GET", f"/api/ankauf/{aid}")[1]
    assert (a["auktion_id"], a["standort_id"]) == (auk, markt["sids"][0])
    assert a["vergleich"]["plan"]["provision"] == 410                                         # 2 % vom Kaufpreis
    schritte = [w["schritt"] for w in a["weg"]]
    assert schritte[:4] == ["Verkaufsanfrage", "Demo-Auktion / Zuschlag", "Kalkulation zum Kaufpreis", "Besichtigung und Kaufprotokoll"]
    assert f"Kalkulation #{g['kalkulation_id']}" in a["weg"][1]["text"] and "nachgerechnet ✓" in a["weg"][2]["text"]
    k = anna("GET", f"/api/kalkulation/{a['kalkulation_id']}")[1]
    assert k["standort"] == "Filiale Nord" and k["auktion_id"] == auk and k["betrag"] == 20500


# ---------------------------------------------------------------- Inserate wie bisher, plus Vorgang
def test_inserat_besichtigung_gekauft_legt_vorgang_an(server, team, db):
    anna = anmelden(server, "Anna")
    fz = anna("GET", "/api/fahrzeuge?filter=bereit")[1][0]
    b = anna("POST", "/api/besichtigung", {"anzeige_id": fz["id"]})[1]
    s, ende, _ = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf(18000))
    assert s == 200 and ende["ankauf"]
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (fz["id"],)).fetchone()[0] == "gekauft"   # unverändert
    a = anna("GET", f"/api/ankauf/{ende['ankauf']}")[1]
    assert (a["herkunft"], a["anzeige_id"], a["kalkulation_id"]) == ("anzeige", fz["id"], None)
    plan = a["vergleich"]["plan"]
    assert plan["quelle"].startswith("Bewertung des Inserats") and plan["kosten"] > 0 and plan["max_ek"] > 0
    assert a["weg"][0]["schritt"] == "Inserat"
    b2 = anna("POST", "/api/besichtigung", {"anzeige_id": anna("GET", "/api/fahrzeuge?filter=bereit")[1][0]["id"]})[1]
    assert anna("POST", f"/api/besichtigung/{b2['id']}/abschluss", {"entscheidung": "offen"})[1]["ankauf"] is None


def test_besichtigung_einer_anfrage_mit_der_inserats_route_nicht_moeglich(markt):
    assert markt["anna"]("POST", "/api/besichtigung", {"anzeige_id": f"anfrage-{markt['anfrage']}"})[0] == 404


# ---------------------------------------------------------------- Migration
def test_migration_v8_altbestand_auf_v9(tmp_path, monkeypatch):
    from wmscout import migrationen
    pfad = tmp_path / "alt.sqlite"
    with monkeypatch.context() as m:
        m.setattr(migrationen, "AKTUELLE_VERSION", 8)
        m.setattr(migrationen, "SCHRITTE", {v: f for v, f in migrationen.SCHRITTE.items() if v <= 8})
        db = Datenbank(str(pfad), wal=False)
        db.con.execute("INSERT INTO besichtigungen (anzeige_id, basis_json) VALUES ('x1', '{}')")
        db.con.commit()
        db.con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == list(range(9, migrationen.AKTUELLE_VERSION + 1))
    con = sqlite3.connect(pfad)
    assert con.execute("SELECT anzeige_id, anfrage_id, basis_json FROM besichtigungen").fetchall() == [("x1", None, "{}")]
    assert {"ankaeufe", "ankauf_kosten", "ankauf_verlauf", "ankauf_dokumente"} <= {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == []
