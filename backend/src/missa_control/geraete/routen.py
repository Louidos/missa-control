"""API der Seite „Geräte“."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.fehler import PanelFehler
from missa_control.geraete.dienst import GeraeteDienst
from missa_control.integrationen.typen import IntegrationsFehler

router = APIRouter(prefix="/api/geraete", tags=["Geräte"])


def _dienst(request: Request) -> GeraeteDienst:
    return request.app.state.geraete


@router.get("")
def uebersicht(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Alle Geräte mit Status, Fähigkeiten und letzten Werten – und der Zustand des MQTT-Brokers."""
    return _dienst(request).uebersicht(db)


@router.get("/{geraet_id}/verlauf")
def verlauf(
    geraet_id: int,
    request: Request,
    faehigkeit: str = Query(..., max_length=40),
    zeitraum: str = Query(default="24h"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Verlauf eines Sensors über 1 Stunde, 24 Stunden oder 7 Tage."""
    return {"verlauf": _dienst(request).verlauf(db, geraet_id, faehigkeit, zeitraum), "zeitraum": zeitraum}


@router.post("/{geraet_id}/koppeln")
def koppeln(geraet_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Neue Zugangsdaten für ein Gerät. Die bisherigen gelten sofort nicht mehr."""
    integration = request.app.state.integrationen.holen(db, geraet_id)
    eintrag = request.app.state.integrationen.katalog.eintraege.get(integration.manifest_id)
    if eintrag is None or eintrag.manifest.art != "geraet":
        raise PanelFehler(409, "Diese Integration ist kein Gerät.")
    try:
        return _dienst(request).koppeln(db, integration)
    except IntegrationsFehler as fehler:
        raise PanelFehler(503, fehler.meldung, fehler.hinweis) from fehler
