# Wohnmobil-Scout

Durchsucht Kleinanzeigen nach privat angebotenen Wohnmobilen, schätzt für jedes Fahrzeug einen fairen
Marktwert, rechnet daraus den Händler-Einkaufspreis aus und schreibt ein Anschreiben vor, das zu
Modell und Baujahr passt – mit einem vorbehaltlichen Angebot. In der Browser-App klickst du ein
Wohnmobil an und schreibst es mit einem Klick an.

## Einrichtung (einmalig, ca. 5 Minuten)

1. **Python 3.13** installieren (python.org → Downloads → Windows → „Python 3.13.x“ →
   „Windows installer (64-bit)“). Ältere Versionen werden nicht unterstützt. **Neuere Versionen wie 3.14/3.15 noch nicht**:
   Für sie gibt es PyYAML nicht fertig für Windows, die Installation bricht dann mit
   „Microsoft Visual C++ 14.0 or greater is required“ ab. 3.13 kann problemlos *zusätzlich* zu
   einer anderen Version installiert sein. Python selbst muss nie geöffnet werden.
2. Diesen Ordner entpacken (Rechtsklick auf die ZIP → „Alle extrahieren“).
3. `config.yaml` mit dem Editor öffnen und anpassen:
   - **anschreiben**: Firma, Name, Telefon, Ort.
   - **suchen**: Suche im Browser auf kleinanzeigen.de zusammenklicken (Ort/Radius, Preis, Art,
     *Anbieter: Privat*), URL kopieren und eintragen. Seitenzahlen ergänzt das Tool selbst.
   - **rechner**: deine echten Kosten und Zielmarge eintragen.

   Tipp: Eigene Werte lieber in eine neue Datei `config.local.yaml` daneben schreiben (gleiche Abschnitte, nur die
   Abweichungen). Sie überlagert `config.yaml`, wird nie ins Repository übernommen und bleibt bei Updates erhalten.
4. **Windows: Doppelklick auf `app.bat`.** Beim ersten Start richtet `installieren.bat` automatisch
   eine eigene Python-Umgebung im Projektordner ein (`.venv`, mit Python 3.13) und installiert dort die
   Zusatzpakete – nur als fertige Pakete, ohne Kompilieren. Globale Python-Einstellungen und andere
   Projekte bleiben unberührt. Danach startet die App sofort. Fehlt Python 3.13, erklärt das Fenster,
   was zu tun ist.
   - Umgebung komplett neu aufbauen: `installieren.bat /neu` (oder den Ordner `.venv` löschen).
   - Mac/Linux: `./start.sh` (richtet `.venv` über `installieren.sh` genauso automatisch ein).

   Der Browser öffnet sich mit `http://127.0.0.1:8765`. Oben rechts auf **„Neue Anzeigen suchen“**
   klicken – oder vorher einmal `python scout.py lauf` ausführen.

## Handy-App fürs Team

Unterwegs mit dem Handy anschreiben, Besichtigungen planen und zuweisen, beim Verkäufer Mängel erfassen (mit
Fotos und live mitlaufendem Preisabzug, auch ohne Netz) und das Ankaufprotokoll unterschreiben lassen.
Einrichtung (Nutzer anlegen, Tailscale, App auf den Startbildschirm): **[docs/HANDY-APP.md](docs/HANDY-APP.md)**.

**Team-Übersicht (in Arbeit):** Sobald Nutzer angelegt sind, merkt sich der Scout, wer welches Fahrzeug bearbeitet.
„Ich übernehme“ reserviert ein Fahrzeug (Standard 2 Tage, `config.yaml → team → reservierung_tage`, 0 = nie);
Anschreiben, Verhandlung oder Besichtigung übernehmen es automatisch. Ein Kollege bekommt dann „Reserviert von …“
statt doppelt anzuschreiben. Nur der Inhaber kann eine fremde Reservierung aufheben oder zuweisen. Die CSV hat am
Ende die Spalten „Bearbeiter“, „Übernommen am“, „Kontaktiert von“. Die Anzeige in Desktop- und Handy-App (Badges,
Knöpfe, Filter) folgt mit Paket T2 – **bis dahin die Team-Funktion nicht im Alltag nutzen**. Status per Kommandozeile:
`scout.py status <id> <status> --nutzer NAME`. Ohne `--nutzer` ist das ein Verwaltungsbefehl ohne Team-Regeln:
es wird niemand als Bearbeiter eingetragen (eine bestehende Reservierung bleibt bis zu ihrem Ablauf).

## Befehle

