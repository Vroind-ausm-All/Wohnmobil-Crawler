# Datenquellen anbinden – Adapter-Schnittstelle

Jede Plattform (Kleinanzeigen, mobile.de – bisher nur gespeicherte Seiten –, später AutoScout24, Caraworld, Händler-Feeds …) wird über einen
**Adapter** angebunden. Ein Adapter liefert ausschließlich `Inserat`-Objekte. Speichern, Bewerten, Anschreiben
und die Oberfläche funktionieren für alle Quellen gleich.

```
config.yaml (suchen) ──▶ Importer ──▶ Quelle.suche(auftrag) ──▶ Suchseite[Inserat, …] ──▶ Datenbank
                                 └──▶ Quelle.details(url)  ──▶ Inserat (vollständig)   ──▶ Datenbank
```

Code: `wmscout/quellen/basis.py` (Schnittstelle), `wmscout/quellen/kleinanzeigen/` (Beispiel), `wmscout/importer.py`.

## 1. Vor dem Programmieren: Zugang klären

| Zugriffsart (`zugriffsart`) | Beispiel | Voraussetzung |
|---|---|---|
| `api` | offizielle Schnittstelle von mobile.de / AutoScout24 | Vertrag bzw. API-Schlüssel des Anbieters |
| `feed` | CSV/XML/JSON-Export eines Händlers | schriftliche Freigabe des Händlers |
| `web` | Abruf öffentlicher Seiten | nur, wenn die Nutzungsbedingungen es erlauben |
| `manuell` | Nutzer fügt URL oder Datei ein | keine |

* `freigegeben = True` nur, wenn der Anbieter den automatisierten Zugriff erlaubt (API-Vertrag, Feed-Freigabe).
  Der Importer schreibt bei nicht freigegebenen Quellen bei jedem Lauf einen Hinweis ins Protokoll.
* **Verboten:** Captchas lösen, Sperren umgehen (IP-Wechsel, gefälschte Browser-Fingerabdrücke), Logins
  automatisieren, Ratenbegrenzungen ignorieren. Bei Sperre muss der Adapter `QuelleGesperrt` werfen.
* Zugangsdaten (API-Schlüssel) nie in `config.yaml`, sondern als Umgebungsvariable.

## 2. Adapter schreiben

```python
# wmscout/quellen/beispiel_feed.py
from collections.abc import Iterator

from .basis import Inserat, Quelle, Suchauftrag, Suchseite


class BeispielFeedQuelle(Quelle):
    kennung = "beispiel_feed"          # eindeutig, wird in der Datenbank gespeichert
    name = "Autohaus Beispiel (Feed)"
    zugriffsart = "feed"
    freigegeben = True                  # Freigabe des Händlers liegt vor (Datum/Ansprechpartner dokumentieren)
    unterstuetzt_details = False        # Feed enthält bereits alle Felder

    def suche(self, auftrag: Suchauftrag) -> Iterator[Suchseite]:
        daten = self.abruf.hole(auftrag.parameter["feed_url"])     # self.abruf: siehe Abschnitt 3
        inserate = [
            Inserat(quelle=self.kennung, anzeigen_id=z["id"], url=z["link"], titel=z["titel"],
                    preis=int(z["preis"]), ez_jahr=int(z["ez"]), km=int(z["km"]), ort=z["plz_ort"],
                    gewerblich=True)
            for z in lese_feed(daten)
        ]
        yield Suchseite(nummer=1, inserate=inserate)
```

Dann in `wmscout/quellen/__init__.py` eintragen:

```python
QUELLEN = {q.kennung: q for q in (KleinanzeigenQuelle, BeispielFeedQuelle)}
```

und in `config.yaml` eine Suche anlegen:

```yaml
suchen:
  - name: Teilintegrierter          # wird als Fahrzeugart für die Bewertung genutzt
    quelle: beispiel_feed
    feed_url: https://haendler.example/export.json   # landet in auftrag.parameter
```

### Regeln für `suche()`

