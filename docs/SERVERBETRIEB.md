# Serverbetrieb – Anleitung für den Betrieb auf einem gemieteten Server (P7-04)

Der Scout läuft bisher auf einem Rechner im Büro (`docs/HANDY-APP.md`). Diese Anleitung beschreibt den Umzug auf einen eigenen
Linux-Server, damit das **öffentliche Ankaufsportal** (P7-03, ADR-068) rund um die Uhr erreichbar ist. Sie ist vorbereitet und
**nicht ausgeführt**: Server mieten, Domain, Verträge und die Freischaltung entscheidet der Betreiber (CLAUDE.md, Regel 13).
Ergänzend gilt die Checkliste `docs/PILOTBETRIEB.md`. Technische Anleitung, keine Rechtsberatung.

> **Wichtig:** Programmbefehle immer als Dienstbenutzer ausführen: `sudo -u scout .venv/bin/python scout.py …` (im Ordner
> `/opt/wohnmobil-scout`) – **nie als root**. Sonst legt `scout.py` Datenbank-, WAL- und Sperrdateien als root an, und die Dienste
> scheitern danach mit „readonly database“ bzw. fehlenden Rechten. Unten steht kurz `S=` für `sudo -u scout .venv/bin/python scout.py`.

## 0. Aufbau

```
Verkäufer (Internet) ──HTTPS──► Caddy :443 ──► Ankaufsportal 127.0.0.1:8770  (scout.py portal: nur Formular, Status, Impressum, Datenschutz)
Team (Handy/PC) ──Tailscale──► tailscale serve ──► Team-App 127.0.0.1:8765  (scout.py app: Anmeldung, alles andere)
                                                        │
                       beide Dienste ──► gleiche SQLite-Datenbank /opt/wohnmobil-scout/daten/anzeigen.sqlite (WAL)
```

Vorlagen im Ordner `betrieb/`:

| Datei | Zweck |
|---|---|
| `systemd/wohnmobil-scout-app.service` | Team-App als Dienst (Neustart bei Fehler, gehärtet) |
| `systemd/wohnmobil-scout-portal.service` | Ankaufsportal als Dienst |
| `systemd/wohnmobil-scout-sicherung.service` + `.timer` | tägliche Sicherung um 03:20 |
| `systemd/wohnmobil-scout-datenschutz.service` + `.timer` | wöchentlich Aufbewahrungsfristen anwenden (vorbereitet, aus) |
| `logrotate-caddy-portal` | Portal-Protokoll täglich rotieren, nach 14 Tagen löschen |
| `Caddyfile` | HTTPS mit automatischen Zertifikaten, HSTS, Größengrenze, gekürzte IP-Adressen im Protokoll |
| `umgebung.beispiel` | Namen der Geheimnisse (Werte nur auf dem Server, Rechte 600) |
| `config.local.beispiel.yaml` | Server-Einstellungen (Adressen, Proxy, Portal, Impressum) |

## 1. Was nur der Betreiber erledigen kann

- [ ] **Server mieten** (kostenpflichtig): Standort Deutschland/EU, z. B. kleiner virtueller Server mit 2 vCPU, 4 GB RAM, 40 GB SSD.
      Vertrag zur **Auftragsverarbeitung** (AV-Vertrag) mit dem Hoster abschließen.
- [ ] **Domain/Subdomain** für das Portal (z. B. `verkaufen.firma.de`) mit DNS-Eintrag (A/AAAA) auf den Server.
- [ ] **Rechtliche Prüfung** von Impressum, Datenschutzhinweisen und Einwilligungstext (Vorlagen in `vorlagen/portal_*.html`,
      Angaben in `config.local.yaml → portal → impressum`). Danach `texte_geprueft: true` und `verkaeuferportal → einwilligung_version` erhöhen.
- [ ] **Tailscale-Konto** für das Team (Variante A, empfohlen) oder Entscheidung für Variante B (Team-App über Caddy).
- [ ] **Freischaltung** des Portals: `portal → aktiv: true`.
- [ ] Ziel für **Sicherungen außer Haus** (z. B. Speicherplatz bei einem zweiten Anbieter) und dessen Zugang.

## 2. Server vorbereiten (einmalig)

Empfohlen: **Debian 13 („trixie“)** – bringt Python 3.13 mit (das Projekt läuft nur mit 3.13, CLAUDE.md Regel 4).

```bash
apt update && apt full-upgrade -y
apt install -y sudo curl python3.13 python3.13-venv git unattended-upgrades ufw logrotate
dpkg-reconfigure -plow unattended-upgrades          # Sicherheitsupdates automatisch
adduser --system --group --home /opt/wohnmobil-scout scout
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable    # 8765/8770 bleiben zu
```

SSH nur mit Schlüssel (`PasswordAuthentication no` in `/etc/ssh/sshd_config`). Datenträgerverschlüsselung beim Hoster prüfen.

## 3. Programm installieren

