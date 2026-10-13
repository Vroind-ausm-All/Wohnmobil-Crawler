"""Dubletten und Nachfassen (Erstkontakt → Erinnerung → Preissenkung → Neueinstellung)."""
from datetime import datetime, timedelta

from tests.daten import BASIS
from wmscout.bewertung.anschreiben import euro
from wmscout.bewertung.auswertung import bewerte_alle, finde_duplikate


def test_finde_duplikate():
    basis = {"marke": "Knaus", "ez_jahr": 2017, "plz": "70173", "serie": "Sky TI"}
    alt = {**basis, "id": "1", "km": 85000, "status": "kontaktiert"}
    neu = {**basis, "id": "2", "km": 85400, "status": "neu"}
    anderer_ort = {**basis, "id": "3", "km": 85000, "plz": "80331"}
    andere_serie = {**basis, "id": "4", "km": 85000, "serie": "Van TI"}
    d = finde_duplikate([alt, neu, anderer_ort, andere_serie])
    assert {b["id"] for b in d["2"]} == {"1"} and "3" not in d and "4" not in d


def _setze(db, spalte, wert, ad_id):
    db.con.execute(f"UPDATE anzeigen SET {spalte}=? WHERE id=?", (wert, ad_id))
    db.con.commit()


def test_nachfassen_ablauf(cfg, db, importiert):
    ad = [z for z in bewerte_alle(cfg, db, BASIS) if z["bereit"]][1]
    ad_id, betrag = ad["a"]["id"], ad["b"].erstangebot
    db.setze_status(ad_id, "kontaktiert", text=ad["brief"], betrag=betrag)
    vor_5_tagen = (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds")
    _setze(db, "kontaktiert_am", vor_5_tagen, ad_id)

    def zeile():
        return next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ad_id)

    z = zeile()
    assert z["nachfassen"] == "seit 5 Tagen keine Antwort"
    assert f"Mein Angebot über {euro(betrag)}" in z["nachfass_text"] and "vorbehaltlich" in z["nachfass_text"]
    assert z["nachfass_betrag"] == betrag

    db.nachgefasst(ad_id, z["nachfass_text"], z["nachfass_betrag"])
    assert zeile()["nachfassen"] is None                     # gerade nachgefasst, max_anzahl erreicht
    _setze(db, "nachgefasst_am", (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"), ad_id)

    # Preissenkung unter unser Angebot → sofort nachfassen mit Zusage
    roh = dict(db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone())
    neuer_preis = betrag - 500
    db.speichere_treffer({**roh, "preis": neuer_preis}, roh["suche"])
    z = zeile()
    assert z["nachfassen"] == f"Preis gesenkt auf {euro(neuer_preis)}"
    assert f"Zu Ihrem neuen Preis von {euro(neuer_preis)}" in z["nachfass_text"]
    assert z["nachfass_betrag"] == neuer_preis

    # Neueinstellung desselben Fahrzeugs → nicht noch einmal anschreiben
    _setze(db, "erstmals_gesehen", vor_5_tagen, ad_id)
    kopie = {**roh, "id": "9" + ad_id, "url": roh["url"] + "-neu"}
    db.speichere_treffer(kopie, roh["suche"])
    db.speichere_details(kopie["id"], {k: roh[k] for k in ("km", "ez_jahr", "marke", "beschreibung", "titel")})
    dz = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == kopie["id"])
    assert "schon bearbeitet" in dz["sperre"] and not dz["bereit"] and dz["a"]["neu_eingestellt"]
