"""Test-Gegenstellen: echte kleine Server, mit denen sich das Panel im Test verbindet."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

import httpx2
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class LaufenderServer:
    """Startet eine ASGI-App auf einem freien Port (in einem eigenen Thread)."""

    def __init__(self, app: ASGIApp, port: int = 0) -> None:
        """`port=0` nimmt einen freien Port; ein fester Port erlaubt, einen Server „neu zu starten“."""
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", port))
        self.port: int = self._socket.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._socket]}, daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> LaufenderServer:
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                return self
            time.sleep(0.02)
        raise RuntimeError("Test-Server startet nicht")

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


def freier_port() -> int:
    """Ein Port, auf dem garantiert nichts lauscht (für „nicht erreichbar“)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NurMitToken:
    """Lässt nur Anfragen mit dem richtigen Bearer-Token durch."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.erwartet = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and dict(scope["headers"]).get(b"authorization") != self.erwartet:
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def notizen_mcp_server() -> MCPServer:
    """Ein kleiner MCP-Server mit einer lesenden und zwei schreibenden Funktionen."""
    server = MCPServer("Notizen")
    notizen: list[str] = ["Milch kaufen"]

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def notizen_auflisten() -> list[str]:
        """Listet alle Notizen auf."""
        return list(notizen)

    @server.tool()
    def notiz_anlegen(text: str) -> str:
        """Legt eine neue Notiz an."""
        notizen.append(text)
        return f"Notiz {len(notizen)} gespeichert"

    @server.tool(annotations=ToolAnnotations(destructive_hint=True))
    def get_and_delete_all() -> str:
        """Löscht alles (klingt lesend, ist es aber nicht)."""
        notizen.clear()
        return "gelöscht"

    @server.tool()
    def search_notizen(begriff: str) -> list[str]:
        """Sucht Notizen (ohne Kennzeichnung, aber der Name ist eindeutig lesend)."""
        return [notiz for notiz in notizen if begriff.lower() in notiz.lower()]

    return server


class Artikel(BaseModel):
    name: str
    preis: float = 0.0


def artikel_rest_api(api_key: str | None = None) -> FastAPI:
    """Eine kleine REST-API mit OpenAPI-Beschreibung unter /openapi.json."""
    app = FastAPI(title="Artikel-API", version="1.0")
    artikel: dict[int, dict[str, Any]] = {1: {"id": 1, "name": "Apfel", "preis": 0.5}}
    app.state.aufrufe = []

    def pruefen(schluessel: str | None) -> None:
        if api_key is not None and schluessel != api_key:
            raise HTTPException(status_code=401, detail="falscher Key")

    @app.get("/artikel", operation_id="artikel_auflisten", summary="Alle Artikel auflisten")
    def auflisten(
        suche: str | None = None, x_api_key: str | None = Header(default=None)
    ) -> list[dict[str, Any]]:
        pruefen(x_api_key)
        app.state.aufrufe.append(("GET", "/artikel", suche))
        return [a for a in artikel.values() if not suche or suche.lower() in a["name"].lower()]

    @app.get("/artikel/{artikel_id}", operation_id="artikel_lesen", summary="Einen Artikel lesen")
    def lesen(artikel_id: int, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
        pruefen(x_api_key)
        if artikel_id not in artikel:
            raise HTTPException(status_code=404, detail="gibt es nicht")
        return artikel[artikel_id]

    @app.post("/artikel", operation_id="artikel_anlegen", summary="Einen Artikel anlegen")
    def anlegen(neu: Artikel, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
        pruefen(x_api_key)
        nummer = max(artikel) + 1
        artikel[nummer] = {"id": nummer, **neu.model_dump()}
        return artikel[nummer]

    @app.delete("/artikel/{artikel_id}", operation_id="artikel_loeschen", summary="Einen Artikel löschen")
    def loeschen(artikel_id: int, x_api_key: str | None = Header(default=None)) -> dict[str, bool]:
        pruefen(x_api_key)
        artikel.pop(artikel_id, None)
        return {"ok": True}

    if api_key is not None:
        original = app.openapi

        def mit_sicherheit() -> dict[str, Any]:
            schema = original()
            schema.setdefault("components", {})["securitySchemes"] = {
                "key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
            return schema

        app.openapi = mit_sicherheit  # type: ignore[method-assign]
    return app


def modell_server(modellname: str = "test-modell", api_key: str | None = None, pause: float = 0.0) -> FastAPI:
    """Ein kleiner OpenAI-kompatibler Server. `app.state.kaputt = True` lässt ihn mit 500 antworten."""
    app = FastAPI()
    app.state.anfragen = []
    app.state.kaputt = False
    app.state.pause = pause

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        koerper = await request.json()
        app.state.anfragen.append(
            {
                "model": koerper.get("model"),
                "auth": request.headers.get("authorization"),
                "stream": bool(koerper.get("stream")),
                "messages": koerper.get("messages"),
            }
        )
        if api_key is not None and request.headers.get("authorization") != f"Bearer {api_key}":
            return JSONResponse({"error": {"message": "invalid api key"}}, status_code=401)
        if app.state.kaputt:
            return JSONResponse({"error": {"message": "model crashed"}}, status_code=500)
        if koerper.get("model") != modellname:
            return JSONResponse(
                {"error": {"message": f"model {koerper.get('model')} not found"}}, status_code=404
            )
        if not koerper.get("messages"):
            return JSONResponse({"error": {"message": "messages must not be empty"}}, status_code=400)
        text = f"Antwort von {modellname} auf: {koerper['messages'][-1]['content']}"
        if koerper.get("stream"):

            async def strom() -> Any:
                for wort in text.split():
                    stueck = {
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": wort + " "}}],
                    }
                    yield f"data: {json.dumps(stueck)}\n\n"
                    await asyncio.sleep(app.state.pause)
                yield "data: [DONE]\n\n"

            return StreamingResponse(strom(), media_type="text/event-stream")
        await asyncio.sleep(app.state.pause)
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": modellname,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 40, "total_tokens": 52},
        }

    @app.get("/kein-openai/v1/chat/completions")
    def unsinn() -> dict[str, str]:
        return {"hallo": "welt"}

    @app.post("/kein-openai/v1/chat/completions")
    def unsinn_post() -> dict[str, str]:
        return {"hallo": "welt"}

    return app


# ---------------------------------------------------------------------- CalDAV (echter Server: Radicale)


class _OhneZugriffsprotokoll(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # kein Protokoll auf der Konsole
        return


class KalenderServer:
    """Ein echter CalDAV-Server (Radicale) mit einem Benutzer – als Gegenstelle für den Nextcloud-Kalender.

    Radicale spricht denselben Standard wie Nextcloud (CalDAV, RFC 4791); nur die Pfade sehen anders aus.
    """

    def __init__(
        self, ordner: Path, benutzer: str = "louis", passwort: str = "app-passwort-geheim-123"
    ) -> None:
        from radicale import Application, config

        self.benutzer, self.passwort = benutzer, passwort
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "benutzer").write_text(f"{benutzer}:{passwort}\n", encoding="utf-8")
        (ordner / "daten" / "collection-root").mkdir(parents=True, exist_ok=True)
        einstellungen = config.load()
        einstellungen.update(
            {
                "storage": {"filesystem_folder": str(ordner / "daten")},
                "auth": {
                    "type": "htpasswd",
                    "htpasswd_filename": str(ordner / "benutzer"),
                    "htpasswd_encryption": "plain",
                },
                "logging": {"level": "critical"},
            },
            "test",
            privileged=True,
        )
        self._server = make_server(
            "127.0.0.1", 0, Application(einstellungen), handler_class=_OhneZugriffsprotokoll
        )
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> KalenderServer:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()

    def _client(self) -> httpx2.Client:
        return httpx2.Client(auth=(self.benutzer, self.passwort), timeout=10)

    def kalender_anlegen(self, pfad: str, name: str, art: str = "VEVENT") -> str:
        """Legt einen Kalender an (das macht sonst die Oberfläche der Nextcloud). Gibt seine Adresse zurück."""
        koerper = (
            '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:set><d:prop>'
            f"<d:displayname>{name}</d:displayname><c:supported-calendar-component-set>"
            f'<c:comp name="{art}"/></c:supported-calendar-component-set></d:prop></d:set></c:mkcalendar>'
        )
        adresse = f"{self.url}/{self.benutzer}/{pfad}/"
        with self._client() as client:
            antwort = client.request(
                "MKCALENDAR", adresse, content=koerper.encode(), headers={"Content-Type": "application/xml"}
            )
        assert antwort.status_code == 201, antwort.text
        return adresse

    def ablegen(self, kalender: str, name: str, ical: str) -> None:
        """Legt einen Termin direkt auf dem Server ab – so, als käme er aus der Nextcloud-Oberfläche."""
        with self._client() as client:
            antwort = client.put(
                f"{self.url}/{self.benutzer}/{kalender}/{name}.ics",
                content=ical.replace("\n", "\r\n").encode(),
                headers={"Content-Type": "text/calendar; charset=utf-8"},
            )
        assert antwort.status_code in (201, 204), antwort.text

    def dateien(self, kalender: str) -> dict[str, str]:
        """Alle Termine eines Kalenders, so wie sie auf dem Server liegen (Name → Kalenderdaten)."""
        ordner = Path(self._server.get_app().configuration.get("storage", "filesystem_folder"))
        sammlung = ordner / "collection-root" / self.benutzer / kalender
        return {datei.name: datei.read_text(encoding="utf-8") for datei in sorted(sammlung.glob("*.ics"))}


# ---------------------------------------------------------------------- Home Assistant (nachgestellt)


class HomeAssistant:
    """Ein nachgestelltes Home Assistant: die REST-API und – auf Wunsch – sein MCP-Server.

    `mcp="http"` bietet den MCP-Server unter /api/mcp an (neuere Versionen), `mcp="sse"` unter
    /mcp_server/sse (ältere). Ohne Angabe gibt es nur die REST-API.
    """

    def __init__(self, token: str, mcp: str | None = None) -> None:
        self.token = token
        self.aufrufe: list[tuple[str, dict[str, Any]]] = []
        self.zustaende: dict[str, dict[str, Any]] = {
            kennung: {
                "entity_id": kennung,
                "state": zustand,
                "attributes": {"friendly_name": name, **eigenschaften},
                "last_changed": "2026-01-15T11:00:00+00:00",
            }
            for kennung, name, zustand, eigenschaften in (
                ("light.wohnzimmer", "Wohnzimmer Licht", "off", {"brightness": None}),
                ("light.kueche", "Küche Licht", "on", {"brightness": 180}),
                ("light.flur", "Flur Licht", "off", {}),
                ("switch.kaffeemaschine", "Kaffeemaschine", "off", {}),
                ("sensor.balkon_temperatur", "Balkon Temperatur", "4.5", {"unit_of_measurement": "°C"}),
                (
                    "sensor.wohnzimmer_luftfeuchtigkeit",
                    "Wohnzimmer Luftfeuchtigkeit",
                    "48",
                    {"unit_of_measurement": "%"},
                ),
                (
                    "climate.wohnzimmer",
                    "Heizung Wohnzimmer",
                    "heat",
                    {"temperature": 21, "current_temperature": 20.4},
                ),
                ("person.louis", "Louis", "home", {}),
                ("sun.sun", "Sonne", "above_horizon", {}),
            )
        }
        self.rest = self._rest_api(mcp)
        self.mcp_app: ASGIApp | None = None
        if mcp is not None:
            server = self._mcp_server()
            app = (
                server.streamable_http_app(streamable_http_path="/api/mcp")
                if mcp == "http"
                else server.sse_app(sse_path="/mcp_server/sse", message_path="/mcp_server/messages/")
            )
            self.mcp_app = app
            self._mcp_geschuetzt = NurMitToken(app, token)

    def _schalten(self, kennung: str, an: bool | None) -> dict[str, Any]:
        zustand = self.zustaende[kennung]
        neu = (zustand["state"] != "on") if an is None else an
        zustand["state"] = "on" if neu else "off"
        return zustand

    def _rest_api(self, mcp: str | None) -> FastAPI:
        app = FastAPI()

        def pruefen(authorization: str | None) -> None:
            if authorization != f"Bearer {self.token}":
                raise HTTPException(status_code=401, detail="Unauthorized")

        @app.get("/api/")
        def laeuft(authorization: str | None = Header(default=None)) -> dict[str, str]:
            pruefen(authorization)
            return {"message": "API running."}

        @app.get("/api/config")
        def konfig(authorization: str | None = Header(default=None)) -> dict[str, Any]:
            pruefen(authorization)
            komponenten = ["api", "light", "switch", "sensor", "climate"] + (["mcp_server"] if mcp else [])
            return {"location_name": "Zuhause", "version": "2026.11.0", "components": komponenten}

        @app.get("/api/states")
        def zustaende(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
            pruefen(authorization)
            return list(self.zustaende.values())

        @app.get("/api/states/{kennung}")
        def zustand(kennung: str, authorization: str | None = Header(default=None)) -> Any:
            pruefen(authorization)
            if kennung not in self.zustaende:
                return JSONResponse({"message": "Entity not found."}, status_code=404)
            return self.zustaende[kennung]

        @app.post("/api/services/{art}/{dienst}")
        async def dienst_aufrufen(
            art: str, dienst: str, request: Request, authorization: str | None = Header(default=None)
        ) -> Any:
            pruefen(authorization)
            daten = await request.json()
            self.aufrufe.append((f"{art}.{dienst}", daten))
            if dienst not in ("turn_on", "turn_off", "toggle", "set_temperature"):
                return JSONResponse({"message": "Service not found."}, status_code=400)
            kennung = daten.get("entity_id")
            if kennung not in self.zustaende:
                return []
            if dienst == "set_temperature":
                self.zustaende[kennung]["attributes"]["temperature"] = daten.get("temperature")
                return [self.zustaende[kennung]]
            if "brightness_pct" in daten:
                self.zustaende[kennung]["attributes"]["brightness"] = round(daten["brightness_pct"] * 2.55)
            return [self._schalten(kennung, {"turn_on": True, "turn_off": False, "toggle": None}[dienst])]

        return app

    def _mcp_server(self) -> MCPServer:
        """Die Werkzeuge, wie sie der MCP-Server von Home Assistant anbietet (Auswahl)."""
        server = MCPServer("Home Assistant")

        def finden(name: str) -> str:
            for kennung, zustand in self.zustaende.items():
                if zustand["attributes"]["friendly_name"].lower() == name.lower():
                    return kennung
            raise ValueError(f"Kein Gerät mit dem Namen {name}")

        @server.tool(name="HassTurnOn", description="Turns on/opens a device or entity")
        def einschalten(name: str) -> str:
            self._schalten(finden(name), True)
            return f"Turned on {name}"

        @server.tool(name="HassTurnOff", description="Turns off/closes a device or entity")
        def ausschalten(name: str) -> str:
            self._schalten(finden(name), False)
            return f"Turned off {name}"

        @server.tool(
            name="GetLiveContext",
            description="Provides real-time information about the current state of devices",
        )
        def lage() -> str:
            return "\n".join(
                f"- {z['attributes']['friendly_name']}: {z['state']}" for z in self.zustaende.values()
            )

        return server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await (self.mcp_app or self.rest)(scope, receive, send)
            return
        pfad = scope.get("path", "")
        if self.mcp_app is not None and pfad.startswith(("/api/mcp", "/mcp_server")):
            await self._mcp_geschuetzt(scope, receive, send)
            return
        await self.rest(scope, receive, send)
