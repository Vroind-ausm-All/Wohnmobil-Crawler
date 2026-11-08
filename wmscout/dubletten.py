"""Dublettenvorschläge aus der Datenbank (P3-02a): nur lesen, nichts Offenes wird gespeichert.

Die Vorschläge entstehen bei jedem Aufruf aus den Zeilen von ``anzeigen`` (wie ``finde_duplikate``) und der reinen Funktion
``normalisierung.identitaet.vergleiche``. Zuordnung zu ``inserate`` nur über (Plattform, Anzeigen-ID). Nicht vorgeschlagen werden Paare, die
schon dasselbe Fahrzeug haben oder zu denen eine geltende Entscheidung („gleich“ oder „verschieden“) vorliegt.

P3-02b: Menschliche Entscheidungen (``bestaetige``, ``lehne_ab``, ``hebe_auf``), jede in EINER Transaktion mit Prüfung der Datensätze im
Code (``PRAGMA foreign_keys`` ist nicht aktiv). „gleich“ hängt die Inserate des Fahrzeugs mit der größeren ID auf das mit der kleineren um
(Protokoll in ``fahrzeug_zuordnungen``); Aufheben nur in umgekehrter Reihenfolge (LIFO). Die Wirkung auf Bewertung und Team-Sperre kommt
über ``Wirkung`` (rein) und ``lade_wirkung`` (Datenbank). Der Ankaufsstatus bleibt am Inserat (``bearbeitung`` wird nicht umgeschlüsselt).
"""
from __future__ import annotations

import json
from collections.abc import Callable
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


# ---------------------------------------------------------------- Wirkung auf Bewertung und Team-Sperre (rein / lesend)
@dataclass(frozen=True)
class Wirkung:
    """Geltende Entscheidungen als Anzeigen-IDs: ``gruppen`` = Inserate desselben Fahrzeugs (je Gruppe mindestens zwei),
    ``getrennt`` = Paare mit geltender Entscheidung „verschieden“."""
    gruppen: tuple[frozenset[str], ...] = ()
    getrennt: frozenset[frozenset[str]] = frozenset()

    @property
    def leer(self) -> bool:
        return not self.gruppen and not self.getrennt

    def karte(self) -> dict[str, frozenset[str]]:
        """id → die anderen Mitglieder seiner Fahrzeuggruppe."""
        return {i: g - {i} for g in self.gruppen for i in g}


def wende_an(duplikate: dict, wirkung: Wirkung | None, holen: Callable[[str], object | None], kennung: Callable[[object], str]) -> dict:
    """Nachbarn eines Inserats i = sein Fahrzeug (bestätigte Gruppe G) ∪ heuristische Nachbarn ALLER Mitglieder von G ∪ deren bestätigte
    Gruppen (eine Stufe, keine Hülle über Heuristik-Ketten), ohne Inserate, deren Fahrzeug zu einem
    Mitglied von G als „verschieden“ entschieden ist (symmetrisch).
    Ohne Entscheidungen kommt ``duplikate`` unverändert zurück (dasselbe Objekt). ``holen(id)`` liefert das Element für eine ID (``None`` =
    unbekannt, wird übergangen), ``kennung(element)`` dessen ID – so gilt dieselbe Regel für Zeilen und für reine IDs."""
    if wirkung is None or wirkung.leer:
        return duplikate
    gruppe_von = {i: g for g in wirkung.gruppen for i in g}
    getrennt = wirkung.getrennt
    heuristisch = {i: {kennung(e) for e in v} for i, v in duplikate.items()}
    umfeld_von: dict[frozenset, set[str]] = {}

    def umfeld(g: frozenset[str]) -> set[str]:
        if g not in umfeld_von:
            kandidaten: set[str] = set()
            for m in g:
                for h in heuristisch.get(m, ()):
                    if frozenset((m, h)) not in getrennt:
                        kandidaten.add(h)
                        kandidaten |= gruppe_von.get(h, {h})
            kandidaten -= g
            umfeld_von[g] = {x for x in kandidaten if not any(frozenset((y, m)) in getrennt for y in gruppe_von.get(x, {x}) for m in g)}
        return umfeld_von[g]

    ergebnis = {}
    for i in [*duplikate, *sorted(k for k in gruppe_von if k not in duplikate)]:
        g = gruppe_von.get(i, frozenset((i,)))
        ziel = (g - {i}) | umfeld(g)
        bekannt = {kennung(e): e for e in duplikate.get(i, [])}
        elemente = [e for k, e in bekannt.items() if k in ziel]
        for j in sorted(ziel - bekannt.keys()):
            if (e := holen(j)) is not None:
                elemente.append(e)
        if elemente:
            ergebnis[i] = elemente
    return ergebnis


