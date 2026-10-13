# Wartungsauftrag Wohnmobil-Scout (für `/loop`)

Verwendung in Claude Code: `/loop 4h Führe den Wartungsauftrag aus .claude/loop.md aus.`
(ohne Intervall entscheidet Claude selbst über den Abstand). Der Auftrag ist sicher wiederholbar: Er ändert nur,
was innerhalb der aktuellen Freigabe liegt, und meldet alles andere.

Die eigentliche Implementierungsarbeit erledigt der Skill `scout-cycle`. Dieser Wartungsauftrag startet **keine**
neuen Arbeitspakete, sondern hält bestehende Arbeit grün und meldet Entscheidungsbedarf.

## Bei jedem Durchlauf

1. **Branch und Pull Requests:** `git fetch --all --prune`, aktuellen Branch und `git status` prüfen. Offene
   Pull Requests im Repository `Vroind-ausm-All/Wohnmobil-Crawler` auflisten (Basis, Head, Mergebarkeit).
2. **Phasenstatus:** In `docs/ROADMAP.md` die freigegebene Phase und Pakete mit Status `IN_PROGRESS`, `REVIEW`,
   `BLOCKED` lesen. In `docs/WORKLOG.md` den letzten Eintrag lesen.
3. **CI und Tests:** CI-Ergebnisse der offenen PRs und des Integrationszweigs `claude/gifted-heisenberg-d1cjlr`
   prüfen. Lokal `.venv/bin/python -m pytest -q` und `.venv/bin/python -m ruff check .` ausführen.
4. **Neue Probleme:** rote Checks, Merge-Konflikte, neue Review-Kommentare, neue fehlschlagende Tests erfassen.
5. **Beheben – nur innerhalb der Freigabe:** kleine, eindeutige Korrekturen (Testfehler durch eigene Änderung,
   Lint, Merge-Konflikt per Merge-Commit, kleine Review-Wünsche) auf dem jeweiligen Arbeitszweig, mit QA-Prüfung
   durch `qa-security-reviewer` bei Code-Änderungen. Größere Wünsche, Architekturfragen, neue Quellen,
   Schemaänderungen → nicht umsetzen, sondern melden.
6. **Erneut testen** (Schritt 3) nach jeder Korrektur; erst dann pushen.
7. **Arbeitsbericht:** `docs/WORKLOG.md` um einen kurzen Wartungseintrag ergänzen, **nur wenn sich etwas geändert
   hat** (Datum, Befund, Maßnahme, Ergebnis). Keine Leer-Einträge.
8. **Melden**, wenn eine Entscheidung oder Freigabe nötig ist (Phase abgeschlossen, Paket `BLOCKED`, Quelle mit
   ungeklärten Rechten, fehlende Zugangsdaten, Kosten).
9. **Keine neue Hauptphase** ohne ausdrückliche Zustimmung des Betreibers.
10. **Niemals nach `main` mergen**, keine PRs mergen, keine History umschreiben, keine Tests deaktivieren.

## Nie im Wartungsauftrag

Datenbanken migrieren oder löschen · Quellen aktivieren · Verkäufer kontaktieren · kostenpflichtige Dienste oder
Dauerprozesse starten · Geheimnisse anlegen oder ausgeben.

## Ergebnis jedes Durchlaufs (kurz)

```
Wartung <Datum>: Branch … · offene PRs … · CI … · Tests … · Maßnahmen … · Entscheidung nötig: ja/nein (…)
```
