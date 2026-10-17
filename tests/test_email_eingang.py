"""E-Mail-Eingang (P2-06, Teil 1: Kern): .eml zerlegen, Plattform-Parser, MailEingang, Importer.importiere_mails, Datenschutz-Frist.

GRENZE: Alle Mails sind NACHGEBILDET (tests/nachgebildet_mails.py, Kopf `X-Scout-Testdaten`). Die Tests belegen die Logik (Links, Hosts,
Felder, Kanal, Frist), nicht dass echte Benachrichtigungen von Kleinanzeigen oder mobile.de so aufgebaut sind – das ist die Abnahme
mit echten Mails (F3).
"""
import os
import socket
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import pytest

from tests.nachgebildet_mails import (EMPFAENGER, KA_ABSENDER, KA_ANZEIGEN, KA_BASIS, MD_ABSENDER, MD_ANZEIGEN, MD_BASIS, TESTKOPF, TESTWERT,
                                      ka_link, nachgebildet_ka_html, nachgebildet_ka_mail, nachgebildet_ka_text, nachgebildet_mail,
                                      nachgebildet_md_html, nachgebildet_md_mail, nachgebildet_md_text, weiterleitung)
from tests.test_seitenimport import KeinNetz, detailseite
from wmscout import datenrechte, domaene
from wmscout.datenbank import BESTAETIGT, import_art
from wmscout.eingang import Eingang, Lesung, Rohdaten
from wmscout.eingang.email import MAX_BYTES, MailEingang, MailFehler, datenqualitaet, eml_dateien, kleinanzeigen, mail_ordner, mobilede, zerlege
from wmscout.importer import Importer

JETZT = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
MD_SEITE = Path(__file__).resolve().parent / "seiten" / "mobilede" / "suchseite.html"


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    """Jeder Netzzugriff in diesen Tests ist ein Fehler (Sockets und urllib gesperrt)."""
    def gesperrt(*a, **k):
        raise AssertionError("Netzzugriff beim Lesen einer Mail")

    monkeypatch.setattr(socket, "socket", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)
    monkeypatch.setattr(urllib.request, "urlopen", gesperrt)


@pytest.fixture
def ordner(cfg, tmp_path):
    cfg["import"] = {"ordner": str(tmp_path / "import")}
    cfg["eingaenge"] = {"email": {"aktiv": True}}                      # Standard ist aus (ADR-036)
    o = mail_ordner(cfg)
    o.mkdir(parents=True)
    return o


def roh(daten: bytes, name="mail.eml") -> Rohdaten:
    return Rohdaten(daten, name, JETZT)


def lese(daten: bytes) -> Lesung:
    return MailEingang().lese(roh(daten))


def mail_aus(absender, html=None, text=None, **kw) -> bytes:
    return nachgebildet_mail(absender, "Neue Treffer", html, text, **kw).as_bytes()


def ka_mail(html=None, text=None, **kw) -> bytes:
    return mail_aus(KA_ABSENDER, html, text, **kw)


def zeile(db, ad_id):
    return db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()


def anzahl(db, tabelle):
    return db.con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


def nach_id(lesung: Lesung) -> dict:
    return {i.anzeigen_id: i for i in lesung.inserate}


# ---------- Vertrag ----------
def test_maileingang_erfuellt_vertrag():
    eingang = MailEingang()
    assert isinstance(eingang, Eingang)
    assert (eingang.kennung, eingang.kanal) == ("email", "email")
    assert eingang.kanal in domaene.PUSH_KANAELE


def test_testmails_sind_gekennzeichnet():
    for daten in (nachgebildet_ka_mail(), nachgebildet_md_mail()):
        assert f"{TESTKOPF}:".encode() in daten and "nachgebildet".encode() in daten
    m = EmailMessage()
    m[TESTKOPF] = TESTWERT
    assert "nachgebildet" in m[TESTKOPF]


# ---------- Zerlegen ----------
def test_zerlege_metadaten_und_teile():
    mail = zerlege(nachgebildet_ka_mail())
    assert mail.absender_domain == "mail.kleinanzeigen.de" and not hasattr(mail, "betreff")
    assert mail.datum == datetime(2026, 10, 17, 6, 15, tzinfo=timezone.utc) and mail.datum.utcoffset() == timedelta(hours=2)
    assert "Knaus Sky TI 650 MEG" in mail.text and "<table>" in mail.html and mail.anhaenge == 0
    assert not hasattr(mail, "absender") and not hasattr(mail, "empfaenger")
    assert EMPFAENGER not in repr(mail) and "noreply-test" not in repr(mail)       # keine Adressen im Objekt


def test_datum_ohne_zeitzone_gilt_als_utc():
    mail = zerlege(mail_aus(KA_ABSENDER, text="x", datum="Sat, 17 Oct 2026 08:15:00 -0000"))
    assert mail.datum == datetime(2026, 10, 17, 8, 15, tzinfo=timezone.utc)


