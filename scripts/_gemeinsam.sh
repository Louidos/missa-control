#!/usr/bin/env bash
# Gemeinsame Helfer für die Skripte von Missa Control.
# Wird von install.sh, update.sh und backup.sh eingebunden (nicht direkt aufrufen).
#
# Alle Docker-Befehle laufen ausschliesslich mit "docker compose -p missa-control"
# und betreffen damit nur die eigenen Container, Volumes und Netzwerke.

PROJEKT="missa-control"
DIENST="missa-control"

meldung() { printf '%s\n' "$*"; }
schritt() { printf '\n==> %s\n' "$*"; }
fehler() {
  printf '\nFEHLER: %s\n' "$1" >&2
  shift || true
  for zeile in "$@"; do printf '        %s\n' "$zeile" >&2; done
  exit 1
}

# Wechselt in den Repo-Ordner (eine Ebene über scripts/).
in_repo_ordner() {
  cd "$(dirname "${BASH_SOURCE[1]}")/.."
  [ -f compose.yaml ] || fehler "compose.yaml nicht gefunden – das Skript muss im Repo von Missa Control liegen."
}

docker_pruefen() {
  command -v docker >/dev/null 2>&1 \
    || fehler "Docker ist nicht installiert." "Anleitung: https://docs.docker.com/engine/install/debian/"
  docker compose version >/dev/null 2>&1 \
    || fehler "Docker Compose fehlt (Plugin \"docker compose\")." \
      "Anleitung: https://docs.docker.com/compose/install/linux/"
  docker info >/dev/null 2>&1 \
    || fehler "Docker läuft nicht oder dieser Benutzer darf Docker nicht verwenden." \
      "Lösung: Skript mit sudo starten oder den Benutzer in die Gruppe \"docker\" aufnehmen." \
      "Dieses Skript ändert daran selbst nichts."
}

# Alle Compose-Aufrufe laufen hier durch – immer mit dem eigenen Projektnamen.
# Der MQTT-Broker für Geräte (Profil "geraete") ist standardmässig dabei. Abschalten: in .env
# COMPOSE_PROFILES= (leer) eintragen. Steht in .env nichts dazu (ältere Installation), gilt der Standard.
compose() {
  if [ -z "${COMPOSE_PROFILES+x}" ] && ! grep -Eq '^[[:space:]]*COMPOSE_PROFILES=' .env 2>/dev/null; then
    COMPOSE_PROFILES=geraete docker compose -p "$PROJEKT" "$@"
  else
    docker compose -p "$PROJEKT" "$@"
  fi
}

# Ist der MQTT-Broker für Geräte eingeschaltet?
geraete_aktiv() {
  local profile
  if [ -n "${COMPOSE_PROFILES+x}" ]; then
    profile="$COMPOSE_PROFILES"
  elif grep -Eq '^[[:space:]]*COMPOSE_PROFILES=' .env 2>/dev/null; then
    profile="$(wert_aus_env COMPOSE_PROFILES "")"
  else
    profile="geraete"
  fi
  case ",$profile," in *,geraete,*) return 0 ;; *) return 1 ;; esac
}

# Liest einen Wert aus .env (ohne die Datei auszuführen). $1 = Name, $2 = Standardwert
wert_aus_env() {
  local zeile wert
  zeile="$(grep -E "^[[:space:]]*$1=" .env 2>/dev/null | tail -n 1 || true)"
  wert="${zeile#*=}"
  wert="${wert%$'\r'}"
  wert="${wert#\"}"; wert="${wert%\"}"
  wert="${wert#\'}"; wert="${wert%\'}"
  printf '%s' "${wert:-$2}"
}

dienst_laeuft() {
  [ -n "$(compose ps --status running --quiet "$DIENST" 2>/dev/null || true)" ]
}

# Wartet, bis das Panel im eigenen Container antwortet (höchstens ca. 2 Minuten).
warte_auf_start() {
  local versuch
  for versuch in $(seq 1 60); do
    if compose exec -T "$DIENST" python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=3)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# Gibt die Adresse aus, unter der das Panel erreichbar ist.
# Gibt „Adresse:Port“ aus, unter der ein Dienst erreichbar ist. $1 = Name der Einstellung, $2 = Standardwert
erreichbar_unter() {
  local bind ip port
  bind="$(wert_aus_env "$1" "$2")"
  if [[ "$bind" == *:* ]]; then ip="${bind%:*}"; port="${bind##*:}"; else ip="0.0.0.0"; port="$bind"; fi
  if [ "$ip" = "0.0.0.0" ] || [ -z "$ip" ]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    [ -n "$ip" ] || ip="$(hostname 2>/dev/null || echo localhost)"
  fi
  printf '%s:%s' "$ip" "$port"
}

panel_adresse() {
  printf 'http://%s' "$(erreichbar_unter MISSA_CONTROL_BIND 0.0.0.0:8090)"
}
