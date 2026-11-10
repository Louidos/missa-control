#!/usr/bin/env bash
# Sichert data/ und .env mit Datum in backups/.
# Läuft das Panel, wird die Datenbank über das Panel selbst als sauberer Schnappschuss gesichert.
#
# Wiederherstellen:
#   docker compose -p missa-control down
#   tar -xzf backups/missa-control-<datum>.tar.gz
#   ./scripts/install.sh
set -euo pipefail

# shellcheck source=scripts/_gemeinsam.sh
source "$(dirname "${BASH_SOURCE[0]}")/_gemeinsam.sh"
in_repo_ordner

[ -f .env ] || fehler "Keine .env gefunden – es gibt noch nichts zu sichern." "Bitte zuerst ./scripts/install.sh ausführen."
[ -d data ] || fehler "Kein Ordner data/ gefunden – es gibt noch nichts zu sichern."

umask 077
mkdir -p backups
chmod 700 backups
ziel="backups/missa-control-$(date +%Y-%m-%d_%H%M%S).tar.gz"
zwischen="backups/.zwischen-$$"
schnappschuss="data/.sicherung.db"
trap 'rm -rf "$zwischen" "$schnappschuss"' EXIT

if command -v docker >/dev/null 2>&1 && dienst_laeuft; then
  # Schnappschuss der laufenden Datenbank; er ersetzt im Archiv die Datenbank-Dateien.
  compose exec -T "$DIENST" python -m missa_control.cli sicherung "/data/.sicherung.db"
  mkdir -p "$zwischen"
  mv "$schnappschuss" "$zwischen/schnappschuss.db"
  tar -czf "$ziel" \
    --exclude='data/missa-control.db' --exclude='data/missa-control.db-wal' \
    --exclude='data/missa-control.db-shm' --exclude='data/.sicherung.db' \
    --transform='s|^schnappschuss\.db$|data/missa-control.db|' \
    .env data -C "$zwischen" schnappschuss.db
else
  tar -czf "$ziel" .env data
fi

tar -tzf "$ziel" | grep -qx 'data/missa-control.db' \
  || fehler "Das Backup enthält keine Datenbank – bitte Ausgabe oben prüfen." "Datei: $ziel"

chmod 600 "$ziel"
meldung "Backup erstellt: $ziel ($(du -h "$ziel" | cut -f1))"
meldung "Das Backup enthält die Schlüssel aus .env – bitte sicher aufbewahren."
