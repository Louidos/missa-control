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
| Regeln, Geräte, Anrufe, Verbindungsbaum | in Arbeit – im Panel als Platzhalter sichtbar (siehe [CHANGELOG](CHANGELOG.md)) |

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

Das Skript prüft Docker und den Port, erzeugt `.env` mit zufälligen Schlüsseln, legt `data/` an,
startet das Panel und gibt am Ende die Adresse aus (Standard: `http://<adresse-von-ai01>:8090`).

- Es kann beliebig oft ausgeführt werden: Eine vorhandene `.env` und vorhandene Daten bleiben unverändert.
- Ist der Port belegt, bricht es mit einer Meldung ab – es stoppt nie etwas Fremdes.
  Anderen Port wählen: in `.env` bei `MISSA_CONTROL_BIND` eintragen, Skript erneut starten.

**Erster Aufruf:** Passwort setzen (mindestens 10 Zeichen), QR-Code mit einer Authenticator-App
scannen, Code bestätigen. Danach ist das Panel nur noch mit Passwort **und** Code erreichbar.
Bitte gleich nach der Installation erledigen – bis dahin kann jeder im Netz das Panel einrichten.

## Betrieb

| Aufgabe | Befehl |
| --- | --- |
| Aktualisieren (sichert vorher die Daten) | `./scripts/update.sh` |
| Backup von `data/` und `.env` nach `backups/` | `./scripts/backup.sh` |
| Protokoll ansehen | `docker compose -p missa-control logs missa-control` |
| Anhalten | `docker compose -p missa-control down` |

Backup wiederherstellen: Panel anhalten, `tar -xzf backups/missa-control-<datum>.tar.gz` im
Repo-Ordner, dann `./scripts/install.sh`. Das Backup enthält die Schlüssel aus `.env` und gehört an
einen sicheren Ort.

Alle Einstellungen stehen kommentiert in [`.env.example`](.env.example).

## Erste Integration in 3 Schritten

1. Im Panel **Katalog** öffnen und eine Karte wählen, z. B. „MCP-Server“.
2. Das Formular ausfüllen (beim MCP-Server nur die URL) und **Verbindung testen**.
3. Rechte prüfen und **Aktivieren**.

Lesende Funktionen sind danach „erlaubt“, schreibende fragen „erst nach“. Eigene Integrationen mit
wenig Code: siehe [docs/eigene-integration.md](docs/eigene-integration.md).

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
| `config/` | Beispiel-Charakterprofil (`profil.example.yaml`), Zusatz für GPU-Werte (`compose.gpu.yaml`) |

## Entwicklung

```bash
# Backend (Python 3.12, uv)
cd backend
uv sync
uv run ruff check .
uv run pytest
```

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
