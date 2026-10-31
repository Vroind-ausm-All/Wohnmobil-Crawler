# Testbericht

Nur tatsächlich ausgeführte Prüfungen. Nicht Ausgeführtes steht unter „nicht geprüft“. Neueste Einträge oben.

---

## P6-01 – Kombinierte Ankaufsliste: alle Quellen, Deal-Score-Sortierung, Risikofaktoren (31.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2579 bestanden (vorher 2548), neu `test_liste.py` (31); keine bestehenden Tests angepasst |
| `ruff check .` | grün |
| Risikofaktoren je Fall (Bewertung fehlt/unsicher, schwerer/leichter Mangel, vermutlich offline, reserviert, Widerspruch, lückenhafte Daten, Ausland, Abholkosten > 500 €, Entfernung > 400 km ohne Kosten, Anbieter unbekannt, > 60 Tage online) – jeweils genau ein Faktor; Grenzen (500 €, 400 km, 60 Tage), Reihenfolge hohe zuerst, Rundung auf 10 € bzw. ganze km | bestanden |
| Korrekturrunde: unvollständige Strukturen (unbekannte Abholvariante, Betrag fehlt, leere Varianten, Mangel ohne Wert, Markierung ohne Text, `b` = None, Zahlen als Text) ohne Ausnahme; `karte` = False für Mängel, Verfügbarkeit, Ausland, Anbieter; verkauft und gewerblich als Faktor | bestanden |
| API: Sortierung nach Deal-Score (ohne Score am Ende) für „alle“ und „bereit“, `filter=top` = genau die priorisierten, `quelle` filtert (Kleinanzeigen/mobile.de/AutoScout24), unbekannte Quelle → 400, Felder `risiken` und `quelle_text` | bestanden |
| Desktop-HTML: Quellen-Auswahl nur mit vorhandenen Quellen, Quellen-Abzeichen, Risiko-Chips (höchstens 3 + „+n“, ohne Mängel), Risikoliste im Detail, Risikotexte in Chip, `title` und Liste escaped | bestanden |
| Handy-App (statisch): Liste „Top-Deals“, Parameter `quelle`, Risikozeile Karte/Detail, Deal-Abzeichen, Texte über `esc()`, Quellenliste gleich `domaene.PLATTFORM_TEXT`, CSS, Service-Worker-Version ≥ 19 | bestanden |
| Klicktest Chromium (Playwright), Desktop 1280 px und 390 px, angemeldet: Reihenfolge nach Score (66, 50 …, ohne Score am Ende), Abzeichen „Kleinanzeigen“/„mobile.de“, Quelle „mobile.de“ zeigt genau die 2 umgestellten Inserate, Risikoliste im Detail („reserviert“), kein Querscrollen | bestanden (nach der Korrekturrunde wiederholt) |
| Klicktest Handy-App `/m` (390 px): Knopf „Top-Deals“, Deal-Abzeichen und Quelle auf den Karten, Quellenfilter (2 Fahrzeuge), Liste „Top-Deals (0)“, Detail mit Deal-Abzeichen und Risikoliste, kein Querscrollen, keine JS-Fehler | bestanden im zweiten Lauf; im ersten Lauf einmal JS-Fehler „reading 'team'“ beim Listenwechsel direkt nach dem Login (bestehender Code, ROADMAP P6-01b) |
| QA-Review (`qa-security-reviewer`, eine Runde, gezielte Tests 52 + 273 bestanden, XSS-Aufrufe der mobil.js-Funktionen in Node) | Freigabe mit Auflagen; B1–B5 behoben, B6 per Test abgesichert, B7/B8 erledigt |

**Nicht geprüft:** CI (läuft nach dem Push), Windows, echtes Handy und Service-Worker-Wechsel auf Version 19, echte Inserate von mobile.de/AutoScout24 in der Liste (nur umgestellte Testdaten), Häufigkeit roter Risiko-Chips auf echten Daten; Korrekturen nicht erneut von der QA geprüft.

## P5-07 – Deal-Score 0–100 und Bewertungsverlauf (30.10.2026) · DONE (PR #50 gemergt)

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2548 bestanden (vorher 2519), neu `test_deal_score.py` (29). Angepasst: `test_neuigkeiten.py` (CSV: „Deal-Score“, „Top-Deal“ nach „Neuigkeit“), `test_zugaenge.py` (Migration bis zur aktuellen Version). Erster Lauf vor der Korrekturrunde: 2542 bestanden, 1 fehlgeschlagen (`test_zugaenge.py`, erwartete Migration nur bis v21) |
| `ruff check .` | grün |
| Einstellungen: Werte aus config.yaml, Standardwerte, Fehleingaben (Tippfehler, negative/unendliche Gewichte, alle 0, Preisgrenzen vertauscht, Schwelle > 100, Text) | bestanden |
| Formel: guter Deal hoch, teurer niedrig, Summe der Teilpunkte = Score, Gewichte relativ, Preisvorteil linear (0,85 voll, 1,0 halb, 1,15 null), Zustand, Abholung (Kosten, Entfernung, unbekannt, Ausland), Frische, Verkäufer (vermutlich offline/reserviert halbieren) | bestanden |
| Kein Score bei Sperre vom Markt her oder ohne belastbare Bewertung; eigener Ankaufsstatus behält den Score; Top-Deal nur offen, privat, sicher verfügbar, Inland, Ampel grün, Bewertung mindestens „mittel“ (Ausland, unsichere Bewertung, vermutlich offline, reserviert, Status vorbereitet → kein Top-Deal); Preisvorteil aus unsicherer Bewertung zählt weniger | bestanden |
| Schema v22: additiv, Sicherung „vor-v22“, nur anfügbar (UPDATE/DELETE abgewiesen), Score 0–100 geprüft, idempotent | bestanden |
| Verlauf: erste Bewertung alle, unverändert nichts, Preisänderung neue Zeile, Score-Bewegung unter 3 Punkten keine Zeile, Datenbankfehler blockiert nichts, ältere Datenbank ohne Tabelle | bestanden |
| Desktop/API/CSV/Kommandozeile: Sortierung „Deal-Score“, Filter „Top-Deals“, Badge, Aufschlüsselung im Detail, `deal_score`/`priorisiert` in der Liste, `deal`/`deal_verlauf` im Detail; CSV-Spalten; `report` schreibt Verlauf, zweiter Report ohne Änderung nichts; ungültiges `deal_score` bricht den Start verständlich ab | bestanden |
| Browser (Orchestrator, Chromium über Playwright, Desktop 1280 und Breite 390): Standardsortierung „Deal-Score“, Badge „Deal 66“, Detail mit sechs Bestandteilen, Punkten und Begründung, Top-Deals-Filter (0 Treffer bei diesen Daten), kein Querscrollen, 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 137 gezielte Tests bestanden, Probeskripte zu Grenzfällen, Verfügbarkeit, Status und Wachstum) | **Ablehnung** (keine kritischen Befunde) wegen B1–B4 (hoch) – behoben; B5–B11 behoben, B12 beim Commit beachtet, B13 begründet; Korrekturen **nicht** erneut von der QA geprüft |
| Fachliche Eichung der Gewichte gegen echte Abschlüsse, Handy-App-Anzeige, Mandantenbetrieb im Detail, Leistung von `merken` über 50.000 Inserate, Windows-CI | nicht geprüft (CI folgt im PR) |

## F10 / P1-14c – Aufbewahrungsfristen, vorbereitet für den Server (27.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2451 bestanden (vorher 2424), neu `test_aufbewahrung.py` (27). Angepasst: `test_email_betrieb.py` (ohne Eintrag keine Frist – config.yaml trägt jetzt 6 Monate ein), `conftest.py` (Import- und Sicherungsordner der Tests im Temp-Ordner). Lauf vor der Korrekturrunde: 2443 bestanden |
| `ruff check .` | grün |
| Einstellungen: Werte aus config.yaml, fehlende Einträge = aus, Fehleingaben (negativ, Text, bool, Tippfehler-Schlüssel, ungültiger Modus) verständlich, Wartung bricht nie ab | bestanden |
| Verkaufsanfragen: nach 12 Monaten anonymisiert (Status bleibt, Verlauf „frist“), frische bleiben, idempotent; nie mit Ankauf (auch storniert), offener Besichtigung oder laufender/unentschiedener Auktion; nach neuen Angaben wieder fällig | bestanden |
| Audit: alte Einträge gelöscht, Trigger danach wieder da, Nachweis ohne Inhalte (auch im Automatikbetrieb); Fehler beim Löschen → Rollback, andere Kategorien laufen weiter | bestanden |
| Sitzungen gelöscht; Kaufunterlagen nur gemeldet (Frist ab Jahresende des letzten Vorgangs inkl. Storno/Verlauf), gesperrte Zugänge gemeldet | bestanden |
| Abgelegte Seiten samt Begleitordner gelöscht, unverarbeitete, neue und Verknüpfungen nicht; Frist zählt ab dem Ablegen | bestanden |
| Sicherung vor dem Löschen: nur wenn etwas fällig ist, höchstens eine je Tag, die letzten drei; manuelle Sicherungen mit Fotos und Migrationssicherungen bleiben | bestanden |
| Inserat mit Ankaufsvorgang ohne Status „gekauft“: nie fällig, keine Sicherung | bestanden |
| Automatik: `nur_bericht` meldet nur (Warnung mit Befehl), `ja` führt aus | bestanden |
| Kommandozeile: Bericht, `--ausfuehren` nur mit `--bestaetigt`, `--json` (Protokoll auf stderr), `--alle-mandanten` (je Mandant getrennt, ein kaputter Mandant hält die anderen nicht auf, Exit-Code 1) | bestanden |
| API: nur Inhaber (Mitarbeiter/Händler 403), Bestätigung nötig, im Audit protokolliert; Statusseite zeigt die Fristen, den Befehl nur dem Inhaber | bestanden |
| Tests schreiben nicht in den Projektordner (keine Datei unter `daten/` nach der Suite) | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 102 gezielte Tests bestanden, fünf Nachstellskripte) | **Ablehnung** wegen B1/B2 (kritisch) – B1–B10 behoben, B11 beim Commit beachtet; Korrekturen **nicht** erneut von der QA geprüft |
| Rechtliche Richtigkeit der Fristen, Windows (Junctions, gesperrte Dateien), echter Datenbestand, Windows-CI | nicht geprüft (CI folgt im PR) |
## F4 / P2-08a – Kunden-Zugänge: Einladungslink und Händlerzugänge (27.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2443 bestanden (vorher 2424), neu `test_zugaenge.py` (19). Lauf vor der Korrekturrunde: 2437 bestanden |
| `ruff check .` | grün |
| Schema v21: additiv, Sicherung „vor-v21“, Altbestand (Nutzer aus v20) bleibt, idempotent | bestanden |
| Einladung: nur Hash gespeichert, einmal gültig, abgelaufen/gesperrt ungültig, neue macht alte ungültig, bis zum Einlösen keine Anmeldung, vorhandene Zugänge nur ausdrücklich und mit ihrer Rolle, alte Einladungen aufgeräumt | bestanden |
| App: Einladen nur Inhaber (Mitarbeiter 403, Händler-Rolle 400), Seite `/einladung` offen, Prüfen und Einlösen gebremst (429), Passwort ≥ 8, nach dem Einlösen angemeldet, zweites Einlösen 410, Audit „einladung“ mit Namen, Prüfen nicht protokolliert; Einzelplatz: erste Einladung mit Hinweis „Anmeldung nötig“ und ohne Neuladen der Seite | bestanden |
| Kommandozeile `nutzer einladen` (Link mit öffentlicher Adresse; vorhandener Name nur mit `--erneut`) | bestanden |
| Händlerzugänge: kein Geheimnis in DB/Antwort, Variable nur `WMSCOUT_…` bzw. im Mandantenbetrieb `WMSCOUT_<KENNUNG>_…`, AutoScout24 ohne Lesefelder, Fehleingaben verständlich | bestanden |
| Verbindungstest (Attrappe statt Netz): genau eine Anfrage auch bei 5xx, Basic-Anmeldung, nur Aufbau gemerkt (keine Inseratsinhalte), 401 ohne Passwort im Text; über die App nur Inhaber, ohne Passwort auf dem Server 400 | bestanden |
| Browser (Orchestrator, Chromium über Playwright, Desktop 1280): Anna meldet sich an, „Zugänge“ zeigt mobile.de/AutoScout24 mit Variablenhinweis, Einladung „Kunde &lt;b&gt;“ als Inhaber → Link mit Hinweis zur fehlenden öffentlichen Adresse; Link im neuen Browser: Code aus der Adresszeile entfernt, Name als Text (escaped), Passwort gesetzt → angemeldet auf „/“; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 118 gezielte Tests bestanden, 9 eigene Proben inkl. Wettlauf beim Einlösen und fremder Herkunft) | Freigabe mit Auflagen – B1–B3 (hoch), B4–B6, B8, B10 behoben, B7 dokumentiert, B9 beim Commit beachtet; Korrekturen **nicht** erneut von der QA geprüft |
| Echter Aufruf der mobile.de Search-API (Pfad, Accept-Kopf, Antwortformat), Betrieb hinter einem Reverse-Proxy, Windows-CI | nicht geprüft (Test mit echtem API-Account durch den Betreiber; CI folgt im PR) |
## P5-06 – Abholung: Auto ab Besigheim oder Bahn ab Stuttgart Hbf (27.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2473 bestanden (vorher 2424), neu `test_abholung.py` (49). Erster Lauf vor der Korrekturrunde: 3 fehlgeschlagen in `test_anschreiben.py`, `test_ausland.py`, `test_suchgebiete.py` – sie erwarteten den bisherigen Firmensitz Stuttgart (Ort im Anschreiben, Entfernung 0 km, Standort-PLZ); jetzt Besigheim 74354. Ebenso angepasst: `test_bewertung.py` (alte Formel ohne Abschnitt `abholung`), `test_risiko.py` (Rechenstand numerisch) |
| `ruff check .` | grün |
| Rechnung nachgerechnet (Auto 200 km, Bahn 220 km), günstigerer Weg (Nahbereich Auto, ab ~30 km Bahn), Ticket 12–160 €, Übernachtung ab 10 Std. je Person, Kosten steigen mit der Entfernung, ohne Entfernung Pauschale, Händlerstandort und `bahn: false` nur Auto | bestanden |
| Konfiguration: ohne/leer/`false` alte Formel, `true` Standardwerte; Fehleingaben (negativ, Text, 0 km/h, NaN, ∞, Tippfehler-Schlüssel, unbekannte Bahnhofs-PLZ, `auto: false`, ticket_min > ticket_max) verständlich gemeldet | bestanden |
| Kalkulation E6: Standardwerte und Abstand Firmensitz → Bahnhof eingefroren (auch gegen geänderte Code-Standards), Konfiguration nicht verändert, JSON-Rundlauf, Strecken auf 10 km gerundet, keine Verkäufer-PLZ; E5-Eingabe (ohne Abholung und Bahnstrecke) rechnet mit der alten Formel unverändert | bestanden |
| Firmensitz weit vom Bahnhof (Mandant Hamburg): Bahn entfällt mit Hinweis (Rechner und Kalkulation) | bestanden |
| Oberfläche: Detail mit beiden Wegen, „✓ gerechnet“, Kostenposten „Abholung (Bahn ab Stuttgart Hbf, … km zurück)“, API `bewertung.abholung`, Nahverkehrsticket unter 50 km, km mit Tausenderpunkt, „60 Min.“ ausgeschlossen | bestanden |
| Browser (Orchestrator, Chromium über Playwright, Desktop 1280 und Breite 390): Verkäufer in München – „Auto ab Firmensitz (2 Personen): ca. 560 € – 253 km, zusammen ca. 14 Std.“, „Bahn ab Stuttgart Hbf: ca. 330 € – ICE-Ticket ca. 75 €, Anreise mit öffentlichen Verkehrsmitteln ca. 3 Std. 30 Min., Rückfahrt im Wohnmobil ca. 3 Std. 15 Min. ✓ gerechnet“; kein Querscrollen; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 291 gezielte Tests bestanden, echte E5-Eingabe aus dem alten Code nachgerechnet, PLZ-Rückrechnung über alle 10.814 PLZ) | Freigabe mit Auflagen – B1 (hoch), B2–B6 behoben, B7/B8 beim Commit/PR beachtet, B9 ins Backlog (P5-06b); Korrekturen **nicht** erneut von der QA geprüft |
| Echte ICE-Preise und Fahrzeiten (kein Netzabruf), Handy-App-Anzeige (P5-06b), Windows-CI | nicht geprüft (CI folgt im PR) |

