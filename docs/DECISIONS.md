# Architekturentscheidungen (ADR)

Format: Kontext · Entscheidung · Alternativen · Folgen. Status: **gilt**, **vorgeschlagen** (Freigabe offen),
**ersetzt**. Neue Entscheidungen werden angehängt, alte nicht gelöscht, sondern als „ersetzt durch ADR-x“ markiert.

---

## ADR-001 – Python 3.13, projektlokale `.venv`, gesperrte Abhängigkeiten · gilt

* **Kontext:** Unter Windows scheiterte die Installation mit Python 3.15 (PyYAML ohne fertiges Paket, C-Compiler
  nötig). Anwender sind nicht technisch versiert.
* **Entscheidung:** Python 3.13 über den `py`-Launcher, projektlokale `.venv`, Installation nur aus
  `requirements*.txt` mit sha256-Hashes (`uv pip compile --universal --generate-hashes`) und `--only-binary=:all:`.
  Start per Doppelklick (`installieren.bat`, `app.bat`, `lauf.bat`), keine globalen Änderungen.
* **Alternativen:** Conda (zu schwer), PyInstaller-EXE (späteres Option für Verteilung), Poetry (zusätzliches Werkzeug).
* **Folgen:** Reproduzierbar, in CI unter Windows tatsächlich geprüft. Abhängigkeitsänderungen erfordern das
  Neuerzeugen der Lock-Dateien.

## ADR-002 – SQLite als einzige Datenbank · gilt

* **Kontext:** Ein Büro-PC, wenige gleichzeitige Nutzer, Datenmengen im Bereich zehntausender Inserate.
* **Entscheidung:** SQLite (eine Datei unter `daten/`). PostgreSQL o. Ä. erst bei nachgewiesenem Bedarf
  (gleichzeitige Schreiblast, mehrere Server, > ~1 Mio. Beobachtungen mit spürbaren Antwortzeiten).
* **Folgen:** Kein Datenbankserver, einfache Backups. Schreibzugriffe müssen serialisiert werden (heute ein Lock
  im Webserver); Migrationen brauchen eigene Werkzeuge (siehe ADR-009).

## ADR-003 – Standardbibliothek-Webserver statt Web-Framework · gilt

* **Kontext:** Lokale App, wenige Nutzer, Doppelklick-Start, keine Build-Kette gewünscht.
* **Entscheidung:** `http.server.ThreadingHTTPServer` mit eigener Routenschicht (`wmscout/web/api.py`), Jinja2-Vorlagen,
  Vanilla-JS. Server lauscht nur auf `127.0.0.1`; Fernzugriff ausschließlich über Tailscale.
* **Alternativen:** Flask/FastAPI (mehr Abhängigkeiten, eigener Server-Prozess), Electron (schwer).
* **Folgen:** Sicherheitsfunktionen (Sitzungen, CSRF, Host-Prüfung) sind selbst gebaut und müssen getestet bleiben.
  Bei deutlich mehr Routen oder Nutzern neu bewerten.

## ADR-004 – Einheitliche Quellen-Schnittstelle mit Freigabe-Kennzeichen · gilt

* **Kontext:** Mehrere Marktplätze mit unterschiedlichen, teils unzulässigen Zugangswegen.
* **Entscheidung:** Jede Quelle ist ein Adapter (`Quelle`) mit `kennung`, `zugriffsart` (`api`/`feed`/`web`/`manuell`)
  und `freigegeben`; Adapter liefern nur `Inserat`-Objekte, der `Importer` verbindet Quellen und Datenbank.
  Bei Sperre (403/429/Captcha) bricht der Abruf ab (`QuelleGesperrt`), es wird nichts umgangen.
* **Folgen:** Neue Quelle = Adapter + Konfiguration; Bewertung bleibt quellenneutral.

## ADR-005 – Kleinanzeigen-Direktabruf ist nicht freigegeben · gilt, Betreiberentscheidung offen

