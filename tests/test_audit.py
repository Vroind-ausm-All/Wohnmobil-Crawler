"""G0b (ADR-031): Audit-Protokoll, Leerlauf-Zeitlimit der Sitzung, Rechte je Ankaufsschritt, Dokumente nur als Download."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung/test_auktion werden importiert und als Parameter genutzt
from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timedelta

import pytest

from tests.test_ankauf import _kauf
from tests.test_auktion import markt  # noqa: F401 – Fixture
from tests.test_cli import _scout
from tests.test_handy import Client
from tests.test_team_bearbeitung import anmelden, server, team  # noqa: F401 – Fixtures
from wmscout.audit import einordnen
from wmscout.team import TeamSpeicher

PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n%Test\n").decode()


def eintraege(db, **filter_) -> list[dict]:
    """Ohne Warten: Der Eintrag ist festgeschrieben, bevor der Client die Antwort erhält."""
    zeilen = [dict(r) for r in db.con.execute("SELECT * FROM audit ORDER BY id")]
    return [z for z in zeilen if all(z.get(k) == v for k, v in filter_.items())]


def test_einordnen():
    assert einordnen("GET", "/api/verkaufsanfrage/12") == ("lesen", "anfrage:12")
    assert einordnen("GET", "/ankauf-dokumente/3/x.pdf") == ("lesen", "ankauf:3")
    assert einordnen("GET", "/api/fahrzeuge") is None and einordnen("GET", "/static/app.js") is None
    assert einordnen("POST", "/api/verkaufsanfrage/12/notiz") == ("aendern", "verkaufsanfrage:12")
    assert einordnen("POST", "/api/login") == ("login", None)


def test_zugriffe_werden_protokolliert_ohne_inhalte(markt, db, server):
    anna, ben, hugo, anfrage = markt["anna"], markt["ben"], markt["hugo"], markt["anfrage"]
    assert ben("GET", f"/api/verkaufsanfrage/{anfrage}")[0] == 200
    lesen = eintraege(db, objekt=f"anfrage:{anfrage}", aktion="lesen", nutzer="Ben")
    assert lesen and lesen[-1]["status"] == 200 and lesen[-1]["rolle"] == "mitarbeiter" and lesen[-1]["ip"] == "127.0.0.1"
    anna("POST", f"/api/verkaufsanfrage/{anfrage}/notiz", {"notiz": "Herr Geheimnis ruft an"})
    assert eintraege(db, objekt=f"verkaufsanfrage:{anfrage}", aktion="aendern", nutzer="Anna")
    assert hugo("GET", f"/api/verkaufsanfrage/{anfrage}")[0] == 403                          # abgelehnt – trotzdem festgehalten
    assert eintraege(db, nutzer="Hugo", status=403)
    s, _, _ = Client(server.server_address[1])("POST", "/api/login", {"name": "Ben", "passwort": "falsch-falsch"})
    assert s == 401 and eintraege(db, aktion="login", nutzer="Ben", status=401)
    roh = " ".join(str(v) for z in eintraege(db) for v in z.values())
    assert "Geheimnis" not in roh and "falsch-falsch" not in roh and "sicher1234" not in roh
    # nur der Inhaber liest das Protokoll; nur anfügbar
    assert ben("GET", "/api/audit")[0] == 403 and hugo("GET", "/api/audit")[0] == 403
    s, liste, _ = anna("GET", "/api/audit?tage=1&nutzer=Ben")
    assert s == 200 and liste and {z["nutzer"] for z in liste} == {"Ben"}
    assert anna("GET", "/api/audit?tage=x")[0] == 400
    for sql in ("UPDATE audit SET nutzer='x'", "DELETE FROM audit"):
        with pytest.raises(sqlite3.IntegrityError, match="nur anfügbar"):
            db.con.execute(sql)
        db.con.rollback()


def test_ohne_team_kein_protokoll(server, db):
    from tests.test_team_bearbeitung import lokal
    c = lokal(server)
    assert c("GET", "/api/fahrzeuge")[0] == 200 and c("POST", "/api/notiz", {"id": "x", "notiz": "y"})[0] in (200, 404)
    assert eintraege(db) == []


def test_leerlauf_beendet_sitzung(db, tmp_path):
    t = TeamSpeicher(db, tmp_path / "f", leerlauf_stunden=1)
    nid = t.nutzer_anlegen("Zoe", "sicher1234")
    token = t.sitzung_anlegen(nid)
    assert t.nutzer_zu_token(token)["name"] == "Zoe"
    vor_2h = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    db.con.execute("UPDATE sitzungen SET zuletzt=?", (vor_2h,))
    db.con.commit()
    assert t.nutzer_zu_token(token) is None
    assert db.con.execute("SELECT COUNT(*) FROM sitzungen").fetchone()[0] == 0              # abgelaufene Sitzung gelöscht
    token = t.sitzung_anlegen(nid)
    db.con.execute("UPDATE sitzungen SET zuletzt=NULL")                                     # Sitzung aus der Zeit vor v10
    db.con.commit()
    assert t.nutzer_zu_token(token)["name"] == "Zoe"
    assert db.con.execute("SELECT zuletzt FROM sitzungen").fetchone()[0]                   # ab jetzt gezählt
    vor_30min = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
    db.con.execute("UPDATE sitzungen SET zuletzt=?", (vor_30min,))
    db.con.commit()
    assert t.nutzer_zu_token(token) and db.con.execute("SELECT zuletzt FROM sitzungen").fetchone()[0] > vor_30min
    aus = TeamSpeicher(db, tmp_path / "f", leerlauf_stunden=0)
    db.con.execute("UPDATE sitzungen SET zuletzt='2000-01-01T00:00:00'")
    db.con.commit()
    assert aus.nutzer_zu_token(token)["name"] == "Zoe"                                     # 0 = aus


def test_ankauf_schritte_nur_fuer_zustaendige_und_dokumente_als_download(markt, db, server):
    anna, ben, anfrage = markt["anna"], markt["ben"], markt["anfrage"]
    carl = anmelden(server, "Carl")
    ben_id = db.con.execute("SELECT id FROM nutzer WHERE name='Ben'").fetchone()[0]
    b = anna("POST", f"/api/verkaufsanfrage/{anfrage}/besichtigung", {"zustaendig_id": ben_id})[1]
    aid = ben("POST", f"/api/besichtigung/{b['id']}/abschluss", _kauf())[1]["ankauf"]
    for art, daten in (("vertrag", {}), ("dokument", {"art": "vertrag", "datei": PDF}), ("kosten", {"art": "transport", "betrag": 100})):
        s, f, _ = carl("POST", f"/api/ankauf/{aid}/{art}", daten)
        assert s == 403 and f["grund"] == "recht", art                                       # weder zuständig noch Bearbeiter
    assert carl("GET", f"/api/ankauf/{aid}")[0] == 200                                    # Lesen bleibt im Team (G2: Mandanten)
    assert ben("POST", f"/api/ankauf/{aid}/vertrag", {})[0] == 200                        # Zuständiger der Besichtigung
    s, d, _ = ben("POST", f"/api/ankauf/{aid}/dokument", {"art": "vertrag", "datei": PDF})
    assert s == 200
    s, _, r = anna("GET", f"/ankauf-dokumente/{aid}/{d['datei']}")
    assert s == 200 and r.getheader("Content-Disposition", "").startswith("attachment") and "sandbox" in r.getheader("Content-Security-Policy")
    assert eintraege(db, objekt=f"ankauf:{aid}", aktion="lesen", nutzer="Anna")
    for pfad in ("/api/ankauf/999", "/ankauf/999/vertrag"):
        assert anna("GET", pfad)[0] == 404
    assert anna("POST", "/api/ankauf/999/vertrag", {})[0] == 404


def test_cli_audit(cfg, tmp_path):
    from wmscout.audit import AuditSpeicher
    from wmscout.datenbank import Datenbank
    db = Datenbank(cfg["ausgabe"]["datenbank"])
    AuditSpeicher(db).schreibe({"id": 1, "name": "Anna", "rolle": "inhaber"}, "127.0.0.1", "GET", "/api/verkaufsanfrage/7", 200,
                               "lesen", "anfrage:7")
    db.con.close()
    r = _scout(cfg, tmp_path, "audit", "--objekt", "anfrage:7")
    assert r.returncode == 0 and "Anna" in r.stdout and "anfrage:7" in r.stdout and "1 Einträge" in r.stdout, r.stderr
