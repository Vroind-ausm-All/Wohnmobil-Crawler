# CampRCrawlR – Überarbeitung vom 08.11.2026

Grundlage: Benutzerfeedback `CampRCrawlR_.txt`, explizit übernommener Codex-Entwicklungsauftrag und ZIP `CampRCrawlR_ueberarbeitet_2026-11-08.zip`. Arbeitszweig: `claude/camprcrawlr-haendlerablauf`, Ausgangscommit `92bc20b`.

## Bestandsaufnahme

| Bereich | Vor dieser Überarbeitung |
|---|---|
| SQLite, Migrationen, Sicherung/Wiederherstellung | vorhanden, umfangreiche bestehende Tests |
| Manuelle HTML-, EML- und Textimporte | vorhanden; HTML/EML nur über Serverordner |
| Kleinanzeigen-Erkennung / Quellenisolation | teilweise; ZIP enthält Verbesserungen, weitere Lücken bei unbekanntem Anbieter, Preisen und Parserfehlern |
| Sortierung | teilweise; Desktop fehlende Preise als 0, unterschiedliche Rangfolgen; ältere Inserate verschwinden nach 21 Tagen |
| Suchprofile und Radius | vorhanden, im Menü schwer erreichbar; kein zentraler Suchknopf für Bestand |
| CSV / Browser-Dateiupload | fehlte |
| Kontakte, Termine, Besichtigungen, Vertragsentwurf | vorhanden; zusammenhängende Abnahme zu ergänzen |
| Datenqualität | Markierungen/Anbieter- und Art-Herkunft vorhanden; allgemeine manuelle Feldbestätigung fehlt |
| Windows/Linux-Installer | vorhanden; Python 3.13, hashgesperrte Abhängigkeiten |

ZIP-Abgleich: 7 geänderte und 3 neue Dateien; vorhandene Funktionen werden gezielt integriert, nicht der gesamte Checkout überschrieben. Die drei bereits zuvor geänderten Batchdateien bleiben erhalten. Der bestehende Checkout wird verwendet; kein zusätzlicher Worktree. Der Projekt-Skill scout-cycle wird für getrennte Zuständigkeiten und unabhängiges Review angewendet; Benutzerauftrag autorisiert alle angegebenen Pakete, lokale Rollen über verfügbare Agenten geladen.

## Ausgangsprüfung

Vorangegangene Einrichtung auf identischem Ausgangsstand: Ruff grün, 2.683 Tests bestanden, ein Umgebungsfehler in `test_systemd_syntax` (Schreibzugriff auf `/run/systemd` fehlt auch außerhalb der Sandbox). Python 3.13.5, Node 24 und Chromium sind vorhanden. Live-Marktplatzabrufe und Windows-Tests wurden in dieser Linux-Maschine nicht ausgeführt.

## Abnahme

Die folgenden Funktionen sind implementiert. Die lokale Prüfung verwendet vorhandene Fixtures und ausdrücklich synthetische Angebote.
Ein echter Chromium steuert eine echte lokale App mit eigener temporärer SQLite-Datenbank; externe Requests sind dabei gesperrt.
Das ist keine Produktivabnahme aktueller Marktplatzseiten.

