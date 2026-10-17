# Architektur Wohnmobil-Scout 2.0

Stand: 13.10.2026, Phase 0 · Code-Stand: Integrationszweig `claude/gifted-heisenberg-d1cjlr` (Commit 3f75f67).
Grundlage: Bestandsaufnahme des Agenten `scout-architect` (nur lesend, mit Belegen), vom Orchestrator im Code
stichprobenartig nachgeprüft (R1, R2, R3, R5, R14). Entscheidungen: `docs/DECISIONS.md`. Phasen und Backlog:
`docs/ROADMAP.md`. Diese Datei ersetzt `docs/ARCHITEKTUR.md` (Phase-1-Plan vom Oktober 2026).

---

## 1. Leitlinien

1. **Abhängigkeiten zeigen nach innen.** Quellen kennen weder Datenbank noch Bewertung; sie liefern `Inserat`-Objekte.
   Der `Importer` ist die einzige Brücke zwischen Quellen und Datenbank. Die Bewertung ist rein (ohne DB, ohne Netz).
2. **Zulässigkeit vor Abdeckung.** Eine Quelle läuft nur, wenn ihr Zugang in `docs/SOURCES.md` als OK belegt ist.
3. **Kein Datenverlust.** Migrationen nur mit Backup, Version und Test gegen Altbestände. Historie wird angehängt,
   nicht überschrieben.
4. **Inkrementell statt Rewrite.** Jede Änderung ist einzeln testbar und rückgängig zu machen; eine Fassade hält
   Oberfläche und Bewertung während des Umbaus lauffähig.
5. **Einfach und lokal.** Standardbibliothek, SQLite, Jinja2, Vanilla-JS; ein Prozess auf dem Büro-PC, Fernzugriff
   über Tailscale. Kein Framework, keine Microservices ohne nachgewiesenen Bedarf.

---

## 2. Ist-Zustand: Module

| Modul | Aufgabe | Kopplung / Auffälligkeit |
|---|---|---|
| `scout.py` | CLI: `app`, `lauf`, `report`, `rechne`, `nutzer`, `status` | hängt an allen Schichten; Passwörter nur per Abfrage bzw. `SCOUT_NEUES_PASSWORT` (P1-09), `config.local.yaml` überlagert `config.yaml` |
| `wmscout/quellen/basis.py` | `Quelle`, `Inserat`, `Suchauftrag`, `Suchseite`, Fehlerklassen | gut; `als_datensatz` nutzt die Anzeigen-ID ohne Quelle als Schlüssel |
| `wmscout/quellen/kleinanzeigen/` | Adapter + HTML-Parser | `freigegeben = False`, läuft aber standardmäßig (R1) |
| `wmscout/quellen/mobilede/` (seit P2-05b) | nur Parser für gespeicherte Such-/Anzeigenseiten (kein Abruf, kein Adapter in `QUELLEN`); IDs `md-<Nummer>` | Selektoren über `data-testid`; Telefon/seller-IDs im RSC-Strom werden nicht gelesen |
| `wmscout/eingang/seiten.py` (seit P2-05) | Plattform- und Seitentyp-Erkennung gespeicherter Seiten (Kleinanzeigen, mobile.de), Art-Herkunft | Erkennung nur über den Seitenkopf |
| `wmscout/eingang/text.py` (seit P2-05) | `TextEingang`: Adresse + eingefügter Text → `Lesung` (Plattform/ID nur aus der Adresse, Bereinigung von Kontaktdaten, Gesuche und fremde Adressen nie speichern); API `POST /api/import/text` | rein, ohne Datenbank und Netz; die Adresse wird nie abgerufen (ADR-010) |
| `wmscout/eingang/basis.py` (seit P2-00) | Schnittstelle der Push-Eingänge: `Rohdaten`, `Lesung`, `Eingang.lese`; `SeitenEingang` (ADR-035) | rein, ohne Datenbank und Netz; geschrieben wird nur über `Importer.importiere` |
| `wmscout/netz.py` | höflicher HTTP-Abruf, Abbruch bei 403/429/Captcha | User-Agent aus Konfiguration ist ein Chrome-Imitat (R2) |
| `wmscout/importer.py` | Suchlauf, Detailseiten, Layout-Diagnose | Freigabe wird nur protokolliert, nicht erzwungen; ein `try` um alle Suchen (R8) |
| `wmscout/datenbank.py` | SQLite, Tabelle `anzeigen`, Status, Nachfassen | `ALTER TABLE` bei jedem Öffnen, ohne Version/Backup (R3); ohne WAL/`busy_timeout` (R7) |
| `wmscout/normalisierung/` | Marke/Serie/Modell/Art, PLZ-Entfernung | reine Funktionen |
| `wmscout/bewertung/rechner.py` | Marktwert, Max-EK, Erstangebot (§25a) | rein; Cache-Schlüssel ohne Quelle |
| `wmscout/bewertung/auswertung.py` | Dubletten, Vergleichsbasis, Nachfassen | liest direkt aus der DB (R15) |
| `wmscout/bewertung/anschreiben.py`, `ausgabe.py` | Texte, CSV, HTML | importieren `STATUS` aus `datenbank` |
| `wmscout/bewertung/besichtigung.py` + `web/static/besichtigung.js` | Mängelabzug (Python verbindlich, JS offline) | Paritätstest |
| `wmscout/team.py` | Nutzer, Sitzungen, Besichtigungen, Fotos | teilt die DB-Verbindung |
| `wmscout/bearbeitung.py` (T1) | reine Team-Regeln: Kürzel, Zustand (frei/reserviert/kontaktiert/ohne Zuordnung/verwaist), Rechte, `TeamSicht` | ohne DB; Schreibzugriffe in `Datenbank` (`uebernimm`, `gib_ab`, `weise_zu`, Team-Pfad von `setze_status`), API `/api/team`, `/api/bearbeitung/<id>/…` |
| `wmscout/web/api.py` | Routen, Zugriffsschutz, Statusübergänge | Fachlogik in der HTTP-Schicht; globaler Lock (R6) |
| `wmscout/app.py` | Server, Suchlauf-Thread, Auto-Suche (alle 3 h) | eigene DB-Verbindung je Thread |
| `wmscout/benachrichtigung.py` | E-Mail, WhatsApp-Link, WhatsApp Cloud API | Geheimnisse korrekt über Umgebungsvariablen |

