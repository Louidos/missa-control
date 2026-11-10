# Installation und Betrieb

Diese Anleitung setzt kein Vorwissen über Missa Control voraus. Sie gilt für ai01 (Debian) und jedes
andere Linux mit Docker.

## Voraussetzungen

| Was | Wozu |
| --- | --- |
| Linux mit **Docker** und dem Plugin **Docker Compose** (`docker compose version` muss antworten) | Das Panel läuft als Container. |
| **git** | zum Holen und Aktualisieren |
| Ein Benutzer, der Docker verwenden darf (Gruppe `docker`) – oder `sudo` | `install.sh` richtet daran selbst nichts ein. |
| Freie Ports **8090** (Panel) und **1883** (MQTT-Broker für Geräte) | Beide lassen sich in `.env` ändern. |
| Internet beim Installieren und Aktualisieren | Docker lädt Grundlagen-Images und Pakete. Im Betrieb braucht das Panel kein Internet. |

Docker fehlt noch? Anleitung: <https://docs.docker.com/engine/install/debian/>

## Installation in 3 Befehlen

```bash
git clone https://github.com/Louidos/missa-control.git
```

```bash
cd missa-control
```

```bash
./scripts/install.sh
```

Am Ende steht die Adresse des Panels, z. B. `http://192.168.1.10:8090`.

**Erster Aufruf – bitte gleich erledigen:** Passwort setzen (mindestens 10 Zeichen), den QR-Code mit
einer Authenticator-App scannen (z. B. Aegis, 2FAS, Google Authenticator) und den Code bestätigen.
Bis dahin kann jeder, der das Panel im Netz erreicht, es einrichten. Danach geht nichts mehr ohne
Passwort **und** Code.

Danach: [Sicherheit](sicherheit.md) lesen – vor allem, wer den Port 8090 erreichen darf.

## Was `install.sh` tut – und was nicht

Das Skript lässt sich beliebig oft ausführen. Der Reihe nach:

1. **Docker prüfen.** Fehlt Docker oder darf der Benutzer es nicht verwenden, bricht es mit einem
   Hinweis ab.
2. **Einstellungen (`.env`).** Gibt es die Datei noch nicht, entsteht sie aus `.env.example` – mit
   zufälligen Schlüsseln, der Benutzer-Nummer für den Container und der Zeitzone von ai01. Eine
   vorhandene `.env` bleibt immer unverändert.
3. **Ports prüfen.** Ist 8090 oder 1883 belegt, bricht das Skript ab und sagt, wie sich der Port
   ändern lässt. Es stoppt nie etwas, das dort schon läuft.
4. **Datenordner anlegen.** `data/` (und `data/mosquitto/` für den MQTT-Broker). Vorhandene Daten
   bleiben erhalten.
5. **Bauen und starten** – nur das eigene Compose-Projekt `missa-control` mit den Diensten
   `missa-control` (Panel) und `mqtt` (Broker für Geräte).
6. **Warten, bis das Panel antwortet,** und die Adresse ausgeben.

Was das Skript nie tut: etwas ausserhalb des Repo-Ordners ändern, fremde Container, Volumes oder
Netzwerke anfassen, Systemdienste, Firewall oder Reverse Proxy ändern, den Docker-Socket verwenden –
und `missa-core` berührt es in keiner Form. Dasselbe gilt für alle Skripte in `scripts/`.

## Alle Einstellungen in `.env`

Nach einer Änderung: `./scripts/install.sh` ausführen – das startet das Panel mit den neuen Werten.

| Einstellung | Standard | Bedeutung |
| --- | --- | --- |
| `MISSA_CONTROL_BIND` | `0.0.0.0:8090` | Adresse und Port des Panels. Nur von ai01 selbst erreichbar: `127.0.0.1:8090`. Nur an einer Netzwerkkarte: `<Adresse-von-ai01>:8090`. |
| `MQTT_BIND` | `0.0.0.0:1883` | Adresse und Port des MQTT-Brokers für Geräte. Das Panel schreibt den Port in die Konfiguration der Geräte. |
| `COMPOSE_PROFILES` | `geraete` | Schaltet den MQTT-Broker ein. Leer (`COMPOSE_PROFILES=`): ohne Broker, die Seite „Geräte“ sagt dann, was fehlt. |
| `SECRET_KEY` | zufällig | Schützt Anmeldungen und Tokens. Wird er geändert, sind alle Anmeldungen und Client-Tokens ungültig. |
| `ENCRYPTION_KEY` | zufällig | Verschlüsselt die gespeicherten Zugänge. Geht er verloren, sind sie nicht mehr lesbar – deshalb gehört `.env` in jedes Backup. |
| `MISSA_CONTROL_UID`, `MISSA_CONTROL_GID` | dein Benutzer | Unter diesem Benutzer laufen die Container (nie als root). `data/` muss ihm gehören. |
| `MISSA_CONTROL_ZEITZONE` | von ai01, sonst `Europe/Zurich` | Für Uhrzeiten in Regeln und Ruhezeiten. |
| `MISSA_CORE_HEALTH_URL` | leer | Optional: Health-Adresse von missa-core, z. B. `http://host.docker.internal:8000/health`. Das Panel ruft sie nur lesend ab (HTTP-GET) und zeigt in der Übersicht, ob Missa läuft. Nicht `127.0.0.1` – das Panel läuft in einem eigenen Container. |
| `MISSA_CONTROL_COOKIE_SECURE` | `auto` | `auto`, `ja` oder `nein`: Anmelde-Cookie nur über HTTPS senden. `auto` passt in aller Regel. |
| `COMPOSE_FILE` | leer | Für Server mit NVIDIA-GPU: `compose.yaml:config/compose.gpu.yaml` zeigt GPU-Werte auf der Seite „Serverlast“ (braucht das NVIDIA Container Toolkit). |

