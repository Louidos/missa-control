"""Startet das Panel: `python -m missa_control`."""

from __future__ import annotations

import uvicorn

from missa_control.config import Einstellungen
from missa_control.main import create_app


def main() -> None:
    einstellungen = Einstellungen.aus_umgebung()
    uvicorn.run(
        create_app(einstellungen),
        host=einstellungen.host,
        port=einstellungen.port,
        log_level="info",
        server_header=False,
    )


if __name__ == "__main__":
    main()
