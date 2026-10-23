"""P3-05 (ADR-043): Anbieterart (privat/gewerblich/unbekannt) mit Herkunft der Einstufung; Rechner ohne unbekannte Anbieter (P2-05d).

Geprüft: Regeln (wer ersetzt wen), Schreibwege der Datenbank (Treffer, Details, Korrektur), Herkunft je Quelle (Kleinanzeigen-Liste mit und ohne
Privatfilter, Detailseite, mobile.de, Text-Import, Mail), Vergleichsbasis des Rechners, Wirkung auf Sperre/Hinweise, API, CSV, Oberfläche und
Schema 14 gegen Altbestände. Alles offline; Seiten sind nachgebaut.
"""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

import pytest

from tests.daten import BASIS, SUCH_URL, FakeAbruf, detail_html, such_html
from tests.test_fahrzeuge import _abbild, _alt_schritte, _nachher_wie_vorher, _sql, baue
from tests.test_migration import pruefsumme, versionen
from tests.test_team_bearbeitung import anmelden, lokal, server  # noqa: F401 – Fixtures
from tests.test_verfuegbarkeit import baue_v12
from wmscout import anbieter as an
from wmscout import migrationen
from wmscout.audit import einordnen
from wmscout.ausgabe import schreibe_ausgaben
from wmscout.bewertung.anschreiben import HINWEIS_ANBIETER_UNBEKANNT, hinweise, sperrgrund
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.kalkulation import vergleich_auszug
from wmscout.bewertung.rechner import Rechner, privatangebot
from wmscout.eingang.text import TextEingang
from wmscout.haendler import HaendlerSpeicher
from wmscout.importer import Importer
from wmscout.migrationen import MigrationsFehler, lese_version, migriere
from wmscout.quellen.kleinanzeigen.parser import parse_detailseite, parse_suchseite
from wmscout.quellen.mobilede import parse_suchseite as md_suchseite
from wmscout.sicherung import sicherungen
from wmscout.team import TeamSpeicher

MD_DATEN = Path(__file__).resolve().parent / "seiten" / "mobilede"
STATIC = BASIS / "wmscout" / "web" / "static"
K, N, A, S, O, ALT = an.KORREKTUR, an.NUTZER, an.ANZEIGE, an.SUCHFILTER, an.OHNE_KENNZEICHEN, an.ALTBESTAND  # noqa: E741 – kurze Namen für die Regeltabelle


def anb(db, ad_id):
    db.con.commit()
    return tuple(db.con.execute("SELECT gewerblich, anbieter_herkunft FROM anzeigen WHERE id=?", (ad_id,)).fetchone())


def treffer(i="a1", **kw):
    return {"id": i, "url": f"https://www.kleinanzeigen.de/s-anzeige/x/{i}-220-1", "titel": "Knaus Sky TI 650 MEG", "preis": 40000, "km": 90000,
            "ez_jahr": 2016, "ort": "70173 Stuttgart", "marke": "Knaus", **kw}


# ---------------------------------------------------------------- 1. Regeln (ohne Datenbank)
def test_typ_und_einstufung():
    assert (an.typ(0), an.typ(False), an.typ(1), an.typ(True), an.typ(None)) == ("privat", "privat", "gewerblich", "gewerblich", "unbekannt")
    assert an.einstufung(None, A) == {"typ": "unbekannt", "herkunft": None, "belegt": False, "text": "Anbieter unbekannt"}
    assert an.einstufung(0, S) == {"typ": "privat", "herkunft": S, "belegt": True, "text": "privat (Suche nur Privatanbieter)"}
    assert an.einstufung(1, A)["text"] == "gewerblich (laut Anzeige)" and an.einstufung(0, N)["text"] == "privat (beim Einlesen vom Team angegeben)"
    assert an.einstufung(0, K)["text"] == "privat (vom Team korrigiert)" and an.einstufung(0, K)["belegt"] is True
    assert an.einstufung(None, K) == {"typ": "unbekannt", "herkunft": K, "belegt": False, "text": "Anbieter unbekannt (vom Team korrigiert)"}
    assert an.einstufung(0, O)["belegt"] is False and an.einstufung(0, None) == an.einstufung(0, ALT) == an.einstufung(0, "quatsch")
    assert an.einstufung(1, ALT)["text"] == "gewerblich (Altbestand, Herkunft nicht erfasst)"


