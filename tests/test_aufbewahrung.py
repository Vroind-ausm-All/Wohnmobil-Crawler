"""F10 – Aufbewahrungsfristen (ADR-058): Plan in config.yaml, Bericht ohne Änderung, Ausführen mit Sicherung, Verkaufsanfragen, Audit,
Sitzungen, abgelegte Seiten, Kaufunterlagen nur melden, automatisch oder nur Bericht, Kommandozeile (auch alle Mandanten) und API."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.daten import lade_cfg
from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_cli import _scout
from tests.test_haendler import MIT_WEITERGABE
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout import aufbewahrung, datenrechte
from wmscout.audit import AuditSpeicher
from wmscout.datenbank import Datenbank
from wmscout.verkauf import VerkaufSpeicher, pruefe_anfrage

JETZT = datetime(2026, 10, 27, 12)
ALT = (JETZT - timedelta(days=900)).isoformat(timespec="seconds")
FRISCH = (JETZT - timedelta(days=10)).isoformat(timespec="seconds")


def _eintrag(plan, schluessel):
    return next(z for z in plan if z["schluessel"] == schluessel)


def _anfrage(db, tmp_path, aktualisiert: str) -> int:
    v = VerkaufSpeicher(db, tmp_path / "fotos" / "anfragen")
    aid = v.anlegen(pruefe_anfrage(MIT_WEITERGABE, jahr=2026), None, "x")["id"]
    db.con.execute("UPDATE verkaufsanfragen SET aktualisiert_am=? WHERE id=?", (aktualisiert, aid))
    db.con.commit()
    return aid


# ---------------------------------------------------------------- 1. Einstellungen
def test_fristen_in_config_yaml():
    e = aufbewahrung.einstellungen(lade_cfg())
    assert e == {"inserate_anonymisieren_nach_monaten": 6, "verkaufsanfragen_anonymisieren_nach_monaten": 12, "sitzungen_loeschen_nach_tagen": 30,
                 "audit_loeschen_nach_monaten": 24, "ankauf_aufbewahren_jahre": 10, "automatisch": "nur_bericht"}   # QA B4: erst prüfen
    assert all(e[k] == empfohlen for k, (empfohlen, *_) in aufbewahrung.FRISTEN.items())     # Doku = config.yaml


def test_fehlende_eintraege_sind_aus_und_schalter():
    e = aufbewahrung.einstellungen({})
    assert all(e[k] == 0 for k in aufbewahrung.FRISTEN) and e["automatisch"] == "ja"   # alte Konfiguration löscht nichts Neues
    assert aufbewahrung.einstellungen({"datenschutz": {"automatisch": False}})["automatisch"] == "nur_bericht"
    assert aufbewahrung.einstellungen({"datenschutz": {"automatisch": True, "audit_loeschen_nach_monaten": None}})["audit_loeschen_nach_monaten"] == 0


@pytest.mark.parametrize("roh, teil", [
    ({"audit_loeschen_nach_monaten": -1}, "audit_loeschen_nach_monaten"), ({"ankauf_aufbewahren_jahre": "10"}, "ankauf_aufbewahren_jahre"),
    ({"sitzungen_loeschen_nach_tagen": True}, "sitzungen_loeschen_nach_tagen"), ({"audit_loeschen_nach_monate": 24}, "unbekannte Einträge"),
    ({"automatisch": "vielleicht"}, "automatisch"), ("ja", "Abschnitt"),
])
def test_fehleingaben(roh, teil):
    with pytest.raises(ValueError, match=teil):
        aufbewahrung.einstellungen({"datenschutz": roh})
    assert datenrechte.frist_anwenden(None, {"datenschutz": roh}, Path("."), Path(".")) == []     # Wartung bricht nie ab


# ---------------------------------------------------------------- 2. Verkaufsanfragen
def test_anfrage_ohne_ankauf_nach_frist_anonymisiert(cfg, db, tmp_path):
    alt, frisch = _anfrage(db, tmp_path, ALT), _anfrage(db, tmp_path, FRISCH)
    assert aufbewahrung.anfragen_faellig(db, 12, JETZT) == [alt]
    vorher = db.con.execute("SELECT status FROM verkaufsanfragen WHERE id=?", (alt,)).fetchone()[0]
    plan = aufbewahrung.bericht(db, cfg, tmp_path, JETZT)
    assert _eintrag(plan, "verkaufsanfragen_anonymisieren_nach_monaten")["faellig"] == 1
    assert db.con.execute("SELECT name FROM verkaeufer v JOIN verkaufsanfragen a ON a.verkaeufer_id=v.id WHERE a.id=?", (alt,)).fetchone()[0] \
        == "Erika Beispiel"                                                                      # Bericht ändert nichts
    plan = aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    assert _eintrag(plan, "verkaufsanfragen_anonymisieren_nach_monaten")["erledigt"] == 1
    r = db.con.execute("SELECT v.name, v.email, a.beschreibung, a.status FROM verkaeufer v JOIN verkaufsanfragen a ON a.verkaeufer_id=v.id "
                       "WHERE a.id=?", (alt,)).fetchone()
    assert (r["name"], r["email"], r["beschreibung"], r["status"]) == ("(gelöscht)", None, None, vorher)    # Status bleibt
    assert db.con.execute("SELECT ereignis FROM anfrage_verlauf WHERE anfrage_id=? ORDER BY id DESC", (alt,)).fetchone()[0] == "frist"
    assert db.con.execute("SELECT beschreibung FROM verkaufsanfragen WHERE id=?", (frisch,)).fetchone()[0]       # frische bleibt
    assert aufbewahrung.anfragen_faellig(db, 12, JETZT) == []                                                       # idempotent


def test_anfrage_mit_ankauf_oder_offener_besichtigung_bleibt(cfg, db, tmp_path):
    mit_ankauf, mit_termin = _anfrage(db, tmp_path, ALT), _anfrage(db, tmp_path, ALT)
    db.con.execute("INSERT INTO besichtigungen (anzeige_id, anfrage_id, status) VALUES ('a', ?, 'abgeschlossen')", (mit_ankauf,))
    bid = db.con.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.con.execute("INSERT INTO ankaeufe (referenz, herkunft, anfrage_id, besichtigung_id, status, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('AK-1', 'anfrage', ?, ?, 'storniert', 1000, '{}', ?)", (mit_ankauf, bid, ALT))
    db.con.execute("INSERT INTO besichtigungen (anzeige_id, anfrage_id, status) VALUES ('b', ?, 'geplant')", (mit_termin,))
    db.con.commit()
    assert aufbewahrung.anfragen_faellig(db, 12, JETZT) == []


# ---------------------------------------------------------------- 3. Audit, Sitzungen, Kaufunterlagen
def test_audit_alt_geloescht_trigger_bleibt(cfg, db, tmp_path):
    for zeit in (ALT, FRISCH):
        db.con.execute("INSERT INTO audit (zeitpunkt, methode, pfad, status, aktion) VALUES (?, 'GET', '/x', 200, 'lesen')", (zeit,))
    db.con.commit()
    plan = aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT, audit=AuditSpeicher(db))
    assert _eintrag(plan, "audit_loeschen_nach_monaten")["erledigt"] == 1
    zeiten = [r[0] for r in db.con.execute("SELECT zeitpunkt FROM audit ORDER BY id")]
    assert ALT not in zeiten and FRISCH in zeiten
    nachweis = db.con.execute("SELECT * FROM audit WHERE pfad='aufbewahrung'").fetchone()
    assert nachweis["methode"] == "SYSTEM" and "audit_loeschen_nach_monaten:1" in nachweis["objekt"]
    with pytest.raises(sqlite3.DatabaseError, match="nur anfügbar"):
        db.con.execute("DELETE FROM audit")                                                    # nur anfügbar wie vorher
    db.con.rollback()


def test_audit_loeschen_scheitert_ohne_folgen(cfg, db, tmp_path, monkeypatch):
    """Scheitert das Löschen, bleibt der Trigger (eine Transaktion) und die anderen Kategorien laufen weiter."""
    db.con.execute("INSERT INTO audit (zeitpunkt, methode, pfad, status, aktion) VALUES (?, 'GET', '/x', 200, 'lesen')", (ALT,))
    alt = _anfrage(db, tmp_path, ALT)
    db.con.commit()
    echt = db.con

    class Kaputt:
        def __getattr__(self, n):
            return getattr(echt, n)

        def execute(self, sql, *a):
            if sql.startswith("DELETE FROM audit"):
                raise sqlite3.OperationalError("Platte voll")
            return echt.execute(sql, *a)
    monkeypatch.setattr(db, "con", Kaputt())
    plan = aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    monkeypatch.setattr(db, "con", echt)
    assert _eintrag(plan, "audit_loeschen_nach_monaten")["fehler"] == "OperationalError"
    assert _eintrag(plan, "verkaufsanfragen_anonymisieren_nach_monaten")["erledigt"] == 1
    assert db.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='audit_kein_delete'").fetchone()[0] == 1
    assert db.con.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1 and alt


def test_sitzungen_und_kaufunterlagen(cfg, db, team, tmp_path):
    db.con.execute("INSERT INTO sitzungen (token_hash, nutzer_id, ablauf) VALUES ('alt', 1, ?), ('frisch', 1, ?)", (ALT, FRISCH))
    db.con.execute("INSERT INTO besichtigungen (anzeige_id, status) VALUES ('a', 'abgeschlossen'), ('b', 'abgeschlossen')")
    db.con.execute("INSERT INTO ankaeufe (referenz, herkunft, anzeige_id, besichtigung_id, kaufpreis, plan_json, vertrag_am, verkauft_am, erstellt_am) "
                   "VALUES ('AK-2014', 'anzeige', 'a', 1, 1000, '{}', '2014-03-01', '2015-06-01', '2014-03-01'), "
                   "('AK-2016', 'anzeige', 'b', 2, 1000, '{}', '2016-03-01', NULL, '2016-03-01')")
    db.con.execute("UPDATE nutzer SET aktiv=0 WHERE name='Carl'")
    db.con.commit()
    plan = aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    assert _eintrag(plan, "sitzungen_loeschen_nach_tagen")["erledigt"] == 1
    assert [r[0] for r in db.con.execute("SELECT token_hash FROM sitzungen WHERE token_hash IN ('alt', 'frisch')")] == ["frisch"]
    ankauf = _eintrag(plan, "ankauf_aufbewahren_jahre")
    # 2015 (Verkauf) + 10 → ab 1.1.2026 fällig; 2016 + 10 → ab 1.1.2027 – nur gemeldet, nie gelöscht
    assert ankauf["referenzen"] == ["AK-2014"] and ankauf["aktion"] == "melden" and ankauf["erledigt"] == 0
    assert ankauf["gesperrte_zugaenge"] == 1 and db.con.execute("SELECT COUNT(*) FROM ankaeufe").fetchone()[0] == 2


# ---------------------------------------------------------------- 4. Abgelegte Seiten, Sicherung, nur Bericht
def _alt_machen(*pfade):
    zeit = time.time() - 400 * 86400
    for p in pfade:
        os.utime(p, (zeit, zeit))


def test_gespeicherte_seiten_nach_frist(cfg, db, tmp_path):
    imp = Path(cfg["import"]["ordner"])
    tag, neu_tag = imp / "eingelesen" / "2025-01-02", imp / "eingelesen" / datetime.now().date().isoformat()
    for d in (tag, neu_tag, imp / "nicht_erkannt", imp / "eingelesen" / "kein-datum"):
        d.mkdir(parents=True)
    (tag / "a.html").write_text("Anbieter Erika", encoding="utf-8")
    (tag / "a_files").mkdir()
    (tag / "a_files" / "bild.jpg").write_bytes(b"x")
    (neu_tag / "b.html").write_text("neu", encoding="utf-8")
    (imp / "nicht_erkannt" / "c.htm").write_text("alt", encoding="utf-8")
    (imp / "eingelesen" / "kein-datum" / "d.html").write_text("alt", encoding="utf-8")
    (imp / "offen.html").write_text("noch nicht eingelesen", encoding="utf-8")
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "x.html").write_text("nie", encoding="utf-8")
    (imp / "eingelesen" / "verknuepft").symlink_to(fremd, target_is_directory=True)
    _alt_machen(tag / "a.html", imp / "nicht_erkannt" / "c.htm", imp / "eingelesen" / "kein-datum" / "d.html", imp / "offen.html", fremd / "x.html")
    assert len(datenrechte.seiten_faellig(imp, 6)) == 3
    assert datenrechte.seiten_nach_frist(imp, 6) == 3
    assert not tag.exists() and (neu_tag / "b.html").is_file() and (imp / "offen.html").is_file() and (fremd / "x.html").is_file()


def test_sicherung_vor_dem_ausfuehren(cfg, db, tmp_path):
    ordner = Path(cfg["ausgabe"]["datenbank"]).parent / "sicherungen"
    aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    assert not list(ordner.glob("*vor-aufbewahrung*"))                                     # nichts fällig – keine Sicherung
    _anfrage(db, tmp_path, ALT)
    aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    kopie = list(ordner.glob("*vor-aufbewahrung*.sqlite"))
    assert len(kopie) == 1
    alt = sqlite3.connect(kopie[0])
    assert alt.execute("SELECT name FROM verkaeufer").fetchone()[0] == "Erika Beispiel"   # Stand vor dem Löschen
    alt.close()


def test_nur_bericht_beim_start(cfg, db, tmp_path, caplog):
    aid = _anfrage(db, tmp_path, ALT)
    cfg["datenschutz"]["automatisch"] = "nur_bericht"
    with caplog.at_level(logging.WARNING, logger="scout"):
        datenrechte.frist_anwenden(db, cfg, tmp_path, tmp_path / "fotos")
    assert "nur Bericht" in caplog.text and "scout.py datenschutz --ausfuehren" in caplog.text
    assert db.con.execute("SELECT beschreibung FROM verkaufsanfragen WHERE id=?", (aid,)).fetchone()[0]
    cfg["datenschutz"]["automatisch"] = "ja"
    datenrechte.frist_anwenden(db, cfg, tmp_path, tmp_path / "fotos")
    assert db.con.execute("SELECT beschreibung FROM verkaufsanfragen WHERE id=?", (aid,)).fetchone()[0] is None


# ---------------------------------------------------------------- 5. Kommandozeile und API
def test_cli_bericht_ausfuehren_json(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    _anfrage(db, tmp_path, ALT)
    db.con.close()
    r = _scout(cfg, tmp_path, "datenschutz")
    assert r.returncode == 0 and "Bericht (nichts geändert)" in r.stdout and "verkaufsanfragen_anonymisieren_nach_monaten" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "datenschutz", "--ausfuehren")
    assert r.returncode != 0 and "--bestaetigt" in r.stderr
    r = _scout(cfg, tmp_path, "datenschutz", "--ausfuehren", "--bestaetigt", "--json")
    assert r.returncode == 0, r.stderr
    assert _eintrag(json.loads(r.stdout), "verkaufsanfragen_anonymisieren_nach_monaten")["erledigt"] == 1


def test_cli_alle_mandanten(cfg, tmp_path):
    from wmscout import mandanten
    cfg["mandanten"] = {"ordner": str(tmp_path / "mandanten")}
    for k in ("firma-a", "firma-b"):
        mandanten.anlegen(cfg, tmp_path, k, k, f"https://{k}.example.de")
    r = _scout(cfg, tmp_path, "datenschutz", "--alle-mandanten", "--json")
    assert r.returncode == 0, r.stderr
    erg = json.loads(r.stdout)
    assert set(erg["mandanten"]) == {"firma-a", "firma-b"} and erg["fehler"] == []


def test_api_nur_inhaber(markt, db):
    anna, ben, hugo = markt["anna"], markt["ben"], markt["hugo"]
    assert ben("GET", "/api/datenschutz")[0] == 403 and hugo("GET", "/api/datenschutz")[0] == 403
    s, d, _ = anna("GET", "/api/datenschutz")
    assert s == 200 and d["einstellungen"]["audit_loeschen_nach_monaten"] == 24 and len(d["plan"]) == len(aufbewahrung.FRISTEN)
    assert ben("POST", "/api/datenschutz/ausfuehren", {"bestaetigt": True})[0] == 403
    assert anna("POST", "/api/datenschutz/ausfuehren", {})[0] == 400
    s, d, _ = anna("POST", "/api/datenschutz/ausfuehren", {"bestaetigt": True})
    assert s == 200 and {z["schluessel"] for z in d["plan"]} == set(aufbewahrung.FRISTEN)
    assert db.con.execute("SELECT COUNT(*) FROM audit WHERE pfad='/api/datenschutz/ausfuehren' AND status=200").fetchone()[0] == 1


# ---------------------------------------------------------------- 6. Korrekturrunde (QA F10)
def test_sicherung_eigene_rotation_verdraengt_nichts(cfg, db, tmp_path):
    """B1: Fremde Sicherungen (manuell mit Fotos, vor Migrationen) bleiben; höchstens eine Frist-Sicherung je Tag, die letzten drei."""
    ordner = Path(cfg["ausgabe"]["datenbank"]).parent / "sicherungen"
    ordner.mkdir(exist_ok=True)
    fremd = [ordner / n for n in ("anzeigen-sicherung-20260101-120000.sqlite", "anzeigen-sicherung-20260101-120000.fotos.zip",
                                  "anzeigen-sicherung-20260102-120000-vor-v21.sqlite")]
    for p in fremd:
        p.write_bytes(b"x")
    for tag in range(1, 6):
        _anfrage(db, tmp_path, ALT)
        aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", datetime(2026, 11, tag, 12))
        _anfrage(db, tmp_path, ALT)
        aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", datetime(2026, 11, tag, 18))      # derselbe Tag: keine zweite
    eigene = sorted(ordner.glob("*-vor-aufbewahrung.sqlite"))
    assert len(eigene) == aufbewahrung.SICHERUNGEN_BEHALTEN and all(p.is_file() for p in fremd)


def test_tests_schreiben_nie_in_den_projektordner(cfg):
    """B2: Sicherungs- und Import-Ordner der Tests liegen im Temp-Ordner (Kommandozeilen-Tests laufen im Projektordner)."""
    from tests.daten import BASIS
    for pfad in (cfg["sicherung"]["ordner"], cfg["import"]["ordner"]):
        assert not Path(pfad).resolve().is_relative_to(BASIS.resolve())


def test_inserat_mit_ankauf_nie_faellig(cfg, db, team, tmp_path):
    """B3: Ankaufsvorgang ohne Status „gekauft“ – nicht fällig, also auch kein Grund für eine Sicherung bei jedem Lauf."""
    db.speichere_treffer({"id": "k1", "titel": "Knaus", "preis": 30000, "ort": "70173 Stuttgart"}, "Teilintegrierter")
    db.con.execute("UPDATE anzeigen SET details_json='{\"verkaeufer_name\": \"Otto\"}', zuletzt_gesehen=?, status='besichtigung' WHERE id='k1'", (ALT,))
    db.con.execute("INSERT INTO besichtigungen (anzeige_id, status) VALUES ('k1', 'abgeschlossen')")
    db.con.execute("INSERT INTO ankaeufe (referenz, herkunft, anzeige_id, besichtigung_id, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('AK-K1', 'anzeige', 'k1', last_insert_rowid(), 1000, '{}', ?)", (FRISCH,))
    db.con.commit()
    assert datenrechte.inserate_faellig(db, 6, JETZT) == []
    aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    assert not list((Path(cfg["ausgabe"]["datenbank"]).parent / "sicherungen").glob("*vor-aufbewahrung*"))


def test_abgelegte_seite_zaehlt_ab_dem_ablegen(tmp_path):
    """B5: Eine alte, gerade eingelesene Seite ist nicht sofort fällig (Änderungszeit beim Ablegen auf „jetzt“)."""
    from wmscout.eingang.seiten import verschiebe
    alt = tmp_path / "import" / "alt.html"
    alt.parent.mkdir()
    alt.write_text("x", encoding="utf-8")
    _alt_machen(alt)
    verschiebe(alt, tmp_path / "import" / "nicht_erkannt")
    assert datenrechte.seiten_faellig(tmp_path / "import", 6) == []


def test_automatik_schreibt_nachweis(cfg, db, tmp_path):
    """B6: auch beim Start bzw. nach Läufen (automatisch: ja) ein Nachweis im Audit-Protokoll – ohne Inhalte."""
    _anfrage(db, tmp_path, ALT)
    cfg["datenschutz"]["automatisch"] = "ja"
    datenrechte.frist_anwenden(db, cfg, tmp_path, tmp_path / "fotos")
    z = db.con.execute("SELECT objekt FROM audit WHERE pfad='aufbewahrung'").fetchone()
    assert z and "verkaufsanfragen_anonymisieren_nach_monaten:1" in z[0] and "Erika" not in z[0]


def test_anfrage_wieder_faellig_und_auktion_und_storno(cfg, db, tmp_path):
    """B8: neue Angaben nach der Löschung werden wieder fällig; B10: laufende/unentschiedene Auktion nie; B9: Storno zählt für die Frist."""
    aid = _anfrage(db, tmp_path, ALT)
    aufbewahrung.ausfuehren(db, cfg, tmp_path, tmp_path / "fotos", JETZT)
    assert aufbewahrung.anfragen_faellig(db, 12, JETZT) == []
    db.con.execute("UPDATE verkaufsanfragen SET notiz='Rückruf 0170 1234567', aktualisiert_am=? WHERE id=?", ("2026-11-01T10:00:00", aid))
    db.con.commit()
    assert aufbewahrung.anfragen_faellig(db, 12, datetime(2028, 1, 1)) == [aid]
    mit_auktion = _anfrage(db, tmp_path, ALT)
    db.con.execute("INSERT INTO auktionen (anfrage_id, status, startpreis, schritt, start_utc, ende_utc) VALUES (?, 'beendet', 1, 1, '2025-01-01T00:00:00Z', '2025-01-02T00:00:00Z')",
                   (mit_auktion,))
    db.con.execute("INSERT INTO besichtigungen (anzeige_id, status) VALUES ('s', 'abgeschlossen')")
    db.con.execute("INSERT INTO ankaeufe (id, referenz, herkunft, anzeige_id, besichtigung_id, kaufpreis, plan_json, status, erstellt_am) "
                   "VALUES (77, 'AK-S', 'anzeige', 's', last_insert_rowid(), 1000, '{}', 'storniert', '2014-01-01')")
    db.con.execute("INSERT INTO ankauf_verlauf (ankauf_id, zeitpunkt, ereignis) VALUES (77, '2018-05-01T10:00:00', 'storno')")
    db.con.commit()
    assert mit_auktion not in aufbewahrung.anfragen_faellig(db, 12, JETZT)
    assert aufbewahrung.ankaeufe_faellig(db, 10, datetime(2028, 6, 1)) == []                     # 2018 + 10 → erst ab 2029
    assert aufbewahrung.ankaeufe_faellig(db, 10, datetime(2029, 1, 1)) == ["AK-S"]


def test_mandanten_getrennt_und_fehler_isoliert(cfg, tmp_path):
    """B7: ein kaputter Mandant hält die anderen nicht auf; jeder Mandant nur mit seinen eigenen Daten."""
    from tests.daten import BASIS
    from wmscout import mandanten
    wurzel = tmp_path / "mandanten"
    cfg["mandanten"] = {"ordner": str(wurzel)}
    for k in ("firma-a", "firma-b"):
        mandanten.anlegen(cfg, BASIS, k, k, f"https://{k}.example.de")
    a = mandanten.mandant_cfg(cfg, BASIS, "firma-a")
    db = Datenbank(str(BASIS / a["ausgabe"]["datenbank"]))
    _anfrage(db, tmp_path, ALT)
    db.con.close()
    (wurzel / "firma-c").mkdir()
    (wurzel / "firma-c" / "mandant.yaml").write_text("datenschutz: kaputt\n", encoding="utf-8")
    r = _scout(cfg, tmp_path, "datenschutz", "--alle-mandanten", "--ausfuehren", "--bestaetigt", "--json")
    erg = json.loads(r.stdout)
    assert r.returncode != 0 and "firma-c" in r.stderr and set(erg["mandanten"]) == {"firma-a", "firma-b"}
    assert _eintrag(erg["mandanten"]["firma-a"], "verkaufsanfragen_anonymisieren_nach_monaten")["erledigt"] == 1
    assert _eintrag(erg["mandanten"]["firma-b"], "verkaufsanfragen_anonymisieren_nach_monaten")["faellig"] == 0


def test_statusseite_zeigt_fristen(markt):
    s, html, _ = markt["anna"]("GET", "/status")
    assert s == 200 and 'id="datenschutz"' in html and "nur Bericht" in html and "scout.py datenschutz --ausfuehren" in html
    assert "scout.py datenschutz --ausfuehren" not in markt["ben"]("GET", "/status")[1]                  # Ausführen nur für den Inhaber
