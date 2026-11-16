"""API der Seite „Statistik“."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from missa_control.db import get_db

router = APIRouter(prefix="/api/statistik", tags=["Statistik"])


@router.get("")
def statistik(
    request: Request, zeitraum: Literal["24h", "7d", "30d"] = "7d", db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Aufrufe, Fehlerquote und Dauer pro Integration und Funktion – berechnet aus dem Protokoll."""
    return request.app.state.statistik.berechnen(db, zeitraum)
