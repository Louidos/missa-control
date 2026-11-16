# Architektur

Wie Missa Control aufgebaut ist: Container, Backend, Oberfläche, Daten und wie das Panel mit
missa-core zusammenarbeitet. Die Bedienung steht im [README](../README.md) und in den übrigen
Anleitungen; wie man selbst etwas ergänzt, in [entwicklung.md](entwicklung.md).

## Im Gesamtbild

Missa besteht aus drei Repos:

| Repo | Aufgabe |
| --- | --- |
| [Missa-Core](https://github.com/Louidos/Missa-Core) | Missa selbst: Charakter, Gedächtnis, Werkzeuge, Zeitplaner, Kanäle, OpenAI-kompatible API |
| **missa-control** (dieses Repo) | Admin-Panel: Integrationen, Freigaben, Regeln, Geräte, Modelle – stellt Missa zusätzliche Funktionen bereit |
| [missa-chat](https://github.com/Louidos/missa-chat) | Chat-App (PWA) für Browser und Handy |

Die Richtung ist immer dieselbe: **missa-core holt sich etwas vom Panel ab** – Funktionen,
Ereignisse, Konfiguration. Das Panel schreibt nie in missa-core hinein (oberste Regel). Es fragt
höchstens lesend dessen `/health` ab, wenn `MISSA_CORE_HEALTH_URL` gesetzt ist.

```text
 Admin-Browser ──(Passwort + 2FA, Cookie)──► Panel-Oberfläche + /api/…
                                                     │
                       ┌─────────────── Missa Control (ai01:8090) ───────────────┐
                       │  Zugriffsschutz → FastAPI-Routen → Dienste → SQLite      │
                       │       │                                                  │
                       │       ├─ /mcp        MCP-Gateway (Funktionen + Freigaben)│
 missa-core ──Token──► │       ├─ /api/events Ereignisse (Stream oder Abruf)      │
                       │       ├─ /api/config Profil, aktive Integrationen        │
                       │       └─ /v1/…       Modell-Anschluss (Rollen → Modelle) │
                       └────┬──────────────┬──────────────┬──────────────┬────────┘
                            ▼              ▼              ▼              ▼
                    fremde APIs,     MQTT-Broker      ntfy / Webhook   /proc, /sys
                    MCP-Server,      (Geräte: ESP32,  (Meldungen)      von ai01 (nur lesen,
                    Nextcloud, HA    Pico)                             Serverlast)
```

## Container

Alles läuft im Compose-Projekt `missa-control` (`compose.yaml`), mit eigenem Netzwerk
`missa-control-net` und ohne Docker-Socket.

| Dienst | Image | Aufgabe | Port (Standard) |
| --- | --- | --- | --- |
| `missa-control` | `missa-control:lokal` (aus `Dockerfile`) | Backend und gebaute Oberfläche in einem Container | `MISSA_CONTROL_BIND` → 8090 |
| `mqtt` | `eclipse-mosquitto:2` | MQTT-Broker für Geräte, nur im Profil `geraete` | `MQTT_BIND` → 1883 |

Härtung: beide Container laufen als eigener Benutzer (nie root), mit schreibgeschütztem
Dateisystem (`read_only`, nur `/tmp` als tmpfs), ohne Linux-Capabilities und mit
`no-new-privileges`. Schreibbar ist nur `./data`. Für die Serverlast sind `/proc` und `/sys`
von ai01 nur lesend eingebunden.

Das `Dockerfile` baut in drei Stufen: Oberfläche (Node 22, `npm run build`), Python-Umgebung
(Python 3.12, uv, `uv.lock`) und die schlanke Laufzeit. Es kopiert bewusst nur einzelne Ordner,
damit `.env`, `data/` oder `node_modules` nie im Image landen.

## Backend

FastAPI-App in `backend/src/missa_control/`. Jeder Bereich ist ein eigenes Paket mit demselben
Aufbau:

| Datei | Inhalt |
| --- | --- |
| `modelle.py` | die Tabellen (SQLAlchemy) |
| `dienst.py` | die eigentliche Logik – ohne HTTP, gut testbar |
| `routen.py` | die HTTP-Routen mit ihren Ein- und Ausgabe-Modellen (Pydantic); rufen nur den Dienst auf |

| Paket | Aufgabe |
| --- | --- |
| `auth` | ein einziger Admin: Passwort + TOTP (2FA), Sitzungen, Sperre nach Fehlversuchen; `schutz.py` ist der Zugriffsschutz für alles |
| `zugaenge` | API-Keys, Tokens, Passwörter – mit `ENCRYPTION_KEY` verschlüsselt, nur maskiert angezeigt |
| `integrationen` | Katalog, eingerichtete Integrationen, Funktionen und Rechte; `adapter/` mit je einem Adapter pro Art (`api`, `mcp`, `openapi`, `python`, `webhook`, `geraet`), `manifest.py` liest `integration.yaml` |
| `gateway` | MCP-Gateway unter `/mcp` (`server.py`), Freigaben (`freigaben.py`) und Protokoll aller Aufrufe (`protokoll.py`) |
| `clients` | wer die Anschlüsse nutzen darf (z. B. missa-core), je mit eigenem Token |
| `ereignisse` | Ereignisse speichern und an Clients verteilen (Server-Sent Events oder Abruf) |
| `modellverwaltung` | Modell-Endpunkte, Rollen „schnell“/„stark“ mit Ersatzmodell, OpenAI-kompatibler Anschluss unter `/v1` |
| `profil` | Missas Charakterprofil mit Versionen, YAML-Export und Test-Chat |
| `gedaechtnis` | Gedächtnis-Einträge mit Volltextsuche (SQLite FTS5) |
| `regeln` | Regeln „Wenn … dann …“: Auslöser beobachten, Bedingung prüfen, Aktion ausführen, Verlauf |
| `geraete` | ESP32/Pico über MQTT (`mqtt.py`): koppeln, Fähigkeiten, Messwerte, Befehle |
| `telefonie` | austauschbarer Telefon-Adapter, erlaubte Anrufer, Ruhezeiten, Anrufverlauf |
| `serverlast` | CPU, RAM, Speicher, GPU von ai01 alle 30 s messen, 7 Tage aufbewahren |
| `status` | die Übersicht: alles als Knoten und Kanten mit Status |
| `statistik` | Nutzung pro Funktion, berechnet aus dem Protokoll |
| `sicherung` | die Einrichtung als eine Datei exportieren und wieder einspielen |
| `meldungen` | Nachrichten an ntfy oder einen Webhook (Freigabe wartet, Ausfall), mit Schutz vor Flut |

Dazu im Paket selbst: `main.py` (baut die App), `config.py` (Einstellungen aus der Umgebung),
`db.py` (SQLite + Alembic), `krypto.py` (Verschlüsselung, Token-Prüfsummen), `fehler.py`
(einheitliche Fehlermeldungen mit Lösungshinweis), `sdk.py` (Hilfen für eigene Integrationen),
`zeit.py` (alles in UTC), `cli.py` (Befehle für die Scripts) und `migrations/`.

### Zwei getrennte Wege hinein

Der Zugriffsschutz (`auth/schutz.py`) läuft als Middleware vor allen Routen. Grundsatz: Alles
unter `/api/`, `/mcp` und `/v1/` ist gesperrt, solange es nicht ausdrücklich freigegeben ist –
neue Routen sind also automatisch geschützt.

| Weg | Wer | Womit | Pfade |
| --- | --- | --- | --- |
| Panel | der Admin im Browser | Sitzungs-Cookie nach Passwort + 2FA; schreibende Anfragen nur von derselben Herkunft | alle übrigen `/api/…` |
| Anschlüsse | Clients wie missa-core, Telefon-Adapter | `Authorization: Bearer <Client-Token>` | `/mcp`, `/v1/…`, `/api/events…`, `/api/config/…`, `/api/telefonie/adapter/…` |
| Webhooks | fremde Dienste und Geräte | zufälliger Schlüssel in der Adresse | `/api/webhook/<schlüssel>` (nimmt nur entgegen) |
| offen | jeder | – | `/api/health`, Login-Schritte unter `/api/auth/…`, die Oberfläche selbst (enthält keine Daten) |

Eine Admin-Sitzung öffnet die Anschlüsse nicht – und ein Client-Token nicht das Panel.
Alle Antworten tragen strenge Sicherheits-Header (u. a. Content-Security-Policy, `X-Frame-Options: DENY`).

### Das MCP-Gateway

`/mcp` bündelt die Funktionen **aller aktiven Integrationen** zu einem einzigen MCP-Server
(Streamable HTTP):

- Funktionsnamen tragen die Vorsilbe der Integration (z. B. `kalender_termine_anzeigen`).
- Jede Funktion hat ein Recht: **erlaubt**, **erst nachfragen** oder **gesperrt** (unsichtbar).
  Die Zugriffsstufe der Integration („Nur lesen“, „Schreiben erst nachfragen“, „Voller
  Zugriff“) setzt diese Rechte mit einem Klick.
- „Erst nachfragen“ hält den Aufruf an, bis im Panel unter **Freigaben** entschieden ist;
  wartet eine Freigabe, gibt es ein Ereignis und auf Wunsch eine Meldung.
- Zugänge (Keys, Passwörter) setzt das Panel beim Aufruf ein – der Client sieht sie nie.
- Jeder Aufruf landet im Protokoll; daraus rechnet die Statistik.

Wie missa-core das Gateway, die Ereignisse und die Konfiguration nutzt:
[anbindung-missa-core.md](anbindung-missa-core.md).

### Was im Hintergrund läuft

Solange das Panel läuft (Lifespan in `main.py`):

| Aufgabe | Takt |
| --- | --- |
| Integrationen und missa-core prüfen (Status der Übersicht) | alle 20 s |
| Serverlast messen | alle 30 s |
| Regeln auswerten | laufend |
| Geräte: Verbindung zum MQTT-Broker (eigener Thread) | laufend |
| Aufräumen: Protokoll, Ereignisse, entschiedene Freigaben, Regel-Verlauf, Anrufe nach 30 Tagen; Messwerte und Modell-Statistik nach 7 Tagen | stündlich |

## Integrationen

Eingebaute Integrationen liegen in `integrations/`, je ein Ordner mit `integration.yaml`
(Manifest) und bei Bedarf `main.py`. Selbst geschriebene oder hochgeladene kommen nach
`data/integrations/`. Der Katalog liest beide Orte.

| Art (`art:`) | Beispiel | Funktionen kommen aus |
| --- | --- | --- |
| `api` | „API hinzufügen“, Wetter, ÖV-Fahrplan, ntfy, SearXNG | OpenAPI-Beschreibung der API, festen `endpunkte` im Manifest oder `…_abrufen`/`…_senden` |
| `mcp` | MCP-Server | dem MCP-Server selbst |
| `openapi` | REST-API | hochgeladener OpenAPI-Datei |
| `python` | Nextcloud-Kalender, Home Assistant, Gedächtnis, Regeln, Serverlast, Telefonie | `main.py` (mit `sdk.py`) |
| `webhook` | eingehender Webhook | – (erzeugt Ereignisse) |
| `geraet` | ESP32, Pico | dem, was das Gerät über MQTT meldet |

Felder des Manifests und ein vollständiges Beispiel: [eigene-integration.md](eigene-integration.md).

## Oberfläche

React 19 + TypeScript mit Vite in `frontend/`. Daten holt sie mit TanStack Query über
`src/api.ts` (gleiche Herkunft, Cookie; jeder Fehler als `ApiFehler` mit verständlicher
Meldung). Der Verbindungsbaum der Übersicht nutzt React Flow (`@xyflow/react`) mit
dagre-Layout.

| Ordner in `frontend/src/` | Seite |
| --- | --- |
| `uebersicht/` | Übersicht (Verbindungsbaum) |
| `integrationen/` | Katalog, Integrationen, Einrichtungs-Assistent, Rechte |
| `gateway/` | Freigaben, Protokoll, Clients, „Missa-Core verbinden“ |
| `zugaenge/`, `modelle/`, `charakter/`, `gedaechtnis/`, `regeln/`, `geraete/`, `anrufe/` | die gleichnamigen Seiten |
| `serverlast/`, `statistik/`, `sicherung/`, `meldungen/` | die gleichnamigen Seiten |
| `auth/` | Einrichtung (Passwort, QR-Code) und Anmeldung |
| `layout/` | Rahmen und Navigation (`navigation.ts` – eine Seite ohne Komponente erscheint als Platzhalter) |
| `ui/` | gemeinsame Bausteine (Dialog, Kopierfeld, Formatierung) |

Im Container liefert das Backend die gebaute Oberfläche aus; unbekannte Pfade bekommen
`index.html` (Single-Page-App).

## Daten

Alles liegt in `data/` (im Container `/data`):

| Was | Wo |
| --- | --- |
| Datenbank | `data/missa-control.db` (SQLite) |
| eigene und hochgeladene Integrationen | `data/integrations/` |
| MQTT-Broker (Benutzer der Geräte, Zustand) | `data/mosquitto/` |
| Schlüssel | `.env` (`SECRET_KEY`, `ENCRYPTION_KEY`) – gehört in jedes Backup |

Das Schema wird mit **Alembic** verwaltet; `Datenbank.migrieren()` bringt es bei jedem Start
auf den neuesten Stand. Die Migrationen sind fortlaufend nummeriert
(`migrations/versions/0001_login.py` … `0016_meldungen.py`).

| Tabelle | Paket |
| --- | --- |
| `admin`, `sitzungen` | `auth` |
| `zugaenge` | `zugaenge` |
| `integrationen`, `funktionen` | `integrationen` |
| `freigaben`, `aufrufe` | `gateway` (Freigaben und Protokoll) |
| `clients` | `clients` |
| `ereignisse` | `ereignisse` |
| `modelle`, `modell_rollen`, `modell_anfragen` | `modellverwaltung` |
| `profil_versionen` | `profil` |
| `gedaechtnis` (+ FTS5-Index) | `gedaechtnis` |
| `regeln`, `regel_ausloesungen` | `regeln` |
| `geraete`, `geraete_werte` | `geraete` |
| `telefonie_einstellungen`, `anrufe` | `telefonie` |
| `messwerte` | `serverlast` |
| `meldeziele` | `meldungen` |
| `uebersicht_positionen` | `status` (Anordnung der Knoten) |

Alle Zeiten werden in UTC gespeichert (`zeit.py`); die Zeitzone `MISSA_CONTROL_ZEITZONE` gilt
nur für Uhrzeiten in Regeln und Ruhezeiten.
