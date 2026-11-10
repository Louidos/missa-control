"""Einstellungen des Panels – alle Werte kommen aus Umgebungsvariablen (siehe `.env.example`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Einstellungen:
    """Alle Einstellungen an einem Ort. Wird beim Start einmal aus der Umgebung gelesen."""

    host: str
    port: int
    daten_ordner: Path
    frontend_ordner: Path | None

    @classmethod
    def aus_umgebung(cls) -> Einstellungen:
        frontend = os.environ.get("MISSA_CONTROL_FRONTEND_DIR", "").strip()
        return cls(
            host=os.environ.get("MISSA_CONTROL_HOST", "127.0.0.1"),
            port=int(os.environ.get("MISSA_CONTROL_PORT", "8090")),
            daten_ordner=Path(os.environ.get("MISSA_CONTROL_DATA_DIR", "data")).resolve(),
            frontend_ordner=Path(frontend).resolve() if frontend else None,
        )
