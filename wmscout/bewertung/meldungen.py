"""Meldungen im Dashboard (P6-04, ADR-064): was jetzt Aufmerksamkeit braucht – Antwort des Verkäufers liegt vor (unsere Rückmeldung fällig),
Besichtigung heute/morgen, Nachfassen fällig, Preis deutlich gesenkt, neu und passend. Gebildet aus den bewerteten Zeilen, rein und ohne
Datenbank. Jede Meldung trägt einen festen Zeitpunkt (``zeit``), damit die Oberfläche „ungelesen“ je Gerät merken kann; versendet wird nichts.
"""
from __future__ import annotations

from datetime import datetime, timedelta

ANTWORT, ANFRAGE, BESICHTIGUNG, NACHFASSEN, PREIS, NEU = "antwort", "anfrage", "besichtigung", "nachfassen", "preis", "neu"
ARTEN = {ANTWORT: "Antwort fällig", ANFRAGE: "Verkaufsanfrage", BESICHTIGUNG: "Besichtigung", NACHFASSEN: "Nachfassen", PREIS: "Preis gesenkt",
         NEU: "Neu"}
ANFRAGE_DRINGEND_STUNDEN = 24   # eine eingegangene Verkaufsanfrage, die so lange niemand angesehen hat, ist dringend (P7-02)
RANG = {a: i for i, a in enumerate(ARTEN)}
ANTWORT_DRINGEND_STUNDEN = 24   # so lange darf eine Antwort des Verkäufers liegen, dann ist sie dringend
MAX = 100


def _zeit(iso: str | None) -> datetime | None:
    """Gespeicherte Zeit als naive Ortszeit; mit Zeitzone (z. B. ein Termin „…+01:00“) umgerechnet – ein solcher Wert legte sonst das ganze
    Dashboard lahm (QA B1). Nicht lesbar: None."""
    try:
        t = datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t and t.tzinfo else t


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _datum(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}."


def _meldung(z: dict, art: str, text: str, zeit: str, dringend: bool) -> dict:
    a = z["a"]
    return {"art": art, "art_text": ARTEN[art], "id": a["id"], "fahrzeug": a.get("fahrzeug"), "quelle": a.get("quelle") or "kleinanzeigen",
            "text": text, "zeit": zeit, "dringend": dringend, "_gruppe": {a["id"], *z.get("dubletten_ids", ())}}


def _anfrage(v: dict, jetzt: datetime) -> dict:
    """Eingegangene Verkaufsanfrage (P7-02): nur Fahrzeugangaben und Referenz – kein Name, keine Kontaktdaten."""
    seit = _zeit(v.get("erstellt_am"))
    stunden = (jetzt - seit).total_seconds() / 3600 if seit else 0
    teile = [f"EZ {v['ez_jahr']}" if v.get("ez_jahr") else None, f"{v['km']:,} km".replace(",", ".") if v.get("km") is not None else None,
             f"Preisvorstellung {v['preisvorstellung']:,} €".replace(",", ".") if v.get("preisvorstellung") else None]
    text = " · ".join(t for t in teile if t) or "ohne Fahrzeugangaben"
    if stunden >= ANFRAGE_DRINGEND_STUNDEN:
        text += f" – unbearbeitet seit {int(stunden // 24)} {'Tag' if stunden < 48 else 'Tagen'}"
    return {"art": ANFRAGE, "art_text": ARTEN[ANFRAGE], "id": f"anfrage-{v['id']}", "fahrzeug": " ".join(x for x in (v.get("marke"), v.get("modell")) if x)
            or "Wohnmobil", "quelle": "anfrage", "text": f"{v.get('referenz') or ''} {text}".strip(), "zeit": (v.get("erstellt_am") or "")[:19],
            "dringend": stunden >= ANFRAGE_DRINGEND_STUNDEN, "link": f"/anfragen#{v['id']}", "_gruppe": {f"anfrage-{v['id']}"}}


