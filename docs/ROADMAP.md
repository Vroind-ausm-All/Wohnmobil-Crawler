# Roadmap und Backlog – Wohnmobil-Scout 2.0

Stand: 13.10.2026 · Gepflegt vom Orchestrator im Ablauf `scout-cycle`.

**Geschäftsziel:** Deutschlandweit möglichst früh geeignete, günstige Wohnmobile privater Verkäufer entdecken und die
besten Ankaufsgelegenheiten zuverlässig identifizieren.

| Phase | Titel | Status | Freigabe |
|---|---|---|---|
| 0 | Bestandsaufnahme | **REVIEW** | freigegeben (13.10.2026) |
| 1 | Stabile Grundlage | TODO (Teile bereits DONE, siehe unten) | **offen** |
| 2 | Multi-Quellen-System | TODO | offen |
| 3 | Datenbank und Marktbeobachtung | TODO | offen |
| 4 | Deutschlandweite Suchstrategie | TODO | offen |
| 5 | Intelligente Ankaufsbewertung | TODO | offen |
| 6 | Ankaufs-Dashboard | TODO (Teile bereits DONE durch die Handy-App) | offen |

Status je Paket: `TODO` / `IN_PROGRESS` / `REVIEW` / `DONE` / `BLOCKED`. Priorität: **P1** (zuerst, blockiert
anderes oder Regelverstoß) · **P2** · **P3**. Agent = verantwortlicher Implementierungs- bzw. Rechercheagent; jedes
Paket wird zusätzlich von `qa-security-reviewer` geprüft.

Frühere Zählung: Der Plan vom Oktober 2026 (`docs/ARCHITEKTUR.md`, jetzt `docs/ARCHITECTURE.md`) hatte die Phasen
1 Grundlage (= neue Phase 1, weitgehend erledigt), 2 Datenqualität (= neue Phase 3), 3 Suchsystem (= Teile der neuen
Phasen 2 und 4) und 4 Erweiterbarkeit (= Teil der neuen Phase 2).

---

## Phase 0 – Bestandsaufnahme

**Abnahme:** vollständiger Architektur- und Arbeitsplan; Agenten, Regeln, Skill und Loop angelegt; Planung von
Architekt und QA unabhängig geprüft.

| ID | Paket | Agent | Status |
|---|---|---|---|
| P0-01 | Repository, Branches, offene PRs prüfen; sichere Entwicklungsbasis bestimmen | Orchestrator | DONE |
| P0-02 | Acht Agenten in `.claude/agents/`, `CLAUDE.md`, Skill `scout-cycle`, `.claude/loop.md`, Test `test_projekt.py` | Orchestrator | DONE |
| P0-03 | Architektur- und Risikoüberblick (`ARCHITECTURE.md`, `DECISIONS.md`) | scout-architect | DONE |
| P0-04 | Quellenrecherche (`SOURCES.md`) | source-researcher | DONE (mit Einschränkung: Originale nicht direkt abrufbar → P2-01) |
| P0-05 | Fehlersammlung, Testabdeckung, Sicherheitslage (`TEST-REPORT.md`) | qa-security-reviewer | DONE |
| P0-06 | Roadmap, Backlog, Kennzahlen, WORKLOG | Orchestrator | DONE |
| P0-07 | Unabhängige Prüfung der Planung durch Architekt und QA; Korrekturen | scout-architect, qa-security-reviewer | siehe WORKLOG |

---

## Phase 1 – Stabile Grundlage

**Abnahme:** Bestehendes Programm startet zuverlässig (Windows-CI „Windows-Start“ grün), alle Regressionstests grün,
**Backup/Wiederherstellung getestet, `schema_version` vorhanden, keine nicht freigegebene Quelle läuft standardmäßig**.

