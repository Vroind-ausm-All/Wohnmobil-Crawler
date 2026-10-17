"""Team (T1), Korrekturrunde 2 nach QA-Runde 2: Besichtiger-Ausnahme nicht per Selbsteintragung, Erzwingen wirkt wirklich und wird nur bei
echter Änderung protokolliert, Besichtigung/Abschluss in EINER Transaktion, Seitenimport verwirft den Dubletten-Zwischenspeicher,
deaktivierte Kollegen blockieren Dubletten nicht, Kommandozeile beachtet Dubletten."""
from __future__ import annotations

import sqlite3

import pytest

from tests.daten import such_html
from tests.test_handy import Client
from tests.test_seitenimport import detailseite
from tests.test_team_bearbeitung import NEUN, anmelden, anzeige_ids, bearbeitung, dublette_herstellen, ids_der_liste, starte
from tests.test_team_korrektur import mit_dora, status_befehl, status_von
from wmscout.bearbeitung import BearbeitungsKonflikt
from wmscout.bewertung.auswertung import dubletten_ids
from wmscout.datenbank import Datenbank
from wmscout.team import TeamSpeicher

@pytest.fixture
def team(db, tmp_path):
    t = TeamSpeicher(db, tmp_path / "fotos")
    t.ids = {n: t.nutzer_anlegen(n, "sicher1234", "inhaber" if n == "Anna" else "mitarbeiter") for n in ("Anna", "Ben", "Carl")}
    return t


@pytest.fixture
def server(cfg, db, importiert):
    srv = starte(cfg, db)
    yield srv
    srv.shutdown()
    srv.server_close()


BASIS_DATEN = {"fahrzeug": "Testmobil", "titel": "Testmobil", "url": "https://example.invalid/x", "ort": "Stuttgart", "angebot": 20000,
               "preis": 25000, "max_ek": 22000}
PNG = "data:image/png;base64,iVBORw0KGgo="


def altbestand_besichtigung(team, ad_id, zustaendig=None):
    """Besichtigung ohne Zuständigen – wie vor der Team-Aktivierung angelegt (Einzelplatz)."""
    return team.besichtigung_anlegen(ad_id, dict(BASIS_DATEN), None, None, zustaendig, None)


def besichtigung_zustaendig(db, bid):
    return db.con.execute("SELECT zustaendig_id FROM besichtigungen WHERE id=?", (bid,)).fetchone()[0]


