"""Datensicherung und Wiederherstellung: Backup-API, Integritätsprüfung, Fotos, Aufbewahrung, Bestätigung."""
import hashlib
import os
import pathlib
import sqlite3
import time
import zipfile
from datetime import datetime as echte_zeit
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from tests.test_cli import _scout
from wmscout import sicherung as modul
from wmscout.datenbank import Datenbank
from wmscout.sicherung import SicherungsFehler, oeffne_lesend, pruefe_behalten, sicherungen, sichere, wiederherstellen
from wmscout.team import TeamSpeicher

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def abbild(db_pfad) -> dict:
    """Alle Tabellen mit allen Zeilen (sortiert) – Vergleichsgrundlage vorher/nachher."""
    con = sqlite3.connect(db_pfad)
    try:
        tabellen = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: sorted(map(repr, con.execute(f"SELECT * FROM {t}").fetchall())) for t in tabellen}
    finally:
        con.close()


def fotos_inhalt(ordner) -> dict:
    return {p.relative_to(ordner).as_posix(): p.read_bytes() for p in sorted(ordner.rglob("*")) if p.is_file()}


@pytest.fixture
def bestand(tmp_path):
    """Datenbank mit Inseraten, Status/Notiz, Nutzer, Besichtigung und Foto."""
    pfad, fotos = tmp_path / "daten" / "anzeigen.sqlite", tmp_path / "daten" / "fotos"
    db = Datenbank(str(pfad))
    for i in range(5):
        db.speichere_treffer({"id": f"id{i}", "url": f"u{i}", "titel": f"Knaus {i}", "preis": 30000 + i * 1000}, "Alkoven")
    db.setze_status("id1", "kontaktiert", notiz="Verkäufer Müller", text="Hallo", betrag=28000)
    team = TeamSpeicher(db, fotos)
    uid = team.nutzer_anlegen("Anna", "sicher1234", "inhaber", "+491701234567")
    bid = team.besichtigung_anlegen("id1", {"angebot": 28000}, "2026-11-01T10:00", "Musterstr. 1", uid, uid)
    team.foto_speichern(bid, JPEG, "dach", uid)
    db.con.close()
    return pfad, fotos, tmp_path / "sicherungen"


def test_sicherung_und_wiederherstellung_identisch(bestand):
    pfad, fotos, ziel = bestand
    vorher, fotos_vorher = abbild(pfad), fotos_inhalt(fotos)
    assert vorher["anzeigen"] and vorher["nutzer"] and vorher["besichtigungen"] and vorher["fotos"] and fotos_vorher

    kopie = sichere(pfad, ziel, fotos)
    assert kopie.is_file() and kopie.with_name(kopie.name[:-7] + ".fotos.zip").is_file()
    assert sqlite3.connect(kopie).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert abbild(kopie) == vorher

    # Datenbank verändern und Fotos verlieren
    con = sqlite3.connect(pfad)
    con.execute("DELETE FROM anzeigen WHERE id IN ('id0', 'id1')")
    con.execute("UPDATE anzeigen SET notiz='kaputt'")
    con.execute("DROP TABLE nutzer")
    con.commit()
    con.close()
    for f in fotos.rglob("*.jpg"):
        f.unlink()
    assert abbild(pfad) != vorher

    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == vorher
    assert fotos_inhalt(fotos) == fotos_vorher and erg.fotos_wiederhergestellt
    assert erg.sicherung_vorher and erg.sicherung_vorher.is_file()          # Stand vor der Wiederherstellung gesichert
    assert "kaputt" in str(abbild(erg.sicherung_vorher)["anzeigen"])


def test_wiederherstellung_nach_beschaedigung_der_datenbank(bestand):
    pfad, fotos, ziel = bestand
    vorher = abbild(pfad)
    kopie = sichere(pfad, ziel, fotos)
    pfad.write_bytes(b"das ist keine datenbank" * 500)                       # Datei zerstört
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == vorher
    assert erg.sicherung_vorher.read_bytes().startswith(b"das ist keine")      # Rohkopie des defekten Stands bleibt erhalten