def lade_wirkung(db: Datenbank) -> Wirkung:
    """Geltende Entscheidungen aus der Datenbank (zwei SELECTs, Index ``idx_inserate_fahrzeug`` / ``idx_dubletten_gilt``)."""
    je_fahrzeug: dict[int, set[str]] = {}
    for fid, aid in db.con.execute("SELECT fahrzeug_id, anzeigen_id FROM inserate WHERE fahrzeug_id IN "
                                   "(SELECT fahrzeug_id FROM inserate GROUP BY fahrzeug_id HAVING COUNT(*) > 1)"):
        je_fahrzeug.setdefault(fid, set()).add(aid)
    getrennt = frozenset(frozenset((a, b)) for a, b in db.con.execute(
        "SELECT ia.anzeigen_id, ib.anzeigen_id FROM dubletten_entscheidungen d JOIN inserate ia ON ia.id = d.inserat_a "
        "JOIN inserate ib ON ib.id = d.inserat_b WHERE d.status = 'gilt' AND d.entscheidung = 'verschieden'"))
    return Wirkung(tuple(frozenset(g) for _, g in sorted(je_fahrzeug.items())), getrennt)


# ---------------------------------------------------------------- Rechte (ADR-040 Nr. 4; Einzelplatz = Rolle „inhaber“ ohne Nutzer-ID)
def darf_bestaetigen(rolle: str | None) -> bool:
    return rolle in ("inhaber", "mitarbeiter")


def darf_ablehnen(rolle: str | None) -> bool:
    return rolle == "inhaber"


darf_aufheben = darf_ablehnen


# ---------------------------------------------------------------- Entscheidungen
class DublettenFehler(ValueError):
    """Unbekanntes Inserat oder unsinnige Eingabe (API: 400)."""


class DublettenKonflikt(Exception):
    """Widerspricht dem gespeicherten Stand (API: 409)."""


def _jetzt() -> str:
    from .datenbank import jetzt_utc
    return jetzt_utc()


def _paar(a, b) -> tuple[int, int]:
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (a, b)):
        raise DublettenFehler("Inserat-IDs müssen ganze Zahlen sein")
    if a == b:
        raise DublettenFehler("Ein Inserat lässt sich nicht mit sich selbst vergleichen")
    return (a, b) if a < b else (b, a)


def _inserat(db: Datenbank, inserat_id: int) -> dict:
    r = db.con.execute("SELECT id, plattform, anzeigen_id, fahrzeug_id FROM inserate WHERE id = ?", (inserat_id,)).fetchone()
    if r is None:
        raise DublettenFehler(f"Inserat {inserat_id} gibt es nicht")
    if r["fahrzeug_id"] is None or not db.con.execute("SELECT 1 FROM fahrzeuge WHERE id = ?", (r["fahrzeug_id"],)).fetchone():
        raise DublettenFehler(f"Inserat {inserat_id} hat kein gültiges Fahrzeug")
    return dict(r)


def _vergleich(db: Datenbank, ia: dict, ib: dict) -> tuple[str | None, list[str]]:
    """Stufe und Gründe (samt Widersprüchen) zum Einfrieren in der Entscheidung; ohne ``anzeigen``-Zeile leer."""
    from .datenbank import STANDARD_PLATTFORM
    zeilen = []
    for i in (ia, ib):
        r = db.con.execute("SELECT * FROM anzeigen WHERE id = ? AND COALESCE(NULLIF(quelle, ''), ?) = ?",
                           (i["anzeigen_id"], STANDARD_PLATTFORM, i["plattform"])).fetchone()
        if r is None:
            return None, []
        zeilen.append(ergaenze_fahrzeug(dict(r)))
    v = vergleiche(*zeilen)
    return v.konfidenz, [*v.gruende, *(f"Widerspruch: {w}" for w in v.widersprueche)]


def _geltende(db: Datenbank, a: int, b: int):
    return db.con.execute("SELECT * FROM dubletten_entscheidungen WHERE inserat_a = ? AND inserat_b = ? AND status = 'gilt'", (a, b)).fetchone()


def _fahrzeug_inserate(db: Datenbank, *fahrzeuge: int) -> list[int]:
    return [r[0] for r in db.con.execute(f"SELECT id FROM inserate WHERE fahrzeug_id IN ({','.join('?' * len(fahrzeuge))}) ORDER BY id", fahrzeuge)]