## 3. Ist-Zustand: Datenfluss

```
config.yaml (suchen) → Suchauftrag → KleinanzeigenQuelle.suche → HoeflicherAbruf → Parser → Inserat
   → Datenbank.speichere_treffer (ein Commit je Treffer) → Importer.details → speichere_details
   → bewerte_alle: Normalisierung → finde_duplikate → vergleichsbasis/fuer_rechner (Import-Art) → bewerte_anzeige
     (Rechner.bewerte, bei unbekannter Art je Kandidat) → sperrgrund/hinweise → Anschreiben
   → Ausgabe (CSV/HTML/Texte) · E-Mail · WhatsApp
   → App: Kontext.zeilen (30-s-Cache) → Desktop „/“ bzw. Handy „/m“
   → Kontakt: Text kopieren + Inserat öffnen + POST /api/status „kontaktiert“   ← zu früh (R5)
   → Besichtigung: planen → durchführen (Mängelabzug) → Abschluss setzt Ankaufsstatus
```

## 4. Ist-Zustand: Datenbank

* **`anzeigen`** – Schlüssel `id` = Anzeigen-ID der Plattform (ohne Quelle). Spalten u. a. `preis`, `preis_vorher`,
  `vb`, `km`, `ez_jahr`, `marke`, `art`, `gewerblich`, `details_json`, `detail_geladen`, `erstmals_gesehen`,
  `zuletzt_gesehen`, `status`, `notiz`, `kontaktiert_am`, `anschreiben_text`, `nachgefasst_am`, `nachfass_anzahl`,
  `angebot_betrag`, `status_am`, `quelle`. Einziger Index `idx_zuletzt`. Keine Fremdschlüssel, keine `schema_version`.
* **Team** (`team.py`): `nutzer`, `sitzungen` (Token nur als SHA-256), `besichtigungen` (JSON-Felder, `version`),
  `fotos` (Dateien unter `daten/fotos/`).
