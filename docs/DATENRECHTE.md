# Datenrechte – Verzeichnis der Daten, Zwecke und Löschwege (Phase G0, ADR-030)

**Entwurf, keine Rechtsberatung.** Grundlage für das Verzeichnis der Verarbeitungstätigkeiten (Art. 30 DSGVO) und für die
Prüfung vor einem Pilotbetrieb. Rechtsgrundlagen und Fristen muss der Betreiber mit Datenschutzbeauftragtem bzw.
Steuerberatung festlegen – hier steht, **was das Programm tatsächlich speichert** und **wie es sich löschen lässt**.
Quellen und Nutzungsrechte der Marktdaten: `docs/SOURCES.md` (Status OK / PRÜFEN / BLOCKED).

## Aufbewahrungsfristen (F10, ADR-058)

Festgelegt am 27.10.2026 in `config.yaml` → `datenschutz` (0 = aus; ein fehlender Eintrag gilt als 0). **Fachliche Annahmen, keine
Rechtsberatung** – vor dem Pilotbetrieb mit Datenschutzbeauftragtem bzw. Steuerberatung bestätigen; Fristen ohne Codeänderung anpassbar.

| Daten | Frist | Danach | Begründung (Annahme) |
|---|---|---|---|
| Inserate fremder Börsen ohne Kauf: Anbietername, Anschreiben, Notiz, Kontakttexte, Besichtigung; abgelegte Mails, gespeicherte Seiten (`import/eingelesen/`, `import/nicht_erkannt/`), Diagnose-Rohseiten | 6 Monate nach letzter Aktivität | anonymisieren bzw. Dateien löschen | Zweck (Ankaufsgelegenheit) erledigt; Marktdaten ohne Personenbezug bleiben |
| Verkaufsanfragen ohne Ankauf (auch ohne stornierten) und ohne offene Besichtigung | 12 Monate nach letzter Änderung | wie Widerruf: Verkäufer, Freitexte, Notiz, Fotos, Besichtigung; Status bleibt, Verlauf „frist“ | Rückfragen und erneute Angebote im Folgejahr; danach kein Zweck |
| Abgelaufene Anmeldungen (`sitzungen`) | 30 Tage nach Ablauf | löschen | technisch nicht mehr nötig |
| Audit-Protokoll | 24 Monate | löschen (Lösch-Trigger nur dafür, in derselben Transaktion) | Nachweis (Art. 5 Abs. 2) für einen überschaubaren Zeitraum; enthält IP und Nutzernamen |
| Kaufunterlagen (Ankauf, Vertrag, Protokoll, Unterschriften, Dokumente) | 10 Jahre ab Ende des Kalenderjahres des letzten Vorgangs | **nur melden** – Löschung von Hand nach Prüfung | handels- und steuerrechtliche Aufbewahrung (§ 257 HGB, § 147 AO; Buchungsbelege seit 2025 teils 8 Jahre) – im Zweifel länger |
| Gesperrte Zugänge (`nutzer.aktiv = 0`) | – | melden | Verweise in Besichtigungen/Ankäufen – Einzelfall |
| Sicherungen | Rotation `sicherung → behalten` | älteste zuerst | Gelöschtes bleibt bis zur Rotation in älteren Sicherungen |