# ======================================================================= Q-H1: Besichtiger-Ausnahme
def test_http_mitarbeiter_kann_sich_auf_fremdem_inserat_nicht_als_besichtiger_eintragen(server, team, db):
    """QA besichtiger.py: Carl trägt sich über „planen“ bei einer Besichtigung ohne Zuständigen auf Bens Fahrzeug ein und setzt es auf „gekauft“."""
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    x, y = ids_der_liste(ben, "alle", n=2)
    ci, bi, ai = team.ids["Carl"], team.ids["Ben"], team.ids["Anna"]
    assert ben("POST", "/api/status", {"id": x, "status": "verhandlung"})[0] == 200
    bid = altbestand_besichtigung(team, x)                                              # NULL-Zuständiger, Ben ist Bearbeiter von x
    assert besichtigung_zustaendig(db, bid) is None
    stand = (status_von(db, x), bearbeitung(db, x))

    # Lesen darf Carl, Schreiben nicht – auch nicht den Zuständigen einsetzen (leer, er selbst oder ein Dritter)
    s, voll, _ = carl("GET", f"/api/besichtigung/{bid}")
    assert s == 200 and voll["darf_bearbeiten"] is False
    for daten in ({"termin": None}, {"zustaendig_id": ci}, {"zustaendig_id": bi}):
        s, antwort, _ = carl("POST", f"/api/besichtigung/{bid}/planen", daten)
        assert s == 403 and antwort["grund"] == "recht", daten
    assert carl("POST", f"/api/besichtigung/{bid}/speichern", {"daten": {}})[0] == 403
    assert carl("POST", f"/api/besichtigung/{bid}/foto", {"bild": "data:image/jpeg;base64,/9j/4A=="})[0] == 403
    ab = {"entscheidung": "gekauft", "endpreis": 1000, "begruendung_unvollstaendig": "x", "unterschrift_verkaeufer": PNG,
          "unterschrift_ankaeufer": PNG}
    for entscheidung in (ab, {"entscheidung": "abgelehnt"}, {"entscheidung": "offen"}, {"entscheidung": "abgebrochen"}):
        assert carl("POST", f"/api/besichtigung/{bid}/abschluss", entscheidung)[0] == 403, entscheidung
    assert besichtigung_zustaendig(db, bid) is None and (status_von(db, x), bearbeitung(db, x)) == stand
    assert team.besichtigung(bid)["status"] == "geplant"

    # Der Bearbeiter (Ben) darf: leere Angabe übernimmt die offene Zuständigkeit, dann reicht er sie an Carl weiter
    s, b, _ = ben("POST", f"/api/besichtigung/{bid}/planen", {"termin": "2026-11-01T10:00"})
    assert s == 200 and b["zustaendig"]["id"] == bi and b["darf_bearbeiten"] is True
    s, b, _ = ben("POST", f"/api/besichtigung/{bid}/planen", {"zustaendig_id": ci})
    assert s == 200 and b["zustaendig"]["id"] == ci
    assert ben("POST", f"/api/besichtigung/{bid}/planen", {"termin": "2026-11-02T10:00"})[1]["zustaendig"]["id"] == ci      # leer = unverändert
    # jetzt ist Carl legitim eingetragen: bearbeiten ja, aber weiterreichen/zurückholen nicht
    assert carl("GET", f"/api/besichtigung/{bid}")[1]["darf_bearbeiten"] is True
    assert carl("POST", f"/api/besichtigung/{bid}/planen", {"termin": "2026-11-03T10:00"})[1]["zustaendig"]["id"] == ci
    assert carl("POST", f"/api/besichtigung/{bid}/planen", {"zustaendig_id": team.ids["Anna"]})[0] == 403
    assert besichtigung_zustaendig(db, bid) == ci
    # die Ausnahme: der eingetragene Besichtiger setzt den Status des fremd gehaltenen Inserats, ohne die Bearbeitung zu übernehmen
    s, _, _ = carl("POST", f"/api/besichtigung/{bid}/abschluss", {"entscheidung": "abgelehnt"})
    assert s == 200 and status_von(db, x) == "abgesagt" and bearbeitung(db, x)[0] == bi

    # Inhaber darf jederzeit zuweisen
    bid2 = altbestand_besichtigung(team, y)
    assert anna("POST", f"/api/besichtigung/{bid2}/planen", {"zustaendig_id": ci})[1]["zustaendig"]["id"] == ci
    bid3 = altbestand_besichtigung(team, y)
    assert anna("POST", f"/api/besichtigung/{bid3}/planen", {})[1]["zustaendig"]["id"] == ai                # offene Zuständigkeit: Aufrufer


def test_http_besichtigung_ohne_zustaendigen_auf_freiem_inserat_nur_fuer_bearbeiter(server, team, db):
    """Auch ein freies Inserat reicht nicht: Wer sich eintragen will, muss das Inserat zuerst übernehmen (sonst könnte er später
    auf dem Inserat des Kollegen, der es danach übernimmt, den Status setzen)."""
    ben, carl = anmelden(server, "Ben"), anmelden(server, "Carl")
    x = ids_der_liste(ben, "alle", n=1)[0]
    bid = altbestand_besichtigung(team, x)
    assert carl("POST", f"/api/besichtigung/{bid}/planen", {})[0] == 403
    assert carl("POST", f"/api/bearbeitung/{x}/uebernehmen", {})[0] == 200
    s, b, _ = carl("POST", f"/api/besichtigung/{bid}/planen", {})
    assert s == 200 and b["zustaendig"]["id"] == team.ids["Carl"]
    # Carl hält das Inserat jetzt: Ben kann es nicht übernehmen
    assert ben("POST", f"/api/bearbeitung/{x}/uebernehmen", {})[0] == 409


