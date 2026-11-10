"""API für Einrichtung, Anmeldung und Abmeldung."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control import __version__
from missa_control.auth.dienst import MAX_PASSWORT_LAENGE, AuthDienst
from missa_control.db import get_db

SITZUNGS_COOKIE = "missa_control_sitzung"
EINRICHTUNGS_COOKIE = "missa_control_einrichtung"
EINRICHTUNG_SEKUNDEN = 15 * 60

router = APIRouter(prefix="/api/auth", tags=["Login"])


class PasswortEingabe(BaseModel):
    passwort: str = Field(max_length=MAX_PASSWORT_LAENGE * 4)


class CodeEingabe(BaseModel):
    code: str = Field(max_length=32)


class AnmeldeEingabe(PasswortEingabe, CodeEingabe):
    pass


def _dienst(request: Request) -> AuthDienst:
    return request.app.state.auth


def _cookie_secure(request: Request) -> bool:
    einstellung = request.app.state.einstellungen.cookie_secure
    return einstellung == "ja" or (einstellung == "auto" and request.url.scheme == "https")


def _cookie_setzen(request: Request, response: Response, name: str, wert: str, sekunden: int) -> None:
    response.set_cookie(
        name,
        wert,
        max_age=sekunden,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(request),
        path="/",
    )


def _sitzung_setzen(request: Request, response: Response, token: str) -> None:
    stunden = request.app.state.einstellungen.sitzung_stunden
    _cookie_setzen(request, response, SITZUNGS_COOKIE, token, stunden * 3600)
    response.delete_cookie(EINRICHTUNGS_COOKIE, path="/")


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    dienst = _dienst(request)
    return {
        "eingerichtet": dienst.ist_eingerichtet(db),
        "angemeldet": dienst.sitzung_gueltig(db, request.cookies.get(SITZUNGS_COOKIE)),
        "version": __version__,
    }


@router.post("/einrichten")
def einrichten(
    eingabe: PasswortEingabe, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, str]:
    daten = _dienst(request).einrichtung_beginnen(db, eingabe.passwort)
    _cookie_setzen(request, response, EINRICHTUNGS_COOKIE, daten.einrichtungs_token, EINRICHTUNG_SEKUNDEN)
    return {"geheimnis": daten.geheimnis, "otpauth_url": daten.otpauth_url, "qr_svg": daten.qr_svg}


@router.post("/einrichten/bestaetigen")
def einrichten_bestaetigen(
    eingabe: CodeEingabe, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, bool]:
    token = _dienst(request).einrichtung_abschliessen(
        db, eingabe.code, request.cookies.get(EINRICHTUNGS_COOKIE)
    )
    _sitzung_setzen(request, response, token)
    return {"ok": True}


@router.post("/anmelden")
def anmelden(
    eingabe: AnmeldeEingabe, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, bool]:
    token = _dienst(request).anmelden(db, eingabe.passwort, eingabe.code)
    _sitzung_setzen(request, response, token)
    return {"ok": True}


@router.post("/abmelden")
def abmelden(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).abmelden(db, request.cookies.get(SITZUNGS_COOKIE))
    response.delete_cookie(SITZUNGS_COOKIE, path="/")
    return {"ok": True}
