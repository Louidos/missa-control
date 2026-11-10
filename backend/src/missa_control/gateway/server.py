"""Der MCP-Endpoint `/mcp`: bündelt die Funktionen aller aktiven Integrationen für Missa.

- Sichtbar sind nur Funktionen aktiver Integrationen, die nicht „gesperrt“ sind.
- Namen tragen die Vorsilbe der Integration (z. B. `kalender_termine_anzeigen`).
- „Erst nachfragen“-Funktionen werden angehalten, bis im Panel entschieden ist.
- Zugänge setzt das Panel ein – der Client bekommt sie nie zu sehen.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.types import Receive, Scope, Send

from missa_control import __version__
from missa_control.auth.schutz import CLIENT_SCHLUESSEL
from missa_control.clients.dienst import ClientAngaben
from missa_control.db import Datenbank
from missa_control.fehler import fehler_antwort
from missa_control.gateway.freigaben import FreigabeDienst
from missa_control.gateway.modelle import FREIGABE_ABGELAUFEN, FREIGABE_ABGELEHNT, FREIGABE_ERLAUBT
from missa_control.gateway.protokoll import ProtokollDienst
from missa_control.integrationen.dienst import IntegrationsDienst, ergebnis_als_text, gateway_name
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.integrationen.typen import AufrufErgebnis, IntegrationsFehler

log = logging.getLogger(__name__)

NACHFRAGE_HINWEIS = (
    " (Wird erst ausgeführt, nachdem der Besitzer im Panel zugestimmt hat – das kann einige Minuten dauern.)"
)
ANLEITUNG = (
    "Missa Control bündelt alle Funktionen, die der Besitzer für Missa freigegeben hat. "
    "Manche Funktionen laufen erst nach einer Freigabe im Panel; eine Ablehnung oder ein Zeitablauf "
    "kommt als verständliche Fehlermeldung zurück."
)


@dataclass
class Ziel:
    integration: Integration
    funktion: Funktion


def sichtbare_funktionen(db: Session) -> list[tuple[str, Integration, Funktion]]:
    """Alle Funktionen, die ein Client sehen darf: aktiv, vorhanden und nicht gesperrt."""
    abfrage = (
        select(Integration)
        .where(Integration.aktiv.is_(True))
        .options(selectinload(Integration.funktionen))
        .order_by(Integration.id)
    )
    sichtbar: list[tuple[str, Integration, Funktion]] = []
    vergeben: set[str] = set()
    for integration in db.scalars(abfrage):
        for funktion in integration.funktionen:
            if not funktion.vorhanden or funktion.recht == "gesperrt":
                continue
            name = gateway_name(integration.kennung, funktion.name)
            if name in vergeben:  # sehr seltene Namensgleichheit: die zuerst eingerichtete gewinnt
                continue
            vergeben.add(name)
            sichtbar.append((name, integration, funktion))
    return sichtbar


def _text(inhalt: str, fehler: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=inhalt)], is_error=fehler)


class Gateway:
    def __init__(
        self,
        *,
        datenbank: Datenbank,
        integrationen: IntegrationsDienst,
        freigaben: FreigabeDienst,
        protokoll: ProtokollDienst,
    ) -> None:
        self.datenbank = datenbank
        self.integrationen = integrationen
        self.freigaben = freigaben
        self.protokoll = protokoll
        self.server: Server[Any] = Server(
            "missa-control",
            version=__version__,
            title="Missa Control",
            instructions=ANLEITUNG,
            on_list_tools=self._funktionen_auflisten,
            on_call_tool=self._funktion_aufrufen,
        )
        # Je laufender Ereignisschleife ein Endpoint (im Betrieb genau einer).
        self._aktiv: dict[asyncio.AbstractEventLoop, StreamableHTTPASGIApp] = {}

    @asynccontextmanager
    async def laufen(self) -> AsyncIterator[None]:
        """Hält den Endpoint am Leben, solange das Panel läuft (wird beim Start des Panels betreten)."""
        # Zustandslos: jede Anfrage steht für sich, das Panel kann jederzeit neu starten.
        # Der Schutz vor fremden Host-Namen entfällt, weil ohnehin jeder Zugriff ein Client-Token braucht.
        sitzungen = StreamableHTTPSessionManager(
            app=self.server,
            stateless=True,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        loop = asyncio.get_running_loop()
        async with sitzungen.run():
            self._aktiv[loop] = StreamableHTTPASGIApp(sitzungen)
            try:
                yield
            finally:
                self._aktiv.pop(loop, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        endpunkt = self._aktiv.get(asyncio.get_running_loop())
        if endpunkt is None:
            antwort = fehler_antwort(
                503, "Das Gateway startet gerade.", "Bitte in ein paar Sekunden erneut versuchen."
            )
            await antwort(scope, receive, send)
            return
        await endpunkt(scope, receive, send)

    # ---------- MCP: Funktionen auflisten ----------

    async def _funktionen_auflisten(
        self, ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        with self.datenbank.sitzung() as db:
            werkzeuge = [
                types.Tool(
                    name=name,
                    description=funktion.beschreibung
                    + (NACHFRAGE_HINWEIS if funktion.recht == "nachfragen" else ""),
                    input_schema=funktion.parameter or {"type": "object", "properties": {}},
                    annotations=types.ToolAnnotations(read_only_hint=not funktion.schreibend),
                )
                for name, _, funktion in sichtbare_funktionen(db)
            ]
        return types.ListToolsResult(tools=werkzeuge)

    # ---------- MCP: Funktion aufrufen ----------

    async def _funktion_aufrufen(
        self, ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        client = _client_aus(ctx)
        start = time.monotonic()
        freigabe = "ohne"
        integration_name = ""

        def protokollieren(ok: bool, fehler: str = "") -> None:
            self.protokoll.eintragen(
                quelle="gateway",
                client_name=client.name,
                integration_name=integration_name,
                funktion=params.name,
                ok=ok,
                fehler=fehler,
                dauer_ms=int((time.monotonic() - start) * 1000),
                freigabe=freigabe,
            )

        with self.datenbank.sitzung() as db:
            treffer = next((t for t in sichtbare_funktionen(db) if t[0] == params.name), None)
            if treffer is None:
                meldung = (
                    f"Die Funktion „{params.name}“ gibt es nicht oder sie ist für Missa nicht freigegeben. "
                    "Die aktuell verfügbaren Funktionen liefert tools/list."
                )
                protokollieren(False, meldung)
                return _text(meldung, fehler=True)
            _, integration, funktion = treffer
            integration_name = integration.name
            argumente = dict(params.arguments or {})
            braucht_freigabe = funktion.recht == "nachfragen"
            beschreibung = funktion.beschreibung

        if braucht_freigabe:
            freigabe = await self.freigaben.anfragen(
                client_name=client.name,
                integration_name=integration_name,
                funktion=params.name,
                beschreibung=beschreibung,
                argumente=argumente,
            )
            if freigabe != FREIGABE_ERLAUBT:
                meldung = _ablehnung(params.name, freigabe, self.freigaben.frist_sekunden)
                protokollieren(False, meldung)
                return _text(meldung, fehler=True)

        with self.datenbank.sitzung() as db:
            integration = db.get(Integration, integration.id)
            if integration is None or not integration.aktiv:
                meldung = f"Die Integration zu „{params.name}“ wurde inzwischen deaktiviert oder entfernt."
                protokollieren(False, meldung)
                return _text(meldung, fehler=True)
            try:
                ergebnis = await self.integrationen.aufrufen(db, integration, funktion.name, argumente)
            except IntegrationsFehler as fehler:
                meldung = fehler.meldung + (f" Hinweis: {fehler.hinweis}" if fehler.hinweis else "")
                protokollieren(False, meldung)
                return _text(meldung, fehler=True)
            except Exception as fehler:
                log.exception("Unerwarteter Fehler beim Aufruf von %s", params.name)
                protokollieren(False, f"Unerwarteter Fehler: {type(fehler).__name__}")
                return _text("Beim Ausführen ist ein unerwarteter Fehler aufgetreten.", fehler=True)

        protokollieren(
            not ergebnis.ist_fehler, ergebnis_als_text(ergebnis)[:300] if ergebnis.ist_fehler else ""
        )
        return _als_mcp(ergebnis)


def _client_aus(ctx: ServerRequestContext[Any]) -> ClientAngaben:
    anfrage = ctx.request
    client = anfrage.scope.get(CLIENT_SCHLUESSEL) if anfrage is not None else None
    return client if isinstance(client, ClientAngaben) else ClientAngaben(id=0, name="unbekannt")


def _ablehnung(funktion: str, status: str, frist_sekunden: float) -> str:
    if status == FREIGABE_ABGELEHNT:
        return f"Die Aktion „{funktion}“ wurde vom Besitzer im Panel abgelehnt und nicht ausgeführt."
    if status == FREIGABE_ABGELAUFEN:
        minuten = max(round(frist_sekunden / 60), 1)
        return (
            f"Die Aktion „{funktion}“ wurde nicht ausgeführt: Innerhalb von {minuten} Minute(n) hat niemand "
            "im Panel zugestimmt. Bitte den Besitzer bitten, die Anfrage unter „Freigaben“ zu erlauben, "
            "und es dann erneut versuchen."
        )
    return f"Die Aktion „{funktion}“ wurde nicht ausgeführt."


def _als_mcp(ergebnis: AufrufErgebnis) -> types.CallToolResult:
    if ergebnis.mcp_inhalt is not None:
        # Antwort eines MCP-Servers: unverändert durchreichen (auch Bilder und andere Inhalte).
        return types.CallToolResult(
            content=ergebnis.mcp_inhalt,
            structured_content=ergebnis.strukturiert,
            is_error=ergebnis.ist_fehler,
        )
    strukturiert = ergebnis.wert if isinstance(ergebnis.wert, dict) else None
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=ergebnis_als_text(ergebnis))],
        structured_content=strukturiert,
        is_error=ergebnis.ist_fehler,
    )