**Ausführung:** ausgeliefert ist `datenschutz → automatisch: nur_bericht` – beim Start und nach Suchlauf/Import wird nur gemeldet
(Statusseite, Protokoll). Nach Prüfung des ersten Berichts `automatisch: ja` setzen, dann gelten die Fristen dort automatisch. Vor einem Lauf,
der etwas ändert, wird die Datenbank gesichert – höchstens einmal je Tag, eigene Rotation (die letzten 3, Zusatz `vor-aufbewahrung`);
manuelle Sicherungen und Sicherungen vor Migrationen werden dadurch nie verdrängt. Jeder Lauf mit Änderungen hinterlässt einen
Nachweis im Audit-Protokoll (nur Anzahlen).
Bericht/Ausführen von Hand: `python scout.py datenschutz` bzw. `… --ausfuehren --bestaetigt` (`--json` für Überwachung); in der App für den
Inhaber `GET /api/datenschutz` und `POST /api/datenschutz/ausfuehren` (`{"bestaetigt": true}`, im Audit protokolliert).
**Server (später):** je Mandant täglich `python scout.py datenschutz --ausfuehren --bestaetigt --alle-mandanten --json` per Aufgabenplanung
(kein Dauerprozess im Programm); ein fehlerhafter Mandant hält die anderen nicht auf, Exit-Code 1 meldet ihn.

## Personenbezogene Daten

