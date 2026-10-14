"""Datensicherung und Wiederherstellung (R3, P1-02).

Sicherung über die SQLite-Backup-API (konsistent, auch bei geöffneter Datenbank), danach ``PRAGMA integrity_check``
auf der Kopie. Fotos (``daten/fotos/``) kommen als ZIP daneben. Aufbewahrung: nur die letzten N eigenen Sicherungen.
Das Datenbankschema kennt dieses Modul nicht; die Prüfung "ist das eine Scout-Datenbank?" kommt beim Wiederherstellen
aus ``migrationen`` (nur dort, lokal importiert, um den Importzyklus zu vermeiden) oder per Parameter ``pruefung``.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STANDARD_BEHALTEN = 10
TEIL_MAX_ALTER = 3600            # Sekunden: liegen gebliebene .teil-Dateien älter als das werden beim Sichern aufgeräumt
_ZUSATZ = re.compile(r"[^A-Za-z0-9-]+")
_SQLITE_BUSY, _SQLITE_LOCKED = 5, 6


class SicherungsFehler(RuntimeError):
    """Verständliche Meldung für den Betreiber."""


@dataclass
class Wiederherstellung:
    sicherung_vorher: Path | None     # Sicherung des Stands vor der Wiederherstellung (bzw. Rohkopie bei defekter DB)
    fotos_wiederhergestellt: bool
    alter_fotoordner: Path | None     # bisherige Fotos, nur umbenannt (nicht gelöscht)


def pruefe_behalten(wert) -> int:
    """Aufbewahrung: ganze Zahl >= 1 (None = Standard). Sonst ``ValueError`` mit verständlicher Meldung."""
    if wert is None:
        return STANDARD_BEHALTEN
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 1:
        raise ValueError(f"Ungültige Aufbewahrung „behalten“: {wert!r} – erwartet wird eine ganze Zahl ab 1 (config.yaml -> sicherung -> behalten)")
    return wert


def sicherung_ordner(cfg: dict, basis: Path) -> Path:
    """Sicherungsordner aus ``config.yaml`` (Abschnitt ``sicherung``); relative Angaben gelten ab ``basis``."""
    return basis / ((cfg.get("sicherung") or {}).get("ordner") or "daten/sicherungen")


def einstellungen(cfg: dict, basis: Path) -> tuple[Path, int]:
    """Sicherungsordner und (geprüfte) Aufbewahrung aus ``config.yaml``; ``ValueError`` bei ungültigem ``behalten``."""
    return sicherung_ordner(cfg, basis), pruefe_behalten((cfg.get("sicherung") or {}).get("behalten"))


def oeffne_lesend(pfad: str | Path, timeout: float = 30) -> sqlite3.Connection:
    """Nur lesen (``mode=ro``): legt nie eine Datei an, auch wenn der Pfad nicht (mehr) existiert."""
    return sqlite3.connect(f"{Path(pfad).resolve().as_uri()}?mode=ro", uri=True, timeout=timeout)


def _muster(stem: str) -> re.Pattern:
    # <db>-sicherung-<JJJJMMTT-HHMMSS>[_<Zähler>][-<zusatz>].sqlite
    return re.compile(rf"^{re.escape(stem)}-sicherung-(\d{{8}}-\d{{6}})(?:_(\d+))?(?:-[A-Za-z0-9-]+)?\.sqlite$")


def _teil_muster(stem: str) -> re.Pattern:
    return re.compile(rf"^\.{re.escape(stem)}-sicherung-\d{{8}}-\d{{6}}(?:_\d+)?(?:-[A-Za-z0-9-]+)?\.(?:sqlite|fotos)\.teil$")


def _reihenfolge(muster: re.Pattern, ordner: Path) -> list[Path]:
    """Eigene Sicherungen, älteste zuerst (Zeitstempel, dann Zähler innerhalb derselben Sekunde)."""
    treffer = [(p, muster.match(p.name)) for p in ordner.iterdir() if p.is_file()]
    return [p for p, m in sorted(((p, m) for p, m in treffer if m), key=lambda t: (t[1].group(1), int(t[1].group(2) or 1), t[0].name))]


def _integritaet(pfad: Path, anzeigename: str | None = None):
    name = anzeigename or pfad.name
    try:
        con = oeffne_lesend(pfad)
        try:
            ergebnis = [r[0] for r in con.execute("PRAGMA integrity_check")]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise SicherungsFehler(f"{name} ist keine lesbare SQLite-Datenbank ({e})") from e
    if ergebnis != ["ok"]:
        raise SicherungsFehler(f"Integritätsprüfung von {name} fehlgeschlagen: {'; '.join(ergebnis[:5])}")


def _kopiere_db(quelle: Path, ziel: Path):
    """Backup-API: konsistente Kopie. Die Quelle wird nur lesend geöffnet (fehlt sie, entsteht keine Datei);
    Verbindungen werden in jedem Fall geschlossen (Windows-Dateisperren)."""
    try:
        src = oeffne_lesend(quelle)
        try:
            dst = sqlite3.connect(str(ziel))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.Error as e:
        raise SicherungsFehler(f"{quelle.name} lässt sich nicht lesen/kopieren ({e})") from e


def _pruefe_sperre(db_pfad: Path, timeout: float):
    """Technische Sperrprüfung: Läuft noch ein Schreiber (App, Suchlauf, geplante Aufgabe), bricht die Wiederherstellung ab."""
    if not db_pfad.is_file():
        return
    try:
        con = sqlite3.connect(f"{db_pfad.resolve().as_uri()}?mode=rw", uri=True, timeout=timeout, isolation_level=None)
    except sqlite3.Error:
        return
    try:
        con.execute("BEGIN EXCLUSIVE")
        con.execute("ROLLBACK")
    except sqlite3.OperationalError as e:
        if (getattr(e, "sqlite_errorcode", 0) or 0) & 0xFF in (_SQLITE_BUSY, _SQLITE_LOCKED):
            raise SicherungsFehler("Die Datenbank ist in Benutzung (App, Suchlauf oder geplante Aufgabe läuft noch?). "
                                   "Alles beenden und erneut versuchen. Es wurde nichts verändert.") from e
    except sqlite3.DatabaseError:
        pass                            # defekte Datei: kein Sperrproblem, wird beim Sichern/Austausch behandelt
    finally:
        con.close()


def _zippe_fotos(foto_ordner: Path, ziel: Path) -> bool:
    dateien = [p for p in sorted(foto_ordner.rglob("*")) if p.is_file()] if foto_ordner.is_dir() else []
    if not dateien:
        return False
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_STORED) as z:   # Fotos sind bereits komprimiert
        for p in dateien:
            z.write(p, p.relative_to(foto_ordner).as_posix())
    return True


def _entferne_still(pfad: Path):
    try:
        pfad.unlink(missing_ok=True)
    except OSError:
        pass


def sichere(db_pfad: str | Path, ziel_ordner: str | Path, foto_ordner: str | Path | None = None,
            behalten: int = STANDARD_BEHALTEN, zusatz: str = "", aufraeumen: bool = True) -> Path:
    """Legt ``<db>-sicherung-<Zeit>[-zusatz].sqlite`` (+ ``.fotos.zip``) im Zielordner an und gibt den DB-Pfad zurück.

    Wirft ``SicherungsFehler``, wenn die Kopie die Integritätsprüfung nicht besteht (Kopie wird dann verworfen).
    Mit ``aufraeumen`` bleiben danach nur die letzten ``behalten`` Sicherungen dieser Datenbank erhalten.
    """
    db_pfad, ziel_ordner = Path(db_pfad), Path(ziel_ordner)
    behalten = pruefe_behalten(behalten)
    if not db_pfad.is_file():
        raise SicherungsFehler(f"Datenbank {db_pfad} nicht gefunden")
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    _raeume_teildateien_auf(ziel_ordner, db_pfad.stem)
    zusatz = _ZUSATZ.sub("-", zusatz).strip("-")
    zeit = datetime.now().strftime("%Y%m%d-%H%M%S")
    nachsatz = f"-{zusatz}" if zusatz else ""
    # mehrere Sicherungen in derselben Sekunde: Zähler fortlaufend über dem größten vorhandenen
    gleiche = [m for p in ziel_ordner.iterdir() if (m := _muster(db_pfad.stem).match(p.name)) and m.group(1) == zeit]
    basis = f"{db_pfad.stem}-sicherung-{zeit}" + (f"_{max(int(m.group(2) or 1) for m in gleiche) + 1}" if gleiche else "") + nachsatz
    ziel, foto_ziel = ziel_ordner / f"{basis}.sqlite", ziel_ordner / f"{basis}.fotos.zip"
    teil_db, teil_foto = ziel_ordner / f".{basis}.sqlite.teil", ziel_ordner / f".{basis}.fotos.teil"
    try:
        _kopiere_db(db_pfad, teil_db)
        _integritaet(teil_db, f"Kopie von {db_pfad.name}")
        if foto_ordner and _zippe_fotos(Path(foto_ordner), teil_foto):
            os.replace(teil_foto, foto_ziel)
        os.replace(teil_db, ziel)
    except BaseException as e:
        _entferne_still(teil_db)
        _entferne_still(teil_foto)
        if not ziel.exists():
            _entferne_still(foto_ziel)
        if isinstance(e, sqlite3.Error):
            raise SicherungsFehler(f"Datenbank {db_pfad.name} lässt sich nicht sichern ({e}). Es wurde keine Kopie angelegt.") from e
        raise
    if aufraeumen:
        _raeume_auf(ziel_ordner, db_pfad.stem, behalten)
    return ziel


def _raeume_teildateien_auf(ordner: Path, stem: str):
    """Entfernt liegen gebliebene eigene ``.teil``-Dateien (Abbruch bei früherer Sicherung); frische bleiben (laufende Sicherung)."""
    muster, grenze = _teil_muster(stem), time.time() - TEIL_MAX_ALTER
    for p in ordner.iterdir():
        try:
            if muster.match(p.name) and p.is_file() and p.stat().st_mtime < grenze:
                _entferne_still(p)
        except OSError:
            pass


def _raeume_auf(ordner: Path, stem: str, behalten: int, geschuetzt: tuple[Path, ...] = ()):
    """Löscht ausschließlich eigene, überzählige Sicherungen (Namensmuster) samt zugehörigem Foto-ZIP.
    ``geschuetzt`` (z. B. die gerade zurückgespielte Quelle) wird nie gelöscht."""
    ausnahmen = {Path(g).resolve() for g in geschuetzt}
    for alt in _reihenfolge(_muster(stem), ordner)[:-behalten]:
        if alt.resolve() in ausnahmen:
            continue
        _entferne_still(alt)
        _entferne_still(alt.with_name(alt.name[: -len(".sqlite")] + ".fotos.zip"))


def sicherungen(ordner: str | Path, db_stem: str) -> list[Path]:
    """Vorhandene Sicherungen der Datenbank, älteste zuerst."""
    ordner = Path(ordner)
    if not ordner.is_dir():
        return []
    return _reihenfolge(_muster(db_stem), ordner)


def _entpacke_sicher(zip_pfad: Path, ziel: Path):
    ziel_abs = ziel.resolve()
    with zipfile.ZipFile(zip_pfad) as z:
        if z.testzip() is not None:
            raise SicherungsFehler(f"Foto-Archiv {zip_pfad.name} ist beschädigt")
        for info in z.infolist():
            ziel_datei = (ziel / info.filename).resolve()
            if ziel_abs != ziel_datei and ziel_abs not in ziel_datei.parents:
                raise SicherungsFehler(f"Foto-Archiv {zip_pfad.name} enthält unzulässige Pfade")
        z.extractall(ziel)


def wiederherstellen(sicherung: str | Path, db_pfad: str | Path, bestaetigt: bool = False,
                     ziel_ordner: str | Path | None = None, foto_ordner: str | Path | None = None,
                     behalten: int = STANDARD_BEHALTEN, pruefung: Callable[[Path], None] | None = None,
                     sperr_timeout: float = 2.0) -> Wiederherstellung:
    """Spielt eine Sicherung zurück. Nur mit ``bestaetigt=True`` (App und Suchlauf müssen beendet sein).

    Reihenfolge: Quelle in eine Arbeitskopie neben der Datenbank kopieren, prüfen (Integrität, Scout-Datenbank,
    Version) und Fotos entpacken -> Sperrprüfung -> Stand vor der Wiederherstellung sichern (ohne Aufräumen) ->
    Datenbank atomar austauschen -> Fotoordner austauschen -> erst jetzt Aufbewahrung (die Quelle bleibt immer erhalten).
    Bei jedem Fehler vor dem Austausch bleibt die bestehende Datenbank unverändert.
    """
    sicherung, db_pfad = Path(sicherung), Path(db_pfad)
    behalten = pruefe_behalten(behalten)
    if not bestaetigt:
        raise SicherungsFehler("Wiederherstellung abgebrochen: App und Suchlauf beenden, dann mit --bestaetigt wiederholen. "
                               "Es wurde nichts verändert.")
    if not sicherung.is_file():
        raise SicherungsFehler(f"Sicherung {sicherung} nicht gefunden")
    if pruefung is None:
        from .migrationen import pruefe_wiederherstellbar as pruefung
    ziel_ordner = Path(ziel_ordner) if ziel_ordner else sicherung.parent
    db_pfad.parent.mkdir(parents=True, exist_ok=True)
    teil = db_pfad.with_name(f".{db_pfad.name}.wiederherstellung.teil")
    foto_zip = sicherung.with_name(sicherung.name[: -len(".sqlite")] + ".fotos.zip")
    foto_ordner = Path(foto_ordner) if foto_ordner else None
    neu = foto_ordner.with_name(f".{foto_ordner.name}.wiederherstellung.teil") if foto_ordner and foto_zip.is_file() else None

    vorher = None
    try:
        # 1. Quelle zuerst in eine Arbeitskopie (nur lesend), dann prüfen – ab hier hängt nichts mehr von der Quelldatei ab
        _entferne_still(teil)
        _kopiere_db(sicherung, teil)
        _integritaet(teil, sicherung.name)
        pruefung(teil)
        # 2. Fotos entpacken und prüfen (Zip-Slip), noch ohne etwas zu verändern
        if neu is not None:
            shutil.rmtree(neu, ignore_errors=True)
            neu.mkdir(parents=True)
            _entpacke_sicher(foto_zip, neu)
        # 3. Läuft noch ein Schreiber? Dann abbrechen, bevor etwas entsteht. SQLite räumt beim Öffnen -wal/-journal
        #    selbst auf (Wiederherstellung bzw. Verwerfen); vorher eine Kopie davon aufheben, damit nichts verloren geht.
        _hebe_reste_auf(db_pfad, ziel_ordner)
        _pruefe_sperre(db_pfad, sperr_timeout)
        # 4. Stand davor sichern – ohne Aufräumen, damit keine Sicherung (auch nicht die Quelle) verschwindet
        if db_pfad.is_file():
            try:
                vorher = sichere(db_pfad, ziel_ordner, foto_ordner, behalten, zusatz="vor-wiederherstellung", aufraeumen=False)
            except (SicherungsFehler, sqlite3.Error):
                # Defekte Datenbank: Rohkopie behalten (außerhalb der Aufbewahrungsregel), damit nichts verloren geht
                vorher = ziel_ordner / f"{db_pfad.stem}-defekt-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite.defekt"
                ziel_ordner.mkdir(parents=True, exist_ok=True)
                shutil.copy2(db_pfad, vorher)
            _pruefe_sperre(db_pfad, sperr_timeout)
        # 5. Austausch; Reste der alten Datenbank dürfen nicht zur neuen passen (erst jetzt, nach erfolgreicher Sperrprüfung)
        for endung in ("-wal", "-shm", "-journal"):
            _entferne_still(db_pfad.with_name(db_pfad.name + endung))
        try:
            os.replace(teil, db_pfad)
        except PermissionError as e:
            raise SicherungsFehler(f"Datenbank ist noch in Benutzung ({e}). App, Suchlauf und geplante Aufgaben beenden "
                                   "und erneut versuchen.") from e
    except BaseException:
        _entferne_still(teil)
        if neu is not None:
            shutil.rmtree(neu, ignore_errors=True)
        raise

    fotos, alt = False, None
    if neu is not None:
        try:
            if foto_ordner.exists():
                alt = _freier_name(foto_ordner.with_name(f"{foto_ordner.name}.alt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"))
                foto_ordner.rename(alt)
            neu.rename(foto_ordner)
            fotos = True
        except OSError as e:
            raise SicherungsFehler(_fotofehler(e, foto_ordner, alt, neu, foto_zip, vorher)) from e
    try:
        if ziel_ordner.is_dir():
            _raeume_auf(ziel_ordner, db_pfad.stem, behalten, geschuetzt=(sicherung,))
    except OSError:
        pass
    return Wiederherstellung(vorher, fotos, alt)


def _hebe_reste_auf(db_pfad: Path, ziel_ordner: Path):
    """Kopiert vorhandene ``-wal``/``-journal`` der alten Datenbank als ``<db>-reste-<Zeit>-wal`` usw. in den Sicherungsordner."""
    reste = [r for r in (db_pfad.with_name(db_pfad.name + e) for e in ("-wal", "-journal")) if r.is_file() and r.stat().st_size]
    if reste:
        ziel_ordner.mkdir(parents=True, exist_ok=True)
        zeit = datetime.now().strftime("%Y%m%d-%H%M%S")
        for r in reste:
            shutil.copy2(r, _freier_name(ziel_ordner / f"{db_pfad.stem}-reste-{zeit}{r.name[len(db_pfad.name):]}"))


def _freier_name(pfad: Path) -> Path:
    """Hängt bei Namensgleichheit (zwei Wiederherstellungen in derselben Sekunde) einen Zähler an; nichts wird überschrieben."""
    kandidat, n = pfad, 1
    while kandidat.exists():
        n += 1
        kandidat = pfad.with_name(f"{pfad.name}_{n}")
    return kandidat


def _fotofehler(e: OSError, foto_ordner: Path, alt: Path | None, neu: Path, foto_zip: Path, vorher: Path | None) -> str:
    """Datenbank ist schon zurückgespielt, der Fotoschritt scheiterte: Rückweg versuchen und klar melden."""
    if alt is not None and not foto_ordner.exists():
        try:
            alt.rename(foto_ordner)
            alt = None
        except OSError:
            pass
    if alt is None:
        shutil.rmtree(neu, ignore_errors=True)
        wo = f"Die bisherigen Fotos liegen unverändert in {foto_ordner}." if foto_ordner.exists() else "Der Fotoordner blieb unverändert."
    else:
        wo = f"Der alte Stand der Fotos liegt in {alt}; die Fotos der Sicherung liegen entpackt in {neu} (Archiv: {foto_zip})."
    davor = f" Stand der Datenbank davor: {vorher}." if vorher else ""
    return (f"Datenbank wiederhergestellt, Fotos NICHT ({e}). {wo} Die Fotos der Sicherung lassen sich später aus "
            f"{foto_zip.name} nachholen.{davor}")
