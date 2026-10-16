# Pilotbetrieb – Checkliste vor dem Betrieb über das interne Netz hinaus (Phase G0, ADR-030)

Der Scout ist für den Betrieb **auf einem Rechner im Büro** gebaut: Server nur auf `127.0.0.1`, Handys über
`tailscale serve` (HTTPS im eigenen Tailnet, docs/HANDY-APP.md). Für diesen Betrieb reicht die Härtung aus Phase G0.
Diese Liste gilt, **bevor** die App über ein öffentliches Netz, für weitere Firmen oder mit fremden Nutzern läuft.
Sie ist eine technische Checkliste, keine Rechtsberatung.

## 1. Erreichbarkeit

- [ ] Die App lauscht weiter nur auf `127.0.0.1`. Erreichbar wird sie ausschließlich über einen **Reverse-Proxy mit TLS**
      (z. B. Caddy oder nginx) oder `tailscale serve`; der Port 8765 ist von außen nicht offen.
- [ ] Proxy setzt **HSTS** (`Strict-Transport-Security: max-age=31536000`) und leitet HTTP auf HTTPS um.
- [ ] `config.yaml → app.oeffentliche_url` = die HTTPS-Adresse; weitere Namen nur über `app.erlaubte_hosts`. Andere Hostnamen
      beantwortet die App mit 403, bevor sie den Inhalt einer Anfrage liest.
- [ ] `app.nur_https: true` – das Anmelde-Cookie ist dann immer `Secure`.
- [ ] `app.vertrauter_proxy: true` **nur**, wenn ausschließlich der eigene Proxy die App erreicht. Dann wertet die App
      `X-Forwarded-For` (Login-Bremse je Gerät) und `X-Forwarded-Proto` aus; ohne Proxy könnte jeder diese Köpfe fälschen.
- [ ] Anfragen mit `X-Forwarded-*`/`Forwarded` gelten nie als „lokal“ – ohne angelegte Nutzer ist die App über den Proxy
      also gesperrt. **Vor dem Pilot mindestens einen Inhaber anlegen** (`scout.py nutzer anlegen …`).

## 2. Grenzen im Proxy

Die App begrenzt selbst: JSON 1 MB, Fotos/Dokumente ca. 8 MB je Bild, Lesezeitlimit 30 s je Verbindung, Login-Bremse
(5 Fehlversuche je Gerät+Name, 20 je Gerät, 15 min). Die Bremse liegt im Speicher und beginnt nach einem Neustart neu.

- [ ] Proxy-Ratenlimit für `/api/login` (z. B. 10/min je IP) und allgemein (z. B. 300/min je IP).
- [ ] Proxy-Grenze für die Größe des Inhalts (z. B. 15 MB) und für Kopfzeilen.
- [ ] Proxy-Timeouts (Lesen/Senden) gesetzt.

## 3. Zugänge

- [ ] Jeder Mitarbeiter und jeder Standort hat einen eigenen Zugang; keine geteilten Passwörter.
- [ ] Ausgeschiedene Nutzer sofort sperren (`scout.py nutzer sperren NAME`).
- [ ] Offene Punkte aus der Sicherheitsprüfung beachten (unten).

## 4. Daten und Sicherungen

- [ ] `docs/DATENRECHTE.md` mit Datenschutzbeauftragtem durchgehen: Rechtsgrundlagen, **Löschfristen**, Auskunft (Art. 15).
- [ ] Datenschutzerklärung für das Verkäuferformular und das Händlerportal veröffentlicht; Einwilligungstext passt dazu.
- [ ] Widerruf einer Verkaufsanfrage einmal durchspielen (`/anfragen` → „Widerruf: personenbezogene Daten löschen“ bzw.
      `scout.py anfrage widerruf REF --bestaetigt`).
- [ ] Sicherungen (`daten/sicherungen/`) **verschlüsselt und außer Haus** kopieren; Wiederherstellung einmal geprüft.
      Gelöschte Daten bleiben bis zur Rotation in älteren Sicherungen – im Verarbeitungsverzeichnis vermerken.
- [ ] Protokolldatei `ausgabe/scout.log` rotiert (5 × 5 MB); Aufbewahrung festlegen.
- [ ] Datenträger des Rechners verschlüsselt (BitLocker/FileVault/LUKS).

## 5. Software

- [ ] Abhängigkeiten mit `pip-audit -r requirements.txt` prüfen (in CI als nicht blockierender Job); Befunde vor dem Pilot klären.
- [ ] Python- und Betriebssystem-Updates eingespielt.
- [ ] Marktquellen: nur `freigegeben = True` mit geklärten Nutzungsrechten (docs/SOURCES.md). Offizielle APIs nur über
      `wmscout/quellen/api_rahmen.py`, Zugangsdaten nur als Umgebungsvariable.

## Offene Punkte aus der Sicherheitsprüfung (G0)

| Punkt | Stand |
|---|---|
| Lesezugriff nach Bedarf (Need-to-know) | Team liest firmenweit alle Anfragen – gewollt für eine Firma; Trennung zwischen Firmen folgt mit **G2 Mandanten** |
| Inline-Skripte (CSP mit `'unsafe-inline'`) | Nonce/Auslagerung als Folgearbeit |
| Sitzungs-Leerlaufzeit | Sitzungen laufen nach fester Dauer ab, nicht nach Untätigkeit |
| CSRF-Token je Sitzung | nicht umgesetzt; Schutz über SameSite-Cookie, JSON-Pflicht, Origin- und Sec-Fetch-Site-Prüfung |
| WebP/HEIC-Metadaten | nur JPEG/PNG werden bereinigt (die App verkleinert Fotos im Browser zu JPEG) |
| Audit-Protokoll wer was gesehen/geändert hat | folgt nach Phase F (Schema v10) |
| Rechte je Ankaufsschritt, PDF als Anhang | folgt nach Phase F |
| Notizen frei für das ganze Team | bewusst so (bestehender Ablauf), Entscheidung des Betreibers offen |