Die Datei `.env.example` enthält dieselben Einstellungen mit Kommentaren.

## Aktualisieren

```bash
./scripts/update.sh
```

Sichert zuerst die Daten nach `backups/`, holt die neue Version (`git pull`) und übergibt dann an
`install.sh`. Ohne Sicherung: `./scripts/update.sh --ohne-backup`. Was sich geändert hat, steht im
[CHANGELOG](../CHANGELOG.md).

## Sichern und wiederherstellen

```bash
./scripts/backup.sh
```

Schreibt `backups/missa-control-<datum>.tar.gz` mit `data/` (Datenbank, Daten des MQTT-Brokers,
eigene Integrationen) und `.env` (den Schlüsseln). Die Datei gehört an einen sicheren Ort ausserhalb
von ai01 – wer sie hat, hat alle gespeicherten Zugänge.

Wiederherstellen (auch auf einem neuen Server):

```bash
docker compose -p missa-control down
```

```bash
tar -xzf backups/missa-control-<datum>.tar.gz
```

```bash
./scripts/install.sh
```

## Alltag

| Aufgabe | Befehl |
| --- | --- |
| Läuft alles? | `docker compose -p missa-control ps` |
| Protokoll des Panels | `docker compose -p missa-control logs missa-control` |
| Protokoll des MQTT-Brokers | `docker compose -p missa-control logs mqtt` |
| Anhalten | `docker compose -p missa-control down` |
| Wieder starten | `./scripts/install.sh` |
| Entfernen | `docker compose -p missa-control down` (Container und Netzwerk), `docker image rm missa-control:lokal` (das selbst gebaute Image) – danach den Repo-Ordner löschen. Alle Daten liegen in `data/`. |

Alle Befehle betreffen nur das Projekt `missa-control`.

## Notfall: Authenticator-App verloren

Ohne Code kommt niemand ins Panel – auch du nicht. Wer Zugriff auf ai01 hat, setzt die
Zwei-Faktor-Anmeldung zurück:

```bash
./scripts/reset-2fa.sh
```

- Alle Anmeldungen am Panel enden sofort.
- Beim nächsten Aufruf fragt das Panel nach dem **bisherigen Passwort** und zeigt einen neuen
  QR-Code. Wer das Passwort nicht kennt, kommt weiterhin nicht hinein.
- Alle Daten bleiben: Integrationen, Zugänge, Regeln, Geräte, Verlauf.

Ist auch das Passwort verloren:

```bash
./scripts/reset-2fa.sh --auch-passwort
```

Dann beginnt die Einrichtung von vorn wie nach der Installation – bitte sofort erledigen, denn bis
dahin kann jeder im Netz das Panel einrichten. Das Skript betrifft nur Missa Control; missa-core und
andere Container bleiben unberührt.

## Fehlerbehebung

| Meldung oder Beobachtung | Ursache und Lösung |
| --- | --- |
| „Docker ist nicht installiert“ / „Docker Compose fehlt“ | Docker nach der Anleitung oben installieren. |
| „Docker läuft nicht oder dieser Benutzer darf Docker nicht verwenden“ | Skript mit `sudo` starten oder den Benutzer in die Gruppe `docker` aufnehmen. |
| „Port 8090 ist bereits belegt“ | Dort läuft schon etwas. In `.env` z. B. `MISSA_CONTROL_BIND=0.0.0.0:8091` eintragen und `install.sh` erneut starten. |
| „Port 1883 ist bereits belegt“ | Auf ai01 läuft schon ein MQTT-Broker. In `.env` z. B. `MQTT_BIND=0.0.0.0:1884` eintragen – oder den eigenen Broker mit `COMPOSE_PROFILES=` abschalten. |
| „Der Ordner data/ gehört nicht dem Benutzer …“ | Den Befehl aus der Meldung ausführen (`sudo chown -R … data`). |
| „Das Panel antwortet nicht“ | `docker compose -p missa-control logs missa-control` zeigt den Grund – meist eine ungültige Einstellung in `.env`, die dort beim Namen genannt wird. |
| Der Bau bricht beim Herunterladen ab | ai01 braucht beim Installieren Internet (Docker Hub, Paketquellen). Später erneut versuchen. |
| „Passwort oder Code falsch“, obwohl beides stimmt | Die Uhr von Handy oder ai01 geht falsch – der Code hängt an der Uhrzeit. Nach 5 Fehlversuchen ist die Anmeldung 15 Minuten gesperrt. |
| Handy weg, kein Code mehr | Siehe „Notfall“ oben. |
| Ein Zugang lässt sich nicht mehr lesen („Wurde ENCRYPTION_KEY in der .env geändert?“) | `ENCRYPTION_KEY` in `.env` wurde geändert oder fehlt. Die alte `.env` aus dem Backup zurückholen – sonst die Zugänge neu eintragen. |
| Seite „Geräte“: Broker nicht erreichbar | `docker compose -p missa-control ps` – läuft `mqtt`? Sonst `./scripts/install.sh`. Mehr dazu: [geraete.md](geraete.md). |
| Knoten „Missa“ in der Übersicht ist rot | Die Health-Adresse antwortet nicht. Vom Panel aus ist `127.0.0.1` der eigene Container – `host.docker.internal` oder die Adresse von ai01 verwenden. missa-core muss seinen Port auf ai01 veröffentlichen. |
| Keine GPU-Werte | Nur mit NVIDIA-GPU, NVIDIA Container Toolkit und `COMPOSE_FILE=compose.yaml:config/compose.gpu.yaml` in `.env`. |
| Regeln lösen zur falschen Uhrzeit aus | `MISSA_CONTROL_ZEITZONE` in `.env` prüfen. |
