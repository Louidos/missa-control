"""Werkzeuge für die Skripte in `scripts/`: `python -m missa_control.cli <befehl>`."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from missa_control.config import Einstellungen


def sicherung(ziel: Path) -> None:
    """Schreibt einen sauberen Schnappschuss der laufenden Datenbank nach `ziel`."""
    quelle_pfad = Einstellungen.aus_umgebung().datenbank_pfad
    if not quelle_pfad.is_file():
        raise SystemExit(f"Keine Datenbank gefunden: {quelle_pfad}")
    ziel.unlink(missing_ok=True)
    quelle = sqlite3.connect(quelle_pfad)
    kopie = sqlite3.connect(ziel)
    try:
        quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()


def zwei_faktor_zuruecksetzen(auch_passwort: bool) -> None:
    """Notfall-Reset der Zwei-Faktor-Anmeldung (siehe scripts/reset-2fa.sh)."""
    from missa_control.auth.dienst import AuthDienst
    from missa_control.db import Datenbank
    from missa_control.krypto import Krypto

    einstellungen = Einstellungen.aus_umgebung()
    if not einstellungen.datenbank_pfad.is_file():
        raise SystemExit(f"Keine Datenbank gefunden: {einstellungen.datenbank_pfad}")
    datenbank = Datenbank(einstellungen.datenbank_pfad)
    datenbank.migrieren()
    try:
        auth = AuthDienst(einstellungen, Krypto(einstellungen.secret_key, einstellungen.encryption_key))
        with datenbank.sitzung() as db:
            print(auth.zwei_faktor_zuruecksetzen(db, auch_passwort=auch_passwort))
    finally:
        datenbank.schliessen()


def main(argumente: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="missa_control.cli", description="Werkzeuge für Missa Control")
    befehle = parser.add_subparsers(dest="befehl", required=True)
    sicherung_parser = befehle.add_parser("sicherung", help="Schnappschuss der Datenbank schreiben")
    sicherung_parser.add_argument("ziel", type=Path)
    reset_parser = befehle.add_parser(
        "zwei-faktor-zuruecksetzen", help="Notfall: Zwei-Faktor-Anmeldung neu einrichten lassen"
    )
    reset_parser.add_argument(
        "--auch-passwort", action="store_true", help="auch das Passwort zurücksetzen (Einrichtung von vorn)"
    )

    eingabe = parser.parse_args(argumente)
    if eingabe.befehl == "sicherung":
        sicherung(eingabe.ziel)
    elif eingabe.befehl == "zwei-faktor-zuruecksetzen":
        zwei_faktor_zuruecksetzen(eingabe.auch_passwort)


if __name__ == "__main__":
    main(sys.argv[1:])
