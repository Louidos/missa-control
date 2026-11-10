"""API der Seite „Charakter“."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.profil.dienst import (
    Profil,
    ProfilDienst,
    profil_als_yaml,
    profil_aus_yaml,
    systemprompt_bauen,
)

router = APIRouter(prefix="/api/profil", tags=["Charakter"])


class Speichern(BaseModel):
    profil: Profil
    kommentar: str = Field(default="", max_length=300)


class YamlEingabe(BaseModel):
    yaml: str = Field(max_length=200_000)


class Nachricht(BaseModel):
    von: Literal["nutzer", "missa"]
    text: str = Field(max_length=20_000)


class TestChat(BaseModel):
    profil: Profil
    rolle: str = Field(default="schnell", max_length=30)
    nachrichten: list[Nachricht] = Field(min_length=1, max_length=100)


def _dienst(request: Request) -> ProfilDienst:
    return request.app.state.profil


@router.get("")
def aktuell(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).aktuell(db)


@router.put("")
def speichern(eingabe: Speichern, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).speichern(db, eingabe.profil, eingabe.kommentar)


@router.post("/vorschau")
def vorschau(profil: Profil) -> dict[str, str]:
    """Der Systemprompt, der aus dem (auch ungespeicherten) Profil entsteht."""
    return {"systemprompt": systemprompt_bauen(profil.bereinigt())}


@router.get("/versionen")
def versionen(request: Request, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return _dienst(request).versionen(db)


@router.get("/versionen/{version_id}")
def version(version_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).version(db, version_id)


@router.post("/versionen/{version_id}/wiederherstellen")
def wiederherstellen(version_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).wiederherstellen(db, version_id)


@router.get("/export", response_class=PlainTextResponse)
def exportieren(request: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
    profil = Profil.model_validate(_dienst(request).aktuell(db)["profil"])
    return PlainTextResponse(
        profil_als_yaml(profil),
        media_type="application/yaml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="missa-profil.yaml"'},
    )


@router.post("/import")
def importieren(eingabe: YamlEingabe) -> dict[str, Any]:
    """Liest ein Profil aus YAML und gibt es zurück – gespeichert wird erst mit „Speichern“."""
    return {"profil": profil_aus_yaml(eingabe.yaml).model_dump()}


@router.get("/beispiel")
def beispiel(request: Request) -> dict[str, Any]:
    return {"profil": _dienst(request).beispiel().model_dump()}


@router.post("/testchat")
async def testchat(eingabe: TestChat, request: Request) -> dict[str, Any]:
    return await _dienst(request).testchat(
        eingabe.profil, eingabe.rolle, [nachricht.model_dump() for nachricht in eingabe.nachrichten]
    )