def test_anhaenge_werden_ignoriert():
    innen = EmailMessage()
    innen["From"], innen["Subject"] = KA_ABSENDER, "weitergeleitet"
    innen.set_content(nachgebildet_ka_text())
    m = nachgebildet_mail(KA_ABSENDER, "Anhang", None, "Keine Anzeigen hier.")
    m.add_attachment(nachgebildet_ka_text(), filename="liste.txt")                  # text/plain als Anhang
    m.add_attachment(b"%PDF-1.4 ...", maintype="application", subtype="pdf", filename="a.pdf")
    m.add_attachment(innen)                                                         # message/rfc822
    mail = zerlege(m.as_bytes())
    assert mail.anhaenge == 3 and mail.text.strip() == "Keine Anzeigen hier."
    assert lese(m.as_bytes()).art == "unbekannt"                                    # Links in Anhängen zählen nicht


@pytest.mark.parametrize("kodierung", [None, "quoted-printable", "base64"])
def test_kodierungen_utf8(kodierung):
    lesung = lese(ka_mail(nachgebildet_ka_html(), nachgebildet_ka_text(), kodierung=kodierung))
    assert [i.titel for i in lesung.inserate][2] == "Bürstner Lyseo TD 728 G" and nach_id(lesung)["3500000103"].ort == "40213 Düsseldorf"


def test_iso_8859_1_quoted_printable():
    def latin1(t):     # ISO-8859-1 kennt weder € noch typografische Anführungszeichen
        return t.replace("€", "EUR").replace("„", '"').replace("“", '"')

    html, text = latin1(nachgebildet_ka_html()), latin1(nachgebildet_ka_text())
    daten = ka_mail(html, text, zeichensatz="iso-8859-1", kodierung="quoted-printable")
    assert b"B=FCrstner" in daten
    treffer = nach_id(lese(daten))
    assert treffer["3500000103"].titel == "Bürstner Lyseo TD 728 G" and treffer["3500000103"].ort == "40213 Düsseldorf"
    assert treffer["3500000103"].preis == 41000


def test_windows_1252_base64_mit_eurozeichen():
    daten = ka_mail(None, nachgebildet_ka_text(), zeichensatz="windows-1252", kodierung="base64")
    assert nach_id(lese(daten))["3500000101"].preis == 38500 and "Bürstner Lyseo TD 728 G" in [i.titel for i in lese(daten).inserate]


def test_unbekannter_zeichensatz_bricht_nicht_ab():
    daten = (b"From: a@mail.kleinanzeigen.de\r\nSubject: x\r\nContent-Type: text/plain; charset=x-gibts-nicht\r\n"
             b"Content-Transfer-Encoding: 8bit\r\n\r\nB\xfcrstner 41.000 \x80\r\n" + KA_BASIS.encode() + b"/s-anzeige/x/3500000103-220-1\r\n")
    mail = zerlege(daten)
    assert "Bürstner" in mail.text and kleinanzeigen.erkennt(mail)


# ---------- Kleinanzeigen ----------
def test_kleinanzeigen_felder_html_und_text():
    for daten in (ka_mail(nachgebildet_ka_html(), nachgebildet_ka_text()), ka_mail(nachgebildet_ka_html()), ka_mail(None, nachgebildet_ka_text())):
        lesung = lese(daten)
        assert lesung.art == "suche" and lesung.plattform == "kleinanzeigen" and lesung.hinweise == []
        assert lesung.art_filter is None and lesung.haupttreffer is None
        treffer = nach_id(lesung)
        assert list(treffer) == [a["id"] for a in KA_ANZEIGEN]
        for a in KA_ANZEIGEN:
            i = treffer[a["id"]]
            assert (i.titel, i.preis, i.vb, i.ort) == (a["titel"], a["preis"], True, f"{a['plz']} {a['ort']}")
            assert i.quelle == "kleinanzeigen" and i.url == f"{KA_BASIS}/s-anzeige/{a['id']}"          # aus der ID gebildet, nicht der Link der Mail
            assert i.gewerblich is None and i.ist_gesuch is False and i.bild is None
        assert treffer["3500000102"].marke == "Hymer"


def test_kleinanzeigen_mehrere_links_derselben_anzeige_sind_ein_treffer():
    lesung = lese(ka_mail(nachgebildet_ka_html()))       # Bild-, Titel- und „Anzeige ansehen“-Link je Anzeige
    assert len(lesung.inserate) == 3 and all(i.titel != "Anzeige ansehen" for i in lesung.inserate)


def test_einzelne_anzeige_im_text_ohne_fussbereich_im_block():
    lesung = lese(ka_mail(nachgebildet_ka_html(KA_ANZEIGEN[:1])))
    (i,) = lesung.inserate
    assert (i.titel, i.preis, i.ort) == ("Knaus Sky TI 650 MEG", 38500, "70173 Stuttgart")


def test_kleinanzeigen_flaches_layout_und_link_um_die_ganze_karte():
    flach = "<body>" + "".join(f'<a href="{ka_link(a)}">{a["titel"]}</a><p>{a["preis"]} €</p><p>{a["plz"]} {a["ort"]}</p>'
                              for a in KA_ANZEIGEN) + "</body>"
    karte = "<body>" + "".join(f'<div><a href="{ka_link(a)}"><div>{a["titel"]}</div><div>{a["preis"]} €</div><div>{a["plz"]} {a["ort"]}</div></a></div>'
                               for a in KA_ANZEIGEN) + "</body>"
    for html in (flach, karte):
        treffer = nach_id(lese(ka_mail(html)))
        assert [(i.titel, i.preis, i.ort) for i in treffer.values()] == [(a["titel"], a["preis"], f"{a['plz']} {a['ort']}") for a in KA_ANZEIGEN]


