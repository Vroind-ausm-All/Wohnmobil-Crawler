"""Ein vollständiger Händlerablauf über echtes lokales HTTP mit synthetischen Angeboten.

Keine Plattformabfragen oder Nachrichten, keine Behauptung einer Live-/Kundenabnahme.
Der Kaufabschluss und alle Personen-/Fahrzeugdaten sind ausschließlich Testdaten in tmp_path.
"""
# ruff: noqa: F811 – importierte HTTP-Fixture
from __future__ import annotations

from datetime import date, timedelta

import pytest
import requests

from tests.test_datei_upload import app, upload  # noqa: F401 – gemeinsame HTTP-Fixture
from wmscout.team import TeamSpeicher

AD = "3900007777"
URL = f"https://www.kleinanzeigen.de/s-anzeige/hymer-b-678/{AD}-220-1"


def angebot(format_, preis):
    if format_ == "csv":
        text = ("url;titel;preis;km;ez;anbieter;art;ort;beschreibung\n"
                f"{URL};Hymer B 678;{preis};95000;2017;privat;Integrierter;70173 Stuttgart;Markise, Solar, gepflegt\n")
    else:
        text = f'''<html><head><link rel="canonical" href="{URL}"></head><body>
<h1 id="viewad-title">Hymer B 678</h1><h2 id="viewad-price">{preis} € VB</h2>
<div id="viewad-locality">70173 Stuttgart</div><div id="viewad-contact">Privater Nutzer</div>
<div id="viewad-details"><ul>
<li><span>Art</span><span>Integrierter</span></li><li><span>Marke</span><span>Hymer</span></li>
<li><span>Kilometerstand</span><span>95.000 km</span></li><li><span>Erstzulassung</span><span>Mai 2017</span></li>
</ul></div><p id="viewad-description-text">Markise, Solar, gepflegt</p></body></html>'''
    return upload(f"angebot.{format_}", text)


