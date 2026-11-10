# Missa Control

Lokales Admin- und Integrations-Panel für die selbstgehostete KI-Assistentin **Missa**.

Missa Control läuft neben `missa-core` auf derselben Maschine (ai01), komplett lokal und ohne
Cloud-Dienste. Über das Panel bekommt Missa neue Fähigkeiten – ohne Programmieren und in wenigen
Klicks: MCP-Server, REST-APIs, Geräte, Kalender und mehr.

> **Oberste Regel:** Missa Control verändert `missa-core` nie. Das Panel arbeitet nur mit seinen
> eigenen Containern, Volumes und Netzwerken (Compose-Projekt `missa-control`) und legt alle Daten
> in `./data` ab.

## Was es kann

- **Integrationen in 3 Schritten:** Karte im Katalog wählen, Formular ausfüllen, „Testen und
  aktivieren“. Ohne Code für MCP-Server (per URL), REST-APIs (per OpenAPI), eingehende Webhooks und
  Geräte; fertige Karten für Nextcloud-Kalender und Home Assistant; eigene Integrationen als Ordner
  mit wenig Python.
- **Ein Anschluss für Missa:** Alle Funktionen kommen über ein MCP-Gateway bei missa-core an – mit
  Rechten pro Funktion (lesen: erlaubt, alles andere: erst nachfragen), Freigaben, Protokoll und
  Ereignissen.
- **Zugänge:** API-Keys, Tokens und Passwörter verschlüsselt gespeichert, nach dem Speichern nur noch
  maskiert sichtbar.
- **Modelle:** Rollen „schnell“ und „stark“ mit Haupt- und Ersatzmodell, OpenAI-kompatibler Anschluss.
- **Charakter:** Missas Profil bearbeiten, mit Versionsverlauf, YAML-Export und Test-Chat.
- **Gedächtnis:** Was Missa sich gemerkt hat, ansehen, suchen, korrigieren, löschen.
- **Regeln und Alarme:** „Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann …“ – per
  Auswahlfeldern oder von Missa selbst angelegt; Aktionen: Ereignis, Funktion aufrufen, anrufen.
- **Geräte:** ESP32 und Raspberry Pi Pico per Kopplungscode über den eigenen MQTT-Broker; Sensoren,
  Knöpfe, Schalter, Verlauf über 7 Tage.
- **Telefonie (vorbereitet):** erlaubte Anrufer, Ruhezeiten, Anrufverlauf – mit Test-Adapter, noch
  ohne echtes Telefon.
- **Serverlast:** CPU, Arbeitsspeicher, Speicherplatz und GPU von ai01 mit Verlauf.
- **Übersicht:** Startseite mit allem Eingerichteten als Verbindungsbaum und Live-Status.
- **Login:** Passwort und Zwei-Faktor-Anmeldung; ein einziger Besitzer, keine Benutzerverwaltung.

## Installation in 3 Befehlen

Voraussetzung: Linux (ai01: Debian) mit Docker und Docker Compose.

```bash
git clone https://github.com/Louidos/missa-control.git
```

```bash
cd missa-control
```

```bash
./scripts/install.sh
```

Das Skript prüft Docker und die Ports, erzeugt `.env` mit zufälligen Schlüsseln, legt `data/` an,
startet das Panel und den MQTT-Broker für Geräte und gibt am Ende die Adresse aus
(Standard: `http://<adresse-von-ai01>:8090`).

- Es kann beliebig oft ausgeführt werden: Eine vorhandene `.env` und vorhandene Daten bleiben unverändert.
- Ist ein Port belegt (Panel 8090, MQTT 1883), bricht es mit einer Meldung ab – es stoppt nie
  etwas Fremdes. Anderen Port wählen: in `.env` bei `MISSA_CONTROL_BIND` bzw. `MQTT_BIND`
  eintragen, Skript erneut starten.
- Ohne Geräte braucht es den MQTT-Broker nicht: in `.env` `COMPOSE_PROFILES=` (leer) eintragen.

**Erster Aufruf:** Passwort setzen (mindestens 10 Zeichen), QR-Code mit einer Authenticator-App
scannen, Code bestätigen. Danach ist das Panel nur noch mit Passwort **und** Code erreichbar.
Bitte gleich nach der Installation erledigen – bis dahin kann jeder im Netz das Panel einrichten.

