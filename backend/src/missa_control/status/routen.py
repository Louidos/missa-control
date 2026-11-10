"""API der Startseite „Übersicht“."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.status.dienst import StatusDienst

router = APIRouter(prefix="/api/status", tags=["Übersicht"])


def _dienst(request: Request) -> StatusDienst:
    return request.app.state.status


@router.get("")
def uebersicht(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Alles Eingerichtete als Knoten und Kanten mit Status (ok, warn, fehler, grau)."""
    return _dienst(request).uebersicht(db)


@router.post("/pruefen")
async def jetzt_pruefen(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Prüft missa-core (nur lesend) und die Integrationen sofort – statt auf die nächste Runde zu warten."""
    await _dienst(request).pruefen()
    db.expire_all()
    return _dienst(request).uebersicht(db)


@router.put("/positionen")
def positionen_speichern(
    request: Request, daten: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Merkt sich, wohin Knoten in der Übersicht gezogen wurden."""
    return _dienst(request).positionen_speichern(db, daten.get("positionen"))


@router.delete("/positionen")
def positionen_loeschen(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Verwirft die eigene Anordnung – die Übersicht ordnet sich wieder selbst."""
    return _dienst(request).positionen_loeschen(db)