def test_weiterleitungslinks_werden_lokal_zerlegt_nie_abgerufen():
    ziel = f"{KA_BASIS}/s-anzeige/knaus/3500000555-220-9999?x=1"
    zweifach = "https://click.mail.kleinanzeigen.de/r?u=" + weiterleitung(ziel).replace("&", "%26").replace("=", "%3D").replace(":", "%3A").replace("/", "%2F")
    pfad = "https://click.mail.kleinanzeigen.de/r/" + ziel.replace(":", "%3A").replace("/", "%2F").replace("?", "%3F")
    for link in (weiterleitung(ziel), zweifach, pfad):
        html = f'<body><div><a href="{link}">Knaus Sky</a><p>12.000 €</p><p>70173 Stuttgart</p></div></body>'
        (i,) = lese(ka_mail(html)).inserate
        assert i.anzeigen_id == "3500000555" and i.url == f"{KA_BASIS}/s-anzeige/3500000555" and i.preis == 12000
    # nur ein undurchsichtiger Token ohne lesbare Ziel-Adresse: nichts zu lesen, nichts wird aufgelöst
    opak = '<body><a href="https://click.mail.kleinanzeigen.de/r?qs=AbCdEf0123456789">Knaus Sky</a> 12.000 €</body>'
    lesung = lese(ka_mail(opak))
    assert lesung.art == "unbekannt" and any("Layout verdächtig" in h for h in lesung.hinweise)


def test_fremde_hosts_und_unzulaessige_schemas_werden_verworfen_und_gezaehlt():
    gut = KA_ANZEIGEN[0]
    schlecht = ["javascript:window.open('https://www.kleinanzeigen.de/s-anzeige/x/3500000199-220-1')",
                "ftp://www.kleinanzeigen.de/s-anzeige/x/3500000194-220-1",
                "https://evil.example.com/s-anzeige/x/3500000198-220-1",
                "https://www.kleinanzeigen.de.evil.example.com/s-anzeige/x/3500000197-220-1",
                "https://www.kleinanzeigen.de@evil.example.com/s-anzeige/x/3500000196-220-1",
                "https://evilkleinanzeigen.de/s-anzeige/x/3500000195-220-1",
                weiterleitung(f"{KA_BASIS}/s-anzeige/x/3500000193-220-1", host="tracker.example.com"),
                "https://click.mail.kleinanzeigen.de/r?url=" + "https%3A%2F%2Fevil.example.com%2Fs-anzeige%2Fx%2F3500000192-220-1",
                "data:text/html,<a href=x>", "mailto:info@kleinanzeigen.de", "#", ""]
    html = (f'<body><div><a href="{ka_link(gut)}">{gut["titel"]}</a><p>1.000 €</p></div>' +
            "".join(f'<div><a href="{s}">Böse {n}</a><p>1 €</p></div>' for n, s in enumerate(schlecht)) + "</body>")
    lesung = lese(ka_mail(html))
    assert [i.anzeigen_id for i in lesung.inserate] == [gut["id"]]
    assert "2 Link(s) mit unzulässigem Schema (nicht http/https) verworfen" in lesung.hinweise
    assert "5 Anzeigenlink(s) auf fremden Hosts verworfen" in lesung.hinweise
    assert not any("evil" in i.url for i in lesung.inserate)


def test_gesuch_wird_uebersprungen_mit_hinweis():
    such, hymer = ka_link({"slug": "s", "id": "3500000300"}), ka_link({"slug": "h", "id": "3500000301"})
    html = (f'<body><div><a href="{such}">Suche Wohnmobil bis 30.000 €</a><p>30.000 €</p></div>'
            f'<div><a href="{hymer}">Hymer B 544</a><p>40.000 €</p></div></body>')
    lesung = lese(ka_mail(html))
    assert [i.anzeigen_id for i in lesung.inserate] == ["3500000301"] and "1 Gesuch(e)/Ankaufsanzeige(n) übersprungen" in lesung.hinweise


def test_nur_gesuche_ist_nichts_zu_speichern():
    html = '<body><div><a href="%s">Suche Wohnmobil</a><p>30.000 €</p></div></body>' % ka_link({"slug": "s", "id": "3500000300"})
    lesung = lese(ka_mail(html))
    assert lesung.art == "unbekannt" and lesung.inserate == [] and "nur Gesuche" in lesung.hinweise[0]


def test_werbemail_ohne_anzeigenlinks_layout_verdaechtig_bzw_unbekannt():
    werbung = '<body><p>Entdecke jetzt unsere Neuheiten!</p><a href="https://www.kleinanzeigen.de/">Zur Startseite</a></body>'
    verdacht = lese(mail_aus(KA_ABSENDER, werbung))                      # Absender erkannt, aber 0 Treffer
    assert verdacht.art == "unbekannt" and verdacht.plattform == "kleinanzeigen" and "Layout verdächtig" in verdacht.hinweise[0]
    verdacht = lese(mail_aus(MD_ABSENDER, werbung))
    assert verdacht.art == "unbekannt" and verdacht.plattform == "mobile.de" and "Layout verdächtig" in verdacht.hinweise[0]
    fremd = lese(mail_aus("newsletter@example.org", werbung))            # nicht von uns und ohne Links
    assert fremd.art == "unbekannt" and fremd.plattform is None and not any("Layout verdächtig" in h for h in fremd.hinweise)


