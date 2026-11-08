"""P3-03: Re-Import-Test (Abnahme Phase 3) – identische Inserate lassen sich über jeden Eingangskanal ohne Datenverlust erneut einlesen;
Preis- und Fahrzeughistorie bleiben erhalten.

Der Altbestand entsteht mit dem echten Code aus allen Kanälen (Suchlauf mit nachgebautem Abruf, gespeicherte Seiten, Text-Import, E-Mail,
Ereignis api) plus Team-Arbeit (Status, Notiz, Bearbeitung, Besichtigung, Ankauf, Dublettenentscheidung). Grenze: Seiten, Mails und Texte sind
nachgebaut (siehe tests/nachgebildet_mails.py, tests/seiten/); echte Kleinanzeigen- oder mobile.de-Daten beweist das nicht.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from tests.daten import BASIS, FakeAbruf, detail_html, such_html
from tests.nachgebildet_mails import KA_ABSENDER, MD_ABSENDER, nachgebildet_ka_html, nachgebildet_ka_text, nachgebildet_mail
from tests.nachgebildet_mails import KA_ANZEIGEN, nachgebildet_md_html, nachgebildet_md_text
from tests.test_seitenimport import KeinNetz, anzeige_url, detailseite
from wmscout import datenrechte
from wmscout.datenbank import Datenbank
from wmscout.dubletten import bestaetige, lehne_ab
from wmscout.eingang import TextEingang
from wmscout.ereignis_speicher import EreignisSpeicher
from wmscout.ereignisse import InseratEreignis
from wmscout.importer import Importer
from wmscout.preisverlauf import preisverlauf
from wmscout.quellen import Inserat
from wmscout.team import TeamSpeicher

SEITEN = BASIS / "tests" / "seiten"
# Beobachtungszeitpunkte rücken beim erneuten Sehen legitim vor – alles andere muss gleich bleiben
ZEITSPALTEN = {"anzeigen": {"zuletzt_gesehen"}, "inserate": {"zuletzt_gesehen", "zuletzt_bestaetigt"}}
MD_ID = "md-3900000099"
KANAELE = ("suche", "seiten", "text", "mail", "api")


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


# Laufprotokoll (P4-04, ADR-050): ein Betriebsprotokoll, das mit jedem Lauf und Import wächst – kein Datenbestand (eigene Tests in test_statusseite)
BETRIEBSPROTOKOLLE = {"suchlaeufe"}


def tabellen(db: Datenbank) -> list[str]:
    """Alle Tabellen der Datenbank (aus sqlite_master) außer dem Laufprotokoll: auch Sitzungen, Audit, Kalkulationen usw. dürfen sich nicht
    ändern."""
    return sorted(r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                  if r[0] not in BETRIEBSPROTOKOLLE)


def dump(db: Datenbank, ohne: dict[str, set] | None = None) -> dict[str, list]:
    """Alle Zeilen aller Tabellen (nur ohne die Zeitspalten, die beim erneuten Sehen vorrücken, und ``ohne``), sortiert."""
    db.con.commit()
    erg = {}
    for t in tabellen(db):
        zeilen = db.con.execute(f"SELECT * FROM {t}").fetchall()
        aus = ZEITSPALTEN.get(t, set()) | (ohne or {}).get(t, set())
        erg[t] = sorted((tuple(v for k, v in zip(z.keys(), z, strict=True) if k not in aus) for z in zeilen), key=repr)
    return erg


def zaehler(db: Datenbank) -> dict[str, int]:
    return {t: db.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabellen(db)}


def historie(db: Datenbank, anzeigen_id: str) -> list[tuple]:
    return [(p["preis"], p["kanal"]) for p in preisverlauf(db, anzeigen_id)]


# ---------------------------------------------------------------- Rohdaten je Kanal (aus denselben Anzeigen)
def ka_text(a: dict, preis: int | None = None) -> str:
    return (f"Kleinanzeigen\n{a['titel']} Teilintegrierter Wohnmobil\n{preis or a['preis']:,} € VB".replace(",", ".") +
            f"\n{a['plz']} {a['ort']}\nDetails\nKilometerstand {a['km']:,} km\nErstzulassung 0{a['monat']}/{a['ez']}\n".replace(",", ".") +
            f"Beschreibung\n{a['lang']}\nAnzeigen-ID: {a['id']}\n")


def mail_bytes(anzeigen: list[dict], datum: datetime | None = None) -> bytes:
    return nachgebildet_mail(KA_ABSENDER, "Neue Treffer", nachgebildet_ka_html(anzeigen), nachgebildet_ka_text(anzeigen),
                             datum=format_datetime(datum or jetzt())).as_bytes()


def md_mail_bytes(datum: datetime | None = None) -> bytes:
    return nachgebildet_mail(MD_ABSENDER, "Neue Treffer", nachgebildet_md_html(), nachgebildet_md_text(), datum=format_datetime(datum or jetzt())).as_bytes()


def ereignis(preis=33000, ereignis_id=None, typ="neu", zeit: datetime | None = None, anzeigen_id=MD_ID, plattform="mobile.de",
              ad: dict | None = None) -> InseratEreignis:
    """``ad``: eine Anzeige aus ``baue_ads`` – URL und Titel stammen dann wie bei der Suche von ihr."""
    url, titel = (anzeige_url(ad), ad["titel"]) if ad else (f"https://beispiel.invalid/{anzeigen_id}", "Knaus Sky TI")
    inserat = Inserat(quelle=plattform, anzeigen_id=anzeigen_id, url=url, titel=titel, preis=preis, ez_jahr=ad["ez"] if ad else 2018,
                      km=ad["km"] if ad else 70000)
    return InseratEreignis(plattform, anzeigen_id, typ, "api", zeit or jetzt(), inserat, ereignis_id)


class Welt:
    """Eine Datenbank samt Import-Ordnern und den Wegen, Daten über jeden Kanal einzulesen. Jede Methode gibt (neu, preis, bekannt) zurück."""

    def __init__(self, cfg, db, tmp, ads):
        self.cfg, self.db, self.tmp, self.ads = cfg, db, tmp, ads
        self.seiten = tmp / "seiten"
        self.mails = tmp / "mails"
        self.seiten.mkdir(exist_ok=True)
        self.mails.mkdir(exist_ok=True)
        cfg["import"] = {"ordner": str(self.seiten)}
        cfg["eingaenge"] = {"email": {"aktiv": True}}
        cfg["suchen"] = [{"name": "Teilintegrierter", "url": cfg["suchen"][0]["url"]}]
        self.zaehler_mail = 0
        self.mail_datum = jetzt() - timedelta(hours=1)
        for kennung in ("mobile.de", "kleinanzeigen"):       # Ereigniseingang nur mit Quellenfreigabe (die Testquelle ist im Code freigegeben, conftest)
            db.con.execute("INSERT OR REPLACE INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES (?, 'api', 1, 1)", (kennung,))
        db.con.commit()

    @staticmethod
    def _tripel(stat: dict) -> tuple[int, int, int]:
        return stat["neu"], stat["preis"], stat["bekannt"]

    def suche(self, ads=None, preise: dict | None = None) -> tuple:
        ads = [{**a, "preis": (preise or {}).get(a["id"], a["preis"])} for a in (ads if ads is not None else self.ads)]
        return self._tripel(Importer(self.cfg, self.db, abruf=FakeAbruf(ads)).lauf(self.cfg["suchen"]))

    def seitenimport(self, ads=None, preise: dict | None = None, mit_testseiten=True) -> tuple:
        """Suchseite + Anzeigenseite je Anzeige (und die sechs echten Testseiten). Jede Datei wandert danach nach eingelesen/."""
        ads = [{**a, "preis": (preise or {}).get(a["id"], a["preis"])} for a in (ads if ads is not None else self.ads[:6])]
        (self.seiten / "suche.html").write_text(such_html(ads), encoding="utf-8")
        for a in ads:
            (self.seiten / f"detail_{a['id']}.html").write_text(detailseite(a), encoding="utf-8")
        if mit_testseiten:
            for pfad in sorted(SEITEN.glob("*/*.html")):
                shutil.copy(pfad, self.seiten / f"{pfad.parent.name}_{pfad.name}")
        return self._tripel(Importer(self.cfg, self.db, abruf=KeinNetz()).importiere_seiten(self.seiten))

    def text(self, a: dict, preis: int | None = None) -> tuple:
        eingang = TextEingang()
        lesung = eingang.lese(TextEingang.rohdaten(anzeige_url(a), ka_text(a, preis), "privat", jetzt()))
        return self._tripel(Importer(self.cfg, self.db, abruf=KeinNetz()).importiere(lesung, eingang.kanal))

    def mail(self, anzeigen: list[dict] | None = None, md=True, datum: datetime | None = None) -> tuple:
        anzeigen = anzeigen if anzeigen is not None else [*KA_ANZEIGEN, self.ads[1]]
        self.zaehler_mail += 1
        (self.mails / f"ka{self.zaehler_mail}.eml").write_bytes(mail_bytes(anzeigen, datum))
        if md:
            (self.mails / f"md{self.zaehler_mail}.eml").write_bytes(md_mail_bytes(datum))
        return self._tripel(Importer(self.cfg, self.db).importiere_mails(self.mails))

    def api(self, preis=33000, ereignis_id=None, typ="neu", zeit: datetime | None = None, anzeigen_id=MD_ID, plattform="mobile.de",
            ad: dict | None = None) -> str:
        return EreignisSpeicher(self.db).verarbeite(ereignis(preis, ereignis_id, typ, zeit, anzeigen_id, plattform, ad))

    def kanal(self, name: str) -> tuple | str:
        """Der Kanal mit denselben Daten wie beim Aufbau des Altbestands."""
        return {"suche": self.suche, "seiten": self.seitenimport, "text": lambda: self.text(self.ads[2]),
                "mail": lambda: self.mail(datum=self.mail_datum), "api": lambda: self.api(ereignis_id="E1")}[name]()


@pytest.fixture
def welt(cfg, db, ads, tmp_path):
    return Welt(cfg, db, tmp_path, ads)


@pytest.fixture
def alt(welt, tmp_path):
    """Altbestand aus allen Kanälen plus Team-Arbeit; Rückgabe: die Welt (Zeilenzahlen und Stand stehen in ``welt.stand``)."""
    db, ads = welt.db, welt.ads
    welt.suche()                                             # 60 Inserate, Detailseiten nachgeladen
    welt.seitenimport()                                      # ads[:6] (Suchseite + Anzeigenseite) + 6 echte Testseiten (Kleinanzeigen, mobile.de)
    welt.text(ads[2])                                        # dieselbe Anzeige wie aus der Suche
    welt.mail(datum=welt.mail_datum)                         # 3 neue Kleinanzeigen + 2 mobile.de + ads[1] (schon bekannt)
    assert welt.api(ereignis_id="E1") == "neu"               # mobile.de-Inserat nur über den Ereigniseingang
    team = TeamSpeicher(db, tmp_path / "fotos")
    anna, ben = team.nutzer_anlegen("Anna", "sicher1234", "inhaber"), team.nutzer_anlegen("Ben", "sicher1234", "mitarbeiter")
    db.setze_status(ads[0]["id"], "kontaktiert", notiz="Rückruf Mittwoch", text="Guten Tag, ...", betrag=21000, nutzer_id=anna)
    db.setze_status(ads[3]["id"], "verhandlung", notiz="will 1.000 € runter", nutzer_id=ben)
    db.setze_notiz(ads[4]["id"], "Standort prüfen")
    db.setze_status(ads[5]["id"], "gekauft", nutzer_id=anna)
    bid = team.besichtigung_anlegen(ads[3]["id"], {"fahrzeug": "Knaus", "titel": ads[3]["titel"]}, "2026-10-30T10:00", "Musterweg 1", ben, anna)
    bid2 = team.besichtigung_anlegen(ads[5]["id"], {"fahrzeug": "Hymer"}, None, None, anna, anna)
    db.con.execute("INSERT INTO ankaeufe (referenz, herkunft, anzeige_id, besichtigung_id, kaufpreis, plan_json, erstellt_am) "
                   "VALUES ('AK-TEST-1', 'anzeige', ?, ?, 24000, '{}', '2026-10-01T10:00:00')", (ads[5]["id"], bid2))
    db.con.commit()
    ia = {a["id"]: db.con.execute("SELECT id FROM inserate WHERE anzeigen_id=?", (a["id"],)).fetchone()[0] for a in ads[10:14]}
    bestaetige(db, ia[ads[10]["id"]], ia[ads[11]["id"]], anna)               # zwei Inserate sind dasselbe Fahrzeug
    lehne_ab(db, ia[ads[12]["id"]], ia[ads[13]["id"]], anna)                  # ... zwei andere ausdrücklich nicht
    welt.stand = {"besichtigung": bid, "ia": ia, "anna": anna, "ben": ben}
    return welt


# ---------------------------------------------------------------- a) identische Daten über jeden Kanal erneut einlesen
def test_altbestand_ist_vielfaeltig(alt):
    """Vorbedingung: der Altbestand enthält wirklich alle Kanäle, Team-Arbeit und eine bestätigte Dublette."""
    db = alt.db
    kanaele = {r[0] for r in db.con.execute("SELECT kanal FROM beobachtungen")}
    assert {"suche", "manuell", "email", "api"} <= kanaele
    z = zaehler(db)
    assert z["anzeigen"] == z["inserate"] and z["anzeigen"] > 70 and z["besichtigungen"] == 2 and z["ankaeufe"] == 1
    assert z["dubletten_entscheidungen"] == 2 and z["fahrzeug_zuordnungen"] == 1 and z["fahrzeuge"] == z["inserate"]      # ein Fahrzeug bleibt ohne Inserat
    assert db.con.execute("SELECT COUNT(DISTINCT fahrzeug_id) FROM inserate").fetchone()[0] == z["inserate"] - 1


@pytest.mark.parametrize("kanal", KANAELE)
def test_gleiche_daten_erneut_ueber_denselben_kanal(alt, kanal):
    db = alt.db
    vorher, n = dump(db), zaehler(db)
    erg = alt.kanal(kanal)
    assert dump(db) == vorher and zaehler(db) == n                       # keine Zeile mehr, keine verändert (Status, Notiz, Besichtigung, Ankauf, ...)
    if kanal == "api":
        assert erg == "bekannt"
    else:
        assert erg[0] == 0 and erg[1] == 0 and erg[2] > 0                # nichts neu, keine Preissenkung, alles bekannt


@pytest.mark.parametrize("kanal", KANAELE)
def test_gleiche_daten_ueber_einen_anderen_kanal(alt, kanal):
    """Dieselben Anzeigen, die ein anderer Kanal schon geliefert hat: kein Phantominserat, Historie unverändert."""
    db, ads = alt.db, alt.ads
    # Text-Import mit der Angabe „privat“: ein neuer Beleg – nur die Herkunft der Anbieterart wird stärker (P3-05), sonst bleibt alles
    ohne = {"anzeigen": {"anbieter_herkunft"}} if kanal == "seiten" else None
    vorher, n = dump(db, ohne), zaehler(db)
    if kanal == "suche":
        erg = alt.seitenimport(mit_testseiten=False)
    elif kanal == "seiten":
        erg = alt.text(ads[7])
    elif kanal == "text":
        erg = alt.mail([ads[8], ads[9]], md=False, datum=alt.mail_datum)
    elif kanal == "mail":
        erg = alt.suche(ads[:5])
    else:
        erg = alt.api(ereignis_id="E2-anderes-ereignis")                 # neue Ereignis-ID, gleicher Inhalt
        assert erg == "bekannt"
    assert dump(db, ohne) == vorher and zaehler(db) == n
    if kanal == "seiten":
        assert db.con.execute("SELECT gewerblich, anbieter_herkunft FROM anzeigen WHERE id=?", (ads[7]["id"],)).fetchone()[:] == (0, "nutzer")
    if kanal != "api":
        assert erg[0] == 0 and erg[1] == 0


def test_alle_kanaele_zweimal_hintereinander(alt):
    db = alt.db
    vorher = dump(db)
    for _ in range(2):
        for kanal in KANAELE:
            alt.kanal(kanal)
    assert dump(db) == vorher


def test_historie_bleibt_vollstaendig_und_ohne_doppelte(alt):
    """Jedes Inserat hat genau einen ersten Preis; der letzte Eintrag trägt den aktuellen Preis; nichts doppelt."""
    db = alt.db
    for kanal in KANAELE:
        alt.kanal(kanal)
    doppelt = db.con.execute("SELECT COUNT(*) FROM (SELECT inserat_id, zeitpunkt, preis, kanal FROM preis_historie "
                             "GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1)").fetchone()[0]
    assert doppelt == 0
    ohne = db.con.execute("SELECT COUNT(*) FROM inserate WHERE preis IS NOT NULL AND id NOT IN (SELECT inserat_id FROM preis_historie)").fetchone()[0]
    assert ohne == 0
    falsch = db.con.execute("SELECT COUNT(*) FROM inserate i WHERE i.preis IS NOT NULL AND i.preis != "
                            "(SELECT preis FROM preis_historie p WHERE p.inserat_id = i.id ORDER BY p.id DESC LIMIT 1)").fetchone()[0]
    assert falsch == 0
    for i in db.con.execute("SELECT anzeigen_id, preis FROM inserate WHERE preis IS NOT NULL").fetchall():     # chronologisch: letzter Preis = aktueller
        assert preisverlauf(db, i["anzeigen_id"])[-1]["preis"] == i["preis"], i["anzeigen_id"]


# ---------------------------------------------------------------- b) Reihenfolge und Kanalmischung
REIHENFOLGEN = {"ssTM": ("suche", "seiten", "text", "mail"), "Mtss": ("mail", "text", "seiten", "suche"), "tmSs": ("text", "mail", "suche", "seiten"),
                "mStS": ("mail", "suche", "text", "seiten"), "sMts": ("seiten", "mail", "text", "suche"), "tSmS": ("text", "suche", "mail", "seiten")}


def spiele(welt: Welt, reihenfolge, anzeigen: list[dict]):
    for kanal in reihenfolge:
        if kanal == "suche":
            welt.suche(anzeigen)
        elif kanal == "seiten":
            welt.seitenimport(anzeigen, mit_testseiten=False)
        elif kanal == "text":
            for a in anzeigen:
                welt.text(a)
        else:
            welt.mail(anzeigen, md=False, datum=welt.mail_datum)


def endstand(db: Datenbank) -> dict:
    """Der fachliche Endstand ohne Zeilennummern und Zeitpunkte (die hängen von der Reihenfolge des Eintragens ab)."""
    db.con.commit()
    anzeigen = {z["id"]: tuple(v for k, v in zip(z.keys(), z, strict=True) if k not in ("erstmals_gesehen", "zuletzt_gesehen"))
                for z in db.con.execute("SELECT * FROM anzeigen")}
    inserate = {(z["plattform"], z["anzeigen_id"]): (z["url"], z["titel"], z["preis"], z["verfuegbarkeit"]) for z in db.con.execute("SELECT * FROM inserate")}
    preise = {z["anzeigen_id"]: [p[0] for p in db.con.execute("SELECT preis FROM preis_historie WHERE inserat_id=? ORDER BY id", (z["id"],))]
              for z in db.con.execute("SELECT id, anzeigen_id FROM inserate")}
    return {"anzeigen": anzeigen, "inserate": inserate, "preise": preise, "fahrzeuge": db.con.execute("SELECT COUNT(*) FROM fahrzeuge").fetchone()[0]}


@pytest.mark.parametrize("reihenfolge", REIHENFOLGEN.values(), ids=REIHENFOLGEN)
def test_reihenfolge_der_kanaele_aendert_den_endstand_nicht(cfg, ads, tmp_path, reihenfolge):
    """Dieselben vier Anzeigen über Suche, Seiten, Text und Mail in beliebiger Reihenfolge: gleicher Endstand (Zeilen, Felder, Preishistorie).
    Nicht gleich bleibt die Zahl der Beobachtungen: ein Kanal, der zuerst nur Titel und Adresse in Kurzform kannte, wird vom reicheren später
    als „geaendert“ vermerkt – das Beobachtungsprotokoll hält fest, was wann gesehen wurde."""
    S = ads[20:24]
    stand = {}
    for name, reihe in (("referenz", REIHENFOLGEN["ssTM"]), ("probe", reihenfolge)):
        ordner = tmp_path / name
        ordner.mkdir()
        w = Welt(cfg, Datenbank(str(ordner / "x.sqlite")), ordner, ads)
        spiele(w, reihe, S)
        stand[name] = endstand(w.db)
        assert w.db.con.execute("SELECT COUNT(*) FROM inserate WHERE id NOT IN (SELECT inserat_id FROM beobachtungen)").fetchone()[0] == 0
    assert stand["probe"] == stand["referenz"]
    assert all(len(p) == 1 for p in stand["probe"]["preise"].values())      # gleicher Preis aus vier Kanälen: genau ein Historieneintrag je Inserat


# ---------------------------------------------------------------- c) Preisänderungen über verschiedene Kanäle
def test_preisaenderungen_ueber_alle_kanaele_vollstaendig_und_chronologisch(welt):
    a = {**welt.ads[30]}
    p0 = a["preis"]
    welt.suche([a])
    welt.seitenimport([{**a, "preis": p0 - 2000}], mit_testseiten=False)                 # Senkung
    welt.text(a, p0 - 500)                                                              # Erhöhung
    welt.mail([{**a, "preis": p0 + 1500}], md=False)                                    # Erhöhung (Mail von jetzt)
    assert welt.api(p0 - 3000, "E-Senkung", "geaendert", anzeigen_id=a["id"], plattform="kleinanzeigen", ad=a) == "geaendert"   # Senkung
    welt.suche([a])                                                                     # zurück auf den Ausgangspreis: Erhöhung
    erwartet = [(p0, "suche"), (p0 - 2000, "manuell"), (p0 - 500, "manuell"), (p0 + 1500, "email"), (p0 - 3000, "api"), (p0, "suche")]
    verlauf = preisverlauf(welt.db, a["id"])
    assert [(v["preis"], v["kanal"]) for v in verlauf] == erwartet
    assert [v["aenderung"] for v in verlauf] == ["erstpreis", "gesenkt", "erhoeht", "erhoeht", "gesenkt", "erhoeht"]
    zeiten = [v["zeitpunkt"] for v in verlauf]
    assert zeiten == sorted(zeiten) and None not in zeiten
    assert welt.db.con.execute("SELECT preis FROM anzeigen WHERE id=?", (a["id"],)).fetchone()[0] == p0
    assert [r[0] for r in welt.db.con.execute("SELECT preis FROM inserate WHERE anzeigen_id=?", (a["id"],))] == [p0]
    # derselbe Endstand noch einmal über jeden Kanal: nichts kommt hinzu
    vorher = dump(welt.db)
    welt.suche([a])
    welt.seitenimport([a], mit_testseiten=False)
    welt.text(a)
    welt.mail([a], md=False)
    assert welt.api(p0, "E-neu", "geaendert", anzeigen_id=a["id"], plattform="kleinanzeigen", ad=a) == "bekannt"
    assert dump(welt.db) == vorher and historie(welt.db, a["id"]) == erwartet


def test_aeltere_mail_aendert_den_neueren_preis_nicht(welt):
    a = {**welt.ads[31]}
    welt.suche([a])
    vorher = dump(welt.db)
    erg = welt.mail([{**a, "preis": a["preis"] + 999}], md=False, datum=jetzt() - timedelta(hours=3))
    assert erg == (0, 0, 1)
    assert dump(welt.db) == vorher and historie(welt.db, a["id"]) == [(a["preis"], "suche")]


def test_mail_haelt_den_zeitpunkt_der_mail_fest(welt):
    """Die Beobachtung einer Mail trägt das Datum der Mail, nicht den Zeitpunkt des Einlesens – sonst wäre der Preisverlauf nach einem
    späten Einlesen falsch geordnet."""
    a = {**welt.ads[32]}
    datum = (jetzt() - timedelta(days=2)).replace(microsecond=0)
    welt.mail([a], md=False, datum=datum)
    welt.suche([{**a, "preis": a["preis"] - 1000}])
    beob = welt.db.con.execute("SELECT b.kanal, b.zeitpunkt FROM beobachtungen b JOIN inserate i ON i.id=b.inserat_id WHERE i.anzeigen_id=? ORDER BY b.id",
                               (a["id"],)).fetchall()
    assert [b["kanal"] for b in beob] == ["email", "suche"] and datetime.fromisoformat(beob[0]["zeitpunkt"]) == datum
    verlauf = preisverlauf(welt.db, a["id"])
    assert [(v["kanal"], v["preis"]) for v in verlauf] == [("email", a["preis"]), ("suche", a["preis"] - 1000)]
    assert datetime.fromisoformat(verlauf[0]["zeitpunkt"]) == datum and datetime.fromisoformat(verlauf[1]["zeitpunkt"]) > datum + timedelta(days=1)


def test_preis_der_detailseite_im_netzabruf_kommt_in_die_historie(welt):
    """Der Detailabruf nach dem Suchlauf (Importer.details) nennt einen anderen Preis als die Trefferliste: Preissenkung und Verlauf (Kanal detail)."""
    a = {**welt.ads[33]}
    welt.suche([a])
    welt.db.speichere_details(a["id"], {"preis": a["preis"] - 1500, "details": {}})
    z = welt.db.con.execute("SELECT preis, preis_vorher FROM anzeigen WHERE id=?", (a["id"],)).fetchone()
    assert (z["preis"], z["preis_vorher"]) == (a["preis"] - 1500, a["preis"])
    assert historie(welt.db, a["id"]) == [(a["preis"], "suche"), (a["preis"] - 1500, "detail")]
    assert welt.db.con.execute("SELECT preis FROM inserate WHERE anzeigen_id=?", (a["id"],)).fetchone()[0] == a["preis"] - 1500
    welt.db.speichere_details(a["id"], {"preis": a["preis"] - 1500, "details": {}})               # gleicher Preis: nichts Neues
    assert len(historie(welt.db, a["id"])) == 2


def test_detailpreis_null_ist_keine_preissenkung(welt):
    a = {**welt.ads[34]}
    welt.suche([a])
    welt.db.speichere_details(a["id"], {"preis": 0, "details": {}})
    z = welt.db.con.execute("SELECT preis, preis_vorher FROM anzeigen WHERE id=?", (a["id"],)).fetchone()
    assert z["preis_vorher"] is None and z["preis"] == 0


def test_fehler_beim_detailpreis_rollt_alles_zurueck(welt, monkeypatch):
    """Scheitert das Spiegeln (z. B. „database is locked“), bleibt nichts Halbes zurück: weder ``preis_vorher`` noch Preis noch Details,
    und es bleibt keine offene Transaktion auf der gemeinsamen Verbindung."""
    db, a = welt.db, {**welt.ads[35]}
    welt.suche([a])
    vorher = dump(db)

    def kaputt(*args, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "spiegle_inserat", kaputt)
    with pytest.raises(sqlite3.OperationalError):
        db.speichere_details(a["id"], {"preis": a["preis"] - 1000, "titel": "Neuer Titel", "details": {"Art": "Alkoven"}})
    assert not db.con.in_transaction and dump(db) == vorher


def test_mail_zwischen_suche_und_detailabruf_setzt_den_preis_nicht_zurueck(welt):
    """Suche vor 3 h (44.600), Detailabruf jetzt (42.600), Mail von vor 1 h mit dem alten Preis: der Detailabruf ist die jüngere Beobachtung."""
    db, a = welt.db, {**welt.ads[43]}
    alt_preis, neu_preis = a["preis"], a["preis"] - 2000
    welt.suche([a])
    vor3h = jetzt() - timedelta(hours=3)
    # die Suche gedanklich vor drei Stunden: alle Zeitpunkte dieses Inserats zurückdatieren
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen=? WHERE id=?", ((datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds"), a["id"]))
    db.con.execute("UPDATE preis_historie SET zeitpunkt=? WHERE inserat_id IN (SELECT id FROM inserate WHERE anzeigen_id=?)",
                   (vor3h.isoformat(timespec="seconds"), a["id"]))
    db.con.commit()
    db.speichere_details(a["id"], {"preis": neu_preis, "details": {}})
    assert welt.mail([a], md=False, datum=jetzt() - timedelta(hours=1)) == (0, 0, 1)
    assert db.con.execute("SELECT preis FROM anzeigen WHERE id=?", (a["id"],)).fetchone()[0] == neu_preis
    verlauf = preisverlauf(db, a["id"])
    assert [(v["preis"], v["kanal"]) for v in verlauf] == [(alt_preis, "suche"), (neu_preis, "detail")]
    assert verlauf[-1]["preis"] == db.con.execute("SELECT preis FROM inserate WHERE anzeigen_id=?", (a["id"],)).fetchone()[0]


def test_mail_aelter_als_der_preisverlauf_aendert_den_preis_nicht(welt):
    """Auch wenn ``zuletzt_gesehen`` es nicht verrät (hier zurückgesetzt): der jüngste Eintrag im Preisverlauf schützt vor einer älteren Mail."""
    db, a = welt.db, {**welt.ads[47]}
    welt.suche([a])
    db.con.execute("UPDATE anzeigen SET zuletzt_gesehen='2000-01-01T00:00:00' WHERE id=?", (a["id"],))
    db.con.commit()
    assert welt.mail([{**a, "preis": a["preis"] + 700}], md=False, datum=jetzt() - timedelta(hours=1)) == (0, 0, 1)
    assert historie(db, a["id"]) == [(a["preis"], "suche")]


def test_unplausibel_altes_maildatum_zaehlt_als_einlesezeit(welt):
    """Ein Mail-Datum von vor über einem Jahr (Uhr falsch, weitergeleitete Alt-Mail) ordnet die Beobachtung nicht in die ferne Vergangenheit:
    Zeitpunkt = Einlesen, mit Hinweis."""
    db, a = welt.db, {**welt.ads[46]}
    (welt.mails / "alt.eml").write_bytes(mail_bytes([a], jetzt() - timedelta(days=800)))
    stat = Importer(welt.cfg, db).importiere_mails(welt.mails)
    assert stat["neu"] == 1 and any("über 365 Tage" in f for f in stat["fehler"])
    v = preisverlauf(db, a["id"])
    assert len(v) == 1 and abs(datetime.fromisoformat(v[0]["zeitpunkt"]) - jetzt()) < timedelta(minutes=2)
    beob = db.con.execute("SELECT b.zeitpunkt FROM beobachtungen b JOIN inserate i ON i.id=b.inserat_id WHERE i.anzeigen_id=?", (a["id"],)).fetchone()[0]
    assert abs(datetime.fromisoformat(beob) - jetzt()) < timedelta(minutes=2)
    # eine bekannte Anzeige: die alte Mail ändert den Preis nicht
    welt.suche([{**a, "preis": a["preis"] - 300}])
    (welt.mails / "alt2.eml").write_bytes(mail_bytes([a], jetzt() - timedelta(days=800)))
    assert Importer(welt.cfg, db).importiere_mails(welt.mails)["preis"] == 0
    assert [p for p, _ in historie(db, a["id"])] == [a["preis"], a["preis"] - 300]


class AbweichenderAbruf(FakeAbruf):
    """Die Anzeigenseite nennt einen anderen Preis als die Trefferliste (``abweichung`` € weniger)."""

    def __init__(self, ads, abweichung):
        super().__init__(ads)
        self.abweichung = abweichung

    def hole(self, url):
        seite = super().hole(url)
        if "/s-anzeige/" in url:
            ad = self.ads[url.rsplit("/", 1)[1].split("-")[0]]
            return detail_html({**ad, "preis": ad["preis"] - self.abweichung})
        return seite


def test_reimport_ueber_den_abrufweg_mit_abweichendem_detailpreis(welt):
    """Echter Weg: Suchlauf, danach ``Importer.details`` (Anzeigenseite mit anderem Preis). Der Detailpreis steht im Verlauf; ein weiterer Lauf
    bringt den Listenpreis als neue Beobachtung, ab dem dritten Lauf ändert sich nichts mehr (Detailseiten werden nicht erneut abgerufen)."""
    db, a = welt.db, {**welt.ads[36]}
    abruf = AbweichenderAbruf([a], 1500)
    lauf = lambda: Importer(welt.cfg, db, abruf=abruf).lauf(welt.cfg["suchen"])      # noqa: E731
    erst = lauf()
    assert (erst["neu"], erst["details"]) == (1, 1)
    p = a["preis"]
    assert historie(db, a["id"]) == [(p, "suche"), (p - 1500, "detail")]
    assert db.con.execute("SELECT preis, preis_vorher FROM anzeigen WHERE id=?", (a["id"],)).fetchone()[:] == (p - 1500, p)
    lauf()                                                 # der Listenpreis ist die neue Beobachtung
    assert historie(db, a["id"]) == [(p, "suche"), (p - 1500, "detail"), (p, "suche")]
    stand = dump(db)
    zweit = lauf()
    assert dump(db) == stand and zweit["neu"] == 0 and zweit["details"] == 0
    assert preisverlauf(db, a["id"])[-1]["preis"] == db.con.execute("SELECT preis FROM inserate WHERE anzeigen_id=?", (a["id"],)).fetchone()[0]


# ---------------------------------------------------------------- d) nach einer Dubletten-Zusammenführung
def test_reimport_nach_zusammenfuehrung_behaelt_gruppe_und_historie(alt):
    db, ads = alt.db, alt.ads
    a10, a11 = ads[10], ads[11]
    fahrzeug = db.con.execute("SELECT fahrzeug_id FROM inserate WHERE anzeigen_id IN (?, ?)", (a10["id"], a11["id"])).fetchall()
    assert fahrzeug[0][0] == fahrzeug[1][0]
    vorher, n = dump(db), zaehler(db)
    alt.suche()
    alt.seitenimport()
    assert dump(db) == vorher and zaehler(db) == n
    # nach dem Zusammenführen sinkt ein Preis: die Historie liegt weiter am Inserat, ist über das Fahrzeug aber gemeinsam lesbar
    alt.suche(preise={a11["id"]: a11["preis"] - 1200})
    z = zaehler(db)
    assert z["fahrzeuge"] == n["fahrzeuge"] and z["inserate"] == n["inserate"] and z["fahrzeug_zuordnungen"] == 1
    assert z["preis_historie"] == n["preis_historie"] + 1 and z["dubletten_entscheidungen"] == 2
    fid = fahrzeug[0][0]
    gemeinsam = preisverlauf(db, fahrzeug_id=fid)
    assert {(v["anzeigen_id"], v["preis"]) for v in gemeinsam} == {(a10["id"], a10["preis"]), (a11["id"], a11["preis"]), (a11["id"], a11["preis"] - 1200)}
    assert [(v["preis"], v["aenderung"]) for v in preisverlauf(db, a11["id"])] == [(a11["preis"], "erstpreis"), (a11["preis"] - 1200, "gesenkt")]
    nachher = dump(db)
    alt.suche(preise={a11["id"]: a11["preis"] - 1200})
    assert dump(db) == nachher
    assert db.con.execute("SELECT fahrzeug_id FROM inserate WHERE anzeigen_id=?", (a10["id"],)).fetchone()[0] == fid


# ---------------------------------------------------------------- e) nach der Anonymisierung (Datenrechte)
DETAIL_ID = "3900000010"             # Testseite tests/seiten/kleinanzeigen/detailseite.html: Profilname „Max Muster“ landet in details_json


def _zeile(db, ad_id):
    return db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()


@pytest.fixture
def anonymisiert(alt, tmp_path):
    db = alt.db
    assert "Max Muster" in _zeile(db, DETAIL_ID)["details_json"]
    db.setze_notiz(DETAIL_ID, "Herr Muster ruft abends an")
    db.setze_status(DETAIL_ID, "kontaktiert", text="Hallo Max Muster, ...", betrag=1000)
    datenrechte.inserat_anonymisieren(db, tmp_path / "ausgabe", DETAIL_ID)
    z = _zeile(db, DETAIL_ID)
    assert "Max Muster" not in z["details_json"] and "anonymisiert_am" in z["details_json"] and z["notiz"] is None and "Max Muster" not in z["anschreiben_text"]
    return alt


@pytest.mark.parametrize("kanal", ["suche", "text", "mail", "api"])
def test_reimport_stellt_nach_anonymisierung_nichts_wieder_her(anonymisiert, kanal):
    """Suche, Text, Mail und Ereignis bringen weder Namen noch Notiz noch Anschreibentext zurück; die Zeile bleibt, wie sie ist."""
    db = anonymisiert.db
    vorher, n = dump(db), zaehler(db)
    anonymisiert.kanal(kanal)
    assert dump(db) == vorher and zaehler(db) == n


def test_gespeicherte_anzeigenseite_stellt_nach_anonymisierung_den_namen_nicht_wieder_her(anonymisiert, tmp_path):
    """Dieselbe gespeicherte Anzeigenseite (mit Profilname) erneut eingelesen: Name kommt nicht zurück, ``anonymisiert_am`` bleibt, Notiz und
    geschwärzter Anschreibentext bleiben. Fahrzeugmerkmale und Preis werden weiter aktualisiert (Marktbeobachtung), die Historie wächst."""
    db = anonymisiert.db
    marke = json.loads(_zeile(db, DETAIL_ID)["details_json"])["anonymisiert_am"]
    vorher = historie(db, DETAIL_ID)
    seite = (SEITEN / "kleinanzeigen" / "detailseite.html").read_text(encoding="utf-8")
    assert "47.300 € VB" in seite and "41.200 km" in seite and "Max Muster" in seite
    ordner = tmp_path / "nur_detail"
    ordner.mkdir()
    (ordner / "detail.html").write_text(seite.replace("47.300 € VB", "45.000 € VB").replace("41.200 km", "43.000 km"), encoding="utf-8")
    stat = Importer(anonymisiert.cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["detailseiten"] == 1 and stat["fehler"] == []
    z = _zeile(db, DETAIL_ID)
    details = json.loads(z["details_json"])
    assert "verkaeufer_name" not in details and details["anonymisiert_am"] == marke and "Max Muster" not in z["details_json"]
    assert details["Kilometerstand"] == "43.000 km" and z["preis"] == 45000            # Merkmale und Preis werden weiter aktualisiert
    assert historie(db, DETAIL_ID) == [*vorher, (45000, "manuell")]
    assert z["notiz"] is None and "Max Muster" not in z["anschreiben_text"] and z["status"] == "kontaktiert"
    assert DETAIL_ID not in datenrechte.inserate_nach_frist(db, tmp_path / "ausgabe", 1, jetzt=datetime.now() + timedelta(days=90))     # nichts mehr zu tun


def test_ohne_anonymisierung_wird_der_profilname_gespeichert(welt):
    """Gegenstück: nur anonymisierte Zeilen behalten den Namen draußen – sonst bleibt das Einlesen wie es war."""
    ordner = welt.tmp / "nur_detail"
    ordner.mkdir()
    shutil.copy(SEITEN / "kleinanzeigen" / "detailseite.html", ordner / "detail.html")
    Importer(welt.cfg, welt.db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert json.loads(_zeile(welt.db, DETAIL_ID)["details_json"])["verkaeufer_name"] == "Max Muster"
