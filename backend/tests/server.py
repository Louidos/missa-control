"""Test-Gegenstellen: echte kleine Server, mit denen sich das Panel im Test verbindet."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Any

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

    def __init__(self, app: ASGIApp) -> None:
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
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