def test_http_besichtigung_anlegen_auf_abgeschlossenem_freiem_inserat_braucht_uebernahme(server, team, db):
    """Besichtigung anlegen ohne Statusänderung (abgesagt/gekauft) vergibt trotzdem eine Zuständigkeit: nur Bearbeiter oder Inhaber."""
    anna, carl = anmelden(server, "Anna"), anmelden(server, "Carl")
    y = ids_der_liste(carl, "alle", n=1)[0]
    db.setze_status(y, "abgesagt")
    assert bearbeitung(db, y) is None
    s, antwort, _ = carl("POST", "/api/besichtigung", {"anzeige_id": y})
    assert s == 403 and antwort["grund"] == "recht" and team.besichtigungen(offen=False, anzeige_id=y) == [] and status_von(db, y) == "abgesagt"
    assert carl("POST", f"/api/bearbeitung/{y}/uebernehmen", {})[0] == 200
    s, b, _ = carl("POST", "/api/besichtigung", {"anzeige_id": y})
    assert s == 200 and b["zustaendig"]["id"] == team.ids["Carl"] and status_von(db, y) == "abgesagt"
    assert anna("POST", "/api/besichtigung", {"anzeige_id": y, "zustaendig_id": team.ids["Carl"]})[0] == 200          # Inhaber immer


def test_http_ungueltige_zustaendig_id_ist_400_nicht_500(server, team):
    ben = anmelden(server, "Ben")
    x = ids_der_liste(ben, "alle", n=1)[0]
    for wert in ("abc", [1], {"a": 1}):
        assert ben("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": wert})[0] == 400, wert


def test_http_abschluss_gibt_nur_inhaber_und_eingetragenem_besichtiger_die_statusausnahme(server, team, db, monkeypatch):
    """Least Privilege: Der Bearbeiter braucht die Ausnahme nicht (er hält das Inserat), also bekommt er sie auch nicht."""
    mit_dora(team)
    anna, ben, carl = (anmelden(server, n) for n in ("Anna", "Ben", "Carl"))
    x, y, z = ids_der_liste(ben, "alle", n=3)
    flags = []
    original = Datenbank.setze_status

    def merke(self, ad_id, status, *a, **kw):
        flags.append((ad_id, status, kw.get("inhaber")))
        return original(self, ad_id, status, *a, **kw)
    monkeypatch.setattr(Datenbank, "setze_status", merke)
    for ad in (x, y, z):
        ben("POST", f"/api/bearbeitung/{ad}/uebernehmen", {})
    bx = ben("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": team.ids["Carl"]})[1]["id"]
    by = ben("POST", "/api/besichtigung", {"anzeige_id": y})[1]["id"]                                         # Ben ist Besichtiger
    bz = ben("POST", "/api/besichtigung", {"anzeige_id": z, "zustaendig_id": team.ids["Carl"]})[1]["id"]
    flags.clear()
    assert ben("POST", f"/api/besichtigung/{bx}/abschluss", {"entscheidung": "abgelehnt"})[0] == 200          # Bearbeiter, Carl ist Besichtiger
    assert flags == [(x, "abgesagt", False)]
    flags.clear()
    assert carl("POST", f"/api/besichtigung/{bz}/abschluss", {"entscheidung": "abgelehnt"})[0] == 200        # eingetragener Besichtiger
    assert flags == [(z, "abgesagt", True)]
    flags.clear()
    assert anna("POST", f"/api/besichtigung/{by}/abschluss", {"entscheidung": "abgelehnt"})[0] == 200         # Inhaber
    assert flags == [(y, "abgesagt", True)]


def test_http_einzelplatz_ohne_nutzer_unveraendert(server, db):
    """Ohne angelegte Nutzer gibt es keine Rechteprüfung: anlegen, planen, speichern und abschließen wie bisher."""
    c = Client(server.server_address[1])
    c.csrf = c("GET", "/api/ich")[1]["csrf"]
    x = ids_der_liste(c, "alle", n=1)[0]
    s, b, _ = c("POST", "/api/besichtigung", {"anzeige_id": x, "termin": "2026-11-01T10:00"})
    assert s == 200 and b["zustaendig"] is None and b["darf_bearbeiten"] is True and status_von(db, x) == "besichtigung"
    s, b, _ = c("POST", f"/api/besichtigung/{b['id']}/planen", {"termin": "2026-11-05T09:00", "adresse": "Hauptstr. 1"})
    assert s == 200 and b["adresse"] == "Hauptstr. 1" and b["zustaendig"] is None and b["darf_bearbeiten"] is True
    s, _, _ = c("POST", f"/api/besichtigung/{b['id']}/abschluss", {"entscheidung": "abgelehnt"})
    assert s == 200 and status_von(db, x) == "abgesagt"
    assert db.con.execute("SELECT status FROM besichtigungen WHERE id=?", (b["id"],)).fetchone()[0] == "abgeschlossen"