* **Kontext:** Die Nutzungsbedingungen von Kleinanzeigen untersagen automatisiertes Auslesen (Beleg: `docs/SOURCES.md`).
  Der bestehende Suchlauf liest Kleinanzeigen-Suchseiten per HTML.
* **Ist-Zustand (Phase 0 geprüft):** Der Adapter ist mit `freigegeben = False` gekennzeichnet, läuft aber trotzdem
  **standardmäßig**: Die Suchaufträge in `config.yaml` zeigen auf Kleinanzeigen, und die Auto-Suche startet bei
  geöffneter App alle 3 Stunden (`app.auto_suche_stunden: 3`). Der Importer protokolliert nur eine Warnung. Das
  verstößt gegen die Projektregeln 11/12 (Risiko R1, KRITISCH).
* **Entscheidung:** Der Importer verweigert Suche **und** Detailabruf für Quellen mit `freigegeben = False`;
  Auto-Suche standardmäßig aus; ehrlicher User-Agent (P1-01a, ohne Abhängigkeit). Eine lokale Ausnahme „auf eigene
  Verantwortung“ widerspräche Projektregel 12 und wird **nicht** auf Vorrat gebaut. Sie käme nur in Frage, wenn der
  Betreiber Regel 12 in `CLAUDE.md` selbst ändert (P1-01b, BLOCKED, Frage F1). Ersatz durch zulässige Eingangskanäle
  (manueller Import, E-Mail-Suchbenachrichtigungen) in Phase 2.
* **Folgen:** Nach P1-01a findet die App keine neuen Kleinanzeigen-Inserate mehr per Abruf, bis die Kanäle aus Phase 2
  bereitstehen. Der Betreiber wird vor dem Merge ausdrücklich darauf hingewiesen.

## ADR-006 – Handy-App als PWA, Server rechnet verbindlich · gilt

* **Kontext:** Mitarbeiter besichtigen unterwegs, teils ohne Netz; kein App-Store gewünscht.
* **Entscheidung:** Progressive Web App unter `/m` auf demselben Server; Offline-Entwürfe und Foto-Warteschlange im
  Browser. Der Mängelabzug wird im Browser (JS) und auf dem Server (Python) identisch gerechnet; verbindlich ist der
  Server. Paritätstest über 600 Zufallsfälle.
* **Folgen:** Jede Änderung an der Abzugslogik muss in beiden Implementierungen erfolgen (Test erzwingt das).

## ADR-007 – Deutsche Bezeichner; englische Entitätsnamen nur in der Planung · vorgeschlagen

* **Kontext:** Der Code nutzt durchgehend deutsche Bezeichner (`anzeigen`, `besichtigungen`, `nutzer`). Die Roadmap
  nennt englische Entitäten (vehicles, listings, …).
* **Entscheidung:** Tabellen und Bezeichner bleiben deutsch. Zuordnung: vehicles → `fahrzeuge`, listings → `inserate`,
  sources → `quellen`, search_profiles → `suchprofile`, price_history → `preis_historie`,
  observations → `beobachtungen`, crawl_runs → `suchlaeufe`, valuations → `bewertungen`, contacts → `kontakte`.
* **Folgen:** Einheitlicher Code; die Zuordnung steht in `docs/ARCHITECTURE.md` und in der Agentendefinition
  `scout-data-engineer`.

## ADR-008 – Branch- und Freigabemodell · gilt

* **Kontext:** `main` enthält nur den Initial-Commit; der Hauptcode liegt im Zweig `claude/gifted-heisenberg-d1cjlr`.
  PR #2 basierte auf dem Arbeitszweig von PR #1 und landete nach dessen Merge nicht im Integrationszweig.
* **Entscheidung:** `claude/gifted-heisenberg-d1cjlr` ist der **Integrationszweig**. Jedes Arbeitspaket bekommt einen
  Zweig `claude/<phase>-<thema>` vom Integrationszweig und einen PR **gegen den Integrationszweig**; keine gestapelten
  PRs. `main` wird nur auf ausdrücklichen Wunsch des Betreibers per PR aktualisiert, nie automatisch.
