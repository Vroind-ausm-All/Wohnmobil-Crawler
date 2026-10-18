"""E-Mail-Eingang, Härtung nach QA-Runde 1 (P2-06): Laufzeitgrenzen, Preisregeln, Gesuche, Empfehlungsblöcke, „Mail ergänzt nur“, Fristen.

Alle Mails sind NACHGEBILDET (tests/nachgebildet_mails.py); die Zeitgrenzen sind großzügig (Rechner und CI schwanken), sie trennen
„Sekunden“ von den früheren Minuten bzw. Stunden.
"""
import os
import time
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest

from tests.nachgebildet_mails import KA_ABSENDER, KA_ANZEIGEN, ka_link, nachgebildet_ka_html, nachgebildet_md_text
from tests.test_email_eingang import KeinNetz, kein_netz, lese, ka_mail, mail_aus, nach_id, zeile  # noqa: F401 – kein_netz ist eine autouse-Fixture
from tests.test_seitenimport import detailseite
from wmscout.eingang import Rohdaten
from wmscout.eingang.email import MAX_BYTES, MailEingang, MailFehler, eml_dateien, kleinanzeigen, mail_ordner, mobilede, verschiebe_mail, zerlege
from wmscout.eingang.email import htmlbaum
from wmscout.eingang.email.treffer import LinkZaehler, html_bloecke
from wmscout.importer import Importer

@pytest.fixture
def ordner(cfg, tmp_path):
    cfg["import"] = {"ordner": str(tmp_path / "import")}
    cfg["eingaenge"] = {"email": {"aktiv": True}}                      # Standard ist aus (ADR-036)
    o = mail_ordner(cfg)
    o.mkdir(parents=True)
    return o


KOPF = b"From: a@mail.kleinanzeigen.de\r\nSubject: x\r\n"


def link(n: int) -> str:
    return f"https://www.kleinanzeigen.de/s-anzeige/x/{3500000000 + n}-220-1"


def html_mail(html: str) -> bytes:
    return KOPF + b"Content-Type: text/html; charset=utf-8\r\n\r\n" + html.encode("utf-8")


def text_mail(text: str) -> bytes:
    return KOPF + b"Content-Type: text/plain; charset=utf-8\r\n\r\n" + text.encode("utf-8")


def zeitlich(f, grenze=15.0):
    start = time.monotonic()
    try:
        return f()
    finally:
        assert time.monotonic() - start < grenze, "zu langsam"


def preise(html: str):
    return [(i.preis, i.vb) for i in lese(ka_mail(html)).inserate]


def karte(titel: str, *zeilen: str, n: int = 101) -> str:
    return f'<body><table><tr><td><a href="{link(n)}">{titel}</a>' + "".join(f"<br>{z}" for z in zeilen) + "</td></tr></table></body>"


# ---------- H1: Laufzeit bei vielen Links ----------
def test_viele_leere_links_auf_dieselbe_anzeige():
    anker = f'<a href="{link(101)}"></a>'
    lesung = zeitlich(lambda: lese(html_mail("<div>" + anker * 10_000 + "</div>")), 5)
    assert [i.anzeigen_id for i in lesung.inserate] == ["3500000101"]


def test_viele_leere_links_auf_200_anzeigen():
    html = "<div>" + "".join(f'<a href="{link(n % 200)}"></a>' for n in range(20_000)) + "</div>"
    lesung = zeitlich(lambda: lese(html_mail(html)), 10)
    assert len(lesung.inserate) == 200


def test_budget_bricht_ueberladene_mails_ab():
    with pytest.raises(MailFehler, match="zu aufwendig"):
        htmlbaum.Budget(10).verbrauche(11)
    baum = zerlege(html_mail(nachgebildet_ka_html())).html_baum
    with pytest.raises(MailFehler, match="zu aufwendig"):
        html_bloecke(baum, kleinanzeigen.PROFIL, LinkZaehler(), htmlbaum.Budget(5))


def test_zu_viele_elemente_und_zu_tiefe_ebenen_werden_abgelehnt():
    with pytest.raises(MailFehler, match="Elemente"):
        zeitlich(lambda: lese(html_mail("<i>x</i>" * 150_000)), 10)
    with pytest.raises(MailFehler, match="Ebenen"):
        lese(html_mail("<b>" * 1000))                                 # nie geschlossen: immer tiefer


