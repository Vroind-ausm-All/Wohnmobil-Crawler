"""Phase-1-Abschluss: P1-07 Versionskonflikt Besichtigung, P1-15 Rollenmatrix, P1-14a Löschung von Verkäuferdaten aus Inseraten."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

from tests.test_team_bearbeitung import anmelden, ids_der_liste, server, team  # noqa: F401 – Fixtures


# ---------------------------------------------------------------- P1-07
def test_besichtigung_speichern_mit_version_und_planen_nach_abschluss(server, team):
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    x = ids_der_liste(anna, "alle", n=1)[0]
    s, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": team.ids["Ben"]})
    assert s == 200
    v = anna("GET", f"/api/besichtigung/{b['id']}")[1]["version"]
    s, r, _ = anna("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"maengel": [], "notiz": "Anna"}, "version": v})
    assert s == 200 and r["version"] == v + 1
    s, f, _ = ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"maengel": [], "notiz": "Ben"}, "version": v})
    assert s == 409 and f["grund"] == "version" and f["version"] == v + 1 and f["daten"]["notiz"] == "Anna"   # nichts überschrieben
    assert anna("GET", f"/api/besichtigung/{b['id']}")[1]["daten"]["notiz"] == "Anna"
    assert ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"notiz": "Ben"}, "version": "1"})[0] == 400
    s, r, _ = ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"maengel": [], "notiz": "Ben"}, "version": v + 1})
    assert s == 200 and r["version"] == v + 2                                        # bewusst übernommen: mit aktueller Version
    assert ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"notiz": "alt"}})[0] == 200   # ältere Geräte ohne Version
    assert ben("POST", f"/api/besichtigung/{b['id']}/abschluss", {"entscheidung": "abgelehnt"})[0] == 200
    s, f, _ = anna("POST", f"/api/besichtigung/{b['id']}/planen", {"termin": "2026-11-01T10:00"})
    assert s == 409 and "abgeschlossen" in f["fehler"]
    assert anna("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {}, "version": v + 3})[0] == 409


# ---------------------------------------------------------------- P1-15
def test_rollenmatrix_schreiben_nur_zustaendig_lesen_frei(server, team, db):
    from tests.test_handy import Client
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    a, b = ids_der_liste(anna, "alle", n=2)
    s, f, _ = ben("POST", "/api/status", {"id": a, "status": "gekauft"})
    assert s == 403 and f["grund"] == "recht" and db.status_von(a) != "gekauft"
    assert anna("POST", "/api/status", {"id": a, "status": "gekauft"})[0] == 200
    assert ben("POST", "/api/suchlauf", {})[0] == 403 and ben("POST", "/api/import", {})[0] == 403
    assert anna("POST", "/api/import", {})[0] == 200                                         # Import liest nur den Ordner (kein Netz)
    assert ben("POST", f"/api/bearbeitung/{b}/zuweisen", {"nutzer_id": team.ids["Carl"]})[0] == 403
    assert ben("POST", "/api/standorte", {"name": "X"})[0] == 403
    assert ben("GET", f"/api/fahrzeug/{a}")[0] == 200 and ben("GET", "/api/team")[0] == 200     # Lesen bleibt frei
    # Oberfläche: Knöpfe für Suchlauf/Import nur beim Inhaber
    seite_ben, seite_anna = ben("GET", "/")[1], anna("GET", "/")[1]
    assert 'id="suchen" class="btn" hidden' in seite_ben and 'id="suchen" class="btn">' in seite_anna
    lokal = Client(server.server_address[1])
    assert lokal("GET", "/api/suchlauf")[0] == 401                                            # mit Team: nur angemeldet


# ---------------------------------------------------------------- P1-14a
def _mit_personendaten(db, team, tmp_path, anzeige_id, alt="2025-01-01T10:00:00"):
    import json
    db.con.execute("UPDATE anzeigen SET details_json=?, anschreiben_text=?, status='kontaktiert', kontaktiert_am=?, status_am=?, "
                   "zuletzt_gesehen=? WHERE id=?",
                   (json.dumps({"verkaeufer_name": "Erika Beispiel", "ausstattung": "Markise"}),
                    "Hallo Erika Beispiel,\nwir interessieren uns für Ihr Wohnmobil.", alt, alt, alt, anzeige_id))
    db.con.commit()
    bid = team.besichtigung_anlegen(anzeige_id, {"anzeige_id": anzeige_id}, None, "Musterweg 1, Berlin", None, None)
    team.besichtigung_abschliessen(bid, {"verkaeufer": {"name": "Erika Beispiel", "telefon": "0170 1"}, "unterschrift_verkaeufer": "data:x",
                                         "bemerkung": "ruft abends an", "entscheidung": "abgelehnt"}, None, "abgeschlossen")
    datei = tmp_path / "ausgabe" / "anschreiben" / f"{anzeige_id}.txt"
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text("Hallo Erika Beispiel", encoding="utf-8")
    return bid, datei


def test_inserat_anonymisieren_einzeln_und_nach_frist(cfg, db, importiert, team, tmp_path):
    import json
    from datetime import datetime
    import pytest
    from wmscout import datenrechte
    ids = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 4")]
    bid, datei = _mit_personendaten(db, team, tmp_path, ids[0])
    erg = datenrechte.inserat_anonymisieren(db, tmp_path / "ausgabe", ids[0])
    assert erg == {"anzeige_id": ids[0], "name_entfernt": True, "besichtigungen": 1} and not datei.exists()
    a = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ids[0],)).fetchone()
    details = json.loads(a["details_json"])
    assert "verkaeufer_name" not in details and details["ausstattung"] == "Markise" and details["anonymisiert_am"]
    assert "Erika" not in a["anschreiben_text"] and "[Name entfernt]" in a["anschreiben_text"] and a["kontaktiert_am"]
    b = db.con.execute("SELECT adresse, protokoll_json FROM besichtigungen WHERE id=?", (bid,)).fetchone()
    assert b["adresse"] is None and "Erika" not in b["protokoll_json"] and "abgelehnt" in b["protokoll_json"]
    # gekauft: Aufbewahrung
    db.con.execute("UPDATE anzeigen SET status='gekauft' WHERE id=?", (ids[1],))
    db.con.commit()
    with pytest.raises(ValueError, match="gekauft"):
        datenrechte.inserat_anonymisieren(db, tmp_path / "ausgabe", ids[1])
    with pytest.raises(LookupError):
        datenrechte.inserat_anonymisieren(db, tmp_path / "ausgabe", "gibtsnicht")
    # Frist: nur alte, nicht gekaufte, noch nicht anonymisierte; 0 = aus
    _mit_personendaten(db, team, tmp_path, ids[2])
    _mit_personendaten(db, team, tmp_path, ids[3], alt=datetime.now().isoformat(timespec="seconds"))     # frisch
    db.con.execute("UPDATE anzeigen SET details_json='{\"verkaeufer_name\": \"Otto\"}', zuletzt_gesehen='2025-01-01' WHERE id=?", (ids[1],))
    db.con.commit()
    assert datenrechte.inserate_nach_frist(db, tmp_path / "ausgabe", 0) == []
    assert datenrechte.inserate_nach_frist(db, tmp_path / "ausgabe", 6, jetzt=datetime(2026, 10, 17)) == [ids[2]]
    assert datenrechte.inserate_nach_frist(db, tmp_path / "ausgabe", 6, jetzt=datetime(2026, 10, 17)) == []   # nichts doppelt
    for falsch in (-1, "6", True):
        with pytest.raises(ValueError):
            datenrechte.frist_aus({"datenschutz": {"inserate_anonymisieren_nach_monaten": falsch}})
    assert datenrechte.frist_aus({}) == 0


def test_cli_inserat_anonymisieren(cfg, db, importiert, team, tmp_path):
    from tests.test_cli import _scout
    anzeige_id = db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 1").fetchone()[0]
    _mit_personendaten(db, team, tmp_path, anzeige_id)
    db.con.close()
    r = _scout(cfg, tmp_path, "inserat", "anonymisieren", anzeige_id)
    assert r.returncode != 0 and "--bestaetigt" in r.stderr
    r = _scout(cfg, tmp_path, "inserat", "anonymisieren", anzeige_id, "--bestaetigt")
    assert r.returncode == 0 and "anonymisiert" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "inserat", "anonymisieren", "--aelter-als", "6", "--bestaetigt")
    assert r.returncode == 0 and "0 Inserat(e)" in r.stdout, r.stderr


# ---------------------------------------------------------------- P1-05
def test_langsamer_whatsapp_versand_blockiert_keine_anfrage(server, team, db, monkeypatch):
    import threading
    import time
    k = server.RequestHandlerClass.kontext
    gestartet, frei = threading.Event(), threading.Event()

    class LangsamerVersand:
        bereit = True

        def sende(self, an, vorlage, parameter):
            gestartet.set()
            frei.wait(10)                                        # simuliert einen hängenden WhatsApp-Server
            return True

    langsam = LangsamerVersand()
    monkeypatch.setattr(k.whatsapp, "sende", langsam.sende)
    monkeypatch.setattr(type(k.whatsapp), "bereit", property(lambda self: True))
    k.cfg.setdefault("whatsapp", {})["vorlage_zuweisung"] = "besichtigung_zugewiesen"
    db.con.execute("UPDATE nutzer SET telefon='+491712222222' WHERE name='Ben'")
    db.con.commit()
    anna, carl = anmelden(server, "Anna"), anmelden(server, "Carl")
    x = ids_der_liste(anna, "alle", n=1)[0]
    t0 = time.monotonic()
    s, _, _ = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": team.ids["Ben"]})
    dauer = time.monotonic() - t0
    try:
        assert s == 200 and gestartet.wait(5) and dauer < 3                          # Antwort, während der Versand noch hängt
        t1 = time.monotonic()
        assert carl("GET", "/api/team")[0] == 200 and time.monotonic() - t1 < 3      # andere Anfragen laufen weiter
    finally:
        frei.set()


# ---------------------------------------------------------------- P1-08
def test_bewertung_ohne_datenbank(cfg, db, importiert):
    import subprocess
    import sys
    from datetime import datetime
    from scout import BASIS
    from wmscout.bewertung.auswertung import bewerte_alle, bewerte_zeilen
    r = subprocess.run([sys.executable, "-c", "import sys, wmscout.bewertung.auswertung, wmscout.bewertung.rechner, "
                        "wmscout.bewertung.anschreiben, wmscout.bewertung.kalkulation, wmscout.domaene; "
                        "print('wmscout.datenbank' in sys.modules, 'sqlite3' in sys.modules)"],
                       capture_output=True, text=True, cwd=BASIS, timeout=60)
    assert r.stdout.strip() == "False False", r.stderr
    # gleiche Ergebnisse aus einfachen Listen wie aus der Datenbank
    mit_preis, aktive = [dict(x) for x in db.alle_mit_preis()], [dict(x) for x in db.aktive()]
    jetzt = datetime.now()
    aus_listen = bewerte_zeilen(cfg, BASIS, mit_preis, aktive, jetzt=jetzt)
    aus_db = bewerte_alle(cfg, db, BASIS)
    assert len(aus_listen) == len(aus_db) > 10
    assert [(z["a"]["id"], z["b"].max_ek, z["b"].ampel, z["bereit"]) for z in aus_listen] == \
        [(z["a"]["id"], z["b"].max_ek, z["b"].ampel, z["bereit"]) for z in aus_db]
    from wmscout.datenbank import STATUS, import_art
    from wmscout import domaene
    assert STATUS is domaene.STATUS and import_art is domaene.import_art                          # alte Importe gelten weiter
