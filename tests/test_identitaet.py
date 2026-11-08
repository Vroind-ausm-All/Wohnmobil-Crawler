"""P3-02a: Regeln zum Vergleich zweier Inserate (reine Funktion), Blockbildung und Verträglichkeit mit ``finde_duplikate``.

Invariante: Jedes Paar, das ``finde_duplikate`` heute gruppiert, ist mindestens „mittel“ – der neue Vergleich ist nie strenger als die
bestehende Heuristik (die Bewertung bleibt unberührt, hier geht es nur um die Vorschläge).
"""
from __future__ import annotations

import itertools
import random
import time

import pytest

from tests.daten import MARKEN, ORTE
from wmscout.bewertung.auswertung import finde_duplikate
from wmscout.normalisierung import identitaet
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.normalisierung.identitaet import (MAX_PAARE_JE_BLOCK, REGEL_VERSION, Vergleich, bloecke, gleichzeitig_online, kandidatenpaare,
                                              modellnummern, vergleiche)

REIHEN = {"Knaus": "Sky TI", "Hymer": "ML-T", "Dethleffs": "Trend", "Bürstner": "Lyseo", "Pössl": "Summit", "Weinsberg": "CaraCompact"}


def z(i="a", **kw) -> dict:
    """Bereits ergänzte Zeile (Marke, Serie, PLZ gesetzt)."""
    basis = {"id": i, "marke": "Knaus", "serie": "Sky TI", "titel": "Knaus Sky TI 650 MEG", "ez_jahr": 2016, "km": 90000, "plz": "70173",
             "preis": 40000, "erstmals_gesehen": "2026-10-01T10:00:00"}
    return {**basis, **kw}


def stufe(a, b):
    return vergleiche(a, b).konfidenz


def mindestens_mittel(v: Vergleich) -> bool:
    """Invariante „finde_duplikate ⇒ mindestens mittel“ – AUSSER bei einem Modellnummer- oder Art-Widerspruch (Regel 2): diese Merkmale
    kennt ``finde_duplikate`` nicht, der Vergleich schließt solche Paare bewusst aus."""
    if v.konfidenz in ("hoch", "mittel"):
        return True
    return bool(v.widersprueche) and all(w.startswith(("abweichende Modellnummer", "andere Fahrzeugart")) for w in v.widersprueche)


# ---------------------------------------------------------------- Stufen
@pytest.mark.parametrize("b, erwartet", [
    pytest.param(z("b"), "hoch", id="hoch-gleich"),
    pytest.param(z("b", titel="Verkaufe Wohnmobil Teilintegrierter", preis=36000), "hoch", id="hoch-preis"),
    pytest.param(z("b", preis=90000, km=91000), "hoch", id="hoch-titel"),
    pytest.param(z("b", titel="Ganz anderer Text", preis=60000), "mittel", id="mittel-titel+preis-fern"),
    pytest.param(z("b", serie=None), "mittel", id="mittel-serie-unbekannt"),
    pytest.param(z("b", titel="Anderer Text hier", preis=1), "mittel", id="mittel-preis-eins"),
    pytest.param(z("b", plz="73728"), "mittel", id="mittel-plz-nah"),            # Esslingen ~ 15 km von Stuttgart
    pytest.param(z("b", plz="80331"), None, id="none-plz-fern"),                 # München
    pytest.param(z("b", plz="73728", titel="Anderer Text hier", preis=60000), None, id="none-plz-nah-aber-schwach"),
    pytest.param(z("b", plz="73728", serie=None), None, id="none-plz-nah-serie-unbekannt"),
    pytest.param(z("b", km=93001), None, id="none-km-ueber-rahmen"),
    pytest.param(z("b", km=93000), "hoch", id="hoch-km-genau-rahmen"),
    pytest.param(z("b", plz=None), None, id="none-plz-fehlt"),
    pytest.param(z("b", km=None), None, id="none-km-fehlt"),
    pytest.param(z("b", ez_jahr=None), None, id="none-ez-fehlt"),
    pytest.param(z("b", marke=None), None, id="none-marke-fehlt"),
    pytest.param(z("b", ez_jahr=2017), None, id="none-ez-plus-eins"),            # kein Widerspruch, aber auch kein Vorschlag
])
def test_stufen(b, erwartet):
    a = z("a")
    v = vergleiche(a, b)
    assert v.konfidenz == erwartet, v
    assert vergleiche(b, a).konfidenz == erwartet                  # symmetrisch
    if erwartet:
        assert v.gruende and not v.widersprueche
        assert all("%" not in g for g in v.gruende)                # Stufe und Gründe, keine Prozentwerte


