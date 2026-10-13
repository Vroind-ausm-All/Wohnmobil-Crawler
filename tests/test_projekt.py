"""Projektkonfiguration für Claude Code: Agenten und Skills haben gültiges Frontmatter, Prüfagenten nur Lesewerkzeuge."""
from pathlib import Path

import pytest
import yaml

WURZEL = Path(__file__).resolve().parents[1]
AGENTEN = {
    "scout-architect", "windows-bootstrap", "source-researcher", "source-integrations",
    "scout-data-engineer", "acquisition-analyst", "scout-ui-engineer", "qa-security-reviewer",
}
NUR_LESEND = {"scout-architect", "source-researcher", "qa-security-reviewer"}
BEKANNTE_WERKZEUGE = {"Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebSearch", "WebFetch"}


def frontmatter(pfad):
    text = pfad.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{pfad}: Frontmatter fehlt"
    kopf, rumpf = text[4:].split("\n---\n", 1)
    return yaml.safe_load(kopf), rumpf


def test_alle_agenten_vorhanden():
    assert {p.stem for p in (WURZEL / ".claude/agents").glob("*.md")} == AGENTEN


@pytest.mark.parametrize("name", sorted(AGENTEN))
def test_agent_frontmatter(name):
    kopf, rumpf = frontmatter(WURZEL / ".claude/agents" / f"{name}.md")
    assert kopf["name"] == name and len(kopf["description"]) > 80
    assert kopf["model"] in {"opus", "sonnet", "haiku", "inherit"}
    werkzeuge = {w.strip() for w in kopf["tools"].split(",")}
    assert werkzeuge <= BEKANNTE_WERKZEUGE
    if name in NUR_LESEND:
        assert not werkzeuge & {"Edit", "Write"}, f"{name} ist ein Prüfagent und darf nicht schreiben"
    assert "CLAUDE.md" in rumpf and len(rumpf) > 1500                 # ausführlicher System-Prompt mit Projektregeln


def test_skill_und_loop():
    kopf, rumpf = frontmatter(WURZEL / ".claude/skills/scout-cycle/SKILL.md")
    assert kopf["name"] == "scout-cycle" and kopf["description"]
    for buchstabe, schritt in zip("ABCDEFGH", ("ANALYZE", "PLAN", "IMPLEMENT", "VERIFY", "REVIEW", "FIX", "COMPLETE", "NEXT"), strict=True):
        assert f"Schritt {buchstabe} – {schritt}" in rumpf
    loop = (WURZEL / ".claude/loop.md").read_text(encoding="utf-8")
    assert "main" in loop and "Freigabe" in loop
