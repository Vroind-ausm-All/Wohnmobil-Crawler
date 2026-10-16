"""Mandanten (G2, ADR-033): mehrere Firmen auf einem Server – jede mit eigener Datenbank, eigenen Fotos, Sicherungen und Zugängen.

Trennung physisch statt per Spalte: Jeder Mandant hat einen eigenen Ordner ``mandanten/<kennung>/`` mit ``mandant.yaml``
(nur Abweichungen von ``config.yaml``: Name, Adresse, Anschreiben, Suchen …) und darunter ``daten/`` und ``ausgabe/``. Die Pfade
legt das Programm fest – ein Mandant kann sie nicht auf die Daten eines anderen zeigen lassen. Der Server wählt den Mandanten
allein nach dem Hostnamen der Anfrage; jeder Hostname gehört zu genau einem Mandanten. Ohne Ordner ``mandanten/`` bleibt alles
wie bisher (ein Betrieb, ``config.yaml``).
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

ORDNER = "mandanten"
KENNUNG = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")
# Diese Abschnitte bestimmt das Programm je Mandant – in mandant.yaml verboten
GESPERRT = ("ausgabe", "sicherung", "import", "mandant", "mandanten")
# Nie von config.yaml erben: Adresse/Hostnamen und Versandwege (sonst sendete ein Mandant über das Konto der Hauptfirma)
NICHT_ERBEN_APP = ("oeffentliche_url", "erlaubte_hosts")
AUS_OHNE_EIGENE_ANGABE = ("whatsapp", "email")


class MandantenFehler(ValueError):
    """Verständliche Meldung für den Betreiber; nichts wurde gestartet oder verändert."""


def _mischen(basis: dict, zusatz: dict) -> dict:
    for k, v in zusatz.items():
        if isinstance(v, dict) and isinstance(basis.get(k), dict):
            _mischen(basis[k], v)
        else:
            basis[k] = copy.deepcopy(v)
    return basis


def _wurzel_text(grund_cfg: dict) -> str:
    """config.yaml → mandanten → ordner (Standard ``mandanten``, relativ zum Projektordner oder vollständiger Pfad)."""
    return str((grund_cfg.get("mandanten") or {}).get("ordner") or ORDNER)


def ordner(grund_cfg: dict, basis: Path, kennung: str) -> Path:
    if not KENNUNG.fullmatch(kennung or ""):
        raise MandantenFehler(f"Ungültige Mandanten-Kennung {kennung!r}: 2–31 Zeichen, nur a–z, 0–9 und Bindestrich")
    return basis / _wurzel_text(grund_cfg) / kennung


def mandant_cfg(grund_cfg: dict, basis: Path, kennung: str) -> dict:
    """``config.yaml`` + ``mandanten/<kennung>/mandant.yaml``; Datenpfade fest im Mandantenordner (relativ zu ``basis``)."""
    pfad = ordner(grund_cfg, basis, kennung) / "mandant.yaml"
    if not pfad.is_file():
        raise MandantenFehler(f"Mandant „{kennung}“ unbekannt ({pfad} fehlt) – anlegen mit: python scout.py mandant anlegen {kennung} …")
    with open(pfad, encoding="utf-8") as f:
        eigen = yaml.safe_load(f) or {}
    if not isinstance(eigen, dict):
        raise MandantenFehler(f"{pfad}: erwartet werden Abschnitte wie in config.yaml")
    verboten = [k for k in GESPERRT if k in eigen]
    if verboten:
        raise MandantenFehler(f"{pfad}: Abschnitt(e) {', '.join(verboten)} legt das Programm je Mandant fest – bitte entfernen")
    name = eigen.pop("name", None) or kennung
    grund = copy.deepcopy(grund_cfg)
    if not isinstance(grund.get("app"), dict):
        grund["app"] = {}
    for k in NICHT_ERBEN_APP:
        grund["app"].pop(k, None)
    for k in AUS_OHNE_EIGENE_ANGABE:
        if isinstance(grund.get(k), dict):
            grund[k]["aktiv"] = False
    cfg = _mischen(grund, eigen)
    rel = Path(_wurzel_text(grund_cfg)) / kennung
    cfg["ausgabe"] = {**(grund_cfg.get("ausgabe") or {}), "ordner": str(rel / "ausgabe"), "datenbank": str(rel / "daten" / "anzeigen.sqlite")}
    cfg["sicherung"] = {**(grund_cfg.get("sicherung") or {}), "ordner": str(rel / "daten" / "sicherungen")}
    cfg["import"] = {**(grund_cfg.get("import") or {}), "ordner": str(rel / "import")}
    cfg["mandant"] = {"kennung": kennung, "name": name}
    return cfg


def kennungen(grund_cfg: dict, basis: Path) -> list[str]:
    wurzel = basis / _wurzel_text(grund_cfg)
    if not wurzel.is_dir():
        return []
    return sorted(p.name for p in wurzel.iterdir() if p.is_dir() and (p / "mandant.yaml").is_file() and KENNUNG.fullmatch(p.name))


def hosts(cfg: dict) -> set[str]:
    """Öffentliche Hostnamen eines Mandanten (ohne 127.0.0.1/localhost – die gehören höchstens dem „lokalen“ Mandanten)."""
    a = cfg.get("app") or {}
    h = {urlparse(a["oeffentliche_url"]).netloc.lower()} if a.get("oeffentliche_url") else set()
    h.update(str(x).lower() for x in a.get("erlaubte_hosts") or [])
    return {x for x in h if x}


def alle(grund_cfg: dict, basis: Path) -> list[dict]:
    """Alle Mandanten geprüft: mindestens ein eigener Hostname, keiner doppelt."""
    liste = [mandant_cfg(grund_cfg, basis, k) for k in kennungen(grund_cfg, basis)]
    if not liste:
        raise MandantenFehler(f"Keine Mandanten in {basis / _wurzel_text(grund_cfg)}/ – anlegen mit: python scout.py mandant anlegen KENNUNG --host …")
    gesehen: dict[str, str] = {}
    for cfg in liste:
        k = cfg["mandant"]["kennung"]
        eigene = hosts(cfg)
        if not eigene:
            raise MandantenFehler(f"Mandant „{k}“ hat keine Adresse (mandant.yaml → app → oeffentliche_url)")
        for h in eigene:
            if h in gesehen:
                raise MandantenFehler(f"Hostname {h} gehört zu „{gesehen[h]}“ und „{k}“ – jeder Hostname nur einmal")
            gesehen[h] = k
    return liste


def anlegen(grund_cfg: dict, basis: Path, kennung: str, name: str, url: str) -> Path:
    """Neuer Mandantenordner mit minimaler ``mandant.yaml``; bestehende Mandanten werden nie überschrieben."""
    ziel = ordner(grund_cfg, basis, kennung)
    if (ziel / "mandant.yaml").exists():
        raise MandantenFehler(f"Mandant „{kennung}“ gibt es schon ({ziel})")
    teile = urlparse(url or "")
    if teile.scheme != "https" or not teile.netloc:
        raise MandantenFehler("Adresse als https://… angeben (ein eigener Hostname je Mandant)")
    (ziel / "daten").mkdir(parents=True, exist_ok=True)
    inhalt = {"name": name or kennung, "app": {"oeffentliche_url": f"https://{teile.netloc}"}, "anschreiben": {"firma": name or kennung}}
    kopf = (f"# Mandant „{name or kennung}“ (G2, docs/MANDANTEN.md). Nur Abweichungen von config.yaml eintragen – z. B. anschreiben,\n"
            "# suchen, whatsapp. Datenpfade (ausgabe, sicherung, import) legt das Programm fest. Keine Passwörter hier eintragen.\n")
    (ziel / "mandant.yaml").write_text(kopf + yaml.safe_dump(inhalt, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ziel