| Befehl | Was passiert |
|---|---|
| `python scout.py app` | Browser-App: Wohnmobile anklicken, anschreiben, Status und Notizen speichern, Suchlauf starten |
| `python scout.py lauf` | Crawlen → bewerten → Report, CSV, Anschreiben (+ Mail, falls aktiv) |
| `python scout.py import` | Im Browser gespeicherte Kleinanzeigen- und mobile.de-Seiten aus dem Ordner `import/` einlesen, bewerten, Report erzeugen (ohne Internet; anderer Ordner: `--ordner PFAD`) |
| `python scout.py import --mails` | Suchagent-Benachrichtigungen (`.eml` aus `import/email/`) einlesen, bewerten, Report erzeugen – nur bei eingeschaltetem Eingang `email` |
| `python scout.py quellen liste` | Pull-Quellen (Suchlauf) und Eingänge mit Status anzeigen; `quellen an KENNUNG` / `quellen aus KENNUNG` schaltet eine Quelle – `an` nur, wenn sie im Code freigegeben ist (Kleinanzeigen ist es nicht; der Suchlauf überspringt sie dann ohne Fehler). Eingänge (`seiten`, `text`, `email`) schaltest du in `config.yaml` unter `eingaenge`; ausgeschaltet wird nichts eingelesen |
| `python scout.py report` | Report neu erzeugen, z. B. nach Änderung der Kosten in `config.yaml` (ohne Internet) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --titel "Knaus Sky TI 650 MEG" --anschreiben` | Einzelfahrzeug durchrechnen und Anschreiben ausgeben (auch für Anfragen außerhalb von Kleinanzeigen; `--text` mit der Beschreibung berücksichtigt Ausstattung/Mängel) |
| `python scout.py rechne --preis 42900 --ez 2017 --km 85000 --marktwert 44000` | mit eigenem Marktwert (z. B. aus mobile.de oder DAT) |
| `python scout.py nutzer anlegen Anna --rolle inhaber --telefon "+49 170 …"` | Team-Zugang für die Handy-App (auch `liste`, `passwort`, `sperren`, `entsperren`); das Passwort wird abgefragt – nie als Argument, für Skripte nur über die Umgebungsvariable `SCOUT_NEUES_PASSWORT` |
| `python scout.py sichern` | Datenbank und Fotos sichern (siehe „Datensicherung“) |
| `python scout.py wiederherstellen <Datei> --bestaetigt [--ohne-fotos]` | Sicherung zurückspielen – vorher App und Suchlauf beenden |
| `python scout.py status 3531797014 kontaktiert` | Status setzen: `neu`, `kontaktiert`, `uninteressant`, `gekauft` (in der App per Klick) |

## Datensicherung

* `python scout.py sichern` legt eine geprüfte Kopie der Datenbank (SQLite-Backup, `integrity_check`) in
  `daten/sicherungen/` ab, die Fotos (`daten/fotos/`) als ZIP daneben. Es bleiben die letzten 10 Sicherungen erhalten
  (`config.yaml` → `sicherung`: `ordner`, `behalten`); andere Dateien im Ordner werden nie gelöscht.
* **Vor jedem Update sichern** – und die Sicherungen gelegentlich auf ein anderes Laufwerk oder einen USB-Stick kopieren.
  Vor jeder Datenbank-Migration (neue Programmversion mit Schemaänderung) wird automatisch gesichert; ohne gelungene
  Sicherung wird nicht migriert.
* Zurückspielen: App und Suchlauf (auch `lauf.bat`, geplante Aufgaben) beenden, dann
  `python scout.py wiederherstellen daten/sicherungen/<Datei>.sqlite --bestaetigt`. Der bisherige Stand wird vorher
  selbst gesichert, bisherige Fotos werden nur umbenannt (`fotos.alt-…`), nicht gelöscht.
  **App vorher wirklich beenden:** Die technische Sperrprüfung erkennt nur *aktive Schreibvorgänge* (Suchlauf, gerade
  speichernde App), nicht eine geöffnete, gerade ruhende App.
* Ist das Foto-Archiv einer Sicherung beschädigt oder abgeschnitten, bricht das Zurückspielen ab und ändert nichts. Mit
  `python scout.py wiederherstellen <Datei> --bestaetigt --ohne-fotos` wird dann nur die Datenbank zurückgespielt; der
  Fotoordner bleibt unverändert.
* **Netzlaufwerke/UNC-Pfade (`\\server\share`) sind nicht geprüft.** Datenbank, Fotos und Sicherungsordner gehören auf ein
  lokales Laufwerk; SQLite-Dateisperren sind auf Netzfreigaben unzuverlässig.
* Ist die Datenbank neuer als das Programm (Schemaversion), startet es nicht – bitte das Programm aktualisieren.
* **Datenschutz:** Sicherungen (`*.sqlite`, `*.fotos.zip`), Rohkopien defekter Datenbanken (`*.defekt`, `*-reste-*`) und
  umbenannte Fotoordner (`fotos.alt-…`) enthalten personenbezogene Daten (Verkäufernamen, Telefonnummern, Anschriften,
  Notizen, Fotos). Nur dort aufbewahren, wo sie hingehören, und nach einer festgelegten Frist selbst löschen – das
  automatische Löschen/Anonymisieren folgt mit P1-14a. Das Programm löscht `.defekt`-, `-reste-`- und `fotos.alt-…`-Kopien nie.
  Bei einem Abbruch (Absturz, Stromausfall) können Arbeitsdateien übrig bleiben: `.….teil`, `.….reserviert` im Sicherungsordner
  sowie `.anzeigen.sqlite.….wiederherstellung.teil` und `.fotos.….wiederherstellung.teil` neben der Datenbank. Sie werden beim
  nächsten Sichern bzw. Wiederherstellen nach über einer Stunde automatisch entfernt; bis dahin enthalten sie personenbezogene Daten.
* Vor einer Migration angelegte Sicherungen (`…-vor-v3`) bleiben erhalten, bis eine normale Sicherung nach `behalten`
  aufräumt; beim Zurückspielen bleibt die verwendete Sicherung immer erhalten.

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
  vor Basisfahrzeug: „Fiat Ducato Knaus …“ → Knaus). Die Modellliste steht in `wmscout/normalisierung/fahrzeug.py`.
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
   öffnet sich in einem neuen Tab und das Fahrzeug steht auf „Text kopiert“ (Text gespeichert; „Rückgängig“ im
   Hinweis unten). Im Team öffnet sich die Anzeige erst, wenn der Server das Fahrzeug für dich reserviert hat –
   hält es ein Kollege, erscheint stattdessen ein roter Hinweis, wer es bearbeitet.
4. In der Anzeige den Kontakt öffnen – bei Kleinanzeigen **„Nachricht schreiben“**, bei mobile.de das **„E-Mail“/„Nachricht“-Formular** des Anbieters → `Strg`+`V` → Senden.
5. **gesendet ✓** klicken – erst jetzt gilt der Verkäufer als „kontaktiert“ (ADR-012).

**Verkaufsanfragen (Phase B, erst intern):** Unter **`/verkaufen`** erfasst ihr ein Fahrzeug, das ein Verkäufer euch selbst
anbietet (Telefon, vor Ort oder Formular am Tablet): Fahrzeug, Mängel, bis zu 12 Fotos, freiwillige Preisvorstellung,
Kontakt und Einwilligung. Danach erscheinen Referenz und – nur bei sicherer Datenlage – eine grobe Spanne für den
Verkäufer (nie Max-EK oder Angebot). Unter **`/anfragen`** stehen alle Anfragen mit Bewertung, Fotos, Status, Bearbeiter
und Verlauf. Es geht keine automatische Nachricht an Verkäufer. Öffentlich erreichbar ist das Portal noch nicht (ADR-025).

**Händlerportal für eure Standorte (Phase C, erst intern):** Standorte legt der Inhaber unter **`/standorte`** an und schaltet
sie nach Prüfung frei; Zugänge: `python scout.py nutzer anlegen NAME --rolle haendler --standort "Filiale Nord"`. Ein
Standort-Zugang sieht nur **`/haendler`**: Verkaufsanfragen, bei denen der Verkäufer der Weitergabe zugestimmt hat UND der
Inhaber sie in `/anfragen` freigegeben hat – anonym (Region „12xxx“, ohne Name/Telefon/E-Mail) mit Preisvorstellung und
Fotos; „Interesse melden“ ist unverbindlich und erscheint bei der Anfrage. Sperren eines Standorts wirkt sofort (ADR-026).

**Demo-Auktionen (Phase D, nur Demo – nicht verbindlich):** Bei einer freigegebenen Anfrage startet der Inhaber in
`/anfragen` eine Demo-Auktion (Startpreis, Mindestpreis – Standard: Preisvorstellung –, Laufzeit 1–168 h). Geprüfte
Standorte bieten in `/haendler` in ganzen Euro, mindestens 100 € über dem Höchstgebot; ein Gebot in den letzten 2 Minuten
verlängert um 2 Minuten. Bieter sehen das Höchstgebot und „Mindestpreis erreicht ja/nein“, nie den Mindestpreis oder andere
Standorte. Nach dem Ende entscheidet allein der Inhaber („Zuschlag bestätigen (Demo)“ oder „Kein Zuschlag“); es geht keine
Nachricht hinaus. Jedes Gebot steht in einem hash-verketteten Protokoll: `python scout.py auktion pruefen` (oder „Protokoll
prüfen“) zeigt, ob etwas verändert wurde. Einstellungen: `config.yaml` → `auktion` (ADR-027).

**Deal-Kalkulation (Phase E):** Direkt am Gebotsfeld sehen Standorte zum eingegebenen Betrag den erwarteten Gewinn, den
Max-EK („sicher bis“ und Obergrenze) sowie Szenarien vorsichtig/erwartet/günstig aus der Marktspanne, einen Risikowert mit
Begründung und alle Annahmen (Kosten, Zielmarge, §25a, Provision, Transport ab Standort). In `/anfragen` rechnet das Team
dasselbe ab Firmensitz und kann speichern. Jedes Gebot speichert die gezeigte Kalkulation samt eingefrorener Eingabe;
„nachrechnen“ bzw. `python scout.py kalkulation pruefen` zeigt, dass sie sich exakt wiederholen lässt. Provision:
`config.yaml` → `kalkulation.provision_prozent` (Standard 2 %, ADR-028).

**Besichtigung und Abwicklung (Phase F):** Auch Verkaufsanfragen werden mit der Handy-App besichtigt (planen in `/anfragen`).
Wird eine Besichtigung mit „gekauft“ abgeschlossen – bei Anfragen wie bei Inseraten –, entsteht unter **`/ankaeufe`** ein
Ankaufsvorgang: druckbares Vertragsmuster (ohne Rechtsgewähr, vor Einsatz prüfen lassen), „Vertrag unterschrieben“ bestätigen
und Scan hochladen, Übergabe und Zahlung, Ist-Kosten, Verkauf. Jeder Vorgang zeigt den Weg vom Angebot bzw. Gebot bis zum
Verkauf mit Belegen und vergleicht Plan (eingefrorene Kalkulation) mit Ist; die Übersicht zeigt die mittleren Abweichungen als
Grundlage, die Kalkulation bewusst nachzustellen (ADR-029).

**Team (nur mit angelegten Nutzern):** An jedem Fahrzeug zeigt ein Abzeichen mit Symbol und Kürzel, wer es bearbeitet
(◔ reserviert, ✉ kontaktiert, ⧉ Dublette, ? ohne Zuordnung, ! verwaist; eigene gefüllt, fremde umrandet). „Ich übernehme“ /
„Abgeben“ auf Karte und im Fenster; der Inhaber kann zusätzlich zuweisen und eine Übernahme erzwingen. Oben stehen die
Zähler je Mitarbeiter (Mitarbeiter sehen nur die eigenen), der Filter **Wer: Alle / Meine / Frei** blendet fremde Fahrzeuge
aus. Der Stand der Kollegen wird jede Minute und beim Zurückkehren zur Seite neu geladen.

**Dubletten entscheiden (Büro-PC, Inhaber und Mitarbeiter):** Der Filter **„Dublettenvorschläge (n)“** zeigt Inserate, die dasselbe Fahrzeug
sein könnten (Stufe „hoch“ oder „mittel“ mit Gründen, beide Inserate nebeneinander). **„Gleiches Fahrzeug“** (Inhaber und Mitarbeiter)
führt sie zusammen: nicht doppelt anschreiben, zählt einmal in der Vergleichsbasis. **„Verschieden“** (nur Inhaber) sperrt das Paar für
künftige Vorschläge. Beides fragt vorher mit den Folgen nach; nichts passiert automatisch. Im Fahrzeugfenster zeigt „Gleiches Fahrzeug“
die Gruppe, den Fahrzeugstatus und den Verlauf; **„Aufheben“** (nur Inhaber) nimmt eine Entscheidung zurück (Reihenfolge: erst die
spätere Zusammenführung). Halten verschiedene Kollegen Inserate einer Gruppe, erscheint eine Warnung. Auf dem Handy wird die Gruppe nur angezeigt.

**Gespeicherte Seiten einlesen:** Öffne eine Suchergebnisseite oder eine einzelne Anzeige auf Kleinanzeigen
ganz normal im Browser, drücke `Strg`+`S` und speichere sie als „Webseite, nur HTML“ in den Ordner `import`
im Programmordner. Dann in der App auf **„⤓ Gespeicherte Seiten einlesen“** klicken (oder `python scout.py import`).
Neue Fahrzeuge erscheinen sofort in der Liste; das Programm ruft dafür nichts selbst aus dem Internet ab.
Eingelesene Dateien wandern nach `import/eingelesen/<Datum>/`, nicht erkannte nach `import/nicht_erkannt/`.

**Anzeige per Adresse + Text einlesen** (jedes Teammitglied, Desktop und Handy; API `POST /api/import/text`): Adresse der einzelnen
Anzeige (Kleinanzeigen oder mobile.de) und den kopierten Anzeigentext einfügen, optional „privat“/„gewerblich“ wählen. Der Server ruft die
Adresse **nicht** ab – sie liefert nur Plattform und Anzeigen-ID; Preis, Kilometer, Erstzulassung, PLZ/Ort und Titel kommen aus dem Text
(fehlt etwas, steht „unvollständig: …“ im Ergebnis; ohne Erstzulassung gibt es keine Beträge). **Ein Preis wird nur gespeichert, wenn er klar gekennzeichnet ist (VB, „Preis: …“, eigene Zeile) oder du ihn im Feld „Preis laut Anzeige“ einträgst** – Beträge im Fließtext zählen nie; bereits vorhandene Angaben anderer Kanäle bleiben bestehen. Telefonnummern, E-Mail-Adressen, Links,
Straßen und Namenszeilen werden vor dem Speichern entfernt, Gesuche („Suche Wohnmobil …“) nicht gespeichert, die Fahrzeugart höchstens
„vorläufig“. Dieselbe Anzeige per Seite und per Text ist eine Zeile. Abschaltbar über `eingaenge.text.aktiv: false`.
Bedienung: Desktop **„＋ Inserat einlesen (Link + Text)“** neben „Gespeicherte Seiten einlesen“, Handy **„Heute“ → „＋ Inserat einlesen“**. Nach dem Einlesen
zeigt die Seite das Ergebnis (neu / Preis gesenkt / bereits bekannt, erkannte Felder, alle Hinweise) mit Link zum Fahrzeug; „gesendet ✓“ bleibt
die einzige Bestätigung einer Kontaktaufnahme. Nur Anzeigentext einfügen – keine Namen, Telefonnummern oder Adressen des Verkäufers.
Online-Aktion: ohne Netz bleibt der Text im Formular stehen, es wird nichts zwischengespeichert.

**Auch mobile.de:** Genauso geht es mit **mobile.de** – Wohnmobil-Suche (Treffer-Liste) oder einzelne Anzeige im Browser öffnen,
`Strg`+`S`, als „Webseite, komplett“ (so sind die Testseiten gespeichert worden) oder „Webseite, nur HTML“ (für mobile.de noch nicht
geprüft) im selben Ordner `import` speichern. Kleinanzeigen- und
mobile.de-Seiten dürfen gemischt im Ordner liegen; das Programm erkennt die Plattform an der Seite selbst. Es wird auch hier nichts
aus dem Internet geladen – weder Anzeigen hinter den Links noch Bilder (die mobile.de-AGB untersagen automatisierte Abfragen). Tipps:
In der mobile.de-Suche den Filter **„Privatanbieter“** setzen (linke Spalte „Anbieter“), dann stehen in der Liste nur private
Verkäufer; jede Suchseite enthält höchstens 20 Treffer, weitere Seiten einzeln speichern. Die Treffer tragen als Nummer `md-<mobile.de-ID>`.
Gesponserte Plätze („Gesponsert“) werden mitgelesen, weil es normale Anzeigen sind. Gewerbliche Anbieter („Gewerbe“, Händler mit
Namen) werden als gewerblich erkannt und – wie bei Kleinanzeigen – nicht zum Anschreiben vorgeschlagen. Fehlt bei einem Treffer der
Anbieterkasten, ist der Anbieter **unbekannt** (nicht „privat“): das Fahrzeug trägt den Hinweis „Anbieter unbekannt“, zählt nicht zur
Vergleichsbasis des Rechners, und beim Einlesen wird die Zahl gemeldet (über die Hälfte der Treffer: Seitenlayout vermutlich geändert). Es werden nur **Wohnmobile und Wohnwagen**
eingelesen; Pkw-Treffer oder -Anzeigen (z. B. Kategorie „Limousine“) landen mit einer Meldung in `import/nicht_erkannt/` bzw. werden
übersprungen und gemeldet. **Orte im Ausland** („SE-123 45 Ort“, „FR-75001 Paris“): keine Entfernung, Ampel höchstens gelb, Brief ohne Betrag
und der Hinweis „Ausland – Abholung, Überführung und Zulassung prüfen“; mit `max_entfernung_km` > 0 werden sie nicht angeschrieben.

Hinweise zum Einlesen:
- Je Klick werden höchstens 25 Dateien (bzw. etwa 20 Sekunden lang) gelesen; den Rest liest der nächste Klick.
  Dateien über 20 MB werden nicht gelesen (sie bleiben liegen).
- Die Fahrzeugart (z. B. Teilintegrierter) bestimmt, wie der Scout den Wert rechnet. **Bestätigt** ist sie bei einer
  Suche über den Art-Filter von Kleinanzeigen (linke Spalte; er gilt nur für die Treffer der eigentlichen Trefferliste,
  nicht für „Weitere Ergebnisse in anderen Orten“) oder wenn die Detailseite der Anzeige mit eingelesen wird (die
  Detailseite hat Vorrang vor dem Filter). Eine Art, die nur aus dem Titel oder einem Suchwort (z. B. „Camper“) geraten
  wurde, ist **vorläufig**; widersprechen sich zwei Hinweise, ist die Art **unbekannt**. Angeschrieben werden kann in
  jedem Fall (Betreiberentscheidung 14.10.2026) – das Fahrzeug trägt aber eine gelbe Hinweiszeile, z. B. „Fahrzeugart
  nicht bestätigt (gerechnet mit der vorläufigen Art) – bitte prüfen“ oder „Fahrzeugart unbekannt (vorsichtig gerechnet
  als Wohnwagen) – bitte prüfen“ (auch in CSV-Spalte „Hinweise“, im Kopf der Anschreiben-Textdatei und in der
  Benachrichtigungs-Mail). Gerechnet wird so: **„nicht bestätigt“ mit der vorläufigen Art**; bei **„unbekannt“
  vorsichtig**: Der Scout rechnet ohne Art („Sonstige“) und mit jeder Art, die im Titel oder in der Kurzbeschreibung
  vorkommt, nimmt den **niedrigsten** Max-EK, zeigt die Spanne über alle Möglichkeiten und stuft die Sicherheit auf
  „niedrig“. Weil Wohnwagen, deren Text kein Art-Wort enthält (z. B. nur „Knaus Südwind 580“), dabei wie ein Wohnmobil
  gerechnet werden, gilt bei **unbekannter** Art: Ampel höchstens **gelb**, und der Brief nennt **keinen Betrag** (er
  fragt nach Angaben). Vor dem Anschreiben die Art prüfen. Der Brief nennt bei nicht bestätigter oder unbekannter Art keine
  Fahrzeugart. Eine später eingelesene Detailseite oder ein Art-Filter bestätigt bzw. korrigiert die Art.
  **mobile.de** nennt die Kategorie („Kastenwagen“, „Teilintegrierter“, „Alkoven“, „Integrierter“, „Wohnwagen“) bei jedem Treffer und
  auf der Anzeigenseite („Kategorie“); sie gilt als **bestätigt**. „Wohnmobil andere“ und „Andere“ sind keine Art – dann gilt
  die Regel für unbekannte bzw. vorläufige Art wie oben. Eine Art-Filter-Adresse wie bei Kleinanzeigen gibt es bei mobile.de nicht
  (die gespeicherte Suchseite enthält keine Suchadresse).
- **Datenschutz:** `import/eingelesen/` enthält die vollständigen gespeicherten Seiten, auch Verkäuferangaben
  (Name, Ort, ggf. Telefonnummer). Das Programm löscht nichts automatisch – lösche die Dateien nach der Prüfung selbst.
  Speichere Seiten möglichst nicht angemeldet, damit keine Kontodaten in der Datei landen. Das gilt ebenso für mobile.de: Der
  Quelltext einer mobile.de-Anzeige kann die Telefonnummer des Anbieters enthalten, auch wenn sie auf der Seite erst nach „Einblenden“
  erscheint. Das Programm liest sie nicht und speichert sie nicht in der Datenbank – in der Datei unter `import/eingelesen/` steht sie aber.
- Beim Einlesen einer alten gespeicherten Seite gilt die Anzeige als „zuletzt gesehen: heute“, auch wenn sie
  inzwischen gelöscht oder verkauft sein kann. Lies deshalb möglichst frisch gespeicherte Seiten ein.

**Suchagent-Mails einlesen (E-Mail-Eingang, Gerüst):** Der Eingang ist standardmäßig **aus** (`config.yaml` → `eingaenge` → `email` → `aktiv: true`).
Benachrichtigungen deines Suchagenten bei Kleinanzeigen oder mobile.de speicherst du als `.eml` – Thunderbird: Mail markieren, *Datei → Speichern unter*
(Dateityp *E-Mail-Datei (.eml)*) oder per Drag&Drop in den Ordner ziehen; im Webmail „Als .eml herunterladen“ – und legst sie in `import/email/`. Dann in der App
auf **„✉ Mails einlesen“** klicken oder `python scout.py import --mails` ausführen. Gelesen wird nur, was in der Mail steht: Links werden nie abgerufen, die
Fahrzeuge kommen mit Titel, Preis (nur aus einer eigenen Preiszeile) und Ort in die Liste; Absender, Empfänger und Betreff werden nicht gespeichert. Ob echte
Mails so aufgebaut sind, ist noch nicht belegt (Abnahme mit echten Mails steht aus, `docs/QUELLEN.md` Abschnitt 6). Eingelesene Mails liegen danach in
`import/email/eingelesen/<Datum>/`, nicht erkannte in `nicht_erkannt/`, unlesbare in `fehlerhaft/`; alles davon löscht die Datenschutz-Frist
(`datenschutz` → `inserate_anonymisieren_nach_monaten`), noch nicht eingelesene Mails nicht, die werden nach Fristablauf gemeldet.

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
- **Datenschutz**: Gespeichert werden Anzeigendaten; aus dem Verkäuferkasten werden keine Telefonnummern, Adressen oder
  Profil-IDs übernommen. (Der Freitext der Anzeige – Titel, Beschreibung – wird unverändert gespeichert und kann
  Kontaktangaben enthalten, wenn der Verkäufer sie dort selbst schreibt.) Einzige Ausnahme beim Verkäuferkasten: der öffentliche **Profilname** des Verkäufers – nur beim **Einlesen gespeicherter Anzeigenseiten**
  (nicht im Suchlauf mit Detailabruf), abgelegt in `details_json` → `verkaeufer_name`; Kürzel, „Privater Nutzer“,
  Nummern und Adressen werden verworfen. Er dient der persönlichen Anrede im Anschreiben und steht deshalb
  auch im erzeugten Brief: in `ausgabe/report.html`, in `ausgabe/anschreiben/<id>.txt` im Anhang der
  Benachrichtigungs-Mail (`report.html`, verlässt damit den Rechner), im Offline-Speicher der Handy-App (Fahrzeugansicht
  mit Brief) und – nach dem Kontakt – im gespeicherten Anschreibentext der Datenbank. **Löschen:** `python scout.py inserat anonymisieren ID --bestaetigt` (oder `--aelter-als MONATE`) entfernt den Profilnamen aus
  `details_json`, den Namen im gespeicherten Anschreiben, Verkäuferangaben im Besichtigungsprotokoll und die Anschreiben-Datei; mit
  `datenschutz → inserate_anonymisieren_nach_monaten` auch automatisch nach jedem Suchlauf (Standard 0 = aus). Gekaufte Fahrzeuge
  bleiben unverändert (Aufbewahrung). Die App selbst lauscht nur auf dem eigenen Rechner (127.0.0.1;
  Handys über `tailscale serve`); Mail-Anhang und Handy-Speicher liegen außerhalb davon.
- **Betrieb über das eigene Büro hinaus** (öffentliche Adresse, weitere Firmen): erst die Checkliste
  `docs/PILOTBETRIEB.md` abarbeiten. Was gespeichert wird und wie es sich löschen lässt: `docs/DATENRECHTE.md`
  (Widerruf einer Verkaufsanfrage: `/anfragen` → „Widerruf: personenbezogene Daten löschen“ oder `scout.py anfrage widerruf REF --bestaetigt`).
  Wer wann Verkäuferdaten gelesen oder etwas geändert hat, zeigt `scout.py audit --tage 7` (nur Metadaten, ohne Inhalte).
- **Mehrere Firmen auf einem Server** (Mandanten, je eigene Datenbank): `docs/MANDANTEN.md`.
- **Nutzung je Monat** (Anfragen, Auktionen, Gebote, Ankäufe, Zugriffe, aktive Nutzer): `scout.py nutzung --monat 2026-10`.
- **Wenn plötzlich 0 Anzeigen gefunden werden**, hat Kleinanzeigen vermutlich das Seitenlayout
  geändert. Die App meldet das als „Seitenlayout geändert“ und legt
  die Seite als `ausgabe/diagnose_suchseite.html` ab. Alle Selektoren liegen in
  `wmscout/quellen/kleinanzeigen/parser.py`.

## Aufbau (für Entwickler)

```
scout.py                      Kommandozeile (app, lauf, report, rechne, status)
config.yaml                   alle Einstellungen
app.bat / lauf.bat            Windows-Start (App / Suchlauf), beide über .venv
installieren.bat / .sh        richtet .venv mit Python 3.13 ein (läuft automatisch beim Start)
start.sh                      macOS/Linux-Start der App
pyproject.toml                Projekt, Abhängigkeiten (Bereiche), Test- und Lint-Einstellungen
requirements.txt              gesperrte Laufzeit-Abhängigkeiten (feste Versionen + Prüfsummen)
requirements-dev.txt          dazu pytest und ruff
vorlagen/                     anschreiben.txt, nachfassen.txt (Texte, frei änderbar), report.html (Oberfläche)
CLAUDE.md                     Projektregeln für Claude Code (Agenten, Branches, Definition of Done)
.claude/                      Agenten-Team, Skill scout-cycle (Entwicklungsablauf), loop.md (Wartung)
docs/ROADMAP.md               Phasen 0–6 und Backlog mit Status
docs/WORKLOG.md               Arbeitsprotokoll je Arbeitspaket
docs/ARCHITECTURE.md          Architektur, Risiken, Ziel-Datenmodell, Migrationsstrategie
docs/DECISIONS.md             Architekturentscheidungen (ADR)
docs/SOURCES.md               Datenquellen: Zulässigkeit, Bewertung, Reihenfolge
docs/TEST-REPORT.md           tatsächliche Testergebnisse und Testabdeckung
docs/QUELLEN.md               Anleitung: neue Datenquelle anbinden
docs/HANDY-APP.md             Handy-App: Einrichtung und Nutzung

