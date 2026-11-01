"""P6-03 – Kontaktstatus, Verhandlungsnotizen und Besichtigungsstatus im Dashboard (ADR-063): Eingabeprüfung, Kontaktlage, Schema v23,
Einträge und Lage aus der Datenbank, Datenschutz (Anonymisierung, Frist), API, Desktop-Bereich „Ankauf in Arbeit“, Handy-App."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import treffer
from tests.test_team_bearbeitung import anmelden, lokal, server, starte  # noqa: F401 – Fixtures
from wmscout import migrationen
from wmscout import verhandlung as vh
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenrechte import inserat_anonymisieren, inserate_faellig
from wmscout.team import TeamSpeicher

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"
JETZT = datetime(2026, 11, 1, 12)


# ---------------------------------------------------------------- 1. Eingabe (rein)
def test_pruefe_gueltig_und_kuerzt():
    e = vh.pruefe({"art": "antwort", "text": "  will 34.500  ", "betrag": 34500.4, "kanal": "telefon"})
    assert e == {"art": "antwort", "text": "will 34.500", "betrag": 34500, "kanal": "telefon"}
    assert len(vh.pruefe({"art": "notiz", "text": "x" * 5000})["text"]) == vh.TEXT_MAX
    assert vh.pruefe({"art": "notiz", "text": "ok", "betrag": "", "kanal": ""}) == {"art": "notiz", "text": "ok", "betrag": None, "kanal": None}


@pytest.mark.parametrize("daten, teil", [
    ({"art": "brief", "text": "x"}, "art"), ({"art": "notiz", "text": "  "}, "text fehlt"), ({"art": "notiz"}, "text fehlt"),
    ({"art": "notiz", "text": 5}, "text fehlt"), ({"art": "notiz", "text": "x", "betrag": -5}, "betrag"),
    ({"art": "notiz", "text": "x", "betrag": True}, "betrag"), ({"art": "notiz", "text": "x", "betrag": float("nan")}, "betrag"),
    ({"art": "notiz", "text": "x", "betrag": "34000"}, "betrag"), ({"art": "notiz", "text": "x", "betrag": 10**9}, "betrag"),
    ({"art": "notiz", "text": "x", "kanal": "telefon"}, "kanal"), ({"art": "antwort", "text": "x", "kanal": "brieftaube"}, "kanal"),
])
def test_pruefe_fehler(daten, teil):
    with pytest.raises(ValueError, match=teil):
        vh.pruefe(daten)


# ---------------------------------------------------------------- 2. Kontaktlage (rein)
def _e(zeit, betrag=None, text="t"):
    return {"zeitpunkt": zeit, "betrag": betrag, "text": text}


def test_zustand_stufen():
    assert vh.zustand(None, None, JETZT) is None and vh.zustand("neu", {}, JETZT) is None
    v = vh.zustand("vorbereitet", {"vorbereitet": True}, JETZT)
    assert v["stufe"] == "vorbereitet" and "noch nicht" in v["text"]
    w = vh.zustand("kontaktiert", {"kontakt_am": "2026-10-28T09:00:00"}, JETZT)
    assert (w["stufe"], w["tage"]) == ("wartet", 4) and w["text"] == "kontaktiert am 28.10. – seit 4 Tagen keine Antwort"
    assert vh.zustand("kontaktiert", {"kontakt_am": "2026-11-01T09:00:00"}, JETZT)["text"].endswith("heute")
    assert "seit 1 Tag keine" in vh.zustand("kontaktiert", {"kontakt_am": "2026-10-31T09:00:00"}, JETZT)["text"]
    a = vh.zustand("kontaktiert", {"kontakt_am": "2026-10-28T09:00:00", "antwort": _e("2026-10-29T18:00:00", 34500)}, JETZT)
    assert a["stufe"] == "antwort" and a["text"] == "Antwort am 29.10. – nennt 34.500 €"
    # Antwort vor dem letzten Kontakt (danach nachgefasst): wieder warten
    assert vh.zustand("verhandlung", {"kontakt_am": "2026-10-30T09:00:00", "antwort": _e("2026-10-29T18:00:00")}, JETZT)["stufe"] == "wartet"
    b = vh.zustand("besichtigung", {"kontakt_am": "2026-10-28T09:00:00", "antwort": _e("2026-10-29T18:00:00"),
                                    "besichtigung": {"status": "geplant", "termin": "2026-11-02T14:00"}}, JETZT)
    assert b["stufe"] == "besichtigung" and b["text"] == "Besichtigung am 02.11. 14:00"
    assert vh.zustand(None, {"besichtigung": {"status": "laeuft", "termin": None}}, JETZT)["text"] == "Besichtigung läuft"
    assert vh.zustand(None, {"besichtigung": {"status": "geplant", "termin": None}}, JETZT)["text"] == "Besichtigung geplant, ohne Termin"
    # abgeschlossene Besichtigung oder nur eine Notiz: Lage ohne Stufe (Detail zeigt sie, das Dashboard nicht)
    fertig = vh.zustand("kontaktiert", {"besichtigung": {"status": "abgeschlossen", "termin": "2026-10-20T10:00"}}, JETZT)
    assert fertig["stufe"] is None and fertig["besichtigung"]["status"] == "abgeschlossen"
    assert vh.zustand("neu", {"notiz": _e("2026-10-30T10:00:00")}, JETZT)["stufe"] is None


@pytest.mark.parametrize("status", ["abgesagt", "uninteressant", "gekauft"])
def test_zustand_erledigt_ohne_stufe(status):
    """QA B1: beendete Vorgänge stehen nicht mehr unter „Ankauf in Arbeit“ – außer eine Besichtigung ist noch offen."""
    lage = {"kontakt_am": "2026-10-01T09:00:00", "vorbereitet": True, "antwort": _e("2026-10-02T09:00:00")}
    assert vh.zustand(status, lage, JETZT) is None                                         # ohne Notiz/Besichtigung gar keine Lage
    assert vh.zustand(status, {**lage, "notiz": _e("2026-10-03T09:00:00")}, JETZT)["stufe"] is None
    assert vh.zustand(status, {**lage, "besichtigung": {"status": "geplant", "termin": "2026-11-05T10:00"}}, JETZT)["stufe"] == "besichtigung"


def test_kurz_ohne_volltexte():
    """QA B3: Listen tragen keine Eintragstexte (Personendaten), nur Lage und Betrag."""
    k = vh.zustand("kontaktiert", {"kontakt_am": "2026-10-28T09:00:00", "antwort": _e("2026-10-29T18:00:00", 34500, "Herr Muster 0170 123"),
                                   "notiz": _e("2026-10-30T10:00:00", None, "Adresse Musterweg 1"), "eintraege": 2}, JETZT)
    kurz = vh.kurz(k)
    assert kurz["stufe"] == "antwort" and kurz["antwort_betrag"] == 34500 and kurz["eintraege"] == 2
    assert "Muster" not in repr(kurz) and vh.kurz(None) is None


# ---------------------------------------------------------------- 3. Schema v23 mit Altbestand
def test_migration_v23_additiv_mit_sicherung(tmp_path, monkeypatch):
    pfad = tmp_path / "alt.sqlite"
    with monkeypatch.context() as m:
        m.setattr(migrationen, "AKTUELLE_VERSION", 22)
        migrationen.migriere(pfad, tmp_path / "s")
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO anzeigen (id, titel, preis, status, notiz) VALUES ('alt1', 'Knaus', 40000, 'kontaktiert', 'Rückruf')")
    con.commit()
    vorher = con.execute("SELECT * FROM anzeigen").fetchall()
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == list(range(23, migrationen.AKTUELLE_VERSION + 1))
    assert [p for p in (tmp_path / "s").iterdir() if f"vor-v{migrationen.AKTUELLE_VERSION}" in p.name]
    con = sqlite3.connect(pfad)
    assert con.execute("SELECT * FROM anzeigen").fetchall() == vorher                    # Altbestand unverändert
    assert con.execute("SELECT COUNT(*) FROM verhandlung").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO verhandlung (anzeige_id, art, zeitpunkt) VALUES ('alt1', 'brief', 'z')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO verhandlung (anzeige_id, art, zeitpunkt, betrag) VALUES ('alt1', 'notiz', 'z', 0)")
    con.close()
    assert migrationen.migriere(pfad, tmp_path / "s") == []                                # idempotent


# ---------------------------------------------------------------- 4. Datenbank: Einträge, Lage, Datenschutz
@pytest.fixture
def drei(db, tmp_path):
    """p1 kontaktiert + Antwort, p2 Text kopiert, p3 kontaktiert + Besichtigung geplant, x1 ohne alles."""
    for i in ("p1", "p2", "p3", "x1"):
        db.speichere_treffer(treffer(i, ort=f"7017{ord(i[-1]) % 10} Stuttgart", km=80000 + 9000 * int(i[-1])), "Alkoven")
    db.setze_status("p1", "kontaktiert", text="Hallo p1")
    db.setze_status("p2", "vorbereitet", text="Hallo p2")
    db.setze_status("p3", "kontaktiert", text="Hallo p3")
    vh.eintragen(db, "p1", vh.pruefe({"art": "antwort", "text": "will 38.000, Herr <b>Muster</b> 0170 123", "betrag": 38000, "kanal": "telefon"}), None,
                 datetime.now() + timedelta(minutes=1))
    vh.eintragen(db, "p1", vh.pruefe({"art": "notiz", "text": "Rückruf Montag"}), None, datetime.now() + timedelta(minutes=2))
    TeamSpeicher(db, tmp_path / "fotos").besichtigung_anlegen("p3", {"fahrzeug": "Knaus"}, "2026-11-08T14:00", "Stuttgart", None, None)
    return db


def test_eintragen_verlauf_und_lage(cfg, drei):
    with pytest.raises(LookupError):
        vh.eintragen(drei, "gibtsnicht", vh.pruefe({"art": "notiz", "text": "x"}), None)
    v = vh.verlauf(drei, "p1")
    assert [x["art"] for x in v] == ["antwort", "notiz"] and v[0]["betrag"] == 38000 and v[0]["kanal"] == "telefon"
    j = vh.als_json(v[0], {})
    assert j["art_text"] == "Antwort des Verkäufers" and j["kanal_text"] == "Telefon" and j["von"] is None
    assert re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", j["zeit_text"])
    lage = vh.lage(drei)
    assert lage["p1"]["antwort"]["betrag"] == 38000 and lage["p1"]["notiz"]["text"] == "Rückruf Montag" and lage["p1"]["eintraege"] == 2
    assert lage["p2"]["vorbereitet"] is True and lage["p2"]["kontakt_am"] is None
    assert lage["p3"]["besichtigung"] == {"status": "geplant", "termin": "2026-11-08T14:00"} and "x1" not in lage
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, drei, BASIS)}
    assert (z["p1"]["kontakt"]["stufe"], z["p2"]["kontakt"]["stufe"], z["p3"]["kontakt"]["stufe"], z["x1"]["kontakt"]) == \
        ("antwort", "vorbereitet", "besichtigung", None)


def test_datenschutz_anonymisieren_und_frist(cfg, drei, tmp_path):
    inserat_anonymisieren(drei, tmp_path, "p1")
    assert [r["text"] for r in vh.verlauf(drei, "p1")] == [None, None]                    # Texte leer, Zeitpunkt/Betrag bleiben
    assert vh.verlauf(drei, "p1")[0]["betrag"] == 38000
    # nur ein Verhandlungstext trägt Personendaten → fällig nach Frist; ein junger Eintrag ist Aktivität
    drei.speichere_treffer(treffer("q1", ort="80331 München", km=150000), "Alkoven")
    alt = datetime.now() - timedelta(days=800)
    drei.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, status_am=NULL, kontaktiert_am=NULL, anschreiben_text=NULL, notiz=NULL WHERE id='q1'",
                     (alt.isoformat(timespec="seconds"),))
    drei.con.commit()
    vh.eintragen(drei, "q1", vh.pruefe({"art": "notiz", "text": "Name Erika"}), None, alt)
    assert "q1" in inserate_faellig(drei, 12)
    vh.eintragen(drei, "q1", vh.pruefe({"art": "antwort", "text": "meldet sich"}), None)
    assert "q1" not in inserate_faellig(drei, 12)
    # QA B2: nach dem Anonymisieren neu eingetragener Text wird nach Frist wieder fällig (und dann wieder geleert)
    inserat_anonymisieren(drei, tmp_path, "q1")
    drei.con.execute("DELETE FROM verhandlung WHERE anzeige_id='q1'")
    drei.con.commit()
    assert "q1" not in inserate_faellig(drei, 12)
    vh.eintragen(drei, "q1", vh.pruefe({"art": "notiz", "text": "Herr Muster 0170"}), None, alt)
    assert "q1" in inserate_faellig(drei, 12)
    inserat_anonymisieren(drei, tmp_path, "q1")
    assert "q1" not in inserate_faellig(drei, 12)


# ---------------------------------------------------------------- 5. API
def test_api_eintragen_lesen_felder(cfg, drei):
    srv = starte(cfg, drei)
    try:
        c = lokal(srv)
        s, d, _ = c("POST", "/api/verhandlung", {"id": "p3", "art": "antwort", "text": "Samstag passt", "kanal": "whatsapp"})
        assert s == 200 and d["ok"] and d["verlauf"][-1]["text"] == "Samstag passt" and d["verlauf"][-1]["kanal_text"] == "WhatsApp"
        assert c("POST", "/api/verhandlung", {"id": "p3", "art": "antwort", "text": ""})[0] == 400
        assert c("POST", "/api/verhandlung", {"id": "p3", "art": "notiz", "text": "x", "kanal": "telefon"})[0] == 400
        assert c("POST", "/api/verhandlung", {"id": "gibtsnicht", "art": "notiz", "text": "x"})[0] == 404
        assert c("GET", "/api/verhandlung/gibtsnicht")[0] == 404
        assert [x["art"] for x in c("GET", "/api/verhandlung/p1")[1]] == ["antwort", "notiz"]
        assert drei.status_von("p3") == "kontaktiert"                                   # ein Eintrag ändert keinen Status
        liste = {f["id"]: f for f in c("GET", "/api/fahrzeuge?filter=alle")[1]}
        assert liste["p1"]["kontakt"]["stufe"] == "antwort" and liste["p3"]["kontakt"]["stufe"] == "besichtigung"
        assert "Muster" not in repr(liste["p1"]) and liste["p1"]["kontakt"]["antwort_betrag"] == 38000      # keine Volltexte in der Liste (B3)
        assert c("POST", "/api/status", {"id": "p1", "status": "abgesagt"})[0] == 200
        assert next(f for f in c("GET", "/api/fahrzeuge?filter=alle")[1] if f["id"] == "p1")["kontakt"]["stufe"] is None     # B1
        detail = c("GET", "/api/fahrzeug/p1")[1]
        assert [x["art"] for x in detail["verhandlung"]] == ["antwort", "notiz"]
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- 6. Oberflächen
def test_desktop_dashboard_karte_detail(cfg, drei):
    zeilen = bewerte_alle(cfg, drei, BASIS)
    html = render_html(cfg, zeilen, BASIS, app={"token": "t"})[0]
    bereich = re.search(r'<section class="kasten" id="ankauf-arbeit".*?</section>', html, re.S).group(0)
    assert re.findall(r'data-pipeline="(\w+)" data-stufe="(\w+)"', bereich) == [("p3", "besichtigung"), ("p1", "antwort"), ("p2", "vorbereitet")]
    assert 'data-stufe-zaehl="besichtigung">Besichtigung: 1' in bereich and "Besichtigung am 08.11. 14:00" in bereich
    assert "Rückruf Montag" in bereich and 'data-pipeline-oeffnen="p1"' in bereich             # jüngster Eintrag (Notiz nach der Antwort)
    karte = re.search(r'<article[^>]*data-id="p1".*?</article>', html, re.S).group(0)
    assert "data-kontakt-tag" in karte and "↩ Antwort" in karte
    detail = re.search(r'<section id="dp1".*?</section>', html, re.S).group(0)
    assert "data-kontakt-detail" in detail and "data-verhandlung" in detail and "data-vh-eintragen" in detail and 'value="telefon"' in detail
    vh.eintragen(drei, "p2", vh.pruefe({"art": "notiz", "text": "<img src=x onerror=alert(1)>"}), None, datetime.now() + timedelta(minutes=5))
    html = render_html(cfg, bewerte_alle(cfg, drei, BASIS), BASIS, app={"token": "t"})[0]
    bereich = re.search(r'<section class="kasten" id="ankauf-arbeit".*?</section>', html, re.S).group(0)
    assert "&lt;img src=x onerror=alert(1)&gt;" in bereich and "<img src=x" not in html             # Texte escaped (B4)
    statisch = render_html(cfg, zeilen, BASIS)[0]
    assert 'id="ankauf-arbeit"' in statisch and "<div class=\"kasten\" data-verhandlung>" not in statisch   # Eintragen nur in der App
    assert "Rückruf Montag" not in statisch and "Letzte Antwort" not in statisch       # Bericht auf der Platte ohne Eintragstexte (B8)
    assert "{#" not in (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8").split("<style>")[1].split("</style>")[0]   # kein Jinja-Kommentar im CSS


def test_desktop_ohne_kontakte_kein_bereich(cfg, db):
    db.speichere_treffer(treffer("x1"), "Alkoven")
    assert 'id="ankauf-arbeit"' not in render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)[0]


def test_handy_app_statisch():
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    for teil in ("function kontaktZeile", "function verhandlungKarte", 'data-aktion="vh-eintragen"', '"/api/verhandlung"', "kontaktZeile(f) + preisZeile(f)",
                 "kontaktZeilen(f) + verhandlungKarte(f)", "esc(x.text)", "esc(k.text)"):
        assert teil in js, teil
    css = (STATIC / "mobil.css").read_text(encoding="utf-8")
    assert ".kontaktlage.wartet" in css and ".vh{" in css
    assert int(re.search(r"wm-scout-(\d+)", (STATIC / "sw.js").read_text(encoding="utf-8")).group(1)) >= 21