* Neueste Inserate zuerst. Der Importer bricht ab, sobald eine ganze Seite (ab Seite 2) schon bekannt ist.
* Eine leere Seite beendet die Suche.
* Hat eine Seite Inhalt, aber es wurde nichts erkannt (Layoutänderung), setzt der Adapter
  `layout_verdacht=True` und `rohdaten=…`. Der Importer speichert dann eine Diagnosedatei und meldet es.
* Gesuche (Kaufgesuche) mit `ist_gesuch=True` kennzeichnen – sie werden nicht gespeichert.

### Regeln für `details()`

* Nur implementieren, wenn die Suche unvollständige Daten liefert (`unterstuetzt_details = True`).
* Inserat weg → `InseratNichtGefunden`. Sonstige Fehler → passende Unterklasse von `QuellenFehler`.

### Felder von `Inserat`

`quelle`, `anzeigen_id`, `url` sind Pflicht. Alle anderen Felder sind optional und in einheitlichen Einheiten:
Preis in ganzen Euro, `km` als Zahl, `ez_jahr` als Jahreszahl, `ort` als „PLZ Ort“ (für die Entfernung),
`gewerblich` als `True`/`False`/`None` (unbekannt). Marke und Modell müssen nicht normalisiert sein, das
erledigt `wmscout/normalisierung/fahrzeug.py`.

## 3. Netzwerk: `Abruf`

Adapter holen Daten nie direkt mit `requests`, sondern über `self.abruf.hole(url)`:

* produktiv `netz.HoeflicherAbruf`: Pausen laut `config.yaml → crawler`, Wiederholung bei Serverfehlern,
  `QuelleGesperrt` bei HTTP 403/429, `HttpFehler`/`NetzwerkFehler` sonst
* in Tests ein Fake ohne Netzwerk (`tests/daten.py → FakeAbruf`)

API-Quellen mit eigener Authentifizierung können einen eigenen Abruf mitbringen. Er muss dieselben
Fehlerklassen werfen.

### Offizielle APIs: `ApiQuelle` (Phase G0)

Für Quellen mit Vertrag oder schriftlicher Erlaubnis gibt es `wmscout/quellen/api_rahmen.py`. Eine Unterklasse setzt
`kennung`, `name`, `basis_url` (nur HTTPS), `zugang_variable` (Name der **Umgebungsvariable** mit dem Schlüssel – nie in
`config.yaml` oder im Repository) und erst nach Klärung der Rechte `freigegeben = True`; sie implementiert `kopfzeilen`,
`suchparameter` und `inserate_aus`. Der Rahmen blättert bis zur leeren Seite, hält das Kontingent
(`api_quellen.<kennung>.max_abrufe_je_lauf`, Standard 50) und die Pause (`pause_sek`) ein, wiederholt nur Serverfehler (5xx)
und bricht bei 401/403/429 ohne Wiederholung ab. Ohne Freigabe oder Schlüssel wird die Quelle gar nicht erst erzeugt.
Beispiel mit Fake-Antworten: `tests/test_api_quellen.py`. Derzeit ist keine API-Quelle angebunden.

### Quellen und Eingänge schalten (P2-04, ADR-036)

Eine Pull-Quelle läuft im Suchlauf, sobald sie im Code freigegeben ist (`freigegeben = True`: bewusste Code-Änderung nach geklärten
Nutzungsrechten, Regel 12, Eintrag in `docs/SOURCES.md`, vom Betreiber per Pull Request geprüft) und in `suchen` eingetragen ist;
der Betreiber kann sie mit `quellen aus` abschalten. Sonst wird sie vor dem Abruf übersprungen und im Ergebnis
unter `uebersprungen` gemeldet (`[{"quelle": …, "grund": "nicht freigegeben" | "deaktiviert"}]`) – das ist kein Fehler.

