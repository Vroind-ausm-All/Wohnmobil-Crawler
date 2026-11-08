# CampRCrawlR beim Kunden installieren

## Windows: Einrichtung und Start aus einem Einstieg

1. Den vollständigen Projektordner aus einer vertrauenswürdigen ZIP mit **Alle extrahieren** entpacken,
   beispielsweise unter `Dokumente\CampRCrawlR`. Nicht direkt aus der ZIP starten. Der Ordner benötigt Schreibrechte.
2. **`kundenstart.bat` doppelklicken.** Es prüft die lokale Projektumgebung, den Python-Launcher und Python 3.13.
   Falls Python fehlt, installiert es das exakte Paket `Python.Python.3.13` aus der offiziellen `winget`-Quelle
   für den aktuellen Windows-Benutzer. Dafür ist Internetzugang nötig. Ein vorhandenes Python 3.12 oder 3.14
   wird nicht entfernt oder als Standard umgestellt.
3. Anschließend richtet der Kundenstart die lokale `.venv` ein, lässt `installieren.bat` die gesperrten
   Projektpakete prüfen/installieren und startet `app.bat`. Der Browser öffnet die Anwendung.
   Das App-Fenster bleibt während der Benutzung geöffnet.

Installiert werden Python 3.13 und die in `requirements.txt` festgelegten Python-Pakete. SQLite gehört zu Python;
es ist kein separater Datenbankserver nötig. Node.js, Browser-Testwerkzeuge, Git und Entwicklungswerkzeuge sind
für den Kundenbetrieb nicht erforderlich. Weitere Quellenzugänge, Teamkonten, Tailscale und öffentliche
Serverbereitstellung sind gesonderte Konfigurationen und werden nicht automatisch eingerichtet.

Die Anwendung verwendet ausschließlich `.venv\Scripts\python.exe`. Der Kundenstart installiert keine globalen
pip-Pakete, verändert keine dauerhaften PATH-/PowerShell-Einstellungen und überschreibt keine
`config.local.yaml`, `daten`, `import`, `mandanten` oder sonstigen Kundendaten. Bestehende Datenbanken werden
beim regulären App-Start nach den vorhandenen Migrationsregeln mit vorgeschalteter Sicherung aktualisiert.
Der offizielle Python-Installer registriert seine eigene benutzerlokale Installation; bestehende
Python-Launcher-Zuordnungen und Dateiverknüpfungen werden durch die gewählten Installeroptionen nicht ersetzt.

## Wenn die Einrichtung nicht startet

- **PowerShell blockiert die Datei:** Die Startdatei verwendet `RemoteSigned` nur für diesen Prozess.
  Bei einer heruntergeladenen ZIP kann Windows die enthaltenen Skripte weiterhin als Internetdateien markieren.
  Bei vertrauenswürdiger Herkunft: Rechtsklick auf die ZIP → **Eigenschaften** → **Zulassen**, danach erneut
  entpacken. Unternehmensrichtlinien haben Vorrang; hierfür die IT kontaktieren. Keine Signatur- oder
  Sicherheitsprüfungen abschalten. Alternativ den unten beschriebenen manuellen Weg verwenden.
- **`winget` fehlt:** Microsoft App Installer aktualisieren oder Python 3.13.x manuell von
  <https://www.python.org/downloads/windows/> installieren. Den Python-Launcher mitinstallieren.
  „Add python.exe to PATH“ ist nicht erforderlich. Danach `kundenstart.bat` erneut starten.
- **Netzwerk-/Paketfehler:** Die konkrete Meldung im Fenster prüfen; der Paketdownload benötigt insbesondere
  `pypi.org` und `files.pythonhosted.org`. Unternehmensproxy oder Firewall durch die IT konfigurieren lassen.
  TLS-, Paket-Hash- und Installerprüfungen bleiben eingeschaltet.
- **Vorhandene `.venv` defekt oder falsche Version:** App beenden, ausschließlich den Ordner `.venv` zur
  Aufbewahrung umbenennen und den Kundenstart wiederholen. Datenordner und Konfiguration behalten.
  Der Kundenstart löscht eine vorgefundene Umgebung nicht automatisch.

Manueller Weg ohne PowerShell/winget: Python **3.13.x** samt Launcher von python.org installieren,
danach **`app.bat`** starten. Die bisherigen Start- und Installationsdateien bleiben verfügbar.

## Update ohne Datenverlust

Vor jedem Update mit der alten Version `.venv\Scripts\python.exe scout.py sichern` ausführen und die
geprüfte Sicherung zusätzlich außerhalb des Projektordners verwahren. App und geplante Suchläufe beenden.
Programmdateien aktualisieren, dabei `config.local.yaml`, Daten-/Foto-/Import-/Mandantenordner und eigene Vorlagen
behalten. Bestehende `.venv` auf demselben Rechner kann wiederverwendet werden; `kundenstart.bat` prüft neue
gesperrte Paketversionen. Eine `.venv` nicht von einem anderen Rechner kopieren.

## Automatisierte Einrichtung und Prüfstand

`kundenstart.bat -NurEinrichten` oder `powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File
.\kundenstart.ps1 -NurEinrichten` richtet nur die Umgebung ein. Es startet weder App noch Browser und pausiert
nicht. In CI muss Python 3.13 vorher bereitgestellt sein (etwa `actions/setup-python`); dort wird kein
Systeminstaller gestartet. Ein Fehler führt zu einem von null verschiedenen Exit-Code.

Der Entwicklungscontainer ist Linux und enthält kein PowerShell. Hier wurden Dateiformat, CRLF der neuen
Batchdatei, Anschluss an die bestehenden Skripte und sicherheitsrelevante Optionen statisch geprüft.
**Windows-Ausführung, PowerShell-Syntaxprüfung und frische winget-Installation sind lokal nicht geprüft.**
Der Windows-CI-Schritt mit vorhandenem Python kann den wiederholten Einrichtungsweg prüfen; eine echte
Kundenabnahme auf einem frischen Windows-Rechner bleibt erforderlich, insbesondere für winget, Dateimarkierung,
Unternehmensrichtlinien und den automatischen Browserstart.
