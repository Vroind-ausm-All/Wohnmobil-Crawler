"""P1-11b: Hintergrund-Threads der App (Suchlauf, Auto-Suche) und Mailversand – ohne Netz, SMTP ersetzt."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

import pytest

from tests.daten import BASIS, FakeAbruf
from wmscout import app as app_modul
from wmscout import benachrichtigung
from wmscout.importer import Importer
from wmscout.laufsperre import Laufsperre


class SMTP:
    """Ersatz für smtplib.SMTP: merkt sich Verbindung, Anmeldung und Nachrichten."""
    gesendet: list = []

    def __init__(self, server, port, timeout):
        self.ablauf = [("verbinden", server, port, timeout)]
        SMTP.gesendet.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.ablauf.append(("ende",))

    def starttls(self):
        self.ablauf.append(("starttls",))

    def login(self, benutzer, passwort):
        self.ablauf.append(("login", benutzer, passwort))

    def send_message(self, msg):
        self.ablauf.append(("senden", msg))


@pytest.fixture
def smtp(monkeypatch):
    SMTP.gesendet = []
    monkeypatch.setattr(benachrichtigung.smtplib, "SMTP", SMTP)
    return SMTP.gesendet


@pytest.fixture
def mail_cfg(cfg, monkeypatch):
    cfg["email"].update(aktiv=True, benutzer="scout@example.test", empfaenger="chef@example.test", nur_bei_neuen_treffern=True)
    monkeypatch.setenv(cfg["email"]["passwort_env"], "geheim-nur-im-test")
    return cfg


def _suchlauf(cfg, ads, monkeypatch) -> app_modul.Suchlauf:
    monkeypatch.setattr(app_modul, "Importer", lambda c, db: Importer(c, db, abruf=FakeAbruf(ads)))
    return app_modul.Suchlauf(cfg, cfg["ausgabe"]["datenbank"], BASIS)


# ---------------------------------------------------------------- Suchlauf
def test_suchlauf_komplett_mit_mail_und_rueckrufen(mail_cfg, ads, smtp, monkeypatch, tmp_path):
    lauf = _suchlauf(mail_cfg, ads, monkeypatch)
    erhalten = []
    lauf.bei_ende += [lambda z: 1 / 0, erhalten.append]                       # fehlerhafter Rückruf stört die anderen nicht
    assert lauf.starte() is True and lauf.stand["laeuft"]
    lauf.thread.join(120)
    st = lauf.stand
    assert not st["laeuft"] and not st["fehler"] and st["ende"] and st["meldung"].startswith("Fertig: 60 neue Anzeigen")
    assert st["neue_treffer"] == sum(1 for z in erhalten[0] if z["neu"] and z["bereit"]) > 0
    assert len(erhalten) == 1 and len(erhalten[0]) >= 60
    assert (tmp_path / "ausgabe" / "report.html").is_file()
    # Mail: TLS, Anmeldung mit dem Passwort aus der Umgebung, Report im Anhang
    assert len(smtp) == 1
    schritte = [s[0] for s in smtp[0].ablauf]
    assert schritte == ["verbinden", "starttls", "login", "senden", "ende"]
    assert smtp[0].ablauf[2] == ("login", "scout@example.test", "geheim-nur-im-test")
    msg = smtp[0].ablauf[3][1]
    assert msg["To"] == "chef@example.test" and msg["Subject"] == f"Wohnmobil-Scout: {st['neue_treffer']} neue Treffer"
    assert [t.get_filename() for t in msg.iter_attachments()] == ["report.html"]
    assert "geheim" not in msg.as_string()
    s = Laufsperre(mail_cfg["ausgabe"]["datenbank"])
    assert s.erwerben()
    s.freigeben()


def test_suchlauf_wendet_datenschutzfrist_an(cfg, ads, monkeypatch, caplog):
    cfg["datenschutz"] = {"inserate_anonymisieren_nach_monaten": 1}
    lauf = _suchlauf(cfg, ads, monkeypatch)
    alt = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
    aufrufe = []
    monkeypatch.setattr(app_modul.datenrechte, "inserate_nach_frist", lambda db, ordner, monate: aufrufe.append(monate) or [alt])
    with caplog.at_level(logging.INFO, logger="scout"):
        lauf.starte()
        lauf.thread.join(120)
    assert aufrufe == [1] and "Datenschutz-Frist: 1 Inserate anonymisiert" in caplog.text


def test_suchlauf_fehler_wird_angezeigt(cfg, monkeypatch):
    monkeypatch.setattr(app_modul, "bewerte_alle", lambda *a, **k: (_ for _ in ()).throw(ValueError("Bewertung kaputt")))
    lauf = _suchlauf(cfg, [], monkeypatch)
    lauf.starte()
    lauf.thread.join(60)
    assert lauf.stand["fehler"] == "Bewertung kaputt" and lauf.stand["meldung"] == "Suchlauf fehlgeschlagen"
    assert not lauf.stand["laeuft"]


# ---------------------------------------------------------------- Auto-Suche
class FakeLauf:
    def __init__(self, laeuft=False, ende=None):
        self.stand = {"laeuft": laeuft, "ende": ende, "naechste_auto": None}
        self.starts = 0
        self.oeffnungen = 0

    def starte(self):
        self.starts += 1
        return True

    def oeffne_datenbank(self):
        self.oeffnungen += 1
        return FakeDb(None)


class FakeDb:
    def __init__(self, letzter):
        self.letzter = letzter

    def letzter_lauf(self):
        if isinstance(self.letzter, Exception):
            raise self.letzter
        return self.letzter


def _auto(lauf, stunden=3):
    return app_modul.AutoSuche({"app": {"auto_suche_stunden": stunden, "auto_suche_von": 0, "auto_suche_bis": 24}}, lauf)


def test_auto_suche_schritt_startet_nur_wenn_faellig():
    lauf = FakeLauf()
    auto = _auto(lauf)
    assert auto._schritt(FakeDb(None)) is True and lauf.starts == 1                   # noch nie gelaufen → sofort
    assert auto._schritt(FakeDb(datetime.now() - timedelta(minutes=10))) is False      # vor 10 min gelaufen → warten
    assert lauf.starts == 1 and lauf.stand["naechste_auto"] > datetime.now().isoformat(timespec="minutes")
    lauf.stand["ende"] = (datetime.now() - timedelta(minutes=5)).isoformat()           # Ende des App-Laufs zählt auch
    assert auto._schritt(FakeDb(datetime.now() - timedelta(hours=5))) is False
    lauf.stand.update(ende=None, laeuft=True)                                           # läuft gerade → kein zweiter Start
    assert auto._schritt(FakeDb(None)) is False and lauf.starts == 1


def test_auto_suche_schleife_ueberlebt_fehler(monkeypatch, caplog):
    lauf = FakeLauf()
    auto = _auto(lauf)
    durchgaenge = []

    def schritt(db):
        durchgaenge.append(db)
        if len(durchgaenge) == 1:
            raise RuntimeError("Datenbank gesperrt")
        auto.halt.set()
        return False

    monkeypatch.setattr(auto, "_schritt", schritt)
    monkeypatch.setattr(auto.halt, "wait", lambda sek: auto.halt.is_set())             # keine Minute warten
    with caplog.at_level(logging.ERROR, logger="scout"):
        auto._schleife()
    assert len(durchgaenge) == 2 and lauf.oeffnungen == 1                               # Verbindung einmal, weiter nach Fehler
    assert "Durchgang fehlgeschlagen" in caplog.text and "Datenbank gesperrt" in caplog.text


def test_auto_suche_nur_wenn_eingestellt():
    for stunden, erwartet in ((0, False), (3, True)):
        auto = _auto(FakeLauf(), stunden=stunden)
        gelaufen = threading.Event()
        auto._schleife = gelaufen.set
        auto.starte()
        assert gelaufen.wait(5 if erwartet else 0.5) is erwartet, stunden


# ---------------------------------------------------------------- Mail
def _zeilen(neu: bool):
    from wmscout.bewertung.rechner import Bewertung
    b = Bewertung(30000, 1, "Test", 34000, 3000, 2000, angebotspreis=28000, sicherheit="mittel", art="Alkoven")
    return [{"bereit": True, "neu": neu, "b": b, "hinweise": ["EZ geschätzt"],
             "a": {"fahrzeug": "Knaus Sun Ti", "ez_jahr": 2015, "ort": "Ulm", "preis": 28000, "url": "https://x.test/1"}}]


def test_mail_aus_ohne_passwort_ohne_neue(mail_cfg, smtp, monkeypatch, tmp_path, caplog):
    bericht = tmp_path / "report.html"
    bericht.write_text("<html></html>", encoding="utf-8")
    benachrichtigung.sende_mail({**mail_cfg, "email": {**mail_cfg["email"], "aktiv": False}}, _zeilen(True), {"html": bericht})
    with caplog.at_level(logging.INFO, logger="scout"):
        benachrichtigung.sende_mail(mail_cfg, _zeilen(False), {"html": bericht})
        assert "Keine neuen Treffer" in caplog.text
        monkeypatch.delenv(mail_cfg["email"]["passwort_env"])
        benachrichtigung.sende_mail(mail_cfg, _zeilen(True), {"html": bericht})
        assert "Umgebungsvariable SCOUT_SMTP_PASSWORT fehlt" in caplog.text
    assert smtp == []
    monkeypatch.setenv(mail_cfg["email"]["passwort_env"], "pw")
    mail_cfg["email"]["nur_bei_neuen_treffern"] = False
    benachrichtigung.sende_mail(mail_cfg, _zeilen(False), {"html": bericht})                # auch ohne neue, wenn so eingestellt
    assert len(smtp) == 1
    text = smtp[0].ablauf[3][1].get_body().get_content()
    assert "Knaus Sun Ti" in text and "Hinweis: EZ geschätzt" in text and "https://x.test/1" in text
