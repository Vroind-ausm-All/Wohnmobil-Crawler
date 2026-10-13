"""Händler-Einkaufspreis-Rechner.

Logik (alle Parameter in config.yaml → rechner):

  Marktwert privat  = Median vergleichbarer Angebote × (1 − Abschlag Angebot→Abschluss)
  Händler-VK        = Marktwert privat × (1 + Händleraufschlag)
  Kosten            = Aufbereitung + HU/Gas + Transport + Standzeit
                      + Gewährleistungsrücklage (% vom VK) + Reparaturrisiko (Alter, km)
  Ziel-Marge        = max(Marge % × VK, Mindestmarge)

  §25a (Differenzbesteuerung):  Gewinn = (VK − EK) × 100/119 − Kosten
        → Max-EK = VK − (Marge + Kosten) × 1,19
  Regelbesteuerung:             Gewinn = VK / 1,19 − EK − Kosten
        → Max-EK = VK / 1,19 − Kosten − Marge

  Erstangebot = Max-EK × Erstangebot-Faktor
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from statistics import median


@dataclass
class Bewertung:
    marktwert_angebote: int | None
    vergleich_anzahl: int
    vergleich_basis: str
    marktwert_privat: int
    haendler_vk: int
    kosten: int
    kosten_posten: dict = field(default_factory=dict)
    ziel_marge: int = 0
    max_ek: int = 0
    erstangebot: int = 0
    angebotspreis: int | None = None
    verhaeltnis: float | None = None
    ampel: str = "grau"
    potenzial: int | None = None   # Gewinn, wenn zum Angebotspreis gekauft würde

    def dict(self):
        return asdict(self)


def _runde(x: float, auf: int = 50) -> int:
    return int(round(x / auf) * auf)


class Rechner:
    def __init__(self, cfg: dict):
        self.c = cfg["rechner"]

    # ---------- Vergleichsbasis ----------
    def vergleichspreise(self, a: dict, alle: list[dict]) -> tuple[list[int], str]:
        jt, kt = self.c["vergleich_jahre_toleranz"], self.c["vergleich_km_toleranz"]

        def passt(b, mit_marke: bool) -> bool:
            if b["id"] == a["id"] or not b["preis"]:
                return False
            if (b.get("suche") or "") != (a.get("suche") or ""):
                return False
            if mit_marke and (not a.get("marke") or (b.get("marke") or "").lower() != a["marke"].lower()):
                return False
            if a.get("ez_jahr"):
                if not b.get("ez_jahr") or abs(b["ez_jahr"] - a["ez_jahr"]) > jt:
                    return False
            if a.get("km") and b.get("km") and abs(b["km"] - a["km"]) > kt:
                return False
            return True

        mindest = self.c["vergleich_min_anzahl"]
        for mit_marke, label in ((True, "gleiche Marke, Art, EZ ± {j} J."), (False, "gleiche Art, EZ ± {j} J.")):
            preise = [b["preis"] for b in alle if passt(b, mit_marke)]
            if len(preise) >= mindest:
                # Ausreißer (oberstes/unterstes 10 %) bei vielen Vergleichen kappen
                preise.sort()
                k = len(preise) // 10
                preise = preise[k:len(preise) - k] if k else preise
                return preise, label.format(j=jt)
        return [], "zu wenig Vergleiche – Angebotspreis als Basis"

    # ---------- Kosten ----------
    def kosten(self, a: dict, vk: float) -> dict:
        k = self.c["kosten"]
        posten = {
            "Aufbereitung": k["aufbereitung"],
            "HU / Gasprüfung": k["hu_gasprüfung"],
            "Transport": k["transport_pauschal"],
            "Standkosten": k["standkosten_pro_monat"] * k["standzeit_monate"],
            "Gewährleistungsrücklage": vk * k["gewährleistung_rücklage_prozent"],
        }
        alter = date.today().year - a["ez_jahr"] if a.get("ez_jahr") else 12
        for stufe in k["reparatur_risiko"]:
            if alter <= stufe["bis_jahre"]:
                posten[f"Reparaturrisiko ({alter} J.)"] = stufe["betrag"]
                break
        if a.get("km") and a["km"] > k["km_zuschlag_ab"]:
            posten["km-Zuschlag"] = (a["km"] - k["km_zuschlag_ab"]) / 10000 * k["km_zuschlag_pro_10000"]
        return {n: _runde(v, 10) for n, v in posten.items()}

    # ---------- Hauptrechnung ----------
    def bewerte(self, a: dict, alle: list[dict] | None = None, marktwert_manuell: int | None = None) -> Bewertung:
        preise, basis = ([], "manuell") if marktwert_manuell else self.vergleichspreise(a, alle or [])
        if marktwert_manuell:
            mw_angebote = marktwert_manuell
        elif preise:
            mw_angebote = median(preise)
        else:
            mw_angebote = a.get("preis")
        if not mw_angebote:
            return Bewertung(None, 0, "kein Preis", 0, 0, 0, angebotspreis=a.get("preis"))

        mw_privat = mw_angebote * (1 - self.c["abschlag_angebot_auf_privatwert"])
        vk = mw_privat * (1 + self.c["aufschlag_haendler_vk"])
        posten = self.kosten(a, vk)
        kosten = sum(posten.values())
        marge = max(vk * self.c["ziel_marge_prozent"], self.c["ziel_marge_min"])

        if self.c["differenzbesteuerung"]:
            max_ek = vk - (marge + kosten) * 1.19
        else:
            max_ek = vk / 1.19 - kosten - marge
        max_ek = max(0, max_ek)

        b = Bewertung(
            marktwert_angebote=_runde(mw_angebote), vergleich_anzahl=len(preise), vergleich_basis=basis,
            marktwert_privat=_runde(mw_privat), haendler_vk=_runde(vk, 100), kosten=_runde(kosten),
            kosten_posten=posten, ziel_marge=_runde(marge), max_ek=_runde(max_ek, 100),
            erstangebot=_runde(max_ek * self.c["erstangebot_faktor"], 100), angebotspreis=a.get("preis"),
        )
        if b.angebotspreis and b.erstangebot > b.angebotspreis:
            # Nie mehr anbieten, als der Verkäufer verlangt
            b.erstangebot = _runde(b.angebotspreis * self.c["erstangebot_faktor"] ** 0.5, 100)
        if b.angebotspreis and b.max_ek:
            b.verhaeltnis = round(b.angebotspreis / b.max_ek, 3)
            amp = self.c["ampel"]
            b.ampel = "gruen" if b.verhaeltnis <= amp["gruen_bis"] else "gelb" if b.verhaeltnis <= amp["gelb_bis"] else "rot"
            b.potenzial = _runde(self.gewinn_bei_ek(vk, kosten, b.angebotspreis))
        return b

    def gewinn_bei_ek(self, vk: float, kosten: float, ek: float) -> float:
        if self.c["differenzbesteuerung"]:
            return (vk - ek) * 100 / 119 - kosten if vk > ek else vk - ek - kosten
        return vk / 1.19 - ek - kosten
