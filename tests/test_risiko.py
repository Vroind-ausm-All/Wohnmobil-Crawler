"""P5-05 – Ausstattung und Mängel; Reparatur-, Gewährleistungs-, Standkostenrisiko (ADR-056): Standzeit nach Saison, Gewährleistungsrücklage
nach Alter, Kapitalbindung, neue Wertfaktoren, Mängelrisiko in Spanne und Sicherheit, Hinweis an den Ankäufer, Kalkulation, Oberfläche."""
# ruff: noqa: F811 – Fixtures aus test_team_bearbeitung werden importiert und als Parameter genutzt
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime

import pytest

from tests.daten import BASIS, lade_cfg
from tests.test_team_bearbeitung import lokal, server  # noqa: F401 – Fixtures
from wmscout.bewertung import kalkulation as kalk
from wmscout.bewertung.anschreiben import hinweis_schwere_maengel, hinweise
from wmscout.bewertung.rechner import Rechner

FZ = {"id": "x", "art": "Teilintegrierter", "marke": "Knaus", "modell": "Sky TI 650 MEG", "serie": "Sky TI", "ez_jahr": 2018, "km": 80000,
      "preis": 40000}
OKTOBER, MAI = datetime(2026, 10, 25, 12), datetime(2026, 5, 15, 12)


def _v(i, preis, **k):
    return {"id": f"v{i}", "art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "preis": preis,
            "zuletzt_gesehen": "2026-10-20T10:00:00", **k}


VGL = [_v(i, 46000 + i * 400) for i in range(9)]


# ---------------------------------------------------------------- 1. Standzeit, Gewährleistung, Kapitalbindung
@pytest.mark.parametrize("monat, monate", [(1, 4), (3, 3), (5, 3), (9, 4), (10, 5), (11, 5), (12, 4)])
def test_standzeit_nach_saison(monat, monate):
    assert Rechner(lade_cfg(), datetime(2026, monat, 15, 12)).standzeit_monate() == monate


def test_standzeit_ohne_eintrag_und_mit_textschluesseln():
    cfg = lade_cfg()
    del cfg["rechner"]["kosten"]["standzeit_saison_zuschlag"]
    assert Rechner(cfg, OKTOBER).standzeit_monate() == 3                                    # ohne Eintrag wie bisher
    cfg["rechner"]["kosten"]["standzeit_saison_zuschlag"] = {"10": 2}                       # nach JSON-Rundreise (gespeicherte Kalkulation)
    assert Rechner(cfg, OKTOBER).standzeit_monate() == 5


@pytest.mark.parametrize("alter, prozent", [(0, 0.02), (5, 0.02), (6, 0.025), (10, 0.025), (14, 0.035), (16, 0.045), (40, 0.045)])
def test_gewaehrleistung_nach_alter(alter, prozent):
    assert Rechner(lade_cfg(), OKTOBER).gewaehrleistung_prozent(alter) == prozent


def test_gewaehrleistung_ohne_staffel_fester_satz():
    cfg = lade_cfg()
    del cfg["rechner"]["kosten"]["gewaehrleistung_staffel"]
    assert Rechner(cfg, OKTOBER).gewaehrleistung_prozent(16) == cfg["rechner"]["kosten"]["gewährleistung_rücklage_prozent"]


def test_kostenposten():
    r = Rechner(lade_cfg(), OKTOBER)
    p = r.kosten(FZ, 50000)
    assert p["Standkosten"] == 120 * 5 and p["Gewährleistungsrücklage"] == 50000 * 0.025          # 8 Jahre → 2,5 %
    assert p["Kapitalbindung (5 Mon.)"] == round(50000 * 0.8 * 0.05 * 5 / 12 / 10) * 10
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["kapitalzins_jahr"] = 0
    assert not any(n.startswith("Kapitalbindung") for n in Rechner(cfg, OKTOBER).kosten(FZ, 50000))