def _lege_an(db: Datenbank, a: int, b: int, art: str, ia: dict, ib: dict, nutzer_id: int | None) -> int:
    konfidenz, gruende = _vergleich(db, ia, ib)
    return db.con.execute(
        "INSERT INTO dubletten_entscheidungen (inserat_a, inserat_b, entscheidung, status, konfidenz, gruende_json, regel_version, nutzer_id, zeitpunkt) "
        "VALUES (?, ?, ?, 'gilt', ?, ?, ?, ?, ?)",
        (a, b, art, konfidenz, json.dumps(gruende, ensure_ascii=False), REGEL_VERSION, nutzer_id, _jetzt())).lastrowid


def bestaetige(db: Datenbank, inserat_a: int, inserat_b: int, nutzer_id: int | None = None) -> dict:
    """Entscheidung „gleiches Fahrzeug“. Die Inserate des Fahrzeugs mit der größeren ID wechseln zum Fahrzeug mit der kleineren ID
    (jede Bewegung als Zeile ``zusammen`` im Protokoll). Gründe, Stufe und Regelversion werden eingefroren – auch ohne aktuellen
    Vorschlag, der Mensch entscheidet. Schon dasselbe Fahrzeug: nichts zu tun. ``DublettenKonflikt``, wenn die entstehende Gruppe ein Paar
    mit geltender Entscheidung „verschieden“ enthält. Rückgabe: ``entscheidung_id`` (None bei schon gleichem Fahrzeug ohne eigene
    Entscheidung), ``neu``, ``bewegt`` (Inserat-IDs)."""
    a, b = _paar(inserat_a, inserat_b)
    with db.transaktion():
        ia, ib = _inserat(db, a), _inserat(db, b)
        gilt = _geltende(db, a, b)
        if ia["fahrzeug_id"] == ib["fahrzeug_id"]:
            return {"entscheidung_id": gilt["id"] if gilt else None, "neu": False, "bewegt": []}
        gruppe = _fahrzeug_inserate(db, ia["fahrzeug_id"], ib["fahrzeug_id"])
        q = ",".join("?" * len(gruppe))
        verboten = db.con.execute(f"SELECT inserat_a, inserat_b FROM dubletten_entscheidungen WHERE status = 'gilt' AND entscheidung = 'verschieden' "
                                  f"AND inserat_a IN ({q}) AND inserat_b IN ({q}) ORDER BY id LIMIT 1", (*gruppe, *gruppe)).fetchone()
        if verboten:
            raise DublettenKonflikt(f"Die Inserate {verboten[0]} und {verboten[1]} sind als „verschieden“ entschieden – erst diese Entscheidung aufheben")
        if gilt and gilt["entscheidung"] == "verschieden":
            raise DublettenKonflikt("Dieses Paar ist als „verschieden“ entschieden – erst diese Entscheidung aufheben")
        eid = gilt["id"] if gilt else _lege_an(db, a, b, "gleich", ia, ib, nutzer_id)
        ziel, von = sorted((ia["fahrzeug_id"], ib["fahrzeug_id"]))
        bewegt = _fahrzeug_inserate(db, von)
        jetzt = _jetzt()
        for iid in bewegt:
            db.con.execute("UPDATE inserate SET fahrzeug_id = ? WHERE id = ?", (ziel, iid))
            db.con.execute("INSERT INTO fahrzeug_zuordnungen (entscheidung_id, inserat_id, von_fahrzeug, nach_fahrzeug, art, nutzer_id, zeitpunkt) "
                           "VALUES (?, ?, ?, ?, 'zusammen', ?, ?)", (eid, iid, von, ziel, nutzer_id, jetzt))
    return {"entscheidung_id": eid, "neu": True, "bewegt": bewegt}


def lehne_ab(db: Datenbank, inserat_a: int, inserat_b: int, nutzer_id: int | None = None) -> dict:
    """Entscheidung „verschiedene Fahrzeuge“: hebt die heuristische Sperre für dieses Paar auf. ``DublettenKonflikt``, wenn beide schon
    dasselbe Fahrzeug haben (erst die Zusammenführung aufheben). Schon geltend: nichts zu tun."""
    a, b = _paar(inserat_a, inserat_b)
    with db.transaktion():
        ia, ib = _inserat(db, a), _inserat(db, b)
        gilt = _geltende(db, a, b)
        if gilt and gilt["entscheidung"] == "verschieden":
            return {"entscheidung_id": gilt["id"], "neu": False}
        if gilt or ia["fahrzeug_id"] == ib["fahrzeug_id"]:
            raise DublettenKonflikt("Beide Inserate gehören bereits zum selben Fahrzeug – erst die Zusammenführung aufheben")
        return {"entscheidung_id": _lege_an(db, a, b, "verschieden", ia, ib, nutzer_id), "neu": True}