def test_mehr_als_die_obergrenze_wird_gemeldet():
    viele = [{"id": str(3500001000 + n), "slug": "x", "titel": f"Hymer {n}", "preis": 10000 + n, "plz": "70173", "ort": "Stuttgart"} for n in range(230)]
    lesung = lese(ka_mail(nachgebildet_ka_html(viele)))
    assert len(lesung.inserate) == 200 and any("30 weitere Anzeigen nicht gelesen" in h for h in lesung.hinweise)


# ---------- mobile.de ----------
def test_mobilede_felder_html_und_text():
    for daten in (nachgebildet_md_mail(), mail_aus(MD_ABSENDER, nachgebildet_md_html()), mail_aus(MD_ABSENDER, None, nachgebildet_md_text())):
        lesung = lese(daten)
        assert lesung.art == "suche" and lesung.plattform == "mobile.de" and lesung.hinweise == []
        treffer = nach_id(lesung)
        assert list(treffer) == [f"md-{a['id']}" for a in MD_ANZEIGEN]
        for a in MD_ANZEIGEN:
            i = treffer[f"md-{a['id']}"]
            assert (i.titel, i.preis, i.ort) == (a["titel"], a["preis"], f"{a['plz']} {a['ort']}")
            assert i.km == int(a["km"].replace(".", "")) and i.ez_jahr == int(a["ez"][-4:])
            assert i.url == f"{MD_BASIS}/fahrzeuge/details.html?id={a['id']}" and i.gewerblich is None and i.art is None and i.bild is None


def test_mobilede_weiterleitung_und_fremder_host():
    ziel = f"{MD_BASIS}/fahrzeuge/details.html?id=3900000077&searchId=abc"
    kodiert = quote(ziel, safe="")
    html = (f'<body><div><a href="https://click.mobile.de/go?url={kodiert}">Beispiel Camper</a><p>9.900 €</p></div>'
            '<div><a href="https://suchen.mobile.de.evil.example.com/fahrzeuge/details.html?id=3900000078">Falsch</a><p>1 €</p></div></body>')
    lesung = lese(mail_aus(MD_ABSENDER, html))
    assert [i.anzeigen_id for i in lesung.inserate] == ["md-3900000077"] and "1 Anzeigenlink(s) auf fremden Hosts verworfen" in lesung.hinweise


# ---------- Erkennung ----------
def test_weitergeleitete_mail_wird_am_inhalt_erkannt_und_gemischte_sind_mehrdeutig():
    weitergeleitet = mail_aus("ich@example.org", None, nachgebildet_md_text())
    assert lese(weitergeleitet).plattform == "mobile.de" and mobilede.erkennt(zerlege(weitergeleitet)) and not kleinanzeigen.erkennt(zerlege(weitergeleitet))
    gemischt = mail_aus("ich@example.org", None, nachgebildet_md_text(MD_ANZEIGEN[:1]) + nachgebildet_ka_text(KA_ANZEIGEN[:1]))
    lesung = lese(gemischt)
    assert lesung.art == "unbekannt" and "mehrere Plattformen" in lesung.hinweise[0]
    # Absender der Plattform entscheidet bei gemischten Links
    assert lese(mail_aus(KA_ABSENDER, None, nachgebildet_md_text(MD_ANZEIGEN[:1]) + nachgebildet_ka_text(KA_ANZEIGEN[:1]))).plattform == "kleinanzeigen"


def test_unbekannte_mail():
    lesung = lese(mail_aus("freund@example.org", None, "Hallo, wie geht es? https://example.org/s-anzeige/x/3500000101-220-1"))
    assert lesung.art == "unbekannt" and lesung.inserate == [] and lesung.hinweise


# ---------- Fehler ----------
def test_zu_grosse_mail_wird_abgelehnt():
    gross = b"From: a@mail.kleinanzeigen.de\r\nSubject: x\r\n\r\n" + b"a" * MAX_BYTES
    with pytest.raises(MailFehler, match="zu groß"):
        zerlege(gross)
    with pytest.raises(MailFehler, match="zu groß"):
        lese(gross)
    zerlege(gross[:MAX_BYTES])                                       # genau am Limit ist erlaubt


@pytest.mark.parametrize("daten", [b"\x00\x01\x02\xff\xfe binary", b"", b"nur ein Satz ohne Kopfzeilen"])
def test_kaputte_dateien_sind_ein_mailfehler(daten):
    with pytest.raises(MailFehler):
        lese(daten)


def test_tief_verschachteltes_html_wird_abgelehnt_statt_ewig_zu_rechnen():
    def mit_tiefe(n):
        return "<div>" * n + f'<a href="{ka_link(KA_ANZEIGEN[0])}">Knaus</a> 1.000 €' + "</div>" * n

    assert [i.anzeigen_id for i in lese(ka_mail(mit_tiefe(60))).inserate] == ["3500000101"]          # echte Layouts sind deutlich flacher
    start = time.monotonic()
    with pytest.raises(MailFehler, match="verschachtelt"):
        lese(ka_mail(mit_tiefe(20000)))
    assert time.monotonic() - start < 10