* **Status** mischt Ankaufsablauf und Verfügbarkeit („gelöscht“, nur bei Inseraten ohne Details erkannt, nie
  zurückgesetzt). **Verfügbarkeit** sonst nur geschätzt (`zuletzt_gesehen` ≤ 21 Tage). **Preis**: aktueller Preis +
  letzte Senkung; Erhöhungen überschreiben spurlos. **Dubletten** bei jeder Auswertung neu berechnet (Marke, EZ, PLZ,
  km ± 3.000, Serie), nicht gespeichert; ohne km/PLZ nie erkannt. **Privat/Händler**: `gewerblich`, „unbekannt“ wird
  als privat gespeichert.

---

## 5. Risiken (priorisiert)

| ID | Risiko | Beleg | Schwere | Maßnahme | Paket |
|---|---|---|---|---|---|
| R1 | Nicht freigegebene Quelle (Kleinanzeigen-HTML) läuft standardmäßig, per Auto-Suche alle 3 h | `config.yaml:10-20,196`; `importer.py:39-40` nur Warnung | **KRITISCH** (Regel 11/12) | Importer verweigert Suche **und** Detailabruf für nicht freigegebene Quellen; Auto-Suche standardmäßig aus | P1-01a |
| R3 | Keine Backups, keine Schema-Version; `ALTER TABLE` bei jedem Öffnen | vorher `datenbank.py` (ALTER TABLE beim Öffnen); **behoben** durch `wmscout/sicherung.py` und `wmscout/migrationen.py` (P1-02/P1-03) | **KRITISCH** (blockiert alle Migrationen) | `scout.py sichern`/`wiederherstellen` über SQLite-Backup-API inkl. Fotos, `integrity_check`, `schema_version` | P1-02, P1-03 |
| R2 | User-Agent gibt sich als Chrome aus | `config.yaml:32`, `netz.py` | HOCH | ehrlicher User-Agent mit Projektname (Regel 11: keine gefälschten Browser-Fingerabdrücke) | P1-01a |
| R4 | Schlüssel ohne Quelle | `migrationen.py:27`; `datenbank.py:36`; `wmscout/quellen/basis.py:103`; `rechner.py:176` | HOCH | `UNIQUE(quelle, anzeigen_id)` **vor** der zweiten Quelle | P2-02 |
| R5 | „kontaktiert“ schon beim Kopieren; Nachfassen macht aus „abgesagt“ wieder „kontaktiert“ | `report.html:406`, `mobil.js:483`, `datenbank.py:117` | HOCH | Statuswert „vorbereitet“, Knopf „gesendet bestätigen“; später Kontakte als Ereignisse | P1-06, P3-06 |
| R6 | Globaler Lock umfasst Bewertung, Antwortversand und WhatsApp-HTTP (Timeout 20 s) | `api.py:57,495-497` | HOCH | Lock nur um DB-Zugriffe, Verbindung je Thread; Versand außerhalb; WhatsApp asynchron | P1-05 |
| R7 | ~~Mehrere SQLite-Verbindungen ohne WAL (nur Python-Standard-Wartezeit 5 s)~~ WAL + 10 s seit P1-04a, Laufsperre seit P1-04; alle HTTP-Threads teilen eine Verbindung; keine Laufsperre (App + `lauf.bat` parallel) | `app.py:59,102`; `scout.py:198`; `api.py:54`; `datenbank.py:30` | HOCH | WAL, `busy_timeout`, Laufsperre (Lease in `suchlaeufe`, Schema v3) | P1-04 |
| R8 | Keine Fehlerisolation je Quelle/Suchauftrag | `importer.py:108-125` | HOCH | `try` je Auftrag und Quelle, Status je Quelle | P2-03 |
| R9 | Verfügbarkeit nur geschätzt; Inserate nach 21 Tagen in der App nicht mehr bearbeitbar | `datenbank.py:77`; `api.py:74-78` | MITTEL | Spalte `verfuegbarkeit` + `zuletzt_bestaetigt` | P3-04 |
| R10 | Preisverlauf geht verloren | `datenbank.py:51-54` | MITTEL | `preis_historie` (nur anhängen) | P2-02 (Start), P3-03 |
| R11 | Dubletten flüchtig/lückenhaft; Ankaufsstatus am Inserat | `auswertung.py:24,74-83` | MITTEL | `fahrzeuge` mit Fingerabdruck, Zusammenführung nur als Vorschlag | P3-02 |
| R12 | Bewertung O(aktive × alle) im Lock; Vergleichsbasis enthält gelöschte/alte Inserate | `auswertung.py:59`; `rechner.py:200,217` | MITTEL | SQL-Vorfilter, Indizes, gespeicherte `bewertungen` | P3-07, P5 |
| R13 | „gewerblich unbekannt“ wird als privat behandelt | `datenbank.py:40` | MITTEL | `anbieter_typ` privat/haendler/unbekannt | P2-02, P3-05 |
| R14 | Besichtigung: letzter Schreiber gewinnt, Konflikt wird nur gemeldet | `api.py:434-437` | MITTEL | `UPDATE … WHERE version=?`, sonst 409 | P1-07 |
| R15 | Bewertung hängt an der Datenbank | `auswertung.py:8,65`; `anschreiben.py:9` | MITTEL | `STATUS` in Domänenmodul; `bewerte_alle` bekommt Listen | P1-08 |
| R16 | Firmen-/Mail-Daten in versionierter `config.yaml`; Passwort als CLI-Argument | `config.yaml:175-181,218-224`; `scout.py:189` | NIEDRIG | `config.local.yaml` (ignoriert) als Überlagerung | P1-09 |
| R17 | Login-Bremse nur 1 s, Sitzungen 30 Tage | `api.py:352,500`; `team.py:21` | NIEDRIG | Sperre nach Fehlversuchen | P1-13 |
| R18 | Python 3.10–3.12 zugelassen, CI testet nur 3.13 | `pyproject.toml:6`, `scout.py:21` | NIEDRIG | festlegen oder mittesten | P1-10 |
| R19 | Detailabruf ohne Freigabeprüfung; Inserate ohne `quelle` fallen auf Kleinanzeigen zurück – auch künftig manuell importierte Inserate würden nachgeladen (verletzt ADR-010) | `importer.py:78-100` | HOCH | Freigabeprüfung auch in `details()`; nur pull-fähige, freigegebene Plattformen | P1-01a |
| R20 | ~~Plattform und Eingangskanal nicht getrennt~~ – **behoben (P2-00, ADR-035):** ein Schreibweg `Importer.importiere(lesung, kanal)`, kanonische Plattform-IDs | `importer.py`, `eingang/basis.py`, `domaene.py` | – | – | P2-00 |

