# Echtzeit-Grundlage (PR feature/realtime-source-engine)

## Umfang und Abgrenzung

Diese Stufe implementiert **keine Live-Suche**, WebSocket-Verbindung, externe API oder neue UI.
Sie liefert ein quellneutrales Ereignismodell, v4-Tabellen, eine Freigabeprüfung für
automatische Eingänge und rein offline getestete Beispiele.

Der Integrationszweig bleibt `claude/gifted-heisenberg-d1cjlr`. `main` wird nicht verändert.

## Datenfluss

```text
(E-Mail / manuell / künftig freigegebene APIs und Streams)
    -> InseratEreignis (wmscout/ereignisse.py)
    -> Importer.importiere_ereignis
    -> EreignisSpeicher.verarbeite
    -> inserate + beobachtungen + preis_historie (Schema v4)
```

- `plattform` bezeichnet den Markt (z. B. mobilede), `kanal` den Eingang (email, manuell, api, stream).
- Eindeutige Inserate nutzen `UNIQUE(plattform, anzeigen_id)`.
- Bekannte Zustände werden nicht erneut protokolliert; optionale externe `ereignis_id` wird dedupliziert.
- Löschereignisse ändern nur die **Verfügbarkeit** des Inserats, nicht dessen Ankaufstatus.
- Preise werden bei Änderung historisiert. Erste Altpreise werden mit Herkunft `migration` übernommen.
- Die neue Tabelle `inserate` liegt parallel zu `anzeigen`. Seit ADR-024 werden beide in denselben Transaktionen
  geschrieben: Suchtreffer erscheinen in v4, neue/geänderte Ereignisse in `anzeigen` (Art unbekannt, F14).
- Die Migration ist versioniert, wird transaktional ausgeführt und erstellt vorher eine verifizierte Sicherung.

## Quellenfreigabe

- Für bestehende `Quelle.suche()` und `Quelle.details()` gilt: `freigegeben=False` führt zum Abbruch **vor dem Abruf**.
- `kleinanzeigen` ist ausdrücklich als nicht freigegeben markiert. Die Standardsuche ist auf 0 Stunden gestellt.
- `api`- und `stream`-Ereignisse werden nur akzeptiert, wenn `quellen` einen explizit **freigegebenen und aktiven**
  Datensatz mit `zugriffsart='api'` enthält. Es gibt keinen automatischen Aktivierungspfad.
- `email` und `manuell` sind Eingänge für vom Nutzer bereitgestellte Daten, keine Erlaubnis zum Nachladen
  verlinkter Webseiten. Die konkrete zulässige Verarbeitung ist für reale Quellen separat zu prüfen.
- Die Ereignis-Pipeline ruft nie Netzwerkfunktionen auf. Daten aus Tests verwenden erfundene URLs.

## Folgearbeiten

1. P1-04: WAL / verbindungsspezifische DB-Zugriffe / Laufsperren.
2. ~~Alte `anzeigen`-Schreibwege und v4-`inserate` synchronisieren~~ – umgesetzt (ADR-024, P1-04b).
3. Sucheingänge mit Berechtigungskonzept anbinden; API-Credentials nur über Umgebungsvariablen.
4. Ereignis-Zeitordnung und Reconnect/Catch-up pro Datenquelle klären (stale Events vermeiden).
5. Benachrichtigungen, Dashboard und Bewertungslogik ausschließlich über verifizierte Daten zuschalten.

## Tests

```bash
python -m pytest -q tests/test_ereignisse.py tests/test_migration.py tests/test_quellen.py
python -m pytest -q
python -m ruff check .
```

Keine Ergebnisse vorweggenommen: Tests müssen in CI ausgeführt und dokumentiert werden.
