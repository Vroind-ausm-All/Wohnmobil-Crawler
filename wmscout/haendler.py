"""Händlerportal (Phase C, ADR-026): eigene Standorte/Filialen sehen freigegebene Verkaufsanfragen – anonymisiert.

Zugang nur für Nutzer mit Rolle ``haendler`` an einem GEPRÜFTEN Standort. Sichtbar ist eine Anfrage nur, wenn der Verkäufer
der Weitergabe zugestimmt UND der Inhaber sie freigegeben hat und sie noch offen ist. Gezeigt werden Fahrzeugdaten, Mängel,
Fotos, Preisvorstellung und der PLZ-Bereich – nie Name, Telefon, E-Mail, genaue PLZ/Ort oder interne Bewertung (Max-EK).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .datenbank import Datenbank
from .verkauf import MAENGEL, OFFEN

STANDORT_STATUS = {"offen": "zur Prüfung", "geprueft": "geprüft", "gesperrt": "gesperrt"}
_TELEFON = re.compile(r"(?:\+|\b0)[\d\s/().-]{6,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def plz_bereich(plz: str | None) -> str | None:
    return f"{plz[:2]}xxx" if plz and len(plz) >= 2 and plz[:2].isdigit() else None


def ohne_kontakt(text: str | None) -> str | None:
    """Telefonnummern, E-Mail-Adressen und Links in Freitexten unkenntlich – der Inhaber prüft die Anfrage vor der Freigabe,
    das hier ist die zweite Sicherung gegen versehentlich mitgegebene Kontaktdaten."""
    if not text:
        return text
    return _URL.sub("[Link entfernt]", _EMAIL.sub("[E-Mail entfernt]", _TELEFON.sub("[Telefon entfernt]", text)))


def anonym(a: dict, fotos: list[dict]) -> dict:
    """Sicht eines Standorts auf eine Anfrage – Positivliste der Felder, nichts sonst."""
    maengel = json.loads(a["maengel"]) if isinstance(a.get("maengel"), str) else (a.get("maengel") or [])
    return {"id": a["id"], "referenz": a["referenz"], "art": a["art"], "marke": a["marke"], "modell": a["modell"],
            "ez_jahr": a["ez_jahr"], "km": a["km"], "preisvorstellung": a["preisvorstellung"],
            "beschreibung": ohne_kontakt(a.get("beschreibung")), "maengel": [MAENGEL.get(m, m) for m in maengel],
            "region": plz_bereich(a.get("plz")), "freigegeben_am": a["freigegeben_am"],
            "fotos": [f["datei"] for f in fotos]}


class HaendlerSpeicher:
    def __init__(self, db: Datenbank):
        self.db, self.con = db, db.con

    # ---------- Standorte (Verwaltung durch den Inhaber) ----------
    def standort_anlegen(self, name: str, plz: str | None = None, ort: str | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Name des Standorts fehlt")
        with self.db.transaktion():
            return self.con.execute("INSERT INTO standorte (name, plz, ort, erstellt_am) VALUES (?,?,?,?)",
                                    (name[:100], (plz or "").strip()[:10] or None, (ort or "").strip()[:80] or None, _jetzt())).lastrowid

    def standorte(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM nutzer n WHERE n.standort_id=s.id AND n.aktiv=1) AS nutzer FROM standorte s ORDER BY s.name")]

    def standort(self, standort_id: int | None) -> dict | None:
        r = self.con.execute("SELECT * FROM standorte WHERE id=?", (standort_id,)).fetchone() if standort_id else None
        return dict(r) if r else None

    def standort_nach_name(self, name: str) -> dict | None:
        r = self.con.execute("SELECT * FROM standorte WHERE name=?", (name.strip(),)).fetchone()
        return dict(r) if r else None

    def setze_standort_status(self, standort_id: int, status: str, nutzer_id: int | None) -> bool:
        """Prüfen = Zugang frei; sperren/zurücksetzen = sofort kein Zugang mehr (wird bei jeder Anfrage neu geprüft)."""
        if status not in STANDORT_STATUS:
            raise ValueError("Status muss offen, geprueft oder gesperrt sein")
        with self.db.transaktion():
            cur = self.con.execute("UPDATE standorte SET status=?, geprueft_am=?, geprueft_von=? WHERE id=?",
                                   (status, _jetzt() if status == "geprueft" else None, nutzer_id if status == "geprueft" else None,
                                    standort_id))
        return cur.rowcount > 0

    def ist_freigeschaltet(self, nutzer: dict | None) -> bool:
        s = self.standort((nutzer or {}).get("standort_id"))
        return bool(s and s["status"] == "geprueft")

    # ---------- Sicht der Standorte ----------
    _SICHTBAR = (f"v.freigegeben_am IS NOT NULL AND v.weitergabe_einwilligung_am IS NOT NULL "
                 f"AND v.status IN ({','.join('?' * len(OFFEN))})")

    def _zeilen(self, extra: str = "", werte: tuple = ()) -> list[dict]:
        sql = ("SELECT v.*, k.plz FROM verkaufsanfragen v JOIN verkaeufer k ON k.id=v.verkaeufer_id WHERE " + self._SICHTBAR + extra
               + " ORDER BY v.freigegeben_am DESC, v.id DESC")
        return [dict(r) for r in self.con.execute(sql, (*OFFEN, *werte))]

    def _fotos(self, anfrage_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT datei FROM anfrage_fotos WHERE anfrage_id=? ORDER BY id", (anfrage_id,))]

    def sichtbare(self, standort_id: int) -> list[dict]:
        gemeldet = {r[0] for r in self.con.execute("SELECT anfrage_id FROM anfrage_interesse WHERE standort_id=?", (standort_id,))}
        return [{**anonym(a, self._fotos(a["id"])), "interesse": a["id"] in gemeldet} for a in self._zeilen()]

    def sichtbar(self, anfrage_id: int, standort_id: int) -> dict | None:
        z = self._zeilen(" AND v.id=?", (anfrage_id,))
        if not z:
            return None
        gemeldet = self.con.execute("SELECT 1 FROM anfrage_interesse WHERE anfrage_id=? AND standort_id=?",
                                    (anfrage_id, standort_id)).fetchone() is not None
        return {**anonym(z[0], self._fotos(anfrage_id)), "interesse": gemeldet}

    def interesse_melden(self, anfrage_id: int, standort_id: int, nutzer_id: int) -> bool:
        """Unverbindlich; je Standort einmal. Rückgabe False: Anfrage für diesen Standort nicht (mehr) sichtbar."""
        with self.db.transaktion():
            if not self._zeilen(" AND v.id=?", (anfrage_id,)):
                return False
            cur = self.con.execute("INSERT OR IGNORE INTO anfrage_interesse (anfrage_id, standort_id, nutzer_id, zeitpunkt) VALUES (?,?,?,?)",
                                   (anfrage_id, standort_id, nutzer_id, _jetzt()))
            if cur.rowcount:
                name = self.con.execute("SELECT name FROM standorte WHERE id=?", (standort_id,)).fetchone()[0]
                self.con.execute("INSERT INTO anfrage_verlauf (anfrage_id, zeitpunkt, nutzer_id, ereignis, alt, neu) VALUES (?,?,?,?,?,?)",
                                 (anfrage_id, _jetzt(), nutzer_id, "interesse", None, name))
        return True
