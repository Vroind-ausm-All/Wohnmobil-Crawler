"""Benachrichtigungen über neue Treffer (derzeit E-Mail; weitere Kanäle folgen hier)."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

from .bewertung.anschreiben import euro

log = logging.getLogger("scout")


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
