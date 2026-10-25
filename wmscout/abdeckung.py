"""Abdeckung und Suchlücken messen (P4-05, ADR-051) – nur lesen, keine Wirkung auf Bewertung oder Suche, kein Netzabruf.

Grundlage sind die Inserate, die im Zeitraum (Standard 30 Tage) **zuerst** eingingen, bewertet wie in der App (``bewerte_alle`` mit
``erstmals_seit``), dazu Beobachtungen, Preisverlauf und Laufprotokoll. Gemessen werden die Kennzahlen aus ``docs/ROADMAP.md`` und drei Arten
von Lücken:

* **Zeitlücken** – Tage ohne neues oder geändertes Inserat einer lesbaren Plattform (Suchauftrag/Benachrichtigung ausgefallen? Import vergessen?).
* **Gebietslücken** – zweistellige PLZ-Bereiche ohne ein einziges neues Inserat.
* **Profillücken** – je aktivem Suchprofil: Plattformen ohne Suchauftrag oder ohne passenden Eingang, Arten bzw. Regionen des Profils ohne
  Treffer, hoher Anteil „unklar“ (Angaben fehlen, das Profil kann nicht entscheiden).

Oben die Fachlogik ohne Datenbank, unten das Einsammeln der Daten.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from . import suchprofile as sp
from .anbieter import PRIVAT, UNBEKANNT, typ
from .normalisierung.geo import plz_bereiche

STANDARD_TAGE, MIN_TAGE, MAX_TAGE = 30, 1, 365
MAX_TAGE_APP = 90                        # in der App (läuft in der Anfrage); längere Zeiträume über „scout.py abdeckung“
UNKLAR_HOCH = 0.5                       # ab diesem Anteil „unklar“ unter den Treffern eines Profils: Hinweis
MAX_LUECKEN = 10                         # so viele Zeitlücken je Plattform werden einzeln genannt


def tage_aus(wert, hoechstens: int = MAX_TAGE) -> int:
    """Zeitraum in Tagen aus Abfrage oder Kommandozeile; ``ValueError`` mit verständlichem Text."""
    if wert in (None, ""):
        return STANDARD_TAGE
    try:
        tage = int(str(wert).strip()) if str(wert).strip().isascii() else None
    except ValueError:
        tage = None
    if tage is None or not MIN_TAGE <= tage <= hoechstens:
        raise ValueError(f"tage muss eine ganze Zahl von {MIN_TAGE} bis {hoechstens} sein")
    return tage


def _zeit(iso) -> datetime | None:
    """ISO-Zeit als lokale Zeit ohne Zeitzone (``anzeigen`` speichert lokal, ``beobachtungen`` und ``preis_historie`` in UTC)."""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else None
    except ValueError:
        return None
    if t is not None and t.tzinfo is not None:
        t = t.astimezone().replace(tzinfo=None)
    return t


def fahrzeuge(zeilen: list[dict]) -> list[set[str]]:
    """Fahrzeuge als Zusammenhangskomponenten der Dublettenbeziehungen (bestätigt oder erkannt; die Heuristik ist nicht transitiv, daher
    keine paarweisen Schlüssel). Eine Komponente enthält auch Inserate außerhalb der Zeilen (``dubletten_ids``)."""
    eltern: dict[str, str] = {}

    def wurzel(x: str) -> str:
        eltern.setdefault(x, x)
        while eltern[x] != x:
            eltern[x] = eltern[eltern[x]]
            x = eltern[x]
        return x
    for z in zeilen:
        for d in (z["a"]["id"], *z.get("dubletten_ids", ())):
            eltern[wurzel(d)] = wurzel(z["a"]["id"])
    gruppen: dict[str, set[str]] = {}
    for x in list(eltern):
        gruppen.setdefault(wurzel(x), set()).add(x)
    return list(gruppen.values())


def _neue_fahrzeuge(zeilen: list[dict]) -> int:
    """Fahrzeuge, deren Inserate ALLE im Zeitraum zuerst eingingen – ein wieder eingestelltes Altfahrzeug ist nicht neu (die Zeilen enthalten
    genau die Inserate des Zeitraums; ein Gruppenmitglied außerhalb ging also früher ein)."""
    im_zeitraum = {z["a"]["id"] for z in zeilen}
    return sum(1 for g in fahrzeuge(zeilen) if g <= im_zeitraum)


def _quelle(a: dict) -> str:
    return a.get("quelle") or "kleinanzeigen"


def _vollstaendig(z: dict) -> bool:
    a = z["a"]
    return all((a.get("preis"), a.get("ez_jahr"), a.get("km"), a.get("plz"))) and z["b"].art not in (None, "Sonstige") \
        and typ(a.get("gewerblich")) != UNBEKANNT


def _anteil(teil: int, ganz: int) -> float | None:
    return round(teil / ganz, 3) if ganz else None


def kennzahlen(zeilen: list[dict], tage: int, preisaenderungen: int, laeufe: list[dict]) -> dict:
    """Kennzahlen über die im Zeitraum zuerst eingegangenen, bewerteten Inserate (``zeilen``)."""
    n = len(zeilen)
    # im Filter = Sperrgrund ohne den Bearbeitungsstatus (wer ein Angebot kontaktiert oder kauft, senkt die Kennzahl nicht, QA B1)
    privat = [z for z in zeilen if typ(z["a"].get("gewerblich")) == PRIVAT and not z.get("sperre_filter", z["sperre"])
              and not z["a"].get("nicht_verfuegbar")]
    mit_dublette = [z for z in zeilen if z.get("dubletten_ids")]
    laeufe_je_art: dict[str, list] = {}
    for lf in laeufe:
        laeufe_je_art.setdefault(lf["art"], []).append(lf)
    return {
        "neue_inserate": n,
        "neue_inserate_je_quelle": dict(sorted(Counter(_quelle(z["a"]) for z in zeilen).items())),
        "neue_fahrzeuge": _neue_fahrzeuge(zeilen),
        "relevante_privatangebote": len(privat), "relevante_privatangebote_pro_tag": round(len(privat) / tage, 1),
        "inserate_mit_dublette": len(mit_dublette), "anteil_mit_dublette": _anteil(len(mit_dublette), n),
        "nicht_verfuegbar": sum(bool(z["a"].get("nicht_verfuegbar")) for z in zeilen),
        "anteil_nicht_verfuegbar": _anteil(sum(bool(z["a"].get("nicht_verfuegbar")) for z in zeilen), n),
        "preisaenderungen": preisaenderungen,
        "anteil_vollstaendig": _anteil(sum(_vollstaendig(z) for z in zeilen), n),
        "importerfolg": {art: {"laeufe": len(ls), "ohne_fehler": sum(lf["ergebnis"] == "ok" for lf in ls),
                               "quote": _anteil(sum(lf["ergebnis"] == "ok" for lf in ls), len(ls))}
                         for art, ls in sorted(laeufe_je_art.items())},
    }


def zeitluecken(eingangstage: dict[str, set[date]], plattformen, heute: date, tage: int) -> dict[str, dict]:
    """Je Plattform: Tage im Zeitraum ohne Eingang, die längsten zusammenhängenden Lücken (ab 2 Tagen) und der letzte Eingangstag."""
    tage_liste = [heute - timedelta(days=i) for i in range(tage - 1, -1, -1)]
    erg = {}
    for plattform in plattformen:
        da = eingangstage.get(plattform, set())
        ohne, luecken, start = 0, [], None
        for t in [*tage_liste, None]:
            if t is not None and t not in da:
                ohne += 1
                start = start or t
            elif start is not None:
                ende = t - timedelta(days=1) if t else heute
                if (ende - start).days >= 1:
                    luecken.append({"von": start.isoformat(), "bis": ende.isoformat(), "tage": (ende - start).days + 1})
                start = None
        luecken.sort(key=lambda lk: (-lk["tage"], lk["von"]))
        erg[plattform] = {"tage_ohne_eingang": ohne, "tage_mit_eingang": tage - ohne, "luecken": luecken[:MAX_LUECKEN],
                          "letzter_eingang": max(da).isoformat() if da else None}
    return erg


def gebietsluecken(zeilen: list[dict]) -> dict:
    """Neue Inserate je zweistelligem PLZ-Bereich; Bereiche ohne Inserat sind Lücken. Inserate ohne PLZ und im Ausland zählen getrennt."""
    je_bereich = Counter(z["a"]["plz"][:2] for z in zeilen if z["a"].get("plz") and not z["a"].get("ausland"))
    alle = plz_bereiche()
    return {"je_bereich": dict(sorted(je_bereich.items())), "ohne_inserat": [b for b in alle if b not in je_bereich],
            "anteil_bereiche_mit_inserat": _anteil(sum(1 for b in alle if b in je_bereich), len(alle)),
            "ohne_plz": sum(1 for z in zeilen if not z["a"].get("plz") and not z["a"].get("ausland")),
            "ausland": sum(1 for z in zeilen if z["a"].get("ausland"))}


def profilluecken(profil: dict, auftraege: dict[str, dict], zeilen: list[dict]) -> dict:
    """Ein Suchprofil über die neuen Inserate: Treffer (passt/unklar, Fahrzeuge einmal gezählt), je Plattform, und Hinweise auf Lücken."""
    treffer = []
    for z in zeilen:
        if z.get("ausblenden"):
            continue
        urteil, _ = sp.pruefe_inserat(profil, z["a"], z["b"].art)
        if urteil != sp.NEIN:
            treffer.append((z, urteil))
    passt = [z for z, u in treffer if u == sp.PASST]
    passt_ids = {z["a"]["id"] for z in passt}
    je_plattform = Counter(_quelle(z["a"]) for z in passt)
    hinweise = []
    for plattform in sp.MIT_EINGANG:
        angelegt = bool((auftraege.get(plattform) or {}).get("angelegt"))
        if not angelegt:
            hinweise.append(f"{plattform}: kein Suchauftrag angelegt")
        elif not je_plattform.get(plattform):
            hinweise.append(f"{plattform}: Suchauftrag angelegt, aber im Zeitraum kein passendes Inserat eingegangen")
    arten_ohne = [art for art in profil.get("arten") or [] if not any(z["b"].art == art for z in passt)]
    if arten_ohne:
        hinweise.append("ohne passendes Inserat: " + ", ".join(arten_ohne))
    regionen_ohne = []
    if profil.get("gebiet") == sp.REGIONEN:
        regionen_ohne = [r for r in profil["gebiet_regionen"] if not any((z["a"].get("plz") or "").startswith(r) for z in passt)]
        if regionen_ohne:
            hinweise.append("PLZ-Bereiche ohne passendes Inserat: " + ", ".join(f"{r}…" for r in regionen_ohne))
    unklar = len(treffer) - len(passt)
    anteil_unklar = _anteil(unklar, len(treffer))
    if anteil_unklar is not None and anteil_unklar >= UNKLAR_HOCH and len(treffer) >= 4:
        hinweise.append(f"{round(anteil_unklar * 100)} % der Treffer sind „unklar“ – Angaben fehlen (Art, Ort, Preis, EZ oder km)")
    return {"id": profil.get("id"), "name": profil["name"], "gebiet": sp.gebiet_text(profil),
            "passt": len(passt), "unklar": unklar, "fahrzeuge": sum(1 for g in fahrzeuge(passt) if g & passt_ids),
            "je_plattform": dict(sorted(je_plattform.items())), "arten_ohne_treffer": arten_ohne, "regionen_ohne_treffer": regionen_ohne,
            "anteil_unklar": anteil_unklar, "hinweise": hinweise}


def beginn(jetzt: datetime, tage: int) -> datetime:
    """Zeitraum = ``tage`` Kalendertage einschließlich heute, ab Mitternacht (Kennzahlen und Zeitlücken zählen dieselben Tage)."""
    return datetime.combine(jetzt.date() - timedelta(days=tage - 1), datetime.min.time())


def auswerten(zeilen: list[dict], eingangstage: dict[str, set[date]], preisaenderungen: int, laeufe: list[dict],
              profile: list[tuple[dict, dict]], jetzt: datetime, tage: int) -> dict:
    """Alles zusammen; ``zeilen`` = bewertete Inserate, die im Zeitraum zuerst eingingen."""
    plattformen = sorted(set(sp.MIT_EINGANG) | set(eingangstage))
    return {"tage": tage, "von": beginn(jetzt, tage).isoformat(timespec="seconds"), "bis": jetzt.isoformat(timespec="seconds"),
            "kennzahlen": kennzahlen(zeilen, tage, preisaenderungen, laeufe),
            "zeitluecken": zeitluecken(eingangstage, plattformen, jetzt.date(), tage),
            "gebietsluecken": gebietsluecken(zeilen),
            "profile": [profilluecken(p, auftraege, zeilen) for p, auftraege in profile]}


# ---------------------------------------------------------------- Daten einsammeln
def messe(cfg: dict, db, basis, tage: int = STANDARD_TAGE, jetzt: datetime | None = None) -> dict:
    """Zeitraum ``tage`` bis ``jetzt`` messen (nur lesen). Bewertet die im Zeitraum zuerst eingegangenen Inserate – das kann bei großen
    Beständen einige Sekunden dauern."""
    from . import laufprotokoll as lp
    from .bewertung.auswertung import bewerte_alle
    from .bewertung.anschreiben import sperrgrund
    jetzt = jetzt or datetime.now()
    seit = beginn(jetzt, tage)
    seit_utc = seit.astimezone(timezone.utc).isoformat(timespec="seconds")
    zeilen = bewerte_alle(cfg, db, basis, erstmals_seit=seit.isoformat(timespec="seconds"))
    for z in zeilen:
        z["sperre_filter"] = sperrgrund({**z["a"], "status": None}, cfg)
    eingangstage: dict[str, set[date]] = {}
    # Eingang = neues oder geändertes Inserat aus Suche, Seite, Mail, Text oder Ereignis; Detailabruf und „gelöscht“ zählen nicht (QA B4).
    # Zeiten sind als Text gespeichert (UTC mit Zeitzone); ältere Einträge ohne Zeitzone verschieben die Grenze höchstens um 1–2 h.
    for plattform, zeitpunkt in db.con.execute("SELECT plattform, zeitpunkt FROM beobachtungen WHERE zeitpunkt >= ? AND kanal <> 'detail' "
                                               "AND ereignis_typ IN ('neu', 'geaendert')", (seit_utc,)):
        t = _zeit(zeitpunkt)
        if t and t >= seit:
            eingangstage.setdefault(plattform, set()).add(t.date())
    # Preisänderung = Eintrag im Preisverlauf mit einem früheren Eintrag desselben Inserats (der erste Preis ist keine Änderung)
    preisaenderungen = db.con.execute(
        "SELECT COUNT(*) FROM preis_historie p WHERE p.zeitpunkt >= ? AND EXISTS "
        "(SELECT 1 FROM preis_historie q WHERE q.inserat_id = p.inserat_id AND q.id < p.id)", (seit_utc,)).fetchone()[0]
    laeufe = lp.Laufprotokoll(db).letzte(None, seit=seit)
    speicher = sp.SuchprofilSpeicher(db)
    profile = [(p, speicher.auftraege(p["id"])) for p in speicher.liste(nur_aktive=True)]
    return auswerten(zeilen, eingangstage, preisaenderungen, laeufe, profile, jetzt, tage)
