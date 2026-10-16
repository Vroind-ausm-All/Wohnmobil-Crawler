"""Verkäuferportal (Phase B, ADR-025): Verkaufsanfragen privater Verkäufer – eigene, autorisierte Angebote.

Bewusst getrennt von beobachteten Inseraten (``anzeigen``/``inserate``): Eine Anfrage kommt vom Verkäufer selbst (Formular,
Telefon oder vor Ort erfasst), mit Einwilligung. Die Bewertung nutzt den unveränderten Rechner; die Fahrzeugdaten der Anfrage
werden dafür nur in dessen Sicht übersetzt (``als_fahrzeug``). Keine automatische Nachricht an Verkäufer (CLAUDE.md, Regel 10).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from .bewertung.auswertung import bewerte_anzeige, vergleichsbasis
from .bewertung.rechner import Bewertung, Rechner
from .datenbank import IMPORT_ARTEN, Datenbank
from .normalisierung.fahrzeug import ergaenze_fahrzeug
from .normalisierung.geo import entfernung_km
from .team import MAX_FOTO_BYTES, bild_endung

ARTEN = IMPORT_ARTEN
MAENGEL = {"feuchtigkeit": "Feuchtigkeit/Wasserschaden", "unfall": "Unfallschaden", "motor": "Motor/Getriebe defekt",
           "rost": "Rost am Rahmen/Unterboden", "hu": "HU abgelaufen", "gas": "Gasprüfung abgelaufen",
           "aufbau": "Risse/Schäden am Aufbau", "technik": "Bordtechnik defekt (Heizung, Kühlschrank, Elektrik)"}
KANAELE = {"telefon": "Telefon", "vor_ort": "vor Ort", "formular": "Formular"}
STATUS = {"eingegangen": "eingegangen", "in_pruefung": "in Prüfung", "angebot": "Angebot gemacht", "abgelehnt": "abgelehnt",
          "zurueckgezogen": "vom Verkäufer zurückgezogen", "gekauft": "gekauft"}
MAX_FOTOS = 12
SICHERHEIT_RANG = {"keine": 0, "niedrig": 1, "manuell": 1, "mittel": 2, "hoch": 3}


class Eingabefehler(ValueError):
    def __init__(self, fehler: list[str]):
        super().__init__("; ".join(fehler))
        self.fehler = fehler


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _text(daten: dict, feld: str, laenge: int) -> str | None:
    wert = str(daten.get(feld) or "").strip()
    return wert[:laenge] or None


def _ganzzahl(daten: dict, feld: str, name: str, von: int, bis: int, fehler: list[str]) -> int | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        return None
    try:
        zahl = int(str(wert).replace(".", "").replace(" ", "").replace("€", ""))
    except ValueError:
        fehler.append(f"{name}: bitte eine ganze Zahl angeben")
        return None
    if not von <= zahl <= bis:
        fehler.append(f"{name}: {zahl} ist nicht plausibel")
        return None
    return zahl


def pruefe_anfrage(daten: dict, jahr: int | None = None) -> dict:
    """Bereinigte Anfrage aus Formulardaten oder ``Eingabefehler`` mit allen Gründen (ohne Netz und Datenbank testbar).

    Pflicht: Fahrzeugart, Marke, Erstzulassung, Name, PLZ, Telefon ODER E-Mail und die Einwilligung. Die Preisvorstellung
    ist freiwillig (Betreiberentscheidung 15.10.2026)."""
    jahr = jahr or datetime.now().year
    f: list[str] = []
    art = daten.get("art")
    if art not in ARTEN:
        f.append("Fahrzeugart fehlt")
    marke = _text(daten, "marke", 60)
    if not marke:
        f.append("Marke fehlt")
    ez_jahr = _ganzzahl(daten, "ez_jahr", "Erstzulassung", 1960, jahr, f)
    if ez_jahr is None and not any(x.startswith("Erstzulassung") for x in f):
        f.append("Erstzulassung fehlt")
    km = _ganzzahl(daten, "km", "Kilometerstand", 0, 2_000_000, f)
    preis = _ganzzahl(daten, "preisvorstellung", "Preisvorstellung", 0, 2_000_000, f)
    name = _text(daten, "name", 100)
    if not name:
        f.append("Name fehlt")
    email = _text(daten, "email", 200)
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        f.append("E-Mail-Adresse ist ungültig")
    telefon = _text(daten, "telefon", 40)
    if not email and not telefon:
        f.append("Telefon oder E-Mail angeben")
    plz = _text(daten, "plz", 10)
    if not plz or not (plz.isdigit() and len(plz) == 5):
        f.append("PLZ: fünfstellig angeben (Abholung in Deutschland)")
    if daten.get("einwilligung") is not True:
        f.append("Einwilligung zur Verarbeitung der Angaben fehlt")
    kanal = daten.get("kanal") or "formular"
    if kanal not in KANAELE:
        f.append("Eingangsweg unbekannt")
    maengel = daten.get("maengel") or []
    if not isinstance(maengel, list) or any(m not in MAENGEL for m in maengel):
        f.append("Unbekannter Mangel")
        maengel = []
    if f:
        raise Eingabefehler(f)
    return {"art": art, "marke": marke, "modell": _text(daten, "modell", 80), "ez_jahr": ez_jahr, "km": km,
            "preisvorstellung": preis, "beschreibung": _text(daten, "beschreibung", 3000), "maengel": sorted(set(maengel)),
            "name": name, "email": email, "telefon": telefon, "plz": plz, "ort": _text(daten, "ort", 80), "kanal": kanal}


def als_fahrzeug(anfrage: dict) -> dict:
    """Sicht des Rechners auf eine Anfrage – wie eine Anzeige mit bestätigter Art (der Verkäufer hat sie angegeben).
    Mängel stehen als Text in der Kurzbeschreibung, damit der Rechner sie wie bei Inseraten als Wertfaktor erkennt."""
    maengel = [MAENGEL[m] for m in json.loads(anfrage["maengel"]) if m in MAENGEL] if isinstance(anfrage.get("maengel"), str) \
        else [MAENGEL[m] for m in anfrage.get("maengel") or [] if m in MAENGEL]
    beschreibung = " ".join(x for x in (anfrage.get("beschreibung"), ("Mängel: " + ", ".join(maengel)) if maengel else None) if x)
    a = {"id": f"anfrage-{anfrage.get('id') or 'neu'}", "suche": anfrage.get("art"), "art": anfrage.get("art"),
         "titel": " ".join(x for x in (anfrage.get("marke"), anfrage.get("modell")) if x), "marke": anfrage.get("marke"),
         "ez_jahr": anfrage.get("ez_jahr"), "km": anfrage.get("km"), "preis": anfrage.get("preisvorstellung"),
         "kurzbeschreibung": beschreibung or None, "plz": anfrage.get("plz"), "ort": anfrage.get("ort"), "gewerblich": 0}
    return ergaenze_fahrzeug(a)


def vergleich_aus(db: Datenbank) -> list[dict]:
    return vergleichsbasis([ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()])


def bewerte(cfg: dict, anfrage: dict, vergleich: list[dict], rechner: Rechner | None = None) -> Bewertung:
    a = als_fahrzeug(anfrage)
    a["entfernung_km"] = entfernung_km(str(cfg["anschreiben"].get("plz") or "") or None, a.get("plz"))
    return bewerte_anzeige(rechner or Rechner(cfg), a, vergleich)


def spanne_fuer_verkaeufer(b: Bewertung, cfg: dict) -> tuple[int, int] | None:
    """Grobe Marktwert-Spanne für den Verkäufer (Betreiberentscheidung 15.10.2026) – nur bei ausreichend sicherer Datenlage
    (``verkaeuferportal.spanne_mindest_sicherheit``) und auf volle 1.000 € nach außen gerundet: keine falsche Genauigkeit,
    kein Angebot. Nie Max-EK oder Erstangebot."""
    c = cfg.get("verkaeuferportal") or {}
    if not c.get("spanne_zeigen", False) or not b.spanne_von or not b.spanne_bis:
        return None
    if SICHERHEIT_RANG.get(b.sicherheit, 0) < SICHERHEIT_RANG.get(c.get("spanne_mindest_sicherheit", "mittel"), 2):
        return None
    von, bis = (b.spanne_von // 1000) * 1000, -(-b.spanne_bis // 1000) * 1000
    return (von, bis) if 0 < von < bis else None


class VerkaufSpeicher:
    def __init__(self, db: Datenbank, foto_ordner: Path):
        self.db, self.con, self.foto_ordner = db, db.con, Path(foto_ordner)

    def _verlauf(self, anfrage_id: int, nutzer_id: int | None, ereignis: str, alt=None, neu=None):
        self.con.execute("INSERT INTO anfrage_verlauf (anfrage_id, zeitpunkt, nutzer_id, ereignis, alt, neu) VALUES (?,?,?,?,?,?)",
                         (anfrage_id, _jetzt(), nutzer_id, ereignis, alt, neu))

    def anlegen(self, a: dict, nutzer_id: int | None, einwilligung_version: str) -> dict:
        """Verkäufer und Anfrage in EINER Transaktion; Referenz ``VA-<Jahr>-<Nr>``. ``a`` aus ``pruefe_anfrage``."""
        jetzt = _jetzt()
        with self.db.transaktion():
            vid = self.con.execute(
                "INSERT INTO verkaeufer (name, email, telefon, plz, ort, einwilligung_am, einwilligung_version, erstellt_am) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (a["name"], a["email"], a["telefon"], a["plz"], a["ort"], jetzt, einwilligung_version, jetzt)).lastrowid
            aid = self.con.execute(
                "INSERT INTO verkaufsanfragen (verkaeufer_id, kanal, art, marke, modell, ez_jahr, km, preisvorstellung, beschreibung, "
                "maengel, erfasst_von, erstellt_am, aktualisiert_am) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, a["kanal"], a["art"], a["marke"], a["modell"], a["ez_jahr"], a["km"], a["preisvorstellung"], a["beschreibung"],
                 json.dumps(a["maengel"]), nutzer_id, jetzt, jetzt)).lastrowid
            referenz = f"VA-{jetzt[:4]}-{aid:04d}"
            self.con.execute("UPDATE verkaufsanfragen SET referenz=? WHERE id=?", (referenz, aid))
            self._verlauf(aid, nutzer_id, "angelegt", None, a["kanal"])
        return {"id": aid, "referenz": referenz}

    _SPALTEN = ("SELECT v.*, k.name, k.email, k.telefon, k.plz, k.ort, k.einwilligung_am, k.einwilligung_version, "
                "(SELECT COUNT(*) FROM anfrage_fotos f WHERE f.anfrage_id = v.id) AS fotos_anzahl "
                "FROM verkaufsanfragen v JOIN verkaeufer k ON k.id = v.verkaeufer_id")

    def liste(self, status: str | None = None) -> list[dict]:
        if status and status not in STATUS:
            raise ValueError("unbekannter Status")
        sql, p = self._SPALTEN, ()
        if status:
            sql, p = sql + " WHERE v.status=?", (status,)
        return [dict(r) for r in self.con.execute(sql + " ORDER BY v.erstellt_am DESC, v.id DESC", p)]

    def lade(self, anfrage_id: int) -> dict | None:
        r = self.con.execute(self._SPALTEN + " WHERE v.id=?", (anfrage_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["fotos"] = [dict(x) for x in self.con.execute("SELECT id, datei, erstellt_am FROM anfrage_fotos WHERE anfrage_id=? ORDER BY id",
                                                        (anfrage_id,))]
        d["verlauf"] = [dict(x) for x in self.con.execute(
            "SELECT zeitpunkt, nutzer_id, ereignis, alt, neu FROM anfrage_verlauf WHERE anfrage_id=? ORDER BY id", (anfrage_id,))]
        return d

    def _aendere(self, anfrage_id: int, spalte: str, wert, ereignis: str, nutzer_id: int | None) -> bool:
        with self.db.transaktion():
            r = self.con.execute(f"SELECT {spalte} FROM verkaufsanfragen WHERE id=?", (anfrage_id,)).fetchone()
            if not r:
                return False
            if r[0] != wert:
                self.con.execute(f"UPDATE verkaufsanfragen SET {spalte}=?, aktualisiert_am=? WHERE id=?", (wert, _jetzt(), anfrage_id))
                self._verlauf(anfrage_id, nutzer_id, ereignis, None if r[0] is None else str(r[0]), None if wert is None else str(wert))
        return True

    def setze_status(self, anfrage_id: int, status: str, nutzer_id: int | None) -> bool:
        if status not in STATUS:
            raise ValueError("unbekannter Status")
        return self._aendere(anfrage_id, "status", status, "status", nutzer_id)

    def setze_bearbeiter(self, anfrage_id: int, bearbeiter_id: int | None, nutzer_id: int | None) -> bool:
        return self._aendere(anfrage_id, "bearbeiter_id", bearbeiter_id, "bearbeiter", nutzer_id)

    def setze_notiz(self, anfrage_id: int, notiz: str, nutzer_id: int | None) -> bool:
        return self._aendere(anfrage_id, "notiz", notiz[:3000] or None, "notiz", nutzer_id)

    def foto_speichern(self, anfrage_id: int, daten: bytes, nutzer_id: int | None) -> dict:
        if len(daten) > MAX_FOTO_BYTES:
            raise ValueError("Foto zu groß (max. 8 MB)")
        endung = bild_endung(daten)
        with self.db.transaktion():
            if not self.con.execute("SELECT 1 FROM verkaufsanfragen WHERE id=?", (anfrage_id,)).fetchone():
                raise LookupError("Anfrage nicht gefunden")
            if self.con.execute("SELECT COUNT(*) FROM anfrage_fotos WHERE anfrage_id=?", (anfrage_id,)).fetchone()[0] >= MAX_FOTOS:
                raise ValueError(f"Höchstens {MAX_FOTOS} Fotos je Anfrage")
            ordner = self.foto_ordner / str(int(anfrage_id))
            ordner.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.{endung}"
            (ordner / name).write_bytes(daten)
            fid = self.con.execute("INSERT INTO anfrage_fotos (anfrage_id, datei, erstellt_am) VALUES (?,?,?)",
                                   (anfrage_id, name, _jetzt())).lastrowid
            self._verlauf(anfrage_id, nutzer_id, "foto", None, name)
        return {"id": fid, "datei": name}

    def foto_pfad(self, anfrage_id: int, datei: str) -> Path | None:
        """Nur Dateien, die zu dieser Anfrage gespeichert sind (kein Pfad-Trick möglich)."""
        r = self.con.execute("SELECT 1 FROM anfrage_fotos WHERE anfrage_id=? AND datei=?", (anfrage_id, datei)).fetchone()
        pfad = self.foto_ordner / str(int(anfrage_id)) / datei
        return pfad if r and pfad.is_file() else None
