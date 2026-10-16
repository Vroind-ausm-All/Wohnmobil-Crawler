# Datenrechte – Verzeichnis der Daten, Zwecke und Löschwege (Phase G0, ADR-030)

**Entwurf, keine Rechtsberatung.** Grundlage für das Verzeichnis der Verarbeitungstätigkeiten (Art. 30 DSGVO) und für die
Prüfung vor einem Pilotbetrieb. Rechtsgrundlagen und Fristen muss der Betreiber mit Datenschutzbeauftragtem bzw.
Steuerberatung festlegen – hier steht, **was das Programm tatsächlich speichert** und **wie es sich löschen lässt**.
Quellen und Nutzungsrechte der Marktdaten: `docs/SOURCES.md` (Status OK / PRÜFEN / BLOCKED).

## Personenbezogene Daten

| Daten | Wo (Tabelle / Ordner) | Zweck | Wer sieht es | Löschweg im Programm | Offen (Betreiber) |
|---|---|---|---|---|---|
| Verkäufer einer Verkaufsanfrage: Name, E-Mail, Telefon, PLZ, Ort, Einwilligung (Zeitpunkt, Textversion) | `verkaeufer` | Bewertung und Kontakt wegen Ankauf (Einwilligung im Formular) | Team; Standorte nur Region „12xxx“, nie Name/Kontakt | **Widerruf** (`/anfragen` Knopf des Inhabers oder `scout.py anfrage widerruf REF --bestaetigt`): anonymisiert, sofern keine weitere Anfrage desselben Verkäufers besteht | Frist ohne Widerruf (z. B. x Monate nach Abschluss) festlegen |
| Freitext und Notiz der Anfrage, Notiz-Verlauf | `verkaufsanfragen.beschreibung/notiz`, `anfrage_verlauf` | Zustand beschreiben, interne Absprache | Team (Standorte: Freitext ohne Telefon/E-Mail/Links) | Widerruf löscht beides | – |
| Fotos der Anfrage | Ordner `fotos/anfragen/<id>/`, `anfrage_fotos` | Zustand beurteilen | Team, freigegebene Standorte | Widerruf löscht Dateien und Einträge | – |
| Metadaten in Fotos (EXIF/GPS, XMP, IPTC) | – | – | – | werden seit G0 beim Speichern entfernt (JPEG, PNG; Anfrage- und Besichtigungsfotos) | andere Formate (WebP/HEIC) nicht bereinigt |
| Offline-Speicher der Handy-App | Browser-Cache des Handys | Arbeiten ohne Netz | Nutzer des Geräts | nur eine Positivliste (Heute, Fahrzeuge, Besichtigungen, Fotos); wird geleert, sobald der Server 401 meldet (abgemeldet, Sitzung abgelaufen oder gesperrt) | verlorene Handys: Sitzung sperren (`scout.py nutzer sperren`) |
| Besichtigung einer Anfrage: Adresse, FIN, Kennzeichen, Notizen, Fotos, Verkäuferangaben, Unterschriften | `besichtigungen` (`basis/daten/protokoll_json`), `fotos`, Ordner `fotos/<besichtigung>/` | Zustandsbericht, Kaufprotokoll | Team | Widerruf schwärzt die Besichtigung und löscht ihre Fotos – **nur ohne Ankauf** | – |
| Ankauf: Kaufprotokoll mit Unterschriften, Vertragsscan, Übergabe, Preise | `ankaeufe`, `ankauf_dokumente`, Ordner `fotos/ankaeufe/` | Kaufvertrag, Buchhaltung, Ergebnisvergleich | Team | **kein automatisches Löschen** – Aufbewahrungspflichten (z. B. HGB/AO); Widerruf wird bei jedem Vorgang verweigert, auch storniert; Vertragsfotos ohne EXIF/GPS | Fristen und Löschung nach Fristablauf festlegen |
| Inserate fremder Börsen (öffentliche Angebote), bei gespeicherten Kleinanzeigen-Seiten der Anbietername | `anzeigen`, `inserate`, `beobachtungen` (`details.verkaeufer_name`) | Marktbeobachtung, Ankaufsgelegenheit | Team | derzeit nur manuell | Frist für nicht weiterverfolgte Inserate festlegen |
| Anschreiben-Texte, Kontaktstatus | `anzeigen.anschreiben_text`, `bearbeitung` | Nachweis bestätigter Kontaktaufnahme | Team | manuell | – |
| Team- und Händler-Zugänge: Name, Telefon, Rolle, Standort, Passwort-Hash, Sitzungen | `nutzer`, `sitzungen` | Anmeldung, Zuständigkeit | Inhaber | `scout.py nutzer sperren`; Sitzungen laufen ab | Löschung ausgeschiedener Nutzer |
| Gebote, Auktionsprotokoll, Kalkulationen | `gebote`, `auktion_protokoll`, `kalkulationen` | Nachvollziehbarkeit (Phase D/E) | Team; Standorte nur eigene Gebote | nur anfügbar – enthalten **keine Kontaktdaten**: Kalkulationen speichern seit G0 Freitexte ohne Telefon/E-Mail/Links | Freitext kann Namen enthalten – Restrisiko |
| Audit-Protokoll (seit v10): Zeitpunkt, Nutzer, Rolle, IP, Methode, Pfad, Status, Objekt – **keine** Inhalte, Passwörter oder Kontaktdaten | `audit` (nur anfügbar) | Nachweis, wer Personendaten gelesen oder geändert hat (Rechenschaft, Art. 5 Abs. 2) | Inhaber (`scout.py audit`, `/api/audit`) | **kein Löschweg** im Programm (nur anfügbar) | Aufbewahrungsfrist festlegen; Löschung nach Frist als Wartungsschritt ergänzen |
| Protokolldatei | `ausgabe/scout.log` | Fehlersuche, Nachvollziehbarkeit von Aktionen | Betreiber | Rotation durch den Betreiber | Aufbewahrung festlegen; Log nennt Nutzernamen und Referenzen, keine Kontaktdaten der Verkäufer |
| Sicherungen | `daten/sicherungen/` (`config.yaml` → `sicherung.behalten`) | Wiederherstellung | Betreiber | rotieren automatisch (älteste zuerst) | **Gelöschte Daten bleiben bis zur Rotation in älteren Sicherungen** – im Verzeichnis vermerken |

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