**Danach:** Den Port 8090 in der Firewall nur für die eigene Admin-Workstation freigeben und das
Panel nie über einen öffentlichen Reverse Proxy veröffentlichen – siehe
[docs/sicherheit.md](docs/sicherheit.md).

Ausführlich, mit allen Einstellungen und Fehlerbehebung: [docs/installation.md](docs/installation.md).

## Erste Integration in 3 Schritten

1. Im Panel **Katalog** öffnen und eine Karte wählen, z. B. „MCP-Server“.
2. Das Formular ausfüllen (beim MCP-Server nur die URL) und **Verbindung testen**.
3. Rechte prüfen und **Aktivieren**.

Lesende Funktionen sind danach „erlaubt“, schreibende fragen „erst nach“. Die Integration erscheint
sofort in der Übersicht.

Fertige Karten gibt es für MCP-Server, REST-APIs (OpenAPI), Nextcloud-Kalender, Home Assistant,
eingehende Webhooks, Geräte sowie Serverlast, Gedächtnis, Regeln und Telefonie. Eigene Integrationen
mit wenig Code: siehe [docs/eigene-integration.md](docs/eigene-integration.md).

## Update, Backup und Betrieb

| Aufgabe | Befehl |
| --- | --- |
| **Update** (sichert vorher die Daten) | `./scripts/update.sh` |
| **Backup** von `data/` und `.env` nach `backups/` | `./scripts/backup.sh` |
| Protokoll ansehen | `docker compose -p missa-control logs missa-control` (MQTT-Broker: `… logs mqtt`) |
| Anhalten | `docker compose -p missa-control down` |
| Notfall: Authenticator-App verloren | `./scripts/reset-2fa.sh` |

Backup wiederherstellen: Panel anhalten, `tar -xzf backups/missa-control-<datum>.tar.gz` im
Repo-Ordner, dann `./scripts/install.sh`. Das Backup enthält die Schlüssel aus `.env` und gehört an
einen sicheren Ort.

Alle Skripte arbeiten nur mit dem Compose-Projekt `missa-control` und nur im Repo-Ordner.

## Anleitungen

| Thema | Dokument |
| --- | --- |
| Installation, alle Einstellungen, Update, Backup, Fehlerbehebung | [docs/installation.md](docs/installation.md) |
| Sicherheit: wer das Panel erreichen darf, Firewall, VPN, `.env` und Backups | [docs/sicherheit.md](docs/sicherheit.md) |
| missa-core anbinden (Funktionen, Ereignisse, Modelle, Profil) | [docs/anbindung-missa-core.md](docs/anbindung-missa-core.md) |
| Eigene Integration schreiben | [docs/eigene-integration.md](docs/eigene-integration.md) |
| Geräte anbinden (ESP32, Raspberry Pi Pico), eigene Firmware | [docs/geraete.md](docs/geraete.md) |
| Telefonie: Einstellungen und eigene Adapter | [docs/telefonie.md](docs/telefonie.md) |

### Übersicht

Die Startseite zeigt alles Eingerichtete als Verbindungsbaum: Missa in der Mitte, darum Clients,
Rollen und Modelle, Integrationen mit ihren Funktionen (aufklappbar), Geräte, Zugänge und Regeln.

| Farbe | Bedeutung |
| --- | --- |
| grün | in Ordnung |
| gelb | Warnung – z. B. eine Freigabe wartet auf deine Entscheidung |
| rot | Fehler – z. B. die Gegenstelle einer Integration ist nicht erreichbar, ein Gerät ist offline |
| grau | deaktiviert oder nicht eingerichtet |

Das Panel prüft die Integrationen alle 20 Sekunden von selbst, die Seite aktualisiert sich alle 30
Sekunden – ein Ausfall ist also innerhalb einer Minute zu sehen, ohne neu zu laden. Ein Klick auf
einen Knoten zeigt Details und den Link zur Bearbeitung, das „+“ führt in den Katalog. Knoten
lassen sich verschieben (die Anordnung bleibt gespeichert), nach Art filtern oder als Liste
anzeigen – auf dem Handy beginnt die Seite mit der Liste.

Ob Missa selbst läuft, zeigt der Knoten in der Mitte, sobald in `.env` die Health-Adresse von
missa-core eingetragen ist (`MISSA_CORE_HEALTH_URL`, optional). Das Panel ruft sie nur lesend ab
(HTTP-GET) und verändert an missa-core nichts; ohne die Einstellung bleibt der Knoten grau.

