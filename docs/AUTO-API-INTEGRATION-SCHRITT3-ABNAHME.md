# Schritt 3: Auto-API-Schema, Offline-DB-Test, Abnahmebericht

Datum: 2026-10-18. Branch: `feature/auto-api-integration-step1`.

## Änderungen
- `wmscout/quellen/auto_api_probe.py`: Beachtet jetzt `meta.next_page = null` als Ende der Paginierung; keine Produktionsregistrierung.
- `tests/test_auto_api_probe.py`: Tests für Paginierungsende und Verarbeitung des synthetischen Inserats in der **echten** `Datenbank`-Klasse auf `tmp_path`, einschließlich idempotentem Wiederimport und Preisreduzierung. Test ist eingecheckt, nicht als bestanden bestätigt.
- Keine weiteren Produktivdateien, Datenbankmigrationen, Secrets oder API-Abhängigkeiten geändert.

## Quellenabgleich – offizielle Dokumentation
Auto-API-Python-README: https://github.com/autoapicom/auto-api-python
- Bestätigt: Client `get_offers('mobilede', page=1, ...)`, Plattformkennungen `mobilede`, `autoscout24`, `meta.page` und `meta.next_page`; `get_offer`, `get_changes`, `AuthError` / `ApiError` werden dokumentiert.
- **Nicht bestätigt:** Top-Level-Datenfeld `offers`, Einzelangebotsfelder `id/url/title/price/mileage/year/brand/location/is_private`, Kategoriezuordnung für Wohnmobile, garantierte verfügbare Anzeigen und Nutzungsrechte. Diese Felder im Probeadapter sind *ausschließlich Testannahmen*. Die Semantik `year` = Erstzulassung ist unbewiesen.
- Kein API-Schlüssel verfügbar bzw. verwendet. Keine Live-Antwort abgerufen. Echtes Schema bleibt ausstehend.

## CI-Befund
- `.github/workflows/tests.yml` ist seit Schritt 2 für diesen Branch auf Push konfiguriert.
- Abfrage von Commit-Status und PR-bezogenen Workflow-Runs für die aktuellen Commits: keine Statusdaten/PR-Runs zurückgegeben. **Nicht als grün werten.** Diese Schnittstelle zeigt nicht alle Push-Workflows; GitHub Actions separat überprüfen.
- Vollständiger Clone in isolierter Laufzeit scheiterte an nicht auflösbarem `github.com`-Host. Keine vollständige lokale Testsuite ausgeführt.
- Daher sind die neuen Tests lediglich **geschrieben**, nicht nachweisbar bestanden. Ein vollständiger Ende-zu-Ende-Test der Produktivimporter-Pipeline wurde nicht ausgeführt.

## Abnahmekriterien
| Kriterium | Status |
| --- | --- |
| Kein produktiver Quelleneintrag, keine Secrets, keine DB-/Schemaänderung | Erfüllt (Codeprüfung) |
| Dokumentierte Pagination in Probeadapter | Implementiert, Ausführung ausstehend |
| Synthetischer Datensatz: Einfügen, Wiederholung, Preisänderung in tmp SQLite | Test implementiert, Ausführung ausstehend |
| Ruff und Pytest Linux/Windows | Offen: CI-Ergebnisse nicht bestätigt |
| Echtes Antwortschema / Wohnmobilfilter verifiziert | Offen |
| Authentifizierungs- und Rate-Limit-Vertrag des konkreten Providers validiert | Offen |
| Wiederherstellung vorhandener Daten aus isolierter Sicherung geprüft | Offen |
| Freigabe produktiver Datenimporte | **Nicht erteilt** |

## Nächste sichere Arbeit
1. GitHub-Actions-Run für Branch kontrollieren, fehlerhafte Tests korrigieren, Ruff und gesamten Pytest-Lauf mit dokumentierten Logs grün bekommen.
2. Anonymisierte echte `get_offers`-Antworten mit zulässigen Daten vom Provider besorgen. Schema verifizieren und Probe-Mapping ohne Rateschritte anpassen.
3. Nach API-Vertrag/Quota-Prüfung im abgesicherten vorhandenen `api_rahmen.py` oder kompatiblen Client-Wrapper integrieren; Ausnahmen sauber auf `QuelleGesperrt` etc. abbilden.
4. Mit temporärer DB vollständigen `Importer`-Test und Backup/Restore-Test durchführen; erst anschließend optionale, standardmäßig deaktivierte Registrierung erwägen.

Rollback: Feature-Branch verwerfen; weder `main` noch Produktivdaten wurden geändert.
