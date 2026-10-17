# Testbericht

Nur tatsächlich ausgeführte Prüfungen. Nicht Ausgeführtes steht unter „nicht geprüft“. Neueste Einträge oben.

---

## P2-06 – E-Mail-Suchagenten (.eml) (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13, vom Orchestrator, Stand vor Zusammenführung mit P2-05) | 1048 bestanden (vorher 940), neu `test_email_eingang.py`, `test_email_haertung.py`, `test_email_betrieb.py` |
| `ruff check .` | grün |
| Kein Netzabruf (Sockets und urllib gesperrt), Links aus Mails nie abgerufen | bestanden |
| Angriffsmails der QA (5 MB Links, 200 000 `[`, 40 000 Encoded Words, 100 000 MIME-Teile, tiefe Verschachtelung) | ≤ 2,5 s, ≤ 152 MB, sonst sauber abgelehnt (vorher bis 253 s bzw. MemoryError) |
| Preis nur aus Preiszeile; ältere Mail ändert neueren Preis nicht; Mails nach Datum gelesen | bestanden; Gegenprobe Altersprüfung aus → rot |
| Seite → Mail → Seite ohne zusätzliche Beobachtungen; Löschfrist inkl. Symlink-Schutz | bestanden |
| Schalter (CLI, API, Importer), Rollen (nur Inhaber), CSRF, Ordner aus der Anfrage ignoriert | bestanden |
| QA Runde 1 / Runde 2 | Freigabe mit Auflagen / Ablehnung (K1) – behoben; Runde 3 von der QA **nicht geprüft** |
| Echte Kleinanzeigen-/mobile.de-Mails (F3), Knopf im Browser, Windows-CI | nicht geprüft |

## P2-04 – Quellen und Eingänge schaltbar (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 940 bestanden (vorher 907), neu `test_schalter.py` (31), Ergänzungen in `test_mandanten.py` |
| `ruff check .` | grün |
| Nicht freigegebene Quelle im Suchlauf: kein Abruf, `uebersprungen` gemeldet, `fehler` bleibt leer | bestanden |
| `quellen an`/`aus` für nicht freigegebene Quelle → Exit ≠ 0, Tabelle unverändert; `aus` für freigegebene Quelle bleibt nach Neustart wirksam | bestanden |
| Detailabruf: gesperrte Zeilen verbrauchen das Limit nicht, werden nicht abgerufen | bestanden |
| Ereignis-Eingang `api` mit Tabellenfreigabe, aber gesperrter Adapterklasse → abgewiesen | bestanden |
| Eingang `seiten` abgeschaltet: `/api/import` → 409 `deaktiviert`, CLI liest nichts; Mandant A aus, Mandant B an | bestanden |
| Ungültiges `eingaenge` (Einzelbetrieb, `mandant.yaml`) → Start bricht mit Meldung ab | bestanden |
| Gegenproben (7 nach QA) | alle erkannt |
| Warnhinweis (15 s) im Browser, Windows-CI | nicht geprüft (CI folgt im PR) |

## P2-00 – Eingang-Schnittstelle (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 907 bestanden (vorher 891), neu `test_eingang.py` (16) |
| `ruff check .` | grün |
| Seitenimport-, mobile.de-, Kleinanzeigen-, Ereignis- und v4-Tests | unverändert grün (Testdaten „mobilede“ → „mobile.de“; Ereignisse über `api` mit Freigabe) |
| `SeitenEingang.lese` ohne Netz (Socket gesperrt) und ohne Datenbank | bestanden |
| Dasselbe Inserat über `manuell` und `email` → eine Zeile in `inserate`/`anzeigen`, keine doppelte Historie | bestanden |
| Unbekannte Plattform/Kanal, fremdes ID-Präfix, gemischte Lesung, `detail_ohne_id` → nichts geschrieben | bestanden |
| Ereignisspeicher weist `email`/`manuell` ab (ADR-035) | bestanden |
| QA: alle 6 Testseiten unter `tests/seiten/` passieren die ID-Prüfung; Dekodierung alt/neu an 20.005 Eingaben verglichen | 0 Abweisungen; 1 Abweichung (doppelte BOM, harmlos) |
| Gegenproben (9) | alle erkannt |
| Windows-CI, echte Betreiberdaten | nicht geprüft (CI folgt im PR) |