Weitere Befunde der QA-Bestandsaufnahme: `docs/TEST-REPORT.md`. R19/R20 stammen aus der Architekturprüfung der
Planung (P0-07). Belege (Datei:Zeile) beziehen sich auf Commit 3f75f67 und werden von `tests/test_projekt.py` auf
Existenz der Zeilen geprüft.

---

## 6. Zielarchitektur

```
                       ┌──────────────────────────── wmscout ────────────────────────────┐
 Suchprofile (DB) ───▶ │ quellen/      Pull-Quellen (suche/details): mobile_de_api, …;   │
                       │               kleinanzeigen (BLOCKED, standardmäßig aus)        │
 Benachrichtigungs-    │ eingang/      Push-Kanäle: Eingang.lese(Rohdaten) → Lesung       │
 E-Mails (.eml/IMAP) ▶ │               email_kleinanzeigen, email_autoscout, manuell     │
 Nutzer-Import ──────▶ │ netz.py       Abruf nur für freigegebene Plattformen            │
                       │ importer.py   importiere(lesung, kanal): einziger Schreibweg;    │
                       │               Lauf je Quelle isoliert, Laufsperre, Kennzahlen    │
                       │ normalisierung/  Fahrzeug, Geo, Datenqualitäts-Markierungen      │
                       │ datenbank/    Schema, Migrationen, Backup, Fassade (Repository) │
                       │ domaene/      Status, Kontaktzustände (ohne I/O)                │
                       │ bewertung/    Rechner, Deal-Score, Mängel – rein                │
                       │ web/ app.py   Routen, Zugriffsschutz; Lock nur um DB-Zugriffe   │
                       │ benachrichtigung.py  E-Mail, WhatsApp (asynchron)               │
                       └─────────────────────────────────────────────────────────────────┘
```

## 7. Ziel-Datenmodell

