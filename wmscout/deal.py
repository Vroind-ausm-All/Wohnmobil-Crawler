"""Deal Intelligence – Anbindung an Datenbank, Verkaufsanfragen und Standorte (Phase E, ADR-028).

Die Rechnung selbst steht in ``bewertung.kalkulation`` (rein, ohne Datenbank). Hier: Eingabe für eine Verkaufsanfrage aus
Sicht eines Standorts (Transport ab dessen PLZ, Entfernung auf 10 km gerundet – genauer muss ein Standort den Wohnort des
Verkäufers nicht eingrenzen können) oder des Teams (Firmensitz, ``anschreiben.plz``); Kalkulationen speichern und nachrechnen.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import verkauf as vk
from .bewertung import kalkulation as kalk
from .datenbank import Datenbank
from .normalisierung.geo import entfernung_km


def _jetzt_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class DealSpeicher:
    def __init__(self, db: Datenbank, cfg: dict):
        self.db, self.con, self.cfg = db, db.con, cfg
        kalk.einstellungen(cfg)            # ValueError mit verständlicher Meldung bei falscher Konfiguration

    def _anfrage(self, anfrage_id: int) -> dict:
        r = self.con.execute("SELECT v.*, k.plz, k.ort FROM verkaufsanfragen v JOIN verkaeufer k ON k.id=v.verkaeufer_id WHERE v.id=?",
                             (anfrage_id,)).fetchone()
        if not r:
            raise LookupError("Anfrage nicht gefunden")
        return dict(r)

    def eingabe(self, anfrage_id: int, betrag: int | None, standort_id: int = 0, stichtag: datetime | None = None) -> dict:
        f = vk.als_fahrzeug(self._anfrage(anfrage_id))
        s = self.con.execute("SELECT name, plz FROM standorte WHERE id=?", (standort_id,)).fetchone() if standort_id else None
        if s:
            km = entfernung_km(s["plz"], f.get("plz")) if s["plz"] else None
            f["entfernung_km"], abholung = (None if km is None else int(round(km, -1))), f"ab Standort {s['name']}"
        else:
            f["entfernung_km"] = entfernung_km(str(self.cfg["anschreiben"].get("plz") or "") or None, f.get("plz"))
            abholung = "ab Firmensitz"
        return kalk.eingabe(self.cfg, f, vk.vergleich_aus(self.db), betrag=betrag, stichtag=stichtag or datetime.now(),
                            abholung=abholung)

    def berechne(self, anfrage_id: int, betrag: int | None, standort_id: int = 0) -> tuple[dict, dict]:
        e = self.eingabe(anfrage_id, betrag, standort_id)
        return e, kalk.rechne(e)

    def speichern(self, e: dict, ergebnis: dict, *, anlass: str, anfrage_id: int, auktion_id: int | None = None,
                  gebot_id: int | None = None, standort_id: int | None = None, nutzer_id: int | None = None) -> int:
        with self.db.transaktion():
            return self.con.execute(
                "INSERT INTO kalkulationen (zeitpunkt_utc, version, anlass, anfrage_id, auktion_id, gebot_id, standort_id, nutzer_id, "
                "betrag, eingabe_json, eingabe_hash, ergebnis_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (_jetzt_utc(), e["version"], anlass, anfrage_id, auktion_id, gebot_id, standort_id or None, nutzer_id, e["betrag"],
                 _json(e), kalk.eingabe_hash(e), _json(ergebnis))).lastrowid

    @staticmethod
    def nachrechnen(r) -> dict:
        """Eingabe unverändert (Hash), gleiche Rechenversion und gleiches Ergebnis wie damals gespeichert?"""
        e = json.loads(r["eingabe_json"])
        hash_ok = kalk.eingabe_hash(e) == r["eingabe_hash"]
        version_gleich = e.get("version") == kalk.VERSION
        gleich = hash_ok and version_gleich and _json(kalk.rechne(e)) == r["ergebnis_json"]
        return {"gleich": gleich, "hash_ok": hash_ok, "version_gleich": version_gleich}

    def liste(self, anfrage_id: int) -> list[dict]:
        aus = []
        for r in self.con.execute("SELECT k.*, s.name AS standort FROM kalkulationen k LEFT JOIN standorte s ON s.id=k.standort_id "
                                  "WHERE k.anfrage_id=? ORDER BY k.id DESC", (anfrage_id,)):
            erg = json.loads(r["ergebnis_json"])
            erw = (erg.get("szenarien") or {}).get("erwartet") or {}
            aus.append({"id": r["id"], "zeitpunkt_utc": r["zeitpunkt_utc"], "anlass": r["anlass"], "betrag": r["betrag"],
                        "standort": r["standort"], "gebot_id": r["gebot_id"], "ampel": erg.get("ampel"), "gewinn": erw.get("gewinn"),
                        "max_ek": erw.get("max_ek"), "hash": r["eingabe_hash"][:12]})
        return aus

    def lade(self, kalkulation_id: int) -> dict | None:
        r = self.con.execute("SELECT k.*, s.name AS standort FROM kalkulationen k LEFT JOIN standorte s ON s.id=k.standort_id "
                             "WHERE k.id=?", (kalkulation_id,)).fetchone()
        if not r:
            return None
        e = json.loads(r["eingabe_json"])
        return {"id": r["id"], "zeitpunkt_utc": r["zeitpunkt_utc"], "anlass": r["anlass"], "anfrage_id": r["anfrage_id"],
                "auktion_id": r["auktion_id"], "gebot_id": r["gebot_id"], "standort": r["standort"], "betrag": r["betrag"],
                "version": r["version"], "eingabe_hash": r["eingabe_hash"], "ergebnis": json.loads(r["ergebnis_json"]),
                "eingabe": {"stichtag": e["stichtag"], "abholung": e["abholung"], "fahrzeug": e["fahrzeug"],
                            "kalkulation": e["kalkulation"], "vergleich_anzahl": len(e["vergleich"])},
                "nachrechnung": self.nachrechnen(r)}

    def pruefe_alle(self) -> dict:
        abweichend = [r["id"] for r in self.con.execute("SELECT * FROM kalkulationen ORDER BY id") if not self.nachrechnen(r)["gleich"]]
        anzahl = self.con.execute("SELECT COUNT(*) FROM kalkulationen").fetchone()[0]
        return {"anzahl": anzahl, "ok": not abweichend, "abweichend": abweichend}
