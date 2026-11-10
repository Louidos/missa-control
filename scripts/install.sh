#!/usr/bin/env bash
# Installiert und startet Missa Control. Kann beliebig oft ausgeführt werden:
# eine vorhandene .env und vorhandene Daten werden nie überschrieben.
#
# Das Skript arbeitet nur im Repo-Ordner und nur mit dem Compose-Projekt "missa-control".
# Es stoppt, ändert oder löscht nichts Fremdes – ist ein Port belegt, bricht es ab.
set -euo pipefail

# shellcheck source=scripts/_gemeinsam.sh
source "$(dirname "${BASH_SOURCE[0]}")/_gemeinsam.sh"
in_repo_ordner

zufall() { head -c "$1" /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'; }

# Gibt die Zeitzone von ai01 aus (nur gelesen, nichts wird verändert). Steht der Server auf UTC
# oder ist nichts eingestellt, gibt es keine Ausgabe – dann bleibt der Standard aus .env.example.
zeitzone_des_servers() {
  local zone=""
  if [ -r /etc/timezone ]; then zone="$(head -n 1 /etc/timezone | tr -d '[:space:]')"; fi
  if [ -z "$zone" ] && [ -L /etc/localtime ]; then
    zone="$(readlink /etc/localtime | sed -n 's|^.*/zoneinfo/||p')"
  fi
  case "$zone" in "" | UTC | Etc/UTC | Etc/GMT | GMT | Universal | Zulu) return 0 ;; esac
  [[ "$zone" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ ]] || return 0
  printf '%s' "$zone"
}

# Prüft, ob auf Adresse $1 und Port $2 schon etwas lauscht.
port_belegt() {
  local ip="$1" port="$2" zeilen ziel
  if command -v ss >/dev/null 2>&1; then
    zeilen="$(ss -Hltn "sport = :$port" 2>/dev/null || true)"
    [ -n "$zeilen" ] || return 1
    case "$ip" in
      0.0.0.0 | "::" | "*" | "") return 0 ;;
    esac
    # Belegt, wenn der andere Dienst auf allen Adressen oder genau auf unserer lauscht.
    printf '%s\n' "$zeilen" | awk '{print $4}' \
      | grep -Eq "^(0\.0\.0\.0|\*|\[::\]|${ip//./\\.}):${port}\$"
    return $?
  fi
  ziel="$ip"
  case "$ip" in 0.0.0.0 | "") ziel="127.0.0.1" ;; esac
  (exec 3<>"/dev/tcp/$ziel/$port") 2>/dev/null
}

# Bricht ab, wenn der gewünschte Port belegt ist – ausser Missa Control selbst nutzt ihn bereits.
# $1 = Dienst, $2 = Port im Container, $3 = Name der Einstellung, $4 = Standardwert
port_pruefen() {
  local dienst="$1" intern="$2" name="$3" bind ip port laufend
  bind="$(wert_aus_env "$name" "$4")"
  if [[ "$bind" == *:* ]]; then ip="${bind%:*}"; port="${bind##*:}"; else ip="0.0.0.0"; port="$bind"; fi
  [[ "$port" =~ ^[0-9]+$ ]] || fehler "$name=$bind ist ungültig." "Erwartet wird z. B. 0.0.0.0:$intern"
  laufend="$(compose port "$dienst" "$intern" 2>/dev/null || true)"
  if [ -n "$laufend" ] && [ "${laufend##*:}" = "$port" ]; then
    meldung "Port $port wird bereits von Missa Control selbst verwendet – in Ordnung."
    return 0
  fi
  if port_belegt "$ip" "$port"; then
    fehler "Port $port ist bereits belegt (Einstellung $name=$bind)." \
      "Es wurde nichts gestartet, gestoppt oder verändert." \
      "Lösung: in der Datei .env bei $name einen freien Port eintragen" \
      "(z. B. $name=0.0.0.0:$((port + 1))) und ./scripts/install.sh erneut starten."
  fi
  meldung "Port $port ist frei."
}

schritt "Prüfe Docker"
docker_pruefen
meldung "Docker und Docker Compose sind vorhanden."

schritt "Prüfe Einstellungen (.env)"
if [ -f .env ]; then
  [ -r .env ] || fehler ".env ist für diesen Benutzer nicht lesbar." \
    "Bitte das Skript mit demselben Benutzer wie bei der Installation starten (z. B. mit sudo)."
  meldung ".env ist vorhanden und bleibt unverändert."
