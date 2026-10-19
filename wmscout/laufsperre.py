"""Laufsperre (P1-04): höchstens ein Suchlauf je Datenbank – App-Suche, Auto-Suche und „scout.py lauf“ (Aufgabenplanung).

Dateisperre des Betriebssystems auf ``<datenbank>.laufsperre``. Endet ein Prozess, auch durch Absturz, gibt das System
die Sperre frei: keine veralteten Sperren, keine Ablaufzeit, keine Schemaänderung. Die Datei selbst bleibt liegen
(Löschen wäre ein Wettlauf mit dem nächsten Lauf). Nicht wartend: wer die Sperre nicht bekommt, startet nicht.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt

    def _sperre(fd: int):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)        # 1 Byte ab Anfang; jenseits des Dateiendes erlaubt

    def _entsperre(fd: int):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _sperre(fd: int):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _entsperre(fd: int):
        fcntl.flock(fd, fcntl.LOCK_UN)


def sperrdatei(db_pfad: str | Path) -> Path:
    p = Path(db_pfad)
    return p.with_name(p.name + ".laufsperre")


class Laufsperre:
    def __init__(self, db_pfad: str | Path):
        self.pfad = sperrdatei(db_pfad)
        self._fd: int | None = None

    @property
    def gehalten(self) -> bool:
        return self._fd is not None

    def erwerben(self) -> bool:
        """True: Sperre gehört jetzt diesem Objekt. False: ein anderer Lauf (oder eine Wiederherstellung) hält sie."""
        if self._fd is not None:
            raise RuntimeError("Laufsperre wird bereits gehalten")
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.pfad, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _sperre(fd)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def freigeben(self):
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _entsperre(fd)
        except OSError:
            pass                    # schließen gibt die Sperre ohnehin frei
        finally:
            os.close(fd)
