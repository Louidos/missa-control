# Entwicklung

Wie man am Panel arbeitet: lokal starten, prüfen, typische Erweiterungen und der Weg vom Branch
bis zum Release. Wie das Panel aufgebaut ist: [architektur.md](architektur.md). Eine eigene
Integration schreiben (ohne das Panel selbst zu ändern): [eigene-integration.md](eigene-integration.md).

## Voraussetzungen

- Python 3.12 und [uv](https://docs.astral.sh/uv/) für das Backend
- Node.js 22 für die Oberfläche
- Docker – nur für die Geräte-Tests (echter MQTT-Broker) und den Image-Bau; ohne Docker werden
  diese Tests übersprungen
- shellcheck für die Scripts (optional, die CI prüft sie sowieso)

## Lokal starten

Backend und Oberfläche laufen getrennt; Vite leitet `/api`, `/mcp` und `/v1` an das Backend
weiter (`frontend/vite.config.ts`).

**1. Schlüssel für die Entwicklung** (einmal, nicht die von ai01 verwenden):

```bash
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

```bash
export ENCRYPTION_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
```

**2. Backend** (Port 8090, nur auf 127.0.0.1):

```bash
cd backend
uv sync
MISSA_CONTROL_DATA_DIR=../data uv run python -m missa_control
```

`../data` ist der Ordner `data/` im Repo – er steht in `.gitignore`. Ohne MQTT-Broker zeigt
die Seite „Geräte“ nur an, was fehlt; mit `MISSA_CONTROL_MQTT_HOST=127.0.0.1` und einem lokalen
Mosquitto funktioniert sie ganz.

**3. Oberfläche** (Port 5173, mit Hot-Reload):

```bash
cd frontend
npm ci
npm run dev
```

Dann <http://localhost:5173> öffnen und wie bei der echten Installation Passwort und 2FA
einrichten.

**Alles wie im Betrieb** (Image bauen und starten): `./scripts/install.sh` im Repo-Ordner.

### Einstellungen nur für Entwicklung und Container

Diese Variablen setzt das `Dockerfile` bzw. `compose.yaml`; von Hand braucht man sie nur ausserhalb
des Containers. Die Einstellungen für den Betrieb stehen in
[installation.md](installation.md#alle-einstellungen-in-env).

| Variable | Standard ausserhalb des Containers | Im Container |
| --- | --- | --- |
| `MISSA_CONTROL_HOST` | `127.0.0.1` | `0.0.0.0` |
| `MISSA_CONTROL_PORT` | `8090` | `8090` |
| `MISSA_CONTROL_DATA_DIR` | `data` (relativ zum aktuellen Ordner) | `/data` |
| `MISSA_CONTROL_FRONTEND_DIR` | leer – Oberfläche kommt vom Vite-Server | `/app/frontend` |
| `MISSA_CONTROL_INTEGRATIONS_DIR` | `integrations/` im Repo | `/app/integrations` |
| `MISSA_CONTROL_CONFIG_DIR` | `config/` im Repo | `/app/config` |
| `MISSA_CONTROL_HOST_PROC`, `MISSA_CONTROL_HOST_SYS` | `/host/proc`, `/host/sys` (fehlen sie, misst das Panel den eigenen Rechner) | `/proc` und `/sys` von ai01, nur lesend |
| `MISSA_CONTROL_MQTT_HOST` | leer (keine Geräte) | `mqtt` |
| `MISSA_CONTROL_MQTT_PORT` | `1883` | `1883` |

## Prüfen

Wie die CI (`.github/workflows/ci.yml`):

```bash
cd backend && uv run ruff check . && uv run pytest
```

```bash
cd frontend && npm run lint && npm test && npm run build
```

```bash
shellcheck -x scripts/*.sh
```

```bash
docker compose -p missa-control build
```

Die CI baut zusätzlich das Image, führt `install.sh` aus und prüft, dass der MQTT-Broker niemanden
ohne Anmeldung hereinlässt.

### Tests, die die Regeln des Projekts absichern

| Test | Prüft |
| --- | --- |
| `test_oberste_regel.py` | Das Panel fasst missa-core und fremde Container nie an |
| `test_migrationen.py` | Migrationen passen genau zu den Tabellen und lassen sich wiederholen |
| `test_doku_beispiel.py` | Das Beispiel aus [eigene-integration.md](eigene-integration.md) funktioniert wirklich – und bleibt kurz |
| `test_manifest_katalog.py`, `test_vorlagen.py` | Alle eingebauten Karten und Vorlagen sind gültig |
| `test_login.py`, `test_reset_2fa.py` | Login, 2FA, Sperre, Notfall-Reset |

Hilfen für eigene Tests: `backend/tests/conftest.py` (App mit eigener Datenbank im temporären
Ordner, `TestClient` und eine stellbare Uhr),
`hilfen.py`, ein kleiner Test-Server (`server.py`) und ein Pico-Nachbau (`pico.py`,
`micropython/`). Die Oberfläche testet mit Vitest und Testing Library (`frontend/tests/`,
gemeinsame Hilfen in `hilfen.tsx`).

## Typische Erweiterungen

### Neue Seite oder neuer Bereich im Backend

1. Paket unter `backend/src/missa_control/<bereich>/` mit `modelle.py` (Tabellen),
   `dienst.py` (Logik) und `routen.py` (HTTP) – siehe [architektur.md](architektur.md#backend).
2. Tabellen in `missa_control/modelle.py` importieren, damit Migrationen und Tests sie kennen.
3. Migration anlegen (siehe unten).
4. Dienst in `create_app()` (`main.py`) als `app.state.<bereich>` bauen und den Router mit
   `app.include_router(...)` einbinden. Neue Pfade unter `/api/` sind automatisch nur für die
   Admin-Sitzung offen; ein Anschluss für Clients muss in `auth/schutz.py` ausdrücklich eingetragen
   werden.
5. Fällt etwas an, das Missa wissen soll: über den Ereignis-Dienst ein Ereignis erzeugen. Muss
   Louis es auch unterwegs sehen: über den Meldungs-Dienst.
6. Alte Daten in `alte_daten_loeschen()` (`main.py`) mit aufräumen.
7. Seite in `frontend/src/<bereich>/`, Eintrag in `frontend/src/layout/navigation.ts`, Tests in
   `frontend/tests/`.
8. Soll der Bereich in der Sicherung landen: `sicherung/dienst.py` ergänzen.
9. Doku: README (Abschnitt „Was es kann“), passende Seite unter `docs/`, [api-referenz.md](api-referenz.md).

### Migration

Die Migrationen werden von Hand geschrieben und fortlaufend nummeriert:

```python
"""Kurz, was dazukommt

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(...)
```

Datei: `backend/src/missa_control/migrations/versions/0017_<name>.py`. Bestehende Daten müssen
erhalten bleiben – ein Update auf ai01 läuft mit echten Daten. `test_migrationen.py` meldet, wenn
Migration und Tabellen-Definition nicht zusammenpassen.

### Neue eingebaute Integration oder Vorlage

Ordner unter `integrations/<id>/` mit `integration.yaml` und bei Bedarf `main.py` – genau wie
eine eigene Integration ([eigene-integration.md](eigene-integration.md)), nur im Repo statt in
`data/integrations/`. Eine Vorlage für eine REST-API braucht nur das Manifest (`art: api` mit
`basis_url` und `endpunkte`). Danach in der Tabelle der Vorlagen im README eintragen.

### Neuer Adapter-Typ

Eine neue **Art** von Integration (neben `api`, `mcp`, `openapi`, `python`, `webhook`, `geraet`)
braucht einen Adapter in `integrationen/adapter/` nach dem Protokoll `Adapter` in
`adapter/__init__.py` und einen Eintrag in `Art`/`ART_NAMEN` in `integrationen/manifest.py`.

## Arbeitsweise im Repo

- **Oberste Regel:** missa-core wird nie verändert. Das Panel arbeitet nur mit dem
  Compose-Projekt `missa-control`, seinen Volumes und Netzwerken und mit `./data`.
- **Branch pro Änderung**, Pull Request nach `main` mit der Vorlage
  (`.github/pull_request_template.md`). Issues über die Vorlagen „Fehler“ und „Wunsch“.
- **Commits** nach [Conventional Commits](https://www.conventionalcommits.org/de/), Texte auf
  Deutsch (`feat: …`, `fix: …`, `docs: …`, `chore: …`).
- **CHANGELOG.md** unter „Unveröffentlicht“ ergänzen, mit Issue-Nummer.
- **Release:** Abschnitt „Unveröffentlicht“ in `## [X.Y.Z] - JJJJ-MM-TT` umbenennen, Version in
  `backend/pyproject.toml` **und** `frontend/package.json` anheben, Projektstand im README
  anpassen, Tag `vX.Y.Z` pushen. Der Workflow `release.yml` prüft, dass beide Versionen zum Tag
  passen, und legt das GitHub-Release mit dem Text aus dem CHANGELOG an. Tags werden nie verschoben
  oder gelöscht. `scripts/update.sh` auf ai01 holt den neuesten Stand von `main` (`git pull --ff-only`)
  und baut das Image neu.