### Geräte (ESP32, Raspberry Pi Pico)

1. Im Panel **Geräte → Gerät hinzufügen**: Namen eingeben, testen, aktivieren.
2. WLAN-Daten eintragen und die fertige `config.py` (Pico) bzw. `config.h` (ESP32) herunterladen.
3. Die Datei mit der Beispiel-Firmware aus `examples/geraete/` aufs Gerät bringen – es erscheint
   als online.

Das Gerät sagt selbst, was es kann: Sensoren werden zu lesenden Funktionen und Messwerten für
Regeln, Knöpfe zu Ereignissen, Schalter zu Funktionen, die erst nachfragen. Ist ein Gerät weg,
zeigt das Panel es nach spätestens 45 Sekunden als offline.

### Anrufe

Auf der Seite **Anrufe** steht, wer Missa erreichen darf (eigene Nummern, erlaubte Anrufer), wann sie
nicht anrufen soll (Ruhezeiten, ausser dringend) und was bisher geschah (Verlauf). Regeln können
anrufen („Wenn …, dann ruft Missa dich an“), Missa selbst erst nach Freigabe. Noch ist kein echtes
Telefon angeschlossen: Der mitgelieferte Test-Adapter protokolliert Anrufe nur.

### Missa anbinden

Missa Control verändert missa-core nie – missa-core holt sich Funktionen, Ereignisse und
Konfiguration selbst ab. Dafür im Panel unter **Clients** einen Client anlegen und dessen Token in
missa-core eintragen.

## Projektstand

Version: noch keine Veröffentlichung.

Alle Bereiche des Panels sind vorhanden und durch automatische Tests abgedeckt. Was noch **nicht**
gegen die echte Gegenstelle erprobt ist:

| Bereich | Stand |
| --- | --- |
| Anbindung an missa-core | Das Panel stellt alles bereit; das Einbinden in missa-core macht der Besitzer von Hand nach `docs/anbindung-missa-core.md`. |
| Nextcloud-Kalender | gegen einen CalDAV-Testserver geprüft, nicht gegen eine echte Nextcloud |
| Home Assistant | gegen einen Nachbau der Schnittstelle geprüft, nicht gegen ein echtes Home Assistant |
| Geräte | MQTT-Broker und Panel gegen den echten Broker geprüft; die Beispiel-Firmware lief nur am Prüfstand, nicht auf echter Hardware |
| Telefonie | nur Schnittstelle mit Test-Adapter – noch kein echtes Telefon |
| GPU-Werte der Serverlast | ohne GPU nicht geprüft |

Nicht enthalten und nicht geplant: Benutzerverwaltung für mehrere Personen, Veröffentlichung über
einen Reverse Proxy, Telemetrie, Cloud-Dienste. Was sich wann geändert hat: [CHANGELOG](CHANGELOG.md).

## Aufbau des Repos

| Ordner | Inhalt |
| --- | --- |
| `backend/` | FastAPI-App (`backend/src/missa_control/`) und pytest-Tests (`backend/tests/`) |
| `frontend/` | React + TypeScript (Vite), vitest-Tests in `frontend/tests/` |
| `integrations/` | eingebaute Integrationen, je ein Ordner mit `integration.yaml` |
| `examples/geraete/` | Beispiel-Firmware für Geräte (Pico 2 W, ESP32) |
| `scripts/` | `install.sh`, `update.sh`, `backup.sh`, `reset-2fa.sh` |
| `docs/` | Anleitungen |
| `config/` | Beispiel-Charakterprofil (`profil.example.yaml`), Zusatz für GPU-Werte (`compose.gpu.yaml`), Einstellungen des MQTT-Brokers (`mosquitto.conf`) |

## Entwicklung

```bash
# Backend (Python 3.12, uv)
cd backend
uv sync
uv run ruff check .
uv run pytest
```

Die Geräte-Tests starten den echten MQTT-Broker als Test-Container (`missa-control-test-mqtt-…`,
wird danach wieder gestoppt). Ohne Docker werden sie übersprungen.

```bash
# Frontend (Node 22)
cd frontend
npm ci
npm run lint
npm test
npm run build
```

Änderungen laufen immer über einen eigenen Branch und einen Pull Request nach `main`;
Commits folgen [Conventional Commits](https://www.conventionalcommits.org/de/), Texte auf Deutsch.

## Lizenz

[MIT](LICENSE)
