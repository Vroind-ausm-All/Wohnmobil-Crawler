"""P3-03: Lesesicht auf den Preisverlauf (``wmscout/preisverlauf.py``) und ``GET /api/preisverlauf`` – chronologisch, mit Kanal, Zeitpunkt und
Plattform; für ein Fahrzeug über alle seine Inserate. Rein lesend. Den Re-Import (Schreibseite) prüft tests/test_reimport.py."""
# ruff: noqa: F811 – Fixtures aus anderen Testmodulen werden importiert und als Parameter genutzt
from __future__ import annotations

import pytest

from tests.test_dubletten_entscheiden import team_api  # noqa: F401 – Fixture
from tests.test_dubletten_vorschlaege import inserat_id, starte, treffer
from tests.test_team_bearbeitung import anmelden, lokal
from wmscout.dubletten import bestaetige
from wmscout.preisverlauf import BEDINGUNG_FAHRZEUG, BEDINGUNG_INSERAT, SQL_VERLAUF, preisverlauf


def eintrag(db, anzeigen_id, zeitpunkt, preis, kanal):
    db.con.execute("INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?, ?, ?, ?)",
                   (inserat_id(db, anzeigen_id), zeitpunkt, preis, kanal))


def test_gemischte_zeitformate_werden_chronologisch_geordnet(db):
    """Die Kanäle schreiben verschieden: UTC mit Offset, Ereignis mit Zone und Mikrosekunden, Altbestand lokal ohne Zone. Sortiert wird nach dem Zeitpunkt."""
    db.speichere_treffer(treffer("a1", preis=None), "Alkoven")
    for zeit, preis, kanal in (("2026-03-05T09:00:00", 30000, "abgleich"),                 # lokal, ohne Zone: ein Tag später als die übrigen
                               ("2026-03-04T10:30:00+00:00", 29000, "suche"),
                               ("2026-03-04T12:45:30.123456+02:00", 28500, "api"),         # = 10:45:30 UTC
                               ("2026-03-04T10:30:00+00:00", 28800, "email"),              # gleiche Sekunde wie „suche“: Reihenfolge des Eintragens
                               ("", 31000, "migration"),                                   # nicht lesbar: am Anfang, gekennzeichnet
                               ("2026-03-03T08:00:00+00:00", 31500, "manuell")):
        eintrag(db, "a1", zeit, preis, kanal)
    v = preisverlauf(db, "a1")
    assert [(x["kanal"], x["preis"]) for x in v] == [("migration", 31000), ("manuell", 31500), ("suche", 29000), ("email", 28800), ("api", 28500),
                                                      ("abgleich", 30000)]
    assert v[0]["zeitpunkt"] is None and v[0]["zeitpunkt_roh"] == "" and all(x["zeitpunkt"].endswith("+00:00") for x in v[1:])
    assert v[4]["zeitpunkt"] == "2026-03-04T10:45:30+00:00"                                # auf Sekunden gekürzt, nach UTC
    assert [x["aenderung"] for x in v] == ["erstpreis", "erhoeht", "gesenkt", "gesenkt", "gesenkt", "erhoeht"]
    assert [x["differenz"] for x in v] == [None, 500, -2500, -200, -300, 1500] and v[1]["vorher"] == 31000


