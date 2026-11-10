"""Startet das Panel: `python -m missa_control`."""

from __future__ import annotations

import os

import uvicorn

from missa_control.config import Einstellungen, EinstellungsFehler
from missa_control.main import create_app


def main() -> None:
    os.umask(0o077)  # Datenbank und andere Dateien in data/ sind nur für den eigenen Benutzer lesbar
    try:
        einstellungen = Einstellungen.aus_umgebung()
    except EinstellungsFehler as fehler:
        raise SystemExit(f"FEHLER: {fehler}") from None
    uvicorn.run(
        create_app(einstellungen),
        host=einstellungen.host,
        port=einstellungen.port,
        log_level="info",
        server_header=False,
    )


if __name__ == "__main__":
    main()