def test_herkunft_fuer_ist_lieber_zu_schwach_als_zu_stark():
    assert an.herkunft_fuer(None, A) is None
    assert (an.herkunft_fuer(1, None), an.herkunft_fuer(0, None), an.herkunft_fuer(0, "quatsch")) == (A, O, O)
    assert an.herkunft_fuer(0, ALT) == O and an.herkunft_fuer(1, K) == A    # „Altbestand“ vergibt nur die Migration, „Korrektur“ nur die App
    assert [an.herkunft_fuer(0, h) for h in (N, A, S, O)] == [N, A, S, O]


@pytest.mark.parametrize("alt_g, alt_h, neu_g, neu_h, erwartet", [
    (None, None, 0, O, True), (None, None, 1, A, True), (None, None, None, None, False),
    (0, ALT, None, None, False), (1, A, None, None, False),                                  # unbekannt ersetzt nie etwas
    (1, A, 0, O, False), (1, A, 0, S, False), (1, A, 0, A, False), (1, A, 0, N, False),      # gewerblich → privat nie automatisch
    (1, ALT, 0, A, False), (1, N, 0, N, False),
    (0, O, 1, A, True), (0, S, 1, A, True), (0, A, 1, A, True), (0, ALT, 1, A, True),
    (0, N, 1, A, True), (0, N, 1, N, True),                                                  # Händlerbeleg schlägt auch die Auswahl beim Text-Import
    (0, K, 1, A, False), (1, K, 0, A, False), (0, K, 0, A, False), (1, K, 1, A, False),      # Korrektur bleibt gegen jeden Import
    (None, K, 0, O, False), (None, K, 0, N, False), (None, K, 1, A, True),                   # „unbekannt“ des Teams: nur ein Händlerbeleg
    (0, O, 0, S, True), (0, S, 0, O, False), (0, A, 0, O, False), (0, ALT, 0, O, True), (0, A, 0, N, True), (0, "quatsch", 0, O, True),
    (1, ALT, 1, A, True), (1, A, 1, ALT, False), (0, O, 0, "quatsch", False),
], ids=lambda x: str(x))
def test_uebernehmen(alt_g, alt_h, neu_g, neu_h, erwartet):
    assert an.uebernehmen(alt_g, alt_h, neu_g, neu_h) is erwartet


def test_korrektur_ersetzt_alles():
    assert an.uebernehmen(1, A, 0, N, korrektur=True) and an.uebernehmen(0, N, None, None, korrektur=True)


# ---------------------------------------------------------------- 2. Datenbank: Treffer, Details, Korrektur
def test_gewerblich_bleibt_gegen_listen_ohne_kennzeichen_und_detailseite_privat(db):
    db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "Teilintegrierter")
    assert anb(db, "a1") == (1, A)
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=O), "Teilintegrierter")         # Trefferliste ohne PRO
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=S), "Teilintegrierter")         # Suche „nur privat“
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=A), "Teilintegrierter")         # Detailseite „Privater Nutzer“
    db.speichere_details("a1", {"gewerblich": False, "anbieter_herkunft": A, "titel": "Knaus Sky TI 650 MEG"})
    assert anb(db, "a1") == (1, A)


def test_privat_wird_belegt_und_faellt_nie_zurueck(db):
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=O), "x")
    assert anb(db, "a1") == (0, O)
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=S), "x")
    assert anb(db, "a1") == (0, S)
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=O), "x")
    assert anb(db, "a1") == (0, S)
    db.speichere_details("a1", {"gewerblich": False, "anbieter_herkunft": A})
    assert anb(db, "a1") == (0, A)
    db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "x")                        # PRO-Kennzeichen taucht auf
    assert anb(db, "a1") == (1, A)


