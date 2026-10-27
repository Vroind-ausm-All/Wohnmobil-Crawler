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

## ADR-011 – Fahrzeug, Inserat und Ankauf trennen · vorgeschlagen (Phasen 2–3) · teilweise ersetzt durch ADR-039

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
  Offen: Gelten alte „kontaktiert“-Einträge als bestätigt? (Betreiberfrage) – bis zur Antwort bleiben sie unverändert
  (Status unverändert; im Kontaktverlauf als „Altbestand“ gekennzeichnet, ADR-044).
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

## ADR-039 – Fahrzeugidentität additiv (Schema v11); `anzeigen` bleibt Arbeitstabelle; Ankaufsstatus vorerst am Inserat · gilt (18.10.2026)

* **Kontext:** ADR-011 und ARCHITECTURE §8 planten für Phase 3 eine Umbenennung von `anzeigen` mit lesender View und den
  Ankaufsstatus am Fahrzeug („Version 5“). Seit ADR-024/035 ist `anzeigen` aber der aktive Schreibweg aller Kanäle (Suche,
  Seiten-, Text-, Mail-Import, Status, Team), und die Versionen 5–10 sind anderweitig belegt.
* **Entscheidung (Betreiber 18.10.2026):**
  1. Schema v11 legt nur `fahrzeuge` (Kennung, Herkunft `migration`/`eingang`, Zeitpunkt UTC) und `inserate.fahrzeug_id` an.
     Jedes vorhandene Inserat bekommt genau ein eigenes Fahrzeug; neue Inserate bekommen es per Trigger
     `inserate_fahrzeug_anlegen`. Es wird nichts automatisch zusammengeführt.
  2. `anzeigen` bleibt eine Tabelle – keine Umbenennung, keine View.
  3. Der Ankaufsstatus bleibt in `anzeigen.status`/`bearbeitung`. Mit P3-02 wird ein Fahrzeugstatus beim Lesen aus den
     Inseraten eines Fahrzeugs abgeleitet; ein gespeicherter Status am Fahrzeug bekommt nach P3-06 eine eigene Entscheidung.
  4. Rückweg: die automatische Sicherung `vor-v11` zurückspielen (danach Geschriebenes geht verloren); kein Rückstufungsskript.
  5. Die Gleichheit `fahrzeuge.id = inserate.id` gilt nur für den Altbestand; Code greift immer über `inserate.fahrzeug_id` zu.
* **Alternativen:** Status sofort ans Fahrzeug (hohes Risiko über alle Statuspfade, kein Nutzen bei 1:1); View `anzeigen` mit
  INSTEAD-OF-Triggern (verdeckte Logik in jedem Schreibweg); `anzeigen.fahrzeug_id` (widerspricht dem Zielmodell).
* **Folgen:** ADR-011 ist für Status und View ersetzt. ADR-023 („`bearbeitung` umschlüsseln“) wandert nach P3-02. Merkmale,
  FIN und Fingerabdruck des Fahrzeugs folgen mit P3-02 als neue Spalten.
* **Nachtrag (20.10.2026, ADR-040):** Merkmale und Fingerabdruck werden **nicht** als Spalten am Fahrzeug gespeichert – sie würden veralten, wenn sich die Normalisierung ändert; der Vergleich rechnet beim Lesen.
* **Hinweise aus der QA (niedrig, offen für P3-02):** `fahrzeuge.id` ist ohne AUTOINCREMENT – nach dem Zurückspielen einer
  Sicherung können IDs erneut vergeben werden; Fahrzeug-IDs deshalb nicht in Dateinamen, URLs oder Exporte übernehmen (oder dann
  AUTOINCREMENT einführen). In `inserate` nur mit einfachem INSERT oder UPSERT schreiben (INSERT OR REPLACE hinterließe ein verwaistes
  Fahrzeug). Ein von Hand angelegter gleichnamiger Trigger würde von `CREATE TRIGGER IF NOT EXISTS` übernommen – nur durch manuelle
  Eingriffe erreichbar.

## ADR-040 – Dubletten: Vorschläge beim Lesen, gespeichert werden nur Entscheidungen (Schema v12) · gilt (20.10.2026)

* **Kontext:** Ein Fahrzeug kann auf mehreren Plattformen oder nach Neueinstellung mehrfach erscheinen (P3-02). Inserate enthalten keine
  FIN; Bild-Hashes bräuchten einen Bilderabruf (Regeln 11/12). Die heutige Heuristik `finde_duplikate` sperrt bereits Anschreiben,
  Vergleichsbasis und Team-Übernahme, ohne Fahrzeuge zusammenzuführen.
* **Entscheidung (Betreiber 20.10.2026):**
  1. Offene Vorschläge werden beim Lesen berechnet (`wmscout/normalisierung/identitaet.py` `vergleiche`, rein; `wmscout/dubletten.py`),
     nicht gespeichert. Gespeichert werden nur menschliche Entscheidungen (`dubletten_entscheidungen`: gleich/verschieden, gilt/aufgehoben,
     Gründe eingefroren, Regelversion) und Umhängungen (`fahrzeug_zuordnungen`, nur anfügbar).
  2. Stufen nur „hoch“/„mittel“ mit erklärenden Gründen, keine Prozentwerte. Widerspruch (kein Vorschlag): andere Marke, EZ-Abstand > 1,
     verschiedene bekannte Serie, km-Rückgang > 3.000, abweichende Modellnummer im Titel, andere Fahrzeugart. Gleichzeitig online →
     höchstens „mittel“. Geschätzte PLZ-Lage wird als „ungefähr“ benannt.
  3. Keine FIN, kein Verkäufername, kein Telefon als Merkmal. Nie automatisch zusammenführen.
  4. Rechte (wirksam ab P3-02b): Bestätigen Inhaber und Mitarbeiter; Ablehnen und Aufheben nur Inhaber; Händler nie. Eine Ablehnung
     „verschieden“ hebt die heuristische Sperre für das Paar auf (protokolliert).
  5. Grenzen: höchstens 2000 Paare je Block (Marke, EZ ±1) mit Hinweis „Gruppe zu groß“, Ausgabe begrenzt (`limit` ≤ 1000).
  6. Rückweg: Sicherung `vor-v12` zurückspielen.
* **Alternativen:** Vorschlagstabelle mit Status „offen“ nach jedem Lauf (mehr Schreibhaken, veraltet bei Änderungen); Merkmale als
  Spalten am Fahrzeug (veralten); automatische Zusammenführung bei „hoch“ (vom Betreiber abgelehnt).
* **Folgen / offen:** P3-02a hat keine fachliche Wirkung (Test). P3-02b (umgesetzt, siehe Nachtrag unten): Bestätigen/Ablehnen/Aufheben (LIFO), Gruppenwirkung auf
  Team-Sperre und Bewertung mit sofortiger Cache-Leerung, Prüfung in derselben Transaktion; `PRAGMA foreign_keys` ist nirgends aktiv –
  Existenz der Datensätze im Code prüfen. Die Invariante „`finde_duplikate` ⇒ mindestens mittel“ gilt außer bei Modellnummer- oder
  Art-Widerspruch; `finde_duplikate` selbst ist unverändert.
* **Nachtrag P3-02b (20.10.2026, umgesetzt):**
  1. Bestätigen hängt alle Inserate des Fahrzeugs mit der größeren ID an das mit der kleineren (Zeilen `zusammen`); Aufheben nur in
     umgekehrter Reihenfolge (LIFO), stellt den Zustand bit-gleich her (Zeilen `zurueck`); verwaiste Fahrzeuge bleiben bestehen.
     Konflikt (409), wenn die entstehende Gruppe ein Paar mit geltendem „verschieden“ enthält.
  2. Wirkung an einer Stelle (`dubletten.wende_an`): Nachbarn eines Inserats = eigene Gruppe ∪ heuristische Nachbarn aller
     Gruppenmitglieder (eine Stufe, keine Hülle über Heuristik-Ketten) ∪ deren Gruppen, minus Paare mit geltendem „verschieden“.
     Ohne Entscheidungen bit-gleich zur reinen Heuristik. Wirkt auf Anschreiben-Sperre (auch über Gruppenmitglieder ohne Preis),
     Team-Sperre (Gruppe zusätzlich per SQL in derselben Transaktion) und Vergleichsbasis (Gruppe zählt einmal, nur Inserate mit Preis).
  3. Cache wird nach jeder Entscheidung sofort geleert. `bearbeitung` und Reservierungen bleiben unverändert; die Antwort warnt, wenn
     Gruppenmitglieder von verschiedenen Kollegen gehalten werden. Fahrzeugstatus nur abgeleitet (`domaene.fahrzeug_status`).
  4. Oberfläche: Desktop mit Vorschlagsliste, „Gleiches Fahrzeug“/„Verschieden“ (je nach Recht, mit Rückfrage) und Gruppe samt
     Verlauf und „Aufheben“ im Fahrzeugfenster; Handy nur Anzeige.
  5. Offen (Backlog): Index `fahrzeug_zuordnungen(entscheidung_id)` (nächste Schemaänderung), Audit-Objekt mit Entscheidungs-ID.

## ADR-041 – Preisverlauf: jede Preisbeobachtung mit Kanal und Zeitpunkt; Personendaten kehren nach Anonymisierung nicht zurück · gilt (21.10.2026)

* **Kontext:** P3-03 verlangt einen vollständigen Preisverlauf und dass identische Inserate ohne Datenverlust erneut eingelesen
  werden können. `preis_historie`/`beobachtungen` (seit v4) erfassten bereits Erstpreis, Senkung und Erhöhung, aber nicht den Preis aus
  dem Netz-Detailabruf, und beim Kanal `email` die Importzeit statt des Mail-Datums.
* **Entscheidung:**
  1. Ohne Schemaänderung. Neuer Kanalwert `detail` für Preise aus dem Detailabruf; ein Detailabruf zählt als Beobachtung
     (`zuletzt_gesehen`). Beim Kanal `email` gilt das Datum der Mail als Beobachtungszeitpunkt – liegt es mehr als 365 Tage zurück,
     gilt die Einlesezeit (mit Hinweis).
  2. Eine Mail ändert den Preis nicht, wenn sie älter ist als der jüngste Eintrag im Preisverlauf des Inserats (ergänzt die
     P2-06-Regel gegen `zuletzt_gesehen`).
  3. Ein fehlender Preis löscht keinen bekannten Preis (kein Eintrag „kein Preis“).
  4. Lesend: `wmscout/preisverlauf.py` (Zeitpunkte nach UTC, auf Sekunden gekürzt; je Inserat oder je Fahrzeug über alle seine
     Inserate) und `GET /api/preisverlauf?anzeige=…&umfang=inserat|fahrzeug` (Inhaber, Mitarbeiter).
  5. Datenschutz: Ist ein Inserat anonymisiert (`anonymisiert_am`), übernimmt ein erneutes Einlesen keine Personendaten
     (`verkaeufer_name`); Fahrzeugdaten und Preis werden weiter aktualisiert.
