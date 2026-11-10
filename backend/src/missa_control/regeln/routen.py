"""API der Seite „Regeln“."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.fehler import PanelFehler
from missa_control.regeln.dienst import RegelDienst

router = APIRouter(prefix="/api/regeln", tags=["Regeln"])


class AktivEingabe(BaseModel):
    aktiv: bool


def _dienst(request: Request) -> RegelDienst:
    return request.app.state.regeln


@router.get("")
def uebersicht(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Alle Regeln (mit lesbarem Satz) und alles, was der Editor zur Auswahl anbietet."""
    return _dienst(request).uebersicht(db)


@router.get("/verlauf")
def verlauf(
    request: Request,
    regel_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Verlauf der Auslösungen, neueste zuerst – für alle Regeln oder eine bestimmte."""
    return _dienst(request).verlauf(db, regel_id, limit)


@router.post("/satz")
def als_satz(
    request: Request, daten: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Prüft (noch nicht gespeicherte) Angaben und gibt die Regel als lesbaren Satz zurück.

    Der Editor fragt bei jeder Änderung – eine unvollständige Regel ist dabei der Normalfall und
    deshalb kein Fehler: dann steht in `meldung`, was noch fehlt.
    """
    try:
        return {"ok": True, "satz": _dienst(request).als_satz(db, daten)}
    except PanelFehler as fehler:
        if fehler.status != 422:
            raise
        return {"ok": False, "meldung": fehler.meldung, "hinweis": fehler.hinweis}


@router.post("", status_code=201)
def anlegen(
    request: Request, daten: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.anlegen(db, daten), dienst.umfeld(db))


@router.put("/{regel_id}")
def aendern(
    regel_id: int, request: Request, daten: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.aendern(db, regel_id, daten), dienst.umfeld(db))


@router.patch("/{regel_id}")
def aktiv_setzen(
    regel_id: int, eingabe: AktivEingabe, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Regel pausieren oder wieder einschalten."""
    dienst = _dienst(request)
    return dienst.ansicht(dienst.aktiv_setzen(db, regel_id, eingabe.aktiv), dienst.umfeld(db))


@router.delete("/{regel_id}", status_code=204)
def loeschen(regel_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    _dienst(request).loeschen(db, regel_id)
    return Response(status_code=204)


@router.post("/{regel_id}/testen")
async def testen(regel_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """„Jetzt testen“: führt die Aktion der Regel sofort aus."""
    return await _dienst(request).testen(db, regel_id)