# ---------- Importer ----------
def test_import_ordner_ablage_zaehler_und_isolation(cfg, db, ordner):
    (ordner / "a_kaputt.eml").write_bytes(b"\x00\x01 kaputt")
    (ordner / "b_kleinanzeigen.eml").write_bytes(nachgebildet_ka_mail())
    (ordner / "c_mobilede.EML").write_bytes(nachgebildet_md_mail())
    (ordner / "d_fremd.eml").write_bytes(mail_aus("freund@example.org", None, "Hallo"))
    (ordner / "e_werbung.eml").write_bytes(mail_aus(KA_ABSENDER, "<body>Neuheiten</body>"))
    (ordner / "f_gross.eml").write_bytes(b"From: a@mail.kleinanzeigen.de\r\nSubject: x\r\n\r\n" + b"a" * (MAX_BYTES + 10))
    (ordner / "notiz.txt").write_text("bleibt", encoding="utf-8")
    netz = KeinNetz()
    stat = Importer(cfg, db, abruf=netz).importiere_mails(ordner)
    assert {k: v for k, v in stat.items() if k != "fehler"} == {"dateien": 6, "suchseiten": 2, "detailseiten": 0, "unbekannt": 2, "fehlerhaft": 2,
                                                                  "neu": 5, "preis": 0, "bekannt": 0, "details": 0, "uebrig": 0,
                                                                  "aeltere": 0}
    assert netz.abrufe == []
    gelesen = ordner / "eingelesen" / date.today().isoformat()
    assert sorted(p.name for p in gelesen.iterdir()) == ["b_kleinanzeigen.eml", "c_mobilede.EML"]
    assert sorted(p.name for p in (ordner / "nicht_erkannt").iterdir()) == ["d_fremd.eml", "e_werbung.eml"]
    assert sorted(p.name for p in ordner.iterdir() if p.is_file()) == ["notiz.txt"]
    assert sorted(p.name for p in (ordner / "fehlerhaft").iterdir()) == ["a_kaputt.eml", "f_gross.eml"]                 # unlesbare/zu große: fehlerhaft/
    text = "\n".join(stat["fehler"])
    assert "a_kaputt.eml: nicht eingelesen" in text and "f_gross.eml: nicht eingelesen (Mail zu groß" in text and "verschoben nach fehlerhaft/" in text
    assert "e_werbung.eml" in text and "Layout verdächtig" in text and "d_fremd.eml" in text
    assert anzahl(db, "anzeigen") == anzahl(db, "inserate") == 5


def test_zu_grosse_datei_wird_gar_nicht_erst_gelesen(cfg, db, ordner, monkeypatch):
    with (ordner / "gross.eml").open("wb") as f:
        f.truncate(MAX_BYTES + 10)                                    # Sparse-Datei: kostet keinen Platz
    gelesen = []
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: gelesen.append(self.name) or original(self))
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert gelesen == [] and stat["fehlerhaft"] == 1 and "Mail zu groß" in stat["fehler"][0] and (ordner / "fehlerhaft" / "gross.eml").is_file()


def test_fehler_bei_einer_datei_haelt_die_uebrigen_nicht_auf(cfg, db, ordner, monkeypatch):
    (ordner / "a.eml").write_bytes(nachgebildet_ka_mail())
    (ordner / "b.eml").write_bytes(nachgebildet_md_mail())
    original = MailEingang.lese

    def lese_mit_fehler(self, rohdaten):
        if rohdaten.name == "a.eml":
            raise RuntimeError("unerwartet: " + EMPFAENGER)
        return original(self, rohdaten)

    monkeypatch.setattr(MailEingang, "lese", lese_mit_fehler)
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert (stat["dateien"], stat["fehlerhaft"], stat["neu"]) == (2, 1, 2) and (ordner / "a.eml").is_file() and not (ordner / "b.eml").exists()
    assert "RuntimeError" in stat["fehler"][0] and EMPFAENGER not in stat["fehler"][0]          # nur der Fehlertyp, nicht sein Text


def test_gleiche_mail_zweimal_ist_bekannt(cfg, db, ordner):
    imp = Importer(cfg, db)
    (ordner / "mail.eml").write_bytes(nachgebildet_ka_mail())
    erste = imp.importiere_mails(ordner)
    historie = (anzahl(db, "beobachtungen"), anzahl(db, "preis_historie"))
    (ordner / "mail.eml").write_bytes(nachgebildet_ka_mail())
    zweite = imp.importiere_mails(ordner)
    assert (erste["neu"], erste["bekannt"], zweite["neu"], zweite["bekannt"], zweite["preis"]) == (3, 0, 0, 3, 0)
    assert (anzahl(db, "beobachtungen"), anzahl(db, "preis_historie")) == historie
    assert anzahl(db, "anzeigen") == 3
    assert (ordner / "eingelesen" / date.today().isoformat() / "mail_2.eml").is_file()


def test_preissenkung_ueber_mail(cfg, db, ordner):
    imp = Importer(cfg, db)
    (ordner / "m1.eml").write_bytes(nachgebildet_ka_mail())
    imp.importiere_mails(ordner)
    guenstiger = [{**KA_ANZEIGEN[0], "preis": 36000}, *KA_ANZEIGEN[1:]]
    (ordner / "m2.eml").write_bytes(mail_aus(KA_ABSENDER, nachgebildet_ka_html(guenstiger)))
    stat = imp.importiere_mails(ordner)
    assert (stat["neu"], stat["preis"], stat["bekannt"]) == (0, 1, 2)
    assert zeile(db, "3500000101")["preis"] == 36000 and zeile(db, "3500000101")["preis_vorher"] == 38500


