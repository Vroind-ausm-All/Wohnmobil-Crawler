"""P4-03: Neuigkeiten – frisch eingegangene Inserate und deutliche Preissenkungen hervorheben, priorisieren und melden. Alles offline."""

# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
import csv
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.daten import BASIS
from tests.test_app_threads import _suchlauf, _zeilen, mail_cfg, smtp  # noqa: F401 – Fixtures
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout import benachrichtigung
from wmscout.ausgabe import schreibe_ausgaben
from wmscout.bewertung import auswertung
from wmscout.bewertung import neuigkeit as nk
from wmscout.bewertung.auswertung import bewerte_alle

JETZT = datetime(2026, 10, 24, 12, 0)
E = nk.einstellungen({})
STATIC = BASIS / "wmscout" / "web" / "static"


def iso(**delta) -> str:
    return (JETZT - timedelta(**delta)).isoformat(timespec="seconds")


def inserat(**kw) -> dict:
    return {"id": "1", "status": "neu", "preis": 40000, "preis_vorher": None, "preis_geaendert_am": None, "erstmals_gesehen": iso(days=30), **kw}


def bew(max_ek=38000, sicherheit="mittel"):
    return SimpleNamespace(max_ek=max_ek, sicherheit=sicherheit)


# ---------------------------------------------------------------- 1. Einstellungen
def test_einstellungen_standard_und_fehleingaben(caplog):
    assert nk.einstellungen(None) == nk.STANDARD == {"frisch_stunden": 48, "senkung_tage": 14, "senkung_min_prozent": 3, "senkung_min_euro": 500}
    assert nk.einstellungen({"neuigkeiten": {"frisch_stunden": 24, "senkung_min_euro": 0}})["frisch_stunden"] == 24
    with caplog.at_level(logging.WARNING, logger="scout"):
        e = nk.einstellungen({"neuigkeiten": {"frisch_stunden": 0, "senkung_tage": "14", "senkung_min_prozent": True, "senkung_min_euro": -1}})
    assert e == nk.STANDARD and caplog.text.count("neuigkeiten ->") == 4
    assert nk.einstellungen({"neuigkeiten": "kaputt"}) == nk.STANDARD


# ---------------------------------------------------------------- 2. Senkung
@pytest.mark.parametrize("kw, erwartet", [
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=2)}, 2000),            # 5 %, 2.000 €
    ({"preis": 9700, "preis_vorher": 10000, "preis_geaendert_am": iso(days=1)}, 300),             # genau 3 %
    ({"preis": 79500, "preis_vorher": 80000, "preis_geaendert_am": iso(days=1)}, 500),            # 0,6 %, aber 500 €
    ({"preis": 79600, "preis_vorher": 80000, "preis_geaendert_am": iso(days=1)}, None),           # 0,5 % und 400 €: nicht deutlich
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=14)}, 2000),          # Grenze: 14 Tage
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=14, seconds=1)}, None),
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=-1)}, None),          # Zeitpunkt in der Zukunft
    ({"preis": 41000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=1)}, None),           # später wieder erhöht
    ({"preis": 40000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=1)}, None),
    ({"preis": None, "preis_vorher": 40000, "preis_geaendert_am": iso(days=1)}, None),
    ({"preis": 38000, "preis_vorher": True, "preis_geaendert_am": iso(days=1)}, None),
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": None}, None),
    ({"preis": 38000, "preis_vorher": 40000, "preis_geaendert_am": "gestern"}, None),
    ({"preis": 0, "preis_vorher": 40000, "preis_geaendert_am": iso(days=1)}, None),
])
def test_senkung(kw, erwartet):
    s = nk.senkung(inserat(**kw), JETZT, E)
    assert (s["euro"] if s else None) == erwartet
    if s:
        assert s["von"] == kw["preis_vorher"] and s["auf"] == kw["preis"] and s["am"] == kw["preis_geaendert_am"]


def test_senkung_schwellen_aus_der_konfiguration():
    a = inserat(preis=79600, preis_vorher=80000, preis_geaendert_am=iso(days=20))
    assert nk.senkung(a, JETZT, E) is None
    assert nk.senkung(a, JETZT, nk.einstellungen({"neuigkeiten": {"senkung_tage": 30, "senkung_min_euro": 400}}))["prozent"] == 0.5