```bash
sudo -u scout git clone <Repository-Adresse> /opt/wohnmobil-scout
cd /opt/wohnmobil-scout
sudo -u scout ./installieren.sh                      # legt .venv an, installiert aus gesperrten Hashes
sudo -u scout mkdir -p daten ausgabe import          # müssen vor dem Dienststart existieren (beschreibbare Ordner)
sudo -u scout cp betrieb/config.local.beispiel.yaml config.local.yaml    # dann anpassen
```

**Daten vom Büro-PC übernehmen:** dort `python scout.py sichern`, die Sicherung (`daten/sicherungen/*.sqlite` und `*.fotos.zip`)
nach `/opt/wohnmobil-scout/daten/sicherungen/` kopieren (`sudo -u scout mkdir -p daten/sicherungen`, danach
`chown scout:scout daten/sicherungen/*`) und `sudo -u scout .venv/bin/python scout.py wiederherstellen <Datei> --bestaetigt` ausführen –
**bevor** die Dienste starten. Danach den Scout auf dem Büro-PC nicht mehr parallel benutzen (zwei getrennte Datenbanken).

Ohne übernommene Daten: ersten Inhaber anlegen (`sudo -u scout .venv/bin/python scout.py nutzer einladen NAME --rolle inhaber`).
Ohne angelegte Nutzer ist die Team-App von außen gesperrt.

## 4. Geheimnisse

```bash
mkdir -p /etc/wohnmobil-scout
cp /opt/wohnmobil-scout/betrieb/umgebung.beispiel /etc/wohnmobil-scout/umgebung
chown root:root /etc/wohnmobil-scout/umgebung && chmod 600 /etc/wohnmobil-scout/umgebung
python3 -c "import secrets; print(secrets.token_urlsafe(48))"     # Wert für SCOUT_PORTAL_SCHLUESSEL
```

Nur dort eintragen, nie in `config.yaml`/`config.local.yaml` oder ins Repository. Ein neuer Portal-Schlüssel macht alle
Statuslinks der Verkäufer ungültig.

## 5. Dienste

```bash
cp /opt/wohnmobil-scout/betrieb/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wohnmobil-scout-app wohnmobil-scout-sicherung.timer
systemctl enable --now wohnmobil-scout-portal       # erst nach Freischaltung (portal → aktiv: true); sonst beendet es sich mit Begründung
journalctl -u wohnmobil-scout-portal -n 30          # Startmeldung bzw. Gründe
```

Die Auto-Suche (`app → auto_suche_stunden`) bleibt aus, solange keine freigegebene Quelle sie braucht (Regel 12).

## 6. HTTPS mit Caddy

```bash
apt install -y caddy
cp /opt/wohnmobil-scout/betrieb/Caddyfile /etc/caddy/Caddyfile     # Platzhalter-Domains ersetzen
mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy
cp /opt/wohnmobil-scout/betrieb/logrotate-caddy-portal /etc/logrotate.d/caddy-portal     # täglich, nach 14 Tagen gelöscht
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

Caddy holt die Zertifikate selbst, sobald der DNS-Eintrag stimmt, und leitet HTTP auf HTTPS um. Das Portal-Protokoll enthält Zeitpunkt,
Methode, aufgerufene Adresse (ohne #-Teil), Antwortcode, Dauer, Größe und die **gekürzte** IP-Adresse – **keine Kopfzeilen** (also auch
keinen Upload-Token, kein Cookie, keinen Browser-Namen). `logrotate` rotiert täglich und löscht nach 14 Tagen. Genau diese Angaben gehören
in `portal → impressum → server_protokolle` (Datenschutzhinweise).
Grenzen gegen Massenanfragen setzt das Portal selbst (je IP und gesamt); der Debian-Caddy hat ohne Zusatzmodul kein Ratenlimit
(nachrüstbar mit `xcaddy` und dem Modul `caddy-ratelimit` oder per `fail2ban` auf das Protokoll – nicht vorbereitet).

## 7. Zugang fürs Team

**Variante A (empfohlen): nur über Tailscale.** Die Team-App ist im Internet gar nicht sichtbar.

```bash
curl -fsSL https://tailscale.com/install.sh | sh && tailscale up
tailscale serve --bg 8765                            # https://<server>.<tailnet>.ts.net → 127.0.0.1:8765
```

Vorher in der Tailscale-Verwaltung **MagicDNS** und **HTTPS Certificates** einschalten (wie in `docs/HANDY-APP.md`). Diese Adresse als
`app → oeffentliche_url` in `config.local.yaml` eintragen (Links in Benachrichtigungen, Hostprüfung).
**Nicht geprüft:** ob `tailscale serve` einen `X-Forwarded-For`-Kopf setzt. Ohne ihn kommen alle Team-Anfragen von 127.0.0.1: Die
Login-Bremse je Gerät (20 Fehlversuche) gilt dann für das ganze Team gemeinsam, und im Audit-Protokoll steht keine Geräteadresse
(der Nutzer schon). `app → vertrauter_proxy: true` nur setzen, wenn ausschließlich `tailscale serve` die App erreicht und der Kopf
nachweislich gesetzt wird (z. B. kurz `sudo -u scout .venv/bin/python scout.py audit --tage 1` nach einem Login prüfen).

**Variante B: über Caddy.** Block `app.example.de` im `Caddyfile` einkommentieren, in `config.local.yaml`
`app → oeffentliche_url: https://app.example.de`, `vertrauter_proxy: true`, `nur_https: true`. Dann gelten zusätzlich alle
Punkte aus `docs/PILOTBETRIEB.md`. Deren Ratenlimit für `/api/login` im Proxy ist mit dem Debian-Caddy ohne Zusatzmodul **nicht**
umsetzbar (siehe Abschnitt 6) – bis dahin gilt nur die Login-Bremse der App; das ist ein Grund mehr für Variante A.

