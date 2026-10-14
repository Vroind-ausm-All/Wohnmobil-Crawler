# Arbeitsprotokoll (WORKLOG)

Neueste Einträge oben. Vorlage und Regeln: Skill `scout-cycle` (`.claude/skills/scout-cycle/SKILL.md`).
Nur tatsächlich Erledigtes und tatsächlich ausgeführte Tests. Nicht Ausgeführtes heißt „nicht geprüft“, ein fehlender
Wert „–“.

---

## Phase 2 (vorgezogen) – Gespeicherte Seiten einlesen, wieder aufgenommen (14.10.2026)

### P2-05 (Teil) – Hinweise statt Sperre, Anrede mit Verkäufername · Status: REVIEW

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
