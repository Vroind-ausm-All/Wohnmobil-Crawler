"""Demo-Auktionen (Phase D, ADR-027): geprüfte Standorte bieten auf freigegebene Verkaufsanfragen.

Nur Demo – nichts ist verbindlich, einen Zuschlag bestätigt ausschließlich der Inhaber (Projektregel 10). Beträge sind ganze
Euro, Zeiten UTC (``JJJJ-MM-TTThh:mm:ssZ``, als Text vergleichbar). Jede Änderung läuft unter der Schreibsperre
(``BEGIN IMMEDIATE``): prüfen und schreiben sind eine Einheit, auch gegen andere Prozesse – gleichzeitige Gebote ergeben genau
ein gültiges Höchstgebot. Ein Gebot trägt eine Wiederholungs-ID (doppelt gesendet = einmal gezählt).

Kein Dauerprozess: Ob eine Auktion abgelaufen ist, wird bei jedem Zugriff geprüft; der Abschluss ist idempotent.
Protokoll und Gebote sind nur anfügbar (Trigger), das Protokoll ist zusätzlich hash-verkettet (``pruefe_protokoll``).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .datenbank import Datenbank
from .haendler import HaendlerSpeicher

STATUS = {"laeuft": "läuft", "beendet": "beendet – Entscheidung offen", "zugeschlagen": "Zuschlag bestätigt (Demo)",
          "abgelehnt": "kein Zuschlag", "abgebrochen": "abgebrochen"}
ERGEBNISSE = {"kein_gebot": "kein Gebot", "unter_mindestpreis": "Mindestpreis nicht erreicht",
              "mindestpreis_erreicht": "Mindestpreis erreicht"}
NULL_HASH = "0" * 64
MAX_BETRAG = 10_000_000
STANDARD = object()          # Mindestpreis nicht angegeben → Preisvorstellung des Verkäufers
_WIEDERHOLUNGS_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")


class AuktionsFehler(ValueError):
    """Aktion abgelehnt, Meldung für den Nutzer. ``status`` ordnet sie für die API ein (400, 403, 404, 409)."""

    def __init__(self, meldung: str, status: int = 409, extra: dict | None = None):
        super().__init__(meldung)
        self.status, self.extra = status, extra or {}


def jetzt_utc() -> datetime:
    return datetime.now(timezone.utc)


def zeit(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _datum(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _ganzzahl(wert, name: str) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int):
        raise AuktionsFehler(f"{name} muss ein ganzer Euro-Betrag sein", 400)
    return wert


def einstellungen(cfg: dict) -> dict:
    """Abschnitt ``auktion`` aus config.yaml mit Standardwerten; ValueError mit verständlicher Meldung bei Unsinn."""
    roh = cfg.get("auktion") or {}
    e = {"laufzeit_stunden": 24, "laufzeit_min_stunden": 1, "laufzeit_max_stunden": 168, "schritt": 100,
         "verlaengerung_minuten": 2, "startpreis_anteil": 0.7}
    for schluessel in e:
        wert = roh.get(schluessel, e[schluessel])
        if isinstance(wert, bool) or not isinstance(wert, (int, float)) or wert < 0:
            raise ValueError(f"config.yaml: auktion -> {schluessel} muss eine Zahl ≥ 0 sein, nicht {wert!r}")
        e[schluessel] = wert
    for schluessel in ("laufzeit_stunden", "laufzeit_min_stunden", "laufzeit_max_stunden", "schritt", "verlaengerung_minuten"):
        if e[schluessel] != int(e[schluessel]):
            raise ValueError(f"config.yaml: auktion -> {schluessel} muss eine ganze Zahl sein")
        e[schluessel] = int(e[schluessel])
    if not (1 <= e["laufzeit_min_stunden"] <= e["laufzeit_stunden"] <= e["laufzeit_max_stunden"]):
        raise ValueError("config.yaml: auktion -> es muss gelten 1 ≤ laufzeit_min_stunden ≤ laufzeit_stunden ≤ laufzeit_max_stunden")
    if e["schritt"] < 1 or not 0 < e["startpreis_anteil"] <= 1:
        raise ValueError("config.yaml: auktion -> schritt ≥ 1 und 0 < startpreis_anteil ≤ 1")
    return e


def protokoll_hash(vorher: str, eintrag_id: int, auktion_id: int, zeitpunkt: str, ereignis: str, nutzer_id: int | None,
                   daten_json: str) -> str:
    roh = json.dumps([vorher, eintrag_id, auktion_id, zeitpunkt, ereignis, nutzer_id, daten_json], ensure_ascii=False,
                     separators=(",", ":"))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


class AuktionSpeicher:
    def __init__(self, db: Datenbank, cfg: dict):
        self.db, self.con = db, db.con
        self.e = einstellungen(cfg)
        self.haendler = HaendlerSpeicher(db)

    # ---------- Protokoll ----------
    def _protokolliere(self, auktion_id: int, ereignis: str, nutzer_id: int | None, daten: dict, zeitpunkt: str):
        """Nur innerhalb einer Transaktion: unter der Schreibsperre ist „letzter Eintrag“ eindeutig."""
        letzte = self.con.execute("SELECT id, hash FROM auktion_protokoll ORDER BY id DESC LIMIT 1").fetchone()
        neue_id, vorher = (letzte[0] + 1, letzte[1]) if letzte else (1, NULL_HASH)
        daten_json = json.dumps(daten, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        h = protokoll_hash(vorher, neue_id, auktion_id, zeitpunkt, ereignis, nutzer_id, daten_json)
        self.con.execute("INSERT INTO auktion_protokoll (id, auktion_id, zeitpunkt_utc, ereignis, nutzer_id, daten_json, vorher_hash, hash) "
                         "VALUES (?,?,?,?,?,?,?,?)", (neue_id, auktion_id, zeitpunkt, ereignis, nutzer_id, daten_json, vorher, h))

    def pruefe_protokoll(self) -> dict:
        """Kette lückenlos (IDs fortlaufend), jeder Hash nachrechenbar, jedes Gebot genau so protokolliert, wie es gespeichert ist.
        Grenze: Wer Schreibzugriff auf die Datei hat, kann die letzten Einträge samt Kette abschneiden – dagegen hilft nur, den
        letzten Hash außerhalb festzuhalten (``scout.py auktion pruefen`` zeigt ihn)."""
        fehler, vorher, erwartet, protokolliert = [], NULL_HASH, 1, {}
        for r in self.con.execute("SELECT * FROM auktion_protokoll ORDER BY id"):
            if r["id"] != erwartet:
                fehler.append(f"Eintrag {erwartet} fehlt (nächster ist {r['id']})")
            if r["vorher_hash"] != vorher:
                fehler.append(f"Eintrag {r['id']}: Verkettung gebrochen")
            if protokoll_hash(r["vorher_hash"], r["id"], r["auktion_id"], r["zeitpunkt_utc"], r["ereignis"], r["nutzer_id"],
                              r["daten_json"]) != r["hash"]:
                fehler.append(f"Eintrag {r['id']}: Inhalt verändert")
            if r["ereignis"] == "gebot":
                d = json.loads(r["daten_json"])
                protokolliert[d.get("gebot_id")] = (r["auktion_id"], d.get("standort_id"), d.get("betrag"))
            vorher, erwartet = r["hash"], r["id"] + 1
        for g in self.con.execute("SELECT id, auktion_id, standort_id, betrag FROM gebote ORDER BY id"):
            if protokolliert.pop(g["id"], None) != (g["auktion_id"], g["standort_id"], g["betrag"]):
                fehler.append(f"Gebot {g['id']} passt nicht zum Protokoll")
        fehler += [f"Gebot {gid} steht im Protokoll, fehlt aber" for gid in protokolliert]
        return {"ok": not fehler, "eintraege": erwartet - 1, "letzter_hash": vorher, "fehler": fehler[:20]}

    def protokoll(self, auktion_id: int) -> list[dict]:
        return [{**dict(r), "daten": json.loads(r["daten_json"])} for r in
                self.con.execute("SELECT * FROM auktion_protokoll WHERE auktion_id=? ORDER BY id", (auktion_id,))]

    def _verlauf(self, anfrage_id: int, nutzer_id: int | None, text: str):
        self.con.execute("INSERT INTO anfrage_verlauf (anfrage_id, zeitpunkt, nutzer_id, ereignis, alt, neu) VALUES (?,?,?,?,?,?)",
                         (anfrage_id, datetime.now().isoformat(timespec="seconds"), nutzer_id, "auktion", None, text))

    # ---------- Zustandsmaschine (laeuft → beendet → zugeschlagen | abgelehnt; laeuft → abgebrochen) ----------
    def _auktion(self, auktion_id: int) -> sqlite3.Row:
        a = self.con.execute("SELECT * FROM auktionen WHERE id=?", (auktion_id,)).fetchone()
        if not a:
            raise AuktionsFehler("Auktion nicht gefunden", 404)
        return a

    def _hoechstgebot(self, auktion_id: int) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM gebote WHERE auktion_id=? ORDER BY betrag DESC LIMIT 1", (auktion_id,)).fetchone()

    def _freigegeben(self, anfrage_id: int) -> dict | None:
        z = self.haendler._zeilen(" AND v.id=?", (anfrage_id,))
        return z[0] if z else None

    def anlegen(self, anfrage_id: int, nutzer_id: int, *, startpreis=None, mindestpreis=STANDARD, laufzeit_stunden=None,
                jetzt: datetime | None = None) -> int:
        """Nur der Inhaber (prüft die API). Anfrage muss für Standorte freigegeben sein; je Anfrage eine aktive Auktion."""
        e, jetzt = self.e, jetzt or jetzt_utc()
        stunden = e["laufzeit_stunden"] if laufzeit_stunden is None else _ganzzahl(laufzeit_stunden, "Laufzeit")
        if not e["laufzeit_min_stunden"] <= stunden <= e["laufzeit_max_stunden"]:
            raise AuktionsFehler(f"Laufzeit {e['laufzeit_min_stunden']}–{e['laufzeit_max_stunden']} Stunden", 400)
        with self.db.transaktion():
            a = self._freigegeben(anfrage_id)
            if not a:
                raise AuktionsFehler("Auktion nur für offene Anfragen mit Zustimmung des Verkäufers und Freigabe für Standorte")
            if self.con.execute("SELECT 1 FROM auktionen WHERE anfrage_id=? AND status IN ('laeuft','beendet','zugeschlagen')",
                                (anfrage_id,)).fetchone():
                raise AuktionsFehler("Für diese Anfrage gibt es schon eine laufende oder zugeschlagene Auktion")
            pv = a["preisvorstellung"]
            if mindestpreis is STANDARD:
                mindestpreis = pv or None
            elif mindestpreis is not None:
                mindestpreis = _ganzzahl(mindestpreis, "Mindestpreis")
            if startpreis is None:
                if not pv:
                    raise AuktionsFehler("Ohne Preisvorstellung bitte einen Startpreis angeben", 400)
                startpreis = max(e["schritt"], int(pv * e["startpreis_anteil"]) // e["schritt"] * e["schritt"])
            startpreis = _ganzzahl(startpreis, "Startpreis")
            for name, wert in (("Startpreis", startpreis), ("Mindestpreis", mindestpreis)):
                if wert is not None and not 0 < wert <= MAX_BETRAG:
                    raise AuktionsFehler(f"{name} muss zwischen 1 und {MAX_BETRAG:,} € liegen".replace(",", "."), 400)
            start, ende = zeit(jetzt), zeit(jetzt + timedelta(hours=stunden))
            aid = self.con.execute(
                "INSERT INTO auktionen (anfrage_id, startpreis, mindestpreis, schritt, start_utc, ende_utc, verlaengerung_sek, erstellt_von) "
                "VALUES (?,?,?,?,?,?,?,?)", (anfrage_id, startpreis, mindestpreis, e["schritt"], start, ende,
                                             e["verlaengerung_minuten"] * 60, nutzer_id)).lastrowid
            self._protokolliere(aid, "gestartet", nutzer_id, {"anfrage_id": anfrage_id, "startpreis": startpreis, "mindestpreis": mindestpreis,
                                                              "schritt": e["schritt"], "ende_utc": ende,
                                                              "verlaengerung_sek": e["verlaengerung_minuten"] * 60}, start)
            self._verlauf(anfrage_id, nutzer_id, f"Demo-Auktion gestartet (Start {startpreis} €, Ende {ende})")
        return aid

    def abschliessen_faellige(self, jetzt: datetime | None = None) -> int:
        """Abgelaufene Auktionen beenden – bei jedem Zugriff aufgerufen, idempotent (zweiter Aufruf findet nichts mehr)."""
        j = zeit(jetzt or jetzt_utc())
        if not self.con.execute("SELECT 1 FROM auktionen WHERE status='laeuft' AND ende_utc<=? LIMIT 1", (j,)).fetchone():
            return 0                 # Normalfall ohne Schreibsperre
        anzahl = 0
        with self.db.transaktion():
            for a in self.con.execute("SELECT * FROM auktionen WHERE status='laeuft' AND ende_utc<=? ORDER BY id", (j,)).fetchall():
                h = self._hoechstgebot(a["id"])
                ergebnis = ("kein_gebot" if not h else
                            "unter_mindestpreis" if a["mindestpreis"] and h["betrag"] < a["mindestpreis"] else "mindestpreis_erreicht")
                cur = self.con.execute("UPDATE auktionen SET status='beendet', ergebnis=?, gewinner_gebot_id=?, beendet_utc=? "
                                       "WHERE id=? AND status='laeuft'", (ergebnis, h["id"] if h else None, a["ende_utc"], a["id"]))
                if cur.rowcount:
                    anzahl += 1
                    self._protokolliere(a["id"], "beendet", None, {"ergebnis": ergebnis, "hoechstgebot_id": h["id"] if h else None,
                                                                   "betrag": h["betrag"] if h else None, "ende_utc": a["ende_utc"]}, j)
        return anzahl

    def gebot_abgeben(self, auktion_id: int, standort_id: int, nutzer_id: int, betrag, wiederholungs_id, *,
                      jetzt: datetime | None = None) -> dict:
        """Atomar: Status, Ende, Freigabe, Höchstgebot und Wiederholungs-ID werden unter der Schreibsperre geprüft."""
        betrag = _ganzzahl(betrag, "Gebot")
        if not isinstance(wiederholungs_id, str) or not _WIEDERHOLUNGS_ID.fullmatch(wiederholungs_id):
            raise AuktionsFehler("Wiederholungs-ID fehlt oder ist ungültig (8–64 Zeichen A–Z, 0–9, _ oder -)", 400)
        if not 0 < betrag <= MAX_BETRAG:
            raise AuktionsFehler("Gebot außerhalb des zulässigen Bereichs", 400)
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        j = zeit(jetzt)
        with self.db.transaktion():
            a = self._auktion(auktion_id)
            schon = self.con.execute("SELECT * FROM gebote WHERE auktion_id=? AND nutzer_id=? AND wiederholungs_id=?",
                                     (auktion_id, nutzer_id, wiederholungs_id)).fetchone()
            if schon:            # dieselbe Anfrage noch einmal (z. B. Netz weg) → dasselbe Ergebnis, kein zweites Gebot
                if schon["betrag"] != betrag:
                    raise AuktionsFehler("Diese Wiederholungs-ID gehört zu einem anderen Gebot", 409)
                return {"gebot_id": schon["id"], "betrag": betrag, "ende_utc": a["ende_utc"], "verlaengert": False, "wiederholt": True}
            if a["status"] != "laeuft" or a["ende_utc"] <= j:
                raise AuktionsFehler("Die Auktion ist beendet", 409)
            if not self.con.execute("SELECT 1 FROM standorte WHERE id=? AND status='geprueft'", (standort_id,)).fetchone():
                raise AuktionsFehler("Bieten nur für geprüfte Standorte", 403)
            if not self._freigegeben(a["anfrage_id"]):
                raise AuktionsFehler("Die Anfrage ist nicht mehr freigegeben – keine Gebote möglich", 409)
            h = self._hoechstgebot(auktion_id)
            if h and h["standort_id"] == standort_id:
                raise AuktionsFehler("Ihr Standort hat bereits das Höchstgebot", 409)
            mindest = h["betrag"] + a["schritt"] if h else a["startpreis"]
            if betrag < mindest:
                raise AuktionsFehler(f"Mindestgebot ist jetzt {mindest} €", 409, {"mindestgebot": mindest})
            ende, verlaengert = a["ende_utc"], False
            if (_datum(ende) - jetzt).total_seconds() < a["verlaengerung_sek"]:
                ende, verlaengert = zeit(jetzt + timedelta(seconds=a["verlaengerung_sek"])), True
                self.con.execute("UPDATE auktionen SET ende_utc=? WHERE id=?", (ende, auktion_id))
            gid = self.con.execute("INSERT INTO gebote (auktion_id, standort_id, nutzer_id, betrag, zeitpunkt_utc, wiederholungs_id) "
                                   "VALUES (?,?,?,?,?,?)", (auktion_id, standort_id, nutzer_id, betrag, j, wiederholungs_id)).lastrowid
            self._protokolliere(auktion_id, "gebot", nutzer_id, {"gebot_id": gid, "standort_id": standort_id, "betrag": betrag,
                                                                 "wiederholungs_id": wiederholungs_id, "ende_utc": ende,
                                                                 "verlaengert": verlaengert}, j)
        return {"gebot_id": gid, "betrag": betrag, "ende_utc": ende, "verlaengert": verlaengert, "wiederholt": False}

    def abbrechen(self, auktion_id: int, nutzer_id: int, grund: str = "", *, jetzt: datetime | None = None):
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        with self.db.transaktion():
            a = self._auktion(auktion_id)
            if a["status"] != "laeuft":
                raise AuktionsFehler("Nur eine laufende Auktion kann abgebrochen werden")
            grund = (grund or "").strip()[:300] or None
            self.con.execute("UPDATE auktionen SET status='abgebrochen', grund=?, entschieden_utc=?, entschieden_von=? WHERE id=?",
                             (grund, zeit(jetzt), nutzer_id, auktion_id))
            self._protokolliere(auktion_id, "abgebrochen", nutzer_id, {"grund": grund}, zeit(jetzt))
            self._verlauf(a["anfrage_id"], nutzer_id, "Demo-Auktion abgebrochen" + (f": {grund}" if grund else ""))

    def entscheiden(self, auktion_id: int, nutzer_id: int, zuschlag: bool, *, jetzt: datetime | None = None):
        """Nach dem Ende: Zuschlag ausdrücklich bestätigen (Demo, nicht verbindlich) oder ablehnen."""
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        with self.db.transaktion():
            a = self._auktion(auktion_id)
            if a["status"] != "beendet":
                raise AuktionsFehler("Entscheiden erst nach dem Ende und nur einmal")
            if zuschlag and not a["gewinner_gebot_id"]:
                raise AuktionsFehler("Ohne Gebot gibt es keinen Zuschlag")
            neu = "zugeschlagen" if zuschlag else "abgelehnt"
            self.con.execute("UPDATE auktionen SET status=?, entschieden_utc=?, entschieden_von=? WHERE id=? AND status='beendet'",
                             (neu, zeit(jetzt), nutzer_id, auktion_id))
            g = self.con.execute("SELECT g.betrag, s.name FROM gebote g JOIN standorte s ON s.id=g.standort_id WHERE g.id=?",
                                 (a["gewinner_gebot_id"],)).fetchone() if zuschlag else None
            self._protokolliere(auktion_id, neu, nutzer_id, {"gebot_id": a["gewinner_gebot_id"] if zuschlag else None}, zeit(jetzt))
            self._verlauf(a["anfrage_id"], nutzer_id, f"Demo-Zuschlag bestätigt: {g['name']}, {g['betrag']} € (nicht verbindlich)"
                          if g else "Demo-Auktion: kein Zuschlag")

    # ---------- Sichten ----------
    def _kopf(self, a: sqlite3.Row, jetzt: datetime) -> dict:
        h = self._hoechstgebot(a["id"])
        anzahl = self.con.execute("SELECT COUNT(*) FROM gebote WHERE auktion_id=?", (a["id"],)).fetchone()[0]
        return {"id": a["id"], "anfrage_id": a["anfrage_id"], "status": a["status"], "status_text": STATUS[a["status"]],
                "ergebnis": a["ergebnis"], "ergebnis_text": ERGEBNISSE.get(a["ergebnis"]), "demo": True,
                "startpreis": a["startpreis"], "schritt": a["schritt"], "start_utc": a["start_utc"], "ende_utc": a["ende_utc"],
                "rest_sek": max(0, int((_datum(a["ende_utc"]) - jetzt).total_seconds())) if a["status"] == "laeuft" else 0,
                "hoechstgebot": h["betrag"] if h else None, "gebote_anzahl": anzahl,
                "mindestpreis_erreicht": None if a["mindestpreis"] is None else bool(h and h["betrag"] >= a["mindestpreis"]),
                "naechstes_mindestgebot": h["betrag"] + a["schritt"] if h else a["startpreis"], "_hoechst": h}

    def fuer_standort(self, standort_id: int, *, jetzt: datetime | None = None) -> list[dict]:
        """Bieter-Sicht: laufende Auktionen freigegebener Anfragen und beendete, an denen der Standort beteiligt war.
        Nie Mindestpreis, andere Standorte oder Kontaktdaten – nur „Mindestpreis erreicht ja/nein“."""
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        sichtbar = {f["id"]: f for f in self.haendler.sichtbare(standort_id)}
        aus = []
        for a in self.con.execute("SELECT a.*, v.referenz, v.marke, v.modell, v.ez_jahr, v.km FROM auktionen a "
                                  "JOIN verkaufsanfragen v ON v.id=a.anfrage_id WHERE (a.status='laeuft' AND a.anfrage_id IN (%s)) "
                                  "OR a.id IN (SELECT auktion_id FROM gebote WHERE standort_id=?) ORDER BY a.status != 'laeuft', a.ende_utc"
                                  % ",".join("?" * len(sichtbar)), (*sichtbar, standort_id)).fetchall():
            k = self._kopf(a, jetzt)
            h = k.pop("_hoechst")
            eigenes = self.con.execute("SELECT MAX(betrag) FROM gebote WHERE auktion_id=? AND standort_id=?",
                                       (a["id"], standort_id)).fetchone()[0]
            fuehrt = bool(h and standort_id and h["standort_id"] == standort_id)
            k.update({"referenz": a["referenz"], "fahrzeug": {x: a[x] for x in ("marke", "modell", "ez_jahr", "km")},
                      "du_fuehrst": fuehrt, "eigenes_hoechstes": eigenes,
                      "zuschlag_fuer_dich": a["status"] == "zugeschlagen" and fuehrt,
                      "bieten_moeglich": bool(standort_id) and a["status"] == "laeuft" and a["anfrage_id"] in sichtbar and not fuehrt})
            aus.append(k)
        return aus

    def fuer_anfrage(self, anfrage_id: int, *, jetzt: datetime | None = None) -> list[dict]:
        """Inhaber/Team: alle Auktionen einer Anfrage, neueste zuerst, mit Geboten (inkl. Standort) und Mindestpreis."""
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        return [self._voll(a, jetzt) for a in
                self.con.execute("SELECT * FROM auktionen WHERE anfrage_id=? ORDER BY id DESC", (anfrage_id,)).fetchall()]

    def lade(self, auktion_id: int, *, jetzt: datetime | None = None) -> dict:
        jetzt = jetzt or jetzt_utc()
        self.abschliessen_faellige(jetzt)
        return {**self._voll(self._auktion(auktion_id), jetzt), "protokoll": self.protokoll(auktion_id)}

    def _voll(self, a: sqlite3.Row, jetzt: datetime) -> dict:
        k = self._kopf(a, jetzt)
        h = k.pop("_hoechst")
        gebote = [dict(g) for g in self.con.execute(
            "SELECT g.id, g.betrag, g.zeitpunkt_utc, g.standort_id, s.name AS standort, n.name AS nutzer FROM gebote g "
            "JOIN standorte s ON s.id=g.standort_id LEFT JOIN nutzer n ON n.id=g.nutzer_id WHERE g.auktion_id=? ORDER BY g.betrag DESC",
            (a["id"],))]
        return {**k, "mindestpreis": a["mindestpreis"], "gewinner_gebot_id": a["gewinner_gebot_id"], "grund": a["grund"],
                "entschieden_utc": a["entschieden_utc"], "fuehrend": gebote[0]["standort"] if h else None, "gebote": gebote}