* `python scout.py quellen liste` zeigt Kennung, Zugriffsart, Code-Freigabe, Schalter und ob der Suchlauf die Quelle ausführt.
* `python scout.py quellen an|aus KENNUNG` schreibt die Zeile in der Tabelle `quellen`. Für nicht freigegebene Quellen werden
  **beide** Befehle abgelehnt (Exit ≠ 0, nichts gespeichert): `an` wäre eine Umgehung der Freigabe, `aus` bewirkt nichts, solange die
  Quelle ohnehin nicht läuft. Fehlt die Zeile (oder steht dort nur der Ausgangswert 0/0), gilt der Code: freigegebene Quelle ⇒ läuft.
* Der Push-Kanal `api`/`stream` (`EreignisSpeicher`) verlangt die Tabelle (freigegeben, aktiv, Zugriffsart `api`) und, wenn es
  einen Adapter gibt, zusätzlich dessen Code-Freigabe.
* Eingänge ohne Portalabruf (`seiten`, `text`, `email`) schaltet `config.yaml → eingaenge → <name> → aktiv` (Standard: an, an,
  aus). Abgeschaltet liest der Eingang nichts; Dateien bleiben liegen. Neue Eingänge fragen `schalter.eingang_pruefen(cfg, name)`.
* Neue Pull-Quelle: `freigegeben = True` nur setzen, wenn die Rechte geklärt sind – damit läuft sie, sobald eine Suche auf sie zeigt.
  Der Report des CLI-Suchlaufs nennt übersprungene Quellen nicht (nur Log und App-Meldung).

## 4. Testen

1. Beispielantworten der Quelle (anonymisiert) als Testdaten anlegen. Keine echten Abrufe in Tests.
2. Der Vertragstest `tests/test_quellen.py::test_vertrag_jeder_quelle` läuft automatisch für jede
   registrierte Quelle.
3. Eigene Tests: Parser (Felder korrekt), `suche()` (Seiten, Abbruch), `details()` (404 → `InseratNichtGefunden`),
   Importer-Lauf mit Fake-Abruf (siehe `test_neue_quelle_wird_importiert`).

## 4a. Eingang per Adresse + Text (P2-05)

Kein Adapter, sondern ein Push-Eingang (`wmscout/eingang/text.py`, `TextEingang`, Kanal `manuell`, ADR-010/035): Der Nutzer liefert die
Adresse einer einzelnen Anzeige und den kopierten Anzeigentext (`POST /api/import/text`, JSON `{"url", "text", "anbieter"}`; Text höchstens
50 000, Adresse höchstens 2000 Zeichen). Der Server **ruft die Adresse nie ab**:

* Plattform und Anzeigen-ID nur aus der Adresse (Hosts `*kleinanzeigen.de`, `*.mobile.de`; nur http/https; ID über die Helfer der Parser,
  `md-…` bei mobile.de). Gespeichert wird die aus der ID neu gebildete Detail-Adresse, nie die eingegebene. Fremde Hosts, andere Schemata,
  Suchseiten und Adressen ohne ID ergeben eine Lesung `unbekannt` mit Hinweis – nichts wird gespeichert (API: 422).
* Preis, Kilometer, Erstzulassung, PLZ/Ort, Titel und Marke aus dem Text; Fehlendes ergibt den Hinweis „unvollständig: …“, gespeichert
  wird trotzdem. **Preis: lieber keiner als ein falscher (ADR-038).**
  Gespeichert wird ein Preis nur, wenn er (a) sicher erkannt ist – Betrag mit VB/VHB davor oder dahinter, mit Label „Preis“/„Kaufpreis“/
  „Festpreis“ oder allein in einer Zeile, jeweils genau ein Wert (auch „24 900 €“ mit Leerzeichen als Tausendertrenner) – oder (b) vom
  Nutzer im Formular eingetragen wurde (API: `preis` ganze Zahl 1–2 000 000 oder `null`, `vb` Wahrheitswert; strikt typgeprüft). Die Nutzerangabe
  hat Vorrang; weicht sie vom sicheren Textpreis ab, steht ein Hinweis da. Beträge im Fließtext („Motor bei 2.500 € überholt“, „Restschuld
  15.000 €“) sind **nie** ein Preis; ohne sicheren oder eingetragenen Preis wird die Anzeige ohne Preis gespeichert (ein vorhandener Preis
  bleibt, keine Preisänderung, keine Nachfass-Folge), `preis_status` ist `unsicher` bzw. `fehlt` und der Hinweis nennt die gefundenen Beträge
  (ohne Jahreszahlen). Beträge nach Neupreis, Tausch, Anzahlung, Rate/mtl., „nachgerüstet“, „unter …“ sowie Zahlen mit Einheit (km, kg, PS …)
  zählen nie. Die Antwort enthält `preis_vorher` und `preis_aenderung` (`gesenkt`/`gestiegen`/`unveraendert`/`null`).
