"""Ergebnisvergleich (Phase F, ADR-029): Plan beim Kauf gegen Ist nach Übergabe, Kosten und Verkauf.

Rein (ohne Datenbank): Der Plan wird beim Anlegen des Ankaufsvorgangs eingefroren – bei Verkaufsanfragen aus einer
gespeicherten, nachrechenbaren Kalkulation zum Kaufpreis (Phase E), bei Inseraten aus der Bewertung zum Kaufzeitpunkt.
Das Ist kommt aus Kaufpreis, erfassten Kosten, Verkaufspreis und Standzeit. Gewinn mit derselben Formel wie der Rechner
(§25a oder Regelbesteuerung – fachliche Annahme, keine Steuerberatung). Nur Anzeige: Die Kalkulation wird nicht automatisch
angepasst; die Abweichungen sind die Grundlage, Parameter in ``config.yaml`` bewusst nachzustellen.
"""
from __future__ import annotations

from datetime import date

from .rechner import Rechner, _runde

KOSTENARTEN = {"transport": "Transport/Abholung", "aufbereitung": "Aufbereitung", "reparatur": "Reparatur", "hu_gas": "HU/Gasprüfung",
               "standkosten": "Standkosten", "provision": "Provision", "gewaehrleistung": "Gewährleistung", "sonstiges": "Sonstiges"}


def _gewinn(vk: int, kosten: int, ek: int, differenzbesteuerung: bool) -> int:
    """Auf 50 € gerundet wie in der Kalkulation – keine falsche Genauigkeit."""
    return _runde(Rechner({"rechner": {"differenzbesteuerung": differenzbesteuerung}}).gewinn_bei_ek(vk, kosten, ek))


def plan_aus_kalkulation(erg: dict, kalkulation_id: int, *, standzeit_tage: int, differenzbesteuerung: bool) -> dict:
    """Erwartetes Szenario einer Kalkulation zum Kaufpreis (Provision ist darin schon Kosten)."""
    s = erg["szenarien"]
    erw = s["erwartet"]
    return {"quelle": f"Kalkulation #{kalkulation_id} zum Kaufpreis (nachrechenbar)", "kalkulation_id": kalkulation_id,
            "haendler_vk": erw["haendler_vk"], "kosten": erw["kosten"] + erw.get("provision", 0), "provision": erw.get("provision", 0),
            "ziel_marge": erw["ziel_marge"], "max_ek": erw["max_ek"], "gewinn": erw.get("gewinn"),
            "vk_spanne": [s["vorsichtig"]["haendler_vk"], s["guenstig"]["haendler_vk"]] if "vorsichtig" in s else None,
            "standzeit_tage": standzeit_tage, "differenzbesteuerung": differenzbesteuerung,
            "abschlag_marke": erg.get("abschlag_marke", 0.0), "kosten_kapital": erg.get("kosten_kapital", 0)}


def plan_aus_bewertung(b, kaufpreis: int, *, standzeit_tage: int, differenzbesteuerung: bool) -> dict:
    """Bewertung eines Inserats (``Rechner.bewerte``) zum Kaufzeitpunkt."""
    return {"quelle": "Bewertung des Inserats zum Kaufzeitpunkt (eingefroren)", "kalkulation_id": None,
            "haendler_vk": b.haendler_vk, "kosten": b.kosten, "provision": 0, "ziel_marge": b.ziel_marge, "max_ek": b.max_ek,
            "gewinn": _gewinn(b.haendler_vk, b.kosten, kaufpreis, differenzbesteuerung),
            "vk_spanne": None, "standzeit_tage": standzeit_tage, "differenzbesteuerung": differenzbesteuerung,
            "abschlag_marke": b.abschlag_marke, "kosten_kapital": kosten_kapital(b.kosten_posten)}


def kosten_kapital(posten: dict) -> int:
    """Rechnerische Kapitalbindung (P5-05) – fällt nie als Ausgabe an, gehört also nicht in den Vergleich mit erfassten Ist-Kosten."""
    return sum(v for n, v in (posten or {}).items() if n.startswith("Kapitalbindung"))


def plan_aus_basis(basis: dict, *, standzeit_tage: int) -> dict:
    """Notbehelf, wenn das Inserat nicht mehr bewertet werden kann: nur die bei der Besichtigung eingefrorenen Werte."""
    return {"quelle": "Grundlage der Besichtigung (Kosten unbekannt)", "kalkulation_id": None, "haendler_vk": basis.get("haendler_vk"),
            "kosten": None, "provision": 0, "ziel_marge": None, "max_ek": basis.get("max_ek"), "gewinn": None, "vk_spanne": None,
            "standzeit_tage": standzeit_tage, "differenzbesteuerung": bool(basis.get("differenzbesteuerung", True))}