# ======================================================================= Q-M1: Erzwingen wirkt wirklich
@pytest.mark.parametrize("status", ["verhandlung", "besichtigung"])
def test_db_erzwingen_bei_verhandlung_und_besichtigung_uebernimmt_wirklich(db, team, importiert, status):
    a, b = anzeige_ids(db, 2)
    anna, ben = team.ids["Anna"], team.ids["Ben"]
    assert db.setze_status(a, "kontaktiert", text="x", nutzer_id=ben)
    # Inhaber ohne Erzwingen: Status ändert sich, Bearbeiter bleibt (Ausnahme)
    assert db.setze_status(a, status, nutzer_id=anna, inhaber=True) and bearbeitung(db, a)[0] == ben
    # mit Erzwingen: Inhaber übernimmt wirklich; der erste Kontakt bleibt bei Ben
    assert db.setze_status(a, status, nutzer_id=anna, inhaber=True, erzwingen=True)
    assert bearbeitung(db, a)[0] == anna and bearbeitung(db, a)[2] == ben and status_von(db, a) == status
    # kontaktierte Dublette eines Kollegen verhindert auch das Erzwingen (nichts geändert)
    assert db.setze_status(b, "kontaktiert", nutzer_id=ben)
    vorher = bearbeitung(db, b)
    with pytest.raises(BearbeitungsKonflikt):
        db.setze_status(a, "besichtigung", nutzer_id=anna, inhaber=True, erzwingen=True, dubletten=[b])
    assert bearbeitung(db, b) == vorher


def erzwungen(caplog):
    return [r.getMessage() for r in caplog.records if "Erzwungene Übernahme" in r.getMessage()]


def test_http_erzwingen_bei_verhandlung_und_besichtigung_uebernimmt_und_protokolliert_nur_echte_aenderungen(server, team, db, caplog):
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    x, y, z, w = ids_der_liste(anna, "alle", n=4)
    ai, bi = team.ids["Anna"], team.ids["Ben"]
    for ad in (x, y, z, w):
        assert ben("POST", "/api/status", {"id": ad, "status": "kontaktiert", "text": "Ben"})[0] == 200
    with caplog.at_level("INFO", logger="scout"):
        # ohne Erzwingen: Ausnahme des Inhabers, kein Wechsel, kein Eintrag
        assert anna("POST", "/api/status", {"id": x, "status": "verhandlung"})[0] == 200
        assert bearbeitung(db, x)[0] == bi and erzwungen(caplog) == []
        # „erzwingen“ bei Verhandlung: Halter danach Inhaber, genau ein Eintrag
        assert anna("POST", "/api/status", {"id": x, "status": "verhandlung", "erzwingen": True})[0] == 200
        assert bearbeitung(db, x)[0] == ai and bearbeitung(db, x)[2] == bi and status_von(db, x) == "verhandlung"
        assert len(erzwungen(caplog)) == 1 and x in erzwungen(caplog)[0] and "von Ben durch Anna" in erzwungen(caplog)[0]
        # dasselbe bei „besichtigung“
        assert anna("POST", "/api/status", {"id": y, "status": "besichtigung", "erzwingen": True})[0] == 200
        assert bearbeitung(db, y)[0] == ai and len(erzwungen(caplog)) == 2
        # Besichtigung anlegen mit Erzwingen
        s, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": z, "erzwingen": True})
        assert s == 200 and bearbeitung(db, z)[0] == ai and status_von(db, z) == "besichtigung" and len(erzwungen(caplog)) == 3
        # nichts zu erzwingen (der Inhaber hält es schon): kein Eintrag
        assert anna("POST", "/api/status", {"id": x, "status": "besichtigung", "erzwingen": True})[0] == 200
        assert len(erzwungen(caplog)) == 3
        # Besichtigung auf einem abgeschlossenen Inserat des Kollegen: Status/Bearbeiter bleiben → nicht als erzwungen melden
        assert ben("POST", "/api/status", {"id": w, "status": "abgesagt"})[0] == 200                      # „gekauft“ nur Inhaber (P1-15)
        assert anna("POST", "/api/besichtigung", {"anzeige_id": w, "erzwingen": True})[0] == 200
        assert bearbeitung(db, w)[0] == bi and status_von(db, w) == "abgesagt" and len(erzwungen(caplog)) == 3
        # Übernehmen-Endpunkt: nur bei tatsächlichem Wechsel
        a = ids_der_liste(anna, "alle", n=5)[4]
        assert anna("POST", f"/api/bearbeitung/{a}/uebernehmen", {"erzwingen": True})[0] == 200               # frei: nichts zu erzwingen
        assert len(erzwungen(caplog)) == 3