* **Folgen / offen:** Weicht die Anzeigenseite systematisch vom Listenpreis ab, entsteht je Abweichung ein Eintrag (echte
  widersprüchliche Quelldaten). Ein Reihenfolgeschutz für `api`/`stream`-Ereignisse fehlt noch und ist vor der Freigabe einer
  API-Quelle nötig. Die Oberfläche zeigt den Verlauf noch nicht (Phase 6).

## ADR-042 – Verfügbarkeit am Inserat, getrennt vom Ankaufsstatus; `zuletzt_bestaetigt` (Schema v13) · gilt (23.10.2026)

* **Kontext:** P3-04. Bisher setzte ein 404 im Detailabruf den Ankaufsstatus auf „gelöscht“ (Wert ohne Platz in `domaene.STATUS`), und
  die Bewertung ließ solche Zeilen ganz weg. `inserate.verfuegbarkeit` (v4) wurde nur auf „aktiv“ gesetzt; einen Zeitpunkt der letzten
  Bestätigung gab es nicht (`zuletzt_gesehen` ist „jede Beobachtung“, bei Mails die Einlesezeit).
* **Entscheidung:**
  1. Verfügbarkeit ist eine Eigenschaft des Marktinserats (aktiv, reserviert, offline, verkauft, unbekannt), getrennt vom
     Ankaufsstatus. Schema v13: `inserate.zuletzt_bestaetigt` (UTC); Rückfüllung nur für „aktiv“/„offline“; dazu Index
     `fahrzeug_zuordnungen(entscheidung_id)` (P3-02c).
  2. Nur aus vorhandenen Beobachtungen, kein zusätzlicher Netzabruf: Sichtung → aktiv; eindeutige Statusmarke im Titel → reserviert
     bzw. verkauft (Positivliste: „– VERKAUFT“, „[Verkauft]“, „(reserviert)“, „ist leider schon verkauft“ …; im Zweifel kein Signal,
     „Rentner verkauft …“ zählt nicht); 404 im Detailabruf oder Löschereignis → offline.
  3. Altersregel für alle Kanäle: Eine Beobachtung, die älter ist als `zuletzt_bestaetigt`, ändert die Verfügbarkeit nicht.
     Zeitpunkt: Mail-Datum, Dateizeit der gespeicherten Seite, Ereigniszeit; Text-Import = jetzt.
  4. „Vermutlich offline“ wird nie gespeichert, sondern beim Lesen abgeleitet (`verfuegbarkeit.offline_nach_tagen`, Standard 14).
  5. Wirkung: verkauft/offline → kein Anschreiben (Sperrgrund); reserviert und „vermutlich offline“ → nur Hinweis. Nicht verfügbare
     Anzeigen ohne jede Ankaufsarbeit (Status neu, keine Reservierung, Besichtigung, Notiz, Ankauf) werden in der Standardliste
     ausgeblendet (Desktop „nur verfügbare“, API `verfuegbar=standard|alle|nur`); laufende Arbeit bleibt immer sichtbar.
  6. Alter Status „gelöscht“ wird nicht umgeschrieben und gilt beim Lesen wie „offline“; neue 404-Fälle ändern den Ankaufsstatus nicht.
  7. Fahrzeug-Verfügbarkeit nur abgeleitet, Rangfolge aktiv > reserviert > unbekannt > vermutlich offline > offline > verkauft.
  8. Rückweg: Sicherung `vor-v13`.
* **Alternativen:** Verfügbarkeit im Ankaufsstatus belassen (vermischt Markt und Team-Arbeit); „lange nicht gesehen“ als offline
  speichern (würde ohne Beobachtung umschreiben); Negativliste für „verkauft“ (QA: sperrte typische Privat-Titel).
* **Folgen / offen:** Reservierungs-/Verkauft-Kennzeichen der Portale selbst (z. B. Badges auf der Detailseite) werden von den Parsern
  noch nicht gelesen (Quellenarbeit). Englisch „sold“ wird nicht erkannt. Reihenfolgeschutz für Preis/Titel bei `api`/`stream` weiter
  offen (ADR-041).

## ADR-043 – Anbieterart mit Herkunft der Einstufung; unbekannte Anbieter nicht in der Vergleichsbasis (Schema v14) · gilt (23.10.2026)

* **Kontext:** P3-05 und P2-05d. `anzeigen.gewerblich` (0/1/NULL) sagte nicht, worauf die Einstufung beruht: ein PRO-Kennzeichen, ein
  Privatfilter der Suche, nur das Fehlen eines Kennzeichens oder die Angabe des Teams. Eine Trefferliste ohne PRO-Kennzeichen setzte einen
  bekannten Händler wieder auf „privat“; Angebote mit unbekanntem Anbieter (Mails) zählten im Rechner wie Privatangebote.
* **Entscheidung:**
  1. Neue Spalte `anzeigen.anbieter_herkunft` (Schema v14), Werte stärkste zuerst: `korrektur` (Team in der App), `nutzer` (Auswahl beim Text-Import),
     `anzeige` (PRO/Händlerprofil, Verkäuferkasten „Privater Nutzer“/„Gewerblicher Nutzer“, mobile.de-Anbieterkasten, „MwSt. ausweisbar“),
     `suchfilter` (Kleinanzeigen-Suche mit `/anbieter:privat` ohne Händlerkennzeichen), `ohne_kennzeichen` (nur kein Kennzeichen gefunden),
     `altbestand` (vor v14). `gewerblich` bleibt der Wert; Regeln in `wmscout/anbieter.py` (ohne Datenbank testbar).
  2. Übernahme: „unbekannt“ ersetzt nie etwas; aus „gewerblich“ wird nie automatisch „privat“ (auch nicht durch „privat“ im Text-Import –
     wie bisher); ein Händlerbeleg ersetzt jedes „privat“, auch die Auswahl beim Text-Import (QA B1: lieber zu vorsichtig); sonst ersetzt eine
     Angabe mit mindestens gleich starker Herkunft. Die Korrektur in der App (`POST /api/anzeige/<id>/anbieter`, alle Team-Mitglieder, im
     Team-Betrieb protokolliert) setzt jeden Wert und bleibt gegen jeden Import stehen; nur ein Händlerbeleg ändert ein vom Team gesetztes
     „unbekannt“ (QA B2: der nächste Suchlauf setzt es nicht still zurück). Als Beleg „privat“ auf der Kleinanzeigen-Detailseite gelten nur die
     Wendungen „Privater Nutzer“/„Privatanbieter“, nicht jedes „privat“ im Namen (QA B4).
  3. Quellen ohne Herkunftsangabe: „gewerblich“ gilt als Angabe der Anzeige, „privat“ nur als `ohne_kennzeichen` (lieber zu schwach).
  4. Rechner (P2-05d): Vergleichsbasis „Marktwert privat“ nur aus Privatangeboten; `gewerblich` ausdrücklich NULL zählt nicht mit
     (`rechner.privatangebot`). Fehlt der Schlüssel ganz (gespeicherte Kalkulations-Eingaben lassen NULL weg), gilt wie bisher „privat“ –
     alte Kalkulationen rechnen unverändert nach; daher keine neue Kalkulationsversion.
  5. Altbestand (Betreiberfrage F6, konservativ vorentschieden): Werte bleiben, Herkunft `altbestand`; kein Hinweis am Fahrzeug.
  6. Anzeige: Desktop, Handy (`anbieter` in der API: Typ, Herkunft, belegt, Text) und CSV („Anbieter“, „Anbieter-Herkunft“).
     Rückweg: Sicherung `vor-v14`.
* **Alternativen:** neue Spalte `anbieter_typ` statt `gewerblich` (größere Migration ohne fachlichen Gewinn); Altbestand als „unbekannt“
  (hätte fast alle Vergleichsangebote entfernt und jede alte Anzeige mit Hinweis versehen); unbekannte Anbieter mit halbem Gewicht in
  der Vergleichsbasis (falsche Genauigkeit).
* **Folgen / offen:** Schwache Einstufungen (`ohne_kennzeichen`, `altbestand`) tragen keinen Hinweis; ob sie einen bekommen sollen, ist
  Betreiberentscheidung. Eine gespeicherte Suchseite zeigt ihren Privatfilter nicht an – Treffer daraus gelten als `ohne_kennzeichen`.
  Fahrzeugweite Anbieterart über mehrere Inserate wird nicht abgeleitet.

## ADR-044 – Kontakte als Ereignisse (Schema v15) · gilt (23.10.2026)

* **Kontext:** P3-06. Ein Kontakt stand nur als Zustand am Inserat (`kontaktiert_am`, `anschreiben_text` mit angehängten Nachfass-Texten,
  im Team `bearbeitung.kontaktiert_von`). Wann was über welchen Kanal von wem vorbereitet und bestätigt wurde, war nicht nachvollziehbar;
  ein Nachfassen galt beim Kopieren sofort als erledigt.
* **Entscheidung:**
  1. Tabelle `kontakte` (nur anfügen; eine Zeile wird höchstens bestätigt oder – solange offen – durch erneutes Kopieren ersetzt):
     `anzeige_id`, `art` (anschreiben/nachfassen), `kanal` (plattform, telefon, email, whatsapp, persoenlich, unbekannt), `text`, `betrag`,
     `nutzer_id` (vorbereitet von), `vorbereitet_am`, `bestaetigt_am`, `bestaetigt_von`, `verworfen_am`, `herkunft` (app/altbestand). Das Fahrzeug wird beim
     Lesen über `inserate.fahrzeug_id` bestimmt (keine veraltete Kopie nach Dubletten-Entscheidungen); der Verlauf zeigt alle Inserate des
     Fahrzeugs.
  2. Ereignisse in derselben Transaktion wie der Status (Fehler oder Team-Konflikt → nichts geschrieben): „Text kopiert“ → vorbereitetes
     Anschreiben (erneut kopiert: ersetzt); „gesendet ✓“ (Status kontaktiert) bestätigt das zuletzt vorbereitete Ereignis – mit neuem Text
     nur ein Anschreiben, ein Nachfassen wird nie überschrieben – oder legt ein bestätigtes an (Kanal „unbekannt“, wenn der Status ohne
     Text und ohne Kanal gesetzt wird); alle übrigen offenen Ereignisse der Anzeige gelten dann als verworfen (es wurde nur eines
     gesendet). Status „neu“ (Rückgängig) verwirft offene Ereignisse. Nachfassen → vorbereitetes Nachfassen, bestätigt über
     `POST /api/kontakt/<id>/bestaetigen` (wer es vorbereitet hat oder der Inhaber; protokolliert); war das Inserat noch nicht
     kontaktiert, ist das der erste Kontakt und läuft über den Status „kontaktiert“ (Zeitpunkt, Team-Zuordnung, Konfliktprüfung).
     Andere Status erzeugen kein Ereignis. Eine Bestätigung in der App macht eine offene Altbestand-Zeile zu „app“.
  3. Bestehende Felder und Abläufe bleiben unverändert (Status, `kontaktiert_am`, `anschreiben_text`, Nachfass-Erinnerung über
     `nachgefasst_am`, Team-Zuordnung) – `kontakte` ergänzt, ersetzt nichts.
  4. Altbestand (Betreiberfrage F7, konservativ vorentschieden): `kontaktiert_am` → bestätigte Zeile mit Kanal „unbekannt“, Herkunft
     `altbestand` („vor der Bestätigungspflicht übernommen“); Status „vorbereitet“ → offene Zeile; letztes Nachfassen → offene Zeile;
     ohne Text (der bleibt in `anschreiben_text`). Kein Status wird geändert.
  5. Kanal per API (`kanal` bei `/api/status`, `/api/nachgefasst`, Bestätigen); die Oberfläche setzt ihn nicht (der Ablauf „kopieren →
     Anzeige öffnen → senden“ ist die Plattform). Verlauf in Handy und Desktop; Anonymisierung entfernt den Namen auch aus `kontakte.text`.
  6. Rückweg: Sicherung `vor-v15`.
