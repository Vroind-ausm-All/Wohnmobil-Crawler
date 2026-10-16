"""Team-Daten: Nutzer und Anmeldungen, Besichtigungen (Termin, Zuständigkeit, Ergebnis) und Fotos.

Liegt in derselben SQLite-Datenbank wie die Inserate (Tabellen: wmscout/migrationen.py). Passwörter werden mit scrypt gehasht, Anmelde-Tokens nur
als SHA-256 gespeichert. Fotos landen als Dateien unter daten/fotos/<Besichtigung>/.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .bearbeitung import TeamSicht, kuerzel
from .datenbank import Datenbank

ROLLEN = {"inhaber": "Inhaber", "mitarbeiter": "Mitarbeiter", "haendler": "Händler (Standort)"}
HAENDLER = "haendler"          # sieht nur das Händlerportal (/haendler); nie Team-Listen, Ankauf oder Kontaktdaten (ADR-026)
BESICHTIGUNG_STATUS = {"geplant": "geplant", "laeuft": "läuft", "abgeschlossen": "abgeschlossen",
                       "abgebrochen": "abgebrochen"}
SITZUNG_TAGE = 30
MAX_FOTO_BYTES = 8 * 1024 * 1024


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_passwort(passwort: str) -> str:
    salz = secrets.token_bytes(16)
    h = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salz.hex()}${h.hex()}"


def pruefe_passwort(passwort: str, gespeichert: str) -> bool:
    try:
        _, n, r, p, salz, h = gespeichert.split("$")
        neu = hashlib.scrypt(passwort.encode("utf-8"), salt=bytes.fromhex(salz), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(h)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(neu.hex(), h)


_ERSATZ_HASH = hash_passwort(secrets.token_urlsafe(16))      # für unbekannte Namen: gleiche Rechenzeit wie ein echter Versuch


def lade_team_sicht(db: Datenbank, tage: int, ich: dict | None = None, jetzt: datetime | None = None) -> TeamSicht | None:
    """Team-Sicht aus der Datenbank (zwei SELECTs). ``None``, wenn kein aktiver Nutzer existiert (= Team-Funktionen aus)."""
    nutzer = [dict(r) for r in db.con.execute("SELECT id, name, rolle, aktiv FROM nutzer WHERE rolle != 'haendler' ORDER BY id")]
    if not any(n["aktiv"] for n in nutzer):
        return None
    return TeamSicht(nutzer, db.bearbeitung_aktiv(), jetzt or datetime.now(), tage, ich)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bild_endung(daten: bytes) -> str:
    """Dateiendung nach dem Inhalt (nicht nach Namen oder Content-Type); andere Formate werden abgelehnt."""
    if daten[:3] == b"\xff\xd8\xff":
        return "jpg"
    if daten[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Nur JPEG, PNG oder WebP")


def ohne_metadaten(daten: bytes) -> bytes:
    """EXIF/GPS, XMP, IPTC und Kommentare aus JPEG und PNG entfernen (G0) – der Browser tut es beim Verkleinern, ein anderer Client
    aber nicht; sonst verriete ein Foto z. B. den Wohnort des Verkäufers. Bildinhalt bleibt unverändert, andere Formate unverändert."""
    if daten[:2] == b"\xff\xd8":
        aus, i = bytearray(b"\xff\xd8"), 2
        while i + 4 <= len(daten) and daten[i] == 0xFF:
            marker = daten[i + 1]
            if marker == 0xDA:                               # Start of Scan: Rest sind Bilddaten
                break
            laenge = int.from_bytes(daten[i + 2:i + 4], "big")
            if marker not in (0xE1, 0xED, 0xFE):             # APP1 (EXIF/XMP), APP13 (IPTC), COM weglassen
                aus += daten[i:i + 2 + laenge]
            i += 2 + laenge
        return bytes(aus + daten[i:])
    if daten[:8] == b"\x89PNG\r\n\x1a\n":
        aus, i = bytearray(daten[:8]), 8
        while i + 8 <= len(daten):
            laenge = int.from_bytes(daten[i:i + 4], "big")
            typ = daten[i + 4:i + 8]
            if typ not in (b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"):
                aus += daten[i:i + 12 + laenge]
            i += 12 + laenge
        return bytes(aus)
    return daten


class TeamSpeicher:
    def __init__(self, db: Datenbank, foto_ordner: Path):
        self.db = db
        self.con = db.con
        self.foto_ordner = Path(foto_ordner)

    # ---------- Nutzer ----------
    def hat_nutzer(self) -> bool:
        return self.con.execute("SELECT 1 FROM nutzer WHERE aktiv=1 LIMIT 1").fetchone() is not None

    def nutzer_anlegen(self, name: str, passwort: str, rolle: str = "mitarbeiter", telefon: str | None = None,
                       standort_id: int | None = None) -> int:
        if rolle not in ROLLEN:
            raise ValueError(f"Rolle muss {' oder '.join(ROLLEN)} sein")
        if len(passwort) < 8:
            raise ValueError("Passwort braucht mindestens 8 Zeichen")
        if (rolle == HAENDLER) != (standort_id is not None):
            raise ValueError("Händler brauchen einen Standort (--standort); andere Rollen haben keinen")
        cur = self.con.execute("INSERT INTO nutzer (name, rolle, passwort_hash, telefon, erstellt_am, standort_id) VALUES (?,?,?,?,?,?)",
                               (name.strip(), rolle, hash_passwort(passwort), telefon, _jetzt(), standort_id))
        self.con.commit()
        return cur.lastrowid

    def passwort_setzen(self, name: str, passwort: str) -> bool:
        if len(passwort) < 8:
            raise ValueError("Passwort braucht mindestens 8 Zeichen")
        cur = self.con.execute("UPDATE nutzer SET passwort_hash=? WHERE name=?", (hash_passwort(passwort), name))
        self.con.execute("DELETE FROM sitzungen WHERE nutzer_id=(SELECT id FROM nutzer WHERE name=?)", (name,))
        self.con.commit()
        return cur.rowcount > 0

    def nutzer_aktiv_setzen(self, name: str, aktiv: bool) -> bool:
        cur = self.con.execute("UPDATE nutzer SET aktiv=? WHERE name=?", (int(aktiv), name))
        if not aktiv:
            self.con.execute("DELETE FROM sitzungen WHERE nutzer_id=(SELECT id FROM nutzer WHERE name=?)", (name,))
        self.con.commit()
        return cur.rowcount > 0

    def nutzer_liste(self, nur_aktive: bool = True, auch_haendler: bool = False) -> list[dict]:
        """Team-Mitglieder (Inhaber, Mitarbeiter); Händler-Zugänge der Standorte nur mit ``auch_haendler`` (Verwaltung)."""
        bedingungen = (["aktiv=1"] if nur_aktive else []) + ([] if auch_haendler else ["rolle != 'haendler'"])
        sql = "SELECT id, name, rolle, telefon, aktiv, standort_id FROM nutzer" + (" WHERE " + " AND ".join(bedingungen) if bedingungen else "")
        return [dict(r) for r in self.con.execute(sql + " ORDER BY name")]

    def nutzer_mit_kuerzel(self, nur_aktive: bool = True) -> list[dict]:
        """Wie ``nutzer_liste``, zusätzlich mit stabilem Kürzel (berechnet über alle Nutzer, auch deaktivierte)."""
        alle = self.nutzer_liste(nur_aktive=False)
        k = kuerzel(alle)
        return [{**n, "kuerzel": k[n["id"]]} for n in alle if n["aktiv"] or not nur_aktive]

    def sicht(self, tage: int, ich: dict | None = None) -> TeamSicht | None:
        return lade_team_sicht(self.db, tage, ich)

    def nutzer(self, nutzer_id: int | None) -> dict | None:
        if not nutzer_id:
            return None
        r = self.con.execute("SELECT id, name, rolle, telefon, aktiv FROM nutzer WHERE id=?", (nutzer_id,)).fetchone()
        return dict(r) if r else None

    # ---------- Anmeldung ----------
    def anmelden(self, name: str, passwort: str) -> str | None:
        """Prüfen und Sitzung anlegen in einem Schritt (Kommandozeile, Tests). Die Web-App trennt beides (``login_daten``,
        ``sitzung_anlegen``), damit das teure scrypt nicht unter der globalen Sperre läuft."""
        nid, gespeichert = self.login_daten(name)
        if not pruefe_passwort(passwort, gespeichert) or nid is None:
            return None
        return self.sitzung_anlegen(nid)

    def login_daten(self, name: str) -> tuple[int | None, str]:
        """(Nutzer-ID, Hash) – bei unbekanntem oder gesperrtem Namen ein Ersatz-Hash, damit die Antwortzeit nichts verrät."""
        r = self.con.execute("SELECT id, passwort_hash FROM nutzer WHERE name=? AND aktiv=1", (name.strip(),)).fetchone()
        return (r["id"], r["passwort_hash"]) if r else (None, _ERSATZ_HASH)

    def sitzung_anlegen(self, nutzer_id: int) -> str:
        token = secrets.token_urlsafe(32)
        ablauf = (datetime.now() + timedelta(days=SITZUNG_TAGE)).isoformat(timespec="seconds")
        self.con.execute("DELETE FROM sitzungen WHERE ablauf < ?", (_jetzt(),))
        self.con.execute("INSERT INTO sitzungen VALUES (?,?,?)", (_token_hash(token), nutzer_id, ablauf))
        self.con.commit()
        return token

    def nutzer_zu_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        r = self.con.execute("SELECT n.id, n.name, n.rolle, n.telefon, n.standort_id FROM sitzungen s JOIN nutzer n ON n.id=s.nutzer_id "
                             "WHERE s.token_hash=? AND s.ablauf>=? AND n.aktiv=1", (_token_hash(token), _jetzt())).fetchone()
        return dict(r) if r else None

    def abmelden(self, token: str):
        self.con.execute("DELETE FROM sitzungen WHERE token_hash=?", (_token_hash(token),))
        self.con.commit()

    # ---------- Besichtigungen ----------
    def _fertig(self):
        """Commit – außer innerhalb von ``Datenbank.transaktion()``: dort entscheidet der äußere Block (Status und Besichtigung
        werden gemeinsam gespeichert oder gemeinsam verworfen)."""
        if not self.db.in_transaktion:
            self.con.commit()

    def _zeile(self, r) -> dict:
        b = dict(r)
        for feld in ("daten", "basis", "ergebnis", "protokoll"):
            roh = b.pop(f"{feld}_json")
            b[feld] = json.loads(roh) if roh else None
        b["zustaendig"] = self.nutzer(b["zustaendig_id"])
        return b

    def besichtigung_anlegen(self, anzeige_id: str, basis: dict, termin: str | None, adresse: str | None,
                             zustaendig_id: int | None, erstellt_von: int | None) -> int:
        cur = self.con.execute(
            "INSERT INTO besichtigungen (anzeige_id, termin, adresse, zustaendig_id, erstellt_von, erstellt_am, "
            "geaendert_am, basis_json) VALUES (?,?,?,?,?,?,?,?)",
            (anzeige_id, termin, adresse, zustaendig_id, erstellt_von, _jetzt(), _jetzt(),
             json.dumps(basis, ensure_ascii=False)))
        self._fertig()
        return cur.lastrowid

    def besichtigung(self, bid: int) -> dict | None:
        r = self.con.execute("SELECT * FROM besichtigungen WHERE id=?", (bid,)).fetchone()
        return self._zeile(r) if r else None

    def besichtigungen(self, zustaendig_id: int | None = None, offen: bool = True,
                       anzeige_id: str | None = None) -> list[dict]:
        sql, werte = "SELECT * FROM besichtigungen WHERE 1=1", []
        if offen:
            sql += " AND status IN ('geplant', 'laeuft')"
        if zustaendig_id:
            sql += " AND zustaendig_id=?"
            werte.append(zustaendig_id)
        if anzeige_id:
            sql += " AND anzeige_id=?"
            werte.append(anzeige_id)
        sql += " ORDER BY COALESCE(termin, '9999'), id"
        return [self._zeile(r) for r in self.con.execute(sql, werte)]

    def besichtigung_planen(self, bid: int, termin: str | None, adresse: str | None, zustaendig_id: int | None) -> bool:
        cur = self.con.execute("UPDATE besichtigungen SET termin=?, adresse=?, zustaendig_id=?, geaendert_am=?, "
                               "version=version+1 WHERE id=?", (termin, adresse, zustaendig_id, _jetzt(), bid))
        self.con.commit()
        return cur.rowcount > 0

    def besichtigung_speichern(self, bid: int, daten: dict, ergebnis: dict) -> int:
        """Speichert Eingaben + Rechnung, setzt Status auf „läuft“. Rückgabe: neue Version."""
        self.con.execute(
            "UPDATE besichtigungen SET daten_json=?, ergebnis_json=?, status=CASE WHEN status='geplant' THEN 'laeuft' "
            "ELSE status END, geaendert_am=?, version=version+1 WHERE id=?",
            (json.dumps(daten, ensure_ascii=False), json.dumps(ergebnis, ensure_ascii=False), _jetzt(), bid))
        self.con.commit()
        return self.con.execute("SELECT version FROM besichtigungen WHERE id=?", (bid,)).fetchone()["version"]

    def besichtigung_abschliessen(self, bid: int, protokoll: dict, endpreis: int | None, status: str = "abgeschlossen"):
        self.con.execute("UPDATE besichtigungen SET protokoll_json=?, endpreis=?, status=?, geaendert_am=?, "
                         "version=version+1 WHERE id=?",
                         (json.dumps(protokoll, ensure_ascii=False), endpreis, status, _jetzt(), bid))
        self._fertig()

    # ---------- Fotos ----------
    def foto_speichern(self, bid: int, daten: bytes, mangel_key: str | None, nutzer_id: int | None) -> dict:
        if len(daten) > MAX_FOTO_BYTES:
            raise ValueError("Foto zu groß (max. 8 MB)")
        endung = bild_endung(daten)
        daten = ohne_metadaten(daten)
        ordner = self.foto_ordner / str(int(bid))
        ordner.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{endung}"
        (ordner / name).write_bytes(daten)
        cur = self.con.execute("INSERT INTO fotos (besichtigung_id, mangel_key, datei, erstellt_am, nutzer_id) "
                               "VALUES (?,?,?,?,?)", (bid, mangel_key, name, _jetzt(), nutzer_id))
        self.con.commit()
        return {"id": cur.lastrowid, "mangel_key": mangel_key, "datei": name}

    def fotos(self, bid: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, mangel_key, datei, erstellt_am FROM fotos WHERE besichtigung_id=? ORDER BY id", (bid,))]

    def foto_pfad(self, bid: int, datei: str) -> Path | None:
        """Nur Dateien, die zu dieser Besichtigung gespeichert sind (kein Pfad-Trick möglich)."""
        r = self.con.execute("SELECT 1 FROM fotos WHERE besichtigung_id=? AND datei=?", (bid, datei)).fetchone()
        pfad = self.foto_ordner / str(int(bid)) / datei
        return pfad if r and pfad.is_file() else None
