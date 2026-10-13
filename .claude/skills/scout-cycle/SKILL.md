---
name: scout-cycle
description: "SCOUT DEVELOPMENT LOOP für Wohnmobil-Scout 2.0. Führt einen vollständigen, überprüfbaren Entwicklungszyklus für das nächste offene Arbeitspaket der freigegebenen Phase aus (Analyze → Plan → Implement → Verify → Review → Fix → Complete → Next), mit Subagenten, Tests, QA-Review, Worklog und Pull Request. Einsetzen, wenn an einem Backlog-Arbeitspaket gearbeitet werden soll."
---

# SCOUT DEVELOPMENT LOOP

Du bist der **Orchestrator**. Du koordinierst, formulierst Aufträge, führst Ergebnisse zusammen und bist für die
Gesamtqualität verantwortlich. Recherche, Implementierung und unabhängige Prüfung delegierst du an die
Projekt-Agenten in `.claude/agents/` (Aufruf über das Agent-Werkzeug mit `subagent_type: <name>`).
Rollen nicht selbst simulieren. Sind die Projekt-Agenten in der Sitzung nicht geladen (erst nach Neustart verfügbar),
einen eingebauten Agenten mit dem Auftrag „Lies `.claude/agents/<name>.md` und handle exakt nach dieser Rolle“
starten (Prüfagenten: `Plan` bzw. Agent ohne Schreibzugriff) und das im WORKLOG vermerken.

Verbindlich: `CLAUDE.md`. Maßgeblicher Planungsstand: `docs/ROADMAP.md` (Backlog) und `docs/WORKLOG.md`.

## Grenzen je Durchgang

| Regel | Wert |
|---|---|
| Abgeschlossene Arbeitspakete pro Durchgang | höchstens **5** |
| Korrekturrunden (Schritt F) je Arbeitspaket | höchstens **3**, danach `BLOCKED` |
| Gleichzeitige Subagenten | höchstens **3**, nur für unabhängige Arbeit, nie dieselben Dateien |
| Neue Hauptphase | **nur nach Freigabe** des Betreibers |
| Merge nach `main` | **niemals** |

Sofort anhalten und berichten bei: kritischem, ungeklärtem Fehler; drohendem Datenverlust; unklaren Nutzungsrechten
einer Quelle (Quelle → `BLOCKED`, zulässige Alternative vorbereiten); fehlenden Zugangsdaten (Integrationspunkt
vorbereiten, nicht raten); Bedarf an kostenpflichtigen Diensten, Dauerprozessen oder rechtsverbindlichen Aktionen.

## Schritt A – ANALYZE

1. `git status`, `git branch -a`, `git log --oneline -10`; offene Pull Requests und CI-Status prüfen.
2. `.venv/bin/python -m pytest -q` und `.venv/bin/python -m ruff check .` ausführen (Ausgangslage festhalten).
3. `docs/ROADMAP.md` lesen: aktuelle, freigegebene Phase; offene Arbeitspakete (`TODO`, `IN_PROGRESS`, `REVIEW`).
4. Wichtigstes nicht abgeschlossenes Paket wählen: zuerst `IN_PROGRESS`/`REVIEW`, dann `TODO` nach Priorität
   (P1 > P2 > P3) und erfüllten Abhängigkeiten. Pakete außerhalb der freigegebenen Phase nicht anfassen.
5. Abhängigkeiten und Risiken notieren.

## Schritt B – PLAN

1. Paket in kleine, einzeln testbare Schritte zerlegen.
2. Betroffene Module/Dateien bestimmen (bei Architekturfragen `scout-architect` fragen).
3. Zuständigen Agenten wählen:

   | Thema | Agent |
   |---|---|
   | Installation, `.venv`, Startskripte, Abhängigkeiten, CI | `windows-bootstrap` |
   | Quellenrecherche, Nutzungsbedingungen | `source-researcher` |
   | Adapter, Import, Feeds, Suchbenachrichtigungen | `source-integrations` |
   | Schema, Migration, Dubletten, Historie, Backup | `scout-data-engineer` |
   | Marktwert, Max-EK, Deal-Score, Mängel | `acquisition-analyst` |
   | Desktop-/Handy-Oberfläche, Workflow | `scout-ui-engineer` |
   | Architektur, Schnittstellen, Migrationsplan | `scout-architect` (nur Planung/Prüfung) |
   | Prüfung, Tests, Sicherheit | `qa-security-reviewer` (nur Prüfung) |

