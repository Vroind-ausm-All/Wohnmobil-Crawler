# Arbeitsprotokoll (WORKLOG)

Neueste Einträge oben. Vorlage und Regeln: Skill `scout-cycle` (`.claude/skills/scout-cycle/SKILL.md`).
Nur tatsächlich Erledigtes und tatsächlich ausgeführte Tests. Nicht Ausgeführtes heißt „nicht geprüft“, ein fehlender
Wert „–“.

---

## Phase B – Verkäuferportal v1, intern (15.10.2026) · Status: REVIEW

- **Anlass:** Betreiber: „mache Phase B das Verkäuferportal“; Entscheidungen per Rückfrage: erst intern, grobe Spanne,
  Preisvorstellung freiwillig (ADR-025). Umgesetzt vom Orchestrator ohne Subagenten.
- **Geändert/neu:** `wmscout/migrationen.py` (Schema v5), `wmscout/verkauf.py` (neu: Prüfung, Rechner-Sicht, Spanne,
  Speicher), `wmscout/team.py` (`bild_endung` gemeinsam), `wmscout/web/api.py` (Seiten `/verkaufen`, `/anfragen`,
  JSON-API, Fotos), `vorlagen/verkaufen.html`, `vorlagen/anfragen.html` (neu), Links in Desktop- und Handy-App,
  `config.yaml` (`verkaeuferportal`), Tests `tests/test_verkauf.py` (neu, 28); Versionstests auf v5 angepasst
  (`test_migration.py`, `test_ereignisse.py`; Paralleltest prüft jetzt allgemein „jeder Schritt genau einmal“).
- **Tests:** `pytest -q` 753 bestanden, `ruff` grün; Gegenprobe an 4 Schutzstellen (Spannen-Sicherheit, Fotopfad,
  Einwilligung nur als echtes `true`, kein Max-EK in der Antwort) – die Fotopfad-Probe fiel zuerst durch, Test ergänzt,
  danach alle 4 erkannt. Browser-Klicktest (Chromium, 400×860): Pflichtfeld-Meldungen, Assistent mit 2 Fotos, Referenz,
  Spanne, Team-Ansicht mit Fotos/Übernehmen/Status/Verlauf, 0 JS-Fehler (Skript nicht im Repository).
- **Nicht geprüft:** öffentlicher Betrieb (bewusst nicht gebaut), Safari/iOS, Windows-CI (folgt im PR).
- **Offen (Betreiber):** Einwilligungstext und Datenschutzhinweis rechtlich prüfen; Widerruf/Löschung; Freigabe B4.

 + P1-06 „gesendet ✓“ (15.10.2026) · Status: REVIEW

- **Anlass:** Betreiber „ja, mach T2“. Grundlage: nicht committeter Entwurf des am Wochenlimit abgebrochenen T2-Agenten
  (Status `vorbereitet`, Desktop-HTML/CSS, Server-Anpassungen; `.bat`-Änderungen waren nur Zeilenenden und wurden verworfen).
  Fertiggestellt vom Orchestrator ohne Subagenten.
- **Ergänzt:** Desktop-JavaScript für Badges, Zähler, Filter „Wer“, Übernehmen/Abgeben/Zuweisen/Erzwingen, Team-Stand
  jede Minute; Team-Code nur bei aktivem Team im HTML (statischer Bericht bleibt ohne Team-Begriffe); Handy-App: Badges,
  Filter „Wer“, Team-Knöpfe, „gesendet ✓“, Anschreiben setzt nur noch `vorbereitet` und öffnet die Anzeige erst nach 200
  (vorher setzte die Handy-App sofort „kontaktiert“); `sw.js`-Version erhöht; Filter „Anschreiben bereit“ (Desktop und
  `/api/fahrzeuge`) behält „Text kopiert“.
- **Fehler unterwegs:** Browser-Klicktest fand, dass „Text kopiert“-Karten aus dem Standardfilter verschwanden („gesendet ✓“
  unerreichbar) – behoben. Ein bestehender Test (`test_fehler_mitten_in_der_transaktion…`) setzte das alte Verhalten voraus
  (Nachfassen = Kontakt); angepasst, prüft den Rollback weiterhin echt.
- **Tests:** `pytest -q` 725 bestanden, `ruff` grün; neu `tests/test_team_oberflaeche.py` (8, inkl. `node --check` der
  ausgelieferten Skripte). Browser-Klicktests (Chromium, Playwright; Desktop und Handy 390×844) mit drei Nutzern:
  Übernehmen, Sperre für Kollegen, Filter „Frei“, Anschreiben → „gesendet ✓“ → kontaktiert, Badges beim Kollegen,
  keine JavaScript-Fehler. Die Klickskripte liegen nicht im Repository (nicht Teil der CI).
- **Nicht geprüft:** Safari/iOS (Zwischenablage nach Serverantwort), Windows-CI (folgt im PR).

 `anzeigen` ↔ v4 gleich halten (15.10.2026) · Status: REVIEW

- **Anlass:** 3.0-Analyse, P0 „Datenmodell vereinheitlichen“; Betreiber: „mach weiter“. Ohne Subagenten umgesetzt.
- **Geänderte Dateien:** `wmscout/datenbank.py` (`spiegle_inserat`, `verknuepfe_inserat`, `gleiche_v4_ab`,
  `schreibe_anzeige`, `speichere_treffer` mit `kanal` unter `BEGIN IMMEDIATE`), `wmscout/ereignis_speicher.py`
  (Transaktion über `Datenbank.transaktion`, Zeile in `anzeigen`), `wmscout/importer.py` (Seitenimport = Kanal `manuell`),
  Tests `tests/test_v4_abgleich.py` (13), Doku ADR-024, ROADMAP, ARCHITECTURE (Versionsplan nachgeführt), EREIGNIS-ENGINE.
- **Tests:** `pytest -q`: 717 bestanden (Linux, inkl. PR-#9-Stand); `ruff check .` grün. Gegenprobe: Spiegeln aus (6
  Fehlschläge), Ereignis → App aus (5), Kollisionsschutz aus (1), Abgleich beim Öffnen aus (2), Änderungserkennung aus (2).
- **Fehler unterwegs:** Abgleich lief im Konstruktor vor `_tiefe` – von den neuen Tests gefunden, behoben.
- **Nicht geprüft:** Windows-CI (folgt im PR); Laufzeit des Abgleichs mit sehr großem Altbestand.

: WAL und Sperr-Wartezeit (14.10.2026) · Status: REVIEW

- **Anlass:** Betreiber-Analyse „Wohnmobil-Scout 3.0“, Vorschlag erster PR `claude/phase1-db-parallelzugriff`
  (Ereigniseingang, Browser-App und Hintergrundläufe nebeneinander). Ohne Subagenten und ohne Warteschleifen umgesetzt.
- **Geänderte Dateien:** `wmscout/datenbank.py` (`_setze_journal`, `wal_aktiv`, `STANDARD_WARTEZEIT` 10 s),
  `wmscout/sicherung.py` (Sicherung im Modus DELETE, Checkpoint-Prüfung vor Wiederherstellung), `wmscout/app.py`,
  `scout.py`, `config.yaml` (`ausgabe.wal`), Tests `tests/test_parallelzugriff.py` (neu), `tests/prozess_helfer.py`,
  `tests/test_sicherung.py` (Dateivergleich ignoriert die SQLite-Arbeitsdateien `-wal`/`-shm`).
