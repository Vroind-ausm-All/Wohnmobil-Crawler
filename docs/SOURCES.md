# Datenquellen: Bewertung, Zulässigkeit, Integrationsreihenfolge

Stand: 13.10.2026 · Erstellt vom Agenten `source-researcher` in Phase 0, übernommen vom Orchestrator.
Anleitung zum Programmieren eines Adapters: `docs/QUELLEN.md`.

> **Keine Rechtsberatung.** Alle Aussagen gelten „laut Nutzungsbedingungen (Stand laut Auszug)“. Für den
> gewerblichen Einsatz ist eine juristische Prüfung empfohlen.
>
> **Einschränkung der Recherche:** In der Recherche-Umgebung war kein direkter Seitenabruf möglich (DNS-Fehler für
> alle Domains, nicht Bot-Schutz). Zitate stammen aus Suchindex-Auszügen vom 13.10.2026; `robots.txt` konnte bei
> keiner Quelle gelesen werden. **Vor einer Freigabe muss jemand die Originale im Browser gegenlesen** und Wortlaut
> und Abrufdatum hier ergänzen (Backlog `P2-01`).

## Statuslegende

* **OK** – zulässiger Zugang ohne weitere Klärung (manuell oder Benachrichtigungen, die der Nutzer selbst bestellt).
* **PRÜFEN** – offizieller Zugang möglich, Bedingungen/Kosten beim Anbieter klären; Adapter höchstens als Stub mit
  `freigegeben = False`.
* **BLOCKED** – automatisierter Zugriff laut Bedingungen untersagt oder ohne Zugangsweg. Kein aktiver Adapter;
  zulässige Alternative nutzen.

## Bewertung

| Quelle / Kanal | Typ | Privatanteil | Zugang | Kosten | Datenqualität | Aktualität | Status |
|---|---|---|---|---|---|---|---|
| Kleinanzeigen – HTML-Abruf (heutiger Adapter) | Generalist | hoch (wahrscheinlich) | keiner, Abruf untersagt | – | mittel | sehr hoch | **BLOCKED** |
| Kleinanzeigen – E-Mail-Suchauftrag | Generalist | hoch | Suchauftrag des Nutzers | kostenlos | gering (Titel, Preis, Ort, Link) | Takt unbekannt | **OK** |
| Kleinanzeigen – manueller Import | Generalist | hoch | Nutzer fügt ein | kostenlos | wie eingefügt | Handarbeit | **OK** |
| mobile.de – Search-API / Ad-Stream | Händler-Mix | gering–mittel (wahrscheinlich) | API-Account über Kundenservice | unbekannt | hoch | Ad-Stream ereignisbasiert | **PRÜFEN** |
| mobile.de – gespeicherte Suche per E-Mail | Händler-Mix | gering–mittel | Suchauftrag | kostenlos | gering | **max. 1 E-Mail/Tag** (belegt) | **OK** (ergänzend) |
| AutoScout24 – Listing Creation API | Händler-Mix | gering | nur Einstellen, kein Lesen | unbekannt | – | – | **BLOCKED** als Lesequelle |
| AutoScout24 – Suchauftrag | Händler-Mix | gering | Push/E-Mail mit Konto | kostenlos | gering | unbekannt | **OK** |
| Caraworld (publimind GmbH) | Spezialmarkt | ca. 22 % privat (2015, veraltet) | kein Lesezugang bekannt | – | wahrscheinlich gut | unbekannt | **PRÜFEN** (Anfrage); manuell OK |
| Quoka | Generalist | unbekannt | kein Zugang bekannt | – | unbekannt | unbekannt | **BLOCKED** automatisch; manuell OK |
| markt.de u. a. regionale Portale | Generalist | unbekannt | unbekannt | – | unbekannt | unbekannt | **PRÜFEN**; manuell OK |
| eBay.de – Browse API | gemischt | unbekannt | Buy-API mit Zulassung und Vertrag | Vertrag | hoch | hoch | **PRÜFEN** (niedrige Priorität) |
| Facebook Marketplace | privat dominiert (wahrscheinlich) | – | keine Marketplace-API (wahrscheinlich) | – | – | – | **BLOCKED**; manuell OK |

## Belege je Quelle