# ---------- H2: Textzeilen ----------
def test_zeile_aus_eckigen_klammern_ist_nicht_quadratisch():
    text = link(101) + "\n" + "[" * 200_000
    lesung = zeitlich(lambda: lese(text_mail(text)), 5)
    assert [i.anzeigen_id for i in lesung.inserate] == ["3500000101"] and any("überlange Textzeile" in h for h in lesung.hinweise)
    zeitlich(lambda: lese(text_mail(link(101) + "\n" + "[" * 4_900_000)), 5)
    zeitlich(lambda: lese(text_mail("Titel\n" + "1.000" * 200_000 + "\n" + link(101) + "\n")), 5)


def test_markdown_link_wird_gelesen():
    text = f"Hymer B 544\n38.500 €\n70173 Stuttgart\n[Anzeige ansehen]({link(101)})\n"
    (i,) = lese(text_mail(text)).inserate
    assert (i.anzeigen_id, i.titel, i.preis, i.ort) == ("3500000101", "Hymer B 544", 38500, "70173 Stuttgart")


# ---------- H3: Kopf und MIME ----------
@pytest.mark.parametrize("kopf", [
    b"Subject: " + b"=?utf-8?q?a?= " * 40_000,                         # früher > 6 GB Speicher
    b"From: " + b"a@b.de, " * 20_000,                                  # früher quadratisch
    b"Subject: " + b"a " * 2_400_000,
    b"".join(b"X-H%d: v\r\n" % i for i in range(100_000)),
], ids=["encoded_words", "viele_adressen", "langer_betreff", "viele_kopfzeilen"])     # kurze IDs: Windows begrenzt PYTEST_CURRENT_TEST auf 32 767 Zeichen
def test_riesige_kopfzeilen_werden_sofort_abgelehnt(kopf):
    with pytest.raises(MailFehler, match="Kopf"):
        zeitlich(lambda: zerlege(b"From: a@mail.kleinanzeigen.de\r\n" + kopf + b"\r\n\r\nx"), 2)


def test_einzelne_zu_lange_kopfzeile():
    with pytest.raises(MailFehler, match="Kopfzeile zu lang"):
        zerlege(b"From: a@mail.kleinanzeigen.de\r\nX-Lang: " + b"a" * 9000 + b"\r\n\r\nx")


