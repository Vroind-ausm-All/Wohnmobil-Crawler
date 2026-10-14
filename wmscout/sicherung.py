"""Datensicherung und Wiederherstellung (R3, P1-02).

Sicherung über die SQLite-Backup-API (konsistent, auch bei geöffneter Datenbank), danach ``PRAGMA integrity_check``
auf der Kopie. Fotos (``daten/fotos/``) kommen als ZIP daneben. Aufbewahrung: nur die letzten N eigenen Sicherungen.
Dieses Modul kennt das Datenbankschema nicht und importiert keine anderen Projektmodule.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STANDARD_BEHALTEN = 10
_ZUSATZ = re.compile(r"[^A-Za-z0-9-]+")


class SicherungsFehler(RuntimeError):
    """Verständliche Meldung für den Betreiber."""


@dataclass
class Wiederherstellung:
    sicherung_vorher: Path | None     # Sicherung des Stands vor der Wiederherstellung (bzw. Rohkopie bei defekter DB)
    fotos_wiederhergestellt: bool
    alter_fotoordner: Path | None     # bisherige Fotos, nur umbenannt (nicht gelöscht)


def _muster(stem: str) -> re.Pattern:
    # <db>-sicherung-<JJJJMMTT-HHMMSS>[_<Zähler>][-<zusatz>].sqlite
    return re.compile(rf"^{re.escape(stem)}-sicherung-(\d{{8}}-\d{{6}})(?:_(\d+))?(?:-[A-Za-z0-9-]+)?\.sqlite$")


def _reihenfolge(muster: re.Pattern, ordner: Path) -> list[Path]:
    """Eigene Sicherungen, älteste zuerst (Zeitstempel, dann Zähler innerhalb derselben Sekunde)."""
    treffer = [(p, muster.match(p.name)) for p in ordner.iterdir() if p.is_file()]
    return [p for p, m in sorted(((p, m) for p, m in treffer if m), key=lambda t: (t[1].group(1), int(t[1].group(2) or 1), t[0].name))]


def _integritaet(pfad: Path):
    con = sqlite3.connect(str(pfad))
    try:
        ergebnis = [r[0] for r in con.execute("PRAGMA integrity_check")]
    except sqlite3.DatabaseError as e:
        raise SicherungsFehler(f"{pfad.name} ist keine lesbare SQLite-Datenbank ({e})") from e
    finally:
        con.close()
    if ergebnis != ["ok"]:
        raise SicherungsFehler(f"Integritätsprüfung von {pfad.name} fehlgeschlagen: {'; '.join(ergebnis[:5])}")


def _kopiere_db(quelle: Path, ziel: Path):
    """Backup-API: konsistente Kopie, Verbindungen werden in jedem Fall geschlossen (Windows-Dateisperren)."""
    src = sqlite3.connect(str(quelle), timeout=30)
    try:
        dst = sqlite3.connect(str(ziel))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


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
            behalten: int = STANDARD_BEHALTEN, zusatz: str = "") -> Path:
    """Legt ``<db>-sicherung-<Zeit>[-zusatz].sqlite`` (+ ``.fotos.zip``) im Zielordner an und gibt den DB-Pfad zurück.

    Wirft ``SicherungsFehler``, wenn die Kopie die Integritätsprüfung nicht besteht (Kopie wird dann verworfen).
    Danach bleiben nur die letzten ``behalten`` Sicherungen dieser Datenbank erhalten.
    """
    db_pfad, ziel_ordner = Path(db_pfad), Path(ziel_ordner)
    if behalten < 1:
        raise ValueError("behalten muss mindestens 1 sein")
    if not db_pfad.is_file():
        raise SicherungsFehler(f"Datenbank {db_pfad} nicht gefunden")
    ziel_ordner.mkdir(parents=True, exist_ok=True)
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
        _integritaet(teil_db)
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
    _raeume_auf(ziel_ordner, db_pfad.stem, behalten)
    return ziel


def _raeume_auf(ordner: Path, stem: str, behalten: int):
    """Löscht ausschließlich eigene, überzählige Sicherungen (Namensmuster) samt zugehörigem Foto-ZIP."""
    eigene = _reihenfolge(_muster(stem), ordner)
    for alt in eigene[:-behalten]:
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
                     behalten: int = STANDARD_BEHALTEN) -> Wiederherstellung:
    """Spielt eine Sicherung zurück. Nur mit ``bestaetigt=True`` (App und Suchlauf müssen beendet sein).

    Reihenfolge: Quelle prüfen -> Stand vor der Wiederherstellung sichern -> Kopie neben der Datenbank erzeugen und
    prüfen -> atomar austauschen. Bei jedem Fehler davor bleibt die bestehende Datenbank unverändert.
    """
    sicherung, db_pfad = Path(sicherung), Path(db_pfad)
    if not bestaetigt:
        raise SicherungsFehler("Wiederherstellung abgebrochen: App und Suchlauf beenden, dann mit --bestaetigt wiederholen. "
                               "Es wurde nichts verändert.")
    if not sicherung.is_file():
        raise SicherungsFehler(f"Sicherung {sicherung} nicht gefunden")
    ziel_ordner = Path(ziel_ordner) if ziel_ordner else sicherung.parent
    _integritaet(sicherung)

    vorher = None
    if db_pfad.is_file():
        try:
            vorher = sichere(db_pfad, ziel_ordner, foto_ordner, behalten, zusatz="vor-wiederherstellung")
        except (SicherungsFehler, sqlite3.Error):
            # Defekte Datenbank: Rohkopie behalten (außerhalb der Aufbewahrungsregel), damit nichts verloren geht
            vorher = ziel_ordner / f"{db_pfad.stem}-defekt-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite.defekt"
            ziel_ordner.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_pfad, vorher)

    db_pfad.parent.mkdir(parents=True, exist_ok=True)
    teil = db_pfad.with_name(f".{db_pfad.name}.wiederherstellung.teil")
    try:
        _kopiere_db(sicherung, teil)
        _integritaet(teil)
        for endung in ("-wal", "-shm", "-journal"):         # Reste der alten Datenbank dürfen nicht zur neuen passen
            _entferne_still(db_pfad.with_name(db_pfad.name + endung))
        try:
            os.replace(teil, db_pfad)
        except PermissionError as e:
            raise SicherungsFehler(f"Datenbank ist noch in Benutzung ({e}). App, Suchlauf und geplante Aufgaben beenden "
                                   "und erneut versuchen.") from e
    except BaseException:
        _entferne_still(teil)
        raise

    foto_zip = sicherung.with_name(sicherung.name[: -len(".sqlite")] + ".fotos.zip")
    fotos, alt = False, None
    if foto_ordner and foto_zip.is_file():
        foto_ordner = Path(foto_ordner)
        neu = foto_ordner.with_name(f".{foto_ordner.name}.wiederherstellung.teil")
        shutil.rmtree(neu, ignore_errors=True)
        neu.mkdir(parents=True)
        try:
            _entpacke_sicher(foto_zip, neu)
            if foto_ordner.exists():
                alt = foto_ordner.with_name(f"{foto_ordner.name}.alt-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
                foto_ordner.rename(alt)
            neu.rename(foto_ordner)
            fotos = True
        except BaseException:
            shutil.rmtree(neu, ignore_errors=True)
            raise
    return Wiederherstellung(vorher, fotos, alt)
