# Missa Control

Lokales Admin- und Integrations-Panel für die selbstgehostete KI-Assistentin **Missa**.

Missa Control läuft neben `missa-core` auf derselben Maschine (ai01), komplett lokal und ohne
Cloud-Dienste. Über das Panel bekommt Missa neue Fähigkeiten – ohne Programmieren und in wenigen
Klicks: MCP-Server, REST-APIs, Geräte, Kalender und mehr.

> **Oberste Regel:** Missa Control verändert `missa-core` nie. Das Panel arbeitet nur mit seinen
> eigenen Containern, Volumes und Netzwerken (Compose-Projekt `missa-control`) und legt alle Daten
> in `./data` ab.

## Projektstand

Version: noch keine Veröffentlichung.

| Bereich | Stand |
| --- | --- |
| Installation per Skript, Login mit Passwort + 2FA | vorhanden |
| Zugänge (API-Keys, Tokens, Passwörter) verschlüsselt verwalten | vorhanden |
| Integrations-Katalog: MCP-Server, REST-APIs (OpenAPI), eigene Python-Integrationen | vorhanden |
| Ein Anschluss für Missa: MCP-Gateway mit Client-Tokens, Freigaben, Protokoll und Ereignissen | vorhanden |
| Modelle verwalten: Rollen „schnell“ und „stark“ mit Ersatzmodell, OpenAI-kompatibler Anschluss | vorhanden |
| Charakterprofil mit Versionsverlauf, YAML-Export/-Import und Test-Chat | vorhanden |
| Serverlast von ai01 (CPU, Arbeitsspeicher, Speicherplatz, GPU) mit Verlauf | vorhanden |
| Gedächtnis: Missa merkt sich Dinge; ansehen, suchen, korrigieren, löschen, Export als JSON | vorhanden |
| Regeln und Alarme mit Zeitplan, Schwellwerten, Ruhezeit und Verlauf – auch von Missa selbst anlegbar | vorhanden |
| Fertige Integrationen: Nextcloud-Kalender (CalDAV), Home Assistant, eingehende Webhooks | vorhanden |
| Geräte (ESP32, Raspberry Pi Pico) per MQTT: koppeln, Werte mit Verlauf, Knöpfe und Schalter | vorhanden |
| Telefonie vorbereitet: erlaubte Anrufer, Ruhezeiten, Anrufe aus Regeln, Verlauf (mit Test-Adapter, noch ohne echtes Telefon) | vorhanden |
| Übersicht als Startseite: grafischer Verbindungsbaum mit Live-Status aller Teile | vorhanden |

## Installation

Voraussetzung: Debian (oder ein anderes Linux) mit Docker und Docker Compose.

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

## Betrieb

| Aufgabe | Befehl |
| --- | --- |
| Aktualisieren (sichert vorher die Daten) | `./scripts/update.sh` |
| Backup von `data/` und `.env` nach `backups/` | `./scripts/backup.sh` |
| Protokoll ansehen | `docker compose -p missa-control logs missa-control` (MQTT-Broker: `… logs mqtt`) |
| Anhalten | `docker compose -p missa-control down` |

Backup wiederherstellen: Panel anhalten, `tar -xzf backups/missa-control-<datum>.tar.gz` im
Repo-Ordner, dann `./scripts/install.sh`. Das Backup enthält die Schlüssel aus `.env` und gehört an
einen sicheren Ort.

Alle Einstellungen stehen kommentiert in [`.env.example`](.env.example).

## Übersicht

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

## Erste Integration in 3 Schritten

1. Im Panel **Katalog** öffnen und eine Karte wählen, z. B. „MCP-Server“.
2. Das Formular ausfüllen (beim MCP-Server nur die URL) und **Verbindung testen**.
3. Rechte prüfen und **Aktivieren**.

Lesende Funktionen sind danach „erlaubt“, schreibende fragen „erst nach“.

Fertige Karten gibt es für MCP-Server, REST-APIs (OpenAPI), Nextcloud-Kalender, Home Assistant,
eingehende Webhooks, Geräte sowie Serverlast, Gedächtnis, Regeln und Telefonie. Eigene Integrationen
mit wenig Code: siehe [docs/eigene-integration.md](docs/eigene-integration.md).

## Geräte anbinden (ESP32, Raspberry Pi Pico)

1. Im Panel **Geräte → Gerät hinzufügen**: Namen eingeben, testen, aktivieren.
2. WLAN-Daten eintragen und die fertige `config.py` (Pico) bzw. `config.h` (ESP32) herunterladen.
3. Die Datei mit der Beispiel-Firmware aus `examples/geraete/` aufs Gerät bringen – es erscheint
   als online.

Das Gerät sagt selbst, was es kann: Sensoren werden zu lesenden Funktionen und Messwerten für
Regeln, Knöpfe zu Ereignissen, Schalter zu Funktionen, die erst nachfragen. Ist ein Gerät weg,
zeigt das Panel es nach spätestens 45 Sekunden als offline. Alles Weitere, auch für eigene
Firmware: [docs/geraete.md](docs/geraete.md).

## Anrufe

Auf der Seite **Anrufe** steht, wer Missa erreichen darf (eigene Nummern, erlaubte Anrufer), wann sie
nicht anrufen soll (Ruhezeiten, ausser dringend) und was bisher geschah (Verlauf). Regeln können
anrufen („Wenn …, dann ruft Missa dich an“), Missa selbst erst nach Freigabe. Noch ist kein echtes
Telefon angeschlossen: Der mitgelieferte Test-Adapter protokolliert Anrufe nur. Wie später ein
echter Adapter dazukommt: [docs/telefonie.md](docs/telefonie.md).

## Missa anbinden

Missa Control verändert missa-core nie – missa-core holt sich Funktionen, Ereignisse und
Konfiguration selbst ab. Dafür im Panel unter **Clients** einen Client anlegen und dessen Token in
missa-core eintragen. Die ganze Anleitung: [docs/anbindung-missa-core.md](docs/anbindung-missa-core.md).

## Aufbau des Repos

| Ordner | Inhalt |
| --- | --- |
| `backend/` | FastAPI-App (`backend/src/missa_control/`) und pytest-Tests (`backend/tests/`) |
| `frontend/` | React + TypeScript (Vite), vitest-Tests in `frontend/tests/` |
| `integrations/` | eingebaute Integrationen, je ein Ordner mit `integration.yaml` |
| `examples/geraete/` | Beispiel-Firmware für Geräte (Pico 2 W, ESP32) |
| `scripts/` | `install.sh`, `update.sh`, `backup.sh` |
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
