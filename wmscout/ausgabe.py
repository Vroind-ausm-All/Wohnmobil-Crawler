"""Ausgaben: HTML-Report (auch Seite der Browser-App), CSV für Excel und Anschreiben als Textdateien."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .anbieter import HERKUNFT_TEXT, einstufung
from .bewertung.anschreiben import euro, tsd
from .bewertung.kalkulation import stunden_text
from .bearbeitung import IN_ARBEIT
from .domaene import STATUS
from .schalter import eingang_aktiv


def render_html(cfg: dict, zeilen: list[dict], basis: Path, fehler: str | None = None, app: dict | None = None,
                team: dict | None = None) -> tuple[str, dict]:
    """app = {"token": …} im Browser-Modus (python scout.py app), sonst statische Datei.
    team = Antwort von ``/api/team`` (nur mit angelegten Nutzern, sonst None): dann zeigt die Seite Bearbeiter-Badges, Zähler und Filter."""
    env = Environment(loader=FileSystemLoader(str(basis / "vorlagen")), autoescape=True)
    env.filters["euro"] = euro
    env.filters["tsd"] = tsd
    env.filters["stunden"] = stunden_text
    env.filters["prozent"] = lambda x: f"{x:+.1%}".replace(".", ",") if x is not None else "–"
    env.filters["anteil"] = lambda x: f"{x:.0%}" if x is not None else "–"
    zaehl = {
        "gruen": sum(z["b"].ampel == "gruen" and not z.get("ausblenden") for z in zeilen),
        "gelb": sum(z["b"].ampel == "gelb" and not z.get("ausblenden") for z in zeilen),
        "neu": sum(z["neu"] for z in zeilen),
        "neuigkeiten": sum(bool(z.get("neuigkeit")) for z in zeilen),
        "anschreiben": sum(z["bereit"] for z in zeilen),
        "kontaktiert": sum(z["a"].get("status") == "kontaktiert" for z in zeilen),
        "arbeit": sum(z["a"].get("status") in IN_ARBEIT for z in zeilen),
        "nachfassen": sum(bool(z["nachfassen"]) for z in zeilen),
    }
    return env.get_template("report.html").render(
        stand=datetime.now().strftime("%d.%m.%Y %H:%M"), anzahl=len(zeilen), zeilen=zeilen, zaehl=zaehl,
        fehler=fehler, app=app or {}, mails_aktiv=eingang_aktiv(cfg, "email"), team=team if team and team.get("aktiv") else None,
        ust_label="USt auf Marge (§25a, 19/119)" if cfg["rechner"]["differenzbesteuerung"] else "USt 19 % im Händler-VK",
        fair_untergrenze=cfg["rechner"].get("fair_untergrenze_privatwert", 0), status_liste=list(STATUS.items()),
        differenzbesteuerung=bool(cfg["rechner"]["differenzbesteuerung"]),
        signatur={k: cfg["anschreiben"].get(k, "") for k in ("ansprechpartner", "firma", "telefon")}), zaehl


def _team_spalten(t: dict | None) -> list[str]:
    """Bearbeiter, Übernommen am, Kontaktiert von – leer ohne Team oder ohne Zuordnung."""
    if not t:
        return ["", "", ""]
    return [(t["bearbeiter"] or {}).get("name", ""), t["seit"] or "", (t["kontaktiert_von"] or {}).get("name", "")]


def _verfuegbarkeit_zelle(a: dict) -> str:
    """CSV: aktiv, reserviert, offline, verkauft, unbekannt – oder „vermutlich offline“ (abgeleitet, nicht gespeichert)."""
    return "vermutlich offline" if a.get("vermutlich_offline") else a.get("verfuegbarkeit") or "unbekannt"


def _anbieter_zellen(a: dict) -> list[str]:
    """CSV: privat / gewerblich / unbekannt und die Herkunft der Einstufung (P3-05)."""
    e = a.get("anbieter") or einstufung(a.get("gewerblich"), a.get("anbieter_herkunft"))
    return [e["typ"], HERKUNFT_TEXT.get(e["herkunft"], "")]


def _qualitaet_zellen(a: dict) -> list:
    """CSV: Qualitätswert 0–100 und die Markierungen als Text (P3-08)."""
    q = a.get("datenqualitaet")
    return [q["wert"], " | ".join(m["text"] for m in q["markierungen"])] if q else ["", ""]


def schreibe_ausgaben(cfg: dict, zeilen: list[dict], basis: Path, fehler: str | None = None, team=None) -> dict:
    """``team``: ``TeamSicht`` (bearbeitung.py) oder ``None`` – dann bleiben die Team-Spalten der CSV leer."""
    ordner = basis / cfg["ausgabe"]["ordner"]
    (ordner / "anschreiben").mkdir(parents=True, exist_ok=True)

    # --- CSV (für Excel: Semikolon + UTF-8 mit BOM) ---
    csv_pfad = ordner / "anzeigen_bewertet.csv"
    with open(csv_pfad, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Ampel", "Titel", "Marke", "Modell", "Art", "EZ", "km", "Ort", "Entfernung km",
                    "Tage online", "Angebotspreis",
                    "Marktniveau", "Spanne von", "Spanne bis", "Sicherheit", "Anz. Vergleiche", "Marktwert privat",
                    "Händler-VK", "Kosten", "Ziel-Marge", "Max-EK", "Erstangebot", "Erstangebot % Marktwert",
                    "Gewinn bei Angebotspreis", "Wertfaktoren", "Sperrgrund", "Hinweise", "Status", "Nachfassen", "Kontaktiert am",
                    "Verfügbarkeit", "Zuletzt bestätigt", "Anbieter", "Anbieter-Herkunft", "Datenqualität", "Datenmarkierungen",
                    "Neuigkeit", "Erstmals gesehen", "URL", "Bearbeiter", "Übernommen am", "Kontaktiert von"])
        for z in sorted(zeilen, key=lambda z: z["b"].verhaeltnis or 99):
            a, b = z["a"], z["b"]
            t = team.objekt(z) if team else None
            # P1-12: ohne Marktwert (Erstzulassung fehlt) keine Beträge – leere Zellen statt 0 €
            betraege = ["", "", "", "", "", "", ""] if b.sicherheit == "keine" else \
                [b.marktwert_privat, b.haendler_vk, b.kosten, b.ziel_marge, b.max_ek, b.erstangebot, b.potenzial]
            w.writerow([a["id"], b.ampel, a["titel"], a["marke"], a.get("modell"), b.art, a["ez_jahr"], a["km"],
                        a["ort"], a.get("entfernung_km"), a.get("tage_online"), a["preis"], b.marktwert_angebote, b.spanne_von, b.spanne_bis, b.sicherheit,
                        b.vergleich_anzahl, *betraege[:6], f"{b.fair_anteil:.0%}" if b.fair_anteil else "", betraege[6],
                        ", ".join(f"{n} {w:+.1%}" for n, w in b.wertfaktoren.items()), z["sperre"] or "",
                        " | ".join(z.get("hinweise") or []), a["status"], z["nachfassen"] or "", a.get("kontaktiert_am") or "",
                        _verfuegbarkeit_zelle(a), a.get("zuletzt_bestaetigt") or "", *_anbieter_zellen(a), *_qualitaet_zellen(a),
                        (z.get("neuigkeit") or {}).get("text", ""), a["erstmals_gesehen"], a["url"],
                        *_team_spalten(t)])

    # --- Anschreiben als Textdateien ---
    for z in zeilen:
        if z["bereit"]:
            hinweis = "".join(f"Hinweis (nicht Teil des Briefs): {h}\n" for h in z.get("hinweise") or [])
            (ordner / "anschreiben" / f"{z['a']['id']}.txt").write_text(
                f"{z['a']['url']}\n{hinweis}\n{z['brief']}\n", encoding="utf-8")

    # --- HTML-Report ---
    html, zaehl = render_html(cfg, zeilen, basis, fehler=fehler)
    html_pfad = ordner / "report.html"
    html_pfad.write_text(html, encoding="utf-8")
    return {"html": html_pfad, "csv": csv_pfad, "zaehl": zaehl}