## P5-05 – Ausstattung, Mängel und Kostenrisiken; Spannen auf 100 € (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2424 bestanden (vorher 2380), neu `test_risiko.py` (44). Angepasst: `test_spannen.py` (Rundung 100 €, Mängel nach Namen, Rechenstand numerisch), `test_preisarten.py`, `test_vergleichsauswahl.py` (Rechenstand numerisch), `test_kalibrierung.py` (Plan-Standzeit im Oktober (3 + 2) × 30 Tage) |
| `ruff check .` | grün |
| Spannen und Händlerniveau auf 100 € nach außen gerundet, Spanne nie 0 € breit | bestanden |
| Standzeit nach Kaufmonat (Saisonzuschlag je Monat, Tippfehler in der Konfiguration → verständliche Meldung), Gewährleistungsrücklage nach Altersstaffel (ohne Staffel pauschal), Kapitalbindung als eigener Posten; Ankauf im Herbst senkt den Max-EK | bestanden |
| Neue Wertfaktoren: Motor-, Getriebe-, Unfallschaden; Anhängerkupplung, Dieselheizung; Gegenproben ohne Treffer („Zylinderkopfdichtung neu“, Webasto-Dachluke) | bestanden |
| Mängelrisiko: nach vollem Wert vor der Deckelung, höchstens 15 %, weitet nur die untere Spanne; ein schwerer Mangel → Sicherheit höchstens mittel, zwei → niedrig; Hinweis „Schwerer Mangel laut Inserat …“ | bestanden |
| Kalkulation E5 (Standardwerte eingefroren, Konfiguration nicht verändert, JSON-Rundlauf); Plan-Standzeit und Kapitalbindung im Ankauf gespeichert, Kalibrierung rechnet die Kapitalbindung heraus | bestanden |
| Browser (Orchestrator, Chromium über Playwright, Desktop 1280, Kaufmonat Oktober): Karte „Max-EK (Spanne) 16.500–25.800 €“ mit Hinweis auf Motorschaden und Feuchtigkeit; Detail „Geplante Standzeit 5 Monate“, Kosten mit Standkosten 600 €, Gewährleistungsrücklage 840 €, „Kapitalbindung (5 Mon.)“ 560 €, Mängelliste mit „Ausmaß unklar: untere Spanne um 15 % weiter“, Sicherheit niedrig; HTML im Titel escaped; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde) | Freigabe mit Auflagen – B1 (hoch) und B2–B8 behoben bzw. dokumentiert, Regressionstests ergänzt; Korrekturen **nicht** erneut von der QA geprüft |
| Handy-Ansicht (keine Änderung an `mobil.js`), echter Datenbestand, Windows-CI | nicht geprüft (CI folgt im PR) |

## P5-04 – Angebots- gegen Abschlusspreise, Händler- gegen Privatpreise (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2380 bestanden (vorher 2364), neu `test_preisarten.py` (16). Angepasst: `test_anbieter.py` (Auszug der Kalkulation enthält jetzt Händlerangebote), `test_spannen.py` (Rechenstand ≥ E3) |
| `ruff check .` | grün |
| Händlerangebote getrennt (unbekannte Anbieter nie), Privatmarkt unverändert durch Händler, Vorfilter liefert dasselbe (privat und Händler) | bestanden |
| Händlermarkt: erst ab 3 Angeboten; Obergrenze bei Händlern knapp über dem Privatmarkt (VK sinkt, Max-EK höchstens moderat, nie unter Marktwert privat, Spanne ≥ 500 €, Sicherheit höchstens mittel); teure Händler ohne Wirkung; **Miet-/Raten-/Lockangebote (1.500 € bzw. 25.000 €) und billigere Händler (Datenkonflikt) drücken den Max-EK nicht** (QA B1); Schalter streng (false, 0, „nein“, „aus“) | bestanden |
| Kalkulation E4: Standardwerte eingefroren, Händler im Auszug, Ergebnis = Bewertung aus der Datenbank, Annahmen nennen die Begrenzung, Szenarien vorsichtig < erwartet < günstig | bestanden |
| Marktbeobachtung: rein (Mindestzahl, Median, Hinweis nur über dem Abschlag, Erhöhung = 0) und aus der Datenbank (Händler und aktive Inserate zählen nicht, vermutlich offline nach 400 Tagen, **je Fahrzeug**: wieder eingestelltes Fahrzeug nicht, zwei Inserate einmal); API, Seite, CLI | bestanden |
| Oberfläche: Händlermarkt im Desktop-Detail (begrenzt, Datenkonflikt) und im Handy-Skript, Service-Worker wm-scout-18 | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – Karte mit Spanne, Detail „Händlermarkt: 5 vergleichbare Händlerangebote, Angebotsniveau 41.000 €“ mit Datenkonflikt in der Vergleichsbasis; `/kalibrierung` – Marktbeobachtung (6 verschwundene Inserate, Senkung 8 %) mit Hinweis; Handy 390 – Händlermarkt im Detail, ohne Querscrollen; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 119 bestanden, Probe mit Lockangeboten) | **Ablehnung** wegen B1 (kritisch) – B1–B5 behoben, B6 beachtet, Regressionstests ergänzt; Korrekturen **nicht** erneut von der QA geprüft |
| Echter Datenbestand (Anteil Händlerangebote, Häufigkeit der Begrenzung), Windows-CI | nicht geprüft (CI folgt im PR) |

## P5-03 – Spannen statt Punktwerte, Abschlag bei unbekannter Marke, Mängelliste (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2364 bestanden (vorher 2335), neu `test_spannen.py` (29). Vorheriger Lauf nach der Korrekturrunde: 2358 bestanden, 6 fehlgeschlagen in `test_seitenimport.py`, `test_kleinanzeigen_echt.py`, `test_mobilede.py` – sie prüften die Hinweisliste exakt mit Testfahrzeugen ohne Marke; jetzt prüfen sie die Art-Hinweise ohne den neuen Markenhinweis. Ebenso vorher angepasst: `test_anschreiben.py` (Hinweislisten), `test_vergleichsauswahl.py` (Rechenstand ≥ E2), `test_statusseite.py` (Service-Worker ≥ 16) |
| `ruff check .` | grün |
| Marke unbekannt (keine Marke, nur Basismarke; Werks-Camper California/Marco Polo/Nugget haben eine Marke), Abschlag nur auf den Händler-VK, abschaltbar, Standard 5 % ohne Eintrag, Hinweis nur bei Abschlag | bestanden |
| Spannen: umschließen den Punktwert (0, 2, 9 Vergleiche und dichte Daten mit 40–150 Vergleichen), auf 500 € nach außen, nie 0 € breit, mehr Daten → engere Spanne; keine Spanne ohne Marktwert oder bei manuellem Wert; unbekannte Art → weiteste Spanne; Max-EK 0 ohne Spanne (Desktop und Handy) | bestanden |
| Mängelliste (schwerste zuerst, verneinte Nennungen nicht, auch ohne Erstzulassung) | bestanden |
| Kalkulation E3 (Abschlag eingefroren, in den Annahmen genannt, im Plan gespeichert); Kalibrierung trennt Fälle mit Abschlag und schlägt dafür den Abschlag vor, nicht den Händleraufschlag | bestanden |
| API (`/api/fahrzeuge`, `/api/fahrzeug/<id>`: Spannen, Mängel, `null` ohne Marktwert), Desktop-Seite (Spanne auf der Karte, Mängelzeile, Detail mit Spannen und Mängelliste, HTML im Titel escaped), Handy-Skript, Verkaufsanfrage-Ansicht, Service-Worker wm-scout-17 | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – Karte „Max-EK (Spanne) 23.500–32.500 € · Mitte 28.100 €“, „Mängel laut Inserat: Wasserschaden, Rost“, Hinweis „Marke unbekannt“, Detail mit Spannen, Mängelliste und VK „darin −5 %“; Handy 390 – Liste und Detail mit Spanne, Mängeln und Hinweis, ohne Querscrollen; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 115 bestanden, Proben mit 1.248 bzw. 300 Fällen) | Freigabe mit Auflagen – B1 (hoch) und B2–B5 behoben, B6 dokumentiert, Regressionstests ergänzt; Korrekturen **nicht** erneut von der QA geprüft |
| Echter Datenbestand, Service-Worker-Update auf dem Gerät, Windows-CI | nicht geprüft (CI folgt im PR) |

## P5-02 – Vergleichsauswahl nach Marke, Modellreihe und Fahrzeugklasse (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2335 bestanden (vorher 2283), neu `test_vergleichsauswahl.py` (52). `test_deal.py`: zwei Prüfungen hingen fest an „E1“ → gegen `kalk.VERSION` geprüft. Ein erster Lauf vor der Korrekturrunde lief ohne Fehler durch, gilt aber für den alten Stand |
| `ruff check .` | grün |
| Länge aus dem Text (22 Fälle: m/cm/mm, „lang“, „über alles“; Bett-, Markisen-, Kabel-, Stellplatz-, Anhängerlänge und Werte außerhalb 4–12 m nicht) | bestanden |
| Basisfahrzeug (15 Fälle: baugleiche Plattformen, erste Nennung zählt; „Knaus T5“, „Transitbereich“, „Boxer Hund“, „Master-Bett“ nicht) | bestanden |
| Stufen und Gewichte (Modell nur mit Grundriss, Modellreihe, Marke, Klasse inkl. „Mittel“, andere; Basismarke Fiat/Ducato ohne Markenstufe), Länge und Basisfahrzeug im Gewicht (unbekannt neutral), Konfiguration überschreibt einzelne Werte | bestanden |
| Wirkung: gleiche Modelle bestimmen den Marktfaktor, ähnliche Länge gibt den Ausschlag, **ein einzelnes gleiches Modell überstimmt 7 andere nicht und hebt die Sicherheit nicht** (QA B1), Deckel 25 % (6 Fälle), Erklärung mit Zusammensetzung und Fahrzeugklasse, Vorfilter liefert dasselbe | bestanden |
| Kalkulation: Rechenstand E2, Gewichte und Feld `modell` eingefroren, gespeicherte Eingabe rechnet unverändert, neue Gewichte wirken nur auf neue Kalkulationen | bestanden |
| Wirkung auf synthetischen Daten (Orchestrator, 120 von 300 Inseraten, gegen die alten Gewichte): Marktniveau Median ±0 %, −6,8 % bis +5,3 %; Sicherheit 117× gleich | gerechnet, nicht als Test hinterlegt |
| QA (eine Runde, vor der Korrekturrunde: 71 bestanden, Proben p1–p4) | **Ablehnung** wegen B1 (hoch) – B1–B7 behoben, Regressionstests ergänzt; Korrekturen **nicht** erneut von der QA geprüft |
| Browser | nicht geprüft (nur der Erklärungstext ändert sich; die Vorlagen escapen ihn) |
| Wirkung auf echten Datenbestand, Windows-CI | nicht geprüft (CI folgt im PR) |

