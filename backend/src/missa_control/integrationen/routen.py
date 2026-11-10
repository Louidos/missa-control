"""API der Seiten „Katalog“ und „Integrationen“."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.fehler import PanelFehler
from missa_control.integrationen.dienst import IntegrationsDienst, ergebnis_als_text, gateway_name
from missa_control.integrationen.katalog import MAX_ZIP_BYTES
from missa_control.integrationen.typen import IntegrationsFehler

router = APIRouter(prefix="/api", tags=["Integrationen"])


class TestEingabe(BaseModel):
    manifest_id: str
    konfig: dict[str, Any] = Field(default_factory=dict)
    integration_id: int | None = None


class IntegrationNeu(BaseModel):
    manifest_id: str
    name: str = Field(default="", max_length=80)
    konfig: dict[str, Any] = Field(default_factory=dict)
    rechte: dict[str, str] = Field(default_factory=dict)
    test_id: str | None = None


class IntegrationAenderung(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    konfig: dict[str, Any] | None = None
    aktiv: bool | None = None
    rechte: dict[str, str] | None = None


class AufrufEingabe(BaseModel):
    funktion: str
    argumente: dict[str, Any] = Field(default_factory=dict)


def _dienst(request: Request) -> IntegrationsDienst:
    return request.app.state.integrationen


# ---------- Katalog ----------


@router.get("/katalog")
def katalog(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _dienst(request).katalog_ansicht(db)


@router.post("/katalog/einlesen")
def katalog_einlesen(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    dienst.katalog.einlesen()
    return dienst.katalog_ansicht(db)


@router.post("/katalog/hochladen")
async def katalog_hochladen(
    request: Request, datei: UploadFile = File(...), ersetzen: bool = Form(False)
) -> dict[str, Any]:
    inhalt = await datei.read(MAX_ZIP_BYTES + 1)
    manifest, ersetzt = _dienst(request).katalog.zip_hochladen(inhalt, ersetzen=ersetzen)
    return {"id": manifest.id, "name": manifest.name, "ersetzt": ersetzt}


@router.delete("/katalog/{manifest_id}")
def katalog_entfernen(manifest_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    dienst = _dienst(request)
    if any(eintrag["manifest_id"] == manifest_id for eintrag in dienst.alle(db)):
        raise PanelFehler(
            409,
            "Diese Integration ist noch eingerichtet.",
            "Zuerst unter „Integrationen“ entfernen, dann aus dem Katalog löschen.",
        )
    dienst.katalog.eigene_entfernen(manifest_id)
    return {"ok": True}


# ---------- eingerichtete Integrationen ----------


@router.post("/integrationen/testen")
async def testen(eingabe: TestEingabe, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _dienst(request).testen(
        db, manifest_id=eingabe.manifest_id, konfig=eingabe.konfig, integration_id=eingabe.integration_id
    )


@router.get("/integrationen")
def auflisten(request: Request, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return _dienst(request).alle(db)


@router.post("/integrationen", status_code=201)
async def anlegen(eingabe: IntegrationNeu, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(await dienst.anlegen(db, **eingabe.model_dump()))


@router.get("/integrationen/{integration_id}")
def holen(integration_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(dienst.holen(db, integration_id))


@router.put("/integrationen/{integration_id}")
async def aendern(
    integration_id: int, eingabe: IntegrationAenderung, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(await dienst.aendern(db, integration_id, **eingabe.model_dump()))


@router.post("/integrationen/{integration_id}/testen")
async def erneut_testen(
    integration_id: int, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    dienst = _dienst(request)
    return dienst.ansicht(await dienst.erneut_testen(db, integration_id))


@router.post("/integrationen/{integration_id}/aufrufen")
async def aufrufen(
    integration_id: int, eingabe: AufrufEingabe, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """„Ausprobieren“ im Panel: ruft eine Funktion direkt auf (unabhängig von den Rechten für Missa)."""
    dienst = _dienst(request)
    integration = dienst.holen(db, integration_id)
    name = gateway_name(integration.kennung, eingabe.funktion)
    start = time.monotonic()

    def protokollieren(ok: bool, fehler: str = "") -> None:
        request.app.state.protokoll.eintragen(
            quelle="panel",
            client_name="Panel (Ausprobieren)",
            integration_name=integration.name,
            funktion=name,
            ok=ok,
            fehler=fehler,
            dauer_ms=int((time.monotonic() - start) * 1000),
        )

    try:
        ergebnis = await dienst.aufrufen(db, integration, eingabe.funktion, eingabe.argumente)
    except IntegrationsFehler as fehler:
        protokollieren(False, fehler.meldung)
        return {"ok": False, "meldung": fehler.meldung, "hinweis": fehler.hinweis}
    text = ergebnis_als_text(ergebnis)
    protokollieren(not ergebnis.ist_fehler, text[:300] if ergebnis.ist_fehler else "")
    return {"ok": not ergebnis.ist_fehler, "ergebnis": text}


@router.post("/integrationen/{integration_id}/webhook/erneuern")
def webhook_erneuern(integration_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Gibt einem Webhook eine neue geheime Adresse. Die alte gilt sofort nicht mehr."""
    integration = request.app.state.webhooks.erneuern(db, integration_id)
    return _dienst(request).ansicht(integration)


@router.delete("/integrationen/{integration_id}")
def entfernen(integration_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    _dienst(request).entfernen(db, integration_id)
    return {"ok": True}
