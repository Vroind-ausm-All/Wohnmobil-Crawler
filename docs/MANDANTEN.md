# Mandantenbetrieb – mehrere Firmen auf einem Server (Phase G2, ADR-033)

Ohne Mandanten läuft alles wie bisher: ein Betrieb, `config.yaml`, Daten in `daten/`. Der Mandantenbetrieb ist **zusätzlich**
und wird nur mit `python scout.py app --mandanten` aktiv. Vorher die Checkliste `docs/PILOTBETRIEB.md` abarbeiten.

## Grundsatz: getrennte Datenbanken statt Mandanten-Spalte

Jede Firma bekommt einen eigenen Ordner `mandanten/<kennung>/` mit

| Inhalt | Pfad |
|---|---|
| eigene Einstellungen (nur Abweichungen von `config.yaml`) | `mandant.yaml` |
| Datenbank, Fotos, Dokumente | `daten/anzeigen.sqlite`, `daten/fotos/` |
| Sicherungen | `daten/sicherungen/` |
| Bericht, Protokolle des Suchlaufs | `ausgabe/` |
| gespeicherte Seiten für den Import | `import/` |

Die Pfade legt das Programm fest – `mandant.yaml` darf `ausgabe`, `sicherung` und `import` nicht enthalten. So kann ein
Konfigurationsfehler nie auf die Daten einer anderen Firma zeigen, und eine vergessene Bedingung in einer Abfrage kann keine
fremden Daten liefern: Jede Firma hat ihre eigene Datei, eigene Zugänge, eigenes Audit-Protokoll, eigene Live-Ereignisse und
eigene Nutzungszähler.

**Nicht geerbt** werden aus `config.yaml`: die Adresse (`app.oeffentliche_url`, `app.erlaubte_hosts`) und die Versandwege
WhatsApp und E-Mail (bleiben aus, bis der Mandant sie in `mandant.yaml` selbst einträgt) – sonst sendete ein Mandant über das
Konto der Hauptfirma. Alles andere (Bewertung, Suchen, Anschreiben-Vorlage …) gilt wie in `config.yaml`, solange `mandant.yaml`
nichts anderes sagt.

## Einrichten

```bash
python scout.py mandant anlegen firma-b --name "Firma B GmbH" --url https://firma-b.example.de
python scout.py --mandant firma-b nutzer einladen "Berta" --rolle inhaber   # Link: Berta setzt ihr Passwort selbst (F4)
python scout.py mandant liste
python scout.py app --mandanten                 # alle Mandanten; Hostname wählt die Firma
python scout.py app --mandanten --lokal firma-b # zusätzlich über http://127.0.0.1:8765 (Rechner des Betreibers)
```

* Jeder Mandant braucht **einen eigenen Hostnamen** (z. B. Subdomain); der Reverse-Proxy leitet alle auf `127.0.0.1:8765`
  weiter und reicht den `Host`-Kopf unverändert durch. Doppelte Hostnamen verhindern den Start.
* Unbekannte Hostnamen erhalten 403, ohne dass die App den Inhalt liest oder Mandanten nennt. `127.0.0.1` ist im
  Mandantenbetrieb nur mit `--lokal KENNUNG` erreichbar.
* Anmeldungen gelten je Mandant: Ein Zugang von Firma A funktioniert bei Firma B nicht, ein Sitzungs-Cookie von A ist bei B
  wertlos.
* Alle Befehle wirken mit `--mandant KENNUNG` auf diesen Mandanten, z. B. `sichern`, `wiederherstellen`, `audit`, `nutzung`,
  `anfrage widerruf`, `standort anlegen`.
* **Kunden-Zugang (F4):** Die Einladung gibt einen Einmal-Link mit der Adresse des Mandanten aus (7 Tage gültig). Der Kunde legt dort
  sein Passwort selbst fest und ist angemeldet; weitere Mitarbeiter lädt er unter „Zugänge“ selbst ein. Dort trägt er auch seine
  Händlerzugänge bei mobile.de/AutoScout24 ein; das Passwort setzt der Betreiber als Umgebungsvariable
  `WMSCOUT_<KENNUNG>_MOBILEDE_PASSWORT` auf dem Server.
* Nutzung aller Mandanten eines Monats: `python scout.py mandant nutzung --monat 2026-10` (Grundlage für eine spätere,
  optionale Abrechnung; keine Preise).

## Grenzen und offene Punkte

* Ein Prozess bedient alle Mandanten; jeder Mandant hat eigene Sperre und eigene Verbindung, aber Threads und Live-Grenzen
  gelten je Mandant. Für viele Mandanten auf einem Rechner nicht ausgelegt (Pilot: wenige Firmen).
* Marktdaten (Suchläufe) holt jeder Mandant selbst – keine gemeinsame Marktdatenbasis. Auto-Suche je Mandant in `mandant.yaml`.
* Kein übergreifender Administrator in der Oberfläche; der Betreiber arbeitet über die Kommandozeile mit `--mandant`.
* **Mandant löschen:** App beenden, `python scout.py --mandant KENNUNG sichern`, Sicherung nach Vertrag aufbewahren bzw.
  löschen, dann den Ordner `mandanten/<kennung>/` entfernen. Das Programm löscht nie selbst einen Mandanten.
* Bestehende Daten (`daten/`) werden nicht automatisch in einen Mandanten verschoben.