# ======================================================================= Q-N1: Status und Besichtigung in EINER Transaktion
def sperre_nach_schreiben(monkeypatch, klasse, name):
    """Ersetzt eine Schreibmethode: Sie schreibt wirklich und meldet danach „database is locked“ (Sperre beim Festschreiben)."""
    original = getattr(klasse, name)

    def kaputt(self, *a, **kw):
        original(self, *a, **kw)
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(klasse, name, kaputt)


@pytest.mark.parametrize("vorher", [False, True])
def test_http_besichtigung_anlegen_ist_atomar(server, team, db, monkeypatch, vorher):
    ben = anmelden(server, "Ben")
    x = ids_der_liste(ben, "alle", n=1)[0]
    if vorher:                                                             # Fehler schon beim Schreiben der Besichtigung
        def kaputt(self, *a, **kw):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(TeamSpeicher, "besichtigung_anlegen", kaputt)
    else:                                                                  # Besichtigung geschrieben, Festschreiben scheitert
        sperre_nach_schreiben(monkeypatch, TeamSpeicher, "besichtigung_anlegen")
    s, antwort, r = ben("POST", "/api/besichtigung", {"anzeige_id": x})
    assert s == 503 and antwort["grund"] == "belegt" and r.getheader("Retry-After")
    assert not db.con.in_transaction
    assert status_von(db, x) == "neu" and bearbeitung(db, x) is None                                          # kein halber Zustand
    assert db.con.execute("SELECT COUNT(*) FROM besichtigungen").fetchone()[0] == 0
    monkeypatch.undo()
    s, b, _ = ben("POST", "/api/besichtigung", {"anzeige_id": x})
    assert s == 200 and status_von(db, x) == "besichtigung" and bearbeitung(db, x)[0] == team.ids["Ben"]
    assert db.con.execute("SELECT COUNT(*) FROM besichtigungen").fetchone()[0] == 1


def test_http_besichtigung_anlegen_einzelplatz_ist_atomar(server, db, monkeypatch):
    c = Client(server.server_address[1])
    c.csrf = c("GET", "/api/ich")[1]["csrf"]
    x = ids_der_liste(c, "alle", n=1)[0]
    sperre_nach_schreiben(monkeypatch, TeamSpeicher, "besichtigung_anlegen")
    assert c("POST", "/api/besichtigung", {"anzeige_id": x})[0] == 503
    assert status_von(db, x) == "neu" and db.con.execute("SELECT COUNT(*) FROM besichtigungen").fetchone()[0] == 0 and not db.con.in_transaction


@pytest.mark.parametrize("team_aktiv", [True, False])
def test_http_abschluss_ist_atomar(server, db, monkeypatch, request, team_aktiv):
    if team_aktiv:
        team = request.getfixturevalue("team")
        wer = anmelden(server, "Ben")
    else:
        team = TeamSpeicher(db, db.con.execute("PRAGMA database_list").fetchone()[2] + ".fotos")
        wer = Client(server.server_address[1])
        wer.csrf = wer("GET", "/api/ich")[1]["csrf"]
    x = ids_der_liste(wer, "alle", n=1)[0]
    bid = wer("POST", "/api/besichtigung", {"anzeige_id": x})[1]["id"]
    assert status_von(db, x) == "besichtigung"
    sperre_nach_schreiben(monkeypatch, TeamSpeicher, "besichtigung_abschliessen")
    s, antwort, _ = wer("POST", f"/api/besichtigung/{bid}/abschluss", {"entscheidung": "abgelehnt"})
    assert s == 503 and antwort["grund"] == "belegt" and not db.con.in_transaction
    assert status_von(db, x) == "besichtigung"                                                                # Status NICHT „abgesagt“
    assert db.con.execute("SELECT status, protokoll_json FROM besichtigungen WHERE id=?", (bid,)).fetchone()[:] == ("geplant", None)
    monkeypatch.undo()
    assert wer("POST", f"/api/besichtigung/{bid}/abschluss", {"entscheidung": "abgelehnt"})[0] == 200
    assert status_von(db, x) == "abgesagt" and team.besichtigung(bid)["status"] == "abgeschlossen"