## Phase 1 – Abschluss (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | **891 bestanden** (vorher 853), neu u. a. `test_rechner_ohne_ez.py` (4), `test_phase1_abschluss.py` (17), `test_netz.py` (9), `test_app_threads.py` (7) |
| `ruff check .` | grün |
| P1-12: ohne EZ keine Beträge in Rechner, CSV, API, CLI; Besichtigung nur mit Marktwert (409 `grund=marktwert`); Invariante Erstangebot ≤ Max-EK ≤ VK über 96 Kombinationen | bestanden |
| P1-07: zwei Clients, veraltete Version → 409 mit aktuellem Stand; Planen nach Abschluss → 409 | bestanden |
| P1-15: HTTP je Rolle (Mitarbeiter: „gekauft“, Suchlauf, Import → 403; Knöpfe ausgeblendet) | bestanden |
| P1-14a: Anonymisierung (Profilname, Anschreiben, Besichtigungsangaben, Datei), gekauft geschützt, Frist, CLI | bestanden |
| P1-05: hängender WhatsApp-Versand blockiert andere Anfragen nicht | bestanden |
| P1-08: Bewertungsmodule laden weder `wmscout.datenbank` noch `sqlite3`; gleiche Ergebnisse aus Listen und Datenbank | bestanden |
| P1-09: `config.local.yaml` überlagert (auch über die CLI), ungültige Datei → Abbruch mit Meldung; `--passwort` abgelehnt | bestanden |
| P1-10: Python-Version in `pyproject.toml`, Installern, `scout.py`, Lock-Dateien einheitlich 3.13 | bestanden |
| Abdeckung (coverage 7.16, nur zum Messen außerhalb des Projekts installiert, gesamte Suite) | `netz.py` 97 %, `app.py` 79 %, `benachrichtigung.py` 86 % (vorher 27 % / 67 % / 81 %) |
| Gegenproben P1-11 (403/429 nicht mehr gesperrt; keine Pause bei 5xx; Auto-Suche ohne Fehlerbehandlung; kein STARTTLS) | alle 4 erkannt |
| Gegenproben P1-12, P1-07, P1-15, P1-14a, P1-05, P1-08, P1-09 | alle erkannt (zwei zunächst wirkungslose Gegenproben ersetzt) |
| Browser-Klicktest Handy (Chromium, 390 px): Inserat ohne EZ zeigt „Erstangebot –“, „Planen“ fragt nach dem Marktwert, Besichtigung mit `marktwert_manuell` 36.000 €; zwei Geräte: Konflikt → „anderen Stand laden“ übernimmt fremde Eingabe, „eigene behalten“ speichert die eigene | bestanden, 0 JS-Fehler (nur die erwarteten 409 in der Konsole) |
| Unabhängige QA-Prüfung (`qa-security-reviewer`, 881 Tests nachgestellt) | Freigabe mit Auflagen, kein KRITISCH; 1 HOCH (N1), 7 MITTEL, 8 NIEDRIG – alle behoben bis auf die unten genannten Reste, je mit Test |
| Gegenproben zu den QA-Korrekturen (N1 API, N1 Plan, N2, N6, Q6, Q15, N5, N8, N9, N4, offene Besichtigung) | alle 11 erkannt; eine weitere (Plan-Absicherung für ältere Besichtigungen) zunächst nicht erkannt → eigener Test ergänzt, danach erkannt |
| Browser (Chromium): Login mit `weiter=/.//evil.example`, `https://evil.example/`, `/\evil.example` → `/m`; `/m#/termine`, `/anfragen` bleiben | bestanden, 0 JS-Fehler |
| Browser: Service Worker speichert abgeschlossene Besichtigung nicht, offene schon | bestanden |
| `pip install` aus den neuen Lock-Dateien, Windows-CI, `installieren.bat` mit vorhandener 3.12-`.venv` | nicht geprüft (Windows-CI folgt im PR) |

**Stand der Befunde aus Phase 0 (Q1–Q18) nach Phase 1** – unabhängig geprüft (`qa-security-reviewer`), danach behoben wie angegeben:

| Befund | Stand | Beleg |
|---|---|---|
| Q1 KRITISCH | behoben (P1-12, Rest N1 behoben) | `test_rechner_ohne_ez.py`, `test_ankauf_ohne_ez_plant_mit_manuellem_marktwert` |
| Q2 HOCH | behoben (G0) | `test_sicherheit::test_negative_oder_kaputte_laenge_wird_sofort_abgelehnt` |
| Q3 HOCH | behoben: Widerruf (G0), Inserate (P1-14a) mit Frist – **Frist legt der Betreiber fest (Standard aus)** | `test_phase1_abschluss` (3 Tests) |
| Q4 | Betreiberentscheidung F11 „Lesen frei“ | `docs/ROLLEN.md` |
| Q5 | behoben (P1-15, N2) | `test_gekauft_verlassen_nur_inhaber`, Rollen-Tests |
| Q6 | behoben (serverseitige Prüfung) | `test_login_ziel_nur_eigene_pfade`, Browser-Test |
| Q7, Q8 | behoben (G0) | `test_ohne_nutzer_ist_ein_proxy_nicht_lokal`, `test_login_bremse_*` |
| Q9 | behoben bis auf bewusste Ausnahmen (`/api/ich`, Fotos offener Besichtigungen) | `test_abgeschlossene_besichtigung_nicht_auf_dem_geraet`, Browser-Test |
| Q10 | offen bis P3-07 (ADR-034) | – |
| Q11 | behoben (Rotation, Maskierung G0; Diagnose-Rohseiten mit Frist) | `test_frist_offene_besichtigung_…` |
| Q12 | behoben (P1-07) | `test_besichtigung_speichern_mit_version_und_planen_nach_abschluss` |
| Q13 | behoben | `test_ics_ohne_nacktes_cr_und_zustaendig_400` |
| Q14 | teilweise: `Secure` und Leerlauf erledigt (G0/G0b); CSRF-Token je Prozess bleibt | `test_cookie_secure_*` |
| Q15 | behoben | `test_ics_ohne_nacktes_cr_und_zustaendig_400` |
| Q16 | behoben (P1-09) | `test_team::test_cli_nutzer` |
| Q17 | behoben (P1-10) | `test_python_version_ueberall_gleich` |
| Q18 | behoben (Kommentar) | – |

## Phase G2 – Mandantenfähigkeit (17.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 853 bestanden, davon 6 neu (`test_mandanten.py`) |
| Konfiguration: erzwungene Pfade, verbotene Abschnitte, nicht geerbte Adresse/WhatsApp, doppelte/fehlende Hostnamen | bestanden |
| HTTP: Hostname wählt Mandanten; Zugang und Sitzung von A bei B wertlos; Anfragen, Audit, Live, Nutzung getrennt | bestanden |
| Unbekannter Host → 403 ohne Mandantennamen; 127.0.0.1 nur mit `--lokal` | bestanden |
| CLI `mandant anlegen/liste/nutzung`, `--mandant` | bestanden |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Reverse-Proxy mit mehreren Hostnamen, Windows-CI, Last | nicht geprüft (Windows-CI folgt im PR) |

## Phase G1 – Echtzeit per SSE und Nutzungszähler (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 847 bestanden, davon 7 neu (`test_live.py`) |
| SSE: Ereignis je Rolle, keine Inhalte, kein Ereignis bei abgelehnter Änderung, Wiederaufnahme mit `Last-Event-ID` | bestanden |
| SSE: nur angemeldet (401), Grenze je Zugang (429), Platz nach Ablauf der Lebensdauer frei | bestanden |
| Nutzungszähler aus vorhandenen Daten, nur Inhaber, Monatsformat | bestanden |
| Gegenprobe 7 Schutzstellen | alle erkannt |
| Browser-Klicktest Live (Desktop + Händler 390 px) | Notiz 0,44 s, Auktion 0,8 s, Gebot 0,45 s; 0 JS-Fehler, 0 CSP-Verstöße |
| Reverse-Proxy, Safari/iOS, Last mit vielen Verbindungen, Windows-CI | nicht geprüft (Windows-CI folgt im PR) |

## Phase G0b – Audit-Protokoll, Leerlauf, Rechte je Ankaufsschritt (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 840 bestanden, davon 6 neu (`test_audit.py`); Migrationstests auf v10 |
| Migration v1/v2-Altbestand → v10 | bestanden (Zeilenzahlen inkl. Sitzungen unverändert, Sicherung `vor-v10`) |
| Protokoll: Lesen/Ändern/abgelehnt/Anmeldung, keine Inhalte/Passwörter, nur Inhaber liest, nur anfügbar | bestanden |
| Gesperrte Datenbank: keine offene Transaktion trotz Audit | bestanden (bestehende Sperr-Tests) |
| Leerlauf-Zeitlimit inkl. Sitzungen vor v10 und „0 = aus“ | bestanden |
| Ankaufsschritte nur Zuständiger/Bearbeiter/Inhaber; PDF als Download in Sandbox | bestanden |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Windows-CI, Safari/iOS, großer Audit-Bestand | nicht geprüft (Windows-CI folgt im PR) |