# ---------------------------------------------------------------- Widersprüche
@pytest.mark.parametrize("aenderung, stichwort", [
    pytest.param({"marke": "Hymer", "serie": None}, "Marke", id="marke"),
    pytest.param({"ez_jahr": 2018}, "Erstzulassung", id="ez2"),
    pytest.param({"serie": "Sky Wave"}, "Modellreihe", id="serie"),
    pytest.param({"km": 80000, "erstmals_gesehen": "2026-10-10T10:00:00"}, "Kilometerstand", id="km-rueckgang"),
])
def test_widerspruch_gibt_keinen_vorschlag(aenderung, stichwort):
    a, b = z("a"), z("b", **aenderung)
    v = vergleiche(a, b)
    assert v.konfidenz is None and v.gruende == [] and len(v.widersprueche) == 1 and stichwort in v.widersprueche[0], v
    assert len(vergleiche(b, a).widersprueche) == 1 and vergleiche(b, a).konfidenz is None


def test_widerspruch_hebt_selbst_ein_sonst_perfektes_paar_auf(monkeypatch):
    """Ohne Widerspruchsprüfung wäre „verschiedene Modellreihe“ nicht an den Gründen erkennbar – hier wird die Prüfung direkt gefordert."""
    assert vergleiche(z("a"), z("b", serie="Sky Wave")).widersprueche
    monkeypatch.setattr(identitaet, "_widersprueche", lambda a, b: [])
    assert vergleiche(z("a"), z("b", ez_jahr=2018)).widersprueche == []            # Gegenprobe: mit abgeschalteter Regel verschwindet er


def test_km_rueckgang_nur_mit_zeitpunkten():
    a, b = z("a", km=90000, erstmals_gesehen=""), z("b", km=80000, erstmals_gesehen="")
    assert vergleiche(a, b).widersprueche == []                                    # ohne Zeitpunkte nicht beurteilbar (und km-Abstand zu groß)
    assert vergleiche(a, b).konfidenz is None
    # km steigt beim jüngeren Inserat: kein Widerspruch (Fahrzeug wurde weitergefahren)
    assert vergleiche(z("a", km=90000), z("b", km=91000, erstmals_gesehen="2026-10-20T10:00:00")).konfidenz == "hoch"


def test_personenmerkmale_und_fin_zaehlen_nicht():
    a, b = z("a"), z("b")
    ohne = vergleiche(a, b)
    mit = vergleiche({**a, "verkaeufer": "Müller", "telefon": "0171 1", "fin": "WDB1234567890"},
                     {**b, "verkaeufer": "Meier", "telefon": "0172 2", "fin": "WDB0000000000", "notiz": "x", "url": "https://y"})
    assert mit == ohne and isinstance(mit, Vergleich) and REGEL_VERSION == 2
    assert "Müller" not in str(mit) and "0171" not in str(mit)


def test_titel_aehnlichkeit_ohne_titel_und_mit_zahlen():
    assert identitaet.titel_aehnlich("Knaus Sky TI 650 MEG!", "knaus sky ti 650 meg") is True
    assert identitaet.titel_aehnlich(None, "Knaus") is False and identitaet.titel_aehnlich("", "") is False
    assert identitaet.titel_aehnlich("Knaus Sky TI 650 MEG", "Hymer B 544 Alkoven") is False