@pytest.mark.parametrize("format_", ["csv", "html"])
def test_import_bis_vertragsmuster_ueber_http(app, cfg, db, tmp_path, monkeypatch, format_):
    def kein_netz(*args, **kwargs):
        raise AssertionError("Dieser Händlerablauf darf kein externes Netzwerk nutzen")
    monkeypatch.setattr(requests.sessions.Session, "request", kein_netz)
    client, _ = app
    team = TeamSpeicher(db, tmp_path / "fotos")
    uid = team.nutzer_anlegen("Testleitung", "sicher1234", "inhaber")
    client.anmelden("Testleitung")

    # Vorschau ist schreibfrei, Import und Reimport verwenden den gleichen echten HTTP-Weg.
    status, vorschau, _ = client("POST", "/api/import/datei", {**angebot(format_, 29900), "vorschau": True})
    assert status == 200 and vorschau["vorschau"][0]["preis"] == 29900
    assert vorschau["vorschau"][0]["anbieter"] == "privat" and not vorschau["gespeichert"]
    assert not db.con.execute("SELECT 1 FROM anzeigen").fetchone()
    for preis, erwartet in ((29900, (1, 0)), (26900, (0, 1)), (26900, (0, 0))):
        status, ergebnis, _ = client("POST", "/api/import/datei", angebot(format_, preis))
        assert status == 200, ergebnis
        assert (ergebnis["neu"], ergebnis["aktualisiert"]) == erwartet and ergebnis["fehlerhaft"] == 0
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1
    assert tuple(db.con.execute("SELECT preis, preis_vorher FROM anzeigen").fetchone()) == (26900, 29900)

    # Gespeichertes Suchprofil mit Radius zeigt dasselbe normalisierte Fahrzeug und seine Bewertung.
    profil = {"name": "Integrierte für Ankauf", "arten": ["Integrierter"], "marken": ["Hymer"],
              "gebiet": "umkreis", "gebiet_plz": "70173", "gebiet_radius_km": 50, "preis_max": 40000, "km_max": 120000}
    status, p, _ = client("POST", "/api/suchprofile", profil)
    assert status == 200, p
    status, liste, _ = client("GET", f"/api/fahrzeuge?filter=alle&profil={p['id']}&sort=chance")
    assert status == 200 and len(liste) == 1 and liste[0]["id"] == AD
    status, f, _ = client("GET", f"/api/fahrzeug/{AD}")
    assert status == 200 and f["titel"] == "Hymer B 678" and f["preis"] == 26900 and f["km"] == 95000
    assert f["anbieter"]["typ"] == "privat" and f["anbieter"]["belegt"] and f["ez_jahr"] == 2017
    assert liste[0]["ankaufchance"] and f["bewertung"]["sicherheit"] and f["brief"]
    assert client("GET", "/api/status")[1]["letzter_erfolgreicher_import"]

    # Vorbereiten speichert lediglich den Entwurf; es versendet nichts und bestätigt keinen Kontakt.
    status, _, _ = client("POST", "/api/status", {"id": AD, "status": "vorbereitet", "text": f["brief"], "kanal": "plattform"})
    assert status == 200
    kontakte = client("GET", f"/api/kontakte/{AD}")[1]
    assert len(kontakte) == 1 and not kontakte[0]["bestaetigt"]

    termin = (date.today() + timedelta(days=1)).isoformat() + "T10:30"
    status, b, _ = client("POST", "/api/besichtigung", {"anzeige_id": AD, "termin": termin,
                                                       "adresse": "Testweg 1, 70173 Stuttgart", "zustaendig_id": uid})
    assert status == 200, b
    assert any(t["id"] == b["id"] for t in client("GET", "/api/heute")[1]["termine"])
    status, kalender, _ = client("GET", f"/api/besichtigung/{b['id']}/ics")
    assert status == 200 and "BEGIN:VEVENT" in kalender

    daten = {"pruefpunkte": {"fin": True, "papiere": True, "probefahrt": True, "heizung": True},
             "fahrzeug": {"fin": "TESTFIN12345678901", "kennzeichen": "TEST-123", "schluessel": 2}, "km_abgelesen": 95500,
             "messungen": {"feuchtigkeit": [{"bereich": f"Testbereich {i}", "wert": 12} for i in range(8)],
                           "reifen": [{"position": p, "dot": f"12{date.today().year % 100:02d}"} for p in ("VL", "VR", "HL", "HR")]},
             "maengel": [{"key": "bremsen", "stufe": "mittel"}]}
    status, gemerkt, _ = client("POST", f"/api/besichtigung/{b['id']}/speichern", {"daten": daten})
    assert status == 200 and gemerkt["ergebnis"]["vollstaendig"] and gemerkt["ergebnis"]["summe_maengel"] > 0
    gespeichert = client("GET", f"/api/besichtigung/{b['id']}")[1]
    assert gespeichert["daten"]["fahrzeug"]["fin"] == daten["fahrzeug"]["fin"]

    # Vertragsvorbereitung vor Kaufentscheidung: dieselben erfassten Angaben, keine Kaufakte/Unterschrift.
    kontakt = {"name": "Testverkäufer Beispiel", "anschrift": "Testweg 1, 70173 Stuttgart",
               "telefon": "000000000", "email": "test@example.invalid", "preis": 25000}
    status, _, _ = client("POST", f"/api/besichtigung/{b['id']}/vertragsdaten", {"werte": kontakt, "version": gespeichert["version"]})
    assert status == 200
    mobile_daten = client("GET", f"/api/besichtigung/{b['id']}")[1]["daten"]
    assert "vertragsdaten" not in mobile_daten and "verkaeufer" not in mobile_daten
    status, entwurf, _ = client("GET", f"/besichtigung/{b['id']}/vertragsentwurf")
    assert status == 200
    for text in ("Entwurf", "Testverkäufer Beispiel", "Testweg 1", "TESTFIN12345678901", "test@example.invalid"):
        assert text in entwurf
    assert client("GET", "/api/ankaeufe")[1]["vorgaenge"] == []
    assert client("GET", f"/api/besichtigung/{b['id']}")[1]["status"] not in ("abgeschlossen", "abgebrochen")

    # Im vorhandenen Ablauf entsteht der Ankauf nach einem ausdrücklich bestätigten Testkauf.
    png = "data:image/png;base64,iVBORw0KGgo="
    status, ende, _ = client("POST", f"/api/besichtigung/{b['id']}/abschluss", {
        "entscheidung": "gekauft", "endpreis": 25000, "unterschrift_verkaeufer": png, "unterschrift_ankaeufer": png,
        "verkaeufer": {"name": "Testverkäufer Beispiel", "anschrift": "Testweg 1, 70173 Stuttgart",
                       "telefon": "000000000", "email": "test@example.invalid", "eigentum_frei": True, "unfall": "keine bekannt"}})
    assert status == 200 and ende["ankauf"], ende
    status, vertrag, _ = client("GET", f"/ankauf/{ende['ankauf']}/vertrag")
    assert status == 200
    for text in ("Kaufvertrag", "MUSTER ohne Rechtsgewähr", "Testverkäufer Beispiel", "Testweg 1", "TESTFIN12345678901", "95.500", "25.000 €"):
        assert text in vertrag
    # Das Lesen des Musters allein bestätigt keinen unterschriebenen Vertrag.
    assert client("GET", f"/api/ankauf/{ende['ankauf']}")[1]["status"] == "gekauft"
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 1