Bereits erledigt (frühere PRs #1/#2, CI grün): Python 3.13 + `.venv` + Doppelklick-Start; gesperrte Abhängigkeiten mit
Hashes; pytest-Suite + GitHub Actions (Ubuntu, Windows, echter `installieren.bat`-Lauf); Aufteilung des Crawlers in
Quellen/Netz/Importer/Normalisierung/Datenbank/Bewertung/Ausgabe/Benachrichtigung; einheitliche Quellen-Schnittstelle.

| ID | Prio | Paket | Agent | Abhängig | Akzeptanzkriterien | Status |
|---|---|---|---|---|---|---|
| P1-01 | P1 | **Quellenfreigabe erzwingen** (R1, R2): nicht freigegebene Quellen laufen nur mit lokaler, nicht versionierter Betreiber-Ausnahme; Auto-Suche standardmäßig aus; ehrlicher User-Agent | source-integrations | Betreiberentscheidung | Test: Lauf ohne Ausnahme ruft Kleinanzeigen nicht ab und meldet das verständlich; mit Ausnahme wie bisher; App startet ohne Auto-Suche | TODO – **Entscheidung nötig** |
| P1-02 | P1 | **Backup und Wiederherstellung** (R3): `scout.py sichern` / `wiederherstellen` (SQLite-Backup-API, Fotos, `integrity_check`), Aufbewahrung konfigurierbar | scout-data-engineer | – | Test: Sicherung → Datenbank beschädigen → Wiederherstellung → identische Zählungen und Inhalte | TODO |
| P1-03 | P1 | **Migrationsrahmen** (ADR-009): `schema_version`, nummerierte idempotente Migrationen, automatisches Backup vor jeder Migration; heutige `ALTER TABLE`-Ergänzungen werden Migration 1–2 | scout-data-engineer | P1-02 | Tests mit v1-(ZIP)- und v2-Fixture: Version erkannt, keine Zeile/Spalte verloren, zweiter Start ändert nichts | TODO |
| P1-04 | P1 | **WAL, `busy_timeout`, Laufsperre** (R7, ADR-013) | scout-data-engineer | P1-03 | Test: paralleler Schreibzugriff während Suchlauf ohne „database is locked“; zweiter Lauf startet nicht parallel | TODO |
| P1-05 | P2 | **Globalen Lock entflechten** (R6): Lock nur um DB-Zugriffe, WhatsApp/E-Mail außerhalb | scout-ui-engineer | P1-04 | Test: langsamer WhatsApp-Aufruf blockiert keine andere Anfrage | TODO |
| P1-06 | P1 | **Kontakt erst nach Bestätigung** (R5, ADR-012): Kopieren → „vorbereitet“, Knopf „gesendet“ → „kontaktiert“ (Desktop + Handy); Nachfassen setzt „abgesagt“ nicht zurück | scout-ui-engineer | Betreiberfrage F7 | HTTP- und Klicktest: Kopieren ändert „kontaktiert“ nicht; Bestätigen setzt Datum | TODO |
| P1-07 | P2 | **Besichtigung: Versionskonflikt** (R14): `UPDATE … WHERE version=?`, sonst 409 mit Hinweis | scout-ui-engineer | – | Test mit zwei Geräten (zwei Clients) | TODO |
| P1-08 | P3 | **Bewertung von DB entkoppeln** (R15, ADR-015): Status in Domänenmodul, `bewerte_alle` bekommt Listen | acquisition-analyst | – | Bewertungstests ohne Datenbank; alle Regressionstests grün | TODO |
| P1-09 | P3 | **Lokale Konfiguration** (R16): `config.local.yaml` (ignoriert) überlagert `config.yaml`; Passwort nicht als CLI-Argument empfehlen | windows-bootstrap | – | Test: Überlagerung greift; `git status` sauber nach Betreiber-Einstellungen | TODO |
| P1-10 | P3 | **Python-Versionen** (R18): nur 3.13 oder 3.12/3.13 in CI-Matrix | windows-bootstrap | Betreiberfrage F9 | CI grün für alle zugelassenen Versionen | TODO |
| P1-11 | P2 | **Fehlende Tests** laut QA: `netz.py` (403/429/5xx, 27 % Abdeckung), Auto-Suche/Suchlauf-Thread, Mailversand mit gemocktem SMTP | windows-bootstrap (netz) / source-integrations | – | Abdeckung `netz.py` ≥ 85 %, `app.py` ≥ 75 %; Tests prüfen Verhalten, nicht nur Aufrufe | TODO |
| P1-12 | P1 | **Rechner ohne EZ** (Q1): kein Max-EK/Erstangebot aus dem Angebotspreis; CSV leer; Besichtigung nur mit manuellem Marktwert | acquisition-analyst | – | Test: Inserat ohne EZ → keine Beträge in CSV, API und Besichtigungsbasis; Invariante Erstangebot ≤ Max-EK ≤ VK | TODO |
| P1-13 | P1 | **Web-Härtung** (Q2, Q6, Q7, Q8, Q13, Q14, Q15): Content-Length prüfen (negativ/ungültig → 400), sichere Weiterleitung nach Login, „lokal“ nie hinter Proxy-Headern, Fehlversuchszähler + scrypt außerhalb des Locks + Dummy-Hash, 400 statt 500, `Secure` bei https-`oeffentliche_url`, ICS-`\r` | scout-ui-engineer | – | Negativtests je Befund (HTTP); bestehende Tests grün | TODO |
| P1-14 | P1 | **Datenschutz** (Q3, Q9, Q11): Lösch-/Anonymisierungsbefehl für Verkäuferdaten, Unterschriften, Fotos mit Frist; Service Worker cacht keine Protokolle/Fotos/`/api/ich`, Cache-Leerung bei 401; Log-Rotation, Nummern maskieren | scout-data-engineer, scout-ui-engineer | Betreiberfrage F10 (Fristen) | Tests: Löschung entfernt Daten und Dateien; Protokoll danach anonymisiert; SW-Regeln geprüft | TODO |
| P1-15 | P2 | **Rechte** (Q4, Q5): Lesen nur für Zuständige/Inhaber; Rollenmatrix (z. B. „gekauft“, Suchlauf, Zuweisung nur Inhaber) | scout-ui-engineer | Betreiberfrage F11 (Rollen) | HTTP-Tests je Rolle | TODO |

---

## Phase 2 – Multi-Quellen-System

**Abnahme:** mindestens zwei voneinander unabhängige, zulässige Eingangskanäle (geplant: manueller Import und
E-Mail-Suchbenachrichtigungen) werden über dieselbe Schnittstelle einheitlich verarbeitet; jede Quelle einzeln
aktivierbar; unzulässige Direkt-Crawler standardmäßig aus.

| ID | Prio | Paket | Agent | Abhängig | Status |
|---|---|---|---|---|---|
| P2-01 | P1 | AGB-Originale und `robots.txt` im Browser gegenlesen, Wortlaut mit Abrufdatum in `SOURCES.md` | Betreiber (manuell) + source-researcher | – | **BLOCKED** (Recherche-Umgebung ohne Seitenabruf) |
| P2-02 | P1 | Migration M2: `quellen`, `inserate` mit `UNIQUE(quelle, anzeigen_id)`, `oeffentliche_id`, Start `preis_historie`, `anbieter_typ` dreiwertig – **vor** der zweiten Quelle | scout-data-engineer | P1-03 | TODO |
| P2-03 | P1 | Fehlerisolation je Quelle/Suchauftrag, Quellenstatus (`zuletzt_ok`, `fehler_in_folge`, `gesperrt_bis`) | source-integrations | P2-02 | TODO |
| P2-04 | P1 | Quellen einzeln aktivierbar (Konfiguration + Tabelle `quellen`) | source-integrations | P2-02, P1-01 | TODO |
| P2-05 | P1 | **Manueller Import**: URL + eingefügter Text oder gespeicherte Seite, ohne Serverabruf (ADR-010); Desktop und Handy | source-integrations, scout-ui-engineer | P2-02 | TODO |
| P2-06 | P1 | **E-Mail-Suchbenachrichtigungen**: `.eml`-Import, Parser zuerst Kleinanzeigen, dann AutoScout24, mobile.de; keine verlinkten Seiten nachladen | source-integrations | P2-02; anonymisierte Beispiel-E-Mails (F3) | TODO |
| P2-07 | P2 | Optional: IMAP-Abruf eines eigenen Postfachs (Zugangsdaten aus Umgebungsvariablen) | source-integrations | P2-06, Betreiber-Postfach | TODO |
| P2-08 | P2 | mobile.de-API: Adapter-Stub (`zugriffsart = api`, `freigegeben = False`) + Anfrageschreiben an mobile.de vorbereiten | source-integrations, source-researcher | Vertrag | **BLOCKED** bis Zusage |
| P2-09 | P3 | Stubs/Anfragen AutoScout24, Caraworld, Quoka; Volumenprüfung regionaler Portale | source-researcher | – | TODO |
| P2-10 | P2 | Datenqualität je Quelle messen (Anteil Preis/EZ/km/PLZ/Anbieterart) | source-integrations | P2-03 | TODO |

## Phase 3 – Datenbank und Marktbeobachtung

**Abnahme:** identische Inserate lassen sich ohne Datenverlust erneut importieren; Preis- und Fahrzeughistorie bleiben
erhalten (Re-Import-Test).

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P3-01 | P1 | Migration M3: `fahrzeuge`, Ankaufsstatus am Fahrzeug, Kompatibilitäts-View `anzeigen` | scout-data-engineer | TODO |
| P3-02 | P1 | Fahrzeugidentität (FIN, Fingerabdruck mit Konfidenz), Dublettenvorschläge mit Bestätigung | scout-data-engineer | TODO |
| P3-03 | P1 | Vollständiger Preisverlauf, `beobachtungen` mit Quelle und Zeitpunkt | scout-data-engineer | TODO |
| P3-04 | P2 | Verfügbarkeit (`aktiv`/`reserviert`/`offline`/`verkauft`/`unbekannt`) + `zuletzt_bestaetigt` | scout-data-engineer | TODO |
| P3-05 | P2 | Privat/Händler-Klassifizierung mit Herkunft der Einstufung | scout-data-engineer | TODO |
| P3-06 | P1 | `kontakte` als Ereignisse (vorbereitet/bestätigt, Kanal, Nutzer) | scout-data-engineer | TODO |
| P3-07 | P2 | Indizes nach `EXPLAIN QUERY PLAN`, Vorfilter für Vergleichsauswahl (R12) | scout-data-engineer | TODO |
| P3-08 | P2 | Markierungen für unvollständige/widersprüchliche Angaben, Datenqualitätswert je Fahrzeug | scout-data-engineer | TODO |

## Phase 4 – Deutschlandweite Suchstrategie

**Abnahme:** Suchprofile sind reproduzierbar, ihre Ergebnisse dedupliziert und ihre Datenabdeckung messbar.

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P4-01 | P1 | Suchprofile in der Datenbank, verwaltbar in der App (Art, Marke, Modell, Preis, EZ, km) | source-integrations, scout-ui-engineer | TODO |
| P4-02 | P1 | Suchgebiete und PLZ-Regionen (bundesweit, Umkreis, Regionenliste) | source-integrations | TODO |
| P4-03 | P1 | Neue Angebote priorisieren; Preissenkungen erkennen und melden | source-integrations | TODO |
| P4-04 | P2 | Intervalle je Quelle; Suchläufe und Fehler überwachen (Statusseite) | source-integrations | TODO |
| P4-05 | P2 | Suchlücken und Abdeckung messen | scout-data-engineer | TODO |
| P4-06 | P3 | Vollständige und inkrementelle Bestandssuche für berechtigte API-Zugänge | source-integrations | BLOCKED bis API-Zugang |

## Phase 5 – Intelligente Ankaufsbewertung

**Abnahme:** jede Bewertung ist erklärbar und weist ihre Unsicherheit aus.

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P5-01 | P1 | Rechner analysieren; Kalibrierung mit manuell eingetragenen tatsächlichen Ankaufspreisen | acquisition-analyst | TODO |
| P5-02 | P1 | Vergleichsauswahl nach Marke/Modellreihe/Fahrzeugklasse, Ähnlichkeitsgewichte | acquisition-analyst | TODO |
| P5-03 | P1 | Marktwertspannen und Unsicherheit statt Punktwerte bei dünner Datenlage | acquisition-analyst | TODO |
| P5-04 | P2 | Angebotspreise vs. Transaktionspreise, Händler- vs. Privatpreise | acquisition-analyst | TODO |
| P5-05 | P2 | Ausstattung und Mängel; Reparatur-, Gewährleistungs-, Standkostenrisiko | acquisition-analyst | TODO |
| P5-06 | P2 | Transportkosten ab konfigurierbarer Standort-PLZ (Grundlage vorhanden: `anschreiben.plz`, `rechner.kosten.transport_*`) | acquisition-analyst | TODO |
| P5-07 | P1 | Deal-Score 0–100 mit benannten Komponenten; Speicherung in `bewertungen` mit `modell_version` | acquisition-analyst | TODO |

## Phase 6 – Ankaufs-Dashboard

**Abnahme:** der Weg vom neuen Angebot zur manuellen Kontaktaufnahme ist nachvollziehbar und ohne doppelte
Dateneingaben möglich.

Bereits vorhanden: Anschreiben je Modell/Baujahr mit vorbehaltlichem Angebot, Nachfassen, Verhandlungs-Assistent,
Handy-App mit Besichtigung, Mängelabzug, Protokoll, Terminen, WhatsApp-Links.

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P6-01 | P1 | Kombinierte Liste aller Quellen, Sortierung nach Deal-Score, Risikofaktoren sichtbar | scout-ui-engineer | TODO |
| P6-02 | P1 | Dublettengruppen und Preisverläufe anzeigen | scout-ui-engineer | TODO |
| P6-03 | P2 | Kontaktstatus (vorbereitet/kontaktiert/Antwort), Verhandlungsnotizen, Besichtigungsstatus im Dashboard | scout-ui-engineer | TODO |
| P6-04 | P2 | Benachrichtigungen im Dashboard (neu, Preissenkung, Antwort fällig) | scout-ui-engineer | TODO |
| P6-05 | P2 | Kennzahlen-Ansicht (siehe unten) | scout-ui-engineer, scout-data-engineer | TODO |
| P6-06 | P3 | Login-Härtung: Sperre nach Fehlversuchen (R17) | scout-ui-engineer | TODO |

---

## Kennzahlen (Erfolgsmessung)

Optimiert wird auf **relevante, verfügbare Ankaufsgelegenheiten**, nicht auf abgerufene Seiten.

| Kennzahl | Definition | Datengrundlage | messbar ab |
|---|---|---|---|
| Neue Inserate pro Quelle | Inserate mit `erstmals_gesehen` im Zeitraum, je Quelle | `inserate` | Phase 2 |
| Neue unterschiedliche Fahrzeuge | neue `fahrzeuge` im Zeitraum (nach Dublettenprüfung) | `fahrzeuge` | Phase 3 |
| Relevante Privatangebote pro Tag | neue Inserate mit `anbieter_typ = privat`, im Filter, verfügbar | `inserate`, Filter | Phase 3 |
| Doppelte Inserate | Inserate je Fahrzeug > 1 (bestätigt / vorgeschlagen) | `inserate`, `fahrzeuge` | Phase 3 |
| Importerfolgsquote | erfolgreich verarbeitete / angelieferte Datensätze je Quelle und Lauf | `suchlaeufe` | Phase 2 |
| Nicht verfügbare Inserate | Anteil `verfuegbarkeit ∈ {offline, verkauft}` | `inserate` | Phase 3 |
| Erkannte Preisänderungen | Einträge in `preis_historie` mit Änderung im Zeitraum | `preis_historie` | Phase 3 |
| Zeit Sichtung → Import | `erstmals_gesehen` − Einstellzeitpunkt laut Quelle (sofern geliefert) bzw. E-Mail-Zeitstempel | `beobachtungen` | Phase 2/4 |
| Vollständig beschriebene Fahrzeuge | Anteil mit Preis, EZ, km, PLZ, Art, Anbieterart | `fahrzeuge`, `inserate` | Phase 3 |
| Mittlere Marktwertunsicherheit | Median der relativen Spannenbreite (`spanne_bis − spanne_von`) / Marktwert | `bewertungen` | Phase 5 |
| Priorisierte Ankaufsangebote | Fahrzeuge mit Deal-Score ≥ Schwelle, verfügbar, privat | `bewertungen` | Phase 5 |
| Kontaktierte Verkäufer | **bestätigte** Kontakte (ADR-012) | `kontakte` | Phase 1 (UI) / 3 |
| Tatsächliche Ankäufe | manuell eingetragen (Besichtigung „gekauft“ mit Endpreis) | `besichtigungen` | heute |

---

## Offene Entscheidungen des Betreibers

| Nr. | Frage | betrifft |
|---|---|---|
| F1 | Kleinanzeigen-Direktabruf und Auto-Suche standardmäßig abschalten? Lokale Ausnahme auf eigene Verantwortung zulassen oder ganz abschalten? | P1-01 (KRITISCH) |
| F2 | Ehrlicher User-Agent (kann die Erreichbarkeit verändern)? | P1-01 |
| F3 | Postfach für Suchbenachrichtigungen: `.eml`-Upload oder IMAP? Anonymisierte Beispiel-E-Mails bereitstellen? | P2-06/07 |
| F4 | Bei mobile.de/AutoScout24 als Händler registriert? Anfrage für API-Zugang stellen? | P2-08/09 |
| F5 | Größe/Ort der produktiven Datenbank; vorhandene Sicherungen; Ziel und Aufbewahrung der Backups? | P1-02 |
| F6 | Altdaten `gewerblich = 0`: als privat übernehmen (Suchen filtern auf privat) oder „unbekannt“? | P2-02/P3-05 |
| F7 | Alte „kontaktiert“-Einträge als bestätigte Kontakte übernehmen? | P1-06/P3-06 |
| F8 | Läuft `lauf.bat` per Aufgabenplanung parallel zur App? | P1-04 |
| F9 | Nur Python 3.13 unterstützen oder auch 3.12? | P1-10 |
| F10 | Aufbewahrungsfristen für Verkäuferdaten, Fotos, Unterschriften (DSGVO); juristische Prüfung von Protokoll und E-Mail-Auswertung | P1-14 |
| F11 | Rollenrechte: Was dürfen Mitarbeiter (Status „gekauft“, Suchläufe starten, Besichtigungen anderer sehen/zuweisen)? | P1-15 |