def test_db_transaktion_verschachtelt_committet_erst_aussen_und_rollt_alles_zurueck(db, team, importiert):
    a, b = anzeige_ids(db, 2)
    ben = team.ids["Ben"]
    with pytest.raises(RuntimeError):
        with db.transaktion():
            assert db.setze_status(a, "besichtigung", nutzer_id=ben)
            assert db.in_transaktion and db.con.in_transaction                                                # innen nicht committet
            bid = team.besichtigung_anlegen(a, dict(BASIS_DATEN), None, None, ben, ben)
            assert db.con.in_transaction and bid
            raise RuntimeError("Absturz vor dem Festschreiben")
    assert not db.in_transaktion and not db.con.in_transaction
    assert status_von(db, a) == "neu" and bearbeitung(db, a) is None and team.besichtigung(bid) is None
    with db.transaktion():
        db.setze_status(a, "besichtigung", nutzer_id=ben)
        bid = team.besichtigung_anlegen(a, dict(BASIS_DATEN), None, None, ben, ben)
        andere = sqlite3.connect(db.con.execute("PRAGMA database_list").fetchone()[2])
        assert andere.execute("SELECT COUNT(*) FROM besichtigungen").fetchone()[0] == 0                       # noch nicht sichtbar
        andere.close()
    assert not db.con.in_transaction and team.besichtigung(bid) and status_von(db, a) == "besichtigung"
    # Konflikt innerhalb: alles zurück
    with pytest.raises(BearbeitungsKonflikt):
        with db.transaktion():
            team.besichtigung_anlegen(b, dict(BASIS_DATEN), None, None, ben, ben)
            db.setze_status(a, "kontaktiert", nutzer_id=team.ids["Carl"])
    assert team.besichtigungen(offen=False, anzeige_id=b) == [] and bearbeitung(db, a)[0] == ben


# ======================================================================= Q-M4: Seitenimport verwirft den Dubletten-Zwischenspeicher
def test_http_seitenimport_macht_neue_dublette_sofort_wirksam(cfg, db, importiert, ads, team, tmp_path):
    """Ben kontaktiert A (füllt den Zwischenspeicher: keine Dublette), dann bringt `POST /api/import` die Dublette B (gleiche Marke, EZ,
    PLZ, km) – Carl darf B nicht mehr übernehmen."""
    ordner = tmp_path / "import"
    ordner.mkdir()
    cfg["import"] = {"ordner": str(ordner)}
    srv = starte(cfg, db)
    try:
        ben, carl = anmelden(srv, "Ben"), anmelden(srv, "Carl")
        a = ads[3]
        b = {**a, "id": "3500009999", "slug": "wohnmobil-dublette"}
        assert ben("POST", "/api/status", {"id": a["id"], "status": "kontaktiert", "text": "Hallo"})[0] == 200
        assert b["id"] not in dubletten_ids(db).get(a["id"], [])
        (ordner / "suche.html").write_text(such_html([b]), encoding="utf-8")
        (ordner / "anzeige.html").write_text(detailseite(b), encoding="utf-8")                              # km kommt von der Detailseite
        assert carl("POST", "/api/import", {})[0] == 403                                                 # Import nur Inhaber (P1-15)
        s, stat, _ = anmelden(srv, "Anna")("POST", "/api/import", {})
        assert s == 200 and stat["neu"] == 1 and stat["detailseiten"] == 1, stat
        assert dubletten_ids(db)[a["id"]] == [b["id"]]
        s, antwort, _ = carl("POST", f"/api/bearbeitung/{b['id']}/uebernehmen", {})
        assert s == 409 and f"Dublette {a['id']}" in antwort["fehler"] and antwort["grund"] == "konflikt"
        assert bearbeitung(db, b["id"]) is None
        assert carl("POST", "/api/status", {"id": b["id"], "status": "kontaktiert", "text": "x"})[0] == 409
    finally:
        srv.shutdown()
        srv.server_close()


