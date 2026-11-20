# Phase 8 – vom Pilot zum SaaS (Planung 8a–8c)

Stand 19.11.2026, Auftrag des Betreibers: „Arbeite Phase 8 aus bis 8c“. Dieses Dokument **plant** – es setzt nichts um. Jedes
Unterpaket startet erst nach Freigabe (CLAUDE.md, Regel 14). Kostenpflichtige Dienste (Mailversand, Zahlungsanbieter, Server) und
Rechtstexte entscheidet der Betreiber (Regel 13). Entscheidungen: ADR-070. Arbeitspakete und Status: `docs/ROADMAP.md`, Phase 8.

## Ausgangslage (geprüft am Code, `main` = 226dbdc)

| vorhanden | wo | für SaaS fehlt |
|---|---|---|
| Mandanten mit eigener Datenbank, eigenem Audit, eigenen Zugängen | `wmscout/mandanten.py`, `docs/MANDANTEN.md` (G2) | Anlegen nur per Kommandozeile; Zuordnung Hostname → Mandant wird beim **Start** gebaut (neuer Kunde erst nach Neustart erreichbar) |
| Einladungslink, Passwort selbst setzen | `team.py` (F4) | „Passwort vergessen“; Versand per Mail (heute gibt der Inhaber den Link weiter) |
| Nutzungszähler je Monat und Nutzer | `wmscout/nutzung.py` (G1) | Tarif-Kontingente, Abrechnung |
| E-Mail-Suchagenten einlesen, EML/CSV/HTML-Upload | `wmscout/eingang/email`, CampRCrawlR Paket 4 | eigene **Eingangsadresse je Kunde**, automatische Abholung (F3 offen) |
| API-Rahmen, Händlerzugänge je Firma, Verbindungstest | `quellen/api_rahmen.py`, `zugaenge.py` (G0, F4) | Test mit echtem Zugang; Freigabe nach Nutzungsbedingungen |
| Mailversand (SMTP) für Treffer-Benachrichtigung | `benachrichtigung.py` | allgemeiner Versand für Konto-Mails (Bestätigung, Passwort, Rechnung) |
| Einstellungen | `config.yaml` / `mandant.yaml` | Oberfläche für den Kunden |
| Löschfristen, Widerruf | `datenrechte.py` (F10) | Datenexport bei Kündigung, Auskunft nach Art. 15 |
| Serverbetrieb | `docs/SERVERBETRIEB.md` (P7-04) | Plattform-Domain mit Subdomains je Kunde |

## Zielbild

```
https://scout.example.de            Startseite, Registrierung, Anmeldung, Passwort vergessen   ← Plattform-Prozess (neu)
https://<kunde>.scout.example.de    App des Kunden (wie heute, Mandant per Hostname)          ← App im Mandantenbetrieb
https://verkaufen.<kunde>…          Ankaufsportal je Kunde (optional, P7-03)
https://scout.example.de/betrieb    Betreiber-Verwaltung – nur über Tailscale/127.0.0.1

daten/plattform.sqlite              NEU: Kundenverzeichnis, Registrierungen, Tarif/Status, Zustimmungen, Zahlungsereignisse
mandanten/<kennung>/daten/…         wie heute: Fachdaten je Kunde, getrennt
```

Grundsatz bleibt: **Fachdaten je Kunde in eigener Datei** (ADR-033). Neu ist nur eine kleine Plattform-Datenbank für das, was über
Kunden hinweg verwaltet werden muss. Sie enthält **keine** Fachdaten (keine Inserate, keine Verkäuferdaten).

---

## 8a – Datenzugang je Kunde

Ohne erlaubten Datenzugang hat ein neuer Kunde eine leere Liste – deshalb zuerst. Keine eigene Abfrage von Börsen (Regeln 11/12):
der Kunde bringt seine Daten über **seine** Suchagenten und **seine** Händlerzugänge mit.

