"""Benachrichtigungen: E-Mail bei neuen Treffern, WhatsApp (Links zum Teilen und offizielle Cloud API)."""
from __future__ import annotations

import logging
import os
import re
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

import requests

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
        + "".join(f"        Hinweis: {h}\n" for h in z.get("hinweise") or [])
        + f"        {z['a']['url']}" for z in treffer[:25])
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


# ---------------------------------------------------------------- WhatsApp
def whatsapp_nummer(telefon: str | None) -> str | None:
    """„+49 170 1234567“ / „0170-1234567“ → „491701234567“ (internationales Format ohne +)."""
    ziffern = re.sub(r"\D", "", telefon or "")
    if not ziffern:
        return None
    if ziffern.startswith("00"):
        ziffern = ziffern[2:]
    elif ziffern.startswith("0"):
        ziffern = "49" + ziffern[1:]          # deutsche Nummer ohne Ländervorwahl
    return ziffern if 8 <= len(ziffern) <= 15 else None


def whatsapp_link(text: str, telefon: str | None = None) -> str:
    """Link, der WhatsApp mit fertigem Text öffnet – ohne Nummer wählt man den Empfänger selbst."""
    nummer = whatsapp_nummer(telefon)
    return f"https://wa.me/{nummer or ''}?text={quote(text)}"


def _maskiert(nummer: str) -> str:
    """Telefonnummer fürs Protokoll: nur Anfang und Ende (G0)."""
    n = str(nummer or "")
    return n[:4] + "…" + n[-2:] if len(n) > 6 else "…"


class WhatsAppCloud:
    """Versand über die offizielle WhatsApp Business Platform (Cloud API) mit freigegebenen Vorlagen.

    Fehler werden protokolliert und nie weitergereicht – eine Benachrichtigung darf keinen Ablauf stoppen."""

    def __init__(self, cfg: dict, sitzung: requests.Session | None = None):
        self.cfg = cfg.get("whatsapp") or {}
        self.sitzung = sitzung or requests.Session()

    @property
    def bereit(self) -> bool:
        return bool(self.cfg.get("aktiv") and self.cfg.get("phone_number_id")
                    and os.environ.get(self.cfg.get("token_env", "SCOUT_WHATSAPP_TOKEN")))

    def nachricht(self, an: str, vorlage: str, parameter: list[str]) -> dict:
        return {
            "messaging_product": "whatsapp", "to": whatsapp_nummer(an), "type": "template",
            "template": {"name": vorlage, "language": {"code": self.cfg.get("sprache", "de")},
                         "components": [{"type": "body", "parameters": [
                             {"type": "text", "text": str(p)[:1000]} for p in parameter]}]},
        }

    def sende(self, an: str | None, vorlage: str | None, parameter: list[str]) -> bool:
        if not self.bereit or not vorlage or not whatsapp_nummer(an):
            return False
        url = (f"https://graph.facebook.com/{self.cfg.get('api_version', 'v23.0')}/"
               f"{self.cfg['phone_number_id']}/messages")
        token = os.environ[self.cfg.get("token_env", "SCOUT_WHATSAPP_TOKEN")]
        try:
            r = self.sitzung.post(url, json=self.nachricht(an, vorlage, parameter), timeout=20,
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                log.warning("WhatsApp an %s fehlgeschlagen: HTTP %s", _maskiert(an), r.status_code)
                return False
            return True
        except requests.RequestException as e:
            log.warning("WhatsApp an %s fehlgeschlagen: %s", _maskiert(an), type(e).__name__)
            return False

    def neue_treffer(self, zeilen: list[dict]) -> int:
        """Nach einem Suchlauf: bei neuen Treffern mit fertigem Anschreiben alle Empfänger informieren."""
        treffer = sorted((z for z in zeilen if z["neu"] and z["bereit"]), key=lambda z: z["b"].verhaeltnis or 99)
        if not treffer:
            return 0
        bestes = treffer[0]
        text = f"{bestes['a']['fahrzeug']} · {euro(bestes['a']['preis'])} (Erstangebot {euro(bestes['b'].erstangebot)})"
        return sum(self.sende(n, self.cfg.get("vorlage_neue_treffer"), [str(len(treffer)), text])
                   for n in self.cfg.get("empfaenger_treffer") or [])
