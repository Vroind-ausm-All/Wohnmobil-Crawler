# Architektur- und Migrationsplan: Wohnmobil-Scout → Multi-Plattform-Suche

Stand: Oktober 2026 · Gilt für den Zweig `claude/phase1-grundlage` (Basis: `claude/gifted-heisenberg-d1cjlr`)

Ziel: Aus dem Kleinanzeigen-Crawler wird eine dauerhaft wartbare Suche, die Wohnmobilangebote aus
mehreren **zulässigen** Quellen findet, zusammenführt, überwacht und für den gewerblichen Ankauf bewertet.
Die vorhandenen Funktionen (Bewertung, Anschreiben, Statusverwaltung, Browser-App, CSV) bleiben dabei
durchgehend nutzbar.

---

## 1. Bestandsaufnahme (Ist-Zustand vor Phase 1)

| Modul | Aufgabe | Beobachtung |
|---|---|---|
| `scout.py` | Kommandozeile (`app`, `lauf`, `report`, `rechne`, `status`) | schlank, gut |
| `wmscout/crawler.py` | HTTP-Abruf mit Pausen/Sperrerkennung, Kleinanzeigen-Seitenlogik, DB-Schreiben, Detail-Priorisierung, Layout-Diagnose | **vermischt 4 Verantwortlichkeiten**, nur eine Quelle denkbar |
| `wmscout/parser.py` | Kleinanzeigen-HTML → Datensätze | quellenspezifisch, aber nicht so benannt |
| `wmscout/db.py` | SQLite, Tabelle `anzeigen` | `id` = Kleinanzeigen-ID (**keine Quelle**), nur aktueller Preis + `preis_vorher`, `status` mischt **Verfügbarkeit** (`gelöscht`) und **Ankaufsablauf** (`kontaktiert` …), `gewerblich` nur 0/1 |
| `wmscout/fahrzeug.py`, `geo.py` | Marke/Modell/Serie/Art erkennen, PLZ-Entfernung | fachlich gut, gehört zur Normalisierung |
| `wmscout/rechner.py` | faire Marktwertschätzung, Händler-EK | gut gekapselt |
| `wmscout/anschreiben.py` | Anschreiben + Nachfass-Texte | gut gekapselt |
| `wmscout/report.py` | Auswertung (Duplikate, Nachfassen) **+** HTML/CSV **+** E-Mail | **vermischt Bewertung, Ausgabe und Benachrichtigung** |
| `wmscout/app.py` | lokale Browser-App, Suchlauf-Thread, Auto-Suche | gut, hängt direkt am Crawler |
| `tests/test_offline.py` | ein großes Testskript | kein Test-Runner, keine CI |
| `requirements.txt` | Versionsbereiche | **nicht reproduzierbar** (keine festen Versionen/Prüfsummen) |
| `installieren.bat`, `app.bat`, `lauf.bat` | `.venv` mit Python 3.13, Doppelklick-Start | funktioniert; unter Windows bisher nur manuell geprüft |

**Rechtlicher Befund:** Die einzige Quelle (Kleinanzeigen) wird per HTML-Abruf gelesen. Die
Nutzungsbedingungen von Kleinanzeigen untersagen automatisiertes Auslesen. Das README weist bereits darauf
hin. Nach den neuen Projektregeln („nur mit Berechtigung“) ist das ein **offener Entscheidungspunkt für
den Betreiber**. Phase 1 ändert das Verhalten nicht, kennzeichnet die Quelle aber technisch als
*nicht freigegeben* (siehe §6).

---

## 2. Zielarchitektur

```
                 ┌──────────────────────────── wmscout ─────────────────────────────┐
 Suchprofile ──▶ │ quellen/            Adapter je Plattform (Interface: Quelle)      │
 (config.yaml)   │   basis.py            Inserat, Suchauftrag, Fehlerklassen         │
                 │   kleinanzeigen/      Adapter + Parser                            │
 URL/Feed ─────▶ │   (Phase 3/4: manuell, feed_csv, mobile_de_api, …)                │
                 │ netz.py             höflicher HTTP-Abruf (Pausen, Sperrerkennung) │
                 │ importer.py         Suchlauf: Quellen → Normalisierung → DB        │
                 │ normalisierung/     Fahrzeug (Marke/Modell/Art), Geo (PLZ)         │
                 │ datenbank.py        SQLite + Migrationen                           │
                 │ bewertung/          Rechner, Anschreiben, Auswertung (Dubletten,   │
                 │                     Nachfassen)                                    │
                 │ ausgabe.py          HTML-Report, CSV, Anschreiben-Dateien          │
                 │ benachrichtigung.py E-Mail (später: weitere Kanäle)                │
                 │ app.py              Browser-App, Suchlauf-Thread, Auto-Suche       │
                 └────────────────────────────────────────────────────────────────────┘
```

