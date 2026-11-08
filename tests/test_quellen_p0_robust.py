"""P0-Regressionen; ausschließlich synthetische Seiten und freigegebene Testquellen, keine Live-Prüfung."""
from __future__ import annotations

import pytest

from wmscout import quellen
from wmscout.importer import Importer
from wmscout.laufprotokoll import Laufprotokoll
from wmscout.quellen.basis import Inserat, NetzwerkFehler, Quelle, QuelleGesperrt, Suchauftrag, Suchseite
from wmscout.quellen.kleinanzeigen.parser import parse_detailseite, parse_suchseite, preis_aus_text


def artikel(n=1, *, preis="", zusatz="", adid=True):
    ident = f'data-adid="{3900000000 + n}"' if adid else ""
    return (f'<article {ident} data-href="/s-anzeige/knaus/{3900000000 + n}-220-1">'
            f'<h3>Knaus Sky TI</h3><p>Fahrzeugbeschreibung</p>{preis}{zusatz}</article>')


@pytest.mark.parametrize("roh, erwartet", [("Preis: 38 900 € VHB", (38900, True)), ("49.000 € Festpreis", (49000, False)),
                                         ("38\u202f900 €", (38900, False)), ("VB", (None, True)),
                                         ("Finanzierung ab 249 € monatlich", (None, False)),
                                         ("Reparatur für 2.999 €", (None, False)), ("39.900 € oder 45.000 €", (None, False))])
def test_preiszeile_muss_eindeutig_sein(roh, erwartet):
    assert preis_aus_text(roh) == erwartet


@pytest.mark.parametrize("markup", [
    '<div class="line-through"><p>49.900 €</p></div><p>45.900 €</p>',
    '<p><del>49.900 €</del>45.900 €</p>',
    '<p style="text-decoration: line-through">49.900 €</p><p>45.900 €</p>',
    '<div hidden><p>49.900 €</p></div><p>45.900 €</p>',
])
def test_altpreise_werden_nicht_als_kaufpreis_eingelesen(markup):
    assert parse_suchseite(artikel(preis=markup))[0]["preis"] == 45900


def test_altlayout_und_details_entfernen_altpreis_und_raten():
    alt = ('<article class="aditem" data-adid="3900000001" data-href="/s-anzeige/knaus/3900000001-220-1">'
           '<h2><a>Knaus Sky</a></h2><p class="aditem-main--middle--price"><del>49.900 €</del>45.900 € VB</p></article>')
    assert (parse_suchseite(alt)[0]["preis"], parse_suchseite(alt)[0]["vb"]) == (45900, True)
    d = parse_detailseite('<h1>Knaus Sky</h1><h2 id="viewad-price"><s>49.900 €</s>45.900 € VB</h2>')
    assert (d["preis"], d["vb"]) == (45900, True)
    assert parse_detailseite('<h1>Knaus Sky</h1><h2 id="viewad-price">Finanzierung ab 299 € monatlich</h2>')["preis"] is None


@pytest.mark.parametrize("container", ['class="line-through"', 'style="display:none"', 'hidden', 'aria-hidden="true"'])
def test_altlayout_und_details_ueberspringen_versteckte_preiscontainer(container):
    alt = ('<article class="aditem" data-adid="3900000001" data-href="/s-anzeige/knaus/3900000001-220-1">'
           f'<div {container}><p class="aditem-main--middle--price">49.900 €</p></div>'
           '<p class="aditem-main--middle--price">45.900 € VB</p></article>')
    d = parse_suchseite(alt)[0]
    assert (d["preis"], d["vb"]) == (45900, True)
    detail = f'<div {container}><h2 id="viewad-price">49.900 €</h2></div><h2 itemprop="price">45.900 € VB</h2>'
    d = parse_detailseite(detail)
    assert (d["preis"], d["vb"]) == (45900, True)


def test_detailpreis_ueberspringt_finanzierung_und_findet_naechsten_kaufpreis():
    d = parse_detailseite('<h2 id="viewad-price">Finanzierung ab 299 € monatlich</h2><h2 itemprop="price">45.900 € VB</h2>')
    assert (d["preis"], d["vb"]) == (45900, True)


