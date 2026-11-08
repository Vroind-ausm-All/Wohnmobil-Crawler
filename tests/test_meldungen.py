"""P6-04 – Meldungen im Dashboard (ADR-064): Antwort fällig, Besichtigung heute/morgen, Nachfassen, Preissenkung, neu – Bildung, Reihenfolge,
Fahrzeuggruppen, kein „keine Antwort“ nach eingetragener Antwort, API, Desktop und Handy-App."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from tests.daten import BASIS
from tests.test_dubletten_vorschlaege import treffer
from tests.test_team_bearbeitung import lokal, starte
from wmscout import verhandlung as vh
from wmscout.ausgabe import render_html
from wmscout.bewertung.auswertung import bewerte_alle, nachfass_grund
from wmscout.bewertung.meldungen import MAX, meldungen

STATIC = Path(__file__).resolve().parent.parent / "wmscout" / "web" / "static"
JETZT = datetime(2026, 11, 2, 12)


def _z(i, kontakt=None, neuigkeit=None, nachfassen=None, bereit=False, top=False, dub=(), erst="2026-11-02T08:00:00"):
    return {"a": {"id": i, "fahrzeug": f"Knaus {i}", "erstmals_gesehen": erst}, "kontakt": kontakt, "neuigkeit": neuigkeit,
            "nachfassen": nachfassen, "bereit": bereit, "deal": {"priorisiert": top}, "dubletten_ids": list(dub)}


def _arten(m):
    return [(x["art"], x["id"]) for x in m]


# ---------------------------------------------------------------- 1. Bildung (rein)
def test_antwort_faellig_und_dringend():
    k = {"stufe": "antwort", "text": "Antwort am 01.11. – nennt 34.500 €", "antwort": {"zeitpunkt": "2026-11-01T09:00:00", "betrag": 34500}}
    m = meldungen([_z("a", kontakt=k)], JETZT)
    assert _arten(m) == [("antwort", "a")] and m[0]["dringend"] and m[0]["text"].endswith("Rückmeldung offen seit 1 Tag")
    assert m[0]["zeit"] == "2026-11-01T09:00:00" and m[0]["art_text"] == "Antwort fällig"
    frisch = meldungen([_z("a", kontakt={**k, "antwort": {"zeitpunkt": "2026-11-02T10:00:00"}})], JETZT)
    assert not frisch[0]["dringend"] and frisch[0]["text"].endswith("Rückmeldung offen")


def test_besichtigung_heute_morgen():
    def bes(termin):
        return _z("b", kontakt={"stufe": "besichtigung", "besichtigung": {"status": "geplant", "termin": termin}})
    heute = meldungen([bes("2026-11-02T16:00")], JETZT)
    assert heute[0]["text"] == "Besichtigung heute 16:00 Uhr" and heute[0]["dringend"]
    morgen = meldungen([bes("2026-11-03T09:30")], JETZT)
    assert morgen[0]["text"] == "Besichtigung morgen 09:30 Uhr" and not morgen[0]["dringend"]
    assert meldungen([bes("2026-11-04T09:30")], JETZT) == [] and meldungen([bes("2026-11-02T08:00")], JETZT) == []   # übermorgen / vorbei


def test_nachfassen_preis_neu():
    nf = _z("n", kontakt={"stufe": "wartet", "kontakt_am": "2026-10-28T09:00:00"}, nachfassen="seit 5 Tagen keine Antwort")
    s = {"von": 40000, "auf": 37900, "euro": 2100, "am": "2026-11-01T18:00:00"}
    preis = _z("p", neuigkeit={"senkung": s, "im_rahmen": True})
    neu = _z("x", neuigkeit={"frisch": True}, bereit=True)
    still = _z("y", neuigkeit={"frisch": True})                                           # frisch, aber weder bereit noch Top-Deal
    m = meldungen([nf, preis, neu, still], JETZT, {"nachfassen": {"nach_tagen": 3}})
    assert _arten(m) == [("preis", "p"), ("nachfassen", "n"), ("neu", "x")]                 # dringend (im Rahmen) zuerst
    assert m[0]["text"] == "40.000 € → 37.900 € (−2.100 €) – jetzt im Rahmen" and m[1]["zeit"] == "2026-10-31T09:00:00"
    assert m[2]["text"] == "Anschreiben bereit – seit 02.11. online"
    # nach eingetragener Antwort kein Nachfassen, sondern „Antwort fällig“
    beantwortet = _z("n", kontakt={"stufe": "antwort", "text": "Antwort am 02.11.", "antwort": {"zeitpunkt": "2026-11-02T11:00:00"}},
                     nachfassen="seit 5 Tagen keine Antwort")
    assert _arten(meldungen([beantwortet], JETZT)) == [("antwort", "n")]


def test_korrekturrunde_qa():
    """B1 Termin mit Zeitzone, B4 Notiz nach der Antwort erledigt sie, B5 Vortag ist nicht „morgen“, Nachfassen wegen Preis: Zeitpunkt der Senkung."""
    def bes(termin, jetzt=JETZT):
        return meldungen([_z("b", kontakt={"stufe": "besichtigung", "besichtigung": {"status": "geplant", "termin": termin}})], jetzt)
    mit_zone = bes("2026-11-02T15:00+00:00")
    assert len(mit_zone) == 1 and mit_zone[0]["text"].startswith("Besichtigung heute") and bes("kaputt") == []
    assert bes("2026-11-01T23:00", datetime(2026, 11, 2, 0, 30)) == []
    k = {"stufe": "antwort", "text": "Antwort am 01.11.", "antwort": {"zeitpunkt": "2026-11-01T09:00:00"}, "notiz": {"zeitpunkt": "2026-11-01T10:00:00"}}
    assert meldungen([_z("a", kontakt=k)], JETZT) == []
    nf = {**_z("n", kontakt={"stufe": "wartet", "kontakt_am": "2026-11-01T09:00:00"}, nachfassen="Preis gesenkt auf 35.000 €")}
    nf["a"]["preis_geaendert_am"] = "2026-11-02T07:00:00"
    assert meldungen([nf], JETZT)[0]["zeit"] == "2026-11-02T07:00:00"
    ohne_namen = {**_z("x", neuigkeit={"frisch": True}, bereit=True), "a": {"id": "x", "erstmals_gesehen": "2026-11-02T08:00:00"}}
    assert meldungen([ohne_namen], JETZT)[0]["fahrzeug"] is None


def test_reihenfolge_gruppen_und_grenze():
    s = {"von": 40000, "auf": 38000, "euro": 2000}
    a = _z("a", neuigkeit={"senkung": {**s, "am": "2026-11-01T10:00:00"}}, dub=["b"])
    b = _z("b", neuigkeit={"senkung": {**s, "am": "2026-11-02T10:00:00"}}, dub=["a"])
    c = _z("c", neuigkeit={"senkung": {**s, "am": "2026-10-30T10:00:00"}})
    assert _arten(meldungen([a, b, c], JETZT)) == [("preis", "b"), ("preis", "c")]         # je Fahrzeug eine, jüngste zuerst
    viele = [_z(f"v{i}", neuigkeit={"frisch": True}, bereit=True) for i in range(MAX + 20)]
    assert len(meldungen(viele, JETZT)) == MAX and meldungen([], JETZT) == []


def test_nachfass_grund_nach_antwort():
    a = {"status": "kontaktiert", "kontaktiert_am": "2026-10-20T10:00:00", "nachfass_anzahl": 0}
    cfg = {"nachfassen": {"nach_tagen": 3, "max_anzahl": 1}}
    assert nachfass_grund(a, cfg, JETZT).startswith("seit 13 Tagen") and nachfass_grund(a, cfg, JETZT, beantwortet=True) is None
    gesenkt = {**a, "preis": 35000, "preis_geaendert_am": "2026-10-25T10:00:00"}
    assert nachfass_grund(gesenkt, cfg, JETZT, beantwortet=True) == "Preis gesenkt auf 35.000 €"   # neuer Preis bleibt ein Anlass


# ---------------------------------------------------------------- 2. Mit Datenbank, API, Oberflächen
def _bestand(db):
    db.speichere_treffer(treffer("p1"), "Alkoven")
    db.speichere_treffer(treffer("p2", ort="80331 München", km=150000), "Alkoven")
    db.setze_status("p1", "kontaktiert", text="Hallo")
    db.con.execute("UPDATE anzeigen SET kontaktiert_am=? WHERE id='p1'", ((datetime.now() - timedelta(days=6)).isoformat(timespec="seconds"),))
    db.con.execute("UPDATE kontakte SET bestaetigt_am=? WHERE anzeige_id='p1'", ((datetime.now() - timedelta(days=6)).isoformat(timespec="seconds"),))
    db.con.commit()


def test_bewertung_antwort_ersetzt_nachfassen(cfg, db):
    _bestand(db)
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert z["p1"]["nachfassen"] and z["p1"]["kontakt"]["stufe"] == "wartet"
    assert ("nachfassen", "p1") in _arten(meldungen(list(z.values()), datetime.now(), cfg))
    vh.eintragen(db, "p1", vh.pruefe({"art": "antwort", "text": "will 38.000 <b>x</b>", "betrag": 38000}), None)
    z = {z["a"]["id"]: z for z in bewerte_alle(cfg, db, BASIS)}
    assert z["p1"]["nachfassen"] is None and z["p1"]["kontakt"]["stufe"] == "antwort"
    m = meldungen(list(z.values()), datetime.now(), cfg)
    assert ("antwort", "p1") in _arten(m) and ("nachfassen", "p1") not in _arten(m)


def test_besichtigung_mit_zeitzone_legt_nichts_lahm(cfg, db, tmp_path):
    """B1: ein Termin mit Zeitzone (die API speichert, was fromisoformat versteht) – Startseite und Meldungen bleiben erreichbar."""
    from wmscout.team import TeamSpeicher
    _bestand(db)
    db.setze_status("p2", "besichtigung")
    morgen = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT10:00+01:00")
    TeamSpeicher(db, tmp_path / "fotos").besichtigung_anlegen("p2", {"fahrzeug": "Knaus"}, morgen, "München", None, None)
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        assert c("GET", "/")[0] == 200 and c("GET", "/api/meldungen")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_antwort_bei_besichtigung_kein_nachfassen(cfg, db, tmp_path):
    """B6: Antwort eingetragen, Besichtigung geplant, Status bleibt „kontaktiert“ – kein „keine Antwort“."""
    from wmscout.team import TeamSpeicher
    _bestand(db)
    vh.eintragen(db, "p1", vh.pruefe({"art": "antwort", "text": "Samstag passt"}), None)
    TeamSpeicher(db, tmp_path / "fotos").besichtigung_anlegen("p1", {"fahrzeug": "Knaus"}, None, None, None, None)
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == "p1")
    assert z["kontakt"]["stufe"] == "besichtigung" and z["nachfassen"] is None


def test_api_und_desktop(cfg, db):
    _bestand(db)
    vh.eintragen(db, "p1", vh.pruefe({"art": "antwort", "text": "egal", "betrag": 38000}), None)
    srv = starte(cfg, db)
    try:
        c = lokal(srv)
        s, d, _ = c("GET", "/api/meldungen")
        assert s == 200 and d["jetzt"] and [m["art"] for m in d["meldungen"] if m["id"] == "p1"] == ["antwort"]
        assert {"art", "art_text", "id", "fahrzeug", "quelle", "text", "zeit", "dringend"} == set(d["meldungen"][0])
        assert "egal" not in repr(d)                                                            # keine Eintragstexte in Meldungen
    finally:
        srv.shutdown()
        srv.server_close()
    for app in ({"token": "t"}, None):
        html = render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS, app=app)[0]
        box = re.search(r'<details class="kasten" id="meldungen".*?</details>', html, re.S).group(0)
        assert 'data-meldung="antwort"' in box and 'data-meldung-oeffnen="p1"' in box and "Antwort fällig" in box and 'id="meldungen-gelesen"' in box
    assert "scout-meldungen-gelesen" in html and "li.dataset.zeit > bis" in html
    assert "if(li.dataset.zeit > bis) bis = li.dataset.zeit;" in html          # „alle gelesen“ deckt auch Zeitpunkte in der Zukunft ab (Klicktest)
    assert 'data-jetzt="' in html and "meldungsBox.dataset.jetzt" in html       # Serverzeit statt Geräteuhr (B3)


def test_ohne_meldungen_kein_bereich(cfg, db):
    db.speichere_treffer(treffer("x1", ort="80331 München", km=150000), "Alkoven")
    db.con.execute("UPDATE anzeigen SET erstmals_gesehen='2025-01-01T00:00:00'")
    db.con.commit()
    assert 'id="meldungen"' not in render_html(cfg, bewerte_alle(cfg, db, BASIS), BASIS)[0]


def test_handy_app_statisch():
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    for teil in ("function meldungenAbschnitt", 'api("/api/meldungen")', 'data-aktion="meldungen-gelesen"', "meldungenAbschnitt(meldungenListe)",
                 "esc(m.text)", "esc(m.fahrzeug || \"Fahrzeug\")", "encodeURIComponent(m.id)", '"scout-meldungen-gelesen"',
                 "(S.meldungen || []).forEach(function (m) { if (m.zeit > bis) bis = m.zeit; });", "S.meldungenJetzt = r[1].jetzt"):
        assert teil in js, teil
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert int(re.search(r"wm-scout-(\d+)", sw).group(1)) >= 22
    assert "meldungen" not in re.search(r"var lesbar = (.*?);", sw, re.S).group(1)        # nicht im Gerätespeicher
    assert ".zeile.meldung.ungelesen" in (STATIC / "mobil.css").read_text(encoding="utf-8")
