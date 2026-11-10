"""API der Seite „Zugänge“. Keine Antwort enthält je einen Wert im Klartext."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.zugaenge.dienst import ZugangsDienst

router = APIRouter(prefix="/api/zugaenge", tags=["Zugänge"])

ZugangTyp = Literal["api_key", "benutzer_passwort", "bearer_token"]


class ZugangNeu(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    typ: ZugangTyp
    wert: str = Field(min_length=1, max_length=10_000)
    benutzer: str | None = Field(default=None, max_length=300)
    notiz: str = Field(default="", max_length=2_000)


class ZugangAenderung(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    wert: str | None = Field(default=None, max_length=10_000)
    benutzer: str | None = Field(default=None, max_length=300)
    notiz: str | None = Field(default=None, max_length=2_000)


def _dienst(request: Request) -> ZugangsDienst:
    return request.app.state.zugaenge


@router.get("")
def auflisten(request: Request, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return _dienst(request).alle(db)


@router.post("", status_code=201)
def anlegen(eingabe: ZugangNeu, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.anlegen(db, **eingabe.model_dump()))


@router.put("/{zugang_id}")
def aendern(
    zugang_id: int, eingabe: ZugangAenderung, request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.aendern(db, zugang_id, **eingabe.model_dump()))


@router.delete("/{zugang_id}")
def loeschen(zugang_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).loeschen(db, zugang_id)
    return {"ok": True}