def test_herbstkauf_senkt_den_max_ek():
    okt, mai = Rechner(lade_cfg(), OKTOBER).bewerte(FZ, VGL), Rechner(lade_cfg(), MAI).bewerte(FZ, VGL)
    assert okt.standzeit_monate == 5 and mai.standzeit_monate == 3
    assert okt.kosten > mai.kosten and okt.max_ek < mai.max_ek


# ---------------------------------------------------------------- 2. Ausstattung und Mängel
@pytest.mark.parametrize("text, erwartet", [
    ("Motorschaden, Kolbenfresser", {"Motorschaden"}), ("Getriebe defekt", {"Getriebeschaden", "Defekt genannt"}),
    ("Unfallfahrzeug, hinten instand gesetzt", {"Unfallschaden"}), ("unfallfrei, gepflegt", set()),
    ("kein Motorschaden, kein Unfallschaden", set()), ("mit AHK und Truma Combi D6", {"Anhängerkupplung", "Dieselheizung"}),
    ("Anhängerkupplung, Webasto Dieselheizung", {"Anhängerkupplung", "Dieselheizung"}),
])
def test_neue_wertfaktoren(text, erwartet):
    assert set(Rechner(lade_cfg(), OKTOBER).wertfaktoren({"beschreibung": text})) == erwartet


def test_maengelrisiko_in_spanne_und_sicherheit():
    r = Rechner(lade_cfg(), OKTOBER)
    sauber = r.bewerte(FZ, VGL)
    feucht = r.bewerte({**FZ, "id": "f", "beschreibung": "Leider Feuchtigkeit im Heck"}, VGL)
    rost = r.bewerte({**FZ, "id": "r", "beschreibung": "etwas Rost am Rahmen"}, VGL)
    viel = r.bewerte({**FZ, "id": "m", "beschreibung": "Motorschaden, Wasserschaden, Delamination"}, VGL)
    assert sauber.maengel_risiko == 0 and sauber.sicherheit == "hoch"
    assert feucht.maengel_risiko == pytest.approx(0.06) and feucht.sicherheit == "mittel"          # schwerer Mangel → höchstens mittel
    assert rost.maengel_risiko == pytest.approx(0.03) and rost.sicherheit == "hoch"                # leichter Mangel: Sicherheit bleibt
    assert viel.maengel_risiko == pytest.approx(0.15)                                              # gedeckelt
    # die untere Spanne reicht weiter, bezogen auf den eigenen Punktwert
    assert (feucht.max_ek - feucht.max_ek_von) > (sauber.max_ek - sauber.max_ek_von)
    assert feucht.spanne_von / feucht.marktwert_angebote < sauber.spanne_von / sauber.marktwert_angebote
    assert feucht.max_ek_von <= feucht.max_ek <= feucht.max_ek_bis and "Mängelrisiko: untere Spanne 6 % weiter" in feucht.vergleich_basis
    cfg = lade_cfg()
    cfg["rechner"]["maengelrisiko_max"] = 0
    aus = Rechner(cfg, OKTOBER).bewerte({**FZ, "id": "f2", "beschreibung": "Leider Feuchtigkeit im Heck"}, VGL)
    assert aus.maengel_risiko == 0 and "Mängelrisiko" not in aus.vergleich_basis


def test_hinweis_schwere_maengel():
    r = Rechner(lade_cfg(), OKTOBER)
    a = {**FZ, "id": "h", "beschreibung": "Feuchtigkeit im Heck, etwas Rost"}
    assert hinweis_schwere_maengel(["Feuchtigkeit"]) in hinweise(a, r.bewerte(a, VGL))
    rost = {**FZ, "id": "h2", "beschreibung": "etwas Rost"}
    assert not any(h.startswith("Schwerer Mangel") for h in hinweise(rost, r.bewerte(rost, VGL)))


