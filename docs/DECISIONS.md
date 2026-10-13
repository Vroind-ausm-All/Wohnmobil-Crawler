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
* **Entscheidung:** Adapter bleibt mit `freigegeben = False` gekennzeichnet. Neue Projektregel: unzulässige
  Direkt-Crawler **nicht standardmäßig aktiv**. Umsetzung (Abschaltung per Voreinstellung, Ersatz durch zulässige
  Eingangskanäle) ist Backlog-Paket in Phase 2 und braucht die Zustimmung des Betreibers, weil sie den heutigen
  Arbeitsablauf ändert.
* **Folgen:** Bis zur Entscheidung läuft der bestehende Abruf nur, wenn der Betreiber ihn startet; das Protokoll weist
  bei jedem Lauf darauf hin.

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
* **Folgen:** Pakete, die aufeinander aufbauen, werden nacheinander gemergt.

## ADR-009 – Versionierte Migrationen mit Backup · vorgeschlagen (Umsetzung Phase 1)

* **Kontext:** Heute ergänzt `wmscout/datenbank.py` fehlende Spalten per `ALTER TABLE` beim Start, ohne Version und
  ohne Backup. Die Phasen 2–3 brauchen tiefgreifende Schemaänderungen (Fahrzeuge/Inserate getrennt, Historie).
* **Entscheidung:** Tabelle `schema_version`; nummerierte, idempotente Migrationsschritte in je einer Transaktion;
  vorher Backup über die SQLite-Backup-API mit `PRAGMA integrity_check`; Test mit Datenbanken jeder Vorversion;
  Kompatibilitäts-View `anzeigen` während des Umbaus.
* **Folgen:** Kein Schemawechsel ohne Rückweg; die bestehenden `ALTER TABLE`-Ergänzungen werden Migration 1–2.