| Daten | Wo (Tabelle / Ordner) | Zweck | Wer sieht es | Löschweg im Programm | Offen (Betreiber) |
|---|---|---|---|---|---|
| Verkäufer einer Verkaufsanfrage: Name, E-Mail, Telefon, PLZ, Ort, Einwilligung (Zeitpunkt, Textversion) | `verkaeufer` | Bewertung und Kontakt wegen Ankauf (Einwilligung im Formular) | Team; Standorte nur Region „12xxx“, nie Name/Kontakt | **Widerruf** (`/anfragen` Knopf des Inhabers oder `scout.py anfrage widerruf REF --bestaetigt`): anonymisiert, sofern keine weitere Anfrage desselben Verkäufers besteht; ohne Widerruf nach 12 Monaten ohne Änderung (F10) | – |
| Freitext und Notiz der Anfrage, Notiz-Verlauf | `verkaufsanfragen.beschreibung/notiz`, `anfrage_verlauf` | Zustand beschreiben, interne Absprache | Team (Standorte: Freitext ohne Telefon/E-Mail/Links) | Widerruf löscht beides | – |
| Fotos der Anfrage | Ordner `fotos/anfragen/<id>/`, `anfrage_fotos` | Zustand beurteilen | Team, freigegebene Standorte | Widerruf löscht Dateien und Einträge | – |
| Metadaten in Fotos (EXIF/GPS, XMP, IPTC) | – | – | – | werden seit G0 beim Speichern entfernt (JPEG, PNG; Anfrage- und Besichtigungsfotos) | andere Formate (WebP/HEIC) nicht bereinigt |
| Offline-Speicher der Handy-App | Browser-Cache des Handys | Arbeiten ohne Netz | Nutzer des Geräts | nur eine Positivliste (Heute, Fahrzeuge, offene Besichtigungen, Fotos, eigene Anmeldung); **abgeschlossene Besichtigungen nie**, Unterschriften und Verkäuferangaben nie (P1-14b); wird geleert, sobald der Server 401 meldet (abgemeldet, Sitzung abgelaufen oder gesperrt) | verlorene Handys: Sitzung sperren (`scout.py nutzer sperren`) |
| Besichtigung einer Anfrage oder eines Inserats: Adresse, FIN, Kennzeichen, Notizen, Fotos, Verkäuferangaben, Unterschriften | `besichtigungen` (`basis/daten/protokoll_json`), `fotos`, Ordner `fotos/<besichtigung>/` | Zustandsbericht, Kaufprotokoll | Team | Widerruf (Anfrage) bzw. Anonymisieren (Inserat, P1-14a) schwärzt die Besichtigung und löscht ihre Fotos – **nur ohne Ankauf** | – |
| Ankauf: Kaufprotokoll mit Unterschriften, Vertragsscan, Übergabe, Preise | `ankaeufe`, `ankauf_dokumente`, Ordner `fotos/ankaeufe/` | Kaufvertrag, Buchhaltung, Ergebnisvergleich | Team | **kein automatisches Löschen** – Aufbewahrungspflichten (z. B. HGB/AO); Widerruf wird bei jedem Vorgang verweigert, auch storniert; Vertragsfotos ohne EXIF/GPS; nach 10 Jahren ab Jahresende gemeldet (F10) | Löschweg nach Fristablauf (von Hand) |
| Inserate fremder Börsen (öffentliche Angebote), bei gespeicherten Kleinanzeigen-Seiten der Anbietername | `anzeigen`, `inserate`, `beobachtungen` (`details.verkaeufer_name`) | Marktbeobachtung, Ankaufsgelegenheit | Team | `scout.py inserat anonymisieren` (einzeln/älter als N Monate), automatisch per `datenschutz → inserate_anonymisieren_nach_monaten` nach jedem Suchlauf, Seitenimport und beim Start der App (P1-14a): Profilname, Name im Anschreiben, Team-Notiz, Besichtigung wie beim Widerruf; gekaufte und solche mit offener Besichtigung nie; Diagnose-Rohseiten (`ausgabe/diagnose_*.html`) und alle vom Scout abgelegten Benachrichtigungs-Mails (`import/email/eingelesen/*/*.eml`, `nicht_erkannt/`, `fehlerhaft/`, P2-06) mit derselben Frist; noch nicht eingelesene Mails direkt in `import/email/` werden nie gelöscht, aber nach Fristablauf gemeldet; abgelegte gespeicherte Seiten (`import/eingelesen/`, `import/nicht_erkannt/`, samt Begleitordner) ebenso gelöscht (F10) | 6 Monate (F10) |
| Per Adresse + Text eingelesene Anzeige (P2-05): Fahrzeugdaten und gekürzte Beschreibung (höchstens 2000 Zeichen) | `anzeigen`, `inserate`, `beobachtungen` (Kanal `manuell`) | Marktbeobachtung, Ankaufsgelegenheit | Team (Mitarbeiter und Inhaber) | wie Inserate oben. **Der eingefügte Text wird nicht gespeichert, nur sein bereinigter Fahrzeugteil:** Telefonnummern, E-Mail-Adressen, Links, Straßenangaben und erkennbare Namenszeilen (Label „Name:“, Grußformel + Unterschrift, Name über „Privater Nutzer“) werden vorher entfernt; die Adresse wird nie abgerufen und nur als kanonische Detail-Adresse (ohne Such-/Tracking-Parameter) gespeichert | Erkannt werden Namen nach „Herr/Frau/Familie (Dr.) …“, „Ich heiße …“, „Verkäufer/Ansprechpartner/Besitzer/Kontakt: …“, Label-Zeilen und Grußformel + Unterschrift. **Nicht erkannt:** Namen im Fließtext ohne diese Anker („ruf mal Peter an“), Straßen ohne Hausnummer oder ohne Straßenwort, Telefonnummern in Wortform oder über Zeilen verteilt, Firmen-/Händlernamen (Zeilen „Firma:“/„Händler:“ bleiben, sie sind Geschäftsdaten) – Restrisiko; Abkürzungs-Grüße (LG/VG/MfG) werden nur als letzte Zeile bzw. am Ende der letzten Zeile entfernt |
| Anschreiben-Texte, Kontaktstatus | `anzeigen.anschreiben_text`, `bearbeitung` | Nachweis bestätigter Kontaktaufnahme | Team | Anonymisieren ersetzt den Namen im Text durch „[Name entfernt]“, Kontaktzeitpunkt bleibt | – |
| Team- und Händler-Zugänge: Name, Telefon, Rolle, Standort, Passwort-Hash, Sitzungen | `nutzer`, `sitzungen` | Anmeldung, Zuständigkeit | Inhaber | `scout.py nutzer sperren`; abgelaufene Sitzungen nach 30 Tagen gelöscht, gesperrte Zugänge gemeldet (F10) | Löschung ausgeschiedener Nutzer |
| Einladungen (F4): Hash des Einmal-Codes, Ablauf, Einlösezeitpunkt, wer eingeladen hat | `einladungen` | einfacher erster Login | Inhaber | Code gilt 7 Tage und einmal; eine neue Einladung löscht offene alte; eingelöste und abgelaufene werden nach 30 Tagen beim nächsten Einladen gelöscht | – |
| Händlerzugänge der Firma (F4): Händlernummer, API-Benutzer, Name der Umgebungsvariable, letztes Testergebnis (ohne Inhalte) – **kein Passwort** | `plattform_zugaenge` | Verbindung zu mobile.de/AutoScout24 vorbereiten | Inhaber | Felder leeren und speichern | – |
| Gebote, Auktionsprotokoll, Kalkulationen | `gebote`, `auktion_protokoll`, `kalkulationen` | Nachvollziehbarkeit (Phase D/E) | Team; Standorte nur eigene Gebote | nur anfügbar – enthalten **keine Kontaktdaten**: Kalkulationen speichern seit G0 Freitexte ohne Telefon/E-Mail/Links | Freitext kann Namen enthalten – Restrisiko |
| Audit-Protokoll (seit v10): Zeitpunkt, Nutzer, Rolle, IP, Methode, Pfad, Status, Objekt – **keine** Inhalte, Passwörter oder Kontaktdaten | `audit` (nur anfügbar) | Nachweis, wer Personendaten gelesen oder geändert hat (Rechenschaft, Art. 5 Abs. 2) | Inhaber (`scout.py audit`, `/api/audit`) | nur anfügbar; nach 24 Monaten gelöscht (F10, Wartungsschritt mit Nachweis-Eintrag ohne Inhalte) | – |
| Protokolldatei | `ausgabe/scout.log` | Fehlersuche, Nachvollziehbarkeit von Aktionen | Betreiber | rotiert automatisch (höchstens 6 × 5 MB, G0); WhatsApp-Nummern maskiert | Aufbewahrung festlegen; Log nennt Nutzernamen und Referenzen, keine Kontaktdaten der Verkäufer |
| Sicherungen | `daten/sicherungen/` (`config.yaml` → `sicherung.behalten`) | Wiederherstellung | Betreiber | rotieren automatisch (älteste zuerst) | **Gelöschte Daten bleiben bis zur Rotation in älteren Sicherungen** – im Verzeichnis vermerken |