def test_unbekannt_ueberschreibt_nichts_und_neu_bleibt_ohne_herkunft(db):
    db.speichere_treffer(treffer("u1", gewerblich=None, anbieter_herkunft=A), "x")
    assert anb(db, "u1") == (None, None)
    db.speichere_treffer(treffer("u1", gewerblich=False, anbieter_herkunft=O), "x")
    db.speichere_treffer(treffer("u1", gewerblich=None), "x")
    assert anb(db, "u1") == (0, O)


def test_ohne_schluessel_wie_bisher_privat_mit_schwaechster_herkunft(db):
    db.speichere_treffer(treffer("k1"), "x")
    assert anb(db, "k1") == (0, O)
    db.speichere_treffer(treffer("k2", gewerblich=True), "x")                                       # Quelle ohne Herkunftsangabe
    assert anb(db, "k2") == (1, A)


@pytest.mark.parametrize("weg", ["liste", "details"])
def test_haendlerbeleg_schlaegt_die_auswahl_privat_beim_text_import(db, weg):
    """QA B1: „privat“ beim Text-Import, später PRO-Kennzeichen → gewerblich (Sperre, nicht in der Vergleichsbasis)."""
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=N), "x")
    if weg == "liste":
        db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "x")
    else:
        db.speichere_details("a1", {"gewerblich": True, "anbieter_herkunft": A})
    assert anb(db, "a1") == (1, A)


def test_korrektur_setzt_jeden_wert_und_bleibt_gegen_importe(db):
    db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "x")
    assert db.setze_anbieter("a1", False) and anb(db, "a1") == (0, K)
    db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "x")                       # bewusste Entscheidung des Teams bleibt
    db.speichere_details("a1", {"gewerblich": True, "anbieter_herkunft": A})
    assert anb(db, "a1") == (0, K)
    assert db.setze_anbieter("a1", True) and anb(db, "a1") == (1, K)
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=A), "x")
    assert anb(db, "a1") == (1, K)
    assert db.setze_anbieter("gibtsnicht", False) is False


def test_korrektur_unbekannt_haelt_bis_zum_haendlerbeleg(db):
    """QA B2: „unbekannt“ des Teams wird vom nächsten Suchlauf ohne Kennzeichen nicht still zu „privat“."""
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=O), "x")
    assert db.setze_anbieter("a1", None) and anb(db, "a1") == (None, K)
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=O), "x")
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=S), "x")
    db.speichere_details("a1", {"gewerblich": False, "anbieter_herkunft": A})
    assert anb(db, "a1") == (None, K)
    db.speichere_treffer(treffer(gewerblich=True, anbieter_herkunft=A), "x")
    assert anb(db, "a1") == (1, A)


def test_speichere_details_ohne_angabe_aendert_nichts(db):
    db.speichere_treffer(treffer(gewerblich=False, anbieter_herkunft=S), "x")
    db.speichere_details("a1", {})
    db.speichere_details("a1", {"gewerblich": None, "anbieter_herkunft": A})
    assert anb(db, "a1") == (0, S)


# ---------------------------------------------------------------- 3. Herkunft je Quelle
def test_kleinanzeigen_liste_pro_und_ohne_kennzeichen(ads):
    html = such_html(ads[:2]).replace('<div class="aditem-main--bottom">', '<div class="aditem-main--bottom"><span>PRO</span>', 1)
    t = {x["id"]: x for x in parse_suchseite(html)}
    assert (t[ads[0]["id"]]["gewerblich"], t[ads[0]["id"]]["anbieter_herkunft"]) == (True, A)
    assert (t[ads[1]["id"]]["gewerblich"], t[ads[1]["id"]]["anbieter_herkunft"]) == (False, O)


