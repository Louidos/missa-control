"""FastAPI-App von Missa Control."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.routing import Route

from missa_control import __version__
from missa_control.auth import routen as auth_routen
from missa_control.auth.dienst import AuthDienst
from missa_control.auth.schutz import Zugriffsschutz, ist_geschuetzt
from missa_control.clients import routen as clients_routen
from missa_control.clients.dienst import ClientDienst
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.ereignisse import routen as ereignisse_routen
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.fehler import fehlerbehandlung_einrichten
from missa_control.gateway import routen as gateway_routen
from missa_control.gateway.freigaben import FreigabeDienst
from missa_control.gateway.protokoll import ProtokollDienst
from missa_control.gateway.server import Gateway
from missa_control.integrationen import routen as integrationen_routen
from missa_control.integrationen.dienst import IntegrationsDienst
from missa_control.integrationen.katalog import Katalog
from missa_control.krypto import Krypto
from missa_control.modellverwaltung import routen as modell_routen
from missa_control.modellverwaltung.dienst import ModellDienst
from missa_control.profil import routen as profil_routen
from missa_control.profil.dienst import ProfilDienst
from missa_control.serverlast import routen as serverlast_routen
from missa_control.serverlast.dienst import ServerlastDienst
from missa_control.zugaenge import routen as zugaenge_routen
from missa_control.zugaenge.dienst import ZugangsDienst
from missa_control.zugaenge.schwaerzen import SCHWAERZER, log_schutz_einrichten

log = logging.getLogger(__name__)

AUFRAEUMEN_SEKUNDEN = 3600


def create_app(einstellungen: Einstellungen | None = None) -> FastAPI:
    """Erzeugt die App. Für Tests können eigene Einstellungen übergeben werden."""
    einstellungen = einstellungen or Einstellungen.aus_umgebung()
    datenbank = Datenbank(einstellungen.datenbank_pfad)
    datenbank.migrieren()
    krypto = Krypto(einstellungen.secret_key, einstellungen.encryption_key)
    log_schutz_einrichten()

    auth = AuthDienst(einstellungen, krypto)
    clients = ClientDienst(krypto)
    ereignisse = EreignisDienst(datenbank)
    protokoll = ProtokollDienst(datenbank)
    freigaben = FreigabeDienst(datenbank, ereignisse, einstellungen.freigabe_sekunden)
    zugaenge = ZugangsDienst(krypto, SCHWAERZER)

    app = FastAPI(
        title="Missa Control",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lebenszyklus,
    )
    app.state.einstellungen = einstellungen
    app.state.datenbank = datenbank
    app.state.krypto = krypto
    app.state.auth = auth
    app.state.clients = clients
    app.state.ereignisse = ereignisse
    app.state.protokoll = protokoll
    app.state.freigaben = freigaben
    app.state.zugaenge = zugaenge
    app.state.serverlast = ServerlastDienst(einstellungen, datenbank)
    app.state.integrationen = IntegrationsDienst(
        katalog=Katalog(einstellungen.integrations_ordner, einstellungen.eigene_integrationen_ordner),
        zugaenge=zugaenge,
        panel=app.state,
    )
    app.state.integrationen.ereignis_melden = ereignisse.melden
    app.state.modelle = ModellDienst(datenbank, zugaenge)
    app.state.profil = ProfilDienst(
        app.state.modelle, einstellungen.config_ordner, einstellungen.testchat_sekunden
    )
    zugaenge.verwendung_quellen = [
        app.state.integrationen.zugang_verwendung,
        app.state.modelle.zugang_verwendung,
    ]
    app.state.gateway = Gateway(
        datenbank=datenbank, integrationen=app.state.integrationen, freigaben=freigaben, protokoll=protokoll
    )

    fehlerbehandlung_einrichten(app)
    app.add_middleware(Zugriffsschutz, auth=auth, clients=clients, datenbank=datenbank)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth_routen.router)
    app.include_router(zugaenge_routen.router)
    app.include_router(integrationen_routen.router)
    app.include_router(clients_routen.router)
    app.include_router(gateway_routen.panel_router)
    app.include_router(gateway_routen.konfig_router)
    app.include_router(ereignisse_routen.client_router)
    app.include_router(ereignisse_routen.panel_router)
    app.include_router(modell_routen.panel_router)
    app.include_router(modell_routen.proxy_router)
    app.include_router(profil_routen.router)
    app.include_router(serverlast_routen.router)
    # Der MCP-Anschluss ist eine eigene kleine ASGI-App (Zugriff nur mit Client-Token, siehe Zugriffsschutz).
    app.router.routes.append(Route("/mcp", endpoint=app.state.gateway))
    app.router.routes.append(Route("/mcp/", endpoint=app.state.gateway))

    if einstellungen.frontend_ordner is not None:
        _frontend_einbinden(app, einstellungen.frontend_ordner)
    return app


@contextlib.asynccontextmanager
async def _lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
    """Läuft, solange das Panel läuft: hält das Gateway offen und räumt regelmässig alte Daten weg."""
    async with app.state.gateway.laufen():
        aufgaben = [asyncio.create_task(_regelmaessig_aufraeumen(app))]
        if app.state.serverlast.intervall > 0:
            aufgaben.append(asyncio.create_task(app.state.serverlast.laufen()))
        try:
            yield
        finally:
            for aufgabe in aufgaben:
                aufgabe.cancel()
            for aufgabe in aufgaben:
                with contextlib.suppress(asyncio.CancelledError):
                    await aufgabe


def alte_daten_loeschen(app: FastAPI) -> None:
    """Protokoll, Ereignisse und entschiedene Freigaben werden nach 30 Tagen gelöscht, die Modell-Statistik nach 7."""
    tage = app.state.einstellungen.aufbewahrung_tage
    geloescht = (
        app.state.protokoll.aufraeumen(tage)
        + app.state.ereignisse.aufraeumen(tage)
        + app.state.freigaben.aufraeumen(tage)
        + app.state.modelle.aufraeumen()  # Modell-Statistik: 7 Tage
        + app.state.serverlast.aufraeumen()  # Messwerte: 7 Tage
    )
    if geloescht:
        log.info("Aufgeräumt: %s Einträge älter als %s Tage gelöscht", geloescht, tage)


async def _regelmaessig_aufraeumen(app: FastAPI) -> None:
    while True:
        try:
            await asyncio.to_thread(alte_daten_loeschen, app)
        except Exception:
            log.exception("Aufräumen fehlgeschlagen")
        await asyncio.sleep(AUFRAEUMEN_SEKUNDEN)


def _frontend_einbinden(app: FastAPI, ordner: Path) -> None:
    """Liefert die gebaute Oberfläche aus; unbekannte Pfade bekommen `index.html` (Single-Page-App)."""

    @app.get("/{pfad:path}", include_in_schema=False)
    def frontend(pfad: str) -> FileResponse:
        if ist_geschuetzt("/" + pfad):
            raise HTTPException(status_code=404)
        datei = (ordner / pfad).resolve()
        if pfad and datei.is_file() and datei.is_relative_to(ordner):
            return FileResponse(datei)
        index = ordner / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Die Oberfläche ist nicht gebaut.")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