Tabellennamen deutsch (ADR-007). Inserats-ID ist keine Fahrzeugidentität. **Plattform ≠ Eingangskanal** (ADR-016):
`inserate` ist eindeutig über `UNIQUE(plattform, anzeigen_id)` (z. B. `kleinanzeigen`/123); auf welchem Weg ein
Inserat ankam (Suche, API, E-Mail, manuell), steht in `beobachtungen.kanal`. So ergibt dasselbe Inserat aus E-Mail und
manuellem Import nur einen Datensatz. In Tabellen und Texten unten steht „quelle“ für die Plattform.

| Entität | Tabelle | Kernfelder | Herkunft |
|---|---|---|---|
| sources | `quellen` | kennung PK, name, zugriffsart, freigegeben, aktiv, intervall_min, zuletzt_ok, fehler_in_folge, gesperrt_bis | Adapter-Metadaten + Konfiguration |
| search_profiles | `suchprofile` | id, name, quelle →, parameter_json, plz, radius_km, intervall_min, aktiv | `config.yaml → suchen` |
| crawl_runs | `suchlaeufe` | id, quelle, suchprofil_id, start, ende, art, seiten, treffer, neu, fehler_art, fehler_text, parser_ok | neu |
| vehicles | `fahrzeuge` | id, fingerabdruck, fin NULL, marke, serie, modell, art, ez_jahr, km_letzter, plz, ankauf_status, status_am, notiz, zusammengefuehrt_in | Normalisierung, Status aus `anzeigen` |
| listings | `inserate` | id INTEGER PK, quelle, anzeigen_id, UNIQUE(quelle, anzeigen_id), fahrzeug_id →, oeffentliche_id, url, titel, Texte, preis, vb, anbieter_typ, verfuegbarkeit, zuletzt_bestaetigt, erstmals/zuletzt_gesehen, detail_geladen, details_json, qualitaet_json | `anzeigen` |
| price_history | `preis_historie` | inserat_id, zeitpunkt, preis, vb, suchlauf_id, herkunft | `preis_vorher` + `preis` |
| observations | `beobachtungen` | inserat_id, suchlauf_id, zeitpunkt, kanal (suche/api/email/manuell/detail), preis, inhalt_hash | neu |
| valuations | `bewertungen` | inserat_id, zeitpunkt, modell_version, marktwert, spanne_von, spanne_bis, max_ek, erstangebot, sicherheit, n_vergleich, deal_score, komponenten_json | heute nur flüchtig |
| contacts | `kontakte` | fahrzeug_id, inserat_id, nutzer_id, art (anschreiben/nachfassen/antwort), kanal, text, betrag, vorbereitet_am, bestaetigt_am | `kontaktiert_am`, `anschreiben_text` |

Grobschätzung `beobachtungen` (nicht gemessen): ~5.000 Zeilen/Tag bei heutiger Suchbreite, ~1,8 Mio./Jahr – mit
Indizes für SQLite tragbar; alternativ nur Änderungen speichern (Entscheidung in Phase 3).

## 8. Migrationsstrategie

Jeder Schritt: **Backup vorher** (SQLite-Backup-API, `PRAGMA integrity_check`), eine Transaktion, idempotent,
Eintrag in `schema_version`, Test gegen Fixtures jeder Vorversion. Rückweg: Backup zurückspielen; alte Tabellen werden
umbenannt, nicht gelöscht.

**Schemaversionen (eine Zählung für alles):** 1 = ZIP-Stand · 2 = heute (ALTER-TABLE-Ergänzungen) · 3 = Phase 1
(`schema_version`, minimale `suchlaeufe` mit Lease) · 4 = Phase 2 · 5 = Phase 3 · 6 = `bewertungen` (Phase 5).
**Schutzregeln:** Ist die Schemaversion der Datenbank höher als die dem Code bekannte, bricht der Start mit
verständlicher Meldung ab (kein Schreiben mit altem Code). Ohne erfolgreiches Backup keine Migration. Wiederherstellung
nur nach ausdrücklicher Bestätigung (P1-02) und, dank Laufsperre (P1-04) nicht während eines Laufs.

