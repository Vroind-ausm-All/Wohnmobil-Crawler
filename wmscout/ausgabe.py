"""Ausgaben: HTML-Report (auch Seite der Browser-App), CSV für Excel und Anschreiben als Textdateien."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .bewertung.anschreiben import euro, tsd
from .datenbank import STATUS


def render_html(cfg: dict, zeilen: list[dict], basis: Path, fehler: str | None = None, app: dict | None = None) -> str:
    """app = {"token": …} im Browser-Modus (python scout.py app), sonst statische Datei."""
    env = Environment(loader=FileSystemLoader(str(basis / "vorlagen")), autoescape=True)
    env.filters["euro"] = euro
    env.filters["tsd"] = tsd
    env.filters["prozent"] = lambda x: f"{x:+.1%}".replace(".", ",") if x is not None else "–"
    env.filters["anteil"] = lambda x: f"{x:.0%}" if x is not None else "–"
    zaehl = {
        "gruen": sum(z["b"].ampel == "gruen" for z in zeilen),
        "gelb": sum(z["b"].ampel == "gelb" for z in zeilen),
        "neu": sum(z["neu"] for z in zeilen),
        "anschreiben": sum(z["bereit"] for z in zeilen),
        "kontaktiert": sum(z["a"].get("status") == "kontaktiert" for z in zeilen),
        "arbeit": sum(z["a"].get("status") in ("kontaktiert", "verhandlung", "besichtigung") for z in zeilen),
        "nachfassen": sum(bool(z["nachfassen"]) for z in zeilen),
    }
    return env.get_template("report.html").render(
        stand=datetime.now().strftime("%d.%m.%Y %H:%M"), anzahl=len(zeilen), zeilen=zeilen, zaehl=zaehl,
        fehler=fehler, app=app or {},
        ust_label="USt auf Marge (§25a, 19/119)" if cfg["rechner"]["differenzbesteuerung"] else "USt 19 % im Händler-VK",
        fair_untergrenze=cfg["rechner"].get("fair_untergrenze_privatwert", 0), status_liste=list(STATUS.items()),
        differenzbesteuerung=bool(cfg["rechner"]["differenzbesteuerung"]),
        signatur={k: cfg["anschreiben"].get(k, "") for k in ("ansprechpartner", "firma", "telefon")}), zaehl


def _team_spalten(t: dict | None) -> list[str]:
    """Bearbeiter, Übernommen am, Kontaktiert von – leer ohne Team oder ohne Zuordnung."""
    if not t:
        return ["", "", ""]
    return [(t["bearbeiter"] or {}).get("name", ""), t["seit"] or "", (t["kontaktiert_von"] or {}).get("name", "")]


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
                    "Erstmals gesehen", "URL", "Bearbeiter", "Übernommen am", "Kontaktiert von"])
        for z in sorted(zeilen, key=lambda z: z["b"].verhaeltnis or 99):
            a, b = z["a"], z["b"]
            t = team.objekt(z) if team else None
            w.writerow([a["id"], b.ampel, a["titel"], a["marke"], a.get("modell"), b.art, a["ez_jahr"], a["km"],
                        a["ort"], a.get("entfernung_km"), a.get("tage_online"), a["preis"], b.marktwert_angebote, b.spanne_von, b.spanne_bis, b.sicherheit,
                        b.vergleich_anzahl, b.marktwert_privat, b.haendler_vk, b.kosten, b.ziel_marge, b.max_ek,
                        b.erstangebot, f"{b.fair_anteil:.0%}" if b.fair_anteil else "", b.potenzial,
                        ", ".join(f"{n} {w:+.1%}" for n, w in b.wertfaktoren.items()), z["sperre"] or "",
                        " | ".join(z.get("hinweise") or []), a["status"], z["nachfassen"] or "", a.get("kontaktiert_am") or "",
                        a["erstmals_gesehen"], a["url"],
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