wmscout/
  quellen/                    Datenquellen – einheitliche Schnittstelle (basis.py) + Adapter
    kleinanzeigen/            Adapter und HTML-Parser für Kleinanzeigen
  netz.py                     höflicher HTTP-Abruf (Pausen, Sperrerkennung)
  importer.py                 Suchlauf: Quellen → Datenbank, Detailabrufe, Layout-Diagnose
  normalisierung/             Marke/Modell/Art (fahrzeug.py), PLZ/Entfernung (geo.py, plz_de.csv)
  datenbank.py                SQLite, Status (Schema und Version: migrationen.py)
  migrationen.py              nummerierte, idempotente Schema-Migrationen mit schema_version und Sicherung vorher
  sicherung.py                Sichern/Wiederherstellen (Backup-API, integrity_check, Fotos, Aufbewahrung)
  bewertung/                  rechner.py (Marktwert, Händler-EK), anschreiben.py, auswertung.py
                              (Dubletten, Nachfassen, Bewertung aller Inserate)
  ausgabe.py                  HTML-Report, CSV, Anschreiben-Dateien
  benachrichtigung.py         E-Mail bei neuen Treffern
  app.py                      Server (nur 127.0.0.1), Suchlauf im Hintergrund, Auto-Suche
  web/api.py                  HTTP-Schnittstelle: Desktop-Liste, Handy-App, Anmeldung, Besichtigungen, Protokoll
  web/static/                 Handy-App (mobil.js, besichtigung.js = Offline-Rechnung, Service Worker, Icons)
  team.py                     Nutzer, Anmeldungen, Besichtigungen, Fotos
  bewertung/besichtigung.py   Mängelabzug (verbindliche Rechnung)