* **Ergänzung nach Architekturprüfung (P0-07):** Parallele Pakete laufen je in einem eigenen `git worktree`. Eine
  Abhängigkeit gilt erst als erfüllt, wenn der Vorgänger im Integrationszweig gemergt ist. `docs/ROADMAP.md`,
  `WORKLOG.md` und `TEST-REPORT.md` ändert nur der Orchestrator. Ob eng gekoppelte Pakete desselben Agenten in einem
  PR gebündelt werden dürfen, entscheidet der Betreiber (Frage F12).
* **Folgen:** Pakete, die aufeinander aufbauen, werden nacheinander gemergt; die Merge-Geschwindigkeit des Betreibers
  bestimmt, wie viele Pakete ein Durchgang schafft.

## ADR-009 – Versionierte Migrationen mit Backup · vorgeschlagen (Umsetzung Phase 1)

* **Kontext:** Heute ergänzt `wmscout/datenbank.py` fehlende Spalten per `ALTER TABLE` beim Start, ohne Version und
  ohne Backup. Die Phasen 2–3 brauchen tiefgreifende Schemaänderungen (Fahrzeuge/Inserate getrennt, Historie).
* **Entscheidung:** Tabelle `schema_version`; nummerierte, idempotente Migrationsschritte in je einer Transaktion;
  vorher Backup über die SQLite-Backup-API mit `PRAGMA integrity_check`; Test mit Datenbanken jeder Vorversion;
  Kompatibilitäts-View `anzeigen` während des Umbaus. Eine Versionszählung für alles: 1 = ZIP-Stand, 2 = heute,
  3 = Phase 1, 4 = Phase 2, 5 = Phase 3, 6 = `bewertungen` (`docs/ARCHITECTURE.md` §8). Start bricht ab, wenn die
  Datenbank neuer ist als der Code; ohne erfolgreiches Backup keine Migration.
* **Folgen:** Kein Schemawechsel ohne Rückweg; die heutigen `ALTER TABLE`-Ergänzungen definieren Version 2.

## ADR-010 – Manueller Import ohne Serverabruf · vorgeschlagen (Umsetzung Phase 2)

* **Kontext:** Die Nutzungsbedingungen von Kleinanzeigen (§ 5) und AutoScout24 (Ziff. 8.2) untersagen
  automatisierte Abfragen. Auch ein einzelner, vom Programm ausgelöster Abruf einer Inseratsseite ist damit heikel
  (`docs/SOURCES.md`).
* **Entscheidung:** Beim manuellen Import liefert der Nutzer URL **und** Inhalt (eingefügter Text oder im Browser
  gespeicherte Seite); der Server ruft die URL nicht ab. Aus Suchbenachrichtigungs-E-Mails wird nur der E-Mail-Inhalt
  ausgewertet, verlinkte Anzeigen werden nicht nachgeladen. Ein Serverabruf ist nur für Quellen mit Status **OK** und
  `freigegeben = True` erlaubt.
* **Alternativen:** Einzelabruf der URL durch den Server (bequemer, aber für die großen Börsen nicht freigegeben).
* **Folgen:** Etwas mehr Handarbeit beim Import; Datenqualität hängt vom eingefügten Text ab. Parser müssen mit
  unvollständigen Daten umgehen und fehlende Felder als „unvollständig“ markieren.

## ADR-011 – Fahrzeug, Inserat und Ankauf trennen · vorgeschlagen (Phasen 2–3)

* **Kontext:** Heute ist die Anzeigen-ID der Primärschlüssel; Ankaufsstatus, Verfügbarkeit und Preis hängen am Inserat.
  Ein neu eingestelltes oder auf zwei Plattformen inseriertes Fahrzeug wird mehrfach geführt und ggf. erneut angeschrieben.
* **Entscheidung:** `inserate` mit `UNIQUE(plattform, anzeigen_id)` (vor der zweiten Quelle, Schema v4, ADR-016); `fahrzeuge` als eigene
  Identität (FIN, sonst Fingerabdruck mit Konfidenz); **Ankaufsstatus am Fahrzeug, Verfügbarkeit am Inserat, Kontakte
  als Ereignisse** (`kontakte`). Zusammenführungen unsicherer Treffer nur als Vorschlag mit Bestätigung.