def _tage(von: str | None, bis: str | None, heute: date) -> int | None:
    if not von:
        return None
    return (date.fromisoformat(bis[:10]) if bis else heute).toordinal() - date.fromisoformat(von[:10]).toordinal()


def _prozent(ist: int | None, plan: int | None) -> float | None:
    return round((ist - plan) / plan * 100, 1) if ist is not None and plan else None


def vergleich(plan: dict, ankauf: dict, kosten: list[dict], heute: date | None = None) -> dict:
    """Plan gegen Ist. Vor dem Verkauf ist der Gewinn „vorläufig“ (Plan-VK statt echtem VK)."""
    heute = heute or date.today()
    je_art: dict[str, int] = {}
    for k in kosten:
        je_art[k["art"]] = je_art.get(k["art"], 0) + k["betrag"]
    ist_kosten, ek, vk = sum(je_art.values()), ankauf["kaufpreis"], ankauf.get("vk_preis")
    steuer = plan.get("differenzbesteuerung", True)
    vorlaeufig = vk is None
    vk_rechnung = vk if vk is not None else plan.get("haendler_vk")
    gewinn = _gewinn(vk_rechnung, ist_kosten, ek, steuer) if vk_rechnung else None
    standzeit = _tage(ankauf.get("uebergabe_am"), ankauf.get("verkauft_am"), heute)
    abw = {"vk": None if vorlaeufig or plan.get("haendler_vk") is None else vk - plan["haendler_vk"],
           "vk_prozent": None if vorlaeufig else _prozent(vk, plan.get("haendler_vk")),
           "kosten": None if plan.get("kosten") is None else ist_kosten - plan["kosten"],
           "gewinn": None if gewinn is None or plan.get("gewinn") is None else gewinn - plan["gewinn"],
           "unter_max_ek": None if plan.get("max_ek") is None else plan["max_ek"] - ek,
           "standzeit_tage": None if standzeit is None else standzeit - plan["standzeit_tage"]}
    hinweise = []
    if abw["unter_max_ek"] is not None and abw["unter_max_ek"] < 0:
        hinweise.append(f"Kaufpreis lag {-abw['unter_max_ek']:,} € über dem Max-EK".replace(",", "."))
    if vorlaeufig:
        hinweise.append("Noch nicht verkauft – Gewinn vorläufig mit dem geplanten Händler-VK")
    if plan.get("kosten") is not None and not kosten and ankauf.get("status") == "verkauft":
        hinweise.append("Keine Ist-Kosten erfasst – der Gewinn ist dann zu hoch")
    if plan.get("vk_spanne") and vk is not None and not plan["vk_spanne"][0] <= vk <= plan["vk_spanne"][1]:
        hinweise.append("Verkaufspreis außerhalb der geplanten Spanne – Marktwert-Schätzung prüfen")
    return {"plan": plan, "ist": {"kaufpreis": ek, "kosten": ist_kosten, "kosten_je_art": je_art, "vk": vk, "gewinn": gewinn,
                                  "vorlaeufig": vorlaeufig, "standzeit_tage": standzeit},
            "abweichung": abw, "hinweise": hinweise}


def uebersicht(vergleiche: list[tuple[dict, dict]]) -> dict:
    """Kennzahlen über alle Vorgänge: (Ankauf, Vergleich). Durchschnitte nur über verkaufte Fahrzeuge."""
    verkauft = [(a, v) for a, v in vergleiche if a["status"] == "verkauft"]
    bestand = [(a, v) for a, v in vergleiche if a["status"] == "uebergeben"]

    def mittel(werte):
        werte = [w for w in werte if w is not None]
        return round(sum(werte) / len(werte), 1) if werte else None
    return {"anzahl": len(vergleiche), "verkauft": len(verkauft), "im_bestand": len(bestand),
            "gekauft_offen": sum(1 for a, _ in vergleiche if a["status"] == "gekauft"),
            "gewinn_ist": sum(v["ist"]["gewinn"] or 0 for _, v in verkauft),
            "gewinn_plan": sum(v["plan"]["gewinn"] or 0 for _, v in verkauft),
            "vk_abweichung_prozent": mittel(v["abweichung"]["vk_prozent"] for _, v in verkauft),
            "kosten_abweichung": mittel(v["abweichung"]["kosten"] for _, v in verkauft),
            "standzeit_tage": mittel(v["ist"]["standzeit_tage"] for _, v in verkauft),
            "kapital_im_bestand": sum(a["kaufpreis"] + v["ist"]["kosten"] for a, v in bestand)}
