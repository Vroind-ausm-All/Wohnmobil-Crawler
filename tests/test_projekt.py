"""Projektkonfiguration für Claude Code und Projektdokumente.

Prüft: Agenten und Skill haben gültiges Frontmatter, Prüfagenten nur Lesewerkzeuge, die Grenzen des
Entwicklungsablaufs stehen im Skill, der Wartungsauftrag hat seine zehn Punkte, und jeder Beleg `datei:zeile` in den
Projektdokumenten zeigt auf eine existierende Zeile. Grenze: Ob die Zeile inhaltlich noch passt, prüft der Test nicht;
erfasst werden nur Belege in Backticks.
"""
import hashlib
import re
import subprocess
from pathlib import Path

import pytest
import yaml

WURZEL = Path(__file__).resolve().parents[1]
MODELLE = {
    "scout-architect": "opus", "acquisition-analyst": "opus", "qa-security-reviewer": "opus",
    "windows-bootstrap": "sonnet", "source-researcher": "sonnet", "source-integrations": "sonnet",
    "scout-data-engineer": "sonnet", "scout-ui-engineer": "sonnet",
}
LESEWERKZEUGE = {"Read", "Grep", "Glob", "WebSearch", "WebFetch"}
ERLAUBTE_WERKZEUGE = {                                       # Prüfagenten: nur lesen (QA zusätzlich Bash für Tests, ADR-018)
    "scout-architect": LESEWERKZEUGE,
    "source-researcher": LESEWERKZEUGE,
    "qa-security-reviewer": LESEWERKZEUGE | {"Bash"},
}
SCHREIBWERKZEUGE = {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}
DOKUMENTE = ["docs/ARCHITECTURE.md", "docs/TEST-REPORT.md", "docs/ROADMAP.md", "docs/DECISIONS.md", "docs/WORKLOG.md"]


def frontmatter(pfad):
    text = pfad.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{pfad}: Frontmatter fehlt"
    kopf, rumpf = text[4:].split("\n---\n", 1)
    return yaml.safe_load(kopf), rumpf


def test_alle_agenten_vorhanden():
    assert {p.stem for p in (WURZEL / ".claude/agents").glob("*.md")} == set(MODELLE)


@pytest.mark.parametrize("name", sorted(MODELLE))
def test_agent_frontmatter(name):
    kopf, rumpf = frontmatter(WURZEL / ".claude/agents" / f"{name}.md")
    assert set(kopf) == {"name", "description", "tools", "model"}, "keine weiteren Schlüssel (z. B. permissionMode)"
    assert kopf["name"] == name and len(kopf["description"]) > 80
    assert kopf["model"] == MODELLE[name]
    werkzeuge = {w.strip() for w in kopf["tools"].split(",")}
    assert werkzeuge <= ERLAUBTE_WERKZEUGE.get(name, SCHREIBWERKZEUGE), f"{name}: unzulässige Werkzeuge {werkzeuge}"
    assert "CLAUDE.md" in rumpf and len(rumpf) > 1500                 # ausführlicher System-Prompt mit Projektregeln
    if name not in ERLAUBTE_WERKZEUGE:
        assert "Kein `git commit`" in rumpf                         # Implementierungsagenten committen nicht selbst


def test_skill_grenzen():
    kopf, rumpf = frontmatter(WURZEL / ".claude/skills/scout-cycle/SKILL.md")
    assert set(kopf) == {"name", "description"} and kopf["name"] == "scout-cycle"
    for buchstabe, schritt in zip("ABCDEFGH", ("ANALYZE", "PLAN", "IMPLEMENT", "VERIFY", "REVIEW", "FIX", "COMPLETE", "NEXT"), strict=True):
        assert f"Schritt {buchstabe} – {schritt}" in rumpf
    for grenze in ("höchstens **5**", "höchstens **3**, danach `BLOCKED`", "| Merge nach `main` | **niemals** |",
                   "**nur nach Freigabe**", "eigenen `git worktree`", "im Integrationszweig gemergt"):
        assert grenze in rumpf, grenze


def test_wartungsauftrag():
    loop = (WURZEL / ".claude/loop.md").read_text(encoding="utf-8")
    punkte = re.findall(r"^(\d+)\. \*\*", loop, flags=re.M)
    assert punkte == [str(i) for i in range(1, 11)]
    assert "**Niemals nach `main` mergen**" in loop and "**Keine neue Hauptphase**" in loop


