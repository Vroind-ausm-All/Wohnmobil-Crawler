"""Phase-7-Restpunkte: P7-01b (nach dem Anonymisieren neu entstandene Personendaten wieder fällig), P7-04b (Dienste schreiben nur
ins Systemprotokoll), Abhängigkeit soupsieve ohne bekannte Schwachstelle."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

import scout
from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import treffer
from wmscout.datenrechte import inserat_anonymisieren, inserate_faellig
from wmscout.team import TeamSpeicher

ALT = (datetime.now() - timedelta(days=800)).isoformat(timespec="seconds")
ANON = (datetime.now() - timedelta(days=700)).isoformat(timespec="seconds")      # vor der Frist (12 Monate) anonymisiert
NEU_ALT = (datetime.now() - timedelta(days=600)).isoformat(timespec="seconds")   # danach entstanden, inzwischen ebenfalls älter als die Frist


def _anonymisiert(db, tmp_path, ad="q1"):
    """Altes Inserat mit Personendaten, vor 700 Tagen anonymisiert."""
    db.speichere_treffer(treffer(ad, ort="80331 München", km=150000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, notiz='Name Erika' WHERE id=?", (ALT, ad))
    db.con.commit()
    inserat_anonymisieren(db, tmp_path, ad)
    details = json.loads(db.con.execute("SELECT details_json FROM anzeigen WHERE id=?", (ad,)).fetchone()[0])
    details["anonymisiert_am"] = ANON
    db.con.execute("UPDATE anzeigen SET details_json=? WHERE id=?", (json.dumps(details), ad))
    db.con.commit()
    assert ad not in inserate_faellig(db, 12)
    return ad


# ---------------------------------------------------------------- P7-01b
def test_besichtigung_nach_anonymisierung_erst_nach_frist_faellig(db, tmp_path):
    ad = _anonymisiert(db, tmp_path)
    t = TeamSpeicher(db, tmp_path / "fotos")
    bid = t.besichtigung_anlegen(ad, {"fahrzeug": "Knaus", "verkaeufer": "Herr Muster"}, None, "Musterweg 1", None, None)
    db.con.commit()
    assert ad not in inserate_faellig(db, 12)                       # offene Besichtigung: nie fällig (wie bisher)
    t.besichtigung_abschliessen(bid, {}, None, status="abgebrochen")
    db.con.commit()
    assert ad not in inserate_faellig(db, 12)                       # heute abgeschlossen: noch keine Bereinigung (QA B2)
    db.con.execute("UPDATE besichtigungen SET erstellt_am=?, geaendert_am=? WHERE id=?", (NEU_ALT, NEU_ALT, bid))
    db.con.commit()
    assert ad in inserate_faellig(db, 12)                           # nach Anonymisierung entstanden und älter als die Frist
    inserat_anonymisieren(db, tmp_path, ad)
    b = db.con.execute("SELECT adresse, basis_json FROM besichtigungen WHERE id=?", (bid,)).fetchone()
    assert b["adresse"] is None and "Muster" not in b["basis_json"]  # tatsächlich bereinigt
    assert ad not in inserate_faellig(db, 12)                       # kein Dauer-„fällig“


def test_kontakttext_nach_anonymisierung_wird_entfernt(db, tmp_path):
    ad = _anonymisiert(db, tmp_path)
    vorher_text = db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (ad,)).fetchone()[0]
    db.nachgefasst(ad, "Hallo Herr Muster, Tel. 0170 1234567")
    assert ad not in inserate_faellig(db, 12)                       # frisch: noch nicht fällig (QA B2)
    db.con.execute("UPDATE kontakte SET vorbereitet_am=? WHERE anzeige_id=? AND text LIKE '%0170%'", (NEU_ALT, ad))
    db.con.commit()
    assert ad in inserate_faellig(db, 12)
    inserat_anonymisieren(db, tmp_path, ad)
    assert not db.con.execute("SELECT 1 FROM kontakte WHERE anzeige_id=? AND text LIKE '%0170%'", (ad,)).fetchone()   # QA B1
    jetzt_text = db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (ad,)).fetchone()[0]
    assert "0170" not in (jetzt_text or "") and (jetzt_text or "") == (vorher_text or "")[:len(jetzt_text or "")]
    assert ad not in inserate_faellig(db, 12)


def test_kontakt_vor_anonymisierung_vorbereitet_danach_bestaetigt(db, tmp_path):
    ad = _anonymisiert(db, tmp_path)
    db.nachgefasst(ad, "Rückruf Herr Muster 0170 7654321")
    db.con.execute("UPDATE kontakte SET vorbereitet_am=?, bestaetigt_am=? WHERE anzeige_id=? AND text LIKE '%7654321%'",
                   (ALT, NEU_ALT, ad))
    db.con.commit()
    assert ad in inserate_faellig(db, 12)                           # Bestätigung nach der Anonymisierung zählt
    inserat_anonymisieren(db, tmp_path, ad)
    assert not db.con.execute("SELECT 1 FROM kontakte WHERE anzeige_id=? AND text LIKE '%7654321%'", (ad,)).fetchone()


def test_ohne_anonymisierung_und_kaputtes_json_unveraendert(db, tmp_path):
    db.speichere_treffer(treffer("q2", ort="80331 München", km=150000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, notiz='x', details_json='{kaputt' WHERE id='q2'", (ALT,))
    db.con.commit()
    assert "q2" in inserate_faellig(db, 12)                         # kaputtes JSON: keine Ausnahme, Verhalten wie bisher


# ---------------------------------------------------------------- P7-04b
def test_protokoll_nur_konsole(cfg, monkeypatch):
    monkeypatch.delenv(scout.PROTOKOLL_NUR_KONSOLE, raising=False)
    standard = scout.protokoll_handler(cfg)
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in standard)
    for h in standard:
        h.close()
    monkeypatch.setenv(scout.PROTOKOLL_NUR_KONSOLE, "1")
    nur = scout.protokoll_handler(cfg)
    assert len(nur) == 1 and type(nur[0]) is logging.StreamHandler


def test_dienste_setzen_nur_konsole():
    for unit in (BASIS / "betrieb" / "systemd").glob("*.service"):
        assert "Environment=SCOUT_PROTOKOLL_NUR_KONSOLE=1" in unit.read_text(encoding="utf-8"), unit.name


# ---------------------------------------------------------------- Abhängigkeiten
def test_soupsieve_ohne_bekannte_luecke():
    for datei in ("requirements.txt", "requirements-dev.txt"):
        version = re.search(r"^soupsieve==(\d+)\.", (BASIS / datei).read_text(encoding="utf-8"), re.M).group(1)
        assert int(version) >= 4, datei                             # CVE-2026-126190 in 3.0.3, behoben ab 4.0.0


# ---------------------------------------------------------------- QA-Nachprüfung P7-01b (N1–N3)
ANSCHREIBEN = "Guten Tag, Angebot 20000 Euro"


def _mit_anschreiben(db, tmp_path, ad="p1"):
    """Anschreibentext mit Länge > 0 (der erste Test hatte Länge 0 und prüfte die Kürzung damit nicht wirklich)."""
    db.speichere_treffer(treffer(ad, ort="80331 München", km=150000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, anschreiben_text=? WHERE id=?", (ALT, ANSCHREIBEN, ad))
    db.con.commit()
    inserat_anonymisieren(db, tmp_path, ad)
    d = json.loads(db.con.execute("SELECT details_json FROM anzeigen WHERE id=?", (ad,)).fetchone()[0])
    assert d["anonymisiert_anschreiben_laenge"] == len(ANSCHREIBEN) and d["anonymisiert_anschreiben_hash"]
    d["anonymisiert_am"] = ANON
    db.con.execute("UPDATE anzeigen SET details_json=? WHERE id=?", (json.dumps(d), ad))
    db.con.commit()
    return ad


def _nachfassen_und_erneut(db, tmp_path, ad):
    db.nachgefasst(ad, "Hallo Frau Muster, Tel. 0170 1234567")
    db.con.execute("UPDATE kontakte SET vorbereitet_am=? WHERE anzeige_id=?", (NEU_ALT, ad))
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, status_am=NULL, kontaktiert_am=NULL WHERE id=?", (ALT, ad))
    db.con.commit()
    assert ad in inserate_faellig(db, 12)
    inserat_anonymisieren(db, tmp_path, ad)
    assert ad not in inserate_faellig(db, 12)
    return db.con.execute("SELECT anschreiben_text FROM anzeigen WHERE id=?", (ad,)).fetchone()[0]


def test_kuerzung_mit_laenge_und_neu_einlesen(db, tmp_path):
    """N1: erneutes Einlesen der Details zwischen den Anonymisierungen verliert den gespeicherten Stand nicht; gekürzt wird auf den
    alten, bereinigten Text (Länge > 0)."""
    ad = _mit_anschreiben(db, tmp_path)
    db.speichere_details(ad, {"details": {"verkaeufer_name": "Erika Muster", "ausstattung": ["x"]}})
    d = json.loads(db.con.execute("SELECT details_json FROM anzeigen WHERE id=?", (ad,)).fetchone()[0])
    assert "verkaeufer_name" not in d and d["anonymisiert_anschreiben_laenge"] == len(ANSCHREIBEN)
    assert _nachfassen_und_erneut(db, tmp_path, ad) == ANSCHREIBEN


def test_ersetzter_anschreibentext_wird_geleert(db, tmp_path):
    """N2: wurde der Text ersetzt statt ergänzt, ist auch sein Anfang nicht bereinigt – er wird beim erneuten Anonymisieren geleert."""
    ad = _mit_anschreiben(db, tmp_path)
    db.con.execute("UPDATE anzeigen SET anschreiben_text=? WHERE id=?", ("Frau Muster, ich rufe Sie unter 0170 9876543 an. " * 2, ad))
    db.con.commit()
    assert _nachfassen_und_erneut(db, tmp_path, ad) is None


def test_vor_anonymisierung_angelegte_besichtigung_danach_abgeschlossen(db, tmp_path):
    """N3: eine vor dem Anonymisieren angelegte Besichtigung, die danach mit neuen Daten abgeschlossen wird, wird wieder fällig."""
    db.speichere_treffer(treffer("p3", ort="80331 München", km=150000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=?, notiz='Name Erika' WHERE id='p3'", (ALT,))
    db.con.commit()
    t = TeamSpeicher(db, tmp_path / "fotos")
    bid = t.besichtigung_anlegen("p3", {"fahrzeug": "Knaus"}, None, None, None, None)
    db.con.execute("UPDATE besichtigungen SET erstellt_am=?, geaendert_am=? WHERE id=?", (ALT, ALT, bid))
    db.con.commit()
    inserat_anonymisieren(db, tmp_path, "p3")
    d = json.loads(db.con.execute("SELECT details_json FROM anzeigen WHERE id='p3'").fetchone()[0])
    d["anonymisiert_am"] = ANON
    db.con.execute("UPDATE anzeigen SET details_json=? WHERE id='p3'", (json.dumps(d),))
    db.con.commit()
    t.besichtigung_abschliessen(bid, {}, None, status="abgebrochen")
    db.con.execute("UPDATE besichtigungen SET geaendert_am=? WHERE id=?", (NEU_ALT, bid))
    db.con.commit()
    assert "p3" in inserate_faellig(db, 12)
