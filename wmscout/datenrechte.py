"""Datenrechte (Phase G0, ADR-030; P1-14a): Widerruf einer Verkaufsanfrage, Anonymisieren von Inseraten – für App und Kommandozeile.

Reihenfolge: offene Demo-Auktionen ohne Zuschlag beenden (Auktionsdaten enthalten keine Personendaten), dann
``VerkaufSpeicher.widerruf`` (anonymisieren, Freitexte und Fotos löschen). Ein Ankauf verhindert das Löschen (Aufbewahrung).
Verzeichnis der Daten und Fristen: docs/DATENRECHTE.md.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .auktion import AuktionSpeicher
from .datenbank import Datenbank
from .eingang.email import mail_ordner
from .verkauf import VerkaufSpeicher

log = logging.getLogger("scout")


def widerruf(db: Datenbank, cfg: dict, foto_ordner: Path, anfrage_id: int, nutzer_id: int | None, grund: str = "widerruf") -> dict:
    """``ValueError`` bei bestehendem Ankauf (nichts geändert), ``LookupError`` wenn es die Anfrage nicht gibt. ``grund="frist"``:
    dieselbe Löschung nach Ablauf der Aufbewahrungsfrist (F10) – der Status der Anfrage bleibt."""
    verkauf = VerkaufSpeicher(db, Path(foto_ordner) / "anfragen")
    if not verkauf.lade(anfrage_id):
        raise LookupError("Anfrage nicht gefunden")
    tabellen = {r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "ankaeufe" in tabellen and db.con.execute("SELECT 1 FROM ankaeufe WHERE anfrage_id=?",
                                                 (anfrage_id,)).fetchone():
        raise ValueError("Für diese Anfrage gibt es einen Ankaufsvorgang – Kaufunterlagen unterliegen der Aufbewahrungspflicht; "
                         "nicht automatisch löschen, Einzelfall klären")
    auktion = AuktionSpeicher(db, cfg)
    for a in auktion.fuer_anfrage(anfrage_id):
        if a["status"] == "laeuft":
            auktion.abbrechen(a["id"], nutzer_id, "Widerruf des Verkäufers" if grund == "widerruf" else "Aufbewahrungsfrist abgelaufen")
        elif a["status"] == "beendet":
            auktion.entscheiden(a["id"], nutzer_id, False)
    return verkauf.widerruf(anfrage_id, nutzer_id, grund)


# ---------------------------------------------------------------- Inserate fremder Börsen (P1-14a, F10)
ERSATZ = "[Name entfernt]"
DIAGNOSE = ("diagnose_suchseite.html", "diagnose_detailseite.html")     # Rohseiten bei Layout-Verdacht (importer.py)


class InseratGekauft(ValueError):
    """Gekaufte Fahrzeuge (Status oder Ankaufsvorgang) unterliegen der Aufbewahrung – nie automatisch anonymisieren."""


def _loeschen(pfade) -> int:
    """Dateien nach dem Commit entfernen; eine gesperrte Datei (Windows) bricht nichts ab, sondern wird protokolliert."""
    n = 0
    for pfad in pfade:
        try:
            if pfad.is_file():
                pfad.unlink()
                n += 1
        except OSError as e:
            log.warning("Datenschutz: %s nicht gelöscht (%s) – bitte von Hand entfernen", pfad, type(e).__name__)
    return n


def inserat_anonymisieren(db: Datenbank, ausgabe_ordner: Path, anzeige_id: str, foto_ordner: Path | None = None) -> dict:
    """Personendaten eines Inserats entfernen – im Umfang wie der Widerruf einer Verkaufsanfrage: Profilname des Verkäufers
    (``details_json``), Name im gespeicherten Anschreibentext und in den Texten des Kontaktverlaufs, Team-Notiz, in Besichtigungen
    Verkäuferangaben, Unterschriften, Adresse, Eingaben vor Ort (FIN, Kennzeichen, Notizen) und Fotos sowie die Anschreiben-Datei in
    ``ausgabe/``. Fahrzeugdaten des Inserats, Preise, Status und Kontaktzeitpunkte bleiben (Marktbeobachtung). Gekaufte Fahrzeuge: ``InseratGekauft``;
    unbekannte Inserate: ``LookupError``. Die Prüfung läuft in derselben Transaktion wie das Schreiben."""
    from .bewertung.anschreiben import anrede_name, verkaeufer_name
    con = db.con
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    besichtigungen, fotos = 0, []
    with db.transaktion():
        a = con.execute("SELECT * FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone()
        if not a:
            raise LookupError(f"Inserat {anzeige_id} unbekannt")
        if a["status"] == "gekauft" or ("ankaeufe" in tabellen and con.execute(
                "SELECT 1 FROM ankaeufe WHERE anzeige_id=?", (anzeige_id,)).fetchone()):
            raise InseratGekauft(f"Inserat {anzeige_id} ist gekauft – Kaufunterlagen unterliegen der Aufbewahrung, nicht automatisch löschen")
        name = verkaeufer_name(dict(a))
        try:
            details = json.loads(a["details_json"] or "{}")
        except ValueError:
            details = {}                                  # unlesbar: Inhalt verwerfen statt das Inserat dauerhaft auszulassen
        details.pop("verkaeufer_name", None)
        details["anonymisiert_am"] = datetime.now().isoformat(timespec="seconds")
        varianten = {name, anrede_name(name) or name} if name else set()

        def ohne_namen(text):
            for variante in varianten:
                text = text.replace(variante, ERSATZ) if text else text
            return text
        con.execute("UPDATE anzeigen SET details_json=?, anschreiben_text=?, notiz=NULL WHERE id=?",
                    (json.dumps(details, ensure_ascii=False), ohne_namen(a["anschreiben_text"]), anzeige_id))
        if "kontakte" in tabellen and varianten:          # Texte im Kontaktverlauf (P3-06) wie das Anschreiben
            for k in con.execute("SELECT id, text FROM kontakte WHERE anzeige_id=? AND text IS NOT NULL", (anzeige_id,)).fetchall():
                con.execute("UPDATE kontakte SET text=? WHERE id=?", (ohne_namen(k["text"]), k["id"]))
        for b in con.execute("SELECT id, basis_json, protokoll_json FROM besichtigungen WHERE anzeige_id=?", (anzeige_id,)).fetchall():
            basis = json.loads(b["basis_json"] or "{}")
            basis.pop("verkaeufer", None)
            protokoll = json.loads(b["protokoll_json"]) if b["protokoll_json"] else None
            if protokoll:
                for feld in ("verkaeufer", "unterschrift_verkaeufer", "unterschrift_ankaeufer", "bemerkung"):
                    protokoll.pop(feld, None)
                if isinstance(protokoll.get("fahrzeug"), dict):
                    for feld in ("fin", "kennzeichen"):
                        protokoll["fahrzeug"].pop(feld, None)
            con.execute("UPDATE besichtigungen SET basis_json=?, protokoll_json=?, adresse=NULL, daten_json='{}', ergebnis_json=NULL "
                        "WHERE id=?", (json.dumps(basis, ensure_ascii=False),
                                       json.dumps(protokoll, ensure_ascii=False) if protokoll else None, b["id"]))
            if "fotos" in tabellen:
                fotos += [(b["id"], r[0]) for r in con.execute("SELECT datei FROM fotos WHERE besichtigung_id=?", (b["id"],))]
                con.execute("DELETE FROM fotos WHERE besichtigung_id=?", (b["id"],))
            besichtigungen += 1
    dateien = [Path(ausgabe_ordner) / "anschreiben" / f"{anzeige_id}.txt"]
    if foto_ordner is not None:
        dateien += [Path(foto_ordner) / str(int(bid)) / d for bid, d in fotos]
    _loeschen(dateien)
    return {"anzeige_id": anzeige_id, "name_entfernt": bool(name), "besichtigungen": besichtigungen, "fotos": len(fotos)}


def inserate_nach_frist(db: Datenbank, ausgabe_ordner: Path, monate: int, jetzt: datetime | None = None,
                        foto_ordner: Path | None = None) -> list[str]:
    """Alle Inserate ohne Kauf und ohne offene Besichtigung, deren letzte Aktivität (zuletzt gesehen, Status, Kontakt) älter als
    ``monate`` ist und die noch Personendaten tragen, anonymisieren. ``monate`` ≤ 0: nichts (Standard, bis der Betreiber
    Fristen festlegt)."""
    if not monate or monate <= 0:
        return []
    erledigt = []
    for anzeige_id in inserate_faellig(db, monate, jetzt):
        try:
            inserat_anonymisieren(db, ausgabe_ordner, anzeige_id, foto_ordner)
            erledigt.append(anzeige_id)
        except InseratGekauft:
            continue                                      # Ankaufsvorgang ohne Status „gekauft“ – Aufbewahrung
    return erledigt


def grenze_monate(monate: int, jetzt: datetime | None = None) -> datetime:
    return (jetzt or datetime.now()) - timedelta(days=round(monate * 30.44))


def inserate_faellig(db: Datenbank, monate: int, jetzt: datetime | None = None) -> list[str]:
    """Inserate, die ``inserate_nach_frist`` anonymisieren würde (ohne Kauf, ohne offene Besichtigung, noch mit Personendaten)."""
    if not monate or monate <= 0:
        return []
    grenze = grenze_monate(monate, jetzt).isoformat(timespec="seconds")
    # Ankaufsvorgang ohne Status „gekauft“: Aufbewahrung – nicht fällig, sonst meldete jeder Lauf es erneut (QA F10 B3)
    ankauf = (" AND id NOT IN (SELECT anzeige_id FROM ankaeufe WHERE anzeige_id IS NOT NULL)"
              if db.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ankaeufe'").fetchone() else "")
    return [r[0] for r in db.con.execute(
        "SELECT id FROM anzeigen WHERE COALESCE(status, 'neu') != 'gekauft' "
        "AND MAX(COALESCE(zuletzt_gesehen, ''), COALESCE(status_am, ''), COALESCE(kontaktiert_am, '')) < ? "
        "AND (details_json LIKE '%verkaeufer_name%' OR anschreiben_text IS NOT NULL OR notiz IS NOT NULL "
        "     OR id IN (SELECT anzeige_id FROM kontakte WHERE text IS NOT NULL) "
        "     OR id IN (SELECT anzeige_id FROM besichtigungen WHERE anzeige_id IS NOT NULL)) "
        "AND id NOT IN (SELECT anzeige_id FROM besichtigungen WHERE anzeige_id IS NOT NULL AND status IN ('geplant', 'laeuft')) "
        "AND COALESCE(details_json, '') NOT LIKE '%anonymisiert_am%'" + ankauf, (grenze,))]


def diagnose_nach_frist(ausgabe_ordner: Path, monate: int, jetzt: datetime | None = None) -> int:
    """Rohseiten aus der Layout-Diagnose (enthalten ganze Inserate) nach derselben Frist löschen (Q11)."""
    return _loeschen(diagnose_faellig(ausgabe_ordner, monate, jetzt))


def diagnose_faellig(ausgabe_ordner: Path, monate: int, jetzt: datetime | None = None) -> list[Path]:
    if not monate or monate <= 0:
        return []
    grenze = grenze_monate(monate, jetzt).timestamp()
    alt = [Path(ausgabe_ordner) / n for n in DIAGNOSE]
    return [p for p in alt if p.is_file() and p.stat().st_mtime < grenze]


MAIL_ABLAGEN = ("eingelesen", "nicht_erkannt", "fehlerhaft")      # Unterordner von import/email/, die der Scout selbst anlegt (P2-06)


def _ist_verknuepfung(pfad: Path) -> bool:
    """Symbolische Verknüpfung oder Junction (Windows): nie verfolgen – sie könnte aus dem Import-Ordner herausführen."""
    return pfad.is_symlink() or (hasattr(pfad, "is_junction") and pfad.is_junction())


def mails_nach_frist(ordner: Path, monate: int, jetzt: datetime | None = None) -> int:
    """Alles, was der Scout von Benachrichtigungs-Mails abgelegt hat (`<ordner>` = import/email), nach derselben Frist löschen (P2-06):
    `eingelesen/<Datum>/*.eml`, `nicht_erkannt/*.eml` und `fehlerhaft/*.eml`. Maßgeblich ist das spätere von Datumsordner (ISO-Name, nicht in der
    Zukunft) und Änderungszeit der Datei; wo es keinen Datumsordner gibt, die Änderungszeit (der Import setzt sie beim Ablegen auf „jetzt“).
    Leere Datumsordner verschwinden mit. Verknüpfungen und Junctions werden nie verfolgt, nur `*.eml`-Dateien gelöscht. Noch nicht
    verarbeitete Mails direkt in `<ordner>` bleiben unberührt (siehe `mails_unverarbeitet`). ``monate`` ≤ 0: nichts."""
    gefunden = mails_faellig(ordner, monate, jetzt)
    n = _loeschen(gefunden)
    for tag in {p.parent for p in gefunden if p.parent.parent.name == "eingelesen"}:
        try:
            tag.rmdir()                                       # nur wenn leer
        except OSError:
            pass
    return n


def mails_faellig(ordner: Path, monate: int, jetzt: datetime | None = None) -> list[Path]:
    """Die Dateien, die ``mails_nach_frist`` löschen würde."""
    return _abgelegt_faellig(Path(ordner), monate, jetzt, MAIL_ABLAGEN, lambda p: p.suffix.lower() == ".eml")


def _abgelegt_faellig(ordner: Path, monate: int, jetzt: datetime | None, ablagen, passt) -> list[Path]:
    """Vom Scout abgelegte Dateien (``<ordner>/<ablage>/`` bzw. ``eingelesen/<Datum>/``), älter als die Frist: maßgeblich ist das spätere
    von Datumsordner (ISO-Name, nicht in der Zukunft) und Änderungszeit. Verknüpfungen und Junctions werden nie verfolgt."""
    if not monate or monate <= 0 or not ordner.is_dir():
        return []
    jetzt = jetzt or datetime.now()
    grenze = grenze_monate(monate, jetzt).timestamp()
    gefunden: list[Path] = []
    for ablage in ablagen:
        wurzel = ordner / ablage
        if not wurzel.is_dir() or _ist_verknuepfung(wurzel):
            continue
        ebenen = [(None, wurzel)]
        if ablage == "eingelesen":
            for tag in (p for p in wurzel.iterdir() if p.is_dir() and not _ist_verknuepfung(p)):
                try:
                    datum = datetime.combine(date.fromisoformat(tag.name), time.min)
                except ValueError:
                    datum = None
                ebenen.append((datum.timestamp() if datum and datum <= jetzt else None, tag))
        for tag_zeit, verzeichnis in ebenen:
            for p in verzeichnis.iterdir():
                if passt(p) and p.is_file() and not _ist_verknuepfung(p) and max(tag_zeit or 0, p.stat().st_mtime) < grenze:
                    gefunden.append(p)
    return gefunden


SEITEN_ABLAGEN = ("eingelesen", "nicht_erkannt")       # Unterordner von import/, die der Seitenimport anlegt


def seiten_faellig(ordner: Path, monate: int, jetzt: datetime | None = None) -> list[Path]:
    """Gespeicherte Seiten, die der Seitenimport abgelegt hat (``import/eingelesen/<Datum>/``, ``import/nicht_erkannt/``) – sie enthalten
    ganze Inserate samt Anbietername (F10, schließt die Lücke aus P1-14a). Unverarbeitete Seiten direkt in ``import/`` bleiben."""
    from .eingang.seiten import HTML_ENDUNGEN
    return _abgelegt_faellig(Path(ordner), monate, jetzt, SEITEN_ABLAGEN, lambda p: p.suffix.lower() in HTML_ENDUNGEN)


def seiten_nach_frist(ordner: Path, monate: int, jetzt: datetime | None = None) -> int:
    """Fällige gespeicherte Seiten samt Begleitordner (``<name>_files``) löschen; Verknüpfungen nie verfolgen."""
    import shutil

    from .eingang.seiten import BEGLEITORDNER
    gefunden = seiten_faellig(ordner, monate, jetzt)
    for datei in gefunden:
        for s in BEGLEITORDNER:
            begleiter = datei.with_name(f"{datei.stem}{s}")
            if begleiter.is_dir() and not _ist_verknuepfung(begleiter):
                try:
                    shutil.rmtree(begleiter)
                except OSError as e:
                    log.warning("Datenschutz: %s nicht gelöscht (%s) – bitte von Hand entfernen", begleiter, type(e).__name__)
    n = _loeschen(gefunden)
    for tag in {p.parent for p in gefunden if p.parent.parent.name == "eingelesen"}:
        try:
            tag.rmdir()
        except OSError:
            pass
    return n


def mails_unverarbeitet(ordner: Path, monate: int, jetzt: datetime | None = None) -> int:
    """Anzahl der `*.eml` direkt in `<ordner>` (import/email), die älter als die Frist sind und noch nicht eingelesen wurden. Sie werden nicht gelöscht
    (Betreiber entscheidet), aber gemeldet. ``monate`` ≤ 0: 0."""
    from .eingang.email import eml_dateien
    if not monate or monate <= 0:
        return 0
    grenze = ((jetzt or datetime.now()) - timedelta(days=round(monate * 30.44))).timestamp()
    return sum(1 for p in eml_dateien(Path(ordner)) if p.stat().st_mtime < grenze)


def mails_unverarbeitet_gemeldet(cfg: dict, ordner: Path) -> int:
    """Wie `mails_unverarbeitet` mit der Frist aus der Konfiguration (für Kommandozeile und App: „N Mails seit über Frist unverarbeitet“)."""
    try:
        return mails_unverarbeitet(ordner, frist_aus(cfg))
    except ValueError:
        return 0


def frist_anwenden(db: Datenbank, cfg: dict, basis: Path, foto_ordner: Path) -> list[str]:
    """Nach Suchlauf und Seitenimport sowie beim Start der App: alle Aufbewahrungsfristen (F10, ``aufbewahrung``) anwenden – mit
    ``datenschutz → automatisch: nur_bericht`` nur melden. Rückgabe: anonymisierte Inserate. Ein Fehler wird protokolliert und bricht
    den Lauf nie ab."""
    from . import aufbewahrung
    try:
        e = aufbewahrung.einstellungen(cfg)
        if e["automatisch"] == "ja":
            from .audit import AuditSpeicher
            plan = aufbewahrung.ausfuehren(db, cfg, basis, foto_ordner, audit=AuditSpeicher(db))     # Nachweis auch im Automatikbetrieb
        else:
            plan = aufbewahrung.bericht(db, cfg, basis)
            if faellig := sum(z["faellig"] + z.get("dateien", 0) for z in plan if z["aktion"] in ("anonymisieren", "loeschen")):
                log.warning("Aufbewahrungsfristen: %d Einträge/Dateien fällig – nur Bericht (datenschutz → automatisch); ausführen mit "
                            "python scout.py datenschutz --ausfuehren --bestaetigt", faellig)
        for z in plan:
            if z["aktion"] == "melden" and z["faellig"]:
                log.warning("Aufbewahrungsfristen: %d Ankäufe über der Aufbewahrungsfrist – Löschung von Hand prüfen (%s)", z["faellig"],
                            ", ".join(z["referenzen"][:5]))
        if ids := next((z.get("anzeige_ids", []) for z in plan if z["schluessel"] == "inserate_anonymisieren_nach_monaten"), []):
            log.info("Datenschutz-Frist: %d Inserate anonymisiert", len(ids))
        mail_dir = mail_ordner(cfg, basis)
        monate = e["inserate_anonymisieren_nach_monaten"]
        if offen := mails_unverarbeitet(mail_dir, monate):
            log.warning("Datenschutz-Frist: %d Mails liegen seit über %d Monaten unverarbeitet in %s – bitte einlesen oder löschen", offen, monate, mail_dir)
    except Exception:  # noqa: BLE001 – Datenschutz-Wartung darf Suchlauf/Import/Start nicht verhindern
        log.exception("Datenschutz-Frist konnte nicht angewendet werden")
        return []
    return ids


def frist_aus(cfg: dict) -> int:
    """config.yaml → datenschutz → inserate_anonymisieren_nach_monaten (0 = aus); prüft dabei den ganzen Abschnitt (F10)."""
    from .aufbewahrung import einstellungen
    return einstellungen(cfg)["inserate_anonymisieren_nach_monaten"]
