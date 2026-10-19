"""Phase G0 – Datenrechte (ADR-030): Widerruf einer Verkaufsanfrage löscht Personendaten, Kalkulationen speichern keine Kontaktdaten."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import base64
import json

from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_cli import _scout
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from tests.test_verkauf import JPEG
from wmscout.datenbank import Datenbank
from wmscout.deal import DealSpeicher


def test_widerruf_loescht_personendaten_und_beendet_auktion(markt, db):
    anna, ben, hugo, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["anfrage"]
    bild = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    foto = anna("POST", f"/api/verkaufsanfrage/{anfrage}/foto", {"bild": bild})[1]["datei"]
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "Herr Beispiel ruft abends an"})
    auk = anna("POST", f"/api/verkaufsanfrage/{anfrage}/auktion", {"startpreis": 20000})[1]["id"]
    hugo("POST", f"/api/haendler/auktion/{auk}/gebot", {"betrag": 20000, "wiederholungs_id": "widerruf-01"})
    assert anna("GET", f"/anfrage-fotos/{anfrage}/{foto}")[0] == 200
    assert ben("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})[0] == 403                     # nur Inhaber
    assert hugo("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})[0] == 403
    s, erg, _ = anna("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})
    assert s == 200 and erg["fotos"] == 1 and erg["verkaeufer_anonymisiert"]
    a = anna("GET", f"/api/verkaufsanfrage/{anfrage}")[1]
    assert (a["name"], a["email"], a["telefon"], a["plz"], a["ort"]) == ("(gelöscht)", None, "(gelöscht)", None, None)
    assert (a["beschreibung"], a["notiz"], a["freigegeben_am"], a["status"], a["fotos"]) == (None, None, None, "zurueckgezogen", [])
    assert a["auktionen"][0]["status"] == "abgebrochen" and a["verlauf"][-1]["ereignis"] == "widerruf"
    assert not [v for v in a["verlauf"] if v["ereignis"] == "notiz" and (v["alt"] or v["neu"])]
    assert anna("GET", f"/anfrage-fotos/{anfrage}/{foto}")[0] == 404
    ordner = markt_foto_ordner(db) / "anfragen" / str(anfrage)
    assert ordner.is_dir() and not list(ordner.glob("*"))                                          # Datei wirklich weg
    assert "Beispiel" not in json.dumps(a, ensure_ascii=False).replace("(gelöscht)", "")
    assert hugo("GET", "/api/haendler/fahrzeuge")[1] == []                                            # Freigabe zurückgenommen
    assert anna("POST", "/api/verkaufsanfrage/999/widerruf", {})[0] == 404


def markt_foto_ordner(db):
    from pathlib import Path
    return Path(db.con.execute("PRAGMA database_list").fetchone()[2]).parent / "fotos"


def test_weitere_anfrage_desselben_verkaeufers_bleibt(markt, db):
    anna, anfrage = markt["anna"], markt["anfrage"]
    vid = db.con.execute("SELECT verkaeufer_id FROM verkaufsanfragen WHERE id=?", (anfrage,)).fetchone()[0]
    db.con.execute("INSERT INTO verkaufsanfragen (referenz, verkaeufer_id, kanal, status, erstellt_am, aktualisiert_am) "
                   "VALUES ('VA-TEST-2', ?, 'telefon', 'eingegangen', 'x', 'x')", (vid,))
    db.con.commit()
    erg = anna("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})[1]
    assert erg["verkaeufer_anonymisiert"] is False
    assert db.con.execute("SELECT name FROM verkaeufer WHERE id=?", (vid,)).fetchone()[0] == "Erika Beispiel"


def test_kalkulation_speichert_keine_kontaktdaten(markt, db, cfg):
    d = DealSpeicher(db, cfg)
    e = d.eingabe(markt["anfrage"], 30000)
    text = json.dumps(e["fahrzeug"], ensure_ascii=False)
    assert "0170" not in text and "@" not in text and "www." not in text and "[Telefon entfernt]" in text


def test_cli_widerruf(cfg, tmp_path):
    from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage
    from tests.test_haendler import MIT_WEITERGABE
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    v = VerkaufSpeicher(db, tmp_path / "f")
    ref = v.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["referenz"]
    db.con.close()
    r = _scout(cfg, tmp_path, "anfrage", "widerruf", ref)
    assert r.returncode != 0 and "--bestaetigt" in r.stderr
    r = _scout(cfg, tmp_path, "anfrage", "widerruf", ref, "--bestaetigt")
    assert r.returncode == 0 and "Widerruf ausgeführt" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "anfrage", "widerruf", "VA-0000-9999", "--bestaetigt")
    assert r.returncode != 0 and "unbekannt" in r.stderr


def test_widerruf_schwaerzt_besichtigung_der_anfrage_und_loescht_ihre_fotos(markt, db):
    from tests.test_sicherheit import _jpeg_mit_exif
    anna, anfrage = markt["anna"], markt["anfrage"]
    b = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {"adresse": "Musterweg 1, Berlin"})[1]
    bild = "data:image/jpeg;base64," + base64.b64encode(_jpeg_mit_exif()).decode()
    foto = anna("POST", f"/api/besichtigung/{b['id']}/foto", {"bild": bild})[1]["datei"]
    datei = markt_foto_ordner(db) / str(b["id"]) / foto
    assert datei.is_file()
    erg = anna("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})[1]
    assert erg["besichtigungen"] == 1 and erg["fotos"] == 1 and not datei.exists()
    r = db.con.execute("SELECT basis_json, adresse, daten_json FROM besichtigungen WHERE id=?", (b["id"],)).fetchone()
    assert "Erika" not in r["basis_json"] and r["adresse"] is None and r["daten_json"] == "{}"


def test_widerruf_mit_ankauf_auch_storniert_wird_verweigert(markt, db):
    from tests.test_ankauf import _kauf
    from tests.test_sicherheit import _jpeg_mit_exif
    anna, anfrage = markt["anna"], markt["anfrage"]
    b = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {})[1]
    aid = anna("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf())[1]["ankauf"]
    bild = "data:image/jpeg;base64," + base64.b64encode(_jpeg_mit_exif()).decode()
    d = anna("POST", f"/api/ankauf/{aid}/dokument", {"art": "vertrag", "datei": bild})[1]           # Vertragsfoto ohne EXIF
    gespeichert = anna("GET", f"/ankauf-dokumente/{aid}/{d['datei']}")[1]
    roh = gespeichert if isinstance(gespeichert, bytes) else str(gespeichert).encode("latin-1", "replace")
    assert b"GPS-DATEN" not in roh and b"BILDDATEN" in roh
    s, f, _ = anna("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})
    assert s == 409 and "Ankaufsvorgang" in f["fehler"]
    assert anna("POST", f"/api/ankauf/{aid}/storno", {"grund": "Verkäufer tritt zurück"})[0] == 200
    assert anna("POST", f"/api/verkaufsanfrage/{anfrage}/widerruf", {})[0] == 409                  # auch storniert: Einzelfall
    assert db.con.execute("SELECT name FROM verkaeufer v JOIN verkaufsanfragen a ON a.verkaeufer_id=v.id WHERE a.id=?",
                          (anfrage,)).fetchone()[0] == "Erika Beispiel"
