"""Laufprotokoll, Intervalle je Quelle und Pause nach einer Sperre (P4-04, ADR-050).

Jeder Suchlauf und jeder Import gespeicherter Seiten bzw. Mails wird in ``suchlaeufe`` (Schema v19) festgehalten: Auslöser, Beginn, Ende,
Ergebnis, Zähler und je Quelle Zahlen und Fehler. Daraus entstehen die Statusseite und – nur für automatische und geplante Läufe – die
Regeln, wann eine Quelle frühestens wieder abgerufen wird:

* **Intervall je Quelle** (``app.intervall_stunden_je_quelle``): mindestens so viele Stunden zwischen zwei automatischen Abrufen.
* **Pause nach einer Sperre** (``app.pause_nach_sperre_stunden``): hat die Quelle zuletzt mit 403/429/Captcha geantwortet, ruft die
  Automatik sie so lange nicht ab. Nichts wird umgangen – es wird nur gewartet (Regel 11).

Ein Lauf von Hand (Knopf in der App, ``scout.py lauf --sofort``) beachtet beides nicht; die Statusseite zeigt aber den Zustand.
Oben die Fachlogik ohne Datenbank, unten der Speicher.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger("scout")

ARTEN = {"suchlauf": "Suchlauf", "seiten": "Gespeicherte Seiten", "mails": "E-Mail-Suchagenten"}
AUSLOESER = {"manuell": "von Hand (App)", "auto": "automatisch (App)", "cli": "Kommandozeile / geplante Aufgabe"}
OK, FEHLER, GESPERRT, ABGEBROCHEN, LAEUFT = "ok", "fehler", "gesperrt", "abgebrochen", "laeuft"
ERGEBNISSE = {OK: "ohne Fehler", FEHLER: "mit Fehler", GESPERRT: "Quelle blockt (403/429/Captcha)", ABGEBROCHEN: "abgebrochen",
              LAEUFT: "läuft"}
AUFBEWAHRUNG_TAGE = 365                  # ältere Einträge löscht der nächste Lauf (kein Personenbezug, nur Platz)
VERWAIST_NACH_STUNDEN = 6                # ein „laufender“ Eintrag ohne Ende ist nach so langer Zeit ein abgebrochener Lauf
STANDARD_PAUSE_NACH_SPERRE = 24
MAX_STUNDEN = 720
MAX_FEHLERTEXT = 500


def _zahl(wert, unten: float, oben: float) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not unten <= wert <= oben:
        return None
    return wert


def einstellungen(cfg: dict | None, kennungen) -> dict:
    """``intervalle`` {Quelle: Stunden} und ``pause_nach_sperre_stunden`` aus ``config.yaml → app``. Unbrauchbare Werte und unbekannte Quellen
    werden gemeldet und übergangen (Pause: Standard 24 h) – ein Tippfehler darf den Lauf nicht verhindern."""
    app = (cfg or {}).get("app")
    app = app if isinstance(app, dict) else {}
    roh = app.get("intervall_stunden_je_quelle") or {}
    intervalle = {}
    if not isinstance(roh, dict):
        log.warning("config.yaml: app -> intervall_stunden_je_quelle muss eine Zuordnung Quelle: Stunden sein – wird ignoriert")
        roh = {}
    for kennung, stunden in roh.items():
        if kennung not in kennungen:
            log.warning("config.yaml: app -> intervall_stunden_je_quelle: unbekannte Quelle %r – wird ignoriert", kennung)
        elif _zahl(stunden, 0, MAX_STUNDEN) is None:
            log.warning("config.yaml: app -> intervall_stunden_je_quelle -> %s muss eine Zahl von 0 bis %d sein, nicht %r – wird ignoriert",
                        kennung, MAX_STUNDEN, stunden)
        elif stunden:
            intervalle[kennung] = stunden
    pause = app.get("pause_nach_sperre_stunden", STANDARD_PAUSE_NACH_SPERRE)
    if _zahl(pause, 0, MAX_STUNDEN) is None:
        log.warning("config.yaml: app -> pause_nach_sperre_stunden muss eine Zahl von 0 bis %d sein, nicht %r – es gilt %d",
                    MAX_STUNDEN, pause, STANDARD_PAUSE_NACH_SPERRE)
        pause = STANDARD_PAUSE_NACH_SPERRE
    return {"intervalle": intervalle, "pause_nach_sperre_stunden": pause}


def _zeit(iso) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if isinstance(iso, str) and iso else None
    except ValueError:
        return None


def wirksames_ergebnis(lauf: dict, jetzt: datetime) -> str:
    """„laeuft“ ohne Ende, das älter als ``VERWAIST_NACH_STUNDEN`` ist, war ein abgebrochener Lauf (Absturz, Stromausfall)."""
    if lauf["ergebnis"] == LAEUFT and not lauf.get("ende"):
        start = _zeit(lauf["start"])
        if start is None or start < jetzt - timedelta(hours=VERWAIST_NACH_STUNDEN):
            return ABGEBROCHEN
    return lauf["ergebnis"]


def quellen_status(laeufe: list[dict], kennungen, e: dict, jetzt: datetime) -> dict[str, dict]:
    """Je Pull-Quelle aus den Suchläufen (neueste zuerst, ``je_quelle`` als Dict): letzter Lauf, letzter Erfolg, Fehler in Folge, letzter
    Fehler, Pause nach Sperre bis, Intervall und ``naechster_auto`` (frühester automatischer Abruf; None = sofort)."""
    erg = {}
    for kennung in kennungen:
        eigene = [(lf, lf["je_quelle"][kennung]) for lf in laeufe if lf["art"] == "suchlauf" and kennung in lf["je_quelle"]
                  and wirksames_ergebnis({**lf, "ergebnis": lf["je_quelle"][kennung].get("ergebnis", lf["ergebnis"])}, jetzt) != LAEUFT]
        zustand = [wirksames_ergebnis({**lf, "ergebnis": q.get("ergebnis", lf["ergebnis"])}, jetzt) for lf, q in eigene]
        in_folge = next((i for i, z in enumerate(zustand) if z == OK), len(zustand))
        letzter = eigene[0] if eigene else None
        erfolg = next((lf for (lf, _), z in zip(eigene, zustand, strict=True) if z == OK), None)
        fehler = next((q.get("fehler") for (_, q), z in zip(eigene, zustand, strict=True) if z != OK and q.get("fehler")), None)
        pause_bis = None
        if letzter and zustand[0] == GESPERRT and e["pause_nach_sperre_stunden"]:
            ende = _zeit(letzter[0].get("ende")) or _zeit(letzter[0]["start"])
            pause_bis = ende + timedelta(hours=e["pause_nach_sperre_stunden"]) if ende else None
        intervall = e["intervalle"].get(kennung)
        kandidaten = [pause_bis]
        if letzter and intervall:
            start = _zeit(letzter[0]["start"])
            kandidaten.append(start + timedelta(hours=intervall) if start else None)
        naechster = max((k for k in kandidaten if k), default=None)
        erg[kennung] = {
            "letzter_lauf": letzter[0]["start"] if letzter else None, "letztes_ergebnis": zustand[0] if zustand else None,
            "letzter_erfolg": (erfolg.get("ende") or erfolg["start"]) if erfolg else None, "fehler_in_folge": in_folge,
            "letzter_fehler": fehler, "pause_bis": pause_bis.isoformat(timespec="seconds") if pause_bis else None,
            "intervall_stunden": intervall,
            "naechster_auto": naechster.isoformat(timespec="seconds") if naechster and naechster > jetzt else None,
        }
    return erg


def sperrgrund(status: dict, jetzt: datetime) -> str | None:
    """Grund, warum ein automatischer Lauf die Quelle jetzt überspringt (oder None)."""
    naechster = _zeit(status.get("naechster_auto"))
    if not naechster or naechster <= jetzt:
        return None
    zeit = naechster.strftime("%d.%m. %H:%M")
    if status.get("pause_bis") and _zeit(status["pause_bis"]) >= naechster:
        return f"Pause nach Sperre der Quelle bis {zeit} Uhr"
    return f"Intervall: frühestens wieder {zeit} Uhr"


def kurz(text) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_FEHLERTEXT else text[:MAX_FEHLERTEXT - 1] + "…"


# ---------------------------------------------------------------- Speicher
class Laufprotokoll:
    """Tabelle ``suchlaeufe`` (Schema v19). Schreibfehler werden protokolliert, nie weitergereicht: ein Lauf scheitert nicht am Protokoll."""

    def __init__(self, db):
        self.db = db

    def beginne(self, art: str, ausloeser: str) -> int | None:
        jetzt = datetime.now()
        try:
            with self.db.transaktion():
                self.db.con.execute("DELETE FROM suchlaeufe WHERE start < ?",
                                    ((jetzt - timedelta(days=AUFBEWAHRUNG_TAGE)).isoformat(timespec="seconds"),))
                return self.db.con.execute("INSERT INTO suchlaeufe (art, ausloeser, start) VALUES (?, ?, ?)",
                                           (art, ausloeser, jetzt.isoformat(timespec="seconds"))).lastrowid
        except Exception:  # noqa: BLE001 – das Protokoll darf den Lauf nicht verhindern
            log.exception("Laufprotokoll: Beginn nicht gespeichert")
            return None

    def beende(self, lauf_id: int | None, ergebnis: str, stat: dict, je_quelle: dict | None = None, uebersprungen: list | None = None,
               fehler: str | None = None):
        if lauf_id is None:
            return
        try:
            with self.db.transaktion():
                self.db.con.execute(
                    "UPDATE suchlaeufe SET ende=?, ergebnis=?, neu=?, preis=?, bekannt=?, details=?, dateien=?, fehler=?, je_quelle=?, "
                    "uebersprungen=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), ergebnis, int(stat.get("neu") or 0), int(stat.get("preis") or 0),
                     int(stat.get("bekannt") or 0), int(stat.get("details") or 0), stat.get("dateien"), kurz(fehler),
                     json.dumps(je_quelle or {}, ensure_ascii=False), json.dumps(uebersprungen or [], ensure_ascii=False), lauf_id))
        except Exception:  # noqa: BLE001
            log.exception("Laufprotokoll: Ende nicht gespeichert")

    def eintrag(self, art: str, ausloeser: str, start: str, ergebnis: str, stat: dict, fehler: str | None = None):
        """Abgeschlossenen Vorgang in einem Schritt festhalten (Importe: erst danach steht fest, ob Dateien gelesen wurden)."""
        lauf_id = self.beginne(art, ausloeser)
        if lauf_id is not None:
            try:
                with self.db.transaktion():
                    self.db.con.execute("UPDATE suchlaeufe SET start=? WHERE id=?", (start, lauf_id))
            except Exception:  # noqa: BLE001
                log.exception("Laufprotokoll: Beginn nicht gespeichert")
        self.beende(lauf_id, ergebnis, stat, fehler=fehler)

    def letzte(self, anzahl: int | None = 200, art: str | None = None, seit: datetime | None = None, nur_mit_quelle: bool = False) -> list[dict]:
        """Neueste zuerst. ``seit``: nur Läufe ab diesem Zeitpunkt (ohne Anzahlgrenze, für Intervall und Pause); ``nur_mit_quelle``: nur
        Läufe, die mindestens eine Quelle abgerufen haben. Eine beschädigte JSON-Spalte wird gemeldet und als leer gelesen."""
        bedingungen, werte = [], []
        if art:
            bedingungen.append("art=?")
            werte.append(art)
        if seit:
            bedingungen.append("start >= ?")
            werte.append(seit.isoformat(timespec="seconds"))
        if nur_mit_quelle:
            bedingungen.append("je_quelle NOT IN ('{}', '')")
        sql = ("SELECT * FROM suchlaeufe" + (" WHERE " + " AND ".join(bedingungen) if bedingungen else "") + " ORDER BY start DESC, id DESC"
               + (" LIMIT ?" if anzahl else ""))
        erg = []
        for z in self.db.con.execute(sql, (*werte, anzahl) if anzahl else werte):
            lf = dict(z)
            for spalte, leer in (("je_quelle", {}), ("uebersprungen", [])):
                try:
                    wert = json.loads(lf[spalte] or "null")
                except (TypeError, ValueError):
                    log.warning("Laufprotokoll: Eintrag %s, Spalte %s ist beschädigt – wird als leer gelesen", lf["id"], spalte)
                    wert = None
                lf[spalte] = wert if isinstance(wert, type(leer)) else leer
            erg.append(lf)
        return erg


# ---------------------------------------------------------------- Übersicht (Statusseite, API, CLI)
def uebersicht(db, cfg: dict, jetzt: datetime | None = None, anzahl_laeufe: int = 30) -> dict:
    """Pull-Quellen (Freigabe, Schalter, eingetragene Suchen, letzter Lauf/Erfolg, Fehler in Folge, Intervall, Pause, nächster automatischer
    Abruf), Eingänge (an/aus, letzter Import), die letzten Läufe und Warnungen. Nur lesen; ohne Personendaten."""
    from .quellen import QUELLEN
    from .quellen.basis import Suchauftrag
    from .schalter import eingaenge, quelle_laeuft
    jetzt = jetzt or datetime.now()
    e = einstellungen(cfg, QUELLEN)
    protokoll = Laufprotokoll(db)
    alle = protokoll.letzte()
    status = quellen_status(protokoll.letzte(500, art="suchlauf", nur_mit_quelle=True), QUELLEN, e, jetzt)
    suchen: dict[str, int] = {}
    for eintrag in cfg.get("suchen") or []:
        q = Suchauftrag.aus_config(eintrag).quelle
        suchen[q] = suchen.get(q, 0) + 1
    quellen, warnungen = [], []
    for kennung in sorted(QUELLEN):
        klasse = QUELLEN[kennung]
        laeuft, grund = quelle_laeuft(db, klasse)
        s = status[kennung]
        quellen.append({"kennung": kennung, "name": getattr(klasse, "name", kennung), "zugriffsart": klasse.zugriffsart,
                        "freigegeben": bool(klasse.freigegeben), "laeuft": laeuft, "grund": grund, "suchen": suchen.get(kennung, 0),
                        "sperrgrund": sperrgrund(s, jetzt), **s})
        if laeuft and suchen.get(kennung) and s["fehler_in_folge"] >= 3:
            warnungen.append(f"{kennung}: {s['fehler_in_folge']} Läufe in Folge mit Fehler – zuletzt: {s['letzter_fehler'] or 'ohne Text'}")
        if s["pause_bis"] and s["naechster_auto"]:
            p = s["pause_bis"]
            warnungen.append(f"{kennung}: Quelle hat zuletzt geblockt – automatische Abrufe pausieren bis {p[8:10]}.{p[5:7]}. {p[11:16]} Uhr")
    art_je_eingang = {"seiten": "seiten", "email": "mails"}
    eingang = []
    for name, an in eingaenge(cfg).items():
        letzter = next(iter(protokoll.letzte(1, art=art_je_eingang[name])), None) if name in art_je_eingang else None
        eingang.append({"name": name, "aktiv": an, "protokolliert": name in art_je_eingang,
                        "letzter_import": letzter["start"] if letzter else None,
                        "letztes_ergebnis": wirksames_ergebnis(letzter, jetzt) if letzter else None})
    laeufe = [{**{k: lf[k] for k in ("id", "art", "ausloeser", "start", "ende", "neu", "preis", "bekannt", "details", "dateien",
                                     "fehler", "je_quelle", "uebersprungen")},
               "ergebnis": wirksames_ergebnis(lf, jetzt)} for lf in alle[:anzahl_laeufe]]
    if any(lf["ergebnis"] == ABGEBROCHEN for lf in laeufe[:5]):
        warnungen.append("Ein Lauf wurde abgebrochen (z. B. Absturz oder Stromausfall) – Protokoll unten prüfen")
    app = cfg.get("app") or {}
    if float(app.get("auto_suche_stunden") or 0) > 0 and not any(q["laeuft"] and q["suchen"] for q in quellen):
        warnungen.append("Die automatische Suche ist eingeschaltet, aber keine eingetragene Suche gehört zu einer laufenden Quelle")
    return {"jetzt": jetzt.isoformat(timespec="seconds"), "quellen": quellen, "eingaenge": eingang, "laeufe": laeufe,
            "warnungen": warnungen, "pause_nach_sperre_stunden": e["pause_nach_sperre_stunden"],
            "auto_suche_stunden": float(app.get("auto_suche_stunden") or 0)}
