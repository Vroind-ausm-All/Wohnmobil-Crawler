"""Ankaufsvorgang (Phase F, ADR-029): nachvollziehbarer Weg vom Gebot bzw. der Besichtigung bis zum Verkauf.

Ein Vorgang entsteht ausschließlich beim Abschluss einer Besichtigung mit „gekauft“ (vereinbarter Preis und beide
Unterschriften im Protokoll) – für Verkaufsanfragen und Inserate gleich. Danach:

    gekauft ──Vertrag bestätigt──▶ (gekauft) ──Übergabe + Zahlung──▶ uebergeben (im Bestand) ──Verkauf──▶ verkauft
       └──Storno (nur Inhaber, nur vor der Übergabe)──▶ storniert

Der Plan (Kalkulation zum Kaufpreis) wird beim Anlegen eingefroren; Ist-Kosten und Verlauf sind nur anfügbar (Korrektur als
Gegenbuchung). Keine automatische Nachricht, keine Zahlung, kein Vertragsschluss durch das Programm (Projektregel 10):
Alles hier dokumentiert, was Menschen getan haben.
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import date, datetime
from pathlib import Path

from . import verkauf as vk
from .bewertung import ergebnis
from .datenbank import Datenbank
from .deal import DealSpeicher
from .team import MAX_FOTO_BYTES, bild_endung, ohne_metadaten

STATUS = {"gekauft": "gekauft – Vertrag/Übergabe offen", "uebergeben": "im Bestand", "verkauft": "verkauft", "storniert": "storniert"}
DOKUMENTARTEN = {"vertrag": "Kaufvertrag (unterschrieben)", "uebergabe": "Übergabe", "sonstiges": "Sonstiges"}


class AnkaufFehler(ValueError):
    """Aktion nicht möglich (Meldung für den Nutzer); ``status`` für die API (400, 404, 409)."""

    def __init__(self, meldung: str, status: int = 409):
        super().__init__(meldung)
        self.status = status


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _datum(wert, name: str, frueheste: str | None = None) -> str:
    try:
        d = date.fromisoformat(str(wert or ""))
    except ValueError as e:
        raise AnkaufFehler(f"{name}: Datum im Format JJJJ-MM-TT angeben", 400) from e
    if d > date.today():
        raise AnkaufFehler(f"{name} liegt in der Zukunft", 400)
    if frueheste and d.isoformat() < frueheste[:10]:
        raise AnkaufFehler(f"{name} liegt vor dem {frueheste[:10]}", 400)
    return d.isoformat()


def _betrag(wert, name: str, null_erlaubt: bool = False) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or not -10_000_000 <= wert <= 10_000_000 or (wert <= 0 and not null_erlaubt):
        raise AnkaufFehler(f"{name} muss ein ganzer Euro-Betrag sein", 400)
    return wert


def dokument_endung(daten: bytes) -> str:
    """Bilder wie bei Fotos, zusätzlich PDF (Scan des Vertrags) – nach Inhalt, nie nach Name oder Typ."""
    if daten[:5] == b"%PDF-":
        return "pdf"
    return bild_endung(daten)


class AnkaufSpeicher:
    def __init__(self, db: Datenbank, cfg: dict, ordner: Path):
        self.db, self.con, self.cfg, self.ordner = db, db.con, cfg, Path(ordner)
        self.deal = DealSpeicher(db, cfg)

    # ---------- Besichtigung einer Verkaufsanfrage ----------
    def zuschlag(self, anfrage_id: int) -> dict | None:
        """Bestätigter Demo-Zuschlag der Anfrage samt Gewinner-Gebot, Standort und dessen Kalkulation (falls vorhanden)."""
        r = self.con.execute(
            "SELECT a.id AS auktion_id, g.id AS gebot_id, g.betrag, g.standort_id, s.name AS standort, a.entschieden_utc, "
            "(SELECT k.id FROM kalkulationen k WHERE k.gebot_id=g.id) AS kalkulation_id FROM auktionen a "
            "JOIN gebote g ON g.id=a.gewinner_gebot_id JOIN standorte s ON s.id=g.standort_id "
            "WHERE a.anfrage_id=? AND a.status='zugeschlagen' ORDER BY a.id DESC LIMIT 1", (anfrage_id,)).fetchone()
        return dict(r) if r else None

    def basis_fuer_anfrage(self, anfrage_id: int) -> dict:
        """Grundlage, die beim Anlegen der Besichtigung eingefroren wird – gleiche Felder wie bei Inseraten (``basis_fuer``),
        dazu Anfrage, Verkäufer (nur für das Team) und ein bestätigter Zuschlag als Angebot."""
        a = vk.VerkaufSpeicher(self.db, self.ordner).lade(anfrage_id)
        if not a:
            raise AnkaufFehler("Anfrage nicht gefunden", 404)
        b = vk.bewerte(self.cfg, a, vk.vergleich_aus(self.db))
        z = self.zuschlag(anfrage_id)
        risiko = sum(v for n, v in b.kosten_posten.items() if n.startswith("Reparaturrisiko"))
        return {"anzeige_id": f"anfrage-{anfrage_id}", "anfrage_id": anfrage_id, "referenz": a["referenz"],
                "fahrzeug": " ".join(x for x in (a["marke"], a["modell"]) if x) or a["referenz"], "titel": a["referenz"], "url": None,
                "ort": " ".join(x for x in (a.get("plz"), a.get("ort")) if x) or None, "ez_jahr": a["ez_jahr"], "km_anzeige": a["km"],
                "preis": a["preisvorstellung"], "art": b.art, "angebot": z["betrag"] if z else b.erstangebot, "max_ek": b.max_ek,
                "marktwert_privat": b.marktwert_privat, "haendler_vk": b.haendler_vk, "reparaturrisiko": risiko,
                "differenzbesteuerung": bool(self.cfg["rechner"]["differenzbesteuerung"]), "zuschlag": z,
                "verkaeufer": {"name": a["name"], "telefon": a.get("telefon"), "email": a.get("email")},
                "eingefroren_am": _jetzt()}

    # ---------- Anlegen (beim Abschluss „gekauft“) ----------
    def _standzeit_tage(self) -> int:
        return int(self.cfg["rechner"]["kosten"].get("standzeit_monate", 3)) * 30

    def plan_vorbereiten(self, b: dict, kaufpreis: int, bewertung=None) -> dict:
        """Vor der Schreibsperre rechnen (liest alle Vergleichsangebote): Plan und – bei Anfragen – die Kalkulation zum Kaufpreis.
        Provision nur, wenn über eine Auktion zugeschlagen wurde; Transport ab dem Standort des Zuschlags."""
        steuer, tage = bool(self.cfg["rechner"]["differenzbesteuerung"]), self._standzeit_tage()
        if b.get("anfrage_id"):
            z = self.zuschlag(b["anfrage_id"])
            cfg = self.cfg if z else {**copy.deepcopy(self.cfg), "kalkulation": {"provision_prozent": 0}}
            deal = DealSpeicher(self.db, cfg)
            e, erg = deal.berechne(b["anfrage_id"], kaufpreis, z["standort_id"] if z else 0)
            return {"herkunft": "anfrage", "zuschlag": z, "kalkulation": (e, erg) if erg.get("moeglich") else None,
                    "plan": None if erg.get("moeglich") else ergebnis.plan_aus_basis(b["basis"], standzeit_tage=tage)}
        plan = (ergebnis.plan_aus_bewertung(bewertung, kaufpreis, standzeit_tage=tage, differenzbesteuerung=steuer) if bewertung
                else ergebnis.plan_aus_basis(b["basis"], standzeit_tage=tage))
        return {"herkunft": "anzeige", "zuschlag": None, "kalkulation": None, "plan": plan}

    def anlegen(self, b: dict, kaufpreis: int, vorbereitet: dict, nutzer_id: int | None) -> int:
        """Nur innerhalb der Abschluss-Transaktion der Besichtigung: Vorgang, Kalkulation zum Kaufpreis und Verlauf – alles oder nichts."""
        with self.db.transaktion():
            z, kalk_id, plan = vorbereitet["zuschlag"], None, vorbereitet["plan"]
            if vorbereitet["kalkulation"]:
                e, erg = vorbereitet["kalkulation"]
                kalk_id = self.deal.speichern(e, erg, anlass="gespeichert", anfrage_id=b["anfrage_id"],
                                              auktion_id=z["auktion_id"] if z else None, standort_id=z["standort_id"] if z else None,
                                              nutzer_id=nutzer_id)
                plan = ergebnis.plan_aus_kalkulation(erg, kalk_id, standzeit_tage=self._standzeit_tage(),
                                                     differenzbesteuerung=bool(self.cfg["rechner"]["differenzbesteuerung"]))
            aid = self.con.execute(
                "INSERT INTO ankaeufe (herkunft, anfrage_id, anzeige_id, besichtigung_id, auktion_id, standort_id, kalkulation_id, kaufpreis, "
                "plan_json, erstellt_am, erstellt_von) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (vorbereitet["herkunft"], b.get("anfrage_id"), None if b.get("anfrage_id") else b["anzeige_id"], b["id"],
                 z["auktion_id"] if z else None, z["standort_id"] if z else None, kalk_id, kaufpreis,
                 json.dumps(plan, ensure_ascii=False), _jetzt(), nutzer_id)).lastrowid
            self.con.execute("UPDATE ankaeufe SET referenz=? WHERE id=?", (f"AK-{date.today().year}-{aid:04d}", aid))
            self._verlauf(aid, nutzer_id, "gekauft", {"kaufpreis": kaufpreis, "besichtigung_id": b["id"], "plan": plan["quelle"]})
        return aid

    # ---------- Schritte ----------
    def _verlauf(self, aid: int, nutzer_id: int | None, ereignis: str, daten: dict | None = None):
        self.con.execute("INSERT INTO ankauf_verlauf (ankauf_id, zeitpunkt, nutzer_id, ereignis, daten_json) VALUES (?,?,?,?,?)",
                         (aid, _jetzt(), nutzer_id, ereignis, json.dumps(daten or {}, ensure_ascii=False)))

    def _vorgang(self, aid: int) -> dict:
        r = self.con.execute("SELECT * FROM ankaeufe WHERE id=?", (aid,)).fetchone()
        if not r:
            raise AnkaufFehler("Ankaufsvorgang nicht gefunden", 404)
        return dict(r)

    def vertrag_bestaetigen(self, aid: int, nutzer_id: int | None):
        """Ein Mensch bestätigt, dass der Kaufvertrag unterschrieben vorliegt (Muster oder eigener Vertrag)."""
        with self.db.transaktion():
            a = self._vorgang(aid)
            if a["status"] != "gekauft" or a["vertrag_am"]:
                raise AnkaufFehler("Vertrag ist bereits bestätigt oder der Vorgang ist nicht mehr offen")
            self.con.execute("UPDATE ankaeufe SET vertrag_am=?, vertrag_von=? WHERE id=?", (_jetzt(), nutzer_id, aid))
            self._verlauf(aid, nutzer_id, "vertrag")

    def uebergabe(self, aid: int, uebergabe_am, zahlung_am, km, nutzer_id: int | None):
        with self.db.transaktion():
            a = self._vorgang(aid)
            if a["status"] != "gekauft":
                raise AnkaufFehler("Übergabe nur für gekaufte, noch nicht übergebene Fahrzeuge")
            if not a["vertrag_am"]:
                raise AnkaufFehler("Erst den unterschriebenen Kaufvertrag bestätigen")
            ueb = _datum(uebergabe_am, "Übergabe", a["erstellt_am"])
            zahl = _datum(zahlung_am, "Zahlung", a["erstellt_am"])
            km = None if km in (None, "") else _betrag(km, "km-Stand", null_erlaubt=True)
            if km is not None and km < 0:
                raise AnkaufFehler("km-Stand darf nicht negativ sein", 400)
            self.con.execute("UPDATE ankaeufe SET status='uebergeben', uebergabe_am=?, zahlung_am=?, km_uebergabe=? WHERE id=?",
                             (ueb, zahl, km, aid))
            self._verlauf(aid, nutzer_id, "uebergeben", {"uebergabe_am": ueb, "zahlung_am": zahl, "km": km})

    def kosten_erfassen(self, aid: int, art: str, betrag, notiz: str | None, datum, nutzer_id: int | None) -> int:
        """Ist-Kosten; negativ = Korrektur/Gutschrift (Einträge sind unveränderlich)."""
        if art not in ergebnis.KOSTENARTEN:
            raise AnkaufFehler("Unbekannte Kostenart", 400)
        betrag = _betrag(betrag, "Betrag", null_erlaubt=True)
        if betrag == 0:
            raise AnkaufFehler("Betrag darf nicht 0 sein", 400)
        with self.db.transaktion():
            a = self._vorgang(aid)
            if a["status"] == "storniert":
                raise AnkaufFehler("Vorgang ist storniert")
            d = _datum(datum, "Datum")
            kid = self.con.execute("INSERT INTO ankauf_kosten (ankauf_id, art, betrag, notiz, datum, nutzer_id, erstellt_am) VALUES (?,?,?,?,?,?,?)",
                                   (aid, art, betrag, (notiz or "").strip()[:300] or None, d, nutzer_id, _jetzt())).lastrowid
            self._verlauf(aid, nutzer_id, "kosten", {"art": art, "betrag": betrag})
        return kid

    def verkaufen(self, aid: int, vk_preis, verkauft_am, nutzer_id: int | None):
        vk_preis = _betrag(vk_preis, "Verkaufspreis")
        with self.db.transaktion():
            a = self._vorgang(aid)
            if a["status"] != "uebergeben":
                raise AnkaufFehler("Verkauf nur für Fahrzeuge im Bestand")
            d = _datum(verkauft_am, "Verkaufsdatum", a["uebergabe_am"])
            self.con.execute("UPDATE ankaeufe SET status='verkauft', vk_preis=?, verkauft_am=? WHERE id=?", (vk_preis, d, aid))
            self._verlauf(aid, nutzer_id, "verkauft", {"vk_preis": vk_preis, "verkauft_am": d})

    def stornieren(self, aid: int, grund: str, nutzer_id: int | None):
        grund = (grund or "").strip()[:300]
        if not grund:
            raise AnkaufFehler("Grund für das Storno angeben", 400)
        with self.db.transaktion():
            a = self._vorgang(aid)
            if a["status"] != "gekauft":
                raise AnkaufFehler("Storno nur vor der Übergabe")
            self.con.execute("UPDATE ankaeufe SET status='storniert', storno_grund=? WHERE id=?", (grund, aid))
            self._verlauf(aid, nutzer_id, "storniert", {"grund": grund})

    # ---------- Dokumente ----------
    def dokument_speichern(self, aid: int, art: str, daten: bytes, nutzer_id: int | None) -> dict:
        if art not in DOKUMENTARTEN:
            raise AnkaufFehler("Unbekannte Dokumentart", 400)
        if len(daten) > MAX_FOTO_BYTES:
            raise AnkaufFehler("Datei zu groß (max. 8 MB)", 400)
        try:
            endung = dokument_endung(daten)
        except ValueError as e:
            raise AnkaufFehler("Nur PDF, JPEG, PNG oder WebP", 400) from e
        self._vorgang(aid)
        ordner = self.ordner / str(int(aid))
        ordner.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{endung}"
        (ordner / name).write_bytes(ohne_metadaten(daten))            # Vertragsfoto: kein GPS/EXIF (G0)
        with self.db.transaktion():
            did = self.con.execute("INSERT INTO ankauf_dokumente (ankauf_id, art, datei, nutzer_id, erstellt_am) VALUES (?,?,?,?,?)",
                                   (aid, art, name, nutzer_id, _jetzt())).lastrowid
            self._verlauf(aid, nutzer_id, "dokument", {"art": art, "datei": name})
        return {"id": did, "art": art, "datei": name}

    def dokument_pfad(self, aid: int, datei: str) -> Path | None:
        """Nur Dateien, die zu diesem Vorgang gespeichert sind (kein Pfad-Trick möglich)."""
        r = self.con.execute("SELECT 1 FROM ankauf_dokumente WHERE ankauf_id=? AND datei=?", (aid, datei)).fetchone()
        pfad = self.ordner / str(int(aid)) / datei
        return pfad if r and pfad.is_file() else None

    # ---------- Sichten ----------
    def _kosten(self, aid: int) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM ankauf_kosten WHERE ankauf_id=? ORDER BY id", (aid,))]

    def _vergleich(self, a: dict) -> dict:
        return ergebnis.vergleich(json.loads(a["plan_json"]), a, self._kosten(a["id"]))

    def _titel(self, a: dict) -> str:
        b = self.con.execute("SELECT basis_json FROM besichtigungen WHERE id=?", (a["besichtigung_id"],)).fetchone()
        return (json.loads(b["basis_json"]) or {}).get("fahrzeug") or a["referenz"] if b else a["referenz"]

    def liste(self) -> dict:
        zeilen = [dict(r) for r in self.con.execute("SELECT * FROM ankaeufe ORDER BY id DESC")]
        paare = [(a, self._vergleich(a)) for a in zeilen]
        return {"vorgaenge": [{"id": a["id"], "referenz": a["referenz"], "fahrzeug": self._titel(a), "herkunft": a["herkunft"],
                               "status": a["status"], "status_text": STATUS[a["status"]], "kaufpreis": a["kaufpreis"],
                               "vk_preis": a["vk_preis"], "gewinn": v["ist"]["gewinn"], "gewinn_plan": v["plan"]["gewinn"],
                               "vorlaeufig": v["ist"]["vorlaeufig"], "erstellt_am": a["erstellt_am"]} for a, v in paare],
                "uebersicht": ergebnis.uebersicht(paare)}

    def zu_anfrage(self, anfrage_id: int) -> list[dict]:
        return [{"id": r["id"], "referenz": r["referenz"], "status": r["status"], "status_text": STATUS[r["status"]]} for r in
                self.con.execute("SELECT id, referenz, status FROM ankaeufe WHERE anfrage_id=? ORDER BY id DESC", (anfrage_id,))]

    def lade(self, aid: int) -> dict:
        a = self._vorgang(aid)
        b = self.con.execute("SELECT * FROM besichtigungen WHERE id=?", (a["besichtigung_id"],)).fetchone()
        basis = json.loads(b["basis_json"]) if b else {}
        protokoll = json.loads(b["protokoll_json"]) if b and b["protokoll_json"] else {}
        verlauf = [{**dict(r), "daten": json.loads(r["daten_json"])} for r in
                   self.con.execute("SELECT v.*, n.name AS nutzer FROM ankauf_verlauf v LEFT JOIN nutzer n ON n.id=v.nutzer_id "
                                    "WHERE v.ankauf_id=? ORDER BY v.id", (aid,))]
        for v in verlauf:
            v.pop("daten_json")
        dokumente = [dict(r) for r in self.con.execute("SELECT id, art, datei, erstellt_am FROM ankauf_dokumente WHERE ankauf_id=? ORDER BY id",
                                                       (aid,))]
        return {**{k: a[k] for k in a if k != "plan_json"}, "status_text": STATUS[a["status"]], "fahrzeug": basis.get("fahrzeug"),
                "basis": basis, "verkaeufer": protokoll.get("verkaeufer"), "kosten": self._kosten(aid), "dokumente": dokumente,
                "verlauf": verlauf, "vergleich": self._vergleich(a), "weg": self._weg(a, b, protokoll, dokumente)}

    def _weg(self, a: dict, b, protokoll: dict, dokumente: list[dict]) -> list[dict]:
        """Der nachvollziehbare Weg – jeder Schritt mit Zeitpunkt und Beleg (Link) oder „offen“."""
        weg = []
        if a["anfrage_id"]:
            r = self.con.execute("SELECT referenz, erstellt_am, kanal FROM verkaufsanfragen WHERE id=?", (a["anfrage_id"],)).fetchone()
            weg.append({"schritt": "Verkaufsanfrage", "erledigt": r["erstellt_am"], "text": f"{r['referenz']} ({r['kanal']})",
                        "link": f"/anfragen#{a['anfrage_id']}"})
        else:
            weg.append({"schritt": "Inserat", "erledigt": a["erstellt_am"], "text": a["anzeige_id"], "link": None})
        if a["auktion_id"]:
            z = self.zuschlag(a["anfrage_id"]) or {}
            weg.append({"schritt": "Demo-Auktion / Zuschlag", "erledigt": z.get("entschieden_utc"),
                        "text": f"{z.get('standort', '?')}: Gebot {z.get('betrag', '?')} €" +
                                (f", Kalkulation #{z['kalkulation_id']}" if z.get("kalkulation_id") else ""),
                        "link": f"/api/kalkulation/{z['kalkulation_id']}" if z.get("kalkulation_id") else None})
        if a["kalkulation_id"]:
            k = self.deal.lade(a["kalkulation_id"])
            weg.append({"schritt": "Kalkulation zum Kaufpreis", "erledigt": k["zeitpunkt_utc"],
                        "text": f"#{k['id']} – " + ("nachgerechnet ✓" if k["nachrechnung"]["gleich"] else "ABWEICHUNG beim Nachrechnen"),
                        "link": f"/api/kalkulation/{k['id']}"})
        weg.append({"schritt": "Besichtigung und Kaufprotokoll", "erledigt": protokoll.get("abgeschlossen_am"),
                    "text": f"#{a['besichtigung_id']}, vereinbart {a['kaufpreis']} €", "link": f"/protokoll/{a['besichtigung_id']}"})
        weg.append({"schritt": "Kaufvertrag unterschrieben", "erledigt": a["vertrag_am"],
                    "text": f"{sum(1 for d in dokumente if d['art'] == 'vertrag')} Scan(s)", "link": f"/ankauf/{a['id']}/vertrag"})
        weg.append({"schritt": "Übergabe und Zahlung", "erledigt": a["uebergabe_am"],
                    "text": f"Zahlung {a['zahlung_am'] or '–'}, km {a['km_uebergabe'] if a['km_uebergabe'] is not None else '–'}", "link": None})
        weg.append({"schritt": "Verkauf", "erledigt": a["verkauft_am"],
                    "text": f"{a['vk_preis']} €" if a["vk_preis"] else "noch im Bestand" if a["status"] == "uebergeben" else "–", "link": None})
        if a["status"] == "storniert":
            r = self.con.execute("SELECT zeitpunkt FROM ankauf_verlauf WHERE ankauf_id=? AND ereignis='storniert'", (a["id"],)).fetchone()
            weg.append({"schritt": "Storniert", "erledigt": r["zeitpunkt"] if r else None, "text": a["storno_grund"], "link": None})
        return weg