* **Alternativen:** Status weiter am Inserat und Dubletten nur anzeigen (einfacher, aber Doppelansprache bleibt möglich).
* **Folgen:** Größte Schemaänderung des Projekts; nur mit Migrationsrahmen (ADR-009) und Kompatibilitäts-View.

## ADR-012 – Kontakt gilt erst nach Bestätigung · vorgeschlagen (UI Phase 1, Datenmodell Phase 3)

* **Kontext:** Desktop (`report.html`) und Handy (`mobil.js`) setzen „kontaktiert“ beim Kopieren des Textes.
* **Entscheidung:** Kopieren/Öffnen setzt nur „vorbereitet“; „kontaktiert“ erst nach ausdrücklicher Bestätigung
  „gesendet“ durch den Nutzer. Nachfassen setzt einen abgesagten Vorgang nicht zurück auf „kontaktiert“.
* **Folgen:** Ein zusätzlicher Klick je Kontakt; Kennzahl „kontaktierte Verkäufer“ wird verlässlich.
  Offen: Gelten alte „kontaktiert“-Einträge als bestätigt? (Betreiberfrage)

## ADR-013 – Nebenläufigkeit und Laufsperre · vorgeschlagen (Phase 1)

* **Kontext:** Ein globaler Lock im Webserver umschließt auch Bewertung, Antwortversand und WhatsApp-HTTP; mehrere
  SQLite-Verbindungen ohne WAL/`busy_timeout`; App-Auto-Suche und `lauf.bat` können parallel laufen.
* **Entscheidung:** WAL, `busy_timeout`, eine Verbindung je Thread, Lock nur um DB-Zugriffe, externe Aufrufe außerhalb
  bzw. asynchron, Laufsperre über die Datenbank.
* **Folgen:** Mehrere Nutzer blockieren sich nicht mehr gegenseitig; Tests für parallele Zugriffe nötig.
* **Umgesetzt (P1-04a, 14.10.2026):** WAL und `busy_timeout` (10 s) in `Datenbank`; abschaltbar mit `ausgabe.wal: false`
  (Netzlaufwerke, dort ist WAL nicht zulässig). `synchronous` bleibt beim sicheren Standard FULL. Sicherungen werden auf
  den Modus DELETE gestellt (eine Datei, kein `-wal` daneben). Die Wiederherstellung prüft zusätzlich per
  `wal_checkpoint(TRUNCATE)`, weil `BEGIN EXCLUSIVE` im WAL-Modus Lesende nicht erkennt. Laufsperre folgt (P1-04).

## ADR-014 – Fehlerisolation je Quelle · vorgeschlagen (Phase 2)

* **Entscheidung:** Ein Fehler betrifft nur den eigenen Suchauftrag bzw. die eigene Quelle; eine Sperre setzt
  `gesperrt_bis` nur für diese Quelle. Unparsebare Datensätze werden gezählt und protokolliert, nie still verworfen.

## ADR-015 – Bewertung bleibt rein und versioniert · vorgeschlagen (Phasen 1/5)

* **Entscheidung:** `wmscout/bewertung/` greift nicht auf Datenbank oder Netz zu und enthält keine quellenspezifische
  Logik; Statuskonstanten wandern in ein Domänenmodul. Gespeicherte Bewertungen tragen eine `modell_version`, damit
  Änderungen am Rechner nachvollziehbar bleiben.

## ADR-016 – Plattform und Eingangskanal trennen · vorgeschlagen (vor Phase 2, Paket P2-00)

* **Kontext:** Phase 2 bringt Push-Kanäle (E-Mail-Suchbenachrichtigungen, manueller Import), die Inserate derselben
  Plattformen liefern wie ein Abruf. Heute ist die „Quelle“ zugleich Plattform und Zugriffsweg.