# ---------------------------------------------------------------- 3. Stufe und Text
GESENKT_UEBER_MAX = {"preis": 37000, "preis_vorher": 40000, "preis_geaendert_am": iso(days=1)}       # Max-EK 38.000 dazwischen


@pytest.mark.parametrize("kw, b, bereit, stufe", [
    (GESENKT_UEBER_MAX, bew(), False, nk.IM_RAHMEN),
    ({**GESENKT_UEBER_MAX, "erstmals_gesehen": iso(hours=1)}, bew(), True, nk.IM_RAHMEN),             # im Rahmen schlägt frisch
    (GESENKT_UEBER_MAX, bew(sicherheit="keine"), False, nk.GESENKT),                                 # ohne belastbaren Max-EK
    (GESENKT_UEBER_MAX, bew(max_ek=36000), False, nk.GESENKT),                                       # noch darüber
    (GESENKT_UEBER_MAX, bew(max_ek=41000), False, nk.GESENKT),                                       # war schon vorher im Rahmen
    (GESENKT_UEBER_MAX, bew(max_ek=None), False, nk.GESENKT),
    ({"erstmals_gesehen": iso(hours=47)}, bew(), True, nk.FRISCH_BEREIT),
    ({**GESENKT_UEBER_MAX, "erstmals_gesehen": iso(hours=1)}, bew(max_ek=30000), True, nk.FRISCH_BEREIT),   # frisch + bereit vor gesenkt
    ({"erstmals_gesehen": iso(hours=1)}, bew(), False, nk.FRISCH),
    ({"erstmals_gesehen": iso(hours=49)}, bew(), True, None),
    ({"erstmals_gesehen": iso(hours=-1)}, bew(), True, None),                                        # Zukunft: kein „frisch“
    ({"erstmals_gesehen": None}, bew(), True, None),
    ({}, bew(), True, None),
])
def test_stufe(kw, b, bereit, stufe):
    n = nk.neuigkeit(inserat(**kw), b, bereit, False, JETZT, E)
    assert (n["stufe"] if n else None) == stufe


def test_kleine_senkung_ueber_die_max_ek_grenze_ist_im_rahmen():
    a = inserat(preis=28700, preis_vorher=29000, preis_geaendert_am=iso(days=1))          # 1 %, 300 €: nicht deutlich (QA B3)
    assert nk.senkung(a, JETZT, E) is None
    n = nk.neuigkeit(a, bew(max_ek=28800), False, False, JETZT, E)
    assert n["stufe"] == nk.IM_RAHMEN and n["senkung"]["euro"] == 300
    assert nk.neuigkeit(a, bew(max_ek=28000), False, False, JETZT, E) is None             # klein und nicht im Rahmen: nichts


def test_gesperrte_inserate_haben_keine_neuigkeit():
    a = inserat(**GESENKT_UEBER_MAX, erstmals_gesehen=iso(hours=1))
    for grund in ("gewerblicher Anbieter", "doppelt eingestellt", "Ausschlussbegriff: Unfall", "zu weit entfernt (400 km)"):
        assert nk.neuigkeit(a, bew(), True, False, JETZT, E, sperre=grund) is None        # QA B1


def test_nur_offene_sichtbare_inserate_und_text():
    a = inserat(**GESENKT_UEBER_MAX)
    for status in ("kontaktiert", "verhandlung", "besichtigung", "gekauft", "abgesagt", "uninteressant", "gelöscht"):
        assert nk.neuigkeit({**a, "status": status}, bew(), False, False, JETZT, E) is None       # dort meldet sich „Nachfassen“
    assert nk.neuigkeit({**a, "status": None}, bew(), False, False, JETZT, E)["im_rahmen"]
    assert nk.neuigkeit({**a, "status": "vorbereitet"}, bew(), False, False, JETZT, E)["stufe"] == nk.IM_RAHMEN
    assert nk.neuigkeit(a, bew(), False, True, JETZT, E) is None                                    # ausgeblendet (verkauft/offline)
    n = nk.neuigkeit(a, bew(), False, False, JETZT, E)
    assert n["text"] == f"Preis gesenkt – jetzt im Rahmen (−3.000 €, {iso(days=1)[8:10]}.{iso(days=1)[5:7]}.)"
    assert nk.neuigkeit(inserat(erstmals_gesehen=iso(hours=1)), bew(), False, False, JETZT, E)["text"] == "neu eingegangen"