## Phase G0 – Voraussetzungen für Skalierung (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, nach Merge mit Phase F) | 834 bestanden, davon 30 neu (`test_sicherheit.py` 17, `test_datenrechte.py` 6, `test_api_quellen.py` 7) |
| Rohe Verbindung: negative/ungültige Länge, fremder Host | 400 bzw. 403 sofort, Inhalt wird nicht gelesen |
| Login-Bremse, JSON-Pflicht, Origin/Sec-Fetch-Site, Proxy nicht „lokal“, Secure-Cookie | bestanden |
| Widerruf (Web + CLI): Personendaten, Fotos samt Dateien, Auktion, Freigabe | bestanden; zweite Anfrage desselben Verkäufers bleibt |
| Gegenprobe 12 Schutzstellen (9 + 3 nach Merge: Vertragsfoto-EXIF, Storno-Regel, Schwärzung der Besichtigung) | alle erkannt |
| `pip-audit -r requirements.txt` | keine bekannten Schwachstellen |
| Browser-Klicktest Login-Seite + Widerruf-Knopf (mit laufender Auktion) | bestanden, 0 JS-Fehler, 0 CSP-Verstöße |
| Widerruf mit Ankaufsvorgang (auch storniert) | verweigert (409), Verkäuferdaten bleiben |
| Reverse-Proxy, Safari/iOS | nicht geprüft |

