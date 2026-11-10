#!/usr/bin/env bash
# Aktualisiert Missa Control: sichert die Daten, holt die neue Version und baut nur
# das eigene Compose-Projekt "missa-control" neu. Fremde Container bleiben unberührt.
#
#   ./scripts/update.sh                 mit Backup vorher
#   ./scripts/update.sh --ohne-backup   ohne Backup
set -euo pipefail

# shellcheck source=scripts/_gemeinsam.sh
source "$(dirname "${BASH_SOURCE[0]}")/_gemeinsam.sh"
in_repo_ordner

[ -f .env ] || fehler "Missa Control ist noch nicht installiert." "Bitte zuerst ./scripts/install.sh ausführen."
docker_pruefen

if [ "${1:-}" != "--ohne-backup" ]; then
  schritt "Sichere Daten vor dem Update"
  ./scripts/backup.sh
fi

schritt "Hole die neue Version"
git pull --ff-only

schritt "Baue und starte Missa Control neu"
compose up -d --build

schritt "Warte, bis das Panel antwortet"
if ! warte_auf_start; then
  fehler "Das Panel antwortet nach dem Update nicht." \
    "Ursache ansehen mit: docker compose -p $PROJEKT logs $DIENST"
fi

meldung ""
meldung "Missa Control ist aktuell und läuft: $(panel_adresse)"