## P5-01 – Rechner analysieren, Kalibrierung mit tatsächlichen Ankaufspreisen (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2283 bestanden (vorher 2239), neu `test_kalibrierung.py` (44). Ein erster Lauf vor der Korrekturrunde wurde bei 72 % ohne Fehler abgebrochen (veralteter Stand) |
| `ruff check .` | grün |
| Empfindlichkeit in `docs/RECHNER-ANALYSE.md` (Max-EK 36.300 € bei 7 Parameteränderungen) | mit `config.yaml` gerechnet (Orchestrator), nicht als Test hinterlegt |
| Eingabeprüfung (gültig; 21 Fehlfälle: Art, EZ, Typen, Datum, Kauf vor EZ, PLZ, km, Verkauf nur zusammen/nicht vor Kauf, Längen) | bestanden |
| Fälle: Ankauf der App (storniert nicht, Kosten/Standzeit erst nach Verkauf, verkauft ohne Kosten = unbekannt, Parameterstand); nachgetragen zum Kaufdatum nur mit dem Marktmodell (heutige Vergleichsangebote ohne Wirkung), älteres Kaufdatum → höherer Plan | bestanden |
| Bericht: Kennzahlen (Median/Quartile interpoliert, gerade Anzahl), Belastbarkeit, keine Vorschläge unter 5 Fällen bzw. innerhalb der Toleranz, Vorschläge mit Warnung außerhalb des üblichen Bereichs, kaufmännisch gerundete Standzeit, Max-EK 0 gesondert, **nach Übernahme eines Vorschlags kein erneuter Vorschlag**, Fälle ohne Parameterstand nicht in den Vorschlägen, Konfiguration unverändert, Bewertung der Inserate unverändert | bestanden |
| Ankauf Ende zu Ende (Besichtigung → gekauft): Plan speichert den Parameterstand, Fall erscheint im Bericht | bestanden |
| Speicher (Anlegen, Reihenfolge, Löschen, CHECK der Tabelle), API (Einzelplatz, CSRF 403, 400 bei Fehleingabe, 404 beim Löschen, HTML in der Notiz), Rechte (Mitarbeiter und Händler-Zugang 403 für Lesen und Schreiben, Inhaber 200, Link nur für den Inhaber), Audit, CLI `scout.py kalibrierung` | bestanden |
| Migration v1, v19 → v20: Daten unverändert, Sicherung `vor-v20`, Rollback, Idempotenz, neue Datenbank | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – von `/ankaeufe` über „Kalibrierung“, Bericht mit Vorschlägen und Warnung, App-Ankauf ohne Kosten „4.000 € / –“, Fall nachtragen, Fehlermeldung bei unvollständigem Verkauf, Löschen, HTML im Fahrzeugnamen als Text; Handy 390 ohne Querscrollen; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 39 bestanden, eigene Proben) | Freigabe mit Auflagen – B1 (hoch), B2–B8 behoben bzw. dokumentiert; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Ankaufsdaten, Windows-CI | nicht geprüft (CI folgt im PR) |

## P4-05 – Abdeckung und Suchlücken messen (25.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2239 bestanden (vorher 2218), neu `test_abdeckung.py` (21) |
| `ruff check .` | grün |
| Zeitraum (`tage` 1–365, App 1–90, ungültige Eingaben, ab Mitternacht) | bestanden |
| Kennzahlen: neue Inserate je Quelle, Fahrzeuge als Zusammenhangskomponenten (nicht transitive Dubletten, wieder eingestelltes Altfahrzeug nicht neu), relevante Privatangebote (Bearbeitungsstatus zählt nicht, Filter-Sperre schon), Dubletten, nicht verfügbar, vollständig beschrieben, Läufe ohne Fehler je Art | bestanden |
| Zeitlücken (Lücken ab 2 Tagen, Rand bis heute, Plattform ohne Eingang), Gebietslücken (96 PLZ-Bereiche, ohne PLZ, Ausland), Profillücken (Hinweise zu Auftrag, Arten, PLZ-Bereichen, Anteil „unklar“) | bestanden |
| Ende zu Ende über die Datenbank: Zeitraumgrenze (2 ältere Inserate ausgenommen), Preisänderung ohne Erstpreis, Laufprotokoll, Eingangstage nur aus neu/geändert (Detailabruf und „gelöscht“ zählen nicht), **keine Schreibzugriffe** (`total_changes` unverändert) | bestanden |
| API/Seite (`/api/abdeckung`, `/abdeckung`, Link von `/status`), 400 bei ungültigem Zeitraum, HTML im Profilnamen escaped, Rechte (Mitarbeiter 200, Händler-Zugang 403), Zwischenspeicher der App (neu nur bei geändertem Bestand), CLI `scout.py abdeckung` | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – über „Status“ → „Abdeckung & Suchlücken“, Kennzahlen, Zeitlücken, Profilhinweise, Gebietslücken, Zeitraumwechsel 7 Tage; Handy 390 ohne Querscrollen; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 18 bestanden, Proben P1–P3, u. a. 38,6 s für 6.000 Inserate/365 Tage) | Freigabe mit Auflagen – B1–B7 behoben bzw. dokumentiert; Korrekturen **nicht** erneut von der QA geprüft |
| Laufzeit mit echtem Bestand, Windows-CI | nicht geprüft (CI folgt im PR) |

## P4-04 – Laufprotokoll, Intervalle je Quelle, Pause nach Sperre, Statusseite (24.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2204 bestanden, 14 fehlgeschlagen – alle in älteren Testdateien: `test_reimport.py` (13; der Vergleich des ganzen Datenbestands vor/nach einem Re-Import sah das neue Laufprotokoll wachsen → Protokoll aus diesem Vergleich ausgenommen, eigene Tests in `test_statusseite.py`) und `test_neuigkeiten.py` (1; prüfte die Service-Worker-Version exakt → „mindestens“). Danach `test_reimport.py`, `test_neuigkeiten.py`, `test_statusseite.py`: 102 bestanden. Neu `test_statusseite.py` (24) |
| `ruff check .` | grün |
| Einstellungen (gültig, Fehleingaben, unbekannte Quelle), Quellenstatus (Fehler in Folge, letzter Erfolg, letzter Fehler, Pause nach Sperre, Intervall, beides, verwaister Lauf) | bestanden |
| Importer: Suchlauf mit Zahlen je Quelle; Sperre (429) → Automatik überspringt ohne jeden Abruf (auch keine Detailseiten), von Hand läuft; Intervall; Pause hält auch nach 250 übersprungenen Läufen; geändertes Layout zählt als Fehler der Quelle (3 in Folge → Warnung); unerwarteter Fehler → „abgebrochen“; Protokoll-Schreibfehler und beschädigte Zeilen lassen den Lauf nicht scheitern; Seitenimport nur mit Dateien; Aufräumen nach 365 Tagen | bestanden |
| App (`starte("auto")` → Auslöser automatisch), CLI (`lauf` beachtet Intervalle, `--sofort` nicht) | bestanden |
| Übersicht/Warnungen, `/api/status`, `/status` (Fehlertext mit HTML escaped), Rechte (Mitarbeiter 200, Händler-Zugang 403), Links Desktop/Handy | bestanden |
| Migration v1, v18 → v19: Daten unverändert, Sicherung `vor-v19`, Rollback, Idempotenz, neue Datenbank | bestanden |
| Browser (Orchestrator, Chromium über Playwright): Desktop 1280 – Status über den Knopf „Status“, Warnung „Pause nach Sperre“, Quelle mit Fehler/Intervall/nächstem Abruf, 2 Läufe, HTML im Fehlertext als Text; Handy 390 – Link auf der Startseite, Seite ohne Querscrollen; 0 JS-Fehler | bestanden (Datumsformat und Ausrichtung danach angepasst) |
| QA (eine Runde, vor der Korrekturrunde: 28 bestanden, eigene Proben P1–P5) | Freigabe mit Auflagen – B1 (hoch), B2, B3, B5 behoben, B4/B7 dokumentiert; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Quelle mit Sperre, Auto-Suche über reale Zeiträume, Mandantenbetrieb, Windows-CI | nicht geprüft (CI folgt im PR) |

## P4-03 – Neuigkeiten: frisch eingegangen und Preissenkungen hervorheben, priorisieren, melden (24.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2193 bestanden, 1 fehlgeschlagen: `test_text_import.py::test_niedrigerer_preis_ist_preissenkung` erwartete, dass `preis_vorher` nach einer Erhöhung stehen bleibt – genau das ändert QA B4 bewusst. Erwartung angepasst (Erhöhung bleibt keine Senkung), danach `test_text_import.py` + `test_neuigkeiten.py`: 139 bestanden. Neu `test_neuigkeiten.py` (42) |
| `ruff check .` | grün |
| Senkung (14 Fälle: Schwellen 3 % / 500 €, Zeitfenster genau 14 Tage, Zukunft, wieder erhöht, ungültige Werte), Einstellungen mit Fehleingaben | bestanden |
| Stufen (13 Fälle): im Rahmen vor frisch, ohne belastbaren Max-EK kein „im Rahmen“, kleine Senkung über die Max-EK-Grenze ist „im Rahmen“; nur offene, sichtbare, nicht gesperrte Inserate (gewerblich, doppelt, Ausschlussbegriff, zu weit) | bestanden |
| Keine Wirkung: Bewertung, bereit, Sperre, Brief, Hinweise, Nachfassen, „neu“ gleich mit und ohne Neuigkeiten | bestanden |
| Import Ende zu Ende: zweiter Eingang mit niedrigerem Preis → Senkung; danach Erhöhung → `preis_vorher`/`preis_geaendert_am` leer, Preisverlauf mit 3 Einträgen vollständig | bestanden |
| API (`filter=neuigkeiten` nach Stufe sortiert, „im Rahmen“ zuerst, `/api/heute`, Einzelfahrzeug), Report (Kachel, Filter, Sortierung, Abzeichen), CSV-Spalte „Neuigkeit“ | bestanden |
| Melden: Mail nur mit Preissenkungen (Betreff, Text, Einzahl), vor dem Lauf gesenkt bzw. abgeschaltet → keine Mail, Max-EK „–“ ohne belastbare Bewertung; Dubletten einmal; Suchlauf zählt nur deutliche Senkungen („2 Preissenkungen, davon 1 deutlich“) | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – Kachel/Filter 2, „jetzt im Rahmen“ zuerst, Abzeichen „Preis −9.700 € (24.10.)“, Tooltip „48,3 %“, gesperrtes Inserat nicht dabei, HTML im Titel nicht ausgeführt; Handy 390 – Kachel und Liste „Neu & gesenkt“ (2); 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 45 bestanden, eigene Proben) | Freigabe mit Auflagen – B1–B7 behoben bzw. dokumentiert, B8 Hinweis; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Mails/SMTP, Browser-Benachrichtigung, Windows-CI | nicht geprüft (SMTP nur mit Ersatz; CI folgt im PR) |

## P4-02 – Suchgebiete: bundesweit, Umkreis, PLZ-Bereiche (24.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2152 bestanden (vorher 2095), neu `test_suchgebiete.py` (57); die letzte JS-Korrektur (versteckte Felder deaktiviert) und ihre statische Prüfung kamen danach – `test_suchgebiete.py` erneut: 57 bestanden |
| `ruff check .` | grün |
| Eingaben: Standard „bundesweit“, nur Angaben der gewählten Art gespeichert, PLZ-Bereiche normalisiert („70“ in „7“ entfällt); 28 ungültige Fälle (Gebietsart falsch/False/0, Mittelpunkt unbekannt/genähert/Vollbreiten-Ziffern/Zahl, Radius fehlt/0/1001/Text, Bereiche leer/zu viele/unbekannt/dreistellig/leerer Eintrag); lange Fehleingaben → kurze Meldung | bestanden |
| Zuordnung (18 Fälle): bundesweit wie bisher (auch Ausland), Umkreis inkl. Grenze genau auf km, Ausland → nein, Ort fehlt → unklar, genäherte PLZ bis 20 km über dem Umkreis → unklar, exakt bekannte PLZ ohne Toleranz; PLZ-Bereiche; „nein“ schlägt „unklar“; unvollständige Zeile → unklar | bestanden |
| Speicher und API: Umkreis-Treffer = Fahrzeuge mit angezeigter Entfernung ≤ 100 km (Mittelpunkt = Standort), PLZ-Bereich „8“ = Testinserate mit 8…; `gebiete`, `standort_plz`, `gebiet_text`; Fehleingabe → 400; keine Wirkung auf die Bewertung | bestanden |
| Migration v1, v16, v17 (mit Profil und Checkliste) → v18: Daten unverändert, Altprofil „bundesweit“, Sicherung `vor-v18`, Idempotenz, Rollback, neue Datenbank | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – Felder je Gebietsart ein-/ausgeblendet, PLZ-Vorschlag aus dem Standort, Umkreis 100 km → 15 Fahrzeuge (max. 12 km), PLZ-Bereiche „8, 81, 1“ → 32, ungültiger Radius im versteckten Feld blockiert nicht, „00“ → Meldung; Handy 390 – Profilauswahl 32; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 105 bestanden, eigene Proben mit Unicode-Ziffern/-Leerraum) | Freigabe mit Auflagen – B1–B6 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Datenbank des Betreibers, Windows-CI | nicht geprüft (CI folgt im PR) |

