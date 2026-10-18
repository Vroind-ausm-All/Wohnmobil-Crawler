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

## ADR-012 – Kontakt gilt erst nach Bestätigung · gilt (umgesetzt 15.10.2026 mit T2, P1-06)

* **Kontext:** Desktop (`report.html`) und Handy (`mobil.js`) setzen „kontaktiert“ beim Kopieren des Textes.
* **Entscheidung:** Kopieren/Öffnen setzt nur „vorbereitet“; „kontaktiert“ erst nach ausdrücklicher Bestätigung
  „gesendet“ durch den Nutzer. Nachfassen setzt einen abgesagten Vorgang nicht zurück auf „kontaktiert“.
* **Folgen:** Ein zusätzlicher Klick je Kontakt; Kennzahl „kontaktierte Verkäufer“ wird verlässlich.
  Offen: Gelten alte „kontaktiert“-Einträge als bestätigt? (Betreiberfrage) – bis zur Antwort bleiben sie unverändert.
* **Umsetzung:** Status `vorbereitet` („Text kopiert“) speichert Text und Angebot, aber weder `kontaktiert_am` noch im
  Team `kontaktiert_von`; im Team reserviert er das Inserat. Desktop und Handy öffnen die Anzeige erst nach der
  Server-Antwort 200 (bei 409 bleibt sie zu). „Text kopiert“ bleibt im Filter „Anschreiben bereit“, bis „gesendet ✓“
  bestätigt ist. Eine veraltete Seite kann einen bestätigten Kontakt nicht per „vorbereitet“ zurücksetzen (409).

## ADR-013 – Nebenläufigkeit und Laufsperre · vorgeschlagen (Phase 1)

* **Kontext:** Ein globaler Lock im Webserver umschließt auch Bewertung, Antwortversand und WhatsApp-HTTP; mehrere
  SQLite-Verbindungen ohne WAL/`busy_timeout`; App-Auto-Suche und `lauf.bat` können parallel laufen.
* **Entscheidung:** WAL, `busy_timeout`, eine Verbindung je Thread, Lock nur um DB-Zugriffe, externe Aufrufe außerhalb
  bzw. asynchron, Laufsperre über die Datenbank.
* **Folgen:** Mehrere Nutzer blockieren sich nicht mehr gegenseitig; Tests für parallele Zugriffe nötig.
* **Umgesetzt (P1-04a, 14.10.2026):** WAL und `busy_timeout` (10 s) in `Datenbank`; abschaltbar mit `ausgabe.wal: false`
  (Netzlaufwerke, dort ist WAL nicht zulässig). `synchronous` bleibt beim sicheren Standard FULL. Sicherungen werden auf
  den Modus DELETE gestellt (eine Datei, kein `-wal` daneben). Die Wiederherstellung prüft zusätzlich per
  `wal_checkpoint(TRUNCATE)`, weil `BEGIN EXCLUSIVE` im WAL-Modus Lesende nicht erkennt. Laufsperre (P1-04): Dateisperre
  des Betriebssystems (`fcntl.flock` bzw. `msvcrt.locking`) auf `<datenbank>.laufsperre` statt der geplanten Tabelle
  `suchlaeufe` mit Lease – ohne Schemaänderung, und ein abgestürzter Lauf hinterlässt keine veraltete Sperre. Nicht wartend:
  App-Suche, Auto-Suche und `scout.py lauf` überspringen, die Wiederherstellung bricht ohne Änderung ab.

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

## ADR-024 – `anzeigen` und v4-Tabellen gleich halten, ohne neue Schemaversion · vorgeschlagen (15.10.2026)

