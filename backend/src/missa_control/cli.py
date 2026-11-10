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


def main(argumente: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="missa_control.cli", description="Werkzeuge für Missa Control")
    befehle = parser.add_subparsers(dest="befehl", required=True)
    sicherung_parser = befehle.add_parser("sicherung", help="Schnappschuss der Datenbank schreiben")
    sicherung_parser.add_argument("ziel", type=Path)

    eingabe = parser.parse_args(argumente)
    if eingabe.befehl == "sicherung":
        sicherung(eingabe.ziel)


if __name__ == "__main__":
    main(sys.argv[1:])