* **Alternativen:** `fahrzeug_id`/`inserat_id` speichern (veraltet nach Dubletten-Entscheidungen); Nachfassen weiter sofort als erledigt
  zählen (widerspricht ADR-012); alte Kontakte als „unbekannt“ weglassen (Verlauf wäre lückenhaft).
* **Folgen / offen:** Ein irrtümlich bestätigter Kontakt lässt sich nicht stornieren (Status „neu“ setzt den Zustand zurück, das Ereignis
  bleibt). Antworten von Verkäufern (`art` antwort) und Kennzahlen „bestätigte Kontakte je Zeitraum“ sind nicht umgesetzt. Kanalwahl in
  der Oberfläche fehlt.

## ADR-045 – Vorfilter der Vergleichsauswahl im Speicher; Indizes nur nach Abfrageplan (Schema v16) · gilt (23.10.2026)

* **Kontext:** P3-07, R12. Messung (nachgebauter Bestand, Linux): 90 % der Bewertungszeit lagen in `Rechner.vergleiche`, das für jede aktive
  Anzeige alle Inserate durchlief (O(aktive × alle)); 6.000 Inserate ≈ 14 s. Abfragepläne aller in den Tests ausgeführten Anweisungen (370
  verschiedene, `EXPLAIN QUERY PLAN` auf 3.000 Inseraten): Tabellendurchläufe im Betrieb nur bei der Warteschlange des Detailabrufs (Durchlauf
  plus Sortierung je Suchlauf) und der Suche nach Besichtigungen einer Verkaufsanfrage; alle übrigen Durchläufe lesen ohnehin (fast) die ganze
  Tabelle oder stammen nur aus Tests.
* **Entscheidung:**
  1. Vorfilter im Speicher statt in SQL: `vergleichsbasis` liefert eine `Vergleichsliste`, die die Angebote einmal nach (Fahrzeugart, EZ-Jahr)
     einsortiert – nur solche, die die datenabhängigen Bedingungen überhaupt erfüllen (Preis ≥ 1.000 €, Privatangebot, EZ bekannt).
     `vergleiche` holt nur das Jahresfenster der eigenen Art (in ursprünglicher Reihenfolge) und prüft es danach vollständig wie bisher –
     das Ergebnis ist identisch (geprüft gegen den Lauf ohne Vorfilter, auch mit Toleranz 0, negativ und als Kommazahl). Ein Jahr, das keine
     ganze Zahl ist, steht in einer Restliste, die immer mitgeprüft wird; jede Änderung der Liste verwirft den Index (QA B1/B2). Einfache
     Listen (Kalkulation, Nachrechnen) laufen unverändert.
  2. Ein SQL-Vorfilter (`alle_mit_preis`) wurde verworfen: dieselben Zeilen dienen der Dublettenerkennung und den Markierungen.
  3. Schema v16, nur Indizes: `idx_anzeigen_detail_offen` (Teilindex `WHERE detail_geladen = 0` auf `erstmals_gesehen`, wirkt, weil die
     Abfrage `detail_geladen=0` als festen Wert enthält) und `idx_besichtigung_anfrage`. Weitere Indizes nicht ohne gemessenen Abfrageplan.
     Rückweg: Sicherung `vor-v16`.
  4. Die Fachlogik bleibt unverändert: alte Anzeigen zählen weiter mit halbem Gewicht, offline/verkaufte weiter als Marktpreise.
* **Folgen / offen:** Messung 1.000 / 3.000 / 6.000 Inserate: 0,61 → 0,45 s, 3,4 → 1,3 s, 13,8 → 3,6 s. Gespeicherte Bewertungen
  (`bewertungen`) und die fachliche Frage, ob offline/verkaufte oder sehr alte Inserate in die Vergleichsbasis gehören, bleiben für Phase 5
  (acquisition-analyst). Änderungen an den Einträgen selbst (nicht an der Liste) bemerkt der Index nicht – kein Aufrufer tut das.
  `kalkulation.vergleich_auszug` nutzt den Vorfilter noch nicht (Backlog).

## ADR-046 – Datenqualität: Markierungen und Wert je Fahrzeug, beim Lesen berechnet, ohne Wirkung · gilt (23.10.2026)

* **Kontext:** P3-08 (und P2-10). Fehlende, unplausible oder widersprüchliche Angaben (Preis 1 €, EZ nach Baujahr, km-Rückgang, falsche
  Marke im Titel) waren nirgends sichtbar; je Quelle gab es nur die Mail-Messfunktion.
* **Entscheidung:**
  1. Reines Modul `normalisierung/qualitaet.py`, beim Lesen berechnet (kein Schema, keine `qualitaet_json`-Spalte: geänderte Regeln wirken
     sofort, nichts veraltet).
  2. Markierungen je Inserat in drei Arten: **fehlt** (Preis, EZ, km, Ort, Marke, Fahrzeugart unbekannt/vorläufig, Anbieter unbekannt),
     **unplausibel** (Preis < 1.000 € oder > 750.000 €, EZ in der Zukunft oder vor 1960, km > 1 Mio., > 60.000 km je Jahr oder < 1.000 km
     ab 3 Jahren) und **Widerspruch** (genanntes Baujahr mehr als ein Jahr nach der EZ – ein Jahr ist oft das Modelljahr; im Text mit „EZ“/
     „Erstzulassung“ genannte EZ ≠ Angabe, nur direkt mit Monat, „ca.“ oder Datum davor; km im **Titel** ≠ Angabe – Beschreibungen nennen
     oft andere Strecken; Marke im Titel ≠ Marke; Basisfahrzeuge zählen nicht).
  3. Je Fahrzeug: eine Angabe fehlt nur, wenn sie in keinem Inserat des Fahrzeugs steht; dazu km-Rückgang gegenüber einem älteren Inserat
     (> 1.000 km; nur mit bekanntem Datum beider Inserate) und abweichende Erstzulassungen. Je Bewertungslauf wird jedes Inserat nur einmal
     geprüft (kein quadratischer Aufwand bei großen Gruppen). Wert = 100 − Abzüge (Kernangaben Preis/EZ 25, km 15, Ort/Marke/Art 10, Art vorläufig und
     Anbieter 5, jede unplausible oder widersprüchliche Angabe 20), mindestens 0; Stufen gut ≥ 80, mittel ≥ 50, schwach.
  4. Nur Anzeige: Bewertung, Ampel, Sperre und Brief bleiben unverändert (Test vergleicht beide Läufe). Desktop/Handy: Abzeichen „Daten
     lückenhaft“ bei schwach, Markierungen im Detail; CSV „Datenqualität“, „Datenmarkierungen“; API `datenqualitaet`.
  5. Je Quelle (P2-10): `scout.py qualitaet` und `GET /api/datenqualitaet` (Team, nicht Händler-Zugang): Anteile je Inserat, Ø-Wert,
     Fahrzeuge mit Widerspruch – ohne Personendaten.
* **Alternativen:** Speichern in `inserate.qualitaet_json` (veraltet bei Regeländerung, Migration nötig); Wirkung auf Ampel/Max-EK
  (fachliche Entscheidung, Betreiberfrage); km-Verlauf je Inserat (bräuchte km in `beobachtungen` – Schemaänderung, offen).
* **Folgen / offen:** Ob eine schwache Datenlage die Ampel dämpfen oder das Anschreiben sperren soll, entscheidet der Betreiber. Ein
  km-Rückgang innerhalb desselben Inserats wird nicht erkannt (kein km-Verlauf gespeichert). Schwellen sind Annahmen und im Code
  (Konstanten) anpassbar, nicht in `config.yaml`.

## ADR-047 – Suchprofile als Filter über eingegangene Daten, Abdeckungscheckliste je Plattform (Schema v17) · gilt (24.10.2026)

* **Kontext:** P4-01. Eine freigegebene Pull-Quelle gibt es nicht (Kleinanzeigen-Suche nur höflich und vom Nutzer gestartet, mobile.de nur
  über Mails und gespeicherte Seiten, AutoScout24 BLOCKED). Gesuchte Fahrzeuge standen bisher nur in `config.yaml → suchen`; ob auf jeder
  Plattform ein passender Suchauftrag bzw. eine E-Mail-Benachrichtigung angelegt ist, war nirgends festgehalten.
* **Entscheidung:**
  1. Additive Migration v17: `suchprofile` (Name eindeutig, aktiv, Arten und Marken als JSON-Liste, Modell-Teiltext, Preis von/bis, EZ von/bis,
     km bis, Notiz) und `suchauftraege` (je Profil und Plattform: angelegt ja/nein, Adresse, Notiz; `UNIQUE(profil_id, plattform)`). Keine
     bestehende Tabelle verändert; Sicherung, Transaktion, Zählinvariante wie bei v11–v16. Die geplante `suchprofile`-Spalte `parameter_json`
     (ARCHITECTURE §7) entfällt: Profile beschreiben das gesuchte Fahrzeug, nicht die Abfrage einer Quelle.
  2. **Profile rufen nichts ab.** Sie filtern die eingegangenen Inserate (Suchlauf, gespeicherte Seiten, Text, Mails). Zuordnung je Inserat:
     **passt**, **unklar** (eine geprüfte Angabe fehlt, Art „Sonstige“/unbekannt) oder **nein** (eine Angabe widerspricht; „nein“ schlägt
     „unklar“). „Unklar“ wird angezeigt und gekennzeichnet, nicht versteckt – sonst fielen gerade schlecht beschriebene Privatangebote heraus.
     Das Modell wird als ganzes Wort bzw. ganze Wortfolge gesucht („TI“ passt nicht zu „Automatik“), Marken normalisiert („vw“ = Volkswagen).
  3. **Abdeckungscheckliste** je Profil und Plattform: Zustand *fehlt* (kein Auftrag), *angelegt*, *prüfen* (angelegt, aber seit 14 Tagen kein
     sicher passender Treffer dieser Plattform; „unklar“ zählt hier nicht) oder *nicht lesbar* (Plattform ohne Eingang im Scout, derzeit
     AutoScout24 – dort lässt sich „angelegt“ nicht setzen). Adressen nur http(s) ohne Leerzeichen. Abdeckung = angelegte
     unter den lesbaren Plattformen. Der Nutzer pflegt die Liste selbst; der Scout legt keine Aufträge an und meldet sich nirgends an.
  4. Pflege (anlegen, ändern, löschen, Checkliste) nur durch den Inhaber, sobald das Team aktiv ist; Lesen und Filtern für alle Team-Mitglieder,
     Händler-Zugang gesperrt. Schreibende Aufrufe mit Token und im Audit-Protokoll (Objekt `suchprofil`).
  5. Keine Wirkung auf Bewertung, Ampel, Max-EK, Sperre oder Anschreiben (Test vergleicht die Läufe). API: `GET/POST /api/suchprofile`,
     `POST /api/suchprofil/<id>[/loeschen|/auftrag]`, `GET /api/fahrzeuge?profil=<id>[&unklar=nein]` (Feld `profil_treffer`, wie bisher
     höchstens 200 Einträge), `GET /api/suchprofil/<id>/treffer` (alle Treffer-IDs ohne Grenze, für den Desktop-Filter). Desktop:
     Auswahl „Suchprofil“ in der Leiste und Panel „Suchprofile“; Handy: Auswahl über der Liste, Abzeichen „Profil unklar“.