## 8. Sicherung

- Täglich 03:20 Sicherung durch den Timer (Dienstbenutzer `scout`). Die Sicherung wird geprüft und rotiert (`config.yaml → sicherung → behalten`).
- **Außer Haus kopieren** (Betreiber): z. B. `restic` oder `rclone` mit eigenem Zugang, **verschlüsselt**, als zweiter Timer nach
  der Sicherung. Gelöschte Daten bleiben bis zur Rotation in älteren Sicherungen (`docs/DATENRECHTE.md`).
- **Wiederherstellung einmal üben:** `systemctl stop wohnmobil-scout-app wohnmobil-scout-portal`,
  `sudo -u scout .venv/bin/python scout.py wiederherstellen <Datei> --bestaetigt`, Dienste wieder starten.
- **Aufbewahrungsfristen** (`config.yaml → datenschutz`) wendet die App beim Start und nach Suchlauf/Import an. Ein Server ohne
  Auto-Suche startet selten neu – dann werden z. B. Portal-Anfragen nicht fristgerecht anonymisiert. Dafür liegt der Timer
  `wohnmobil-scout-datenschutz.timer` bei (wöchentlich „datenschutz --ausfuehren --bestaetigt“ als Dienstbenutzer, mit Sicherung vorher); er ist
  **nicht** eingeschaltet – nach Freigabe durch den Betreiber: `systemctl enable --now wohnmobil-scout-datenschutz.timer`.

## 9. Überwachung

- `GET /gesund` (nur GET, nicht HEAD) liefert `{"ok": true}` ohne Anmeldung und ohne Daten (prüft die Datenbank): Team-App
  `curl -fsS http://127.0.0.1:8765/gesund`, Portal `curl -fsS https://verkaufen.example.de/gesund`. Für einen externen
  Verfügbarkeitsdienst nur die Portal-Adresse verwenden. Über den Proxy antwortet die Team-App erst, wenn Nutzer angelegt sind.
- Protokolle: `journalctl -u wohnmobil-scout-app -u wohnmobil-scout-portal`, `ausgabe/scout.log` (rotiert), `/var/log/caddy/`.
- Wöchentlich: `sudo -u scout .venv/bin/python scout.py audit --tage 7`, `… scout.py datenschutz` (fällige Löschungen, nur Bericht),
  `systemctl list-timers`.
- App, Portal und Sicherung schreiben in dieselbe `ausgabe/scout.log`; beim Rotieren können Zeilen in der falschen Datei landen.
  Vollständig ist das Systemprotokoll (`journalctl`).

## 10. Updates

```bash
cd /opt/wohnmobil-scout
sudo -u scout .venv/bin/python scout.py sichern       # zuerst sichern
sudo -u scout git pull
sudo -u scout ./installieren.sh
cp betrieb/systemd/* /etc/systemd/system/ && systemctl daemon-reload     # falls sich die Vorlagen geändert haben
systemctl try-restart wohnmobil-scout-app wohnmobil-scout-portal          # startet nur, was schon läuft
```

Eine nötige Datenbank-Migration läuft beim Start automatisch – mit Sicherung vorher, in einer Transaktion (CLAUDE.md, Regel 3).

## 11. Suchagenten-Mails

Benachrichtigungen der Börsen (P2-06) liest der Scout als `.eml` aus `import/email/` (`eingaenge → email → aktiv: true`). Auf dem
Server müssen die Mails dort ankommen – z. B. per eigenem Postfach und einem Abholprogramm (getmail/fetchmail) oder von Hand.
Einrichtung und Zugangsdaten liegen beim Betreiber; Passwörter nur in `/etc/wohnmobil-scout/umgebung`.

## Nicht geprüft

Die Vorlagen sind nicht auf einem echten Server getestet. Geprüft ist nur die Syntax der systemd-Dateien (`systemd-analyze verify`,
ohne installiertes Programm) und was `tests/test_serverbetrieb.py` beschreibt (Inhalt der Vorlagen, Health-Check). **Nicht geprüft:**
`caddy validate` (insbesondere die `ip_mask`-Syntax der Debian-Version), Zertifikatsbezug, `logrotate`, Tailscale (Kopfzeilen, Zusammenspiel
mit Caddy auf Port 443) und die Härtungsoptionen (`ProtectSystem=strict` u. a.) im laufenden Betrieb.
