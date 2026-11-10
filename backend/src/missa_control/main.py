"""FastAPI-App von Missa Control."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from missa_control import __version__
from missa_control.config import Einstellungen

# Pfade, die nie mit der Oberfläche beantwortet werden (API, Gateway, Modell-Anschluss).
_KEIN_FRONTEND = ("api", "mcp", "v1")


def create_app(einstellungen: Einstellungen | None = None) -> FastAPI:
    """Erzeugt die App. Für Tests können eigene Einstellungen übergeben werden."""
    einstellungen = einstellungen or Einstellungen.aus_umgebung()
    app = FastAPI(title="Missa Control", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.einstellungen = einstellungen

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if einstellungen.frontend_ordner is not None:
        _frontend_einbinden(app, einstellungen.frontend_ordner)
    return app


def _frontend_einbinden(app: FastAPI, ordner: Path) -> None:
    """Liefert die gebaute Oberfläche aus; unbekannte Pfade bekommen `index.html` (Single-Page-App)."""

    @app.get("/{pfad:path}", include_in_schema=False)
    def frontend(pfad: str) -> FileResponse:
        if pfad.split("/", 1)[0] in _KEIN_FRONTEND:
            raise HTTPException(status_code=404, detail="Nicht gefunden")
        datei = (ordner / pfad).resolve()
        if pfad and datei.is_file() and datei.is_relative_to(ordner):
            return FileResponse(datei)
        index = ordner / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Oberfläche ist nicht gebaut")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