def test_gesenkt_seit():
    zeilen = [{"neuigkeit": {"senkung": {"am": "2026-10-24T10:00:00"}}}, {"neuigkeit": {"senkung": {"am": "2026-10-23T10:00:00"}}},
              {"neuigkeit": {"senkung": None}}, {"neuigkeit": None}, {}]
    assert nk.gesenkt_seit(zeilen, "2026-10-24T09:00:00") == zeilen[:1]
    assert nk.gesenkt_seit(zeilen, None) == []
    # ein Fahrzeug mit zwei Inseraten wird einmal gemeldet – das wichtigere (QA B2)
    paar = [{"a": {"id": "a", "preis": 30000}, "dubletten_ids": ["b"], "neuigkeit": {"stufe": 3, "senkung": {"am": "2026-10-24T10:00:00"}}},
            {"a": {"id": "b", "preis": 29000}, "dubletten_ids": ["a"], "neuigkeit": {"stufe": 1, "senkung": {"am": "2026-10-24T10:00:00"}}},
            {"a": {"id": "c", "preis": 20000}, "dubletten_ids": [], "neuigkeit": {"stufe": 3, "senkung": {"am": "2026-10-24T10:00:00"}}}]
    assert [z["a"]["id"] for z in nk.gesenkt_seit(paar, "2026-10-24T09:00:00")] == ["b", "c"]


# ---------------------------------------------------------------- 4. Bewertung: Feld vorhanden, ohne Wirkung
def _offene_ueber_max_ek(cfg, db) -> list[str]:
    """IDs offener, nicht gesperrter Inserate, deren Preis deutlich über dem Max-EK liegt (eine kleine Senkung bleibt darüber)."""
    return [z["a"]["id"] for z in bewerte_alle(cfg, db, BASIS)
            if not z["sperre"] and not z["ausblenden"] and z["b"].max_ek and z["a"]["preis"] > z["b"].max_ek + 2000]


def _senke(db, ad_id: str, neu: int):
    jetzt = datetime.now().isoformat(timespec="seconds")
    db.con.execute("UPDATE anzeigen SET preis_vorher=preis, preis=?, preis_geaendert_am=? WHERE id=?", (neu, jetzt, ad_id))
    db.con.commit()


def test_bewertung_ohne_wirkung(cfg, db, importiert, monkeypatch):
    ziel = next(z for z in bewerte_alle(cfg, db, BASIS) if z["b"].max_ek and z["a"]["preis"] > z["b"].max_ek + 1000 and not z["sperre"] and not z["ausblenden"])
    _senke(db, ziel["a"]["id"], ziel["b"].max_ek - 500)
    mit = bewerte_alle(cfg, db, BASIS)
    monkeypatch.setattr(auswertung, "neuigkeit", lambda *a, **k: None)
    ohne = bewerte_alle(cfg, db, BASIS)
    felder = ("bereit", "sperre", "brief", "hinweise", "nachfassen", "ausblenden", "neu")
    assert [(z["b"], *(z[f] for f in felder)) for z in mit] == [(z["b"], *(z[f] for f in felder)) for z in ohne]
    n = next(z for z in mit if z["a"]["id"] == ziel["a"]["id"])["neuigkeit"]
    assert n["im_rahmen"] and n["stufe"] == nk.IM_RAHMEN and n["senkung"]["auf"] == ziel["b"].max_ek - 500
    assert all(z["neuigkeit"] and z["neuigkeit"]["frisch"] for z in mit if not z["ausblenden"] and not z["sperre"])   # gerade eingelesen
    assert all(z["neuigkeit"] is None for z in mit if z["sperre"]) and any(z["sperre"] for z in mit)


def test_erhoehung_setzt_die_gemerkte_senkung_zurueck(cfg, db, importiert, ads):
    """30.000 → 27.000 → 29.500: danach keine „Senkung“ mehr und kein Nachfass-Grund „Preis gesenkt“ (QA B4)."""
    from tests.daten import FakeAbruf
    from wmscout.importer import Importer
    gesenkt, erhoeht = copy.deepcopy(ads), copy.deepcopy(ads)
    gesenkt[0]["preis"] = int(ads[0]["preis"] * 0.9)
    erhoeht[0]["preis"] = int(ads[0]["preis"] * 0.98)
    Importer(cfg, db, abruf=FakeAbruf(gesenkt)).lauf(cfg["suchen"])
    assert db.con.execute("SELECT preis_vorher FROM anzeigen WHERE id=?", (ads[0]["id"],)).fetchone()[0] == ads[0]["preis"]
    Importer(cfg, db, abruf=FakeAbruf(erhoeht)).lauf(cfg["suchen"])
    zeile = db.con.execute("SELECT preis, preis_vorher, preis_geaendert_am FROM anzeigen WHERE id=?", (ads[0]["id"],)).fetchone()
    assert tuple(zeile) == (erhoeht[0]["preis"], None, None)
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ads[0]["id"])
    assert not (z["neuigkeit"] or {}).get("senkung")
    assert db.con.execute("SELECT COUNT(*) FROM preis_historie ph JOIN inserate i ON i.id=ph.inserat_id WHERE i.anzeigen_id=?",
                          (ads[0]["id"],)).fetchone()[0] == 3                                # der Preisverlauf bleibt vollständig