4. **Akzeptanzkriterien** messbar formulieren (aus ROADMAP übernehmen und konkretisieren).
5. Teststrategie: welche Unit-, Integrations-, Migrations- und Klicktests belegen die Kriterien?
6. Paket in `docs/ROADMAP.md` auf `IN_PROGRESS` setzen.

## Schritt C – IMPLEMENT

1. Branch vom Integrationszweig: `git fetch origin claude/gifted-heisenberg-d1cjlr` und
   `git checkout -b claude/<phase>-<thema> origin/claude/gifted-heisenberg-d1cjlr`.
2. Implementierungsagenten beauftragen. Der Auftrag enthält: Ziel, Kontext, betroffene Dateien,
   Akzeptanzkriterien, Teststrategie, Grenzen („keine Änderungen an … “), erwartetes Ausgabeformat.
3. Bestehende Schnittstellen erhalten; nötige Brüche mit Kompatibilitätsschicht.
4. Tests ergänzen; Doku (README, `docs/*`) anpassen.

## Schritt D – VERIFY (selbst ausführen, nicht nur dem Agenten glauben)

* `.venv/bin/python -m pytest -q` (vollständig, inkl. Regressionen) und `.venv/bin/python -m ruff check .`
* Integrations-/Migrationstests mit Altbestand, wo Daten betroffen sind.
* Klicktest (Playwright/Chromium), wo Oberfläche betroffen ist.
* Windows: lokal nicht ausführbar → CI-Jobs „Tests (windows-latest)“ und „Windows-Start“ nach dem Push abwarten.
* Jedes Akzeptanzkriterium einzeln abhaken. **Nicht Ausgeführtes heißt „nicht geprüft“.**

## Schritt E – REVIEW

`qa-security-reviewer` mit Diff (`git diff origin/claude/gifted-heisenberg-d1cjlr...HEAD`), Akzeptanzkriterien und
Testergebnissen beauftragen. Bei Schema-/Architekturänderungen zusätzlich `scout-architect`.
Befunde nach KRITISCH / HOCH / MITTEL / NIEDRIG erfassen. Paket auf `REVIEW` setzen.

## Schritt F – FIX (höchstens 3 Runden)

Bei roten Tests oder KRITISCH/HOCH-Befunden: Ursache ermitteln → Befund mit Beleg an den zuständigen
Implementierungsagenten → kleine, gezielte Korrektur → Schritt D → Schritt E (nur betroffene Befunde).
Nach der 3. Runde mit offenen kritischen Befunden: Paket `BLOCKED`, Ursache und nötige Entscheidung im WORKLOG,
nicht weiterarbeiten. MITTEL/NIEDRIG dürfen begründet ins Backlog.

## Schritt G – COMPLETE

1. Commit(s) mit deutscher, aussagekräftiger Nachricht; `git push -u origin <branch>`.
2. Pull Request **gegen `claude/gifted-heisenberg-d1cjlr`** (nie `main`, nie gegen einen anderen Arbeitszweig):
   Änderungen, Akzeptanzkriterien mit Nachweis, Tests (Befehl + Ergebnis), nicht geprüft, Risiken, Entscheidungen.
3. CI abwarten; rot → zurück zu Schritt F.
4. `docs/WORKLOG.md`-Eintrag (Vorlage unten), `docs/ROADMAP.md` (Status `DONE` erst, wenn CI grün und QA ohne
   kritische Befunde), `docs/TEST-REPORT.md`, ggf. `docs/DECISIONS.md`. Neue Risiken und Ideen ins Backlog.

## Schritt H – NEXT

* Weitere unabhängige Pakete der **freigegebenen** Phase offen und Limit (5) nicht erreicht → zurück zu A.
* Phase vollständig: Abnahmekriterium der Phase prüfen, Phasenbericht in `docs/WORKLOG.md`, Betreiber um
  Freigabe der nächsten Phase bitten. **Nicht eigenmächtig weitermachen.**

## WORKLOG-Vorlage

```
### <Task-ID> – <Titel>  ·  Status: DONE | BLOCKED | REVIEW
- Phase:
- Verantwortlicher Agent:
- Geänderte Dateien:
- Implementierte Funktionen:
- Tests: (Befehle)
- Testergebnis: (wörtlich, z. B. „95 passed“; nicht Ausgeführtes als „nicht geprüft“)
- Review-Ergebnis: (Urteil QA, offene Befunde mit Stufe)
- Bekannte Risiken:
- Commit/PR:
- Nächster sinnvoller Schritt:
```
