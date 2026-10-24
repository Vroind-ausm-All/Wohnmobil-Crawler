"""Suchprofile und Abdeckungscheckliste (P4-01, ADR-047).

Ein Suchprofil beschreibt gesuchte Fahrzeuge (Art, Marke, Modell, Preis, EZ, km). Solange keine freigegebene Pull-Quelle existiert, ruft es
nichts ab: Es filtert die eingegangenen Inserate (Suchlauf, gespeicherte Seiten, Text, Mails). Die Abdeckungscheckliste hält je Profil und
Plattform fest, ob der Nutzer dort einen Suchauftrag bzw. eine E-Mail-Benachrichtigung angelegt hat, und zeigt, wann zuletzt ein passendes
Inserat dieser Plattform einging.

Oben die Fachlogik ohne Datenbank (Prüfen, Zuordnen, Abdeckung), unten der Speicher.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from .domaene import KLEINANZEIGEN, MOBILEDE, PLATTFORMEN
from .normalisierung.fahrzeug import normalisiere_marke

ARTEN = ("Teilintegrierter", "Integrierter", "Alkoven", "Kastenwagen", "Wohnwagen", "Sonstige")
# Plattformen, deren Eingänge der Scout lesen kann (gespeicherte Seiten, Mails); autoscout24 ist nur vorgemerkt
MIT_EINGANG = (KLEINANZEIGEN, MOBILEDE)
PASST, UNKLAR, NEIN = "passt", "unklar", "nein"
STILL_NACH_TAGEN = 14                     # angelegter Suchauftrag, aber so lange kein passendes Inserat: „prüfen“
MAX_NAME, MAX_MODELL, MAX_NOTIZ, MAX_URL, MAX_MARKEN = 80, 60, 500, 500, 30
GRENZEN = {"preis": (1, 2_000_000), "km": (0, 2_000_000)}


class Eingabefehler(ValueError):
    """Ungültige Profil- oder Auftragsangabe (Text für den Nutzer)."""


def _zahl(daten: dict, feld: str, unten: int, oben: int, name: str) -> int | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        return None
    if isinstance(wert, bool) or not isinstance(wert, int) or not unten <= wert <= oben:
        raise Eingabefehler(f"{name} muss eine ganze Zahl von {unten} bis {oben} sein")
    return wert


def _text(daten: dict, feld: str, laenge: int, name: str) -> str | None:
    wert = daten.get(feld)
    if wert in (None, ""):
        return None
    if not isinstance(wert, str):
        raise Eingabefehler(f"{name} muss Text sein")
    wert = " ".join(wert.split())
    if len(wert) > laenge:
        raise Eingabefehler(f"{name} höchstens {laenge} Zeichen")
    return wert or None


def pruefe_profil(daten: dict, jetzt: datetime) -> dict:
    """Eingabe → gespeicherte Form (``Eingabefehler`` mit verständlichem Text). Leere Kriterien = keine Einschränkung."""
    if not isinstance(daten, dict):
        raise Eingabefehler("Profil muss ein Objekt sein")
    name = _text(daten, "name", MAX_NAME, "Name")
    if not name:
        raise Eingabefehler("Name fehlt")
    arten = daten.get("arten") or []
    if not isinstance(arten, list) or any(a not in ARTEN for a in arten):
        raise Eingabefehler(f"arten: Liste aus {', '.join(ARTEN)}")
    marken = daten.get("marken") or []
    if not isinstance(marken, list) or len(marken) > MAX_MARKEN or any(not isinstance(m, str) or not m.strip() or len(m) > 40 for m in marken):
        raise Eingabefehler(f"marken: Liste mit höchstens {MAX_MARKEN} Namen")
    ez_oben = jetzt.year + 1
    p = {"name": name, "aktiv": daten.get("aktiv", True), "arten": sorted(set(arten), key=ARTEN.index),
         "marken": sorted({normalisiere_marke(m.strip()) or m.strip() for m in marken}),
         "modell": _text(daten, "modell", MAX_MODELL, "Modell"),
         "preis_min": _zahl(daten, "preis_min", *GRENZEN["preis"], "Preis von"), "preis_max": _zahl(daten, "preis_max", *GRENZEN["preis"], "Preis bis"),
         "ez_min": _zahl(daten, "ez_min", 1960, ez_oben, "EZ von"), "ez_max": _zahl(daten, "ez_max", 1960, ez_oben, "EZ bis"),
         "km_max": _zahl(daten, "km_max", *GRENZEN["km"], "km bis"), "notiz": _text(daten, "notiz", MAX_NOTIZ, "Notiz")}
    if not isinstance(p["aktiv"], bool):
        raise Eingabefehler("aktiv muss wahr oder falsch sein")
    for unten, oben, name_ in (("preis_min", "preis_max", "Preis"), ("ez_min", "ez_max", "EZ")):
        if p[unten] is not None and p[oben] is not None and p[unten] > p[oben]:
            raise Eingabefehler(f"{name_}: „von“ ist größer als „bis“")
    return p


def pruefe_auftrag(daten: dict) -> dict:
    """Eintrag der Abdeckungscheckliste: ``plattform``, ``angelegt`` (bool), ``url`` (nur http/https), ``notiz``."""
    if not isinstance(daten, dict):
        raise Eingabefehler("Auftrag muss ein Objekt sein")
    plattform = daten.get("plattform")
    if plattform not in PLATTFORMEN:
        raise Eingabefehler(f"plattform: eine von {', '.join(PLATTFORMEN)}")
    angelegt = daten.get("angelegt", False)
    if not isinstance(angelegt, bool):
        raise Eingabefehler("angelegt muss wahr oder falsch sein")
    if angelegt and plattform not in MIT_EINGANG:
        raise Eingabefehler(f"{plattform}: Inserate dieser Plattform kann der Scout noch nicht einlesen")
    url = _text(daten, "url", MAX_URL, "Adresse")
    if url and not re.fullmatch(r"https?://[^\s/]+\S*", url, re.I):
        raise Eingabefehler("Adresse muss mit http:// oder https:// beginnen und darf keine Leerzeichen enthalten")
    erg = {"plattform": plattform, "angelegt": angelegt, "url": url}
    if "notiz" in daten:                                  # ohne Schlüssel bleibt die gespeicherte Notiz erhalten
        erg["notiz"] = _text(daten, "notiz", MAX_NOTIZ, "Notiz")
    return erg


def pruefe_inserat(profil: dict, a: dict, art: str | None) -> tuple[str, list[str]]:
    """Passt das Inserat (``a``: bewertete Zeile mit ``marke``, ``modell``, ``fahrzeug``) zum Profil? ``art``: Fahrzeugart der Bewertung.
    „unklar“, wenn eine geforderte Angabe fehlt (lieber zeigen als still verschweigen), „nein“, sobald eine Angabe nicht passt."""
    nein, unklar = [], []
    if profil["arten"] and art not in profil["arten"]:
        (unklar if art in (None, "Sonstige") else nein).append(f"Art {art or 'unbekannt'}")
    if profil["marken"]:
        marke = normalisiere_marke(a.get("marke"))
        if not marke:
            unklar.append("Marke unbekannt")
        elif marke.lower() not in {m.lower() for m in profil["marken"]}:
            nein.append(f"Marke {marke}")
    if profil["modell"]:
        text = " ".join(str(a.get(k) or "") for k in ("modell", "fahrzeug", "titel", "kurzbeschreibung")).lower()
        if not re.search(r"(?<!\w)" + re.escape(profil["modell"].lower()) + r"(?!\w)", text):     # ganze Wörter: „TI“ passt nicht zu „Automatik“
            nein.append(f"Modell nicht „{profil['modell']}“")
    for feld, unten, oben, name in (("preis", "preis_min", "preis_max", "Preis"), ("ez_jahr", "ez_min", "ez_max", "EZ"), ("km", None, "km_max", "km")):
        grenze_u, grenze_o = (profil[unten] if unten else None), profil[oben]
        if grenze_u is None and grenze_o is None:
            continue
        wert = a.get(feld)
        if not isinstance(wert, (int, float)) or isinstance(wert, bool):
            unklar.append(f"{name} unbekannt")
        elif (grenze_u is not None and wert < grenze_u) or (grenze_o is not None and wert > grenze_o):
            nein.append(f"{name} {wert}")
    return (NEIN, nein) if nein else (UNKLAR, unklar) if unklar else (PASST, [])


def abdeckung(profil: dict, auftraege: dict[str, dict], letzte_treffer: dict[str, str | None], jetzt: datetime) -> dict:
    """Checkliste eines Profils je Plattform: ``zustand`` fehlt / angelegt / pruefen (angelegt, aber seit ``STILL_NACH_TAGEN`` Tagen kein passendes
    Inserat dieser Plattform) / nicht_lesbar (Plattform ohne Eingang im Scout). ``quote``: angelegte unter den lesbaren Plattformen."""
    grenze = (jetzt - timedelta(days=STILL_NACH_TAGEN)).isoformat(timespec="seconds")
    zeilen = []
    for plattform in PLATTFORMEN:
        a = auftraege.get(plattform) or {}
        letzter = letzte_treffer.get(plattform)
        if plattform not in MIT_EINGANG:
            zustand = "nicht_lesbar"
        elif not a.get("angelegt"):
            zustand = "fehlt"
        else:
            zustand = "angelegt" if letzter and letzter >= grenze else "pruefen"
        zeilen.append({"plattform": plattform, "angelegt": bool(a.get("angelegt")), "url": a.get("url"), "notiz": a.get("notiz"),
                       "letzter_treffer": letzter, "zustand": zustand})
    lesbar = [z for z in zeilen if z["plattform"] in MIT_EINGANG]
    return {"plattformen": zeilen, "quote": round(sum(z["angelegt"] for z in lesbar) / len(lesbar), 2) if lesbar else 0.0}


# ---------------------------------------------------------------- Speicher
class SuchprofilSpeicher:
    """Tabellen ``suchprofile`` und ``suchauftraege`` (Schema v17). Schreibt über die gemeinsame Verbindung in kurzen Transaktionen."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _aus_zeile(z) -> dict:
        p = dict(z)
        p["aktiv"] = bool(p["aktiv"])
        p["arten"], p["marken"] = json.loads(p["arten"] or "[]"), json.loads(p["marken"] or "[]")
        return p

    def liste(self, nur_aktive: bool = False) -> list[dict]:
        sql = "SELECT * FROM suchprofile" + (" WHERE aktiv=1" if nur_aktive else "") + " ORDER BY name COLLATE NOCASE"
        return [self._aus_zeile(z) for z in self.db.con.execute(sql)]

    def profil(self, profil_id: int) -> dict | None:
        z = self.db.con.execute("SELECT * FROM suchprofile WHERE id=?", (profil_id,)).fetchone()
        return self._aus_zeile(z) if z else None

    def auftraege(self, profil_id: int) -> dict[str, dict]:
        return {z["plattform"]: dict(z) for z in self.db.con.execute("SELECT * FROM suchauftraege WHERE profil_id=?", (profil_id,))}

    def _werte(self, p: dict) -> list:
        return [p["name"], int(p["aktiv"]), json.dumps(p["arten"], ensure_ascii=False), json.dumps(p["marken"], ensure_ascii=False), p["modell"],
                p["preis_min"], p["preis_max"], p["ez_min"], p["ez_max"], p["km_max"], p["notiz"]]

    _SPALTEN = ("name", "aktiv", "arten", "marken", "modell", "preis_min", "preis_max", "ez_min", "ez_max", "km_max", "notiz")

    def anlegen(self, p: dict) -> int:
        """``p`` aus ``pruefe_profil``. ``Eingabefehler``, wenn der Name schon vergeben ist."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        with self.db._exklusiv():
            if self.db.con.execute("SELECT 1 FROM suchprofile WHERE name=? COLLATE NOCASE", (p["name"],)).fetchone():
                raise Eingabefehler(f"Ein Profil „{p['name']}“ gibt es schon")
            cur = self.db.con.execute(f"INSERT INTO suchprofile ({', '.join(self._SPALTEN)}, erstellt_am, geaendert_am) "
                                      f"VALUES ({', '.join('?' * (len(self._SPALTEN) + 2))})", [*self._werte(p), jetzt, jetzt])
        return cur.lastrowid

    def aendern(self, profil_id: int, p: dict) -> bool:
        jetzt = datetime.now().isoformat(timespec="seconds")
        with self.db._exklusiv():
            if self.db.con.execute("SELECT 1 FROM suchprofile WHERE name=? COLLATE NOCASE AND id<>?", (p["name"], profil_id)).fetchone():
                raise Eingabefehler(f"Ein Profil „{p['name']}“ gibt es schon")
            cur = self.db.con.execute(f"UPDATE suchprofile SET {', '.join(f'{s}=?' for s in self._SPALTEN)}, geaendert_am=? WHERE id=?",
                                      [*self._werte(p), jetzt, profil_id])
        return cur.rowcount > 0

    def loeschen(self, profil_id: int) -> bool:
        """Profil und seine Checkliste entfernen (keine Personendaten, keine Wirkung auf Inserate)."""
        with self.db._exklusiv():
            self.db.con.execute("DELETE FROM suchauftraege WHERE profil_id=?", (profil_id,))
            cur = self.db.con.execute("DELETE FROM suchprofile WHERE id=?", (profil_id,))
        return cur.rowcount > 0

    def setze_auftrag(self, profil_id: int, a: dict) -> bool:
        """``a`` aus ``pruefe_auftrag``; legt die Zeile an oder ersetzt sie. False, wenn es das Profil nicht gibt."""
        jetzt = datetime.now().isoformat(timespec="seconds")
        with self.db._exklusiv():
            if not self.db.con.execute("SELECT 1 FROM suchprofile WHERE id=?", (profil_id,)).fetchone():
                return False
            notiz = "notiz=excluded.notiz, " if "notiz" in a else ""
            self.db.con.execute("INSERT INTO suchauftraege (profil_id, plattform, angelegt, url, notiz, geaendert_am) VALUES (?, ?, ?, ?, ?, ?) "
                                f"ON CONFLICT(profil_id, plattform) DO UPDATE SET angelegt=excluded.angelegt, url=excluded.url, {notiz}"
                                "geaendert_am=excluded.geaendert_am",
                                (profil_id, a["plattform"], int(a["angelegt"]), a["url"], a.get("notiz"), jetzt))
        return True