# ---------------------------------------------------------------- Verträglichkeit mit finde_duplikate
def _synthetisch(n: int, seed: int) -> list[dict]:
    """Viele Kollisionen mit kleinen Wertebereichen: Marken, Jahre, PLZ, Reihen (auch unbekannt), km in 1.000er-Schritten."""
    rng = random.Random(seed)
    zeilen = []
    for i in range(n):
        marke = rng.choice(["Knaus", "Hymer", "Hobby"])
        zeilen.append({"id": f"s{i}", "marke": marke, "serie": rng.choice([None, "A", "B"]), "titel": rng.choice(["Eins", "Zwei", "Eins plus"]),
                       "ez_jahr": rng.choice([2015, 2016, 2017, None]), "km": rng.choice([None, 0, 50000, 51000, 52500, 54000, 56000, 90000]),
                       "plz": rng.choice(["70173", "70174", "73728", "80331", None]), "preis": rng.choice([None, 1, 30000, 33000, 50000]),
                       "erstmals_gesehen": f"2026-10-{rng.randint(1, 20):02d}T10:00:00"})
    return zeilen


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_invariante_finde_duplikate_ist_mindestens_mittel_synthetisch(seed):
    zeilen = _synthetisch(250, seed)
    nach_id = {r["id"]: r for r in zeilen}
    gruppiert = finde_duplikate(zeilen)
    paare = {tuple(sorted((i, b["id"]))) for i, andere in gruppiert.items() for b in andere}
    assert paare, "Testdaten ohne Dubletten wären wertlos"
    for i, j in paare:
        v = vergleiche(nach_id[i], nach_id[j])
        assert v.konfidenz in ("hoch", "mittel") and not v.widersprueche, (nach_id[i], nach_id[j], v)       # synthetisch: keine Nummern/Arten


def test_invariante_finde_duplikate_ist_mindestens_mittel_mit_fixture_und_planten(cfg, db, importiert):
    """Die 60 nachgebauten Inserate der Fixtures (tests/daten.py), dazu geplante Dubletten; alle über ``ergaenze_fahrzeug`` wie in der Bewertung."""
    rows = [dict(r) for r in db.alle_mit_preis()]
    for i, r in enumerate(rows[:12]):                                              # Wiedereinstellung: gleiche Merkmale, neue Kennung
        rows.append({**r, "id": f"dup{i}", "preis": (r["preis"] or 10000) + 500, "km": (r["km"] or 50000) + 800 * (i % 3)})
    alle = [ergaenze_fahrzeug(dict(r)) for r in rows]
    nach_id = {r["id"]: r for r in alle}
    paare = {tuple(sorted((i, b["id"]))) for i, andere in finde_duplikate(alle).items() for b in andere}
    assert len(paare) >= 6
    for i, j in paare:
        assert mindestens_mittel(vergleiche(nach_id[i], nach_id[j])), (nach_id[i]["titel"], nach_id[j]["titel"])
    # und der neue Vergleich findet die Wiedereinstellungen über die Blockbildung
    gefunden = {tuple(sorted((a["id"], b["id"]))) for a, b in kandidatenpaare(alle) if vergleiche(a, b).konfidenz}
    assert len(paare - gefunden) <= len(paare) // 10 + 1 and all(mindestens_mittel(vergleiche(nach_id[i], nach_id[j])) for i, j in paare - gefunden)


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_blockbildung_findet_dieselben_paare_wie_der_volle_vergleich(seed):
    zeilen = _synthetisch(220, seed)
    voll = {tuple(sorted((a["id"], b["id"]))) for a, b in itertools.combinations(zeilen, 2) if vergleiche(a, b).konfidenz}
    mit_bloecken = [tuple(sorted((a["id"], b["id"]))) for a, b in kandidatenpaare(zeilen) if vergleiche(a, b).konfidenz]
    assert len(mit_bloecken) == len(set(mit_bloecken))                              # kein Paar doppelt
    assert set(mit_bloecken) == voll and voll