def test_viele_mime_teile_und_tiefe_verschachtelung():
    teile = b"".join(b"--B\r\nContent-Type: text/plain\r\n\r\nx\r\n" for _ in range(100_000))
    with pytest.raises(MailFehler, match="MIME-Teile"):
        zeitlich(lambda: zerlege(KOPF + b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n' + teile + b"--B--\r\n"), 2)
    tief = b"".join(b'--B%d\r\nContent-Type: multipart/mixed; boundary="B%d"\r\n\r\n' % (i, i + 1) for i in range(40))
    with pytest.raises(MailFehler, match="verschachtelt"):
        zerlege(KOPF + b'Content-Type: multipart/mixed; boundary="B0"\r\n\r\n' + tief + b"x")


def test_from_mit_vielen_klammern_ist_kein_absturz():
    daten = b"From: " + b"(" * 8000 + b"a@mail.kleinanzeigen.de\r\nSubject: x\r\n\r\nx"
    zerlege(daten)                                                     # RecursionError wird MailFehler bzw. gar kein Fehler
    daten = b"From: " + b"(" * 2000 + b"a@mail.kleinanzeigen.de\r\n\r\nx"
    assert zerlege(daten).absender_domain in (None, "mail.kleinanzeigen.de")


def test_datum_und_absender_ohne_policy_default():
    mail = zerlege(b"From: =?utf-8?q?M=C3=BCller?= <info@Mail.Kleinanzeigen.de>\r\nDate: Sat, 17 Oct 2026 08:15:00 +0200\r\n\r\nx")
    assert mail.absender_domain == "mail.kleinanzeigen.de" and mail.datum.utcoffset().total_seconds() == 7200
    kaputt = zerlege(b"From: a@b.de\r\nDate: 99 Foo 99999 99:99\r\n\r\nx")
    assert kaputt.datum is None and "Datum der Mail nicht lesbar" in kaputt.hinweise


# ---------- H4: Preise ----------
def test_betrag_im_titel_ist_kein_preis():
    assert preise(karte("Hymer B544 2.000 € unter NP", "VB", "70173 Stuttgart")) == [(None, None)]
    assert preise(karte("Hymer B544", "Neupreis 60.000 €", "VB")) == [(None, None)]
    assert preise(karte("Hymer B544 für 5.000 € Anzahlung reserviert", "70173 Stuttgart")) == [(None, None)]


def test_preis_nur_aus_eigener_preiszeile():
    assert preise(karte("Hymer", "38.500 €")) == [(38500, False)]
    assert preise(karte("Hymer", "38.500 € VB")) == [(38500, True)]
    assert preise(karte("Hymer", "VB 38.500 €")) == [(38500, True)]
    assert preise(karte("Hymer", "Preis: 38.500,00 €")) == [(38500, False)]
    assert preise(karte("Hymer", "38.500 €", "VB")) == [(38500, True)]                     # VB in der Zeile danach
    assert preise(karte("Hymer", "EUR 38.500")) == [(38500, False)]


def test_durchgestrichener_preis_zaehlt_nicht():
    assert preise(karte("Hymer", "<s>40.000 €</s> 35.000 €")) == [(35000, False)]
    assert preise(karte("Hymer", "<del>40.000 €</del><br>35.000 €")) == [(35000, False)]
    assert preise(karte("Hymer", '<span style="text-decoration: line-through">40.000 €</span> 35.000 €')) == [(35000, False)]
    assert preise(karte("Hymer", "40.000 € 35.000 €")) == [(None, None)]                  # zwei Beträge in einer Zeile
    assert preise(karte("Hymer", "<strike>40.000 €</strike>")) == [(None, None)]


def test_mehrere_oder_unplausible_preiszeilen_ergeben_keinen_preis():
    assert preise(karte("Hymer", "38.500 €", "36.000 €")) == [(None, None)]
    assert preise(karte("Hymer", "1 €")) == [(None, None)]
    assert preise(karte("Hymer", "5.000.000 €")) == [(None, None)]
    assert preise(karte("Hymer", "Statt", "40.000 €")) == [(None, None)]                  # Zeile davor entwertet den Betrag
    assert preise(karte("Wohnmobil mieten pro Tag", "89 €")) == [(None, None)]
    assert preise(karte("Hymer", "Zu verschenken")) == [(None, None)]


def test_ohne_preis_kein_falscher_preis_und_keine_preissenkung_in_der_db(cfg, db, ads, importiert, ordner):
    a = ads[0]
    vorher = dict(db.con.execute("SELECT preis, preis_vorher, vb FROM anzeigen WHERE id=?", (a["id"],)).fetchone())
    historie = db.con.execute("SELECT COUNT(*) FROM preis_historie").fetchone()[0]
    html = (f'<body><table><tr><td><a href="https://www.kleinanzeigen.de/s-anzeige/x/{a["id"]}-220-1">{a["titel"]} 2.000 € unter NP</a>'
            "<br>VB<br>70173 Stuttgart</td></tr></table></body>")
    (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html))
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert (stat["neu"], stat["preis"], stat["bekannt"]) == (0, 0, 1)
    assert dict(db.con.execute("SELECT preis, preis_vorher, vb FROM anzeigen WHERE id=?", (a["id"],)).fetchone()) == vorher
    assert db.con.execute("SELECT COUNT(*) FROM preis_historie").fetchone()[0] == historie
    assert any("ohne eindeutige Preiszeile" in f for f in stat["fehler"])


def test_vb_der_mail_ueberschreibt_nichts_ohne_preiszeile(cfg, db, ads, importiert, ordner):
    a = ads[1]
    db.con.execute("UPDATE anzeigen SET vb=1 WHERE id=?", (a["id"],))
    db.con.commit()
    html = karte(a["titel"], "70173 Stuttgart", n=1).replace(link(1), f"https://www.kleinanzeigen.de/s-anzeige/x/{a['id']}-220-1")
    (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html))
    Importer(cfg, db).importiere_mails(ordner)
    assert db.con.execute("SELECT vb FROM anzeigen WHERE id=?", (a["id"],)).fetchone()[0] == 1


