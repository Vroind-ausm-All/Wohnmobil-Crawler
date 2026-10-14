"""Orte im Ausland (quellenunabhängig): keine deutsche PLZ, keine Entfernung, Ampel höchstens gelb, sichtbarer Hinweis, Brief ohne Betrag."""
from datetime import date

import pytest

from tests.daten import BASIS
from wmscout.bewertung.anschreiben import HINWEIS_AUSLAND, kontext, sperrgrund
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.datenbank import Datenbank
from wmscout.normalisierung.fahrzeug import ergaenze_fahrzeug
from wmscout.normalisierung.geo import auslands_kuerzel, plz_aus_text


@pytest.mark.parametrize("ort, land, plz", [
    ("FR-75001 Paris", "FR", None), ("IT-20121 Mailand", "IT", None), ("ES-28001 Madrid", "ES", None),
    ("SE-123 45 Beispielstadt", "SE", None), ("NL-1234AB Beispieldorf", "NL", None), ("AT-1010 Wien", "AT", None),
    ("CH-8001 Zürich", "CH", None),
    ("D-70191 Stuttgart", None, "70191"),
    ("DEU-70191 Stuttgart", None, "70191"), ("GER-70191 Stuttgart", None, "70191"),
    ("DE-70191 Stuttgart", None, "70191"), ("70173 Stuttgart", None, "70173"),
    ("Stuttgart", None, None), ("", None, None), (None, None, None),
])
def test_auslandskuerzel_und_plz(ort, land, plz):
    assert auslands_kuerzel(ort) == land
    assert plz_aus_text(ort) == plz                       # fünf Ziffern hinter einem fremden Kürzel sind keine deutsche PLZ


def test_ergaenze_fahrzeug_setzt_ausland_und_keine_plz():
    a = ergaenze_fahrzeug({"id": "x", "titel": "Camper", "ort": "FR-75001 Paris"})
    assert (a["plz"], a["ausland"]) == (None, "FR")
    a = ergaenze_fahrzeug({"id": "x", "titel": "Camper", "ort": "D-70191 Stuttgart"})
    assert (a["plz"], a["ausland"]) == ("70191", None)


@pytest.fixture
def orte(cfg, db: Datenbank):
    jahr = date.today().year - 8
    for i, ort in enumerate(["70173 Stuttgart", "D-70191 Stuttgart", "Stuttgart", "FR-75001 Paris", "SE-123 45 Beispielstadt",
                             "NL-1234AB Beispieldorf", "IT-20121 Mailand", "ES-28001 Madrid"]):
        db.speichere_treffer({"id": f"o{i}", "titel": "Hymer Kastenwagen", "preis": 15000, "km": 90000, "ez_jahr": jahr, "ort": ort,
                              "gewerblich": False, "url": "u"}, "Kastenwagen")          # Crawler-Suche: Art bestätigt, kein Art-Hinweis
    return {z["a"]["ort"]: z for z in bewerte_alle(cfg, db, BASIS)}


def test_ausland_ohne_entfernung_ampel_gelb_hinweis_ohne_betrag(orte):
    for ort in ("FR-75001 Paris", "SE-123 45 Beispielstadt", "NL-1234AB Beispieldorf", "IT-20121 Mailand", "ES-28001 Madrid"):
        z = orte[ort]
        assert z["a"]["plz"] is None and z["a"]["entfernung_km"] is None and z["a"]["ausland"] == ort[:2], ort
        assert z["b"].ampel == "gelb" and "Ausland" in z["b"].vergleich_basis, ort
        assert len(z["hinweise"]) == 1 and z["hinweise"][0].startswith(HINWEIS_AUSLAND), ort
        assert z["sperre"] is None and z["brief"] and "€ an" not in z["brief"], ort           # bleibt anschreibbar, aber ohne Betrag
        assert z["bereit"]                                                                       # Ampel gelb genügt (ab_ampel: gelb)


def test_inland_bleibt_unveraendert(orte):
    for ort in ("70173 Stuttgart", "D-70191 Stuttgart", "Stuttgart"):
        z = orte[ort]
        assert z["a"]["ausland"] is None and z["hinweise"] == [] and z["b"].ampel == "gruen" and "€ an" in z["brief"], ort
    assert orte["70173 Stuttgart"]["a"]["entfernung_km"] == 0 and orte["D-70191 Stuttgart"]["a"]["plz"] == "70191"
    assert orte["D-70191 Stuttgart"]["a"]["entfernung_km"] == 3                      # „D-“ ist Inland: Entfernung wird berechnet
    assert orte["Stuttgart"]["a"]["plz"] is None and orte["Stuttgart"]["a"]["entfernung_km"] is None


def test_ausland_wird_bei_entfernungsgrenze_gesperrt_inland_nicht(cfg, orte):
    ausland, inland = orte["FR-75001 Paris"]["a"], orte["D-70191 Stuttgart"]["a"]
    assert sperrgrund(ausland, cfg) is None and sperrgrund(inland, cfg) is None             # max_entfernung_km 0 = egal
    cfg["filter"]["max_entfernung_km"] = 100
    assert sperrgrund(ausland, cfg) == "Ausland (FR) – Entfernung nicht berechenbar"
    assert sperrgrund(inland, cfg) is None


def test_ort_kurz_ohne_plz_und_laenderkuerzel(cfg, orte):
    for ort, kurz in (("70173 Stuttgart", "Stuttgart"), ("FR-75001 Paris", "Paris"), ("SE-123 45 Beispielstadt", "Beispielstadt"),
                      ("NL-1234AB Beispieldorf", "Beispieldorf"), ("Stuttgart", "Stuttgart")):
        z = orte[ort]
        assert kontext(z["a"], z["b"], cfg)["ort_kurz"] == kurz, ort


def test_ort_kurz_entfernt_nur_plz_und_auslandskennung():
    """QA Q2-N3: Ein großgeschriebenes Zweibuchstaben-Wort nach einer deutschen PLZ gehört zum Ort."""
    from wmscout.bewertung.anschreiben import kontext
    from tests.daten import lade_cfg
    cfg = lade_cfg()
    for ort, erwartet in (("70173 Stuttgart", "Stuttgart"), ("12345 XY", "XY"), ("NL-7595XP Beispieldorf", "Beispieldorf"),
                          ("SE-123 45 Beispielstadt", "Beispielstadt"), ("", "Ihrer Nähe")):
        assert kontext({"ort": ort, "titel": "x"}, None, cfg)["ort_kurz"] == erwartet, ort
