# Arbeitsprotokoll (WORKLOG)

Neueste Einträge oben. Vorlage und Regeln: Skill `scout-cycle` (`.claude/skills/scout-cycle/SKILL.md`).
Nur tatsächlich Erledigtes und tatsächlich ausgeführte Tests. Nicht Ausgeführtes heißt „nicht geprüft“, ein fehlender
Wert „–“.

---

## Phase 1 (vorgezogen) – Datensicherung und Migrationsrahmen (14.10.2026)

### P1-02 / P1-03 – Sicherung, Wiederherstellung, Migrationsrahmen · Status: REVIEW

- **Phase:** 1, vorgezogen als Voraussetzung für die Team-Übersicht (Tabelle `bearbeitung`, Schema-Version 3) und
  für jede weitere Schemaänderung (Regel 3).
- **Verantwortliche Agenten:** `scout-data-engineer` (Umsetzung, zwei Korrekturrunden), `qa-security-reviewer`
  (zwei Prüfungen), Orchestrator (Doku-Belege, Commits).
- **Zweig/Commits:** `claude/phase1-sicherung-migration` (Worktree): 1b104ad (Umsetzung), e8b1be1 (Runde 1),
  Korrekturrunde 2 (dieser Commit).
- **Geänderte Dateien:**
  - `wmscout/sicherung.py` (neu): `sichere`, `wiederherstellen` (mit `--bestaetigt`, `--ohne-fotos`), Aufbewahrung
  - `wmscout/migrationen.py` (neu): `schema_version`, Schritte 2 und 3, `migriere`, `pruefe_wiederherstellbar`
  - `wmscout/datenbank.py` (ruft `migriere` auf), `wmscout/team.py` (kein eigenes Schema mehr), `wmscout/app.py`
  - `scout.py` (`sichern`, `wiederherstellen`), `config.yaml` (Abschnitt `sicherung`), `README.md`
  - Tests: `tests/test_sicherung.py`, `tests/test_migration.py`
- **Implementierte Funktionen:**
  - Sicherung über die SQLite-Backup-API mit `integrity_check`, Fotos als ZIP; Aufbewahrung `behalten` aus der
    Konfiguration; eigene und gerade verwendete Sicherungen sind vor dem Aufräumen geschützt (auch bei Uhrsprung).
  - Wiederherstellung nur mit Bestätigung: Quelle nur lesend in eine Arbeitskopie, Prüfung (Integrität, Scout-DB,
    Version), Sperrprüfung vor und kurz vor dem Austausch, Vorher-Sicherung, atomarer Austausch, Fotos mit Rückweg.
  - Migrationen: Sicherung vorher (ohne Aufräumen), je Schritt eine Transaktion, idempotent, parallel startende
    Prozesse sicher (Reservierung der Sicherungsnummer, Neuprüfung), „DB neuer als Code“ bricht verständlich ab.
  - Windows-taugliche Datei-URIs (Laufwerk, UNC), CLI-Meldungen ohne Traceback, Typprüfung der Konfiguration.
- **Tests:** `pytest -q -p no:cacheprovider`, `ruff check .` (Python der Haupt-`.venv`), Mutationsläufe der Agenten
  und der QA in Kopien, QA-Reproduktionsskripte (Uhrsprung, Parallelprozesse, defektes ZIP, Sonderzeichen-Pfade)
- **Testergebnis (Orchestrator):** nach Korrekturrunde 2 `182 passed`; nach Ergänzung N-1 `182 passed`, ruff „All checks passed!“.
  Agent: 55 Mutanten, nach Nachträgen alle getötet (Volllauf nach den letzten Tests nicht wiederholt).
