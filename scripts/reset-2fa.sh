#!/usr/bin/env bash
# Notfall: setzt die Zwei-Faktor-Anmeldung von Missa Control zurück – z. B. wenn das Handy mit der
# Authenticator-App verloren ging. Danach fragt das Panel nach dem bisherigen Passwort und zeigt
# einen neuen QR-Code. Alle Daten (Integrationen, Zugänge, Regeln …) bleiben erhalten.
#
#   ./scripts/reset-2fa.sh                  Zwei-Faktor-Anmeldung zurücksetzen (Passwort bleibt)
#   ./scripts/reset-2fa.sh --auch-passwort  auch das Passwort zurücksetzen (Einrichtung von vorn)
#   ./scripts/reset-2fa.sh --ja             ohne Rückfrage
#
# Das Skript betrifft nur das eigene Panel: Es ruft ein Werkzeug im Container "missa-control" auf.
# missa-core und alle anderen Container bleiben unberührt.
set -euo pipefail

# shellcheck source=scripts/_gemeinsam.sh
source "$(dirname "${BASH_SOURCE[0]}")/_gemeinsam.sh"
in_repo_ordner

auch_passwort=""
ohne_rueckfrage=""
for angabe in "$@"; do
  case "$angabe" in
    --auch-passwort) auch_passwort="--auch-passwort" ;;
    --ja) ohne_rueckfrage="ja" ;;
    *) fehler "Unbekannte Angabe: $angabe" "Möglich sind: --auch-passwort und --ja" ;;
  esac
done

[ -f .env ] || fehler "Missa Control ist noch nicht installiert." "Bitte zuerst ./scripts/install.sh ausführen."
docker_pruefen
dienst_laeuft || fehler "Das Panel läuft nicht." "Bitte zuerst ./scripts/install.sh ausführen."

if [ -n "$auch_passwort" ]; then
  meldung "Passwort UND Zwei-Faktor-Anmeldung von Missa Control werden zurückgesetzt."
  meldung "Danach kann das Panel von jedem neu eingerichtet werden, der es im Netz erreicht –"
  meldung "bitte gleich anschliessend selbst erledigen."
else
  meldung "Die Zwei-Faktor-Anmeldung von Missa Control wird zurückgesetzt. Das Passwort bleibt."
fi
meldung "Alle Anmeldungen am Panel werden beendet. Alle anderen Daten bleiben erhalten."

if [ -z "$ohne_rueckfrage" ]; then
  printf 'Wirklich zurücksetzen? [j/N] '
  read -r antwort || antwort=""
  case "$antwort" in
    j | J | ja | Ja | JA) ;;
    *) meldung "Abgebrochen – es wurde nichts geändert."; exit 0 ;;
  esac
fi

schritt "Setze zurück"
# shellcheck disable=SC2086  # $auch_passwort ist leer oder genau eine Angabe
compose exec -T "$DIENST" python -m missa_control.cli zwei-faktor-zuruecksetzen $auch_passwort

meldung ""
meldung "Jetzt das Panel öffnen und neu einrichten: $(panel_adresse)"
