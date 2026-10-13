# Wohnmobil-Scout

Durchsucht Kleinanzeigen nach privat angebotenen Wohnmobilen, schätzt für jedes Fahrzeug einen fairen
Marktwert, rechnet daraus den Händler-Einkaufspreis aus und schreibt ein Anschreiben vor, das zu
Modell und Baujahr passt – mit einem vorbehaltlichen Angebot. In der Browser-App klickst du ein
Wohnmobil an und schreibst es mit einem Klick an.

## Einrichtung (einmalig, ca. 5 Minuten)

1. **Python 3.13** installieren (python.org → Downloads → Windows → „Python 3.13.x“ →
   „Windows installer (64-bit)“). 3.10–3.12 gehen auch. **Neuere Versionen wie 3.14/3.15 noch nicht**:
   Für sie gibt es PyYAML nicht fertig für Windows, die Installation bricht dann mit
   „Microsoft Visual C++ 14.0 or greater is required“ ab. 3.13 kann problemlos *zusätzlich* zu
   einer anderen Version installiert sein. Python selbst muss nie geöffnet werden.
2. Diesen Ordner entpacken (Rechtsklick auf die ZIP → „Alle extrahieren“).
3. `config.yaml` mit dem Editor öffnen und anpassen:
   - **anschreiben**: Firma, Name, Telefon, Ort.
   - **suchen**: Suche im Browser auf kleinanzeigen.de zusammenklicken (Ort/Radius, Preis, Art,
     *Anbieter: Privat*), URL kopieren und eintragen. Seitenzahlen ergänzt das Tool selbst.
   - **rechner**: deine echten Kosten und Zielmarge eintragen.
4. **Windows: Doppelklick auf `app.bat`.** Beim ersten Start richtet `installieren.bat` automatisch
   eine eigene Python-Umgebung im Projektordner ein (`.venv`, mit Python 3.13) und installiert dort die
   Zusatzpakete – nur als fertige Pakete, ohne Kompilieren. Globale Python-Einstellungen und andere
   Projekte bleiben unberührt. Danach startet die App sofort. Fehlt Python 3.13, erklärt das Fenster,
   was zu tun ist.
   - Umgebung komplett neu aufbauen: `installieren.bat /neu` (oder den Ordner `.venv` löschen).
   - Mac/Linux: `python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt`,
     danach `.venv/bin/python scout.py app`.

   Der Browser öffnet sich mit `http://127.0.0.1:8765`. Oben rechts auf **„Neue Anzeigen suchen“**
   klicken – oder vorher einmal `python scout.py lauf` ausführen.

## Befehle

| Befehl | Was passiert |
|---|---|
| `python scout.py app` | Browser-App: Wohnmobile anklicken, anschreiben, Status und Notizen speichern, Suchlauf starten |
| `python scout.py lauf` | Crawlen → bewerten → Report, CSV, Anschreiben (+ Mail, falls aktiv) |
| `python scout.py report` | Report neu erzeugen, z. B. nach Änderung der Kosten in `config.yaml` (ohne Internet) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --titel "Knaus Sky TI 650 MEG" --anschreiben` | Einzelfahrzeug durchrechnen und Anschreiben ausgeben (auch für Anfragen außerhalb von Kleinanzeigen; `--text` mit der Beschreibung berücksichtigt Ausstattung/Mängel) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --marktwert 44000` | mit eigenem Marktwert (z. B. aus mobile.de oder DAT) |
| `python scout.py status 3531797014 kontaktiert` | Status setzen: `neu`, `kontaktiert`, `uninteressant`, `gekauft` (in der App per Klick) |

## So rechnet der Einkaufspreis-Rechner (faire Bewertung)

