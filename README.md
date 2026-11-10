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
| Repo-Struktur, CI, Docker-Grundgerüst | vorhanden |
| Panel mit Login, Integrationen, Gateway, … | in Arbeit (siehe [CHANGELOG](CHANGELOG.md)) |

## Installation

Voraussetzung: Docker mit Docker Compose.

```bash
git clone https://github.com/Louidos/missa-control.git
cd missa-control
docker compose -p missa-control up -d --build
```

Danach antwortet das Grundgerüst unter `http://<adresse-von-ai01>:8090/api/health`.
Das Installationsskript `scripts/install.sh` folgt mit dem Panel selbst.

## Aufbau des Repos

| Ordner | Inhalt |
| --- | --- |
| `backend/` | FastAPI-App (`backend/src/missa_control/`) und pytest-Tests (`backend/tests/`) |
| `frontend/` | React + TypeScript (Vite), vitest-Tests in `frontend/tests/` |
| `integrations/` | eingebaute Integrationen, je ein Ordner mit `integration.yaml` |
| `examples/geraete/` | Beispiel-Firmware für Geräte (Pico 2 W, ESP32) |
| `scripts/` | Installation, Update, Backup |
| `docs/` | Anleitungen |
| `config/` | Beispiel-Konfiguration |

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
