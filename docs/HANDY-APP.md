# Handy-App fürs Team: Anschreiben, Besichtigung, Ankaufprotokoll

Die Handy-App ist eine **Web-App (PWA)**: Sie läuft auf dem Büro-PC und wird auf iPhone und Android über den Browser
auf den Startbildschirm gelegt. Sie sieht aus und funktioniert wie eine App, braucht keinen App-Store, und jedes
Update ist sofort bei allen. Unterwegs verbinden sich die Handys über **Tailscale** (ein sicheres privates Netz) mit
dem Büro-PC.

## Was die App kann

| Bereich | Funktion |
|---|---|
| **Heute** | Zähler „Anschreiben bereit“, „Nachfassen“, „In Arbeit“; Besichtigungen des Tages; Suchlauf starten |
| **Inserat einlesen** | Auf „Heute“ **„＋ Inserat einlesen (Link + Text)“**: Adresse der Anzeige und den kopierten Anzeigentext einfügen, optional den **Preis laut Anzeige** (und „VB“) eintragen – ein Preis aus dem Fließtext wird nie übernommen –, Anbieter wählen (unbekannt/privat/gewerblich), „Einlesen“. Bei unsicherem Preis bleiben die Eingaben stehen, nur der Preis muss ergänzt werden. Ergebnis: neu / Preis gesenkt / bereits bekannt, erkannte Felder, alle Hinweise (z. B. „unvollständig: …“) und Link zum Fahrzeug. Nur Inhaber und Mitarbeiter (nicht Standort-Zugänge). **Braucht Netz**: ohne Verbindung steht eine Meldung da, die Eingaben bleiben im Formular, nichts wird vorgemerkt oder gespeichert. Keine Namen, Telefonnummern oder Adressen des Verkäufers einfügen – Kontaktdaten werden entfernt, Namen im Fließtext nicht immer |
| **Anschreiben** | Liste mit Bewertung; Fahrzeug antippen → Text prüfen → „✉ Kopieren & Anzeige öffnen“ (Status „Text kopiert“); nach dem Absenden **„gesendet ✓“** tippen – erst dann gilt der Verkäufer als kontaktiert. Nachfassen genauso |
| **Wer bearbeitet was** | Abzeichen mit Kürzel an jedem Fahrzeug (◔ reserviert, ✉ kontaktiert, ⧉ Dublette); Filter „Alle / Meine / Frei“; „Ich übernehme“ / „Abgeben“ (Inhaber: „Übernahme erzwingen“); hält ein Kollege das Fahrzeug, ist „Anschreiben“ gesperrt und der Grund steht daneben |
| **Gleiches Fahrzeug** | Im Fahrzeugdetail (Inhaber, Mitarbeiter) steht „Gleiches Fahrzeug wie …“ mit Links zu den anderen Inseraten und dem Fahrzeugstatus – **nur Anzeige**; entschieden und aufgehoben wird am Büro-PC. Die Daten werden nie im Gerätespeicher abgelegt |
| **Besichtigung planen** | Termin, Adresse, zuständiger Mitarbeiter; WhatsApp an den Mitarbeiter öffnet sich mit fertigem Text; Termin als Kalenderdatei (.ics); Navigation |
| **Besichtigung durchführen** | Fahrzeugdaten (FIN, km, HU, Gas, Schlüssel), Pflicht-Checkliste, Feuchtigkeitsmessung, Reifen-DOT, Mängelkatalog mit Schweregrad, Fotos je Mangel, Anpassung mit Begründung – **Abzug und Endpreis-Vorschlag rechnen live mit** |
| **Ohne Netz** | Alle Eingaben und Fotos werden auf dem Handy gesichert und automatisch übertragen, sobald wieder Netz da ist („1 wartet“ oben rechts) |
| **Abschluss** | Ergebnis (gekauft / offen / kein Kauf / abgebrochen), Kaufpreis, Verkäuferdaten und -erklärungen, Unterschriften auf dem Display → **Ankaufprotokoll** mit Mängeln und Fotos, druckbar bzw. als PDF speicherbar |
| **Team** | Anmeldung je Mitarbeiter; Inhaber sieht alle Besichtigungen, Mitarbeiter ihre eigenen; nur Zuständige und Inhaber dürfen eine Besichtigung bearbeiten |

### Besichtigung einer Verkaufsanfrage (Phase F)

