"""Team-Daten: Nutzer, Anmeldung, Besichtigungen, Fotos – und die Nutzerverwaltung über die Kommandozeile."""
import pytest

from tests.test_cli import _scout
from wmscout.team import TeamSpeicher, hash_passwort, pruefe_passwort

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture
def team(db, tmp_path):
    return TeamSpeicher(db, tmp_path / "fotos")


def test_passwort_hash():
    h = hash_passwort("geheim123")
    assert h.startswith("scrypt$") and "geheim123" not in h
    assert pruefe_passwort("geheim123", h) and not pruefe_passwort("falsch123", h)
    assert not pruefe_passwort("x", "kaputt")


def test_nutzer_und_anmeldung(team):
    assert not team.hat_nutzer()
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber", "+491701234567")
    assert team.hat_nutzer()
    assert team.anmelden("anna", "falsch") is None
    token = team.anmelden("anna", "sicher1234")                 # Name ohne Groß-/Kleinschreibung
    assert team.nutzer_zu_token(token)["name"] == "Anna"
    assert token not in str(list(team.con.execute("SELECT * FROM sitzungen").fetchall()[0]))   # nur Hash gespeichert
    team.passwort_setzen("Anna", "neuesPasswort")
    assert team.nutzer_zu_token(token) is None                   # Passwortwechsel beendet Sitzungen
    with pytest.raises(ValueError):
        team.nutzer_anlegen("Kurz", "123")
    team.nutzer_aktiv_setzen("Anna", False)
    assert team.anmelden("Anna", "neuesPasswort") is None


def test_besichtigung_ablauf_und_fotos(team):
    uid = team.nutzer_anlegen("Ben", "sicher1234")
    bid = team.besichtigung_anlegen("3500000001", {"angebot": 30000}, "2026-10-14T10:00", "Hauptstr. 1, Stuttgart",
                                    uid, uid)
    assert [b["id"] for b in team.besichtigungen(zustaendig_id=uid)] == [bid]
    v = team.besichtigung_speichern(bid, {"maengel": [{"key": "schluessel"}]}, {"vorschlag": 29600})
    b = team.besichtigung(bid)
    assert b["status"] == "laeuft" and v == 2 and b["daten"]["maengel"][0]["key"] == "schluessel"
    assert b["zustaendig"]["name"] == "Ben" and b["basis"]["angebot"] == 30000

    f = team.foto_speichern(bid, JPEG, "schluessel", uid)
    assert team.foto_pfad(bid, f["datei"]).read_bytes() == JPEG
    assert team.foto_pfad(bid, "../../anzeigen.sqlite") is None and team.foto_pfad(999, f["datei"]) is None
    with pytest.raises(ValueError):
        team.foto_speichern(bid, b"GIF89a....", None, uid)

    team.besichtigung_abschliessen(bid, {"entscheidung": "gekauft"}, 29500)
    assert team.besichtigungen(zustaendig_id=uid) == []          # nicht mehr offen
    assert team.besichtigung(bid)["endpreis"] == 29500


def test_cli_nutzer(cfg, tmp_path):
    r = _scout(cfg, tmp_path, "nutzer", "anlegen", "Chris", "--rolle", "inhaber", "--passwort", "sicher1234")
    assert r.returncode == 0 and "angelegt" in r.stdout, r.stderr
    r = _scout(cfg, tmp_path, "nutzer", "liste")
    assert "Chris" in r.stdout and "Inhaber" in r.stdout
    r = _scout(cfg, tmp_path, "nutzer", "anlegen", "Kurz", "--passwort", "123")
    assert r.returncode != 0 and "mindestens 8" in r.stderr