- **Tests:** `pytest -q`: 684 bestehende + 12 neue grün; `ruff check .` grün. Gegenproben (je Änderung einmal
  zurückgebaut): ohne WAL 5 Fehlschläge, ohne DELETE-Sicherung 1, ohne Checkpoint-Prüfung 1 – alle drei erkannt.
- **Windows-CI (PR #9, 1. Lauf):** 695 von 696 grün; `test_m2_reste_der_alten_datenbank_…` schrieb eine erfundene `-shm`
  neben die WAL-Datenbank, die Windows sperrt. Korrigiert: der Test stellt den Altfall ausdrücklich im Modus DELETE nach.
- **Nicht geprüft:** Datenbank auf Netzlaufwerk; Laufsperre (P1-04, offen).
- **Nachtrag P1-04 Laufsperre (15.10.2026, gleicher PR):** `wmscout/laufsperre.py` (Dateisperre des Betriebssystems),
  eingebunden in `Suchlauf.starte` (App/Auto-Suche), `scout.py lauf` und `sicherung.wiederherstellen`. Tests
  `tests/test_laufsperre.py` (8, u. a. echter zweiter Prozess, Kill gibt frei, echter Aufruf `scout.py lauf`).
  Gegenprobe: jede der vier Einbindungen einmal entfernt – jeweils 1 Test schlägt an. Erster Testentwurf hing (getöteter
  Hilfsprozess blockierte ein Event); korrigiert, der Kill-Test nutzt kein Event mehr.
- **Offen:** Verbindung `anzeigen` ↔ v4-Tabellen (eigener PR); Phasen A–G der 3.0-Analyse brauchen je eigene Freigabe.

## Phase 2 – Team-Übersicht (14.10.2026)

### T1 – Team-Übersicht Kern und API · Status: REVIEW

- **Anlass:** Betreiberwunsch „auf Masse gehen und trotzdem den Überblick behalten auch unter den Kollegen“.
  Plan: `scout-architect` (Freigabe mit Auflagen); Betreiber-Standards: Reservierung 2 Tage, nur Inhaber erzwingt/
  weist zu, „gesendet ✓“ zählt (P1-06, mit T2).
- **Verantwortliche Agenten:** `scout-architect` (Plan), `scout-data-engineer` (Umsetzung, Korrekturrunde 1),
  `qa-security-reviewer` (Runde 1), Orchestrator (Doku, ADR-023).
- **Zweig/Commits:** `claude/phase2-team-kern`: 33defb1 (Umsetzung), e91b81d (Merge mobile.de), Korrekturrunde 1.
- **Geänderte Dateien:** `wmscout/bearbeitung.py` (neu), `wmscout/datenbank.py`, `wmscout/team.py`,
  `wmscout/web/api.py`, `wmscout/bewertung/auswertung.py` (`dubletten_ids` ohne Bewertung), `wmscout/ausgabe.py`,
  `wmscout/app.py`, `scout.py` (`status --nutzer`), `wmscout/web/static/sw.js`, `config.yaml` (`team`), Tests
  `tests/test_team_bearbeitung.py`, `tests/test_team_korrektur.py`, `tests/prozess_helfer.py`.
- **Implementierte Funktionen:** siehe ADR-023; Fehlerantworten mit `grund` (`csrf`, `recht`, `zugriff`,
  `konflikt`, `belegt`) für T2; gesperrte Datenbank → 503 statt 500, keine offene Transaktion.
- **Tests:** `pytest -q -p no:cacheprovider`, `ruff check .`, `node --check sw.js`; Nebenläufigkeit mit zwei
  Datenbank-Objekten und zwei Prozessen; QA-Skripte (Wettlauf 4 Prozesse, Nebenwege, Sperre, Dubletten mit mobile.de,
  Regression ohne Nutzer, Performance); Mutationsproben.
- **Testergebnis (Orchestrator):** **658 passed**, ruff grün. Agent: QA-Wettlauf 43 Runden 0 Abweichungen;
  `/api/status` mit Team bei 3 000 Inseraten 16,1 s → 0,2 s (10 Aufrufe). Korrektur: Hier stand zunächst
  „29 Mutationen erkannt“; die gespeicherte Ergebnisdatei belegte nur 24 von 29 (QA-Runde 2, Q-M2). Belegter Stand
  nach Korrekturrunde 2: **62 von 63** erkannt (Datei `/tmp/claude-0/team3/mutation_ergebnis.txt`, volle Suite je
  Mutation); nicht erkannt nur eine gleichwertige Mutante (Reihenfolge innerhalb einer Transaktion).
- **Review-Ergebnis:** QA-Runde 1 (e91b81d): FREIGABE MIT AUFLAGEN – Atomarität, Rechte, CSRF, Einzelplatz ok;
  offen H1 (Besichtigung umgeht Reservierung), H2 (Verhandlung/Besichtigung ohne Übernahme), H3 (Doku), M1–M5,
  N1–N7 → Korrekturrunde 1 bearbeitet (M4/N5 → T2). Nachprüfung steht aus.
- **QA-Runde 2 (f16943d): FREIGABE MIT AUFLAGEN** – H1/H2/M1–M3/M5 bestätigt behoben; neu Q-H1: über eine
  Besichtigung ohne Zuständigen konnte sich ein Mitarbeiter selbst eintragen und ein fremdes Fahrzeug auf „gekauft“
  setzen. Korrekturrunde 2: Zuständigkeit setzen nur Inhaber oder Bearbeiter; Besichtigungen fremd gehaltener
  Inserate ohne Zuständigen sind für Mitarbeiter nur lesbar; Erzwingen bei Verhandlung/Besichtigung übernimmt
  wirklich und wird nur bei echter Änderung protokolliert; Besichtigung anlegen/abschließen in EINER Transaktion;
  fehlende Tests ergänzt. **678 passed.**
- **Entscheidungen (Orchestrator):** Der zuständige Besichtiger darf beim Abschluss den Status setzen (sonst könnte
  er seine Besichtigung nicht abschließen); eintragen dürfen ihn nur Inhaber oder Bearbeiter des Fahrzeugs. Erzwingen/Zuweisen scheitert an einer
  kontaktierten Dublette eines anderen (409, erst dort zuweisen).
- **Bekannte Risiken:** Bisherige Oberflächen werten 409 nicht aus (M4) → Team-Betrieb erst mit T2; bei gesperrter
  DB warten Anfragen bis 5 s; Zeitumstellung (naive Ortszeit) bis 1 h Abweichung beim Ablauf; Windows/echte Browser
  nicht geprüft.
- **Nächster sinnvoller Schritt:** QA-Nachprüfung, PR; danach T2 (Oberfläche) mit P1-06.


## Phase 2 (vorgezogen) – mobile.de-Seiten einlesen (14.10.2026)

### P2-05b – mobile.de: gespeicherte Such- und Anzeigenseiten einlesen · Status: REVIEW

- **Anlass:** Betreiberwunsch „auf Masse gehen“, Beispielseiten von mobile.de geliefert (3 Such-, 3 Anzeigenseiten;
  nicht im Repo).
- **Verantwortliche Agenten:** `source-integrations` (Umsetzung, Korrekturrunde 1), `qa-security-reviewer` (Runde 1),
  Orchestrator (Doku, ADR-022).
- **Zweig/Commits:** `claude/phase2-mobilede` (Worktree): 45ae636 (Umsetzung), 2ce4649 (Merge Stand PR #4),
  Korrekturrunde 1 (dieser Commit).
- **Geänderte Dateien (Auswahl):** `wmscout/quellen/mobilede/` (neu), `wmscout/eingang/seiten.py`,
  `wmscout/importer.py`, `wmscout/normalisierung/geo.py` (Ausland), `wmscout/bewertung/auswertung.py`/`anschreiben.py`
  (Ausland-Hinweis, Anbieter unbekannt), `wmscout/datenbank.py` (`gewerblich` NULL = unbekannt), `wmscout/web/api.py`
  (Bindestrich-IDs), `vorlagen/report.html`, `wmscout/web/static/mobil.js` (Hinweise je Plattform), `README.md`,
  Tests `tests/test_mobilede.py`, `tests/test_ausland.py`, Fixtures `tests/seiten/mobilede/` (frei erfunden).
- **Implementierte Funktionen:** mobile.de-Seiten im selben `import/`-Ordner; IDs `md-<Nummer>`, `quelle=mobile.de`;
  privat/gewerblich/unbekannt; Kategorie als bestätigte Art (ADR-022); Pkw-Seiten werden abgewiesen; Auslandsorte
  ohne Entfernung, Ampel höchstens gelb, Brief ohne Betrag; keine Telefonnummern, seller-IDs, Händlernamen, Tracking.
- **Tests:** `pytest -q -p no:cacheprovider`, `ruff check .`, `node --check`, Mutationsproben, Lauf mit 6 echten Seiten.
- **Testergebnis (Orchestrator):** **570 passed**, ruff grün, `node --check` ok. Agent: 24 Mutanten erkannt;
  6 echte Seiten: 65 Inserate (24 privat, 41 gewerblich), 55 Arten bestätigt, 2 Auslandsorte mit Hinweis.
- **Review-Ergebnis:** QA-Runde 1 (2ce4649): ABLEHNUNG ohne KRITISCH – Parser 0 Abweichungen auf 65 Inseraten,
  Kleinanzeigen bitgleich, keine Datenlecks; aber H1 (Handy-App 404 bei `md-`-IDs), H2 (Fixtures mit echten
  Merkmalskombinationen – liegen in 45ae636/2ce4649 auf GitHub; Squash-Merge empfohlen), H3 (Auslandsorte →
  falsche/fehlende Entfernung), M1–M5, N1–N6 → in Korrekturrunde 1 bearbeitet; QA-Runde 2 steht aus.
- **Bekannte Risiken:** „Webseite, nur HTML“, Händler-Anzeigenseite und andere Kategorien nicht mit echten Seiten
  geprüft; Fehlklassifikation durch Anbieter; Rechner wertet unbekannten Anbieter in der Vergleichsbasis wie privat;
  Verbraucher-AGB zum dauerhaften Speichern nicht zitiert (M5).
- **QA-Runde 2 (77b773b): FREIGABE MIT AUFLAGEN** – H1–H3, M1–M3, M5, N3 bestätigt behoben; Kleinanzeigen bitgleich;
  32/32 Mutanten erkannt. Auflage Q2-H1 (Nachfassen nennt Betrag, obwohl der Brief keinen nannte; Desktop/Handy
  speicherten das rechnerische Erstangebot) → in PR #4 behoben (`betrag_im_brief`, 6ef9a49) und hier um „Ausland“
  ergänzt; Q2-M2 (ARCHITECTURE/QUELLEN/Backlog P2-05c/P2-05d), Q2-N1 (`DEU-`/`GER-`/`BRD-` = Inland), Q2-N3
  (`ort_kurz`) erledigt. Q2-M1 war eine Fehldiagnose (Tabelle hat 7 Spalten; zu kurz sind ältere Zeilen). Q2-M3:
  alte Fixtures in 45ae636/2ce4649 → **Squash-Merge Pflicht**. Q2-M4 (Pkw-Campingbusse wie „Van/Kleinbus“ werden
  abgewiesen) → Betreiberfrage.
- **Nächster sinnvoller Schritt:** PR gegen den Integrationszweig nach dem Merge von PR #4.

## Phase 2 (vorgezogen) – Gespeicherte Seiten einlesen, wieder aufgenommen (14.10.2026)

### P2-05 (Teil) – Hinweise statt Sperre, Anrede mit Verkäufername · Status: REVIEW

- **Zusammenführung mit PR #5 (14.10.2026):** Der Merge des Integrationszweigs in diesen Zweig (d31c2dc) ließ in
  `scout.py` beide Fassungen von `main()` stehen (Datenbank-Start ohne Sicherungsordner, `import` fehlte im zweiten
  Aufruf) → 8 CLI-Tests rot. Behoben; außerdem nutzt ein Import-Test statt `:memory:` eine Temp-Datei (der
  Migrationsrahmen öffnet eigene Verbindungen). Danach **464 passed**, ruff grün.
- **Nachfassen ohne Betrag (QA P2-05b, Befund Q2-H1, gilt schon für F14):** Nannte der Erstbrief keinen Betrag, nannte
  das Nachfassen trotzdem „Mein Angebot über … steht weiterhin“, und Desktop/Handy speicherten beim Kontakt das
  rechnerische Erstangebot als `angebot_betrag`. Jetzt eine Regel `betrag_im_brief` für Brief, Nachfassen, Zeile
  (`brief_betrag`), API und Handy; Report beschriftet „rechnerisch, nicht im Anschreiben“. Zwei Tests, beide Mutationen
  erkannt; **465 passed**.
- **F14 umgesetzt (Betreiberentscheidung 14.10.2026, Orchestrator):** Bei unbekannter Fahrzeugart Ampel höchstens
  „gelb“ (`bewerte_anzeige`) und Brief ohne Betrag (`kontext`, `mit_angebot`); Hinweistext nennt beides. Zwei neue
  Tests, beide Änderungen per Mutationsprobe in einer Kopie erkannt. PR #4 während der Änderung als Entwurf markiert.

- **QA-Runde 7 (Stand be0afd2): FREIGABE MIT AUFLAGEN** (für den PR, nicht für den Merge). 374 passed; 18 echte Seiten
  identisch zur Agentenanalyse; nicht bestätigt ohne Hinweis 0; künstliche Cache-id in keiner Ausgabe; Rechner
  unverändert; Mutationen 24 von 28 erkannt.
  - **A1 / H7-1 (HOCH, Betreibervorbehalt = F14):** Wohnwagen ohne Art-Wort werden als „Sonstige“ gerechnet: 10 der
    Top 20 der echten Daten sind Wohnwagen, Briefangebote z. B. 25.300 € statt 15.200 € (als Wohnwagen gerechnet).
    **Kein Merge und keine produktive Nutzung des Seitenimports, bevor der Betreiber F14 entschieden hat.**
  - A2: M7-1 (Schutztest enthielt die Namen ROT13-lesbar → gesalzene SHA-256-Werte, jetzt inkl. docs/) und M7-2
    (README: Mail-Anhang und Handy-Offline-Speicher als Speicherorte) behoben; N7-3 (Beleg ROADMAP) festgeschrieben.
  - Backlog: M7-3 (Laufzeit je Kandidat), N7-1 („KaufeWohnmobile“), N7-2 (Modell aus Bindestrich-Ketten), N7-4
    (Besichtigungsbasis friert vorsichtige Art ohne Hinweis ein), N7-5 (Formulierungen); fehlende Tests:
    Dublettenfilter in `vergleichsbasis`, `rechne --marktwert`, unbekannte Art + manueller Marktwert.

- **Anlass:** Betreiberentscheidung 14.10.2026: „möglichst jedes Wohnmobil anschreiben“, Brief mit weniger
  Modellname und mit dem Profilnamen (ADR-021). Damit ist der BLOCKED-Grund (K-A als Sperr-Risiko) entfallen.
- **Verantwortliche Agenten:** `source-integrations` (Import, Parser, Ausgaben), `acquisition-analyst` (Brief,
  Bewertungs-Vorstufe, eigener Worktree, danach zusammengeführt), `qa-security-reviewer` (Runde 5), Orchestrator
  (`scout.py rechne`, Doku).
- **Zweig/Commits:** `claude/phase2-seitenimport`: 12cef17/a912c83/bcdb68b (Zwischenstände „ungeprüft“), 5174eef
  (Korrektur nach QA-Runde 5), 9479b6b + fc086f3 (Anschreiben, Merge), 7f96a8e (Doku), Korrektur nach QA-Runde 6.
- **Geänderte Dateien (Auswahl):**
  - `wmscout/bewertung/anschreiben.py` (`hinweise`, `verkaeufer_name`, `anrede_name`, `art_bestaetigt`)
  - `wmscout/bewertung/auswertung.py` (`fuer_rechner`, Feld `hinweise`)
  - `vorlagen/anschreiben.txt`, `vorlagen/nachfassen.txt`
  - `wmscout/eingang/seiten.py` (`haupttabelle_ids`, strenger Kopf), `wmscout/importer.py`, `wmscout/datenbank.py`
    (`detail_art`, GLOB)
  - `wmscout/quellen/kleinanzeigen/parser.py` (Profilname), `wmscout/normalisierung/person.py` (neu)
  - `wmscout/ausgabe.py`, `wmscout/benachrichtigung.py` (Hinweise in CSV, Datei, Mail)
  - `wmscout/web/api.py`, `wmscout/web/static/mobil.js`, `vorlagen/report.html` (gelbe Hinweiszeile)
  - `scout.py` (`rechne` nutzt `fuer_rechner`), `README.md`
  - Tests: `tests/test_anschreiben.py` (neu), `tests/test_seitenimport.py`, `tests/test_kleinanzeigen_echt.py`,
    `tests/seiten/kleinanzeigen/suchseite_andere_orte.html` (neu, anonymisiert)
- **Implementierte Funktionen:**
  - Nicht bestätigte Fahrzeugart sperrt nicht mehr; Hinweis „Fahrzeugart nicht bestätigt/unbekannt (gerechnet …) –
    bitte prüfen“ in allen Ausgaben.
  - K-A behoben: Der Art-Filter bestätigt nur Treffer aus `#srchrslt-adtable`. Detailseite hat Vorrang (M-W).
  - Brief: „Hallo <Name>,“ aus dem Profil (Hr → Herr, Kleinschreibung korrigiert), Modell nur einmal in der
    Einleitung, danach Marke bzw. „Ihr Wohnmobil“; bei nicht bestätigter Art keine Art im Text.
  - Bei unbekannter Art rechnet die Vorstufe vorsichtig: niedrigster Max-EK über „ohne Art“ und die Art-Wörter im
    Text, Spanne über alle Kandidaten, Sicherheit „niedrig“; Rechner unverändert. `scout.py rechne` nutzt dieselbe
    Logik (`vergleichsbasis`, `bewerte_anzeige`).
  - Brief markenneutral „Ihr <Art> von <Marke>“ (statt „Ihr Hobby …“).
  - Datenschutz: nur der Profilname, nur beim Seitenimport; Zeichen-Whitelist, keine Ziffern/Adressen/Füllwörter;
    keine Telefonnummern/Profil-IDs. Echte Namen und Orte aus Fixtures, Tests und Vorlagen entfernt; ein Test
    (`test_keine_echten_verkaeufernamen_im_repository`) verhindert ihre Rückkehr.
- **Tests:** `.venv/bin/python -m pytest -q -p no:cacheprovider`, `.venv/bin/python -m ruff check .`,
  `node --check wmscout/web/static/mobil.js`, Mutationsproben der Agenten in Kopien
- **Testergebnis (Orchestrator):** Stand 7f96a8e `326 passed`; nach Korrektur Runde 6 (bcdb68b) **`374 passed`**,
  ruff „All checks passed!“. Mutationsproben der Agenten in Kopien: alle erkannt (Runde 6: 17 von 17).
- **Review-Ergebnis:** QA-Runde 5 (Stand a912c83): ABLEHNUNG ohne KRITISCH; K-A, H-T, M-W, N-1..N-3 bestätigt
  behoben. Offen waren H1 (echte Profilnamen in Tests), H2 (Name gespeichert, aber ungenutzt), H3 (unbekannte Art mit
  Titel-Art gerechnet), M1–M4, N1–N5 → bearbeitet. QA-Runde 6 (Stand 7f96a8e): ABLEHNUNG ohne KRITISCH – H1-R (die
  echten Namen kamen über den parallelen Anschreiben-Worktree zurück: der Orchestrator hatte sie dem Agenten als
  Beispiel genannt), H6-1 (unbekannte Art als „Sonstige“: echter Wohnwagen mit Max-EK 54.600 € statt 18.900 € auf
  Rang 3), M6-1..M6-3, N6-1..N6-5 → in Korrekturrunde 2 bearbeitet. QA-Runde 7: steht aus.
- **Bekannte Risiken:**
  - Die echten Profilnamen aus a912c83 stehen in der Historie des Arbeitszweigs (Bereinigung nur mit Freigabe des
    Betreibers; Squash-Merge hält sie aus dem Integrationszweig).
  - F14: Wohnwagen ohne Art-Wort im Text werden wie Wohnmobile gerechnet (zu hoher Max-EK, teils „grün“).
  - Max-EK 0 ergibt Ampel „grau“ (bestehendes Rechnerverhalten).
  - N4: früher falsch bestätigte Inserate werden nicht automatisch herabgestuft.
  - Kein Browser-Klicktest der Hinweiszeile; Windows nicht geprüft.
- **Nächster sinnvoller Schritt:** QA-Runde 7 (letzte erlaubte Runde nach Wiederaufnahme), dann PR gegen den
  Integrationszweig; Betreiberentscheidung F14.

## Phase 2 (vorgezogen) – Gespeicherte Seiten einlesen (13.10.2026)

### P2-05 (Teil) – Gespeicherte Kleinanzeigen-Seiten einlesen · Status: BLOCKED (aufgehoben 14.10.2026, siehe oben)

- **Phase:** 2, vorgezogen. Der Betreiber hat das Paket am 13.10.2026 freigegeben, nachdem der Kleinanzeigen-Webabruf
  0 Treffer lieferte (neues Seitenlayout).
- **Verantwortlicher Agent:**
  - `source-integrations`: Umsetzung; die erste Fassung lief als eingebauter Agent nach Definition, danach als
    Projekt-Agent.
  - `qa-security-reviewer`: vier Prüfungen.
- **Zweig/Commits:** `claude/phase2-seitenimport`: 796eda6 (Umsetzung), 8c212c2 (Runde 1), 981398e (echte Seiten),
  fd9c580 (Runde 2), 9b2396d (Runde 3). Die Zwischenstände 6df53c1/a83fe4f sind als „ungeprüft“ markiert.
  Kein PR, weil BLOCKED.
- **Geänderte Dateien:**
  - `wmscout/eingang/` (neu)
  - `wmscout/importer.py`
  - `wmscout/datenbank.py` (`ohne_details`-Filter, Import-Suchwerte; keine Schemaänderung)
  - `wmscout/quellen/kleinanzeigen/parser.py` (neues Layout, Detailliste, Anzeigen-ID)
  - `wmscout/quellen/kleinanzeigen/adapter.py`
  - `wmscout/normalisierung/fahrzeug.py` (Basismarken-Normalisierung, `arten_im_text`)
  - `wmscout/bewertung/anschreiben.py` (Sperrgrund Fahrzeugart)
  - `wmscout/web/api.py` (`POST /api/import`)
  - `vorlagen/report.html` (Knopf, Meldungen)
  - `scout.py` (`import`)
  - `config.yaml` (`import.ordner`)
  - `.gitignore`, `README.md`
  - Tests: `tests/test_seitenimport.py`, `tests/test_kleinanzeigen_echt.py`, `tests/seiten/kleinanzeigen/*.html`
    (anonymisiert, IDs/Orte verfremdet)
- **Implementierte Funktionen:**
  - Im Browser gespeicherte Such- und Detailseiten aus `import/` einlesen. Das geht per Knopf, per
    `scout.py import` und über die API.
  - Kein Netzabruf, auch später kein automatisches Nachladen von Detailseiten (ADR-010).
  - Dateien wandern nach `eingelesen/<Datum>/` bzw. `nicht_erkannt/`.
  - Grenzen: 25 Dateien bzw. 20 s je Klick, 20 MB je Datei.
  - Fahrzeugart nur aus Art-Filter oder Detailseite gilt als bestätigt und ist anschreibbar. Titel und Suchbegriff
    gelten als vorläufig und werden gesperrt (ADR-020).
- **Tests:**
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python -m ruff check .`
  - Klicktest (Chromium headless)
  - Lauf mit den 18 echten, vom Betreiber gespeicherten Seiten (Temp-DB, Netz gesperrt)
  - Mutationsproben (QA)
- **Testergebnis:**
  - `194 passed`, ruff „All checks passed!“.
  - Klicktest: Knopf, Meldung und Neuladen funktionieren, keine JS-Fehler (Stand 796eda6).
  - 18 echte Seiten: 16 Such- und 2 Detailseiten, 0 nicht erkannt, 352 neu, 42 bekannt.
  - Arten: bestätigt 2, vorläufig 186, unbekannt 164; bereit 0; „nicht bestätigt und bereit“ 0.
  - Reihenfolge vorwärts/rückwärts: 0 Abweichungen.
  - Windows: nicht geprüft (CI läuft beim Push; noch nicht ausgewertet).
- **Review-Ergebnis:** Vier QA-Prüfungen, alle ABLEHNUNG. Die Befunde der jeweils vorigen Runde waren jedes Mal behoben.
  1. K1 (Fahrzeugart ging verloren), H1, M1–M4 → behoben in Runde 1.
  2. K1-R (Stichwort der Suchseite galt als Fahrzeugart), K1-D, M6, M7 → behoben in Runde 2.
  3. K-T (Titel mit mehreren Arten) und R-O (Reihenfolge) → behoben in Runde 3 mit der Regel „nur bestätigte Art“.
  4. **K-A (KRITISCH, offen):** Der Art-Filter einer Suchseite würde auch die Anzeigen im Block „Weitere Ergebnisse
     in anderen Orten“ (`#srchrslt-adtable-altads`) bestätigen. Diese Anzeigen ignorieren Filter und Kategorie.
     Belegt mit einem echten Original und eingesetztem Filter: „Citroen Campster“ wäre als Teilintegrierter
     anschreibbar, mit einem Max-EK von 37.300 € statt 31.100 €.
  - Weitere offene Befunde: H-T (fehlender Test für die Garantie „Detailseite ohne Art bestätigt nicht“), M-W (zwei
    bestätigte Quellen widersprechen sich), N-1 bis N-3.
- **Bekannte Risiken:**
  - Nicht belegt ist, ob echte, mit Art-Filter gespeicherte Seiten `art_s:` in canonical/og:url tragen. Unter den
    18 Originalen ist keine Filterseite. Fehlt `art_s:`, ist nur über Detailseiten etwas anschreibbar.
  - Der Betreiber nutzt die Vorabversion bereits. Ältere Zweigstände konnten falsche Arten erzeugen; erneutes Einlesen
    mit dem aktuellen Stand sperrt sie (M-A).
- **Grund für BLOCKED:** Laut Skill `scout-cycle` sind höchstens 3 Korrekturrunden je Paket erlaubt; nach der dritten
  ist ein KRITISCH-Befund offen.
- **Nötige Entscheidung des Betreibers:**
  - (a) Eine 4. Runde ausnahmsweise erlauben, nur für K-A, H-T und M-W. Vorschlag: Der Filter bestätigt nur Anzeigen
    aus der Haupttabelle `#srchrslt-adtable`, und eine echte Filterseite wird geliefert.
  - (b) Übergangsweise nur Detailseiten als Bestätigung zulassen. Dann ist K-A ausgeschlossen, braucht aber ebenfalls
    eine kleine Runde.
  - (c) Den Stand ohne PR liegen lassen.
- **Nächster sinnvoller Schritt:** Entscheidung des Betreibers sowie eine mit Art-Filter gespeicherte Ergebnisseite als
  Testdatum.
## Phase 1 (vorgezogen) – Datensicherung und Migrationsrahmen (14.10.2026)

### P1-02 / P1-03 – Sicherung, Wiederherstellung, Migrationsrahmen · Status: DONE (PR #5 gemergt 14.10.2026)

- **Phase:** 1, vorgezogen als Voraussetzung für die Team-Übersicht (Tabelle `bearbeitung`, Schema-Version 3) und
  für jede weitere Schemaänderung (Regel 3).
- **Verantwortliche Agenten:** `scout-data-engineer` (Umsetzung, zwei Korrekturrunden), `qa-security-reviewer`
  (zwei Prüfungen), Orchestrator (Doku-Belege, Commits).
- **Zweig/Commits:** `claude/phase1-sicherung-migration` (Worktree): 1b104ad (Umsetzung), e8b1be1 (Runde 1),
  Korrekturrunde 2 (dieser Commit).
- **Geänderte Dateien:**
  - `wmscout/sicherung.py` (neu): `sichere`, `wiederherstellen` (mit `--bestaetigt`, `--ohne-fotos`), Aufbewahrung
  - `wmscout/migrationen.py` (neu): `schema_version`, Schritte 2 und 3, `migriere`, `pruefe_wiederherstellbar`
  - `wmscout/datenbank.py` (ruft `migriere` auf), `wmscout/team.py` (kein eigenes Schema mehr), `wmscout/app.py`
  - `scout.py` (`sichern`, `wiederherstellen`), `config.yaml` (Abschnitt `sicherung`), `README.md`
  - Tests: `tests/test_sicherung.py`, `tests/test_migration.py`
- **Implementierte Funktionen:**
  - Sicherung über die SQLite-Backup-API mit `integrity_check`, Fotos als ZIP; Aufbewahrung `behalten` aus der
    Konfiguration; eigene und gerade verwendete Sicherungen sind vor dem Aufräumen geschützt (auch bei Uhrsprung).
  - Wiederherstellung nur mit Bestätigung: Quelle nur lesend in eine Arbeitskopie, Prüfung (Integrität, Scout-DB,
    Version), Sperrprüfung vor und kurz vor dem Austausch, Vorher-Sicherung, atomarer Austausch, Fotos mit Rückweg.
  - Migrationen: Sicherung vorher (ohne Aufräumen), je Schritt eine Transaktion, idempotent, parallel startende
    Prozesse sicher (Reservierung der Sicherungsnummer, Neuprüfung), „DB neuer als Code“ bricht verständlich ab.
  - Windows-taugliche Datei-URIs (Laufwerk, UNC), CLI-Meldungen ohne Traceback, Typprüfung der Konfiguration.
- **Tests:** `pytest -q -p no:cacheprovider`, `ruff check .` (Python der Haupt-`.venv`), Mutationsläufe der Agenten
  und der QA in Kopien, QA-Reproduktionsskripte (Uhrsprung, Parallelprozesse, defektes ZIP, Sonderzeichen-Pfade)
- **Testergebnis (Orchestrator):** nach Korrekturrunde 2 `182 passed`; nach Ergänzung N-1 `182 passed`, ruff „All checks passed!“.
  Agent: 55 Mutanten, nach Nachträgen alle getötet (Volllauf nach den letzten Tests nicht wiederholt).
- **Review-Ergebnis:**
  1. QA-Runde 1 (1b104ad): ABLEHNUNG – K1 (älteste Sicherung zurückspielen → leere DB), H1, M1–M5, N1–N4.
  2. QA-Runde 2 (e8b1be1): FREIGABE MIT AUFLAGEN – alle Runde-1-Befunde behoben; neu Q-F1–Q-F10 (MITTEL/NIEDRIG).
  3. Korrekturrunde 2: Q-F1–Q-F10 und fehlende Mutantentests bearbeitet.
  4. QA-Runde 3 (001fe60): **FREIGABE** – alle Q-F behoben (eigene Nachstellung), 64 von 69 Mutanten getötet (alle 55
     des Agenten); 8 Prozesse gleichzeitig: 8 eindeutige, intakte Sicherungen. Offen: N-1 (MITTEL, Schutztest „Aufräumen
     löscht nie die DB“) → vom Orchestrator ergänzt, Mutant X1 jetzt erkannt; N-2..N-7 (NIEDRIG) → Backlog.
- **Bekannte Risiken:** Windows und Netzlaufwerke nicht real geprüft; Sperrprüfung erkennt nur aktive
  Schreibvorgänge (App vorher beenden; echte Laufsperre mit P1-04); Sicherungen enthalten personenbezogene Daten
  (Löschfristen mit P1-14a).
- **CI Windows (PR #5):** 7 Tests rot – offene SQLite-Verbindungen in Tests sperrten unter Windows die Datei, ein
  Testordner enthielt `?`. Behoben (Tests schließen Verbindungen; `_ersetze` wiederholt `os.replace` bei kurzzeitiger
  Sperre durch Virenscanner/Indexdienst, danach Meldung „in Benutzung“; zwei neue Tests). Lokal 184 passed.
- **Backlog aus QA-Runde 3:** N-2 verwaiste `-journal`-Begleitdateien von Arbeitskopien; N-3 Meldung bei
  Schreibschutz; N-4 Doppelfehler im Fotoschritt; N-5 Tests für `ordner: ""`, Foto-`.teil` im Fehlerpfad,
  ZIP_DEFLATED-Fehler, CLI-Hinweis `--ohne-fotos`; N-6 `\\?\unc\` in Kleinschreibung.
- **Nächster sinnvoller Schritt:** PR gegen `claude/gifted-heisenberg-d1cjlr`; danach Team-Übersicht (Tabelle
  `bearbeitung`, Schema-Version 3).

## Phase 0 – Bestandsaufnahme (13.10.2026)

Zweig `claude/phase0-agentensystem` (Basis `claude/gifted-heisenberg-d1cjlr`, Commit 3f75f67).
Commits: 185dc0b, 548c1fc, c31d668, aadfd67 und der Korrektur-Commit zu P0-07.

### Hinweis zur Agentennutzung

Claude Code lädt die Projekt-Agenten in `.claude/agents/` erst beim Start einer Sitzung. In der Sitzung, in der sie
angelegt wurden, ließen sie sich noch nicht aufrufen. Die Fehlermeldung lautete: „Agent type 'scout-architect' not found“.

Deshalb liefen zwei Aufträge über eingebaute Agenten, jeweils mit der Anweisung, die Agentendefinition zu lesen und
exakt danach zu handeln:
- die Architektur-Bestandsaufnahme (P0-03) über den eingebauten Nur-Lese-Agenten `Plan`,
- die Quellenrecherche (P0-04) über einen eingebauten Agenten mit Web-Recherche.

Nach einem Neustart der Sitzung waren die Projekt-Agenten geladen. Ab P0-05 liefen alle Aufträge über die echten
Projekt-Agenten.

### P0-07 – Unabhängige Prüfung der Planung · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `scout-architect` und `qa-security-reviewer` (Projekt-Agenten, parallel und unabhängig);
  Korrekturen durch den Orchestrator
- **Geänderte Dateien (Korrekturrunde 1 von höchstens 3):**
  - `docs/ARCHITECTURE.md`, `DECISIONS.md`, `ROADMAP.md`, `TEST-REPORT.md`, `WORKLOG.md`
  - `.claude/skills/scout-cycle/SKILL.md`, `.claude/loop.md`, `.claude/agents/*.md`
  - `tests/test_projekt.py`
- **Implementierte Änderungen:**
  - **Belege:** Falsche Datei:Zeile-Belege korrigiert:
    - R1: `importer.py:39-40`
    - R7: `app.py:59,102`, `scout.py:198`, `api.py:54`
    - R8: `importer.py:108-125`
    - R18: `pyproject.toml:6`
  - **Neue Risiken:**
    - R19: Detailabruf ohne Freigabeprüfung
    - R20: keine Push-Schnittstelle; Plattform und Eingangskanal sind vermischt
  - **Kleinanzeigen-Abschaltung:** P1-01 geteilt.
    - P1-01a schaltet ohne Abhängigkeit ab. Das ist nötig, weil Regel 12 die Abschaltung bereits verlangt.
    - P1-01b, die lokale Ausnahme, ist BLOCKED, bis der Betreiber Regel 12 selbst ändert.
    - F2 entfällt, weil ein ehrlicher User-Agent nach Regel 11 Pflicht ist.
  - **Phase 1:**
    - Abnahmekriterien vervollständigt.
    - Agenten neu zugeordnet:
      - P1-05 → `scout-data-engineer`
      - P1-11a → `source-integrations`
      - P1-11b → `scout-data-engineer`
      - P1-14 aufgeteilt in 14a (Daten/Logs) und 14b (Service Worker)
    - P1-06 ohne Schemawechsel und ohne Abhängigkeit von F7.
    - Plan für den ersten Durchgang mit exklusiven Dateien je Agent.
  - **Schemaversionen:** einheitliche Zählung 1–6 mit Schutzregeln. Die Laufsperre kommt als minimale Tabelle
    `suchlaeufe` in Version 3.
  - **Neue ADRs:**
    - ADR-016: Plattform ≠ Eingangskanal
    - ADR-017: Push-Eingang
    - ADR-018: QA mit `Bash`
    - Neues Paket P2-00
  - **Skill:** eigene Worktrees für parallele Pakete; eine Abhängigkeit gilt erst nach dem Merge als erfüllt; nur der
    Orchestrator pflegt die Planungsdokumente und committet; `loop.md` läuft nicht parallel zum Skill.
  - **Agenten:** Implementierungsagenten haben einen Abschnitt „Git“ bekommen (kein Commit, kein Push). Der Architekt
    erhält Diffs als Text.
  - **Testbericht:** Befundzahlen korrigiert (8 MITTEL, 7 NIEDRIG). R1 und R3 als KRITISCH geführt. Q1 nach der
    QA-Skala auf KRITISCH angehoben.
  - **`tests/test_projekt.py` erweitert:**
    - genaue Werkzeugmenge je Prüfagent und genaues Modell je Agent
    - kein zusätzlicher Frontmatter-Schlüssel (z. B. `permissionMode`)
    - Skill-Grenzen und die 10 Punkte von `loop.md`
    - neuer Test: Jeder `datei:zeile`-Beleg in ARCHITECTURE, TEST-REPORT, ROADMAP und DECISIONS zeigt auf eine
      existierende Zeile
- **Tests:**
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python -m ruff check .`
  - Mutationsprobe von `test_projekt.py` in einem separaten Worktree
- **Testergebnis:**
  - Mutationsprobe: Jede Mutation wird erkannt (jeweils „1 failed“):
    - alte ARCHITECTURE mit falschen Belegen
    - Architekt mit `Bash`
    - Architekt auf `haiku`
    - Skill-Grenze „5“ entfernt
    - `permissionMode` ergänzt
    - Punkt 9 aus `loop.md` entfernt
  - Gesamtsuite nach der Korrektur: `96 passed`; ruff „All checks passed!“
- **Review-Ergebnis:**
  - Architekt: **FREIGABE MIT AUFLAGEN**
    - vor Phase 1: A1, A2, A3, A12, alle umgesetzt
    - vor Phase 2: A4, umgesetzt als ADR-016/017 und Paket P2-00
    - A5–A14 übernommen
  - QA: **FREIGABE MIT AUFLAGEN**
    - kein KRITISCH-Befund im Diff
    - HOCH: B1 (Belege) und B2 (WORKLOG-Felder), beide behoben
    - MITTEL: B3, M1, M2, behoben bzw. als ADR-018 dokumentiert
    - NIEDRIG: N1–N3, behoben
  - Bestätigt von der QA: Testzahlen (81 → 91), Coverage-Werte und CI grün für aadfd67 (alle vier Jobs).
- **Bekannte Risiken:**
  - Die QA kann über `Bash` technisch schreiben. Eine technische Sperre über `.claude/settings.json` ist eine
    Berechtigungsänderung; die entscheidet der Betreiber (F13). Bis dahin vergleicht der Orchestrator vor und nach jedem
    QA-Lauf `git rev-parse HEAD`, `git status --short --ignored` und `git stash list`.
  - Die Zitate in `SOURCES.md` sind nicht am Original geprüft (P2-01).
- **Korrekturrunde 2:** Nachprüfung der QA nach Runde 1
  - Urteil: **FREIGABE MIT AUFLAGEN**. B1–B3, M1, M2, N1 und N3 sind behoben; 14 von 14 Mutationen werden erkannt;
    `96 passed`.
  - Neue Befunde: K1–K5. Kein KRITISCH- oder HOCH-Befund.
  - Behoben in Runde 2:
    - **K1:** P1-02 verlangt jetzt eine ausdrückliche Bestätigung vor der Wiederherstellung. Die technische Sperre
      während eines Laufs kommt mit P1-04.
    - **K2:** ADR-018 und Skill vergleichen jetzt `rev-parse HEAD`, `status --ignored` und `stash list`.
    - **K4:** Die Grenze der Belegprüfung steht im Test; `WORKLOG.md` wird mitgeprüft.
    - **K5:** Die Dateilisten für P1-01a und P1-12 sind ergänzt.
    - **K3:** PR-Nummer siehe unten.
  - Tests nach Runde 2: `97 passed`, ruff grün.
  - Runde 2 betraf nur MITTEL- und NIEDRIG-Befunde in der Doku. Die QA hat sie **nicht erneut geprüft**.
- **Commit/PR:** 7a99f82 (Runde 1), a8a7b89 (Runde 2); PR https://github.com/Vroind-ausm-All/Wohnmobil-Crawler/pull/3 (gegen den Integrationszweig, nicht gemergt)
- **Nächster sinnvoller Schritt:** PR gegen den Integrationszweig; Freigabe von Phase 1 und Antworten auf F1, F12
  einholen

### P0-06 – Roadmap, Backlog, Kennzahlen · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:** `docs/ROADMAP.md`, `README.md` (Verweise)
- **Implementierte Funktionen:**
  - Phasen 0–6 mit Abnahmekriterien
  - Backlog mit IDs, Prioritäten, Agenten, Abhängigkeiten und Akzeptanzkriterien (Phase 1 vollständig; Phasen 2–6 werden
    vor ihrer Freigabe ergänzt)
  - 13 Kennzahlen mit Definition und Datengrundlage
  - offene Betreiberfragen F1–F13
  - Zuordnung der früheren Phasenzählung
- **Tests:** `test_projekt.py`, Belegprüfung
- **Testergebnis:** siehe P0-07
- **Review-Ergebnis:** geprüft in P0-07 (Architekt und QA)
- **Bekannte Risiken:** Die Pakete der Phasen 2–6 sind noch grob.
- **Commit/PR:** c31d668, Korrekturen in P0-07
- **Nächster sinnvoller Schritt:** erster Phase-1-Durchgang nach Freigabe

### P0-05 – QA-Bestandsaufnahme · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `qa-security-reviewer` (Projekt-Agent). Der erste Versuch brach am Nutzungslimit der
  Sitzung ohne Ergebnis ab; der zweite lief vollständig.
- **Geänderte Dateien:** `docs/TEST-REPORT.md` (vom Orchestrator aus dem Bericht übernommen), `docs/ROADMAP.md`
  (P1-11 bis P1-15)
- **Implementierte Funktionen:** –
- **Tests:**
  - `pytest -q -p no:cacheprovider`
  - `ruff check .`
  - Coverage außerhalb der `.venv`
  - Missbrauchsskripte im Scratchpad mit temporärer Datenbank
- **Testergebnis:**
  - `91 passed in 17.16s`
  - ruff: „All checks passed!“
  - Abdeckung 88 %; schwach abgedeckt sind `netz.py` (27 %), `app.py` (52 %) und `benachrichtigung.py` (55 %)
- **Review-Ergebnis:** **FREIGABE MIT AUFLAGEN**
  - **KRITISCH:** Q1, angehoben in P0-07; dazu R1 und R3
  - **HOCH:** Q2 und Q3; dazu R5
  - **MITTEL:** acht Befunde (Q4–Q11)
  - **NIEDRIG:** sieben Befunde (Q12–Q18)
  - keine XSS-Lücke, keine Geheimnisse im Repository
- **Bekannte Risiken:** Nicht geprüft wurden:
  - Q6 und Q7 im echten Browser bzw. hinter dem Proxy
  - Performance bei großem Datenbestand
- **Commit/PR:** aadfd67
- **Nächster sinnvoller Schritt:** Befunde in Phase 1 beheben (P1-01a, P1-12, P1-13, P1-14a/b)
- **Hinweis:** Die QA meldete Änderungen im Arbeitsbaum, die nicht von ihr stammten. Es waren die Doku-Dateien, die der
  Orchestrator parallel geschrieben hatte. Die QA selbst hat nur unter `/tmp` geschrieben.

### P0-04 – Quellenrecherche · Status: DONE (mit Einschränkung)

- **Phase:** 0
- **Verantwortlicher Agent:** `source-researcher` (ausgeführt als eingebauter Agent nach Definition, siehe Hinweis oben)
- **Geänderte Dateien:**
  - `docs/SOURCES.md`
  - `docs/DECISIONS.md` (ADR-010)
  - `.claude/agents/source-integrations.md` (kein Serverabruf beim manuellen Import)
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - Kleinanzeigen, mobile.de (AGB-HB), AutoScout24 und Meta untersagen automatisiertes Auslesen.
  - Zulässig und ohne Vertrag testbar sind zwei unabhängige Kanäle: manueller Import und E-Mail-Suchbenachrichtigungen.
  - Einziger belegter offizieller Lesezugang: mobile.de API-Account.
- **Tests:** – (Recherche)
- **Testergebnis:**
  - Direkte Seitenabrufe scheiterten in der Recherche-Umgebung (DNS). Die Zitate stammen deshalb aus
    Suchindex-Auszügen.
  - `robots.txt`: nicht geprüft
- **Review-Ergebnis:** in P0-07 nicht inhaltlich geprüft (keine Abrufe gegen Marktplätze)
- **Bekannte Risiken:** Der Wortlaut der AGB kann von den Auszügen abweichen (P2-01, BLOCKED).
- **Commit/PR:** 548c1fc
- **Nächster sinnvoller Schritt:** AGB-Originale im Browser gegenlesen (Betreiber); Anfrage an mobile.de vorbereiten

### P0-03 – Architektur- und Risikoüberblick · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** `scout-architect` (ausgeführt als `Plan`-Agent nach Definition, siehe Hinweis oben)
- **Geänderte Dateien:**
  - `docs/ARCHITEKTUR.md` → `docs/ARCHITECTURE.md`
  - `docs/DECISIONS.md`
  - `README.md`
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - Modulübersicht, Datenfluss, Ist-Schema
  - Risiken R1–R18; R19 und R20 kamen in P0-07 dazu
  - Ziel-Datenmodell mit 9 Entitäten, Migrationsstrategie, Nebenläufigkeit
- **Tests:** Der Orchestrator hat die Risiken im Code stichprobenartig nachgeprüft:
  - R1: `config.yaml:196`, `importer.py:39-40`
  - R2: `config.yaml:32`
  - R3: `datenbank.py:49-53`
  - R5: `report.html:406`, `mobil.js:483`
  - R14: `api.py:434-437`
- **Testergebnis:**
  - Inhaltlich bestätigt.
  - Mehrere Zeilennummern waren falsch. Gefunden in P0-07, korrigiert und jetzt durch einen Test abgesichert.
  - Die erste Fassung von ADR-005 behauptete, der Kleinanzeigen-Abruf laufe nur auf Start durch den Betreiber. Das ist
    falsch (Auto-Suche) und wurde korrigiert.
- **Review-Ergebnis:** Urteil zum Phasenplan: **FREIGABE MIT AUFLAGEN**. Die Auflagen (a)–(d) sind übernommen.
- **Bekannte Risiken:** siehe `ARCHITECTURE.md` §5
- **Commit/PR:** c31d668
- **Nächster sinnvoller Schritt:** P0-07

### P0-02 – Agentensystem, Regeln, Skill, Loop · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:**
  - `CLAUDE.md`
  - `.claude/agents/*.md` (8)
  - `.claude/skills/scout-cycle/SKILL.md`
  - `.claude/loop.md`
  - `.gitignore`
  - `tests/test_projekt.py`
- **Implementierte Funktionen:**
  - acht Agenten mit YAML-Frontmatter; Prüfagenten ohne `Edit`/`Write`
  - Modelle: opus für Architektur, Ankaufsbewertung und QA; sonnet für die übrigen
  - SCOUT DEVELOPMENT LOOP mit Schritten A–H und Grenzen
  - Wartungsauftrag für `/loop`
- **Tests:** `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`
- **Testergebnis:**
  - Der erste Lauf scheiterte am YAML: Beschreibungen mit „: “ waren ungültig. Behoben durch Anführungszeichen.
  - Danach: `91 passed`, ruff „All checks passed!“
- **Review-Ergebnis:** geprüft in P0-07; Lücken in `test_projekt.py` dort behoben
- **Bekannte Risiken:** siehe ADR-018 (`Bash` bei QA)
- **Commit/PR:** 185dc0b
- **Nächster sinnvoller Schritt:** Projekt-Agenten nach Neustart nutzen (erledigt ab P0-05)

### P0-01 – Repository-Zustand und Entwicklungsbasis · Status: DONE

- **Phase:** 0
- **Verantwortlicher Agent:** Orchestrator
- **Geänderte Dateien:** –
- **Implementierte Funktionen:** –
- **Ergebnis:**
  - `main` enthält nur den Initial-Commit 76cb64d.
  - Integrationszweig: `claude/gifted-heisenberg-d1cjlr`.
  - PR #1 (Grundlage) und PR #2 (Handy-App) sind gemergt. PR #2 war auf den Arbeitszweig von PR #1 gestapelt und kam
    deshalb nicht im Integrationszweig an. Nachgezogen per Merge-Commit 3f75f67.
  - Die Arbeitszweige der PRs sind gemergt. Es gibt keine ungesicherten Änderungen.
- **Tests:** vor dem Push von 3f75f67: `pytest -q`, `ruff check .`
- **Testergebnis:** `81 passed`, ruff grün
- **Review-Ergebnis:** –
- **Bekannte Risiken:** Gestapelte PRs, deshalb ADR-008 (immer gegen den Integrationszweig).
- **Commit/PR:** 3f75f67 (im Integrationszweig)
- **Nächster sinnvoller Schritt:** Arbeitszweig `claude/phase0-agentensystem` anlegen
