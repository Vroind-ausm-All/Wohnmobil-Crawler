"""Import gespeicherter Kleinanzeigen-Seiten (P2-05, ADR-010): erkennen, speichern, verschieben – ohne Netzabruf.

Grenze: Die Seiten sind nachgebautes Markup aus tests/daten.py; echte, im Browser gespeicherte Seiten liegen noch nicht vor.
"""
import threading
from datetime import date

import pytest

from tests.daten import BASIS, detail_html, such_html
from tests.test_cli import _scout
from tests.test_handy import Client
from wmscout.app import erstelle_server
from wmscout.datenbank import IMPORT_SUCHE
from wmscout.bewertung.anschreiben import sperrgrund
from wmscout.bewertung.auswertung import bewerte_alle
from wmscout.bewertung.rechner import Rechner
from wmscout.datenbank import Datenbank
from wmscout.eingang import erkenne_seite, fahrzeugart_der_suchseite
from wmscout.normalisierung.fahrzeug import art_schluessel
from wmscout.importer import Importer
from wmscout.team import TeamSpeicher


class KeinNetz:
    """Abruf, der jeden Aufruf verweigert und mitzählt – beweist, dass der Import nichts abruft."""

    def __init__(self):
        self.abrufe = []

    def hole(self, url):
        self.abrufe.append(url)
        raise AssertionError(f"Netzabruf verboten: {url}")


def anzeige_url(a):
    return f"https://www.kleinanzeigen.de/s-anzeige/{a['slug']}/{a['id']}-220-1234"


def mit_kopf(html, kopf):
    return html.replace("<html>", f"<html><head><title>Kleinanzeigen</title>{kopf}</head>", 1)


def detailseite(a, art="canonical"):
    kopf = {"canonical": f'<link rel="canonical" href="{anzeige_url(a)}">',
            "og": f'<meta property="og:url" content="{anzeige_url(a)}">',
            "kopflink": f'<link rel="alternate" hreflang="de" href="{anzeige_url(a)}">'}[art]
    return mit_kopf(detail_html(a), kopf)


@pytest.fixture
def ordner(cfg, tmp_path):
    o = tmp_path / "import"
    o.mkdir()
    cfg["import"] = {"ordner": str(o)}
    return o


def eingelesen(ordner):
    return ordner / "eingelesen" / date.today().isoformat()


def zeile(db, ad_id):
    return db.con.execute("SELECT * FROM anzeigen WHERE id=?", (ad_id,)).fetchone()


def test_suchseite_wird_eingelesen_und_verschoben(cfg, db, ads, ordner):
    (ordner / "suche.html").write_text(such_html(ads[:25]), encoding="utf-8")
    (ordner / "notiz.txt").write_text("bleibt liegen", encoding="utf-8")
    netz = KeinNetz()
    stat = Importer(cfg, db, abruf=netz).importiere_seiten(ordner)
    assert stat == {"dateien": 1, "suchseiten": 1, "detailseiten": 0, "unbekannt": 0, "fehlerhaft": 0, "neu": 25,
                    "preis": 0, "bekannt": 0, "details": 0, "fehler": [], "uebrig": 0}
    assert netz.abrufe == []
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 25
    z = zeile(db, ads[0]["id"])
    assert z["quelle"] == "kleinanzeigen" and z["suche"] == IMPORT_SUCHE and z["preis"] == ads[0]["preis"]
    assert z["url"] == anzeige_url(ads[0]) and z["ez_jahr"] == ads[0]["ez"] and z["detail_geladen"] == 0
    assert not (ordner / "suche.html").exists() and (eingelesen(ordner) / "suche.html").is_file()
    assert (ordner / "notiz.txt").read_text(encoding="utf-8") == "bleibt liegen"


