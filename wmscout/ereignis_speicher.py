"""Additiver Echtzeit-Eingang: persistiert simulierte Ereignisse in den v4-Tabellen.

Die bestehende Tabelle 'anzeigen' und damit Browser-App, Ankauf und Bewertung bleiben
absichtlich unverändert. Die spätere Anbindung beider Sichten erfolgt in einem eigenen PR.
"""
from __future__ import annotations

import hashlib
import json

from .ereignisse import InseratEreignis


class QuelleNichtFreigegeben(PermissionError):
    """Ein automatisierter Kanal hat keine aktivierte, dokumentierte Quellenfreigabe."""


class EreignisSpeicher:
    def __init__(self, datenbank):
        self.db = datenbank

    def verarbeite(self, ereignis: InseratEreignis) -> str:
        """'neu', 'geaendert', 'geloescht', 'bekannt' oder 'unbekannt'.

        Atomar: Inserat, Beobachtung und Preisverlauf werden gemeinsam geschrieben.
        Gleiche Ereignis-IDs werden nicht ein zweites Mal verarbeitet.
        """
        con = self.db.con
        con.execute("BEGIN IMMEDIATE")
        try:
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
                    con.commit()
                    return "bekannt"

            alt = con.execute("SELECT * FROM inserate WHERE plattform=? AND anzeigen_id=?",
                              (ereignis.plattform, ereignis.anzeigen_id)).fetchone()
            if alt is None and ereignis.typ == "geloescht":
                con.commit()
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
                con.commit()
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

            inhalt_hash = hashlib.sha256(json.dumps(signatur, ensure_ascii=False).encode("utf-8")).hexdigest()
            con.execute(
                """INSERT INTO beobachtungen
                   (inserat_id, plattform, kanal, ereignis_typ, ereignis_id, zeitpunkt, preis, inhalt_hash)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (inserat_id, ereignis.plattform, ereignis.kanal, ereignis.typ,
                 ereignis.ereignis_id, zeit, preis, inhalt_hash))
            if preis is not None and (neu or alt["preis"] != preis):
                con.execute(
                    "INSERT INTO preis_historie (inserat_id, zeitpunkt, preis, kanal) VALUES (?,?,?,?)",
                    (inserat_id, zeit, preis, ereignis.kanal))
            con.commit()
            return "neu" if neu else "geloescht" if ereignis.typ == "geloescht" else "geaendert"
        except BaseException:
            con.rollback()
            raise
