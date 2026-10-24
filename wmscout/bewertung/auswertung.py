"""Bewertet alle aktiven Inserate: Entfernung, Dubletten, Marktwert, Anschreiben, Nachfassen."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..domaene import STATUS, UNBEKANNT, import_art
from ..dubletten import Wirkung, lade_wirkung, wende_an
from ..anbieter import einstufung
from ..normalisierung.qualitaet import pruefe_fahrzeug, pruefe_inserat
from ..normalisierung.fahrzeug import arten_im_text, ergaenze_fahrzeug
from ..normalisierung.geo import entfernung_km
from ..verfuegbarkeit import ergaenze as ergaenze_verfuegbarkeit
from ..verfuegbarkeit import offline_nach_tagen
from .anschreiben import Anschreiber, betrag_im_brief, euro, hinweise, sperrgrund
from .neuigkeit import einstellungen as neuigkeit_einstellungen
from .neuigkeit import neuigkeit
from .rechner import Bewertung, Rechner, Vergleichsliste

if TYPE_CHECKING:                      # nur für Typangaben – die Bewertung selbst braucht keine Datenbank (P1-08)
    from ..datenbank import Datenbank


BEARBEITET = {"vorbereitet", "kontaktiert", "verhandlung", "besichtigung", "gekauft", "abgesagt", "uninteressant"}


def finde_duplikate(alle: list[dict]) -> dict[str, list[dict]]:
    """id → andere Anzeigen desselben Fahrzeugs (gleiche Marke, EZ, PLZ, Modellreihe, km ± 3.000).

    Typisch: Verkäufer löscht die Anzeige und stellt sie neu ein, oder inseriert doppelt."""
    gruppen = defaultdict(list)
    for a in alle:
        if a.get("marke") and a.get("ez_jahr") and a.get("km") and a.get("plz"):
            gruppen[(a["marke"].lower(), a["ez_jahr"], a["plz"])].append(a)
    duplikate = {}
    for liste in gruppen.values():
        for a in liste if len(liste) > 1 else []:
            andere = [b for b in liste if b["id"] != a["id"] and abs(b["km"] - a["km"]) <= 3000
                      and (not a.get("serie") or not b.get("serie") or a["serie"] == b["serie"])]
            if andere:
                duplikate[a["id"]] = andere
    return duplikate


def dubletten_ids(db: Datenbank) -> dict[str, list[str]]:
    """id → sortierte IDs der Dubletten – dieselbe Gruppierung wie in `bewerte_alle` (`dubletten_ids` je Zeile), aber ohne
    Rechner, Anschreiben und Entfernungen. Für die Team-Prüfung bei Schreibzugriffen (Reservierung wirkt auf die Fahrzeuggruppe).
    Heuristik ∪ bestätigte Fahrzeuggruppe, ohne Paare mit Entscheidung „verschieden“ (P3-02b); die Gruppe gilt auch für Inserate ohne Preis."""
    alle = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    ids = {i: [b["id"] for b in andere] for i, andere in finde_duplikate(alle).items()}
    ids = wende_an(ids, lade_wirkung(db), lambda i: i, lambda i: i)
    return {i: sorted(andere) for i, andere in ids.items()}


def fuer_rechner(a: dict) -> dict:
    """Fahrzeugdaten, wie der Rechner sie bekommt (QA H3): Bei importierten Inseraten mit UNBEKANNTER Fahrzeugart darf
    der Titel die Art nicht bestimmen – sonst macht „Everest Minicamp, Camper, Wohnwagen, Motocrosshänger“ über den
    ersten Art-Begriff einen Kastenwagen. Der Rechner (`art_schluessel(suche, art, titel)`) bleibt unverändert; er
    bekommt eine Kopie ohne `art`/`titel`, der Titel wandert vor die Kurzbeschreibung, damit Ausstattung und Mängel
    (Wertfaktoren) gleich erkannt werden. Ergebnis: Diese Sicht rechnet mit „Sonstige“; so steht die Anzeige auch in
    der Vergleichsliste. Bewertet wird sie selbst vorsichtig über alle Kandidaten-Arten (siehe `bewerte_anzeige`).
    Vorläufige Arten bleiben (mit Hinweis), alle anderen Anzeigen werden unverändert durchgereicht."""
    if import_art(a.get("suche"))[1] != UNBEKANNT:
        return a
    return {**a, "art": None, "titel": None, "kurzbeschreibung": f"{a.get('titel') or ''} {a.get('kurzbeschreibung') or ''}"}


def kandidaten_arten(a: dict) -> list[str]:
    """Arten, mit denen eine importierte Anzeige UNBEKANNTER Art gerechnet wird: „Sonstige“ (ohne Art) und jede Art,
    die Titel oder Kurzbeschreibung nennen (`arten_im_text`, z. B. „Wohnwagen .Bürstner premio life“ → Wohnwagen).
    Leer für alle anderen Anzeigen (Crawler-Funde, vorläufige und bestätigte Arten)."""
    if import_art(a.get("suche"))[1] != UNBEKANNT:
        return []
    return ["Sonstige"] + sorted(arten_im_text(f"{a.get('titel') or ''} {a.get('kurzbeschreibung') or ''}"))


def _sicht_als(sicht: dict, art: str) -> dict:
    """Rechner-Sicht mit vorgegebener Art. „Sonstige“ ist genau die Sicht aus der Vergleichsliste (gleiche id); jede
    andere Art bekommt eine eigene Kennung, weil der Rechner Referenzwerte je id zwischenspeichert – sonst bekäme die
    Anzeige in der Vergleichsliste den Referenzwert einer anderen Art (M6-1)."""
    if art == "Sonstige":
        return sicht
    kennung = sicht.get("id")
    return {**sicht, "art": art, "id": f"{kennung}#als {art}" if kennung and kennung != "manuell" else kennung}


SICHERHEIT_ART_UNBEKANNT = "niedrig"


def bewerte_anzeige(rechner: Rechner, a: dict, vergleich: list[dict], marktwert_manuell: int | None = None) -> Bewertung:
    """Bewertung einer Anzeige in Rechner-Sicht; `vergleich` aus `vergleichsbasis`.

    Orte im Ausland (`a["ausland"]`, siehe `normalisierung.geo.auslands_kuerzel`) haben keine PLZ und keine Entfernung; der Rechner
    nähme dann die Transportpauschale für unbekannte Entfernung – für eine Abholung im Ausland viel zu wenig, der Max-EK wäre zu hoch.
    Deshalb Ampel höchstens „gelb“ und ein Vermerk in der Vergleichsbasis; der Hinweis am Fahrzeug steht in `anschreiben.hinweise`.

    Bei UNBEKANNTER Art (Import) vorsichtig (QA H6-1), ohne den Rechner zu ändern:
      * Der Rechner läuft einmal je Kandidaten-Art (`kandidaten_arten`); genommen wird die Bewertung mit dem
        NIEDRIGSTEN Max-EK (bei Gleichstand „Sonstige“). „Sonstige“ allein wäre zu hoch, wenn die Anzeige z. B. ein
        Wohnwagen ist (Neupreis 30.000 statt 65.000 €).
      * Sicherheit höchstens „niedrig“ – die Art ist nicht bekannt, die Vergleichsgruppe also unsicher. „keine“ und
        „manuell“ bleiben. Ampel, Verhältnis und Sortierung hängen nur am Max-EK (Sicherheit nur über „keine“) und
        bleiben damit zur genommenen Bewertung stimmig.
      * Ampel höchstens „gelb“ (Betreiberentscheidung F14, 14.10.2026): Wohnwagen ohne Art-Wort im Text würden sonst als
        „Sonstige“ grün; der Brief nennt dann keinen Betrag (`anschreiben.kontext`).
      * Spanne = von der kleinsten bis zur größten Spanne aller Kandidaten (Unsicherheit über die Art ausweisen).
    Welche Art genommen wurde, steht in `b.art` und im Hinweis am Fahrzeug (`anschreiben.hinweise(a, b)`)."""
    b = _bewerte_nach_art(rechner, a, vergleich, marktwert_manuell)
    if a.get("ausland"):
        b = replace(b, ampel="gelb" if b.ampel == "gruen" else b.ampel,
                    vergleich_basis=f"{b.vergleich_basis} · Ausland ({a['ausland']}): Entfernung und Transport nicht berechnet")
    return b


def _bewerte_nach_art(rechner: Rechner, a: dict, vergleich: list[dict], marktwert_manuell: int | None) -> Bewertung:
    sicht = fuer_rechner(a)
    kandidaten = kandidaten_arten(a)
    if not kandidaten:
        return rechner.bewerte(sicht, vergleich, marktwert_manuell=marktwert_manuell)
    alle_b = [rechner.bewerte(_sicht_als(sicht, art), vergleich, marktwert_manuell=marktwert_manuell) for art in kandidaten]
    b = min(alle_b, key=lambda x: x.max_ek)                       # min() nimmt bei Gleichstand den ersten: „Sonstige“
    von = [x.spanne_von for x in alle_b if x.spanne_von]
    bis = [x.spanne_bis for x in alle_b if x.spanne_bis]
    basis = b.vergleich_basis
    if len(kandidaten) > 1:
        geprueft = ", ".join("ohne Art" if k == "Sonstige" else k for k in kandidaten)
        basis += f" · Fahrzeugart unbekannt: niedrigster Max-EK aus {geprueft}"
    return replace(b, sicherheit=SICHERHEIT_ART_UNBEKANNT if b.sicherheit in ("hoch", "mittel") else b.sicherheit,
                   ampel="gelb" if b.ampel == "gruen" else b.ampel,
                   spanne_von=min(von) if von else b.spanne_von, spanne_bis=max(bis) if bis else b.spanne_bis,
                   vergleich_basis=basis)


def vergleichsbasis(alle: list[dict], duplikate: dict[str, list[dict]] | None = None) -> list[dict]:
    """Vergleichsangebote für den Rechner – für `bewerte_alle` und `scout.py rechne` gleich: von mehrfach eingestellten
    Fahrzeugen nur die aktuellste Anzeige, jede in Rechner-Sicht (`fuer_rechner`), damit Art und Rechner-Cache (je id)
    zur bewerteten Anzeige passen (M6-1/M6-2). Als ``Vergleichsliste`` mit Vorfilter für ``Rechner.vergleiche`` (P3-07)."""
    duplikate = finde_duplikate(alle) if duplikate is None else duplikate
    return Vergleichsliste(fuer_rechner(a) for a in alle if not any((b.get("zuletzt_gesehen") or "", b["id"]) > (a.get("zuletzt_gesehen") or "", a["id"])
                                                     for b in duplikate.get(a["id"], [])))


def vergleichsbasis_aus(db: Datenbank) -> list[dict]:
    """``vergleichsbasis`` über alle Inserate mit Preis, mit den geltenden Dublettenentscheidungen (wie `bewerte_alle`)."""
    alle = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    nach_id = {a["id"]: a for a in alle}
    return vergleichsbasis(alle, wende_an(finde_duplikate(alle), lade_wirkung(db), nach_id.get, lambda a: a["id"]))  # nur Inserate mit Preis


def _datum(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}." if iso and len(iso) >= 10 else "?"


def nachfass_grund(a: dict, cfg: dict, jetzt: datetime) -> str | None:
    """Warum jetzt nachgefasst werden sollte (oder None)."""
    nf = cfg.get("nachfassen") or {}
    letzter = max(a.get("kontaktiert_am") or "", a.get("nachgefasst_am") or "")
    if a.get("status") not in ("kontaktiert", "verhandlung", "abgesagt") or not letzter:
        return None
    if a.get("preis_geaendert_am") and a["preis_geaendert_am"] > letzter:
        return f"Preis gesenkt auf {euro(a['preis'])}"
    tage = (jetzt - datetime.fromisoformat(letzter)).days
    if (a["status"] == "kontaktiert" and tage >= nf.get("nach_tagen", 3)
            and (a.get("nachfass_anzahl") or 0) < nf.get("max_anzahl", 1)):
        return f"seit {tage} Tagen keine Antwort"
    return None


def bewerte_alle(cfg: dict, db: Datenbank, basis: Path, lauf_start: str | None = None) -> list[dict]:
    """Liest die Inserate und die geltenden Dublettenentscheidungen aus der Datenbank und bewertet sie (``bewerte_zeilen``)."""
    wirkung = lade_wirkung(db)
    mitglieder = {i for g in wirkung.gruppen for i in g}
    roh = db.verfuegbarkeit_zu()                       # Verfügbarkeit aus „inserate“, eine Abfrage für alle Zeilen (P3-04)
    arbeit = db.anzeigen_mit_arbeit()                  # Team-Arbeit, die nicht im Ankaufsstatus steht (Reservierung, Besichtigung, Ankauf)

    def zeile(r) -> dict:
        return {**dict(r), **roh.get(r["id"], {}), "hat_arbeit": r["id"] in arbeit}
    return bewerte_zeilen(cfg, basis, [zeile(r) for r in db.alle_mit_preis()], [zeile(r) for r in db.aktive()], lauf_start,
                          wirkung=wirkung, gruppenzeilen=[zeile(r) for r in db.anzeigen_zu(mitglieder)])


def bewerte_zeilen(cfg: dict, basis: Path, mit_preis: list[dict], aktive: list[dict], lauf_start: str | None = None,
                   jetzt: datetime | None = None, wirkung: Wirkung | None = None, gruppenzeilen: list[dict] = ()) -> list[dict]:
    """Bewertung ohne Datenbank (P1-08, ADR-015): ``mit_preis`` = alle Inserate mit Preis (Vergleichsbasis, Dubletten),
    ``aktive`` = die zu bewertenden Inserate – beide als einfache Dicts mit den Spalten der Tabelle ``anzeigen``.
    ``wirkung``: geltende Dublettenentscheidungen (bestätigte Fahrzeuggruppen, „verschieden“-Paare); ohne sie gilt nur die Heuristik.
    ``gruppenzeilen``: Zeilen der Gruppenmitglieder (auch ohne Preis oder lange nicht gesehen). Sperren und Markierungen berücksichtigen
    jedes Mitglied, das als ``mit_preis``-, ``aktive``- oder Gruppenzeile vorliegt; die Vergleichsbasis nur Inserate mit Preis."""
    rechner, schreiber = Rechner(cfg), Anschreiber(cfg, basis)
    jetzt = jetzt or datetime.now()
    standort = str(cfg["anschreiben"].get("plz") or "") or None
    tage = offline_nach_tagen(cfg)
    neu_e = neuigkeit_einstellungen(cfg)

    def angereichert(r) -> dict:                      # Fahrzeugmerkmale + Verfügbarkeit (wirksam, „vermutlich offline“ beim Lesen abgeleitet)
        a = ergaenze_verfuegbarkeit(ergaenze_fahrzeug(dict(r)), jetzt, tage)
        a["anbieter"] = einstufung(a.get("gewerblich"), a.get("anbieter_herkunft"))     # Anbieterart mit Herkunft (P3-05)
        return a
    alle = [angereichert(r) for r in mit_preis]
    nach_id = {a["id"]: a for a in alle}
    heuristisch = finde_duplikate(alle)
    vergleich = vergleichsbasis(alle, wende_an(heuristisch, wirkung, nach_id.get, lambda a: a["id"]))
    if wirkung is None or wirkung.leer:
        duplikate = heuristisch
    else:                                   # Mitglieder ohne Preis zählen für Sperren und Markierungen, nicht für die Vergleichsbasis
        sonst = {z["id"]: angereichert(z) for z in [*aktive, *gruppenzeilen] if z["id"] not in nach_id}
        duplikate = wende_an(heuristisch, wirkung, {**sonst, **nach_id}.get, lambda a: a["id"])
    qcache: dict[str, list] = {}

    def markierungen(b: dict) -> list[dict]:          # Datenqualität je Inserat nur einmal je Bewertungslauf (P3-08, Gruppen)
        if b["id"] not in qcache:
            qcache[b["id"]] = pruefe_inserat(b, jetzt)
        return qcache[b["id"]]
    zeilen = []
    for r in aktive:
        a = angereichert(r)                  # Altbestand-Status „gelöscht“ bleibt in der Liste und gilt wie offline (gesperrt, Abzeichen)
        a["entfernung_km"] = entfernung_km(standort, a.get("plz"))
        andere = duplikate.get(a["id"], [])
        # Datenqualität (P3-08): Markierungen des Inserats und Wert des Fahrzeugs über alle seine Inserate – nur Anzeige, keine Wirkung
        a["datenqualitaet_inserat"] = markierungen(a)
        a["datenqualitaet"] = pruefe_fahrzeug(a, andere, jetzt, a["datenqualitaet_inserat"], vorab=markierungen)
        seit = min([a.get("erstmals_gesehen") or jetzt.isoformat()] + [b.get("erstmals_gesehen") or "9" for b in andere])
        a["tage_online"] = max(0, (jetzt - datetime.fromisoformat(seit)).days)
        a["neu_eingestellt"] = any((b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "") for b in andere)
        bearbeitet = [b for b in andere if b.get("status") in BEARBEITET]
        live_aelter = [b for b in andere if b.get("status") in (None, "neu") and not b.get("nicht_verfuegbar")
                       and (b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "")
                       and (b.get("zuletzt_gesehen") or "") >= (a.get("zuletzt_gesehen") or "")[:10]]
        if bearbeitet:
            b0 = bearbeitet[0]
            a["duplikat"] = (f"gleiches Fahrzeug schon bearbeitet: Anzeige {b0['id']} "
                             f"({STATUS.get(b0['status'], b0['status'])} am {_datum(b0.get('status_am') or b0.get('kontaktiert_am'))})")
        elif live_aelter:
            a["duplikat"] = f"doppelt eingestellt – ältere Anzeige {live_aelter[0]['id']} ist noch online"
        b = bewerte_anzeige(rechner, a, vergleich)
        sperre = sperrgrund(a, cfg)
        # Text gibt es für jede nicht gesperrte Anzeige; „bereit“ sind nur die, deren Ampel passt.
        # `hinweise` (z. B. Fahrzeugart nicht bestätigt) sperren nichts, sie stehen sichtbar am Fahrzeug
        brief = schreiber.text(a, b) if not sperre else None
        grund = nachfass_grund(a, cfg, jetzt)
        nachfass_text, nachfass_betrag = schreiber.nachfass(a, b) if grund else (None, None)
        if cfg["rechner"]["differenzbesteuerung"]:
            ust = (b.haendler_vk - b.max_ek) * 19 / 119
        else:
            ust = b.haendler_vk - b.haendler_vk / 1.19
        # Verkaufte/nicht mehr online stehende Anzeigen ohne Ankaufsarbeit sind in den Standardlisten ausgeblendet (wie früher Status „gelöscht“)
        # …es sei denn, es wird schon daran gearbeitet: Status, Team-Reservierung, Besichtigung/Ankauf oder eine Notiz (nichts Eigenes verstecken)
        ausblenden = (bool(a.get("nicht_verfuegbar")) and a.get("status") in (None, "neu", "gelöscht")
                      and not a.get("hat_arbeit") and not str(a.get("notiz") or "").strip())
        bereit = bool(brief) and schreiber.soll_schreiben(b.ampel)
        zeilen.append({
            "a": a, "b": b, "sperre": sperre, "ausblenden": ausblenden, "hinweise": hinweise(a, b), "brief": brief, "ust": round(ust / 10) * 10,
            "brief_betrag": betrag_im_brief(a, b),
            "bereit": bereit,
            # frisch eingegangen / Preis deutlich gesenkt / dadurch jetzt im Rahmen: Rang für „Neuigkeiten zuerst“, ohne Wirkung (P4-03)
            "neuigkeit": neuigkeit(a, b, bereit, ausblenden, jetzt, neu_e, sperre),
            "neu": bool(lauf_start and (a.get("erstmals_gesehen") or "") >= lauf_start) and not ausblenden,
            "nachfassen": grund, "nachfass_text": nachfass_text, "nachfass_betrag": nachfass_betrag,
            "dubletten_ids": sorted(b["id"] for b in andere),       # Fahrzeuggruppe: Team-Reservierungen wirken auf alle
        })
    return zeilen
