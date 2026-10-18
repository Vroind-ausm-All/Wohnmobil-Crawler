# Rollenmatrix (P1-15, Betreiberentscheidung F11 vom 17.10.2026)

Grundsatz: **Lesen frei im Team, Schreiben nur, wer zuständig ist.** Ohne angelegte Nutzer (Einzelplatz, Zugriff nur vom
eigenen Rechner) gibt es keine Rollen – dann darf der lokale Nutzer alles wie bisher. Standort-Zugänge (Händler) sehen nur
das Händlerportal (Positivliste, ADR-026). Jede Änderung und jedes Lesen von Verkäuferdaten steht im Audit-Protokoll (ADR-031).

„Zuständig“ heißt je Objekt:
* **Inserat:** wer es übernommen hat (Bearbeiter) bzw. wer es kontaktiert hat;
* **Verkaufsanfrage:** ihr Bearbeiter (ohne Bearbeiter: jedes Teammitglied, das sie dabei übernimmt);
* **Besichtigung:** eingetragener Besichtiger oder Bearbeiter des Inserats bzw. der Anfrage;
* **Ankaufsvorgang:** wie die zugehörige Besichtigung.

| Aktion | Inhaber | Mitarbeiter | Standort |
|---|---|---|---|
| Inserate, Anfragen, Besichtigungen, Ankäufe, Team-Übersicht **lesen** | ja | ja | nein (nur Händlerportal) |
| Inserat übernehmen / abgeben | ja | übernehmen, wenn frei; abgeben, wenn eigenes | nein |
| Inserat einem Kollegen zuweisen, Übernahme erzwingen | ja | nein | nein |
| Status setzen (vorbereitet, kontaktiert, Verhandlung, abgesagt …) | ja | nur bei eigenem oder freiem Inserat | nein |
| Status **„gekauft“** direkt setzen | ja | nein – nur über den Abschluss der Besichtigung | nein |
| Notiz am Inserat | ja | ja (bewusst frei, Absprache im Team) | nein |
| **Suchlauf** starten, gespeicherte Seiten (Ordner) **importieren** | ja | nein | nein |
| Inserat per URL + Text einlesen (`POST /api/import/text`, Desktop und Handy) | ja | ja | nein |
| Besichtigung anlegen (Inserat ohne EZ: nur mit Marktwert) | ja | ja, übernimmt dabei das Inserat | nein |
| Besichtigung planen, speichern, Fotos, Abschluss | ja | Besichtiger oder Bearbeiter | nein |
| Verkaufsanfrage erfassen | ja | ja | nein |
| Verkaufsanfrage ändern (Status, Notiz, Fotos, übernehmen) | ja | Bearbeiter (oder übernimmt sie, wenn frei) | nein |
| Verkaufsanfrage für Standorte freigeben, Widerruf ausführen | ja | nein | nein |
| Demo-Auktion starten, abbrechen, Zuschlag/Ablehnung | ja | nein | nein |
| Gebot abgeben, Interesse melden | nein | nein | ja (nur freigegebene Fahrzeuge) |
| Kalkulation speichern / nachrechnen | ja | ja | nur ansehen am Gebot |
| Ankaufsschritte (Vertrag, Übergabe, Kosten, Verkauf, Dokumente) | ja | zuständig (wie Besichtigung) | nein |
| Ankauf stornieren | ja | nein | nein |
| Standorte anlegen/prüfen, Audit-Protokoll, Nutzungszähler | ja | nein | nein |
| Nutzer anlegen/sperren, Sicherung, Wiederherstellung, Mandanten | nur Kommandozeile (Betreiber) | – | – |

Geprüft durch HTTP-Tests je Rolle (`tests/test_phase1_abschluss.py`, `test_team_*.py`, `test_haendler.py`, `test_auktion.py`,
`test_audit.py`, `test_sicherheit.py`).