def meldungen(zeilen: list[dict], jetzt: datetime, cfg: dict | None = None, anfragen: list[dict] | None = None) -> list[dict]:
    """[{art, art_text, id, fahrzeug, quelle, text, zeit, dringend}] – dringende zuerst, dann nach Art und jüngste zuerst; höchstens ``MAX``.
    Je Art und Fahrzeug (Inserat mit seinen Dubletten) eine Meldung: die wichtigere bzw. jüngere. ``anfragen``: eingegangene
    Verkaufsanfragen (P7-02) – je eine Meldung mit ``link`` zur Anfragenseite; nur übergeben, wer Anfragen sehen darf."""
    nach_tagen = ((cfg or {}).get("nachfassen") or {}).get("nach_tagen", 3)
    morgen_ende = (jetzt + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    erg: list[dict] = []
    for z in zeilen:
        a, k, n = z["a"], z.get("kontakt") or {}, z.get("neuigkeit") or {}

        def m(art: str, text: str, zeit: str, dringend: bool = False, z=z):
            erg.append(_meldung(z, art, text, zeit, dringend))
        notiz_danach = bool(k.get("notiz") and k.get("antwort") and k["notiz"]["zeitpunkt"] >= k["antwort"]["zeitpunkt"])
        if k.get("stufe") == "antwort" and k.get("antwort") and not notiz_danach:        # eine Notiz danach erledigt die Rückmeldung (QA B4)
            seit = _zeit(k["antwort"]["zeitpunkt"])
            stunden = (jetzt - seit).total_seconds() / 3600 if seit else 0
            m(ANTWORT, f"{k['text']} – Rückmeldung offen" + (f" seit {int(stunden // 24)} {'Tag' if stunden < 48 else 'Tagen'}" if stunden >= 24 else ""),
              k["antwort"]["zeitpunkt"], stunden >= ANTWORT_DRINGEND_STUNDEN)
        bes = k.get("besichtigung") or {}
        termin = _zeit(bes.get("termin"))
        if k.get("stufe") == "besichtigung" and termin and jetzt - timedelta(hours=2) <= termin < morgen_ende and termin.date() >= jetzt.date():
            tag = "heute" if termin.date() == jetzt.date() else "morgen"
            m(BESICHTIGUNG, f"Besichtigung {tag} {termin:%H:%M} Uhr", _iso(termin - timedelta(days=1)), tag == "heute")
        if z.get("nachfassen") and k.get("stufe") != "antwort":
            kontakt = _zeit(k.get("kontakt_am") or a.get("kontaktiert_am"))
            if str(z["nachfassen"]).startswith("Preis gesenkt") and a.get("preis_geaendert_am"):
                zeit = a["preis_geaendert_am"][:19]                                  # Anlass ist die Senkung, nicht die Wartezeit
            else:
                zeit = _iso(kontakt + timedelta(days=nach_tagen)) if kontakt else _iso(jetzt.replace(hour=0, minute=0, second=0, microsecond=0))
            m(NACHFASSEN, f"Nachfassen: {z['nachfassen']}", zeit)
        s = n.get("senkung")
        if s:
            m(PREIS, f"{s['von']:,} € → {s['auf']:,} € (−{s['euro']:,} €)".replace(",", ".") + (" – jetzt im Rahmen" if n.get("im_rahmen") else ""),
              s["am"], bool(n.get("im_rahmen")))
        top = bool((z.get("deal") or {}).get("priorisiert"))
        if n.get("frisch") and (z.get("bereit") or top) and a.get("erstmals_gesehen"):
            m(NEU, ("Top-Deal" if top else "Anschreiben bereit") + f" – seit {_datum(a['erstmals_gesehen'])} online", a["erstmals_gesehen"], top)
    erg += [_anfrage(v, jetzt) for v in anfragen or () if v.get("status") == "eingegangen"]
    erg.sort(key=lambda x: x["zeit"] or "", reverse=True)                     # jüngste zuerst …
    erg.sort(key=lambda x: (not x["dringend"], RANG[x["art"]]))               # … innerhalb von Dringlichkeit und Art (stabil)
    ergebnis, gesehen = [], {art: set() for art in ARTEN}
    for x in erg:
        gruppe = x.pop("_gruppe")
        if gruppe & gesehen[x["art"]]:
            continue
        gesehen[x["art"]] |= gruppe
        ergebnis.append(x)
    return ergebnis[:MAX]
