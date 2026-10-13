"""Bewertet alle aktiven Anzeigen und schreibt HTML-Report, CSV und Anschreiben-Dateien."""
from __future__ import annotations

import csv
import logging
import os
import smtplib
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .anschreiben import Anschreiber, euro, sperrgrund, tsd
from .db import STATUS, Datenbank
from .fahrzeug import ergaenze_fahrzeug
from .geo import entfernung_km
from .rechner import Rechner

log = logging.getLogger("scout")


BEARBEITET = {"kontaktiert", "verhandlung", "besichtigung", "gekauft", "abgesagt", "uninteressant"}


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
    rechner, schreiber = Rechner(cfg), Anschreiber(cfg, basis)
    jetzt = datetime.now()
    standort = str(cfg["anschreiben"].get("plz") or "") or None
    alle = [ergaenze_fahrzeug(dict(r)) for r in db.alle_mit_preis()]
    duplikate = finde_duplikate(alle)
    # Vergleichsbasis: von mehrfach eingestellten Fahrzeugen nur die aktuellste Anzeige
    vergleich = [a for a in alle if not any((b.get("zuletzt_gesehen") or "", b["id"]) > (a.get("zuletzt_gesehen") or "", a["id"])
                                            for b in duplikate.get(a["id"], []))]
    zeilen = []
    for r in db.aktive():
        a = ergaenze_fahrzeug(dict(r))
        if a.get("status") == "gelöscht":
            continue
        a["entfernung_km"] = entfernung_km(standort, a.get("plz"))
        andere = duplikate.get(a["id"], [])
        seit = min([a.get("erstmals_gesehen") or jetzt.isoformat()] + [b.get("erstmals_gesehen") or "9" for b in andere])
        a["tage_online"] = max(0, (jetzt - datetime.fromisoformat(seit)).days)
        a["neu_eingestellt"] = any((b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "") for b in andere)
        bearbeitet = [b for b in andere if b.get("status") in BEARBEITET]
        live_aelter = [b for b in andere if b.get("status") in (None, "neu")
                       and (b.get("erstmals_gesehen") or "") < (a.get("erstmals_gesehen") or "")
                       and (b.get("zuletzt_gesehen") or "") >= (a.get("zuletzt_gesehen") or "")[:10]]
        if bearbeitet:
            b0 = bearbeitet[0]
            a["duplikat"] = (f"gleiches Fahrzeug schon bearbeitet: Anzeige {b0['id']} "
                             f"({STATUS.get(b0['status'], b0['status'])} am {_datum(b0.get('status_am') or b0.get('kontaktiert_am'))})")
        elif live_aelter:
            a["duplikat"] = f"doppelt eingestellt – ältere Anzeige {live_aelter[0]['id']} ist noch online"
        b = rechner.bewerte(a, vergleich)
        sperre = sperrgrund(a, cfg)
        # Text gibt es für jede nicht gesperrte Anzeige; „bereit“ sind nur die, deren Ampel passt
        brief = schreiber.text(a, b) if not sperre else None
        grund = nachfass_grund(a, cfg, jetzt)
        nachfass_text, nachfass_betrag = schreiber.nachfass(a, b) if grund else (None, None)
        if cfg["rechner"]["differenzbesteuerung"]:
            ust = (b.haendler_vk - b.max_ek) * 19 / 119
        else:
            ust = b.haendler_vk - b.haendler_vk / 1.19
        zeilen.append({
            "a": a, "b": b, "sperre": sperre, "brief": brief, "ust": round(ust / 10) * 10,
            "bereit": bool(brief) and schreiber.soll_schreiben(b.ampel),
            "neu": bool(lauf_start and (a.get("erstmals_gesehen") or "") >= lauf_start),
            "nachfassen": grund, "nachfass_text": nachfass_text, "nachfass_betrag": nachfass_betrag,
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


def schreibe_ausgaben(cfg: dict, zeilen: list[dict], basis: Path, fehler: str | None = None) -> dict:
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
                    "Gewinn bei Angebotspreis", "Wertfaktoren", "Sperrgrund", "Status", "Nachfassen", "Kontaktiert am",
                    "Erstmals gesehen", "URL"])
        for z in sorted(zeilen, key=lambda z: z["b"].verhaeltnis or 99):
            a, b = z["a"], z["b"]
            w.writerow([a["id"], b.ampel, a["titel"], a["marke"], a.get("modell"), b.art, a["ez_jahr"], a["km"],
                        a["ort"], a.get("entfernung_km"), a.get("tage_online"), a["preis"], b.marktwert_angebote, b.spanne_von, b.spanne_bis, b.sicherheit,
                        b.vergleich_anzahl, b.marktwert_privat, b.haendler_vk, b.kosten, b.ziel_marge, b.max_ek,
                        b.erstangebot, f"{b.fair_anteil:.0%}" if b.fair_anteil else "", b.potenzial,
                        ", ".join(f"{n} {w:+.1%}" for n, w in b.wertfaktoren.items()), z["sperre"] or "",
                        a["status"], z["nachfassen"] or "", a.get("kontaktiert_am") or "", a["erstmals_gesehen"], a["url"]])

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
