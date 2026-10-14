"""Projektkonfiguration für Claude Code und Projektdokumente.

Prüft: Agenten und Skill haben gültiges Frontmatter, Prüfagenten nur Lesewerkzeuge, die Grenzen des
Entwicklungsablaufs stehen im Skill, der Wartungsauftrag hat seine zehn Punkte, und jeder Beleg `datei:zeile` in den
Projektdokumenten zeigt auf eine existierende Zeile. Grenze: Ob die Zeile inhaltlich noch passt, prüft der Test nicht;
erfasst werden nur Belege in Backticks.
"""
import codecs
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


# Echte Verkäufer-Profilnamen aus Originalseiten, die schon einmal im Arbeitsbaum standen (QA H1-R). Als ROT13 und als
# Muster gespeichert, damit dieser Test nicht selbst trifft. Neue Funde hier ergänzen.
_ECHTE_NAMEN_ROT13 = (r"\oibyxre\o", r"\o(?:ue|uree)\o\.?\f*jvr\o")


def test_keine_echten_verkaeufernamen_im_repository():
    """Personenbezogene Daten aus Originalseiten gehören nicht ins Repository – Tests und Doku nutzen erfundene Namen.
    Geprüft werden alle getrackten Dateien außer docs/ (die Projektdokumente bereinigt der Orchestrator)."""
    muster = [re.compile(codecs.decode(m, "rot13"), re.I) for m in _ECHTE_NAMEN_ROT13]
    namen = subprocess.run(["git", "ls-files"], cwd=WURZEL, capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(namen) > 50                                            # die Liste ist tatsächlich gefüllt
    treffer = []
    for name in namen:
        pfad = WURZEL / name
        if name.startswith("docs/") or not pfad.is_file():
            continue
        text = pfad.read_bytes().decode("utf-8", errors="ignore")
        treffer += [f"{name}:{text.count(chr(10), 0, m.start()) + 1}" for mu in muster for m in mu.finditer(text)]
    assert not treffer, treffer
