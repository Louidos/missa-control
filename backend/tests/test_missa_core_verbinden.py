"""„Missa-Core verbinden“: zwei Zeilen für missa-core und die Anzeige, ob Missa wirklich abholt."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from hilfen import Uhr
from missa_control.config import Einstellungen
from server import LaufenderServer
from test_gateway import mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
def einstellungen(einstellungen: Einstellungen) -> Einstellungen:
    return dataclasses.replace(einstellungen, panel_port_aussen=8123)


def _missa(client: TestClient) -> dict:
    return next(k for k in client.get("/api/status").json()["knoten"] if k["id"] == "missa")


def _detail(knoten: dict, titel: str) -> object:
    return next(d["wert"] for d in knoten["details"] if d["titel"] == titel)


def test_legt_client_an_und_nennt_token_und_port(angemeldet: TestClient) -> None:
    erster = angemeldet.post("/api/clients/missa-core")
    assert erster.status_code == 201
    daten = erster.json()
    assert daten["name"] == "missa-core"
    assert daten["token"].startswith("mc_")
    assert daten["port"] == 8123
    assert daten["zuletzt_gesehen"] is None and daten["zuletzt_abgeholt"] is None
    # Ein zweites Mal: eigener Name, eigener Token
    zweiter = angemeldet.post("/api/clients/missa-core").json()
    assert zweiter["name"] == "missa-core 2"
    assert zweiter["token"] != daten["token"]
    # Danach ist der Token nirgends mehr zu sehen
    assert daten["token"] not in angemeldet.get("/api/clients").text


def test_port_kommt_aus_missa_control_bind(
    monkeypatch: pytest.MonkeyPatch, einstellungen: Einstellungen
) -> None:
    monkeypatch.setenv("SECRET_KEY", einstellungen.secret_key)
    monkeypatch.setenv("ENCRYPTION_KEY", einstellungen.encryption_key)
    monkeypatch.setenv("MISSA_CONTROL_BIND", "127.0.0.1:9100")
    assert Einstellungen.aus_umgebung().panel_port_aussen == 9100
    monkeypatch.delenv("MISSA_CONTROL_BIND")
    assert Einstellungen.aus_umgebung().panel_port_aussen == 8090


async def test_nach_der_ersten_abfrage_verbunden_und_abgeholt(
    angemeldet: TestClient, panel: LaufenderServer, uhr: Uhr
) -> None:
    daten = angemeldet.post("/api/clients/missa-core").json()
    assert _detail(_missa(angemeldet), "Funktionen abgeholt") == "noch nie"

    async with mcp(panel, daten["token"]) as client:
        await client.list_tools()

    gelistet = next(c for c in angemeldet.get("/api/clients").json() if c["id"] == daten["id"])
    assert gelistet["zuletzt_gesehen"] is not None
    assert gelistet["zuletzt_abgeholt"] is not None
    missa = _missa(angemeldet)
    assert _detail(missa, "Funktionen abgeholt") == gelistet["zuletzt_abgeholt"]
    knoten = next(
        k for k in angemeldet.get("/api/status").json()["knoten"] if k["id"] == f"client:{daten['id']}"
    )
    assert _detail(knoten, "Funktionen abgeholt") == gelistet["zuletzt_abgeholt"]

    # Ein widerrufener Client zählt nicht mehr
    angemeldet.post(f"/api/clients/{daten['id']}/widerrufen")
    assert _detail(_missa(angemeldet), "Funktionen abgeholt") == "noch nie"
