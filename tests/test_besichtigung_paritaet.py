"""Die Handy-App rechnet offline in JavaScript – sie muss exakt so rechnen wie der Server (Python).

Erzeugt viele zufällige, aber reproduzierbare Besichtigungen und vergleicht beide Ergebnisse vollständig.
Läuft nur, wenn Node.js installiert ist (in GitHub Actions immer der Fall)."""
import json
import random
import shutil
import subprocess
from datetime import date

import pytest

from tests.daten import BASIS
from tests.test_besichtigung import GRUND, KATALOG, vollstaendig
from wmscout.bewertung.besichtigung import berechne, mangel_index

JS = BASIS / "wmscout" / "web" / "static" / "besichtigung.js"
HEUTE = "2026-10-13"


def faelle(n: int = 600) -> list[dict]:
    rng = random.Random(7)
    index = list(mangel_index(KATALOG).values())
    liste = [{"daten": vollstaendig(), "basis": GRUND}]
    for _ in range(n):
        d = {"pruefpunkte": {p["key"]: rng.random() < 0.8 for p in KATALOG["pruefpunkte"]},
             "messungen": {
                 "feuchtigkeit": [{"bereich": rng.choice(["Heck links", "Heck rechts", "Bad", "Dachluke", "", "Bug"]),
                                   "wert": rng.choice([rng.randint(5, 45), round(rng.uniform(5, 45), 1), "", "abc",
                                                       f"{rng.randint(10, 30)},5"])}
                                  for _ in range(rng.randint(0, 12))],
                 "reifen": [{"position": rng.choice(["VL", "VR", "HL", "HR", ""]),
                             "dot": rng.choice([f"{rng.randint(1, 53):02d}{rng.randint(14, 26):02d}"] * 6
                                               + ["9918", "", "12", "0130", " 2318 "])}
                            for _ in range(rng.randint(0, 6))]},
             "km_abgelesen": rng.choice([None, "", 80000, 85000, 91000, 120500, "abc", "99000"]),
             "maengel": [], "anpassung": {"betrag": rng.choice([0, -200, 350, "", "x", "125,5"])}}
        for m in rng.sample(index, rng.randint(0, 8)):
            e = {"key": m["key"], "notiz": "n"}
            if "stufen" in m:
                e["stufe"] = rng.choice(list(m["stufen"]) + [None])
            if m.get("frei") or rng.random() < 0.15:
                e["betrag"] = rng.choice([rng.randint(50, 3000), "", "abc", 333.33])
                e["name"] = rng.choice(["Markise fehlt", "", "  Sat fehlt "])
            d["maengel"].append(e)
        if rng.random() < 0.1:
            d["maengel"].append({"key": "gibtsnicht"})
        basis = {**GRUND, "angebot": rng.randint(5000, 90000), "max_ek": rng.randint(5000, 95000),
                 "marktwert_privat": rng.randint(8000, 120000), "reparaturrisiko": rng.choice([0, 500, 1500, 2500, 4000]),
                 "differenzbesteuerung": rng.choice([True, False]), "km_anzeige": rng.choice([None, 85000, 0])}
        liste.append({"daten": d, "basis": basis})
    return liste


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js nicht installiert")
def test_javascript_rechnet_wie_python(tmp_path):
    liste = faelle()
    eingabe = tmp_path / "faelle.json"
    eingabe.write_text(json.dumps({"katalog": KATALOG, "faelle": liste, "heute": HEUTE}), encoding="utf-8")
    skript = ("const B=require(process.argv[1]);const fs=require('fs');const e=JSON.parse(fs.readFileSync(process.argv[2]));"
              "process.stdout.write(JSON.stringify(e.faelle.map(f=>B.berechne(e.katalog,f.daten,f.basis,e.heute))));")
    r = subprocess.run(["node", "-e", skript, str(JS), str(eingabe)], capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    heute = date.fromisoformat(HEUTE)
    for i, (fall, ergebnis_js) in enumerate(zip(liste, js, strict=True)):
        ergebnis_py = json.loads(json.dumps(berechne(KATALOG, fall["daten"], fall["basis"], heute)))
        assert ergebnis_js == ergebnis_py, f"Fall {i} weicht ab:\n{json.dumps(fall, ensure_ascii=False)}"