* **Entscheidung:** `inserate` trägt `plattform` (kleinanzeigen, mobile_de, autoscout24, …) und ist über
  `UNIQUE(plattform, anzeigen_id)` eindeutig. Der Eingangskanal (suche, api, email, manuell, detail) steht in
  `beobachtungen.kanal`. Detailabruf nur, wenn die Plattform freigegeben ist und eine pull-fähige Quelle hat.
* **Folgen:** Dasselbe Inserat aus E-Mail und manuellem Import ergibt einen Datensatz mit zwei Beobachtungen.

## ADR-017 – Push-Eingänge über eine eigene Schnittstelle · vorgeschlagen (Paket P2-00)

* **Entscheidung:** Push-Kanäle implementieren `Eingang.lese(roh: bytes, meta) -> Iterable[Inserat]`.
  `Importer.importiere(inserate, kanal)` ist der einzige Schreibweg für Pull- und Push-Daten; Vertrags- und
  Isolationstests gelten für beide Arten.
* **Folgen:** `Quelle` (Pull) bleibt unverändert; neue Kanäle brauchen keinen Abruf.

## ADR-018 – Prüfagent mit `Bash` · gilt

* **Kontext:** Der Betreiber verlangt für Prüfagenten nur lesende Werkzeuge; `qa-security-reviewer` muss aber Tests
  ausführen (`pytest`, `ruff`, `coverage`), wofür Claude Code nur `Bash` anbietet.
* **Entscheidung:** QA erhält `Read, Grep, Glob, Bash`, kein `Edit`/`Write`. Schreibverbot im Repository über den
  System-Prompt; der Orchestrator prüft nach jedem QA-Lauf `git status`. `scout-architect` und `source-researcher` haben
  kein `Bash`. Eine technische Sperre über Deny-Regeln in `.claude/settings.json` (z. B. für `git commit`/`git push`)
  wäre möglich, ist eine Änderung der Berechtigungen und bleibt dem Betreiber vorbehalten (Frage F13).
* **Folgen:** Restrisiko, dass QA per Shell schreibt. `git status` allein erkennt weder Commits noch Schreibzugriffe
  in ignorierten Pfaden (`daten/`, `ausgabe/`, `.venv/`). Deshalb vergleicht der Orchestrator vor und nach jedem
  QA-Lauf `git rev-parse HEAD`, `git status --short --ignored` und `git stash list`.

## ADR-020 – Fahrzeugart beim Seitenimport nur „bestätigt“ aus Art-Filter oder Detailseite · Sperre ersetzt durch ADR-021 (14.10.2026)

* **Kontext:** Bei gespeicherten Suchseiten ist die Fahrzeugart oft nur aus dem Suchbegriff oder dem Anzeigentitel zu
  erraten. Drei QA-Runden haben mit echten Seiten gezeigt, dass jedes Raten Fälle mit falscher Art erzeugt, zum
  Beispiel „Wohnwagen Dethleffs Camper“ → Kastenwagen. Daraus entstehen falsche Max-EK und Anschreiben.
* **Entscheidung:** Als **bestätigt** gilt eine Art nur aus dem Art-Filter (`art_s:`) der Suchseite oder dem Feld
  „Art“ einer Detailseite. Eine Art aus Titel oder Suchbegriff ist **vorläufig**. Vorläufige und unbekannte Arten sind
  nie anschreibbar (Sperrgrund mit Handlungshinweis). Die Herkunft steht in `suche`
  („Import <Art> (bestätigt|vorläufig)“, „Import (gespeicherte Seite)“); das Schema bleibt unverändert.
* **Folgen:** Weniger Fahrzeuge sind sofort anschreibbar, dafür keine falschen Angebote. Der Betreiber sucht über den
  Art-Filter oder liest Detailseiten ein. K-A (Filter bestätigte auch „Weitere Ergebnisse in anderen Orten“) ist
  behoben: Bestätigt werden nur Treffer aus `#srchrslt-adtable`. **Die Sperre gilt seit 14.10.2026 nicht mehr, siehe
  ADR-021.**

