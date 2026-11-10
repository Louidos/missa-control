"""Art `mcp`: ein beliebiger MCP-Server per URL (Streamable HTTP oder SSE)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from missa_control.integrationen.kontext import Kontext, auth_header
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, FunktionsInfo, IntegrationsFehler, TestErgebnis

VERBINDEN_SEKUNDEN = 20.0
AUFRUF_SEKUNDEN = 120.0
TRANSPORT_HTTP = "http"
TRANSPORT_SSE = "sse"

# Namen, die fast sicher nur lesen – für MCP-Server, die keine Angabe dazu machen.
_LESEND = re.compile(
    r"^(get|list|search|find|read|fetch|query|describe|show|lookup|check|count|view|"
    r"hole|liste|suche|zeige|lese|pruefe)([_\-A-Z]|$)"
)


def url_pruefen(url: str) -> str:
    url = url.strip()
    teile = urlsplit(url)
    if teile.scheme not in ("http", "https") or not teile.netloc:
        raise IntegrationsFehler(
            "Die URL ist ungültig.",
            "Eine vollständige Adresse angeben, z. B. http://192.168.1.20:8000/mcp",
        )
    return url


def ist_lesend(name: str, anmerkungen: Any) -> bool:
    """Lesend ist, was der Server so kennzeichnet – oder was eindeutig danach klingt."""
    hinweis = getattr(anmerkungen, "read_only_hint", None)
    if hinweis is not None:
        return bool(hinweis)
    if getattr(anmerkungen, "destructive_hint", None):
        return False
    return bool(_LESEND.match(name))


@asynccontextmanager
async def _client(url: str, headers: dict[str, str], transport: str) -> AsyncIterator[Client]:
    if transport == TRANSPORT_SSE:
        async with Client(sse_client(url, headers=headers, timeout=VERBINDEN_SEKUNDEN)) as client:
            yield client
        return
    zeitlimit = httpx2.Timeout(VERBINDEN_SEKUNDEN, read=AUFRUF_SEKUNDEN + 30)
    async with (
        httpx2.AsyncClient(headers=headers, timeout=zeitlimit) as http,
        Client(streamable_http_client(url, http_client=http)) as client,
    ):
        yield client


def _reihenfolge(url: str, gewuenscht: str, bekannt: str | None) -> list[str]:
    """Welche Verbindungsarten in welcher Reihenfolge versucht werden."""
    if gewuenscht in (TRANSPORT_HTTP, TRANSPORT_SSE):
        return [gewuenscht]
    if bekannt in (TRANSPORT_HTTP, TRANSPORT_SSE):
        return [bekannt]
    if urlsplit(url).path.rstrip("/").endswith("/sse"):
        return [TRANSPORT_SSE, TRANSPORT_HTTP]
    return [TRANSPORT_HTTP, TRANSPORT_SSE]


def _endgueltig(fehler: BaseException) -> bool:
    """Fehler, bei denen eine andere Verbindungsart sicher nicht hilft (nicht erreichbar, Zugang falsch)."""
    offen: list[BaseException] = [fehler]
    while offen:
        aktuell = offen.pop()
        if isinstance(aktuell, BaseExceptionGroup):
            offen.extend(aktuell.exceptions)
            continue
        if isinstance(aktuell, httpx2.ConnectError | httpx2.ConnectTimeout):
            return True
        if isinstance(aktuell, httpx2.HTTPStatusError) and aktuell.response.status_code in (401, 403):
            return True
        if aktuell.__cause__ is not None:
            offen.append(aktuell.__cause__)
    return False


@asynccontextmanager
async def mcp_verbinden(
    url: str, headers: dict[str, str], *, gewuenscht: str = "auto", bekannt: str | None = None
) -> AsyncIterator[tuple[Client, str]]:
    """Verbindet sich mit einem MCP-Server und liefert (Client, verwendete Verbindungsart)."""
    reihenfolge = _reihenfolge(url, gewuenscht, bekannt)
    erster_fehler: BaseException | None = None
    for transport in reihenfolge:
        verbunden = False
        try:
            async with _client(url, headers, transport) as client:
                verbunden = True
                yield client, transport
            return
        except Exception as fehler:
            if verbunden or _endgueltig(fehler):
                raise
            if transport == reihenfolge[-1]:
                # Beide Verbindungsarten sind gescheitert: der erste Fehler sagt meist mehr aus.
                if erster_fehler is not None:
                    raise erster_fehler from fehler
                raise
            erster_fehler = fehler


def _werkzeug_als_funktion(werkzeug: Any) -> FunktionsInfo:
    schema = dict(werkzeug.input_schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return FunktionsInfo(
        name=werkzeug.name,
        beschreibung=(werkzeug.description or werkzeug.title or werkzeug.name).strip(),
        parameter=schema,
        schreibend=not ist_lesend(werkzeug.name, werkzeug.annotations),
    )


async def werkzeuge_auflisten(client: Client) -> list[FunktionsInfo]:
    funktionen: list[FunktionsInfo] = []
    cursor: str | None = None
    for _ in range(50):  # höchstens 50 Seiten
        seite = await client.list_tools(cursor=cursor)
        funktionen.extend(_werkzeug_als_funktion(werkzeug) for werkzeug in seite.tools)
        cursor = seite.next_cursor
        if not cursor:
            break
    return funktionen


class McpAdapter:
    art = "mcp"

    @staticmethod
    def _zugangsdaten(kontext: Kontext) -> tuple[str, dict[str, str], str]:
        url = url_pruefen(str(kontext.konfig.get("url", "")))
        headers = auth_header(kontext.zugang_optional("zugang"))
        return url, headers, str(kontext.konfig.get("verbindung") or "auto")

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        url, headers, gewuenscht = self._zugangsdaten(kontext)
        with anyio.fail_after(VERBINDEN_SEKUNDEN + 10):
            async with mcp_verbinden(url, headers, gewuenscht=gewuenscht) as (client, transport):
                funktionen = await werkzeuge_auflisten(client)
                server = client.server_info
        name = (server.title or server.name) if server else None
        art = "Streamable HTTP" if transport == TRANSPORT_HTTP else "SSE"
        return TestErgebnis(
            ok=True,
            meldung=f"Verbunden mit {name or 'dem MCP-Server'} – {len(funktionen)} Funktion(en) gefunden.",
            details=[f"Verbindungsart: {art}"],
            funktionen=funktionen,
            zustand={"transport": transport},
        )

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        url, headers, gewuenscht = self._zugangsdaten(kontext)
        try:
            with anyio.fail_after(AUFRUF_SEKUNDEN):
                async with mcp_verbinden(
                    url, headers, gewuenscht=gewuenscht, bekannt=kontext.zustand.get("transport")
                ) as (client, _):
                    ergebnis = await client.call_tool(funktion.name, argumente)
        except TimeoutError as fehler:
            raise IntegrationsFehler(
                f"Der MCP-Server hat nicht innerhalb von {int(AUFRUF_SEKUNDEN)} Sekunden geantwortet.",
                "Der Server ist erreichbar, braucht aber zu lange. Später erneut versuchen.",
            ) from fehler
        return AufrufErgebnis(
            mcp_inhalt=list(ergebnis.content),
            strukturiert=ergebnis.structured_content,
            ist_fehler=bool(ergebnis.is_error),
        )
