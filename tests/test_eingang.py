"""Eingang-Schnittstelle (P2-00, ADR-035): Eingang.lese → Lesung → Importer.importiere – rein lesen, einheitlich schreiben."""
import socket
from datetime import datetime, timezone

import pytest

from tests.daten import such_html
from tests.test_seitenimport import canonical, detailseite, suchseite
from wmscout import domaene, quellen
from wmscout.datenbank import BESTAETIGT, VORLAEUFIG, import_art
from wmscout.eingang import Eingang, Lesung, Rohdaten, SeitenEingang, SuchseitenArt
from wmscout.eingang.seiten import QUELLE
from wmscout.importer import Importer
from wmscout.quellen import mobilede
from wmscout.quellen.basis import Inserat

JETZT = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


def roh(html: str, name="seite.html") -> Rohdaten:
    return Rohdaten(html.encode("utf-8"), name, JETZT)


def zaehle(db, tabelle):
    return db.con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


def test_seiteneingang_erfuellt_vertrag():
    eingang = SeitenEingang()
    assert isinstance(eingang, Eingang)
    assert (eingang.kennung, eingang.kanal) == ("seiten", "manuell")
    assert eingang.kanal in domaene.PUSH_KANAELE


def test_lese_braucht_weder_netz_noch_datenbank(ads, monkeypatch):
    def gesperrt(*a, **k):
        raise AssertionError("Netzzugriff beim Lesen")

    monkeypatch.setattr(socket, "socket", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)
    html = suchseite(ads[:4], canonical("kastenwagen"))
    lesung = SeitenEingang().lese(roh(html))                          # kein Importer, keine Datenbank, gesperrtes Netz
    assert isinstance(lesung, Lesung) and lesung.art == "suche" and len(lesung.inserate) == 4
    assert lesung.plattform == QUELLE and lesung.art_filter == SuchseitenArt(filter="Kastenwagen")
    assert lesung.haupttreffer == frozenset(i.anzeigen_id for i in lesung.inserate) and isinstance(lesung.haupttreffer, frozenset)
    detail = SeitenEingang().lese(roh(detailseite(ads[0])))
    assert detail.art == "detail" and [i.anzeigen_id for i in detail.inserate] == [ads[0]["id"]]
    assert detail.art_filter is None and detail.haupttreffer is None
    unbekannt = SeitenEingang().lese(roh("<html><body>Wetter</body></html>"))
    assert unbekannt.art == "unbekannt" and unbekannt.inserate == []


def test_dasselbe_inserat_ueber_zwei_kanaele_ist_eine_zeile(cfg, db, ads):
    imp = Importer(cfg, db)
    lesung = SeitenEingang().lese(roh(detailseite(ads[0])))
    a = imp.importiere(lesung, "manuell")
    assert a["neu"] == 1 and a["detailseiten"] == 1 and a["details"] == 1
    historie = (zaehle(db, "beobachtungen"), zaehle(db, "preis_historie"))
    b = imp.importiere(lesung, "email")                               # zweite Beobachtung, inhaltlich unverändert
    assert b["neu"] == 0 and b["bekannt"] == 1
    assert (zaehle(db, "inserate"), zaehle(db, "anzeigen")) == (1, 1)
    assert (zaehle(db, "beobachtungen"), zaehle(db, "preis_historie")) == historie       # ADR-024: nichts Neues protokolliert
    assert [r[0] for r in db.con.execute("SELECT kanal FROM beobachtungen")] == ["manuell"]


def test_kanal_wird_gespeichert(cfg, db, ads):
    Importer(cfg, db).importiere(SeitenEingang().lese(roh(detailseite(ads[0]))), "email")
    assert [r[0] for r in db.con.execute("SELECT kanal FROM beobachtungen")] == ["email"]
    assert [r[0] for r in db.con.execute("SELECT kanal FROM preis_historie")] == ["email"]


def test_unbekannter_kanal_und_automatische_kanaele_werden_abgewiesen(cfg, db, ads):
    lesung = SeitenEingang().lese(roh(detailseite(ads[0])))
    imp = Importer(cfg, db)
    with pytest.raises(ValueError, match="Unbekannter Eingangskanal"):
        imp.importiere(lesung, "telepathie")
    for kanal in ("api", "stream"):                                   # brauchen die Quellenfreigabe des EreignisSpeichers
        with pytest.raises(ValueError, match="kein Push-Eingang"):
            imp.importiere(lesung, kanal)
    assert zaehle(db, "anzeigen") == zaehle(db, "inserate") == 0