def test_kanal_email_und_art_hoechstens_vorlaeufig(cfg, db, ordner):
    (ordner / "k.eml").write_bytes(nachgebildet_ka_mail())
    (ordner / "m.eml").write_bytes(nachgebildet_md_mail())
    Importer(cfg, db).importiere_mails(ordner)
    assert {r[0] for r in db.con.execute("SELECT kanal FROM beobachtungen")} == {"email"} and anzahl(db, "beobachtungen") == 5
    assert {r[0] for r in db.con.execute("SELECT kanal FROM preis_historie")} == {"email"}
    for z in db.con.execute("SELECT * FROM anzeigen"):
        assert import_art(z["suche"])[1] != BESTAETIGT and z["gewerblich"] is None and z["detail_geladen"] == 0
    assert import_art(zeile(db, "3500000102")["suche"]) == ("Kastenwagen", "vorlaeufig")      # Titel nennt genau eine Art
    assert import_art(zeile(db, "md-3900000011")["suche"]) == ("Kastenwagen", "vorlaeufig")


def test_gleiche_id_wie_seitenimport_ist_eine_zeile(cfg, db, ads, ordner, tmp_path):
    seiten = tmp_path / "seiten"
    seiten.mkdir()
    imp = Importer(cfg, db, abruf=KeinNetz())
    # Kleinanzeigen: Detailseite, dann dieselbe Anzeige per Mail
    a = ads[0]
    (seiten / "detail.html").write_text(detailseite(a), encoding="utf-8")
    # mobile.de: Suchseite mit md-3900000011 und md-3900000012
    (seiten / "md.html").write_text(MD_SEITE.read_text(encoding="utf-8"), encoding="utf-8")
    imp.importiere_seiten(seiten)
    vorher = anzahl(db, "anzeigen")
    ka = [{"id": a["id"], "slug": a["slug"], "titel": a["titel"], "preis": a["preis"], "plz": a["plz"], "ort": a["ort"]}]
    (ordner / "ka.eml").write_bytes(mail_aus(KA_ABSENDER, nachgebildet_ka_html(ka)))
    (ordner / "md.eml").write_bytes(nachgebildet_md_mail())
    stat = imp.importiere_mails(ordner)
    assert (stat["neu"], stat["bekannt"]) == (0, 3) and anzahl(db, "anzeigen") == anzahl(db, "inserate") == vorher
    plattformen = db.con.execute("SELECT plattform FROM inserate WHERE anzeigen_id IN (?, 'md-3900000011')", (a["id"],))
    assert {r[0] for r in plattformen} == {"kleinanzeigen", "mobile.de"}
    assert zeile(db, a["id"])["detail_geladen"] == 1                      # die Mail überschreibt die Detailangaben der Seite nicht


def test_max_dateien_und_uebrig(cfg, db, ordner):
    for n in range(3):
        (ordner / f"m{n}.eml").write_bytes(mail_aus(KA_ABSENDER, nachgebildet_ka_html([{**KA_ANZEIGEN[0], "id": str(3500002000 + n)}])))
    stat = Importer(cfg, db).importiere_mails(ordner, max_dateien=2)
    assert (stat["dateien"], stat["uebrig"], stat["neu"]) == (2, 1, 2) and (ordner / "m2.eml").is_file()
    stat = Importer(cfg, db).importiere_mails(ordner, max_sekunden=0)
    assert stat["dateien"] == 1 and stat["neu"] == 1


def test_hinweise_landen_im_protokoll_ohne_den_import_zu_stoppen(cfg, db, ordner):
    html = nachgebildet_ka_html(KA_ANZEIGEN[:1]).replace("</table>", '</table><a href="https://evil.example.com/s-anzeige/x/3500000191-220-1">x</a>')
    (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html))
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert stat["neu"] == 1 and stat["fehlerhaft"] == 0 and any("fremden Hosts verworfen" in f for f in stat["fehler"])


def test_keine_adressen_und_keine_links_in_der_datenbank(cfg, db, ordner):
    (ordner / "k.eml").write_bytes(nachgebildet_ka_mail())
    (ordner / "m.eml").write_bytes(nachgebildet_md_mail())
    Importer(cfg, db).importiere_mails(ordner)
    db.con.commit()
    alles = "\n".join(db.con.iterdump())
    for verboten in (EMPFAENGER, "max.mustermann", KA_ABSENDER, "noreply-test", MD_ABSENDER, "suchagent-test", "Hallo Max", "uid=ABC123", "GEHEIM",
                     "utm_", "searchId", "Albert-Einstein-Ring", "Neue Anzeigen für Deinen Suchauftrag"):
        assert verboten not in alles, verboten


def test_datenqualitaet_der_nachgebildeten_mails():
    ka = datenqualitaet(lese(nachgebildet_ka_mail()).inserate)
    md = datenqualitaet(lese(nachgebildet_md_mail()).inserate)
    assert ka == {"titel": 1.0, "preis": 1.0, "ez": 0.0, "km": 0.0, "plz": 1.0, "anbieter_bekannt": 0.0}
    assert md == {"titel": 1.0, "preis": 1.0, "ez": 1.0, "km": 1.0, "plz": 1.0, "anbieter_bekannt": 0.0}
    assert datenqualitaet([])["preis"] == 0.0


