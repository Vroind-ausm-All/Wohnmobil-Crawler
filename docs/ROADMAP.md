# Roadmap und Backlog – Wohnmobil-Scout 2.0

Stand: 17.10.2026 · Gepflegt vom Orchestrator im Ablauf `scout-cycle`.

**Geschäftsziel:** Deutschlandweit möglichst früh geeignete, günstige Wohnmobile privater Verkäufer entdecken und die
besten Ankaufsgelegenheiten zuverlässig identifizieren.

| Phase | Titel | Status | Freigabe |
|---|---|---|---|
| 0 | Bestandsaufnahme | **REVIEW** (PR #3) | freigegeben (13.10.2026) |
| 1 | Stabile Grundlage | **REVIEW** (`claude/phase1-abschluss`, alle Pakete umgesetzt außer P1-01b BLOCKED) | **offen** – Abnahme durch den Betreiber |
| 2 | Multi-Quellen-System | **IN_PROGRESS** | freigegeben (17.10.2026) |
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
| P0-07 | Unabhängige Prüfung der Planung durch Architekt und QA; Korrekturen | scout-architect, qa-security-reviewer | DONE |

---

## Phase 1 – Stabile Grundlage

**Abnahme (Pflicht):**
- Das bestehende Programm startet zuverlässig (Windows-CI „Windows-Start“ grün), alle Regressionstests grün.
- Keine nicht freigegebene Quelle wird abgerufen, weder per Suche noch per Detailabruf (P1-01a).
- Backup und Wiederherstellung getestet (P1-02). `schema_version` mit Schutzregeln vorhanden (P1-03).
- WAL und Laufsperre getestet (P1-04). Keine Netzaufrufe unter dem Lock (P1-05).
- Kontakt zählt erst nach Bestätigung (P1-06). Keine Beträge ohne Erstzulassung (P1-12).
- Keine offenen KRITISCH/HOCH-Befunde aus `TEST-REPORT.md`.

P1-08, P1-09, P1-10 und P1-15 dürfen mit Begründung in die nächste Phase wandern.

Bereits erledigt (frühere PRs #1/#2, CI grün):
- Python 3.13 + `.venv` + Doppelklick-Start.
- Gesperrte Abhängigkeiten mit Hashes.
- pytest-Suite + GitHub Actions (Ubuntu, Windows, echter `installieren.bat`-Lauf).
- Aufteilung des Crawlers in Quellen, Netz, Importer, Normalisierung, Datenbank, Bewertung, Ausgabe, Benachrichtigung.
- Einheitliche Quellen-Schnittstelle.

| ID | Prio | Paket | Agent | Abhängig | Akzeptanzkriterien | Status |
|---|---|---|---|---|---|---|
| P1-01a | P1 | **Quellenfreigabe erzwingen** (R1, R2, R19, ADR-005): Importer verweigert `suche()` **und** `details()` für Quellen mit `freigegeben = False`; Auto-Suche in `config.yaml` auf 0; ehrlicher User-Agent | source-integrations | – | Fake-Abruf zählt 0 Aufrufe für Lauf, Auto-Suche und Detailpfad; Meldung in `gesamt["fehler"]` und in der App; bestehende Tests nutzen eine Testquelle mit `freigegeben = True` und werden nicht abgeschwächt | DONE (PR #7, gemergt; Prüfung auch für `details()`, Test `test_ereignisse::test_kleinanzeigen_web_gesperrt_auch_mit_fake_und_detailabruf`) |
| P1-01b | – | Lokale Ausnahme für Kleinanzeigen „auf eigene Verantwortung“ | – | F1: nur wenn der Betreiber Regel 12 selbst ändert | – (wird nicht auf Vorrat gebaut) | **BLOCKED** |
| P1-02 | P1 | **Backup und Wiederherstellung** (R3): `scout.py sichern` / `wiederherstellen` (SQLite-Backup-API, Fotos, `integrity_check`), Aufbewahrung konfigurierbar; Wiederherstellung nur nach ausdrücklicher Bestätigung „App und Suchlauf beendet“ (technische Sperre folgt mit P1-04) | scout-data-engineer | – | Test: Sicherung → Datenbank beschädigen → Wiederherstellung → identische Zählungen und Inhalte inkl. Fotos; ohne Bestätigung keine Wiederherstellung | DONE (PR #5, gemergt 14.10.2026) |
| P1-03 | P1 | **Migrationsrahmen** (ADR-009): `schema_version` (Version 3), nummerierte idempotente Migrationen, automatisches Backup vor jeder Migration; Start bricht ab, wenn die DB neuer ist als der Code | scout-data-engineer | P1-02 | Tests mit v1-(ZIP)- und v2-Fixture: Version erkannt, keine Zeile/Spalte verloren, zweiter Start ändert nichts; Migration ohne Backup bricht ab; „DB neuer als Code“ → verständliche Meldung | DONE (PR #5, gemergt 14.10.2026) |
| P1-04a | P1 | **WAL und `busy_timeout`** (R7, ADR-013): Journalmodus WAL (`ausgabe.wal`, Standard an), Wartezeit 10 s, Sicherungen als Einzeldatei (DELETE), Wiederherstellung erkennt Lesende per Checkpoint | Orchestrator | P1-03 | Test: Schreiber mit `timeout=0` neben offener Lesetransaktion; 4 Threads und 3 Prozesse ohne Verlust; Sicherung enthält Daten aus `-wal`; Wiederherstellung ohne alten `-wal`-Rest | DONE (PR #9, gemergt) |
| P1-04 | P1 | **Laufsperre** (Rest von R7, ADR-013): Dateisperre des Betriebssystems auf `<datenbank>.laufsperre` statt Tabelle mit Lease – keine Schemaänderung, Absturz gibt die Sperre frei | Orchestrator | P1-04a | Test: App-Suche und `scout.py lauf` starten nicht neben einem fremden Lauf (echter Prozess); Absturz (Kill) gibt frei; Wiederherstellung wird verweigert, solange ein Lauf aktiv ist; Freigabe auch nach Fehler im Lauf | DONE (PR #9, gemergt) |
| P1-04b | P0 | **`anzeigen` ↔ v4 gleich halten** (ADR-024, 3.0-Analyse P0): Suche/Seitenimport spiegeln nach v4, Ereignisse erscheinen in der App, Abgleich des Altbestands | Orchestrator | P1-04 | Test: ein Inserat je (Plattform, ID); nur Änderungen protokolliert; Löschereignis ändert keinen Ankaufstatus; ID-Kollision überschreibt nicht; Fehler rollt beide Seiten zurück; Abgleich idempotent, ohne neue Version | DONE (PR #10, gemergt) |
| P1-05 | P2 | **Globalen Lock entflechten** (R6, Q10): Verbindung je Thread, Lock nur um DB-Zugriffe, WhatsApp/E-Mail außerhalb | scout-data-engineer | P1-04 | Test: langsamer WhatsApp-Aufruf blockiert keine andere Anfrage | REVIEW (`claude/phase1-abschluss`) – eng umgesetzt (ADR-034): WhatsApp-Zuweisung im Hintergrund; Verbindung je Thread bewusst nicht |
| P1-06 | P1 | **Kontakt erst nach Bestätigung** (R5, ADR-012): neuer Statuswert `vorbereitet`; Text wird beim Kopieren gespeichert, `kontaktiert_am` erst beim Knopf „gesendet“; Nachfassen setzt „abgesagt“ nicht zurück; Dublettensperre (in `bewerte_alle`, Stand 3f75f67: `auswertung.py:74-83`) berücksichtigt `vorbereitet`. Kein Schemawechsel. | scout-ui-engineer | – | HTTP- und Klicktest (Desktop + Handy): Kopieren setzt nur `vorbereitet`; Bestätigen setzt `kontaktiert` + Datum | DONE (PR #11, gemergt) |
| P1-07 | P2 | **Besichtigung: Versionskonflikt** (R14, Q12): `UPDATE … WHERE version=?`, sonst 409; Planen nach Abschluss → 409 | scout-ui-engineer | – | Test mit zwei Clients; Planen nach Abschluss | REVIEW (`claude/phase1-abschluss`) |
| P1-08 | P3 | **Bewertung von DB entkoppeln** (R15, ADR-015): Status in Domänenmodul, `bewerte_alle` bekommt Listen | acquisition-analyst | P1-12 | Bewertungstests ohne Datenbank; alle Regressionstests grün | REVIEW (`claude/phase1-abschluss`) |
| P1-09 | P3 | **Lokale Konfiguration** (R16, Q16): `config.local.yaml` (ignoriert) überlagert `config.yaml`; `--passwort` nur über Umgebungsvariable | windows-bootstrap | – | Test: Überlagerung greift; `git status` sauber nach Betreiber-Einstellungen | REVIEW (`claude/phase1-abschluss`) |
| P1-10 | P3 | **Python-Versionen** (R18, Q17): nur 3.13 oder 3.12/3.13 in CI-Matrix | windows-bootstrap | F9 | CI grün für alle zugelassenen Versionen; `installieren.bat`, `pyproject.toml`, `scout.py` einheitlich | REVIEW (`claude/phase1-abschluss`) – F9: nur 3.13 |
| P1-11a | P2 | **Tests für `netz.py`** (27 % Abdeckung): 403/429/Captcha → `QuelleGesperrt`, Retry bei 5xx, Pausen (gemockte Session) | source-integrations | – | Abdeckung `netz.py` ≥ 85 %; Tests prüfen Verhalten | REVIEW (`claude/phase1-abschluss`) – Abdeckung `netz.py` 97 % |
| P1-11b | P2 | **Tests für App-Threads und Mail**: `Suchlauf._lauf`, `AutoSuche._schleife` inkl. Fehlerpfad, Mailversand mit gemocktem SMTP | scout-data-engineer | P1-04 | Abdeckung `app.py` ≥ 75 %, `benachrichtigung.py` ≥ 75 % | REVIEW (`claude/phase1-abschluss`) – Abdeckung `app.py` 79 %, `benachrichtigung.py` 86 %; Auto-Suche überlebt Fehler |
| P1-12 | P1 | **Rechner ohne EZ** (Q1, KRITISCH): kein Max-EK/Erstangebot aus dem Angebotspreis; CSV leer; Besichtigung nur mit manuellem Marktwert | acquisition-analyst | – | Test: Inserat ohne EZ → keine Beträge in CSV, API und Besichtigungsbasis; Invariante Erstangebot ≤ Max-EK ≤ VK | REVIEW (`claude/phase1-abschluss`) |
| P1-13 | P1 | **Web-Härtung** (Q2, Q6, Q7, Q8, Q13, Q14, Q15, R17): Content-Length prüfen (negativ/ungültig → 400); sichere Weiterleitung nach Login; „lokal“ nie bei Proxy-Headern; Fehlversuchszähler, scrypt außerhalb des Locks, Dummy-Hash; 400 statt 500; `Secure` bei https-`oeffentliche_url`; ICS-`\r` | scout-ui-engineer | P1-05 | Negativtest je Befund (HTTP); bestehende Tests grün | REVIEW – Q2/Q7/Q8/Q13/Q14 (Secure, Leerlauf) in G0/G0b gemergt; Q6 (Weiterleitung, jetzt serverseitig geprüft) und Q15 (ICS) in `claude/phase1-abschluss`. Offen: CSRF-Token je Sitzung statt je Prozess (`docs/PILOTBETRIEB.md`) |
| P1-14a | P1 | **Datenschutz Daten** (Q3, Q11): Lösch-/Anonymisierungsbefehl für Verkäuferdaten (u. a. Profilname in `details_json`, im gespeicherten Anschreibentext und in `ausgabe/`), Unterschriften, Fotos mit Frist; Log-Rotation; Nummern im Log maskieren | scout-data-engineer | F10 (Fristen) | Test: Löschung entfernt Daten und Dateien, Protokoll danach anonymisiert; Log enthält keine vollständigen Nummern | REVIEW (`claude/phase1-abschluss`) – F10: Befehl + Frist (Standard aus); Log-Rotation/Maskierung bereits G0 |
| P1-14b | P1 | **Datenschutz Handy** (Q9): Service Worker cacht keine Protokolle, Fotos und kein `/api/ich`; Cache-Leerung bei 401 | scout-ui-engineer | – | Test der SW-Regeln; Klicktest Abmelden/Ablauf | REVIEW (`claude/phase1-abschluss`) – Positivliste und Leeren bei 401 seit G0; jetzt keine abgeschlossenen Besichtigungen, keine Unterschriften/Verkäuferangaben auf dem Gerät. Bewusst offline: `/api/ich` (Start ohne Netz) und Fotos offener Besichtigungen |
| P1-15 | P2 | **Rechte** (Q4, Q5): Lesen nur für Zuständige/Inhaber; Rollenmatrix | scout-ui-engineer | F11 (Rollen) | HTTP-Tests je Rolle | REVIEW (`claude/phase1-abschluss`) – F11, `docs/ROLLEN.md` |

### Vorschlag erster Phase-1-Durchgang

Vorschlag des Architekten (P0-07): höchstens 5 Pakete, höchstens 3 Agenten parallel, je eigener Worktree, Dateien
exklusiv.

| Agent | Pakete | Dateien (exklusiv) |
|---|---|---|
| source-integrations | P1-01a, danach P1-11a | `importer.py`, `netz.py`, `config.yaml` (User-Agent, Auto-Suche), `app.py` (Meldung im Suchlauf), `tests/test_freigabe.py`, `tests/test_import.py`, `tests/test_quellen.py`, `tests/test_netz.py` (Meldung in der Oberfläche nur über die bestehende Fehleranzeige, keine Vorlagenänderung) |
| scout-data-engineer | P1-02 und P1-03 (Bündelung nur bei Zustimmung F12, sonst nacheinander) | `wmscout/sicherung.py`, `wmscout/migrationen.py` (neu), `datenbank.py`, `team.py` (Schema), `scout.py`, `tests/test_sicherung.py`, `tests/test_migration.py`, `tests/test_datenbank.py` |
| acquisition-analyst | P1-12 | `rechner.py`, `ausgabe.py`, `api.py` nur `basis_fuer` und Anlegen der Besichtigung, `bewertung/besichtigung.py`, `web/static/besichtigung.js` und `mobil.js` (Eingabe manueller Marktwert), `tests/test_rechner_ohne_ez.py`; Paritätstest muss grün bleiben |

Danach in dieser Reihenfolge, weil fast alle Pakete `api.py` ändern: P1-04 → P1-05 → P1-13 → P1-06 → P1-07 →
P1-14a/b → P1-15.

---

> **Regel:** Abhängigkeiten und Akzeptanzkriterien der Pakete in den Phasen 2–6 werden vor der Freigabe der jeweiligen
> Phase vom Architekten ergänzt und geprüft.

## Phase 2 – Multi-Quellen-System

**Abnahme:** mindestens zwei voneinander unabhängige, zulässige Eingangskanäle (geplant: manueller Import und
E-Mail-Suchbenachrichtigungen) werden über dieselbe Schnittstelle einheitlich verarbeitet; jede Quelle einzeln
aktivierbar; unzulässige Direkt-Crawler standardmäßig aus.

**Stand 18.10.2026 (Betreiber):** Phase 2 ist für alle Kanäle ohne API-Zugang umgesetzt (gespeicherte Seiten, URL + Text,
E-Mail-Suchagenten; Schalter je Quelle und Eingang) – die Abnahme ist damit erfüllt, bis auf die Prüfung mit echten Mails (F3).
Die übrigen Pakete hängen an Zugängen, die es noch nicht gibt (API-Verträge, AGB-Prüfung im Browser), oder lohnen erst mit
echten Daten; sie sind zurückgestellt bzw. blockiert. Weiter mit Phase 3; wieder aufnehmen, sobald ein API-Zugang oder echte
Beispiel-Mails vorliegen.

| ID | Prio | Paket | Agent | Abhängig | Status |
|---|---|---|---|---|---|
| P2-00 | P1 | **Architektur Push-Eingänge** (ADR-016/017): Plattform ≠ Eingangskanal, `Eingang.lese(Rohdaten) -> Lesung`, `Importer.importiere(lesung, kanal)` (ADR-035); Vertrags- und Isolationstests für Pull und Push | scout-architect (Entwurf), source-integrations | P1-03 | REVIEW (`claude/phase2-eingang`) – ein Schreibweg, kanonische Plattform-IDs, ADR-035 |
| P2-01 | P1 | AGB-Originale und `robots.txt` im Browser gegenlesen, Wortlaut mit Abrufdatum in `SOURCES.md` | Betreiber (manuell) + source-researcher | – | **BLOCKED** (Recherche-Umgebung ohne Seitenabruf) |
| P2-02 | P1 | Migration auf Version 4: `quellen`, `inserate` mit `UNIQUE(plattform, anzeigen_id)`, `beobachtungen.kanal`, `oeffentliche_id`, Start `preis_historie`, `anbieter_typ` dreiwertig – **vor** der zweiten Quelle | scout-data-engineer | P2-00 | DONE (PR #7/#10, gemergt) – Rest (`oeffentliche_id`, dreiwertige Anbieterart) → Phase 3 |
| P2-03 | P1 | Fehlerisolation je Quelle/Suchauftrag, Quellenstatus (`zuletzt_ok`, `fehler_in_folge`, `gesperrt_bis`) | source-integrations | P2-02 | ZURÜCKGESTELLT (18.10.2026) – lohnt erst mit automatischen Quellen; heute läuft keine Pull-Quelle (alle nicht freigegeben), die Push-Eingänge sind je Datei isoliert |
| P2-04 | P1 | Quellen einzeln aktivierbar (Konfiguration + Tabelle `quellen`) | source-integrations | P2-02, P1-01a | DONE (PR #23, gemergt) |
| P2-05 | P1 | **Manueller Import**: URL + eingefügter Text oder gespeicherte Seite, ohne Serverabruf (ADR-010); Desktop und Handy | source-integrations, scout-ui-engineer | P2-02 | DONE – gespeicherte Seiten (PR #4), URL + Text auf Desktop und Handy (PR #24, gemergt; ADR-038) |
| P2-05b | P1 | **mobile.de – gespeicherte Such- und Anzeigenseiten einlesen** (ohne Abruf, ADR-010/022): Parser `quellen/mobilede`, privat/gewerblich, Kategorie als Art, Auslandsorte vorsichtig, nur Wohnmobil-/Wohnwagen-Seiten | source-integrations | P2-05 | 6 echte Seiten: 65 Inserate feldgenau; Datenschutz (keine Telefonnummern, Händlernamen, Tracking); Kleinanzeigen unverändert | DONE (PR #6, gemergt) |
| P2-05c | P3 | Plausibilität der Fahrzeugart (z. B. Länge/Gewicht je Art; QA P2-05b: „Ford Nugget“ als Alkoven) als Hinweis | acquisition-analyst | P2-05b | Test mit erfundenen Grenzfällen; nur Hinweis, keine Sperre | ZURÜCKGESTELLT (18.10.2026) – gehört zur Bewertung, mit Phase 5 aufnehmen |
| P2-05d | P2 | Rechner-Vergleichsbasis: Anbieter unbekannt (`gewerblich` NULL) nicht wie privat werten (`rechner.py`, Vergleich) | acquisition-analyst | P2-05b | Test: NULL-Angebote getrennt bzw. ausgeschlossen; Entscheidung dokumentiert | ZURÜCKGESTELLT (18.10.2026) – mit P3-05 (Privat/Händler-Klassifizierung) bzw. Phase 5 aufnehmen |
| T1 | P1 | **Team-Übersicht Kern/API** (ADR-023): Reservierung „Ich übernehme“, Kontakt durch wen, Ablauf, Inhaber erzwingt/weist zu, Dubletten, Zähler, `wer=meine/frei`, CSV-Spalten | scout-data-engineer | P1-03 | atomar über Prozesse, 409 statt Doppelkontakt, Einzelplatz unverändert | DONE (PR #8, gemergt) |
| T2 | P1 | **Team-Übersicht Oberfläche** (Desktop + Handy): Badges mit Kürzel, Knöpfe Übernehmen/Abgeben/Zuweisen, Filter, Zählerleiste, Inserat erst nach 200 öffnen, 409-Meldung, mit P1-06 „gesendet ✓“ | scout-ui-engineer | T1, P1-06 | Klickablauf dokumentiert; ohne Nutzer keine Team-Elemente | DONE (PR #11, gemergt) |
| P2-06 | P1 | **E-Mail-Suchbenachrichtigungen**: `.eml`-Import, Parser zuerst Kleinanzeigen, dann AutoScout24, mobile.de; keine verlinkten Seiten nachladen | source-integrations | P2-02; anonymisierte Beispiel-E-Mails (F3) | REVIEW – `.eml` aus `import/email/` (CLI `import --mails`, Knopf in der Desktop-App, Schalter `eingaenge.email`, Standard aus); Parser nur mit nachgebildeten Mails geprüft, Abnahme mit echten Mails (F3) offen; Frist löscht alles vom Scout Abgelegte |
| P2-05e | P2 | Gemeinsames Feld-Modul für Text- und Mail-Eingang (URL-Prüfung, Preis, km, EZ, PLZ, Gesuch; QA A1) und ein Mechanismus „nur leere Felder“ für beide Kanäle | source-integrations | P2-05, P2-06 | Doppelte Regeln entfernt, Tests beider Eingänge grün | ZURÜCKGESTELLT (18.10.2026) – sinnvoll, sobald echte Mails (F3) die Regeln bestätigen; bis dahin bewusst doppelt |
| P2-07 | P2 | Optional: IMAP-Abruf eines eigenen Postfachs (Zugangsdaten aus Umgebungsvariablen) | source-integrations | P2-06, Betreiber-Postfach | ZURÜCKGESTELLT (18.10.2026) – optional, `.eml`-Ablage reicht; erst nach Abnahme mit echten Mails (F3) |
| P2-08 | P2 | mobile.de-API: Adapter-Stub (`zugriffsart = api`, `freigegeben = False`) + Anfrageschreiben an mobile.de vorbereiten | source-integrations, source-researcher | Vertrag | **BLOCKED** bis Zusage |
| P2-09 | P3 | Stubs/Anfragen AutoScout24, Caraworld, Quoka; Volumenprüfung regionaler Portale | source-researcher | – | ZURÜCKGESTELLT (18.10.2026) – Anfragen erst nach Betreiberentscheidung F4 (Händlerregistrierung/API-Zugang) |
| P2-10 | P2 | Datenqualität je Quelle messen (Anteil Preis/EZ/km/PLZ/Anbieterart) | source-integrations | P2-03 | ZURÜCKGESTELLT (18.10.2026) – Messfunktion für Mails vorhanden (`datenqualitaet`); Auswertung je Quelle erst mit echten Daten bzw. mit P3-08 |

## Phase B (3.0) – Verkäuferportal

Freigegeben vom Betreiber am 15.10.2026 („mache Phase B das Verkäuferportal“); Entscheidungen siehe ADR-025.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| B1 | P1 | **Datenmodell v5**: `verkaeufer`, `verkaufsanfragen`, `anfrage_fotos`, `anfrage_verlauf` (Sicherung vor Migration, additiv) | Orchestrator | P1-04b | Migration Altbestand v1/v2/v4 → v5 ohne Verlust, je Schritt genau einmal (auch parallel) | REVIEW |
| B2 | P1 | **Erfassungsassistent `/verkaufen`**: Fahrzeug, Zustand/Mängel, Fotos, Preis (freiwillig), Kontakt, Einwilligung; Referenz; grobe Spanne nur bei sicherer Datenlage | Orchestrator | B1 | Vollständige Anfrage ohne manuelle Datenbankarbeit; nie Max-EK/Angebot an den Verkäufer | REVIEW |
| B3 | P1 | **Team-Ansicht `/anfragen`**: Liste mit Bewertung, Detail mit Fotos, Kontakt, Status, Bearbeiter, Notiz, Verlauf | Orchestrator | B1 | Statuswechsel nachvollziehbar (Verlauf); nur angemeldet | REVIEW |
| B4 | P2 | Öffentlicher Betrieb: Hosting/HTTPS, Spam-Schutz, Status-Link, Datenschutzerklärung, Widerruf/Löschung | – | B1–B3, Sicherheitsprüfung | Betreiberfreigabe + Rechtsprüfung | TODO (Freigabe nötig) |

## Phase C (3.0) – Händlerportal (eigene Standorte)

Freigegeben vom Betreiber am 16.10.2026 („Phase C“); Entscheidungen siehe ADR-026.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| C1 | P1 | **Schema v6**: Standorte, Standort je Nutzer, Weitergabe/Freigabe, Interesse | Orchestrator | B1 | Altbestand v1/v2/v4/v5 → v6 ohne Verlust (bestehende Spalten unverändert) | REVIEW |
| C2 | P1 | **Rolle `haendler` + Positivliste**, Standortprüfung, Verwaltung `/standorte` + CLI | Orchestrator | C1 | Ungeprüfte/gesperrte Standorte sehen nichts; Händler erreichen nichts außer `/haendler` | REVIEW |
| C3 | P1 | **`/haendler`**: anonymisierte Fahrzeuge mit Preisvorstellung, Fotos, Interesse; Freigabe in `/anfragen` | Orchestrator | C2 | Keine Kontaktdaten/Max-EK; nur zugestimmt + freigegeben + offen | REVIEW |

## Phase D (3.0) – Demo-Auktionssystem

Auftrag des Betreibers am 16.10.2026 („Phase D fertigstellen“); Entscheidungen siehe ADR-027.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| D1 | P1 | **Schema v7**: Auktionen, Gebote, hash-verkettetes Protokoll (nur anfügbar) | Orchestrator | C1 | Altbestand v6 → v7 mit Sicherung, ohne Änderung bestehender Daten | REVIEW |
| D2 | P1 | **Zustandsmaschine + atomares Gebot** (Schritt, Wiederholungs-ID, Verlängerung, Abschluss beim Zugriff) | Orchestrator | D1 | Gleichzeitige Gebote (Prozesse) → genau ein gültiges Höchstgebot | REVIEW |
| D3 | P1 | **Oberfläche**: Bieten in `/haendler`, Starten/Entscheiden/Prüfen in `/anfragen`, CLI `auktion` | Orchestrator | D2 | Bieter sehen keinen Mindestpreis und keine anderen Standorte; Zuschlag nur durch Inhaber | REVIEW |

## Phase E (3.0) – Deal Intelligence

Auftrag des Betreibers am 16.10.2026 („Phase E“); Entscheidungen siehe ADR-028.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| E1 | P1 | **Kalkulation zum Betrag**: Szenarien aus der Marktspanne, Max-EK inkl. Provision, Korridor, Risiko, Annahmen | Orchestrator | D2 | Rein, ohne Datenbank; Auszug rechnet wie die ganze Datenbank | REVIEW |
| E2 | P1 | **Nachrechenbar**: eingefrorene Eingabe (Stichtag, Parameter, Vergleichsauszug), Schema v8, Prüfung + CLI | Orchestrator | E1 | Gespeicherte Kalkulation unabhängig von späterer Config/Datenlage; Manipulation erkannt | REVIEW |
| E3 | P1 | **Am Gebotsfeld**: Standorte live zum Betrag (Transport ab Standort), Team in `/anfragen`, Gebot speichert Kalkulation | Orchestrator | E2 | Jedes angenommene Gebot hat genau eine Kalkulation | REVIEW |

## Phase F (3.0) – Besichtigung und Abwicklung

Auftrag des Betreibers am 16.10.2026 („Phase F“); Entscheidungen siehe ADR-029.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| F1 | P1 | **Handy-Besichtigung für Verkaufsanfragen** (Grundlage aus Bewertung/Zuschlag, Rechte über Bearbeiter) | Orchestrator | B1, D2 | Inserate unverändert; Anfrage-Besichtigung nur durch Inhaber/Bearbeiter | REVIEW |
| F2 | P1 | **Ankaufsvorgang** (Schema v9): Vertrag (Muster + Bestätigung + Scan), Übergabe/Zahlung, Kosten, Verkauf, Storno | Orchestrator | F1, E2 | Weg vom Gebot zum Ankauf lückenlos mit Belegen; Verlauf/Kosten nur anfügbar | REVIEW |
| F3 | P1 | **Ergebnisvergleich** Plan (eingefrorene Kalkulation) gegen Ist, Übersicht | Orchestrator | F2 | Nur Anzeige; Gewinn mit derselben Formel wie der Rechner, gerundet | REVIEW |

## Phase G (3.0) – Skalierung (Voraussetzungen, Echtzeit, Mandanten)

Auftrag des Betreibers am 16.10.2026 („Phase G“); Entscheidungen siehe ADR-030. Reihenfolge: G0 → G1 → G2, je eigener PR.

| ID | Prio | Arbeitspaket | Agent | Abhängig | Akzeptanz | Status |
|---|---|---|---|---|---|---|
| G0 | P1 | **Voraussetzungen**: Härtung nach Sicherheitsprüfung, Datenrechte + Widerruf, API-Rahmen, Pilot-Checkliste | Orchestrator | E3 | Befunde H1–H3, M4, M8–M10 behoben und getestet; keine Quelle aktiv | REVIEW |
| G0b | P1 | Audit-Protokoll (Schema v10), Leerlauf der Sitzung, Rechte je Ankaufsschritt, Dokumente als Download (ADR-031) | Orchestrator | Phase F | Personendaten-Zugriffe nachvollziehbar, ohne Inhalte; Migration v9→v10 ohne Verlust | REVIEW |
| G1 | P1 | **Echtzeit per SSE** (Auktion, Team, Anfragen, Ankäufe) + **Nutzungszähler** (ADR-032) | Orchestrator | Phase F | Änderungen < 1 s sichtbar, keine Inhalte im Ereignis, Rückfall auf Abfragen | REVIEW |
| G2 | P1 | **Mandantenfähigkeit**: je Firma eigene Datenbank, Hostname wählt den Mandanten (ADR-033) | Orchestrator | G0, G1 | Keine Daten, Zugänge, Ereignisse oder Zähler übergreifend sichtbar; Einzelbetrieb unverändert | REVIEW |

## Phase 3 – Datenbank und Marktbeobachtung

**Abnahme:** identische Inserate lassen sich ohne Datenverlust erneut importieren; Preis- und Fahrzeughistorie bleiben
erhalten (Re-Import-Test).

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P3-01 | P1 | Migration auf **Version 11**: `fahrzeuge` + `inserate.fahrzeug_id`, je Inserat ein Fahrzeug, Trigger für neue Inserate; Ankaufsstatus bleibt am Inserat, keine View (ADR-039, Betreiber 18.10.2026) | scout-data-engineer | REVIEW |
| P3-02a | P1 | Fahrzeugidentität – Grundlage: Schema v12 (Entscheidungen, Zuordnungen), Vergleich mit Stufe und Gründen, Vorschläge nur lesend (API, CLI), ohne fachliche Wirkung (ADR-040) | scout-data-engineer | DONE (PR #28, gemergt) |
| P3-02b | P1 | Dubletten bestätigen/ablehnen/aufheben (Rechte laut ADR-040), Wirkung auf Team-Sperre und Bewertung, Oberfläche Desktop (Handy nur Anzeige) | scout-data-engineer, scout-ui-engineer | REVIEW |
| P3-02c | P3 | Index `fahrzeug_zuordnungen(entscheidung_id)` bei der nächsten Schemaänderung; Audit-Objekt mit Entscheidungs-ID (QA P3-02b N1/N3) | scout-data-engineer | TODO |
| P3-03 | P1 | Vollständiger Preisverlauf, `beobachtungen` mit Kanal und Zeitpunkt; **Re-Import-Test** (identische Inserate erneut importieren → kein Datensatz doppelt, Historie vollständig) | scout-data-engineer | TODO |
| P3-04 | P2 | Verfügbarkeit (`aktiv`/`reserviert`/`offline`/`verkauft`/`unbekannt`) + `zuletzt_bestaetigt` | scout-data-engineer | TODO |
| P3-05 | P2 | Privat/Händler-Klassifizierung mit Herkunft der Einstufung | scout-data-engineer | TODO |
| P3-06 | P1 | `kontakte` als Ereignisse (vorbereitet/bestätigt, Kanal, Nutzer) | scout-data-engineer | TODO |
| P3-07 | P2 | Indizes nach `EXPLAIN QUERY PLAN`, Vorfilter für Vergleichsauswahl (R12) | scout-data-engineer | TODO |
| P3-08 | P2 | Markierungen für unvollständige/widersprüchliche Angaben, Datenqualitätswert je Fahrzeug | scout-data-engineer | TODO |

## Phase 4 – Deutschlandweite Suchstrategie

**Abnahme:** Suchprofile sind reproduzierbar, ihre Ergebnisse dedupliziert und ihre Datenabdeckung messbar.

| ID | Prio | Paket | Agent | Status |
|---|---|---|---|---|
| P4-01 | P1 | Suchprofile in der Datenbank, verwaltbar in der App (Art, Marke, Modell, Preis, EZ, km) – solange keine freigegebene Pull-Quelle existiert, als **Filter über eingegangene Daten** plus **Abdeckungscheckliste** der vom Nutzer angelegten Suchaufträge je Plattform | source-integrations, scout-ui-engineer | TODO |
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
| P5-07 | P1 | Deal-Score 0–100 mit benannten Komponenten; Speicherung in `bewertungen` mit `modell_version` (braucht Migration auf Version 6, scout-data-engineer) | acquisition-analyst | TODO |

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
| Zeit Sichtung → Import | `erstmals_gesehen` − Einstellzeitpunkt laut Quelle (sofern geliefert) bzw. E-Mail-Zeitstempel | `beobachtungen` | Phase 3 |
| Vollständig beschriebene Fahrzeuge | Anteil mit Preis, EZ, km, PLZ, Art, Anbieterart | `fahrzeuge`, `inserate` | Phase 3 |
| Mittlere Marktwertunsicherheit | Median der relativen Spannenbreite (`spanne_bis − spanne_von`) / Marktwert | `bewertungen` | Phase 5 |
| Priorisierte Ankaufsangebote | Fahrzeuge mit Deal-Score ≥ Schwelle, verfügbar, privat | `bewertungen` | Phase 5 |
| Kontaktierte Verkäufer | **bestätigte** Kontakte (ADR-012) | `kontakte` | Phase 1 (UI) / 3 |
| Tatsächliche Ankäufe | manuell eingetragen (Besichtigung „gekauft“ mit Endpreis) | `besichtigungen` | heute |

---

## Offene Entscheidungen des Betreibers

| Nr. | Frage | betrifft |
|---|---|---|
| F1 | Soll es für Kleinanzeigen überhaupt eine lokale Ausnahme „auf eigene Verantwortung“ geben? Das erfordert, dass Sie Regel 12 in `CLAUDE.md` selbst ändern. Ohne Änderung wird der Abruf mit P1-01a abgeschaltet (Regeln 11/12 verlangen das bereits). | P1-01a/b |
| F2 | entfällt: ehrlicher User-Agent ist nach Regel 11 Pflicht | – |
| F3 | Postfach für Suchbenachrichtigungen: `.eml`-Upload oder IMAP? Anonymisierte Beispiel-E-Mails bereitstellen? | P2-06/07 |
| F4 | Bei mobile.de/AutoScout24 als Händler registriert? Anfrage für API-Zugang stellen? | P2-08/09 |
| F5 | Größe/Ort der produktiven Datenbank; vorhandene Sicherungen; Ziel und Aufbewahrung der Backups? | P1-02 |
| F6 | Altdaten `gewerblich = 0`: als privat übernehmen (Suchen filtern auf privat) oder „unbekannt“? | P2-02/P3-05 |
| F7 | Alte „kontaktiert“-Einträge als bestätigte Kontakte übernehmen? | P1-06/P3-06 |
| F8 | Läuft `lauf.bat` per Aufgabenplanung parallel zur App? | P1-04 |
| F9 | Nur Python 3.13 unterstützen oder auch 3.12? | P1-10 |
| F10 | Aufbewahrungsfristen für Verkäuferdaten, Fotos, Unterschriften (DSGVO); juristische Prüfung von Protokoll und E-Mail-Auswertung | P1-14 |
| F11 | Rollenrechte: Was dürfen Mitarbeiter (Status „gekauft“, Suchläufe starten, Besichtigungen anderer sehen/zuweisen)? | P1-15 |
| F12 | Dürfen eng gekoppelte Pakete desselben Agenten (z. B. P1-02 + P1-03) in einem PR gebündelt werden? Wie schnell können Sie PRs prüfen und mergen? | Durchgangsplanung |
| F13 | Sollen Deny-Regeln in `.claude/settings.json` den Prüfagenten technisch am Schreiben hindern (z. B. `git commit`/`git push`)? Das ändert Berechtigungen und bleibt Ihnen vorbehalten. | ADR-018 |
| F14 | ~~Fahrzeugart **unbekannt**: Wohnwagen ohne Art-Wort werden wie Wohnmobile gerechnet.~~ **Entschieden 14.10.2026:** Ampel höchstens „gelb“, Brief ohne Betrag (umgesetzt in PR #4). Baureihen-Erkennung für Wohnwagen bleibt eigenes Paket. | ADR-021 |