def test_doppelte_karten_ergaenzen_preis_vb_und_anbieternachweis():
    html = artikel(zusatz='<span>Privater Anbieter</span><span>EZ 06/2019</span><span>70173 Stuttgart</span>')
    html += artikel(2, preis='<p>41.000 €</p>')
    html += artikel(preis='<p>39.900 € VB</p>')
    treffer = parse_suchseite(html)
    assert [t["id"] for t in treffer] == ["3900000001", "3900000002"]
    assert (treffer[0]["preis"], treffer[0]["vb"], treffer[0]["gewerblich"]) == (39900, True, False)
    assert treffer[0]["ez_jahr"] == 2019 and treffer[0]["anbieter_herkunft"] == "anzeige"
    assert parse_suchseite(html + artikel(zusatz='<span>PRO</span>'))[0]["gewerblich"] is True


def test_ohne_kennzeichnung_ist_anbieter_unbekannt():
    for d in (parse_suchseite(artikel())[0], parse_detailseite('<h1>Knaus Sky</h1>')):
        assert d["gewerblich"] is None and d["anbieter_herkunft"] is None


def test_reimport_ohne_preis_bewahrt_verhandlungsbasis(db):
    (d,) = parse_suchseite(artikel(preis='<p>39.900 € VB</p>'))
    db.speichere_treffer(d, "Test")
    (d,) = parse_suchseite(artikel())
    assert d["preis"] is None and d["vb"] is None
    db.speichere_treffer(d, "Test")
    assert tuple(db.con.execute("SELECT preis,vb FROM anzeigen").fetchone()) == (39900, 1)


def test_kanonische_identitaet_und_sichere_links():
    html = artikel(adid=False).replace('-220-1"', '-220-1?tracking=foo#bilder"')
    t = parse_suchseite(html)[0]
    assert t["id"] == "3900000001" and t["url"] == "https://www.kleinanzeigen.de/s-anzeige/knaus/3900000001-220-1"
    assert parse_suchseite(html.replace('/s-anzeige/knaus/', 'https://evil.example/s-anzeige/knaus/')) == []
    assert parse_suchseite(artikel().replace('data-adid="3900000001"', 'data-adid="9999999999"'))[0]["id"] == "3900000001"
    assert parse_suchseite(artikel().replace('/s-anzeige/knaus/3900000001-220-1', 'javascript:alert(1)')) == []


def test_seitenimport_meldet_ungueltige_karten_ohne_gueltige_zu_verlieren(cfg, db, tmp_path):
    datei = tmp_path / "gemischt.html"
    datei.write_text(artikel(preis='<p>39.900 €</p>') + artikel(2).replace('3900000002', 'md-999'), encoding="utf-8")
    stat = Importer(cfg, db).importiere_seiten(tmp_path)
    assert stat["neu"] == 1 and stat["fehlerhaft"] == 0
    assert any("1 Anzeigenkarten ohne gültige Anzeigen-ID/Adresse" in f for f in stat["fehler"])
    assert db.con.execute("SELECT id FROM anzeigen").fetchall()[0][0] == "3900000001"


class TestQuelle(Quelle):
    __test__ = False
    kennung, name, zugriffsart, freigegeben = "test_p0", "Test", "feed", True

    def suche(self, auftrag):
        yield Suchseite(1, [Inserat(self.kennung, "p0-1", "https://example.org/1", titel="Knaus Sky", preis=39900)])


def registriere(monkeypatch, *klassen):
    for klasse in klassen:
        monkeypatch.setitem(quellen.QUELLEN, klasse.kennung, klasse)