```
Referenzwert       = Neupreis heute (Art × Markenklasse) × Restwert nach Alter
                     × km-Faktor (Laufleistung im Verhältnis zum Alter, ± max. 12 %)
                     × Wertfaktoren (Ausstattung + / genannte Mängel −, verneinte zählen nicht)
Marktniveau        = Referenzwert × Marktfaktor
  Marktfaktor      = gewichteter Median aus (Preis ÷ Referenzwert) vergleichbarer Privatangebote:
                     gleiche Art, EZ ± 3 J., km ± 50.000; gleiche Marke zählt doppelt,
                     nähere Baujahre/km mehr, Ausreißer fliegen raus. Jeder Vergleich wird so
                     auf Alter, km und Ausstattung DIESES Fahrzeugs umgerechnet.
                     Wenige Vergleiche werden zum Referenzmodell hin gemittelt (Gewicht n/(n+4)).
Marktwert privat   = Marktniveau − 7 %   (Angebotspreise werden selten voll bezahlt)
Händler-VK         = Marktwert privat + 10 %
Kosten             = Aufbereitung + HU/Gas + Transport + Standzeit
                     + Gewährleistungsrücklage (2,5 % VK) + Reparaturrisiko (nach Alter, km)
Max. Einkaufspreis = VK − (Ziel-Marge + Kosten) × 1,19     (Differenzbesteuerung §25a)
Erstangebot        = Max-EK × 0,92, aber mind. 75 % vom Marktwert privat (Fair-Untergrenze,
                     höchstens Max-EK) und nie über dem Wunschpreis des Verkäufers
Ampel              grün: Wunschpreis ≤ 110 % vom Max-EK · gelb: ≤ 125 % · rot: darüber
```

Zu jedem Fahrzeug zeigt die App die **Sicherheit** der Schätzung (hoch / mittel / niedrig), eine
plausible **Spanne**, die erkannten **Wertfaktoren** und einen **Fair-Check** (Erstangebot und Max-EK in
Prozent vom privaten Marktwert). Ohne Erstzulassung gibt es bewusst keine Ampel und keinen Betrag – das
Anschreiben fragt dann nach EZ/km.

Alle Beträge, Neupreise, Restwert-Tabelle, Markenklassen und Wertfaktoren stehen in `config.yaml`.
Das Referenzmodell ist ein Startwert; mit jedem Lauf wächst die Datenbank und die echten Angebote
übernehmen. Die ersten Tage am besten mit `rechne --marktwert` (z. B. Wert aus mobile.de/DAT) gegenprüfen.
Die steuerliche Vereinfachung (§25a) bitte einmal mit dem Steuerberater abgleichen.

## Das Anschreiben

Der Text (`vorlagen/anschreiben.txt`, frei änderbar) wird für jedes Fahrzeug passend erzeugt:

- **Modell**: Marke + erkannte Modellreihe + Grundriss, z. B. „Knaus Sky TI 650 MEG“ (Aufbauhersteller
  vor Basisfahrzeug: „Fiat Ducato Knaus …“ → Knaus). Die Modellliste steht in `wmscout/fahrzeug.py`.
- **Baujahr**: EZ und km im ersten Satz, dazu je nach Alter die richtigen Prüfpunkte und Foto-Wünsche
  (jung: Dichtigkeitsprüfungen/Garantie · 4–9 J.: Wartung, Zahnriemen · 10–15 J.: Aufbau, Reifenalter,
  Gasprüfung · älter: zusätzlich Rahmen/Unterboden).
- **Ausstattung**: erkannte Extras (Markise, Solar, Automatik …) und Pflegenachweise werden erwähnt.
- **Vorbehaltliches Angebot**: konkreter Betrag (Erstangebot) „vorbehaltlich einer Besichtigung mit
  Probefahrt und Feuchtigkeitsmessung und sofern der Zustand der Beschreibung entspricht“, unverbindlich,
  mit kurzer Begründung (Vergleichsangebote, Alter, Laufleistung, Ausstattung). Bei gelber Ampel wird
  erklärt, warum der Wunschpreis nicht ganz erreicht wird.

## Automatisch laufen lassen

Am einfachsten: die App offen lassen – sie sucht alle 3 Stunden selbst (`config.yaml` → `app`).

**Windows** (Aufgabenplanung): `lauf.bat` als Aufgabe anlegen, z. B. täglich 7:00, 12:00, 18:00 Uhr.
`lauf.bat` nutzt dieselbe `.venv` wie die App.

**Mac / Linux** (`crontab -e`):
```
5 7,12,18 * * *  cd /pfad/zu/wohnmobil-scout && .venv/bin/python scout.py lauf >> ausgabe/cron.log 2>&1
```

