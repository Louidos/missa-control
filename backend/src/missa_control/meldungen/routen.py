"""API der Seite „Meldungen“."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.meldungen.dienst import MeldungsDienst

router = APIRouter(prefix="/api/meldungen", tags=["Meldungen"])


class Ziel(BaseModel):
    name: str = Field(max_length=80)
    art: str = Field(max_length=20)
    adresse: str = Field(max_length=500)
    thema: str = Field(default="", max_length=200)
    zugang_id: int | None = None
    panel_adresse: str = Field(default="", max_length=300)
    arten: list[str] = Field(default_factory=list)
    aktiv: bool = True


def _dienst(request: Request) -> MeldungsDienst:
    return request.app.state.meldungen


@router.get("")
def auflisten(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).alle(db)


@router.post("", status_code=201)
def anlegen(eingabe: Ziel, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.speichern(db, eingabe.model_dump()))


@router.put("/{ziel_id}")
def aendern(ziel_id: int, eingabe: Ziel, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.speichern(db, eingabe.model_dump(), ziel_id))


@router.delete("/{ziel_id}")
def loeschen(ziel_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).loeschen(db, ziel_id)
    return {"ok": True}


@router.post("/{ziel_id}/testen")
def testen(ziel_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sendet eine Test-Meldung (läuft im Thread-Pool – blockiert das Panel nicht)."""
    return _dienst(request).testen(db, ziel_id)