def test_echte_preissenkung_in_der_mail_wird_erkannt(cfg, db, ads, importiert, ordner):
    a = ads[2]
    html = karte(a["titel"], f"{a['preis'] - 1000:,}".replace(",", ".") + " €", n=1).replace(link(1), f"https://www.kleinanzeigen.de/s-anzeige/x/{a['id']}-220-1")
    (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html, datum=format_datetime(datetime.now(timezone.utc))))  # neuer als der Suchlauf (K1)
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert stat["preis"] == 1 and zeile(db, a["id"])["preis_vorher"] == a["preis"]


# ---------- M1: eine Mail ergänzt nur ----------
def test_seite_mail_seite_mail_ohne_zusaetzliche_beobachtungen(cfg, db, ads, ordner, tmp_path):
    seiten = tmp_path / "seiten"
    seiten.mkdir()
    imp = Importer(cfg, db, abruf=KeinNetz())
    a = ads[0]

    def beobachtungen():
        return db.con.execute("SELECT COUNT(*) FROM beobachtungen").fetchone()[0]

    def seite():
        (seiten / "d.html").write_text(detailseite(a), encoding="utf-8")
        imp.importiere_seiten(seiten)

    def mail(titel):
        html = karte(titel, f"{a['preis']:,}".replace(",", ".") + " € VB", "70173 Stuttgart", n=1)
        (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html.replace(link(1), f"https://www.kleinanzeigen.de/s-anzeige/x/{a['id']}-220-1")))
        imp.importiere_mails(ordner)

    seite()
    mail(a["titel"][:12] + "…")                                          # die erste Mail darf leere Felder füllen (Ort)
    ausgang = dict(zeile(db, a["id"]))
    n = beobachtungen()
    seite()
    mail("Ganz anderer Titel")
    seite()
    assert beobachtungen() == n                                          # kein „geaendert“ ohne echte Änderung
    jetzt = dict(zeile(db, a["id"]))
    for feld in ("url", "titel", "ort", "vb", "km", "ez_jahr", "marke", "preis"):
        assert jetzt[feld] == ausgang[feld], feld


def test_mail_fuellt_nur_leere_felder_und_neue_zeilen(cfg, db, ordner):
    neu = f"https://www.kleinanzeigen.de/s-anzeige/x/{3500000999}-220-1"
    html = f'<body><table><tr><td><a href="{neu}">Knaus Sky TI</a><br>38.500 € VB<br>70173 Stuttgart<br>EZ 03/2018 • 80.000 km</td></tr></table></body>'
    (ordner / "m.eml").write_bytes(mail_aus(KA_ABSENDER, html))
    imp = Importer(cfg, db)
    imp.importiere_mails(ordner)
    z = zeile(db, "3500000999")
    assert (z["titel"], z["preis"], z["ort"], z["vb"], z["km"], z["ez_jahr"]) == ("Knaus Sky TI", 38500, "70173 Stuttgart", 1, 80000, 2018)
    assert z["url"] == "https://www.kleinanzeigen.de/s-anzeige/3500000999"
    db.con.execute("UPDATE anzeigen SET ort=NULL, km=NULL WHERE id='3500000999'")
    db.con.commit()
    (ordner / "m2.eml").write_bytes(mail_aus(KA_ABSENDER, html.replace("Knaus Sky TI", "Anderer Titel").replace("80.000 km", "90.000 km")))
    imp.importiere_mails(ordner)
    z = zeile(db, "3500000999")
    assert (z["titel"], z["ort"], z["km"]) == ("Knaus Sky TI", "70173 Stuttgart", 90000)       # leere Felder gefüllt, vorhandene bleiben