* **Alternativen:** Profile als Suchparameter für die Kleinanzeigen-Suche (wäre zusätzlicher Netzabruf je Profil – nicht ohne Freigabe);
  „unklar“ ausblenden (verliert Treffer); Profile in `config.yaml` (nicht in der App pflegbar, kein Team-Recht).
* **Folgen / offen:** `config.yaml → suchen` bleibt für den bestehenden Suchlauf unverändert; eine Verknüpfung (Suchlauf je Profil) erst mit
  einer freigegebenen Pull-Quelle (P4-06). Suchgebiete/PLZ (P4-02) und die Messung von Suchlücken (P4-05) bauen auf den Profilen auf.
  Betreiberfragen: ob auch Mitarbeiter Profile pflegen dürfen und ob „unklar“ standardmäßig ausgeblendet werden soll.

## ADR-048 – Suchgebiet je Suchprofil: bundesweit, Umkreis um eine PLZ oder PLZ-Bereiche (Schema v18) · gilt (24.10.2026)

* **Kontext:** P4-02. Suchprofile (ADR-047) kannten kein Gebiet; die Entfernung wurde nur zum eigenen Standort angezeigt
  (`config.yaml → anschreiben.plz`). Für eine deutschlandweite Suche sollen Profile auf ein Gebiet begrenzt werden können – weiterhin als
  Filter über eingegangene Daten, ohne zusätzlichen Abruf.
* **Entscheidung:**
  1. Additive Migration v18: Spalten `gebiet` (`bundesweit`/`umkreis`/`regionen`, Standard `bundesweit`), `gebiet_plz`, `gebiet_radius_km`,
     `gebiet_regionen` (JSON-Liste) an `suchprofile`. Bestehende Profile werden „bundesweit“ und filtern unverändert.
  2. **bundesweit** = kein Gebietsfilter (auch Orte im Ausland bleiben wie bisher sichtbar). **Umkreis**: geschätzte Fahrstrecke wie die
     angezeigte Entfernung (`geo.entfernung_km`, Luftlinie × 1,25) um eine **exakt bekannte** PLZ (fängt Tippfehler ab; Vorschlag: eigener
     Standort), 1–1.000 km; die PLZ eines Inserats darf genähert sein (Mittel des PLZ-Bereichs). **PLZ-Bereiche**: erste ein oder zwei
     Ziffern deutscher PLZ (z. B. „7“, „80“), 1–50 Einträge; ein Bereich, der in einem anderen steckt („70“ bei „7“), entfällt.
  3. Zuordnung: Ort im Ausland → **nein**, PLZ bzw. Entfernung unbekannt → **unklar**, sonst passt/nein nach Gebiet; „nein“ schlägt
     „unklar“ wie bei den übrigen Kriterien. Gründe nennen Entfernung bzw. PLZ. Ist die PLZ des Inserats nur über ihren Bereich genähert und
     liegt die Schätzung höchstens 20 km über dem Umkreis, wird es „unklar“ statt „nein“ (lieber zeigen als still ausblenden).
  4. Nur die Angaben der gewählten Gebietsart werden gespeichert (die übrigen geleert). API: `gebiete`, `standort_plz` und je Profil
     `gebiet_text` in `GET /api/suchprofile`; Eingaben über die bestehenden Profil-Endpunkte (Rechte unverändert: Pflege durch den Inhaber).
  5. Keine Wirkung auf Bewertung, Abholkosten, `max_entfernung_km` oder den Suchlauf.
* **Alternativen:** Bundesländer/Landkreise (PLZ-Bereiche schneiden Ländergrenzen, eine amtliche Zuordnung fehlt im Projekt – erst mit
  geprüfter Datenquelle); Umkreis in Luftlinie (wiche von der angezeigten Entfernung ab); Gebiet als Parameter des Kleinanzeigen-Suchlaufs
  (zusätzlicher Abruf – erst mit freigegebener Pull-Quelle, P4-06).
* **Folgen / offen:** Die Entfernung ist eine Schätzung (± einige km, bei genäherter PLZ mehr); Treffer knapp an der Grenze können
  abweichen (genäherte PLZ: siehe 3.). Mehrere Umkreise je Profil sind nicht vorgesehen (dafür zwei Profile). Betreiberfrage: ob „bundesweit“ Orte im Ausland
  ausschließen soll.

## ADR-049 – Neuigkeiten: frisch eingegangen und deutliche Preissenkungen hervorheben, priorisieren und melden · gilt (24.10.2026)

* **Kontext:** P4-03. Preissenkungen erkannte der Import schon (`anzeigen.preis_vorher`, `preis_geaendert_am`, Ergebnis „preis“), sichtbar
  waren sie nur als dauerhaftes Abzeichen „Preis gesenkt“ (auch Jahre später oder nach erneuter Erhöhung). „Neu“ hieß nur „seit dem letzten
  Suchlauf“ – Eingänge über Mails, gespeicherte Seiten oder Text blieben dabei unbemerkt. Gemeldet wurden nur neue Treffer.
* **Entscheidung:**
  1. Reines Modul `bewertung/neuigkeit.py`, beim Lesen berechnet, **ohne Schemaänderung** und **ohne Wirkung** auf Bewertung, Ampel, Sperre und
     Anschreiben (Test vergleicht beide Läufe). Je offenem, sichtbarem, **nicht gesperrtem** Inserat (Status neu/vorbereitet; an kontaktierten
     meldet sich eine Senkung wie bisher über „Nachfassen“; gewerblich, doppelt eingestellt, Ausschlussbegriff, außerhalb des Filters ist
     keine Ankaufsgelegenheit) eine Stufe: **1 Preis gesenkt – jetzt im Rahmen** (eine Senkung – auch eine kleine – brachte den Preis von
     über auf höchstens den Max-EK, nur bei belastbarer Bewertung), **2 neu und Anschreiben bereit**, **3 Preis deutlich gesenkt**,
     **4 neu eingegangen**.
  2. **Frisch** = erster Eingang (`erstmals_gesehen`, egal über welchen Kanal) innerhalb von 48 Stunden. **Deutliche Senkung** = letzte Senkung
     innerhalb von 14 Tagen, Preis noch darunter, mindestens 3 % **oder** 500 €. Werte in `config.yaml → neuigkeiten`, ungültige gelten als Standard.
  3. Priorisieren: Filter „Neu & gesenkt“ und Sortierung „Neuigkeiten zuerst“ (Stufe, dann beste Chance) am Desktop, Liste und Kachel am Handy,
     `GET /api/fahrzeuge?filter=neuigkeiten` (nach Stufe sortiert), Zähler in `/api/heute`, Kachel im Report, CSV-Spalte „Neuigkeit“.
     Das alte Abzeichen „Preis gesenkt“ erscheint nur noch, solange der Preis unter dem früheren liegt.
  4. Melden: nach einem Suchlauf nennt der Browser-Hinweis die deutlichen Senkungen dieses Laufs; die Mail listet sie mit (Betreff
     „… neue Treffer, n Preissenkungen“) und geht bei `nur_bei_neuen_treffern` auch ohne neue Treffer raus (`email.preissenkungen_melden`,
     Standard an; bestehende Nutzer mit `nur_bei_neuen_treffern` bekommen damit auch Mails nur mit Preissenkungen). Mehrere Inserate
     desselben Fahrzeugs werden dabei einmal gemeldet. WhatsApp bleibt bei neuen Treffern (eine weitere Vorlage bräuchte die Freigabe bei Meta).
  5. Wird ein Preis nach einer Senkung wieder **erhöht**, setzt der Import `preis_vorher`/`preis_geaendert_am` zurück (sonst „Preis
     gesenkt“ und ein Nachfass-Grund trotz Erhöhung). Der vollständige Verlauf bleibt in `preis_historie`.
* **Alternativen:** Senkungen aus `preis_historie` statt aus `anzeigen` (gleicher Inhalt, aber eine Abfrage je Inserat); Stufe speichern
  (veraltet mit der Zeit, Migration); Wirkung auf die Ampel (fachliche Entscheidung, die Ampel folgt dem neuen Preis ohnehin).
* **Folgen / offen:** Die CSV hat die neue Spalte „Neuigkeit“ vor „Erstmals gesehen“ (Auswertungen nach Spaltennummer anpassen).
  Eingänge über Mails, Seiten und Text lösen keinen eigenen Hinweis aus (nur sichtbar in Kachel, Filter und Liste) –
  Hinweise nach jedem Import wären eine Erweiterung. Betreiberfragen: Schwellen (48 h, 14 Tage, 3 % / 500 €) und ob Preissenkungen per Mail
  gemeldet werden sollen (Standard: ja).

## ADR-050 – Laufprotokoll, Intervalle je Quelle, Pause nach Sperre, Statusseite (Schema v19) · gilt (24.10.2026)

* **Kontext:** P4-04. Ob und wie Suchläufe und Importe liefen, stand nur im Speicher der App (letzte Meldung) und in `scout.log`. Es gab
  ein Intervall für die Auto-Suche, aber keines je Quelle, und nach einer Sperre (403/429/Captcha) versuchte die Automatik es beim nächsten
  Termin erneut.