@pytest.mark.parametrize("ersatz, erwartet", [
    (None, (False, A)),                                                                            # „Privater Nutzer“
    ('<div id="viewad-contact"><span class="userprofile-vip">Gewerblicher Nutzer</span></div>', (True, A)),
    ('<div id="viewad-contact"></div>', (False, O)),                                             # Kasten ohne Angabe
    ("", (False, O)),                                                                              # gar kein Kasten
    ('<div id="viewad-contact"><span class="userprofile-vip">Privat-Camper-Center</span></div>', (False, O)),   # QA B4: Name ist kein Beleg
    ('<div id="viewad-contact"><span>Privatanbieter</span></div>', (False, A)),
], ids=["privat", "gewerblich", "leer", "ohne_kasten", "name_mit_privat", "privatanbieter"])
def test_kleinanzeigen_detailseite(ads, ersatz, erwartet):
    html = detail_html(ads[0])
    if ersatz is not None:
        html = html.replace('<div id="viewad-contact"><span class="userprofile-vip">Privater Nutzer</span></div>', ersatz)
    d = parse_detailseite(html)
    assert (d["gewerblich"], d["anbieter_herkunft"]) == erwartet


def test_mobilede_anbieterkasten_ist_angabe_der_anzeige():
    treffer_ = md_suchseite((MD_DATEN / "suchseite.html").read_text(encoding="utf-8"))
    assert treffer_
    for t in treffer_:
        assert t["anbieter_herkunft"] == (None if t["gewerblich"] is None else A)
    assert {t["gewerblich"] for t in treffer_} >= {True, False}


def test_crawler_ohne_filter_dann_detailseite(cfg, db, ads):
    Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    zeilen = db.con.execute("SELECT detail_geladen, gewerblich, anbieter_herkunft FROM anzeigen").fetchall()
    assert zeilen and {(z[1], z[2]) for z in zeilen if z[0]} == {(0, A)}                         # Detailseite: „Privater Nutzer“
    assert {(z[1], z[2]) for z in zeilen if not z[0]} <= {(0, O)}


def test_crawler_mit_privatfilter_belegt_privat(cfg, db, ads):
    cfg["suchen"] = [{"name": "Teilintegrierter", "url": SUCH_URL + "/anbieter:privat/anzeige:angebote"}]
    cfg["crawler"]["detailseiten_pro_lauf"] = 0
    Importer(cfg, db, abruf=FakeAbruf(ads)).lauf(cfg["suchen"])
    assert {tuple(z) for z in db.con.execute("SELECT gewerblich, anbieter_herkunft FROM anzeigen")} == {(0, S)}


@pytest.mark.parametrize("angabe, erwartet", [("privat", (0, N)), ("gewerblich", (1, N)), (None, (None, None))])
def test_text_import_mit_und_ohne_angabe(cfg, db, angabe, erwartet):
    eingang = TextEingang()
    url = "https://www.kleinanzeigen.de/s-anzeige/knaus/3311111111-220-1"
    lesung = eingang.lese(eingang.rohdaten(url, "Knaus Sky TI 650\n38.500 € VB\nEZ 05/2016\n90.000 km\n70173 Stuttgart", angabe))
    Importer(cfg, db).importiere(lesung, eingang.kanal)
    assert anb(db, "3311111111") == erwartet


def test_text_import_privat_ueberschreibt_gewerblich_nicht(cfg, db):
    db.speichere_treffer(treffer("3311111111", gewerblich=True, anbieter_herkunft=A), "x")
    eingang = TextEingang()
    lesung = eingang.lese(eingang.rohdaten("https://www.kleinanzeigen.de/s-anzeige/knaus/3311111111-220-1", "Knaus Sky TI 650\n38.500 €", "privat"))
    Importer(cfg, db).importiere(lesung, eingang.kanal)
    assert anb(db, "3311111111") == (1, A)


# ---------------------------------------------------------------- 4. Rechner (P2-05d)
def test_privatangebot():
    assert privatangebot({}) and privatangebot({"gewerblich": 0}) and privatangebot({"gewerblich": False})
    assert not privatangebot({"gewerblich": None}) and not privatangebot({"gewerblich": 1})


def vergleichsfahrzeug(i, preis, gewerblich):
    return {"id": i, "suche": "Teilintegrierter", "titel": "Knaus Sky TI", "marke": "Knaus", "ez_jahr": 2016, "km": 90000, "preis": preis,
            "gewerblich": gewerblich}


