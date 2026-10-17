"""Phase-1-Abschluss: P1-07 Versionskonflikt, P1-15 Rollenmatrix, P1-14a Löschung, P1-05 Sperre, P1-08 Bewertung ohne DB, P1-10 Python."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import sys

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
    # Eingaben vor Ort, Foto und Team-Notiz wie beim Widerruf einer Anfrage (N5)
    db.con.execute("UPDATE besichtigungen SET daten_json=? WHERE id=?", (json.dumps({"fahrzeug": {"fin": "WDB123", "kennzeichen": "B-EB 1"}}), bid))
    db.con.execute("UPDATE anzeigen SET notiz='Frau Beispiel 0170 1' WHERE id=?", (ids[0],))
    db.con.execute("INSERT INTO fotos (besichtigung_id, datei, erstellt_am) VALUES (?, 'a.jpg', '2025-01-01')", (bid,))
    db.con.commit()
    foto = team.foto_ordner / str(bid) / "a.jpg"
    foto.parent.mkdir(parents=True)
    foto.write_bytes(b"jpg")
    erg = datenrechte.inserat_anonymisieren(db, tmp_path / "ausgabe", ids[0], team.foto_ordner)
    assert erg == {"anzeige_id": ids[0], "name_entfernt": True, "besichtigungen": 1, "fotos": 1} and not datei.exists() and not foto.exists()
    b = db.con.execute("SELECT daten_json, ergebnis_json FROM besichtigungen WHERE id=?", (bid,)).fetchone()
    assert b["daten_json"] == "{}" and b["ergebnis_json"] is None
    assert db.con.execute("SELECT COUNT(*) FROM fotos WHERE besichtigung_id=?", (bid,)).fetchone()[0] == 0
    assert db.con.execute("SELECT notiz FROM anzeigen WHERE id=?", (ids[0],)).fetchone()[0] is None
    a = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ids[0],)).fetchone()
    details = json.loads(a["details_json"])
    assert "verkaeufer_name" not in details and details["ausstattung"] == "Markise" and details["anonymisiert_am"]
    assert "Erika" not in a["anschreiben_text"] and "[Name entfernt]" in a["anschreiben_text"] and a["kontaktiert_am"]
    b = db.con.execute("SELECT adresse, protokoll_json FROM besichtigungen WHERE id=?", (bid,)).fetchone()
    assert b["adresse"] is None and "Erika" not in b["protokoll_json"] and "abgelehnt" in b["protokoll_json"]
    # gekauft: Aufbewahrung
    db.con.execute("UPDATE anzeigen SET status='gekauft' WHERE id=?", (ids[1],))
    db.con.commit()
    with pytest.raises(datenrechte.InseratGekauft, match="gekauft"):
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



def test_frist_offene_besichtigung_kaputtes_json_gesperrte_datei_diagnose(cfg, db, importiert, team, tmp_path, monkeypatch, caplog):
    """QA-Befunde N4, N8, N9 und Q11: offene Besichtigung schützt, kaputtes JSON wird nicht dauerhaft übersprungen, eine gesperrte
    Datei bricht nichts ab, Diagnose-Rohseiten verfallen mit derselben Frist, Fehler beenden keinen Lauf."""
    import logging
    import os
    from datetime import datetime
    from pathlib import Path
    from wmscout import datenrechte
    ids = [r[0] for r in db.con.execute("SELECT id FROM anzeigen ORDER BY id LIMIT 3")]
    _mit_personendaten(db, team, tmp_path, ids[0])
    team.besichtigung_anlegen(ids[0], {"anzeige_id": ids[0]}, None, "Weg 2", None, None)       # noch offen
    _, datei = _mit_personendaten(db, team, tmp_path, ids[1])
    db.con.execute("UPDATE anzeigen SET details_json='{\"verkaeufer_name\": kaputt' WHERE id=?", (ids[1],))
    db.con.commit()
    original = Path.unlink

    def gesperrt(pfad, *a, **k):
        if pfad == datei:
            raise PermissionError("von einem anderen Prozess verwendet")
        return original(pfad, *a, **k)

    monkeypatch.setattr(Path, "unlink", gesperrt)
    with caplog.at_level(logging.WARNING, logger="scout"):
        assert datenrechte.inserate_nach_frist(db, tmp_path / "ausgabe", 6, jetzt=datetime(2026, 10, 17)) == [ids[1]]
    assert "nicht gelöscht (PermissionError)" in caplog.text and datei.exists()
    assert "anonymisiert_am" in db.con.execute("SELECT details_json FROM anzeigen WHERE id=?", (ids[1],)).fetchone()[0]
    # Diagnose-Rohseiten
    ausgabe = tmp_path / "ausgabe"
    alt, frisch = ausgabe / "diagnose_suchseite.html", ausgabe / "diagnose_detailseite.html"
    for f in (alt, frisch):
        f.write_text("<html>Inserat</html>", encoding="utf-8")
    os.utime(alt, (datetime(2025, 1, 1).timestamp(),) * 2)
    assert datenrechte.diagnose_nach_frist(ausgabe, 6) == 1 and not alt.exists() and frisch.exists()
    assert datenrechte.diagnose_nach_frist(ausgabe, 0) == 0 and frisch.exists()
    # Fehler (z. B. ungültige Frist) werden protokolliert, nicht weitergereicht
    with caplog.at_level(logging.ERROR, logger="scout"):
        assert datenrechte.frist_anwenden(db, {**cfg, "datenschutz": {"inserate_anonymisieren_nach_monaten": -3}}, tmp_path,
                                          team.foto_ordner) == []
    assert "Datenschutz-Frist konnte nicht angewendet werden" in caplog.text


def test_frist_auch_nach_seitenimport_und_beim_start(cfg, db, importiert, server, team, monkeypatch):
    """N4: Verkäufernamen kommen über den Seitenimport – die Frist greift dort und beim Start, nicht nur nach einem Suchlauf."""
    from tests.daten import BASIS
    from wmscout import app as app_modul
    from wmscout import datenrechte
    aufrufe = []
    monkeypatch.setattr(datenrechte, "frist_anwenden", lambda *a, **k: aufrufe.append(a[1] is not None) or [])
    anna = anmelden(server, "Anna")
    assert anna("POST", "/api/import", {})[0] == 200 and aufrufe == [True]
    srv, _, _ = app_modul.erstelle_server(cfg, db, BASIS, port=0)
    srv.server_close()
    assert aufrufe == [True, True]


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


# ---------------------------------------------------------------- P1-10: nur Python 3.13 (F9)
def test_python_version_ueberall_gleich():
    from tests.daten import BASIS
    lesen = lambda name: (BASIS / name).read_text(encoding="utf-8")                      # noqa: E731
    assert 'requires-python = ">=3.13,<3.14"' in lesen("pyproject.toml")
    assert "if sys.version_info[:2] != (3, 13):" in lesen("scout.py")
    for skript in ("installieren.bat", "installieren.sh"):
        t = lesen(skript)
        assert "sys.version_info[:2] == (3, 13)" in t and "3.12" not in t and "3.10" not in t, skript
    for lock in ("requirements.txt", "requirements-dev.txt"):
        assert "--python-version 3.13" in lesen(lock) and "python_full_version <" not in lesen(lock), lock
    assert sys.version_info[:2] == (3, 13)


# ---------------------------------------------------------------- QA-Befunde zum Phase-1-Abschluss
PNG = "data:image/png;base64,iVBORw0KGgo="


def test_ankauf_ohne_ez_plant_mit_manuellem_marktwert(server, team, db):
    """N1 (HOCH): Kauf eines Inserats ohne EZ – der Plan rechnet mit dem Marktwert der Besichtigung, nicht mit 0 €."""
    ziel = db.con.execute("SELECT id FROM anzeigen WHERE ez_jahr IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]
    db.con.execute("UPDATE anzeigen SET ez_jahr=NULL WHERE id=?", (ziel,))
    db.con.commit()
    server.RequestHandlerClass.kontext.veraendert()
    anna = anmelden(server, "Anna")
    s, b, _ = anna("POST", "/api/besichtigung", {"anzeige_id": ziel, "marktwert": 36000})
    assert s == 200, b
    basis = anna("GET", f"/api/besichtigung/{b['id']}")[1]["basis"]
    s, r, _ = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", {"entscheidung": "gekauft", "endpreis": 25000,
                   "begruendung_unvollstaendig": "Test", "unterschrift_verkaeufer": PNG, "unterschrift_ankaeufer": PNG})
    assert s == 200 and r["ankauf"], r
    plan = anna("GET", f"/api/ankauf/{r['ankauf']}")[1]["vergleich"]["plan"]
    assert plan["max_ek"] == basis["max_ek"] > 0 and plan["haendler_vk"] == basis["haendler_vk"] > 0 and plan["gewinn"] > 0
    f = anna("GET", f"/api/fahrzeug/{ziel}")[1]["bewertung"]                                   # N11: null statt 0
    assert f["sicherheit"] == "keine" and f["max_ek"] is None and f["erstangebot"] is None and f["haendler_vk"] is None


def test_gekauft_verlassen_nur_inhaber(server, team, db):
    """N2: „gekauft“ setzt und ändert nur der Inhaber."""
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    a = ids_der_liste(anna, "alle", n=1)[0]
    assert anna("POST", "/api/status", {"id": a, "status": "gekauft"})[0] == 200
    for status in ("neu", "uninteressant", "abgesagt"):
        s, f, _ = ben("POST", "/api/status", {"id": a, "status": status})
        assert s == 403 and f["grund"] == "recht", status
    assert db.status_von(a) == "gekauft"
    assert anna("POST", "/api/status", {"id": a, "status": "abgesagt"})[0] == 200


def test_termin_verschieben_ohne_versionskonflikt(server, team, db):
    """N6: Planen (Termin/Adresse/Zuständig) erhöht die Version der Eingaben nicht."""
    anna, ben = anmelden(server, "Anna"), anmelden(server, "Ben")
    x = ids_der_liste(anna, "alle", n=1)[0]
    b = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": team.ids["Ben"]})[1]
    v = ben("GET", f"/api/besichtigung/{b['id']}")[1]["version"]
    s, r, _ = ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"notiz": "1"}, "version": v})
    assert s == 200
    assert anna("POST", f"/api/besichtigung/{b['id']}/planen", {"termin": "2026-11-02T10:00"})[0] == 200
    assert ben("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": {"notiz": "2"}, "version": r["version"]})[0] == 200
    assert ben("GET", f"/api/besichtigung/{b['id']}")[1]["termin"].startswith("2026-11-02")


def test_login_ziel_nur_eigene_pfade(server):
    """Q6/N3: das Ziel nach der Anmeldung prüft der Server; fremde Adressen und Umwege landen auf /m."""
    import json
    import re
    from tests.test_sicherheit import roh
    from wmscout.web.api import sicheres_ziel
    for gut in ("/m", "/m#/besichtigung/3", "/anfragen?status=neu", "/haendler"):
        assert sicheres_ziel(gut) == gut
    for boese in ("//evil.com", "/.//evil.com", "/\\evil.com", "https://evil.com", "/../x", "/m/./x", "evil.com",
                  "javascript:alert(1)", "/m\r\nSet-Cookie:x", "/ m", "", None, "/" + "a" * 600):
        assert sicheres_ziel(boese) == "/m", boese
    assert sicheres_ziel("/%5Cevil") == "/%5Cevil"                          # bleibt ein Pfad auf diesem Server (kodiert)
    for weiter, erwartet in (("/.//evil.com", "/m"), ("https://evil.com/", "/m"), ("/m#/termine", "/m#/termine")):
        from urllib.parse import quote
        html = roh(server, "GET", "/login?weiter=" + quote(weiter, safe=""))[1].decode()
        assert json.loads(re.search(r"var ziel = (\"[^\"]*\");", html).group(1)) == erwartet, weiter


def test_ics_ohne_nacktes_cr_und_zustaendig_400(server, team):
    """Q15: \\r aus Adresse/Titel bricht keine ICS-Zeile; Q13: ungültiger Zuständiger → 400."""
    from wmscout.web.api import ics
    text = ics({"id": 1, "termin": "2026-11-02T10:00", "adresse": "Musterweg 1\rATTENDEE:mailto:x@y", "basis": {"fahrzeug": "A\r\nB"}}, {}, None)
    zeilen = text.split("\r\n")
    assert "\r" not in "".join(zeilen) and not any(z.startswith("ATTENDEE") for z in zeilen)
    assert "LOCATION:Musterweg 1\\nATTENDEE:mailto:x@y" in zeilen
    anna = anmelden(server, "Anna")
    x = ids_der_liste(anna, "alle", n=1)[0]
    s, f, _ = anna("POST", "/api/besichtigung", {"anzeige_id": x, "zustaendig_id": "abc"})
    assert s == 400, f


def test_cli_frist_nur_positiv_und_hinweis_passwort_variable(cfg, tmp_path):
    from tests.test_cli import _scout
    r = _scout(cfg, tmp_path, "inserat", "anonymisieren", "--aelter-als", "-5", "--bestaetigt")
    assert r.returncode != 0 and "mindestens 1" in r.stderr                                      # N16
    r = _scout(cfg, tmp_path, "nutzer", "anlegen", "Eva", umgebung={"SCOUT_NEUES_PASSWORT": "sicher1234"})
    assert r.returncode == 0 and "SCOUT_NEUES_PASSWORT" in r.stderr                              # N13


def test_plan_ohne_unabhaengigen_marktwert_aus_grundlage(cfg, db, tmp_path):
    """N1 für ältere Besichtigungen ohne manuellen Marktwert: Bewertung „keine“ liefert keine 0-€-Beträge in den Plan."""
    from wmscout.ankauf import AnkaufSpeicher
    from wmscout.bewertung.rechner import Rechner
    b = Rechner(cfg).bewerte({"id": "x", "titel": "Knaus Sun Ti", "preis": 39000, "km": 90000, "suche": "Alkoven"}, [])
    assert b.sicherheit == "keine"
    v = AnkaufSpeicher(db, cfg, tmp_path / "ankaeufe").plan_vorbereiten({"id": 1, "basis": {"max_ek": 25100, "haendler_vk": 36800}}, 25000, b)
    assert v["plan"]["max_ek"] == 25100 and v["plan"]["haendler_vk"] == 36800 and v["plan"]["quelle"].startswith("Grundlage")