| ID | Paket | Abnahmekriterien |
|---|---|---|
| P8a-01 | **Mail-Eingang je Mandant:** Abholung per IMAP aus EINEM Plattform-Postfach mit Plus-Adressen (`eingang+<kennung>.<zufall>@…`); Zuordnung nur über das geheime Adress-Suffix je Mandant; nur bekannte Absender (Kleinanzeigen, mobile.de, AutoScout24) werden verarbeitet, Rest in Quarantäne ohne Inhalt im Log; Abholung per Timer; Zugangsdaten nur als Umgebungsvariable | Test (Fake-IMAP): Mail an Adresse A landet nur bei A; erratene/fremde Kennung ohne Suffix → Quarantäne; unbekannter Absender → nicht eingelesen; doppelt abgeholte Mail → kein doppeltes Inserat; Postfach-Fehler stoppt keinen anderen Mandanten; Mails nach Verarbeitung gelöscht bzw. nach Frist (F10) |
| P8a-02 | **Einrichtungsseite „Eingang“ in der App:** persönliche Eingangsadresse anzeigen, Anleitung je Börse (Suchagent anlegen, Weiterleitung), Status „letzte Mail am …“, Warnung „seit n Tagen keine Mail“, Adresse neu erzeugen (alte wird ungültig) | Test: Adresse je Mandant eindeutig und nicht erratbar; Neu-Erzeugen macht alte unwirksam; Warnung nach Schwelle; Seite nur für Inhaber/Mitarbeiter |
| P8a-03 | **mobile.de-Search-API im Pilot** mit dem echten Händlerzugang eines Pilotkunden: Adapter auf `api_rahmen`, Zugang je Mandant (`WMSCOUT_<KENNUNG>_…`), Speicherdauer nach den Nutzungsbedingungen | **BLOCKED** bis schriftliche Freigabe/Bedingungen vorliegen (Regel 12). Dann: Vertragstest gegen aufgezeichnete Antworten, Kontingent, Abbruch bei 401/403/429, Löschung nach Bedingungen |
| P8a-04 | **Quellenstatus je Kunde:** Eingang der letzten 7/30 Tage je Weg (Mail, Upload, API), Hinweis bei Lücken; Grundlage für Support | Test: Zahlen je Mandant getrennt; kein Zugriff auf andere Mandanten |

**Abhängigkeit:** F3 (Mail-Technik) und F16 (Plattform-Domain/Postfach). P8a-03 hängt am Pilotkunden und den Bedingungen von mobile.de.

---

## 8b – Self-Service