- **Review-Ergebnis:**
  1. QA-Runde 1 (1b104ad): ABLEHNUNG – K1 (älteste Sicherung zurückspielen → leere DB), H1, M1–M5, N1–N4.
  2. QA-Runde 2 (e8b1be1): FREIGABE MIT AUFLAGEN – alle Runde-1-Befunde behoben; neu Q-F1–Q-F10 (MITTEL/NIEDRIG).
  3. Korrekturrunde 2: Q-F1–Q-F10 und fehlende Mutantentests bearbeitet.
  4. QA-Runde 3 (001fe60): **FREIGABE** – alle Q-F behoben (eigene Nachstellung), 64 von 69 Mutanten getötet (alle 55
     des Agenten); 8 Prozesse gleichzeitig: 8 eindeutige, intakte Sicherungen. Offen: N-1 (MITTEL, Schutztest „Aufräumen
     löscht nie die DB“) → vom Orchestrator ergänzt, Mutant X1 jetzt erkannt; N-2..N-7 (NIEDRIG) → Backlog.
- **Bekannte Risiken:** Windows und Netzlaufwerke nicht real geprüft; Sperrprüfung erkennt nur aktive
  Schreibvorgänge (App vorher beenden; echte Laufsperre mit P1-04); Sicherungen enthalten personenbezogene Daten
  (Löschfristen mit P1-14a).
