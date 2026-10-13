# Testbericht

Nur tatsächlich ausgeführte Prüfungen. Nicht Ausgeführtes steht unter „nicht geprüft“. Neueste Einträge oben.

---

## P2-05 (Teil) – Gespeicherte Seiten einlesen (13.10.2026) · BLOCKED

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
| R3 | KRITISCH | Keine Backups, keine Schemaversion; blockiert jede Migration | `datenbank.py:49-53` | P1-02, P1-03 |
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
| Q18 | NIEDRIG | Irreführender Kommentar zur Thread-Nutzung | `datenbank.py:45` | P1-04 |

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
