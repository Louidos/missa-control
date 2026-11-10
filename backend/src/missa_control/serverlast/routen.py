"""API der Seite „Serverlast“."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from missa_control.db import get_db

router = APIRouter(prefix="/api/serverlast", tags=["Serverlast"])


@router.get("")
def uebersicht(
    request: Request, zeitraum: str = Query(default="1h"), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Aktuelle Werte und Verlauf für 1 Stunde, 24 Stunden oder 7 Tage."""
    return request.app.state.serverlast.uebersicht(db, zeitraum)