def test_bloecke_enthalten_nur_vollstaendige_zeilen_und_nachbarjahr():
    zeilen = [z("a"), z("b", ez_jahr=2017), z("c", ez_jahr=2019), z("d", plz=None), z("e", km=None), z("f", marke="Hymer")]
    namen = sorted(sorted(r["id"] for r in blk) for blk in bloecke(zeilen))
    assert namen == [["a", "b"], ["b"], ["c"], ["f"]]                               # a+b (2016/2017), b allein (2017/-), c, f; d und e fehlt etwas


# ---------------------------------------------------------------- Laufzeit
def _grosse_menge(n: int) -> tuple[list[dict], set[tuple[str, str]]]:
    rng = random.Random(42)
    marken = list(MARKEN) + [f"Marke{i}" for i in range(34)]
    plzs = [o.split()[0] for o in ORTE] + [f"{rng.randint(10000, 99999)}" for _ in range(300)]
    zeilen = [{"id": f"g{i}", "marke": (m := rng.choice(marken)), "serie": f"R{rng.randint(1, 6)}", "titel": f"{m} Modell {rng.randint(1, 400)}",
               "ez_jahr": rng.randint(2000, 2024), "km": rng.randint(5, 250) * 1000, "plz": rng.choice(plzs), "preis": rng.randint(15, 90) * 1000,
               "erstmals_gesehen": "2026-10-01T10:00:00"} for i in range(n)]
    geplant = set()
    for i in range(0, 1000, 10):                                                   # 100 geplante Dubletten
        r = zeilen[i]
        zeilen.append({**r, "id": f"p{i}", "km": r["km"] + 500, "erstmals_gesehen": "2026-10-05T10:00:00"})
        geplant.add((r["id"], f"p{i}"))
    return zeilen, geplant


def test_laufzeit_50000_zeilen(capsys):
    zeilen, geplant = _grosse_menge(50_000)
    start = time.perf_counter()
    treffer = {}
    pruefungen = 0
    for a, b in kandidatenpaare(zeilen):
        pruefungen += 1
        if (v := vergleiche(a, b)).konfidenz:
            treffer[tuple(sorted((a["id"], b["id"])))] = v.konfidenz
    dauer = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[P3-02a] Vergleich von {len(zeilen)} Zeilen: {dauer:.2f} s, {pruefungen} geprüfte Paare, {len(treffer)} Vorschläge")
    assert all(tuple(sorted(p)) in treffer for p in geplant)                        # jede geplante Dublette gefunden
    assert pruefungen < len(zeilen) * 20                                            # Blockbildung: weit unter n²/2 = 1,25 Mrd. Paaren
    assert dauer < 60


def test_koordinaten_vorberechnete_praefixmittel_wie_die_alte_suche():
    """P3-02a hat die Näherung für unbekannte PLZ (Mittel je Präfix) vorberechnet; Ergebnis muss dem früheren Durchsuchen der Tabelle gleichen."""
    from wmscout.normalisierung import geo
    daten = geo._lade()
    rng = random.Random(5)
    proben = [f"{rng.randint(1000, 99999):05d}" for _ in range(300)] + ["12", "123", "1234", "00000", "99999", "70173"]
    for plz in proben:
        erwartet = None
        if plz in daten:
            erwartet = daten[plz]
        else:
            for stellen in (3, 2):
                naechste = [k for p, k in daten.items() if p.startswith(plz[:stellen])]
                if naechste:
                    erwartet = (sum(k[0] for k in naechste) / len(naechste), sum(k[1] for k in naechste) / len(naechste))
                    break
        assert geo.koordinaten(plz) == erwartet, plz