@pytest.mark.parametrize("ausnahme", [QuelleGesperrt("HTTP 429"), NetzwerkFehler("Timeout"), ValueError("persoenliche Rohdaten")])
def test_quellenfehler_isoliert_und_teilzaehler_bleiben(cfg, db, monkeypatch, caplog, ausnahme):
    class Kaputt(TestQuelle):
        kennung = "kaputt"
        def suche(self, auftrag):
            yield from super().suche(auftrag)
            raise ausnahme

    class Gesund(TestQuelle):
        kennung = "gesund"
        def suche(self, auftrag):
            yield Suchseite(1, [Inserat(self.kennung, "p0-2", "https://example.org/2", titel="Hymer B")])

    registriere(monkeypatch, Kaputt, Gesund)
    stat = Importer(cfg, db).lauf([{"name": "A", "quelle": "kaputt"}, {"name": "B", "quelle": "gesund"}])
    assert stat["neu"] == 2 and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 2
    prot = Laufprotokoll(db).letzte()[0]
    assert prot["je_quelle"]["kaputt"]["neu"] == 1 and prot["je_quelle"]["gesund"]["ergebnis"] == "ok"
    assert prot["je_quelle"]["kaputt"]["ergebnis"] == ("gesperrt" if isinstance(ausnahme, QuelleGesperrt) else "fehler")
    assert "persoenliche Rohdaten" not in caplog.text and "persoenliche Rohdaten" not in (stat["fehler"] or "")


def test_parserfehler_isoliert_suchauftrag_sperre_stoppt_quelle(cfg, db, monkeypatch):
    class Unterschiedlich(TestQuelle):
        aufrufe = []
        def suche(self, auftrag):
            self.aufrufe.append(auftrag.name)
            if auftrag.name == "parser":
                raise ValueError("ungueltiger Datensatz")
            if auftrag.name == "sperre":
                raise QuelleGesperrt("HTTP 403")
            yield from super().suche(auftrag)

    registriere(monkeypatch, Unterschiedlich)
    stat = Importer(cfg, db).lauf([{"name": n, "quelle": Unterschiedlich.kennung} for n in ("parser", "gut", "sperre", "danach")])
    assert stat["neu"] == 1 and Unterschiedlich.aufrufe == ["parser", "gut", "sperre"]
    assert Laufprotokoll(db).letzte()[0]["je_quelle"][Unterschiedlich.kennung]["ergebnis"] == "gesperrt"


def test_detailfehler_blockiert_andere_quelle_nicht(cfg, db, monkeypatch):
    class Kaputt(TestQuelle):
        kennung = "a_kaputt"
        unterstuetzt_details = True
        def details(self, url):
            raise ValueError("Parser kaputt")

    class Gesund(TestQuelle):
        kennung = "z_gesund"
        def suche(self, auftrag):
            yield Suchseite(1, [Inserat(self.kennung, "p0-2", "https://example.org/2", titel="Hymer B")])

    registriere(monkeypatch, Kaputt, Gesund)
    stat = Importer(cfg, db).lauf([{"name": "A", "quelle": Kaputt.kennung}, {"name": "B", "quelle": Gesund.kennung}])
    assert stat["neu"] == 2 and stat["details"] == 1
    assert db.con.execute("SELECT detail_geladen FROM anzeigen WHERE id='p0-2'").fetchone()[0] == 1


@pytest.mark.parametrize("optimiert, seiten", [(False, [1, 2, 3]), (True, [1, 2])])
def test_bekannte_seiten_nur_mit_expliziter_quellengarantie_abbrechen(cfg, db, monkeypatch, optimiert, seiten):
    class Blaettern(TestQuelle):
        stop_bei_bekannter_seite = optimiert
        gelesen = []
        def suche(self, auftrag):
            for nummer in (1, 2, 3):
                self.gelesen.append(nummer)
                yield Suchseite(nummer, [Inserat(self.kennung, "p0-1", "https://example.org/1", preis=39900 if nummer < 3 else 37900)])

    registriere(monkeypatch, Blaettern)
    db.speichere_treffer({"id": "p0-1", "quelle": Blaettern.kennung, "url": "https://example.org/1", "preis": 39900}, "x")
    stat = Importer(cfg, db).suche(Suchauftrag("x", quelle=Blaettern.kennung))
    assert Blaettern.gelesen == seiten and stat["preis"] == (0 if optimiert else 1)