* **Entscheidung:**
  1. Additive Migration v19: Tabelle `suchlaeufe` – je Suchlauf bzw. Import gespeicherter Seiten/Mails (nur wenn Dateien gelesen wurden):
     Art, Auslöser (von Hand in der App, automatisch, Kommandozeile/geplante Aufgabe), Beginn, Ende, Ergebnis (ohne Fehler / mit Fehler /
     Quelle blockt / abgebrochen), Zähler, Fehlertext (gekürzt) und je Quelle Zahlen, Ergebnis und Fehler (JSON). Einträge älter als
     365 Tage löscht der nächste Lauf. Ein Lauf ohne Ende gilt nach 6 Stunden als abgebrochen (Absturz, Stromausfall). Das Protokoll
     darf einen Lauf nie scheitern lassen (Schreibfehler werden nur geloggt).
  2. **Intervall je Quelle** (`app.intervall_stunden_je_quelle`, Standard leer) und **Pause nach Sperre** (`app.pause_nach_sperre_stunden`,
     Standard 24): gelten nur für die automatische Suche der App und `scout.py lauf` (geplante Aufgabe); `--sofort` und der Knopf „Neue
     Anzeigen suchen“ warten nicht. Eine übersprungene Quelle wird nicht abgerufen, auch nicht ihre Detailseiten. Nichts wird umgangen
     (Regel 11) – es wird nur länger gewartet. Ausgewertet werden alle Läufe im längsten Fenster (Pause bzw. Intervall), ohne
     Anzahlgrenze. Eine geladene, aber nicht erkannte Suchseite (Layout geändert) zählt als Fehler der Quelle.
  3. **Statusseite** `/status` (serverseitig gerendert, ohne eigenes JavaScript; Team, nicht Händler-Zugang) und `GET /api/status`:
     Pull-Quellen (Freigabe/Schalter, eingetragene Suchen, letzter Lauf, letzter Erfolg, Fehler in Folge, letzter Fehler, Intervall,
     nächster automatischer Abruf), Eingänge (an/aus, letzter Import), die letzten 30 Läufe und Warnungen (3 Fehler in Folge, Pause nach
     Sperre, abgebrochener Lauf, Auto-Suche ohne laufende Quelle). `scout.py quellen liste` zeigt den Status je Quelle mit.
* **Alternativen:** eine Zeile je Quelle und Lauf (mehr Zeilen, gleiche Aussage); Auswertung von `scout.log` (rotiert, nicht strukturiert);
  Intervall auch für Läufe von Hand (würde den Betreiber bevormunden; der Knopf ist eine bewusste Entscheidung).
* **Folgen / offen:** Der Import einzelner Inserate über „Link + Text“ wird nicht protokolliert (einzelne Handgriffe). Fehlertexte können
  Such- und Inserat-URLs sowie Dateinamen gespeicherter Seiten enthalten (keine systematischen Personendaten; 365 Tage, Team sichtbar).
  Ein abgestürzter Lauf hat keine Zahlen je Quelle: er erscheint als „abgebrochen“ mit Warnung, startet aber das Intervall der Quelle
  nicht neu. Beschädigte Protokollzeilen werden gemeldet und als leer gelesen. Betreiberfragen: Pausendauer nach einer Sperre, Intervalle je Quelle (Standard: keine).

## ADR-051 – Abdeckung und Suchlücken messen: Kennzahlen, Zeit-, Gebiets- und Profillücken, nur lesen · gilt (25.10.2026)

* **Kontext:** P4-05 und die Abnahme von Phase 4 („Datenabdeckung messbar“). Die Kennzahlen der ROADMAP waren beschrieben, aber nirgends
  berechnet; ob Suchaufträge, Benachrichtigungen oder Importe ausfallen, war nur indirekt zu erkennen.
* **Entscheidung:**
  1. Reines Modul `abdeckung.py`, **ohne Schemaänderung und ohne Schreibzugriff**. Grundlage: alle Inserate, die im Zeitraum (Standard
     30 Kalendertage einschließlich heute, ab Mitternacht; App 1–90, Kommandozeile 1–365) **zuerst** eingingen, bewertet wie in der App (`bewerte_alle(…, erstmals_seit=…)` – auch Inserate, die inzwischen nicht
     mehr gesehen werden), dazu `beobachtungen`, `preis_historie` und das Laufprotokoll (ADR-050).
  2. **Kennzahlen:** neue Inserate (je Quelle), neue unterschiedliche Fahrzeuge (Zusammenhangskomponenten der bestätigten oder erkannten
     Dubletten; ein wieder eingestelltes Fahrzeug, dessen anderes Inserat vor dem Zeitraum einging, ist nicht neu), relevante
     Privatangebote (privat, im Filter – der Bearbeitungsstatus zählt nicht, sonst senkte jeder Kontakt die Kennzahl –, verfügbar; je Tag), Inserate mit Dublette, nicht mehr verfügbar, erkannte
     Preisänderungen (Eintrag im Preisverlauf mit Vorgänger – der erste Preis zählt nicht), vollständig beschrieben (Preis, EZ, km, PLZ,
     Art, Anbieterart), Läufe ohne Fehler je Art (statt verarbeiteter je angelieferter Datensätze – das liefert keine Quelle). „Zeit Sichtung → Import“ bleibt offen (Einstellzeitpunkt liefert keine Quelle verlässlich).
  3. **Zeitlücken:** je lesbarer Plattform Tage ohne neues oder geändertes Inserat (Beobachtung „neu“/„geändert“ aus Suche, Seite, Mail,
     Text oder Ereignis; Detailabruf und „gelöscht“ zählen nicht – ein Tag mit nur Bekanntem gilt als Lücke) und die längsten zusammenhängenden Lücken ab 2 Tagen.
     **Gebietslücken:** zweistellige PLZ-Bereiche (96) ohne neues Inserat; ohne PLZ und Ausland getrennt. **Profillücken:** je aktivem
     Suchprofil Treffer (passt/unklar, Fahrzeuge einmal), je Plattform, Hinweise: kein Suchauftrag, Auftrag ohne passenden Eingang, Arten
     bzw. PLZ-Bereiche des Profils ohne Treffer, mindestens 50 % „unklar“ (ab 4 Treffern).
  4. Ausgabe: Seite `/abdeckung` (Zeitraum 7/30/90 Tage, Link von `/status`), `GET /api/abdeckung?tage=`, `scout.py abdeckung --tage`.
     Team darf lesen, Händler-Zugang nicht; keine Personendaten.
* **Alternativen:** Kennzahlen täglich speichern (Verlauf über Monate – eigene Tabelle, erst bei Bedarf); Lücken je Landkreis/Bundesland
  (keine amtliche Zuordnung im Projekt, ADR-048); Messung über die 21-Tage-Liste der App (würde ältere Eingänge des Zeitraums verlieren).
* **Folgen / offen:** Die Messung bewertet die Inserate des Zeitraums neu und läuft in der Anfrage unter der Datenbanksperre der App – die
  App speichert das Ergebnis bis zu 5 Minuten (neu bei geändertem Bestand) und erlaubt höchstens 90 Tage; QA maß 39 s für 6.000 Inserate
  und 365 Tage (synthetisch) – längere Zeiträume deshalb über `scout.py abdeckung`. Gebietslücken sagen ohne Pull-Quelle vor allem, wo eure eigenen Suchaufträge nicht hinreichen.

## ADR-052 – Kalibrierung des Rechners mit tatsächlichen Ankäufen: Bericht und Vorschläge, keine automatische Änderung · gilt (25.10.2026)

* **Kontext:** P5-01. Die Parameter des Rechners (Neupreise, Restwertkurve, Abschlag Angebot → Abschluss, Händleraufschlag, Kosten,
  Standzeit) sind Schätzwerte; ob sie zu den echten Ankäufen passen, war nirgends geprüft. Die Analyse (`docs/RECHNER-ANALYSE.md`) zeigt:
  Max-EK hängt mit einem Hebel von gut 1 an der Marktwert-Schätzung, Kosten und Standzeit wirken deutlich schwächer.
* **Entscheidung:**
  1. **Fälle** aus zwei Quellen: Ankäufe der App (Plan beim Kauf eingefroren, Ist aus Kaufpreis, Kosten, Verkauf; stornierte zählen nicht;
     Ist-Kosten und Standzeit erst nach dem Verkauf) und **manuell nachgetragene frühere Ankäufe** – neue Tabelle `kalibrierung_faelle`
     (Schema v20; nur Fahrzeugdaten, Preise, Daten, Notiz – **keine Verkäuferdaten**). Manuelle Fälle rechnet der Rechner zum Kaufdatum
     nach (Stichtag 12 Uhr, Entfernung ab `anschreiben.plz`), **nur mit dem Marktmodell**: Vergleichsangebote von damals fehlen, und
     heutige Angebote desselben EZ-Jahrgangs würden für ein früheres Kaufdatum zu alt bewertet (QA B1). Bezugsdaten: Kaufdatum bei App-Fällen
     = Anlage des Vorgangs; Standzeit bei App-Fällen ab Übergabe, bei nachgetragenen ab Kauf. Ein verkaufter Ankauf ohne erfasste Kosten
     zählt bei den Kosten als unbekannt, nicht als 0.
  2. **Bericht** (`bewertung/kalibrierung.py`, ohne Datenbank testbar): Kaufpreis ÷ Max-EK, Verkaufspreis ÷ geplanter Händler-VK,
     Ist- minus Plankosten, Standzeit gegenüber Plan – je Median, mittlere Hälfte (Quartile) und Anzahl; Belastbarkeit nach Fallzahl
     (unter 3 keine Aussage, unter 5 erste Hinweise, ab 10 belastbar). Median und Quartile mit Interpolation. Max-EK 0 (Rechner riet ab)
     wird gesondert gezählt.
  3. **Vorschläge** erst ab 5 verwertbaren Fällen und einer Abweichung über der Toleranz (VK 5 %, Kosten 300 €, Standzeit 30 Tage):
     `rechner.aufschlag_haendler_vk` (oder alternativ `abschlag_angebot_auf_privatwert`), `rechner.kosten.aufbereitung` (Median der
     Kostenabweichung, auf 50 € gerundet), `rechner.kosten.standzeit_monate` (kaufmännisch gerundet). Gerechnet wird **je Fall relativ zu dem Parameterstand, mit dem er geplant
     wurde**: Beim Anlegen eines Ankaufs speichert der Plan diesen Stand (`plan.parameter`); nachgetragene Fälle nutzen die aktuelle
     Konfiguration. So schlägt der nächste Bericht eine übernommene Korrektur nicht erneut vor (QA B2). Ankäufe ohne gespeicherten Stand
     (vor P5-01, Plan aus der Grundlage der Besichtigung) zählen in den Kennzahlen, nicht in den Vorschlägen. Werte außerhalb des üblichen
     Bereichs (Aufschlag 0–30 %, Abschlag 0–25 %) erhalten eine Warnung; Anteile auf 0,01 gerundet. **Nichts wird automatisch geändert**; der Betreiber stellt
     `config.yaml` bewusst nach. Hinweis, wenn im Median über dem Max-EK gekauft wurde.
  4. Ausgabe: Seite `/kalibrierung` (Bericht, Fälle, Formular zum Nachtragen und Löschen; Link aus `/ankaeufe`), `GET /api/kalibrierung`,
     `POST /api/kalibrierung`, `POST /api/kalibrierung/<id>/loeschen`, `scout.py kalibrierung`. Im Team **nur der Inhaber** (Kaufpreise);
     Händler-Zugang nicht; Änderungen im Audit-Protokoll.