### Kleinanzeigen

* **Nutzungsbedingungen § 5** (https://themen.kleinanzeigen.de/nutzungsbedingungen/, Index-Auszug, laut Index ca.
  969 Tage alt – **Wortlaut im Original prüfen**): untersagt sinngemäß den Zugriff mit „Crawlern, Spidern, Scrapern“
  oder ähnlichen automatisierten Mechanismen ohne ausdrückliche schriftliche Zustimmung sowie das Sammeln von
  Kontaktdaten anderer Nutzer ohne deren Einwilligung.
* **Hilfeseite „IP eingeschränkt“** (https://themen.kleinanzeigen.de/ip-eingeschraenkt/), wörtlich: „Nutzung von
  Kleinanzeigen durch Crawler, Spider, Scraper oder andere automatisierte Mechanismen ohne ausdrückliche Zustimmung
  durch Kleinanzeigen.“ – als Grund für IP-Sperren.
* **Suchauftrag** (https://themen.kleinanzeigen.de/hilfe/suche/suchbenachrichtigung/): „Suchauftrag speichern“,
  E-Mail zu neu eingestellten passenden Anzeigen, Verwaltung unter „Meins → Suchaufträge“. Versandtakt: unbekannt.
* Öffentliche Lese-API: nicht gefunden.
* **Folge:** Der bestehende HTML-Adapter bleibt **BLOCKED** (siehe ADR-005). Beim E-Mail-Import nur den Inhalt der
  E-Mail auswerten, **verlinkte Anzeigen nicht automatisch nachladen**.

### mobile.de

* **API-Übersicht** (https://services.mobile.de/), wörtlich: „There are two account types: an API-account, for which
  certain APIs such as the Search-API can be activated; please contact customer support for activation and
  credentials.“ Ad-Stream: „Websocket based API to receive server side events (created or changed ads)“ – nur mit
  API-Account.
* **Ergänzende Bedingungen Inseratseinbindung 2016** (https://mobile.de/service/pdfs/agb_inseratseinbindung_2016_de.pdf),
  wörtlich: „Der Händler ist berechtigt, die mobile.de-Inserate für einen Zeitraum von maximal 24 Stunden ab Abruf
  zwischenzuspeichern.“ – veraltet; falls noch gültig, **Konflikt mit Preishistorie und Marktdatenbasis**.
* **AGB Händlerbereich** (https://www.mobile.de/service/pdfs/mobile.de_AGB-HB_DE.pdf, gültig ab 01.04.2025): „Der
  Einsatz von Data Mining, Robots, Grabbing, Scraping und/oder …“ (Verbot, Auszug abgeschnitten).
* **Gespeicherte Suche** (https://www.mobile.de/magazin/artikel/suchen-und-kaufen-41618), wörtlich: „Du erhältst
  maximal eine E-Mail pro Tag – und auch nur dann, wenn neue, passende Fahrzeuge inseriert wurden.“
* Kosten und Zulassung eines Ankäufers ohne eigenes Inventar: **unbekannt – beim Kundenservice anfragen**.

### AutoScout24

* **Verbraucher-AGB Ziffer 8.2** (https://www.autoscout24.de/unternehmen/verbraucher-agb/), wörtlich: „Eine
  automatisierte Abfrage durch Scripte, durch Umgehung der Suchmaske durch Suchsoftware oder vergleichbare Maßnahmen
  sind nicht gestattet.“ Ziffer 8.3 untersagt die Nutzung „zum Aufbau einer eigenen Datenbank … und/oder für eine
  gewerbliche Datenverwertung“.
* **API** (https://www.autoscout24.de/haendlerportal/api/): Listing Creation API = Einstellen von Inseraten.
  Lesender Marktzugang: unbekannt; Kontakt laut FAQ: daten@autoscout24.de.
* **Suchauftrag** (https://www.autoscout24.de/promo-lp/suchauftrag/): Push oder E-Mail, kostenloses Konto.
* Bot-Schutz (Akamai): laut Drittanbietern, wahrscheinlich.

### Caraworld (publimind GmbH)

* **AGB** (https://www.caraworld.de/service/allgemeine-geschaeftsbedingungen): Privatinserat kostenfrei (1 Fahrzeug,
  6 Monate); Ziffer 15 sinngemäß: Weiterverarbeitung von Inseraten durch Dritte nur mit schriftlicher Erlaubnis.
* Lesezugang, Feed, Suchbenachrichtigung: unbekannt – bei publimind anfragen.

### Quoka

* **AGB** (https://hilfebereich.quoka.de/agb/), wörtlich: Ansicht und Download „ausschließlich für persönliche und
  nicht-kommerzielle Zwecke“. Relevanz für Wohnmobile: wahrscheinlich gering.

### eBay.de

* https://developer.ebay.com/api-docs/buy/static/buy-requirements.html: Produktivzugang zu den Buy APIs erfordert
  „meet standard eligibility requirements, get approvals … and sign contracts with eBay“.

### Facebook Marketplace

* Meta-Nutzungsbedingungen Ziff. 3.2.3: „You may not access or collect data from our Products using automated means
  (without our prior permission)“; Entwicklerdoku: Platform APIs sind „the only allowable means to access data
  programmatically“. Keine Marketplace-API bekannt.

## Empfohlene Integrationsreihenfolge (Phase 2)

1. **Manueller Import** (`zugriffsart = "manuell"`, `freigegeben = True`): Nutzer fügt URL **und** Anzeigentext ein
   oder lädt eine im Browser gespeicherte Seite hoch. **Der Server ruft die URL nicht selbst ab** (ADR-010).
   Funktioniert für jede Quelle.
2. **E-Mail-Suchbenachrichtigungen** aus einem Postfach des Betreibers (Suchaufträge legt der Nutzer selbst an):
   `.eml`-Upload, später optional IMAP mit Zugangsdaten aus Umgebungsvariablen. Parser je Absender: zuerst
   Kleinanzeigen (höchster Privatanteil), dann AutoScout24, dann mobile.de. Verlinkte Anzeigen werden nicht nachgeladen.
   → Kanäle 1 und 2 sind voneinander unabhängig, zulässig und ohne Vertrag testbar (Abnahmekriterium Phase 2).
3. **Vertragsbasierte Zugänge:** mobile.de API-Account (Search-API, Ad-Stream) zuerst; danach Anfragen bei AutoScout24,
   publimind, Quoka; eBay Browse API nur bei nachgewiesenem Volumen. Adapter erst nach schriftlicher Zusage, bis dahin
   Stub mit `freigegeben = False`.
4. **Kleinanzeigen-HTML-Adapter:** nicht standardmäßig aktiv (Entscheidung des Betreibers, ADR-005).

## Offene Fragen

**An den Betreiber**

* Kleinanzeigen-HTML-Adapter endgültig abschalten oder nur standardmäßig deaktivieren?
* Eigenes Postfach für Suchbenachrichtigungen? `.eml`-Upload oder IMAP gewünscht?
* Anonymisierte Beispiel-E-Mails der Suchaufträge (Kleinanzeigen, AutoScout24, mobile.de) als Testdaten.
* Ist der Betrieb bei mobile.de oder AutoScout24 als Händler registriert?
* Juristische Prüfung: E-Mail-Auswertung zu gewerblichen Zwecken, Speicherung von Verkäuferdaten (DSGVO),
  Speicherfristen bei API-Daten.
* AGB-Originale und `robots.txt` im Browser gegenlesen (Backlog `P2-01`).

**An Anbieter**

* **mobile.de** (Kundenservice): API-Account für gewerblichen Ankäufer ohne eigenes Inventar? Bedingungen für
  Search-API/Ad-Stream, Kosten, Rate-Limits, Speicherfristen (gilt die 24-Stunden-Regel?), Nutzung zur Preisbewertung,
  Filter für Privatanbieter und Wohnmobile?
* **AutoScout24** (daten@autoscout24.de): lesender Markt- oder Suchzugang für Dritte?
* **publimind/Caraworld:** Lesezugang oder Feed (ggf. nur Privatinserate)? E-Mail-Suchaufträge?
* **Kleinanzeigen, Quoka:** schriftliche Zustimmung oder Partnerzugang möglich? Format/Takt der Suchauftrags-E-Mails?
* **eBay:** Zulassungsfähigkeit des Anwendungsfalls für die Browse API?
