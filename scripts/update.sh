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

# Ab hier übernimmt install.sh in der soeben geholten Version: Es prüft die Ports, legt Ordner an,
# die eine neue Version braucht, und baut und startet nur das eigene Compose-Projekt.
# Vorhandene Einstellungen (.env) und Daten bleiben dabei unverändert.
MISSA_CONTROL_NACH_UPDATE=1 exec ./scripts/install.sh
