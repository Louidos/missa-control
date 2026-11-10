"""API der Seite „Gedächtnis“."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import get_db
from missa_control.gedaechtnis.dienst import GedaechtnisDienst, ansicht

router = APIRouter(prefix="/api/gedaechtnis", tags=["Gedächtnis"])


class EintragEingabe(BaseModel):
    text: str
    kategorie: str = "sonstiges"


class EintragAenderung(BaseModel):
    text: str | None = None
    kategorie: str | None = None


def _dienst(request: Request) -> GedaechtnisDienst:
    return request.app.state.gedaechtnis


@router.get("")
def uebersicht(
    request: Request,
    suche: str = Query(default="", max_length=200),
    kategorie: str = Query(default=""),
    quelle: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Einträge, gefiltert nach Suchtext, Kategorie und Quelle (neueste bzw. beste Treffer zuerst)."""
    return _dienst(request).uebersicht(db, suche=suche, kategorie=kategorie, quelle=quelle, limit=limit)


@router.get("/export")
def export(request: Request, db: Session = Depends(get_db)) -> Response:
    """Das ganze Gedächtnis als JSON-Datei zum Herunterladen."""
    inhalt = json.dumps(_dienst(request).export(db), ensure_ascii=False, indent=2)
    name = f"missa-gedaechtnis-{zeit.jetzt().date().isoformat()}.json"
    return Response(
        inhalt,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("", status_code=201)
def anlegen(eingabe: EintragEingabe, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    eintrag, neu = _dienst(request).anlegen(db, eingabe.text, eingabe.kategorie)
    return {**ansicht(eintrag), "neu": neu}


@router.put("/{eintrag_id}")
def aendern(
    eintrag_id: int, eingabe: EintragAenderung, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return ansicht(_dienst(request).aendern(db, eintrag_id, text=eingabe.text, kategorie=eingabe.kategorie))


@router.delete("/{eintrag_id}", status_code=204)
def loeschen(eintrag_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    _dienst(request).loeschen(db, eintrag_id)
    return Response(status_code=204)