# ---------------------------------------------------------------- Regel 2: Modellnummer, Art (B1)
@pytest.mark.parametrize("titel, erwartet", [
    pytest.param("Knaus Sky TI 650 MEG", {"650"}, id="grundriss"),
    pytest.param("Summit 600 Prime", {"600"}, id="summit"),
    pytest.param("Hymer B 544 EZ 2016 39.900 €", {"544"}, id="jahr-preis"),
    pytest.param("Wohnmobil 90000 km 140 PS 3.500 kg", set(), id="einheiten"),
    pytest.param("Ducato 2,3 Multijet 130PS 12345 Stuttgart", set(), id="ps-plz"),
    pytest.param("Hymer 4500 VB 544", {"544"}, id="vb"),
    pytest.param("Preis: 4500 Knaus 650", {"650"}, id="preis-wort"),
    pytest.param("T 7057 EB", {"7057"}, id="vierstellig"),
    pytest.param(None, set(), id="none"),
])
def test_modellnummern(titel, erwartet):
    assert set(modellnummern(titel)) == erwartet


@pytest.mark.parametrize("ta, tb", [
    pytest.param("Knaus Sky TI 650 MEG", "Knaus Sky TI 700 MEG", id="sky"),
    pytest.param("Pössl Summit 600", "Pössl Summit 640", id="summit"),
], )
def test_andere_modellnummer_ist_widerspruch_nie_hoch(ta, tb):
    a, b = z("a", titel=ta), z("b", titel=tb)
    v = vergleiche(a, b)
    assert v.konfidenz is None and len(v.widersprueche) == 1 and v.widersprueche[0].startswith("abweichende Modellnummer")
    assert vergleiche(b, a).konfidenz is None
    assert finde_duplikate([{**a, "id": "a"}, {**b, "id": "b"}])                       # finde_duplikate gruppiert sie weiterhin (Ausnahme der Invariante)
    assert mindestens_mittel(v)


@pytest.mark.parametrize("ta, tb, konf", [
    pytest.param("Knaus Sky TI 650 MEG", "Knaus Sky TI 650 MEG", "hoch", id="gleich"),
    pytest.param("Knaus Sky TI 650 MEG 2016", "Knaus Sky TI 650 MEG 2017", "hoch", id="jahr"),
    pytest.param("Knaus Sky TI 650 MEG 39.900 €", "Knaus Sky TI 650 MEG 35.000 €", "hoch", id="preis"),
    pytest.param("Knaus Sky TI 650 MEG", "Knaus Sky TI MEG gepflegt", "hoch", id="nur-eine-nummer"),
    pytest.param("Knaus Sky TI 650 MEG 90000 km", "Knaus Sky TI 650 MEG 91000 km", "hoch", id="km"),
])
def test_keine_falschen_modellnummer_widersprueche(ta, tb, konf):
    v = vergleiche(z("a", titel=ta), z("b", titel=tb))
    assert not v.widersprueche and v.konfidenz == konf, v


@pytest.mark.parametrize("aa, ab, widerspruch", [
    pytest.param("Alkoven", "Teilintegriert", True, id="alkoven-teil"),
    pytest.param("Teilintegrierter", "Teilintegriert", False, id="gleich"),
    pytest.param("Wohnmobil", "Alkoven", False, id="unbekannt"),
    pytest.param(None, "Alkoven", False, id="fehlt"),
])
def test_bekannt_verschiedene_art_ist_widerspruch(aa, ab, widerspruch):
    v = vergleiche(z("a", art=aa), z("b", art=ab))
    assert bool(v.widersprueche) is widerspruch
    assert (v.konfidenz is None) is widerspruch
    if widerspruch:
        assert "Fahrzeugart" in v.widersprueche[0] and mindestens_mittel(v)


