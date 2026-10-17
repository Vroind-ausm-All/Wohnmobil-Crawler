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

## 5. Bekannte Einschränkungen (Phase 1)

* Die Datenbank-ID ist noch die Anzeigen-ID. Zwei Quellen mit gleicher ID würden kollidieren. Phase 2 führt
  `UNIQUE(quelle, anzeigen_id)` ein. Bis dahin pro Quelle eindeutige IDs verwenden, z. B. mit Präfix.
* Ein Fehler einer Quelle beendet derzeit den ganzen Lauf (wie bisher). Die Isolation je Quelle folgt in Phase 3.