def test_unbekannte_plattform_und_fremde_id_werden_abgewiesen(cfg, db):
    imp = Importer(cfg, db)

    def lesung(quelle, ad_id):
        return Lesung("detail", [Inserat(quelle=quelle, anzeigen_id=ad_id, url="u", titel="Knaus")])

    with pytest.raises(ValueError, match="Unbekannte Plattform"):
        imp.importiere(lesung("mobilede", "md-1"), "manuell")         # alte Schreibweise ist nicht kanonisch
    with pytest.raises(ValueError, match="passt nicht zur Plattform"):
        imp.importiere(lesung("mobile.de", "123"), "manuell")         # mobile.de-IDs tragen „md-“
    with pytest.raises(ValueError, match="passt nicht zur Plattform"):
        imp.importiere(lesung("kleinanzeigen", "md-123"), "manuell")  # und fremde Präfixe gehören nicht zu Kleinanzeigen
    with pytest.raises(ValueError, match="nicht speicherbar"):
        imp.importiere(Lesung("unbekannt"), "manuell")
    assert zaehle(db, "anzeigen") == zaehle(db, "inserate") == 0       # nichts geschrieben


def test_plattformkonstanten_passen_zu_den_quellen():
    assert domaene.KLEINANZEIGEN == QUELLE == quellen.STANDARD_QUELLE
    assert domaene.MOBILEDE == mobilede.KENNUNG and domaene.ID_PRAEFIX[domaene.MOBILEDE] == mobilede.ID_PRAEFIX
    assert domaene.ID_PRAEFIX[domaene.KLEINANZEIGEN] == ""
    assert set(domaene.PUSH_KANAELE) <= set(domaene.KANAELE) and "email" in domaene.PUSH_KANAELE


def art_in_db(db, ad_id):
    return import_art(db.suche_zu(ad_id))


def test_vorlaeufige_art_wird_nicht_bestaetigt(cfg, db, ads):
    """Hinweis im Seitenpfad (kein Filter) → Art höchstens vorläufig; Filter in der Haupttabelle → bestätigt."""
    hinweis_kopf = '<link rel="canonical" href="https://www.kleinanzeigen.de/s-wohnwagen-mobile/alkoven/c220">'
    vorlaeufig = SeitenEingang().lese(roh(suchseite(ads[:2], hinweis_kopf)))
    assert vorlaeufig.art_filter == SuchseitenArt(hinweis="Alkoven")
    imp = Importer(cfg, db)
    imp.importiere(vorlaeufig, "manuell")
    assert {art_in_db(db, i["id"]) for i in ads[:2]} == {("Alkoven", VORLAEUFIG)}

    bestaetigt = SeitenEingang().lese(roh(suchseite(ads[2:4], canonical("kastenwagen"))))
    imp.importiere(bestaetigt, "email")
    assert {art_in_db(db, i["id"]) for i in ads[2:4]} == {("Kastenwagen", BESTAETIGT)}


def test_art_herkunft_geht_ueber_importiere_nicht_verloren(cfg, db, ads):
    """Dieselbe Seite einmal mit Filter, einmal ohne Filter in der Lesung: die Herkunft der Art kommt allein aus der Lesung."""
    html = suchseite(ads[:2], canonical("kastenwagen"))
    lesung = SeitenEingang().lese(roh(html))
    ohne = Lesung(lesung.art, lesung.inserate, lesung.hinweise, None, None)
    Importer(cfg, db).importiere(ohne, "manuell")
    assert {art_in_db(db, i["id"])[1] for i in ads[:2]} != {BESTAETIGT}
    Importer(cfg, db).importiere(lesung, "manuell")
    assert {art_in_db(db, i["id"]) for i in ads[:2]} == {("Kastenwagen", BESTAETIGT)}


def test_treffer_ausserhalb_der_haupttabelle_erben_den_filter_nicht(cfg, db, ads):
    lesung = SeitenEingang().lese(roh(suchseite(ads[:3], canonical("kastenwagen"))))
    nur_einer = Lesung(lesung.art, lesung.inserate, lesung.hinweise, lesung.art_filter, frozenset({ads[0]["id"]}))
    Importer(cfg, db).importiere(nur_einer, "manuell")
    assert art_in_db(db, ads[0]["id"]) == ("Kastenwagen", BESTAETIGT)
    assert art_in_db(db, ads[1]["id"])[1] != BESTAETIGT


