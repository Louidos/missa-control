"""API der Seite „Clients“."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.clients.dienst import ClientDienst
from missa_control.db import get_db

router = APIRouter(prefix="/api/clients", tags=["Clients"])


class ClientNeu(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _dienst(request: Request) -> ClientDienst:
    return request.app.state.clients


@router.get("")
def auflisten(request: Request, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return _dienst(request).alle(db)


@router.post("", status_code=201)
def anlegen(eingabe: ClientNeu, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    dienst = _dienst(request)
    client, token = dienst.anlegen(db, eingabe.name)
    # Der Token steht nur in dieser einen Antwort.
    return {**dienst.ansicht(client), "token": token}


@router.post("/{client_id}/widerrufen")
def widerrufen(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.widerrufen(db, client_id))


@router.delete("/{client_id}")
def loeschen(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).loeschen(db, client_id)
    return {"ok": True}