| ID | Paket | Abnahmekriterien |
|---|---|---|
| P8b-01 | **Konto-Mails:** Versandmodul mit Vorlagen (Bestätigung, Passwort, Einladung, später Rechnung/Mahnung), Absender der Plattform, Versanddienst per SMTP-Zugang aus Umgebungsvariable; Anleitung SPF/DKIM/DMARC | Test mit Fake-SMTP: richtige Vorlage, keine Geheimnisse im Log, Fehler blockiert die Anfrage nicht (Warteschlange mit Wiederholung) |
| P8b-02 | **Plattform-Datenbank + dynamische Mandanten:** `plattform.sqlite` (Kunden, Status, Hostnamen, Tarif, Zustimmungen); Mandanten werden zur Laufzeit erkannt (kein Neustart); Übernahme der bestehenden `mandanten/`-Ordner per Migration mit Sicherung | Test: neuer Mandant sofort erreichbar; bestehende Mandanten unverändert; Migration idempotent, mit Altbestand; unbekannter Host weiter 403 |
| P8b-03 | **Registrierung:** Firma, Name, E-Mail, Passwort, Zustimmung zu AGB/AV-Vertrag (Version gespeichert); E-Mail-Bestätigung; danach Mandant anlegen (Kennung → Subdomain); Spamschutz wie Portal (P7-03); **Freigabe-Modus** (Betreiber schaltet neue Kunden frei) standardmäßig an | Test: ohne Bestätigung kein Mandant; doppelte E-Mail/Kennung abgelehnt ohne Konten zu verraten; reservierte Kennungen (`www`, `betrieb`, `verkaufen`, …) gesperrt; Grenzen je IP; Zustimmungsversion gespeichert |
| P8b-04 | **Passwort vergessen:** Link per Mail, Token nur als Hash, 1 h, einmalig; gleiche Antwort ob Konto existiert oder nicht; alle Sitzungen danach ungültig | Test: Ablauf, Einmaligkeit, keine Kontoaufzählung, Bremse, Audit-Eintrag |
| P8b-05 | **Einstellungen in der Oberfläche (Inhaber):** Firmendaten, Standort-PLZ, Anschreiben-Vorlage, Bewertungsparameter in festen Grenzen, Benachrichtigungen; gespeichert in der Mandanten-DB (Tabelle `einstellungen`, Schema v25), überlagert `config.yaml`; dieselben Prüfungen wie beim Start | Test: ungültige Werte abgelehnt mit Meldung; Wirkung sofort ohne Neustart; Audit jeder Änderung; Mitarbeiter/Standort 403; Migration v25 mit Sicherung |
| P8b-06 | **Einrichtungsassistent** beim ersten Login: Firmendaten → Standort → Eingang (P8a-02) → Team einladen | Klicktest Desktop/Handy; Assistent überspringbar, später fortsetzbar |
| P8b-07 | **Betreiber-Verwaltung `/betrieb`:** Kundenliste mit Status, Tarif, Nutzung (Monat), letzter Anmeldung, Speicherbedarf; Freischalten, Sperren (nur lesen), Entsperren; **kein** Einblick in Fachdaten der Kunden; nur über 127.0.0.1/Tailscale, eigener Zugang | Test: keine Inserate/Verkäuferdaten in Antworten; Sperre wirkt sofort (Schreiben 403, Lesen bleibt); jede Aktion im Plattform-Audit |
| P8b-08 | **Kündigung und Datenexport:** Export je Mandant (ZIP: Daten als CSV/JSON, Fotos, Dokumente); Kündigung → nur-lesen → Löschung nach Frist mit Nachweis; Auskunft nach Art. 15 je Verkäufer | Test: Export vollständig und nur eigene Daten; Löschung entfernt Ordner, Sicherungen nach Rotation (dokumentiert); Kaufunterlagen-Aufbewahrung beachtet (F10) |

**Abhängigkeit:** P8b-01 vor P8b-03/04; P8b-02 vor P8b-03/07. Domain mit Wildcard-Zertifikat (F16).

---

## 8c – Bezahlung und Recht

| ID | Paket | Abnahmekriterien |
|---|---|---|
| P8c-01 | **Tarife und Kontingente** in der Plattform-Konfiguration (z. B. Nutzer, Standorte, Verkaufsanfragen/Monat, Speicher); Anzeige „Verbrauch“ für den Inhaber; Überschreitung zuerst nur Hinweis, harte Grenze schaltbar | Test: Zählung aus `nutzung.py`; Hinweis bei 80 %/100 %; harte Grenze blockiert nur Neuanlagen, nie Lesen/Export |
| P8c-02 | **Status-Lebenszyklus:** Test (z. B. 30 Tage) → aktiv → überfällig (Hinweis) → gesperrt (nur lesen) → gekündigt → gelöscht; Fristen konfigurierbar; jede Änderung im Plattform-Audit | Test: Übergänge nur in erlaubter Richtung; Daten bleiben bis zur Löschfrist; Export immer möglich |
| P8c-03 | **Zahlungsanbieter-Anbindung:** gehostete Bezahlseite und Kundenportal des Anbieters (keine Kartendaten bei uns), Webhooks mit Signaturprüfung, idempotent, Status aus Webhook → P8c-02 | **BLOCKED** bis Anbieter/Konto gewählt (F18, Regel 13). Dann: Test mit aufgezeichneten Webhooks (gültig, gefälscht, doppelt, außer Reihenfolge); kein Geheimnis im Repository |
| P8c-04 | **Rechnungen:** über den Zahlungsanbieter (Pflichtangaben, USt, Rechnungsnummern) statt eigener Buchhaltung; Rechnung im Konto abrufbar; Aufbewahrung 10 Jahre beim Anbieter | Steuerliche Prüfung durch den Betreiber; Test: Link zur Rechnung nur für den Inhaber |
| P8c-05 | **Rechtstexte der Plattform (Vorlagen):** AGB, AV-Vertrag nach Art. 28 DSGVO mit TOM (aus DATENRECHTE/PILOTBETRIEB/SERVERBETRIEB), Liste der Unterauftragsverarbeiter, Datenschutzerklärung der Plattform; versioniert, Zustimmung je Version | **Rechtliche Prüfung durch den Betreiber** (Anwalt); Test: neue Version → erneute Zustimmung beim nächsten Login, alte Zustimmungen bleiben nachweisbar |
| P8c-06 | **Hinweise in der App:** Bewertungen und Max-EK sind Schätzungen; §25a-Rechnung ist keine Steuerberatung; Quellen-Nutzung liegt in der Verantwortung des Kunden (eigene Suchagenten/Zugänge) | Texte an Bewertung, Kalkulation und Eingangsseite; Test: Hinweise sichtbar |