def test_rechner_vergleicht_nur_mit_privatangeboten(cfg):
    a = vergleichsfahrzeug("ich", 40000, 0)
    alle = [a] + [vergleichsfahrzeug(f"p{i}", 40000 + i * 500, 0) for i in range(4)] + [vergleichsfahrzeug(f"u{i}", 60000, None) for i in range(3)] \
        + [vergleichsfahrzeug("g1", 65000, 1)]
    r = Rechner(cfg)
    assert len(r.vergleiche(a, alle)) == 4
    ohne_unbekannte = Rechner(cfg).vergleiche(a, [x for x in alle if x["gewerblich"] is not None])
    assert r.vergleiche(a, alle) == ohne_unbekannte                                                  # Unbekannte verändern nichts
    auszug = vergleich_auszug(Rechner(cfg), a, alle)
    assert {x["id"] for x in auszug} == {"ich", "p0", "p1", "p2", "p3"} and all(x["gewerblich"] == 0 for x in auszug)
    # gespeicherte Kalkulations-Eingaben (vor P3-05) ließen None-Werte weg: ohne Schlüssel gilt weiter „privat“ – Nachrechnen bleibt gleich
    alt = [{k: v for k, v in x.items() if v is not None} for x in alle]
    assert len(Rechner(cfg).vergleiche(a, alt)) == 7


def test_unbekannte_zaehlen_in_der_bewertung_nicht_mit(cfg, db, importiert):
    zeilen = bewerte_alle(cfg, db, BASIS)
    vorher = {z["a"]["id"]: z["b"].vergleich_anzahl for z in zeilen}
    ziel, andere = zeilen[0]["a"]["id"], [z["a"]["id"] for z in zeilen[1:]]
    for ad_id in andere:
        db.setze_anbieter(ad_id, None)
    nachher = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert vorher[ziel] > 0 and nachher[ziel]["b"].vergleich_anzahl == 0
    assert HINWEIS_ANBIETER_UNBEKANNT in nachher[andere[0]]["hinweise"]


# ---------------------------------------------------------------- 5. Wirkung, API, CSV, Oberfläche
def test_korrektur_wirkt_auf_sperre_und_hinweis(cfg, db, importiert):
    ad = bewerte_alle(cfg, db, BASIS)[0]["a"]["id"]
    db.setze_anbieter(ad, True)
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ad)
    assert z["sperre"] == "gewerblicher Anbieter" == sperrgrund(z["a"], cfg) and z["a"]["anbieter"]["text"] == "gewerblich (vom Team korrigiert)"
    db.setze_anbieter(ad, False)
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ad)
    assert z["sperre"] != "gewerblicher Anbieter" and HINWEIS_ANBIETER_UNBEKANNT not in hinweise(z["a"])


def test_api_einstufung_und_korrektur(server, db, cfg, importiert):
    c = lokal(server)
    ad = c("GET", "/api/fahrzeuge?filter=alle")[1][0]["id"]
    f = c("GET", f"/api/fahrzeug/{ad}")[1]
    assert f["anbieter"]["typ"] == "privat" and f["anbieter"]["herkunft"] in (A, O)
    s, d, _ = c("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": "gewerblich"})
    assert s == 200 and d["anbieter"] == {"typ": "gewerblich", "herkunft": K, "belegt": True, "text": "gewerblich (vom Team korrigiert)"}
    f = c("GET", f"/api/fahrzeug/{ad}")[1]
    assert f["sperre"] == "gewerblicher Anbieter" and f["anbieter"]["herkunft"] == K
    assert c("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": None})[0] == 200
    f = c("GET", f"/api/fahrzeug/{ad}")[1]
    assert f["anbieter"]["typ"] == "unbekannt" and HINWEIS_ANBIETER_UNBEKANNT in f["hinweise"]
    assert c("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": ""})[0] == 200 and anb(db, ad) == (None, K)
    for falsch in ("händler", ["privat"], 1, True):
        assert c("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": falsch})[0] == 400
    assert c("POST", "/api/anzeige/gibtsnicht/anbieter", {"anbieter": "privat"})[0] == 404
    assert c("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": "privat"})[0] == 200 and anb(db, ad) == (0, K)
    assert einordnen("POST", f"/api/anzeige/{ad}/anbieter") == ("aendern", f"anzeige:{ad}")