def test_ohne_bestaetigung_keine_wiederherstellung(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    sqlite3.connect(pfad).execute("DELETE FROM anzeigen").connection.commit()
    geaendert = abbild(pfad)
    with pytest.raises(SicherungsFehler, match="--bestaetigt"):
        wiederherstellen(kopie, pfad, bestaetigt=False, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == geaendert
    assert len(sicherungen(ziel, "anzeigen")) == 1                             # auch keine Zusatz-Sicherung


def test_defekte_sicherung_wird_nicht_eingespielt(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    daten = bytearray(kopie.read_bytes())
    daten[:200] = b"\x00" * 200                                                # Kopf zerstören
    kopie.write_bytes(bytes(daten))
    vorher = abbild(pfad)
    with pytest.raises(SicherungsFehler):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == vorher
    assert not list(pfad.parent.glob(".*teil"))


def test_sicherung_einer_defekten_datenbank_wird_verworfen(bestand):
    pfad, fotos, ziel = bestand
    pfad.write_bytes(b"x" * 4096)
    with pytest.raises(SicherungsFehler):
        sichere(pfad, ziel, fotos)
    assert not list(ziel.iterdir())                                            # nichts Halbfertiges zurückgeblieben


def test_aufbewahrung_loescht_nur_eigene_alte_sicherungen(bestand):
    pfad, fotos, ziel = bestand
    ziel.mkdir()
    fremd = [ziel / "notiz.txt", ziel / "anzeigen-sicherung-handgemacht.sqlite", ziel / "andere-sicherung-20200101-000000.sqlite",
             ziel / "anzeigen-defekt-20200101-000000.sqlite.defekt", ziel / "anzeigen.sqlite"]
    for f in fremd:
        f.write_bytes(b"wichtig")
    gemacht = [sichere(pfad, ziel, fotos, behalten=4) for _ in range(7)]       # alle in (fast) derselben Sekunde
    uebrig = sicherungen(ziel, "anzeigen")
    assert uebrig == gemacht[-4:]                                              # die letzten 4, Reihenfolge stimmt
    assert all(f.read_bytes() == b"wichtig" for f in fremd)
    for alt in gemacht[:-4]:
        assert not alt.exists() and not alt.with_name(alt.name[:-7] + ".fotos.zip").exists()
    for neu in gemacht[-4:]:
        assert neu.with_name(neu.name[:-7] + ".fotos.zip").exists()
    with pytest.raises(ValueError):
        sichere(pfad, ziel, behalten=0)


def test_sicherung_ohne_fotos_und_fehlende_datenbank(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, tmp_path / "gibtsnicht")
    assert not kopie.with_name(kopie.name[:-7] + ".fotos.zip").exists()
    with pytest.raises(SicherungsFehler):
        sichere(tmp_path / "fehlt.sqlite", ziel)


def test_sicherung_bei_geoeffneter_datenbank(bestand):
    pfad, fotos, ziel = bestand
    db = Datenbank(str(pfad))
    db.con.execute("UPDATE anzeigen SET notiz='ungespeichert'")               # offene Transaktion, nicht committet
    kopie = sichere(pfad, ziel)
    assert "ungespeichert" not in str(abbild(kopie)["anzeigen"])               # Kopie ist konsistent (nur Festgeschriebenes)
    db.con.rollback()
    db.con.close()


def test_cli_sichern_und_wiederherstellen(cfg, tmp_path):
    cfg["sicherung"] = {"ordner": str(tmp_path / "sich"), "behalten": 2}
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    db.speichere_treffer({"id": "a1", "url": "u", "titel": "Hymer", "preis": 41000}, "Alkoven")
    db.con.close()
    r = _scout(cfg, tmp_path, "sichern")
    assert r.returncode == 0, r.stderr
    kopie = sicherungen(tmp_path / "sich", "anzeigen")[0]
    assert kopie.name in r.stdout
    sqlite3.connect(cfg["ausgabe"]["datenbank"]).execute("DELETE FROM anzeigen").connection.commit()

    r = _scout(cfg, tmp_path, "wiederherstellen", kopie.name)
    assert r.returncode != 0 and "--bestaetigt" in (r.stdout + r.stderr)
    assert sqlite3.connect(cfg["ausgabe"]["datenbank"]).execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0
    r = _scout(cfg, tmp_path, "wiederherstellen", kopie.name, "--bestaetigt")
    assert r.returncode == 0, r.stderr
    assert sqlite3.connect(cfg["ausgabe"]["datenbank"]).execute("SELECT titel FROM anzeigen").fetchall() == [("Hymer",)]


# ---------- Korrekturrunde 1: K1 (Quelle darf nie verschwinden), M1-M4, N1, Mutationslücken ----------

def hash_datei(pfad) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def dateien(ordner) -> set[str]:
    return {p.relative_to(ordner).as_posix() for p in ordner.rglob("*")} if ordner.exists() else set()


def beschaedige_index(pfad):
    """Lesbar, aber integritätsverletzt: Index aus dem Schema entfernen, seine Seiten bleiben verwaist (Tabellen bleiben lesbar)."""
    con = sqlite3.connect(pfad)
    con.executemany("INSERT INTO anzeigen (id, titel, zuletzt_gesehen) VALUES (?,?,?)", [(f"z{i}", "x", f"2026-01-01T00:{i % 60:02d}:{i}") for i in range(300)])
    con.commit()
    con.execute("PRAGMA writable_schema=ON")
    con.execute("DELETE FROM sqlite_master WHERE name='idx_zuletzt'")
    con.commit()
    con.close()
    con = sqlite3.connect(pfad)
    assert con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] > 300                      # Tabelle weiterhin lesbar
    assert con.execute("PRAGMA integrity_check").fetchone()[0] != "ok"                           # ... aber nicht integer
    con.close()


def test_k1_aelteste_sicherung_bei_voller_aufbewahrung_wird_zurueckgespielt(bestand):
    pfad, fotos, ziel = bestand
    liste = []
    for i in range(3):                                                         # drei unterscheidbare Stände, behalten=3 (voll)
        con = sqlite3.connect(pfad)
        con.execute("UPDATE anzeigen SET notiz=?", (f"stand{i}",))
        con.commit()
        con.close()
        liste.append(sichere(pfad, ziel, fotos, behalten=3))
    aelteste = liste[0]
    stand0 = abbild(aelteste)
    assert "stand0" in str(stand0["anzeigen"]) and len(sicherungen(ziel, "anzeigen")) == 3

    erg = wiederherstellen(aelteste, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, behalten=3)
    assert aelteste.is_file() and aelteste.with_name(aelteste.name[:-7] + ".fotos.zip").is_file()    # Quelle bleibt erhalten
    assert abbild(pfad) == stand0 and "stand0" in str(abbild(pfad)["anzeigen"])                       # und ist wirklich eingespielt
    assert abbild(pfad)["nutzer"] and sqlite3.connect(pfad).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert erg.sicherung_vorher.is_file() and "stand2" in str(abbild(erg.sicherung_vorher)["anzeigen"])
    uebrig = sicherungen(ziel, "anzeigen")
    assert uebrig == [*liste, erg.sicherung_vorher]                                                 # 3 neueste (voll) + geschützte Quelle
    assert aelteste.with_name(aelteste.name[:-7] + ".fotos.zip").is_file()

    erg2 = wiederherstellen(aelteste, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, behalten=2)
    assert sicherungen(ziel, "anzeigen") == [aelteste, erg.sicherung_vorher, erg2.sicherung_vorher]  # 2 neueste + Quelle, Rest weg


def test_k1_behalten_1_loescht_quelle_nicht(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos, behalten=1)
    vorher = abbild(pfad)
    con = sqlite3.connect(pfad)
    con.execute("DELETE FROM anzeigen WHERE id='id0'")
    con.commit()
    con.close()
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, behalten=1)
    assert kopie.is_file() and abbild(pfad) == vorher
    assert erg.sicherung_vorher.is_file()


def test_aufbewahrung_laeuft_erst_nach_erfolgreicher_wiederherstellung(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopien = [sichere(pfad, ziel, behalten=5) for _ in range(3)]
    monkeypatch.setattr(modul, "_integritaet", lambda *a, **k: (_ for _ in ()).throw(SicherungsFehler("Absicht")))
    with pytest.raises(SicherungsFehler):
        wiederherstellen(kopien[0], pfad, bestaetigt=True, ziel_ordner=ziel, behalten=1)
    assert sicherungen(ziel, "anzeigen") == kopien                              # nichts aufgeräumt, nichts angelegt


def test_fehlende_quelle_fehler_und_keine_leere_datenbank(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    fest, vorher = hash_datei(pfad), dateien(tmp_path)
    weg = ziel / "anzeigen-sicherung-20200101-000000.sqlite"
    with pytest.raises(SicherungsFehler, match="nicht gefunden"):
        wiederherstellen(weg, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    # Quelle verschwindet erst nach der is_file-Prüfung: lesende Öffnung legt keine Datei an
    with pytest.raises(sqlite3.Error):
        oeffne_lesend(weg).execute("SELECT 1")
    with pytest.raises(SicherungsFehler):
        modul._kopiere_db(weg, tmp_path / "ziel.sqlite")
    assert not weg.exists() and not (tmp_path / "ziel.sqlite").exists()
    with pytest.raises(SicherungsFehler, match="nicht gefunden"):
        sichere(tmp_path / "fehlt.sqlite", ziel)
    assert not (tmp_path / "fehlt.sqlite").exists()
    assert hash_datei(pfad) == fest and dateien(tmp_path) == vorher


def test_quelle_verschwindet_waehrend_der_wiederherstellung(bestand, tmp_path, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    fest = hash_datei(pfad)
    echt = modul._kopiere_db

    def loesche_dann_kopiere(quelle, zielpfad):
        quelle.unlink()                                                         # genau der K1-Fall: Datei ist plötzlich weg
        echt(quelle, zielpfad)

    monkeypatch.setattr(modul, "_kopiere_db", loesche_dann_kopiere)
    with pytest.raises(SicherungsFehler):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert not kopie.exists() and hash_datei(pfad) == fest                      # keine leere Datenbank eingesetzt
    assert not list(pfad.parent.glob(".*teil"))


def test_m1_fremde_oder_zu_neue_datei_wird_nicht_eingespielt(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    fest = hash_datei(pfad)
    fremd = tmp_path / "fremd.sqlite"
    con = sqlite3.connect(fremd)
    con.execute("CREATE TABLE etwas (x)")
    con.commit()
    con.close()
    leer = tmp_path / "leer.sqlite"
    sqlite3.connect(leer).close()
    neu = sichere(pfad, ziel)
    con = sqlite3.connect(neu)
    con.execute("INSERT INTO schema_version VALUES (99, 'x')")
    con.commit()
    con.close()
    for quelle, muster in ((fremd, "keine Wohnmobil-Scout-Datenbank"), (leer, "keine Wohnmobil-Scout-Datenbank|nicht als"),
                           (neu, "Schemaversion 99")):
        with pytest.raises(SicherungsFehler, match=muster):
            wiederherstellen(quelle, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert hash_datei(pfad) == fest
    assert len(sicherungen(ziel, "anzeigen")) == 1                              # keine "vor-wiederherstellung"-Sicherung angelegt


def test_m2_gesperrte_datenbank_bricht_ab_ohne_aenderung(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    fest, vorher = hash_datei(pfad), dateien(pfad.parent) | dateien(ziel)
    schreiber = sqlite3.connect(pfad, isolation_level=None)
    schreiber.execute("BEGIN IMMEDIATE")                                        # läuft noch: hält die Schreibsperre
    try:
        with pytest.raises(SicherungsFehler, match="in Benutzung"):
            wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, sperr_timeout=0.2)
    finally:
        schreiber.execute("ROLLBACK")
        schreiber.close()
    assert hash_datei(pfad) == fest
    assert dateien(pfad.parent) | dateien(ziel) == vorher                       # kein Rest: keine Zusatz-Sicherung, keine .teil-Datei
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)    # ohne Sperre geht es


def test_m2_reste_der_alten_datenbank_werden_erst_beim_austausch_entfernt(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    reste = [pfad.with_name(pfad.name + e) for e in ("-wal", "-shm", "-journal")]
    schreiber = sqlite3.connect(pfad, isolation_level=None)
    schreiber.execute("BEGIN IMMEDIATE")
    try:
        for r in reste[1:]:                    # (eine -wal-Datei würde SQLite selbst als WAL-Betrieb deuten und die Sperre umgehen)
            r.write_bytes(b"rest der alten datenbank")
        with pytest.raises(SicherungsFehler):
            wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, sperr_timeout=0.2)
        assert all(r.read_bytes() == b"rest der alten datenbank" for r in reste[1:])    # bei Abbruch unangetastet
    finally:
        schreiber.execute("ROLLBACK")
        schreiber.close()
    for r in reste:
        r.write_bytes(b"rest der alten datenbank")
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
    assert not any(r.exists() for r in reste)                                    # M12: nach dem Austausch passt kein Rest zur neuen DB
    assert sqlite3.connect(pfad).execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def _foto_zip_ersetzen(kopie, eintraege: dict[str, bytes]):
    z = kopie.with_name(kopie.name[:-7] + ".fotos.zip")
    with zipfile.ZipFile(z, "w") as zf:
        for name, inhalt in eintraege.items():
            zf.writestr(zipfile.ZipInfo(name), inhalt)


@pytest.mark.parametrize("name", ["../boese.jpg", "unter/../../boese.jpg", "/abs-boese.jpg"])
def test_m7_zip_slip_wird_abgewiesen(bestand, tmp_path, name):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    _foto_zip_ersetzen(kopie, {name: b"boese"})
    con = sqlite3.connect(pfad)
    con.execute("DELETE FROM anzeigen WHERE id='id0'")
    con.commit()
    con.close()
    fest, fotos_vorher, vorher = hash_datei(pfad), fotos_inhalt(fotos), dateien(tmp_path)
    with pytest.raises(SicherungsFehler, match="unzulässige Pfade"):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert hash_datei(pfad) == fest and fotos_inhalt(fotos) == fotos_vorher       # auch die Datenbank blieb unverändert
    assert not any("boese" in p for p in dateien(tmp_path)) and not pathlib.Path("/abs-boese.jpg").exists()
    assert not list(tmp_path.rglob("*.teil")) and not [p for p in dateien(tmp_path) if "vor-wiederherstellung" in p]
    assert dateien(tmp_path) == vorher


def test_m8_wiederherstellung_aus_integritaetsverletzter_sicherung_wird_abgewiesen(bestand):
    pfad, fotos, ziel = bestand
    beschaedige_index(pfad)
    schlecht = ziel / "anzeigen-sicherung-20200101-000000.sqlite"
    ziel.mkdir(parents=True, exist_ok=True)
    schlecht.write_bytes(pfad.read_bytes())                                      # lesbare, aber nicht integre Datei
    gut = bestand[0].parent / "gut.sqlite"
    gut.write_bytes(b"")                                                         # Platzhalter, damit die Live-DB getauscht wird
    gut.unlink()
    live = pfad.parent / "live.sqlite"
    Datenbank(str(live)).con.close()
    fest = hash_datei(live)
    with pytest.raises(SicherungsFehler, match="Integritätsprüfung"):
        wiederherstellen(schlecht, live, bestaetigt=True, ziel_ordner=ziel)
    assert hash_datei(live) == fest and not list(live.parent.glob(".*teil"))


def test_m9_sicherung_einer_integritaetsverletzten_datenbank_wird_verworfen(bestand):
    pfad, fotos, ziel = bestand
    beschaedige_index(pfad)
    with pytest.raises(SicherungsFehler, match="Integritätsprüfung"):
        sichere(pfad, ziel, fotos)
    assert not ziel.exists() or not list(ziel.iterdir())                         # weder Kopie noch .teil-Rest


def test_defekte_live_datenbank_bei_wiederherstellung_wird_roh_gesichert(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    beschaedige_index(pfad)                                                      # Integrität verletzt -> Rohkopie statt Sicherung
    roh_inhalt = pfad.read_bytes()
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == vorher and erg.sicherung_vorher.name.endswith(".sqlite.defekt")
    assert erg.sicherung_vorher.read_bytes() == roh_inhalt


def test_m4_fotoschritt_scheitert_meldet_klar_und_datenbank_bleibt_wiederhergestellt(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    sqlite3.connect(pfad).execute("DELETE FROM anzeigen").connection.commit()
    fotos_jetzt = fotos_inhalt(fotos)
    echt = pathlib.Path.rename

    def rename(self, ziel_):
        if self.name.endswith(".wiederherstellung.teil"):
            raise OSError("simuliert: Zugriff verweigert")
        return echt(self, ziel_)

    monkeypatch.setattr(pathlib.Path, "rename", rename)
    with pytest.raises(SicherungsFehler, match=r"Datenbank wiederhergestellt, Fotos NICHT.*unverändert in") as e:
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert "vor-wiederherstellung" in str(e.value)
    assert abbild(pfad) == vorher                                                # Datenbank ist zurückgespielt
    assert fotos_inhalt(fotos) == fotos_jetzt                                    # Rückweg: alter Fotoordner liegt wieder da
    assert not list(fotos.parent.glob("fotos.alt-*")) and not list(fotos.parent.glob(".*teil"))


def test_m4_fotoschritt_scheitert_und_rueckweg_scheitert_alter_stand_wird_genannt(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    fotos_jetzt = fotos_inhalt(fotos)
    echt = pathlib.Path.rename

    def rename(self, ziel_):
        if self.name.endswith(".wiederherstellung.teil") or ".alt-" in self.name:
            raise OSError("simuliert: gesperrt")
        return echt(self, ziel_)

    monkeypatch.setattr(pathlib.Path, "rename", rename)
    with pytest.raises(SicherungsFehler, match=r"Fotos NICHT.*alte Stand der Fotos liegt in .*fotos\.alt-") as e:
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    alt = next(fotos.parent.glob("fotos.alt-*"))
    assert str(alt) in str(e.value) and fotos_inhalt(alt) == fotos_jetzt         # nichts gelöscht
    assert next(fotos.parent.glob(".fotos.*teil"))                                # entpackte Sicherungsfotos bleiben nutzbar


def test_liegen_gebliebene_teil_dateien_werden_beim_sichern_aufgeraeumt(bestand):
    pfad, fotos, ziel = bestand
    ziel.mkdir()
    alt_zeit = time.time() - modul.TEIL_MAX_ALTER - 60
    eigene_alt = [ziel / ".anzeigen-sicherung-20200101-000000.sqlite.teil", ziel / ".anzeigen-sicherung-20200101-000000_2-vor-v3.fotos.teil"]
    eigene_frisch = ziel / ".anzeigen-sicherung-20991231-235959.sqlite.teil"
    fremd = [ziel / ".andere-sicherung-20200101-000000.sqlite.teil", ziel / "notiz.teil", ziel / ".anzeigen-sicherung-handgemacht.sqlite.teil"]
    for f in [*eigene_alt, eigene_frisch, *fremd]:
        f.write_bytes(b"x")
    for f in [*eigene_alt, *fremd]:
        os.utime(f, (alt_zeit, alt_zeit))
    sichere(pfad, ziel)
    assert not any(f.exists() for f in eigene_alt)
    assert eigene_frisch.exists() and all(f.exists() for f in fremd)             # frische (laufende) und fremde bleiben


def test_n1_behalten_wird_validiert(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    for schlecht in (0, -1, 2.5, "3", True):
        with pytest.raises(ValueError, match="behalten"):
            pruefe_behalten(schlecht)
        with pytest.raises(ValueError, match="behalten"):
            sichere(pfad, ziel, behalten=schlecht)
    assert pruefe_behalten(None) == modul.STANDARD_BEHALTEN and pruefe_behalten(3) == 3
    kopie = sichere(pfad, ziel)
    with pytest.raises(ValueError):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, behalten=0)


def test_n1_cli_meldet_fehler_ohne_traceback(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    db.speichere_treffer({"id": "a1", "url": "u", "titel": "Hymer", "preis": 41000}, "Alkoven")
    db.con.close()
    for schlecht in ("abc", 0, -2):
        cfg["sicherung"] = {"ordner": str(tmp_path / "sich"), "behalten": schlecht}
        for befehl in (("sichern",), ("wiederherstellen", "x.sqlite", "--bestaetigt"), ("report",)):
            r = _scout(cfg, tmp_path, *befehl)
            assert r.returncode != 0 and "Traceback" not in r.stderr and "behalten" in r.stderr, (schlecht, befehl, r.stderr)
    cfg["sicherung"] = {"ordner": str(tmp_path / "sich"), "behalten": 2}
    kaputt = tmp_path / "kaputt.sqlite"
    kaputt.write_bytes(b"kein sqlite" * 300)
    r = _scout(cfg, tmp_path, "wiederherstellen", str(kaputt), "--bestaetigt")
    assert r.returncode != 0 and "Traceback" not in r.stderr and "kaputt.sqlite" in r.stderr
    assert sqlite3.connect(cfg["ausgabe"]["datenbank"]).execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1


def test_m12_reste_einer_defekten_datenbank_werden_beim_austausch_entfernt(bestand):
    """Bei defekter Datei räumt SQLite selbst nichts auf: -wal/-shm/-journal der alten Datenbank müssen explizit weg."""
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    pfad.write_bytes(b"zerstoert" * 600)
    reste = [pfad.with_name(pfad.name + e) for e in ("-wal", "-shm", "-journal")]
    for r in reste:
        r.write_bytes(b"rest der alten datenbank" * 50)
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert not any(r.exists() for r in reste)
    assert abbild(pfad) == vorher
    assert erg.sicherung_vorher.read_bytes().startswith(b"zerstoert")
    aufgehoben = {p.name.rsplit("-", 1)[1]: p.read_bytes() for p in ziel.glob("anzeigen-reste-*")}    # SQLite löscht sie beim Öffnen selbst
    assert aufgehoben == {"wal": b"rest der alten datenbank" * 50, "journal": b"rest der alten datenbank" * 50}


def test_m2_schreiber_waehrend_der_vorher_sicherung_wird_vor_dem_austausch_erkannt(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    fest = hash_datei(pfad)
    echt, schreiber = modul.sichere, []

    def sichere_und_starte_schreiber(*a, **k):
        ergebnis = echt(*a, **k)
        con = sqlite3.connect(pfad, isolation_level=None)                       # ein Suchlauf startet genau jetzt
        con.execute("BEGIN IMMEDIATE")
        schreiber.append(con)
        return ergebnis

    monkeypatch.setattr(modul, "sichere", sichere_und_starte_schreiber)
    try:
        with pytest.raises(SicherungsFehler, match="in Benutzung"):
            wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, sperr_timeout=0.2)
    finally:
        for con in schreiber:
            con.execute("ROLLBACK")
            con.close()
    assert hash_datei(pfad) == fest and not list(pfad.parent.glob(".*teil"))


def test_m12_reste_ohne_datenbankdatei_werden_beim_austausch_entfernt(bestand):
    """Datenbankdatei fehlt, -wal/-shm/-journal liegen noch da (SQLite öffnet nichts und räumt nicht auf)."""
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    pfad.unlink()
    reste = [pfad.with_name(pfad.name + e) for e in ("-wal", "-shm", "-journal")]
    for r in reste:
        r.write_bytes(b"rest der alten datenbank" * 50)
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert not any(r.exists() for r in reste) and abbild(pfad) == vorher


# ---------- Korrekturrunde 2: Uhr, Parallelität, Foto-Archiv, Windows-Pfade, Konfiguration ----------

def uhr(monkeypatch, start: echte_zeit):
    """Ersetzt ``datetime`` im Modul durch eine einstellbare Uhr (``Uhr.jetzt``)."""
    class Uhr(echte_zeit):
        jetzt = start

        @classmethod
        def now(cls, tz=None):
            return cls.jetzt
    monkeypatch.setattr(modul, "datetime", Uhr)
    return Uhr


def test_f1_zurueckgestellte_uhr_loescht_weder_neue_sicherung_noch_vorher_sicherung(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    u = uhr(monkeypatch, echte_zeit(2026, 10, 25, 2, 40, 0))               # Sommerzeit-Ende: 02:40 vor 02:20
    k1 = sichere(pfad, ziel, fotos, behalten=1)
    u.jetzt = echte_zeit(2026, 10, 25, 2, 20, 0)
    k2 = sichere(pfad, ziel, fotos, behalten=1)
    assert k1.is_file() and k2.is_file()                                      # die gerade angelegte (dem Namen nach ältere) bleibt
    u.jetzt = echte_zeit(2026, 10, 25, 2, 10, 0)
    erg = wiederherstellen(k1, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, behalten=1)
    assert erg.sicherung_vorher.is_file() and k1.is_file()                    # Vorher-Sicherung und Quelle bleiben
    assert erg.sicherung_vorher.with_name(erg.sicherung_vorher.name[:-7] + ".fotos.zip").is_file()


def test_f2_gleiche_sekunde_zweite_sicherung_waehrend_der_ersten_bekommt_eigenen_namen(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    uhr(monkeypatch, echte_zeit(2026, 5, 1, 12, 0, 0))
    echt, ergebnis, gestartet = modul._kopiere_db, [], []

    def kopiere_und_starte_zweite(quelle, zielpfad):
        if not gestartet:
            gestartet.append(True)
            ergebnis.append(sichere(pfad, ziel, fotos, behalten=10))          # "zweiter Prozess" mitten in der ersten Sicherung
        echt(quelle, zielpfad)

    monkeypatch.setattr(modul, "_kopiere_db", kopiere_und_starte_zweite)
    erste = sichere(pfad, ziel, fotos, behalten=10)
    zweite = ergebnis[0]
    assert erste != zweite and erste.is_file() and zweite.is_file()
    assert sorted(p.name for p in sicherungen(ziel, "anzeigen")) == sorted([erste.name, zweite.name])
    for k in (erste, zweite):
        assert k.with_name(k.name[:-7] + ".fotos.zip").is_file()
        assert sqlite3.connect(k).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not [p for p in ziel.iterdir() if p.name.startswith(".")]          # keine .teil-/Reservierungsreste


def test_f2_reservierte_nummer_wird_uebersprungen_und_freigegeben(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    uhr(monkeypatch, echte_zeit(2026, 5, 1, 12, 0, 0))
    ziel.mkdir()
    (ziel / ".anzeigen-sicherung-20260501-120000.reserviert").write_bytes(b"")     # läuft gerade in einem anderen Prozess
    kopie = sichere(pfad, ziel, fotos)
    assert kopie.name == "anzeigen-sicherung-20260501-120000_2.sqlite"
    assert [p.name for p in ziel.iterdir() if p.name.startswith(".")] == [".anzeigen-sicherung-20260501-120000.reserviert"]   # fremde bleibt


def test_q10_fremdes_foto_zip_wird_im_fehlerpfad_nicht_geloescht_eigenes_schon(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    uhr(monkeypatch, echte_zeit(2026, 5, 1, 12, 0, 0))
    fremd = ziel / "anzeigen-sicherung-20260501-120000.fotos.zip"
    echt = modul._integritaet

    def integritaet_scheitert(*a, **k):
        fremd.write_bytes(b"gehoert einem anderen Prozess")                     # taucht erst nach der Namensreservierung auf
        raise SicherungsFehler("Absicht")

    monkeypatch.setattr(modul, "_integritaet", integritaet_scheitert)
    ziel.mkdir()
    with pytest.raises(SicherungsFehler, match="Absicht"):
        sichere(pfad, ziel, fotos)
    assert fremd.read_bytes() == b"gehoert einem anderen Prozess"
    assert [p.name for p in ziel.iterdir()] == [fremd.name]
    # scheitert dagegen das Ablegen der Datenbank, nachdem unser eigenes Foto-ZIP schon liegt, wird dieses wieder entfernt
    fremd.unlink()
    monkeypatch.setattr(modul, "_integritaet", echt)
    echt_replace = os.replace

    def replace(quelle, ziel_):
        if str(ziel_).endswith(".sqlite"):
            raise OSError("simuliert: Datenträger voll")
        return echt_replace(quelle, ziel_)

    monkeypatch.setattr(modul.os, "replace", replace)
    with pytest.raises(OSError, match="voll"):
        sichere(pfad, ziel, fotos)
    assert list(ziel.iterdir()) == []


def test_q30_zusatz_wird_bereinigt_kein_pfad_ausbruch(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos, zusatz="../ausbruch/x y")
    assert kopie.parent == ziel and kopie.name.endswith("-ausbruch-x-y.sqlite") and ".." not in kopie.name
    assert not (tmp_path / "ausbruch").exists() and sicherungen(ziel, "anzeigen") == [kopie]


def _zerstoere_archiv(kopie, art: str):
    z = kopie.with_name(kopie.name[:-7] + ".fotos.zip")
    daten = bytearray(z.read_bytes())
    if art == "abgeschnitten":
        z.write_bytes(bytes(daten[: len(daten) // 2]))
    else:                                                                       # Nutzdaten verändert, Verzeichnis intakt: CRC stimmt nicht
        i = daten.find(b"0000")
        daten[i] = ord("1")
        z.write_bytes(bytes(daten))


@pytest.mark.parametrize("art", ["abgeschnitten", "crc"])
def test_f3_beschaedigtes_foto_archiv_wird_gemeldet_nichts_veraendert(bestand, tmp_path, art):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    _zerstoere_archiv(kopie, art)
    con = sqlite3.connect(pfad)
    con.execute("DELETE FROM anzeigen WHERE id='id0'")
    con.commit()
    con.close()
    fest, fotos_vorher, vorher = hash_datei(pfad), fotos_inhalt(fotos), dateien(tmp_path)
    with pytest.raises(SicherungsFehler, match=r"beschädigt.*--ohne-fotos"):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert hash_datei(pfad) == fest and fotos_inhalt(fotos) == fotos_vorher and dateien(tmp_path) == vorher


def test_f3_ohne_fotos_spielt_nur_die_datenbank_zurueck(bestand, tmp_path):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    stand = abbild(kopie)
    _zerstoere_archiv(kopie, "abgeschnitten")
    sqlite3.connect(pfad).execute("DELETE FROM anzeigen").connection.commit()
    fotos_vorher = fotos_inhalt(fotos)
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos, mit_fotos=False)
    assert abbild(pfad) == stand and fotos_inhalt(fotos) == fotos_vorher
    assert erg.fotos_wiederhergestellt is False and erg.alter_fotoordner is None
    assert not list(tmp_path.rglob("fotos.alt-*")) and not list(tmp_path.rglob("*.teil"))


def test_f3_cli_beschaedigtes_archiv_ohne_traceback_und_ausweg_ohne_fotos(cfg, tmp_path):
    cfg["sicherung"] = {"ordner": str(tmp_path / "sich"), "behalten": 5}
    db_pfad, fotos = pathlib.Path(cfg["ausgabe"]["datenbank"]), tmp_path / "fotos"
    db = Datenbank(str(db_pfad))
    db.speichere_treffer({"id": "a1", "url": "u", "titel": "Hymer", "preis": 41000}, "Alkoven")
    db.con.close()
    fotos.mkdir()
    (fotos / "a.jpg").write_bytes(JPEG)
    assert _scout(cfg, tmp_path, "sichern").returncode == 0
    kopie = sicherungen(tmp_path / "sich", "anzeigen")[0]
    _zerstoere_archiv(kopie, "abgeschnitten")
    sqlite3.connect(db_pfad).execute("DELETE FROM anzeigen").connection.commit()
    r = _scout(cfg, tmp_path, "wiederherstellen", kopie.name, "--bestaetigt")
    assert r.returncode != 0 and "Traceback" not in r.stderr and "--ohne-fotos" in r.stderr, r.stderr
    assert sqlite3.connect(db_pfad).execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0     # nichts verändert
    r = _scout(cfg, tmp_path, "wiederherstellen", kopie.name, "--bestaetigt", "--ohne-fotos")
    assert r.returncode == 0, r.stderr
    assert sqlite3.connect(db_pfad).execute("SELECT titel FROM anzeigen").fetchall() == [("Hymer",)]
    assert fotos_inhalt(fotos) == {"a.jpg": JPEG} and not list(tmp_path.glob("fotos.alt-*"))


def test_f4_scheitert_schon_das_umbenennen_des_alten_fotoordners_verweist_die_meldung_nicht_auf_fehlenden_ordner(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    sqlite3.connect(pfad).execute("DELETE FROM anzeigen").connection.commit()
    fotos_jetzt = fotos_inhalt(fotos)
    echt = pathlib.Path.rename

    def rename(self, ziel_):
        if self == fotos:
            raise OSError("simuliert: Ordner gesperrt")
        return echt(self, ziel_)

    monkeypatch.setattr(pathlib.Path, "rename", rename)
    with pytest.raises(SicherungsFehler, match=r"Fotos NICHT.*unverändert in") as e:
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert "alt-" not in str(e.value) and "entpackt" not in str(e.value)
    assert abbild(pfad) == vorher and fotos_inhalt(fotos) == fotos_jetzt
    assert not list(fotos.parent.glob("fotos.alt-*")) and not list(fotos.parent.glob(".*teil"))


@pytest.mark.parametrize("pfad, erwartet", [
    (PureWindowsPath("C:/Daten/anzeigen.sqlite"), "file:///C:/Daten/anzeigen.sqlite"),
    (PureWindowsPath(r"C:\Users\Müller & Söhne\a b#c?d%e.sqlite"), "file:///C:/Users/M%C3%BCller%20%26%20S%C3%B6hne/a%20b%23c%3Fd%25e.sqlite"),
    (PureWindowsPath(r"\\server\share\Wohnmobil Scout\db.sqlite"), "file:////server/share/Wohnmobil%20Scout/db.sqlite"),
    (PureWindowsPath(r"\\?\UNC\server\share\db.sqlite"), "file:////server/share/db.sqlite"),
    (PureWindowsPath(r"\\?\C:\lang\db.sqlite"), "file:///C:/lang/db.sqlite"),
    (PurePosixPath("/tmp/a b/x#y.sqlite"), "file:///tmp/a%20b/x%23y.sqlite"),
])
def test_f5_datei_uri_ohne_authority_und_prozentkodiert(pfad, erwartet):
    assert modul.datei_uri(pfad) == erwartet
    assert modul.datei_uri(pfad, "?mode=ro") == erwartet + "?mode=ro"
    assert not modul.datei_uri(pfad)[len("file://"):].startswith(("server", "localhost"))      # Authority bleibt leer


def test_f5_uri_funktioniert_mit_sqlite_auch_mit_doppeltem_schraegstrich_und_sonderzeichen(tmp_path):
    ordner = tmp_path / "a b#c?d%e"
    ordner.mkdir()
    db = ordner / "x y.sqlite"
    sqlite3.connect(db).execute("CREATE TABLE t (a)").connection.close()
    assert oeffne_lesend(db).execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 1
    doppelt = PurePosixPath("/" + db.resolve().as_posix())                       # "//tmp/..." entspricht der UNC-Form file:////server/...
    assert modul.datei_uri(doppelt).startswith("file:////")
    assert sqlite3.connect(modul.datei_uri(doppelt, "?mode=ro"), uri=True).execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 1
    with pytest.raises(sqlite3.Error, match="authority"):                        # die bisherige Form von Path.as_uri() bei UNC
        sqlite3.connect("file://server/share/x.sqlite?mode=ro", uri=True)


def test_f5_sperrpruefung_schluckt_oeffnungsfehler_nicht(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    fest = hash_datei(pfad)
    echt = modul.datei_uri
    monkeypatch.setattr(modul, "datei_uri", lambda p, abfrage="": "file://server/share/x.sqlite" + abfrage if "rw" in abfrage else echt(p, abfrage))
    with pytest.raises(SicherungsFehler, match="Sperrprüfung.*nicht möglich"):
        modul._pruefe_sperre(pfad, 0.1)
    # auch in der Wiederherstellung: Abbruch statt stillem Überspringen, nichts verändert
    with pytest.raises(SicherungsFehler, match="Sperrprüfung.*nicht möglich"):
        wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert hash_datei(pfad) == fest and not list(pfad.parent.glob(".*teil")) and len(sicherungen(ziel, "anzeigen")) == 1


class _FesteVerbindung:
    """Verbindung, deren BEGIN EXCLUSIVE mit einem bestimmten SQLite-Fehlercode scheitert (z. B. SQLITE_LOCKED im Shared-Cache)."""

    def __init__(self, code):
        self.code = code

    def execute(self, sql):
        if sql.startswith("BEGIN"):
            e = sqlite3.OperationalError("simuliert")
            e.sqlite_errorcode = self.code
            raise e

    def close(self):
        pass


@pytest.mark.parametrize("code, meldung", [(sqlite3.SQLITE_BUSY, "in Benutzung"), (sqlite3.SQLITE_LOCKED, "in Benutzung"),
                                           (sqlite3.SQLITE_IOERR, "Sperrprüfung.*nicht möglich")])
def test_q12_sperrpruefung_erkennt_busy_und_locked_und_meldet_andere_fehler(bestand, monkeypatch, code, meldung):
    pfad, fotos, ziel = bestand
    monkeypatch.setattr(modul.sqlite3, "connect", lambda *a, **k: _FesteVerbindung(code))
    with pytest.raises(SicherungsFehler, match=meldung):
        modul._pruefe_sperre(pfad, 0.1)


def test_f7_falsche_typen_in_der_konfiguration_geben_valueerror_mit_hinweis(tmp_path):
    for schlecht in ({"sicherung": "daten/x"}, {"sicherung": ["a"]}, {"sicherung": {"ordner": 5}}, {"sicherung": {"ordner": ["a"]}},
                     {"sicherung": {"behalten": "3"}}):
        with pytest.raises(ValueError, match="config.yaml|sicherung"):
            modul.einstellungen(schlecht, tmp_path)
    assert modul.einstellungen({}, tmp_path) == (tmp_path / "daten/sicherungen", modul.STANDARD_BEHALTEN)
    assert modul.einstellungen({"sicherung": None}, tmp_path)[0] == tmp_path / "daten/sicherungen"
    assert modul.einstellungen({"sicherung": {"ordner": "x", "behalten": 3}}, tmp_path) == (tmp_path / "x", 3)


def test_f7_cli_falsche_typen_ohne_traceback(cfg, tmp_path):
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    db.con.close()
    for schlecht in ("daten/x", {"ordner": 5}, [1]):
        cfg["sicherung"] = schlecht
        for befehl in (("sichern",), ("wiederherstellen", "x.sqlite", "--bestaetigt"), ("report",)):
            r = _scout(cfg, tmp_path, *befehl)
            assert r.returncode != 0 and "Traceback" not in r.stderr and "config.yaml" in r.stderr, (schlecht, befehl, r.stderr)


def test_f9_rohkopie_ueberschreibt_keine_vorhandene_rohkopie(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    uhr(monkeypatch, echte_zeit(2026, 5, 1, 12, 0, 0))
    alte_rohkopie = ziel / "anzeigen-defekt-20260501-120000.sqlite.defekt"
    alte_rohkopie.write_bytes(b"frueherer defekter Stand")
    pfad.write_bytes(b"zerstoert" * 600)
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert alte_rohkopie.read_bytes() == b"frueherer defekter Stand"
    assert erg.sicherung_vorher != alte_rohkopie and erg.sicherung_vorher.name.endswith(".sqlite.defekt")
    assert erg.sicherung_vorher.read_bytes().startswith(b"zerstoert")


def test_f10_arbeitskopien_haben_eindeutige_namen(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    echt, namen = modul._kopiere_db, []

    def merke(quelle, zielpfad):
        namen.append(zielpfad.name)
        echt(quelle, zielpfad)

    monkeypatch.setattr(modul, "_kopiere_db", merke)
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    arbeitskopien = [n for n in namen if n.endswith(".wiederherstellung.teil")]
    assert len(arbeitskopien) == 2 and len(set(arbeitskopien)) == 2
    assert all(n.startswith(".anzeigen.sqlite.") for n in arbeitskopien)


def test_f10_und_q6_liegen_gebliebene_arbeitskopien_stoeren_nicht_und_alte_werden_aufgeraeumt(bestand):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    vorher = abbild(pfad)
    alt_zeit = time.time() - modul.TEIL_MAX_ALTER - 60
    ungueltig_alt_name = pfad.parent / ".anzeigen.sqlite.wiederherstellung.teil"            # Name wie vor der Kennung
    ungueltig_alt_name.write_bytes(b"kein sqlite" * 100)
    alt_db = pfad.parent / ".anzeigen.sqlite.123-0123abcd.wiederherstellung.teil"
    frisch_db = pfad.parent / ".anzeigen.sqlite.456-89abcdef.wiederherstellung.teil"
    alt_fotos = fotos.parent / ".fotos.123-0123abcd.wiederherstellung.teil"
    frisch_fotos = fotos.parent / ".fotos.456-89abcdef.wiederherstellung.teil"
    fremd = pfad.parent / ".andere.sqlite.123-0123abcd.wiederherstellung.teil"
    for f in (alt_db, frisch_db, fremd):
        f.write_bytes(b"x" * 100)
    for d in (alt_fotos, frisch_fotos):
        d.mkdir()
        (d / "x.jpg").write_bytes(b"x")
    for f in (ungueltig_alt_name, alt_db, alt_fotos, fremd, pfad, kopie):                 # auch DB und Sicherung „alt“ (QA N-1)
        os.utime(f, (alt_zeit, alt_zeit))
    erg = wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert abbild(pfad) == vorher                                                           # ungültige Altlast beeinträchtigt nichts
    assert kopie.is_file() and abbild(erg.sicherung_vorher) == vorher                      # Aufräumen ließ DB und Sicherung stehen
    assert not ungueltig_alt_name.exists() and not alt_db.exists() and not alt_fotos.exists()
    assert frisch_db.exists() and (frisch_fotos / "x.jpg").exists() and fremd.exists()      # frische (laufende) und fremde bleiben


def test_f2_liegen_gebliebene_teil_dateien_mit_kennung_und_reservierungen_werden_aufgeraeumt(bestand):
    pfad, fotos, ziel = bestand
    ziel.mkdir()
    alt_zeit = time.time() - modul.TEIL_MAX_ALTER - 60
    alt = [ziel / ".anzeigen-sicherung-20200101-000000_2-vor-v3.4711-0a1b2c3d.sqlite.teil",
           ziel / ".anzeigen-sicherung-20200101-000000.4711-0a1b2c3d.fotos.teil",
           ziel / ".anzeigen-sicherung-20200101-000000_3.reserviert"]
    frisch = ziel / ".anzeigen-sicherung-20991231-235959.reserviert"
    fremd = ziel / ".andere-sicherung-20200101-000000.reserviert"
    for f in [*alt, frisch, fremd]:
        f.write_bytes(b"x")
    for f in [*alt, fremd]:
        os.utime(f, (alt_zeit, alt_zeit))
    sichere(pfad, ziel)
    assert not any(f.exists() for f in alt) and frisch.exists() and fremd.exists()


def test_f2_fertige_sicherung_waehrend_der_reservierung_belegt_die_nummer(tmp_path, monkeypatch):
    """Ein anderer Prozess wird fertig (Reservierung schon freigegeben), nachdem wir die Nummer 1 gewählt haben: wir nehmen 2."""
    zeit, ordner = "20260501-120000", tmp_path
    echt, ersten = os.open, []

    def open_(pfad, *a, **k):
        if not ersten:
            ersten.append(True)
            (ordner / f"anzeigen-sicherung-{zeit}.sqlite").write_bytes(b"fertig")
        return echt(pfad, *a, **k)

    monkeypatch.setattr(modul.os, "open", open_)
    nummer, reservierung = modul._reserviere(ordner, "anzeigen", zeit)
    assert nummer == 2 and reservierung.name == f".anzeigen-sicherung-{zeit}_2.reserviert"
    assert not (ordner / f".anzeigen-sicherung-{zeit}.reserviert").exists()            # die erste Reservierung wurde wieder freigegeben


def test_f9_freier_name_belegt_dateinamen_atomar_und_setzt_zaehler_vor_die_endung(tmp_path):
    erste = modul._freier_name(tmp_path / "x-defekt-1", ".sqlite.defekt", datei=True)
    zweite = modul._freier_name(tmp_path / "x-defekt-1", ".sqlite.defekt", datei=True)
    assert erste.name == "x-defekt-1.sqlite.defekt" and zweite.name == "x-defekt-1_2.sqlite.defekt"
    assert erste.is_file() and zweite.is_file()                                         # schon belegt, bevor jemand hineinschreibt
    verz = modul._freier_name(tmp_path / "ordner")
    verz.mkdir()
    assert modul._freier_name(tmp_path / "ordner").name == "ordner_2" and verz.name == "ordner"


def test_f9_rohkopie_und_reste_namen_sind_vor_dem_kopieren_belegt(bestand, monkeypatch):
    pfad, fotos, ziel = bestand
    kopie = sichere(pfad, ziel, fotos)
    pfad.write_bytes(b"zerstoert" * 600)
    pfad.with_name(pfad.name + "-journal").write_bytes(b"rest")
    echt, belegt = modul.shutil.copy2, []

    def copy2(quelle, ziel_, **k):
        belegt.append(pathlib.Path(ziel_).is_file())                                  # Platzhalter existiert schon (O_EXCL)
        return echt(quelle, ziel_, **k)

    monkeypatch.setattr(modul.shutil, "copy2", copy2)
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel, foto_ordner=fotos)
    assert len(belegt) == 2 and all(belegt)                                           # -journal-Rest und Rohkopie
