# Schritt 2 – Auto API Probeadapter (18.10.2026)

## Status
Implementiert als **deaktivierter Offline-Prototyp**, nicht als Live-Integration. Keine produktive DB, Migration, Konfiguration, Secrets oder bestehende Registrierungen geändert.

## Änderungen
- `wmscout/quellen/auto_api_probe.py`: reine Normalisierung und isolierte `AutoApiQuelle`. Nur mit explizit injiziertem Fake-Client instanziierbar. **Nicht** in `QUELLEN` registriert.
- `tests/test_auto_api_probe.py`: synthetische Fake-Antworten, quellenspezifische IDs, fehlende Felder, ungültige Links, Pagination und Fehler.
- `.github/workflows/tests.yml`: Push-CI speziell für `feature/auto-api-integration-step1` ergänzt. Unveränderte Jobs prüfen Pytest, Ruff und Startskripte.

## Vorhandene Architektur
- `wmscout/quellen/api_rahmen.py` begrenzt bestehende API-Abfragen und schützt Secrets, HTTPS und 401/403/429. Der Probeadapter verwendet diesen Rahmen **noch nicht**, da der echte Drittanbieter-Client eine andere Aufrufstruktur hat.
- `tests/test_api_quellen.py` enthält bestehende Offline-Vertragstests für diesen Rahmen.
- In `wmscout/quellen/__init__.py` bleibt ausschließlich Kleinanzeigen aktiv.

## Wichtig: Annahmen des Probeformats
Die Felder `offers`, `id`, `url`, `title`, `price`, `mileage`, `year`, `brand`, `location` und `is_private` sind **nur synthetische Testannahmen**. In der Client-README sind `get_offers(source, page=...)` und `meta.next_page` beschrieben, das vollständige Antwortschema für Reisemobile wurde hier nicht überprüft. `year` ist ausdrücklich noch kein validierter Ersatz für die Erstzulassung. Kein Mapping von Preiswährung oder Laufleistung wird geraten.

## Freigabekriterien für nächsten Implementierungsschritt
- [x] Probeadapter isoliert und deaktiviert
- [x] Offline-Tests hinzugefügt; keine Netzwerkabfragen in den Tests
- [x] CI-Branchfilter ergänzt
- [ ] Neuer Pytest- und Ruff-Lauf erfolgreich von GitHub Actions nachgewiesen
- [ ] Live-API-Feldschema, Kategorie Reisemobil, Herkunft/Verwendungsrechte und Authentifizierung verifiziert
- [ ] Vergleich von Anbieterdaten zu echten Anzeigen mit dokumentierter Feldabdeckung
- [ ] Produktiver Adapter benutzt abgesicherte Authentifizierung, Quoten und Fehlerklassen; 401/403/429 stoppt
- [ ] Backup/Restore in isolierter Umgebung erfolgreich getestet

## Datenschutz und Rollback
Keine Käufer-/Verkäuferdaten verarbeitet. Kein API-Schlüssel im Repository. Bei Bedarf Branch verwerfen; der produktive Branch und Datenbestand sind unverändert. Erst nach Abnahme wird die neue Quelle optional und standardmäßig aus registriert.