maengel.yaml                  Mängelkatalog mit Richtwerten für Reparaturkosten

tests/                        pytest, komplett ohne Internet (nachgebautes Markup, Fake-Abruf)
.github/workflows/tests.yml   CI: Tests unter Linux und Windows, Windows-Start mit installieren.bat

ausgabe/                      report.html, anzeigen_bewertet.csv, anschreiben/*.txt, scout.log
daten/anzeigen.sqlite         gesammelte Anzeigen (Grundlage für die Vergleichspreise)
daten/sicherungen/            Sicherungen der Datenbank (+ Fotos als ZIP)
```

**Tests ausführen:** einmalig `.venv\Scripts\python -m pip install -r requirements-dev.txt` (macOS/Linux:
`.venv/bin/python -m pip …`), dann `.venv\Scripts\python -m pytest` und `.venv\Scripts\python -m ruff check .`

**Abhängigkeiten ändern:** Bereich in `pyproject.toml` anpassen, dann die beiden Lock-Dateien mit den Befehlen
aus `pyproject.toml` neu erzeugen (`uv pip compile …`). `installieren.bat` installiert sie beim nächsten Start
automatisch nach.

PLZ-Koordinaten: GeoNames (www.geonames.org), Lizenz CC BY 4.0.

## Umsetzungsstand

Phasen, Backlog und offene Entscheidungen: `docs/ROADMAP.md`; Architektur und Risiken: `docs/ARCHITECTURE.md`.
Die Zeilen „Phase 1“ unten beziehen sich auf den früheren Phasenplan; die neue Zählung (Phasen 0–6) steht in der Roadmap.

| Bereich | Stand | Geprüft durch |
|---|---|---|
| Faire Bewertung, Händler-EK, Fair-Check | umgesetzt | `tests/test_bewertung.py` |
| Anschreiben (Modell, Baujahr, vorbehaltliches Angebot), Nachfassen, Verhandlungs-Assistent | umgesetzt | `test_bewertung.py`, `test_auswertung.py`; Assistent: Browsertest manuell |
| Statusverwaltung, Browser-App, CSV/HTML | umgesetzt | `test_app.py`, `test_import.py` |
| **Phase 1:** Python 3.13 + `.venv`, Start per Doppelklick | umgesetzt | CI-Job „Windows-Start“ führt `installieren.bat` aus; `installieren.sh` in CI |
| **Phase 1:** gesperrte Abhängigkeiten (Versionen + Prüfsummen) | umgesetzt | CI installiert ausschließlich aus den Lock-Dateien |
| **Phase 1:** pytest-Suite + GitHub Actions (Linux, Windows) | umgesetzt | Tests und Ruff in CI, aktuelle Zahlen in `docs/TEST-REPORT.md` |
| **Phase 1:** Komponenten (Quellen, Import, Normalisierung, Datenbank, Bewertung, Ausgabe, Benachrichtigung) | umgesetzt | alle Tests |
| **Phase 1:** einheitliche Quellen-Schnittstelle | umgesetzt | Vertragstest je Quelle, Test mit Beispielquelle |
| Spalte `quelle` je Inserat (Vorstufe zu Phase 2) | umgesetzt | `test_import.py`, `test_quellen.py` |
| Handy-App (PWA): Anmeldung, Team-Rollen, Anschreiben/Nachfassen am Handy | umgesetzt | `test_handy.py`, Klicktest im Handy-Browser |
| Besichtigungsmodus: Pflicht-Checkliste, Messwerte, Mängelkatalog, Fotos, Live-Abzug, offline | umgesetzt | `test_besichtigung.py`, Paritätstest Python↔JavaScript (600 Fälle), Klicktest inkl. Offline |
| Ankaufprotokoll mit Unterschriften, Termine/Zuständigkeit, Kalender (.ics), WhatsApp-Links | umgesetzt | `test_handy.py`, Klicktest |
| WhatsApp automatisch (Cloud API von Meta) | umgesetzt, **nicht live getestet** (braucht Meta-Konto und freigegebene Vorlagen) | `test_handy.py` mit nachgebautem Server |
| Mehrere Quellen, Datenmodell/Historie, Suchprofile, Deal-Score, Ankaufs-Dashboard | **geplant** – Phasen 2–6 in `docs/ROADMAP.md` | – |