def test_erneuter_import_ohne_dubletten_und_preissenkung(cfg, db, ads, ordner):
    imp = Importer(cfg, db, abruf=KeinNetz())
    (ordner / "suche.html").write_text(such_html(ads[:25]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    (ordner / "suche.html").write_text(such_html(ads[:25]), encoding="utf-8")
    stat = imp.importiere_seiten(ordner)
    assert (stat["neu"], stat["preis"], stat["bekannt"]) == (0, 0, 25)
    assert db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 25
    assert (eingelesen(ordner) / "suche_2.html").is_file()                  # Namenskonflikt → Zähler

    guenstiger = [{**ads[0], "preis": ads[0]["preis"] - 1000}, *ads[1:25]]
    (ordner / "suche.html").write_text(such_html(guenstiger), encoding="utf-8")
    stat = imp.importiere_seiten(ordner)
    assert (stat["neu"], stat["preis"], stat["bekannt"]) == (0, 1, 24)
    z = zeile(db, ads[0]["id"])
    assert z["preis"] == ads[0]["preis"] - 1000 and z["preis_vorher"] == ads[0]["preis"]
    assert (eingelesen(ordner) / "suche_3.html").is_file()


def test_detailseite_bekannt_und_unbekannt(cfg, db, ads, ordner):
    imp = Importer(cfg, db, abruf=KeinNetz())
    (ordner / "suche.html").write_text(such_html(ads[:5]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["km"] is None                            # Suchliste liefert keinen km-Stand

    (ordner / "anzeige.html").write_text(detailseite(ads[0]), encoding="utf-8")
    (ordner / "neu.HTM").write_text(detailseite(ads[30], "og"), encoding="utf-8")
    stat = imp.importiere_seiten(ordner)
    assert stat["fehler"] == [] and (stat["detailseiten"], stat["details"], stat["neu"], stat["bekannt"]) == (2, 2, 1, 1)
    z = zeile(db, ads[0]["id"])
    assert z["detail_geladen"] == 1 and z["km"] == ads[0]["km"] and z["ez_jahr"] == ads[0]["ez"]
    assert "Kilometerstand" in z["details_json"] and z["beschreibung"] == ads[0]["lang"]
    z = zeile(db, ads[30]["id"])
    assert z is not None and z["detail_geladen"] == 1 and z["titel"] == ads[30]["titel"] and z["km"] == ads[30]["km"]
    assert z["url"] == anzeige_url(ads[30]) and z["suche"] == IMPORT_SUCHE and z["preis"] == ads[30]["preis"]
    assert (eingelesen(ordner) / "neu.HTM").is_file()


def test_erkennung():
    from tests.daten import baue_ads
    ads = baue_ads(5)
    assert erkenne_seite(detailseite(ads[0], "kopflink"))[0] == "detail"
    # Detailseite mit „ähnlichen Anzeigen“ (Trefferliste) bleibt eine Detailseite, wenn die canonical-URL eindeutig ist
    aehnlich = detailseite(ads[0]).replace("</body>", such_html(ads[1:4]).split("<body>")[1])
    art, inserate = erkenne_seite(aehnlich)
    assert art == "detail" and [i.anzeigen_id for i in inserate] == [ads[0]["id"]]
    gesuch = [{**ads[0], "titel": "Gesuch: suche Wohnmobil"}, *ads[1:3]]
    art, inserate = erkenne_seite(such_html(gesuch))
    assert art == "suche" and [i.anzeigen_id for i in inserate] == [a["id"] for a in ads[1:3]]
    assert all(i.quelle == "kleinanzeigen" for i in inserate)
    assert erkenne_seite("<html><body><h1>Wetter</h1></body></html>") == ("unbekannt", [])
    assert erkenne_seite("") == ("unbekannt", [])


def test_unbekannte_seite_und_andere_dateien(cfg, db, ordner):
    (ordner / "wetter.html").write_text("<html><body><h1>Wetter</h1></body></html>", encoding="utf-8")
    (ordner / "bild.png").write_bytes(b"\x89PNG")
    (ordner / "kaputt.html").write_bytes(b"<html>\xff\xfe nicht UTF-8</html>")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["dateien"] == 2 and stat["unbekannt"] == 2 and stat["neu"] == 0
    assert any(f.startswith("wetter.html") for f in stat["fehler"]) and any(f.startswith("kaputt.html") for f in stat["fehler"])
    assert (ordner / "nicht_erkannt" / "wetter.html").is_file() and (ordner / "nicht_erkannt" / "kaputt.html").is_file()
    assert (ordner / "bild.png").read_bytes() == b"\x89PNG"
    assert not (ordner / "eingelesen").exists()


def test_lesefehler_stoppt_andere_dateien_nicht(cfg, db, ads, ordner, monkeypatch):
    import wmscout.importer as importer_modul
    echt = importer_modul.lies_html

    def lies(pfad):
        if pfad.name == "a_gesperrt.html":
            raise OSError("Datei ist gesperrt")
        return echt(pfad)

    monkeypatch.setattr(importer_modul, "lies_html", lies)
    (ordner / "a_gesperrt.html").write_text(such_html(ads[:3]), encoding="utf-8")
    (ordner / "b_suche.html").write_text(such_html(ads[3:6]), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["dateien"] == 2 and stat["neu"] == 3 and len(stat["fehler"]) == 1
    assert "a_gesperrt.html" in stat["fehler"][0] and "gesperrt" in stat["fehler"][0]
    assert (ordner / "a_gesperrt.html").is_file()                            # bleibt für den nächsten Versuch liegen


def test_begleitordner_wandern_mit(cfg, db, ads, ordner):
    (ordner / "seite.html").write_text(such_html(ads[:2]), encoding="utf-8")
    (ordner / "seite_files").mkdir()
    (ordner / "seite_files" / "bild.jpg").write_bytes(b"jpg")
    (ordner / "anzeige.html").write_text(detailseite(ads[0]), encoding="utf-8")
    (ordner / "anzeige-Dateien").mkdir()
    (ordner / "anzeige-Dateien" / "stil.css").write_text("x", encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["fehler"] == [] and stat["dateien"] == 2
    ziel = eingelesen(ordner)
    assert (ziel / "seite_files" / "bild.jpg").read_bytes() == b"jpg" and not (ordner / "seite_files").exists()
    assert (ziel / "anzeige-Dateien" / "stil.css").is_file() and not (ordner / "anzeige-Dateien").exists()


def test_dateigrenze(cfg, db, ads, ordner):
    for i in range(3):
        (ordner / f"s{i}.html").write_text(such_html(ads[i * 2:i * 2 + 2]), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner, max_dateien=2)
    assert stat["dateien"] == 2 and stat["uebrig"] == 1 and (ordner / "s2.html").is_file()


def test_importierte_inserate_werden_nicht_nachgeladen(cfg, db, ads, ordner):
    (ordner / "suche.html").write_text(such_html(ads[:10]), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert db.ohne_details(100) == []
    netz = KeinNetz()
    assert Importer(cfg, db, abruf=netz).details() == 0 and netz.abrufe == []
    assert all(r["detail_geladen"] == 0 for r in db.con.execute("SELECT detail_geladen FROM anzeigen"))
    # Vom Crawler gefundene Inserate werden wie bisher nachgeladen; ein späterer Seitenimport ändert daran nichts
    db.speichere_treffer({"id": ads[20]["id"], "url": anzeige_url(ads[20]), "titel": "x"}, "Teilintegrierter")
    (ordner / "suche.html").write_text(such_html(ads[20:21]), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert [r["id"] for r in db.ohne_details(100)] == [ads[20]["id"]] and zeile(db, ads[20]["id"])["suche"] == "Teilintegrierter"


@pytest.fixture
def server(cfg, db, ordner):
    srv, _, suchlauf = erstelle_server(cfg, db, BASIS, port=0)
    srv.suchlauf = suchlauf
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_api_import(server, db, ads, ordner, tmp_path):
    port = server.server_address[1]
    lokal = Client(port)
    lokal.csrf = lokal("GET", "/api/ich")[1]["csrf"]
    status, daten, _ = lokal("POST", "/api/import", {})
    assert status == 200 and daten["dateien"] == 0 and daten["ordner"] == str(ordner.resolve())

    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "x.html").write_text(such_html(ads[:3]), encoding="utf-8")
    (ordner / "suche.html").write_text(such_html(ads[:4]), encoding="utf-8")
    assert lokal("POST", "/api/import", {}, token=False)[0] == 403                     # ohne CSRF-Token
    status, daten, _ = lokal("POST", "/api/import", {"ordner": str(fremd)})            # Pfad aus Anfrage wird ignoriert
    assert status == 200 and (daten["dateien"], daten["suchseiten"], daten["neu"]) == (1, 1, 4)
    assert daten["fehler"] == [] and daten["ordner"] == str(ordner.resolve())
    assert (fremd / "x.html").is_file() and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 4
    assert ads[0]["titel"] in lokal("GET", "/")[1]                                    # Liste zeigt die neuen Inserate

    TeamSpeicher(db, tmp_path / "fotos").nutzer_anlegen("Anna", "sicher1234", "inhaber")
    anna = Client(port).anmelden("Anna")
    assert anna("POST", "/api/import", {}, token=False)[0] == 403
    assert Client(port)("POST", "/api/import", {})[0] == 401
    status, daten, _ = anna("POST", "/api/import", {})
    assert status == 200 and daten["dateien"] == 0


def test_cli_import(cfg, ads, tmp_path):
    ordner = tmp_path / "gespeichert"
    r = _scout(cfg, tmp_path, "import", "--ordner", str(ordner))
    assert r.returncode == 0, r.stderr
    assert "Keine gespeicherten Seiten" in r.stdout and str(ordner) in r.stdout and ordner.is_dir()

    (ordner / "suche.html").write_text(such_html(ads[:7]), encoding="utf-8")
    (ordner / "anzeige.html").write_text(detailseite(ads[0]), encoding="utf-8")
    r = _scout(cfg, tmp_path, "import", "--ordner", str(ordner))
    assert r.returncode == 0, r.stderr
    assert "2 Dateien gelesen: 1 Suchseite, 1 Detailseite, 0 nicht erkannt" in r.stdout
    assert "7 neue Anzeigen" in r.stdout and "Report:" in r.stdout
    assert (tmp_path / "ausgabe" / "report.html").exists()


# ---------- Korrekturrunde 1 ----------
SUCHSEITE = "https://www.kleinanzeigen.de/s-wohnwagen-mobile/{}/anbieter:privat/c220+wohnwagen_mobile.art_s:{}"


def suchseite(ads, kopf="", davor=""):
    return davor + such_html(ads).replace("<html>", f"<html><head>{kopf}</head>", 1)


def canonical(art):
    return f'<link rel="canonical" href="{SUCHSEITE.format(art, art)}">'


@pytest.mark.parametrize("kopf, davor, erwartet", [
    (canonical("teilintegrierter"), "", "Teilintegrierter"),
    (canonical("wohnwagen"), "", "Wohnwagen"),
    ('<meta property="og:url" content="https://www.kleinanzeigen.de/s-wohnwagen-mobile/alkoven/c220">', "", "Alkoven"),
    ("", "<!-- saved from url=(0080)https://www.kleinanzeigen.de/s-wohnwagen-mobile/integrierter/k0c220 -->\n",
     "Integrierter"),
    (canonical("kastenwagen") + "<title>Alkoven - Kleinanzeigen</title>", "", "Kastenwagen"),   # URL geht vor Titel
    ("<title>Teilintegrierter Wohnmobile &amp; Wohnwagen gebraucht kaufen - Kleinanzeigen</title>", "", "Teilintegrierter"),
    ("<title>Alkoven in Stuttgart - Kleinanzeigen</title>", "", "Alkoven"),
    # keine Art erkennbar: allgemeine Kategorie darf nicht als „Wohnwagen“ gelten
    ('<link rel="canonical" href="https://www.kleinanzeigen.de/s-wohnwagen-mobile/c220">', "", None),
    ('<link rel="canonical" href="https://www.kleinanzeigen.de/s-wohnwagen-mobile/andere/c220+wohnwagen_mobile.art_s:andere">',
     "", None),
    ("<title>Wohnwagen &amp; Wohnmobile - Kleinanzeigen</title>", "", None),
    ("", "", None),
])
def test_fahrzeugart_der_suchseite(ads, kopf, davor, erwartet):
    assert fahrzeugart_der_suchseite(suchseite(ads[:2], kopf, davor)) == erwartet


def test_import_name_trifft_keinen_art_begriff():
    assert art_schluessel(IMPORT_SUCHE) == "Sonstige"
    for art in ("Teilintegrierter", "Integrierter", "Alkoven", "Kastenwagen", "Wohnwagen"):
        assert art_schluessel(f"Import {art}") == art


def max_eks(cfg, db):
    return {z["a"]["id"]: z["b"].max_ek for z in bewerte_alle(cfg, db, BASIS)}


def test_suchseite_art_geht_in_die_bewertung(cfg, db, ads, ordner, tmp_path):
    eigene = ads[:12]
    (ordner / "s.html").write_text(suchseite(eigene, canonical("teilintegrierter")), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert {zeile(db, a["id"])["suche"] for a in eigene} == {"Import Teilintegrierter"}
    assert db.ohne_details(100) == []                                         # weiterhin kein Detailabruf
    rechner = Rechner(cfg)
    assert {rechner.art(dict(zeile(db, a["id"]))) for a in eigene} == {"Teilintegrierter"}

    # Vergleich mit demselben Inserat, das der Crawler unter „Teilintegrierter“ gefunden hätte
    referenz = Datenbank(str(tmp_path / "referenz.sqlite"))
    for t in erkenne_seite(such_html(eigene))[1]:
        referenz.speichere_treffer(t.als_datensatz(), "Teilintegrierter")
    ek, ek_ref = max_eks(cfg, db), max_eks(cfg, referenz)
    assert ek == ek_ref and len(ek) == 12
    # ohne erkannte Art wäre es „Sonstige“ gewesen und deutlich anders bewertet worden
    ohne = Datenbank(str(tmp_path / "ohne.sqlite"))
    for t in erkenne_seite(such_html(eigene))[1]:
        ohne.speichere_treffer(t.als_datensatz(), IMPORT_SUCHE)
    assert max_eks(cfg, ohne) != ek_ref


def test_wohnwagen_suchseite(cfg, db, ads, ordner):
    (ordner / "w.html").write_text(suchseite(ads[:3], canonical("wohnwagen")), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["suche"] == "Import Wohnwagen"
    assert Rechner(cfg).art(dict(zeile(db, ads[0]["id"]))) == "Wohnwagen"


def test_unbestimmter_import_wird_durch_erkannte_art_ersetzt_aber_nicht_zurueck(cfg, db, ads, ordner):
    imp = Importer(cfg, db, abruf=KeinNetz())
    (ordner / "a.html").write_text(suchseite(ads[:3]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["suche"] == IMPORT_SUCHE
    (ordner / "b.html").write_text(suchseite(ads[:3], canonical("alkoven")), encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["suche"] == "Import Alkoven"
    (ordner / "c.html").write_text(suchseite(ads[:3]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["suche"] == "Import Alkoven"


def test_art_unbekannt_sperrt_das_anschreiben(cfg, db, ads, ordner):
    text = "Fahrzeugart unbekannt – Detailseite der Anzeige speichern und einlesen"
    a = {"preis": 30000, "ez_jahr": 2018, "suche": IMPORT_SUCHE, "titel": "Knaus Sky TI", "detail_geladen": 0}
    assert sperrgrund(a, cfg) == text
    assert sperrgrund({**a, "titel": "Hymer Integrierter 2018"}, cfg) is None          # Art aus dem Titel
    assert sperrgrund({**a, "suche": "Import Alkoven"}, cfg) is None
    assert sperrgrund({**a, "detail_geladen": 1}, cfg) is None
    assert sperrgrund({**a, "suche": "Teilintegrierter"}, cfg) is None                  # Crawler-Suche: unverändert
    assert sperrgrund({**a, "suche": "Sonstige / Camper"}, cfg) is None

    (ordner / "s.html").write_text(suchseite(ads[:20]), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    zeilen = bewerte_alle(cfg, db, BASIS)
    assert len(zeilen) == 20 and not any(z["bereit"] for z in zeilen) and all(z["brief"] is None for z in zeilen)
    assert any(z["sperre"] == text for z in zeilen)
    # Detailseite liefert die Art → keine Sperre wegen unbekannter Art mehr
    (ordner / "d.html").write_text(detailseite(ads[0]), encoding="utf-8")
    Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    z = next(z for z in bewerte_alle(cfg, db, BASIS) if z["a"]["id"] == ads[0]["id"])
    assert z["sperre"] != text and z["a"]["art"] == "Teilintegrierter"


def test_gewerblich_bleibt_nach_detailseite(cfg, db, ads, ordner):
    imp = Importer(cfg, db, abruf=KeinNetz())
    pro = such_html(ads[:3]).replace('<span class="simpletag">', '<span class="badge-hint-pro-small-srp">PRO</span><span class="simpletag">', 1)
    (ordner / "s.html").write_text(pro, encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["gewerblich"] == 1 and zeile(db, ads[1]["id"])["gewerblich"] == 0
    (ordner / "d.html").write_text(detailseite(ads[0]), encoding="utf-8")        # Detailseite ohne Gewerbe-Hinweis
    (ordner / "e.html").write_text(detailseite(ads[1]), encoding="utf-8")
    (ordner / "f.html").write_text(detailseite(ads[40]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[0]["id"])["gewerblich"] == 1 and zeile(db, ads[1]["id"])["gewerblich"] == 0
    assert zeile(db, ads[40]["id"])["gewerblich"] == 0
    # Detailseite mit Gewerbe-Hinweis setzt es weiterhin
    gewerblich = detailseite(ads[1]).replace("Privater Nutzer", "Gewerblicher Nutzer")
    (ordner / "g.html").write_text(gewerblich, encoding="utf-8")
    imp.importiere_seiten(ordner)
    assert zeile(db, ads[1]["id"])["gewerblich"] == 1


def test_detailseite_mit_aehnlichen_anzeigen_ohne_adresse(cfg, db, ads, ordner):
    ohne_adresse = detail_html(ads[0]).replace("</body>", such_html(ads[1:4]).split("<body>")[1])
    assert erkenne_seite(ohne_adresse) == ("detail_ohne_id", [])
    # mit Adresse im Kopf (auch nur als Link) bleibt es die Anzeige selbst
    art, inserate = erkenne_seite(mit_kopf(ohne_adresse, f'<link rel="alternate" href="{anzeige_url(ads[0])}">'))
    assert art == "detail" and [i.anzeigen_id for i in inserate] == [ads[0]["id"]]

    (ordner / "anzeige.html").write_text(ohne_adresse, encoding="utf-8")
    (ordner / "suche.html").write_text(such_html(ads[5:8]), encoding="utf-8")         # echte Suchseite bleibt Suchseite
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert (stat["unbekannt"], stat["suchseiten"], stat["detailseiten"], stat["neu"]) == (1, 1, 0, 3)
    assert "Anzeigenseite" in stat["fehler"][0] and "anzeige.html" in stat["fehler"][0]
    assert (ordner / "nicht_erkannt" / "anzeige.html").is_file()
    assert zeile(db, ads[1]["id"]) is None                                        # „ähnliche“ nicht fälschlich importiert


def test_zeitbudget(cfg, db, ads, ordner):
    for i in range(3):
        (ordner / f"s{i}.html").write_text(such_html(ads[i * 2:i * 2 + 2]), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner, max_sekunden=0)
    assert stat["dateien"] == 1 and stat["uebrig"] == 2 and (ordner / "s1.html").is_file()
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner, max_sekunden=60)
    assert stat["dateien"] == 2 and stat["uebrig"] == 0


def test_grosse_datei_wird_nicht_gelesen(cfg, db, ads, ordner):
    gross = ordner / "gross.html"
    with gross.open("wb") as f:
        f.truncate(21_000_000)                                                    # Hohlraumdatei, belegt kaum Platz
    (ordner / "klein.html").write_text(such_html(ads[:2]), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["dateien"] == 2 and stat["fehlerhaft"] == 1 and stat["neu"] == 2 and stat["unbekannt"] == 0
    assert "gross.html" in stat["fehler"][0] and "zu groß" in stat["fehler"][0] and "bleibt liegen" in stat["fehler"][0]
    assert gross.is_file() and not (ordner / "nicht_erkannt").exists()


def test_preissenkung_ueber_detailseite(cfg, db, ads, ordner):
    imp = Importer(cfg, db, abruf=KeinNetz())
    (ordner / "s.html").write_text(such_html(ads[:3]), encoding="utf-8")
    imp.importiere_seiten(ordner)
    guenstiger = {**ads[0], "preis": ads[0]["preis"] - 1500}
    (ordner / "d.html").write_text(detailseite(guenstiger), encoding="utf-8")
    stat = imp.importiere_seiten(ordner)
    assert (stat["preis"], stat["neu"], stat["bekannt"], stat["details"]) == (1, 0, 0, 1)
    z = zeile(db, ads[0]["id"])
    assert z["preis"] == ads[0]["preis"] - 1500 and z["preis_vorher"] == ads[0]["preis"] and z["preis_geaendert_am"]


def test_oserror_beim_verschieben(cfg, db, ads, ordner, monkeypatch):
    import wmscout.importer as importer_modul

    def kaputt(datei, ziel):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(importer_modul, "verschiebe", kaputt)
    (ordner / "s.html").write_text(such_html(ads[:3]), encoding="utf-8")
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["neu"] == 3 and stat["fehlerhaft"] == 0 and len(stat["fehler"]) == 1
    assert "nicht verschoben" in stat["fehler"][0] and "Zugriff verweigert" in stat["fehler"][0]
    assert (ordner / "s.html").is_file()
    monkeypatch.undo()
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)             # erneut: keine Dubletten
    assert (stat["neu"], stat["bekannt"]) == (0, 3) and not (ordner / "s.html").exists()


def test_nur_begleitordner_nicht_verschoben(cfg, db, ads, ordner, monkeypatch):
    import wmscout.eingang.seiten as seiten_modul
    echt = seiten_modul.shutil.move

    def move(quelle, ziel):
        if str(quelle).endswith("_files"):
            raise OSError("in Benutzung")
        return echt(quelle, ziel)

    monkeypatch.setattr(seiten_modul.shutil, "move", move)
    (ordner / "seite.html").write_text(such_html(ads[:2]), encoding="utf-8")
    (ordner / "seite_files").mkdir()
    stat = Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert stat["neu"] == 2 and stat["fehlerhaft"] == 0 and len(stat["fehler"]) == 1
    assert "Begleitordner seite_files" in stat["fehler"][0] and "in Benutzung" in stat["fehler"][0]
    assert "nicht verschoben (" not in stat["fehler"][0]
    assert (eingelesen(ordner) / "seite.html").is_file() and (ordner / "seite_files").is_dir()


def test_fehler_werden_protokolliert(cfg, db, ordner, caplog):
    (ordner / "wetter.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    with caplog.at_level("WARNING", logger="scout"):
        Importer(cfg, db, abruf=KeinNetz()).importiere_seiten(ordner)
    assert any("wetter.html" in r.getMessage() for r in caplog.records)


def test_api_import_grenzen_und_wirkung(server, db, ads, ordner, tmp_path, monkeypatch):
    import wmscout.web.api as api
    import wmscout.eingang.seiten as seiten_modul
    assert api.MAX_IMPORT_DATEIEN <= 25 and api.MAX_IMPORT_SEKUNDEN <= 20
    lokal = Client(server.server_address[1])
    lokal.csrf = lokal("GET", "/api/ich")[1]["csrf"]
    for i in range(3):
        (ordner / f"s{i}.html").write_text(such_html(ads[i * 2:i * 2 + 2]), encoding="utf-8")

    # laufender Suchlauf → 409, nichts wird gelesen
    server.suchlauf.stand["laeuft"] = True
    status, daten, _ = lokal("POST", "/api/import", {})
    assert status == 409 and "Suchlauf" in daten["fehler"]
    assert len(list(ordner.glob("*.html"))) == 3 and db.con.execute("SELECT COUNT(*) FROM anzeigen").fetchone()[0] == 0
    server.suchlauf.stand["laeuft"] = False

    # Liste vorher zwischenspeichern, danach muss der Import sie ungültig machen (k.veraendert)
    assert lokal("GET", "/api/fahrzeuge?filter=alle")[1] == []
    monkeypatch.setattr(api, "MAX_IMPORT_DATEIEN", 2)
    status, daten, _ = lokal("POST", "/api/import", {})
    assert status == 200 and daten["dateien"] == 2 and daten["uebrig"] == 1 and daten["neu"] == 4
    assert len(lokal("GET", "/api/fahrzeuge?filter=alle")[1]) == 4

    monkeypatch.setattr(api, "MAX_IMPORT_DATEIEN", 25)
    monkeypatch.setattr(api, "MAX_IMPORT_SEKUNDEN", 0)
    (ordner / "s3.html").write_text(such_html(ads[10:12]), encoding="utf-8")
    status, daten, _ = lokal("POST", "/api/import", {})
    assert status == 200 and daten["dateien"] == 1 and daten["uebrig"] == 1

    # Ordner im Projektordner wird relativ ausgegeben
    monkeypatch.setattr(seiten_modul, "PROJEKT", tmp_path.resolve())
    status, daten, _ = lokal("POST", "/api/import", {})
    assert status == 200 and daten["ordner"] == str(ordner.resolve().relative_to(tmp_path.resolve()))
