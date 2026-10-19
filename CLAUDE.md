# Wohnmobil-Scout 2.0 – Projektregeln für Claude Code

Deutschlandweite Such- und Analyseplattform für den **gewerblichen Ankauf gebrauchter Wohnmobile**.

* **Primärziel:** möglichst früh günstige, relevante Wohnmobile **privater Verkäufer** entdecken, Dubletten
  vermeiden, Angebote wirtschaftlich bewerten und die besten Ankaufsgelegenheiten anzeigen.
* **Sekundärziel:** aus zulässig zugänglichen Marktdaten eine immer bessere Bewertungsgrundlage aufbauen.
* Erfolg misst sich an **relevanten, verfügbaren Ankaufsgelegenheiten**, nicht an abgerufenen Seiten.

## Oberste Regeln (gelten für jeden Agenten und jede Sitzung)

1. Bestehenden Code analysieren, bevor größere Änderungen erfolgen. Keine unkontrollierten Komplett-Rewrites.
2. Bestehende Funktionen (Bewertung, Anschreiben, Statusverwaltung, Browser-App, Handy-App, CSV) nicht grundlos entfernen.
3. **Keine Datenbank löschen oder ohne Backup migrieren.** Jede Migration: Backup vorher, Transaktion, idempotent, Test mit Altbestand.
4. Keine globalen Python-Installationen verändern. Python 3.13 und projektlokale `.venv`.
5. **Keine Zugangsdaten, Passwörter, Tokens oder API-Schlüssel im Repository.** Geheimnisse nur über Umgebungsvariablen.
6. **Keine Änderungen direkt auf `main`, niemals automatisch nach `main` mergen.**
7. Pro größerem Arbeitspaket ein eigener Branch `claude/<phase>-<thema>`, Pull Request gegen den Integrationszweig.
8. Nachvollziehbare Commits; Pull Requests beschreiben Änderungen, Tests und offene Punkte.
9. **Tests prüfen reale Funktionalität. Keine erfundenen oder geschönten Testergebnisse.** Nicht Ausgeführtes heißt „nicht geprüft“.
10. **Keine automatisierte Verkäuferansprache, keine selbstständigen Kaufzusagen**, keine rechtsverbindlichen Aktionen.
11. **Keine Captchas, Zugangssperren, Rate-Limits oder Anti-Bot-Mechanismen umgehen** (kein IP-Wechsel, keine
    gefälschten Browser-Fingerabdrücke, keine automatisierten Logins).
12. Datenzugang nur über offizielle APIs, freigegebene Feeds, Suchbenachrichtigungen des Nutzers oder manuellen Import.
    Quellen mit ungeklärten Nutzungsrechten: Adapter bleibt deaktiviert bzw. `freigegeben = False`, Status BLOCKED.
13. Keine dauerhaften Prozesse, kostenpflichtigen Dienste oder riskanten Migrationen ohne Freigabe des Betreibers.
14. Jede Phase liefert überprüfbare Ergebnisse. **Vor jeder neuen Hauptphase Freigabe einholen.**
15. Stabilität, Datenintegrität und Sicherheit gehen vor Geschwindigkeit.

## Branches

| Zweig | Rolle |
|---|---|
| `main` | Nur Initial-Commit. Übernahme ausschließlich nach ausdrücklicher Freigabe durch den Betreiber. |
| `claude/gifted-heisenberg-d1cjlr` | **Integrationszweig** (aktueller Hauptcode). Ziel aller Pull Requests. |
| `claude/<phase>-<thema>` | Arbeitszweig je Arbeitspaket, z. B. `claude/phase0-agentensystem`. |

