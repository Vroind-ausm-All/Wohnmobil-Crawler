"""Verhandlung im Dashboard (P6-03, ADR-063): Antworten des Verkäufers und Verhandlungsnotizen als Einträge (Tabelle ``verhandlung``, v23) und
die **Kontaktlage** je Inserat – Text kopiert, kontaktiert und wartet, Antwort erhalten, Besichtigung –, gebildet aus Kontakten (P3-06),
Einträgen und Besichtigungen.

Erfasst wird von Hand (das Team trägt ein, was der Verkäufer geantwortet hat); nichts wird automatisch gesendet oder gelesen. Ein Eintrag ändert
keinen Status. Texte können Personendaten enthalten: Anonymisierung und Fristen (``datenrechte``) leeren sie wie die Team-Notiz.
Die Prüf- und Anzeigefunktionen sind rein; die Datenbankfunktionen bekommen die Verbindung (kein Import von ``sqlite3``/``datenbank``).
"""
from __future__ import annotations

from datetime import datetime

from .kontakte import KANAELE

ANTWORT, NOTIZ = "antwort", "notiz"
ARTEN = {ANTWORT: "Antwort des Verkäufers", NOTIZ: "Notiz"}
TEXT_MAX = 2000
BETRAG_MAX = 10_000_000
# Kontaktlage, wichtigste zuerst (Dashboard-Reihenfolge)
BESICHTIGUNG, ANTWORT_DA, WARTET, VORBEREITET = "besichtigung", "antwort", "wartet", "vorbereitet"
STUFEN = {BESICHTIGUNG: "Besichtigung", ANTWORT_DA: "Antwort erhalten", WARTET: "wartet auf Antwort", VORBEREITET: "Text kopiert"}
REIHENFOLGE = {s: i for i, s in enumerate(STUFEN)}
ERLEDIGT = ("abgesagt", "uninteressant", "gekauft")   # Vorgang beendet: keine Stufe mehr (außer einer noch offenen Besichtigung, QA B1)


def pruefe(daten: dict) -> dict:
    """Eingabe für einen Eintrag: ``art`` (antwort|notiz), ``text`` (Pflicht, gekürzt auf 2.000 Zeichen), ``betrag`` (optional, ganze Euro,
    z. B. die Preisvorstellung des Verkäufers), ``kanal`` (optional, nur bei Antworten). ``ValueError`` mit verständlicher Meldung."""
    art = daten.get("art")
    if art not in ARTEN:
        raise ValueError("art muss antwort oder notiz sein")
    text = daten.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text fehlt")
    betrag = daten.get("betrag")
    if betrag in (None, ""):
        betrag = None
    elif isinstance(betrag, bool) or not isinstance(betrag, (int, float)) or betrag != betrag or not 0 < betrag <= BETRAG_MAX:
        raise ValueError(f"betrag muss eine Zahl zwischen 1 und {BETRAG_MAX:,} € sein".replace(",", "."))
    kanal = daten.get("kanal") or None
    if kanal is not None and (art != ANTWORT or kanal not in KANAELE):
        raise ValueError(f"kanal nur bei Antworten, einer von {', '.join(KANAELE)}")
    return {"art": art, "text": text.strip()[:TEXT_MAX], "betrag": None if betrag is None else round(betrag), "kanal": kanal}


def kurz(k: dict | None) -> dict | None:
    """Kontaktlage für Listen (API ``/api/fahrzeuge``, Gerätespeicher der Handy-App): ohne Volltexte der Einträge – die stehen nur im Detail
    (Datenminimierung, QA B3)."""
    if not k:
        return None
    return {"stufe": k["stufe"], "text": k["text"], "tage": k["tage"], "kontakt_am": k["kontakt_am"], "besichtigung": k["besichtigung"],
            "eintraege": k["eintraege"], "antwort_betrag": (k.get("antwort") or {}).get("betrag")}


def _datum(iso: str | None) -> str | None:
    return f"{iso[8:10]}.{iso[5:7]}." if iso and len(iso) >= 10 else None


def als_json(z, namen: dict[int, str] | None = None) -> dict:
    """Anzeigeform eines Eintrags; ``namen``: Nutzer-ID → Name (Team)."""
    return {"id": z["id"], "anzeige_id": z["anzeige_id"], "art": z["art"], "art_text": ARTEN.get(z["art"], z["art"]), "zeitpunkt": z["zeitpunkt"],
            "zeit_text": f"{_datum(z['zeitpunkt'])}{z['zeitpunkt'][:4]} {z['zeitpunkt'][11:16]}".rstrip() if z["zeitpunkt"] else None,
            "betrag": z["betrag"], "kanal": z["kanal"], "kanal_text": KANAELE.get(z["kanal"]) if z["kanal"] else None, "text": z["text"],
            "von": (namen or {}).get(z["nutzer_id"])}


