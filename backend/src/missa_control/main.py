"""FastAPI-App von Missa Control."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from missa_control import __version__
from missa_control.auth import routen as auth_routen
from missa_control.auth.dienst import AuthDienst
from missa_control.auth.schutz import Zugriffsschutz, ist_geschuetzt
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.fehler import fehlerbehandlung_einrichten
from missa_control.krypto import Krypto


def create_app(einstellungen: Einstellungen | None = None) -> FastAPI:
    """Erzeugt die App. Für Tests können eigene Einstellungen übergeben werden."""
    einstellungen = einstellungen or Einstellungen.aus_umgebung()
    datenbank = Datenbank(einstellungen.datenbank_pfad)
    datenbank.migrieren()
    krypto = Krypto(einstellungen.secret_key, einstellungen.encryption_key)
    auth = AuthDienst(einstellungen, krypto)

    app = FastAPI(title="Missa Control", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.einstellungen = einstellungen
    app.state.datenbank = datenbank
    app.state.krypto = krypto
    app.state.auth = auth

    fehlerbehandlung_einrichten(app)
    app.add_middleware(Zugriffsschutz, auth=auth, datenbank=datenbank)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth_routen.router)

    if einstellungen.frontend_ordner is not None:
        _frontend_einbinden(app, einstellungen.frontend_ordner)
    return app


def _frontend_einbinden(app: FastAPI, ordner: Path) -> None:
    """Liefert die gebaute Oberfläche aus; unbekannte Pfade bekommen `index.html` (Single-Page-App)."""

    @app.get("/{pfad:path}", include_in_schema=False)
    def frontend(pfad: str) -> FileResponse:
        if ist_geschuetzt("/" + pfad):
            raise HTTPException(status_code=404)
        datei = (ordner / pfad).resolve()
        if pfad and datei.is_file() and datei.is_relative_to(ordner):
            return FileResponse(datei)
        index = ordner / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Die Oberfläche ist nicht gebaut.")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