* **Herkunft der gespeicherten Werte:** Werte aus Suchlauf, Seitenimport und Mail-Import überschreibt der Text nicht (`Lesung.nur_leere_felder`):
  nur Leeres wird gefüllt; der Preis läuft wie immer über Preis- und Beobachtungshistorie. Werte, die selbst aus einem Text-Import stammen
  (Markierung `{"eingang": "text"}` in `details_json`, keine Schemaänderung), darf ein neuer Text ersetzen – ein falsch eingefügter Text
  lässt sich korrigieren. Jeder andere Kanal, der die Zeile schreibt, entfernt die Markierung. Nennt der Text eine andere Marke als die
  gespeicherte (geschützte) Anzeige, wird kein Preis aus dem Text übernommen (Hinweis „Text passt offenbar nicht zur gespeicherten Anzeige“);
  ein ausdrücklich eingetragener Preis gilt trotzdem.
* Adressen: nur ASCII, Anzeigen-ID ohne führende Null; mobile.de-Adressen der Form `/auto-inserat/<slug>/<id>.html` sind **offen** (Form nicht
  belegt, wird nicht erraten – nur `details.html?id=…`). Die Fahrzeugart wird nie gesetzt; der Importer leitet höchstens eine vorläufige
  Art aus dem Titel ab. Empfehlungen anderer Anzeigen am Textende („Ähnliche Anzeigen“) zählen nicht.
* Datenschutz: Telefonnummern, E-Mail-Adressen, Links, Straßenangaben und Namenszeilen werden vor der Auswertung entfernt (`bereinige`),
  Gesuche („Suche …“, „Wir kaufen …“) nicht gespeichert, Anbieter nur nach Nutzerangabe (sonst unbekannt).
* Gespeichert wird allein über `Importer.importiere(lesung, "manuell")`; dieselbe Anzeige über Seite und Text ist eine Zeile
  (gleiche Plattform + ID). Tests: `tests/test_text_import.py`.

## 5. Bekannte Einschränkungen (Phase 1)

* Die Datenbank-ID ist noch die Anzeigen-ID. Zwei Quellen mit gleicher ID würden kollidieren. Phase 2 führt
  `UNIQUE(quelle, anzeigen_id)` ein. Bis dahin pro Quelle eindeutige IDs verwenden, z. B. mit Präfix.
* Ein Fehler einer Quelle beendet derzeit den ganzen Lauf (wie bisher). Die Isolation je Quelle folgt in Phase 3.

## 6. E-Mail-Suchagenten (Gerüst, P2-06)

> **Nur mit nachgebildeten Mails geprüft – Abnahme mit echten Mails ausstehend (F3).** Der Aufbau der Parser folgt dem öffentlich bekannten
> Muster von Suchagent-Mails (Anzeigenblock je Treffer mit Bild, Titel, Preis, Ort, Link). Ob echte Mails von Kleinanzeigen und mobile.de
> so aufgebaut sind, ist **nicht belegt**; die Testmails (`tests/nachgebildet_mails.py`, Kopf `X-Scout-Testdaten`) sind selbst erzeugt.
> Erst wenn der Betreiber anonymisierte Original-Mails (`.eml`) liefert und der Import damit sauber läuft, gilt der Kanal als abgenommen.