# ---------------------------------------------------------------- 3. Kalkulation und Ankauf
def test_kalkulation_e5_nachrechenbar():
    cfg = lade_cfg()
    for k in ("standzeit_saison_zuschlag", "gewaehrleistung_staffel", "kapitalzins_jahr", "kapital_anteil_vk"):
        del cfg["rechner"]["kosten"][k]
    del cfg["rechner"]["maengelrisiko_max"]
    vorher = copy.deepcopy(cfg)
    e = kalk.eingabe(cfg, {**FZ, "entfernung_km": 50}, VGL, betrag=30000, stichtag=OKTOBER, abholung="Firmensitz")
    assert cfg == vorher                                                                    # Konfiguration nicht verändert
    assert e["version"] == kalk.VERSION and int(kalk.VERSION[1:]) >= 5 and e["rechner"]["maengelrisiko_max"] == 0.0
    assert e["rechner"]["kosten"]["standzeit_saison_zuschlag"] == {} and e["rechner"]["kosten"]["kapitalzins_jahr"] == 0.0
    voll = kalk.eingabe(lade_cfg(), {**FZ, "entfernung_km": 50}, VGL, betrag=30000, stichtag=OKTOBER, abholung="Firmensitz")
    gespeichert = json.loads(json.dumps(voll))                                              # Monatsschlüssel werden Text
    assert kalk.rechne(gespeichert) == kalk.rechne(voll)
    assert kalk.rechne(voll)["szenarien"]["erwartet"]["kosten"] > kalk.rechne(e)["szenarien"]["erwartet"]["kosten"]


def test_ankauf_plant_mit_saison(db, cfg, tmp_path):
    from wmscout.ankauf import AnkaufSpeicher
    assert AnkaufSpeicher(db, cfg, tmp_path / "f")._standzeit_tage() == Rechner(cfg).standzeit_monate() * 30


# ---------------------------------------------------------------- 4. Oberfläche
def test_detail_zeigt_risiken(server, db):
    jahr = date.today().year - 8
    for i in range(5):
        db.speichere_treffer({"id": f"p{i}", "titel": f"Knaus Sky TI {i}", "preis": 40000 + i * 300, "km": 60000 + i * 7000, "ez_jahr": jahr,
                              "ort": "70173 Stuttgart"}, "Teilintegrierter")
    db.speichere_treffer({"id": "z1", "titel": "Knaus Sky TI mit Feuchtigkeit <b>x</b>", "preis": 30000, "km": 100000, "ez_jahr": jahr,
                          "ort": "70173 Stuttgart"}, "Teilintegrierter")
    db.con.commit()
    c = lokal(server)
    html = c("GET", "/")[1]
    detail = re.search(r'<section id="dz1".*?</section>', html, re.S).group(0)
    assert "data-standzeit" in detail and "Kapitalbindung (" in detail and "data-maengelrisiko" in detail and "<b>x</b>" not in detail
    d = c("GET", "/api/fahrzeug/z1")[1]
    assert d["bewertung"]["maengel_risiko"] == pytest.approx(0.06) and any(h.startswith("Schwerer Mangel") for h in d["hinweise"])
    assert BASIS.exists()


# ---------------------------------------------------------------- 5. Korrekturrunde (QA P5-05)
@pytest.mark.parametrize("text, erwartet", [
    ("Zahnriemen und Zylinderkopfdichtung neu", set()), ("ZKD erneuert", set()), ("neue Kupplung", set()),           # QA B1
    ("Zylinderkopfdichtung defekt", {"Motorschaden", "Defekt genannt"}),
    ("Webasto Dachluke", set()), ("Webasto Klimaanlage", set()), ("Webasto Air Top 2000", {"Dieselheizung"}),        # QA B4
])
def test_muster_korrekturen(text, erwartet):
    assert set(Rechner(lade_cfg(), OKTOBER).wertfaktoren({"beschreibung": text})) == erwartet


