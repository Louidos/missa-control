"""API der Seite „Sicherung“: herunterladen, Vorschau, einspielen."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import get_db
from missa_control.fehler import PanelFehler
from missa_control.sicherung.dienst import SicherungsDienst

router = APIRouter(prefix="/api/sicherung", tags=["Sicherung"])
MAX_DATEI_ZEICHEN = 20 * 1024 * 1024


class Export(BaseModel):
    # Mit Passwort kommen die Zugänge verschlüsselt mit – dafür braucht es Passwort und Code des Panels.
    sicherungs_passwort: str | None = Field(default=None, max_length=200)
    passwort: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=12)


class Vorschau(BaseModel):
    datei: str = Field(max_length=MAX_DATEI_ZEICHEN)
    sicherungs_passwort: str | None = Field(default=None, max_length=200)


class Einspielen(Vorschau):
    modi: dict[str, str] = Field(default_factory=dict)
    passwort: str = Field(max_length=200)
    code: str = Field(max_length=12)


def _dienst(request: Request) -> SicherungsDienst:
    return request.app.state.sicherung


def _bestaetigen(request: Request, db: Session, passwort: str | None, code: str | None) -> None:
    if not passwort or not code:
        raise PanelFehler(
            403,
            "Bitte zur Bestätigung Passwort und Code eingeben.",
            "Zugänge sichern und eine Sicherung einspielen geht nur mit erneuter Anmeldung.",
        )
    request.app.state.auth.bestaetigen(db, passwort, code)


@router.post("/export")
def exportieren(eingabe: Export, request: Request, db: Session = Depends(get_db)) -> Response:
    if eingabe.sicherungs_passwort:
        _bestaetigen(request, db, eingabe.passwort, eingabe.code)
    datei = _dienst(request).exportieren(db, eingabe.sicherungs_passwort or None)
    name = f"missa-control-sicherung-{zeit.jetzt().strftime('%Y-%m-%d')}.json"
    return Response(
        content=json.dumps(datei, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.post("/vorschau")
def vorschau(eingabe: Vorschau, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.vorschau(db, dienst.lesen(eingabe.datei), eingabe.sicherungs_passwort or None)


@router.post("/einspielen")
def einspielen(eingabe: Einspielen, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _bestaetigen(request, db, eingabe.passwort, eingabe.code)
    dienst = _dienst(request)
    return dienst.einspielen(
        db, dienst.lesen(eingabe.datei), modi=eingabe.modi, passwort=eingabe.sicherungs_passwort or None
    )