Auch Fahrzeuge, die Verkäufer selbst anbieten, werden mit der Handy-App besichtigt. Geplant wird in `/anfragen` (Karte
„Besichtigung und Ankauf“) durch den Inhaber oder den Bearbeiter der Anfrage; danach steht der Termin unter „Heute“. Statt des
Inserat-Links zeigt die Besichtigung „Verkaufsanfrage VA-…“, Name und Telefon des Verkäufers sind im Abschluss vorbelegt, das
Angebot ist ein bestätigter Demo-Zuschlag oder das Erstangebot. Abschluss mit „gekauft“ legt automatisch einen Ankaufsvorgang
an (`/ankaeufe`) – bei Inseraten genauso.

## So rechnet der Mängelabzug

Die Rechnung ist regelbasiert und im Protokoll nachvollziehbar. Die Richtwerte stehen in **`maengel.yaml`** und
sollten einmal mit euren echten Werkstattkosten abgeglichen werden.

```
Summe Mängel   = Feuchtigkeit: je Bereich der höchste Messwert → Stufe (≤15 % ok, ≤20 leicht, ≤30 mittel, darüber schwer)
               + Reifen älter als 6 Jahre (je Reifen)
               + Mehr-km gegenüber der Anzeige (1,5 % vom Marktwert je 10.000 km, 3.000 km Toleranz)
               + erfasste Mängel (Schweregrad leicht/mittel/schwer, fester Betrag, % vom Marktwert oder frei)
− Gutschrift   = 50 % der Reparaturrisiko-Pauschale, die schon in der Kalkulation steckt (keine Doppelzählung)
± Anpassung    = z. B. neue Batterie vorhanden (mit Begründung)
= Netto-Abzug
× 1,19         bei Differenzbesteuerung (§25a), damit eure Marge gleich bleibt
= Abzug vom EK
Vorschlag      = vorbehaltliches Angebot − Abzug vom EK, höchstens neuer Max-EK, auf 50 € abgerundet
```

* **Bewertungsgrundlage einfrieren:** Angebot, Max-EK, Marktwert und Reparaturrisiko werden beim Planen der
  Besichtigung festgehalten. Ein späterer Suchlauf verändert die Rechnung nicht mehr.
* **Pflichtpunkte:** FIN-Abgleich, Papiere, Probefahrt, Heizung, mind. 8 Feuchte-Messpunkte, 4 Reifen-DOT.
  Ohne sie lässt sich „gekauft“ nur mit schriftlicher Begründung abschließen.
* **K.-o.-Mängel** (z. B. Fäulnis, schwere Delamination, durchgerosteter Rahmen) zeigen „Ankauf nicht empfohlen“.
* **Zuverlässig:** Die App rechnet offline mit derselben Logik wie der Server; verbindlich ist immer die Rechnung des
  Servers beim Speichern. Ein automatischer Test vergleicht beide Rechnungen über 600 Zufallsfälle.

## Einrichtung (einmalig)

### 1. Zugänge anlegen

Im Projektordner die Eingabeaufforderung öffnen (Adressleiste → `cmd`) und je Person:

```
.venv\Scripts\python scout.py nutzer anlegen Anna --rolle inhaber --telefon "+49 170 1234567"
.venv\Scripts\python scout.py nutzer anlegen Ben --telefon "+49 171 7654321"
```

Das Passwort wird abgefragt (mind. 8 Zeichen). Weitere Befehle: `nutzer liste`, `nutzer passwort Ben`,
`nutzer sperren Ben`, `nutzer entsperren Ben`.
**Ab dem ersten Nutzer ist überall eine Anmeldung nötig**, auch am Büro-PC.

### 2. Büro-PC über Tailscale erreichbar machen

1. Tailscale auf dem Büro-PC installieren (tailscale.com/download) und anmelden. Konditionen für kleine Teams auf
   der Tailscale-Seite prüfen.
2. In der Tailscale-Verwaltung (login.tailscale.com → DNS) **MagicDNS** und **HTTPS Certificates** einschalten.
3. Auf dem Büro-PC in der Eingabeaufforderung:
   ```
   tailscale serve --bg 8765
   ```
   Tailscale zeigt danach eine Adresse wie `https://buero-pc.tail1234.ts.net`. Kontrolle mit `tailscale serve status`.
4. Diese Adresse in `config.yaml` eintragen:
   ```yaml
   app:
     oeffentliche_url: "https://buero-pc.tail1234.ts.net"
   ```
5. `app.bat` neu starten. Der Büro-PC muss laufen und `app.bat` geöffnet sein. Tipp: Verknüpfung zu `app.bat` in
   den Autostart-Ordner (Windows-Taste + R → `shell:startup`) und in den Energieoptionen den Ruhezustand abschalten.

