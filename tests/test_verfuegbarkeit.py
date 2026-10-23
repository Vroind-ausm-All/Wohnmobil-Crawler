"""P3-04 (ADR-042): Verfügbarkeit (aktiv/reserviert/offline/verkauft/unbekannt) + ``zuletzt_bestaetigt`` am Inserat.

Geprüft: Erkennung im Titel (positive und negative Beispiele), Übergänge je Kanal (Suche, Seite/Text über ``kanal``, Mail mit Altersregel, Ereignis,
Detailabruf), abgeleitetes „vermutlich offline“ (nie gespeichert), Fahrzeug-Rangfolge, Wirkung auf Sperre/Hinweise/Listen/CSV/Oberfläche, Altbestand mit
Status „gelöscht“ und Schema 13 gegen Altbestände aller Vorversionen. Alles offline; Seiten, Mails und Ereignisse sind nachgebaut.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.daten import BASIS, FakeAbruf, such_html
from tests.test_dubletten_vorschlaege import _Abbruch, baue_v11, inserat_id, treffer
from tests.test_ereignisse import _freigeben
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_migration import pruefsumme, versionen
from tests.test_reimport import Welt
from tests.test_seitenimport import KeinNetz, detailseite
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout import migrationen, verfuegbarkeit as v
from wmscout.ausgabe import render_html, schreibe_ausgaben
from wmscout.bewertung.anschreiben import hinweise, sperrgrund
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenbank import Datenbank
from wmscout.dubletten import bestaetige
from wmscout.ereignisse import InseratEreignis
from wmscout.importer import Importer
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.quellen import Inserat
from wmscout.sicherung import sicherungen, wiederherstellen

STATIC = BASIS / "wmscout" / "web" / "static"
JETZT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def vor(tage: float, ab: datetime = JETZT) -> str:
    return (ab - timedelta(days=tage)).isoformat(timespec="seconds")


def ink(db, ad_id):
    return db.con.execute("SELECT * FROM inserate WHERE anzeigen_id=?", (ad_id,)).fetchone()


def alt_machen(db, ad_id, tage):
    """Die letzte Bestätigung liegt ``tage`` Tage zurück (so, als wäre das Inserat damals zuletzt gesehen worden)."""
    db.con.execute("UPDATE inserate SET zuletzt_bestaetigt=? WHERE anzeigen_id=?", (vor(tage, datetime.now(timezone.utc)), ad_id))
    db.con.commit()


def beobachtungen(db, ad_id):
    zeilen = db.con.execute("SELECT kanal, ereignis_typ, zeitpunkt FROM beobachtungen WHERE inserat_id=? ORDER BY id", (ink(db, ad_id)["id"],))
    return [tuple(r) for r in zeilen]


# ---------------------------------------------------------------- 1. Erkennung im Titel (rein)
POSITIV = [("RESERVIERT", "reserviert"), ("*** reserviert *** Knaus Sky", "reserviert"), ("*** RESERVIERT ***", "reserviert"),
           ("Hymer B 544 (reserviert)", "reserviert"), ("RESERVIERT Knaus Sky TI", "reserviert"), ("Hymer B 544 RESERVIERT", "reserviert"),
           ("Das Fahrzeug ist reserviert", "reserviert"), ("VERKAUFT", "verkauft"), ("Hymer B 544 - verkauft", "verkauft"),
           ("Hymer B 544 – VERKAUFT", "verkauft"), ("[Verkauft] Knaus Sky TI", "verkauft"), ("VERKAUFT! Knaus Sky", "verkauft"),
           ("Leider schon verkauft!", "verkauft"), ("Wurde verkauft", "verkauft"), ("Hymer ist verkauft", "verkauft"),
           ("Nicht gefahren. Verkauft!", "verkauft"), ("Verkauft! Knaus Sky, reserviert war er auch", "verkauft")]
# Positivliste (QA F1/F3): als Verb oder in einer Fortsetzung ist „verkauft“/„reserviert“ KEIN Signal – typische Titel privater Verkäufer dürfen nie sperren
NEGATIV = ["Nicht verkauft", "NICHT VERKAUFT", "noch nicht verkauft", "Wird verkauft", "wird nur privat verkauft", "Wohnmobil soll verkauft werden",
           "Verkauf wegen Krankheit", "Verkaufe Hymer B 544", "Zu verkaufen: Knaus Sky", "unverkauft", "Verkauft wie gesehen", "Verkauft ohne Gewähr",
           "Verkauft nur an Selbstabholer", "Verkauft wird nur gegen Bargeld", "Kann reserviert werden", "nicht reserviert", "Reservierung möglich",
           "Anzahlung zur Reservierung", "Wenn reserviert, bitte melden", "reserviert-bar", "", "Hymer B 544 Teilintegrierter 2018", "Reservieren Sie jetzt",
           "Fahrzeug ist noch nicht verkauft", "Rentner verkauft gepflegten Hymer B 544", "Familie verkauft Wohnmobil", "Ehepaar verkauft Hymer",
           "Opa verkauft sein Wohnmobil", "Hymer B 544 verkauft wg. Umzug", "Hymer verkauft aus Altersgründen", "Wohnmobil verkauft privat",
           "Hymer verkauft da neues Fahrzeug", "Hymer B 544 verkauft, weil zu groß", "Verkauft: nur an Privat", "Preis reserviert für Abholer",
           "Probefahrt reserviert", "Hymer B 544 reserviert für Händler? Nein", "Bereits reserviert für Herrn Müller", "Reserviert bis Freitag",
           "Hymer B 544 reserviert", "Hymer B 544 verkauft", "HYMER B 544 VERKAUFT WEGEN UMZUG"]


@pytest.mark.parametrize("text, erwartet", POSITIV, ids=[f"p{i}" for i in range(len(POSITIV))])
def test_signal_erkannt(text, erwartet):
    assert v.erkenne_signal(text) == erwartet


@pytest.mark.parametrize("text", NEGATIV, ids=[f"n{i}" for i in range(len(NEGATIV))])
def test_kein_signal_bei_verneinung_absicht_oder_anderem_wort(text):
    assert v.erkenne_signal(text) is None


def test_signal_robust_gegen_unsinn_und_lange_texte():
    assert v.erkenne_signal(None, "", 0) is None
    assert v.erkenne_signal("x" * 5000 + " verkauft") is None                      # nur die ersten 300 Zeichen
    assert v.erkenne_signal("Hymer", "VERKAUFT") == "verkauft"                       # mehrere Texte
    assert v.aus_signal(None) == "aktiv" and v.aus_signal("reserviert") == "reserviert"


# ---------------------------------------------------------------- 2. Konfiguration
@pytest.mark.parametrize("cfg, erwartet", [
    (None, 14), ({}, 14), ({"verfuegbarkeit": None}, 14), ({"verfuegbarkeit": {}}, 14), ({"verfuegbarkeit": {"offline_nach_tagen": 7}}, 7),
    ({"verfuegbarkeit": {"offline_nach_tagen": 1}}, 1), ({"verfuegbarkeit": {"offline_nach_tagen": "7"}}, 14),
    ({"verfuegbarkeit": {"offline_nach_tagen": 0}}, 14), ({"verfuegbarkeit": {"offline_nach_tagen": -3}}, 14),
    ({"verfuegbarkeit": {"offline_nach_tagen": True}}, 14), ({"verfuegbarkeit": {"offline_nach_tagen": 3.5}}, 14),
    ({"verfuegbarkeit": {"offline_nach_tagen": 99999}}, 14), ({"verfuegbarkeit": "kaputt"}, 14), ({"verfuegbarkeit": [1]}, 14)],
    ids=[f"c{i}" for i in range(14)])
def test_offline_nach_tagen_defensiv_gelesen(cfg, erwartet):
    assert v.offline_nach_tagen(cfg) == erwartet


def test_config_yaml_hat_den_abschnitt_mit_dem_standard():
    import yaml
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["verfuegbarkeit"]["offline_nach_tagen"] == 14 and v.offline_nach_tagen(cfg) == 14


# ---------------------------------------------------------------- 3. Wirksamer Wert beim Lesen (rein)
def test_vermutlich_offline_ist_abgeleitet_mit_schwelle():
    knapp = v.bewerte("aktiv", vor(13.9), vor(13.9), "neu", JETZT)
    genau = v.bewerte("aktiv", vor(14), vor(14), "neu", JETZT)
    assert (knapp["wert"], knapp["vermutlich_offline"], knapp["text"]) == ("aktiv", False, None)
    assert (genau["wert"], genau["gespeichert"], genau["vermutlich_offline"]) == ("aktiv", "aktiv", True)         # Wert bleibt, nur Kennzeichnung
    assert "vermutlich offline" in genau["text"] and "14 Tagen" in genau["hinweis"] and genau["sperrgrund"] is None
    assert v.bewerte("aktiv", vor(5), vor(5), "neu", JETZT, tage=3)["vermutlich_offline"] is True              # Schwelle konfigurierbar
    assert v.bewerte("aktiv", vor(5), vor(5), "neu", JETZT, tage=30)["vermutlich_offline"] is False


def test_vermutlich_offline_betrifft_nur_aktiv_reserviert_unbekannt():
    for wert, erwartet in (("aktiv", True), ("reserviert", True), ("unbekannt", True), ("offline", False), ("verkauft", False)):
        assert v.bewerte(wert, vor(40), vor(40), "neu", JETZT)["vermutlich_offline"] is erwartet, wert
    r = v.bewerte("reserviert", vor(40), vor(40), "neu", JETZT)
    assert "reserviert" in r["hinweis"] and r["sperrgrund"] is None                                          # kein Sperrgrund


def test_ohne_bestaetigung_gilt_zuletzt_gesehen_und_ohne_alles_unbekannt():
    alt = v.bewerte("unbekannt", None, vor(30), "neu", JETZT)
    assert alt["vermutlich_offline"] is True and alt["zuletzt_bestaetigt"] is None and alt["wert"] == "unbekannt"
    leer = v.bewerte(None, None, None, None, JETZT)
    assert (leer["wert"], leer["vermutlich_offline"], leer["sperrgrund"], leer["nicht_verfuegbar"]) == ("unbekannt", False, None, False)
    kaputt = v.bewerte("aktiv", "kein Datum", "auch nicht", "neu", JETZT)
    assert kaputt["wert"] == "aktiv" and kaputt["vermutlich_offline"] is False                               # unlesbar: kein Absturz, keine Behauptung
    assert v.bewerte("quatsch", vor(1), vor(1), "neu", JETZT)["wert"] == "unbekannt"


def test_altbestand_status_geloescht_gilt_wie_offline_und_bleibt_lesbar():
    g = v.bewerte("aktiv", vor(1), vor(1), "gelöscht", JETZT)
    assert (g["wert"], g["gespeichert"], g["nicht_verfuegbar"], g["sperrgrund"]) == ("offline", "aktiv", True, v.SPERRE_OFFLINE)
    o = v.bewerte("offline", vor(1), vor(1), "neu", JETZT)
    assert {k: g[k] for k in ("wert", "sperrgrund", "nicht_verfuegbar", "text")} == {k: o[k] for k in ("wert", "sperrgrund", "nicht_verfuegbar", "text")}


def test_verkauft_und_offline_sperren_reserviert_nicht():
    a = {"preis": 30000}
    cfg = {"filter": {"preis_min": 1, "preis_max": 99999, "ez_ab_jahr": 1990, "km_max": 999999, "sperrbegriffe": []}}
    assert sperrgrund(a, cfg) is None
    for wert, sperre in (("verkauft", v.SPERRE_VERKAUFT), ("offline", v.SPERRE_OFFLINE)):
        z = v.ergaenze({**a, "inserat_verfuegbarkeit": wert, "inserat_bestaetigt": vor(1)}, JETZT)
        assert sperrgrund(z, cfg) == sperre and z["nicht_verfuegbar"]
    z = v.ergaenze({**a, "inserat_verfuegbarkeit": "reserviert", "inserat_bestaetigt": vor(1)}, JETZT)
    assert sperrgrund(z, cfg) is None and v.HINWEIS_RESERVIERT in hinweise(z)                                 # nur Hinweis
    z = v.ergaenze({**a, "inserat_verfuegbarkeit": "aktiv", "inserat_bestaetigt": vor(30)}, JETZT)
    assert sperrgrund(z, cfg) is None and any("vermutlich" in h for h in hinweise(z))
    z = v.ergaenze({**a, "inserat_verfuegbarkeit": "aktiv", "inserat_bestaetigt": vor(1)}, JETZT)
    assert hinweise(z) == []                                                                                  # Gegenprobe: aktiv und frisch = still


# ---------------------------------------------------------------- 4. Fahrzeug: Rangfolge (rein)
def _b(wert, tage=1):
    return v.bewerte(wert, vor(tage), vor(tage), "neu", JETZT)


@pytest.mark.parametrize("inserate, wert, vermutlich", [
    ([_b("offline"), _b("aktiv")], "aktiv", False), ([_b("verkauft"), _b("reserviert"), _b("offline")], "reserviert", False),
    ([_b("unbekannt"), _b("reserviert")], "reserviert", False), ([_b("offline"), _b("verkauft")], "offline", False),
    ([_b("verkauft"), _b("unbekannt")], "unbekannt", False), ([_b("aktiv", 30), _b("offline")], "aktiv", True),     # nur vermutlich offline schlägt offline
    ([_b("aktiv", 30), _b("reserviert")], "reserviert", False), ([_b("aktiv", 30), _b("verkauft")], "aktiv", True),
    ([_b("aktiv", 30), _b("reserviert", 30)], "aktiv", True), ([_b("verkauft")], "verkauft", False), ([], "unbekannt", False)],
    ids=[f"r{i}" for i in range(11)])
def test_fahrzeug_verfuegbarkeit_rangfolge(inserate, wert, vermutlich):
    r = v.fahrzeug_verfuegbarkeit(inserate)
    assert (r["wert"], r["vermutlich_offline"], r["anzahl"]) == (wert, vermutlich, len(inserate))


def test_fahrzeug_von_ueber_bestaetigte_gruppe(db):
    db.speichere_treffer(treffer("f1"), "Alkoven")
    db.speichere_treffer(treffer("f2", quelle="mobile.de"), "Alkoven")
    assert v.fahrzeug_von(db.con, db.fahrzeug_id_zu("f1"), datetime.now())["anzahl"] == 1
    bestaetige(db, inserat_id(db, "f1"), inserat_id(db, "f2"))
    db.markiere_offline("f1")
    fid = db.fahrzeug_id_zu("f1")
    assert fid == db.fahrzeug_id_zu("f2")
    r = v.fahrzeug_von(db.con, fid, datetime.now())
    assert (r["wert"], r["vermutlich_offline"], r["anzahl"]) == ("aktiv", False, 2)                          # f2 ist noch aktiv
    assert {(i["anzeigen_id"], i["wert"]) for i in r["inserate"]} == {("f1", "offline"), ("f2", "aktiv")}
    db.markiere_offline("f2")
    assert v.fahrzeug_von(db.con, fid, datetime.now())["wert"] == "offline"
    r = v.fahrzeug_von(db.con, fid, datetime.now() + timedelta(days=60))
    assert r["wert"] == "offline"                                                                             # sicher offline bleibt, auch nach Jahren
    assert v.fahrzeug_von(db.con, 99999, datetime.now()) == {"wert": "unbekannt", "vermutlich_offline": False, "anzahl": 0, "inserate": []}


# ---------------------------------------------------------------- 5. Übergänge je Kanal (Datenbank)
def test_suche_setzt_aktiv_und_bestaetigt_ohne_doppelzeilen(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    z = ink(db, "a1")
    assert z["verfuegbarkeit"] == "aktiv" and v.zu_utc(z["zuletzt_bestaetigt"]) is not None
    assert abs((datetime.now(timezone.utc) - v.zu_utc(z["zuletzt_bestaetigt"])).total_seconds()) < 60
    for _ in range(3):
        db.speichere_treffer(treffer("a1"), "Alkoven")                                                       # Wiederholung: keine neuen Beobachtungen
    assert [b[:2] for b in beobachtungen(db, "a1")] == [("suche", "neu")]
    assert ink(db, "a1")["verfuegbarkeit"] == "aktiv"


def test_titel_reserviert_dann_wieder_aktiv_jede_aenderung_ist_eine_beobachtung(db):
    db.speichere_treffer(treffer("a1", titel="RESERVIERT Knaus Sky TI"), "Alkoven")
    assert ink(db, "a1")["verfuegbarkeit"] == "reserviert"
    db.speichere_treffer(treffer("a1", titel="RESERVIERT Knaus Sky TI"), "Alkoven")
    assert len(beobachtungen(db, "a1")) == 1
    db.speichere_treffer(treffer("a1", titel="Knaus Sky TI"), "Alkoven")
    assert ink(db, "a1")["verfuegbarkeit"] == "aktiv" and [b[:2] for b in beobachtungen(db, "a1")] == [("suche", "neu"), ("suche", "geaendert")]
    db.speichere_treffer(treffer("a1", titel="Knaus Sky TI - VERKAUFT"), "Alkoven")
    assert ink(db, "a1")["verfuegbarkeit"] == "verkauft" and len(beobachtungen(db, "a1")) == 3
    db.speichere_treffer(treffer("a1", titel="Knaus Sky TI - nicht verkauft"), "Alkoven")                    # Verneinung ist kein Signal
    assert ink(db, "a1")["verfuegbarkeit"] == "aktiv"


@pytest.mark.parametrize("kanal", ["suche", "manuell", "email"])
def test_jeder_kanal_nennt_sich_in_der_beobachtung(db, kanal):
    db.speichere_treffer(treffer("a1", titel="Hymer - verkauft"), "Alkoven", kanal=kanal)
    assert ink(db, "a1")["verfuegbarkeit"] == "verkauft" and beobachtungen(db, "a1")[0][0] == kanal


def test_mail_zeitpunkt_ist_der_zeitpunkt_der_bestaetigung(db):
    mail = (datetime.now() - timedelta(days=3)).replace(microsecond=0)
    db.speichere_treffer(treffer("m1"), "Alkoven", kanal="email", gesehen_am=mail.isoformat())
    z = ink(db, "m1")
    assert v.zu_utc(z["zuletzt_bestaetigt"]) == mail.astimezone(timezone.utc)                                # Mail-Datum, nicht die Einlesezeit
    assert v.zu_utc(beobachtungen(db, "m1")[0][2]) == mail.astimezone(timezone.utc)


def test_aeltere_mail_ueberschreibt_keine_neuere_verfuegbarkeit(db):
    db.speichere_treffer(treffer("m1"), "Alkoven")
    alt_machen(db, "m1", 5)
    db.markiere_offline("m1", zeitpunkt=vor(3, datetime.now(timezone.utc)))
    vorher, stand = beobachtungen(db, "m1"), ink(db, "m1")["zuletzt_bestaetigt"]
    assert ink(db, "m1")["verfuegbarkeit"] == "offline"
    zu_alt = (datetime.now() - timedelta(days=4)).isoformat(timespec="seconds")
    db.speichere_treffer(treffer("m1", titel="Knaus Sky TI 650 MEG"), "Alkoven", kanal="email", gesehen_am=zu_alt)
    z = ink(db, "m1")
    assert (z["verfuegbarkeit"], z["zuletzt_bestaetigt"]) == ("offline", stand) and beobachtungen(db, "m1") == vorher       # ältere Mail: nichts geändert
    neuer = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    db.speichere_treffer(treffer("m1"), "Alkoven", kanal="email", gesehen_am=neuer)
    assert ink(db, "m1")["verfuegbarkeit"] == "aktiv" and len(beobachtungen(db, "m1")) == len(vorher) + 1     # jüngere Mail gewinnt (wieder eingestellt)


def test_aeltere_mail_ueber_den_importer_gegen_404_von_heute(cfg, db, ads, tmp_path):
    """Dieselbe Altersregel auf dem echten Weg (Suchlauf + 404 im Detailabruf + Mail-Import mit Date-Kopf)."""
    welt = Welt(cfg, db, tmp_path, ads)
    S = ads[20:22]
    welt.suche(S)
    ziel = S[0]
    stunden = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h))                                    # noqa: E731
    db.con.execute("UPDATE inserate SET zuletzt_bestaetigt=? WHERE anzeigen_id=?", (stunden(10).isoformat(timespec="seconds"), ziel["id"]))
    db.con.commit()
    db.markiere_offline(ziel["id"], zeitpunkt=stunden(2).isoformat(timespec="seconds"))                      # 404 vor 2 Stunden
    welt.mail([ziel], md=False, datum=stunden(5))                                                            # Mail von vor 5 Stunden, älter als das 404
    assert ink(db, ziel["id"])["verfuegbarkeit"] == "offline"
    welt.mail([ziel], md=False, datum=stunden(1))                                                            # Mail von vor einer Stunde: jünger
    assert ink(db, ziel["id"])["verfuegbarkeit"] == "aktiv"
    assert ink(db, S[1]["id"])["verfuegbarkeit"] == "aktiv"                                                  # Gegenprobe: das andere Inserat blieb unberührt


def test_detailabruf_404_setzt_offline_und_laesst_den_ankaufsstatus(cfg, db, ads):
    fehlend = ads[3]["id"]
    stat = Importer(cfg, db, abruf=FakeAbruf(ads, fehlend={fehlend})).lauf(cfg["suchen"])
    assert stat["fehler"] is None
    z = ink(db, fehlend)
    assert z["verfuegbarkeit"] == "offline" and v.zu_utc(z["zuletzt_bestaetigt"]) is not None
    assert db.con.execute("SELECT status FROM anzeigen WHERE id=?", (fehlend,)).fetchone()[0] in (None, "neu")       # kein „gelöscht“ mehr
    assert [b[:2] for b in beobachtungen(db, fehlend)] == [("suche", "neu"), ("detail", "geloescht")]
    assert all(r[0] == "aktiv" for r in db.con.execute("SELECT verfuegbarkeit FROM inserate WHERE anzeigen_id<>?", (fehlend,)))   # Gegenprobe
    # erneut gesehen (wieder eingestellt oder Fehlalarm): die jüngere Beobachtung gewinnt, ebenfalls als Beobachtung vermerkt
    db.speichere_treffer({"id": fehlend, "url": "https://x.invalid/x", "titel": "Hymer ML-T 570 T3"}, "Teilintegrierter")
    assert ink(db, fehlend)["verfuegbarkeit"] == "aktiv" and len(beobachtungen(db, fehlend)) == 3


def test_markiere_offline_aendert_den_ankaufsstatus_nie_und_ist_wiederholbar(db):
    db.speichere_treffer(treffer("o1"), "Alkoven")
    db.setze_status("o1", "kontaktiert", notiz="Rückruf 0171 1234567", text="Hallo", betrag=20000)
    vorher = dict(db.con.execute("SELECT * FROM anzeigen WHERE id='o1'").fetchone())
    assert db.markiere_offline("o1") is True
    assert db.markiere_offline("o1") is False                                                                # zweites Mal: keine Doppelzeile
    assert dict(db.con.execute("SELECT * FROM anzeigen WHERE id='o1'").fetchone()) == vorher
    assert [b[:2] for b in beobachtungen(db, "o1")] == [("suche", "neu"), ("detail", "geloescht")]
    assert db.markiere_offline("gibtsnicht") is False


def test_erfolgreicher_detailabruf_bestaetigt_und_erkennt_das_signal(db):
    db.speichere_treffer(treffer("d1", titel="Knaus Sky"), "Alkoven")
    alt_machen(db, "d1", 5)
    db.markiere_offline("d1", zeitpunkt=vor(2, datetime.now(timezone.utc)))
    assert db.bestaetige_verfuegbarkeit("d1", "Knaus Sky") is True and ink(db, "d1")["verfuegbarkeit"] == "aktiv"
    assert db.bestaetige_verfuegbarkeit("d1", "Knaus Sky") is False                                          # unverändert: nur der Zeitpunkt rückt vor
    assert db.bestaetige_verfuegbarkeit("d1", "RESERVIERT Knaus Sky") is True and ink(db, "d1")["verfuegbarkeit"] == "reserviert"
    assert [b[0] for b in beobachtungen(db, "d1")] == ["suche", "detail", "detail", "detail"]


def test_speichere_details_aus_dem_netz_bestaetigt_import_von_seiten_nicht(db):
    db.speichere_treffer(treffer("d2", titel="Knaus Sky"), "Alkoven")
    alt_machen(db, "d2", 5)
    db.markiere_offline("d2", zeitpunkt=vor(2, datetime.now(timezone.utc)))
    # Seiten-/Textimport: kein Netzabruf, keine Bestätigung
    db.speichere_details("d2", {"titel": "Knaus Sky", "details": {}})
    assert ink(db, "d2")["verfuegbarkeit"] == "offline"
    # leerer Abruf („nichts nachzuladen“) bestätigt nichts
    db.speichere_details("d2", {}, netz_abruf=True)
    assert ink(db, "d2")["verfuegbarkeit"] == "offline"
    db.speichere_details("d2", {"titel": "Knaus Sky", "details": {}}, netz_abruf=True)
    assert ink(db, "d2")["verfuegbarkeit"] == "aktiv"


def ereignis_am(zeit, typ="neu", preis=34000, ereignis_id=None, titel="Knaus Sky TI"):
    inserat = None if typ == "geloescht" else Inserat(quelle="mobile.de", anzeigen_id="123", url="https://beispiel.invalid/123", titel=titel, preis=preis,
                                                      ez_jahr=2018, km=70000)
    return InseratEreignis("mobile.de", "123", typ, "api", zeit, inserat, ereignis_id)


def test_ereignis_loeschen_aktivieren_und_altersregel(cfg, db):
    imp = Importer(cfg, db)
    _freigeben(db, "mobile.de")
    zeit = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
    assert imp.importiere_ereignis(ereignis_am(zeit)) == "neu"
    assert ink(db, "123")["verfuegbarkeit"] == "aktiv" and v.zu_utc(ink(db, "123")["zuletzt_bestaetigt"]) == zeit
    assert imp.importiere_ereignis(ereignis_am(zeit + timedelta(days=2), "geloescht", ereignis_id="e2")) == "geloescht"
    z = ink(db, "123")
    assert z["verfuegbarkeit"] == "offline" and v.zu_utc(z["zuletzt_bestaetigt"]) == zeit + timedelta(days=2)
    # ein älteres Ereignis (Zeitpunkt vor dem Löschereignis) darf die Verfügbarkeit nicht zurückdrehen
    assert imp.importiere_ereignis(ereignis_am(zeit + timedelta(days=1), "geaendert", ereignis_id="e3")) == "bekannt"
    assert ink(db, "123")["verfuegbarkeit"] == "offline"
    assert imp.importiere_ereignis(ereignis_am(zeit + timedelta(days=3), "geaendert", ereignis_id="e4")) == "geaendert"
    assert ink(db, "123")["verfuegbarkeit"] == "aktiv"
    assert [b[1] for b in beobachtungen(db, "123")] == ["neu", "geloescht", "geaendert"]
    # dasselbe Ereignis erneut (gleiche ID) und ein gleich lautendes mit späterem Zeitpunkt: keine neue Zeile, nur der Zeitpunkt rückt vor
    assert imp.importiere_ereignis(ereignis_am(zeit + timedelta(days=3), "geaendert", ereignis_id="e4")) == "bekannt"
    assert imp.importiere_ereignis(ereignis_am(zeit + timedelta(days=5), "geaendert", ereignis_id="e5")) == "bekannt"
    assert len(beobachtungen(db, "123")) == 3 and v.zu_utc(ink(db, "123")["zuletzt_bestaetigt"]) == zeit + timedelta(days=5)


def test_ereignis_mit_signal_im_titel(cfg, db):
    imp = Importer(cfg, db)
    _freigeben(db, "mobile.de")
    ev = ereignis_am(datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc), titel="Knaus Sky TI - VERKAUFT")
    assert imp.importiere_ereignis(ev) == "neu" and ink(db, "123")["verfuegbarkeit"] == "verkauft"


def test_unbekannt_bleibt_bis_zur_ersten_beobachtung(db):
    """Altbestand aus v4 (``unbekannt``, ohne Bestätigung) wird nicht umgeschrieben, bis das Inserat wieder gesehen wird."""
    db.speichere_treffer(treffer("u1"), "Alkoven")
    db.con.execute("UPDATE inserate SET verfuegbarkeit='unbekannt', zuletzt_bestaetigt=NULL WHERE anzeigen_id='u1'")
    db.con.commit()
    assert db.gleiche_v4_ab() == 0 and ink(db, "u1")["verfuegbarkeit"] == "unbekannt"
    db.speichere_treffer(treffer("u1"), "Alkoven")
    assert ink(db, "u1")["verfuegbarkeit"] == "aktiv"


# ---------------------------------------------------------------- 6. Wirkung auf Bewertung, Anschreiben, Listen, CSV
def zeilen_von(cfg, db):
    return {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}


def setze(db, ad_id, wert, bestaetigt=None):
    db.con.execute("UPDATE inserate SET verfuegbarkeit=?, zuletzt_bestaetigt=? WHERE anzeigen_id=?",
                   (wert, bestaetigt or datetime.now(timezone.utc).isoformat(timespec="seconds"), ad_id))
    db.con.commit()


def bereite_vor(cfg, db, n=3):
    """Drei Inserate, die angeschrieben werden könnten (bereit, ohne Sperre)."""
    z = [x for x in zeilen_von(cfg, db).values() if x["bereit"] and not x["sperre"]]
    assert len(z) >= n
    return [x["a"]["id"] for x in z[:n]]


def weiteres(cfg, db, *ausser):
    return next(i for i in bereite_vor(cfg, db, len(ausser) + 1) if i not in ausser)


def test_wirkung_auf_sperre_bereit_und_hinweise(cfg, db, importiert):
    offline, verkauft, reserviert = bereite_vor(cfg, db)
    vorher = zeilen_von(cfg, db)
    db.markiere_offline(offline)
    setze(db, verkauft, "verkauft")
    setze(db, reserviert, "reserviert")
    nachher = zeilen_von(cfg, db)
    assert len(nachher) == len(vorher)                                                                       # keine Zeile verschwindet mehr
    z = nachher[offline]
    assert (z["sperre"], z["bereit"], z["brief"], z["ausblenden"], z["a"]["verfuegbarkeit"]) == (v.SPERRE_OFFLINE, False, None, True, "offline")
    z = nachher[verkauft]
    assert (z["sperre"], z["bereit"], z["brief"], z["ausblenden"]) == (v.SPERRE_VERKAUFT, False, None, True)
    z = nachher[reserviert]                                                                                  # reserviert: weiter anschreibbar, mit Hinweis
    assert (z["sperre"], z["bereit"], z["ausblenden"]) == (None, True, False) and z["brief"] and v.HINWEIS_RESERVIERT in z["hinweise"]
    for ad_id, z in nachher.items():                                                                         # Gegenprobe: alle übrigen Zeilen unverändert
        if ad_id not in (offline, verkauft, reserviert):
            assert (z["sperre"], z["bereit"], z["hinweise"]) == (vorher[ad_id]["sperre"], vorher[ad_id]["bereit"], vorher[ad_id]["hinweise"])


def test_vermutlich_offline_hinweis_sperrt_nicht_und_schwelle_aus_der_config(cfg, db, importiert):
    ad = bereite_vor(cfg, db, 1)[0]
    setze(db, ad, "aktiv", vor(20, datetime.now(timezone.utc)))
    z = zeilen_von(cfg, db)[ad]
    assert z["a"]["vermutlich_offline"] and z["sperre"] is None and z["bereit"] and any("vermutlich" in h for h in z["hinweise"])
    assert z["a"]["verfuegbarkeit"] == "aktiv" and db.con.execute("SELECT verfuegbarkeit FROM inserate WHERE anzeigen_id=?", (ad,)).fetchone()[0] == "aktiv"
    cfg["verfuegbarkeit"] = {"offline_nach_tagen": 30}
    assert not zeilen_von(cfg, db)[ad]["a"]["vermutlich_offline"]
    cfg["verfuegbarkeit"] = {"offline_nach_tagen": "kaputt"}                                                  # Fehleingabe: Standard 14, keine Ausnahme
    assert zeilen_von(cfg, db)[ad]["a"]["vermutlich_offline"]
    cfg["verfuegbarkeit"] = {"offline_nach_tagen": 21}
    assert not zeilen_von(cfg, db)[ad]["a"]["vermutlich_offline"]


def test_altbestand_status_geloescht_bleibt_sichtbar_und_verhaelt_sich_wie_offline(cfg, db, importiert):
    alt, neu = bereite_vor(cfg, db, 2)
    vorher_anzahl = len(zeilen_von(cfg, db))
    db.setze_status(alt, "gelöscht")                                                                         # Stand vor P3-04
    db.markiere_offline(neu)                                                                                 # Stand ab P3-04
    z = zeilen_von(cfg, db)
    assert len(z) == vorher_anzahl                                                                           # früher verschwand die Zeile ganz
    a, n = z[alt], z[neu]
    # Status bleibt lesbar, gespeicherter Wert unverändert
    assert (a["a"]["status"], a["a"]["verfuegbarkeit"]) == ("gelöscht", "offline")
    gleich = (v.SPERRE_OFFLINE, False, True, False)
    assert (a["sperre"], a["bereit"], a["ausblenden"], a["neu"]) == (n["sperre"], n["bereit"], n["ausblenden"], n["neu"]) == gleich
    # in Arbeit (Status ≠ neu) + offline: nicht ausgeblendet, die Arbeit bleibt sichtbar
    db.setze_status(neu, "kontaktiert", text="Hallo", betrag=1000)
    assert zeilen_von(cfg, db)[neu]["ausblenden"] is False and zeilen_von(cfg, db)[neu]["sperre"] == v.SPERRE_OFFLINE


def test_offline_aeltere_dublette_gilt_nicht_mehr_als_noch_online(cfg, db):
    db.speichere_treffer(treffer("x1", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.speichere_treffer(treffer("x2", titel="Hobby Optima De Luxe 65", marke="Hobby"), "Alkoven")
    db.con.execute("UPDATE anzeigen SET erstmals_gesehen='2026-09-01T10:00:00' WHERE id='x1'")
    db.con.commit()
    assert "ist noch online" in (zeilen_von(cfg, db)["x2"]["a"].get("duplikat") or "")
    db.markiere_offline("x1")
    assert "ist noch online" not in (zeilen_von(cfg, db)["x2"]["a"].get("duplikat") or "")                  # kein Hinweis auf eine Anzeige, die weg ist


def test_kpi_zaehler_und_html_abzeichen_ohne_innerhtml_aus_daten(cfg, db, importiert):
    offline, verkauft, reserviert = bereite_vor(cfg, db)
    db.markiere_offline(offline)
    setze(db, verkauft, "verkauft")
    setze(db, reserviert, "reserviert")
    db.speichere_treffer(treffer("h1", titel="<script>alert(1)</script> - reserviert"), "Alkoven")
    zeilen = list(bewerte_alle(cfg, db, BASIS))
    html, zaehl = render_html(cfg, zeilen, BASIS)
    assert html.count("data-verfuegbarkeit") == 4 and 'id="nurverf"' in html and "nur verfügbare" in html
    assert "<script>alert(1)" not in html                                                                     # Jinja maskiert Titel
    assert re.search(r'data-id="%s"[^>]*data-verf="offline"' % offline, html, re.S)
    assert re.search(r'data-id="%s"[^>]*data-verf="reserviert"' % reserviert, html, re.S)
    ohne = [z for z in zeilen if z["ausblenden"]]
    assert len(ohne) == 2
    assert zaehl["gruen"] == sum(z["b"].ampel == "gruen" and not z["ausblenden"] for z in zeilen)           # ausgeblendete zählen nicht in die Kennzahlen


def test_csv_spalten_verfuegbarkeit(cfg, db, importiert, tmp_path):
    offline, verkauft, reserviert = bereite_vor(cfg, db)
    db.markiere_offline(offline)
    setze(db, verkauft, "verkauft")
    setze(db, reserviert, "reserviert")
    setze(db, weiteres(cfg, db, offline, verkauft, reserviert), "aktiv", vor(30, datetime.now(timezone.utc)))
    erg = schreibe_ausgaben(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    with open(erg["csv"], newline="", encoding="utf-8-sig") as f:
        zeilen = list(csv.reader(f, delimiter=";"))
    kopf = zeilen[0]
    assert kopf[kopf.index("Verfügbarkeit") + 1] == "Zuletzt bestätigt" and kopf[-3:] == ["Bearbeiter", "Übernommen am", "Kontaktiert von"]
    zelle = {r[0]: r[kopf.index("Verfügbarkeit")] for r in zeilen[1:]}
    assert (zelle[offline], zelle[verkauft], zelle[reserviert]) == ("offline", "verkauft", "reserviert")
    assert list(zelle.values()).count("vermutlich offline") == 1 and set(zelle.values()) <= {"aktiv", "offline", "verkauft", "reserviert", "vermutlich offline"}
    best = {r[0]: r[kopf.index("Zuletzt bestätigt")] for r in zeilen[1:]}
    assert all(best[i] for i in (offline, verkauft, reserviert))


# ---------------------------------------------------------------- 6b. QA-Auflagen: F1 (Titel privater Verkäufer), F2 (Arbeit nie ausblenden), F4 (Zeitpunkt)
PRIVAT_TITEL = ["Rentner verkauft gepflegten Hymer B 544", "Familie verkauft Wohnmobil", "Ehepaar verkauft Hymer", "Opa verkauft sein Wohnmobil",
                "Hymer B 544 verkauft wg. Umzug", "Hymer verkauft aus Altersgründen", "Wohnmobil verkauft privat", "Hymer verkauft da neues Fahrzeug",
                "Hymer B 544 verkauft, weil zu groß", "Verkauft: nur an Privat", "Preis reserviert für Abholer", "Probefahrt reserviert",
                "Hymer B 544 reserviert für Händler? Nein"]


@pytest.mark.parametrize("titel", PRIVAT_TITEL, ids=[f"t{i}" for i in range(len(PRIVAT_TITEL))])
def test_privattitel_sperren_und_verstecken_nichts_ende_zu_ende(cfg, db, titel):
    """Gegenprobe zu F1: ein Angebot privater Verkäufer bleibt aktiv, ohne Sperre durch die Verfügbarkeit und nicht ausgeblendet."""
    db.speichere_treffer(treffer("t1", titel=titel), "Alkoven")
    assert ink(db, "t1")["verfuegbarkeit"] == "aktiv"
    z = zeilen_von(cfg, db)["t1"]
    assert z["a"]["verfuegbarkeit"] == "aktiv" and z["ausblenden"] is False
    assert z["sperre"] not in (v.SPERRE_OFFLINE, v.SPERRE_VERKAUFT) and v.HINWEIS_RESERVIERT not in z["hinweise"]


def test_markenartige_titel_werden_ende_zu_ende_erkannt(cfg, db):
    for ad_id, titel, wert in (("s1", "Knaus Sky TI - VERKAUFT", "verkauft"), ("s2", "[reserviert] Hymer B 544", "reserviert")):
        db.speichere_treffer(treffer(ad_id, titel=titel), "Alkoven")
        assert ink(db, ad_id)["verfuegbarkeit"] == wert
    z = zeilen_von(cfg, db)
    assert z["s1"]["sperre"] == v.SPERRE_VERKAUFT and z["s1"]["ausblenden"] and z["s2"]["sperre"] != v.SPERRE_VERKAUFT


def _arbeit_variante(db, ad_id, art):
    if art == "reservierung":
        db.con.execute("INSERT INTO bearbeitung (anzeige_id, bearbeiter_id, uebernommen_am) VALUES (?, 1, '2026-10-22T10:00:00')", (ad_id,))
    elif art == "besichtigung":
        db.con.execute("INSERT INTO besichtigungen (anzeige_id, daten_json) VALUES (?, '{}')", (ad_id,))
    elif art == "notiz":
        db.setze_notiz(ad_id, "Rückruf vereinbart")
    db.con.commit()


@pytest.mark.parametrize("art", ["keine", "reservierung", "besichtigung", "notiz"])
def test_offline_wird_nur_ohne_jede_arbeit_ausgeblendet(cfg, db, importiert, art, server):
    ad = bereite_vor(cfg, db, 1)[0]
    _arbeit_variante(db, ad, art)
    db.markiere_offline(ad)
    z = zeilen_von(cfg, db)[ad]
    assert z["a"]["verfuegbarkeit"] == "offline" and z["sperre"] == v.SPERRE_OFFLINE                       # gesperrt bleibt es immer
    assert z["ausblenden"] is (art == "keine")
    standard = {f["id"] for f in lokal(server)("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert (ad in standard) is (art != "keine")                                                              # API standard entsprechend
    html, _ = render_html(cfg, list(zeilen_von(cfg, db).values()), BASIS)
    assert re.search(r'data-id="%s"[^>]*data-ausblenden="%d"' % (ad, 1 if art == "keine" else 0), html, re.S)    # serverseitig berechnet


def test_ausblenden_regel_steht_nur_im_server_und_js_liest_das_attribut():
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "k.dataset.ausblenden === '1'" in html and "k.dataset.verf === 'offline'" not in html


def seiten_dateien(welt, ads, alter_stunden):
    """Suchseite + Anzeigenseiten im Importordner, mit Dateizeit vor ``alter_stunden`` Stunden (Zeitpunkt des Speicherns im Browser)."""
    (welt.seiten / "suche.html").write_text(such_html(ads), encoding="utf-8")
    for a in ads:
        (welt.seiten / f"detail_{a['id']}.html").write_text(detailseite(a), encoding="utf-8")
    zeit = (datetime.now() - timedelta(hours=alter_stunden)).timestamp()
    for datei in welt.seiten.glob("*.html"):
        os.utime(datei, (zeit, zeit))


def test_aeltere_gespeicherte_seite_hebt_ein_404_von_heute_nicht_auf(cfg, db, ads, tmp_path):
    welt = Welt(cfg, db, tmp_path, ads)
    S = ads[20:22]
    welt.suche(S)
    db.con.execute("UPDATE inserate SET zuletzt_bestaetigt=? WHERE anzeigen_id=?", (vor(1, datetime.now(timezone.utc)), S[0]["id"]))
    db.con.commit()
    db.markiere_offline(S[0]["id"])                                                                          # 404 heute
    seiten_dateien(welt, S, alter_stunden=6)                                                                 # Seite wurde vor 6 Stunden gespeichert
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(welt.seiten)
    assert ink(db, S[0]["id"])["verfuegbarkeit"] == "offline"
    assert ink(db, S[1]["id"])["verfuegbarkeit"] == "aktiv"                                                  # Gegenprobe: unberührtes Inserat
    seiten_dateien(welt, S, alter_stunden=0)                                                                 # Seite von jetzt: neuer als das 404
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(welt.seiten)
    assert ink(db, S[0]["id"])["verfuegbarkeit"] == "aktiv"


def test_unplausibel_alte_mail_aendert_keine_verfuegbarkeit(cfg, db, ads, tmp_path):
    welt = Welt(cfg, db, tmp_path, ads)
    S = ads[20:22]
    welt.suche(S)
    db.markiere_offline(S[0]["id"])
    # Datum > 365 Tage: als Beobachtung gilt „jetzt“, für die Verfügbarkeit aber das (alte) Datum
    welt.mail([S[0]], md=False, datum=datetime.now(timezone.utc) - timedelta(days=400))
    z = ink(db, S[0]["id"])
    assert z["verfuegbarkeit"] == "offline"
    assert ink(db, S[1]["id"])["verfuegbarkeit"] == "aktiv"
    # ein dadurch NEU angelegtes Inserat bekommt keine frische Bestätigung: es gilt sofort als vermutlich offline
    welt.mail([ads[40]], md=False, datum=datetime.now(timezone.utc) - timedelta(days=400))
    n = ink(db, ads[40]["id"])
    assert v.bewerte(n["verfuegbarkeit"], n["zuletzt_bestaetigt"], n["zuletzt_gesehen"], None, datetime.now())["vermutlich_offline"] is True


# ---------------------------------------------------------------- 7. API
def test_api_felder_filter_und_fahrzeug(server, db, cfg, importiert):
    offline, verkauft, reserviert = bereite_vor(cfg, db)
    db.markiere_offline(offline)
    setze(db, verkauft, "verkauft")
    setze(db, reserviert, "reserviert")
    alt = weiteres(cfg, db, offline, verkauft, reserviert)
    setze(db, alt, "aktiv", vor(20, datetime.now(timezone.utc)))
    c = lokal(server)
    s, alle, _ = c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=alle")
    assert s == 200
    nach_id = {f["id"]: f for f in alle}
    assert {"verfuegbarkeit", "zuletzt_bestaetigt", "vermutlich_offline", "verfuegbarkeit_text"} <= set(alle[0])
    assert (nach_id[offline]["verfuegbarkeit"], nach_id[offline]["verfuegbarkeit_text"]) == ("offline", "offline")
    assert nach_id[verkauft]["verfuegbarkeit_text"] == "verkauft" and nach_id[reserviert]["verfuegbarkeit_text"] == "reserviert"
    assert nach_id[reserviert]["sperre"] is None and nach_id[offline]["sperre"] == v.SPERRE_OFFLINE
    f = nach_id[alt]
    assert (f["verfuegbarkeit"], f["vermutlich_offline"]) == ("aktiv", True) and f["zuletzt_bestaetigt"]
    assert f["verfuegbarkeit_text"].startswith("vermutlich offline")
    ruhig = next(x for x in alle if x["verfuegbarkeit"] == "aktiv" and not x["vermutlich_offline"])
    assert ruhig["verfuegbarkeit_text"] is None                                                               # kein Abzeichen bei aktiv
    # Filter: Standard blendet verkauft/offline ohne Ankaufsarbeit aus (wie früher „gelöscht“), „alle“ nichts, „nur“ alles Nicht-Verfügbare
    standard = {x["id"] for x in c("GET", "/api/fahrzeuge?filter=alle")[1]}
    assert offline not in standard and verkauft not in standard and reserviert in standard and alt in standard
    assert {x["id"] for x in c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=nur")[1]} == standard
    assert len(alle) == len(standard) + 2
    assert c("GET", "/api/fahrzeuge?filter=alle&verfuegbar=quatsch")[0] == 400
    d = c("GET", f"/api/fahrzeug/{offline}")[1]                                                               # Detail auch für ausgeblendete
    assert d["verfuegbarkeit"] == "offline" and d["verfuegbarkeit_fahrzeug"]["wert"] == "offline" and d["verfuegbarkeit_fahrzeug"]["anzahl"] == 1
    assert d["verfuegbarkeit_fahrzeug"]["inserate"][0]["anzeigen_id"] == offline


def test_api_preisverlauf_unveraendert(server, db, cfg, importiert):
    ad = bereite_vor(cfg, db, 1)[0]
    c = lokal(server)
    d = c("GET", f"/api/preisverlauf?anzeige={ad}")[1]
    assert set(d) == {"anzeige", "umfang", "inserat_id", "fahrzeug_id", "inserate", "anzahl", "verlauf"}
    assert set(d["verlauf"][0]) == {"zeitpunkt", "zeitpunkt_roh", "preis", "kanal", "plattform", "anzeigen_id", "inserat_id", "vorher", "aenderung",
                                    "differenz"}


def test_lesen_schreibt_nichts(cfg, db, importiert):
    db.con.commit()
    vor_ = {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in ("anzeigen", "inserate", "beobachtungen", "preis_historie")}
    bewerte_alle(cfg, db, BASIS)
    db.verfuegbarkeit_zu()
    assert vor_ == {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in vor_}


# ---------------------------------------------------------------- 8. Oberfläche (statisch)
def test_oberflaeche_statisch():
    mobil = (STATIC / "mobil.js").read_text(encoding="utf-8")
    funktion = mobil[mobil.index("function verfTag"):mobil.index("function ampelTag")]
    assert "esc(f.verfuegbarkeit_text)" in funktion and "innerHTML" not in funktion and "+ f.verfuegbarkeit_text" not in funktion
    assert mobil.count("+ verfTag(f)") == 2                                                                     # Liste und Fahrzeugdetail
    css = (STATIC / "mobil.css").read_text(encoding="utf-8")
    assert ".tag.verf" in css and ".tag.verf.reserviert" in css
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 10
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "data-verfuegbarkeit" in html and 'id="nurverf"' in html and "nurVerf.checked" in html and "a.verfuegbarkeit_text" in html
    assert "| safe" not in html[html.index("data-verfuegbarkeit"):html.index("data-verfuegbarkeit") + 400]       # kein ungeprüftes HTML


# ---------------------------------------------------------------- 9. Schema 13: Migration gegen Altbestände jeder Vorversion
def bis_13(monkeypatch):
    """Schritt 13 ist hier der letzte bekannte Schritt: die Tests prüfen ihn so, wie er zu seiner Zeit lief (Schritt 14 prüft tests/test_anbieter.py)."""
    _alt_schritte(monkeypatch, 13)


def baue_v12(pfad, monkeypatch, tmp_path):
    baue_v11(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 12)
        assert migriere(pfad, tmp_path / "stand12") == [12]
    assert lese_version(pfad) == 12


def mit_zeitstempeln(pfad):
    """Fügt Inserate mit allen Arten von Altwerten ein (naive lokale Zeit, Zeit mit Offset, leer, unlesbar; je Verfügbarkeit)."""
    con = sqlite3.connect(pfad)
    for i, (wert, gesehen) in enumerate([("aktiv", "2026-10-02T10:00:00+02:00"), ("aktiv", "2026-10-01T10:00:00"), ("offline", "2026-09-30T08:15:00+00:00"),
                                          ("unbekannt", "2026-10-03T10:00:00+00:00"), ("aktiv", ""), ("aktiv", "kein Datum"),
                                          ("verkauft", "2026-10-04T10:00:00+00:00"),
                                          ("reserviert", "2026-10-05T10:00:00+00:00")]):
        con.execute("INSERT INTO inserate (plattform, anzeigen_id, verfuegbarkeit, erstmals_gesehen, zuletzt_gesehen) VALUES ('kleinanzeigen', ?, ?, 'a', ?)",
                    (f"z{i}", wert, gesehen))
    con.commit()
    con.close()


def zustand13(pfad):
    return {r[0]: r[1:] for r in _sql(pfad, "SELECT anzeigen_id, verfuegbarkeit, zuletzt_gesehen, zuletzt_bestaetigt FROM inserate")}


@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v11", "v12"])
def test_migration_auf_13_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v11":
        baue_v11(pfad, monkeypatch, tmp_path)
    elif art == "v12":
        baue_v12(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    if art in ("v11", "v12"):
        mit_zeitstempeln(pfad)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    zaehlung = {t: len(z) for t, (_, z) in vorher.items()}
    erledigt = migriere(pfad, ziel)
    assert erledigt[-1] == 13 and lese_version(pfad) == 13 and versionen(pfad)[-1] == 13
    assert erledigt == (list(range(2, 14)) if art == "v1" else list(range(vorher_version + 1, 14)))
    nachher = _abbild(pfad)
    assert {t: len(nachher[t][1]) for t in zaehlung if t != "fahrzeuge"} == {t: n for t, n in zaehlung.items() if t != "fahrzeuge"}     # Zeilenzahlen
    neue = {t: v_ for t, v_ in vorher.items() if t != "fahrzeuge"}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue                    # alle bisherigen Spalten und Zeilen gleich
    assert "zuletzt_bestaetigt" in [r[1] for r in _sql(pfad, "PRAGMA table_info(inserate)")]
    # Status, Notizen, Kontakt, Preise vollständig da
    if art in ("v10", "v11", "v12"):
        assert _sql(pfad, "SELECT status, notiz, angebot_betrag FROM anzeigen WHERE id='k1'") == [("kontaktiert", "Müller 0171 1234567", 25000)]
        assert _sql(pfad, "SELECT kaufpreis FROM ankaeufe") == [(18000,)]
        assert sorted(r[0] for r in _sql(pfad, "SELECT preis FROM anzeigen WHERE preis IS NOT NULL")) == [1, 30000, 41500]
        assert _sql(pfad, "SELECT COUNT(*) FROM preis_historie")[0][0] == len(vorher["preis_historie"][1])
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)] and _sql(pfad, "PRAGMA foreign_key_check") == []
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v13" in k.name]
    assert len(kopien) == 1 and _sql(kopien[0], "PRAGMA integrity_check") == [("ok",)] and lese_version(kopien[0]) == vorher_version
    assert _abbild(kopien[0]) == vorher                                                                           # Sicherung = Stand davor, vollständig
    assert _sql(pfad, "SELECT name FROM sqlite_master WHERE name='idx_zuordnungen_entscheidung'") == [("idx_zuordnungen_entscheidung",)]


def test_rueckfuellung_zuletzt_bestaetigt(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    vorher = zustand13_alt = {r[0]: r[1:3] for r in _sql(pfad, "SELECT anzeigen_id, verfuegbarkeit, zuletzt_gesehen FROM inserate")}
    migriere(pfad, ziel)
    z = zustand13(pfad)
    assert {k: x[:2] for k, x in z.items()} == vorher                                                           # Verfügbarkeit und zuletzt_gesehen unverändert
    assert z["z0"][2] == "2026-10-02T08:00:00+00:00"                                                            # Offset nach UTC
    assert z["z1"][2] == datetime.fromisoformat("2026-10-01T10:00:00").astimezone(timezone.utc).isoformat(timespec="seconds")   # naive Zeit = lokal
    assert z["z2"][2] == "2026-09-30T08:15:00+00:00"                                                            # auch offline
    assert z["z3"][2] is None and z["z6"][2] is None and z["z7"][2] is None                                     # unbekannt/verkauft/reserviert: nichts erfunden
    # leer/unlesbar bleibt leer (Anzeige fällt auf zuletzt_gesehen zurück)
    assert z["z4"][2] is None and z["z5"][2] is None
    assert all(zeit is None for k, (_, _, zeit) in z.items() if not k.startswith("z") and zustand13_alt.get(k, ("",))[0] not in ("aktiv", "offline"))


def test_schritt_13_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    stand, schema = _abbild(pfad), _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_13(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _abbild(pfad) == stand and _sql(pfad, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema


def _noch_12(pfad, vorher):
    assert lese_version(pfad) == 12 and versionen(pfad)[-1] == 12 and _abbild(pfad) == vorher
    assert "zuletzt_bestaetigt" not in [r[1] for r in _sql(pfad, "PRAGMA table_info(inserate)")]
    assert not _sql(pfad, "SELECT 1 FROM sqlite_master WHERE name='idx_zuordnungen_entscheidung'")


def test_fehler_im_schritt_13_rollt_zurueck_sicherung_bleibt_dann_gelingt_es(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    vorher, echt = _abbild(pfad), migrationen._schritt_13

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 13, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    _noch_12(pfad, vorher)
    kopien = [k for k in sicherungen(ziel, "db") if "vor-v13" in k.name]
    assert len(kopien) == 1 and _abbild(kopien[0]) == vorher
    monkeypatch.setitem(migrationen.SCHRITTE, 13, echt)
    assert migriere(pfad, ziel) == [13]


def test_verletzte_invariante_in_schritt_13_rollt_zurueck(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    vorher, echt, aufrufe = _abbild(pfad), migrationen._zaehle_v11, []

    def mit_nebeneffekt(con):
        aufrufe.append(1)
        if len(aufrufe) == 2:
            con.execute("INSERT INTO bearbeitung (anzeige_id) VALUES ('eingeschleust')")
        return echt(con)

    monkeypatch.setattr(migrationen, "_zaehle_v11", mit_nebeneffekt)
    with pytest.raises(MigrationsFehler, match="zurückgerollt") as fehler:
        migriere(pfad, ziel)
    assert "Zeilenzahlen" in str(fehler.value)
    _noch_12(pfad, vorher)


def test_geaenderter_wert_in_schritt_13_wird_bemerkt(tmp_path, monkeypatch):
    """Die Inhaltsprüfung des Schritts bemerkt auch eine Änderung bestehender Inseratsspalten (nicht nur die Zeilenzahl)."""
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    vorher, echt, aufrufe = _abbild(pfad), migrationen._zaehle_v11, []

    def verfaelscht(con):
        aufrufe.append(1)
        if len(aufrufe) == 2:                                       # zweite Zählung = nach dem Schritt: gleiche Zeilenzahlen, aber ein Preis anders
            con.execute("UPDATE inserate SET preis = COALESCE(preis, 0) + 1")
        return echt(con)

    monkeypatch.setattr(migrationen, "_zaehle_v11", verfaelscht)
    with pytest.raises(MigrationsFehler, match="Inseratsspalten"):
        migriere(pfad, ziel)
    _noch_12(pfad, vorher)


def test_sicherung_vor_v13_laesst_sich_zurueckspielen_und_erneut_migrieren(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    vorher = _abbild(pfad)
    assert migriere(pfad, ziel) == [13]
    kopie = [k for k in sicherungen(ziel, "db") if "vor-v13" in k.name][0]
    wiederherstellen(kopie, pfad, bestaetigt=True, ziel_ordner=ziel)
    _noch_12(pfad, vorher)
    assert migriere(pfad, ziel) == [13]
    assert _nachher_wie_vorher(pfad, vorher) == vorher


def test_neue_datenbank_hat_die_spalte_und_den_index(tmp_path):
    d = Datenbank(str(tmp_path / "neu.sqlite"))
    assert lese_version(tmp_path / "neu.sqlite") >= 13
    assert "zuletzt_bestaetigt" in [r[1] for r in d.con.execute("PRAGMA table_info(inserate)")]
    assert d.con.execute("SELECT name FROM sqlite_master WHERE name='idx_zuordnungen_entscheidung'").fetchone()


def test_abfrageplaene_nutzen_indizes(db):
    plan = " | ".join(r["detail"] for r in db.con.execute("EXPLAIN QUERY PLAN SELECT * FROM fahrzeug_zuordnungen WHERE entscheidung_id = ?", (1,)))
    assert "idx_zuordnungen_entscheidung" in plan and "SCAN" not in plan, plan
    plan = " | ".join(r["detail"] for r in db.con.execute(
        "EXPLAIN QUERY PLAN SELECT a.id, i.verfuegbarkeit, i.zuletzt_bestaetigt, i.zuletzt_gesehen FROM anzeigen a JOIN inserate i "
        "ON i.plattform = COALESCE(NULLIF(a.quelle, ''), ?) AND i.anzeigen_id = a.id", ("kleinanzeigen",)))
    # ein Durchlauf über inserate, je Zeile eine Indexsuche
    assert "SEARCH a USING INDEX" in plan and "SCAN a" not in plan, plan
    plan = " | ".join(r["detail"] for r in db.con.execute(
        "EXPLAIN QUERY PLAN SELECT i.plattform FROM inserate i LEFT JOIN anzeigen a "
        "ON a.id = i.anzeigen_id AND COALESCE(NULLIF(a.quelle, ''), ?) = i.plattform "
        "WHERE i.fahrzeug_id = ?", ("kleinanzeigen", 1)))
    assert "idx_inserate_fahrzeug" in plan, plan


ABBRUCHSTELLEN = 24                  # ``con.execute``-Aufrufe in Schritt 13 (der Test unten stellt sicher, dass die Spanne bis hinter den letzten reicht)


@pytest.mark.parametrize("n", range(1, ABBRUCHSTELLEN + 2))
def test_abbruch_mitten_im_schritt_13_rollt_alles_zurueck(tmp_path, monkeypatch, n):
    bis_13(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    vorher, echt, aufrufe = _abbild(pfad), migrationen._schritt_13, {}

    def abbrechen(con):
        p = _Abbruch(con, n)
        try:
            echt(p)
        finally:
            aufrufe["i"] = p.i

    monkeypatch.setitem(migrationen.SCHRITTE, 13, abbrechen)
    try:
        migriere(pfad, ziel)
        assert n > aufrufe["i"]                                       # nur Abbruchstellen hinter dem letzten Aufruf laufen durch
        assert lese_version(pfad) == 13
    except MigrationsFehler:
        _noch_12(pfad, vorher)
        assert any("vor-v13" in k.name for k in sicherungen(ziel, "db"))
        monkeypatch.setitem(migrationen.SCHRITTE, 13, echt)
        assert migriere(pfad, ziel) == [13]


def test_abbruchstellen_decken_alle_aufrufe_von_schritt_13_ab(tmp_path, monkeypatch):
    bis_13(monkeypatch)
    pfad = tmp_path / "db.sqlite"
    baue_v12(pfad, monkeypatch, tmp_path)
    mit_zeitstempeln(pfad)
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        p = _Abbruch(con, 10_000)
        migrationen._schritt_13(p)
        con.execute("ROLLBACK")
    finally:
        con.close()
    assert p.i <= ABBRUCHSTELLEN, f"Schritt 13 hat {p.i} execute-Aufrufe, die Abbruchstellen enden bei {ABBRUCHSTELLEN}"