**Bedienung.**
1. **Einschalten** (Standard aus): `config.yaml` bzw. `config.local.yaml` → `eingaenge: {email: {aktiv: true}}`. Ausgeschaltet wird nichts gelesen und kein Ordner angelegt.
2. **Mails ablegen:** Die Benachrichtigung des Suchagenten als `.eml` speichern und in `import/email/` legen (der Ordner wird beim ersten Einlesen angelegt).
   Thunderbird: Mail markieren → *Datei → Speichern unter → Datei…* (Dateityp *E-Mail-Datei (.eml)*) oder die Mail per Drag&Drop in den Ordner ziehen;
   Webmail: „Als .eml herunterladen“ bzw. „Original herunterladen/Quelltext speichern“. Mehrere Mails pro Durchgang sind möglich.
3. **Einlesen:** `python scout.py import --mails` (anderer Ordner: `--ordner PFAD`; ohne `--mails` liest `import` wie bisher nur gespeicherte Seiten) oder in der App der Knopf
   **„✉ Mails einlesen“** (erscheint nur bei eingeschaltetem Eingang; nur Inhaber; je Klick höchstens 25 Mails bzw. 20 Sekunden, der Rest beim nächsten Klick).
   Danach bewertet der Scout neu und erzeugt den Report.
4. **Ergebnis lesen:** Die Ausgabe nennt gelesene, nicht erkannte und nicht lesbare Mails und „Bitte prüfen“-Hinweise (verworfene Links, übersprungene Gesuche,
   „Layout verdächtig“ …); alles steht auch in `ausgabe/scout.log`.

**Was passiert.** `Importer.importiere_mails(ordner)` liest nur `*.eml` direkt im Ordner (nicht rekursiv, keine Verknüpfungen):

* Erkannt wird über die Absender-Domain (`*.kleinanzeigen.de`, `*.mobile.de`) oder – bei weitergeleiteten Mails – über Links auf Anzeigen dieser
  Plattform. Verweist eine Mail auf beide Plattformen gleich oft und hat keinen passenden Absender, ist sie „unbekannt“.
* Gelesen werden nur die Teile `text/plain` und `text/html` (HTML bevorzugt); Anhänge, auch angehängte Mails, werden ignoriert.
  Kodierungen quoted-printable/base64, Zeichensätze UTF-8, ISO-8859-1, Windows-1252 (unbekannter Zeichensatz → UTF-8, sonst Windows-1252).
  Grenzen (ADR-037): 5 MB je Datei, Kopf ≤ 64 KB, Kopfzeile ≤ 8 KB, ≤ 500 MIME-Trennzeilen, ≤ 200 000 HTML-Elemente, ≤ 100 HTML-Ebenen, ≤ 200 Anzeigen je Mail –
  darüber wird die Datei nach `fehlerhaft/` verschoben bzw. gekürzt und gemeldet.
* **Festgemacht wird an den Anzeigen-Links** (Kleinanzeigen `/s-anzeige/<slug>/<id>-<kat>-<region>`, mobile.de `details.html?id=<id>`, IDs nur ASCII-Ziffern ohne führende 0);
  Titel, Preis, Ort (sowie EZ und km bei mobile.de) kommen aus dem Textblock um den Link. Weiterleitungs-/Tracking-Links werden **nur mit `urllib.parse`
  zerlegt** (Ziel-Adresse in einem Parameter oder im Pfad); undurchsichtige Tokens ohne lesbare Ziel-Adresse bleiben ungelesen. **Kein Link wird abgerufen**,
  verlinkte Anzeigen werden nicht nachgeladen (ADR-010).
* Gespeichert wird nie der Link der Mail, sondern die aus der ID gebildete Adresse (Kleinanzeigen `https://www.kleinanzeigen.de/s-anzeige/<id>`,
  mobile.de `…/fahrzeuge/details.html?id=<id>`). Links mit fremdem Host (auch `evil.de/…?u=https://www.kleinanzeigen.de/…`, `www.kleinanzeigen.de@evil.de`)
  oder anderem Schema (`javascript:`, `ftp:`) werden verworfen und im Protokoll gezählt. Bilder werden nicht übernommen.
