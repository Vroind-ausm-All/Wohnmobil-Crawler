# Arbeitsprotokoll (WORKLOG)

Neueste Einträge oben. Vorlage und Regeln: Skill `scout-cycle` (`.claude/skills/scout-cycle/SKILL.md`).
Nur tatsächlich Erledigtes und tatsächlich ausgeführte Tests; nicht Ausgeführtes heißt „nicht geprüft“.

---

## Phase 0 – Bestandsaufnahme (13.10.2026)

### Hinweis zur Agentennutzung

Die Projekt-Agenten in `.claude/agents/` werden von Claude Code erst beim Start einer Sitzung geladen. In der Sitzung,
in der sie angelegt wurden, waren sie noch nicht aufrufbar (Fehlermeldung „Agent type 'scout-architect' not found“).
Daher liefen **Architektur-Bestandsaufnahme** (eingebauter Nur-Lese-Agent `Plan`) und **Quellenrecherche**
(eingebauter Agent mit Web-Recherche) mit dem Auftrag, die jeweilige Agentendefinition zu lesen und exakt danach zu
handeln. Nach einem Neustart der Sitzung waren die Projekt-Agenten geladen; ab der **QA-Bestandsaufnahme** laufen alle
Aufträge über die echten Projekt-Agenten.

### P0-01 – Repository-Zustand und Entwicklungsbasis · Status: DONE

- Phase: 0
- Verantwortlicher Agent: Orchestrator
- Ergebnis:
  - `main` enthält nur den Initial-Commit.
  - Integrationszweig `claude/gifted-heisenberg-d1cjlr`, Commit 3f75f67.
  - PR #1 (Grundlage) und PR #2 (Handy-App) sind gemergt.
  - PR #2 war auf den Arbeitszweig von PR #1 gestapelt und kam nach dessen Merge zunächst nicht im Integrationszweig
    an. Die Handy-App wurde per Merge-Commit 3f75f67 nachgezogen. Das Inhaltsverzeichnis ist identisch mit dem
    geprüften Stand; vor dem Push liefen 81 Tests und ruff grün.
  - Arbeitszweige `claude/phase1-grundlage` und `claude/handy-app` sind gemergt. Keine ungesicherten Änderungen.
- Sichere Basis: Integrationszweig. Arbeitszweig für Phase 0: `claude/phase0-agentensystem`.
- Folge: ADR-008 (keine gestapelten PRs; Basis ist immer der Integrationszweig).

### P0-02 – Agentensystem, Regeln, Skill, Loop · Status: DONE

- Phase: 0
- Verantwortlicher Agent: Orchestrator
- Geänderte Dateien:
  - `CLAUDE.md`
  - `.claude/agents/*.md` (8 Dateien)
  - `.claude/skills/scout-cycle/SKILL.md`
  - `.claude/loop.md`
  - `.gitignore` (`.claude/settings.local.json`)
  - `tests/test_projekt.py`
- Implementierte Funktionen:
  - Acht Agenten mit YAML-Frontmatter (`name`, `description`, `tools`, `model`).
  - Prüfagenten nur mit Lesewerkzeugen: `scout-architect` (Read, Grep, Glob); `qa-security-reviewer` und
    `source-researcher` ohne Edit/Write.
  - Modelle: opus für Architektur, Ankaufsbewertung und QA; sonnet für die übrigen Agenten.
  - SCOUT DEVELOPMENT LOOP (Schritte A–H, Grenzen: 5 Pakete, 3 Korrekturrunden, 3 parallele Agenten, kein Merge nach
    `main`, Freigabe je Phase).
- Tests: `.venv/bin/python -m pytest -q`; `.venv/bin/python -m ruff check .`
- Testergebnis:
  - Beim ersten Lauf fiel der YAML-Parser durch: Beschreibungen mit „: “ waren ungültiges YAML. Behoben durch
    Anführungszeichen.
  - Danach: `91 passed`, ruff „All checks passed!“.
  - `test_projekt.py` prüft jetzt dauerhaft:
    - Frontmatter
    - Dateiname = `name`
    - bekannte Werkzeuge
    - keine Schreibwerkzeuge für Prüfagenten
    - Skill-Schritte A–H
- Bekannte Risiken: Die Werkzeugbeschränkung von `qa-security-reviewer` erlaubt `Bash` (für Tests), damit sind
  technisch auch Schreibbefehle möglich. Eingeschränkt wird das nur über den System-Prompt.
- Commit/PR: 185dc0b (Zweig `claude/phase0-agentensystem`).

### P0-03 – Architektur- und Risikoüberblick · Status: DONE