def test_stat_wird_fortlaufend_ergaenzt(cfg, db, ads):
    stat = {"neu": 5}
    rueck = Importer(cfg, db).importiere(SeitenEingang().lese(roh(such_html(ads[:3]))), "manuell", stat)
    assert rueck is stat and stat["neu"] == 8 and stat["suchseiten"] == 1 and stat["detailseiten"] == 0


def test_mobilede_lesung_ueber_zwei_kanaele(cfg, db):
    ins = Inserat(quelle="mobile.de", anzeigen_id="md-123", url="https://suchen.mobile.de/fahrzeuge/details.html?id=123",
                  titel="Knaus Sky TI", preis=34000, ez_jahr=2018, km=70000, art="Alkoven", details={"art_quelle": "kategorie"})
    lesung = Lesung("suche", [ins])
    imp = Importer(cfg, db)
    assert imp.importiere(lesung, "manuell")["neu"] == 1
    assert imp.importiere(lesung, "email")["bekannt"] == 1
    assert [tuple(r) for r in db.con.execute("SELECT plattform, anzeigen_id FROM inserate")] == [("mobile.de", "md-123")]
    assert zaehle(db, "anzeigen") == 1 and art_in_db(db, "md-123") == ("Alkoven", BESTAETIGT)


def test_ereignis_prueft_plattform_und_kanal_gegen_die_konstanten():
    from wmscout.ereignisse import InseratEreignis

    ins = Inserat(quelle="mobilede", anzeigen_id="md-1", url="u", titel="Knaus")
    with pytest.raises(ValueError, match="Unbekannte Plattform"):
        InseratEreignis("mobilede", "md-1", "neu", "email", JETZT, ins)
    ins = Inserat(quelle="mobile.de", anzeigen_id="md-1", url="u", titel="Knaus")
    with pytest.raises(ValueError, match="Unbekannter Eingangskanal"):
        InseratEreignis("mobile.de", "md-1", "neu", "fax", JETZT, ins)
    assert InseratEreignis("mobile.de", "md-1", "neu", "email", JETZT, ins).plattform == "mobile.de"


def test_gemischte_lesung_schreibt_nichts_und_detail_ohne_id_wird_abgewiesen(cfg, db):
    """QA P2-00: alle Prüfungen laufen vor dem ersten Schreiben – ein ungültiges Inserat verhindert die ganze Lesung."""
    imp = Importer(cfg, db)
    gut = Inserat(quelle="kleinanzeigen", anzeigen_id="3500000001", url="u", titel="Knaus")
    schlecht = Inserat(quelle="kleinanzeigen", anzeigen_id="as-1", url="u", titel="Hymer")
    with pytest.raises(ValueError, match="passt nicht zur Plattform"):
        imp.importiere(Lesung("suche", [gut, schlecht]), "email")
    with pytest.raises(ValueError, match="nicht speicherbar"):
        imp.importiere(Lesung("detail_ohne_id"), "manuell")
    assert zaehle(db, "anzeigen") == zaehle(db, "inserate") == zaehle(db, "beobachtungen") == 0


def test_rohdaten_brauchen_zeitzone_und_kanalliste_ist_einheitlich():
    import typing
    from wmscout.ereignisse import Eingangskanal
    with pytest.raises(ValueError, match="Zeitzone"):
        Rohdaten(b"", "x.html", datetime(2026, 10, 17, 9, 0))
    assert typing.get_args(Eingangskanal) == domaene.KANAELE                 # Typ-Alias und Konstante laufen nicht auseinander
    assert set(domaene.PUSH_KANAELE) < set(domaene.KANAELE)


def test_seite_mit_unpassender_id_bleibt_liegen(cfg, db, tmp_path, ads):
    """QA P2-00 (B4): Eine Seite mit unpassender Anzeigen-ID wird nicht teilweise gespeichert, sondern bleibt mit Meldung liegen."""
    ordner = tmp_path / "import"
    ordner.mkdir()
    (ordner / "s.html").write_text(such_html([dict(ads[0], id="md-999")]), encoding="utf-8")
    stat = Importer(cfg, db).importiere_seiten(ordner)
    assert stat["fehlerhaft"] == 1 and (ordner / "s.html").exists() and zaehle(db, "anzeigen") == 0
    assert any("passt nicht zur Plattform kleinanzeigen" in f for f in stat["fehler"])