* **Kontext:** Schema v4 (PR #7) legte `inserate`, `beobachtungen`, `preis_historie` neben `anzeigen` an. Suche,
  Seitenimport, App und Bewertung schrieben/lasen weiter nur `anzeigen`, der Ereigniseingang nur v4 – zwei getrennte
  Datenwege (Befund P0 der 3.0-Analyse).
* **Entscheidung:**
  1. `Datenbank.speichere_treffer` spiegelt jeden Treffer in derselben Transaktion (`BEGIN IMMEDIATE`) nach v4
     (Kanal `suche` bzw. `manuell` für eingelesene Seiten); protokolliert werden nur Änderungen.
  2. `EreignisSpeicher` schreibt neue/geänderte Inserate zusätzlich nach `anzeigen`: unbekannte Art (`IMPORT_SUCHE`,
     F14), eine vorhandene Zuordnung bleibt. Löschereignisse ändern nur `inserate.verfuegbarkeit`, nie den Ankaufstatus.
     Gehört dieselbe Anzeigen-ID in `anzeigen` einer anderen Plattform, bleibt die App-Zeile unberührt (Warnung).
  3. Beim Öffnen ergänzt ein rein additiver, idempotenter Abgleich fehlende v4-Gegenstücke (Kanal `abgleich`).
  4. Zeitpunkte in v4 aus Suche/Abgleich in UTC (Ereignisse waren es schon); `anzeigen` bleibt bei Ortszeit.
* **Warum keine Migration v5:** Nur additive Daten in abgeleiteten Tabellen, keine Strukturänderung; v5 bleibt für
  Fahrzeugidentitäten frei. Kein Löschen, kein Überschreiben bestehender `anzeigen`-Werte durch den Abgleich.
* **Folgen:** App und Ereigniseingang sehen dieselben Fahrzeuge; Preisverlauf entsteht ab jetzt auch aus der Suche.
  Offen: Verfügbarkeit („offline“) in der App anzeigen (UI); Anzeigen-ID-Kollision über Plattformen hinweg löst erst
  ein plattformbezogener Schlüssel in `anzeigen` (v5).

## ADR-025 – Verkäuferportal v1: intern, eigene Tabellen, grobe Spanne nur bei sicherer Datenlage · vorgeschlagen (15.10.2026)

* **Kontext:** 3.0-Analyse Phase B. Verkäufer sollen ihr Fahrzeug selbst anbieten (eigener, autorisierter Zulauf statt
  Beobachtung fremder Börsen). Betreiberentscheidungen 15.10.2026: Version 1 **erst intern** (App lokal/Tailscale,
  Telefon- und Vor-Ort-Anfragen erfasst das Team); dem Verkäufer eine **grobe Spanne**; Preisvorstellung **freiwillig**.
* **Entscheidung:**
  1. Eigene Tabellen in Schema **v5** (`verkaeufer`, `verkaufsanfragen`, `anfrage_fotos`, `anfrage_verlauf`) – getrennt von
     `anzeigen`/`inserate` (Architekturregel 1: Beobachtung ≠ freigegebenes Angebot). Geldbeträge ganze Euro, Status per
     CHECK, jede Änderung im Verlauf (wer, wann, alt → neu). Verkäufer und Anfrage in einer Transaktion.
  2. Bewertung mit dem unveränderten Rechner über `verkauf.als_fahrzeug` (Art vom Verkäufer, Mängel als Text) –
     keine portal-spezifische Logik in der Ankaufsberechnung.
  3. Dem Verkäufer höchstens eine auf 1.000 € nach außen gerundete Spanne des Angebotsniveaus, nur bei Sicherheit
     ≥ `verkaeuferportal.spanne_mindest_sicherheit` (Standard „mittel“), mit Hinweis „kein Kaufangebot“; nie Max-EK
     oder Erstangebot. Abschaltbar (`spanne_zeigen`).
  4. Alle Seiten hinter der bestehenden Anmeldung; keine automatische Nachricht an Verkäufer (Regel 10); Fotos im
     Browser verkleinert (keine EXIF/GPS-Originale), nur JPEG/PNG/WebP, höchstens 12, im Fotoordner (mitgesichert).
  5. Einwilligung Pflicht, mit Zeitpunkt und Textversion (`einwilligung_version`) gespeichert.
* **Folgen / offen:** Fahrzeugidentität rückt auf v6. Vor einem **öffentlichen** Betrieb: eigene Sicherheits- und
  Betriebsarchitektur (Hosting, HTTPS, Spam-/Missbrauchsschutz, Status-Link mit Geheimnis), Datenschutzerklärung und
  Einwilligungstext rechtlich prüfen, Löschung/Widerruf (Anonymisieren) umsetzen.

## ADR-026 – Händlerportal v1 für eigene Standorte: Positivliste, doppelte Freigabe, anonymisiert · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase C. Betreiberentscheidungen 16.10.2026: „Händler“ sind die **eigenen Standorte/Filialen**
  (kein externer Marktplatz); Freigabe einer Anfrage nur mit **Zustimmung des Verkäufers UND Freigabe des Inhabers**;
  Standorte sehen **anonymisiert mit Preisvorstellung**; Version 1 **erst intern**.
* **Entscheidung:**
  1. Schema **v6** (additiv): `standorte` (Status offen/geprüft/gesperrt), `nutzer.standort_id`, an `verkaufsanfragen`
     `weitergabe_einwilligung_am`, `freigegeben_am`, `freigegeben_von`, Tabelle `anfrage_interesse` (je Standort einmal).
  2. Neue Rolle `haendler` (nur mit Standort). **Positivliste im Server** (`_haendler_erlaubt`): solche Zugänge erreichen nur
     `/haendler`, `/api/haendler/…`, `/haendler-fotos/…`, `/api/ich`, `/api/logout`; alles andere 403, `/` leitet um.
     Händler erscheinen nie in Team-Listen (Kürzel, Zähler, Zuweisen, Besichtigungen).
  3. Sichtbar nur, wenn Standort **geprüft** (bei jeder Anfrage neu geprüft – Sperre wirkt sofort) und die Anfrage
     zugestimmt, freigegeben und offen ist (eingegangen/in Prüfung/Angebot). Sonst 404 statt 403 (kein Hinweis auf Existenz).
  4. Anonyme Sicht als **Positivliste** (`haendler.anonym`): Fahrzeug, Mängel, Fotos, Preisvorstellung, PLZ-Bereich
     („12xxx“) – nie Name, Telefon, E-Mail, genaue PLZ/Ort, Max-EK/Erstangebot. Telefonnummern, E-Mails und Links in
     Freitexten werden zusätzlich maskiert; der Inhaber prüft vor der Freigabe.
  5. Freigeben/zurücknehmen nur der Inhaber; jede Änderung im Verlauf. „Interesse melden“ ist unverbindlich (Vorstufe zu D).
  6. Verkäuferformular: freiwillige Zustimmung zur Weitergabe (Einwilligungstext Version `2026-10-entwurf-2`).
* **Folgen / offen:** Fahrzeugidentität rückt auf v7. Externe Partnerhändler (Marktplatz) wären eine eigene Entscheidung
  (Gewerbenachweis, Verträge, Datenschutz). Öffentlicher Betrieb weiter erst mit B4.

## ADR-027 – Demo-Auktionen: Schreibsperre statt Dienst, Ganzzahlen, UTC, Hash-Kette, Zuschlag nur durch den Inhaber · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase D: simulierte Gebote, Zustandsmaschine, Timer, Höchstgebot, Audit-Log; gleichzeitige
  Gebote müssen genau ein gültiges Ergebnis liefern. Projektregeln 10 (keine selbstständigen Kaufzusagen) und 13 (keine
  Dauerprozesse ohne Freigabe). Betreiberauftrag „Phase D fertigstellen“ ohne Detailvorgaben → Standardwerte, alle in
  `config.yaml` → `auktion` änderbar.
* **Entscheidung:**
  1. Schema **v7** (nur neue Tabellen): `auktionen` (Status `laeuft` → `beendet` → `zugeschlagen`/`abgelehnt`, `laeuft` →
     `abgebrochen`; `demo = 1` per CHECK; Ergebnis `kein_gebot`/`unter_mindestpreis`/`mindestpreis_erreicht`), `gebote`,
     `auktion_protokoll`. Je Anfrage höchstens eine laufende, offene oder zugeschlagene Auktion (partieller UNIQUE-Index).
  2. **Beträge ganze Euro** (CHECK `typeof = 'integer'`, API lehnt Kommazahlen, Texte und Wahrheitswerte ab), **Zeiten UTC**
     als `JJJJ-MM-TTThh:mm:ssZ` (als Text sortierbar).
  3. **Atomares Gebot** unter `BEGIN IMMEDIATE`: Status, Ende, Standort geprüft, Anfrage noch freigegeben, Höchstgebot,
     Mindestschritt (Standard 100 €) und Wiederholungs-ID werden in derselben Transaktion geprüft und geschrieben – auch
     gegen andere Prozesse. Zweite Sicherung in der Datenbank: `UNIQUE(auktion_id, betrag)` (Gebote steigen streng),
     `UNIQUE(auktion_id, nutzer_id, wiederholungs_id)`. Wer führt (Standort), kann sich nicht selbst überbieten.
  4. **Wiederholungs-ID** je Gebotsabsicht (Browser erzeugt sie, behält sie bei Netzfehler/503, verwirft sie bei neuem Betrag):
     gleiche ID + gleicher Betrag = dasselbe Ergebnis ohne zweites Gebot; gleiche ID + anderer Betrag = 409.
  5. **Kein Dienst, kein Timer im Server:** Abgelaufene Auktionen werden bei jedem Zugriff (Liste, Detail, Gebot, CLI)
     idempotent beendet (`UPDATE … WHERE status = 'laeuft'`). Gebot in den letzten 2 Minuten verlängert auf 2 Minuten ab dem
     Gebot. Laufzeit Standard 24 h, erlaubt 1–168 h. Der Countdown im Browser ist nur Anzeige (Restzeit vom Server).
  6. **Mindestpreis** Standard = Preisvorstellung (Inhaber kann ändern oder weglassen); Bieter sehen nur „erreicht ja/nein“,
     nie den Betrag, nie andere Standorte. Da Standorte die Preisvorstellung seit ADR-026 sehen, ist der Standard-Mindestpreis
     für sie erschließbar – wer das nicht will, setzt einen anderen Mindestpreis.
  7. **Zuschlag nur durch den Inhaber** nach dem Ende, ausdrücklich und einmal; auch unter Mindestpreis möglich (Entscheidung
     des Inhabers). Alles ist als **Demo – nicht verbindlich** gekennzeichnet; es entsteht keine Zusage gegenüber Verkäufer
     oder Standort und keine automatische Nachricht. Start, Abbruch und Entscheidung stehen zusätzlich im Anfrage-Verlauf.
  8. **Protokoll:** jede Zustandsänderung und jedes Gebot als Eintrag mit SHA-256 über (vorheriger Hash, ID, Auktion, Zeit,
     Ereignis, Nutzer, Daten). Trigger verhindern UPDATE/DELETE an `gebote` und `auktion_protokoll`. `pruefe_protokoll`
     erkennt Lücken, gebrochene Verkettung, veränderte Einträge und Gebote, die nicht zum Protokoll passen
     (`scout.py auktion pruefen`, Knopf „Protokoll prüfen“).
* **Folgen / offen:** Wer Schreibzugriff auf die Datei hat, kann Trigger entfernen und die **letzten** Einträge samt Kette
  abschneiden; dagegen hilft nur, den letzten Hash außerhalb festzuhalten (CLI zeigt ihn). Echte, verbindliche Auktionen
  (AGB, Widerruf, Zahlungsabwicklung, externe Bieter) sind ausdrücklich nicht Teil von Phase D und brauchen eine eigene
  Entscheidung samt rechtlicher Prüfung. Fahrzeugidentität rückt auf v8.

## ADR-028 – Deal Intelligence: Kalkulation am Gebot, eingefrorene Eingabe, Standorte sehen Max-EK · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase E: Gewinnkalkulation und Max-EK unmittelbar neben dem Gebotsfeld; jede Kalkulation mit Annahmen
  und Unsicherheit reproduzierbar. Architekturregel: Marktwert bleibt eigenständiges Modul. Betreiberentscheidungen 16.10.2026:
  **Standorte und Team sehen die volle Kalkulation** (eigene Filialen); **Provision als Prozent vom Zuschlag**.
* **Entscheidung:**
  1. Neues reines Modul `bewertung/kalkulation.py` auf dem unveränderten Rechner: Szenarien vorsichtig/erwartet/günstig aus der
     Marktspanne (ohne Spanne nur „erwartet“), je Händler-VK, Kosten, Zielmarge, **Max-EK inkl. Provision** (Bisektion, auf 100 €
     abgerundet) und Gewinn beim Betrag (auf 50 € gerundet). Korridor: „sicher bis“ = Max-EK vorsichtig, „Obergrenze“ = Max-EK
     erwartet; Ampel für den Betrag. Risikowert 0–100 als Summe benannter Punkte (Datenlage, Spannbreite, Mängel, Alter, km,
     Gebotshöhe) – eine Faustregel, kein Modell; jeder Punkt wird angezeigt.
  2. **Nachrechenbar:** Die Eingabe enthält alles, wovon das Ergebnis abhängt – Fahrzeug in Rechner-Sicht (ohne PLZ/Ort), die
     tatsächlich passenden Vergleichsangebote (gleiche Filter wie der Rechner, getestet gegen die ganze Datenbank), die wirksamen
     Rechner-Parameter inkl. eingebauter Standards, Provision, Stichtag, Entfernung, Betrag – und wird mit SHA-256 gespeichert.
     Der Rechner bekommt dafür einen optionalen Stichtag (ohne Angabe unverändert). Eine Rechenversion (`E1`) markiert
     Formeländerungen; ältere Kalkulationen gelten dann als „andere Version“ statt still abzuweichen.
  3. Schema **v8**: `kalkulationen` (nur anfügbar, je Gebot höchstens eine). Jedes angenommene Gebot speichert die Kalkulation,
     die der Standort gesehen hat, **in derselben Transaktion**; abgelehnte oder wiederholte Gebote speichern nichts. Scheitert die
     Kalkulation, zählt das Gebot trotzdem (Hilfe, keine Gebotsregel; Fehler im Log).
  4. **Sicht der Standorte:** Kalkulation live zum eingegebenen Betrag, Transport ab Standort-PLZ, Entfernung auf 10 km gerundet
     (genauer muss ein Standort den Wohnort des Verkäufers nicht eingrenzen). Hebt ADR-026 Nr. 4 für Max-EK und Gewinn auf;
     Name, Kontaktdaten, genaue PLZ/Ort bleiben verborgen. Das Team sieht dieselbe Rechnung ab Firmensitz, kann sie speichern und
     jede gespeicherte Kalkulation nachrechnen (`/api/kalkulation/<id>`, `scout.py kalkulation pruefen`).
* **Folgen / offen:** Jede Kalkulation liest alle Vergleichsangebote (wie die bestehende Bewertung) – bei sehr großer Datenbank
  zwischenspeichern. Provision wirkt als Kosten ohne eigene Umsatzsteuer (Annahme). Tatsächlicher EK/VK zur Kalibrierung folgt mit
  Phase F. Nebenbei behoben: Verkaufsanfragen verloren ihre PLZ (Transport immer pauschal) – deren Bewertungen ändern sich.

## ADR-029 – Besichtigung und Abwicklung: ein Vorgang je Kauf, Weg mit Belegen, Plan gegen Ist · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase F: Fahrzeugzustand, Verhandlung, Übergabe, Kaufvorgang und Ergebnisvergleich; Erfolgskriterium
  „nachvollziehbarer Weg vom Gebot zum abgeschlossenen Ankauf“. Projektregel 10 (keine automatischen rechtsverbindlichen Aktionen).
  Betreiberentscheidungen 16.10.2026: **Handy-Besichtigung auch für Verkaufsanfragen**, **gekaufte Inserate automatisch als
  Vorgang**, **Vertragsmuster zum Ausdrucken**, **Vorgang bis zum Verkauf mit Vergleich**.
* **Entscheidung:**
  1. Besichtigungen von Verkaufsanfragen nutzen Tabelle, Rechnung, Fotos, Protokoll und Handy-App der Inserate unverändert;
     Kennung `anfrage-<id>` plus neue Spalte `besichtigungen.anfrage_id` (v9). Grundlage beim Anlegen eingefroren: Bewertung der
     Anfrage, Angebot = bestätigter Demo-Zuschlag oder Erstangebot, Verkäufer (nur Team). Rechte: Inhaber oder Bearbeiter der
     Anfrage statt Halter des Inserats; je Anfrage eine offene Besichtigung; nur offene Anfragen.
  2. **Ankaufsvorgang** entsteht ausschließlich beim Abschluss „gekauft“ (vereinbarter Preis, beide Unterschriften) – in derselben
     Transaktion wie Protokoll und Status (Anfrage bzw. Inserat). Zustände `gekauft → uebergeben → verkauft`, `storniert` nur vor
     der Übergabe und nur durch den Inhaber. Übergabe erst nach bestätigtem Vertrag; Daten nicht in der Zukunft und in zeitlicher
     Reihenfolge. Verlauf und Ist-Kosten nur anfügbar (Trigger), Korrekturen als Gegenbuchung.
  3. **Plan eingefroren:** Bei Anfragen eine neue, nachrechenbare Kalkulation (ADR-028) zum Kaufpreis – Transport ab dem Standort des
     Zuschlags, Provision nur bei Auktion; bei Inseraten die Bewertung zum Kaufzeitpunkt; ohne Bewertung die Grundlage der Besichtigung.
  4. **Weg** je Vorgang: Anfrage/Inserat → Zuschlag mit Gebotskalkulation → Kalkulation zum Kaufpreis (nachgerechnet) → Besichtigung
     und Protokoll → Vertrag → Übergabe/Zahlung → Verkauf, jeweils mit Zeitpunkt und Beleg-Link oder „offen“.
  5. **Vertrag:** druckbares Muster aus Vorgangsdaten (Parteien, Fahrzeug, Preis, Mängel aus dem Protokoll, Felder zum Ausfüllen) mit
     deutlichem Hinweis „Muster ohne Rechtsgewähr“; Sachmängelhaftung bleibt ein Freifeld. Ein Mensch bestätigt die Unterschriften und
     lädt den Scan hoch (PDF/Bild, Inhalt geprüft, nur über den Vorgang abrufbar).
  6. **Ergebnisvergleich** (`bewertung/ergebnis.py`, rein): Plan gegen Ist für Einkauf/Max-EK, Kosten, VK, Gewinn (gleiche Formel
     wie der Rechner, auf 50 € gerundet; vor dem Verkauf „vorläufig“), Standzeit; Übersicht über alle Vorgänge. Nur Anzeige – keine
     automatische Kalibrierung; Parameter werden bewusst in `config.yaml` nachgestellt.
* **Folgen / offen:** Vertragsmuster vor Einsatz juristisch prüfen lassen. Kein Abschluss ohne Netz (wie bisher). Gekaufte Inserate
  ohne Handy-Besichtigung (nur Status „gekauft“) erhalten keinen Vorgang. Fahrzeugidentität rückt auf v10.

## ADR-030 – Phase G0: Voraussetzungen für Skalierung – Härtung, Datenrechte, API-Rahmen · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase G (Skalierung/B2B): „Freigegebene API-Quellen, Echtzeit-Betrieb, mandantenfähige Nutzung und
  optionale Abrechnung. Abhängigkeit: Sicherheitsprüfung, Datenrechte und belastbarer Pilotbetrieb.“ Betreiberentscheidungen
  16.10.2026: erst Voraussetzungen (G0), dann Mandantenfähigkeit, je eigener PR; Echtzeit per SSE; Abrechnung nur als
  Nutzungszähler; **keine** konkrete API-Quelle anbinden, nur den Rahmen. Eine unabhängige Sicherheitsprüfung (Rolle
  `qa-security-reviewer`) urteilte: interner Tailnet-Betrieb mit Auflagen vertretbar, öffentlicher oder mandantenfähiger
  Betrieb **abgelehnt**, bis u. a. Login-Bremse, Proxy-Erkennung, Bearbeiterrecht und Löschweg umgesetzt sind.
* **Entscheidung:**
  1. **Härtung ohne neue Dienste** (`wmscout/web/sicherheit.py`): Login-Bremse im Speicher je (Gerät, Name) und je Gerät (429),
     gleiche Rechenzeit für unbekannte Namen, Login nur als JSON mit Origin- und Sec-Fetch-Site-Prüfung, Sicherheits-Header
     (CSP – vorerst mit `'unsafe-inline'` –, `frame-ancestors 'none'`, nosniff, no-referrer), kein Server-Versionskopf,
     Lesezeitlimit 30 s, Host-Prüfung **vor** dem Lesen des Inhalts, negative/ungültige Längen → 400.
  2. **„Lokal“ heißt wirklich lokal:** Host-Kopf und Loopback-Absender und **keine** Proxy-Kopfzeilen. `X-Forwarded-*` zählt nur
     mit `app.vertrauter_proxy: true`; `app.nur_https` erzwingt das Secure-Cookie.
  3. **Bearbeiterrecht:** Eine Verkaufsanfrage mit Bearbeiter ändert nur dieser oder der Inhaber (Prüfung und Änderung in einer
     Transaktion). Notizen bleiben teamweit frei (bestehender Ablauf); Lesen bleibt firmenweit – Trennung zwischen Firmen ist
     Aufgabe von G2.
  4. **Datenrechte:** Register `docs/DATENRECHTE.md`; **Widerruf** einer Verkaufsanfrage (Inhaber, Web und CLI) anonymisiert den
     Verkäufer (nur ohne weitere Anfrage), löscht Freitexte, Notizverlauf, Fotos samt Dateien und schwärzt die Besichtigung,
     bricht laufende Auktionen ab und nimmt die Freigabe zurück. Mit Ankaufsvorgang – auch storniert – wird verweigert
     (Aufbewahrungspflichten, Einzelfall klären).
     Fotos verlieren beim Speichern EXIF/GPS (JPEG, PNG); Kalkulationen frieren Freitexte ohne Kontaktdaten ein; der
     Offline-Speicher der Handy-App nimmt nur eine Positivliste auf und wird bei 401 geleert; Links aus fremden Seiten nur http(s).
  5. **API-Rahmen** `wmscout/quellen/api_rahmen.py`: `ApiQuelle` ist standardmäßig nicht freigegeben, verlangt den Zugang per
     Umgebungsvariable, nur HTTPS, Kontingent je Lauf, Pause, bricht bei 401/403/429 **ohne Wiederholung** ab. Keine Quelle aktiv.
  6. **Pilotbetrieb** nur nach `docs/PILOTBETRIEB.md` (TLS-Proxy, HSTS, Ratenlimits, verschlüsselte Sicherungen außer Haus,
     pip-audit, Datenschutzerklärung, Löschfristen).
* **Folgen / offen:** Bremse beginnt nach Neustart neu (Proxy-Limits ergänzen). Offen: CSP-Nonce, Leerlauf-Zeitlimit der
  Sitzung, CSRF-Token je Sitzung, Audit-Protokoll (Schema v10) und Rechte je Ankaufsschritt (G0b), Auskunft Art. 15.

## ADR-031 – G0b: Audit-Protokoll, Leerlauf der Sitzung, Rechte je Ankaufsschritt · vorgeschlagen (16.10.2026)

* **Kontext:** Restpunkte der Sicherheitsprüfung aus ADR-030, die Phase F voraussetzten (M6, N16, Audit, Dokument-Download).
  Für einen Pilot mit mehreren Personen muss nachvollziehbar sein, wer Verkäuferdaten gelesen oder geändert hat.
* **Entscheidung:**
  1. Schema **v10** (additiv): Tabelle `audit` (nur anfügbar per Trigger) und Spalte `sitzungen.zuletzt`.
  2. **Zentral im Router** statt in jeder Route: jede Änderung (POST), Anmeldung/Abmeldung und jedes Lesen von Personendaten
     (Anfrage-Detail und -Fotos, Besichtigung, Protokoll, Fahrzeugsicht einer Anfrage, Ankauf, Vertrag, Dokumente, Audit selbst)
     – auch abgelehnte Zugriffe. Gespeichert werden nur Metadaten, nie Inhalte, Passwörter oder Kontaktdaten. Ohne angelegte
     Nutzer kein Protokoll. Die Antwort wird zwischengespeichert; der Eintrag wird **vor** dem Senden festgeschrieben – außerhalb
     der globalen Sperre und jeder App-Transaktion, über eine **eigene Verbindung** (autocommit, 3 s Wartezeit). Er kann die
     Transaktion der App nie offen lassen und läuft nie parallel zur nächsten Anfrage desselben Clients; scheitert er bei
     gesperrter Datenbank, steht das im Log (bei 503 entfällt er).
     Listen (z. B. `/api/verkaufsanfragen`, `/api/heute`) werden bewusst nicht protokolliert (Rauschen).
  3. **Leerlauf:** Sitzung endet nach `app.sitzung_leerlauf_stunden` (Standard 72) ohne Nutzung, spätestens nach 30 Tagen;
     `zuletzt` wird höchstens alle 5 Minuten geschrieben. Sitzungen aus der Zeit vor v10 zählen ab der ersten Nutzung.
  4. **Ankaufsschritte** (Vertrag, Übergabe, Kosten, Verkauf, Dokument; Storno weiter nur Inhaber) nur für Inhaber, Zuständigen
     der Besichtigung oder Bearbeiter der Anfrage/des Inserats – dieselbe Regel wie für das Schreiben der Besichtigung.
     Lesen bleibt teamweit (Trennung je Firma: G2).
  5. **Hochgeladene Dokumente** werden mit `Content-Security-Policy: sandbox` ausgeliefert, PDFs nur als Download.
* **Folgen / offen:** Das Protokoll wächst ohne Löschung – Aufbewahrungsfrist und Wartungsschritt festlegen. Kein Manipulationsschutz
  über Hash-Kette (anders als das Auktionsprotokoll); wer Dateizugriff auf die Datenbank hat, kann Trigger umgehen.

## ADR-032 – G1: Echtzeit per Server-Sent Events, Nutzungszähler aus vorhandenen Daten · vorgeschlagen (16.10.2026)

* **Kontext:** 3.0-Analyse Phase G „Echtzeit-Betrieb“ und „optionale Abrechnung“. Betreiberentscheidungen 16.10.2026:
  **Live per SSE**, **nur Nutzungszähler** (keine Abrechnung). Bisher fragten Seiten in Abständen ab (Händlerportal alle 20 s,
  Team-Übersicht alle 60 s, `/anfragen` und `/ankaeufe` gar nicht).
* **Entscheidung:**
  1. **SSE statt WebSocket:** Standardbibliothek reicht (`http.server`), läuft durch `tailscale serve` und übliche Proxys, der
     Browser verbindet selbst neu (`EventSource`, `Last-Event-ID`). Endpunkt `/api/ereignisse` mit derselben Anmeldung und
     Positivliste wie jede Route; ohne globale Sperre offen gehalten.
  2. **Nur „etwas hat sich geändert“:** Ereignis = Art (`anfrage`, `auktion`, `ankauf`, `besichtigung`, `team`, `suchlauf`) und
     beim Team die ID – nie Inhalte. Die Seite lädt über ihre rechtegeprüften Routen nach. Standorte erhalten nur `auktion` ohne
     ID. Gemeldet wird nach jedem erfolgreichen POST (Status < 400) aus dem Pfad und am Ende eines Suchlaufs.
  3. **Im Speicher, begrenzt:** Ringpuffer der letzten 500 Ereignisse; fällt etwas heraus, meldet der Server „alles“ (neu laden).
     Je Verbindung ein Thread – daher höchstens 4 je Zugang und 40 insgesamt (`app.live_max_*`), Lebensdauer 5 min (danach neue
     Verbindung, Anmeldung wird neu geprüft), Lebenszeichen alle 15 s.
  4. **Rückfall bleibt:** Das Abfragen in Abständen bleibt bestehen und pausiert nur, solange die Live-Verbindung steht. Eingaben
     werden nicht überschrieben (Detail lädt nur nach, wenn dort kein Feld den Fokus hat).
  5. **Nutzungszähler** (`wmscout/nutzung.py`, `scout.py nutzung`, `/api/nutzung` nur Inhaber) zählt je Monat aus den vorhandenen
     Tabellen (Anfragen, Auktionen, Gebote, Kalkulationen, Besichtigungen, Ankäufe, Verkäufe) und dem Audit-Protokoll (Anmeldungen,
     Zugriffe, Änderungen, aktive Nutzer) – keine eigene Zähltabelle, die auseinanderlaufen könnte; keine Preise, keine Rechnung.
* **Folgen / offen:** Mehrere App-Prozesse teilen keine Ereignisse (es läuft ohnehin nur einer). Mit Mandanten (G2) müssen
  Ereignisse und Zähler je Mandant getrennt werden. Handy-App (`/m`) nutzt Live noch nicht (offline-orientiert).

## ADR-033 – G2: Mandanten als getrennte Datenbanken, Auswahl allein über den Hostnamen · vorgeschlagen (17.10.2026)

* **Kontext:** 3.0-Analyse Phase G „mandantenfähige Nutzung“; Betreiber: „Beides nacheinander“ (G0, dann Mandanten). Die
  Sicherheitsprüfung (ADR-030) lehnte mandantenfähigen Betrieb ab, solange alle Daten in einer Datenbank ohne Trennung liegen
  (Befund M7: Lesen firmenweit).
* **Entscheidung:**
  1. **Eine Datenbank je Mandant** statt `mandant_id` in jeder Tabelle: 257 SQL-Aufrufe (`execute`, Stand G2) müssten sonst einzeln und für immer
     korrekt gefiltert werden; ein einziger vergessener Filter wäre ein Datenleck. Getrennte Dateien trennen auch Fotos,
     Sicherungen, Audit, Live-Ereignisse (G1) und Nutzungszähler – ohne Schemaänderung und ohne Migration bestehender Daten.
  2. Ordner `mandanten/<kennung>/` (konfigurierbar: `mandanten.ordner`) mit `mandant.yaml` = Abweichungen von `config.yaml`.
     Datenpfade erzwingt das Programm; `ausgabe`, `sicherung`, `import` in `mandant.yaml` sind verboten. Adresse und Versandwege
     (WhatsApp, E-Mail) werden nicht geerbt.
  3. **Hostname wählt den Mandanten** (vor jeder anderen Verarbeitung, unbekannt → 403 ohne Lesen des Inhalts und ohne Nennung
     der Mandanten). Jeder Hostname gehört zu genau einem Mandanten (sonst kein Start). `127.0.0.1` nur mit `--lokal KENNUNG`.
     Ein Prozess, je Mandant ein eigener Kontext (Verbindung, Sperre, Bremse, Live, Audit, Suchlauf).
  4. Kommandozeile mit `--mandant KENNUNG` für alle Befehle; `mandant anlegen|liste|nutzung`.
  5. Einzelbetrieb unverändert (ohne `--mandanten` keine Wirkung).
* **Folgen / offen:** Keine gemeinsame Marktdatenbasis (jeder Mandant sucht selbst). Kein Administrator in der Oberfläche.
  Viele Mandanten in einem Prozess nicht vorgesehen (Threads je Live-Verbindung). Bestehende Daten werden nicht verschoben.

## ADR-034 – Phase-1-Abschluss: Grenzen von P1-05, Bewertung ohne Datenbank, lokale Konfiguration, nur Python 3.13 · vorgeschlagen (17.10.2026)

* **Kontext:** Betreiber „Schließe Phase 1 komplett ab“ mit den Entscheidungen F9 „Nur 3.13“, F10 „Befehl + einstellbare Frist,
  Standard aus“ und F11 „Lesen frei, Schreiben nur zuständig“.
* **Entscheidung:**
  1. **P1-05 eng statt Umbau:** Der einzige Netzaufruf, der während einer Web-Anfrage unter der globalen Sperre lief, war die
     WhatsApp-Nachricht bei Zuweisung einer Besichtigung (bis 20 s). Sie läuft jetzt in einem eigenen Thread
     (`WhatsAppCloud.sende_im_hintergrund`). E-Mail und die WhatsApp-Meldung neuer Treffer liefen schon im Suchlauf-Thread.
     Eine Datenbankverbindung je Thread mit Sperre nur um Datenbankzugriffe wird **nicht** gebaut: SQLite schreibt ohnehin
     nacheinander, WAL (ADR-013) entkoppelt Lesen und Schreiben, und der Umbau berührt jede Route. Das Akzeptanzkriterium
     „langsamer WhatsApp-Aufruf blockiert keine andere Anfrage“ ist erfüllt und getestet. Die Bewertung aller Inserate unter
     der Sperre (Q10) bleibt bis P3-07 bestehen.
  2. **Bewertung ohne Datenbank (ADR-015, P1-08):** Fachbegriffe (Status, Herkunft der Fahrzeugart) in `wmscout/domaene.py`;
     `bewerte_zeilen` rechnet auf Listen, `bewerte_alle` liest nur noch die Datenbank. `datenbank.py` stellt die Namen für
     bestehende Importe weiter bereit.
  3. **Lokale Konfiguration (P1-09):** `config.local.yaml` neben `config.yaml` (ignoriert, auch `*.local.yaml`) wird
     abschnittsweise zusammengeführt, einzelne Werte und Listen werden ersetzt. Passwörter für Zugänge nie als Argument:
     Abfrage am Terminal oder `SCOUT_NEUES_PASSWORT` für Skripte.
  4. **Nur Python 3.13 (F9, P1-10):** `pyproject.toml`, Installer und Hinweis in `scout.py` einheitlich; Lock-Dateien für 3.13
     ohne Versionswechsel neu erzeugt. Eine vorhandene `.venv` mit älterem Python wird beim nächsten Start neu angelegt.
  5. **Ohne Erstzulassung keine Beträge (P1-12):** Der Angebotspreis ist kein Marktwert. Max-EK und Erstangebot gibt es erst mit
     manuell angegebenem Marktwert; die Besichtigung eines solchen Inserats verlangt ihn.
  6. **Versionsprüfung beim Speichern der Besichtigung (P1-07):** Ein Gerät mit veraltetem Stand überschreibt nichts still,
     sondern erhält 409 mit dem aktuellen Stand und entscheidet selbst.
  7. **Rollen (F11, P1-15):** `docs/ROLLEN.md`. „Gekauft“ direkt, Suchlauf und Seitenimport nur Inhaber.
  8. **Verkäuferdaten in Inseraten (F10, P1-14a):** Befehl `scout.py inserat anonymisieren` und optionale Frist
     `datenschutz.inserate_anonymisieren_nach_monaten` (Standard 0 = aus); gekaufte Fahrzeuge nie (Aufbewahrungspflichten).
     Umfang wie der Widerruf einer Anfrage (ADR-030): auch Team-Notiz, Eingaben vor Ort (FIN, Kennzeichen), Fotos der
     Besichtigung; Inserate mit offener Besichtigung lässt die Frist aus. Die Frist läuft nach Suchlauf, Seitenimport und beim
     Start der App, weil Verkäufernamen fast nur über den Seitenimport kommen; ein Fehler dabei bricht nichts ab.
  9. **Ziel nach der Anmeldung prüft der Server** (`sicheres_ziel`): nur Pfade auf diesem Server, ohne „//“, „\“, Punkt-
     Segmente und Steuerzeichen. Die frühere Prüfung im Browser ließ „/.//fremd“ durch (QA-Befund N3).
  10. **Handy-Offline-Speicher (P1-14b):** Abgeschlossene Besichtigungen markiert der Server (`X-Scout-Offline: nein`), der
      Service Worker speichert sie nicht; Unterschriften und Verkäuferangaben liefert die Handy-API nie. Offline bleiben bewusst
      `/api/ich` (Start ohne Netz) und Fotos offener Besichtigungen.
  11. **Planen ändert keine Version:** Termin, Adresse und Zuständiger gehören nicht zu den Eingaben vor Ort; ein verschobener
      Termin löst auf dem Handy keinen Versionskonflikt aus.
* **Folgen / offen:** Fristen legt der Betreiber mit dem Datenschutzbeauftragten fest (`docs/DATENRECHTE.md`, Standard aus).
  Q10 bleibt bis P3-07. CSRF-Token je Prozess statt je Sitzung (Schutz über SameSite, JSON-Pflicht, Origin-Prüfung).

## ADR-035 – Push-Eingänge: Eingang.lese → Lesung → Importer.importiere · gilt (17.10.2026)

* **Kontext:** Phase 2 bringt zwei weitere Eingänge, die der Nutzer selbst beliefert (URL + eingefügter Text, P2-05; E-Mail-
  Suchbenachrichtigung, P2-06). Es gab drei Schreibwege: Suchlauf (`speichere_treffer`, Kanal `suche`), gespeicherte Seiten
  (`_speichere_seite`, Kanal `manuell`) und den `EreignisSpeicher` (`api`/`stream`/`email`). Die Plattform-ID war uneinheitlich:
  `mobile.de` im Code und in den echten Daten, `mobilede` in Tests des Ereigniseingangs.
* **Entscheidung:**
  1. **Ein Schreibweg für Push-Eingänge:** `Eingang.lese(Rohdaten) -> Lesung` (rein, ohne Datenbank und Netz,
     `wmscout/eingang/basis.py`), gespeichert wird nur über `Importer.importiere(lesung, kanal)`. Der Seitenimport ist der erste
     Eingang (`SeitenEingang`, Kanal `manuell`); `importiere_seiten` bleibt Dateischleife mit Verschieben und Grenzen.
  2. **`Lesung` statt reiner Inserat-Liste:** Die Herkunft der Fahrzeugart (Art-Filter der Suchseite, Haupttabelle, je Treffer
     bestätigte Kategorie bei mobile.de, ADR-020/021/022) muss bis zum Speichern mitgehen; sonst würde ein neuer Kanal die
     Regeln „bestätigt/vorläufig“ und „gewerblich“ umgehen.
  3. **Ereignisse nur für `api`/`stream` – in beide Richtungen erzwungen:** `importiere_ereignis`/`EreignisSpeicher` bleibt Weg
     der freigegebenen automatischen Kanäle und weist `email`/`manuell` ab (ValueError, QA-Befund B1). `importiere` weist
     `api`/`stream` ab und schreibt über `speichere_treffer` wie der Seitenimport.
  4. **Kanonische Namen in `wmscout/domaene.py`:** Plattformen `kleinanzeigen` (IDs ohne Präfix), `mobile.de` (`md-`), vorgemerkt
     `autoscout24` (`as-`); Kanäle `stream`, `api`, `email`, `manuell` (Push: `email`, `manuell`). Unbekannte Plattform, Kanal oder
     nicht zur Plattform passende Anzeigen-ID → `ValueError` vor dem Schreiben. Gespeicherte Werte ändern sich nicht.
  5. **Zweite Beobachtung ohne inhaltliche Änderung wird nicht protokolliert** (wie ADR-024): dasselbe Inserat über zwei Kanäle
     ist eine Zeile in `inserate` und `anzeigen`; `beobachtungen`/`preis_historie` erhalten nur Änderungen.
  6. **Zeitpunkt:** Gespeichert wird der Zeitpunkt, zu dem der Scout das Angebot kennt (Import), nicht der Eingangszeitpunkt
     der Rohdaten. `Rohdaten.empfangen_am` (mit Zeitzone) bleibt für Meldungen und Kanäle mit eigenem Datum (E-Mail-Datum,
     P2-06), das dort als Angabe am Inserat erscheint; eine rückdatierte Historie gibt es nicht (QA-Befund B2).
* **Folgen / offen:** P2-05 und P2-06 liefern nur noch einen `Eingang` (Parser/Normalisierung); sie schreiben nie selbst.
  Der Kanalwert wird nicht aus dem Eingang geraten, der Aufrufer nennt ihn. `Datenbank.speichere_treffer` prüft Plattformen nicht
  selbst (Suchlauf und Altbestand); die Prüfung sitzt im `Importer`. Ein E-Mail-Eingang braucht eigene Regeln, was er aus
  Benachrichtigungen lesen darf (ADR-010: verlinkte Anzeigen werden nicht nachgeladen).

## ADR-036 – Quellen und Eingänge schaltbar: Freigabe im Code, Aktivierung in Tabelle bzw. config · gilt (17.10.2026)

* **Kontext:** Die Code-Freigabe (`Quelle.freigegeben`) wurde geprüft, aber ein Suchlauf mit der Standard-Konfiguration endete
  deshalb mit einem Fehlertext „nicht freigegeben“. Die Spalte `quellen.aktiv` (Schema v4) las nur der `EreignisSpeicher` für
  `api`/`stream`; Seitenimport und der kommende Text-/E-Mail-Eingang (P2-05/P2-06) hatten keinen Schalter.
* **Entscheidung:**
  1. **Zwei Ebenen, strikt getrennt:** Die *Freigabe* (Nutzungsrechte, Regel 12) steht im Code und ändert nur ein Entwickler nach
     Klärung (`docs/SOURCES.md`) – eine bewusste Code-Änderung, die der Betreiber per Pull Request prüft. Der *Schalter* gehört dem
     Betreiber: für Pull-Quellen in der Tabelle `quellen` (`python scout.py quellen an|aus KENNUNG`), für Eingänge in
     `config.yaml → eingaenge → seiten|text|email → aktiv`. Eine Pull-Quelle läuft, sobald sie im Code freigegeben ist und in
     `suchen` steht; abgeschaltet wird sie mit `quellen aus`. `quellen an` **und** `quellen aus` werden für nicht freigegebene
     Quellen abgelehnt (Exit ≠ 0, Tabelle unverändert): „an“ wäre eine Umgehung, „aus“ ließe sich als 0/0 nicht von „nicht
     entschieden“ unterscheiden, und eine spätere Code-Freigabe liefe ohne Zustimmung. Ein von Hand gesetztes `aktiv=1` gibt nichts frei.
  2. **Übersprungen ist kein Fehler:** `Importer.lauf` prüft je Quelle vor dem Abruf und meldet `uebersprungen`
     (`[{quelle, grund}]`, Grund „nicht freigegeben“ oder „deaktiviert“, eine Meldung je Quelle). `fehler` bleibt Auffälligkeiten
     (Layout, Sperre, Netz) vorbehalten und ist ohne solche `None`. Der Detailabruf des Suchlaufs betrifft nur laufende Quellen;
     `Importer.details()` ohne Einschränkung sperrt nicht freigegebene Quellen weiterhin mit `QuellenFehler`.
  3. **Fehlende Zeile bzw. Seed-Zeile = „nicht entschieden“:** Schema v4 legt `kleinanzeigen` mit freigegeben=0, aktiv=0 an, das
     ist von einem ausdrücklichen „aus“ nicht zu unterscheiden. Deshalb entscheidet bei fehlender oder 0/0-Zeile der Code
     (freigegeben ⇒ läuft), damit bestehende Installationen und Testquellen weiterlaufen; `quellen an|aus` schreibt die
     Entscheidung (nur für im Code freigegebene Quellen) mit `freigegeben` = 1, `aktiv` = Wunsch und `zugriffsart` der Klasse, danach
     gilt die Tabelle. Keine Schemaänderung.
  3a. **Push-Kanäle `api`/`stream`** (`EreignisSpeicher`): Tabelle (`freigegeben`, `aktiv`, Zugriffsart `api`) *und*, wenn für die
     Plattform ein Adapter in `quellen.QUELLEN` steht, dessen Code-Freigabe. Pull-Suchlauf: Code + Tabelle.
  4. **Eingänge:** Hilfsfunktion `schalter.eingang_aktiv(cfg, name)`; Standard seiten=an, text=an, email=aus; ungültige Werte
     scheitern beim Start (`scout.py`), wie `datenschutz`. Abgeschaltet liest der Eingang nichts, Dateien bleiben liegen
     (CLI: Hinweis, Exit 0; API: 409 mit `grund: deaktiviert`, die Oberfläche zeigt den Hinweis 15 s als Warnung;
     `Importer.importiere_seiten` wirft `EingangDeaktiviert`). Die Konfiguration wird beim Start jedes Kontexts geprüft
     (`scout.py`, `Kontext`, bei Mandanten `mandanten.alle` mit Mandantenname im Fehler).
  5. **Detailabruf im Suchlauf:** `Datenbank.ohne_details(limit, kennungen)` filtert nach laufenden Quellen schon in SQL, Zeilen
     gesperrter Quellen verbrauchen das LIMIT nicht und werden nicht mitgezählt.
* **Alternativen:** Schalter nur in `config.yaml` (zwei Wahrheiten neben `quellen`, Tabelle bliebe tot); Seed-Zeile per
  Migration ändern (Schemaänderung ohne Not, bestehende Datenbanken behielten die alte Zeile); alle Fehler weiter als `fehler`
  melden (die Standard-Konfiguration endete rot).
* **Folgen / offen:** Der Report von `scout.py lauf` (und die CSV) weist übersprungene Quellen nicht aus – sie stehen nur im Log
  und in der Meldung des App-Suchlaufs (QA-Befund F8, bewusst offen). Das CLI schreibt `config.yaml` nicht; Eingänge werden von Hand (oder `config.local.yaml`) geschaltet.
  P2-05 prüft vor dem Text-Eingang `eingang_pruefen(cfg, "text")`, P2-06 für `email`. Die Oberfläche zeigt `uebersprungen` nur
  in der Meldung des App-Suchlaufs.

## ADR-037 – E-Mail-Eingang (P2-06): Links nie abrufen, URL aus der ID, Absender nur zur Erkennung · gilt (17.10.2026)

* **Kontext:** Suchagent-Benachrichtigungen von Kleinanzeigen und mobile.de sind ein zulässiger Eingangskanal (ADR-010, ADR-035). Der Betreiber liefert sie als
  `.eml`; echte Beispiel-Mails folgen später (F3). Mails enthalten Personen- und Trackingdaten (Empfänger-Adresse, Nutzerkennungen in Links).
* **Entscheidung:**
  1. **Nur lesen, was in der Mail steht.** Links werden mit `urllib.parse` zerlegt, auch Weiterleitungs-/Tracking-Links (Ziel in Parameter oder Pfad), aber **nie
     abgerufen**; verlinkte Anzeigen werden nicht nachgeladen, Detailabruf gibt es für `email` nicht.
  2. **Die URL wird aus der ID neu gebildet.** Aus einem Link zählt nur die Anzeigen-ID; gespeichert wird die kanonische Detail-Adresse. Host muss zur Plattform gehören
     (Domain oder Subdomain, auch beim äußeren Weiterleitungs-Host), Schema nur http(s); alles andere wird verworfen und gezählt. Bilder werden nicht übernommen.
  3. **Absender nur zur Erkennung.** `Mail` hält nur die Absender-Domain und das Datum; Adressen von Absender und Empfänger werden weder gehalten noch gespeichert,
     der Betreff wird nicht einmal dekodiert. Eine Mail ohne passenden Absender wird (weitergeleitet) am Inhalt erkannt; Mehrdeutiges ist „unbekannt“.
  4. **Grenzen statt Hoffnung** (QA-Runde 1: mit `policy.default` und ungebremstem Lesen genügten einzelne Mails für Minuten, Gigabytes und RecursionError). Vor dem Parsen:
     5 MB je Mail, Kopfbereich ≤ 64 KB, Kopfzeile ≤ 8 KB, ≤ 500 MIME-Trennzeilen; beim Lesen: `policy.compat32` (Kopfzeilen bleiben Zeichenketten; Absender per
     `parseaddr`, Datum per `parsedate_to_datetime` auf gekürzten Werten), ≤ 200 Teile, ≤ 20 multipart-Ebenen, nur `text/plain`/`text/html`, Anhänge ignoriert; HTML: ≤ 200 000
     Elemente, ≤ 100 Ebenen, ≤ 200 Anzeigen, Textzeilen > 4 500 Zeichen verworfen (gezählt), alle Abfragen einer Mail teilen ein Budget von 3 Mio. Knotenbesuchen. Überschreitung
     ist ein `MailFehler` (Datei nach `fehlerhaft/`) bzw. ein Hinweis. Gemessen (Wiederholung der QA-Angriffe): jeweils unter 3 s und unter 150 MB. Eigener schlanker HTML-Baum
     (`htmlbaum.py`, nur lesend): Er war beim Bauen nur etwa 1,6-mal so schnell wie BeautifulSoup; der eigentliche Engpass war `html_bloecke` (Block je Link statt je Anzeige) und ist
     dort behoben. Behalten wurde er, weil Blockgrenzen ohne Verändern des Baums entstehen (Bs4 wird beim Einfügen quadratisch langsam).
  5. **Anbieter unbekannt, Art höchstens vorläufig.** Mails nennen privat/gewerblich nicht verlässlich; `gewerblich` bleibt leer. Die Art folgt den Titel-Regeln des
     Seitenimports. Erkannt, aber ohne Treffer ist „Layout verdächtig“, mit weniger als 50 % Preis oder Titel „Layout teilweise verdächtig“ (Datei nach `nicht_erkannt/` bzw. Hinweis).
     **Lieber kein Preis als ein falscher:** Preis und VB nur aus einer eigenen Preiszeile; nie aus dem Titel, nie bei mehreren Beträgen, Durchgestrichenem, Neupreis/Miete/Raten;
     „VB“ ist unbekannt (None), wenn es keine Preiszeile gibt, und überschreibt dann nichts. Gesuche/Ankaufsanzeigen und Empfehlungsblöcke („Ähnliche Anzeigen“) werden nicht
     gespeichert. Die Gesuchsregeln entsprechen vorerst `eingang/text.py` (P2-05); die Vereinheitlichung folgt als eigenes Paket (A1).
  6. **Eine Mail ergänzt nur.** Bei vorhandener Zeile bleiben Adresse, Titel, Ort, km, EZ, Marke und VB unverändert (`Importer._mail_ergaenzt_nur`); leere Felder werden gefüllt, der Preis
     läuft über den normalen Preis-/Historienweg. So erzeugt der Wechsel Seite → Mail → Seite keine „geaendert“-Beobachtungen, und ein gekürzter Titel beeinflusst die Bewertung nicht.
  7. **Löschung über die vorhandene Datenschutz-Frist** für alles, was der Scout ablegt: `eingelesen/<Datum>/`, `nicht_erkannt/` und `fehlerhaft/` (unlesbare oder zu große Mails werden dorthin
     verschoben; die Änderungszeit wird beim Ablegen auf „jetzt“ gesetzt). Maßgeblich ist das spätere von Datumsordner (ISO-Name) und Änderungszeit. Verknüpfungen werden nie gelesen,
     verschoben oder verfolgt. Noch nicht eingelesene Mails direkt in `import/email/` werden nicht gelöscht, aber nach Ablauf der Frist gemeldet (Protokoll, Kommandozeile, App).
  8. **Eingang schaltbar, Standard aus (ADR-036):** `eingaenge.email.aktiv`; `Importer.importiere_mails` wirft `EingangDeaktiviert`, Kommandozeile (`import --mails`) und App
     (`POST /api/import/mails`, nur Inhaber, 409 „deaktiviert“) prüfen vorher und legen den Ordner dann nicht an.
  9. **Abnahme an echte Mails geknüpft.** Die Parser sind mit nachgebildeten Mails geprüft; bis der Betreiber anonymisierte Originale liefert (F3), gilt der Kanal als Gerüst
     (`docs/QUELLEN.md` Abschnitt 6). Kein IMAP (P2-07).
* **Folgen / offen:** Das Mail-Datum steht als `details["mail_datum"]` am `Inserat`, wird bei Such-Lesungen aber noch nicht gespeichert (kein Feld; ADR-035 Nr. 6 bleibt offen).
  Der Seitenimport hat dieselbe Lücke bei `import/eingelesen/` (Backlog). `Inserat.vb` kann jetzt `None` sein (unbekannt, überschreibt beim Update nichts). Die Absender-Domain als
  Erkennungsmerkmal ist fälschbar; das ist hier unkritisch, weil nur der Nutzer eigene Dateien einlegt und die Adresse aus der ID neu gebildet wird.

## ADR-038 – Text-Import: nur sichere oder eingetragene Preise; gespeicherte Angaben anderer Kanäle bleiben · gilt (17.10.2026)

* **Kontext:** Der Text-Import (P2-05, ADR-035) liest Felder per Heuristik aus kopiertem Freitext. Ein „geschätzter“ Preis aus dem Fließtext
  („Motor bei 2.500 € überholt“, „Restschuld 15.000 €“) wurde wie ein bestätigter gespeichert, überschrieb den Preis der Anzeige, erzeugte
  eine Preissenkung und landete in Ampel, Erstangebot, Anschreiben und Nachfass-Text. Ebenso überschrieben grob gelesene Titel, Beschreibung,
  Marke, Kilometer und Erstzulassung die Werte einer gecrawlten oder aus einer gespeicherten Seite gelesenen Anzeige.
* **Entscheidung:**
  1. **Preis nur sicher oder eingetragen.** Sicher = Betrag mit VB/VHB-Bezug, Preis-Label oder allein in einer Zeile, genau ein Wert. Sonst
     trägt der Nutzer den Preis im Formular ein (`preis`/`vb` der API). Ohne beides wird ohne Preis gespeichert; ein vorhandener Preis
     bleibt (keine Preisänderung); die Antwort meldet `preis_status` (`text`, `eingetragen`, `unsicher`, `fehlt`) und die Oberfläche lässt die
     Eingaben stehen. Lieber kein Preis als ein falscher: Ampel, Erstangebot und Anschreiben entstehen nur aus bestätigten Preisen.
  2. **Gespeicherte Angaben anderer Kanäle bleiben:** der Text füllt nur leere Felder (`Lesung.nur_leere_felder`, `Datenbank.speichere_treffer(…,
     nur_leere=True)`); der Preis läuft wie immer über die Preis-/Beobachtungshistorie. Werte aus einem früheren Text-Import darf ein neuer
     Text ersetzen (Markierung in `details_json`, keine Schemaänderung); jeder andere Schreibweg entfernt die Markierung.
  3. **Widerspricht die Marke** im Text der geschützten Anzeige, wird kein Preis aus dem Text übernommen.
* **Alternativen:** geschätzten Preis mit Warnhinweis speichern (verworfen: der Hinweis erreicht Ampel, Anschreiben und Nachfass nicht);
  Herkunft je Feld in einer neuen Spalte (verworfen: Schemaänderung); Text-Import ohne Überschreibschutz (verworfen, siehe Kontext).
* **Folgen / offen:** Wer den Preis nicht einträgt, bekommt eine Anzeige ohne Preis (graue Ampel) – gewollt. Zeilen aus dem Text-Import
  vor dieser Entscheidung tragen keine Markierung und gelten als geschützt. Die Erkennung des sicheren Preises bleibt Heuristik über
  nachgebaute Texte; echte Anzeigen können anders aufgebaut sein.