else
  # Der Container läuft nie als root: Bei "sudo" gehört alles dem aufrufenden Benutzer,
  # bei echtem root einem eigenen Benutzer ohne Rechte (10001).
  if [ "$(id -u)" -ne 0 ]; then
    ziel_uid="$(id -u)"; ziel_gid="$(id -g)"
  elif [ -n "${SUDO_UID:-}" ] && [ "${SUDO_UID}" -ne 0 ]; then
    ziel_uid="$SUDO_UID"; ziel_gid="${SUDO_GID:-$SUDO_UID}"
  else
    ziel_uid=10001; ziel_gid=10001
  fi
  zeitzone="$(zeitzone_des_servers)"
  (
    umask 077
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$(zufall 48)|" \
      -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$(zufall 32)|" \
      -e "s|^MISSA_CONTROL_UID=.*|MISSA_CONTROL_UID=$ziel_uid|" \
      -e "s|^MISSA_CONTROL_GID=.*|MISSA_CONTROL_GID=$ziel_gid|" \
      ${zeitzone:+-e "s|^MISSA_CONTROL_ZEITZONE=.*|MISSA_CONTROL_ZEITZONE=$zeitzone|"} \
      .env.example > .env
  )
  chmod 600 .env
  if [ "$(id -u)" -eq 0 ]; then chown "$ziel_uid:$ziel_gid" .env; fi
  meldung ".env wurde mit zufälligen Schlüsseln erzeugt."
  meldung "Zeitzone für Regeln: $(wert_aus_env MISSA_CONTROL_ZEITZONE Europe/Zurich) (änderbar in .env)."
fi

schritt "Prüfe Ports"
port_pruefen "$DIENST" 8090 MISSA_CONTROL_BIND 0.0.0.0:8090
if geraete_aktiv; then
  port_pruefen mqtt 1883 MQTT_BIND 0.0.0.0:1883
else
  meldung "MQTT-Broker für Geräte ist abgeschaltet (COMPOSE_PROFILES in .env)."
fi

schritt "Lege Datenordner an"
# data/mosquitto gehört dem MQTT-Broker für Geräte; er läuft unter demselben Benutzer wie das Panel.
mkdir -p data data/mosquitto
ziel_uid="$(wert_aus_env MISSA_CONTROL_UID 10001)"
ziel_gid="$(wert_aus_env MISSA_CONTROL_GID 10001)"
if [ "$(stat -c %u data)" != "$ziel_uid" ] || [ "$(stat -c %u data/mosquitto)" != "$ziel_uid" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    chown -R "$ziel_uid:$ziel_gid" data
  else
    fehler "Der Ordner data/ gehört nicht dem Benutzer mit der ID $ziel_uid (siehe MISSA_CONTROL_UID in .env)." \
      "Lösung: sudo chown -R $ziel_uid:$ziel_gid data"
  fi
fi
chmod 700 data 2>/dev/null || true
meldung "data/ ist bereit (vorhandene Daten bleiben erhalten)."

schritt "Baue und starte Missa Control"
compose up -d --build

schritt "Warte, bis das Panel antwortet"
if ! warte_auf_start; then
  fehler "Das Panel antwortet nicht." \
    "Ursache ansehen mit: docker compose -p $PROJEKT logs $DIENST"
fi

meldung ""
if [ -n "${MISSA_CONTROL_NACH_UPDATE:-}" ]; then
  meldung "Missa Control ist aktuell und läuft."
else
  meldung "Missa Control läuft."
fi
meldung ""
meldung "  Adresse:  $(panel_adresse)"
if geraete_aktiv; then
  meldung "  Geräte:   MQTT-Broker auf $(erreichbar_unter MQTT_BIND 0.0.0.0:1883) (Geräte im Panel unter „Geräte“ hinzufügen)"
fi
[ -z "${MISSA_CONTROL_NACH_UPDATE:-}" ] || exit 0
cat <<FERTIG

Beim ersten Aufruf: Passwort setzen und die Zwei-Faktor-Anmeldung einrichten.
Bitte gleich erledigen – bis dahin kann jeder im Netz das Panel einrichten.
FERTIG