---

## Nicht in 8a–8c (später, 8d)

Zwei-Faktor-Anmeldung, CSP ohne `unsafe-inline`, CSRF-Token je Sitzung, externer Penetrationstest, Überwachung mit Alarm,
Staging-Umgebung, gesteuerte Updates aller Mandanten, P7-04b. **Vor dem ersten zahlenden Fremdkunden** sollten 2FA für Inhaber und der
Penetrationstest erledigt sein.

## Reihenfolge und Aufwand (grobe Schätzung, ohne Wartezeiten auf Entscheidungen)

1. **Pilot ohne neuen Code** (1–2 Kunden, Mandanten per Hand, `SERVERBETRIEB.md`) – parallel möglich, liefert echte Anforderungen.
2. **8a:** P8a-01, P8a-02, P8a-04 (ca. 3 Arbeitspakete); P8a-03 sobald freigegeben.
3. **8b:** P8b-01 → P8b-02 → P8b-03/04 → P8b-05/06 → P8b-07/08 (8 Pakete, größter Block).
4. **8c:** P8c-01/02 ohne Anbieter umsetzbar; P8c-03/04 nach Anbieterwahl; P8c-05 parallel beim Anwalt; P8c-06 klein.

Jedes Paket wie bisher: eigener Branch, Tests, eine QA-Runde, PR gegen den Integrationszweig.

## Entscheidungen des Betreibers (vor dem jeweiligen Paket)

| Nr. | Frage | betrifft | Empfehlung |
|---|---|---|---|
| F15 | Geschäftsmodell: SaaS, Installation beim Kunden (`KUNDENINSTALLATION.md`) oder beides? | ganz 8b/8c | beides; 8b/8c nur für SaaS, Installation bleibt ohne Konto/Bezahlung |
| F16 | Plattform-Domain, Subdomain je Kunde, Wildcard-Zertifikat (DNS-Anbieter mit API für Caddy) | P8a-01, P8b-02/03 | eigene Domain nur für die Plattform |
| F3 | Mail-Eingang: IMAP-Postfach mit Plus-Adressen oder Eingangs-Webhook eines Mail-Dienstes? | P8a-01 | IMAP mit Plus-Adressen (kein Zusatzdienst, bestehender Mail-Parser) |
| F17 | Dienst für Konto-Mails (Versand, SPF/DKIM) | P8b-01 | EU-Anbieter mit SMTP-Zugang |
| F18 | Zahlungsanbieter und Konto | P8c-03/04 | Anbieter mit gehosteter Bezahlseite, Kundenportal und Rechnungsstellung |
| F19 | Tarife: Preise, Grenzen, Testdauer | P8c-01/02 | erst nach dem Pilot festlegen |
| F20 | Neue Kunden automatisch oder erst nach Freischaltung? | P8b-03 | Freischaltung durch den Betreiber in der Anfangszeit |
| F21 | Rechtstexte (AGB, AV-Vertrag, Datenschutz) vom Anwalt | P8c-05 | vor dem ersten zahlenden Kunden |