**Stand 15.10.2026 (Plan nachgeführt):** Tatsächlich umgesetzt sind v3 (`schema_version`) und v4 (PR #7: `quellen`,
`inserate`, `beobachtungen`, `preis_historie` parallel zu `anzeigen`). WAL und Laufsperre kamen ohne Schemaänderung
(P1-04a/P1-04, Dateisperre statt `suchlaeufe`). `anzeigen` und v4 werden seit ADR-024 in denselben Transaktionen
geschrieben. **v5** (Phase B, ADR-025) enthält das Verkäuferportal (`verkaeufer`, `verkaufsanfragen`, `anfrage_fotos`,
`anfrage_verlauf`), **v6** (Phase C, ADR-026) das Händlerportal (`standorte`, `anfrage_interesse`, `nutzer.standort_id`,
Weitergabe/Freigabe an `verkaufsanfragen`), **v7** (Phase D, ADR-027) die Demo-Auktionen (`auktionen`, `gebote`,
`auktion_protokoll`), **v8** (Phase E, ADR-028) gespeicherte Kalkulationen (`kalkulationen`), **v9** (Phase F, ADR-029)
Ankaufsvorgänge (`ankaeufe`, `ankauf_kosten`, `ankauf_verlauf`, `ankauf_dokumente`, `besichtigungen.anfrage_id`). Die nächste freie
Version für Fahrzeugidentitäten ist damit **v10**; die Zeilen unten sind
der ursprüngliche Plan.

| Version | Phase | Inhalt |
|---|---|---|
| v3 | 1 | `schema_version` anlegen, Altbestände als v1/v2 erkennen; minimale `suchlaeufe` (id, quelle, start, ende, laeuft_bis, ergebnis) als Laufsperre; WAL, `busy_timeout`; Indizes nur nach `EXPLAIN QUERY PLAN` |
| v4 | 2 | `quellen`, `suchprofile`, `suchlaeufe` vollständig; `inserate` aus `anzeigen` (`plattform = COALESCE(quelle, 'kleinanzeigen')`), `beobachtungen` mit `kanal`; `oeffentliche_id` = alte ID bei Kleinanzeigen, sonst `<quelle>_<id>` (passt zu Routen `\w+` und `besichtigungen.anzeige_id`); `preis_historie` mit Herkunft „migration“ |
| v5 | 3 | je Inserat ein Fahrzeug; Ankaufsstatus → `fahrzeuge`; „gelöscht“ → `verfuegbarkeit = offline`; `gewerblich` → `anbieter_typ` (Altdaten-Regel: Betreiberfrage); `kontakte` aus `anschreiben_text`; `besichtigungen.fahrzeug_id`; Dubletten nur als bestätigte Vorschläge |

**Kompatibilitätsschicht:** Die Klasse `Datenbank` bleibt Fassade mit den bisherigen Methoden und Zeilen-Dicts.
Die alte Tabelle wird zu `anzeigen_alt_v2` umbenannt; eine lesende View `anzeigen` mit den bisherigen Spalten hält
`bewerte_alle`, Desktop-App, Handy-App und CSV unverändert lauffähig. Schreibzugriffe nur über die Fassade.

## 9. Nebenläufigkeit

WAL-Modus, `busy_timeout`, eine Verbindung je Thread; Lock im Webserver nur um Datenbankzugriffe; Antworten und
externe Aufrufe (WhatsApp, E-Mail) außerhalb des Locks; Laufsperre über `suchlaeufe`, damit App-Auto-Suche und
`lauf.bat` nicht parallel laufen; Bewertungsstand nach jedem Lauf speichern statt bei jeder Anfrage neu rechnen.

## 10. Teststrategie

* `pytest`, komplett offline; Fake-Abruf, temporäre Datenbanken, nachgebaute Seiten und E-Mails.
* Vertragstest für jede registrierte Quelle; Isolationstest (eine fehlerhafte Quelle stoppt die anderen nicht).
* Migrationstests gegen v1/v2-Fixtures mit Zählungen vorher/nachher; Backup-/Restore-Test.
* Re-Import-Test: identische Inserate erneut importieren → keine Dubletten, Historie vollständig.
* Rechner: von Hand nachgerechnete Beispiele, Monotonie, Grenzfälle; Paritätstest Python/JS für den Mängelabzug.
* HTTP-Tests für Zugriffsschutz; Klicktests (Playwright) für Desktop und Handy bei Oberflächenänderungen.
* CI: Ubuntu + Windows (Python 3.13), echter Lauf von `installieren.bat`.