## Mehrere Firmen (Mandanten, G2)

Im Mandantenbetrieb gilt dieses Verzeichnis **je Firma**: Jede Firma ist eigener Verantwortlicher für ihre Daten; der Betreiber
des Servers verarbeitet im Auftrag (Auftragsverarbeitungsvertrag nötig). Daten liegen je Firma in einer eigenen Datenbank unter
`mandanten/<kennung>/daten/` – mit eigenen Zugängen, eigenem Audit-Protokoll und eigenen Sicherungen. Ende eines Mandats:
Sicherung erstellen, nach Vertrag übergeben oder löschen, Ordner entfernen (`docs/MANDANTEN.md`).

## Rechte der Betroffenen

| Recht | Stand |
|---|---|
| Widerruf / Löschung (Art. 7 Abs. 3, Art. 17) | umgesetzt für Verkaufsanfragen (siehe oben); Ankauf blockiert bewusst |
| Auskunft (Art. 15) | **offen** – derzeit nur über die Anfrage-Ansicht; ein Export je Verkäufer fehlt |
| Berichtigung (Art. 16) | über Bearbeitung der Anfrage im Team |

## Datenquellen (Marktdaten)

Automatischer Abruf nur bei Quellen mit Vertrag oder schriftlicher Erlaubnis (`freigegeben = True`, Regel 12). Der Rahmen für
offizielle APIs (`wmscout/quellen/api_rahmen.py`) verlangt Freigabe, Zugangsdaten per Umgebungsvariable, HTTPS und Kontingent und bricht
bei 401/403/429 ab. Derzeit ist **keine** API-Quelle freigegeben; Status je Quelle in `docs/SOURCES.md`.