Grundsätze:

1. **Abhängigkeiten zeigen nach innen.** Quellen kennen weder Datenbank noch Bewertung; sie liefern nur
   `Inserat`-Objekte. Der `Importer` ist die einzige Stelle, die Quellen und Datenbank verbindet.
2. **Eine Quelle = ein Adapter** mit Metadaten zu Zugriffsart und Freigabe (siehe `docs/QUELLEN.md`).
3. **Netzwerk ist austauschbar** (`Abruf`-Protokoll). Tests laufen komplett offline mit einem Fake-Abruf.
4. **Fehler einer Quelle bleiben bei dieser Quelle.** In Phase 1 wird nur die Struktur vorbereitet,
   die vollständige Isolation folgt in Phase 3.
5. **Keine Big-Bang-Neuentwicklung:** Module werden verschoben (Git-Historie bleibt erhalten) und nur dort
   geändert, wo die Trennung es verlangt. Fachlogik (Rechner, Texte, Oberfläche) bleibt unverändert.

---

## 3. Ziel-Datenmodell (Phase 2)

```
quellen            (kennung PK, name, zugriffsart, freigegeben, zuletzt_ok, fehler_in_folge)
inserate           (id PK, quelle → quellen, anzeigen_id, UNIQUE(quelle, anzeigen_id),
                    fahrzeug_id → fahrzeuge, url, titel, beschreibung, …,
                    anbieter_typ  privat | haendler | unbekannt,
                    verfuegbarkeit aktiv | reserviert | offline | verkauft,
                    zuletzt_bestaetigt, erstmals_gesehen, zuletzt_gesehen)
fahrzeuge          (id PK, marke, serie, modell, art, ez_jahr, fin NULL, fingerabdruck,
                    km_letzter, plz)                     -- Identität unabhängig vom Inserat
preis_historie     (inserat_id, zeitpunkt, preis, vb)    -- jede Preisänderung
beobachtungen      (inserat_id, suchlauf_id, zeitpunkt, gefunden_in_suche, detail_geladen)
ankauf             (fahrzeug_id PK, status, status_am, kontaktiert_am, angebot_betrag,
                    nachgefasst_am, nachfass_anzahl, anschreiben_text, notiz)
suchlaeufe         (id, start, ende, art schnell|voll, quelle, seiten, treffer, neu, fehler, parser_ok)
schema_version     (version, angewendet_am)
```

* **Fahrzeugidentität:** Ein Fahrzeug kann mehrere Inserate haben (Neueinstellung, mehrere Plattformen).
  Zuordnung über einen Fingerabdruck (Marke, Serie, EZ, PLZ-Region, km-Band; FIN, wenn vorhanden) mit
  Konfidenz. Unsichere Treffer werden nur *vorgeschlagen*, nicht automatisch zusammengeführt.
  Die heutige Funktion `finde_duplikate()` ist die erste Stufe davon.
* **Ankaufsstatus hängt am Fahrzeug, nicht am Inserat.** Dadurch wird ein neu eingestelltes Fahrzeug nicht
  erneut angeschrieben.
* **Verfügbarkeit ist ein eigener Status** mit `zuletzt_bestaetigt`. Heute steckt sie als `gelöscht` im
  Ankaufsstatus.

---

## 4. Migrationsstrategie für bestehende SQLite-Daten

1. Tabelle `schema_version`. Die heutigen Datenbanken gelten als Version 1 (ZIP-Stand) bzw. 2 (mit
   `bild`, `kontaktiert_am`, … – wird bereits per `ALTER TABLE` ergänzt).
2. Migrationen sind nummerierte Python-Funktionen (`migration_003_quellen()` …). Jede läuft in einer
   Transaktion, ist idempotent und wird in `schema_version` vermerkt.
