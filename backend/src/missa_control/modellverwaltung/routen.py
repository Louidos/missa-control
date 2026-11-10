"""API der Seite „Modelle“ und der OpenAI-kompatible Modell-Anschluss `/v1` für Clients."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import get_db
from missa_control.modellverwaltung.dienst import ModellDienst, ModellFehler

panel_router = APIRouter(prefix="/api", tags=["Modelle"])
proxy_router = APIRouter(prefix="/v1", tags=["Modell-Anschluss (für Clients)"])


class ModellEingabe(BaseModel):
    name: str = Field(max_length=80)
    url: str = Field(max_length=500)
    modellname: str = Field(max_length=200)
    zugang_id: int | None = None
    kontextlaenge: int | None = Field(default=None, ge=1, le=10_000_000)


class RolleNeu(BaseModel):
    kennung: str = Field(max_length=30)
    name: str = Field(default="", max_length=60)
    beschreibung: str = Field(default="", max_length=300)


class RolleAenderung(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    beschreibung: str | None = Field(default=None, max_length=300)
    haupt_modell_id: int | None = None
    ersatz_modell_id: int | None = None


def _dienst(request: Request) -> ModellDienst:
    return request.app.state.modelle


# ---------- Panel ----------


@panel_router.get("/modelle")
def uebersicht(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).uebersicht(db)


@panel_router.post("/modelle", status_code=201)
def modell_anlegen(eingabe: ModellEingabe, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.modell_ansicht(dienst.modell_anlegen(db, eingabe.model_dump()))


@panel_router.put("/modelle/{modell_id}")
def modell_aendern(
    modell_id: int, eingabe: ModellEingabe, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.modell_ansicht(dienst.modell_aendern(db, modell_id, eingabe.model_dump()))


@panel_router.post("/modelle/{modell_id}/testen")
async def modell_testen(modell_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.modell_ansicht(await dienst.testen(db, modell_id))


@panel_router.delete("/modelle/{modell_id}")
def modell_loeschen(modell_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).modell_loeschen(db, modell_id)
    return {"ok": True}


@panel_router.post("/rollen", status_code=201)
def rolle_anlegen(eingabe: RolleNeu, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.rollen_ansicht(dienst.rolle_anlegen(db, **eingabe.model_dump()), {})


@panel_router.put("/rollen/{rolle_id}")
def rolle_aendern(
    rolle_id: int, eingabe: RolleAenderung, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    dienst.rolle_aendern(db, rolle_id, eingabe.model_dump(exclude_unset=True))
    return dienst.uebersicht(db)


@panel_router.delete("/rollen/{rolle_id}")
def rolle_loeschen(rolle_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).rolle_loeschen(db, rolle_id)
    return {"ok": True}


# ---------- Modell-Anschluss für Clients (OpenAI-kompatibel, mit Client-Token) ----------


def _fehler(status: int, meldung: str, hinweis: str | None = None) -> JSONResponse:
    """Fehler im Format der OpenAI-API, damit Clients die Meldung anzeigen können."""
    text = f"{meldung} {hinweis}" if hinweis else meldung
    return JSONResponse(
        {"error": {"message": text, "type": "missa_control_error", "code": status}}, status_code=status
    )


@proxy_router.get("/models")
def models(request: Request) -> dict[str, Any]:
    erstellt = int(zeit.jetzt().timestamp())
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": erstellt, "owned_by": "missa-control"}
            for name in _dienst(request).rollen_namen()
        ],
    }


@proxy_router.post("/chat/completions")
async def chat_completions(request: Request) -> Any:
    """Leitet an das Modell der Rolle weiter (`model` = `missa-schnell`, `missa-stark`, …)."""
    dienst = _dienst(request)
    try:
        koerper = await request.json()
    except ValueError:
        return _fehler(400, "Die Anfrage ist kein gültiges JSON.")
    if not isinstance(koerper, dict) or not isinstance(koerper.get("model"), str):
        return _fehler(400, "In der Anfrage fehlt „model“.", "Zum Beispiel missa-schnell oder missa-stark.")
    try:
        if koerper.get("stream"):
            ziel, status, strom = await dienst.chat_stream(koerper["model"], koerper)
            return StreamingResponse(
                strom,
                status_code=status,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Accel-Buffering": "no",
                    "X-Missa-Modell": quote(ziel.name),
                },
            )
        antwort = await dienst.chat(koerper["model"], koerper)
    except ModellFehler as fehler:
        return _fehler(fehler.status, fehler.meldung, fehler.hinweis)
    return JSONResponse(
        antwort.inhalt, status_code=antwort.status, headers={"X-Missa-Modell": quote(antwort.ziel.name)}
    )
