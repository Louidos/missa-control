#!/usr/bin/env bash
# Missa Control mit einem einzigen Befehl installieren:
#
#   curl -fsSL https://raw.githubusercontent.com/Louidos/missa-control/main/scripts/schnellstart.sh | bash
#
# Holt das Repo nach ~/missa-control (änderbar mit MISSA_CONTROL_ORDNER), prüft git und Docker und
# übergibt an scripts/install.sh – das prüft die Ports, erzeugt .env, startet das Panel und zeigt die
# Adresse. Kann beliebig oft ausgeführt werden: .env und data/ bleiben unverändert.
#
# Das Skript installiert nichts selbst (auch nicht Docker), liest nichts von der Tastatur, arbeitet nur
# im eigenen Ordner und nur mit dem Compose-Projekt "missa-control".
#
# Einstellungen (alle optional):
#   MISSA_CONTROL_ORDNER    Zielordner (Standard: ~/missa-control)
#   MISSA_CONTROL_REPO_URL  Quelle des Repos (Standard: GitHub; für Tests auch ein lokaler Ordner)
#   MISSA_CONTROL_ZWEIG     Branch, der geholt wird (Standard: main)
#
# Der ganze Inhalt steckt in einer Funktion, die erst in der letzten Zeile aufgerufen wird: Bricht der
# Download mittendrin ab, wird nichts halb ausgeführt.

schnellstart() {
  set -euo pipefail

  local repo_url="${MISSA_CONTROL_REPO_URL:-https://github.com/Louidos/missa-control.git}"
  local ordner="${MISSA_CONTROL_ORDNER:-$HOME/missa-control}"
  local zweig="${MISSA_CONTROL_ZWEIG:-main}"

  # Nie nach etwas fragen – weder git noch ssh.
  export GIT_TERMINAL_PROMPT=0
  export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}"

  _meldung() { printf '%s\n' "$*"; }
  _schritt() { printf '\n==> %s\n' "$*"; }
  _abbruch() {
    printf '\nFEHLER: %s\n' "$1" >&2
    shift || true
    local zeile
    for zeile in "$@"; do printf '        %s\n' "$zeile" >&2; done
    printf '\nEs wurde nichts verändert.\n' >&2
    exit 1
  }

  # Gleiche Quelle? „https://github.com/a/b(.git)“, „git@github.com:a/b.git“ und lokale Pfade.
  _normalisiert() {
    local url="${1%/}"
    url="${url%.git}"
    url="${url#https://}"
    url="${url#http://}"
    url="${url#ssh://}"
    url="${url#git@}"
    url="${url/://}"
    printf '%s' "$url" | tr '[:upper:]' '[:lower:]'
  }

  _schritt "Prüfe git und Docker"
  command -v git >/dev/null 2>&1 \
    || _abbruch "git ist nicht installiert." \
      "Unter Debian/Ubuntu: sudo apt install git" \
      "Danach diesen Befehl erneut ausführen."
  command -v docker >/dev/null 2>&1 \
    || _abbruch "Docker ist nicht installiert." \
      "Anleitung: https://docs.docker.com/engine/install/debian/" \
      "Danach diesen Befehl erneut ausführen."
  docker compose version >/dev/null 2>&1 \
    || _abbruch "Docker Compose fehlt (Plugin \"docker compose\")." \
      "Anleitung: https://docs.docker.com/compose/install/linux/"
  docker info >/dev/null 2>&1 \
    || _abbruch "Docker läuft nicht oder dieser Benutzer darf Docker nicht verwenden." \
      "Lösung: den Benutzer in die Gruppe \"docker\" aufnehmen (sudo usermod -aG docker \$USER, neu anmelden)" \
      "oder den Befehl mit sudo ausführen. Dieses Skript ändert daran selbst nichts."
  _meldung "git und Docker sind bereit."

  _schritt "Hole Missa Control nach $ordner"
  if [ ! -e "$ordner" ]; then
    git clone --quiet --branch "$zweig" -- "$repo_url" "$ordner" </dev/null \
      || _abbruch "Das Repo lässt sich nicht holen ($repo_url)." "Besteht eine Verbindung ins Internet?"
    _meldung "Neu geholt."
  elif [ -d "$ordner/.git" ] && [ -f "$ordner/scripts/install.sh" ]; then
    local herkunft
    herkunft="$(git -C "$ordner" remote get-url origin 2>/dev/null || true)"
    if [ "$(_normalisiert "$herkunft")" != "$(_normalisiert "$repo_url")" ]; then
      _abbruch "Im Ordner $ordner liegt ein anderes Repo ($herkunft)." \
        "Anderen Ordner wählen: MISSA_CONTROL_ORDNER=/pfad/zum/ordner vor den Befehl setzen."
    fi
    git -C "$ordner" pull --quiet --ff-only </dev/null \
      || _abbruch "Der Ordner $ordner lässt sich nicht aktualisieren (git pull --ff-only)." \
        "Gibt es dort eigene Änderungen? Mit \"git -C $ordner status\" nachsehen."
    _meldung "Bereits vorhanden – auf den neusten Stand gebracht."
  else
    _abbruch "Den Ordner $ordner gibt es schon, aber er enthält nicht Missa Control." \
      "Anderen Ordner wählen: MISSA_CONTROL_ORDNER=/pfad/zum/ordner vor den Befehl setzen," \
      "oder den Ordner selbst umbenennen. Dieses Skript löscht nichts."
  fi

  # Ab hier übernimmt install.sh: Ports prüfen, .env erzeugen (nur wenn sie fehlt), starten, Adresse zeigen.
  "$ordner/scripts/install.sh" </dev/null
}

schnellstart "$@"
