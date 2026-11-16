"""Zugriffsstufe pro Integration: „Nur lesen“, „Schreiben erst nachfragen“, „Voller Zugriff“."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient

from missa_control.config import Einstellungen
from missa_control.integrationen.typen import recht_fuer_stufe
from server import LaufenderServer
from test_gateway import MAIN, MANIFEST, _client_anlegen, _text, mcp

pytestmark = pytest.mark.anyio

# Eine Version der Werkstatt mit einer zusätzlichen schreibenden Funktion („später dazugekommen“)
NEUE_FUNKTION = (
    MAIN
    + """

@funktion(beschreibung="Startet die Säge.", schreibend=True)
def saege_starten(kontext: Kontext) -> str:
    return "Säge läuft"


@funktion(beschreibung="Misst den Lärm.", schreibend=False)
def laerm(kontext: Kontext) -> int:
    return 70
"""
)


@pytest.fixture
def einstellungen(einstellungen: Einstellungen) -> Einstellungen:
    ordner = einstellungen.eigene_integrationen_ordner / "werkstatt"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(MANIFEST, encoding="utf-8")
    (ordner / "main.py").write_text(MAIN, encoding="utf-8")
    return dataclasses.replace(einstellungen, stream_ping_sekunden=0.2)


def _anlegen(client: TestClient, zugriff: str | None = None, rechte: dict | None = None) -> dict[str, Any]:
    test = client.post("/api/integrationen/testen", json={"manifest_id": "werkstatt", "konfig": {}}).json()
    assert test["ok"] is True, test
    daten: dict[str, Any] = {"manifest_id": "werkstatt", "konfig": {}, "test_id": test["test_id"]}
    if zugriff is not None:
        daten["zugriff"] = zugriff
    if rechte is not None:
        daten["rechte"] = rechte
    antwort = client.post("/api/integrationen", json=daten)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _rechte(integration: dict[str, Any]) -> dict[str, str]:
    return {f["name"]: f["recht"] for f in integration["funktionen"]}


def test_recht_fuer_stufe() -> None:
    assert [recht_fuer_stufe(s, False) for s in ("lesen", "nachfragen", "voll")] == ["erlaubt"] * 3
    assert [recht_fuer_stufe(s, True) for s in ("lesen", "nachfragen", "voll")] == [
        "gesperrt",
        "nachfragen",
        "erlaubt",
    ]


def test_standard_ist_nachfragen_und_verhaelt_sich_wie_bisher(angemeldet: TestClient) -> None:
    integration = _anlegen(angemeldet)
    assert integration["zugriff"] == "nachfragen"
    # Die Standardrechte aus dem Manifest gelten wie bisher (tresor_oeffnen: gesperrt) → „angepasst“
    assert _rechte(integration) == {
        "kaputt": "erlaubt",
        "lampe_schalten": "nachfragen",
        "temperatur": "erlaubt",
        "tresor_oeffnen": "gesperrt",
    }
    assert integration["zugriff_angepasst"] is True


@pytest.mark.parametrize(
    ("stufe", "erwartet"),
    [
        (
            "lesen",
            {
                "kaputt": "erlaubt",
                "lampe_schalten": "gesperrt",
                "temperatur": "erlaubt",
                "tresor_oeffnen": "gesperrt",
            },
        ),
        (
            "nachfragen",
            {
                "kaputt": "erlaubt",
                "lampe_schalten": "nachfragen",
                "temperatur": "erlaubt",
                "tresor_oeffnen": "nachfragen",
            },
        ),
        (
            "voll",
            {
                "kaputt": "erlaubt",
                "lampe_schalten": "erlaubt",
                "temperatur": "erlaubt",
                "tresor_oeffnen": "erlaubt",
            },
        ),
    ],
)
def test_stufe_setzt_alle_rechte_auf_einmal(angemeldet: TestClient, stufe: str, erwartet: dict) -> None:
    integration = _anlegen(angemeldet)
    geaendert = angemeldet.put(f"/api/integrationen/{integration['id']}", json={"zugriff": stufe}).json()
    assert geaendert["zugriff"] == stufe
    assert _rechte(geaendert) == erwartet
    assert geaendert["zugriff_angepasst"] is False

    # Ein einzelnes Recht lässt sich danach ändern → „angepasst“
    anders = "gesperrt" if erwartet["temperatur"] != "gesperrt" else "erlaubt"
    einzeln = angemeldet.put(
        f"/api/integrationen/{integration['id']}", json={"rechte": {"temperatur": anders}}
    ).json()
    assert einzeln["zugriff"] == stufe
    assert einzeln["zugriff_angepasst"] is True

    ereignisse = angemeldet.get("/api/ereignisse", params={"art": "zugriff_geaendert"}).json()
    if stufe == "nachfragen":
        assert ereignisse == []  # keine Änderung, kein Ereignis
    else:
        assert ereignisse[0]["daten"]["alt"] == "nachfragen"
        assert ereignisse[0]["daten"]["neu"] == stufe


def test_stufe_schon_beim_anlegen(angemeldet: TestClient) -> None:
    integration = _anlegen(angemeldet, zugriff="lesen")
    assert integration["zugriff"] == "lesen"
    assert _rechte(integration)["lampe_schalten"] == "gesperrt"
    assert (
        angemeldet.put(f"/api/integrationen/{integration['id']}", json={"zugriff": "alles"}).status_code
        == 422
    )


async def test_nur_lesen_versteckt_schreibende_funktionen(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    integration = _anlegen(angemeldet)
    _id, token = _client_anlegen(angemeldet)
    async with mcp(panel, token) as client:
        namen = {w.name for w in (await client.list_tools()).tools}
        assert "werkstatt_lampe_schalten" in namen
        angemeldet.put(f"/api/integrationen/{integration['id']}", json={"zugriff": "lesen"})
        namen = {w.name for w in (await client.list_tools(cache_mode="refresh")).tools}
        assert "werkstatt_lampe_schalten" not in namen
        assert "werkstatt_tresor_oeffnen" not in namen
        assert "werkstatt_temperatur" in namen


async def test_voller_zugriff_laeuft_ohne_freigabe_und_steht_im_protokoll(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    integration = _anlegen(angemeldet, zugriff="voll")
    assert _rechte(integration)["lampe_schalten"] == "erlaubt"
    _id, token = _client_anlegen(angemeldet)
    async with mcp(panel, token) as client:
        ergebnis = await asyncio.wait_for(client.call_tool("werkstatt_lampe_schalten", {"an": True}), 10)
        assert _text(ergebnis) == "Lampe ist an"
    assert angemeldet.get("/api/freigaben/anzahl").json()["offen"] == 0
    protokoll = angemeldet.get("/api/protokoll").json()["eintraege"]
    assert any(e.get("funktion") == "werkstatt_lampe_schalten" and e.get("ok") for e in protokoll)


def test_neue_funktionen_unter_voll_muessen_geprueft_werden(
    angemeldet: TestClient, einstellungen: Einstellungen
) -> None:
    integration = _anlegen(angemeldet, zugriff="voll")
    assert integration["neu_zu_pruefen"] == 0
    (einstellungen.eigene_integrationen_ordner / "werkstatt" / "main.py").write_text(
        NEUE_FUNKTION, encoding="utf-8"
    )
    getestet = angemeldet.post(f"/api/integrationen/{integration['id']}/testen").json()
    rechte = _rechte(getestet)
    assert rechte["saege_starten"] == "nachfragen"  # neu und schreibend: erst nachfragen
    assert rechte["laerm"] == "erlaubt"  # neu und lesend
    assert rechte["lampe_schalten"] == "erlaubt"  # bekannte bleiben
    assert getestet["neu_zu_pruefen"] == 1
    assert [f["name"] for f in getestet["funktionen"] if f["zu_pruefen"]] == ["saege_starten"]
    assert getestet["zugriff_angepasst"] is False  # der Hinweis zählt nicht als „angepasst“

    # Als geprüft markieren – der Hinweis verschwindet, das Recht bleibt.
    geprueft = angemeldet.put(f"/api/integrationen/{integration['id']}", json={"neue_geprueft": True}).json()
    assert geprueft["neu_zu_pruefen"] == 0
    assert _rechte(geprueft)["saege_starten"] == "nachfragen"


@pytest.mark.parametrize(("stufe", "recht"), [("lesen", "gesperrt"), ("nachfragen", "nachfragen")])
def test_neue_funktionen_bekommen_ihr_recht_nach_der_stufe(
    angemeldet: TestClient, einstellungen: Einstellungen, stufe: str, recht: str
) -> None:
    integration = _anlegen(angemeldet, zugriff=stufe, rechte={})
    (einstellungen.eigene_integrationen_ordner / "werkstatt" / "main.py").write_text(
        NEUE_FUNKTION, encoding="utf-8"
    )
    getestet = angemeldet.post(f"/api/integrationen/{integration['id']}/testen").json()
    assert _rechte(getestet)["saege_starten"] == recht
    assert _rechte(getestet)["laerm"] == "erlaubt"
    assert getestet["neu_zu_pruefen"] == 0


def test_konfig_api_und_uebersicht_nennen_die_stufe(angemeldet: TestClient) -> None:
    integration = _anlegen(angemeldet)
    angemeldet.put(f"/api/integrationen/{integration['id']}", json={"zugriff": "lesen"})
    _id, token = _client_anlegen(angemeldet)
    konfig = angemeldet.get("/api/config/integrations", headers={"Authorization": f"Bearer {token}"}).json()
    assert konfig["integrationen"][0]["zugriff"] == "lesen"
    knoten = next(
        k
        for k in angemeldet.get("/api/status").json()["knoten"]
        if k["id"] == f"integration:{integration['id']}"
    )
    assert knoten["zugriff"] == "lesen"
    assert {"titel": "Zugriff", "wert": "Nur lesen", "zeit": False} in knoten["details"]
    assert knoten["untertitel"].endswith("· Nur lesen")


def test_migration_setzt_bestehende_auf_nachfragen_und_laesst_rechte(tmp_path: Path) -> None:
    """Eine Datenbank im Stand vor 0014 mit einer Integration: Nach dem Update ist alles wie vorher."""
    from alembic.config import Config

    from missa_control.db import MIGRATIONS_ORDNER, Datenbank

    datenbank = Datenbank(tmp_path / "alt.db")
    konfig = Config()
    konfig.set_main_option("script_location", str(MIGRATIONS_ORDNER))
    with datenbank.engine.begin() as verbindung:
        konfig.attributes["connection"] = verbindung
        command.upgrade(konfig, "0013")
    with datenbank.engine.begin() as verbindung:
        verbindung.execute(
            sa.text(
                "INSERT INTO integrationen (id, manifest_id, name, kennung, konfig, zustand, aktiv, status, "
                "status_meldung, status_hinweis, erstellt, geaendert) VALUES (1, 'werkstatt', 'Werkstatt', "
                "'werkstatt', '{}', '{}', 1, 'ok', '', '', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        verbindung.execute(
            sa.text(
                "INSERT INTO funktionen (integration_id, name, beschreibung, parameter, schreibend, recht, "
                "vorhanden, extra) VALUES (1, 'lampe_schalten', '', '{}', 1, 'erlaubt', 1, '{}'), "
                "(1, 'tresor_oeffnen', '', '{}', 1, 'gesperrt', 1, '{}')"
            )
        )
    datenbank.migrieren()
    with datenbank.engine.connect() as verbindung:
        assert verbindung.execute(sa.text("SELECT zugriff FROM integrationen")).scalar() == "nachfragen"
        rechte = dict(verbindung.execute(sa.text("SELECT name, recht FROM funktionen")).all())
        assert rechte == {"lampe_schalten": "erlaubt", "tresor_oeffnen": "gesperrt"}
        assert verbindung.execute(sa.text("SELECT SUM(zu_pruefen) FROM funktionen")).scalar() == 0
    datenbank.schliessen()