## Phase F – Besichtigung und Abwicklung (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 804 bestanden, davon 8 neu (`test_ankauf.py`) |
| Ablauf Anfrage ohne/mit Demo-Zuschlag, Inserat, Ablehnung, Storno | bestanden (Weg, Plan aus nachrechenbarer Kalkulation, Provision nur mit Auktion) |
| Migration v8-Altbestand → v9 | Besichtigungen unverändert, neue Spalte leer, zweiter Lauf ohne Wirkung |
| Gegenprobe 18 Schutzstellen | alle erkannt |
| Browser-Klicktest Desktop + Handy (390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase E – Deal Intelligence (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 796 bestanden, davon 13 neu (`test_deal.py`) |
| Auszug der Vergleichsangebote = ganze Datenbank | gleiche Szenarien und gleicher Risikowert |
| Nachrechnen nach Änderung von Konfiguration und Marktdaten | gespeicherte Kalkulation unverändert, neue ändert sich |
| Manipulation (Ergebnis, Eingabe, Rechenversion, Trigger) | erkannt; CLI `kalkulation pruefen` meldet Abweichung mit Exit-Code ≠ 0 |
| Gegenprobe 14 Schutzstellen | alle erkannt |
| Browser-Klicktest Team + Standort (390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS, große Datenbank | nicht geprüft |

## Phase D – Demo-Auktionssystem (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 783 bestanden, davon 18 neu (`test_auktion.py`) |
| Gleichzeitige Gebote: 4 Prozesse (spawn) × 8 Runden, 3 Threads × 6 Runden | je Runde genau 1 Gebot angenommen, keine Fehler, keine offene Transaktion, Protokoll gültig, `integrity_check` ok |
| Migration v6-Altbestand → v7 | bestanden: Sicherung `vor-v7`, Bestandsdaten unverändert, zweiter Lauf ohne Wirkung |
| Gegenprobe 13 Schutzstellen | alle erkannt (Ende-Prüfung erst nach Testergänzung) |
| Browser-Klicktest Auktion (Desktop + Handybreite 390 px) | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase C – Händlerportal v1 (16.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 765 bestanden, davon 12 neu (`test_haendler.py`) |
| Gegenprobe 6 Schutzstellen | alle erkannt |
| Browser-Klicktest Händlerablauf | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## Phase B – Verkäuferportal v1 (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 753 bestanden, davon 28 neu (`test_verkauf.py`) |
| Migration v1/v2/v4 → v5, parallel 3 Prozesse | bestanden (Versionstests angepasst) |
| Gegenprobe 4 Schutzstellen | alle erkannt (Fotopfad erst nach Testergänzung) |
| Browser-Klicktest `/verkaufen` + `/anfragen` | bestanden, 0 JS-Fehler |
| Windows-CI, Safari/iOS | nicht geprüft |

## T2 + P1-06 – Team-Oberfläche, „gesendet ✓“ (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 725 bestanden, davon 8 neu (`test_team_oberflaeche.py`) |
| `node --check` der ausgelieferten Seite (mit Team, ohne Nutzer, statisch) und `mobil.js`/`sw.js` | ohne Fehler |
| Browser-Klicktest Desktop (Chromium, 3 Nutzer) | Übernehmen, Sperre, Filter, gesendet ✓, Badges, Zähler – bestanden, 0 JS-Fehler |
| Browser-Klicktest Handy (390×844) | Übernehmen, Sperre mit Grund, Filter „Frei“, gesendet ✓ – bestanden, 0 JS-Fehler |
| Safari/iOS, Windows-CI | nicht geprüft |

## P1-04b – `anzeigen` ↔ v4 (15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux) | 717 bestanden, davon 13 neu (`test_v4_abgleich.py`) |
| Gegenproben (5 Kernstellen einzeln entfernt) | jede erkannt (6 / 5 / 1 / 2 / 2 Fehlschläge) |
| Windows-CI | nicht geprüft (folgt im PR) |

## P1-04a/P1-04 – WAL, Sperr-Wartezeit, Laufsperre (14.–15.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q` (Linux, Python 3.13) | 684 bestehende + 12 neue (`test_parallelzugriff.py`) bestanden |
| `ruff check .` | grün |
| Gegenprobe ohne WAL / ohne DELETE-Sicherung / ohne Checkpoint-Prüfung | 5 / 1 / 1 Tests schlagen an |
| Laufsperre (`tests/test_laufsperre.py`, 8 Tests, Linux) | bestanden; Gegenprobe: App, `scout.py lauf`, Wiederherstellung, Freigabe nach Fehler – je 1 Test schlägt an |
| Windows-CI, 2. Lauf (895ba6b) | alle Jobs grün (Tests Windows/Linux, Start-Skripte) |
| Windows-CI, 1. Lauf | 1 Fehlschlag: `test_m2_reste_…` schrieb eine erfundene `-shm` neben die jetzt WAL-Datenbank (unter Windows gesperrt, Errno 22); Test stellt den Fall nun ausdrücklich im Modus DELETE nach |

## T1 – Team-Übersicht Kern und API (14.10.2026) · REVIEW

| Prüfung | Ergebnis |
|---|---|
| `pytest -q -p no:cacheprovider` (Orchestrator, nach Korrekturrunde 1) | **658 passed** |
| `ruff check .` / `node --check sw.js` | All checks passed! / ok |
| QA-Runde 1: Wettlauf 4 Prozesse (43 Runden: übernehmen, kontaktiert, nachgefasst, Dubletten) | je Runde genau ein Gewinner, 0 offene Transaktionen |
| QA-Runde 1: Regression ohne Nutzer (HTTP, DB, CSV, Report gegen e99623e) | gleich bis auf Zeitstempel und neue Felder |
| QA-Runde 1: 19 Mutationen | 19 erkannt |
| QA-Urteil Runde 1 | **FREIGABE MIT AUFLAGEN** (H1 Besichtigung, H2 Verhandlung, H3 Doku) → Korrekturrunde 1 |
| Agent nach Korrekturrunde 1: QA-Skripte (Nebenwege, Wettlauf, Sperre, Dubletten, Inaktive, Suchlauf, Regression) | H1/H2 → 409; 503 statt 500, keine offene Transaktion; 10× `/api/status` mit Team 16,1 s → 0,2 s |
| QA-Runde 2 (f16943d) | FREIGABE MIT AUFLAGEN (Q-H1 Selbsteintragung als Besichtiger) → Korrekturrunde 2 |
| Nach Korrekturrunde 2 (Agent): pytest / Mutationen (volle Suite je Mutation) | **678 passed**; **62 von 63** erkannt (1 gleichwertig) |
| QA-Skripte nach Korrekturrunde 2 (Besichtiger, Erzwingen, Sperre, Dubletten-Cache, Nebenwege) | Selbsteintragung 403; Erzwingen übernimmt, Log nur bei Änderung; Sperre → 503 ohne halben Zustand |
| Browser, Windows | nicht geprüft |

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
| Q2-H1 (Nachfassen/gespeicherter Betrag ohne Betrag im Brief) | 2 Tests, Mutationen erkannt; **465 passed**, ruff grün |
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
