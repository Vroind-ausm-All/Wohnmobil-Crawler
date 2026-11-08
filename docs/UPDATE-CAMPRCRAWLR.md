# CampRCrawlR sicher aktualisieren

Die neue Version führt Schema 24 ein: bestätigte Fahrzeugfelder werden zusätzlich gespeichert. Bestehende Importdaten
werden nicht umgeschrieben; die Migration legt vor Änderungen mit der vorhandenen Sicherungsfunktion ein Backup an.

1. App, Suchlauf, geplante Aufgaben und weitere schreibende Prozesse beenden. Mit der bisherigen Version
   `.venv/bin/python scout.py sichern` (Windows: `.venv\Scripts\python scout.py sichern`) ausführen und den Erfolg prüfen.
2. Zusätzlich den bisherigen Projektordner als vollständige Sicherheitskopie aufbewahren. Insbesondere
   `config.local.yaml`, eigene `*.local.yaml`, angepasste `config.yaml`/`maengel.yaml`/Vorlagen,
   `daten/` einschließlich Fotos und Dokumenten, `mandanten/`, `import/`, `ausgabe/` und Sicherungen behalten.
3. Neue Version in einen **neuen Ordner** entpacken. Die `.venv` nicht aus dem alten Ordner kopieren.
   Unter Windows `kundenstart.bat -NurEinrichten` (oder bei bereits vorhandenem Python 3.13 `installieren.bat`),
   unter Linux/macOS `./installieren.sh` ausführen. So wird zunächst nur die Umgebung eingerichtet.
4. Bei weiter gestoppter alter App eigene Konfiguration und Datenordner in den neuen Ordner übernehmen.
   Bei benutzerdefinierten absoluten Datenpfaden sicherstellen, dass nicht beide Versionen gleichzeitig dieselbe Datenbank nutzen.
   Versionierte Vorlagenänderungen gezielt vergleichen, nicht blind ersetzen.
5. Neue App starten. Das Protokoll meldet ggf. die Migration und ihr Backup. Falls sie scheitert, abbrechen und den
   konkreten Fehler prüfen; keine Datenbank löschen. Fahrzeuganzahl, Teamzugänge, Bilder, Termine und einen Altankauf prüfen.
6. Eine eigene rechtmäßig gespeicherte Beispieldatei importieren und Titel, Preis, Verkäuferstatus, Reimport und Preisverlauf kontrollieren.
   Zuerst mit einer Kopie des Datenbestands erproben, bevor der bisherige Ordner ersetzt wird.

## Zurück zur bisherigen Version

Eine ältere Programmversion darf die Schema-24-Datenbank nicht öffnen. Alle Prozesse stoppen und die vor dem Update
angelegte vollständige Kopie bzw. das Backup zusammen mit der dazugehörigen alten Programmversion wiederherstellen.
Seit dem Update hinzugekommene Daten zunächst separat sichern. Keine Schema-Nummer von Hand zurücksetzen.

## Nach der Übernahme

Manuelle Bestätigungen sind nur bei selbst geprüften Angaben sinnvoll. Bei Konflikten zeigt der Fahrzeugdialog sowohl den
Importwert als auch den bestätigten Wert. Bestätigungen lassen sich dort einzeln zurücknehmen. Alte Inserate bleiben sichtbar
und werden bei fehlender aktueller Bestätigung als möglicherweise veraltet markiert.

Automatische Marktplatzabfragen sind keine Updatevoraussetzung. Kleinanzeigen bleibt als Livequelle gesperrt.
Die Offline-Tests mit synthetischen Dateien sind keine Abnahme aktueller Plattformlayouts oder rechtlicher Zugangsberechtigungen.