## P4-01 – Suchprofile als Filter, Abdeckungscheckliste je Plattform (24.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2095 bestanden (vorher 2039), neu `test_suchprofile.py` (56) |
| `ruff check .` | grün |
| Eingaben: Normalisierung (Name, Arten, Marken, Modell), 19 ungültige Profile, Checkliste (Plattform, angelegt, Adresse nur http(s) ohne Leerzeichen, AutoScout24 nicht „angelegt“), Notiz bleibt beim Speichern ohne Notiz erhalten | bestanden |
| Zuordnung passt/unklar/nein (21 Fälle: Art, Marke, Modell als ganzes Wort, Preis/EZ/km mit Grenzen und fehlenden Werten, „nein“ schlägt „unklar“); Abdeckung fehlt/angelegt/prüfen/nicht lesbar, Quote | bestanden |
| API: anlegen, Name doppelt, filtern (`profil=`, `unklar=nein`, `profil=²` → 400), Treffer-Endpunkt ohne 200er-Grenze (260 Inserate), Checkliste, löschen, 404; Rechte Inhaber/Mitarbeiter/Händler-Zugang, Token, Audit | bestanden |
| Keine Wirkung auf Bewertung, Ampel, Sperre, Brief (Vergleich mit und ohne Profile) | bestanden |
| Migration v1, v2, v10, v16 → v17: Daten unverändert, Sicherung `vor-v17`, Idempotenz, Rollback, neue Datenbank | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nach der Korrekturrunde): Desktop 1280 – Panel, Profil anlegen, Filter 60 → 10 Fahrzeuge, Checkliste (angelegt/fehlt/nicht lesbar, Abdeckung 50 %), Profil bleibt nach dem Speichern offen, Kommazahl vom Browser abgewiesen, Preisgrenze → 8; HTML im Profilnamen nicht ausgeführt. Handy 390 – Profilauswahl 60 → 8; 0 JS-Fehler | bestanden |
| QA (eine Runde, vor der Korrekturrunde: 53 bestanden, eigene Proben) | Freigabe mit Auflagen – B1–B9 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Datenbank des Betreibers, Service Worker offline, Windows-CI | nicht geprüft (CI folgt im PR) |

## P3-08 – Datenqualität: Markierungen und Wert je Fahrzeug (23.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 2039 bestanden (vorher 1985), neu `test_datenqualitaet.py` (54) |
| `ruff check .` | grün |
| Regeln je Inserat: fehlend (7), unplausibel (8 Fälle + 7 Grenzwerte ohne Markierung), Widerspruch (10 Fälle) und 11 typische Texte ohne Falschmarkierung (Wartungs-km, Reichweite, Modelljahr, „Erstzulassung Basisfahrzeug“, Basisfahrzeug im Titel) | bestanden |
| Fahrzeugsicht: fehlende Angabe im anderen Inserat, km-Rückgang, abweichende EZ, Toleranz, ohne Datum kein Vergleich; Wert/Stufen, nie negativ | bestanden |
| Keine Wirkung: Bewertung, Sperre, Brief, „bereit“ und Hinweise gleich bei beliebigen Markierungen | bestanden |
| Je Inserat nur einmal geprüft (Gruppe aus 6 bestätigten Dubletten) | bestanden |
| API (`datenqualitaet`, `/api/datenqualitaet`; Mitarbeiter 200, Händler-Zugang 403), CSV-Spalten, CLI `scout.py qualitaet`, Escaping in der Desktop-Ausgabe | bestanden |
| Plausibilität auf den 60 nachgebauten Inseraten: keine Markierung (keine Falschmeldungen) | geprüft |
| Browser (Orchestrator, Chromium über Playwright): Desktop 1280 – Abzeichen „Daten lückenhaft“, 30/100 mit 4 Markierungen, HTML im Titel nicht ausgeführt; Handy 390 – Karte und Listen-Abzeichen; 0 JS-Fehler | bestanden (vor der Korrekturrunde) |
| QA (eine Runde, vor der Korrekturrunde: 68 bestanden, ~45 eigene Proben, 5.000 Inserate in 10er-Gruppen 10,5 s) | Freigabe mit Auflagen – B1–B7 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Anzeigentexte, Windows-CI | nicht geprüft (CI folgt im PR) |

## P3-07 – Indizes nach Abfrageplan, Vorfilter der Vergleichsauswahl (23.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1985 bestanden (vorher 1964), neu `test_vorfilter.py` (21) |
| `ruff check .` | grün |
| Vorfilter ändert kein Ergebnis: 7 Zufallsbestände (je 400 Inserate mit Randfällen: Preis fehlt/<1.000/=1.000, Anbieter privat/gewerblich/unbekannt/ohne Schlüssel, Jahr fehlt/Kommazahl/2015.5, alte Anzeigen) und Toleranz 3/0/−1/2.0/6 – jede Bewertung, Sperre und jeder Brief gleich wie ohne Vorfilter | bestanden |
| Liste verändert (anhängen, ersetzen bei gleicher Länge, pop+insert) → gleiches Ergebnis wie vollständiger Durchlauf; Jahr als Text bricht wie bisher ab | bestanden |
| Abfragepläne der tatsächlich ausgeführten Detail-Warteschlange (mit/ohne Quellenfilter): Teilindex, keine Sortierung; Besichtigung zur Anfrage: Index | bestanden |
| Migration v1, v2, v10, v15 → v16: Daten unverändert, Indizes da, Sicherung `vor-v16`, Idempotenz, Rollback | bestanden |
| Messung (Orchestrator, nachgebauter Bestand, ohne Profiler, gleiche Ergebnisse geprüft): 1.000 / 3.000 / 6.000 Inserate 0,61 → 0,45 s / 3,42 → 1,34 s / 13,8–14,3 → 3,6–3,8 s; Detail-Warteschlange 200 Abfragen bei 20.000 Anzeigen 0,32 → 0,02 s | gemessen |
| Abfragepläne: 370 mitgeschnittene Anweisungen aus 13 Testmodulen auf 3.000 Inseraten, 37 mit Tabellendurchlauf, davon 2 im Betrieb relevant (behoben) | geprüft |
| QA (eine Runde, vor der Korrekturrunde: 61 + 38 bestanden, eigene Proben) | Freigabe mit Auflagen – B1, B2 behoben, B3 Backlog; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Datenbank des Betreibers, Windows-CI | nicht geprüft (CI folgt im PR) |

## P3-06 – Kontakte als Ereignisse (23.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1964 bestanden (vorher 1937), neu `test_kontakte.py` (27) |
| `ruff check .` | grün |
| Ereignisse: Text kopiert (erneut: ersetzt) → gesendet; direkt kontaktiert mit/ohne Text und Kanal; erneutes „kontaktiert“ und andere Status ohne Ereignis; Rückgängig verwirft; nur das zuletzt Kopierte wird bestätigt, ältere verworfen; neuer Brief überschreibt kein Nachfassen; Altbestand nach Bestätigung „app“ | bestanden |
| Nachfassen: vorbereitet, ersetzt, bestätigt (idempotent), verworfen nicht bestätigbar; erstes Nachfassen an nicht kontaktiertem Inserat → Status kontaktiert und Team-Kontakt | bestanden |
| Transaktion: Fehler im Ereignis → Status und Nachfass-Zähler unverändert; Team-Konflikt → kein Ereignis | bestanden |
| Verlauf über das ganze Fahrzeug (zwei Inserate, gleiches Fahrzeug) | bestanden |
| API: Kanal 400 bei Unsinn, Verlauf in `/api/fahrzeug` und `/api/kontakte`, Bestätigen 200/404/409; Team: Vorbereiter oder Inhaber, sonst 403, ohne Token 403, Händler-Zugang 403, Audit-Einträge | bestanden |
| Anonymisierung: Verkäufername aus allen Texten des Verlaufs entfernt, Zeitpunkte bleiben | bestanden |
| Migration v1, v2, v10, v14 → v15: bisherige Tabellen unverändert, Altbestand (Kontaktzeitpunkt, „Text kopiert“, Nachfassen) als `altbestand`, Sicherung `vor-v15`, Idempotenz, Rollback; neue DB mit Tabelle und Index (Abfrageplan) | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nachgebaute Daten): Desktop 1280 – Verlauf, „gesendet ✓“ fürs Nachfassen; Handy 390 – Verlauf mit Kanal und Betrag; 0 JS-Fehler | bestanden (vor und nach der Korrekturrunde) |
| QA (eine Runde, vor der Korrekturrunde: Teilsuite 102 bestanden, eigene Szenarien) | Freigabe mit Auflagen – B1 (HOCH), B2–B6, B8 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Abläufe mit mehreren Geräten, Windows-CI | nicht geprüft (CI folgt im PR) |

## P3-05 – Privat/Händler mit Herkunft der Einstufung (23.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1937 bestanden (vorher 1863), neu `test_anbieter.py` (74) |
| `ruff check .` | grün |
| Übernahmeregeln (33 Fälle): unbekannt ersetzt nie; gewerblich → privat nie automatisch; Händlerbeleg schlägt „privat“ aus dem Text-Import (QA B1); Korrektur bleibt gegen Importe, „unbekannt“ des Teams nur bis zum Händlerbeleg (QA B2) | bestanden |
| Herkunft je Quelle: Kleinanzeigen-Liste mit PRO / ohne Kennzeichen / mit Privatfilter, Detailseite (Privater Nutzer, Gewerblicher Nutzer, leer, ohne Kasten, Name „Privat-Camper-Center“, Privatanbieter), mobile.de-Anbieterkasten, Text-Import mit und ohne Auswahl | bestanden |
| Rechner (P2-05d): unbekannte Anbieter nicht in der Vergleichsbasis, Kalkulations-Auszug ohne sie, alte Eingaben ohne Schlüssel rechnen gleich nach; Ende-zu-Ende Vergleichsanzahl sinkt auf 0, wenn alle anderen unbekannt sind | bestanden |
| Wirkung, API, CSV: Sperre „gewerblicher Anbieter“ und Hinweis „Anbieter unbekannt“ nach Korrektur; `POST /api/anzeige/<id>/anbieter` 200/400/404; Team-Betrieb: ohne Token 403, Mitarbeiter darf, Händler-Zugang 403, Audit-Eintrag; CSV-Spalten | bestanden |
| Migration v1, v2, v10, v13 → v14: alle bisherigen Spalten und Zeilen gleich, Herkunft `altbestand` nur bei bekannter Anbieterart, Sicherung `vor-v14` = Stand davor, Idempotenz, Fehler im Schritt → Rollback, danach erfolgreich | bestanden |
| Re-Import (P3-03): unverändert bis auf die stärkere Herkunft nach Text-Import mit „privat“ (bewusst, im Test benannt) | bestanden |
| Browser (Orchestrator, Chromium über Playwright, nachgebaute Daten): Desktop 1280 – Einstufung „privat (laut Anzeige)“, Korrektur auf gewerblich; Handy 390 – „Anbieter unbekannt“ → „privat (vom Team korrigiert)“; 0 JS-Fehler | bestanden (nach der Korrekturrunde) |
| QA (eine Runde, vor der Korrekturrunde: Teilsuite 281 bestanden, volle Suite Exit 0) | Freigabe mit Auflagen – B1 (HOCH), B2–B4 behoben, B5 Betreiberfrage; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Portalseiten, Windows-CI, Laufzeit der Invariante bei großer Datenbank | nicht geprüft (CI folgt im PR) |