Stacked PRs vermeiden: Ein PR, dessen Basis ein anderer Arbeitszweig ist, landet nach dem Merge nicht im
Integrationszweig, wenn der Basis-PR vorher gemergt wurde (so geschehen mit PR #2). Basis immer der Integrationszweig.

## Befehle

```bash
# Einrichtung (legt .venv mit Python 3.13 an, installiert aus gesperrten Hashes)
installieren.bat            # Windows
./installieren.sh           # macOS/Linux
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt   # Entwicklungswerkzeuge

# Prüfen (vor jedem Commit)
.venv/bin/python -m pytest -q          # komplett offline
.venv/bin/python -m ruff check .

# Abhängigkeiten ändern: pyproject.toml anpassen, dann Lock-Dateien neu erzeugen (siehe README „Abhängigkeiten“)

# Starten
.venv/bin/python scout.py app          # Browser-App auf http://127.0.0.1:8765 (Handy-App unter /m)
.venv/bin/python scout.py rechne --anschreiben
```

Unter Windows `.venv\Scripts\python` statt `.venv/bin/python`.

## Code-Aufbau (Kurzfassung, Details in `docs/ARCHITECTURE.md`)

```
scout.py                      Kommandozeile: app, lauf, report, rechne, nutzer, status
wmscout/quellen/              Quellen-Schnittstelle (basis.py) + Adapter (kleinanzeigen/)
wmscout/netz.py               höflicher HTTP-Abruf, bricht bei 403/429/Captcha ab
wmscout/importer.py           Suchlauf: Quellen → Normalisierung → Datenbank
wmscout/normalisierung/       Fahrzeugerkennung, PLZ/Entfernung
wmscout/datenbank.py          SQLite (Tabelle anzeigen) + ALTER-TABLE-Ergänzungen
wmscout/bewertung/            rechner.py (Marktwert, Max-EK), anschreiben.py, auswertung.py, besichtigung.py
wmscout/team.py               Nutzer, Sitzungen, Besichtigungen, Fotos
wmscout/web/                  api.py (HTTP-Routen), static/ (PWA)
wmscout/app.py                Server, Suchlauf-Thread, Auto-Suche
vorlagen/                     Jinja2-Vorlagen (Desktop-App, Login, Handy, Protokoll, Anschreiben)
config.yaml, maengel.yaml     Konfiguration (keine Geheimnisse!)
tests/                        pytest, offline, mit Fixtures in tests/daten.py
```

## Konventionen

* **Sprache:** Bezeichner, Kommentare, Doku und Commit-Nachrichten auf Deutsch (bestehender Stil). Umlaute in
  Bezeichnern vermeiden (`preis_historie`, nicht `preis_historië`).
* Ruff mit Zeilenlänge 160. Kommentardichte wie im umgebenden Code: knapp, nur wo nötig.
* Einfache, stabile Lösungen: Standardbibliothek, SQLite, kein Web-Framework, keine Microservices.
* Fachlogik ohne Netz- und Datenbankzugriff testbar halten. Quellen liefern nur `Inserat`-Objekte;
  **keine quellenspezifische Logik in der Ankaufsberechnung.**
* Geldbeträge bei unsicherer Datenlage nicht mit falscher Genauigkeit ausgeben (runden, Spannen, Unsicherheit ausweisen).
* §25a-UStG-Kalkulation ist eine fachliche Annahme, keine Steuerberatung. Parameter bleiben konfigurierbar.
* Ein Verkäufer gilt erst nach **bestätigter** Kontaktaufnahme als „kontaktiert“, nicht beim Kopieren eines Textes.

## Agenten-Team (`.claude/agents/`)

| Agent | Zuständigkeit | schreibt Code? |
|---|---|---|
| `scout-architect` | Architektur, Modulgrenzen, Migrationsstrategie, Architekturprüfung | nein |
| `windows-bootstrap` | Python 3.13, `.venv`, Startskripte, Abhängigkeiten, Windows-Probleme | ja |
| `source-researcher` | Marktplätze, offizielle Zugänge, Nutzungsbedingungen, Priorisierung | nein (nur Recherche) |
| `source-integrations` | Quellenadapter, Feeds, Suchbenachrichtigungen, manueller Import | ja |
| `scout-data-engineer` | Datenmodell, Migrationen, Dubletten, Historie, Backups | ja |
| `acquisition-analyst` | Marktwert, Max-EK, Deal-Score, Unsicherheit | ja (Bewertung) |
| `scout-ui-engineer` | Desktop- und Handy-Oberfläche, Workflow | ja |
| `qa-security-reviewer` | unabhängige Prüfung, Tests ausführen, Freigabe/Ablehnung | nein |

Entwicklungsablauf: Skill **`scout-cycle`** (`.claude/skills/scout-cycle/SKILL.md`).
Wartungsauftrag für `/loop`: `.claude/loop.md`.

## Projektdokumente (aktuell halten)

`docs/ROADMAP.md` (Phasen + Backlog) · `docs/WORKLOG.md` (Arbeitsprotokoll) · `docs/ARCHITECTURE.md` ·
`docs/DECISIONS.md` (Architekturentscheidungen) · `docs/SOURCES.md` (Quellenbewertung) ·
`docs/TEST-REPORT.md` (tatsächliche Testergebnisse) · `docs/QUELLEN.md` (Anleitung Adapter) ·
`docs/HANDY-APP.md` (Handy-App).

Arbeitspaket-Status: `TODO` / `IN_PROGRESS` / `REVIEW` / `DONE` / `BLOCKED`.
**Definition of Done:** Akzeptanzkriterien erfüllt, pytest + ruff grün, CI grün, QA-Review ohne kritische
Befunde, Doku und WORKLOG aktualisiert, PR erstellt (nicht gemergt).
