# Wohnmobil-Scout

Durchsucht Kleinanzeigen nach privat angebotenen Wohnmobilen, rechnet für jedes Fahrzeug den
maximalen Händler-Einkaufspreis aus und erzeugt passende Anschreiben. Ergebnis ist ein
HTML-Report (`ausgabe/report.html`) mit Ampel, Kalkulation und Anschreiben zum Kopieren.

## Einrichtung (einmalig, ca. 5 Minuten)

1. Python 3.10+ installieren (Windows: python.org, Haken bei „Add to PATH“).
2. Im Ordner dieses Projekts:
   ```
   pip install -r requirements.txt
   ```
3. `config.yaml` öffnen und anpassen:
   - **suchen**: Suche im Browser auf kleinanzeigen.de zusammenklicken (Ort/Radius, Preis, Art,
     *Anbieter: Privat*), URL kopieren und eintragen. Seitenzahlen ergänzt das Tool selbst.
   - **rechner**: deine echten Kosten und Zielmarge eintragen.
   - **anschreiben**: Firma, Name, Telefon.
4. Erster Lauf:
   ```
   python scout.py lauf
   ```
   Danach `ausgabe/report.html` im Browser öffnen.

## Befehle

| Befehl | Was passiert |
|---|---|
| `python scout.py lauf` | Crawlen → bewerten → Report, CSV, Anschreiben (+ Mail, falls aktiv) |
| `python scout.py report` | Report neu erzeugen, z. B. nach Änderung der Kosten in `config.yaml` (ohne Internet) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --marke Knaus` | Einzelfahrzeug durchrechnen (auch für Anfragen außerhalb von Kleinanzeigen) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --marktwert 44000` | mit eigenem Marktwert (z. B. aus mobile.de oder DAT) |
| `python scout.py status 3531797014 kontaktiert` | Status setzen: `neu`, `kontaktiert`, `uninteressant`, `gekauft` – kontaktierte erscheinen nicht mehr mit Anschreiben |

## So rechnet der Einkaufspreis-Rechner

```
Vergleichspreis    = Median ähnlicher Privatangebote in der Datenbank
                     (gleiche Art + Marke, EZ ± 2 Jahre, km ± 40.000; ohne Marke, wenn zu wenige)
Marktwert privat   = Vergleichspreis − 7 %   (Angebotspreise werden selten voll bezahlt)
Händler-VK         = Marktwert privat + 10 %
Kosten             = Aufbereitung + HU/Gas + Transport + Standzeit
                     + Gewährleistungsrücklage (2,5 % VK) + Reparaturrisiko (nach Alter, km)
Max. Einkaufspreis = VK − (Ziel-Marge + Kosten) × 1,19     (Differenzbesteuerung §25a)
Erstangebot        = Max-EK × 0,92
Ampel              grün: Angebotspreis ≤ 110 % vom Max-EK · gelb: ≤ 125 % · rot: darüber
```

Alle Prozentsätze und Beträge stehen in `config.yaml`. Die Vergleichsbasis wird mit jedem Lauf
besser, weil die Datenbank wächst. Die ersten Tage am besten mit `--marktwert` gegenprüfen.
Die steuerliche Vereinfachung (§25a) bitte einmal mit dem Steuerberater abgleichen.

## Automatisch laufen lassen

**Windows** (Aufgabenplanung): `lauf.bat` als Aufgabe anlegen, z. B. täglich 7:00, 12:00, 18:00 Uhr.

**Mac / Linux** (`crontab -e`):
```
5 7,12,18 * * *  cd /pfad/zu/wohnmobil-scout && /usr/bin/python3 scout.py lauf >> ausgabe/cron.log 2>&1
```

**Mail-Benachrichtigung**: In `config.yaml` unter `email` auf `aktiv: true` stellen und das
SMTP-Passwort als Umgebungsvariable `SCOUT_SMTP_PASSWORT` setzen (bei Gmail ein App-Passwort).
Du bekommst dann nur eine Mail, wenn neue Treffer mit Anschreiben dabei sind.

## Arbeitsablauf

1. Mail kommt bzw. Report öffnen → Filter „Anschreiben bereit“.
2. Karte anklicken → Kalkulation prüfen, Text ggf. anpassen.
3. „Text kopieren & Anzeige öffnen“ → auf Kleinanzeigen „Nachricht schreiben“, einfügen, senden.
4. „Als kontaktiert markieren“ (bzw. `scout.py status … kontaktiert` für dauerhaft).

Das Absenden bleibt bewusst ein Klick von dir: Kleinanzeigen sperrt Konten, die automatisiert
Nachrichten verschicken, und viele Verkäufer reagieren auf Massenanfragen allergisch.

## Wichtige Hinweise

- **Nutzungsbedingungen**: Kleinanzeigen untersagt automatisiertes Auslesen in seinen
  Nutzungsbedingungen. Das Tool ist bewusst langsam (4–9 s Pause, begrenzte Seitenzahl), bricht
  bei Sperren ab und ist nur für den eigenen Arbeitsgebrauch gedacht. Die Nutzung liegt in deiner
  Verantwortung.
- **Händleranfragen**: Anzeigen mit „keine Händler“ o. ä. werden automatisch ausgefiltert
  (Liste unter `filter → sperrbegriffe`). Das Anschreiben nennt dich offen als gewerblichen Ankäufer.
- **Datenschutz**: Gespeichert werden nur Anzeigendaten, keine Kontaktdaten der Verkäufer.
- **Wenn plötzlich 0 Anzeigen gefunden werden**, hat Kleinanzeigen vermutlich das Seitenlayout
  geändert. Alle Selektoren liegen in `wmscout/parser.py`.

## Dateien

```
config.yaml               alle Einstellungen
scout.py                  Startpunkt
vorlagen/anschreiben.txt  Text des Anschreibens (Jinja2, frei änderbar)
vorlagen/report.html      Aussehen des Reports
wmscout/                  Crawler, Parser, Datenbank, Rechner
ausgabe/                  report.html, anzeigen_bewertet.csv, anschreiben/*.txt, scout.log
daten/anzeigen.sqlite     gesammelte Anzeigen (Grundlage für die Vergleichspreise)
tests/test_offline.py     Selbsttest ohne Internet: python -m tests.test_offline
```