def test_gleicher_preis_ist_gleich_und_ohne_preis_leer(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    eintrag(db, "a1", "2099-01-01T00:00:00+00:00", 40000, "api")
    assert [x["aenderung"] for x in preisverlauf(db, "a1")] == ["erstpreis", "gleich"]
    db.speichere_treffer(treffer("a2", preis=None), "Alkoven")
    assert preisverlauf(db, "a2") == []                                                    # bekanntes Inserat ohne Preis: leer, kein Fehler


def test_fehlender_preis_loescht_nichts_und_schreibt_keinen_eintrag(db):
    """Eine Lesung ohne Preis (Mail ohne Preiszeile, „Preis auf Anfrage“) nimmt den letzten bekannten Preis nicht zurück (Absicht: ein nicht
    gelesener Preis ist keine Preisrücknahme; ``preis_historie.preis`` ist NOT NULL)."""
    db.speichere_treffer(treffer("a1", preis=40000), "Alkoven")
    db.speichere_treffer(treffer("a1", preis=None), "Alkoven")
    assert [(x["preis"], x["kanal"]) for x in preisverlauf(db, "a1")] == [(40000, "suche")]
    assert db.con.execute("SELECT preis FROM anzeigen WHERE id='a1'").fetchone()[0] == 40000


def test_fahrzeug_ueber_alle_inserate_mit_plattform(db):
    db.speichere_treffer(treffer("k1", preis=40000), "Alkoven")
    db.speichere_treffer(treffer("md-5", preis=41000, quelle="mobile.de", ort="80331 München", km=91000), "Alkoven")
    db.speichere_treffer(treffer("k1", preis=39000), "Alkoven")
    db.speichere_treffer(treffer("md-5", preis=40500, quelle="mobile.de", ort="80331 München", km=91000), "Alkoven")
    db.speichere_treffer(treffer("k3", preis=20000, ort="10115 Berlin", km=10000, titel="Hymer B 544", marke="Hymer"), "Alkoven")
    assert len(preisverlauf(db, fahrzeug_id=db.fahrzeug_id_zu("k1"))) == 2                 # vor der Zusammenführung: nur das eigene Inserat
    bestaetige(db, inserat_id(db, "k1"), inserat_id(db, "md-5"))
    fid = db.fahrzeug_id_zu("k1")
    assert fid == db.fahrzeug_id_zu("md-5") != db.fahrzeug_id_zu("k3")
    gemeinsam = preisverlauf(db, fahrzeug_id=fid)
    assert {(x["plattform"], x["anzeigen_id"], x["preis"]) for x in gemeinsam} == {
        ("kleinanzeigen", "k1", 40000), ("kleinanzeigen", "k1", 39000), ("mobile.de", "md-5", 41000), ("mobile.de", "md-5", 40500)}
    zeiten = [x["zeitpunkt"] for x in gemeinsam]
    assert zeiten == sorted(zeiten)
    # „vorher“ bezieht sich nur auf das eigene Inserat – Preise verschiedener Plattformen werden nicht verrechnet
    erste = {x["anzeigen_id"]: x for x in gemeinsam if x["aenderung"] == "erstpreis"}
    assert set(erste) == {"k1", "md-5"} and {x["anzeigen_id"]: x["differenz"] for x in gemeinsam if x["aenderung"] == "gesenkt"} == {"k1": -1000, "md-5": -500}
    assert [x["preis"] for x in preisverlauf(db, "k1")] == [40000, 39000]                  # das Inserat allein: weiter nur seine eigenen
    assert [x["preis"] for x in preisverlauf(db, fahrzeug_id=db.fahrzeug_id_zu("k3"))] == [20000]


def test_fehler_und_unbekannte(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    with pytest.raises(ValueError):
        preisverlauf(db)
    with pytest.raises(ValueError):
        preisverlauf(db, "a1", fahrzeug_id=1)
    with pytest.raises(LookupError):
        preisverlauf(db, "gibtsnicht")
    with pytest.raises(LookupError):
        preisverlauf(db, fahrzeug_id=99999)


def test_rein_lesend(db):
    db.speichere_treffer(treffer("a1"), "Alkoven")
    db.speichere_treffer(treffer("a1", preis=39000), "Alkoven")
    db.con.commit()
    vorher = db.con.total_changes
    preisverlauf(db, "a1")
    preisverlauf(db, fahrzeug_id=db.fahrzeug_id_zu("a1"))
    assert db.con.total_changes == vorher and not db.con.in_transaction


@pytest.mark.parametrize("bedingung, index", [(BEDINGUNG_INSERAT, "idx_preis_historie_inserat"), (BEDINGUNG_FAHRZEUG, "idx_inserate_fahrzeug")],
                         ids=["inserat", "fahrzeug"])
def test_abfrageplan_nutzt_indizes(db, bedingung, index):
    plan = " | ".join(r["detail"] for r in db.con.execute("EXPLAIN QUERY PLAN " + SQL_VERLAUF + bedingung, (1,)))
    assert index in plan and "SCAN" not in plan, plan


# ---------------------------------------------------------------- API
def verlauf_api(client, anzeige, umfang=None):
    return client("GET", f"/api/preisverlauf?anzeige={anzeige}" + (f"&umfang={umfang}" if umfang else ""))


def test_api_vertrag_inserat_und_fahrzeug(team_api, db):
    anna = anmelden(team_api, "Anna")
    db.speichere_treffer(treffer("p1", preis=38000), "Alkoven")
    status, d, _ = verlauf_api(anna, "p1")
    assert status == 200 and (d["anzeige"], d["umfang"], d["anzahl"]) == ("p1", "inserat", 2)
    assert d["inserat_id"] == inserat_id(db, "p1") and d["fahrzeug_id"] == db.fahrzeug_id_zu("p1")
    assert d["inserate"] == [{"anzeigen_id": "p1", "plattform": "kleinanzeigen"}]
    assert [(v["preis"], v["kanal"], v["aenderung"], v["vorher"], v["differenz"]) for v in d["verlauf"]] == [
        (40000, "suche", "erstpreis", None, None), (38000, "suche", "gesenkt", 40000, -2000)]
    assert set(d["verlauf"][0]) == {"zeitpunkt", "zeitpunkt_roh", "preis", "kanal", "plattform", "anzeigen_id", "inserat_id", "vorher", "aenderung",
                                    "differenz"}
    assert verlauf_api(anna, "p1", "inserat")[1] == d
    bestaetige(db, inserat_id(db, "p1"), inserat_id(db, "p2"))
    s, f, _ = verlauf_api(anna, "p2", "fahrzeug")
    assert s == 200 and f["umfang"] == "fahrzeug" and f["fahrzeug_id"] == d["fahrzeug_id"] and [i["anzeigen_id"] for i in f["inserate"]] == ["p1", "p2"]
    assert {(v["anzeigen_id"], v["preis"]) for v in f["verlauf"]} == {("p1", 40000), ("p1", 38000), ("p2", 40000)} and f["anzahl"] == 3
    assert [v["preis"] for v in verlauf_api(anna, "p2")[1]["verlauf"]] == [40000]          # Standard: nur das eigene Inserat


def test_api_fehler_und_rechte(team_api, db):
    anna, ben, hugo = (anmelden(team_api, n) for n in ("Anna", "Ben", "Hugo"))
    assert verlauf_api(ben, "p1")[0] == 200                                                # Mitarbeiter lesen
    s, d, _ = verlauf_api(hugo, "p1")
    assert s == 403 and d["grund"] == "recht"                                              # Standort-Zugang nie
    assert verlauf_api(hugo, "p1", "fahrzeug")[0] == 403
    assert verlauf_api(anna, "gibtsnicht")[0] == 404 and anna("GET", "/api/preisverlauf")[0] == 404
    s, d, _ = verlauf_api(anna, "p1", "alle")
    assert s == 400 and "umfang" in d["fehler"]
    from tests.test_handy import Client
    assert verlauf_api(Client(team_api.server_address[1]), "p1")[0] == 401                  # ohne Anmeldung
    assert anna("POST", "/api/preisverlauf", {"anzeige": "p1"})[0] in (400, 404, 405)      # nur lesen


def test_api_aendert_nichts(team_api, db):
    anna = anmelden(team_api, "Anna")
    db.con.commit()
    daten = {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in ("anzeigen", "inserate", "fahrzeuge", "beobachtungen", "preis_historie")}
    for umfang in ("inserat", "fahrzeug"):
        assert verlauf_api(anna, "p1", umfang)[0] == 200
    db.con.commit()
    assert daten == {t: sorted(map(tuple, db.con.execute(f"SELECT * FROM {t}"))) for t in daten}


def test_api_einzelplatz_ohne_nutzer(cfg, db, ads, importiert):
    srv = starte(cfg, db)
    try:
        s, d, _ = verlauf_api(lokal(srv), ads[0]["id"])
        assert s == 200 and d["anzahl"] == 1 and d["verlauf"][0]["preis"] == ads[0]["preis"] and d["verlauf"][0]["kanal"] == "suche"
    finally:
        srv.shutdown()
        srv.server_close()