Die App selbst lauscht nur auf dem PC (127.0.0.1). Erreichbar ist sie ausschließlich über Tailscale, mit
verschlüsselter Verbindung und Anmeldung, nicht aus dem offenen Internet.

### 3. Handys einrichten

1. Tailscale-App installieren und mit demselben Tailscale-Konto bzw. Team anmelden.
2. Im Browser `https://buero-pc.tail1234.ts.net/m` öffnen und anmelden.
3. Auf den Startbildschirm legen: **iPhone** (Safari) → Teilen → „Zum Home-Bildschirm“; **Android** (Chrome) → ⋮ →
   „App installieren“.

## WhatsApp

**Sofort nutzbar, ohne Einrichtung:** Beim Planen einer Besichtigung für einen Kollegen öffnet sich WhatsApp mit
fertigem Text (Fahrzeug, Termin, Adresse, Link zum Inserat und zur App). Voraussetzung: Telefonnummer beim Nutzer
hinterlegt (`--telefon`). In „Termine“ gibt es den WhatsApp-Knopf zusätzlich.

**Automatische Nachrichten (optional):** Für Nachrichten ohne Antippen, z. B. „3 neue Treffer“ nach jedem
Suchlauf oder „Besichtigung zugewiesen“, braucht es die offizielle **WhatsApp Business Platform (Cloud API)** von
Meta. WhatsApp erlaubt automatische Nachrichten nur darüber.

1. Im Meta-Business-Konto eine WhatsApp-Business-App anlegen und eine Telefonnummer verbinden (Meta-Entwicklerportal).
2. Zwei Nachrichtenvorlagen (Sprache Deutsch) zur Prüfung einreichen, Beispiele:
   * `neue_treffer`: „Wohnmobil-Scout: {{1}} neue Fahrzeuge mit fertigem Anschreiben. Bestes: {{2}}“
   * `besichtigung_zugewiesen`: „Neue Besichtigung für dich: {{1}} am {{2}}, {{3}}. Details in der App.“
3. In `config.yaml` unter `whatsapp` `aktiv: true`, die `phone_number_id` und `empfaenger_treffer` eintragen.
4. Das Zugriffstoken als Umgebungsvariable `SCOUT_WHATSAPP_TOKEN` setzen, nie in die Datei schreiben.

Meta berechnet die Nachrichten je nach Art und Land. Aktuelle Preise und Regeln bitte im Meta-Portal prüfen.
Fehler beim Versand werden nur protokolliert und halten nichts auf.

## Datenschutz und Sicherheit

* **Datenablage:** Fotos liegen unter `daten/fotos/`, Besichtigungen und Verkäuferdaten in `daten/anzeigen.sqlite`,
  beides nur auf dem Büro-PC. Den Ordner `daten/` regelmäßig sichern.
* **Verkäuferdaten:** Gespeichert wird nur, was für das Protokoll nötig ist (Name, Anschrift, Telefon). Löschfristen
  bitte mit eurer Datenschutzregelung abstimmen.
* **Passwörter und Anmeldungen:** Passwörter werden mit scrypt gespeichert, Anmeldungen laufen nach 30 Tagen ab, ein
  Passwortwechsel meldet überall ab. Abmelden in der App löscht die zwischengespeicherten Daten auf dem Handy.

* **Team-Übersicht (ADR-023):** Gespeichert wird, wer ein Fahrzeug übernommen bzw. angeschrieben hat und wann.
  Mitarbeiter sehen nur ihre eigenen Zähler, der Inhaber alle; Kürzel am Fahrzeug sehen alle. Das sind
  Leistungsdaten – Zweck (Doppelkontakt vermeiden, Arbeit verteilen) und Speicherdauer festlegen; bei Betriebsrat
  Mitbestimmung beachten.

## Grenzen

* Das Ankaufprotokoll ist ein **Muster** und ersetzt keinen Kaufvertrag. Vor dem ersten Einsatz rechtlich prüfen lassen.
* Die Kalendereinträge kommen als `.ics`-Datei zum Antippen und werden nicht automatisch synchronisiert.
* Push-Mitteilungen der App selbst gibt es noch nicht. Automatische Hinweise laufen über WhatsApp (Cloud API).
* Ist der Büro-PC aus, ist die App nicht erreichbar. Bereits geöffnete Besichtigungen lassen sich offline weiter
  bearbeiten.
