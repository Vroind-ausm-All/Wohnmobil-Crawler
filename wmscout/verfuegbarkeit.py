"""Verfügbarkeit eines Inserats (P3-04, ADR-042): Eigenschaft des Marktes, getrennt vom Ankaufsstatus (``anzeigen.status``).

Gespeichert wird nur, was beobachtet wurde (``inserate.verfuegbarkeit`` + ``zuletzt_bestaetigt``). „Vermutlich offline“ ist KEIN
gespeicherter Wert: es wird beim Lesen aus dem Alter der letzten Bestätigung abgeleitet, damit nichts ohne Beobachtung umgeschrieben wird.
Alles hier ist rein (ohne Netz); die Datenbankzugriffe stehen in ``datenbank.py`` (Schreiben) und unten (Lesen für mehrere Inserate).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)

AKTIV, RESERVIERT, OFFLINE, VERKAUFT, UNBEKANNT = "aktiv", "reserviert", "offline", "verkauft", "unbekannt"
WERTE = (AKTIV, RESERVIERT, OFFLINE, VERKAUFT, UNBEKANNT)
# Nach dieser Zeit ohne Bestätigung gilt ein aktives/reserviertes/unbekanntes Inserat als „vermutlich offline“ (config.yaml → verfuegbarkeit)
STANDARD_OFFLINE_NACH_TAGEN = 14
MAX_OFFLINE_NACH_TAGEN = 3650

HINWEIS_RESERVIERT = "Beim Verkäufer reserviert (laut Anzeige) – Anschreiben bleibt möglich, Verfügbarkeit vorher klären"
SPERRE_VERKAUFT = "Anzeige als verkauft markiert – nicht mehr verfügbar"
SPERRE_OFFLINE = "Anzeige nicht mehr online"
TEXT = {RESERVIERT: "reserviert", VERKAUFT: "verkauft", OFFLINE: "offline"}


# ---------- Zeit ----------
def zu_utc(wert) -> datetime | None:
    """ISO-Text oder datetime nach UTC; ohne Zeitzone gilt die lokale Zeit (so speichert ``anzeigen``). Nicht lesbar: None."""
    try:
        zeit = wert if isinstance(wert, datetime) else datetime.fromisoformat(wert) if wert else None
        return zeit.astimezone(timezone.utc) if zeit else None
    except (TypeError, ValueError):
        return None


def utc_text(zeit: datetime) -> str:
    return zeit.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------- Konfiguration ----------
def offline_nach_tagen(cfg: dict | None) -> int:
    """``verfuegbarkeit.offline_nach_tagen`` aus config.yaml; jeder unbrauchbare Wert (fehlt, Text, Wahrheitswert, ≤ 0, zu groß) ergibt den Standard
    – die Anzeige darf an einer Fehleingabe nicht scheitern."""
    abschnitt = (cfg or {}).get("verfuegbarkeit")
    wert = abschnitt.get("offline_nach_tagen") if isinstance(abschnitt, dict) else None
    if wert is None:
        return STANDARD_OFFLINE_NACH_TAGEN
    if isinstance(wert, bool) or not isinstance(wert, int) or not 0 < wert <= MAX_OFFLINE_NACH_TAGEN:
        log.warning("config.yaml: verfuegbarkeit -> offline_nach_tagen muss eine ganze Zahl von 1 bis %d sein, nicht %r – es gilt %d",
                    MAX_OFFLINE_NACH_TAGEN, wert, STANDARD_OFFLINE_NACH_TAGEN)
        return STANDARD_OFFLINE_NACH_TAGEN
    return wert


# ---------- Erkennung im Anzeigentext ----------
# POSITIVLISTE (P3-04, QA F1): „verkauft“/„reserviert“ zählt nur als Statusmarke, nicht als Verb im Satz („Rentner verkauft Hymer“, „Hymer verkauft
# wg. Umzug“). Alles, was keine der Formen unten ist, ergibt KEIN Signal – lieber eines verpassen als ein Angebot privater Verkäufer sperren.
_SIGNAL = re.compile(r"(?<![\w-])(reserviert|verkauft)(?![\w-])", re.I)
_SATZ = re.compile(r"[.!?;:\n|*()\[\]{}\"„“]")
_WORT = re.compile(r"[a-zäöüß]+")
_OEFFNER, _SCHLIESSER = "([*", ")]*"
_NACH_ANFANG = "!)]*-–—|"                  # direkt hinter einer Marke am Titelanfang („VERKAUFT!“, „Verkauft – Hymer …“); NICHT „:“ und „,“
_VOR_ENDE = "-–—|:/.!([*"                  # direkt vor einer Marke am Titelende („Hymer B 544 – verkauft“, „… Verkauft!“)
_HILFSWORT = frozenset({"bereits", "schon", "leider", "ist", "wurde"})       # „ist verkauft“, „leider schon verkauft“ (ohne Fortsetzung im Satzteil)
_ENDE_SATZTEIL = ".!?,;:|-–—)]*"
_VERNEINUNG = frozenset({"nicht", "noch", "kein", "keine", "nie", "wird", "werden", "soll", "sollte", "kann", "zu", "falls", "wenn", "ob"})


def _ist_statusmarke(text: str, m: re.Match) -> bool:
    vor, nach = text[:m.start()].rstrip(), text[m.end():].lstrip()
    vorwoerter = _WORT.findall(_SATZ.split(text[:m.start()].lower())[-1])[-3:]
    if not _VERNEINUNG.isdisjoint(vorwoerter[-2:]):
        return False
    nach_frei = nach.lstrip("!")
    if vor[-1:] and vor[-1] in _OEFFNER and nach_frei[:1] and nach_frei[0] in _SCHLIESSER:        # „(reserviert)“, „[Verkauft]“, „*** RESERVIERT ***“
        return True
    if not vor.strip(_OEFFNER + " -–—|!") and (not nach or nach[0] in _NACH_ANFANG):              # am Titelanfang, allein oder abgetrennt
        return True
    if not nach.strip("!.)]*? ") and vor[-1:] and vor[-1] in _VOR_ENDE:                          # am Titelende, abgetrennt
        return True
    if m.group(1).isupper() and any(c.islower() for c in text):                                   # komplett großgeschrieben, Titel sonst nicht
        return True
    return bool(vorwoerter) and vorwoerter[-1] in _HILFSWORT and (not nach or nach[0] in _ENDE_SATZTEIL)


def erkenne_signal(*texte: str | None) -> str | None:
    """``reserviert`` oder ``verkauft``, wenn der Text (Titel der Anzeige) es als Statusmarke sagt, sonst None; ``verkauft`` geht vor.

    Statusmarke heißt (Positivliste): allein oder abgetrennt am Titelanfang/-ende („VERKAUFT!“, „– verkauft“, „[Verkauft]“, „(reserviert)“,
    „*** RESERVIERT ***“), komplett großgeschrieben als eigenes Wort in einem sonst gemischt geschriebenen Titel, oder direkt nach
    bereits/schon/leider/ist/wurde ohne Fortsetzung im selben Satzteil („Hymer ist verkauft“, „leider schon verkauft“). Alles andere ist KEIN Signal:
    „Rentner verkauft Hymer“, „verkauft wg. Umzug“, „Verkauft: nur an Privat“, „Probefahrt reserviert“, „nicht verkauft“, „wird verkauft“.
    Nur die ersten 300 Zeichen je Text werden gelesen."""
    gefunden = set()
    for text in texte:
        if not text:
            continue
        t = str(text)[:300]
        for m in _SIGNAL.finditer(t):
            if _ist_statusmarke(t, m):
                gefunden.add(m.group(1).lower())
    return VERKAUFT if VERKAUFT in gefunden else RESERVIERT if RESERVIERT in gefunden else None



def aus_signal(signal: str | None) -> str:
    """Verfügbarkeit einer Beobachtung, in der das Inserat zu sehen war: das erkannte Signal, sonst ``aktiv``."""
    return signal or AKTIV


# ---------- Lesen: wirksamer Wert, abgeleitetes „vermutlich offline“ ----------
def _datum(zeit: datetime | None) -> str:
    return zeit.astimezone().strftime("%d.%m.%Y") if zeit else "?"


def bewerte(roh: str | None, bestaetigt, gesehen, status: str | None, jetzt, tage: int = STANDARD_OFFLINE_NACH_TAGEN) -> dict:
    """Wirksame Verfügbarkeit eines Inserats beim Lesen (rein, schreibt nichts).

    ``roh`` = gespeicherter Wert, ``bestaetigt`` = ``zuletzt_bestaetigt``, ``gesehen`` = ``zuletzt_gesehen`` (Ersatz für Altbestand ohne Bestätigung),
    ``status`` = Ankaufsstatus. Der Altbestand-Status ``gelöscht`` (bis P3-03 vom Detailabruf bei 404 gesetzt) gilt wie ``offline``.
    Rückgabe: ``wert`` (einer aus ``WERTE``), ``gespeichert`` (Rohwert), ``zuletzt_bestaetigt`` (UTC-Text oder None), ``vermutlich_offline``
    (aktiv/reserviert/unbekannt und seit mindestens ``tage`` Tagen nicht bestätigt), ``tage_seit_bestaetigung``, ``text`` (Abzeichen oder None),
    ``hinweis``, ``sperrgrund`` (verkauft/offline) und ``nicht_verfuegbar``."""
    gespeichert = roh if roh in WERTE else UNBEKANNT
    wert = OFFLINE if status == "gelöscht" else gespeichert
    letzte = zu_utc(bestaetigt) or zu_utc(gesehen)
    jetzt_utc = zu_utc(jetzt) or datetime.now(timezone.utc)
    seit = max(0, (jetzt_utc - letzte).days) if letzte else None
    vermutlich = wert in (AKTIV, RESERVIERT, UNBEKANNT) and seit is not None and (jetzt_utc - letzte).total_seconds() >= tage * 86400
    nicht_verfuegbar = wert in (OFFLINE, VERKAUFT)
    text = TEXT.get(wert)
    hinweis = HINWEIS_RESERVIERT if wert == RESERVIERT else None
    if vermutlich:
        text = f"vermutlich offline – zuletzt bestätigt {_datum(letzte)}"
        hinweis = (f"Seit {seit} Tagen nicht mehr bestätigt (zuletzt {_datum(letzte)}) – vermutlich nicht mehr online, vor dem Anschreiben prüfen"
                   + (" · beim Verkäufer reserviert" if wert == RESERVIERT else ""))
    return {"wert": wert, "gespeichert": gespeichert, "zuletzt_bestaetigt": utc_text(letzte) if letzte and zu_utc(bestaetigt) else None,
            "vermutlich_offline": vermutlich, "tage_seit_bestaetigung": seit, "text": text, "hinweis": hinweis,
            "sperrgrund": SPERRE_VERKAUFT if wert == VERKAUFT else SPERRE_OFFLINE if wert == OFFLINE else None,
            "nicht_verfuegbar": nicht_verfuegbar}


# Schlüssel in den Zeilen von ``anzeigen``, die ``Datenbank.verfuegbarkeit_zu`` aus ``inserate`` ergänzt (Rohwerte)
ROH_SCHLUESSEL = ("inserat_verfuegbarkeit", "inserat_bestaetigt", "inserat_gesehen")


def ergaenze(a: dict, jetzt, tage: int = STANDARD_OFFLINE_NACH_TAGEN) -> dict:
    """Ergänzt eine Zeile (Dict) um ``verfuegbarkeit`` (wirksamer Wert), ``zuletzt_bestaetigt``, ``vermutlich_offline``, ``verfuegbarkeit_text``,
    ``verfuegbarkeit_hinweis``, ``verfuegbarkeit_sperre`` und ``nicht_verfuegbar``. Fehlen die Rohwerte (keine Verknüpfung zu ``inserate``),
    gilt „unbekannt“ – nie „offline“ aus Mangel an Daten."""
    b = bewerte(a.get("inserat_verfuegbarkeit"), a.get("inserat_bestaetigt"), a.get("inserat_gesehen"), a.get("status"), jetzt, tage)
    a.update(verfuegbarkeit=b["wert"], zuletzt_bestaetigt=b["zuletzt_bestaetigt"], vermutlich_offline=b["vermutlich_offline"],
             verfuegbarkeit_text=b["text"], verfuegbarkeit_hinweis=b["hinweis"], verfuegbarkeit_sperre=b["sperrgrund"],
             nicht_verfuegbar=b["nicht_verfuegbar"])
    return a


# ---------- Fahrzeug: abgeleitet aus seinen Inseraten ----------
# Reihenfolge „am ehesten noch zu haben“: ein frisch bestätigtes aktives Inserat schlägt reserviert, das unbekannt, das nur vermutlich offline,
# das sicher offline; verkauft ist am Ende (das Fahrzeug ist weg). Bei Gleichstand gewinnt der kleinere Rang der Werte.
_RANG = {AKTIV: 0, RESERVIERT: 1, UNBEKANNT: 2}
_VERMUTLICH = 10
_OFFLINE, _VERKAUFT = 20, 30


def fahrzeug_verfuegbarkeit(inserate: list[dict]) -> dict:
    """Verfügbarkeit eines Fahrzeugs aus den ``bewerte``-Ergebnissen seiner Inserate: ``{"wert", "vermutlich_offline", "anzahl"}``.

    Rangfolge: aktiv > reserviert > unbekannt > (vermutlich offline) > offline > verkauft; ein nur vermutlich offline geführtes Inserat steht
    hinter jedem frisch bestätigten, aber vor einem sicher offline oder verkauften. Ohne Inserate ``unbekannt``."""
    if not inserate:
        return {"wert": UNBEKANNT, "vermutlich_offline": False, "anzahl": 0}

    def rang(b: dict) -> int:
        if b["wert"] == VERKAUFT:
            return _VERKAUFT
        if b["wert"] == OFFLINE:
            return _OFFLINE
        return _RANG[b["wert"]] + (_VERMUTLICH if b["vermutlich_offline"] else 0)
    best = min(inserate, key=rang)
    return {"wert": best["wert"], "vermutlich_offline": bool(best["vermutlich_offline"]), "anzahl": len(inserate)}


def fahrzeug_von(con, fahrzeug_id: int, jetzt, tage: int = STANDARD_OFFLINE_NACH_TAGEN) -> dict:
    """Verfügbarkeit eines Fahrzeugs (``fahrzeuge.id``) beim Lesen: ``{"wert", "vermutlich_offline", "anzahl", "inserate": [...]}`` – je Inserat
    Plattform, Anzeigen-ID, wirksamer Wert, ``zuletzt_bestaetigt``, ``vermutlich_offline`` und ``text``. Nur lesend."""
    from .domaene import KLEINANZEIGEN
    zeilen = con.execute(
        "SELECT i.plattform, i.anzeigen_id, i.verfuegbarkeit, i.zuletzt_bestaetigt, i.zuletzt_gesehen, a.status "
        "FROM inserate i LEFT JOIN anzeigen a ON a.id = i.anzeigen_id AND COALESCE(NULLIF(a.quelle, ''), ?) = i.plattform "
        "WHERE i.fahrzeug_id = ? ORDER BY i.id", (KLEINANZEIGEN, fahrzeug_id)).fetchall()
    bewertet = [(z, bewerte(z["verfuegbarkeit"], z["zuletzt_bestaetigt"], z["zuletzt_gesehen"], z["status"], jetzt, tage)) for z in zeilen]
    return {**fahrzeug_verfuegbarkeit([b for _, b in bewertet]),
            "inserate": [{"plattform": z["plattform"], "anzeigen_id": z["anzeigen_id"], "wert": b["wert"], "zuletzt_bestaetigt": b["zuletzt_bestaetigt"],
                          "vermutlich_offline": b["vermutlich_offline"], "text": b["text"]} for z, b in bewertet]}
