"""Ereignisse abholen: für Clients (`/api/events`, mit Client-Token) und fürs Panel (`/api/ereignisse`)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.fehler import PanelFehler

client_router = APIRouter(prefix="/api/events", tags=["Ereignisse (für Clients)"])
panel_router = APIRouter(prefix="/api/ereignisse", tags=["Ereignisse"])


def _dienst(request: Request) -> EreignisDienst:
    return request.app.state.ereignisse


def _zeit_lesen(wert: str | None) -> datetime | None:
    if not wert:
        return None
    try:
        zeitpunkt = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        raise PanelFehler(
            422,
            "„seit“ ist kein gültiger Zeitpunkt.",
            "Erwartet wird ISO 8601, z. B. 2026-01-15T12:00:00Z",
        ) from None
    return zeitpunkt if zeitpunkt.tzinfo else zeitpunkt.replace(tzinfo=UTC)


@client_router.get("")
def abholen(
    request: Request,
    seit: str | None = Query(default=None, description="Zeitpunkt (ISO 8601): nur Ereignisse ab dann"),
    nach_id: int | None = Query(default=None, description="Nur Ereignisse mit grösserer Nummer"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ereignisse seit einem Zeitpunkt oder nach einer Nummer – älteste zuerst."""
    ereignisse = _dienst(request).seit(db, nach_id=nach_id, seit_zeit=_zeit_lesen(seit), limit=limit)
    letzte = ereignisse[-1]["id"] if ereignisse else nach_id
    return {"ereignisse": ereignisse, "letzte_id": letzte}


def _token_noch_gueltig(request: Request) -> bool:
    token = request.headers.get("authorization", "").partition(" ")[2].strip()
    with request.app.state.datenbank.sitzung() as db:
        return request.app.state.clients.pruefen(db, token) is not None


def _sse(inhalt: dict[str, Any]) -> str:
    return f"id: {inhalt['id']}\nevent: ereignis\ndata: {json.dumps(inhalt, ensure_ascii=False)}\n\n"


@client_router.get("/stream")
async def stream(request: Request, nach_id: int | None = Query(default=None)) -> StreamingResponse:
    """Server-Sent Events: neue Ereignisse kommen sofort. `Last-Event-ID` setzt nach einer Unterbrechung fort."""
    dienst = _dienst(request)
    letzte = request.headers.get("last-event-id")
    if nach_id is None and letzte and letzte.isdigit():
        nach_id = int(letzte)

    async def erzeugen() -> AsyncIterator[str]:
        yield ": verbunden\n\n"
        quelle = dienst.abonnieren(nach_id).__aiter__()
        naechstes: asyncio.Task[dict[str, Any]] | None = None
        try:
            while True:
                if naechstes is None:
                    naechstes = asyncio.ensure_future(quelle.__anext__())
                fertig, _ = await asyncio.wait(
                    {naechstes}, timeout=request.app.state.einstellungen.stream_ping_sekunden
                )
                if fertig:
                    yield _sse(naechstes.result())
                    naechstes = None
                else:
                    if not _token_noch_gueltig(request):
                        return  # Token wurde widerrufen: Verbindung beenden
                    yield ": ping\n\n"  # hält die Verbindung offen
        finally:
            if naechstes is not None:
                naechstes.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await (
                        naechstes
                    )  # erst wenn das Warten wirklich beendet ist, lässt sich das Abo schliessen
            with contextlib.suppress(RuntimeError):
                await quelle.aclose()

    return StreamingResponse(
        erzeugen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------- fürs Panel ----------


class TestEreignis(BaseModel):
    nachricht: str = Field(default="Das ist ein Test-Ereignis aus dem Panel.", max_length=500)
    dringlichkeit: str = Field(default="normal")


@panel_router.get("")
def auflisten(
    request: Request,
    art: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return _dienst(request).seit(db, art=art or None, limit=limit, neueste_zuerst=True)


@panel_router.post("/test")
def test_senden(eingabe: TestEreignis, request: Request) -> dict[str, Any]:
    """Erzeugt ein Test-Ereignis – praktisch, um die Anbindung eines Clients zu prüfen."""
    return _dienst(request).melden(
        "test", "Test-Ereignis", eingabe.nachricht, dringlichkeit=eingabe.dringlichkeit, quelle="panel"
    )