- **CI Windows (PR #5):** 7 Tests rot – offene SQLite-Verbindungen in Tests sperrten unter Windows die Datei, ein
  Testordner enthielt `?`. Behoben (Tests schließen Verbindungen; `_ersetze` wiederholt `os.replace` bei kurzzeitiger
  Sperre durch Virenscanner/Indexdienst, danach Meldung „in Benutzung“; zwei neue Tests). Lokal 184 passed.
- **Backlog aus QA-Runde 3:** N-2 verwaiste `-journal`-Begleitdateien von Arbeitskopien; N-3 Meldung bei
  Schreibschutz; N-4 Doppelfehler im Fotoschritt; N-5 Tests für `ordner: ""`, Foto-`.teil` im Fehlerpfad,
  ZIP_DEFLATED-Fehler, CLI-Hinweis `--ohne-fotos`; N-6 `\\?\unc\` in Kleinschreibung.
- **Nächster sinnvoller Schritt:** PR gegen `claude/gifted-heisenberg-d1cjlr`; danach Team-Übersicht (Tabelle
  `bearbeitung`, Schema-Version 3).

## Phase 0 – Bestandsaufnahme (13.10.2026)

Zweig `claude/phase0-agentensystem` (Basis `claude/gifted-heisenberg-d1cjlr`, Commit 3f75f67).
Commits: 185dc0b, 548c1fc, c31d668, aadfd67 und der Korrektur-Commit zu P0-07.

### Hinweis zur Agentennutzung

Claude Code lädt die Projekt-Agenten in `.claude/agents/` erst beim Start einer Sitzung. In der Sitzung, in der sie
angelegt wurden, ließen sie sich noch nicht aufrufen. Die Fehlermeldung lautete: „Agent type 'scout-architect' not found“.

Deshalb liefen zwei Aufträge über eingebaute Agenten, jeweils mit der Anweisung, die Agentendefinition zu lesen und
exakt danach zu handeln:
- die Architektur-Bestandsaufnahme (P0-03) über den eingebauten Nur-Lese-Agenten `Plan`,
- die Quellenrecherche (P0-04) über einen eingebauten Agenten mit Web-Recherche.

Nach einem Neustart der Sitzung waren die Projekt-Agenten geladen. Ab P0-05 liefen alle Aufträge über die echten
Projekt-Agenten.

### P0-07 – Unabhängige Prüfung der Planung · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `scout-architect` und `qa-security-reviewer` (Projekt-Agenten, parallel und unabhängig);
  Korrekturen durch den Orchestrator
- **Geänderte Dateien (Korrekturrunde 1 von höchstens 3):**
  - `docs/ARCHITECTURE.md`, `DECISIONS.md`, `ROADMAP.md`, `TEST-REPORT.md`, `WORKLOG.md`
  - `.claude/skills/scout-cycle/SKILL.md`, `.claude/loop.md`, `.claude/agents/*.md`
  - `tests/test_projekt.py`
- **Implementierte Änderungen:**
  - **Belege:** Falsche Datei:Zeile-Belege korrigiert:
    - R1: `importer.py:39-40`
    - R7: `app.py:59,102`, `scout.py:198`, `api.py:54`
    - R8: `importer.py:108-125`
    - R18: `pyproject.toml:6`
  - **Neue Risiken:**
    - R19: Detailabruf ohne Freigabeprüfung
    - R20: keine Push-Schnittstelle; Plattform und Eingangskanal sind vermischt
  - **Kleinanzeigen-Abschaltung:** P1-01 geteilt.
    - P1-01a schaltet ohne Abhängigkeit ab. Das ist nötig, weil Regel 12 die Abschaltung bereits verlangt.
    - P1-01b, die lokale Ausnahme, ist BLOCKED, bis der Betreiber Regel 12 selbst ändert.
    - F2 entfällt, weil ein ehrlicher User-Agent nach Regel 11 Pflicht ist.
  - **Phase 1:**
    - Abnahmekriterien vervollständigt.
    - Agenten neu zugeordnet:
      - P1-05 → `scout-data-engineer`
      - P1-11a → `source-integrations`
      - P1-11b → `scout-data-engineer`
      - P1-14 aufgeteilt in 14a (Daten/Logs) und 14b (Service Worker)
    - P1-06 ohne Schemawechsel und ohne Abhängigkeit von F7.
    - Plan für den ersten Durchgang mit exklusiven Dateien je Agent.
  - **Schemaversionen:** einheitliche Zählung 1–6 mit Schutzregeln. Die Laufsperre kommt als minimale Tabelle
    `suchlaeufe` in Version 3.
  - **Neue ADRs:**
    - ADR-016: Plattform ≠ Eingangskanal
    - ADR-017: Push-Eingang
    - ADR-018: QA mit `Bash`
    - Neues Paket P2-00
  - **Skill:** eigene Worktrees für parallele Pakete; eine Abhängigkeit gilt erst nach dem Merge als erfüllt; nur der
    Orchestrator pflegt die Planungsdokumente und committet; `loop.md` läuft nicht parallel zum Skill.
  - **Agenten:** Implementierungsagenten haben einen Abschnitt „Git“ bekommen (kein Commit, kein Push). Der Architekt
    erhält Diffs als Text.
  - **Testbericht:** Befundzahlen korrigiert (8 MITTEL, 7 NIEDRIG). R1 und R3 als KRITISCH geführt. Q1 nach der
    QA-Skala auf KRITISCH angehoben.
  - **`tests/test_projekt.py` erweitert:**
    - genaue Werkzeugmenge je Prüfagent und genaues Modell je Agent
    - kein zusätzlicher Frontmatter-Schlüssel (z. B. `permissionMode`)
    - Skill-Grenzen und die 10 Punkte von `loop.md`
    - neuer Test: Jeder `datei:zeile`-Beleg in ARCHITECTURE, TEST-REPORT, ROADMAP und DECISIONS zeigt auf eine
      existierende Zeile
- **Tests:**
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python -m ruff check .`
  - Mutationsprobe von `test_projekt.py` in einem separaten Worktree
- **Testergebnis:**
  - Mutationsprobe: Jede Mutation wird erkannt (jeweils „1 failed“):
    - alte ARCHITECTURE mit falschen Belegen
    - Architekt mit `Bash`
    - Architekt auf `haiku`
    - Skill-Grenze „5“ entfernt
    - `permissionMode` ergänzt
    - Punkt 9 aus `loop.md` entfernt
  - Gesamtsuite nach der Korrektur: `96 passed`; ruff „All checks passed!“
- **Review-Ergebnis:**
  - Architekt: **FREIGABE MIT AUFLAGEN**
    - vor Phase 1: A1, A2, A3, A12, alle umgesetzt
    - vor Phase 2: A4, umgesetzt als ADR-016/017 und Paket P2-00
    - A5–A14 übernommen
  - QA: **FREIGABE MIT AUFLAGEN**
    - kein KRITISCH-Befund im Diff
    - HOCH: B1 (Belege) und B2 (WORKLOG-Felder), beide behoben
    - MITTEL: B3, M1, M2, behoben bzw. als ADR-018 dokumentiert
    - NIEDRIG: N1–N3, behoben
  - Bestätigt von der QA: Testzahlen (81 → 91), Coverage-Werte und CI grün für aadfd67 (alle vier Jobs).
- **Bekannte Risiken:**
  - Die QA kann über `Bash` technisch schreiben. Eine technische Sperre über `.claude/settings.json` ist eine
    Berechtigungsänderung; die entscheidet der Betreiber (F13). Bis dahin vergleicht der Orchestrator vor und nach jedem
    QA-Lauf `git rev-parse HEAD`, `git status --short --ignored` und `git stash list`.
  - Die Zitate in `SOURCES.md` sind nicht am Original geprüft (P2-01).
- **Korrekturrunde 2:** Nachprüfung der QA nach Runde 1
  - Urteil: **FREIGABE MIT AUFLAGEN**. B1–B3, M1, M2, N1 und N3 sind behoben; 14 von 14 Mutationen werden erkannt;
    `96 passed`.
  - Neue Befunde: K1–K5. Kein KRITISCH- oder HOCH-Befund.
  - Behoben in Runde 2:
    - **K1:** P1-02 verlangt jetzt eine ausdrückliche Bestätigung vor der Wiederherstellung. Die technische Sperre
      während eines Laufs kommt mit P1-04.
    - **K2:** ADR-018 und Skill vergleichen jetzt `rev-parse HEAD`, `status --ignored` und `stash list`.
    - **K4:** Die Grenze der Belegprüfung steht im Test; `WORKLOG.md` wird mitgeprüft.
    - **K5:** Die Dateilisten für P1-01a und P1-12 sind ergänzt.
    - **K3:** PR-Nummer siehe unten.
  - Tests nach Runde 2: `97 passed`, ruff grün.
  - Runde 2 betraf nur MITTEL- und NIEDRIG-Befunde in der Doku. Die QA hat sie **nicht erneut geprüft**.
- **Commit/PR:** 7a99f82 (Runde 1), a8a7b89 (Runde 2); PR https://github.com/Vroind-ausm-All/Wohnmobil-Crawler/pull/3 (gegen den Integrationszweig, nicht gemergt)
- **Nächster sinnvoller Schritt:** PR gegen den Integrationszweig; Freigabe von Phase 1 und Antworten auf F1, F12
  einholen

### P0-06 – Roadmap, Backlog, Kennzahlen · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:** `docs/ROADMAP.md`, `README.md` (Verweise)
- **Implementierte Funktionen:**
  - Phasen 0–6 mit Abnahmekriterien
  - Backlog mit IDs, Prioritäten, Agenten, Abhängigkeiten und Akzeptanzkriterien (Phase 1 vollständig; Phasen 2–6 werden
    vor ihrer Freigabe ergänzt)
  - 13 Kennzahlen mit Definition und Datengrundlage
  - offene Betreiberfragen F1–F13
  - Zuordnung der früheren Phasenzählung
- **Tests:** `test_projekt.py`, Belegprüfung
- **Testergebnis:** siehe P0-07
- **Review-Ergebnis:** geprüft in P0-07 (Architekt und QA)
- **Bekannte Risiken:** Die Pakete der Phasen 2–6 sind noch grob.
- **Commit/PR:** c31d668, Korrekturen in P0-07
- **Nächster sinnvoller Schritt:** erster Phase-1-Durchgang nach Freigabe

### P0-05 – QA-Bestandsaufnahme · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `qa-security-reviewer` (Projekt-Agent). Der erste Versuch brach am Nutzungslimit der
  Sitzung ohne Ergebnis ab; der zweite lief vollständig.
- **Geänderte Dateien:** `docs/TEST-REPORT.md` (vom Orchestrator aus dem Bericht übernommen), `docs/ROADMAP.md`
  (P1-11 bis P1-15)
- **Implementierte Funktionen:** –
- **Tests:**
  - `pytest -q -p no:cacheprovider`
  - `ruff check .`
  - Coverage außerhalb der `.venv`
  - Missbrauchsskripte im Scratchpad mit temporärer Datenbank
- **Testergebnis:**
  - `91 passed in 17.16s`
  - ruff: „All checks passed!“
  - Abdeckung 88 %; schwach abgedeckt sind `netz.py` (27 %), `app.py` (52 %) und `benachrichtigung.py` (55 %)
- **Review-Ergebnis:** **FREIGABE MIT AUFLAGEN**
  - **KRITISCH:** Q1, angehoben in P0-07; dazu R1 und R3
  - **HOCH:** Q2 und Q3; dazu R5
  - **MITTEL:** acht Befunde (Q4–Q11)
  - **NIEDRIG:** sieben Befunde (Q12–Q18)
  - keine XSS-Lücke, keine Geheimnisse im Repository
- **Bekannte Risiken:** Nicht geprüft wurden:
  - Q6 und Q7 im echten Browser bzw. hinter dem Proxy
  - Performance bei großem Datenbestand
- **Commit/PR:** aadfd67
- **Nächster sinnvoller Schritt:** Befunde in Phase 1 beheben (P1-01a, P1-12, P1-13, P1-14a/b)
- **Hinweis:** Die QA meldete Änderungen im Arbeitsbaum, die nicht von ihr stammten. Es waren die Doku-Dateien, die der
  Orchestrator parallel geschrieben hatte. Die QA selbst hat nur unter `/tmp` geschrieben.

### P0-04 – Quellenrecherche · Status: DONE (mit Einschränkung)

- **Phase:** 0
- **Verantwortlicher Agent:** `source-researcher` (ausgeführt als eingebauter Agent nach Definition, siehe Hinweis oben)
- **Geänderte Dateien:**
  - `docs/SOURCES.md`
  - `docs/DECISIONS.md` (ADR-010)
  - `.claude/agents/source-integrations.md` (kein Serverabruf beim manuellen Import)
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - Kleinanzeigen, mobile.de (AGB-HB), AutoScout24 und Meta untersagen automatisiertes Auslesen.
  - Zulässig und ohne Vertrag testbar sind zwei unabhängige Kanäle: manueller Import und E-Mail-Suchbenachrichtigungen.
  - Einziger belegter offizieller Lesezugang: mobile.de API-Account.
- **Tests:** – (Recherche)
- **Testergebnis:**
  - Direkte Seitenabrufe scheiterten in der Recherche-Umgebung (DNS). Die Zitate stammen deshalb aus
    Suchindex-Auszügen.
  - `robots.txt`: nicht geprüft
- **Review-Ergebnis:** in P0-07 nicht inhaltlich geprüft (keine Abrufe gegen Marktplätze)
- **Bekannte Risiken:** Der Wortlaut der AGB kann von den Auszügen abweichen (P2-01, BLOCKED).
- **Commit/PR:** 548c1fc
- **Nächster sinnvoller Schritt:** AGB-Originale im Browser gegenlesen (Betreiber); Anfrage an mobile.de vorbereiten

### P0-03 – Architektur- und Risikoüberblick · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `scout-architect` (ausgeführt als `Plan`-Agent nach Definition, siehe Hinweis oben)
- **Geänderte Dateien:**
  - `docs/ARCHITEKTUR.md` → `docs/ARCHITECTURE.md`
  - `docs/DECISIONS.md`
  - `README.md`
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - Modulübersicht, Datenfluss, Ist-Schema
  - Risiken R1–R18; R19 und R20 kamen in P0-07 dazu
  - Ziel-Datenmodell mit 9 Entitäten, Migrationsstrategie, Nebenläufigkeit
- **Tests:** Der Orchestrator hat die Risiken im Code stichprobenartig nachgeprüft:
  - R1: `config.yaml:196`, `importer.py:39-40`
  - R2: `config.yaml:32`
  - R3: `datenbank.py:49-53`
  - R5: `report.html:406`, `mobil.js:483`
  - R14: `api.py:434-437`
- **Testergebnis:**
  - Inhaltlich bestätigt.
  - Mehrere Zeilennummern waren falsch. Gefunden in P0-07, korrigiert und jetzt durch einen Test abgesichert.
  - Die erste Fassung von ADR-005 behauptete, der Kleinanzeigen-Abruf laufe nur auf Start durch den Betreiber. Das ist
    falsch (Auto-Suche) und wurde korrigiert.
- **Review-Ergebnis:** Urteil zum Phasenplan: **FREIGABE MIT AUFLAGEN**. Die Auflagen (a)–(d) sind übernommen.
- **Bekannte Risiken:** siehe `ARCHITECTURE.md` §5
- **Commit/PR:** c31d668
- **Nächster sinnvoller Schritt:** P0-07

### P0-02 – Agentensystem, Regeln, Skill, Loop · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:**
  - `CLAUDE.md`
  - `.claude/agents/*.md` (8)
  - `.claude/skills/scout-cycle/SKILL.md`
  - `.claude/loop.md`
  - `.gitignore`
  - `tests/test_projekt.py`
- **Implementierte Funktionen:**
  - acht Agenten mit YAML-Frontmatter; Prüfagenten ohne `Edit`/`Write`
  - Modelle: opus für Architektur, Ankaufsbewertung und QA; sonnet für die übrigen
  - SCOUT DEVELOPMENT LOOP mit Schritten A–H und Grenzen
  - Wartungsauftrag für `/loop`
- **Tests:** `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`
- **Testergebnis:**
  - Der erste Lauf scheiterte am YAML: Beschreibungen mit „: “ waren ungültig. Behoben durch Anführungszeichen.
  - Danach: `91 passed`, ruff „All checks passed!“
- **Review-Ergebnis:** geprüft in P0-07; Lücken in `test_projekt.py` dort behoben
- **Bekannte Risiken:** siehe ADR-018 (`Bash` bei QA)
- **Commit/PR:** 185dc0b
- **Nächster sinnvoller Schritt:** Projekt-Agenten nach Neustart nutzen (erledigt ab P0-05)

### P0-01 – Repository-Zustand und Entwicklungsbasis · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:** –
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - `main` enthält nur den Initial-Commit 76cb64d.
  - Integrationszweig: `claude/gifted-heisenberg-d1cjlr`.
  - PR #1 (Grundlage) und PR #2 (Handy-App) sind gemergt. PR #2 war auf den Arbeitszweig von PR #1 gestapelt und kam
    deshalb nicht im Integrationszweig an. Nachgezogen per Merge-Commit 3f75f67.
  - Die Arbeitszweige der PRs sind gemergt. Es gibt keine ungesicherten Änderungen.
- **Tests:** vor dem Push von 3f75f67: `pytest -q`, `ruff check .`
- **Testergebnis:** `81 passed`, ruff grün
- **Review-Ergebnis:** –
- **Bekannte Risiken:** Gestapelte PRs, deshalb ADR-008 (immer gegen den Integrationszweig).
- **Commit/PR:** 3f75f67 (im Integrationszweig)
- **Nächster sinnvoller Schritt:** Arbeitszweig `claude/phase0-agentensystem` anlegen
