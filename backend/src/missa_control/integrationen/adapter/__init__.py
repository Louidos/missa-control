"""Adapter: je Integrationsart die Logik für „Verbindung testen“ und „Funktion aufrufen“."""

from __future__ import annotations

from typing import Any, Protocol

from missa_control.integrationen.adapter.mcp import McpAdapter
from missa_control.integrationen.adapter.openapi import OpenApiAdapter
from missa_control.integrationen.adapter.python import PythonAdapter
from missa_control.integrationen.adapter.webhook import WebhookAdapter
from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, TestErgebnis


class Adapter(Protocol):
    art: str

    async def testen(self, kontext: Kontext) -> TestErgebnis: ...

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis: ...


def standard_adapter() -> dict[str, Adapter]:
    adapter: tuple[Adapter, ...] = (McpAdapter(), OpenApiAdapter(), PythonAdapter(), WebhookAdapter())
    return {einer.art: einer for einer in adapter}
