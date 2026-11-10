"""API der Seite „Anrufe“ – und der Anschluss, über den ein Telefonie-Adapter dem Panel etwas meldet."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.auth.schutz import CLIENT_SCHLUESSEL
from missa_control.db import get_db
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.telefonie.dienst import TelefonieDienst

panel_router = APIRouter(prefix="/api/telefonie", tags=["Telefonie"])
# Für Adapter ausserhalb des Panels (Telefon-App, SIP-Brücke): Zugriff nur mit Client-Token.
adapter_router = APIRouter(prefix="/api/telefonie/adapter", tags=["Telefonie-Adapter"])


class AnrufEingabe(BaseModel):
    text: str = Field(max_length=2000)
    nummer: str | None = Field(default=None, max_length=60)
    dringlichkeit: str = Field(default="normal", max_length=20)


class NummerEingabe(BaseModel):
    nummer: str = Field(default="", max_length=60)


class BeendetEingabe(BaseModel):
    dauer_sekunden: int | None = Field(default=None, ge=0, le=86_400)
    ergebnis: str = Field(default="beendet", max_length=20)
    meldung: str = Field(default="", max_length=300)


def _dienst(request: Request) -> TelefonieDienst:
    return request.app.state.telefonie


@panel_router.get("")
def uebersicht(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Einstellungen, verfügbare Adapter und ob gerade Ruhezeit ist."""
    return _dienst(request).ansicht(db)


@panel_router.put("/einstellungen")
def einstellungen_speichern(
    request: Request, daten: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _dienst(request).speichern(db, daten)


@panel_router.get("/anrufe")
def verlauf(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    richtung: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Der Anrufverlauf, neueste zuerst."""
    return {"anrufe": _dienst(request).verlauf(db, limit, richtung or None)}


@panel_router.post("/anrufen")
async def anrufen(eingabe: AnrufEingabe, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Ein Anruf aus dem Panel heraus – zum Ausprobieren, ohne Freigabe."""
    try:
        ergebnis = await _dienst(request).anrufen(
            db,
            text=eingabe.text,
            nummer=eingabe.nummer,
            dringlichkeit=eingabe.dringlichkeit,
            quelle="panel",
            quelle_name="Panel",
        )
    except IntegrationsFehler as fehler:
        return {"ok": False, "meldung": fehler.meldung, "hinweis": fehler.hinweis}
    return {"ok": True, "meldung": ergebnis["meldung"], "anruf": ergebnis}


@panel_router.post("/eingehend-simulieren")
def eingehend_simulieren(eingabe: NummerEingabe, request: Request) -> dict[str, Any]:
    """Tut so, als riefe diese Nummer an: zeigt, ob sie durchkäme. Es klingelt nirgends."""
    return _dienst(request).eingehend_simulieren(eingabe.nummer)


# ---------- Anschluss für Adapter ----------


@adapter_router.post("/eingehend")
def eingehend(eingabe: NummerEingabe, request: Request) -> dict[str, Any]:
    """Der Adapter meldet einen eingehenden Anruf. Die Antwort sagt, ob er ihn annehmen darf."""
    client = request.scope.get(CLIENT_SCHLUESSEL)
    return _dienst(request).eingehender_anruf(
        eingabe.nummer, adapter=getattr(client, "name", "") or "Adapter"
    )


@adapter_router.post("/anrufe/{anruf_id}/beendet")
def beendet(anruf_id: int, eingabe: BeendetEingabe, request: Request) -> dict[str, Any]:
    """Der Adapter meldet das Ende eines Anrufs (mit Dauer)."""
    return _dienst(request).anruf_beendet(
        anruf_id, dauer_sekunden=eingabe.dauer_sekunden, ergebnis=eingabe.ergebnis, meldung=eingabe.meldung
    )