def test_api_im_team_betrieb_rechte_token_und_audit(server, db, cfg, importiert, tmp_path):
    team = TeamSpeicher(db, tmp_path / "fotos")
    team.nutzer_anlegen("Anna", "sicher1234", "inhaber")
    team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    sid = HaendlerSpeicher(db).standort_anlegen("Filiale", "70173", "Stuttgart")
    team.nutzer_anlegen("Hugo", "sicher1234", "haendler", standort_id=sid)
    db.con.commit()
    ben = anmelden(server, "Ben")
    ad = ben("GET", "/api/fahrzeuge?filter=alle")[1][0]["id"]
    assert ben("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": "gewerblich"}, token=False)[0] == 403   # ohne CSRF-Token
    assert anb(db, ad)[0] == 0
    assert ben("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": "gewerblich"})[0] == 200 and anb(db, ad) == (1, K)   # Mitarbeiter darf
    assert anmelden(server, "Hugo")("POST", f"/api/anzeige/{ad}/anbieter", {"anbieter": "privat"})[0] == 403          # Händler-Zugang nicht
    assert anb(db, ad) == (1, K)
    db.con.commit()
    eintraege = db.con.execute("SELECT nutzer, aktion, objekt, status FROM audit WHERE pfad LIKE '%/anbieter'").fetchall()
    assert ("Ben", "aendern", f"anzeige:{ad}", 200) in [tuple(e) for e in eintraege]


def test_csv_spalten_anbieter(cfg, db, importiert, tmp_path):
    ad = bewerte_alle(cfg, db, BASIS)[0]["a"]["id"]
    db.setze_anbieter(ad, None)
    schreibe_ausgaben(cfg, bewerte_alle(cfg, db, BASIS), BASIS)
    pfad = Path(cfg["ausgabe"]["ordner"]) / "anzeigen_bewertet.csv"
    zeilen = list(csv.reader(pfad.open(encoding="utf-8-sig"), delimiter=";"))
    kopf = zeilen[0]
    i, j = kopf.index("Anbieter"), kopf.index("Anbieter-Herkunft")
    assert j == i + 1 and kopf[i - 1] == "Zuletzt bestätigt"
    werte = {z[0]: (z[i], z[j]) for z in zeilen[1:]}
    assert werte[ad] == ("unbekannt", "vom Team korrigiert")
    assert {w for k, w in werte.items() if k != ad} <= {("privat", "laut Anzeige"), ("privat", "kein Händlerkennzeichen gefunden")}


def test_oberflaeche_statisch():
    js, html = (STATIC / "mobil.js").read_text(encoding="utf-8"), (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    assert "esc(a.text)" in js and "/anbieter" in js and 'id="anbieter"' in js
    assert "data-anbieter-setzen" in html and "/anbieter'" in html and "tag.textContent = d.anbieter.text" in html
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"var VERSION = 'wm-scout-(\d+)'", sw).group(1)) >= 11 and "11: Anbieter mit Herkunft" in sw


# ---------------------------------------------------------------- 6. Schema 14
def bis_14(monkeypatch):
    """Schritt 14 ist hier der letzte bekannte Schritt: die Tests prüfen ihn so, wie er zu seiner Zeit lief (Schritt 15 prüft tests/test_kontakte.py)."""
    _alt_schritte(monkeypatch, 14)