# ======================================================================= Q-N2 / Q11: deaktivierte Kollegen
def test_db_dublette_eines_deaktivierten_kollegen_blockiert_zuweisen_und_erzwingen_nicht(db, team, importiert):
    a, b, c = dublette_herstellen(db, 3)
    ben, carl, anna = team.ids["Ben"], team.ids["Carl"], team.ids["Anna"]
    assert db.setze_status(a, "kontaktiert", text="x", nutzer_id=ben)
    with pytest.raises(BearbeitungsKonflikt):                                           # solange Ben aktiv ist, blockiert seine Dublette
        db.weise_zu(b, carl, NEUN, dubletten=[a, c])
    assert db.uebernimm(b, anna, NEUN, erzwingen=True, dubletten=[a, c]) is False
    team.nutzer_aktiv_setzen("Ben", False)
    db.weise_zu(b, carl, NEUN, dubletten=[a, c])                                        # kein Konflikt mehr
    assert bearbeitung(db, b)[0] == carl and bearbeitung(db, a)[0] == ben and bearbeitung(db, a)[2] == ben      # a bleibt unberührt
    assert db.uebernimm(c, anna, NEUN, erzwingen=True, dubletten=[a, b]) is True        # Carl hält b nur reserviert: zieht mit
    assert bearbeitung(db, c)[0] == anna and bearbeitung(db, b)[0] == anna and bearbeitung(db, a)[0] == ben


def test_http_dublette_eines_deaktivierten_kollegen_blockiert_zuweisen_und_erzwingen_nicht(server, team, db):
    a, b = dublette_herstellen(db)
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    assert ben("POST", "/api/status", {"id": a, "status": "kontaktiert", "text": "Ben"})[0] == 200
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Carl"]})
    assert s == 409 and "Ben" in antwort["fehler"]
    s, antwort, _ = anna("POST", f"/api/bearbeitung/{b}/uebernehmen", {"erzwingen": True})
    assert s == 409
    team.nutzer_aktiv_setzen("Ben", False)                                                                    # Ben verlässt das Team
    assert anna("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 200
    assert bearbeitung(db, b)[0] == team.ids["Carl"]
    assert anna("POST", f"/api/bearbeitung/{b}/uebernehmen", {"erzwingen": True})[0] == 200
    assert bearbeitung(db, b)[0] == team.ids["Anna"]


def test_db_uebertragung_nimmt_nie_kontaktierte_reservierungen_mit(db, team, importiert):
    """Doppelte Absicherung: Auch wenn eine kontaktierte Dublette eines aktiven Kollegen bis hierher durchkäme, wird sie nicht umgehängt."""
    a, b = anzeige_ids(db, 2)
    ben, carl = team.ids["Ben"], team.ids["Carl"]
    assert db.setze_status(a, "kontaktiert", text="x", nutzer_id=ben)
    assert db.uebernimm(b, ben, NEUN)
    db._uebertrage_reservierungen([a, b], carl, NEUN, "")
    db.con.commit()
    assert bearbeitung(db, a)[0] == ben                                                                       # kontaktiert: bleibt
    assert bearbeitung(db, b)[0] == carl                                                                      # nur reserviert: zieht mit


# ======================================================================= Q-N3: Kommandozeile beachtet Dubletten
def test_kommandozeile_status_mit_nutzer_lehnt_dublette_eines_kollegen_ab(cfg, db, team, importiert):
    a, b = dublette_herstellen(db)
    status_befehl(cfg, db, a, "kontaktiert", nutzer="Ben")
    with pytest.raises(SystemExit) as e:
        status_befehl(cfg, db, b, "kontaktiert", nutzer="Carl")
    assert f"Dublette {a}" in str(e.value) and "Ben" in str(e.value)
    assert status_von(db, b) == "neu" and bearbeitung(db, b) is None
    for status in ("verhandlung", "besichtigung"):
        with pytest.raises(SystemExit):
            status_befehl(cfg, db, b, status, nutzer="Carl")
    status_befehl(cfg, db, b, "kontaktiert", nutzer="Ben")                                                    # die eigene Gruppe darf
    assert status_von(db, b) == "kontaktiert" and bearbeitung(db, b)[0] == team.ids["Ben"]