def aufheben_blockiert_durch(db: Datenbank, entscheidung_id: int) -> int | None:
    """ID der späteren geltenden „gleich“-Entscheidung, die dieselben Inserate oder Fahrzeuge bewegt hat (dann nur LIFO), sonst ``None``."""
    zeilen = db.con.execute("SELECT inserat_id, von_fahrzeug, nach_fahrzeug FROM fahrzeug_zuordnungen WHERE entscheidung_id = ? AND art = 'zusammen'",
                            (entscheidung_id,)).fetchall()
    if not zeilen:
        return None
    inserate = {z[0] for z in zeilen}
    fahrzeuge = {f for z in zeilen for f in (z[1], z[2])}
    qi, qf = ",".join("?" * len(inserate)), ",".join("?" * len(fahrzeuge))
    r = db.con.execute(
        "SELECT MIN(d.id) FROM dubletten_entscheidungen d JOIN fahrzeug_zuordnungen z ON z.entscheidung_id = d.id AND z.art = 'zusammen' "
        "WHERE d.id > ? AND d.status = 'gilt' AND d.entscheidung = 'gleich' "
        f"AND (z.inserat_id IN ({qi}) OR z.von_fahrzeug IN ({qf}) OR z.nach_fahrzeug IN ({qf}))",
        (entscheidung_id, *inserate, *fahrzeuge, *fahrzeuge)).fetchone()
    return r[0]


def hebe_auf(db: Datenbank, entscheidung_id: int, nutzer_id: int | None = None) -> dict:
    """Entscheidung aufheben (Verlauf bleibt). Bei „gleich“ nur in umgekehrter Reihenfolge (``DublettenKonflikt`` mit der ID der späteren
    Entscheidung); die Inserate gehen exakt an ihr früheres Fahrzeug zurück (Zeilen ``zurueck``). Schon aufgehoben: nichts zu tun."""
    if isinstance(entscheidung_id, bool) or not isinstance(entscheidung_id, int):
        raise DublettenFehler("entscheidung_id muss eine ganze Zahl sein")
    with db.transaktion():
        e = db.con.execute("SELECT * FROM dubletten_entscheidungen WHERE id = ?", (entscheidung_id,)).fetchone()
        if e is None:
            raise DublettenFehler(f"Entscheidung {entscheidung_id} gibt es nicht")
        if e["status"] != "gilt":
            return {"entscheidung_id": entscheidung_id, "neu": False, "zurueck": []}
        zurueck = []
        if e["entscheidung"] == "gleich":
            spaeter = aufheben_blockiert_durch(db, entscheidung_id)
            if spaeter is not None:
                raise DublettenKonflikt(f"Zuerst die spätere Entscheidung {spaeter} aufheben (nur in umgekehrter Reihenfolge)")
            jetzt = _jetzt()
            zeilen = db.con.execute("SELECT inserat_id, von_fahrzeug, nach_fahrzeug FROM fahrzeug_zuordnungen "
                                    "WHERE entscheidung_id = ? AND art = 'zusammen' ORDER BY id DESC", (entscheidung_id,)).fetchall()
            for iid, _von, nach in zeilen:
                aktuell = db.con.execute("SELECT fahrzeug_id FROM inserate WHERE id = ?", (iid,)).fetchone()
                if aktuell is None or aktuell[0] != nach:
                    raise DublettenKonflikt(f"Inserat {iid} gehört inzwischen zu einem anderen Fahrzeug – nichts geändert")
            for iid, von, nach in zeilen:
                db.con.execute("UPDATE inserate SET fahrzeug_id = ? WHERE id = ?", (von, iid))
                db.con.execute("INSERT INTO fahrzeug_zuordnungen (entscheidung_id, inserat_id, von_fahrzeug, nach_fahrzeug, art, nutzer_id, zeitpunkt) "
                               "VALUES (?, ?, ?, ?, 'zurueck', ?, ?)", (entscheidung_id, iid, nach, von, nutzer_id, jetzt))
                zurueck.append(iid)
        db.con.execute("UPDATE dubletten_entscheidungen SET status = 'aufgehoben', aufgehoben_am = ?, aufgehoben_von = ? WHERE id = ?",
                       (_jetzt(), nutzer_id, entscheidung_id))
    return {"entscheidung_id": entscheidung_id, "neu": True, "zurueck": zurueck}