def test_eml_dateien_nur_eml_nicht_rekursiv(tmp_path):
    (tmp_path / "B.EML").write_bytes(b"x")
    (tmp_path / "a.eml").write_bytes(b"x")
    (tmp_path / "seite.html").write_bytes(b"x")
    (tmp_path / "unter").mkdir()
    (tmp_path / "unter" / "c.eml").write_bytes(b"x")
    assert [p.name for p in eml_dateien(tmp_path)] == ["a.eml", "B.EML"] and eml_dateien(tmp_path / "gibtsnicht") == []


def test_mail_ordner_ist_unterordner_des_import_ordners(cfg, tmp_path):
    cfg["import"] = {"ordner": str(tmp_path / "x")}
    assert mail_ordner(cfg) == (tmp_path / "x").resolve() / "email"


# ---------- Datenschutz-Frist ----------
def setze_alter(pfad: Path, tage: float):
    t = time.time() - tage * 86400
    os.utime(pfad, (t, t))


def test_importierte_mail_traegt_die_zeit_des_einlesens(cfg, db, ordner):
    datei = ordner / "alt.eml"
    datei.write_bytes(nachgebildet_ka_mail())
    setze_alter(datei, 800)                                           # lange vor dem Einlesen gespeichert
    Importer(cfg, db).importiere_mails(ordner)
    (eingelesen,) = (ordner / "eingelesen").glob("*/alt.eml")
    assert time.time() - eingelesen.stat().st_mtime < 3600


def test_mails_nach_frist_loescht_alles_abgelegte_nur_wenn_alt(tmp_path):
    mails = tmp_path / "email"
    alt, frisch = mails / "eingelesen" / "2025-01-02" / "alt.eml", mails / "eingelesen" / "2026-10-10" / "frisch.eml"
    gemischt = mails / "eingelesen" / "2025-02-02"
    ne_alt, ne_frisch = mails / "nicht_erkannt" / "alt.eml", mails / "nicht_erkannt" / "frisch.eml"
    fe_alt, fe_frisch = mails / "fehlerhaft" / "alt.eml", mails / "fehlerhaft" / "frisch.eml"
    sonst = [mails / "eingelesen" / "2025-01-02" / "notiz.txt", mails / "offen.eml", mails / "anderes" / "alt.eml"]
    for p in [alt, frisch, gemischt / "alt2.eml", gemischt / "frisch2.eml", ne_alt, ne_frisch, fe_alt, fe_frisch, *sonst]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    jetzt = datetime(2026, 10, 17, 12, 0)
    for p in [alt, gemischt / "alt2.eml", ne_alt, fe_alt, *sonst]:
        os.utime(p, (datetime(2025, 1, 5).timestamp(),) * 2)
    for p in [frisch, gemischt / "frisch2.eml", ne_frisch, fe_frisch]:
        os.utime(p, (datetime(2026, 10, 10).timestamp(),) * 2)
    assert datenrechte.mails_nach_frist(mails, 0, jetzt) == 0 and alt.exists()                       # 0 = aus
    assert datenrechte.mails_nach_frist(mails, 6, jetzt) == 4
    assert not any(p.exists() for p in (alt, gemischt / "alt2.eml", ne_alt, fe_alt))
    assert all(p.exists() for p in (frisch, gemischt / "frisch2.eml", ne_frisch, fe_frisch))         # frische bleiben
    assert all(p.exists() for p in sonst)                                                            # unverarbeitete, fremde Ordner, Nicht-.eml
    assert datenrechte.mails_nach_frist(tmp_path / "gibtsnicht", 6, jetzt) == 0


def test_frist_massgeblich_ist_das_spaetere_von_datumsordner_und_mtime(tmp_path):
    mails = tmp_path / "email" / "eingelesen"
    jetzt = datetime(2026, 10, 17, 12, 0)
    alte_datei_neuer_ordner = mails / "2026-10-10" / "a.eml"        # lange vor dem Einlesen gespeichert, vor einer Woche eingelesen
    neue_datei_alter_ordner = mails / "2025-01-02" / "b.eml"        # nachträglich angefasst
    ordnername_kaputt = mails / "kein-datum" / "c.eml"
    for p in (alte_datei_neuer_ordner, neue_datei_alter_ordner, ordnername_kaputt):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
    os.utime(alte_datei_neuer_ordner, (datetime(2020, 1, 1).timestamp(),) * 2)
    os.utime(neue_datei_alter_ordner, (datetime(2026, 10, 15).timestamp(),) * 2)
    os.utime(ordnername_kaputt, (datetime(2020, 1, 1).timestamp(),) * 2)
    assert datenrechte.mails_nach_frist(tmp_path / "email", 6, jetzt) == 1
    assert alte_datei_neuer_ordner.exists() and neue_datei_alter_ordner.exists() and not ordnername_kaputt.exists()   # Rückfall: mtime