* **Alternativen:** Parameter automatisch anpassen (Regel 15: Bewertung darf sich nicht unbemerkt verschieben; zu wenige Fälle);
  Regression über mehrere Parameter (braucht deutlich mehr Fälle); Marktdaten zum Kaufdatum rekonstruieren (liegen nicht vor).
* **Folgen / offen:** Der Bericht wird bei jedem Aufruf neu gerechnet (je manuellem Fall eine Bewertung ohne Vergleichsangebote –
  schnell). Nachgetragene Fälle prüfen damit das Marktmodell, Ankäufe der App das Modell samt Vergleichsangeboten; beide stehen
  gemeinsam im Bericht (Spalte Fall). Die Kostenabweichung wird ganz der Aufbereitung zugeschlagen; die Alternative im Vorschlag nennt
  die Verteilung auf die verursachenden Posten. §25a bleibt eine fachliche Annahme, keine Steuerberatung. Betreiberfragen: Mindestfallzahl
  (5) und Toleranzen; ob Mitarbeiter den Bericht sehen dürfen (derzeit nein).

## ADR-053 – Vergleichsauswahl nach Ähnlichkeit: Marke, Modellreihe, Modell, Markenklasse und Fahrzeugklasse · gilt (25.10.2026)

* **Kontext:** P5-02, Schwäche S2 der Rechner-Analyse. Bisher zählten alle Vergleichsangebote gleicher Art und EZ ± 3 Jahre fast gleich:
  gleiche Marke ×1,0, andere ×0,5, gleiche Modellreihe ×1,5. Ein 6-m-Teilintegrierter und ein 7,5-m-Teilintegrierter galten als gleich;
  ein exakt gleiches Modell wog kaum mehr als irgendein Knaus.
* **Entscheidung:**
  1. **Gewichten statt ausschließen.** Die Vorauswahl (Art, EZ-, km-Toleranz, Privatangebot) bleibt; innerhalb davon zählt jedes
     Angebot nach **Ähnlichkeitsstufe**: gleiches Modell samt Grundriss 2,5 · gleiche Modellreihe 1,8 · gleiche Marke 1,0 · andere Marke
     derselben Markenklasse 0,7 (Premium/Gehoben/Einstieg; bekannte Aufbauhersteller ohne Eintrag bilden „Mittel“) · andere oder
     unbekannte Marke 0,5. Ist die Marke nur das Basisfahrzeug (Fiat, Mercedes …), gibt es keine Markenstufe; „gleiches Modell“ nur mit
     Grundriss (Modell ≠ Modellreihe). **Deckel:** kein einzelnes Angebot trägt mehr als 25 % des Gesamtgewichts (bei weniger als
     4 Vergleichen zählen alle gleich) – so kann ein einzelnes sehr ähnliches Angebot mit Wunschpreis den Markt nicht überstimmen
     (QA B1). Die Streuung für Spanne und Sicherheit ist mindestens die ungewichtete – Gewichte heben die Sicherheit nicht. Harte Stufen (nur das gleiche Modell, sobald
     5 da sind) hätten die Zahl der Vergleiche und damit das Marktgewicht n ÷ (n + 4) gesenkt und wären bei 4 gegen 5 Treffern gesprungen.
  2. **Fahrzeugklasse** aus Titel und Beschreibung (`normalisierung/fahrzeug.py`): Länge („Länge 7,40 m“, „Gesamtlänge 699 cm“,
     „7,4 m lang“; nur 4–12 m, nicht direkt nach Zubehör wie Markise, Kabel, Stellplatz, Anhänger, Bett) und Basisfahrzeug (Plattformen, baugleiche zusammengefasst: Ducato/Jumper/
     Boxer, Sprinter, Transit, Daily, Master/Movano/NV400, Crafter/TGE, VW Transporter; die erste Nennung im Text zählt). Je Meter Längenunterschied −40 % (höchstens bis
     40 %), anderes Basisfahrzeug ×0,8 – **nur wenn beide Angaben bekannt sind**, sonst neutral.
  3. Baujahr-, km-Abstand und Alter der Anzeige wirken wie bisher; Ausreißer nach Tukey ebenso. Alle Werte in `config.yaml →
     rechner.vergleich_aehnlichkeit` (fehlt der Abschnitt, gelten dieselben Standardwerte).
  4. **Erklärung:** Die Vergleichsbasis nennt die Zusammensetzung („3 gleiches Modell, 2 gleiche Modellreihe, 7 andere Marken; ähnlichere
     zählen mehr“) und die erkannte Fahrzeugklasse; `Bewertung.vergleich_stufen`, `Bewertung.fahrzeugklasse`.
  5. **Nachrechenbarkeit:** Kalkulationen (Phase E) frieren die wirksamen Gewichte und das Feld `modell` der Vergleiche ein;
     Rechenstand **E2**. Gespeicherte E1-Kalkulationen gelten beim Nachrechnen als „andere Version“ (vorgesehenes Verhalten), ihr
     gespeichertes Ergebnis bleibt unverändert.
* **Alternativen:** harte Stufen (siehe oben); Länge und Basisfahrzeug als Datenbankspalten (erst sinnvoll, wenn Quellen sie strukturiert
  liefern – dann ohne Textsuche); effektive Fallzahl nach Gewichten für das Marktgewicht (gehört zu P5-03 Unsicherheit).
* **Folgen / offen:** Wirkung auf synthetischen Testdaten (300 Inserate, 120 bewertet, gegen die alten Gewichte): Marktniveau im
  Median unverändert, −6,8 % bis +5,3 %; Sicherheit in 117 von 120 Fällen gleich, 2× mittel → hoch, 1× hoch → mittel. Mehrere gleiche
  Modelle können eine Mehrheit anderer Marken überstimmen (3 × 2,5 gegen 7 × 0,5) – gewollt; ein einzelnes nicht. Erkennungsmuster
  für Länge/Basisfahrzeug: jede Änderung verlangt eine neue Rechenversion (gespeicherte Kalkulationen frieren den Text ein). Länge und Basisfahrzeug stehen in Kleinanzeigen-Texten oft nicht; dann wirkt nur
  die Markenstufe. Betreiberfragen: Gewichte und Deckel bestätigen; ob Marken ohne Eintrag (Knaus, Dethleffs, Bürstner …) als „Mittel“
  richtig eingeordnet sind.

## ADR-054 – Spannen statt Punktwerte, Abschlag bei unbekannter Marke, Mängelliste · gilt (25.10.2026)

* **Kontext:** P5-03 (Schwäche S3: Punktwerte dominieren, falsche Genauigkeit bei dünner Datenlage) und Betreiberwunsch vom 25.10.2026:
  „Die fehlende Marke sollte schmälernd auf den Verkaufspreis wirken, der Käufer soll nur darauf hingewiesen werden. Bepreisung eher als
  Spanne, Mängel als Liste beim Inserat deutlich.“ Rückfrage: gemeint ist eine **unbekannte** Marke (keine Aufbaumarke erkennbar),
  Abschlag **5 %**.
* **Entscheidung:**
  1. **Abschlag bei unbekannter Marke** (`rechner.abschlag_marke_unbekannt`, Standard 0,05): keine Marke oder nur die Basismarke
     (Fiat, Mercedes, VW …; Werks-Camper wie VW California, Mercedes Marco Polo, Ford Nugget haben eine Marke) → Händler-VK × 0,95; Kosten, Marge, Max-EK, Ampel und Erstangebot folgen daraus. Marktwert und Marktwert
     privat bleiben unverändert (der Abschlag betrifft den Wiederverkauf). Am Fahrzeug steht ein **Hinweis** („Marke unbekannt –
     Händler-VK 5 % niedriger angesetzt; Marke beim Verkäufer erfragen, dann neu bewerten“); er sperrt nichts, das Anschreiben bleibt
     unverändert (keine automatische Verkäuferansprache).
  2. **Spannen:** Max-EK und Marktwert privat zusätzlich als Spanne aus der Marktspanne (unteres/oberes Ende durch dieselbe
     Rechenkette), auf **500 € nach außen** gerundet (seit P5-05 auf Wunsch des Betreibers **100 €**, ADR-056) – die Spanne umschließt den Punktwert immer und ist nie 0 € breit. Oberfläche (Karte und Handy-Liste): „Max-EK (Spanne) 23.500–32.500 €“, darunter klein „Mitte
     28.100 €“; im Detail eine Spannen-Zeile, die Punktwerte dienen nur der Herleitung. Ampel, Erstangebot und Anschreiben rechnen weiter
     mit dem Punktwert (ein Brief braucht einen Betrag). Ohne Marktwert (Sicherheit „keine“) oder bei manuellem Marktwert keine Spanne.
     Bei unbekannter Art die weiteste Spanne aller Kandidaten.
  3. **Mängelliste:** im Inserat genannte Mängel (negative Wertfaktoren aus `config.yaml`, verneinte Nennungen zählen nicht) als
     `Bewertung.maengel`, der schwerste zuerst – auch ohne Erstzulassung. Karte und Handy-Liste: rote Zeile „Mängel laut Inserat: …“;
     Detail: Liste „Im Inserat genannte Mängel – bei der Besichtigung prüfen“ mit dem Abzug im Referenzwert.
  4. Kalkulation: Rechenstand **E3**, der Abschlag wird eingefroren und in den Annahmen genannt; Verkaufsanfragen zeigen Spanne,
     Hinweis und Mängel ebenso. Der Plan beim Kauf speichert den Abschlag; die Kalibrierung (ADR-052) wertet Fälle mit Abschlag
     getrennt aus und schlägt dafür `rechner.abschlag_marke_unbekannt` vor, nicht den Händleraufschlag.
* **Alternativen:** Abschlag auf den Marktwert (würde Erstangebot und Fair-Untergrenze gegenüber dem Verkäufer senken – nicht gewollt,
  es geht um den Wiederverkauf); nur noch Spannen ohne Punktwert (Ampel, Brief und Verhandlungs-Assistent brauchen einen Betrag);
  effektive Fallzahl für die Spanne (offen für eine spätere Kalibrierung).
* **Folgen / offen:** Fahrzeuge ohne erkennbare Marke landen seltener auf Grün. Die Spanne ist bei dünner Datenlage breit (±15 % auf
  das Marktniveau, nach Kosten oft ±20 % auf den Max-EK) – gewollt sichtbar. Betreiberfragen: Rundung auf 500 €; ob die Spanne auch im
  Verkäuferportal bzw. Händlerportal anders erscheinen soll (dort unverändert).

## ADR-055 – Angebots- gegen Abschlusspreise, Händler- gegen Privatpreise: Händlermarkt als Obergrenze, Marktbeobachtung · gilt (25.10.2026)