# ---------------------------------------------------------------- Lesen
def inserat_zu_anzeige(db: Datenbank, anzeigen_id: str) -> int | None:
    from .datenbank import STANDARD_PLATTFORM
    r = db.con.execute("SELECT i.id FROM anzeigen a JOIN inserate i ON i.plattform = COALESCE(NULLIF(a.quelle, ''), ?) AND i.anzeigen_id = a.id "
                       "WHERE a.id = ?", (STANDARD_PLATTFORM, anzeigen_id)).fetchone()
    return r[0] if r else None


def gruppe(db: Datenbank, inserat_id: int) -> list[dict]:
    """Alle Inserate mit demselben Fahrzeug (auch das angefragte), älteste ID zuerst, mit Anzeigedaten und Ankaufsstatus."""
    from .datenbank import STANDARD_PLATTFORM
    return [dict(r) for r in db.con.execute(
        "SELECT i.id AS inserat_id, i.anzeigen_id, i.plattform, i.fahrzeug_id, a.titel, a.preis, a.url, COALESCE(a.status, 'neu') AS status "
        "FROM inserate i LEFT JOIN anzeigen a ON a.id = i.anzeigen_id AND COALESCE(NULLIF(a.quelle, ''), ?) = i.plattform "
        "WHERE i.fahrzeug_id = (SELECT fahrzeug_id FROM inserate WHERE id = ?) ORDER BY i.id", (STANDARD_PLATTFORM, inserat_id))]


def entscheidungen_zu(db: Datenbank, *inserat_ids: int) -> list[dict]:
    """Entscheidungen (auch aufgehobene), die eines dieser Inserate betreffen, neueste zuerst; ``aufhebbar`` = nicht durch eine spätere
    „gleich“-Entscheidung blockiert (nur bei geltenden)."""
    if not inserat_ids:
        return []
    q = ",".join("?" * len(inserat_ids))
    ergebnis = []
    for r in db.con.execute(
            "SELECT d.*, ia.anzeigen_id AS anzeige_a, ia.plattform AS plattform_a, ib.anzeigen_id AS anzeige_b, ib.plattform AS plattform_b, "
            "n.name AS nutzer, n2.name AS aufgehoben_von_name FROM dubletten_entscheidungen d "
            "JOIN inserate ia ON ia.id = d.inserat_a JOIN inserate ib ON ib.id = d.inserat_b "
            "LEFT JOIN nutzer n ON n.id = d.nutzer_id LEFT JOIN nutzer n2 ON n2.id = d.aufgehoben_von "
            f"WHERE d.inserat_a IN ({q}) OR d.inserat_b IN ({q}) ORDER BY d.id DESC", (*inserat_ids, *inserat_ids)):
        e = dict(r)
        e["gruende"] = json.loads(e.pop("gruende_json"))
        blockiert = aufheben_blockiert_durch(db, e["id"]) if e["status"] == "gilt" and e["entscheidung"] == "gleich" else None
        e["aufhebbar"] = e["status"] == "gilt" and blockiert is None
        e["blockiert_durch"] = blockiert
        ergebnis.append(e)
    return ergebnis


def halter_der_gruppe(db: Datenbank, anzeigen_ids: list[str], grenze: str) -> list[dict]:
    """Wer hält (Kontakt bestätigt oder Reservierung nicht abgelaufen) welches Inserat der Gruppe – für die Warnung, wenn nach dem
    Zusammenführen verschiedene Kollegen beteiligt sind (Reservierungen werden dabei nicht übertragen)."""
    if not anzeigen_ids:
        return []
    q = ",".join("?" * len(anzeigen_ids))
    return [dict(r) for r in db.con.execute(
        "SELECT b.anzeige_id, b.bearbeiter_id, n.name FROM bearbeitung b JOIN nutzer n ON n.id = b.bearbeiter_id AND n.aktiv = 1 "
        f"WHERE b.anzeige_id IN ({q}) AND (b.kontaktiert_von IS NOT NULL OR COALESCE(b.uebernommen_am, '') >= ?) ORDER BY b.anzeige_id",
        (*anzeigen_ids, grenze))]
