# Testbericht

Nur tatsächlich ausgeführte Prüfungen. Nicht Ausgeführtes steht unter „nicht geprüft“. Neueste Einträge oben.

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