## ADR-021 – Jedes Fahrzeug anschreibbar: Hinweis statt Sperre bei der Fahrzeugart · gilt (14.10.2026)

* **Kontext:** Der Betreiber will „möglichst jedes Wohnmobil anschreiben“ und auf Masse gehen. Die Sperre aus ADR-020
  hielt fast alle importierten Fahrzeuge zurück (18 echte Seiten: 350 von 352 ohne bestätigte Art).
* **Entscheidung des Betreibers (14.10.2026):** Jedes Fahrzeug soll anschreibbar sein; der Brief soll weniger den
  Modellnamen und, falls vorhanden, den Profilnamen des Verkäufers verwenden.
* **Umsetzungsentscheidungen (Orchestrator, nach QA):** Eine vorläufige oder unbekannte Fahrzeugart ist **kein
  Sperrgrund** mehr, sondern ein sichtbarer **Hinweis** in Desktop-App, API, Handy-App, CSV, Anschreiben-Datei und
  Mail. Die Herkunftsregeln aus ADR-020 bleiben und steuern den Hinweis. Der Art-Filter bestätigt nur Treffer der
  Haupttabelle, eine Detailseite hat Vorrang vor dem Filter. Bei **vorläufiger** Art wird mit der vorläufigen Art
  gerechnet. Bei **unbekannter** Art rechnet die Vorstufe (`fuer_rechner`, `bewerte_anzeige`) vorsichtig: niedrigster
  Max-EK über „ohne Art“ und die Art-Wörter in Titel/Kurzbeschreibung, Spanne über alle Kandidaten, Sicherheit höchstens
  „niedrig“ – der Rechner bleibt unverändert. Bei nicht bestätigter Art nennt der Brief keine Art. Der Profilname wird
  nur beim Seitenimport für die Anrede in `details_json` gespeichert (keine Telefonnummer, keine Profil-ID); er steht
  danach auch im erzeugten Brief. Eine Löschfunktion folgt mit P1-14a.
* **Folgen:** Viel mehr Fahrzeuge sind sofort anschreibbar. Max-EK kann bei falscher Art danebenliegen – der
  Mitarbeiter prüft vor dem Absenden. Wohnwagen ohne Art-Wort im Text werden wie Wohnmobile gerechnet (QA: 10 der
  Top 20 echter Daten); deshalb **Betreiberentscheidung F14 (14.10.2026): bei unbekannter Art Ampel höchstens „gelb“ und
  Brief ohne Betrag**. Die Erkennung von Wohnwagen-Baureihen bleibt ein eigenes Paket. Die übrigen Sperrgründe (gewerblich, Sperrbegriffe, Filter) folgen
  als Hinweise in einem eigenen Paket. ADR-020 gilt nur noch für die Herkunftsregeln.

## ADR-022 – mobile.de: Kategorie des Treffers gilt als bestätigte Art; Auslandsangebote vorsichtig · gilt (14.10.2026)

* **Kontext:** mobile.de liefert je Treffer und auf der Anzeigenseite die vom Anbieter gewählte Kategorie als eigenes
  Feld („Kastenwagen • …“, „Kategorie“). ADR-020 kennt als Bestätigung nur den Kleinanzeigen-Art-Filter und das Feld
  „Art“ der Detailseite. Außerdem enthält mobile.de Angebote aus dem Ausland („SE-…“, „NL-…“), für die die deutsche
  PLZ-Entfernung falsch oder leer war (QA P2-05b H3).
* **Entscheidung (Orchestrator, nach QA):** Die strukturierte Kategorie gilt als **bestätigt** – gleichwertig zum
  Detailseitenfeld –, aber nur mit dem ausdrücklichen Kennzeichen `details["art_quelle"] = "kategorie"`
  (`ART_QUELLE_KATEGORIE`), nicht durch bloße Anwesenheit einer Art. „Wohnmobil andere“/„Andere“ sind keine Art.
  Nur Wohnmobil-/Wohnwagen-Seiten werden importiert. Orte mit fremdem Länderkürzel ergeben keine PLZ/Entfernung;
  Ampel höchstens „gelb“, Brief ohne Betrag, Hinweis „Ausland – Abholung, Überführung und Zulassung prüfen“; mit
  gesetzter `max_entfernung_km` gesperrt. Fehlt die Anbieterangabe, wird `gewerblich` als unbekannt (NULL) gespeichert
  und als Hinweis gezeigt, nicht als privat.
