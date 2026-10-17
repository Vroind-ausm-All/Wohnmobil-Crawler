"""Schalter für Eingänge und Pull-Quellen (P2-04, ADR-036) – ohne Netz- und Oberflächenbezug.

* **Eingänge** (`seiten`, `text`, `email`): `config.yaml → eingaenge → <name> → aktiv`. Fehlt der Abschnitt, gelten die Standardwerte
  (`STANDARD_EINGAENGE`); ungültige Werte werden beim Start gemeldet (`pruefe_eingaenge`).
* **Pull-Quellen** (Suchlauf): Freigabe steht im Code (`Quelle.freigegeben`, Nutzungsrechte, Regel 12), die Aktivierung durch den
  Betreiber in der Tabelle `quellen` (`aktiv`). Eine Quelle läuft nur, wenn beides stimmt. Nicht Freigegebenes oder Abgeschaltetes wird
  übersprungen und gemeldet – das ist kein Fehler.

Zeile in `quellen` (Schema v4, unverändert): Die Migration legt für Kleinanzeigen eine Zeile mit freigegeben=0, aktiv=0 an. Diese
Seed-Zeile und eine fehlende Zeile bedeuten „nicht entschieden“ – es gilt der Code: Eine Quelle läuft, sobald sie im Code freigegeben
ist (bewusste Code-Änderung nach geklärten Nutzungsrechten, Regel 12, per Pull Request geprüft) und in `suchen` eingetragen ist;
abgeschaltet wird sie mit `quellen aus`. Erst `quellen an/aus` schreibt eine ausdrückliche Entscheidung: `freigegeben` spiegelt
dann die Code-Freigabe (1), `aktiv` den Wunsch des Betreibers. `aus` ist nur für im Code freigegebene Quellen möglich: Bei einer
gesperrten Quelle wäre die Zeile nicht von „nicht entschieden“ zu unterscheiden und eine spätere Freigabe liefe ohne Zustimmung.
Eine Zeile ohne Spiegel (freigegeben=0, aktiv=1) schaltet nie etwas frei.
"""
from __future__ import annotations

from collections.abc import Mapping

STANDARD_EINGAENGE = {"seiten": True, "text": True, "email": False}
EINGANG_NAMEN = {"seiten": "Gespeicherte Seiten (Import-Ordner)", "text": "URL + eingefügter Text",
                 "email": "E-Mail-Suchagenten (folgt mit P2-06)"}

GRUND_NICHT_FREIGEGEBEN = "nicht freigegeben"
GRUND_DEAKTIVIERT = "deaktiviert"


class EingangDeaktiviert(Exception):
    """Ein Eingang ist in config.yaml abgeschaltet; es wurde nichts gelesen."""


class QuelleNichtSchaltbar(ValueError):
    """Eine Quelle ohne Code-Freigabe lässt sich weder aktivieren (Regel 12: Nutzungsrechte) noch sinnvoll abschalten."""


# ---------- Eingänge (config.yaml) ----------
def eingaenge(cfg: dict) -> dict[str, bool]:
    """Status aller Eingänge laut config.yaml (+ Standardwerte). ValueError bei ungültiger Konfiguration."""
    abschnitt = cfg.get("eingaenge")
    if abschnitt is None:
        abschnitt = {}
    if not isinstance(abschnitt, Mapping):
        raise ValueError("eingaenge: erwartet werden die Einträge seiten, text, email (je mit „aktiv: true|false“)")
    unbekannt = sorted(str(k) for k in abschnitt if k not in STANDARD_EINGAENGE)
    if unbekannt:
        raise ValueError(f"eingaenge: unbekannter Eingang {', '.join(unbekannt)} (erlaubt: {', '.join(STANDARD_EINGAENGE)})")
    erg = dict(STANDARD_EINGAENGE)
    for name, eintrag in abschnitt.items():
        if eintrag is None:
            continue
        if not isinstance(eintrag, Mapping) or set(eintrag) - {"aktiv"}:
            raise ValueError(f"eingaenge → {name}: erwartet wird „aktiv: true|false“")
        if "aktiv" in eintrag:
            if not isinstance(eintrag["aktiv"], bool):
                raise ValueError(f"eingaenge → {name} → aktiv: true oder false erwartet, nicht {eintrag['aktiv']!r}")
            erg[name] = eintrag["aktiv"]
    return erg