**Mail-Benachrichtigung**: In `config.yaml` unter `email` auf `aktiv: true` stellen und das
SMTP-Passwort als Umgebungsvariable `SCOUT_SMTP_PASSWORT` setzen (bei Gmail ein App-Passwort).
Du bekommst dann nur eine Mail, wenn neue Treffer mit Anschreiben dabei sind.

## Arbeitsablauf

1. `python scout.py app` (oder `app.bat`) – Filter „Anschreiben bereit“ ist vorausgewählt.
2. **Wohnmobil anklicken** → Bewertung prüfen, Text bei Bedarf anpassen.
3. **✉ Anschreiben** (auf der Karte oder im Fenster) → der Text liegt in der Zwischenablage, die Anzeige
   öffnet sich in einem neuen Tab und das Fahrzeug wird als „kontaktiert“ gespeichert (inkl. gesendetem
   Text; „Rückgängig“ im Hinweis unten).
4. Auf Kleinanzeigen **„Nachricht schreiben“** → `Strg`+`V` → Senden.

Status (offen / kontaktiert / uninteressant / gekauft) und Notizen setzt du im Fahrzeugfenster. Unter
„Kontaktiert“ findest du alle angeschriebenen Fahrzeuge mit dem Text, den du geschickt hast.

Der statische Report `ausgabe/report.html` (z. B. aus der Mail) funktioniert genauso, merkt sich den Status
aber nur im jeweiligen Browser.

Das Absenden bleibt bewusst ein Klick von dir: Kleinanzeigen sperrt Konten, die automatisiert
Nachrichten verschicken, und viele Verkäufer reagieren auf Massenanfragen allergisch.

## Wichtige Hinweise

- **Nutzungsbedingungen**: Kleinanzeigen untersagt automatisiertes Auslesen in seinen
  Nutzungsbedingungen. Das Tool ist bewusst langsam (4–9 s Pause, begrenzte Seitenzahl), bricht
  bei Sperren ab und ist nur für den eigenen Arbeitsgebrauch gedacht. Die Nutzung liegt in deiner
  Verantwortung.
- **Händleranfragen**: Anzeigen mit „keine Händler“ o. ä. werden automatisch ausgefiltert
  (Liste unter `filter → sperrbegriffe`). Das Anschreiben nennt dich offen als gewerblichen Ankäufer.
- **Datenschutz**: Gespeichert werden nur Anzeigendaten, keine Kontaktdaten der Verkäufer. Die App ist
  nur auf dem eigenen Rechner erreichbar (127.0.0.1).
- **Wenn plötzlich 0 Anzeigen gefunden werden**, hat Kleinanzeigen vermutlich das Seitenlayout
  geändert. Alle Selektoren liegen in `wmscout/parser.py`.

## Dateien

```
config.yaml               alle Einstellungen (Suchen, Kosten, Marktmodell, Wertfaktoren, Anschreiben)
scout.py                  Startpunkt
app.bat / lauf.bat        Windows: App starten / Suchlauf (beide nutzen .venv)
installieren.bat          richtet .venv mit Python 3.13 ein (läuft automatisch beim Start)
requirements.txt          Zusatzpakete für .venv
.venv/                    projekteigene Python-Umgebung (wird automatisch angelegt)
vorlagen/anschreiben.txt  Text des Anschreibens (Jinja2, frei änderbar – Felder stehen oben in der Datei)
vorlagen/report.html      Oberfläche von App und Report
wmscout/rechner.py        faire Bewertung und Händler-EK
wmscout/fahrzeug.py       Marken, Modellreihen, Modellerkennung
wmscout/app.py            lokale Browser-App (nur 127.0.0.1)
wmscout/                  außerdem Crawler, Parser, Datenbank, Report
ausgabe/                  report.html, anzeigen_bewertet.csv, anschreiben/*.txt, scout.log
daten/anzeigen.sqlite     gesammelte Anzeigen (Grundlage für die Vergleichspreise)
tests/test_offline.py     Selbsttest ohne Internet: .venv\Scripts\python -m tests.test_offline
wmscout/plz_de.csv        PLZ-Koordinaten für Entfernungen (GeoNames, CC BY 4.0)
```