## P3-04 – Verfügbarkeit und zuletzt_bestaetigt (23.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1863 bestanden (vorher 1686), neu `test_verfuegbarkeit.py` (177) |
| `ruff check .` | grün |
| Migration v1, v2, v10, v11, v12 → v13: Zählungen und SHA-256 über Inseratspalten gleich, Sicherung `vor-v13` zurückspielbar, Idempotenz, Abbruch an jeder der 24 Stellen des Schritts → Rollback; alter Code (v12) lehnt v13-DB ab (QA) | bestanden |
| Übergänge je Kanal (Suche, Seite, Text, Mail, Ereignis, Detailabruf-404), Altersregel (Mail, Ereignis, ältere gespeicherte Seite, alte Mail) | bestanden |
| Titel-Erkennung: 17 Positiv-, 42 Negativfälle (u. a. „Rentner verkauft …“, „Probefahrt reserviert“); Ende-zu-Ende 13 Privat-Titel ohne Sperre | bestanden |
| Wirkung: verkauft/offline gesperrt, reserviert nur Hinweis; Ausblenden nur ohne Ankaufsarbeit (Reservierung, Besichtigung, Notiz, Ankauf bleiben sichtbar); alter Status „gelöscht“ wie offline | bestanden |
| Re-Import (P3-03) bleibt bit-gleich (außer `zuletzt_gesehen`/`zuletzt_bestaetigt`) | bestanden |
| API-Felder, `verfuegbar=` (400 bei unbekannt), CSV-Spalten, KPI | bestanden |
| Browser (QA, Chromium): Desktop 1280 und Handy 390 – Abzeichen, Checkbox „nur verfügbare“, XSS-Titel escaped, 0 JS-Fehler | 15 Prüfungen bestanden (vor der Korrekturrunde) |
| QA (eine Runde) | Freigabe mit Auflagen – F1 (HOCH), F2–F4 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Portalseiten, Windows-CI | nicht geprüft (CI folgt im PR) |

## P3-03 – Vollständiger Preisverlauf und Re-Import-Test (21.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1686 bestanden (vorher 1638), neu `test_reimport.py`, `test_preisverlauf.py` |
| `ruff check .` | grün |
| Re-Import identischer Daten über Suche, gespeicherte Seiten, Text, Mail, Ereignis (`api`) – auch kanalübergreifend und zweimal hintereinander: Dump **aller** Tabellen (aus `sqlite_master`) unverändert außer `zuletzt_gesehen`; Ergebnis „bekannt“ | bestanden |
| Andere Reihenfolge der Kanäle → gleicher fachlicher Endstand (6 Reihenfolgen in der Suite, 24 in der Voruntersuchung) | bestanden |
| Preisverlauf über Kanäle (Senkung, Erhöhung, zurück): vollständig, chronologisch, letzter Eintrag = aktueller Preis für alle Inserate | bestanden |
| Ältere Mail ändert neueren Preis nicht (gegen `zuletzt_gesehen` und gegen den Preisverlauf); Mail-Datum als Zeitpunkt, älter als 365 Tage → Einlesezeit | bestanden |
| Detailpreis über den echten Abrufweg in der Historie; Fehler beim Schreiben → vollständiger Rollback; Detailpreis 0 keine Senkung | bestanden |
| Re-Import nach Dubletten-Zusammenführung: Gruppe bleibt, keine neuen Fahrzeuge | bestanden |
| Re-Import nach Anonymisierung: kein Personendatum kehrt zurück (gespeicherte Seite, Suche, Text, Mail, Ereignis, Abgleich) | bestanden |
| `GET /api/preisverlauf`: Rollen (200/403/401), 404/400, schreibt nichts, keine Personendaten | bestanden |
| QA (eine Runde) | Freigabe mit Auflagen – M1, M2, N1–N3 behoben; Korrekturen **nicht** erneut von der QA geprüft |
| Echte Seiten/Mails, Windows-CI, Last | nicht geprüft (CI folgt im PR) |

## P3-02b – Dubletten bestätigen, ablehnen, aufheben mit Wirkung (20.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1638 bestanden (vorher 1529), neu `test_dubletten_entscheiden.py`, `test_dubletten_oberflaeche.py` |
| `ruff check .` | grün |
| Bestätigen hängt um, Protokoll vollständig, idempotent; Konflikt bei „verschieden“ in der Gruppe; Ketten und Verzweigungen | bestanden |
| Aufheben nur LIFO, bit-gleich; Zufallsketten (10 Seeds in der Suite, 40 bei der QA) | bestanden |
| Fehler mitten in der Transaktion → vollständiger Rollback; drei gleichzeitige Verbindungen (QA, je 30×) → keine Inkonsistenz | bestanden |
| Wirkung: Gruppe sperrt Anschreiben (auch über Mitglied ohne Preis, H1), Team-Sperre sofort (D2) und im Wettlauf (D3), heuristische Nachbarn der Mitglieder (M1); „verschieden“ hebt Paar-Sperre auf; Vergleichsbasis zählt die Gruppe einmal | bestanden |
| Ohne Entscheidungen bit-gleich zur reinen Heuristik; `bewerte_zeilen` ohne Datenbank-Import | bestanden |
| Rechte je Rolle × Aktion, CSRF, ungültige IDs → 400, Audit | bestanden |
| Oberfläche: kein innerHTML mit Daten, Links nur http(s), Rendern nach Rolle; Klicktest Desktop 1280 / Handy 390, hell/dunkel | 31 Prüfungen bestanden, 0 JS-Fehler |
| Leistung (QA, 50 000 Inserate, 13 000 Entscheidungen) | Wirkung laden 0,12 s; Gruppe je Anzeige 0,03 ms |
| QA (eine Runde) | Freigabe mit Auflagen – H1, M1, N2 behoben; N1/N3 Backlog (P3-02c); Korrekturen **nicht** erneut von der QA geprüft |
| Windows-CI, Service-Worker-Update im Browser, echte Geräte, echte Marktdaten | nicht geprüft (CI folgt im PR) |

## P3-02a – Fahrzeugidentität: Grundlage, Vorschläge nur lesend (20.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator nach der Korrekturrunde) | 1529 bestanden (vorher 1384), neu `test_identitaet.py`, `test_dubletten_vorschlaege.py` |
| `ruff check .` | grün |
| Migration v1, v2, v10, v11 → v12: Zählungen und Inhalte gleich, Sicherung `vor-v12` zurückspielbar, Idempotenz, Rollback bei Abbruch an jeder der 29 Stellen des Schritts | bestanden |
| Entscheidungen: Löschschutz, nur `gilt → aufgehoben`; Zuordnungen nur anfügbar | bestanden |
| Keine fachliche Wirkung: `bewerte_alle` und `dubletten_ids` nach eingetragenen Entscheidungen/Zuordnungen frisch gelesen identisch; Snapshot-Hash `bewerte_zeilen` gleich dem Stand vorher | bestanden |
| Invariante `finde_duplikate` ⇒ mindestens „mittel“ (außer Modellnummer-/Art-Widerspruch); QA-Fuzz 300 Seeds: 0 Verletzungen, 0 verlorene Paare an Blockgrenzen | bestanden |
| Falsch-Positive: Knaus Sky TI 650 vs. 700, Summit 600 vs. 640, Alkoven vs. Teilintegriert → kein Vorschlag; gleichzeitig online → höchstens „mittel“ | bestanden |
| Laufzeit: 50 100 Zeilen Vergleich 0,9 s; Worst Case 3000 gleiche Fahrzeuge 0,02 s (Obergrenze 2000 Paare/Block, Hinweis); 50 030 Inserate aus der Datenbank 13,7–15,3 s (vor der Korrektur gemessen) | gemessen |
| API-Rollen (Inhaber/Mitarbeiter 200, Händler 403, ohne Anmeldung 401), `limit`, Cache-Neuberechnung; CLI `scout.py dubletten` | bestanden |
| QA (eine Runde) | Freigabe mit Auflagen – B1–B4, B6, B7 behoben, B5 ergänzt; Korrekturen **nicht** erneut von der QA geprüft |
| Windows-CI, echte Marktdaten | nicht geprüft (CI folgt im PR) |

## P3-01 – Fahrzeuge getrennt von Inseraten, Schema v11 (20.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator) | 1384 bestanden (vorher 1365), neu `test_fahrzeuge.py` (19) |
| `ruff check .` | grün |
| Altbestand v1, v2, v10 (mit Kollision `legacy_id` NULL, Team-, Besichtigungs-, Ankaufsdaten) → v11: je Inserat ein Fahrzeug, alle bisherigen Tabellen zeilen- und inhaltsgleich, `integrity_check`/`foreign_key_check` ok | bestanden |
| Sicherung `vor-v11` vorhanden, zurückspielbar, danach erneute Migration | bestanden |
| Idempotenz, zwei gleichzeitige Prozesse (QA: 5×) → Schritt genau einmal | bestanden |
| Fehler an jeder der 27 Stellen des Schritts (QA) → Version 10, Schema unverändert | bestanden |
| Neue Inserate über Suche, Seiten-, Text-, Mail-Import, Ereigniseingang, Abgleich → je ein Fahrzeug; `inserat_id` in Beobachtungen/Preisverlauf korrekt | bestanden |
| Alter Code (v10) öffnet v11-Datenbank → Abbruch ohne Schreiben (QA) | bestanden |
| Laufzeit Migration inkl. Sicherung | 50 000 Inserate 0,3–0,4 s; 500 000 Inserate 5,0 s (QA) |
| Mandanten: zwei Datenbanken migrieren unabhängig, je eigene Sicherung | bestanden |
| Gegenproben (Trigger aus, Invarianten aus, Sicherung übersprungen) | alle erkannt |
| Windows-CI, echte Betreiberdatenbank | nicht geprüft (CI folgt im PR) |