def pruefe_eingaenge(cfg: dict) -> dict[str, bool]:
    """Beim Start aufrufen (wie ``datenrechte.frist_aus``): meldet eine ungültige Konfiguration sofort."""
    return eingaenge(cfg)


def eingang_aktiv(cfg: dict, kennung: str) -> bool:
    if kennung not in STANDARD_EINGAENGE:
        raise ValueError(f"Unbekannter Eingang {kennung!r} (erlaubt: {', '.join(STANDARD_EINGAENGE)})")
    return eingaenge(cfg)[kennung]


def eingang_pruefen(cfg: dict, kennung: str):
    """Wirft ``EingangDeaktiviert`` mit verständlichem Text, wenn der Eingang abgeschaltet ist."""
    if not eingang_aktiv(cfg, kennung):
        raise EingangDeaktiviert(f"Eingang „{kennung}“ ({EINGANG_NAMEN[kennung]}) ist abgeschaltet – es wurde nichts gelesen. "
                                 f"Einschalten: config.yaml bzw. config.local.yaml → eingaenge → {kennung} → aktiv: true")


# ---------- Pull-Quellen (Code-Freigabe + Tabelle quellen) ----------
def quelle_zeile(db, kennung: str):
    return db.con.execute("SELECT kennung, zugriffsart, freigegeben, aktiv FROM quellen WHERE kennung=?", (kennung,)).fetchone()


def bewerte_quelle(code_freigegeben: bool, zeile: Mapping | None) -> tuple[bool, str | None]:
    """(läuft, Grund des Überspringens). Ohne Code-Freigabe läuft nichts, was auch in der Tabelle steht."""
    if not code_freigegeben:
        return False, GRUND_NICHT_FREIGEGEBEN
    if zeile is None or (not zeile["freigegeben"] and not zeile["aktiv"]):
        return True, None                                  # nicht entschieden: der Code gibt die Quelle frei
    return (True, None) if zeile["aktiv"] else (False, GRUND_DEAKTIVIERT)


def quelle_laeuft(db, klasse) -> tuple[bool, str | None]:
    return bewerte_quelle(bool(klasse.freigegeben), quelle_zeile(db, klasse.kennung))


def setze_quelle(db, klasse, aktiv: bool):
    """`quellen an|aus`: legt die Zeile an bzw. ändert sie in einer Transaktion. Nur für im Code freigegebene Quellen:
    „an“ wäre eine Umgehung der Freigabe, „aus“ würde als 0/0 („nicht entschieden“) gespeichert und nichts bewirken."""
    if not klasse.freigegeben:
        if aktiv:
            raise QuelleNichtSchaltbar(
                f"Quelle {klasse.name} ({klasse.kennung}) ist im Code nicht freigegeben ({klasse.zugriffsart}) und lässt sich nicht "
                f"aktivieren. {klasse.hinweis} Freigabe nur nach geklärten Nutzungsrechten (docs/SOURCES.md).".strip())
        raise QuelleNichtSchaltbar(
            f"Quelle {klasse.name} ({klasse.kennung}) läuft ohnehin nicht (nicht freigegeben) – nichts gespeichert; "
            "nach einer Freigabe im Code mit `quellen aus` abschalten.")
    with db.transaktion():
        db.con.execute("INSERT OR IGNORE INTO quellen (kennung, zugriffsart, freigegeben, aktiv) VALUES (?, ?, 0, 0)",
                       (klasse.kennung, klasse.zugriffsart))
        db.con.execute("UPDATE quellen SET zugriffsart=?, freigegeben=1, aktiv=? WHERE kennung=?",
                       (klasse.zugriffsart, int(bool(aktiv)), klasse.kennung))