* **Kontext:** P5-04, Schwäche S4 der Rechner-Analyse: Der Rechner kennt nur Angebotspreise privater Inserate und setzt pauschal 7 % für
  Angebot → Abschluss an; Händlerangebote fließen gar nicht ein. Kein Portal liefert echte Abschlusspreise – die einzigen sind die eigenen
  Ankäufe und Verkäufe (Kalibrierung, ADR-052).
* **Entscheidung:**
  1. **Privat und Händler getrennt.** Marktwert und Marktwert privat bleiben reine Privatsicht (gewerbliche und unbekannte Anbieter zählen
     dort nie). Händlerangebote (`gewerblich` ausdrücklich gesetzt) bilden eine eigene **Händlermarkt-Sicht** mit derselben Auswahl,
     Ähnlichkeit und Ausreißerbehandlung (ADR-053).
  2. **Händlermarkt als Obergrenze** für den eigenen Händler-VK: ab `rechner.haendler_vergleich_min` (3) vergleichbaren Händlerangeboten
     gilt Händler-VK ≤ Niveau ihrer Angebotspreise × (1 − `abschlag_haendler_angebot`, 5 % Verhandlung beim Händler). Teurer als
     vergleichbare Händler kann ein Händler nicht verkaufen. Die Obergrenze wirkt nur nach unten (nie Aufschlag); Kosten, Marge, Max-EK,
     Ampel und Erstangebot folgen. **Schutz vor Miet-, Raten- und Lockangeboten** (QA B1): Händlerangebote unter 80 % des privaten
     Marktniveaus zählen nicht (die Erklärung nennt sie); liegt das Händlerniveau danach unter dem privaten, ist das ein **Datenkonflikt**
     – keine Obergrenze; der Händler-VK sinkt nie unter den Marktwert privat. Die Spanne nutzt die Streuung der Händlerangebote
     (Obergrenze am unteren/oberen Viertel, in der Kalkulation je Szenario), die Sicherheit ist bei aktiver Obergrenze höchstens
     „mittel“ (QA B2). Abschaltbar (`haendler_vk_deckel: false`, auch 0/„nein“/„aus“). Erklärung und Detail nennen Anzahl, Niveau und
     ob begrenzt wurde.
  3. **Marktbeobachtung** (Kalibrierungsbericht, Seite, CLI): private **Fahrzeuge**, deren Inserate alle vom Markt verschwunden sind
     (verkauft, offline oder vermutlich offline nach der Regel der App) – erster Preis über alle Inserate gegen den letzten; wieder
     eingestellte oder mehrfach inserierte Fahrzeuge zählen einmal bzw. gar nicht, solange ein Inserat verfügbar ist (QA B3). Die Senkung bis zum
     Verschwinden ist eine **Untergrenze** für den Abschlag Angebot → Abschluss (verhandelt wird danach noch). Liegt ihr Median über dem
     eingestellten Abschlag (ab 5 Inseraten), gibt es einen Hinweis; geändert wird nichts.
  4. Kalkulation: Rechenstand **E4**; der Auszug enthält die Händlerangebote, die Standardwerte werden eingefroren, die Annahmen nennen
     eine Begrenzung.
* **Alternativen:** Händlerangebote mit einem festen Faktor in den Privatmarkt mischen (Händleraufschläge schwanken stark nach Marke,
  Alter und Garantieleistung – die Mischung würde den Privatmarkt verzerren); Abschlag Angebot → Abschluss automatisch aus der
  Marktbeobachtung setzen (nur Untergrenze, außerdem verschwinden Inserate auch ohne Verkauf).
* **Folgen / offen:** Die Obergrenze greift nur, wenn das Händlerniveau zwischen dem Privatniveau und etwa +8 % liegt, und senkt den
  Händler-VK dann um höchstens rund 7 % (bis auf den Marktwert privat); deutlich billigere Händlerangebote gelten als Miet-/Lockangebote
  oder Datenkonflikt. Die Händlersicht ist so
  gut wie die Anbietererkennung (ADR-043). Betreiberfragen: Mindestzahl 3 und 5 % Verhandlung beim Händler bestätigen.

## ADR-056 – Ausstattung, Mängel und Kostenrisiken: Gewährleistung nach Alter, Standzeit nach Saison, Kapitalbindung, Mängelrisiko · gilt (25.10.2026)

* **Kontext:** P5-05 (Schwächen S5/S6): Gewährleistungsrücklage pauschal 2,5 %, Standzeit fest 3 Monate unabhängig vom Kaufmonat,
  gebundenes Kapital kostet nichts, schwere Mängel (Motor, Getriebe, Unfall) fehlten in der Liste, und das unklare Ausmaß genannter
  Mängel war in Spanne und Sicherheit nicht sichtbar. Dazu Betreiberwunsch vom 25.10.2026: Spannen nur auf 100 € runden.
* **Entscheidung:**
  1. **Gewährleistungsrücklage nach Alter** (`kosten.gewaehrleistung_staffel`): bis 5 J. 2,0 %, bis 10 J. 2,5 %, bis 15 J. 3,5 %, darüber
     4,5 % vom Händler-VK. Ohne Staffel der bisherige feste Satz.
  2. **Standzeit nach Saison** (`kosten.standzeit_saison_zuschlag`, Monat → zusätzliche Monate): September +1, Oktober/November +2,
     Dezember/Januar +1 – im Herbst gekauft, im Frühjahr verkauft. Gilt für Standkosten, Kapitalbindung, den Plan beim Ankauf und die
     Kalibrierung (Standzeit-Vorschlag bleibt relativ zum Grundwert).
  3. **Kapitalbindung** als Kostenposten: Händler-VK × 0,8 (gebundenes Kapital ≈ Einkauf + Kosten) × 5 % p. a. × Standzeit. 0 = aus.
  4. **Mängel:** neue Wertfaktoren Motorschaden −15 %, Getriebeschaden −10 %, Unfallschaden −8 % (verneinte Nennungen wie „unfallfrei“
     zählen nicht; erledigte Reparaturen wie „Zylinderkopfdichtung neu“ ebenfalls nicht), Ausstattung Anhängerkupplung und
     Dieselheizung je +0,5 % („Webasto“ nur mit Standheizung/Air Top). Der Deckel für Mängelabzüge steigt von 15 % auf 25 %
     (`wertfaktoren.max_minus`), sonst zählte ein zweiter schwerer Mangel neben einem Motorschaden nicht. „Defekt genannt“ (−4 %) kann
     zusätzlich zu einem bestimmten Mangel zählen („Getriebe defekt“) – bewusst, die Summe bleibt gedeckelt. **Mängelrisiko:** Der Punktwert enthält den Abzug; weil das
     Ausmaß im Inserat unklar ist, reicht die untere Spanne um die Summe der Mängelabzüge weiter nach unten (höchstens 15 %,
     `maengelrisiko_max`), ebenso das Kalkulationsszenario „vorsichtig“. Ein schwerer Mangel (voller Abzug laut config.yaml ≥ 5 %)
     senkt die Sicherheit auf höchstens „mittel“, zwei oder mehr auf „niedrig“, und erzeugt einen Hinweis an den Ankäufer („Ausmaß bei
     der Besichtigung klären“) – sperrt nichts.
  5. **Spannen auf 100 €** nach außen gerundet (statt 500 €), ebenso das Händlermarkt-Niveau.
  6. Kalkulation: Rechenstand **E5**; alle neuen Werte werden eingefroren (ohne Eintrag: altes Verhalten). Der Plan beim Ankauf
     übernimmt die Standzeit aus derselben Bewertung bzw. Kalkulation und speichert die Kapitalbindung getrennt; die Kalibrierung
     vergleicht Ist-Kosten mit den Plankosten **ohne** Kapitalbindung (sie fällt nie als Ausgabe an). Fehleingaben bei den
     Saisonzuschlägen melden sich verständlich.
* **Alternativen:** Reparaturreserve je Mangel zusätzlich zum Wertabzug (Doppelzählung); Mängel aus der Besichtigung automatisch in die
  Inseratsbewertung zurückschreiben (die Besichtigung hat eine eigene, verbindlichere Abzugsrechnung – offen für später).
* **Folgen / offen:** Im Herbst gekaufte Fahrzeuge bekommen einen niedrigeren Max-EK (Beispiel Teilintegrierter 2018: rund 2 Monate
  mehr Standkosten und Kapitalbindung). Die Saisonwerte sind Annahmen; die Kalibrierung zeigt mit der Zeit, ob sie stimmen.
  Alle Ampeln können zum 1. September, 1. Oktober, 1. Dezember und 1. Februar umspringen (Saisonwechsel) – gewollt.
  Betreiberfragen: Staffel, Saisonzuschläge, Zinssatz, Mängelrisiko-Deckel.

## ADR-057 – Abholung: Auto ab Firmensitz oder Bahn ab Stuttgart Hbf, der günstigere Weg zählt · gilt (27.10.2026)

* **Kontext:** P5-06 (Schwäche S6): Transport war Grundpauschale 80 € + 0,90 €/km ab `anschreiben.plz` (bisher Stuttgart). Betreiber
  27.10.2026: „ausgehend von Besigheim (mit dem Auto) oder von Stuttgart Hbf mit dem Zug – ungefähre ICE-Ticketpreise und Reisezeit mit
  öffentlichen Verkehrsmitteln“.
* **Entscheidung:**
  1. **Firmensitz Besigheim** (`anschreiben.plz: "74354"`; die genannte 74534 gibt es nicht) – gilt auch für die angezeigte Entfernung
     und den Entfernungsfilter der Anschreiben.
  2. **Zwei Wege** (`rechner.kosten.abholung`), der günstigere geht in die Kosten: **Auto** – zwei Personen im PKW hin, zurück eine im
     Wohnmobil, eine im PKW (PKW 0,30 €/km hin und zurück, 90 km/h); **Bahn** – eine Person: Zubringer Firmensitz → Stuttgart Hbf
     (6 €, ½ Std.), ICE-Ticket grob 0,30 €/km Schienenstrecke (mindestens 12 €, höchstens 160 € – Flexpreis 2. Klasse ohne BahnCard,
     Sparpreise oft günstiger, aber nicht planbar), Reiseschnitt 110 km/h plus ¾ Std. für den Weg zum Verkäufer; zurück im Wohnmobil zum
     Firmensitz. Beide: Wohnmobil 0,25 €/km bei 80 km/h, 1 Std. Übergabe je Person vor Ort, Zeit je Person × 25 €/h; mehr als 10 Std. je
     Person → je weiterem Tag eine Übernachtung (90 € je Person).
  3. **Strecken** aus PLZ geschätzt (Luftlinie × 1,25 wie bisher) – keine Abrufe bei Routen- oder Fahrplandiensten (Regel 12), keine
     Preisauskunft. Anzeige gerundet: Euro auf 10 €, Ticket auf 5 € aufgerundet, Zeiten auf Viertelstunden, mit „ca.“.
  4. **Händlerstandorte** (Deal-Kalkulation ab Standort): nur Auto ab dem Standort, keine Bahn ab Stuttgart.
  5. **Kalkulation E6:** Abholwerte samt Standardwerten und der Entfernung Firmensitz → Bahnhof eingefroren; gespeichert werden die
     Strecken auf 10 km gerundet (`entfernung_km`, `entfernung_bahn_km`), nicht die PLZ des Verkäufers – zwei genaue Entfernungen von
     zwei bekannten Orten verrieten sie (QA B2). Ohne Abschnitt `abholung` (leer oder `false`) gilt die alte Formel – gespeicherte
     E5-Kalkulationen rechnen unverändert. Fehleingaben (auch NaN, unbekannte Schlüssel als Tippfehler, unbekannte Bahnhofs-PLZ) melden
     sich verständlich (QA B3).
  6. **Firmensitz weit vom Bahnhof** (z. B. Mandant mit eigenem Sitz): mehr als 80 km (`bahn.zubringer_max_km`) → die Bahn-Variante
     entfällt mit Hinweis „Bahn ab … nicht gerechnet“, statt die Anreise zum Bahnhof zu vergessen (QA B1). Im Nahbereich (unter 50 km
     Bahnstrecke) heißt das Ticket „Nahverkehrsticket“ (QA B4).