| Paket | Erledigt und wesentliche Dateien | Nachweis |
|---|---|---|
| 1 Import/Parser | Alte/neue Kleinanzeigen-Karten, kanonische Links, Preis/VB, Altpreis-/Ratenfilter, belegte Anbieterart, Zusammenführung und Reimport. Fehlerhafte Dateien bleiben zur Prüfung liegen. `wmscout/quellen/kleinanzeigen/parser.py`, `wmscout/eingang/seiten.py` | `test_quellen_p0_robust.py`, bestehende Seiten-/Eingangs-/Sicherheitstests; Chromium-Import |
| 2 Sortierung | Gemeinsame Rangfolgen für Python, Desktop und Mobil; fehlende Werte zuletzt, feste Gleichstandsregeln, Ankaufchance mit Gründen. Alte API-Standards bleiben erhalten. `wmscout/bewertung/sortierung.py`, `auswertung.py`, `deal_score.py` | `test_ankauf_sortierung.py` führt auch den tatsächlichen JavaScript-Komparator mit Node aus; Chromium |
| 3 Quellenablauf | Fehler pro Quelle/Auftrag isoliert, Teilzähler erhalten, bekannte Seiten nur nach Quellengarantie vorzeitig abbrechen, ehrlicher Status. Alte Inserate bleiben sichtbar und veraltet markiert. `wmscout/importer.py`, `quellen/basis.py`, `app.py`, `laufprotokoll.py` | Synthetische freigegebene Testquellen mit Timeout, 403/429 und Parserfehler; bestehende Status-/Schaltertests |
| 4 Eingänge | HTML-/CSV-/EML-Upload im Browser, CSV-Vorschau und Feldzuordnung, Ergebniszähler, bestehender Link/Text-Import. Gemeinsamer Importer; kein Abruf verlinkter Seiten. `wmscout/eingang/dateien.py`, `web/api.py`, `web/static/dateiimport.js` | `test_datei_upload.py`: Rechte/CSRF, Grenzen, Gesuche, Schadtexte, Reimporte; Chromium einschließlich verzögerter CSV-Vorschau |
| 5 Oberfläche | Hauptmenü, Tagesablauf, Bestandssuche per Knopf, PLZ/Radius, Art/Marke/Modell, Filter und Suchprofile. `vorlagen/report.html`, `web/static/haendler.js`, `suchprofile.js`, `mobil.js` | HTTP- und Browserablauf; Desktop und Mobilansicht visuell geprüft |
| 6 Datenqualität | Originale getrennt von bestätigten Feldern, Herkunft/Fehlstellen/Konflikte und Zurücksetzen; Migration 24, Bestätigungen auch in Anonymisierung/Aufbewahrungsfristen. Vorhandene Ausstattungserkennung und Bewertungsformeln weiterverwendet. `wmscout/feldbestaetigungen.py`, `migrationen.py`, `datenrechte.py`, `normalisierung/qualitaet.py`, `web/static/angaben.js` | `test_feldbestaetigungen.py`: Altbestand, Backup, Idempotenz, Wiederherstellung, Konflikte, Fristen; bestehende Bewertungstests |
| 7 Händlerablauf/Betrieb | Kontakt vorbereiten, Termin/Besichtigung, FIN/Kilometer, Verkäufername/Adresse/Telefon/Mail und Vertragsentwurf vor Kaufabschluss; serverseitige Kontaktdaten. Kundenstart für Windows, Browser-CI, Update-Anleitung. `vorlagen/vertragsentwurf.html`, `vertrag.html`, `kundenstart.bat`, `kundenstart.ps1`, `.github/workflows/tests.yml` | `test_haendler_ablauf.py` über HTTP für CSV und HTML, Chromium bis zum Entwurf; Windows nur statisch geprüft |

Neue Tests liegen unter `tests/`, der ausführbare Browsertest unter `tests/browser/`. Konkrete Befehle, Ergebnisse und die
entdeckten/behobenen Regressionen stehen im [Testbericht](TEST-REPORT.md). Der Browser braucht Node/Playwright nur für die Entwicklung;
Kunden benötigen diese Werkzeuge nicht.

Abschließender lokaler Prüfstand: **2.776 Python-Tests bestanden, ein systemd-Test umgebungsbedingt übersprungen**,
Ruff und Chromium-Ablauf grün. Die vollständige Suite lief in vier Dateigruppen; eine Gruppe wurde nach einem Laufzeitfehler
unter paralleler Last allein erfolgreich wiederholt. Die Testliste wurde mit allen abschließenden JUnit-Ergebnissen abgeglichen.

## Erledigt / Teilweise / Offen

- **Erledigt:** Die sieben oben beschriebenen Implementierungspakete, lokale Regression, Browserablauf, Dokumentation,
  nachvollziehbarer Arbeitszweig und Quellcode-ZIP. Die vorhandenen Änderungen an `app.bat`, `installieren.bat` und `lauf.bat`
  wurden unverändert erhalten und gehören nicht zum neuen Commit.
- **Teilweise:** Kundeninstallation und CI sind vorbereitet. Die Linux-Installation und echte Browserinteraktionen sind geprüft;
  Windows/winget sowie die neuen GitHub-Actions-Jobs wurden in dieser Sitzung nicht ausgeführt.