- Verantwortlicher Agent: scout-architect (ausgeführt als `Plan`-Agent nach Definition, siehe Hinweis oben)
- Ergebnis:
  - `docs/ARCHITECTURE.md` (ersetzt `docs/ARCHITEKTUR.md`) mit Modulübersicht, Datenfluss, Ist-Schema,
    18 Risiken (2 KRITISCH, 6 HOCH), Zieldatenmodell, Migrationsschritten M1–M3 und Nebenläufigkeit.
  - `docs/DECISIONS.md` mit ADR-001 bis ADR-015.
  - Urteil des Architekten zum Phasenplan: **FREIGABE MIT AUFLAGEN**.
    - (a) R1/R2 schon in Phase 1.
    - (b) Backup, `schema_version`, WAL/Laufsperre und Lock-Entflechtung in Phase 1.
    - (c) `UNIQUE(quelle, anzeigen_id)` vor der zweiten Quelle.
    - (d) UI-Bestätigung „kontaktiert“ in Phase 1.
  - Alle Auflagen sind in `ROADMAP.md` übernommen (P1-01 bis P1-07, P2-02).
- Nachprüfung durch den Orchestrator im Code bestätigt:
  - R1: `config.yaml:196` `auto_suche_stunden: 3`; der Importer warnt nur.
  - R2: Chrome-User-Agent in `config.yaml:32`.
  - R3: `ALTER TABLE` ohne Backup in `datenbank.py:49-53`.
  - R5: `report.html` setzt beim Kopieren „kontaktiert“; `mobil.js` ebenso.
  - R14: `api.py:434-437` speichert trotz Konflikt.
- Korrektur: Die erste Fassung von ADR-005 behauptete, der Kleinanzeigen-Abruf laufe nur auf Start durch den
  Betreiber. Das ist falsch, denn die Auto-Suche ist standardmäßig aktiv. ADR-005 ist korrigiert.

### P0-04 – Quellenrecherche · Status: DONE (mit Einschränkung)

- Verantwortlicher Agent: source-researcher (ausgeführt als eingebauter Agent nach Definition)
- Ergebnis: `docs/SOURCES.md`
  - Belegt: Kleinanzeigen, mobile.de (AGB-HB), AutoScout24 und Meta untersagen das automatisierte Auslesen.
  - Zulässig und ohne Vertrag testbar sind zwei unabhängige Kanäle: manueller Import und E-Mail-Suchbenachrichtigungen.
  - Einziger belegter offizieller Lesezugang: mobile.de API-Account (Konditionen unbekannt).
  - Neue Entscheidung ADR-010: Beim manuellen Import ruft der Server die URL nicht selbst ab.
- Einschränkung:
  - In der Recherche-Umgebung schlug jeder direkte Seitenabruf fehl (DNS), deshalb stammen die Zitate aus
    Suchindex-Auszügen.
  - `robots.txt`: nicht geprüft.
  - Das Gegenlesen der Originale ist Paket P2-01 (BLOCKED, braucht einen Menschen mit Browser).

### P0-05 – QA-Bestandsaufnahme · Status: DONE

- Verantwortlicher Agent: qa-security-reviewer (Projekt-Agent). Der erste Versuch brach am Nutzungslimit der Sitzung
  ohne Ergebnis ab; der zweite Versuch lief vollständig.
- Tests: `pytest -q -p no:cacheprovider`, `ruff check .`, Coverage außerhalb der `.venv`, Missbrauchsskripte im
  Scratchpad mit Temp-DB.
- Testergebnis:
  - `91 passed in 17.16s`
  - ruff: „All checks passed!“
  - Abdeckung 88 %. Schwach abgedeckt sind `netz.py` (27 %), `app.py` (52 %) und `benachrichtigung.py` (55 %).
- Review-Ergebnis: **FREIGABE MIT AUFLAGEN**
  - Kein KRITISCH-Befund im Anwendungscode.
  - Fünf HOCH-Befunde: Q1 Max-EK aus Angebotspreis ohne EZ, Q2 negativer Content-Length, Q3 keine Löschfunktion für
    Verkäuferdaten, dazu R1 und R5.
  - Zehn MITTEL- und fünf NIEDRIG-Befunde.
  - Keine XSS-Lücke und keine Geheimnisse im Repository gefunden.
- Übernahme: Alle Befunde stehen in `docs/TEST-REPORT.md` und sind in der Roadmap Paketen zugeordnet
  (neu: P1-11 bis P1-15).
- Hinweis der QA: Sie meldete Änderungen im Arbeitsbaum, die nicht von ihr stammten. Das waren die parallel vom
  Orchestrator geschriebenen Doku-Dateien (ROADMAP, WORKLOG, ARCHITECTURE). Die QA hat nur unter `/tmp` geschrieben.