def test_mehrere_schwere_maengel():
    """QA B2: „schwer“ nach dem vollen Wert; zwei schwere Mängel → Sicherheit niedrig, alle im Hinweis, tiefer als ein einzelner."""
    r = Rechner(lade_cfg(), OKTOBER)
    eins = r.bewerte({**FZ, "id": "e", "beschreibung": "Motorschaden"}, VGL)
    drei = r.bewerte({**FZ, "id": "d", "beschreibung": "Motorschaden, Wasserschaden, Delamination"}, VGL)
    assert eins.sicherheit == "mittel" and drei.sicherheit == "niedrig" and drei.max_ek < eins.max_ek
    assert {m["name"] for m in drei.maengel if m["roh"] <= -0.05} == {"Motorschaden", "Wasserschaden", "Delamination"}
    a = {**FZ, "id": "d", "beschreibung": "Motorschaden, Wasserschaden, Delamination"}
    hinweis = next(h for h in hinweise(a, drei) if h.startswith("Schwerer Mangel"))
    assert all(n in hinweis for n in ("Motorschaden", "Wasserschaden", "Delamination"))


def test_kalibrierung_ohne_kapitalbindung():
    """QA B3: die rechnerische Kapitalbindung ist nicht Teil der Plankosten im Vergleich mit Ist-Kosten."""
    from wmscout.bewertung import ergebnis
    from wmscout.bewertung import kalibrierung as kal
    r = Rechner(lade_cfg(), OKTOBER)
    b = r.bewerte(FZ, VGL)
    kapital = ergebnis.kosten_kapital(b.kosten_posten)
    assert kapital > 0
    plan = ergebnis.plan_aus_bewertung(b, 30000, standzeit_tage=150, differenzbesteuerung=True)
    assert plan["kosten_kapital"] == kapital
    a = {"id": 1, "referenz": "AK-1", "status": "verkauft", "kaufpreis": 30000, "plan_json": json.dumps(plan), "uebergabe_am": "2026-01-01",
         "verkauft_am": "2026-05-01", "vk_preis": 40000, "erstellt_am": "2025-12-30T10:00:00"}
    assert kal.fall_aus_ankauf(a, [{"art": "aufbereitung", "betrag": 1000}])["kosten_plan"] == b.kosten - kapital
    f = kal.pruefe_fall({"art": "Teilintegrierter", "marke": "Knaus", "ez_jahr": 2018, "km": 80000, "ankauf_am": "2025-10-25",
                         "ankauf_preis": 30000}, date(2026, 10, 25))
    m = kal.fall_aus_manuell({**f, "id": 9}, lade_cfg())
    nach = Rechner(lade_cfg(), datetime(2025, 10, 25, 12)).bewerte({"id": "kalibrierung-9", "art": "Teilintegrierter", "marke": "Knaus",
                                                                   "ez_jahr": 2018, "km": 80000, "titel": "Knaus"}, [])
    assert m["kosten_plan"] == nach.kosten - ergebnis.kosten_kapital(nach.kosten_posten)


def test_plan_standzeit_aus_bewertung_und_kalkulation():
    """QA B6: die Plan-Standzeit beim Ankauf stammt aus derselben Rechnung wie die Plankosten."""
    e = kalk.eingabe(lade_cfg(), {**FZ, "entfernung_km": 50}, VGL, betrag=30000, stichtag=OKTOBER, abholung="Firmensitz")
    assert kalk.rechne(e)["standzeit_monate"] == 5
    e = kalk.eingabe(lade_cfg(), {**FZ, "entfernung_km": 50}, VGL, betrag=30000, stichtag=MAI, abholung="Firmensitz")
    assert kalk.rechne(e)["standzeit_monate"] == 3


@pytest.mark.parametrize("wert", [{10: "2 Mon"}, {13: 1}, {10: -1}, "Oktober"])
def test_saison_fehleingabe_verstaendlich(wert):
    """QA B7: eine Fehleingabe meldet sich verständlich, statt jede Bewertung scheitern zu lassen."""
    cfg = lade_cfg()
    cfg["rechner"]["kosten"]["standzeit_saison_zuschlag"] = wert
    with pytest.raises(ValueError, match="standzeit_saison_zuschlag"):
        Rechner(cfg, OKTOBER)