## P2-06 – E-Mail-Suchagenten (.eml) (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator, Stand vor Zusammenführung mit P2-05) | 1048 bestanden (vorher 940), neu `test_email_eingang.py`, `test_email_haertung.py`, `test_email_betrieb.py` |
| `pytest -q` nach Zusammenführung mit P2-05 (Integrationszweig inkl. PR #24) | **1365 bestanden** |
| `ruff check .` | grün |
| Kein Netzabruf (Sockets und urllib gesperrt), Links aus Mails nie abgerufen | bestanden |
| Angriffsmails der QA (5 MB Links, 200 000 `[`, 40 000 Encoded Words, 100 000 MIME-Teile, tiefe Verschachtelung) | ≤ 2,5 s, ≤ 152 MB, sonst sauber abgelehnt (vorher bis 253 s bzw. MemoryError) |
| Preis nur aus Preiszeile; ältere Mail ändert neueren Preis nicht; Mails nach Datum gelesen | bestanden; Gegenprobe Altersprüfung aus → rot |
| Seite → Mail → Seite ohne zusätzliche Beobachtungen; Löschfrist inkl. Symlink-Schutz | bestanden |
| Schalter (CLI, API, Importer), Rollen (nur Inhaber), CSRF, Ordner aus der Anfrage ignoriert | bestanden |
| QA Runde 1 / Runde 2 | Freigabe mit Auflagen / Ablehnung (K1) – behoben; Runde 3 von der QA **nicht geprüft** |
| Echte Kleinanzeigen-/mobile.de-Mails (F3), Knopf im Browser, Windows-CI | nicht geprüft |
## P2-05 – Import per URL + eingefügtem Text (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator) | 1257 bestanden (vorher 940), neu `test_text_import.py`, `test_text_import_korrektur.py`, `test_text_import_r2.py`, `test_text_import_oberflaeche.py` |
| `ruff check .` | grün |
| Kein Netzabruf der Adresse (Sockets gesperrt), 22+ unzulässige Adressen (Lookalikes, Schema, IDN, Unicode-Ziffern, führende Null) abgelehnt | bestanden |
| Preise: Fließtext-Beträge (Markise, Reifen, Restschuld, Gutachten, Neupreis …) → kein Preis, keine Preissenkung; „24 900 € VB“ → 24.900; Nutzerpreis aus dem Formular wird gespeichert | bestanden |
| Bereinigung: Telefon, E-Mail, Straße, Namen entfernt; Fahrzeugdaten (Maße, Gurtplätze, Marken) bleiben; Datenbank-Durchsuchung findet keine Kontaktdaten | bestanden |
| Laufzeit: 61 bösartige Muster à 50 000 Zeichen (QA) | ≤ 0,46 s (vorher bis 17,5 s) |
| Rollen (Inhaber, Mitarbeiter 200; Standort 403; ohne Anmeldung 401; ohne CSRF 403), Schalter aus → 409 | bestanden |
| Angaben aus Suchlauf/Seitenimport bleiben bei Text-Import erhalten, Preissenkung wird weiter erkannt | bestanden |
| Klicktest Desktop 1280 px und Handy 390 px, hell/dunkel (Runde 1 der Oberfläche) | 61 Prüfungen bestanden, 0 JS-Fehler |
| QA Runde 1 / Runde 2 | Ablehnung / Ablehnung – Befunde behoben; Runde 3 von der QA **nicht geprüft** |
| Preisfeld der dritten Runde im Browser, echte kopierte Anzeigentexte, Windows-CI | nicht geprüft (CI folgt im PR) |

## P2-04 – Quellen und Eingänge schaltbar (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 940 bestanden (vorher 907), neu `test_schalter.py` (31), Ergänzungen in `test_mandanten.py` |
| `ruff check .` | grün |
| Nicht freigegebene Quelle im Suchlauf: kein Abruf, `uebersprungen` gemeldet, `fehler` bleibt leer | bestanden |
| `quellen an`/`aus` für nicht freigegebene Quelle → Exit ≠ 0, Tabelle unverändert; `aus` für freigegebene Quelle bleibt nach Neustart wirksam | bestanden |
| Detailabruf: gesperrte Zeilen verbrauchen das Limit nicht, werden nicht abgerufen | bestanden |
| Ereignis-Eingang `api` mit Tabellenfreigabe, aber gesperrter Adapterklasse → abgewiesen | bestanden |
| Eingang `seiten` abgeschaltet: `/api/import` → 409 `deaktiviert`, CLI liest nichts; Mandant A aus, Mandant B an | bestanden |
| Ungültiges `eingaenge` (Einzelbetrieb, `mandant.yaml`) → Start bricht mit Meldung ab | bestanden |
| Gegenproben (7 nach QA) | alle erkannt |
| Warnhinweis (15 s) im Browser, Windows-CI | nicht geprüft (CI folgt im PR) |

## P2-00 – Eingang-Schnittstelle (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 907 bestanden (vorher 891), neu `test_eingang.py` (16) |
| `ruff check .` | grün |
| Seitenimport-, mobile.de-, Kleinanzeigen-, Ereignis- und v4-Tests | unverändert grün (Testdaten „mobilede“ → „mobile.de“; Ereignisse über `api` mit Freigabe) |
| `SeitenEingang.lese` ohne Netz (Socket gesperrt) und ohne Datenbank | bestanden |
| Dasselbe Inserat über `manuell` und `email` → eine Zeile in `inserate`/`anzeigen`, keine doppelte Historie | bestanden |
| Unbekannte Plattform/Kanal, fremdes ID-Präfix, gemischte Lesung, `detail_ohne_id` → nichts geschrieben | bestanden |
| Ereignisspeicher weist `email`/`manuell` ab (ADR-035) | bestanden |
| QA: alle 6 Testseiten unter `tests/seiten/` passieren die ID-Prüfung; Dekodierung alt/neu an 20.005 Eingaben verglichen | 0 Abweisungen; 1 Abweichung (doppelte BOM, harmlos) |
| Gegenproben (9) | alle erkannt |
| Windows-CI, echte Betreiberdaten | nicht geprüft (CI folgt im PR) |

## Phase 1 – Abschluss (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | **891 bestanden** (vorher 853), neu u. a. `test_rechner_ohne_ez.py` (4), `test_phase1_abschluss.py` (17), `test_netz.py` (9), `test_app_threads.py` (7) |
| `ruff check .` | grün |
| P1-12: ohne EZ keine Beträge in Rechner, CSV, API, CLI; Besichtigung nur mit Marktwert (409 `grund=marktwert`); Invariante Erstangebot ≤ Max-EK ≤ VK über 96 Kombinationen | bestanden |
| P1-07: zwei Clients, veraltete Version → 409 mit aktuellem Stand; Planen nach Abschluss → 409 | bestanden |
| P1-15: HTTP je Rolle (Mitarbeiter: „gekauft“, Suchlauf, Import → 403; Knöpfe ausgeblendet) | bestanden |
| P1-14a: Anonymisierung (Profilname, Anschreiben, Besichtigungsangaben, Datei), gekauft geschützt, Frist, CLI | bestanden |
| P1-05: hängender WhatsApp-Versand blockiert andere Anfragen nicht | bestanden |
| P1-08: Bewertungsmodule laden weder `wmscout.datenbank` noch `sqlite3`; gleiche Ergebnisse aus Listen und Datenbank | bestanden |
| P1-09: `config.local.yaml` überlagert (auch über die CLI), ungültige Datei → Abbruch mit Meldung; `--passwort` abgelehnt | bestanden |
| P1-10: Python-Version in `pyproject.toml`, Installern, `scout.py`, Lock-Dateien einheitlich 3.13 | bestanden |
| Abdeckung (coverage 7.16, nur zum Messen außerhalb des Projekts installiert, gesamte Suite) | `netz.py` 97 %, `app.py` 79 %, `benachrichtigung.py` 86 % (vorher 27 % / 67 % / 81 %) |
| Gegenproben P1-11 (403/429 nicht mehr gesperrt; keine Pause bei 5xx; Auto-Suche ohne Fehlerbehandlung; kein STARTTLS) | alle 4 erkannt |
| Gegenproben P1-12, P1-07, P1-15, P1-14a, P1-05, P1-08, P1-09 | alle erkannt (zwei zunächst wirkungslose Gegenproben ersetzt) |
| Browser-Klicktest Handy (Chromium, 390 px): Inserat ohne EZ zeigt „Erstangebot –“, „Planen“ fragt nach dem Marktwert, Besichtigung mit `marktwert_manuell` 36.000 €; zwei Geräte: Konflikt → „anderen Stand laden“ übernimmt fremde Eingabe, „eigene behalten“ speichert die eigene | bestanden, 0 JS-Fehler (nur die erwarteten 409 in der Konsole) |
| Unabhängige QA-Prüfung (`qa-security-reviewer`, 881 Tests nachgestellt) | Freigabe mit Auflagen, kein KRITISCH; 1 HOCH (N1), 7 MITTEL, 8 NIEDRIG – alle behoben bis auf die unten genannten Reste, je mit Test |
| Gegenproben zu den QA-Korrekturen (N1 API, N1 Plan, N2, N6, Q6, Q15, N5, N8, N9, N4, offene Besichtigung) | alle 11 erkannt; eine weitere (Plan-Absicherung für ältere Besichtigungen) zunächst nicht erkannt → eigener Test ergänzt, danach erkannt |
| Browser (Chromium): Login mit `weiter=/.//evil.example`, `https://evil.example/`, `/\evil.example` → `/m`; `/m#/termine`, `/anfragen` bleiben | bestanden, 0 JS-Fehler |
| Browser: Service Worker speichert abgeschlossene Besichtigung nicht, offene schon | bestanden |
| `pip install` aus den neuen Lock-Dateien, Windows-CI, `installieren.bat` mit vorhandener 3.12-`.venv` | nicht geprüft (Windows-CI folgt im PR) |

**Stand der Befunde aus Phase 0 (Q1–Q18) nach Phase 1** – unabhängig geprüft (`qa-security-reviewer`), danach behoben wie angegeben:

| Befund | Stand | Beleg |
|---|---|---|
| Q1 KRITISCH | behoben (P1-12, Rest N1 behoben) | `test_rechner_ohne_ez.py`, `test_ankauf_ohne_ez_plant_mit_manuellem_marktwert` |
| Q2 HOCH | behoben (G0) | `test_sicherheit::test_negative_oder_kaputte_laenge_wird_sofort_abgelehnt` |
| Q3 HOCH | behoben: Widerruf (G0), Inserate (P1-14a) mit Frist – **Frist legt der Betreiber fest (Standard aus)** | `test_phase1_abschluss` (3 Tests) |
| Q4 | Betreiberentscheidung F11 „Lesen frei“ | `docs/ROLLEN.md` |
| Q5 | behoben (P1-15, N2) | `test_gekauft_verlassen_nur_inhaber`, Rollen-Tests |
| Q6 | behoben (serverseitige Prüfung) | `test_login_ziel_nur_eigene_pfade`, Browser-Test |
| Q7, Q8 | behoben (G0) | `test_ohne_nutzer_ist_ein_proxy_nicht_lokal`, `test_login_bremse_*` |
| Q9 | behoben bis auf bewusste Ausnahmen (`/api/ich`, Fotos offener Besichtigungen) | `test_abgeschlossene_besichtigung_nicht_auf_dem_geraet`, Browser-Test |
| Q10 | offen bis P3-07 (ADR-034) | – |
| Q11 | behoben (Rotation, Maskierung G0; Diagnose-Rohseiten mit Frist) | `test_frist_offene_besichtigung_…` |
| Q12 | behoben (P1-07) | `test_besichtigung_speichern_mit_version_und_planen_nach_abschluss` |
| Q13 | behoben | `test_ics_ohne_nacktes_cr_und_zustaendig_400` |
| Q14 | teilweise: `Secure` und Leerlauf erledigt (G0/G0b); CSRF-Token je Prozess bleibt | `test_cookie_secure_*` |
| Q15 | behoben | `test_ics_ohne_nacktes_cr_und_zustaendig_400` |
| Q16 | behoben (P1-09) | `test_team::test_cli_nutzer` |
| Q17 | behoben (P1-10) | `test_python_version_ueberall_gleich` |
| Q18 | behoben (Kommentar) | – |

## Phase G2 – Mandantenfähigkeit (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 853 bestanden, davon 6 neu (`test_mandanten.py`) |
| Konfiguration: erzwungene Pfade, verbotene Abschnitte, nicht geerbte Adresse/WhatsApp, doppelte/fehlende Hostnamen | bestanden |
| HTTP: Hostname wählt Mandanten; Zugang und Sitzung von A bei B wertlos; Anfragen, Audit, Live, Nutzung getrennt | bestanden |
| Unbekannter Host → 403 ohne Mandantennamen; 127.0.0.1 nur mit `--lokal` | bestanden |
| CLI `mandant anlegen/liste/nutzung`, `--mandant` | bestanden |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Reverse-Proxy mit mehreren Hostnamen, Windows-CI, Last | nicht geprüft (Windows-CI folgt im PR) |

## Phase G1 – Echtzeit per SSE und Nutzungszähler (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 847 bestanden, davon 7 neu (`test_live.py`) |
| SSE: Ereignis je Rolle, keine Inhalte, kein Ereignis bei abgelehnter Änderung, Wiederaufnahme mit `Last-Event-ID` | bestanden |
| SSE: nur angemeldet (401), Grenze je Zugang (429), Platz nach Ablauf der Lebensdauer frei | bestanden |
| Nutzungszähler aus vorhandenen Daten, nur Inhaber, Monatsformat | bestanden |
| Gegenprobe 7 Schutzstellen | alle erkannt |
| Browser-Klicktest Live (Desktop + Händler 390 px) | Notiz 0,44 s, Auktion 0,8 s, Gebot 0,45 s; 0 JS-Fehler, 0 CSP-Verstöße |
| Reverse-Proxy, Safari/iOS, Last mit vielen Verbindungen, Windows-CI | nicht geprüft (Windows-CI folgt im PR) |

## Phase G0b – Audit-Protokoll, Leerlauf, Rechte je Ankaufsschritt (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 840 bestanden, davon 6 neu (`test_audit.py`); Migrationstests auf v10 |
| Migration v1/v2-Altbestand → v10 | bestanden (Zeilenzahlen inkl. Sitzungen unverändert, Sicherung `vor-v10`) |
| Protokoll: Lesen/Ändern/abgelehnt/Anmeldung, keine Inhalte/Passwörter, nur Inhaber liest, nur anfügbar | bestanden |
| Gesperrte Datenbank: keine offene Transaktion trotz Audit | bestanden (bestehende Sperr-Tests) |
| Leerlauf-Zeitlimit inkl. Sitzungen vor v10 und „0 = aus“ | bestanden |
| Ankaufsschritte nur Zuständiger/Bearbeiter/Inhaber; PDF als Download in Sandbox | bestanden |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Windows-CI, Safari/iOS, großer Audit-Bestand | nicht geprüft (Windows-CI folgt im PR) |

## Phase G0 – Voraussetzungen für Skalierung (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, nach Merge mit Phase F) | 834 bestanden, davon 30 neu (`test_sicherheit.py` 17, `test_datenrechte.py` 6, `test_api_quellen.py` 7) |
| Rohe Verbindung: negative/ungültige Länge, fremder Host | 400 bzw. 403 sofort, Inhalt wird nicht gelesen |
| Login-Bremse, JSON-Pflicht, Origin/Sec-Fetch-Site, Proxy nicht „lokal“, Secure-Cookie | bestanden |
| Widerruf (Web + CLI): Personendaten, Fotos samt Dateien, Auktion, Freigabe | bestanden; zweite Anfrage desselben Verkäufers bleibt |
| Gegenprobe 12 Schutzstellen (9 + 3 nach Merge: Vertragsfoto-EXIF, Storno-Regel, Schwärzung der Besichtigung) | alle erkannt |
| `pip-audit -r requirements.txt` | keine bekannten Schwachstellen |
| Browser-Klicktest Login-Seite + Widerruf-Knopf (mit laufender Auktion) | bestanden, 0 JS-Fehler, 0 CSP-Verstöße |
| Widerruf mit Ankaufsvorgang (auch storniert) | verweigert (409), Verkäuferdaten bleiben |
| Reverse-Proxy, Safari/iOS | nicht geprüft |

## Phase F – Besichtigung und Abwicklung (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 804 bestanden, davon 8 neu (`test_ankauf.py`) |
| Ablauf Anfrage ohne/mit Demo-Zuschlag, Inserat, Ablehnung, Storno | bestanden (Weg, Plan aus nachrechenbarer Kalkulation, Provision nur mit Auktion) |
| Migration v8-Altbestand → v9 | Besichtigungen unverändert, neue Spalte leer, zweiter Lauf ohne Wirkung |
| Gegenprobe 18 Schutzstellen | alle erkannt |
| Browser-Klicktest Desktop + Handy (390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase E – Deal Intelligence (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 796 bestanden, davon 13 neu (`test_deal.py`) |
| Auszug der Vergleichsangebote = ganze Datenbank | gleiche Szenarien und gleicher Risikowert |
| Nachrechnen nach Änderung von Konfiguration und Marktdaten | gespeicherte Kalkulation unverändert, neue ändert sich |
| Manipulation (Ergebnis, Eingabe, Rechenversion, Trigger) | erkannt; CLI `kalkulation pruefen` meldet Abweichung mit Exit-Code ≠ 0 |
| Gegenprobe 14 Schutzstellen | alle erkannt |
| Browser-Klicktest Team + Standort (390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS, große Datenbank | nicht geprüft |

## Phase D – Demo-Auktionssystem (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 783 bestanden, davon 18 neu (`test_auktion.py`) |
| Gleichzeitige Gebote: 4 Prozesse (spawn) × 8 Runden, 3 Threads × 6 Runden | je Runde genau 1 Gebot angenommen, keine Fehler, keine offene Transaktion, Protokoll gültig, `integrity_check` ok |
| Migration v6-Altbestand → v7 | bestanden: Sicherung `vor-v7`, Bestandsdaten unverändert, zweiter Lauf ohne Wirkung |
| Gegenprobe 13 Schutzstellen | alle erkannt (Ende-Prüfung erst nach Testergänzung) |
| Browser-Klicktest Auktion (Desktop + Handybreite 390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase C – Händlerportal v1 (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 765 bestanden, davon 12 neu (`test_haendler.py`) |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Browser-Klicktest Händlerablauf | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase B – Verkäuferportal v1 (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 753 bestanden, davon 28 neu (`test_verkauf.py`) |
| Migration v1/v2/v4 → v5, parallel 3 Prozesse | bestanden (Versionstests angepasst) |
| Gegenprobe 4 Schutzstellen | alle erkannt (Fotopfad erst nach Testergänzung) |
| Browser-Klicktest `/verkaufen` + `/anfragen` | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## T2 + P1-06 – Team-Oberfläche, „gesendet ✓“ (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 725 bestanden, davon 8 neu (`test_team_oberflaeche.py`) |
| `node --check` der ausgelieferten Seite (mit Team, ohne Nutzer, statisch) und `mobil.js`/`sw.js` | ohne Fehler |
| Browser-Klicktest Desktop (Chromium, 3 Nutzer) | Übernehmen, Sperre, Filter, gesendet ✓, Badges, Zähler – bestanden, 0 JS-Fehler |
| Browser-Klicktest Handy (390×844) | Übernehmen, Sperre mit Grund, Filter „Frei“, gesendet ✓ – bestanden, 0 JS-Fehler |
| Safari/iOS, Windows-CI | nicht geprüft |

## P1-04b – `anzeigen` ↔ v4 (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 717 bestanden, davon 13 neu (`test_v4_abgleich.py`) |
| Gegenproben (5 Kernstellen einzeln entfernt) | jede erkannt (6 / 5 / 1 / 2 / 2 Fehlschläge) |
| Windows-CI | nicht geprüft (folgt im PR) |

## P1-04a/P1-04 – WAL, Sperr-Wartezeit, Laufsperre (14.–15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 684 bestehende + 12 neue (`test_parallelzugriff.py`) bestanden |
| `ruff check .` | grün |
| Gegenprobe ohne WAL / ohne DELETE-Sicherung / ohne Checkpoint-Prüfung | 5 / 1 / 1 Tests schlagen an |
| Laufsperre (`tests/test_laufsperre.py`, 8 Tests, Linux) | bestanden; Gegenprobe: App, `scout.py lauf`, Wiederherstellung, Freigabe nach Fehler – je 1 Test schlägt an |
| Windows-CI, 2. Lauf (895ba6b) | alle Jobs grün (Tests Windows/Linux, Start-Skripte) |
| Windows-CI, 1. Lauf | 1 Fehlschlag: `test_m2_reste_…` schrieb eine erfundene `-shm` neben die jetzt WAL-Datenbank (unter Windows gesperrt, Errno 22); Test stellt den Fall nun ausdrücklich im Modus DELETE nach |

## T1 – Team-Übersicht Kern und API (14.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q -p no:cacheprovider` (Orchestrator, nach Korrekturrunde 1) | **658 passed** |
| `ruff check .` / `node --check sw.js` | All checks passed! / ok |
| QA-Runde 1: Wettlauf 4 Prozesse (43 Runden: übernehmen, kontaktiert, nachgefasst, Dubletten) | je Runde genau ein Gewinner, 0 offene Transaktionen |
| QA-Runde 1: Regression ohne Nutzer (HTTP, DB, CSV, Report gegen e99623e) | gleich bis auf Zeitstempel und neue Felder |
| QA-Runde 1: 19 Mutationen | 19 erkannt |
| QA-Urteil Runde 1 | **FREIGABE MIT AUFLAGEN** (H1 Besichtigung, H2 Verhandlung, H3 Doku) → Korrekturrunde 1 |
| Agent nach Korrekturrunde 1: QA-Skripte (Nebenwege, Wettlauf, Sperre, Dubletten, Inaktive, Suchlauf, Regression) | H1/H2 → 409; 503 statt 500, keine offene Transaktion; 10× `/api/status` mit Team 16,1 s → 0,2 s |
| QA-Runde 2 (f16943d) | FREIGABE MIT AUFLAGEN (Q-H1 Selbsteintragung als Besichtiger) → Korrekturrunde 2 |
| Nach Korrekturrunde 2 (Agent): pytest / Mutationen (volle Suite je Mutation) | **678 passed**; **62 von 63** erkannt (1 gleichwertig) |
| QA-Skripte nach Korrekturrunde 2 (Besichtiger, Erzwingen, Sperre, Dubletten-Cache, Nebenwege) | Selbsteintragung 403; Erzwingen übernimmt, Log nur bei Änderung; Sperre → 503 ohne halben Zustand |
| Browser, Windows | nicht geprüft |

---


## P2-05b – mobile.de: gespeicherte Seiten einlesen (14.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q -p no:cacheprovider` (Orchestrator, nach Korrekturrunde 1) | **570 passed** |
| `ruff check .` / `node --check mobil.js` | All checks passed! / ok |
| QA-Runde 1: Feldvergleich aller 70 Trefferblöcke der 6 echten Seiten (unabhängiger Extraktor) | 0 Abweichungen |
| QA-Runde 1: Datenschutz (41 Telefonnummern, 43 seller-IDs, 19 Händlertexte, Tracking) in DB/Report/CSV/API/Log | 0 Treffer |
| QA-Runde 1: Kleinanzeigen-Regression (18 echte Seiten + Fixtures, Code vor/nach) | Hash identisch |
| QA-Urteil Runde 1 | **ABLEHNUNG** (H1 Handy 404, H2 Fixtures, H3 Ausland) → Korrekturrunde 1 |
| Agent nach Korrekturrunde 1: 6 echte Seiten | 65 Inserate, 24 privat, 41 gewerblich, 0 unbekannt; 2 Auslandsorte mit Hinweis; Fixture-Kombinationsscan 0 Treffer; 24 Mutanten erkannt |
| QA-Runde 2, „Webseite, nur HTML“, Händler-Anzeigenseite, Browser-Klicktest | nicht geprüft |

---

## P2-05 (Teil) – Hinweise statt Sperre, Anrede mit Verkäufername (14.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `.venv/bin/python -m pytest -q -p no:cacheprovider` (Orchestrator) | 7f96a8e: 326 passed; nach Korrektur Runde 6 (bcdb68b): **374 passed** |
| `.venv/bin/python -m ruff check .` | All checks passed! |
| `node --check wmscout/web/static/mobil.js` (Agent) | ohne Fehler |
| QA-Runde 5 (Stand a912c83): 18 echte Seiten, Temp-DB, Sockets gesperrt | 352 Inserate; bestätigt 2, vorläufig 186, unbekannt 164; nicht bestätigt ohne Hinweis: **0**; Sperrgrund Fahrzeugart: 0; vorwärts/rückwärts 0 Abweichungen |
| QA-Runde 5: K-A am echten Original mit eingesetztem Filter | altads-Seiten: 0 bestätigt; Adria-Seite: 27 bestätigt |
| QA-Runde 5: Mutationen | 26 von 29 erkannt (überlebt: `|safe`, Ziffernprüfung, eine gleichwertige) → in dieser Runde mit Tests abgedeckt |
| Mutationen der Agenten (Kopien) | Import-Korrektur: alle erkannt (M1, M2, M4, N1, N3, N5, H2); Anschreiben: 13 von 13 |
| QA-Urteil Runde 5 | **ABLEHNUNG** (H1–H3, M1–M4) → bearbeitet |
| QA-Runde 6 (7f96a8e): 18 echte Seiten, Briefmatrix 1.152 Briefe + 1.152 Nachfass-Texte | Modell mehrfach: 0; Art-Wort bei nicht bestätigter Art: 0; Escaping hält; Mutationen 28 von 34 erkannt |
| QA-Urteil Runde 6 | **ABLEHNUNG** (H1-R echte Namen zurück, H6-1 Wohnwagen als „Sonstige“ auf Rang 3) → bearbeitet |
| Agent nach Korrektur Runde 6: 18 echte Seiten vorher/nachher | Bürstner-Wohnwagen 54.600 € (hoch, Rang 3) → 18.900 € (niedrig, Rang 22); Dethleffs-Wohnanhänger → nicht bereit; Sicherheit bei unbekannter Art: 96 niedrig, 68 keine |
| QA-Runde 7 (be0afd2): Tests, 18 echte Seiten, Hinweise, Briefe, id-Leck, Laufzeit, Mutationen | 374 passed; Hinweise konsistent in allen Ausgaben; `#als`-id 0 Treffer; 1.500 unbekannte Importe 23 s statt 6,4 s; Mutationen 24 von 28 |
| QA-Urteil Runde 7 | **FREIGABE MIT AUFLAGEN** – A1: F14 (10 der Top 20 sind Wohnwagen ohne Art-Wort, Rechnung als „Sonstige“) vor Merge entscheiden; A2: M7-1/M7-2 → behoben |
| Namensschutz nach M7-1 (Orchestrator) | Gegenprobe: eingefügter echter Name → Test rot; ohne → grün |
| Q2-H1 (Nachfassen/gespeicherter Betrag ohne Betrag im Brief) | 2 Tests, Mutationen erkannt; **465 passed**, ruff grün |
| Nach Zusammenführung mit PR #5 (Datensicherung) | zunächst 8 failed (doppelte `main()` in `scout.py`, `:memory:`-Test) → behoben: **464 passed**, ruff grün |
| F14 (Orchestrator): Ampel höchstens gelb, Brief ohne Betrag bei unbekannter Art | **377 passed** (vor Zusammenführung); Mutationen „Ampel nicht gedeckelt“ und „Betrag trotzdem“ jeweils von einem Test erkannt |
| Browser-Klicktest Hinweiszeile, Windows, CI | nicht geprüft |

---

## P2-05 (Teil) – Gespeicherte Seiten einlesen (13.10.2026) · BLOCKED (aufgehoben 14.10.2026)

| Prüfung | Ergebnis |
|---|---|
| `.venv/bin/python -m pytest -q` (Stand 9b2396d) | **194 passed** |
| `.venv/bin/python -m ruff check .` | All checks passed! |
| 18 echte gespeicherte Seiten (Temp-DB, Netz gesperrt) | 16 Such- und 2 Detailseiten erkannt, 0 nicht erkannt; 352 neu, 42 bekannt. Arten: bestätigt 2, vorläufig 186, unbekannt 164. Bereit 0, nicht bestätigt und bereit 0. Reihenfolge vorwärts/rückwärts: 0 Abweichungen |
| Stichproben gegen Originale (Preis, Ort, EZ, km, PRO, Gesuche) | übereinstimmend (Orchestrator und QA) |
| Klicktest Desktop-Knopf (Chromium headless, Stand 796eda6) | Knopf, Meldung und Neuladen funktionieren, keine JS-Fehler |
| QA-Mutationsproben | Runde 2: 20 von 20 erkannt, Runde 3: 13 von 13, Runde 4: 17 von 18 (H-T unentdeckt) |
| QA-Urteil nach Runde 3 | **ABLEHNUNG**: K-A KRITISCH (Art-Filter bestätigt auch „Weitere Ergebnisse in anderen Orten“); H-T, M-W, N-1 bis N-3 offen |
| Windows | nicht geprüft |
| Echte Seite mit Kleinanzeigen-Art-Filter | **nicht geprüft** (liegt nicht vor) |
## P1-02 / P1-03 – Datensicherung und Migrationsrahmen (14.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q -p no:cacheprovider` (Orchestrator, Worktree nach Korrekturrunde 2 und Test N-1) | **182 passed** |
| `ruff check .` | All checks passed! |
| QA-Runde 1 (1b104ad): Nachbau „älteste Sicherung bei voller Aufbewahrung“ | **leere DB** (K1) → ABLEHNUNG |
| QA-Runde 2 (e8b1be1): K1/H1/Zip-Slip/paralleles Neuanlegen nachgebaut | behoben (Quelle bleibt, 15 → 16 Sicherungen, 3× abgewiesen, 0 Fehler) |
| QA-Runde 2: Uhrsprung, 2 Prozesse auf Altbestand, abgeschnittenes ZIP, UNC-URI | Befunde Q-F1–Q-F5 reproduziert → FREIGABE MIT AUFLAGEN |
| Agent nach Korrekturrunde 2: QA-Skripte s4/s7/s9/s5/s1 | Sicherungen bleiben; 10 Runden à 2 Prozesse 0 Fehler; kein Traceback |
| Migration v1-Altbestand (QA, 203 Zeilen) | ohne Verlust, Sicherung = Altstand, zweiter Lauf ändert nichts |
| CI Windows (PR #5, 4edf505) | **7 failed**: offene Test-Verbindungen sperrten die Datei („Zugriff verweigert“ beim Austausch), `?` im Ordnernamen → behoben: Tests schließen Verbindungen (lokal 0 ResourceWarnings statt mehrerer), Austausch mit kurzen Wiederholungen, Ordnername ohne `?` unter Windows; 184 passed lokal. CI 0616f1f: Windows nur noch 1 failed (Linux-spezifischer UNC-Nachbau `//tmp` → unter Windows übersprungen, dort decken die `PureWindowsPath`-Fälle UNC ab) |
| Netzlaufwerke | nicht geprüft |
| QA-Runde 3 (001fe60): Q-F-Nachstellungen, 8 Prozesse gleichzeitig, Aufräumen mit zurückdatierten Dateien, Schreibschutz (als `nobody`) | alle Q-F behoben; 8 eindeutige intakte Sicherungen; DB und Sicherungen bleiben; kein Datenverlust |
| QA-Runde 3: Mutationen (55 des Agenten + 14 eigene) | 64 von 69 getötet; X1 (Aufräumen trifft DB) danach durch erweiterten Test erkannt (Orchestrator, Gegenprobe in Kopie) |
| QA-Urteil Runde 3 | **FREIGABE** (N-1 MITTEL behoben, N-2..N-7 NIEDRIG im Backlog) |

---

## Phase 0 – Bestandsaufnahme (13.10.2026)

Prüfer: Orchestrator und Agent `qa-security-reviewer` (unabhängig; ohne Edit/Write, `Bash` nur per Prompt auf
Lesen und Tests beschränkt, siehe ADR-018).
Code-Stand: Integrationszweig 3f75f67 plus Phase-0-Dateien (Zweig `claude/phase0-agentensystem`).

### Ausgeführte Prüfungen

| Prüfung | Befehl | Ergebnis |
|---|---|---|
| Testsuite (Orchestrator) | `.venv/bin/python -m pytest -q` | **91 passed** (81 bisherige + 10 neue in `test_projekt.py`) |
| Testsuite nach Korrekturrunde P0-07 (Orchestrator) | `.venv/bin/python -m pytest -q` | **96 passed** (`test_projekt.py` von 10 auf 15 Tests erweitert, u. a. Belegprüfung `datei:zeile`) |
| Testsuite (QA, unabhängig) | `.venv/bin/python -m pytest -q -p no:cacheprovider` | **91 passed in 17.16s** |
| Statische Prüfung | `.venv/bin/python -m ruff check .` | **All checks passed!** |
| Testabdeckung | `coverage run --source=wmscout,scout -m pytest` (coverage außerhalb der `.venv` installiert) | **88 %** (1864 Anweisungen, 218 nicht ausgeführt) |
| Geheimnisse | `git grep -i -E "token\|passwort\|password\|api_key\|secret"` + Historie nach Schlüsselmustern | keine Geheimnisse gefunden |
| Missbrauchsfälle (QA, Skripte im Scratchpad, Temp-DB, ohne Netz) | negativer Content-Length, Lesen fremder Besichtigungen, Rollen, Versionskonflikt, Login-Zeitverhalten | Befunde Q1, Q2, Q4, Q5, Q8, Q12–Q14 **reproduziert** |
| CI (frühere PRs #1/#2) | GitHub Actions: Tests Ubuntu + Windows, Windows-Start (`installieren.bat`), Linux-Start | grün (Stand vor Phase 0) |

### Testabdeckung je Modul

| Modul | Abdeckung | ungetestet |
|---|---|---|
| `wmscout/netz.py` | **27 %** | gesamter höflicher Abruf: Abbruch bei 403/429/Captcha, Retry bei 5xx, Pausen |
| `wmscout/app.py` | **52 %** | Suchlauf-Thread `_lauf`, Auto-Suche-Schleife, `starte` |
| `wmscout/benachrichtigung.py` | **55 %** | Mailversand, WhatsApp-Fehlerpfade |
| `wmscout/normalisierung/fahrzeug.py` | 86 % | einzelne Erkennungszweige |
| `wmscout/importer.py` | 90 % | Fehlerpfade |
| `wmscout/web/api.py` | 92 % | einzelne Fehlerantworten |
| `wmscout/team.py` | 94 % | – |
| `wmscout/bewertung/rechner.py` | 95 % | – |
| `wmscout/bewertung/auswertung.py` | 96 % | – |
| `wmscout/datenbank.py` | 97 % | – |
| `wmscout/bewertung/besichtigung.py` | 99 % | – |
| `scout.py` | nicht gemessen | CLI-Tests laufen als Unterprozess |

### Urteil der QA

**FREIGABE MIT AUFLAGEN.** Tests und ruff sind grün. Die QA stufte Q1 zunächst als HOCH ein. Der Orchestrator
hob Q1 nach Hinweis des Architekten auf **KRITISCH**, weil die QA-Skala „falsche Ankaufsbeträge“ als KRITISCH
definiert. Offen sind damit:

- **KRITISCH:** Q1, R1 und R3 (`docs/ARCHITECTURE.md`)
- **HOCH:** Q2, Q3, R5 und R19
- **MITTEL:** 8 Befunde (Q4–Q11)
- **NIEDRIG:** 7 Befunde (Q12–Q18)

Alle Befunde sind Phase-1-Paketen zugeordnet.

Bestätigung der Architektur-Risiken durch die QA:

| Risiko | Urteil |
|---|---|
| R1 | bestätigt und im Prüflauf ausgeführt: Warnung wird geloggt, danach wird trotzdem importiert |
| R2 | bestätigt |
| R3 | bestätigt |
| R4 | bestätigt |
| R5 | bestätigt |
| R6 | bestätigt |
| R7 | teilweise: Python-`sqlite3` wartet standardmäßig 5 s; kein WAL, keine Laufsperre |
| R8 | bestätigt |
| R14 | ausgeführt: Speichern mit falscher Version überschreibt trotzdem |

### Befunde (QA und Architektur)

| ID | Stufe | Befund | Beleg | Paket |
|---|---|---|---|---|
| R1 | KRITISCH | Nicht freigegebene Quelle (Kleinanzeigen) läuft standardmäßig und per Auto-Suche alle 3 h; Detailabruf ohne Freigabeprüfung (R19) | `config.yaml:196`; `importer.py:39-40`; `importer.py:78-100` | P1-01a |
| R3 | KRITISCH | Keine Backups, keine Schemaversion; blockiert jede Migration (behoben mit P1-02/P1-03, `wmscout/migrationen.py`) | – | P1-02, P1-03 |
| Q1 | KRITISCH | Ohne Erstzulassung wird der **Angebotspreis als Marktniveau** genommen. Max-EK und Erstangebot sind damit zirkulär. Die Oberfläche blendet sie aus, CSV und eingefrorene Besichtigungsbasis übernehmen sie aber. | `rechner.py:261-264`; `api.py:104`; `ausgabe.py:57-58` | P1-12 |
| Q2 | HOCH | **Negativer `Content-Length`** umgeht das Größenlimit (`rfile.read(-1)`), noch vor der Anmeldung. Der Thread hängt und puffert unbegrenzt. | `api.py:485-488` (ausgeführt) | P1-13 |
| Q3 | HOCH | **Datenschutz:** Verkäuferdaten, Unterschriften und Fotos werden unbefristet gespeichert, eine Lösch- oder Anonymisierungsfunktion fehlt | `team.py`, `api.py:461-467` | P1-14a |
| R5 | HOCH | „kontaktiert“ schon beim Kopieren des Textes | `report.html:406`; `mobil.js:483` | P1-06 |
| Q4 | MITTEL | Lesen ist nicht autorisiert: Mitarbeiter sehen fremde Besichtigungen, Protokolle, Fotos und ICS | `api.py:218-224,274-288` (ausgeführt) | P1-15 |
| Q5 | MITTEL | Keine Rollenprüfung: Mitarbeiter setzen jeden Status (auch „gekauft“), starten Suchläufe, weisen zu | `api.py:361-376` (ausgeführt) | P1-15 |
| Q6 | MITTEL | Offene Weiterleitung nach dem Login (`/\evil.com`) | `vorlagen/login.html:34-35` (abgeleitet, nicht im Browser ausgeführt) | P1-13 |
| Q7 | MITTEL | „lokal“ wird am Host-Header erkannt. Hinter `tailscale serve` kommt jede Anfrage von 127.0.0.1. | `api.py:198-205` (Proxy-Verhalten nicht verifiziert) | P1-13 |
| Q8 | MITTEL | Login-Schutz: parallele Versuche unbegrenzt, scrypt unter dem globalen Lock; Zeitunterschied verrät, ob ein Nutzername existiert | `api.py:349-353`; `team.py:117-119` (ausgeführt) | P1-13 |
| Q9 | MITTEL | Service Worker cacht `/api/*` (inkl. CSRF-Token, Protokolle) und Fotos trotz `no-store`; Cache wird nur beim Abmelden geleert | `static/sw.js:17-24` | P1-14b |
| Q10 | MITTEL | Bewertung aller Inserate alle 30 s unter dem Lock (koppelt an R6/R12) | `auswertung.py:59-84`; `api.py:65-68` (nicht gemessen) | P1-05, P3-07 |
| Q11 | MITTEL | `scout.log` ohne Rotation, enthält Telefonnummern; Diagnose-HTML mit Verkäuferinhalten in `ausgabe/` | `scout.py:60-62`; `benachrichtigung.py:99,103` | P1-14a |
| Q12 | NIEDRIG | Abgeschlossene Besichtigung lässt sich weiter planen | `api.py:419-426` (ausgeführt) | P1-07 |
| Q13 | NIEDRIG | `zustaendig_id:"abc"` → 500 statt 400 | `api.py:392-397` (ausgeführt) | P1-13 |
| Q14 | NIEDRIG | `Secure`-Cookie hängt an fälschbarem `X-Forwarded-Proto`; ein CSRF-Token je Prozess; kein Leerlauf-Ablauf | `api.py:354` | P1-13 |
| Q15 | NIEDRIG | ICS-Escape behandelt `\r` nicht | `api.py:124-125` | P1-13 |
| Q16 | NIEDRIG | Verstecktes `--passwort` in Prozessliste/Shell-Historie | `scout.py:189` | P1-09 |
| Q17 | NIEDRIG | `installieren.bat` akzeptiert 3.10–3.13 | `installieren.bat:28` | P1-10 |
| Q18 | NIEDRIG | Irreführender Kommentar zur Thread-Nutzung | `datenbank.py:29` | P1-04 |

Positiv geprüft:
- **Keine XSS-Lücke gefunden.** Autoescape ist aktiv, kein `|safe`, Fremddaten laufen über `textContent` bzw. `esc()`, Links nur http(s), Unterschriften werden per Regex geprüft.
- **Foto-Upload ist robust.** Prüfung der Dateisignatur (Magic Bytes), UUID-Dateinamen, Auslieferung nur nach DB-Abgleich, `nosniff`.
- Lock-Dateien mit sha256-Hashes vorhanden.

### Fehlende Tests (QA)

1. `netz.py`: 403/429 → `QuelleGesperrt`, Retry bei 5xx, Pausen (gemockte Session).
2. Eine nicht freigegebene Quelle wird nicht abgerufen, weder per CLI noch per Auto-Suche. Der heutige `test_quellen.py:28` prüft nur das Flag.
3. Fehlerisolation: Ein Fehler in einer Quelle oder Suche stoppt die übrigen nicht.
4. `AutoSuche._schleife` und `Suchlauf._lauf` inklusive Fehlerpfad; Parallelbetrieb von App und `lauf`.
5. Rechner ohne EZ: keine Beträge in CSV und Besichtigungsbasis. §25a gegen Regelbesteuerung gegenrechnen. Invariante prüfen: Erstangebot ≤ Max-EK ≤ Verkaufspreis.
6. Versionskonflikt beim Speichern; Planen nach Abschluss.
7. Lese-Autorisierung, Rollenrechte, ungültiger Content-Length, Login-Weiterleitung, Host-Header hinter einem Proxy.
8. „kontaktiert“ erst nach Bestätigung (API-Vertragstest).
9. Mailversand mit gemocktem SMTP.

### Nicht geprüft

- Host-Header-Verhalten von `tailscale serve` (Q7) und die offene Weiterleitung im echten Browser (Q6).
- Windows-Startskripte unter Windows in dieser Phase: nur gelesen. Zuletzt geprüft in der CI der PRs #1/#2. Der CI-Lauf für Phase 0 folgt mit dem PR.
- Performance mit großem Datenbestand (Q10).
- Detailprüfung von `besichtigung.py`, `anschreiben.py`, `fahrzeug.py`, `geo.py` und dem Kleinanzeigen-Parser: nur über die Coverage geprüft.
- PWA-Caches und localStorage auf echten Geräten nach dem Abmelden.
- Handy-App auf echten Handys über Tailscale (offen seit PR #2).
- WhatsApp Cloud API live (offen seit PR #2).
