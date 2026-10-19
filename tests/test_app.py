"""Browser-App: HTTP-Schnittstelle, Zugriffsschutz, Status/Notiz/Nachfassen, Auto-Suche."""
import http.client
import json
import threading
from datetime import datetime

import pytest

from tests.daten import BASIS
from wmscout.app import AutoSuche, erstelle_server


@pytest.fixture
def app(cfg, db, importiert):
    server, token, _ = erstelle_server(cfg, db, BASIS, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def anfrage(methode, pfad, daten=None, kopf=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request(methode, pfad, body=json.dumps(daten) if daten is not None else None,
                  headers={"Content-Type": "application/json", **(kopf or {})})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")

    yield anfrage, {"X-Scout-Token": token}, token
    server.shutdown()
    server.server_close()


def test_app_ablauf(app, db, ads):
    anfrage, kopf, token = app
    ad_id = ads[1]["id"]
    status, html = anfrage("GET", "/")
    assert status == 200 and "Wohnmobil-Scout" in html and token in html
    assert anfrage("POST", "/api/status", {"id": ad_id, "status": "kontaktiert"})[0] == 403        # ohne Token
    assert anfrage("GET", "/", kopf={"Host": "boese.example:80"})[0] == 403                        # DNS-Rebinding
    assert anfrage("POST", "/api/status", {"id": ad_id, "status": "kontaktiert", "text": "Hallo Test"}, kopf)[0] == 200
    zeile = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
    assert zeile["status"] == "kontaktiert" and zeile["anschreiben_text"] == "Hallo Test" and zeile["kontaktiert_am"]
    assert anfrage("POST", "/api/notiz", {"id": ad_id, "notiz": "Rückruf Fr"}, kopf)[0] == 200
    assert anfrage("POST", "/api/status", {"id": ad_id, "status": "quatsch"}, kopf)[0] == 400
    html = anfrage("GET", "/")[1]
    assert "Hallo Test" in html and "Rückruf Fr" in html
    assert anfrage("POST", "/api/status", {"id": ad_id, "status": "verhandlung", "betrag": 31000}, kopf)[0] == 200
    assert anfrage("POST", "/api/nachgefasst", {"id": ad_id, "text": "Noch aktuell?", "betrag": 31000}, kopf)[0] == 200
    zeile = db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
    assert zeile["status"] == "verhandlung" and zeile["angebot_betrag"] == 31000 and zeile["nachfass_anzahl"] == 1
    assert zeile["anschreiben_text"].startswith("Hallo Test") and "Noch aktuell?" in zeile["anschreiben_text"]
    assert anfrage("POST", "/api/nachgefasst", {"id": ad_id}, kopf)[0] == 400                     # ohne Text
    assert anfrage("POST", "/api/status", {"id": ad_id, "status": "neu"}, kopf)[0] == 200
    status, daten = anfrage("GET", "/api/suchlauf")
    assert status == 200 and json.loads(daten)["laeuft"] is False


def test_auto_suche_zeitplan():
    auto = AutoSuche({"app": {"auto_suche_stunden": 3, "auto_suche_von": 7, "auto_suche_bis": 21}}, None)
    t = datetime(2026, 10, 13, 11, 0)
    assert auto.naechste(datetime(2026, 10, 13, 10, 0), t) == datetime(2026, 10, 13, 13, 0)
    assert auto.naechste(datetime(2026, 10, 13, 6, 0), t) == t                     # überfällig → jetzt
    assert auto.naechste(datetime(2026, 10, 13, 20, 0), t) == datetime(2026, 10, 14, 7, 0)
    assert auto.naechste(None, datetime(2026, 10, 13, 5, 0)) == datetime(2026, 10, 13, 7, 0)