def zustand(status: str | None, lage: dict | None, jetzt: datetime) -> dict | None:
    """Kontaktlage eines Inserats aus ``lage`` (siehe ``lage``): ``stufe`` (besichtigung, antwort, wartet, vorbereitet), ``text`` für Karte und
    Dashboard, ``tage`` (seit dem letzten gesendeten Kontakt), ``antwort``/``notiz`` (letzter Eintrag) und ``besichtigung``. None ohne Kontakt,
    Eintrag oder Besichtigung. Eine Antwort zählt nur, wenn sie nach dem letzten gesendeten Kontakt kam; danach wartet man wieder. Abgesagte,
    uninteressante und gekaufte Inserate bekommen keine Stufe – sie stehen nicht mehr unter „Ankauf in Arbeit“."""
    if not lage:
        return None
    kontakt, antwort, bes = lage.get("kontakt_am"), lage.get("antwort"), lage.get("besichtigung")
    tage = max(0, (jetzt - datetime.fromisoformat(kontakt[:19])).days) if kontakt else None
    erg = {"stufe": None, "text": None, "tage": tage, "kontakt_am": kontakt, "antwort": antwort, "notiz": lage.get("notiz"),
           "eintraege": lage.get("eintraege", 0), "besichtigung": bes}
    if status in ERLEDIGT and not (bes and bes["status"] in ("geplant", "laeuft")):
        pass
    elif bes and bes["status"] in ("geplant", "laeuft"):
        erg["stufe"] = BESICHTIGUNG
        erg["text"] = "Besichtigung läuft" if bes["status"] == "laeuft" else \
            ("Besichtigung " + (f"am {_datum(bes['termin'])} {bes['termin'][11:16]}".rstrip() if bes.get("termin") else "geplant, ohne Termin"))
    elif antwort and (not kontakt or antwort["zeitpunkt"] >= kontakt):
        erg["stufe"] = ANTWORT_DA
        erg["text"] = f"Antwort am {_datum(antwort['zeitpunkt'])}" + (f" – nennt {antwort['betrag']:,} €".replace(",", ".") if antwort.get("betrag") else "")
    elif kontakt:
        erg["stufe"] = WARTET
        erg["text"] = f"kontaktiert am {_datum(kontakt)} – " + ("heute" if not tage else f"seit {tage} {'Tag' if tage == 1 else 'Tagen'} keine Antwort")
    elif lage.get("vorbereitet") or status == "vorbereitet":
        erg["stufe"] = VORBEREITET
        erg["text"] = "Text kopiert – noch nicht als gesendet bestätigt"
    if erg["stufe"] is None and not lage.get("notiz") and not bes:
        return None
    return erg


# ---------------------------------------------------------------- Datenbank (Verbindung von außen)
def eintragen(db, anzeige_id: str, eingabe: dict, nutzer_id: int | None, jetzt: datetime | None = None) -> int:
    """Eintrag anfügen (``eingabe`` aus ``pruefe``); ``LookupError``, wenn es das Inserat nicht gibt."""
    zeit = (jetzt or datetime.now()).isoformat(timespec="seconds")
    with db.transaktion():
        if not db.con.execute("SELECT 1 FROM anzeigen WHERE id=?", (anzeige_id,)).fetchone():
            raise LookupError(f"Inserat {anzeige_id} unbekannt")
        return db.con.execute("INSERT INTO verhandlung (anzeige_id, art, zeitpunkt, nutzer_id, kanal, betrag, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (anzeige_id, eingabe["art"], zeit, nutzer_id, eingabe["kanal"], eingabe["betrag"], eingabe["text"])).lastrowid


def verlauf(db, anzeige_id: str) -> list:
    """Einträge der Anzeige und aller Inserate desselben Fahrzeugs (bestätigte Dubletten, wie ``kontakte_zu``), älteste zuerst."""
    ids = {anzeige_id}
    fid = db.fahrzeug_id_zu(anzeige_id)
    if fid is not None:
        ids |= {r[0] for r in db.con.execute("SELECT anzeigen_id FROM inserate WHERE fahrzeug_id=?", (fid,))}
    return db.con.execute(f"SELECT * FROM verhandlung WHERE anzeige_id IN ({','.join('?' * len(ids))}) ORDER BY zeitpunkt, id",
                          sorted(ids)).fetchall()


def lage(db) -> dict[str, dict]:
    """Für alle Inserate mit Kontakt, Eintrag oder Besichtigung in wenigen Abfragen: ``kontakt_am`` (letzter gesendeter Kontakt), ``vorbereitet``
    (offenes „Text kopiert“), ``antwort``/``notiz`` (letzter Eintrag je Art: zeitpunkt, betrag, text), ``eintraege`` und ``besichtigung``
    (offene mit frühestem Termin, sonst die zuletzt geänderte: status, termin)."""
    erg: dict[str, dict] = {}

    def zu(i):
        return erg.setdefault(i, {})
    for r in db.con.execute("SELECT anzeige_id, MAX(bestaetigt_am) AS am, "
                            "SUM(bestaetigt_am IS NULL AND verworfen_am IS NULL) AS offen FROM kontakte GROUP BY anzeige_id"):
        zu(r["anzeige_id"]).update(kontakt_am=r["am"], vorbereitet=bool(r["offen"]))
    for r in db.con.execute("SELECT v.* FROM verhandlung v JOIN (SELECT anzeige_id, art, MAX(id) AS id FROM verhandlung GROUP BY anzeige_id, art) l "
                            "ON l.id = v.id"):
        zu(r["anzeige_id"])[r["art"]] = {"zeitpunkt": r["zeitpunkt"], "betrag": r["betrag"], "text": r["text"]}
    for r in db.con.execute("SELECT anzeige_id, COUNT(*) AS n FROM verhandlung GROUP BY anzeige_id"):
        zu(r["anzeige_id"])["eintraege"] = r["n"]
    for r in db.con.execute("SELECT anzeige_id, status, termin, geaendert_am, id FROM besichtigungen WHERE anzeige_id IS NOT NULL "
                            "ORDER BY status NOT IN ('geplant', 'laeuft'), CASE WHEN status IN ('geplant', 'laeuft') THEN COALESCE(termin, '9') END, "
                            "COALESCE(geaendert_am, erstellt_am, '') DESC, id DESC"):
        zu(r["anzeige_id"]).setdefault("besichtigung", {"status": r["status"], "termin": r["termin"]})
    return erg