3. **Vor jeder Migration** wird eine Kopie `anzeigen.sqlite.vor-v<N>-<datum>.bak` angelegt.
4. Abbildung alt → neu (Phase 2):
   * `anzeigen.id` → `inserate(quelle='kleinanzeigen', anzeigen_id=id)`
   * `preis_vorher` + `preis` → zwei Einträge in `preis_historie`
   * `status='gelöscht'` → `verfuegbarkeit='offline'`; Ankaufsstatus → Tabelle `ankauf`
   * `gewerblich` → `anbieter_typ` (`1` → `haendler`, `0` → `privat` nur bei geprüften Detailseiten, sonst `unbekannt`)
5. Eine **Kompatibilitäts-View** `anzeigen` hält Bewertung und Oberfläche während des Umbaus lauffähig.
6. Tests mit Beispiel-Datenbanken jeder Vorversion stellen sicher, dass nichts verloren geht.

---

## 5. Phasenplan

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **1 Grundlage** | Python 3.13 + `.venv`, gesperrte Abhängigkeiten, pytest + GitHub Actions (Linux/Windows), Aufteilung in Komponenten, Quellen-Interface | alle bestehenden Funktionen laufen, Tests grün in CI, Windows-Start in CI geprüft |
| **2 Datenqualität** | Datenmodell §3, Migration §4, Preis-/Beobachtungshistorie, Verfügbarkeit, Händler/Privat, Fahrzeugidentität + Dublettenvorschläge | Migration alter DBs verlustfrei getestet; Oberfläche zeigt Preisverlauf |
| **3 Suchsystem** | Suchprofile (Art, Marke, Region, Preis, EZ, km) je Quelle, Scheduler (schnell/voll), Fehlerisolation je Quelle, Detail-Priorisierung, Quellenstatus/Abdeckung, Import einzelner URLs und Feeds (CSV/JSON/XML) | eine fehlerhafte Quelle bricht keinen Lauf ab; Statusseite zeigt Fehlerquoten |
| **4 Erweiterbarkeit** | dokumentierte Adapter für API-/Feed-Quellen; Stubs für mobile.de, AutoScout24, Caraworld, Händler-Feeds | neue Quelle = 1 Datei + Konfiguration, Vertragstests laufen automatisch |

---

## 6. Quellen und rechtlicher Rahmen

| Quelle | geplanter Zugang | Status |
|---|---|---|
| Kleinanzeigen | HTML-Abruf (bestehend) | **nicht freigegeben** – Nutzungsbedingungen untersagen automatisiertes Auslesen. Betreiber entscheidet: weiter auf eigene Verantwortung, abschalten oder durch manuellen URL-Import ersetzen |
| mobile.de | offizielle Schnittstellen für gewerbliche Kunden | Zugang/Konditionen beim Anbieter klären; bis dahin nur Interface + manueller Import |
| AutoScout24 | Partner-/Händlerschnittstellen | wie mobile.de |
| Caraworld u. a. Spezialmärkte | unbekannt | Anfrage beim Betreiber; bis dahin manueller Import |
| Regionale Händler | freigegebene CSV/XML-Feeds nach Absprache | Feed-Adapter (Phase 3) |

Regeln für alle Adapter: offizielle APIs und freigegebene Feeds bevorzugen; **keine** Umgehung von Captchas,
Sperren oder Schutzmechanismen. Bei Sperre bricht der Adapter ab (wie heute bei HTTP 403/429/Captcha).
Jeder Adapter deklariert `zugriffsart` und `freigegeben`. Nicht freigegebene Quellen erzeugen beim Lauf
einen Hinweis im Protokoll.

---

## 7. Teststrategie

* `pytest`, komplett offline: nachgebautes Kleinanzeigen-HTML, Fake-Abruf, temporäre Datenbanken.
* Vertragstest für jede registrierte Quelle (Metadaten, Interface, `Inserat`-Felder).
* End-to-End: Suchlauf → Bewertung → HTML/CSV/Anschreiben → App-Server (HTTP).
* Migrationstest mit einer Datenbank im Ur-Schema (ZIP-Stand).
* GitHub Actions: Ubuntu + Windows mit Python 3.13; zusätzlich ein Windows-Job, der `installieren.bat`
  wirklich ausführt.

---

## 8. Umsetzungsstand

Siehe Abschnitt „Umsetzungsstand“ in `README.md` (wird mit jeder Phase aktualisiert).
