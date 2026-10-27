"""Aufbewahrungsfristen (F10, ADR-058): ein Plan für alle personenbezogenen Daten – wie lange sie bleiben und was danach geschieht –
und ein Wartungsschritt, der Fälliges anonymisiert bzw. löscht oder nur meldet.

Aufrufer: Einzelplatz beim Start der App und nach Suchlauf/Import (``datenrechte.frist_anwenden``), Kommandozeile
(``scout.py datenschutz``, auch ``--alle-mandanten``), App für den Inhaber (``/api/datenschutz``) und später ein Server, der den
Schritt je Mandant regelmäßig aufruft (z. B. täglich per Aufgabenplanung – kein Dauerprozess im Programm). Jeder Aufruf ist
idempotent: Bereits Anonymisiertes ist nicht mehr fällig.

Fristen in config.yaml → datenschutz. Fachliche Annahmen, keine Rechtsberatung – vor dem Pilotbetrieb mit Datenschutzbeauftragtem
bzw. Steuerberatung abstimmen (docs/DATENRECHTE.md). Kaufunterlagen werden nie automatisch gelöscht, nur nach Fristablauf gemeldet.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import datenrechte
from .datenbank import Datenbank

log = logging.getLogger("scout")

# Schlüssel in config.yaml → datenschutz: (empfohlener Wert – so in config.yaml eingetragen, Einheit, Beschreibung). 0 = aus; ein fehlender
# Eintrag gilt als 0 (alte Konfigurationen löschen nichts, was sie vorher nicht gelöscht haben).
FRISTEN = {
    "inserate_anonymisieren_nach_monaten": (6, "Monate", "Inserate fremder Börsen ohne Kauf: Anbietername, Anschreiben, Notiz, Besichtigung "
                                            "anonymisieren; abgelegte Mails, gespeicherte Seiten und Diagnose-Rohseiten löschen"),
    "verkaufsanfragen_anonymisieren_nach_monaten": (12, "Monate", "Verkaufsanfragen ohne Ankauf nach der letzten Änderung: Verkäufer, "
                                                    "Freitexte, Fotos und Besichtigung löschen (wie ein Widerruf, der Status bleibt)"),
    "sitzungen_loeschen_nach_tagen": (30, "Tage", "abgelaufene Anmeldungen löschen"),
    "audit_loeschen_nach_monaten": (24, "Monate", "Audit-Protokoll (Nutzer, IP, Zugriffe) löschen"),
    "ankauf_aufbewahren_jahre": (10, "Jahre", "Kaufunterlagen (Vertrag, Protokoll, Unterschriften) ab Ende des Kalenderjahres – nach Ablauf "
                                 "nur melden, nie automatisch löschen"),
}
MODI = ("ja", "nur_bericht")


def einstellungen(cfg: dict) -> dict:
    """Wirksame Fristen (fehlende Einträge: 0 = aus) und ``automatisch`` (``ja`` = beim Start und nach Läufen ausführen,
    ``nur_bericht`` = dort nur melden). Fehleingaben verständlich melden."""
    roh = cfg.get("datenschutz") or {}
    if not isinstance(roh, dict):
        raise ValueError("config.yaml: datenschutz muss ein Abschnitt sein")
    erlaubt = {*FRISTEN, "automatisch"}
    if fremd := sorted(set(roh) - erlaubt):
        raise ValueError(f"config.yaml: datenschutz → unbekannte Einträge {', '.join(map(str, fremd))} (Tippfehler?) – erlaubt: "
                         f"{', '.join(sorted(erlaubt))}")
    erg = {}
    for k, (_, einheit, _) in FRISTEN.items():
        w = roh.get(k, 0)
        w = 0 if w is None else w
        if isinstance(w, bool) or not isinstance(w, int) or w < 0:
            raise ValueError(f"config.yaml: datenschutz → {k}: ganze Zahl ≥ 0 ({einheit}, 0 = aus), nicht {w!r}")
        erg[k] = w
    modus = roh.get("automatisch", "ja")
    modus = {True: "ja", False: "nur_bericht"}.get(modus, modus)
    if modus not in MODI:
        raise ValueError(f"config.yaml: datenschutz → automatisch: ja oder nur_bericht, nicht {modus!r}")
    erg["automatisch"] = modus
    return erg


def _pfade(cfg: dict, basis: Path) -> dict:
    from .eingang import import_ordner
    from .eingang.email import mail_ordner
    return {"ausgabe": Path(basis) / cfg["ausgabe"]["ordner"], "mails": mail_ordner(cfg, basis), "seiten": import_ordner(cfg, basis)}


def _tabellen(db: Datenbank) -> set[str]:
    return {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def anfragen_faellig(db: Datenbank, monate: int, jetzt: datetime | None = None) -> list[int]:
    """Verkaufsanfragen ohne Ankauf (auch keinen stornierten), ohne offene Besichtigung und ohne laufende oder unentschiedene Auktion,
    seit ``monate`` unverändert und seit dem letzten Widerruf bzw. der letzten Frist-Löschung wieder geändert (oder nie gelöscht)."""
    t = _tabellen(db)
    if not monate or "verkaufsanfragen" not in t:
        return []
    grenze = datenrechte.grenze_monate(monate, jetzt).isoformat(timespec="seconds")
    # schon gelöscht = Widerruf/Frist im Verlauf und seitdem keine Änderung (spätere Einträge wie eine neue Notiz werden wieder fällig, QA B8)
    sql = ("SELECT v.id FROM verkaufsanfragen v WHERE v.status != 'gekauft' AND v.aktualisiert_am < ? "
           "AND NOT EXISTS (SELECT 1 FROM anfrage_verlauf h WHERE h.anfrage_id=v.id AND h.ereignis IN ('widerruf', 'frist') "
           "                AND h.zeitpunkt >= v.aktualisiert_am)")
    if "auktionen" in t:          # laufende oder unentschiedene Auktion: Entscheidung bleibt beim Menschen (QA B10)
        sql += " AND NOT EXISTS (SELECT 1 FROM auktionen u WHERE u.anfrage_id=v.id AND u.status IN ('laeuft', 'beendet'))"
    if "ankaeufe" in t:
        sql += " AND NOT EXISTS (SELECT 1 FROM ankaeufe k WHERE k.anfrage_id=v.id)"
    if "anfrage_id" in {r[1] for r in db.con.execute("PRAGMA table_info(besichtigungen)")}:
        sql += " AND NOT EXISTS (SELECT 1 FROM besichtigungen b WHERE b.anfrage_id=v.id AND b.status IN ('geplant', 'laeuft'))"
    return [r[0] for r in db.con.execute(sql + " ORDER BY v.id", (grenze,))]


def _sitzungen_grenze(tage: int, jetzt: datetime | None) -> str:
    return ((jetzt or datetime.now()) - timedelta(days=tage)).isoformat(timespec="seconds")


def ankaeufe_faellig(db: Datenbank, jahre: int, jetzt: datetime | None = None) -> list[str]:
    """Ankäufe, deren Aufbewahrung abgelaufen ist: ``jahre`` ab Ende des Kalenderjahres des letzten Vorgangs (Vertrag, Übergabe, Zahlung,
    Verkauf, Anlage, jeder Eintrag im Ankaufsverlauf wie Storno oder Kosten) – nur zum Melden."""
    if not jahre or "ankaeufe" not in _tabellen(db):
        return []
    heute = (jetzt or datetime.now()).date()
    faellig = []
    verlauf = ("COALESCE((SELECT MAX(h.zeitpunkt) FROM ankauf_verlauf h WHERE h.ankauf_id=k.id), '')"
               if "ankauf_verlauf" in _tabellen(db) else "''")                 # auch Storno und spätere Buchungen (QA B9)
    for r in db.con.execute("SELECT referenz, MAX(COALESCE(vertrag_am, ''), COALESCE(uebergabe_am, ''), COALESCE(zahlung_am, ''), "
                            f"COALESCE(verkauft_am, ''), COALESCE(erstellt_am, ''), {verlauf}) AS zuletzt FROM ankaeufe k ORDER BY id"):
        try:
            jahr = int(str(r["zuletzt"])[:4])
        except ValueError:
            continue
        if heute >= date(jahr + jahre + 1, 1, 1):
            faellig.append(r["referenz"])
    return faellig


def _eintrag(schluessel: str, wert: int, aktion: str, faellig: int, **extra) -> dict:
    _, einheit, text = FRISTEN[schluessel]
    return {"schluessel": schluessel, "frist": wert, "einheit": einheit, "beschreibung": text, "aktion": aktion if wert else "aus",
            "faellig": faellig if wert else 0, "erledigt": 0, **extra}


def bericht(db: Datenbank, cfg: dict, basis: Path, jetzt: datetime | None = None) -> list[dict]:
    """Was nach den Fristen fällig ist – ändert nichts. Ohne Personendaten (nur Anzahlen und Ankaufs-Referenzen)."""
    e, pf = einstellungen(cfg), _pfade(cfg, basis)
    m = e["inserate_anonymisieren_nach_monaten"]
    dateien = (len(datenrechte.mails_faellig(pf["mails"], m, jetzt)) + len(datenrechte.seiten_faellig(pf["seiten"], m, jetzt))
               + len(datenrechte.diagnose_faellig(pf["ausgabe"], m, jetzt)))
    t = _tabellen(db)
    sitz = e["sitzungen_loeschen_nach_tagen"]
    audit = e["audit_loeschen_nach_monaten"]
    ankaeufe = ankaeufe_faellig(db, e["ankauf_aufbewahren_jahre"], jetzt)
    gesperrt = db.con.execute("SELECT COUNT(*) FROM nutzer WHERE aktiv=0").fetchone()[0] if "nutzer" in t else 0
    return [
        _eintrag("inserate_anonymisieren_nach_monaten", m, "anonymisieren", len(datenrechte.inserate_faellig(db, m, jetzt)), dateien=dateien if m else 0),
        _eintrag("verkaufsanfragen_anonymisieren_nach_monaten", e["verkaufsanfragen_anonymisieren_nach_monaten"], "anonymisieren",
                 len(anfragen_faellig(db, e["verkaufsanfragen_anonymisieren_nach_monaten"], jetzt))),
        _eintrag("sitzungen_loeschen_nach_tagen", sitz, "loeschen", db.con.execute(
            "SELECT COUNT(*) FROM sitzungen WHERE ablauf < ?", (_sitzungen_grenze(sitz, jetzt),)).fetchone()[0] if sitz and "sitzungen" in t else 0),
        _eintrag("audit_loeschen_nach_monaten", audit, "loeschen", db.con.execute(
            "SELECT COUNT(*) FROM audit WHERE zeitpunkt < ?", (datenrechte.grenze_monate(audit, jetzt).isoformat(timespec="seconds"),)
        ).fetchone()[0] if audit and "audit" in t else 0),
        _eintrag("ankauf_aufbewahren_jahre", e["ankauf_aufbewahren_jahre"], "melden", len(ankaeufe), referenzen=ankaeufe,
                 gesperrte_zugaenge=gesperrt),
    ]


def _audit_loeschen(db: Datenbank, grenze: str) -> int:
    """Das Audit-Protokoll ist nur anfügbar (Trigger, v10). Für die Frist wird der Lösch-Trigger in DERSELBEN Transaktion entfernt und
    wiederhergestellt – scheitert etwas, bleibt alles wie vorher."""
    with db.transaktion():
        db.con.execute("DROP TRIGGER IF EXISTS audit_kein_delete")
        n = db.con.execute("DELETE FROM audit WHERE zeitpunkt < ?", (grenze,)).rowcount
        db.con.execute("""CREATE TRIGGER IF NOT EXISTS audit_kein_delete BEFORE DELETE ON audit
            BEGIN SELECT RAISE(ABORT, 'audit ist nur anfügbar'); END""")
    return n


SICHERUNG_ZUSATZ = "vor-aufbewahrung"
SICHERUNGEN_BEHALTEN = 3


def _sichern(db: Datenbank, jetzt: datetime | None = None):
    """Sicherung (nur Datenbank) vor dem Schreiben – Regel 3 – in den Sicherungsordner der Datenbank (wie vor Migrationen). Höchstens
    eine je Tag und eigene Rotation (die letzten ``SICHERUNGEN_BEHALTEN``): Die allgemeine Rotation liefe über ALLE Sicherungen und
    verdrängte manuelle Vollsicherungen samt Fotos und die Sicherungen vor Migrationen (QA F10 B1). Gelöschtes bleibt bis zur Rotation in
    diesen Kopien."""
    from .sicherung import sichere
    pfad = db.con.execute("PRAGMA database_list").fetchone()[2]
    if not pfad:                                      # In-Memory-Datenbank: nichts zu sichern
        return
    ordner, stem = Path(db.sicherung_ordner), Path(pfad).stem
    muster = re.compile(rf"^{re.escape(stem)}-sicherung-(\d{{8}})-\d{{6}}(?:_\d+)?-{SICHERUNG_ZUSATZ}\.sqlite$")
    eigene = sorted(p for p in ordner.glob(f"{stem}-sicherung-*-{SICHERUNG_ZUSATZ}.sqlite") if muster.match(p.name)) if ordner.is_dir() else []
    heute = (jetzt or datetime.now()).strftime("%Y%m%d")
    if any(muster.match(p.name).group(1) == heute for p in eigene):
        return                                        # heute schon gesichert
    neu = sichere(pfad, ordner, None, zusatz=SICHERUNG_ZUSATZ, aufraeumen=False)
    for alt in [p for p in eigene if p != neu][:max(0, len(eigene) + 1 - SICHERUNGEN_BEHALTEN)]:
        try:
            alt.unlink()
        except OSError as e:
            log.warning("Aufbewahrung: alte Sicherung %s nicht gelöscht (%s)", alt.name, type(e).__name__)


def ausfuehren(db: Datenbank, cfg: dict, basis: Path, foto_ordner: Path, jetzt: datetime | None = None, *, sichern: bool = True,
               audit=None) -> list[dict]:
    """Fälliges anonymisieren bzw. löschen (Kaufunterlagen nur melden); Rückgabe wie ``bericht`` mit ``erledigt``. Vorher eine Sicherung,
    falls überhaupt etwas zu ändern ist. Ein Fehler in einer Kategorie hält die anderen nicht auf (``fehler`` im Eintrag)."""
    plan = bericht(db, cfg, basis, jetzt)
    e, pf = einstellungen(cfg), _pfade(cfg, basis)
    if sichern and any(z["aktion"] in ("anonymisieren", "loeschen") and (z["faellig"] or z.get("dateien")) for z in plan):
        _sichern(db, jetzt)
    nach = {z["schluessel"]: z for z in plan}

    def schritt(schluessel: str, fn):
        try:
            nach[schluessel]["erledigt"] = fn()
        except Exception as fehler:  # noqa: BLE001 – eine Kategorie darf die anderen nicht verhindern
            log.exception("Aufbewahrung: %s fehlgeschlagen", schluessel)
            nach[schluessel]["fehler"] = type(fehler).__name__
    m = e["inserate_anonymisieren_nach_monaten"]
    if m:
        def inserate() -> int:
            ids = datenrechte.inserate_nach_frist(db, pf["ausgabe"], m, jetzt=jetzt, foto_ordner=foto_ordner)
            nach["inserate_anonymisieren_nach_monaten"]["anzeige_ids"] = ids
            nach["inserate_anonymisieren_nach_monaten"]["dateien_geloescht"] = (
                datenrechte.mails_nach_frist(pf["mails"], m, jetzt) + datenrechte.seiten_nach_frist(pf["seiten"], m, jetzt)
                + datenrechte.diagnose_nach_frist(pf["ausgabe"], m, jetzt))
            return len(ids)
        schritt("inserate_anonymisieren_nach_monaten", inserate)
    if va := e["verkaufsanfragen_anonymisieren_nach_monaten"]:
        def anfragen() -> int:
            n = 0
            for anfrage_id in anfragen_faellig(db, va, jetzt):
                try:
                    datenrechte.widerruf(db, cfg, foto_ordner, anfrage_id, None, grund="frist")
                    n += 1
                except ValueError:
                    continue                              # inzwischen ein Ankaufsvorgang – Aufbewahrung
            return n
        schritt("verkaufsanfragen_anonymisieren_nach_monaten", anfragen)
    if (sitz := e["sitzungen_loeschen_nach_tagen"]) and "sitzungen" in _tabellen(db):
        def sitzungen() -> int:
            with db.transaktion():
                return db.con.execute("DELETE FROM sitzungen WHERE ablauf < ?", (_sitzungen_grenze(sitz, jetzt),)).rowcount
        schritt("sitzungen_loeschen_nach_tagen", sitzungen)
    if (au := e["audit_loeschen_nach_monaten"]) and nach["audit_loeschen_nach_monaten"]["faellig"]:
        schritt("audit_loeschen_nach_monaten", lambda: _audit_loeschen(db, datenrechte.grenze_monate(au, jetzt).isoformat(timespec="seconds")))
    erledigt = {z["schluessel"]: z["erledigt"] for z in plan if z["erledigt"]}
    if erledigt and audit is not None:                # Nachweis ohne Inhalte: nur Anzahlen je Kategorie
        audit.schreibe(None, "", "SYSTEM", "aufbewahrung", 200, "loeschen", ", ".join(f"{k}:{v}" for k, v in erledigt.items())[:200])
    if erledigt:
        log.info("Aufbewahrungsfristen angewendet: %s", ", ".join(f"{k}={v}" for k, v in erledigt.items()))
    return plan


def kurztext(plan: list[dict]) -> list[str]:
    """Zeilen für Kommandozeile und Protokoll."""
    zeilen = []
    for z in plan:
        frist = "aus" if z["aktion"] == "aus" else f"{z['frist']} {z['einheit']}"
        teile = [f"fällig {z['faellig']}"]
        if z.get("dateien"):
            teile.append(f"{z['dateien']} abgelegte Datei(en)")
        if z["erledigt"] or z.get("dateien_geloescht"):
            teile.append(f"erledigt {z['erledigt']}" + (f" (+{z['dateien_geloescht']} Dateien)" if z.get("dateien_geloescht") else ""))
        if z.get("referenzen"):
            teile.append("prüfen: " + ", ".join(z["referenzen"][:10]) + (" …" if len(z["referenzen"]) > 10 else ""))
        if z.get("gesperrte_zugaenge"):
            teile.append(f"{z['gesperrte_zugaenge']} gesperrte Zugänge – prüfen, ob löschbar")
        if z.get("fehler"):
            teile.append(f"FEHLER {z['fehler']}")
        zeilen.append(f"{z['schluessel']:<46} {frist:<11} {z['aktion']:<14} " + " · ".join(teile))
    return zeilen