* **Folgen:** 55 von 65 echten Treffern haben eine bestätigte Art. Restrisiko: Fehlklassifikation durch den Anbieter
  (QA: ca. 1 von 65); Plausibilitätsprüfung (z. B. Länge je Art) als Backlog. Die Kategorie lässt sich mit einer Zeile
  im Importer wieder auf „vorläufig“ stellen. Plattformkennung im Code `mobile.de` (ADR-016 nennt `mobile_de`;
  Vereinheitlichung mit P2-00).

## ADR-023 – Team-Übersicht: Reservierung je Inserat in `bearbeitung`, Wirkung beim Lesen, ohne Schemaänderung · gilt (14.10.2026)

* **Kontext:** Mehrere Mitarbeiter schreiben in Masse an; Doppelkontakt muss verhindert und sichtbar werden, wer
  welches Fahrzeug bearbeitet. Fahrzeugidentität gibt es erst ab P3-02; Schema-Version 4 ist für Phase 2 vergeben.
* **Entscheidung:** Tabelle `bearbeitung` (v3) als aktueller Zustand, keine Migration. „Ich übernehme“ ist ein
  bedingtes UPSERT (atomar auch über mehrere Verbindungen); Konflikt → HTTP 409 mit `grund: "konflikt"`. Alle Status
  in Arbeit (kontaktiert, Verhandlung, Besichtigung) und das Anlegen einer Besichtigung übernehmen in derselben
  Transaktion (`BEGIN IMMEDIATE`). Ablauf (Standard 2 Tage, `team.reservierung_tage`), Kürzel und Dublettenwirkung
  werden beim Lesen berechnet; Reservierungen inaktiver Nutzer gelten als frei, ihre kontaktierten Fahrzeuge als
  „verwaist“. Nur der Inhaber darf erzwingen und zuweisen; Erzwingen/Zuweisen nimmt nicht kontaktierte Reservierungen
  erkannter Dubletten mit; Erzwingen übernimmt auch bei Verhandlung/Besichtigung. Den Besichtiger tragen nur Inhaber
  oder Bearbeiter des Fahrzeugs ein; der eingetragene Besichtiger darf beim Abschluss den Status setzen. Der Inhaber
  darf den Status „Verhandlung/Besichtigung“ eines von einem Kollegen gehaltenen Fahrzeugs ohne Übernahme ändern. Ohne
  angelegte Nutzer ist die Funktion aus. Mitarbeiter sehen nur ihre eigenen Zähler, der Inhaber alle; die Kürzel am
  Fahrzeug sehen alle (nötig gegen Doppelkontakt). Kein Verlauf in der DB (nur Log bei Erzwingen/Zuweisen).
* **Alternativen:** v4 mit Verlaufstabelle (verschiebt Phasen-Versionen; Verlauf kommt mit P3-06), Spalte in
  `anzeigen` (Migration), Gruppenreservierung beim Schreiben (Dubletten sind flüchtig).
* **Folgen:** Kein Backup-/Migrationsschritt nötig. P2-02/P3-01 müssen `bearbeitung` umschlüsseln und in `_zaehle`
  aufnehmen. Leistungsdaten je Mitarbeiter entstehen (Zähler, CSV-Spalten) – Zweck „Doppelkontakt vermeiden,
  Arbeit verteilen“; Mitbestimmung (§ 87 Abs. 1 Nr. 6 BetrVG) beachten, Speicherdauer mit P1-14a. Die bisherigen
  Oberflächen werten 409 noch nicht aus → **Team-Betrieb erst mit T2**.
