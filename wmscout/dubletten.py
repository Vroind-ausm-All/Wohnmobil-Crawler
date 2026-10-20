"""Dublettenvorschläge aus der Datenbank (P3-02a): nur lesen, nichts Offenes wird gespeichert.

Die Vorschläge entstehen bei jedem Aufruf aus den Zeilen von ``anzeigen`` (wie ``finde_duplikate``) und der reinen Funktion
``normalisierung.identitaet.vergleiche``. Zuordnung zu ``inserate`` nur über (Plattform, Anzeigen-ID). Nicht vorgeschlagen werden Paare, die
schon dasselbe Fahrzeug haben oder zu denen eine geltende Entscheidung („gleich“ oder „verschieden“) vorliegt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .normalisierung.fahrzeug import ergaenze_fahrzeug
from .normalisierung.identitaet import REGEL_VERSION, kandidatenpaare, vergleiche

if TYPE_CHECKING:
    from .datenbank import Datenbank

STUFEN = {"hoch": 0, "mittel": 1}
STANDARD_LIMIT, MAX_LIMIT = 200, 1000
HINWEIS_GEKUERZT = "Gruppe zu groß – nicht vollständig geprüft"


@dataclass
class Ergebnis:
    vorschlaege: list[dict]
    gekuerzt: list[str] = field(default_factory=list)       # Blöcke („Marke EZ“), die wegen ihrer Größe nicht vollständig geprüft wurden

    @property
    def hinweis(self) -> str | None:
        return f"{HINWEIS_GEKUERZT}: {', '.join(sorted(set(self.gekuerzt)))}" if self.gekuerzt else None
ANZEIGE_FELDER = ("titel", "preis", "km", "ez_jahr", "ort", "url", "marke", "modell")


def _seite(z: dict, inserat: dict) -> dict:
    return {"inserat_id": inserat["id"], "anzeigen_id": z["id"], "plattform": inserat["plattform"], "fahrzeug_id": inserat["fahrzeug_id"],
            **{k: z.get(k) for k in ANZEIGE_FELDER}}


def dubletten_vorschlaege(db: Datenbank, zeilen: list[dict] | None = None) -> list[dict]:
    """Offene Vorschläge, beste zuerst (ohne Hinweis auf gekürzte Blöcke – dafür ``pruefe_dubletten``)."""
    return pruefe_dubletten(db, zeilen).vorschlaege


def pruefe_dubletten(db: Datenbank, zeilen: list[dict] | None = None) -> Ergebnis:
    """Offene Vorschläge, beste zuerst, und die Blöcke, die zu groß waren (``Ergebnis.hinweis``).
    ``zeilen``: bereits mit ``ergaenze_fahrzeug`` ergänzte Zeilen (sonst aus der Datenbank)."""
    from .datenbank import STANDARD_PLATTFORM
    if zeilen is None:
        zeilen = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    inserate = {(r["plattform"], r["anzeigen_id"]): {"id": r["id"], "plattform": r["plattform"], "fahrzeug_id": r["fahrzeug_id"]}
                for r in db.con.execute("SELECT id, plattform, anzeigen_id, fahrzeug_id FROM inserate")}
    entschieden = {(r[0], r[1]) for r in db.con.execute("SELECT inserat_a, inserat_b FROM dubletten_entscheidungen WHERE status = 'gilt'")}
    zu_inserat = {z["id"]: inserate.get((z.get("quelle") or STANDARD_PLATTFORM, z["id"])) for z in zeilen}
    vorschlaege, gekuerzt = [], []
    for a, b in kandidatenpaare([z for z in zeilen if zu_inserat[z["id"]]], gekuerzt=gekuerzt):
        ia, ib = zu_inserat[a["id"]], zu_inserat[b["id"]]
        if ia["fahrzeug_id"] is not None and ia["fahrzeug_id"] == ib["fahrzeug_id"]:
            continue
        if ia["id"] > ib["id"]:
            a, b, ia, ib = b, a, ib, ia
        if (ia["id"], ib["id"]) in entschieden:
            continue
        v = vergleiche(a, b)
        if v.konfidenz:
            vorschlaege.append({"stufe": v.konfidenz, "gruende": v.gruende, "regel_version": REGEL_VERSION,
                                "inserat_a": ia["id"], "inserat_b": ib["id"], "anzeigen_a": a["id"], "anzeigen_b": b["id"],
                                "plattform_a": ia["plattform"], "plattform_b": ib["plattform"],
                                "a": _seite(a, ia), "b": _seite(b, ib)})
    vorschlaege.sort(key=lambda p: (STUFEN[p["stufe"]], p["inserat_a"], p["inserat_b"]))
    return Ergebnis(vorschlaege, gekuerzt)