def test_leerer_datumsordner_verschwindet(tmp_path):
    eingelesen = tmp_path / "email" / "eingelesen"
    (eingelesen / "2025-01-02").mkdir(parents=True)
    datei = eingelesen / "2025-01-02" / "alt.eml"
    datei.write_bytes(b"x")
    setze_alter(datei, 800)
    assert datenrechte.mails_nach_frist(tmp_path / "email", 6) == 1 and not (eingelesen / "2025-01-02").exists() and eingelesen.is_dir()


def test_frist_folgt_keinen_verknuepfungen(tmp_path):
    mails = tmp_path / "email"
    fremd = tmp_path / "fremd"
    (mails / "eingelesen").mkdir(parents=True)
    fremd.mkdir()
    wichtig, ziel_datei = fremd / "wichtig.eml", tmp_path / "ziel.eml"
    wichtig.write_bytes(b"x")
    ziel_datei.write_bytes(b"x")
    for p in (wichtig, ziel_datei):
        os.utime(p, (0, 0))
    (mails / "eingelesen" / "2020-01-01").symlink_to(fremd, target_is_directory=True)      # Datumsordner als Verknüpfung
    (mails / "nicht_erkannt").mkdir()
    (mails / "nicht_erkannt" / "link.eml").symlink_to(ziel_datei)                          # Datei als Verknüpfung
    assert datenrechte.mails_nach_frist(mails, 6) == 0
    assert wichtig.exists() and ziel_datei.exists() and (mails / "nicht_erkannt" / "link.eml").is_symlink()
    (mails / "fehlerhaft").symlink_to(fremd, target_is_directory=True)                      # ganze Ablage als Verknüpfung
    assert datenrechte.mails_nach_frist(mails, 6) == 0 and wichtig.exists()


def test_unverarbeitete_mails_werden_gemeldet_aber_nicht_geloescht(tmp_path):
    mails = tmp_path / "email"
    mails.mkdir()
    alt, neu = mails / "alt.eml", mails / "neu.eml"
    alt.write_bytes(b"x")
    neu.write_bytes(b"x")
    setze_alter(alt, 400)
    assert datenrechte.mails_unverarbeitet(mails, 6) == 1 and datenrechte.mails_unverarbeitet(mails, 0) == 0
    assert datenrechte.mails_nach_frist(mails, 6) == 0 and alt.exists()


def test_frist_anwenden_loescht_mails_nach_konfigurierter_frist(cfg, db, tmp_path, caplog):
    cfg["import"] = {"ordner": "import"}                               # relativ zu `basis`, nicht zum echten Projektordner
    basis = tmp_path
    mails = mail_ordner(cfg, basis)
    assert mails == tmp_path / "import" / "email"
    alt, frisch, offen = mails / "eingelesen" / "2025-01-02" / "alt.eml", mails / "eingelesen" / "2026-10-10" / "frisch.eml", mails / "offen.eml"
    for p in (alt, frisch, offen):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    setze_alter(alt, 400)
    setze_alter(frisch, 3)
    setze_alter(offen, 400)
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 0}
    datenrechte.frist_anwenden(db, cfg, basis, tmp_path / "fotos")
    assert alt.exists()                                               # Standard: keine Frist
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 6}
    with caplog.at_level("WARNING", logger="scout"):
        datenrechte.frist_anwenden(db, cfg, basis, tmp_path / "fotos")
    assert not alt.exists() and frisch.exists() and offen.exists()
    assert any("unverarbeitet" in r.getMessage() for r in caplog.records)


# ---------- K1: Reihenfolge und Alter der Mails ----------
def _ka_mail_mit(preis: int, datum: str) -> bytes:
    a = [{**KA_ANZEIGEN[0], "preis": preis}]
    return nachgebildet_mail(KA_ABSENDER, "Suchauftrag", nachgebildet_ka_html(a), nachgebildet_ka_text(a), datum=datum).as_bytes()


def _preis_und_historie(db, ad_id):
    return tuple(db.con.execute("SELECT preis, preis_vorher FROM anzeigen WHERE id=?", (ad_id,)).fetchone())


def test_alte_mail_nach_neuerer_beobachtung_aendert_den_preis_nicht(cfg, db, ordner):
    ad = KA_ANZEIGEN[0]["id"]
    (ordner / "neu.eml").write_bytes(_ka_mail_mit(27600, "Sat, 17 Oct 2026 08:15:00 +0200"))
    assert Importer(cfg, db).importiere_mails(ordner)["neu"] == 1
    vorher = _preis_und_historie(db, ad)
    (ordner / "alt.eml").write_bytes(_ka_mail_mit(25000, "Mon, 21 Sep 2026 08:15:00 +0200"))
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert stat["preis"] == 0 and stat["aeltere"] == 1
    assert any("älteren Mails" in f for f in stat["fehler"])
    assert _preis_und_historie(db, ad) == vorher == (27600, None)                      # keine Preissenkung


def test_mails_werden_nach_datum_nicht_nach_namen_gelesen(cfg, db, ordner):
    ad = KA_ANZEIGEN[0]["id"]
    (ordner / "a_neu.eml").write_bytes(_ka_mail_mit(24000, "Sat, 17 Oct 2026 08:15:00 +0200"))
    (ordner / "b_alt.eml").write_bytes(_ka_mail_mit(29900, "Mon, 21 Sep 2026 08:15:00 +0200"))
    Importer(cfg, db).importiere_mails(ordner)
    assert _preis_und_historie(db, ad)[0] == 24000                                     # der neuere Preis gewinnt