# ---------------------------------------------------------------- Regel 2: gleichzeitig online (B3)
def online(i, von, bis, **kw):
    return z(i, erstmals_gesehen=f"2026-10-{von:02d}T10:00:00", zuletzt_gesehen=f"2026-10-{bis:02d}T10:00:00", **kw)


@pytest.mark.parametrize("a, b, konf, gleichzeitig", [
    pytest.param(online("a", 1, 20), online("b", 5, 20), "mittel", True, id="lange-parallel"),
    pytest.param(online("a", 1, 10), online("b", 12, 20), "hoch", False, id="nacheinander"),
    pytest.param(online("a", 1, 10), online("b", 9, 20), "hoch", False, id="genau-ein-tag"),
    pytest.param(online("a", 1, 10), online("b", 8, 20), "mittel", True, id="zwei-tage"),
    pytest.param(z("a"), z("b"), "hoch", False, id="ohne-zuletzt"),
    pytest.param(online("a", 1, 20, serie=None), online("b", 5, 20, serie=None), "mittel", True, id="mittel-bleibt"),
])
def test_gleichzeitig_online_hoechstens_mittel(a, b, konf, gleichzeitig):
    v = vergleiche(a, b)
    assert v.konfidenz == konf and gleichzeitig_online(a, b) is gleichzeitig and gleichzeitig_online(b, a) is gleichzeitig
    assert ("beide gleichzeitig online" in v.gruende) is gleichzeitig


def test_gleichzeitig_online_mit_unlesbaren_zeitpunkten():
    assert gleichzeitig_online(z("a", erstmals_gesehen="a", zuletzt_gesehen="b"), z("b", erstmals_gesehen="", zuletzt_gesehen=None)) is False
    assert gleichzeitig_online(online("a", 1, 20), z("b", erstmals_gesehen="2026-10-01T10:00:00Z", zuletzt_gesehen="2026-10-20T10:00:00Z")) is False


# ---------------------------------------------------------------- B7: geschätzte Lage
def test_entfernungsstufe_bei_geschaetzter_plz_nur_ungefaehr():
    from wmscout.normalisierung import geo
    assert geo.plz_bekannt("70173") and not geo.plz_bekannt("70100") and not geo.plz_bekannt(None)
    genau = vergleiche(z("a"), z("b", plz="73728"))
    assert genau.konfidenz == "mittel" and any("höchstens 30 km" in g and "ungefähr" not in g for g in genau.gruende)
    geschaetzt = vergleiche(z("a"), z("b", plz="70100"))                                  # nicht in der PLZ-Tabelle: Präfixmittel
    assert geschaetzt.konfidenz == "mittel" and any("ungefähr" in g and "geschätzt" in g for g in geschaetzt.gruende)


def test_koordinaten_einstellige_plz_ist_none_ab_zwei_stellen_wie_frueher():
    from wmscout.normalisierung import geo
    assert geo.koordinaten("1") is None and geo.koordinaten("") is None and geo.koordinaten(None) is None
    assert geo.koordinaten("12") is not None and geo.koordinaten("701") == geo.koordinaten("70100")


# ---------------------------------------------------------------- B2: Worst Case
def test_worst_case_tausende_gleiche_fahrzeuge_begrenzt(capsys):
    zeilen = [z(f"w{i}", erstmals_gesehen="2026-10-01T10:00:00") for i in range(3000)]       # 3000 identische Inserate
    gekuerzt: list[str] = []
    start = time.perf_counter()
    treffer = [(a["id"], b["id"]) for a, b in kandidatenpaare(zeilen, gekuerzt=gekuerzt) if vergleiche(a, b).konfidenz]
    dauer = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[P3-02a] Worst Case 3000 gleiche Fahrzeuge: {dauer:.2f} s, {len(treffer)} Paare (Grenze {MAX_PAARE_JE_BLOCK} je Block)")
    assert 0 < len(treffer) <= MAX_PAARE_JE_BLOCK and gekuerzt == ["Knaus 2016"]
    assert dauer < 10
