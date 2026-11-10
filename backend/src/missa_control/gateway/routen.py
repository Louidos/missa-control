"""API der Seiten „Freigaben“ und „Protokoll“ sowie die lesende Konfig-API für Clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.fehler import PanelFehler
from missa_control.gateway.freigaben import FreigabeDienst
from missa_control.gateway.protokoll import ProtokollDienst
from missa_control.gateway.server import sichtbare_funktionen

panel_router = APIRouter(prefix="/api", tags=["Freigaben und Protokoll"])
konfig_router = APIRouter(prefix="/api/config", tags=["Konfiguration (für Clients)"])


class Entscheidung(BaseModel):
    erlauben: bool


def _freigaben(request: Request) -> FreigabeDienst:
    return request.app.state.freigaben


# ---------- Freigaben ----------


@panel_router.get("/freigaben")
def freigaben(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _freigaben(request)
    return {
        "offen": dienst.offene(db),
        "verlauf": dienst.verlauf(db),
        "frist_sekunden": dienst.frist_sekunden,
    }


@panel_router.get("/freigaben/anzahl")
def freigaben_anzahl(request: Request, db: Session = Depends(get_db)) -> dict[str, int]:
    return {"offen": _freigaben(request).anzahl_offen(db)}


@panel_router.post("/freigaben/{freigabe_id}")
async def entscheiden(
    freigabe_id: int, eingabe: Entscheidung, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _freigaben(request).entscheiden(db, freigabe_id, eingabe.erlauben)


# ---------- Protokoll ----------


def _zeit(wert: str | None, name: str) -> datetime | None:
    if not wert:
        return None
    try:
        zeitpunkt = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        raise PanelFehler(422, f"„{name}“ ist kein gültiger Zeitpunkt.") from None
    return zeitpunkt if zeitpunkt.tzinfo else zeitpunkt.replace(tzinfo=UTC)


@panel_router.get("/protokoll")
def protokoll(
    request: Request,
    client: str | None = None,
    integration: str | None = None,
    suche: str | None = None,
    ergebnis: str | None = Query(default=None, pattern="^(ok|fehler)$"),
    von: str | None = None,
    bis: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    versatz: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    dienst: ProtokollDienst = request.app.state.protokoll
    return dienst.suchen(
        db,
        client=client or None,
        integration=integration or None,
        suche=suche or None,
        ok=None if ergebnis is None else ergebnis == "ok",
        von=_zeit(von, "von"),
        bis=_zeit(bis, "bis"),
        limit=limit,
        versatz=versatz,
    )


# ---------- Konfig-API für Clients (nur lesend, mit Client-Token) ----------


@konfig_router.get("/integrations")
def konfig_integrationen(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Was Missa gerade nutzen kann: aktive Integrationen mit ihren sichtbaren Funktionen."""
    nach_integration: dict[int, dict[str, Any]] = {}
    for name, integration, funktion in sichtbare_funktionen(db):
        eintrag = nach_integration.setdefault(
            integration.id,
            {
                "name": integration.name,
                "kennung": integration.kennung,
                "art": integration.manifest_id,
                "status": integration.status,
                "funktionen": [],
            },
        )
        eintrag["funktionen"].append(
            {
                "name": name,
                "beschreibung": funktion.beschreibung,
                "schreibend": funktion.schreibend,
                "recht": funktion.recht,
            }
        )
    return {"integrationen": list(nach_integration.values())}


@konfig_router.get("/profile")
def konfig_profil(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Missas Charakterprofil. Solange im Panel noch keines gespeichert ist: `vorhanden: false`."""
    profil = getattr(request.app.state, "profil", None)
    if profil is None:
        return {"vorhanden": False, "profil": None, "systemprompt": None, "version": None}
    return profil.fuer_clients(db)
