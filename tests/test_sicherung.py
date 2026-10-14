"""Datensicherung und Wiederherstellung: Backup-API, Integritätsprüfung, Fotos, Aufbewahrung, Bestätigung."""
import sqlite3

import pytest

from tests.test_cli import _scout
from wmscout.datenbank import Datenbank
from wmscout.sicherung import SicherungsFehler, sicherungen, sichere, wiederherstellen
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
