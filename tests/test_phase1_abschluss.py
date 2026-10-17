"""Phase-1-Abschluss: P1-07 Versionskonflikt Besichtigung, P1-15 Rollenmatrix, P1-14a Löschung von Verkäuferdaten aus Inseraten."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

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