# ---------- M2: Ablage und Frist ----------
def test_ablage_setzt_aenderungszeit_und_kennt_namenskonflikte(tmp_path):
    quelle, ziel = tmp_path / "email", tmp_path / "email" / "fehlerhaft"
    quelle.mkdir()
    (quelle / "a.eml").write_bytes(b"neu")
    (quelle / "a_files").mkdir()
    ziel.mkdir()
    (ziel / "a.eml").write_bytes(b"ALT")
    os.utime(quelle / "a.eml", (0, 0))
    neu = verschiebe_mail(quelle / "a.eml", ziel)
    assert neu.name == "a_2.eml" and neu.read_bytes() == b"neu" and (ziel / "a.eml").read_bytes() == b"ALT"
    assert time.time() - neu.stat().st_mtime < 3600                    # Frist zählt ab Ablage
    assert (quelle / "a_files").is_dir() and not (ziel / "a_files").exists()       # kein Begleitordner


def test_unlesbare_mails_wandern_nach_fehlerhaft_mit_aktueller_zeit(cfg, db, ordner):
    datei = ordner / "kaputt.eml"
    datei.write_bytes(b"\x00\x01 kaputt")
    os.utime(datei, (0, 0))
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert stat["fehlerhaft"] == 1 and not datei.exists()
    abgelegt = ordner / "fehlerhaft" / "kaputt.eml"
    assert abgelegt.is_file() and time.time() - abgelegt.stat().st_mtime < 3600


# ---------- N2: Verknüpfungen ----------
def test_verknuepfungen_werden_nicht_gelesen_oder_verschoben(cfg, db, ordner, tmp_path):
    geheim = tmp_path / "geheim.eml"
    geheim.write_bytes(mail_aus(KA_ABSENDER, nachgebildet_ka_html()))
    (ordner / "link.eml").symlink_to(geheim)
    (ordner / "verz.eml").mkdir()
    assert eml_dateien(ordner) == []
    stat = Importer(cfg, db).importiere_mails(ordner)
    assert stat["dateien"] == 0 and geheim.exists() and (ordner / "link.eml").is_symlink()


# ---------- M3: Gesuche und Ankauf ----------
@pytest.mark.parametrize("titel", ["Ankauf Wohnmobile aller Art – zahle bar", "Wohnmobil gesucht", "Kaufe Wohnmobil sofort", "Suche Wohnmobil bis 30.000 €",
                                   "Wir kaufen Ihr Wohnmobil", "Wohnmobil-Ankauf zu Höchstpreisen", "‮Kaufe Wohnmobil sofort‬"])
def test_gesuche_und_ankaufsanzeigen_werden_nicht_gespeichert(titel):
    lesung = lese(ka_mail(karte(titel, "30.000 €")))
    assert lesung.art == "unbekannt" and lesung.inserate == [] and any("Gesuch" in h for h in lesung.hinweise)


@pytest.mark.parametrize("titel", ["Suche neuen Besitzer für Hymer B 544", "Hymer B 544 zu verkaufen – kein Ankauf durch Händler", "Hymer B 544",
                                                      "Kastenwagen Sucher-Dachträger"])
def test_verkaufsanzeigen_mit_gesuchsnahen_woertern_bleiben(titel):
    assert len(lese(ka_mail(karte(titel, "30.000 €"))).inserate) == 1


# ---------- M4: Empfehlungsblöcke ----------
def test_empfehlungsblock_wird_nicht_uebernommen():
    html = (f'<body><h2>Deine Treffer</h2><div><a href="{link(104)}">Hymer</a><p>40.000 €</p></div>'
            f'<h2>Das könnte dich auch interessieren</h2><div><a href="{link(105)}">Wohnwagen Tabbert</a><p>5.000 €</p></div></body>')
    lesung = lese(ka_mail(html))
    assert list(nach_id(lesung)) == ["3500000104"] and any("Empfehlungsblock" in h for h in lesung.hinweise)
    text = f"Hymer\n40.000 €\n{link(104)}\n\nÄhnliche Anzeigen\n\nTabbert\n5.000 €\n{link(105)}\n"
    lesung = lese(mail_aus(KA_ABSENDER, None, text))
    assert list(nach_id(lesung)) == ["3500000104"] and any("Empfehlungsblock" in h for h in lesung.hinweise)
    nur = f'<body><h3>Ähnliche Anzeigen</h3><div><a href="{link(105)}">Tabbert</a><p>5.000 €</p></div></body>'
    assert lese(ka_mail(nur)).art == "unbekannt"                       # nur Empfehlungen: nichts zu speichern