def _dateien():
    namen = subprocess.run(["git", "ls-files"], cwd=WURZEL, capture_output=True, text=True, check=True).stdout.split()
    nach_name = {}
    for n in namen:
        nach_name.setdefault(Path(n).name, set()).add(n)
        nach_name.setdefault(n, set()).add(n)
    return nach_name


BELEG = re.compile(r"`([\w./-]+\.(?:py|yaml|html|js|bat|sh|toml|md|txt)):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)`")


@pytest.mark.parametrize("dokument", DOKUMENTE)
def test_belege_zeigen_auf_existierende_zeilen(dokument):
    dateien, fehler, geprueft = _dateien(), [], 0
    for datei, bereiche in BELEG.findall((WURZEL / dokument).read_text(encoding="utf-8")):
        kandidaten = dateien.get(datei) or dateien.get(Path(datei).name) or []
        if len(kandidaten) != 1:
            fehler.append(f"{datei}: Datei nicht eindeutig gefunden ({kandidaten})")
            continue
        zeilen = len((WURZEL / next(iter(kandidaten))).read_text(encoding="utf-8").splitlines())
        hoechste = max(int(z) for z in re.findall(r"\d+", bereiche))
        geprueft += 1
        if hoechste > zeilen:
            fehler.append(f"{datei}:{bereiche} – Datei hat nur {zeilen} Zeilen")
    assert not fehler, "\n".join(fehler)
    if dokument in ("docs/ARCHITECTURE.md", "docs/TEST-REPORT.md"):
        assert geprueft > 20                                          # Belege werden tatsächlich gefunden


# Echte Verkäufer-Profilnamen aus Originalseiten, die schon einmal im Arbeitsbaum standen (QA H1-R). Nur als gesalzene
# SHA-256-Werte normalisierter Wortfolgen (1–2 Wörter, klein) gespeichert, damit die Namen nicht lesbar im Repository
# stehen (QA M7-1). Neue Funde: hashlib.sha256((_SALZ + "wortfolge").encode()).hexdigest() ergänzen.
_SALZ = "wmscout-h1r"
_ECHTE_NAMEN_SHA256 = {
    "96d20e9324977ad3e0465e00e6644967569eb95b958b005be3ccd8f5f60a17c5",
    "4b880c8a98e9edfd6b2b08fda1f86b47d5140d61a866dcedbca7b72103d215c2",
    "a892721fbbe33edc99f8c531bc461686acc296092bd41efad25b6a021ff85cda",
}
_WORT = re.compile(r"[^\W\d_]+")


def _namens_treffer(text: str) -> list[int]:
    """Zeilennummern, in denen eine Wortfolge (1 oder 2 Wörter) einem gespeicherten Hash entspricht."""
    treffer = []
    for nr, zeile in enumerate(text.splitlines(), 1):
        woerter = [w.lower() for w in _WORT.findall(zeile)]
        folgen = woerter + [f"{a} {b}" for a, b in zip(woerter, woerter[1:], strict=False)]
        if any(hashlib.sha256((_SALZ + f).encode()).hexdigest() in _ECHTE_NAMEN_SHA256 for f in folgen):
            treffer.append(nr)
    return treffer


def test_namensschutz_erkennt_gespeicherte_wortfolgen():
    """Gegenprobe ohne echte Namen: ein künstlich gespeicherter Hash wird gefunden, auch über Satzzeichen hinweg."""
    _ECHTE_NAMEN_SHA256.add(hashlib.sha256((_SALZ + "fr beispiel").encode()).hexdigest())
    try:
        assert _namens_treffer("x\nHallo Fr. Beispiel,\n") == [2]
        assert _namens_treffer("Hallo Frau Beispiel") == []
    finally:
        _ECHTE_NAMEN_SHA256.discard(hashlib.sha256((_SALZ + "fr beispiel").encode()).hexdigest())


def test_keine_echten_verkaeufernamen_im_repository():
    """Personenbezogene Daten aus Originalseiten gehören nicht ins Repository – Tests und Doku nutzen erfundene Namen.
    Geprüft werden alle getrackten Dateien einschließlich docs/."""
    namen = subprocess.run(["git", "ls-files"], cwd=WURZEL, capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(namen) > 50                                            # die Liste ist tatsächlich gefüllt
    treffer = []
    for name in namen:
        pfad = WURZEL / name
        if not pfad.is_file() or pfad.suffix in (".png", ".jpg", ".ico", ".zip"):
            continue
        text = pfad.read_bytes().decode("utf-8", errors="ignore")
        treffer += [f"{name}:{nr}" for nr in _namens_treffer(text)]
    assert not treffer, treffer
