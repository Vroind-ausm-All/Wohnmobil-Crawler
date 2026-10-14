"""Datensicherung und Wiederherstellung: Backup-API, Integritätsprüfung, Fotos, Aufbewahrung, Bestätigung."""
import hashlib
import os
import pathlib
import sqlite3
import time
import zipfile

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