def test_ueberschrift_im_fliesstext_ist_kein_marker():
    html = (f'<body><div><a href="{link(104)}">Hymer</a><p>40.000 €</p></div><p>Ähnliche Anzeigen findest du in der App.</p>'
            f'<div><a href="{link(105)}">Knaus</a><p>5.000 €</p></div></body>')
    assert len(lese(ka_mail(html)).inserate) == 2


# ---------- M5: teilweiser Layoutfehler ----------
def test_teilweise_verdaechtiges_layout_wird_gemeldet():
    gut = lese(ka_mail(nachgebildet_ka_html()))
    assert not any("teilweise verdächtig" in h for h in gut.hinweise)
    schlecht = "<body>" + "".join(f'<div><a href="{ka_link(a)}">{a["titel"]}</a></div>' for a in KA_ANZEIGEN) + "</body>"
    lesung = lese(ka_mail(schlecht))
    assert len(lesung.inserate) == 3 and any("Layout teilweise verdächtig" in h for h in lesung.hinweise)


# ---------- N4/N5/N6 ----------
def test_bidi_steuerzeichen_werden_entfernt():
    (i,) = lese(ka_mail(karte("‮Hymer‬ B⁦ 544⁩", "30.000 €"))).inserate
    assert i.titel == "Hymer B 544"


def test_anzeigen_ids_nur_ascii_ziffern_ohne_fuehrende_null():
    def ids(url: str, parser=kleinanzeigen):
        return [i.anzeigen_id for i in parser.lese(zerlege(html_mail(f'<body><div><a href="{url}">T</a><p>30.000 €</p></div></body>'))).inserate]

    assert ids("https://www.kleinanzeigen.de/s-anzeige/x/3500000101-220-1") == ["3500000101"]
    for schlecht in ("https://www.kleinanzeigen.de/s-anzeige/x/0500000101-220-1", "https://www.kleinanzeigen.de/s-anzeige/x/٣٥٠٠٠٠٠١٠١-220-1",
                     "https://www.kleinanzeigen.de/s-anzeige/x/12345-220-1", "https://www.kleinanzeigen.de/s-anzeige/hilfe/3500000101",
                     "https://www.kleinanzeigen.de/s-anzeige/x/3500000101", "https://www.kleinanzeigen.de/hilfe/3500000101-220-1"):
        assert ids(schlecht) == [], schlecht
    assert ids("https://suchen.mobile.de/fahrzeuge/details.html?id=123456789", mobilede) == ["md-123456789"]
    for schlecht in ("https://suchen.mobile.de/fahrzeuge/details.html?id=０１２３４５６７８", "https://suchen.mobile.de/fahrzeuge/details.html?id=0123456789",
                     "https://suchen.mobile.de/fahrzeuge/details.html?id=1234"):
        assert ids(schlecht, mobilede) == [], schlecht


def test_verworfene_links_aus_html_und_text_werden_zusammen_gezaehlt():
    fremd1, fremd2 = "https://evil.example.com/s-anzeige/x/3500000191-220-1", "https://evil2.example.com/s-anzeige/x/3500000192-220-1"
    html = f'<body><div><a href="{link(101)}">Hymer</a><p>30.000 €</p></div><a href="{fremd1}">x</a></body>'
    text = f"Hymer\n30.000 €\n{link(101)}\n{fremd1}\n{fremd2}\n"
    lesung = lese(mail_aus(KA_ABSENDER, html, text))
    assert len(lesung.inserate) == 1 and "2 Anzeigenlink(s) auf fremden Hosts verworfen" in lesung.hinweise      # fremd1 nur einmal


def test_mobilede_text_wie_bisher():
    assert len(lese(mail_aus("x@mobile.de", None, nachgebildet_md_text())).inserate) == 2


def test_mailfehler_ist_valueerror_und_eingang_wirft_ihn():
    with pytest.raises(ValueError):
        MailEingang().lese(Rohdaten(b"x" * (MAX_BYTES + 1), "x.eml", datetime.now(timezone.utc)))