* **Preis nur aus einer eigenen Preiszeile** („38.500 €“, „38.500 € VB“, „Preis: 38.500 €“); nie aus dem Titel („… 2.000 € unter NP“), bei mehreren Beträgen,
  Durchgestrichenem, Neupreis/Miete/Raten – dann **kein Preis** (Hinweis „ohne eindeutige Preiszeile“). Lieber kein Preis als ein falscher; ein bekannter Preis in der Datenbank bleibt dann unberührt.
* Anbieter bleibt **unbekannt** (`gewerblich` leer), die Fahrzeugart höchstens **vorläufig** (aus dem Titel, Regeln wie beim Seitenimport).
  Gesuche und Ankaufsanzeigen („Suche …“, „Wohnmobil gesucht“, „Ankauf …“, „Kaufe …“) und Empfehlungsblöcke („Das könnte dich auch interessieren“, „Ähnliche Anzeigen“) werden
  nicht gespeichert und gemeldet. Haben weniger als die Hälfte der Treffer einen Preis oder Titel, steht der Hinweis „Layout teilweise verdächtig“.
* **Eine Mail ergänzt nur:** Bei bereits bekannter Anzeige bleiben Adresse, Titel, Ort, km, EZ, Marke und VB unverändert; nur leere Felder werden gefüllt, der Preis
  läuft über den normalen Preis-/Historienweg. Absender, Empfänger, Betreff und Mailtext werden nicht gespeichert.
* Gespeichert wird über `Importer.importiere(lesung, "email")` (Kanal `email` in `beobachtungen`/`preis_historie`); dieselbe Anzeige aus Mail und
  gespeicherter Seite ist **eine** Zeile (IDs: Kleinanzeigen numerisch, mobile.de `md-…`).
* Ablage: eingelesen → `import/email/eingelesen/<Datum>/`; nicht erkannt (andere Mails, Werbung, nur Gesuche, „Layout verdächtig“ = Plattform erkannt, aber keine
  Anzeigenlinks) → `import/email/nicht_erkannt/` mit Grund im Protokoll; unlesbare, zu große oder überladene Mails → `import/email/fehlerhaft/`. Ein Fehler in einer Datei hält die übrigen nicht auf.
* **Datenschutz:** Alles, was der Scout abgelegt hat (`eingelesen/`, `nicht_erkannt/`, `fehlerhaft/`), wird mit der Frist `datenschutz.inserate_anonymisieren_nach_monaten`
  gelöscht (`datenrechte.mails_nach_frist`, Teil von `frist_anwenden`: nach Mail-Import, Suchlauf, Seitenimport und beim App-Start). Maßgeblich ist das spätere von Datumsordner und Dateizeit;
  die Dateizeit wird beim Ablegen auf „jetzt“ gesetzt. **Noch nicht eingelesene Mails direkt in `import/email/` werden nicht gelöscht**, aber nach Ablauf der Frist gemeldet
  („N Mails liegen seit über der Datenschutz-Frist unverarbeitet im Ordner“ – Kommandozeile, App, Protokoll). Wer `nicht_erkannt/` zur Analyse aufheben will, kopiert Dateien vorher heraus.

**Annahmen über das Layout (bis zur Abnahme):** (1) Jede Anzeige hat einen eigenen Block, in dem Titel, Preis und „PLZ Ort“ als eigene Zeilen/Elemente stehen; (2) die
Links gehen direkt auf die Plattform-Domain oder über einen Weiterleitungs-Link derselben Domain mit lesbarer Ziel-Adresse; (3) mobile.de nennt EZ/km in einer Zeile
(„EZ 05/2015 • 80.000 km • …“); (4) im reinen Text steht die Angabenzeile im selben Absatz wie der Link; (5) der Preis steht in einer eigenen Zeile. Weicht die Wirklichkeit ab, meldet der Import „Layout verdächtig“
bzw. „Layout teilweise verdächtig“ – die Datei liegt dann in `nicht_erkannt/` und dient als Vorlage für die Anpassung (Selektoren und Regeln in `wmscout/eingang/email/`).