def test_import_erkennt_senkung_und_neuigkeit(cfg, db, importiert, ads):
    """Ende zu Ende über den Import: ein zweiter Eingang mit niedrigerem Preis wird als Senkung erkannt und hervorgehoben."""
    from tests.daten import FakeAbruf
    from wmscout.importer import Importer
    i = [a["id"] for a in ads].index(_offene_ueber_max_ek(cfg, db)[0])
    geaendert = copy.deepcopy(ads)
    geaendert[i]["preis"] = int(ads[i]["preis"] * 0.9)
    stat = Importer(cfg, db, abruf=FakeAbruf(geaendert)).lauf(cfg["suchen"])
    assert stat["preis"] == 1
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ads[i]["id"])
    assert z["neuigkeit"]["senkung"]["von"] == ads[i]["preis"] and z["neuigkeit"]["senkung"]["auf"] == geaendert[i]["preis"]


# ---------------------------------------------------------------- 5. API, Ausgabe
def test_api_liste_neuigkeiten_wichtigste_zuerst(cfg, server, db, importiert):
    ziel = next(z for z in bewerte_alle(cfg, db, BASIS) if z["b"].max_ek and z["a"]["preis"] > z["b"].max_ek + 1000 and not z["sperre"] and not z["ausblenden"])
    ziel = {"id": ziel["a"]["id"], "max_ek": ziel["b"].max_ek}
    _senke(db, ziel["id"], ziel["max_ek"] - 500)              # vor der ersten Anfrage: der Server bewertet danach frisch
    c = lokal(server)
    liste = c("GET", "/api/fahrzeuge?filter=neuigkeiten")[1]
    assert liste[0]["id"] == ziel["id"] and liste[0]["neuigkeit"]["stufe"] == nk.IM_RAHMEN
    stufen = [f["neuigkeit"]["stufe"] for f in liste]
    assert stufen == sorted(stufen) and all(f["neuigkeit"] for f in liste)
    assert c("GET", "/api/heute")[1]["neuigkeiten"] == len(liste) > 1
    einzeln = c("GET", f"/api/fahrzeug/{ziel['id']}")[1]
    assert einzeln["neuigkeit"]["senkung"]["auf"] == ziel["max_ek"] - 500


def test_report_und_csv(cfg, db, importiert, tmp_path):
    zeilen = bewerte_alle(cfg, db, BASIS)
    ziel = next(z for z in zeilen if z["b"].max_ek and z["a"]["preis"] > z["b"].max_ek + 1000 and not z["sperre"] and not z["ausblenden"])
    _senke(db, ziel["a"]["id"], ziel["b"].max_ek - 500)
    zeilen = bewerte_alle(cfg, db, BASIS)
    erg = schreibe_ausgaben(cfg, zeilen, BASIS)
    html = erg["html"].read_text(encoding="utf-8")
    assert html.count("data-im-rahmen") == 1 and html.count("data-senkung") == 1 and 'data-f="neuigkeiten"' in html
    assert 'value="prio"' in html and f"<b>{sum(bool(z['neuigkeit']) for z in zeilen)}</b><span>Neu &amp; Preis gesenkt" in html
    with open(erg["csv"], encoding="utf-8-sig", newline="") as f:
        reihen = list(csv.reader(f, delimiter=";"))
    i = reihen[0].index("Neuigkeit")
    assert reihen[0][i - 1] == "Datenmarkierungen" and reihen[0][i + 1] == "Erstmals gesehen"
    assert any(r[i].startswith("Preis gesenkt – jetzt im Rahmen") for r in reihen[1:])


