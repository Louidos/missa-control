"""Einheitliche Fehlermeldungen: immer verständlich, wenn möglich mit Lösungshinweis."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class PanelFehler(Exception):
    """Ein Fehler, den die Oberfläche direkt anzeigen kann."""

    def __init__(self, status: int, meldung: str, hinweis: str | None = None) -> None:
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung
        self.hinweis = hinweis


def fehler_antwort(status: int, meldung: str, hinweis: str | None = None) -> JSONResponse:
    inhalt: dict[str, object] = {"meldung": meldung}
    if hinweis:
        inhalt["hinweis"] = hinweis
    return JSONResponse(inhalt, status_code=status)


_STANDARD_MELDUNGEN = {
    404: "Nicht gefunden",
    405: "Diese Aktion ist hier nicht möglich",
}


def fehlerbehandlung_einrichten(app: FastAPI) -> None:
    @app.exception_handler(PanelFehler)
    async def _panel_fehler(_: Request, fehler: PanelFehler) -> JSONResponse:
        return fehler_antwort(fehler.status, fehler.meldung, fehler.hinweis)

    @app.exception_handler(StarletteHTTPException)
    async def _http_fehler(_: Request, fehler: StarletteHTTPException) -> JSONResponse:
        meldung = _STANDARD_MELDUNGEN.get(fehler.status_code) or str(fehler.detail)
        return fehler_antwort(fehler.status_code, meldung)

    @app.exception_handler(RequestValidationError)
    async def _eingabe_fehler(_: Request, fehler: RequestValidationError) -> JSONResponse:
        felder = []
        for eintrag in fehler.errors():
            ort = ".".join(str(teil) for teil in eintrag.get("loc", ()) if teil not in ("body", "query"))
            felder.append(f"{ort}: {eintrag.get('msg', 'ungültig')}" if ort else str(eintrag.get("msg")))
        return fehler_antwort(422, "Die Eingabe ist unvollständig oder ungültig.", "; ".join(felder) or None)
