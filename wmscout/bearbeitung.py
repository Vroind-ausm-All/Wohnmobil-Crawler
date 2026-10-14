"""Team-Bearbeitung: Wer hat welches Inserat übernommen oder kontaktiert? Reine Logik, ohne Datenbank und Netz.

Gespeichert wird nur die Tabelle ``bearbeitung`` (Schema Version 3: Bearbeiter, Übernahme-Zeitpunkt, erster Kontakt).
Zustand, Ablauf, Kürzel und Wirkung auf Dubletten werden hier beim Lesen berechnet.

Zustände eines Inserats:
  frei             niemand hält es (nie übernommen, Reservierung abgelaufen oder der Bearbeiter ist deaktiviert)
  reserviert       ein aktiver Kollege hat es übernommen, noch kein bestätigter Kontakt (läuft nach ``reservierung_tage`` ab)
  kontaktiert      der Kontakt wurde bestätigt (``kontaktiert_von``); läuft nie ab
  ohne_zuordnung   Altbestand: Status „kontaktiert“/„in Verhandlung“/„Besichtigung“, aber niemand zugeordnet
  verwaist         Status wie oben, der Kontakt wurde bestätigt, der Bearbeiter ist aber deaktiviert (oder fehlt); übernehmbar wie
                   ``ohne_zuordnung`` (Mitarbeiter per Übernehmen, Inhaber per Zuweisen), damit nichts liegen bleibt
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

FREI, RESERVIERT, KONTAKTIERT, OHNE_ZUORDNUNG, VERWAIST = "frei", "reserviert", "kontaktiert", "ohne_zuordnung", "verwaist"
IN_ARBEIT = ("kontaktiert", "verhandlung", "besichtigung")      # Inserat-Status, die einen Kontakt voraussetzen
OFFEN = ("neu", *IN_ARBEIT)                                      # nicht abgeschlossen (für „meine“ auf der Startseite)
INHABER = "inhaber"

STANDARD_RESERVIERUNG_TAGE = 2
MAX_RESERVIERUNG_TAGE = 3650


class BearbeitungsKonflikt(Exception):
    """Ein Kollege hält das Inserat (oder eine Dublette); die Änderung wurde nicht durchgeführt."""

    def __init__(self, anzeige_id: str):
        super().__init__(f"Inserat {anzeige_id} ist von einem Kollegen belegt")
        self.anzeige_id = anzeige_id


# ---------------------------------------------------------------- Konfiguration
def reservierung_tage(cfg: dict) -> int:
    """Dauer einer Reservierung in Tagen (config.yaml → team → reservierung_tage; 0 = läuft nie ab).
    ``ValueError`` mit verständlicher Meldung bei falschen Typen."""
    abschnitt = cfg.get("team")
    if abschnitt is None:
        return STANDARD_RESERVIERUNG_TAGE
    if not isinstance(abschnitt, dict):
        raise ValueError(f"Ungültiger Abschnitt „team“ in config.yaml: {abschnitt!r} – erwartet wird der Eintrag "
                         "„reservierung_tage“ (ganze Zahl ab 0)")
    wert = abschnitt.get("reservierung_tage")
    if wert is None:
        return STANDARD_RESERVIERUNG_TAGE
    if isinstance(wert, bool) or not isinstance(wert, int) or not 0 <= wert <= MAX_RESERVIERUNG_TAGE:
        raise ValueError(f"Ungültige Reservierungsdauer „reservierung_tage“: {wert!r} – erwartet wird eine ganze Zahl von 0 bis "
                         f"{MAX_RESERVIERUNG_TAGE} (Tage; 0 = läuft nie ab) (config.yaml -> team -> reservierung_tage)")
    return wert


# ---------------------------------------------------------------- Kürzel
def _kandidaten(name: str) -> list[str]:
    woerter = re.findall(r"[^\W\d_]+", name)
    if not woerter:
        return []
    erstes, letztes = woerter[0].upper(), woerter[-1].upper()
    if len(woerter) == 1:
        return [erstes[:i] for i in range(min(2, len(erstes)), len(erstes) + 1)]
    kandidaten = [erstes[:i] + letztes[:j] for i, j in ((1, 1), (2, 1), (2, 2), (3, 2), (3, 3))]
    return list(dict.fromkeys(kandidaten))


def kuerzel(nutzer_liste: list[dict]) -> dict[int, str]:
    """Kürzel je Nutzer-ID: Initialen aus Vor- und Nachname („Anna Schmidt“ → AS), sonst die ersten zwei Buchstaben („Ben“ → BE).

    Kollisionen werden nach ID aufsteigend aufgelöst: Wer die kleinere ID hat, behält das Kürzel, der Spätere wird
    verlängert („Bernd“ → BER). Neue Kollegen (größere ID) ändern deshalb nie ein bestehendes Kürzel. Übergeben werden
    alle Nutzer, auch deaktivierte – sonst würden Kürzel wandern."""
    vergeben: set[str] = set()
    ergebnis: dict[int, str] = {}
    for n in sorted(nutzer_liste, key=lambda n: n["id"]):
        kandidaten = _kandidaten(str(n.get("name") or ""))
        wahl = next((k for k in kandidaten if k not in vergeben), None)
        if wahl is None:
            basis = kandidaten[0] if kandidaten else "N"
            wahl = f"{basis}{n['id']}"
            while wahl in vergeben:
                wahl += "_"
        vergeben.add(wahl)
        ergebnis[n["id"]] = wahl
    return ergebnis


# ---------------------------------------------------------------- Zustand
def ablauf_grenze(jetzt: datetime, tage: int) -> str:
    """Zeitpunkt (ISO, Sekunden), vor dem eine Übernahme als abgelaufen gilt. Leer = läuft nie ab (nichts ist kleiner als "")."""
    return "" if tage <= 0 else (jetzt - timedelta(days=tage)).isoformat(timespec="seconds")


def halter(zeile: dict | None, grenze: str, aktive_ids) -> int | None:
    """Wer hält das Inserat wirksam? Der Bearbeiter, wenn er aktiv ist und (der Kontakt bestätigt oder die Übernahme nicht
    abgelaufen) ist. Sonst ``None``: Reservierungen deaktivierter Nutzer und abgelaufene Reservierungen gelten als frei."""
    if not zeile or not zeile.get("bearbeiter_id") or zeile["bearbeiter_id"] not in aktive_ids:
        return None
    if zeile.get("kontaktiert_von") or (zeile.get("uebernommen_am") or "") >= grenze:
        return zeile["bearbeiter_id"]
    return None


def zustand(zeile: dict | None, jetzt: datetime, reservierung_tage: int, aktive_ids) -> str:
    """``zeile``: Zeile aus ``bearbeitung`` (oder ``None``) plus ``status`` des Inserats (für den Altbestand)."""
    z = zeile or {}
    grenze = ablauf_grenze(jetzt, reservierung_tage)
    if z.get("kontaktiert_von"):
        # Kontakt bestätigt: hält ihn niemand mehr (Bearbeiter deaktiviert) und ist das Inserat noch in Arbeit → verwaist
        return KONTAKTIERT if halter(z, grenze, aktive_ids) or z.get("status") not in IN_ARBEIT else VERWAIST
    if halter(z, grenze, aktive_ids):
        return RESERVIERT
    return OHNE_ZUORDNUNG if z.get("status") in IN_ARBEIT else FREI


# ---------------------------------------------------------------- Rechte
def darf_erzwingen(rolle: str | None) -> bool:
    return rolle == INHABER


def darf_zuweisen(rolle: str | None) -> bool:
    return rolle == INHABER


def darf_uebernehmen(halter_id: int | None, ich_id: int | None) -> bool:
    return halter_id is None or halter_id == ich_id


def darf_status(halter_id: int | None, ich_id: int | None, rolle: str | None) -> bool:
    """Notizen sind für alle frei; Status (außer Kontakt, der eine Übernahme braucht): frei, eigen oder Inhaber."""
    return halter_id is None or halter_id == ich_id or rolle == INHABER


def darf_abgeben(zustand_: str, bearbeiter_id: int | None, ich_id: int | None, rolle: str | None) -> bool:
    """Nur eine noch nicht kontaktierte Reservierung; Bearbeiter oder Inhaber."""
    return zustand_ == RESERVIERT and (bearbeiter_id == ich_id or rolle == INHABER)


# ---------------------------------------------------------------- Sicht für Anzeige und Meldungen
def kurz_datum(iso: str | None) -> str:
    """„14.10. 10:42“ aus einem ISO-Zeitpunkt."""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}" if iso and len(iso) >= 16 else "?"


class TeamSicht:
    """Alles, was zur Anzeige und zu Meldungen nötig ist, aus bereits gelesenen Daten (eine Anfrage = ein Stand).

    ``nutzer``: alle Nutzer (auch deaktivierte) mit ``id``, ``name``, ``aktiv``; ``zeilen``: Zeilen aus ``bearbeitung`` je Inserat-ID
    (alle, auch zu Dubletten, die gerade nicht in der Liste stehen); ``ich``: der angemeldete Nutzer (``id``, ``rolle``)."""

    def __init__(self, nutzer: list[dict], zeilen: dict[str, dict], jetzt: datetime, tage: int, ich: dict | None = None):
        self.nutzer = {n["id"]: n for n in nutzer}
        self.kuerzel = kuerzel(nutzer)
        self.aktive = frozenset(i for i, n in self.nutzer.items() if n.get("aktiv", 1))
        self.zeilen, self.jetzt, self.tage = zeilen, jetzt, tage
        self.grenze = ablauf_grenze(jetzt, tage)
        self.ich_id = (ich or {}).get("id")
        self.rolle = (ich or {}).get("rolle")

    def person(self, nutzer_id: int | None) -> dict | None:
        n = self.nutzer.get(nutzer_id)
        if not n:
            return None
        return {"id": n["id"], "name": n["name"], "kuerzel": self.kuerzel[n["id"]], "aktiv": bool(n.get("aktiv", 1))}

    def halter(self, anzeige_id: str) -> int | None:
        return halter(self.zeilen.get(anzeige_id), self.grenze, self.aktive)

    def _dublette(self, anzeige_id: str, dubletten) -> dict | None:
        """Eine Dublette, die jemand hält; Fremdreservierungen zuerst."""
        treffer = [(d, h) for d in dubletten if d != anzeige_id and (h := self.halter(d))]
        if not treffer:
            return None
        d, h = next((t for t in treffer if t[1] != self.ich_id), treffer[0])
        return {"id": d, "bearbeiter": self.person(h), "mein": h == self.ich_id,
                "zustand": KONTAKTIERT if self.zeilen[d].get("kontaktiert_von") else RESERVIERT}

    def objekt(self, z: dict) -> dict:
        """Team-Objekt zu einer bewerteten Zeile aus ``bewerte_alle``."""
        a = z["a"]
        return self.objekt_id(a["id"], a.get("status") or "neu", z.get("dubletten_ids") or ())

    def objekt_id(self, anzeige_id: str, status: str | None, dubletten=()) -> dict:
        zeile = self.zeilen.get(anzeige_id)
        zu = zustand({**(zeile or {}), "status": status}, self.jetzt, self.tage, self.aktive)
        h = self.halter(anzeige_id)
        gehalten = zu in (RESERVIERT, KONTAKTIERT)
        seit = zeile.get("uebernommen_am") if zeile and gehalten else None
        laeuft_ab = None
        if zu == RESERVIERT and self.tage > 0 and seit:
            laeuft_ab = (datetime.fromisoformat(seit) + timedelta(days=self.tage)).isoformat(timespec="seconds")
        kontakt = zeile.get("kontaktiert_von") if zeile else None
        dublette = self._dublette(anzeige_id, dubletten)
        fremde_dublette = bool(dublette and not dublette["mein"])
        return {
            "zustand": zu, "bearbeiter": self.person(zeile["bearbeiter_id"]) if zeile and gehalten else None, "seit": seit,
            "laeuft_ab": laeuft_ab, "kontaktiert_von": self.person(kontakt), "kontaktiert_am": zeile.get("kontaktiert_am") if kontakt else None,
            "mein": h is not None and h == self.ich_id, "dublette_von": dublette,
            "darf": {"uebernehmen": darf_uebernehmen(h, self.ich_id) and not fremde_dublette,
                     "abgeben": darf_abgeben(zu, zeile.get("bearbeiter_id") if zeile else None, self.ich_id, self.rolle),
                     "status": darf_status(h, self.ich_id, self.rolle), "zuweisen": darf_zuweisen(self.rolle),
                     "erzwingen": darf_erzwingen(self.rolle)},
        }

    @staticmethod
    def ist_frei(obj: dict) -> bool:
        """Niemand hält es: keine aktive Reservierung, kein bestätigter Kontakt, auch nicht über Dubletten."""
        return obj["zustand"] in (FREI, OHNE_ZUORDNUNG, VERWAIST) and not obj["dublette_von"]

    @staticmethod
    def ist_triviale_sicht(obj: dict) -> bool:
        return obj["zustand"] == FREI and not obj["dublette_von"]

    def fremder_halter(self, anzeige_id: str, dubletten=()) -> tuple[str, int] | None:
        """(Inserat-ID, Nutzer-ID) eines anderen Kollegen, der dieses Inserat oder eine Dublette hält."""
        h = self.halter(anzeige_id)
        if h is not None and h != self.ich_id:
            return anzeige_id, h
        for d in dubletten:
            h = self.halter(d)
            if d != anzeige_id and h is not None and h != self.ich_id:
                return d, h
        return None

    def kontaktierte_dublette(self, anzeige_id: str, dubletten, ziel_id: int | None) -> tuple[str, int] | None:
        """(Dublette, Bearbeiter) einer bereits kontaktierten Dublette, die ein anderer aktiver Kollege als ``ziel_id`` bearbeitet:
        Zuweisen und Erzwingen scheitern daran (erst dort zuweisen)."""
        for d in dubletten:
            h = self.halter(d)
            if d != anzeige_id and h is not None and h != ziel_id and (self.zeilen.get(d) or {}).get("kontaktiert_von"):
                return d, h
        return None

    def zuweisung_konflikt_text(self, anzeige_id: str, dubletten, ziel_id: int | None) -> str:
        f = self.kontaktierte_dublette(anzeige_id, dubletten, ziel_id)
        if not f:
            return "Die Zuordnung hat sich gerade geändert – bitte erneut versuchen"
        p = self.person(f[1])
        return (f"Dublette {f[0]} ist bereits von {p['name']} ({p['kuerzel']}) kontaktiert – bitte zuerst dort zuweisen "
                "(oder den Kontakt mit Status „offen“ zurücksetzen)")

    def konflikt_text(self, anzeige_id: str, dubletten=()) -> str:
        f = self.fremder_halter(anzeige_id, dubletten)
        if not f:
            return "Die Reservierung hat sich gerade geändert – bitte erneut versuchen"
        aid, uid = f
        p, zeile = self.person(uid), self.zeilen[aid]
        wer = f"{p['name']} ({p['kuerzel']})"
        if zeile.get("kontaktiert_von"):
            text = f"Bereits kontaktiert, bearbeitet von {wer} seit {kurz_datum(zeile.get('kontaktiert_am'))}"
        else:
            text = f"Reserviert von {wer} seit {kurz_datum(zeile.get('uebernommen_am'))}"
        return text if aid == anzeige_id else f"Dublette {aid}: {text}"
