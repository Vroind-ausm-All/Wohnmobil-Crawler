"""Bewertet alle aktiven Anzeigen und schreibt HTML-Report, CSV und Anschreiben-Dateien."""
from __future__ import annotations

import csv
import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .anschreiben import Anschreiber, euro, sperrgrund, tsd
from .db import Datenbank
from .fahrzeug import ergaenze_fahrzeug
from .rechner import Rechner

log = logging.getLogger("scout")


def bewerte_alle(cfg: dict, db: Datenbank, basis: Path, lauf_start: str | None = None) -> list[dict]:
    rechner, schreiber = Rechner(cfg), Anschreiber(cfg, basis)
    vergleich = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    zeilen = []
    for r in db.aktive():
        a = ergaenze_fahrzeug(dict(r))
        if a.get("status") == "gelöscht":
            continue
        b = rechner.bewerte(a, vergleich)
        sperre = sperrgrund(a, cfg)
        # Text gibt es für jede nicht gesperrte Anzeige; „bereit“ sind nur die, deren Ampel passt
        brief = schreiber.text(a, b) if not sperre else None
        if cfg["rechner"]["differenzbesteuerung"]:
            ust = (b.haendler_vk - b.max_ek) * 19 / 119
        else:
            ust = b.haendler_vk - b.haendler_vk / 1.19
        zeilen.append({
            "a": a, "b": b, "sperre": sperre, "brief": brief, "ust": round(ust / 10) * 10,
            "bereit": bool(brief) and schreiber.soll_schreiben(b.ampel),
            "neu": bool(lauf_start and (a.get("erstmals_gesehen") or "") >= lauf_start),
        })
    return zeilen


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
    }
    return env.get_template("report.html").render(
        stand=datetime.now().strftime("%d.%m.%Y %H:%M"), anzahl=len(zeilen), zeilen=zeilen, zaehl=zaehl,
        fehler=fehler, app=app or {},
        ust_label="USt auf Marge (§25a, 19/119)" if cfg["rechner"]["differenzbesteuerung"] else "USt 19 % im Händler-VK",
        fair_untergrenze=cfg["rechner"].get("fair_untergrenze_privatwert", 0)), zaehl


def schreibe_ausgaben(cfg: dict, zeilen: list[dict], basis: Path, fehler: str | None = None) -> dict:
    ordner = basis / cfg["ausgabe"]["ordner"]
    (ordner / "anschreiben").mkdir(parents=True, exist_ok=True)

    # --- CSV (für Excel: Semikolon + UTF-8 mit BOM) ---
    csv_pfad = ordner / "anzeigen_bewertet.csv"
    with open(csv_pfad, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Ampel", "Titel", "Marke", "Modell", "Art", "EZ", "km", "Ort", "Angebotspreis",
                    "Marktniveau", "Spanne von", "Spanne bis", "Sicherheit", "Anz. Vergleiche", "Marktwert privat",
                    "Händler-VK", "Kosten", "Ziel-Marge", "Max-EK", "Erstangebot", "Erstangebot % Marktwert",
                    "Gewinn bei Angebotspreis", "Wertfaktoren", "Sperrgrund", "Status", "Kontaktiert am",
                    "Erstmals gesehen", "URL"])
        for z in sorted(zeilen, key=lambda z: z["b"].verhaeltnis or 99):
            a, b = z["a"], z["b"]
            w.writerow([a["id"], b.ampel, a["titel"], a["marke"], a.get("modell"), b.art, a["ez_jahr"], a["km"],
                        a["ort"], a["preis"], b.marktwert_angebote, b.spanne_von, b.spanne_bis, b.sicherheit,
                        b.vergleich_anzahl, b.marktwert_privat, b.haendler_vk, b.kosten, b.ziel_marge, b.max_ek,
                        b.erstangebot, f"{b.fair_anteil:.0%}" if b.fair_anteil else "", b.potenzial,
                        ", ".join(f"{n} {w:+.1%}" for n, w in b.wertfaktoren.items()), z["sperre"] or "",
                        a["status"], a.get("kontaktiert_am") or "", a["erstmals_gesehen"], a["url"]])

    # --- Anschreiben als Textdateien ---
    for z in zeilen:
        if z["bereit"]:
            (ordner / "anschreiben" / f"{z['a']['id']}.txt").write_text(
                f"{z['a']['url']}\n\n{z['brief']}\n", encoding="utf-8")

    # --- HTML-Report ---
    html, zaehl = render_html(cfg, zeilen, basis, fehler=fehler)
    html_pfad = ordner / "report.html"
    html_pfad.write_text(html, encoding="utf-8")
    return {"html": html_pfad, "csv": csv_pfad, "zaehl": zaehl}


def sende_mail(cfg: dict, zeilen: list[dict], ergebnis: dict):
    m = cfg["email"]
    if not m.get("aktiv"):
        return
    treffer = [z for z in zeilen if z["bereit"] and (z["neu"] or not m.get("nur_bei_neuen_treffern"))]
    if m.get("nur_bei_neuen_treffern") and not treffer:
        log.info("Keine neuen Treffer – keine Mail.")
        return
    passwort = os.environ.get(m["passwort_env"])
    if not passwort:
        log.warning("Umgebungsvariable %s fehlt – Mail wird nicht gesendet.", m["passwort_env"])
        return
    treffer.sort(key=lambda z: z["b"].verhaeltnis or 99)
    zeilen_txt = "\n".join(
        f"[{z['b'].ampel.upper():5}] {z['a']['fahrzeug']} · EZ {z['a']['ez_jahr'] or '?'} – {z['a']['ort']}\n"
        f"        Angebot {euro(z['a']['preis'])} · Max-EK {euro(z['b'].max_ek)} · Erstangebot {euro(z['b'].erstangebot)}\n"
        f"        {z['a']['url']}" for z in treffer[:25])
    msg = EmailMessage()
    msg["Subject"] = f"Wohnmobil-Scout: {len(treffer)} neue Treffer"
    msg["From"], msg["To"] = m["benutzer"], m["empfaenger"]
    msg.set_content(f"{len(treffer)} Anzeigen mit fertigem Anschreiben:\n\n{zeilen_txt}\n\n"
                    f"Report im Anhang (im Browser öffnen) – oder „python scout.py app“ starten.")
    msg.add_attachment(ergebnis["html"].read_bytes(), maintype="text", subtype="html", filename="report.html")
    with smtplib.SMTP(m["smtp_server"], m["smtp_port"], timeout=30) as s:
        s.starttls()
        s.login(m["benutzer"], passwort)
        s.send_message(msg)
    log.info("Mail an %s gesendet.", m["empfaenger"])
