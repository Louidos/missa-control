"""Helfer für Tests: stellbare Uhr und Abkürzungen für Einrichtung und Codes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pyotp
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

PASSWORT = "ein-langes-test-passwort"


class Uhr:
    """Ersetzt die Systemzeit des Panels, damit Tests Zeit vergehen lassen können."""

    def __init__(self) -> None:
        self.jetzt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.jetzt

    def vor(self, **zeitraum: float) -> None:
        self.jetzt += timedelta(**zeitraum)


def code_fuer(geheimnis: str, uhr: Uhr) -> str:
    """Der Code, den die Authenticator-App gerade anzeigen würde."""
    return pyotp.TOTP(geheimnis).at(int(uhr.jetzt.timestamp()))


def einrichten(client: TestClient, uhr: Uhr, passwort: str = PASSWORT) -> str:
    """Führt die Einrichtung durch (danach ist der Client angemeldet) und gibt das 2FA-Geheimnis zurück."""
    antwort = client.post("/api/auth/einrichten", json={"passwort": passwort})
    assert antwort.status_code == 200, antwort.text
    geheimnis = antwort.json()["geheimnis"]
    antwort = client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    assert antwort.status_code == 200, antwort.text
    return geheimnis


# ---------------------------------------------------------------------- Integrationen und Gateway


def integration_anlegen(
    admin: TestClient, manifest_id: str, konfig: dict[str, Any] | None = None, name: str = ""
) -> dict[str, Any]:
    """Richtet eine Integration ein, wie es der Assistent tut: testen, dann aktivieren."""
    test = admin.post(
        "/api/integrationen/testen", json={"manifest_id": manifest_id, "konfig": konfig or {}}
    ).json()
    assert test["ok"] is True, test
    antwort = admin.post(
        "/api/integrationen",
        json={"manifest_id": manifest_id, "name": name, "konfig": konfig or {}, "test_id": test["test_id"]},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def client_token(admin: TestClient, name: str = "missa-core") -> str:
    """Legt einen Client an und gibt seinen Token zurück."""
    antwort = admin.post("/api/clients", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["token"]


@asynccontextmanager
async def mcp_client(panel_url: str, token: str) -> AsyncIterator[Client]:
    """Ein echter MCP-Client am Gateway – so, wie sich missa-core verbinden würde."""
    kopf = {"Authorization": f"Bearer {token}"}
    async with (
        httpx2.AsyncClient(headers=kopf, timeout=httpx2.Timeout(20.0)) as http,
        Client(streamable_http_client(panel_url + "/mcp", http_client=http)) as client,
    ):
        yield client


def mcp_text(ergebnis: Any) -> str:
    return "\n".join(block.text for block in ergebnis.content if hasattr(block, "text"))


async def warte_auf(bedingung: Callable[[], Any], sekunden: float = 5.0) -> Any:
    """Wartet, bis `bedingung()` etwas Wahres liefert, und gibt es zurück."""
    for _ in range(int(sekunden / 0.02)):
        wert = bedingung()
        if wert:
            return wert
        await asyncio.sleep(0.02)
    raise AssertionError("Bedingung wurde nicht rechtzeitig erfüllt")
