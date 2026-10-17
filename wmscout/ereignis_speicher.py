"""Additiver Echtzeit-Eingang: persistiert simulierte Ereignisse in den v4-Tabellen.

Neue und geänderte Inserate erscheinen zusätzlich in 'anzeigen' (Browser-App, Ankauf, Bewertung); umgekehrt spiegelt
``Datenbank.speichere_treffer`` jeden Such- und Seitentreffer in die v4-Tabellen. Beide Sichten bleiben so gleich.
"""
from __future__ import annotations

import logging

from .datenbank import IMPORT_SUCHE, STANDARD_PLATTFORM, inhalt_hash
from .domaene import PUSH_KANAELE
from .ereignisse import InseratEreignis

log = logging.getLogger(__name__)


class QuelleNichtFreigegeben(PermissionError):
    """Ein automatisierter Kanal hat keine aktivierte, dokumentierte Quellenfreigabe."""


class EreignisSpeicher:
    def __init__(self, datenbank):
        self.db = datenbank

    def verarbeite(self, ereignis: InseratEreignis) -> str:
        """'neu', 'geaendert', 'geloescht', 'bekannt' oder 'unbekannt'.

        Atomar: Inserat, Beobachtung, Preisverlauf und – bei neuen oder geänderten Daten – die Zeile in ``anzeigen`` (App,
        Bewertung) werden gemeinsam geschrieben. Gleiche Ereignis-IDs werden nicht ein zweites Mal verarbeitet.
        Ein Löschereignis ändert nur die Verfügbarkeit in ``inserate``, nie den Ankaufstatus in ``anzeigen``.
        """
        with self.db.transaktion():
            return self._verarbeite(ereignis)

    def _verarbeite(self, ereignis: InseratEreignis) -> str:
        con = self.db.con
        if ereignis.kanal in PUSH_KANAELE:
            # Was der Nutzer liefert (E-Mail, Text, Seite), läuft über Importer.importiere mit den Regeln zu Art und Anbieter (ADR-035)
            raise ValueError(f"Kanal {ereignis.kanal!r} ist ein Push-Eingang – Importer.importiere verwenden, nicht den EreignisSpeicher")
        if ereignis.kanal in ("stream", "api"):
            q = con.execute("SELECT freigegeben, aktiv, zugriffsart FROM quellen WHERE kennung=?",
                            (ereignis.plattform,)).fetchone()
            if q is None or not q["freigegeben"] or not q["aktiv"] or q["zugriffsart"] != "api":
                raise QuelleNichtFreigegeben(f"Automatischer Eingang für {ereignis.plattform} nicht freigegeben")
        if ereignis.ereignis_id is not None:
            schon = con.execute(
                "SELECT 1 FROM beobachtungen WHERE plattform=? AND kanal=? AND ereignis_id=?",
                (ereignis.plattform, ereignis.kanal, ereignis.ereignis_id)).fetchone()
            if schon:
                return "bekannt"

        alt = con.execute("SELECT * FROM inserate WHERE plattform=? AND anzeigen_id=?",
                          (ereignis.plattform, ereignis.anzeigen_id)).fetchone()
        if alt is None and ereignis.typ == "geloescht":
            return "unbekannt"

        zeit = ereignis.empfangen_am.isoformat()
        if ereignis.typ == "geloescht":
            status = "offline"
            url, titel, preis = alt["url"], alt["titel"], alt["preis"]
        else:
            status = "aktiv"
            i = ereignis.inserat
            url = i.url or (alt["url"] if alt else None)
            titel = i.titel if i.titel is not None else (alt["titel"] if alt else None)
            preis = i.preis if i.preis is not None else (alt["preis"] if alt else None)

        neu = alt is None
        alt_signatur = (alt["url"], alt["titel"], alt["preis"], alt["verfuegbarkeit"]) if alt else None
        signatur = (url, titel, preis, status)
        if alt_signatur == signatur:
            return "bekannt"

        if neu:
            con.execute(
                """INSERT INTO inserate (plattform, anzeigen_id, url, titel, preis, verfuegbarkeit,
                   erstmals_gesehen, zuletzt_gesehen) VALUES (?,?,?,?,?,?,?,?)""",
                (ereignis.plattform, ereignis.anzeigen_id, url, titel, preis, status, zeit, zeit))
            inserat_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            inserat_id = alt["id"]
            con.execute(
                "UPDATE inserate SET url=?, titel=?, preis=?, verfuegbarkeit=?, zuletzt_gesehen=? WHERE id=?",
                (url, titel, preis, status, zeit, inserat_id))

        con.execute(
            """INSERT INTO beobachtungen
               (inserat_id, plattform, kanal, ereignis_typ, ereignis_id, zeitpunkt, preis, inhalt_hash)
               VALUES (?,?,?,?,?,?,?,?)""",
            (inserat_id, ereignis.plattform, ereignis.kanal, ereignis.typ,
             ereignis.ereignis_id, zeit, preis, inhalt_hash(signatur)))
        if preis is not None and (neu or alt["preis"] != preis):
            con.execute(
                "INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?,?,?,?)",
                (inserat_id, zeit, preis, ereignis.kanal))
        if ereignis.typ != "geloescht":
            self._in_anzeigen(ereignis, inserat_id)
        return "neu" if neu else "geloescht" if ereignis.typ == "geloescht" else "geaendert"

    def _in_anzeigen(self, ereignis: InseratEreignis, inserat_id: int):
        """App und Bewertung lesen ``anzeigen``: dort anlegen bzw. aktualisieren. Die Art ist aus einem Ereignis nicht belegt –
        neue Zeilen bekommen ``IMPORT_SUCHE`` (Art unbekannt: Ampel höchstens gelb, kein Betrag im Brief, F14); eine vorhandene
        Zuordnung bleibt. Gehört dieselbe Anzeigen-ID in ``anzeigen`` einer anderen Plattform, bleibt diese Zeile unberührt."""
        ad_id = ereignis.anzeigen_id
        zeile = self.db.con.execute("SELECT quelle, suche FROM anzeigen WHERE id=?", (ad_id,)).fetchone()
        if zeile is not None and (zeile["quelle"] or STANDARD_PLATTFORM) != ereignis.plattform:
            log.warning("Anzeigen-ID %s gehört in „anzeigen“ zu %s, nicht zu %s – App-Zeile bleibt unverändert.",
                        ad_id, zeile["quelle"] or STANDARD_PLATTFORM, ereignis.plattform)
            return
        self.db.schreibe_anzeige(ereignis.inserat.als_datensatz(), zeile["suche"] if zeile and zeile["suche"] else IMPORT_SUCHE)
        self.db.verknuepfe_inserat(inserat_id, ad_id)
