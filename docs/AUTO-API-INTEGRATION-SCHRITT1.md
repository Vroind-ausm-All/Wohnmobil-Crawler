# Auto API Integration – Schritt 1: sichere Ausgangsbasis

Stand: 2026-10-18. Status: **Vorbereitung; keine API-Integration aktiviert**.

## Ausgangslage und Entscheidung

- Basisbranch: `claude/phaseG2-mandanten`, nicht `main` (dort nur Initialstand).
- Isolierter Arbeitsbranch: `feature/auto-api-integration-step1`.
- GitHub-Vergleiche: G2 liegt 3 Commits vor `claude/phaseG1-echtzeit`, 5 vor `claude/phaseG0b-audit`, 12 vor `claude/phaseF-abwicklung` und 38 vor `feature/realtime-source-engine` (jeweils ohne Behind-Commits). Dies ist kein vollständiges Audit aller Branches.
- Quellenvertrag: `wmscout/quellen/basis.py`; Registrierung: `wmscout/quellen/__init__.py`; Verarbeitung: `wmscout/importer.py`. Derzeit ist nur die Kleinanzeigen-Quelle registriert.
- `wmscout/quellen/api_rahmen.py` und `tests/test_api_quellen.py` sind laut `docs/QUELLEN.md` bereits vorgesehen bzw. vorhanden. Vor neuer Implementierung wiederverwenden und gegen tatsächlich vorhandenen Code prüfen.
- `docs/TEST-REPORT.md` meldet für G2 853 bestandene Linux-Tests (17.10.2026), aber das ist **kein neuer Testlauf**. Windows/Last/Proxy sind laut Bericht nicht vollständig geprüft.
- Keine fremde Bibliothek, kein API-Schlüssel und kein externer Dienst in Schritt 1 ergänzt.

## Schutz der Bestandsdaten

1. Keine Schemaänderung, Migration oder Bearbeitung von `daten/`, `mandanten/`, Fotos oder Sicherungen in diesem Schritt.
2. Vor einem lokalen Test mit produktiver Datenbank: App und Suchlauf beenden; `python scout.py sichern` ausführen; Sicherung **außerhalb** des Arbeitsverzeichnisses aufbewahren und deren Integrität sowie Wiederherstellbarkeit mit einer isolierten Testkopie prüfen.
3. Integrationstests ausschließlich mit temporärer SQLite-Datenbank und Fake-API-Antworten; niemals echte Verkaufs-/Kundendaten als Fixture einchecken.
4. API-Schlüssel ausschließlich aus einer Umgebungsvariable; nichts davon in Git, Logs oder `config.yaml`.
5. Neue API-Quelle standardmäßig deaktiviert; Aktivierung erst nach dokumentierter Freigabe, verifizierter Wohnmobil-Abdeckung und erfolgreichem Pilot.
6. Keine automatischen Verkäuferkontakte, Gebote, Käufe oder Datenlöschungen durch den Adapter.
7. Bestehende Quellenerfassung, Status, Reservierung, Kalkulation, Mandantentrennung und Audit müssen unverändert bleiben.

## Geplante Schritte nach dieser Vorbereitung

1. Baseline auf Linux und Windows in GitHub Actions ausführen: `ruff check .`, `pytest`, Starttests und Migrationstests; CI-Status und tatsächliche Testzahlen dokumentieren.
2. Externen Auto-API-Vertrag validieren: Endpoint, Authentifizierung, Quellennamen, Filter für Reisemobile, Seitenlimit, Rate Limits, Preis, Nutzungsrechte und Beispielantworten. **Ohne echten API-Schlüssel keine Live-Abdeckung behaupten.**
3. Zunächst isolierte Mapping-Funktion von Provider-JSON zu `Inserat` implementieren; Tests für fehlende Felder, Preiswährung, Kilometer, Erstzulassung, Fahrzeugart, Verkäuferart und stabile Anzeigen-ID.
4. Adapter in vorhandenen Quellenvertrag integrieren, mit standardmäßig deaktivierter Konfiguration; Quelle nur bei Freigabe und vorhandenem Secret aktivieren.
5. Importer mit Fake-Antworten auf Dubletten, Preisänderungen, HTTP 401/403/429, Timeout, abgelaufene Listings und idempotenten Wiederholungslauf prüfen.
6. Optionaler begrenzter Live-Pilot in isolierter Testdatenbank, erst nach Zugangsklärung; Ergebnisse und Fehlerquoten protokollieren.
7. Erst nach grünen Tests und Review einen Pull Request gegen den tatsächlich gewünschten Zielbranch eröffnen. **Kein automatischer Merge nach `main`.**

## Abnahmekriterien Schritt 1

- [x] Entwicklungsbranch separat von `main` angelegt.
- [x] Basisbranch anhand der Vorfahren-Vergleiche begründet.
- [x] Architektur, Datenrisiken und Integrationsgrenzen dokumentiert.
- [x] Keine produktiven Datenbanken/Secrets geändert.
- [ ] Aktueller CI-Lauf auf neuem Branch nachgewiesen.
- [ ] Vollständiger Testlauf lokal oder in CI nachgewiesen.
- [ ] Wiederherstellungstest mit isolierter Datenkopie nachgewiesen.
- [ ] Auto-API-Vertrag und Wohnmobilabdeckung live validiert.

**Freigaberegel:** Erst wenn CI, Migrationen, wiederholbarer Backup/Restore-Test und API-Vertrag geprüft sind, die eigentliche Integration aktivieren. Fehlende Prüfungen ausdrücklich als offen behandeln.