# ---------------------------------------------------------------- 6. Melden
def _gesenkt_zeile():
    z = _zeilen(False)[0]
    z["neuigkeit"] = {"stufe": nk.IM_RAHMEN, "text": "Preis gesenkt – jetzt im Rahmen (−3.000 €, 24.10.)",
                      "senkung": {"von": 31000, "auf": 28000, "euro": 3000, "prozent": 9.7, "am": "2026-10-24T10:00:00"}}
    return z


def test_mail_meldet_preissenkungen(mail_cfg, smtp, tmp_path, caplog):
    bericht = tmp_path / "report.html"
    bericht.write_text("<html></html>", encoding="utf-8")
    benachrichtigung.sende_mail(mail_cfg, [_gesenkt_zeile()], {"html": bericht}, seit="2026-10-24T09:00:00")
    msg = smtp[0].ablauf[3][1]
    assert msg["Subject"] == "Wohnmobil-Scout: 0 neue Treffer, 1 Preissenkung"
    text = msg.get_body().get_content()
    assert "1 Preissenkung:" in text and "31.000 € → 28.000 €" in text and "Anzeigen mit fertigem Anschreiben" not in text
    # vor dem Lauf gesenkt → nicht gemeldet; abgeschaltet → nicht gemeldet
    with caplog.at_level(logging.INFO, logger="scout"):
        benachrichtigung.sende_mail(mail_cfg, [_gesenkt_zeile()], {"html": bericht}, seit="2026-10-24T11:00:00")
        mail_cfg["email"]["preissenkungen_melden"] = False
        benachrichtigung.sende_mail(mail_cfg, [_gesenkt_zeile()], {"html": bericht}, seit="2026-10-24T09:00:00")
    assert len(smtp) == 1 and caplog.text.count("Keine neuen Treffer") == 2


def test_mail_ohne_belastbaren_max_ek_und_ohne_ort(mail_cfg, smtp, tmp_path):
    bericht = tmp_path / "report.html"
    bericht.write_text("<html></html>", encoding="utf-8")
    z = _gesenkt_zeile()
    z["b"].sicherheit = "keine"
    z["a"]["ort"] = None
    benachrichtigung.sende_mail(mail_cfg, [z], {"html": bericht}, seit="2026-10-24T09:00:00")
    text = smtp[0].ablauf[3][1].get_body().get_content()
    assert "Max-EK –" in text and "Max-EK 0 €" not in text and "Ort ?" in text and "None" not in text


def test_suchlauf_meldet_deutliche_senkungen(cfg, ads, monkeypatch):
    lauf = _suchlauf(cfg, ads, monkeypatch)
    assert lauf.starte()
    lauf.thread.join(120)
    assert lauf.stand["preissenkungen"] == 0
    from wmscout.datenbank import Datenbank
    ids = [a["id"] for a in ads]
    gross, klein = (ids.index(x) for x in _offene_ueber_max_ek(cfg, Datenbank(cfg["ausgabe"]["datenbank"]))[:2])
    geaendert = copy.deepcopy(ads)
    geaendert[gross]["preis"] = int(ads[gross]["preis"] * 0.9)              # deutlich
    geaendert[klein]["preis"] = ads[klein]["preis"] - 100                    # nicht deutlich (< 3 % und < 500 €), bleibt über dem Max-EK
    lauf2 = _suchlauf(cfg, geaendert, monkeypatch)
    assert lauf2.starte()
    lauf2.thread.join(120)
    st = lauf2.stand
    assert st["preissenkungen"] == 1 and "2 Preissenkungen, davon 1 deutlich" in st["meldung"]


# ---------------------------------------------------------------- 7. Oberfläche
def test_oberflaeche_statisch():
    html = (BASIS / "vorlagen" / "report.html").read_text(encoding="utf-8")
    js = (STATIC / "mobil.js").read_text(encoding="utf-8")
    assert "s.preissenkungen" in html and "filter === 'neuigkeiten' && k.dataset.prio !== '9'" in html
    assert "if(s === 'prio')" in html and "|safe" not in html.split("data-senkung")[1][:300]
    assert 'neuigkeiten: "Neu & gesenkt"' in js and "function neuTag" in js and "esc(f.neuigkeit.text)" in js
    assert "#/liste/neuigkeiten" in js and "d.neuigkeiten" in js
    assert "wm-scout-15" in (STATIC / "sw.js").read_text(encoding="utf-8")
