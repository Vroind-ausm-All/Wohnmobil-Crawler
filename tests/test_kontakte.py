"""P3-06 (ADR-044): Kontakte als Ereignisse – vorbereitet (Text kopiert) → bestätigt (gesendet), mit Kanal und Nutzer.

Geprüft: Ereignisse je Statuswechsel und Nachfassen (Einzelplatz und Team), Ersetzen eines erneut kopierten Textes, Bestätigen, keine Ereignisse bei
Konflikt oder Fehler, Verlauf über das ganze Fahrzeug, API (Kanal, Bestätigen, Rechte, Audit), Anonymisierung, Oberfläche und Schema 15 gegen
Altbestände (Betreiberfrage F7). Alles offline.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import json
import re
import sqlite3

import pytest

from tests.daten import BASIS
from tests.test_anbieter import baue_v13
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_migration import pruefsumme, versionen
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from wmscout import kontakte as ko
from wmscout import migrationen
from wmscout.audit import einordnen
from wmscout.bearbeitung import BearbeitungsKonflikt
from wmscout.datenrechte import ERSATZ, inserat_anonymisieren
from wmscout.haendler import HaendlerSpeicher
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.sicherung import sicherungen
from wmscout.team import TeamSpeicher

STATIC = BASIS / "wmscout" / "web" / "static"


def zeilen(db, ad_id=None):
    db.con.commit()
    sql, werte = "SELECT * FROM kontakte", ()
    if ad_id:
        sql, werte = sql + " WHERE anzeige_id=?", (ad_id,)
    return [dict(r) for r in db.con.execute(sql + " ORDER BY id", werte)]


def eine_id(db):
    return db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 1").fetchone()[0]


# ---------------------------------------------------------------- 1. Begriffe
def test_kanal_pruefen():
    assert ko.pruefe_kanal(None) is None and ko.pruefe_kanal("") is None and ko.pruefe_kanal("telefon") == "telefon"
    for falsch in ("fax", 1, ["email"], True):
        with pytest.raises(ValueError):
            ko.pruefe_kanal(falsch)


def test_anzeigeform():
    z = {"id": 1, "anzeige_id": "a", "art": "nachfassen", "kanal": "email", "betrag": 900, "nutzer_id": 2, "vorbereitet_am": "2026-10-20T10:05:00",
         "bestaetigt_am": None, "bestaetigt_von": None, "verworfen_am": None, "herkunft": "app", "text": "x"}
    j = ko.als_json(z, {2: "Ben"})
    assert (j["art_text"], j["kanal_text"], j["bestaetigt"], j["vorbereitet_von"], j["zeit_text"]) == ("Nachfassen", "E-Mail", False, "Ben", "20.10.2026 10:05")
    assert j["zustand"].startswith("Text kopiert")
    alt = ko.als_json({**z, "bestaetigt_am": "2026-01-05T09:00:00", "herkunft": "altbestand"})
    assert alt["bestaetigt"] and "vor der Bestätigungspflicht" in alt["zustand"] and alt["vorbereitet_von"] is None
    weg = ko.als_json({**z, "verworfen_am": "2026-10-21T08:00:00"})
    assert weg["verworfen"] and weg["zustand"] == "verworfen (nicht gesendet)" and not weg["bestaetigt"]


# ---------------------------------------------------------------- 2. Einzelplatz
def test_text_kopiert_dann_gesendet(db, importiert):
    ad = eine_id(db)
    assert db.setze_status(ad, "vorbereitet", text="Hallo, Angebot 20.000 €", betrag=20000)
    assert db.setze_status(ad, "vorbereitet", text="Hallo, Angebot 21.000 €", betrag=21000)        # erneut kopiert: ersetzt
    (z,) = zeilen(db, ad)
    assert (z["art"], z["kanal"], z["text"], z["betrag"], z["bestaetigt_am"], z["herkunft"], z["nutzer_id"]) == (
        "anschreiben", "plattform", "Hallo, Angebot 21.000 €", 21000, None, "app", None) and z["vorbereitet_am"]
    assert db.setze_status(ad, "kontaktiert")
    (z,) = zeilen(db, ad)
    assert z["bestaetigt_am"] and z["kanal"] == "plattform" and z["text"] == "Hallo, Angebot 21.000 €"
    db.setze_status(ad, "kontaktiert")                                                               # nochmal: kein neues Ereignis
    db.setze_status(ad, "verhandlung")
    assert len(zeilen(db, ad)) == 1


def test_direkt_kontaktiert_mit_und_ohne_text_und_kanal(db, importiert):
    a, b, c = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 3")]
    db.setze_status(a, "kontaktiert")
    db.setze_status(b, "kontaktiert", text="Hallo", betrag=15000)
    db.setze_status(c, "kontaktiert", kanal="telefon")
    assert [(z["kanal"], z["text"], bool(z["bestaetigt_am"]), z["vorbereitet_am"]) for z in zeilen(db)] == [
        ("unbekannt", None, True, None), ("plattform", "Hallo", True, None), ("telefon", None, True, None)]


def test_neu_setzt_zurueck_ereignisse_bleiben_und_neuer_kontakt_zaehlt(db, importiert):
    ad = eine_id(db)
    db.setze_status(ad, "vorbereitet", text="Erst")
    db.setze_status(ad, "kontaktiert", kanal="email")
    db.setze_status(ad, "neu")
    assert len(zeilen(db, ad)) == 1 and zeilen(db, ad)[0]["kanal"] == "email"
    db.setze_status(ad, "vorbereitet", text="Zweit")
    db.setze_status(ad, "kontaktiert")
    assert [(z["text"], bool(z["bestaetigt_am"])) for z in zeilen(db, ad)] == [("Erst", True), ("Zweit", True)]


def offene(db, ad):
    return [(z["art"], z["text"], bool(z["bestaetigt_am"]), bool(z["verworfen_am"])) for z in zeilen(db, ad)]


def test_rueckgaengig_verwirft_den_kopierten_text(db, importiert):
    """QA B3: „Text kopiert“ → Rückgängig („neu“) → später direkt „kontaktiert“: der verworfene Text wird nicht bestätigt."""
    ad = eine_id(db)
    db.setze_status(ad, "vorbereitet", text="Alt-Text")
    db.nachgefasst(ad, "Alt-Nachfassen")
    db.setze_status(ad, "neu")
    assert offene(db, ad) == [("anschreiben", "Alt-Text", False, True), ("nachfassen", "Alt-Nachfassen", False, True)]
    db.setze_status(ad, "kontaktiert")
    assert offene(db, ad)[-1] == ("anschreiben", None, True, False) and len(zeilen(db, ad)) == 3
    assert db.bestaetige_kontakt(zeilen(db, ad)[1]["id"], None) is False                          # verworfen: nicht mehr bestätigbar


def test_gesendet_bestaetigt_das_letzte_und_verwirft_aeltere(db, importiert):
    """QA B2: Anschreiben kopiert, dann Nachfassen kopiert, dann „gesendet ✓“ – nur eines wurde gesendet."""
    ad = eine_id(db)
    db.setze_status(ad, "vorbereitet", text="Brief")
    db.nachgefasst(ad, "Nachfassen")
    db.setze_status(ad, "kontaktiert")
    assert offene(db, ad) == [("anschreiben", "Brief", False, True), ("nachfassen", "Nachfassen", True, False)]


def test_neuer_brief_ueberschreibt_kein_nachfassen(db, importiert):
    """QA B4: kontaktiert → Nachfassen offen → „kontaktiert“ mit neuem Text: neues Anschreiben, das Nachfassen bleibt mit seinem Text."""
    ad = eine_id(db)
    db.setze_status(ad, "kontaktiert", text="Erster Brief")
    db.nachgefasst(ad, "Noch da?")
    db.setze_status(ad, "kontaktiert", text="Neuer Brief")
    assert offene(db, ad) == [("anschreiben", "Erster Brief", True, False), ("nachfassen", "Noch da?", False, True),
                              ("anschreiben", "Neuer Brief", True, False)]


def test_bestaetigen_in_der_app_macht_altbestand_zu_app(db, importiert):
    """QA B5: eine offene Altbestand-Zeile, die heute bestätigt wird, gilt als in der App bestätigt."""
    ad = eine_id(db)
    db.con.execute("INSERT INTO kontakte (anzeige_id, art, kanal, vorbereitet_am, herkunft) VALUES (?, 'anschreiben', 'plattform', "
                   "'2026-10-01T10:00:00', 'altbestand')", (ad,))
    db.con.commit()
    db.setze_status(ad, "kontaktiert")
    (z,) = zeilen(db, ad)
    assert z["herkunft"] == "app" and z["bestaetigt_am"] and ko.als_json(z)["zustand"] == "gesendet"


def test_andere_status_und_unbekannte_anzeige_ohne_ereignis(db, importiert):
    ad = eine_id(db)
    for s in ("verhandlung", "besichtigung", "abgesagt", "neu"):
        db.setze_status(ad, s)
    assert zeilen(db) == []
    assert db.setze_status("gibtsnicht", "vorbereitet", text="x") is False and zeilen(db) == []
    assert db.nachgefasst("gibtsnicht", "x") is False and zeilen(db) == []


def test_nachfassen_vorbereitet_ersetzt_bestaetigt(db, importiert):
    ad = eine_id(db)
    db.setze_status(ad, "kontaktiert", text="Hallo")
    db.nachgefasst(ad, "Noch Interesse?", 19000)
    db.nachgefasst(ad, "Noch Interesse? (2)", 19500, kanal="whatsapp")
    erst, nf = zeilen(db, ad)
    assert (nf["art"], nf["text"], nf["betrag"], nf["kanal"], nf["bestaetigt_am"]) == ("nachfassen", "Noch Interesse? (2)", 19500, "whatsapp", None)
    assert db.bestaetige_kontakt(nf["id"], None, "telefon")
    nf = zeilen(db, ad)[1]
    assert nf["bestaetigt_am"] and nf["kanal"] == "telefon"
    vorher = nf["bestaetigt_am"]
    assert db.bestaetige_kontakt(nf["id"], None, "email") and zeilen(db, ad)[1]["bestaetigt_am"] == vorher    # zweimal: unverändert
    assert zeilen(db, ad)[1]["kanal"] == "telefon" and db.bestaetige_kontakt(999999, None) is False
    db.nachgefasst(ad, "Drittes")
    assert len(zeilen(db, ad)) == 3 and erst["bestaetigt_am"]


def test_fehler_im_ereignis_rollt_den_status_zurueck(db, importiert, monkeypatch):
    ad = eine_id(db)

    def kaputt(*a, **k):
        raise RuntimeError("Absicht")

    monkeypatch.setattr(db, "_kontakt_ereignis", kaputt)
    with pytest.raises(RuntimeError):
        db.setze_status(ad, "vorbereitet", text="x")
    assert db.status_von(ad) == "neu" and zeilen(db) == []
    monkeypatch.setattr(db, "_kontakt_vorbereiten", kaputt)
    with pytest.raises(RuntimeError):
        db.nachgefasst(ad, "x")
    assert db.con.execute("SELECT nachfass_anzahl FROM anzeigen WHERE id=?", (ad,)).fetchone()[0] in (0, None)


# ---------------------------------------------------------------- 3. Team
@pytest.fixture
def team(db, tmp_path):
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.ids = {n: t.nutzer_anlegen(n, "sicher1234", "inhaber" if n == "Anna" else "mitarbeiter") for n in ("Anna", "Ben", "Carl")}
    db.con.commit()
    return t


def test_team_nutzer_und_konflikt_ohne_ereignis(db, importiert, team):
    ad, ben, carl = eine_id(db), team.ids["Ben"], team.ids["Carl"]
    db.setze_status(ad, "vorbereitet", text="Ben schreibt", nutzer_id=ben)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(ad, "vorbereitet", text="Carl auch", nutzer_id=carl)
    with pytest.raises(BearbeitungsKonflikt):
        db.nachgefasst(ad, "Carl fasst nach", nutzer_id=carl)
    (z,) = zeilen(db, ad)
    assert (z["nutzer_id"], z["text"]) == (ben, "Ben schreibt")
    db.setze_status(ad, "kontaktiert", nutzer_id=ben)
    (z,) = zeilen(db, ad)
    assert (z["nutzer_id"], z["bestaetigt_von"]) == (ben, ben) and z["bestaetigt_am"]


def test_verlauf_ueber_das_ganze_fahrzeug(db, importiert):
    a, b = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 2")]
    db.setze_status(a, "kontaktiert", text="an A")
    db.setze_status(b, "vorbereitet", text="an B")
    assert [z["text"] for z in db.kontakte_zu(a)] == ["an A"]
    fa = db.fahrzeug_id_zu(a)
    db.con.execute("UPDATE inserate SET fahrzeug_id=? WHERE anzeigen_id=?", (fa, b))                # wie nach bestätigter Dublette
    db.con.commit()
    assert {z["text"] for z in db.kontakte_zu(a)} == {"an A", "an B"} == {z["text"] for z in db.kontakte_zu(b)}


# ---------------------------------------------------------------- 4. API
def test_api_kanal_verlauf_bestaetigen(server, db, cfg, importiert):
    c = lokal(server)
    ad = c("GET", "/api/fahrzeuge?filter=alle")[1][0]["id"]
    assert c("POST", "/api/status", {"id": ad, "status": "vorbereitet", "text": "Hallo", "kanal": "fax"})[0] == 400
    assert db.status_von(ad) == "neu" and zeilen(db) == []
    assert c("POST", "/api/status", {"id": ad, "status": "vorbereitet", "text": "Hallo", "betrag": 20000})[0] == 200
    k = c("GET", f"/api/fahrzeug/{ad}")[1]["kontakte"]
    assert len(k) == 1 and not k[0]["bestaetigt"] and k[0]["kanal"] == "plattform"
    assert c("POST", "/api/status", {"id": ad, "status": "kontaktiert", "kanal": "email"})[0] == 200
    k = c("GET", f"/api/kontakte/{ad}")[1]
    assert k[0]["bestaetigt"] and k[0]["kanal_text"] == "E-Mail" and k[0]["vorbereitet_von"] is None
    assert c("POST", f"/api/kontakt/{k[0]['id']}/bestaetigen", {})[0] == 409                         # Anschreiben: über „gesendet ✓“
    assert c("POST", "/api/nachgefasst", {"id": ad, "text": "Noch da?", "kanal": "whatsapp"})[0] == 200
    nf = c("GET", f"/api/kontakte/{ad}")[1][1]
    assert (nf["art"], nf["kanal"], nf["bestaetigt"]) == ("nachfassen", "whatsapp", False)
    assert c("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {"kanal": "unsinn"})[0] == 400
    s, d, _ = c("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {})
    assert s == 200 and d["kontakt"]["bestaetigt"] and d["kontakt"]["kanal"] == "whatsapp"
    assert c("POST", "/api/kontakt/999999/bestaetigen", {})[0] == 404
    assert c("GET", "/api/kontakte/gibtsnicht")[0] == 404
    assert c("POST", "/api/nachgefasst", {"id": ad, "text": "x", "kanal": 5})[0] == 400
    assert einordnen("POST", f"/api/kontakt/{nf['id']}/bestaetigen") == ("aendern", f"kontakt:{nf['id']}")


def test_api_team_rechte_namen_audit(server, db, cfg, importiert, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    for n, r in (("Anna", "inhaber"), ("Ben", "mitarbeiter"), ("Carl", "mitarbeiter")):
        team.nutzer_anlegen(n, "sicher1234", r)
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    ben, carl, anna = anmelden(server, "Ben"), anmelden(server, "Carl"), anmelden(server, "Anna")
    ad = ben("GET", "/api/fahrzeuge?filter=alle")[1][0]["id"]
    assert ben("POST", "/api/status", {"id": ad, "status": "kontaktiert", "text": "Hallo"})[0] == 200
    assert ben("POST", "/api/nachgefasst", {"id": ad, "text": "Noch da?"})[0] == 200
    nf = ben("GET", f"/api/kontakte/{ad}")[1][1]
    assert nf["vorbereitet_von"] == "Ben"
    assert carl("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {})[0] == 403
    assert ben("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {}, token=False)[0] == 403
    assert anna("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {})[0] == 200
    assert anna("GET", f"/api/kontakte/{ad}")[1][1]["bestaetigt_von"] == "Anna"
    hugo = anmelden(server, "Hugo")
    assert hugo("GET", f"/api/kontakte/{ad}")[0] == 403 and hugo("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {})[0] == 403
    db.con.commit()
    eintraege = [tuple(r) for r in db.con.execute("SELECT nutzer, objekt, status FROM audit WHERE pfad LIKE '/api/kontakt/%'")]
    assert ("Anna", f"kontakt:{nf['id']}", 200) in eintraege and ("Carl", f"kontakt:{nf['id']}", 403) in eintraege


def test_api_erstes_nachfassen_bestaetigt_ueber_den_status(server, db, cfg, importiert, tmp_path):
    """QA B1: Nachfassen an einem noch nicht kontaktierten Inserat → „gesendet ✓“ macht es zum ersten Kontakt (Status, Zeitpunkt, Team)."""
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    ben_id = team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    team.nutzer_anlegen("Carl", "sicher1234", "mitarbeiter")
    db.con.commit()
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    ad = ben("GET", "/api/fahrzeuge?filter=alle")[1][0]["id"]
    assert ben("POST", "/api/nachgefasst", {"id": ad, "text": "Noch zu haben?"})[0] == 200
    assert db.status_von(ad) == "vorbereitet"
    nf = ben("GET", f"/api/kontakte/{ad}")[1][0]
    assert ben("POST", f"/api/kontakt/{nf['id']}/bestaetigen", {"kanal": "telefon"})[0] == 200
    db.con.commit()
    z = db.con.execute("SELECT status, kontaktiert_am FROM anzeigen WHERE id=?", (ad,)).fetchone()
    assert z["status"] == "kontaktiert" and z["kontaktiert_am"]
    assert db.con.execute("SELECT kontaktiert_von FROM bearbeitung WHERE anzeige_id=?", (ad,)).fetchone()[0] == ben_id
    (k,) = zeilen(db, ad)
    assert (k["art"], k["kanal"], k["bestaetigt_von"], bool(k["bestaetigt_am"])) == ("nachfassen", "telefon", ben_id, True)
    # ein zweites Inserat, das Carl nur kopiert hat; Ben hält es nicht – Carl bestätigt selbst, Ben darf es nicht
    ad2 = [f["id"] for f in carl("GET", "/api/fahrzeuge?filter=alle")[1] if f["id"] != ad][0]
    assert carl("POST", "/api/nachgefasst", {"id": ad2, "text": "Hallo?"})[0] == 200
    nf2 = carl("GET", f"/api/kontakte/{ad2}")[1][0]
    assert ben("POST", f"/api/kontakt/{nf2['id']}/bestaetigen", {})[0] == 403
    assert carl("POST", "/api/status", {"id": ad2, "status": "neu"})[0] == 200                       # Rückgängig: verworfen
    assert carl("POST", f"/api/kontakt/{nf2['id']}/bestaetigen", {})[0] == 409


# ---------------------------------------------------------------- 5. Anonymisierung
def test_anonymisierung_entfernt_den_namen_aus_dem_verlauf(cfg, db, importiert, tmp_path):
    ad = eine_id(db)
    db.con.execute("UPDATE anzeigen SET details_json=? WHERE id=?", (json.dumps({"verkaeufer_name": "Max Muster"}), ad))
    db.con.commit()
    db.setze_status(ad, "kontaktiert", text="Hallo Max Muster, ich biete 20.000 €")
    db.nachgefasst(ad, "Hallo Max Muster, noch da?")
    inserat_anonymisieren(db, tmp_path, ad)
    texte = [z["text"] for z in zeilen(db, ad)]
    assert texte == [f"Hallo {ERSATZ}, ich biete 20.000 €", f"Hallo {ERSATZ}, noch da?"] and all("Muster" not in t for t in texte)
    assert all(z["bestaetigt_am"] or z["vorbereitet_am"] for z in zeilen(db, ad))                    # Zeitpunkte bleiben


# ---------------------------------------------------------------- 6. Oberfläche
def test_oberflaeche_statisch():
    js, html = (STATIC / "mobil.js").read_text(encoding="utf-8"), (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "function kontaktZeilen" in js and "esc(x.zustand)" in js and "esc(x.kanal_text)" in js and "/bestaetigen" in js
    assert "function ladeKontakte" in html and "p.textContent = x.art_text" in html and "innerHTML" not in html.split("function ladeKontakte")[1][:1500]
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"var VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 12 and "12: Kontaktverlauf" in sw


# ---------------------------------------------------------------- 7. Schema 15 (F7: Altbestand konservativ übernommen)
def bis_15(monkeypatch):
    """Schritt 15 ist hier der letzte bekannte Schritt: die Tests prüfen ihn so, wie er zu seiner Zeit lief."""
    _alt_schritte(monkeypatch, 15)


def baue_v14(pfad, monkeypatch, tmp_path):
    baue_v13(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 14)
        assert migriere(pfad, tmp_path / "stand14") == [14]
    assert lese_version(pfad) == 14


def mit_kontakten(pfad):
    """Altbestand: bestätigter Kontakt mit Bearbeiter, offenes „Text kopiert“, Nachfassen, ein unberührtes Inserat."""
    con = sqlite3.connect(pfad)
    zeilen_ = [("c1", "kontaktiert", "2026-10-01T10:00:00", None, None, 22000), ("c2", "vorbereitet", None, "2026-10-02T11:00:00", None, 18000),
               ("c3", "verhandlung", "2026-09-01T09:00:00", "2026-09-03T09:00:00", "2026-09-10T08:00:00", None), ("c4", "neu", None, None, None, None)]
    for i, status, kontaktiert, status_am, nachgefasst, betrag in zeilen_:
        con.execute("INSERT INTO anzeigen (id, url, titel, status, kontaktiert_am, status_am, nachgefasst_am, angebot_betrag, zuletzt_gesehen) "
                    "VALUES (?, ?, 'Alt', ?, ?, ?, ?, ?, '2026-10-05T10:00:00')", (i, f"https://x.invalid/{i}", status, kontaktiert, status_am,
                                                                                   nachgefasst, betrag))
    con.execute("INSERT INTO bearbeitung (anzeige_id, bearbeiter_id, uebernommen_am, kontaktiert_von, kontaktiert_am) "
                "VALUES ('c1', 1, '2026-10-01T09:00:00', 1, '2026-10-01T10:00:00')")
    con.execute("INSERT INTO bearbeitung (anzeige_id, bearbeiter_id, uebernommen_am) VALUES ('c2', 2, '2026-10-02T10:00:00')")
    con.commit()
    con.close()


def test_rueckfuellung_altbestand(tmp_path, monkeypatch):
    bis_15(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v14(pfad, monkeypatch, tmp_path)
    mit_kontakten(pfad)
    assert migriere(pfad, ziel) == [15]
    k = {(r[0], r[1]): r[2:] for r in _sql(pfad, "SELECT anzeige_id, art, kanal, betrag, nutzer_id, vorbereitet_am, bestaetigt_am, bestaetigt_von, "
                                                  "herkunft, text FROM kontakte WHERE anzeige_id LIKE 'c%'")}
    assert k == {
        ("c1", "anschreiben"): ("unbekannt", 22000, 1, None, "2026-10-01T10:00:00", 1, "altbestand", None),
        ("c2", "anschreiben"): ("plattform", 18000, 2, "2026-10-02T11:00:00", None, None, "altbestand", None),
        ("c3", "anschreiben"): ("unbekannt", None, None, None, "2026-09-01T09:00:00", None, "altbestand", None),
        ("c3", "nachfassen"): ("plattform", None, None, "2026-09-10T08:00:00", None, None, "altbestand", None)}
    # jede Anzeige mit Kontaktzeitpunkt hat genau eine bestätigte Zeile (auch k1 & Co. aus dem Bestand von baue_v10)
    assert _sql(pfad, "SELECT COUNT(*) FROM anzeigen WHERE COALESCE(kontaktiert_am, '') != ''") == \
        _sql(pfad, "SELECT COUNT(*) FROM kontakte WHERE bestaetigt_am IS NOT NULL")


@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v14"])
def test_migration_auf_15_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_15(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v14":
        baue_v14(pfad, monkeypatch, tmp_path)
        mit_kontakten(pfad)
    else:
        baue(art, pfad, monkeypatch)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    erledigt = migriere(pfad, ziel)
    assert erledigt[-1] == 15 and lese_version(pfad) == 15 and versionen(pfad)[-1] == 15
    neue = {t: v_ for t, v_ in vorher.items() if t != "fahrzeuge"}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue
    assert _sql(pfad, "SELECT COUNT(*) FROM kontakte WHERE herkunft != 'altbestand'") == [(0,)]
    if art == "v2":                                                                                   # Altbestand mit Kontaktzeitpunkt
        assert _sql(pfad, "SELECT anzeige_id, bestaetigt_am, betrag FROM kontakte WHERE art='anschreiben'") == [("1", "2026-01-05T09:00:00", 36000)]
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)] and _sql(pfad, "PRAGMA foreign_key_check") == []
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v15" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_15_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_15(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v14(pfad, monkeypatch, tmp_path)
    mit_kontakten(pfad)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    stand = _abbild(pfad)
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_15(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _abbild(pfad) == stand


def test_fehler_im_schritt_15_rollt_zurueck_dann_gelingt_es(tmp_path, monkeypatch):
    bis_15(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v14(pfad, monkeypatch, tmp_path)
    mit_kontakten(pfad)
    vorher, echt = _abbild(pfad), migrationen._schritt_15

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 15, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 14 and _abbild(pfad) == vorher and not _sql(pfad, "SELECT 1 FROM sqlite_master WHERE name='kontakte'")
    monkeypatch.setitem(migrationen.SCHRITTE, 15, echt)
    assert migriere(pfad, ziel) == [15]


def test_neue_datenbank_hat_die_tabelle_und_indizes(db):
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 15
    namen = {r[0] for r in db.con.execute("SELECT name FROM sqlite_master")}
    assert {"kontakte", "idx_kontakte_anzeige", "idx_kontakte_bestaetigt"} <= namen
    plan = " | ".join(r["detail"] for r in db.con.execute("EXPLAIN QUERY PLAN SELECT * FROM kontakte WHERE anzeige_id=? ORDER BY id", ("x",)))
    assert "idx_kontakte_anzeige" in plan, plan