def baue_v13(pfad, monkeypatch, tmp_path):
    baue_v12(pfad, monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _alt_schritte(m, 13)
        assert migriere(pfad, tmp_path / "stand13") == [13]
    assert lese_version(pfad) == 13


def mit_anbietern(pfad):
    """Altbestand mit allen Anbieterwerten: privat (0), gewerblich (1), unbekannt (NULL)."""
    con = sqlite3.connect(pfad)
    for i, g in enumerate((0, 1, None)):
        con.execute("INSERT INTO anzeigen (id, url, titel, gewerblich) VALUES (?, ?, 'Alt', ?)", (f"g{i}", f"https://x.invalid/g{i}", g))
    con.commit()
    con.close()


@pytest.mark.parametrize("art", ["v1", "v2", "v10", "v13"])
def test_migration_auf_14_ohne_datenverlust(tmp_path, monkeypatch, art):
    bis_14(monkeypatch)
    pfad, ziel = tmp_path / "alt.sqlite", tmp_path / "sich"
    if art == "v13":
        baue_v13(pfad, monkeypatch, tmp_path)
    else:
        baue(art, pfad, monkeypatch)
    mit_anbietern(pfad)
    vorher_version, vorher = lese_version(pfad), _abbild(pfad)
    erledigt = migriere(pfad, ziel)
    assert erledigt[-1] == 14 and lese_version(pfad) == 14 and versionen(pfad)[-1] == 14
    neue = {t: v_ for t, v_ in vorher.items() if t != "fahrzeuge"}
    assert {t: x for t, x in _nachher_wie_vorher(pfad, vorher).items() if t in neue} == neue                    # alle bisherigen Spalten und Zeilen gleich
    assert dict(_sql(pfad, "SELECT id, anbieter_herkunft FROM anzeigen WHERE id LIKE 'g%'")) == {"g0": ALT, "g1": ALT, "g2": None}
    assert _sql(pfad, "SELECT COUNT(*) FROM anzeigen WHERE gewerblich IS NULL AND anbieter_herkunft IS NOT NULL") == [(0,)]
    assert _sql(pfad, "SELECT COUNT(*) FROM anzeigen WHERE gewerblich IS NOT NULL AND anbieter_herkunft IS NOT 'altbestand'") == [(0,)]
    assert _sql(pfad, "PRAGMA integrity_check") == [("ok",)] and _sql(pfad, "PRAGMA foreign_key_check") == []
    kopien = [k for k in sicherungen(ziel, "alt") if "vor-v14" in k.name]
    assert len(kopien) == 1 and lese_version(kopien[0]) == vorher_version and _abbild(kopien[0]) == vorher


def test_schritt_14_zweite_ausfuehrung_aendert_nichts(tmp_path, monkeypatch):
    bis_14(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v13(pfad, monkeypatch, tmp_path)
    mit_anbietern(pfad)
    migriere(pfad, ziel)
    fest, anzahl = pruefsumme(pfad), len(sicherungen(ziel, "db"))
    assert migriere(pfad, ziel) == [] and pruefsumme(pfad) == fest and len(sicherungen(ziel, "db")) == anzahl
    stand = _abbild(pfad)
    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        migrationen._schritt_14(con)
        con.execute("COMMIT")
    finally:
        con.close()
    assert _abbild(pfad) == stand


def test_fehler_im_schritt_14_rollt_zurueck_dann_gelingt_es(tmp_path, monkeypatch):
    bis_14(monkeypatch)
    pfad, ziel = tmp_path / "db.sqlite", tmp_path / "sich"
    baue_v13(pfad, monkeypatch, tmp_path)
    mit_anbietern(pfad)
    vorher, echt = _abbild(pfad), migrationen._schritt_14

    def fehler_am_ende(con):
        echt(con)
        raise RuntimeError("Absicht")

    monkeypatch.setitem(migrationen.SCHRITTE, 14, fehler_am_ende)
    with pytest.raises(MigrationsFehler, match="zurückgerollt"):
        migriere(pfad, ziel)
    assert lese_version(pfad) == 13 and _abbild(pfad) == vorher
    assert "anbieter_herkunft" not in [r[1] for r in _sql(pfad, "PRAGMA table_info(anzeigen)")]
    monkeypatch.setitem(migrationen.SCHRITTE, 14, echt)
    assert migriere(pfad, ziel) == [14]


def test_neue_datenbank_hat_die_spalte(db):
    assert "anbieter_herkunft" in [r[1] for r in db.con.execute("PRAGMA table_info(anzeigen)")]
    assert lese_version(db.con.execute("PRAGMA database_list").fetchone()[2]) >= 14