* **Alternativen:** Fahrplan-/Routen-API (Netzabruf, Nutzungsbedingungen ungeklärt – später über eine freigegebene Schnittstelle
  möglich); Transport durch Dienstleister (Überführungsfirma) als dritter Weg – vorbereitet durch die Variantenliste, Preise fehlen.
* **Folgen / offen:** Bis ~30 km ist das Auto günstiger, darüber meist die Bahn. Beispiele ab Besigheim: Bietigheim ca. 70 €, München
  ca. 330 € (Bahn, Ticket ca. 75 €), Köln ca. 440 €, Hamburg ca. 820 € (Ticket ca. 160 €, eine Übernachtung) – im Nahbereich günstiger,
  in der Ferne teurer als die alte Formel. Ticketpreise, Stundensatz, Übernachtung und Übergabezeit sind Annahmen; die Kalibrierung
  vergleicht sie mit tatsächlichen Transportkosten.
## ADR-058 – Aufbewahrungsfristen: ein Plan für alle Personendaten, ein Wartungsschritt für Einzelplatz, Kommandozeile und Server · gilt (27.10.2026)

* **Kontext:** F10 (Betreiber 27.10.2026: „Aufbewahrungsfristen nach DSGVO etablieren und vorbereiten für spätere Serveranbindung“).
  Bisher gab es nur die Inseratsfrist (P1-14a, Standard aus); Verkaufsanfragen ohne Widerruf, Audit-Protokoll, Sitzungen und
  gespeicherte Seiten in `import/eingelesen/` hatten keinen Löschweg, Kaufunterlagen keine Frist.
* **Entscheidung:**
  1. **Fristen in `config.yaml` → `datenschutz`** (0 = aus, fehlender Eintrag = 0, damit alte Konfigurationen nichts Neues löschen):
     Inserate 6 Monate, Verkaufsanfragen ohne Ankauf 12 Monate, abgelaufene Sitzungen 30 Tage, Audit 24 Monate, Kaufunterlagen 10 Jahre
     ab Ende des Kalenderjahres (nur melden). Tippfehler-Schlüssel werden gemeldet.
  2. **Ein Wartungsschritt** (`wmscout/aufbewahrung.py`): `bericht` (nur Anzahlen, ändert nichts) und `ausfuehren` (vorher Sicherung
     der Datenbank in ihren Sicherungsordner, jede Kategorie für sich – ein Fehler hält die anderen nicht auf). Idempotent.
  3. **Verkaufsanfragen** über denselben Weg wie der Widerruf (`grund="frist"`): Verkäufer, Freitexte, Fotos, Besichtigung; Status
     bleibt; nie mit Ankaufsvorgang (auch storniert) oder offener Besichtigung.
  4. **Audit** bleibt nur anfügbar; der Lösch-Trigger wird nur für die Frist in derselben Transaktion entfernt und wiederhergestellt.
     Ein Nachweis-Eintrag nennt nur Anzahlen je Kategorie.
  5. **Kaufunterlagen** werden nie automatisch gelöscht – Aufbewahrungspflichten (HGB/AO) und Einzelfälle (Gewährleistung,
     Rechtsstreit) verlangen eine Prüfung.
  6. **Aufrufer:** beim Start der App und nach Suchlauf/Import (`automatisch: ja`; ausgeliefert `nur_bericht`), Kommandozeile
     `scout.py datenschutz [--ausfuehren --bestaetigt] [--json] [--alle-mandanten]`, App für den Inhaber (`/api/datenschutz`). Für den
     Server ist kein Dauerprozess vorgesehen (Regel 13), sondern ein täglicher Aufruf per Aufgabenplanung je Mandant.
* **Alternativen:** Fristen fest im Code (nicht anpassbar ohne Release); Löschen der Kaufunterlagen nach Fristablauf (zu riskant ohne
  Prüfung); eigener Scheduler-Thread (Dauerprozess, Regel 13).
  7. **Korrekturrunde (QA-Ablehnung):** Sicherung vor dem Löschen höchstens einmal je Tag mit eigener Rotation (die allgemeine Rotation
     verdrängte manuelle Vollsicherungen und Migrationssicherungen, B1); Tests nutzen eigene Sicherungs- und Import-Ordner (B2);
     Inserate mit Ankaufsvorgang sind nie fällig (B3); ausgeliefert `automatisch: nur_bericht` mit Bericht auf der Statusseite – der
     Betreiber schaltet nach Prüfung auf `ja` (B4); abgelegte Seiten zählen ab dem Ablegen (B5); Audit-Nachweis auch im Automatikbetrieb
     (B6); Mandanten einzeln geladen, Fehler isoliert (B7); nach der Löschung neu eingetragene Angaben werden wieder fällig (B8);
     Storno und Verlauf zählen für die Kaufunterlagen-Frist (B9); Anfragen mit laufender oder unentschiedener Auktion nie fällig (B10).
* **Folgen / offen:** Nach dem Update ändert sich ohne Zutun nichts (nur Bericht). Wird `automatisch: ja` gesetzt oder einmal ausgeführt,
  werden Altbestände über der Frist anonymisiert (vorher Sicherung). Juristische Prüfung der Fristen und von Protokoll/E-Mail-Auswertung
  bleibt offen (F10). Gelöschtes bleibt bis zur Rotation in Sicherungen.
## ADR-059 – Kunden-Zugänge: Einladungslink für den ersten Login, Händlerzugänge bei mobile.de/AutoScout24 ohne Geheimnisse · gilt (27.10.2026)

* **Kontext:** F4 (Betreiber 27.10.2026): „Kunden sind als Händler registriert – soll vorbereitet sein zum Einpflegen und einfachen Login
  für Kunden der fertigen Software. Test wird dann durchgeführt.“ Bisher: Zugänge nur per Kommandozeile mit Passworteingabe durch den
  Betreiber; kein Ort für die Händlerdaten der Kunden; die Search-API von mobile.de braucht einen vom Kundenservice freigeschalteten
  API-Account, AutoScout24 hat nur eine Einstell-API (docs/SOURCES.md).
* **Entscheidung:**
  1. **Einladung statt Passwortübergabe:** `scout.py [--mandant K] nutzer einladen NAME --rolle inhaber` bzw. „Zugänge“ in der App
     (Inhaber) legt den Zugang ohne bekanntes Passwort an und gibt einen Einmal-Link `…/einladung#<Code>` aus (7 Tage, nur einmal,
     gespeichert nur der Hash; eine neue Einladung macht die alte ungültig). Der Code steht hinter `#` und erreicht den Server nie als
     Adresse (nicht im Protokoll); die Seite sendet ihn per POST. Einlösen setzt das Passwort, beendet alte Sitzungen und meldet an;
     Fehlversuche gebremst wie die Anmeldung, im Audit als „einladung“.
  2. **Händlerzugänge je Firma** (`plattform_zugaenge`, Schema v21): Händlernummer, API-Benutzer und nur der **Name** der
     Umgebungsvariable mit dem Passwort (Regel 5); der Name muss mit `WMSCOUT_` beginnen, damit über die Oberfläche keine andere
     Server-Variable an einen Anbieter gesendet werden kann. Vorschlag `WMSCOUT_<MANDANT>_MOBILEDE_PASSWORT`.
  3. **Verbindungstest** (nur Inhaber, ausdrücklicher Klick): genau eine HTTPS-Anfrage an die Search-API (Basic-Anmeldung, JSON-Kopf –
     Annahmen aus der öffentlichen Übersicht, mit echtem Zugang zu bestätigen), ohne globale Sperre; gespeichert werden nur Status und
     Aufbau der Antwort (Schlüssel, Anzahl), keine Inserate. 401/403/429 werden gemeldet, nie wiederholt.
  4. **Kein Datenabruf** bis zur Freigabe (Regel 12): Der mobile.de-Adapter (P2-08) folgt erst nach dem Test mit echtem API-Account und
     schriftlicher Klärung der Bedingungen (Speicherdauer laut älteren Bedingungen „maximal 24 Stunden“ – Konflikt mit der Preishistorie).
     AutoScout24: nur Händlernummer; neue Angebote weiter über Suchaufträge per E-Mail.
* **Alternativen:** Passwörter verschlüsselt in der Datenbank (bräuchte eine Krypto-Bibliothek und einen Server-Schlüssel – Betreiberentscheidung,
  falls Kunden ihr Passwort selbst eintragen sollen); Anmeldung „mit mobile.de“ (kein öffentlicher Login-Dienst bekannt).
  5. **Korrekturrunde (QA):** Vorhandene Zugänge nur ausdrücklich (`erneut`) und nur mit ihrer Rolle neu einladen – eine Einladung übernimmt
     nie still ein Konto mit anderer Rolle (B2); bis zum Einlösen steht statt eines Hashs ein Platzhalter, eine Anmeldung ist unmöglich,
     angelegt in einer Transaktion (B10); im Einzelplatz meldet die erste Einladung, dass ab jetzt eine Anmeldung nötig ist, und die Seite
     lädt nicht neu (B1); im Mandantenbetrieb nur Variablen `WMSCOUT_<KENNUNG>_…` – alle Mandanten teilen die Umgebung des Servers (B3);
     Verbindungstest auch bei 5xx ohne Wiederholung (B4); auch die Code-Prüfung ist gebremst und prüft die Herkunft (B6); alte Einladungen
     werden aufgeräumt (B8). Die Bremse zählt je IP: hinter einem Proxy `vertrauter_proxy: true` setzen, sonst teilen sich alle eine Grenze (B7).
* **Folgen / offen:** Für den Test braucht der Kunde einen freigeschalteten API-Account; der Betreiber setzt die Umgebungsvariable und gibt den
  Verbindungstest frei (SOURCES: PRÜFEN). Antwortformat und Pfad nicht gegen eine echte Antwort geprüft (Doku von hier nicht erreichbar).