- **Offen / nicht live verifiziert:** Aktuelle, rechtmäßig gespeicherte Originaldateien je Plattform, echte Händlerzugänge,
  Windows-Kundenabnahme und Abnahme mit einer Kopie des tatsächlichen Kundenbestands. AutoScout24-HTML/CSV ist nicht unterstützt;
  dafür wird ein belegtes, zulässiges Format benötigt. Es wurde keine API erfunden oder freigeschaltet.

Der ROADMAP-Status bleibt deshalb **REVIEW**. Es gibt keine Behauptung einer grünen Remote-CI oder vollständigen Produktivfreigabe.

## Datenquellen in dieser Version

| Quelle/Eingang | Tatsächlicher Umfang |
|---|---|
| Kleinanzeigen | Manuell gespeicherte unterstützte HTML-Seiten, Link/Text, zugeordnete CSV und unterstützte EML. Der einzige registrierte Web-Pull-Adapter bleibt `freigegeben = False`. |
| mobile.de | Vorhandene unterstützte HTML-/Text-/EML-Formate und CSV mit gültigen Inseratlinks. Kein neuer automatischer Plattformabruf. |
| AutoScout24 | Bestehende Zugangskonfiguration bleibt erhalten; kein neu implementierter oder live geprüfter HTML-/CSV-/API-Import. |
| E-Mail-Eingang | Standardmäßig aus; explizit aktivieren, bevor eigene unterstützte `.eml` importiert werden. Kein automatischer Nachrichtenversand durch Import oder Entwurf. |
| Automatische Suche | Infrastruktur und Schalter vorhanden, benötigt ausdrücklich freigegebene, eingerichtete Quelle. Die Standardkonfiguration beschafft keine neuen Anzeigen automatisch. |

## Noch erforderliche praktische Prüfungen

1. Auf einem frischen Windows-Rechner ZIP entpacken, `kundenstart.bat -NurEinrichten` zweimal ausführen, danach App starten.
   Python-Erkennung, winget, Pfad mit Leerzeichen, Dateimarkierung und Browserstart prüfen.
2. [Update-Anleitung](UPDATE-CAMPRCRAWLR.md) mit einer Kopie des Kundenbestands durchführen. Sicherung und Rückkehr zur alten
   Version erproben; Fahrzeugzahl, Preisverläufe, Teamzugänge, Fotos, Termine und Altankäufe vergleichen.
3. Je gewünschtem, zulässigem Format eine aktuelle anonymisierte Originaldatei importieren und ID, Preis/VB, Anbieter,
   Art, Modell, EZ, Kilometer und Ausstattung mit dem Original vergleichen. Reimport und Preissenkung prüfen.
4. Im Händlerteam einen Kontakt selbst vorbereiten und bestätigen, Termin zuweisen, echte Besichtigung auf dem Zielgerät
   erfassen und den Entwurf drucken. Vertragsmuster und betriebliche Aufbewahrungsfristen fachlich freigeben.
5. Den Branch in der vorgesehenen GitHub-Umgebung prüfen; Linux-, Windows-, Installations- und Browser-Jobs ausführen.

## Grenzen der Entwicklungsumgebung

Python 3.13.5, Node 24, Chromium und gesperrte Abhängigkeiten funktionieren hier. Der Container kann keinen systemd-Laufzeitpfad
unter `/run/systemd` anlegen; genau dieser Syntaxcheck wird mit Begründung übersprungen. Der reale systemd-Betrieb ist nicht geprüft.
Das Cloud-Konfigurationswerkzeug lehnt das Speichern der Einrichtungs-/Startanweisungen mit `INVALID_ARGUMENT` ab;
deren dauerhafte Registrierung und Veröffentlichung sind nicht bestätigt. Lokale Ersatzdateien liegen außerhalb des Repos
unter `/workspace/cloud-setup/wohnmobil/install.sh` und `START-AKTUELL.md`.

## Übergabe und Update

Arbeitszweig: `claude/camprcrawlr-haendlerablauf`, auf Basis von `92bc20b`. Kein Merge nach `main` und kein automatisches Deployment.
Das Quellcode-Archiv enthält keine `.venv`, Kundenkonfiguration, Datenbanken, Fotos oder Importdateien aus dem Arbeitsbereich.
Für ein Update zuerst [UPDATE-CAMPRCRAWLR.md](UPDATE-CAMPRCRAWLR.md) lesen und die bisherige Version vollständig sichern.
