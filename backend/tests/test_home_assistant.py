"""Home Assistant: nutzt den MCP-Server von Home Assistant, falls eingerichtet – sonst die REST-API.

Home Assistant ist hier nachgestellt (siehe `server.HomeAssistant`): die REST-API so, wie sie
dokumentiert ist, und der MCP-Server mit einer Auswahl seiner Werkzeuge.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import client_token, mcp_client, mcp_text, warte_auf
from server import HomeAssistant, LaufenderServer, artikel_rest_api, freier_port

pytestmark = pytest.mark.anyio

TOKEN = "langlebiges-token-von-home-assistant-0123456789"


@pytest.fixture
def ha() -> Iterator[tuple[HomeAssistant, LaufenderServer]]:
    """Home Assistant ohne MCP-Server: es bleibt die REST-API."""
    zuhause = HomeAssistant(TOKEN)
    with LaufenderServer(zuhause) as server:
        yield zuhause, server


def _konfig(
    admin: TestClient, url: str, token: str = TOKEN, name: str = "Home Assistant Token"
) -> dict[str, Any]:
    zugang = admin.post("/api/zugaenge", json={"name": name, "typ": "bearer_token", "wert": token})
    assert zugang.status_code == 201, zugang.text
    return {"url": url, "zugang": zugang.json()["id"]}


def _testen(admin: TestClient, konfig: dict[str, Any]) -> dict:
    return admin.post(
        "/api/integrationen/testen", json={"manifest_id": "home-assistant", "konfig": konfig}
    ).json()


def _einrichten(admin: TestClient, url: str) -> dict:
    konfig = _konfig(admin, url)
    test = _testen(admin, konfig)
    assert test["ok"] is True, test
    antwort = admin.post(
        "/api/integrationen",
        json={"manifest_id": "home-assistant", "konfig": konfig, "test_id": test["test_id"]},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _aufrufen(admin: TestClient, integration: dict, funktion: str, **argumente: Any) -> dict:
    antwort = admin.post(
        f"/api/integrationen/{integration['id']}/aufrufen",
        json={"funktion": funktion, "argumente": argumente},
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# ====================================================================== REST-API


def test_einrichten_und_testen_zeigt_geraete_und_entitaeten(
    angemeldet: TestClient, ha: tuple[HomeAssistant, LaufenderServer]
) -> None:
    """Fertig-wenn: Home Assistant einrichten und testen zeigt Geräte/Entitäten an."""
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "home-assistant")
    assert [(f["name"], f["typ"]) for f in karte["felder"]] == [("url", "url"), ("zugang", "zugang")]
    assert "Langlebige Zugriffstoken" in karte["hinweis"]  # wie man den Token erstellt
    assert "Token erstellen" in karte["hinweis"]

    test = _testen(angemeldet, _konfig(angemeldet, ha[1].url))
    assert test["ok"] is True, test
    assert test["meldung"] == "Verbunden mit „Zuhause“ (Version 2026.11.0) – 9 Geräte und Entitäten gefunden."
    assert test["details"] == [
        "9 Geräte und Entitäten: 3 Lichter, 2 Sensoren, 1 Schalter, 1 Heizung/Klima, 1 Personen, 1 weitere",
        "Zum Beispiel: Wohnzimmer Licht, Küche Licht, Flur Licht, Kaffeemaschine, Heizung Wohnzimmer",
        "Verbindung über die REST-API (der MCP-Server von Home Assistant ist nicht eingerichtet)",
    ]
    assert {f["name"]: (f["recht"], f["schreibend"]) for f in test["funktionen"]} == {
        "geraete_anzeigen": ("erlaubt", False),
        "zustand_lesen": ("erlaubt", False),
        "einschalten": ("nachfragen", True),
        "ausschalten": ("nachfragen", True),
        "dienst_aufrufen": ("nachfragen", True),
    }


def test_geraete_anzeigen_zustand_lesen_und_schalten(
    angemeldet: TestClient, ha: tuple[HomeAssistant, LaufenderServer]
) -> None:
    zuhause, server = ha
    integration = _einrichten(angemeldet, server.url)
    assert TOKEN not in json.dumps(integration)

    def ergebnis(funktion: str, **argumente: Any) -> Any:
        antwort = _aufrufen(angemeldet, integration, funktion, **argumente)
        assert antwort["ok"] is True, antwort
        try:
            return json.loads(antwort["ergebnis"])
        except ValueError:
            return antwort["ergebnis"]

    lichter = ergebnis("geraete_anzeigen", art="Licht")  # die Art geht auch auf Deutsch
    assert lichter["anzahl"] == 3
    assert lichter["geraete"] == [
        {"id": "light.flur", "name": "Flur Licht", "zustand": "off", "art": "light"},
        {"id": "light.kueche", "name": "Küche Licht", "zustand": "on", "art": "light"},
        {"id": "light.wohnzimmer", "name": "Wohnzimmer Licht", "zustand": "off", "art": "light"},
    ]
    wohnzimmer = ergebnis("geraete_anzeigen", suche="wohnzimmer")
    assert [g["name"] for g in wohnzimmer["geraete"]] == [
        "Heizung Wohnzimmer",
        "Wohnzimmer Licht",
        "Wohnzimmer Luftfeuchtigkeit",
    ]
    assert wohnzimmer["geraete"][2]["zustand"] == "48 %"  # mit Einheit
    assert ergebnis("geraete_anzeigen", anzahl=2)["hinweis"].startswith(
        "Es gibt 9 passende – angezeigt werden 2."
    )
    assert ergebnis("geraete_anzeigen", suche="garage")["hinweis"].startswith("Nichts gefunden.")

    heizung = ergebnis("zustand_lesen", id="climate.wohnzimmer")
    assert heizung["name"] == "Heizung Wohnzimmer"
    assert heizung["eigenschaften"] == {"temperature": 21, "current_temperature": 20.4}

    assert ergebnis("einschalten", id="light.wohnzimmer") == "„Wohnzimmer Licht“ ist eingeschaltet."
    assert zuhause.zustaende["light.wohnzimmer"]["state"] == "on"
    assert zuhause.aufrufe[-1] == ("homeassistant.turn_on", {"entity_id": "light.wohnzimmer"})
    assert ergebnis("ausschalten", id="Light.Wohnzimmer ") == "„Wohnzimmer Licht“ ist ausgeschaltet."
    assert zuhause.zustaende["light.wohnzimmer"]["state"] == "off"

    assert (
        ergebnis("dienst_aufrufen", dienst="light.turn_on", id="light.flur", daten={"brightness_pct": 40})
        == "Erledigt."
    )
    assert zuhause.aufrufe[-1] == ("light.turn_on", {"brightness_pct": 40, "entity_id": "light.flur"})
    assert zuhause.zustaende["light.flur"]["attributes"]["brightness"] == 102

    # Fehler sind verständlich – und kein Grund, die ganze Integration als ausgefallen zu melden.
    for funktion, argumente, meldung in (
        (
            "zustand_lesen",
            {"id": "light.garage"},
            "Das Gerät „light.garage“ gibt es in Home Assistant nicht.",
        ),
        ("einschalten", {"id": "das Licht"}, "„das Licht“ ist keine gültige Kennung."),
        ("dienst_aufrufen", {"dienst": "licht an"}, "„licht an“ ist kein gültiger Dienst."),
        (
            "dienst_aufrufen",
            {"dienst": "light.explode", "id": "light.flur"},
            "Home Assistant hat „light.explode“ abgelehnt",
        ),
    ):
        antwort = _aufrufen(angemeldet, integration, funktion, **argumente)
        assert antwort["ok"] is False
        assert antwort["meldung"].startswith(meldung)
    assert angemeldet.get(f"/api/integrationen/{integration['id']}").json()["status"] == "ok"


async def test_schalten_fragt_erst_nach_und_sagt_welches_geraet(
    angemeldet: TestClient, panel: LaufenderServer, ha: tuple[HomeAssistant, LaufenderServer]
) -> None:
    zuhause, server = ha
    _einrichten(angemeldet, server.url)
    token = client_token(angemeldet)
    async with mcp_client(panel.url, token) as missa:
        namen = {w.name for w in (await missa.list_tools()).tools}
        assert namen == {
            "home_assistant_geraete_anzeigen",
            "home_assistant_zustand_lesen",
            "home_assistant_einschalten",
            "home_assistant_ausschalten",
            "home_assistant_dienst_aufrufen",
        }
        gelesen = await missa.call_tool("home_assistant_zustand_lesen", {"id": "sensor.balkon_temperatur"})
        assert json.loads(mcp_text(gelesen))["zustand"] == "4.5 °C"

        aufruf = asyncio.create_task(
            missa.call_tool("home_assistant_einschalten", {"id": "switch.kaffeemaschine"})
        )
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["vorschau"] == "Schaltet „Kaffeemaschine“ (switch.kaffeemaschine) ein – jetzt: off"
        assert zuhause.zustaende["switch.kaffeemaschine"]["state"] == "off"  # noch nichts geschaltet
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        assert mcp_text(await asyncio.wait_for(aufruf, timeout=10)) == "„Kaffeemaschine“ ist eingeschaltet."
        assert zuhause.zustaende["switch.kaffeemaschine"]["state"] == "on"

        aufruf = asyncio.create_task(
            missa.call_tool(
                "home_assistant_dienst_aufrufen",
                {
                    "dienst": "climate.set_temperature",
                    "id": "climate.wohnzimmer",
                    "daten": {"temperature": 22},
                },
            )
        )
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["vorschau"] == (
            "Ruft in Home Assistant „climate.set_temperature“ für „Heizung Wohnzimmer“ (climate.wohnzimmer) auf (temperature = 22)"
        )
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        await asyncio.wait_for(aufruf, timeout=10)
        assert zuhause.zustaende["climate.wohnzimmer"]["attributes"]["temperature"] == 22

        # Ein Gerät, das es nicht gibt: sofortige Antwort, keine Freigabe.
        unbekannt = await asyncio.wait_for(
            missa.call_tool("home_assistant_einschalten", {"id": "light.garage"}), timeout=10
        )
        assert unbekannt.is_error is True
        assert "gibt es in Home Assistant nicht" in mcp_text(unbekannt)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []


# ====================================================================== MCP-Server von Home Assistant


@pytest.mark.parametrize(("art", "pfad"), [("http", "/api/mcp"), ("sse", "/mcp_server/sse")])
async def test_mit_mcp_server_nutzt_missa_die_werkzeuge_von_home_assistant(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer, art: str, pfad: str
) -> None:
    zuhause = HomeAssistant(TOKEN, mcp=art)
    with LaufenderServer(zuhause) as server:
        test = _testen(angemeldet, _konfig(angemeldet, server.url))
        assert test["ok"] is True, test
        assert test["details"][-1] == "Verbindung über den MCP-Server von Home Assistant (3 Funktionen)"
        assert test["details"][0].startswith(
            "9 Geräte und Entitäten: 3 Lichter"
        )  # die Übersicht gibt es trotzdem
        # Statt der REST-Funktionen kommen die Werkzeuge von Home Assistant selbst.
        assert {f["name"]: (f["recht"], f["schreibend"]) for f in test["funktionen"]} == {
            "GetLiveContext": ("erlaubt", False),
            "HassTurnOn": ("nachfragen", True),
            "HassTurnOff": ("nachfragen", True),
        }
        integration = angemeldet.post(
            "/api/integrationen",
            json={
                "manifest_id": "home-assistant",
                "konfig": {"url": server.url, "zugang": 1},
                "test_id": test["test_id"],
            },
        ).json()
        with app.state.datenbank.sitzung() as db:
            zustand = app.state.integrationen.holen(db, integration["id"]).zustand
        assert (zustand["weg"], zustand["mcp_url"]) == ("mcp", server.url + pfad)

        token = client_token(angemeldet)
        async with mcp_client(panel.url, token) as missa:
            werkzeuge = {w.name: w for w in (await missa.list_tools()).tools}
            assert set(werkzeuge) == {
                "home_assistant_GetLiveContext",
                "home_assistant_HassTurnOn",
                "home_assistant_HassTurnOff",
            }
            assert werkzeuge["home_assistant_HassTurnOn"].input_schema["required"] == ["name"]
            lage = await missa.call_tool("home_assistant_GetLiveContext", {})
            assert "- Wohnzimmer Licht: off" in mcp_text(lage)

            aufruf = asyncio.create_task(
                missa.call_tool("home_assistant_HassTurnOn", {"name": "Wohnzimmer Licht"})
            )
            offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
            assert offen[0]["argumente"] == {"name": "Wohnzimmer Licht"}
            angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
            assert mcp_text(await asyncio.wait_for(aufruf, timeout=10)) == "Turned on Wohnzimmer Licht"
            assert zuhause.zustaende["light.wohnzimmer"]["state"] == "on"

            # Fehler eines Werkzeugs kommen unverändert als Fehler an.
            aufruf = asyncio.create_task(missa.call_tool("home_assistant_HassTurnOff", {"name": "Garage"}))
            offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
            angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
            assert (await asyncio.wait_for(aufruf, timeout=10)).is_error is True


def test_wird_der_mcp_server_spaeter_eingerichtet_stellt_testen_um(angemeldet: TestClient) -> None:
    """Erst nur REST; dann richtet man in Home Assistant den MCP-Server ein und klickt im Panel auf „Testen“."""
    port = freier_port()

    with LaufenderServer(HomeAssistant(TOKEN), port) as server:
        integration = _einrichten(angemeldet, server.url)
        assert {f["name"] for f in integration["funktionen"] if f["vorhanden"]} >= {
            "geraete_anzeigen",
            "einschalten",
        }

    with LaufenderServer(HomeAssistant(TOKEN, mcp="http"), port):
        neu = angemeldet.post(f"/api/integrationen/{integration['id']}/testen").json()
        assert neu["status"] == "ok"
        assert "MCP-Server von Home Assistant" not in neu["status_meldung"]  # die Meldung nennt den Ort
        vorhanden = {f["name"] for f in neu["funktionen"] if f["vorhanden"]}
        assert vorhanden == {"GetLiveContext", "HassTurnOn", "HassTurnOff"}
        # Die REST-Funktionen stehen noch in der Liste, sind aber nicht mehr verfügbar.
        assert {f["name"] for f in neu["funktionen"] if not f["vorhanden"]} == {
            "geraete_anzeigen",
            "zustand_lesen",
            "einschalten",
            "ausschalten",
            "dienst_aufrufen",
        }
        nicht_mehr = _aufrufen(angemeldet, neu, "geraete_anzeigen")
        assert nicht_mehr["ok"] is False


# ====================================================================== Fehler


def test_fehler_beim_einrichten_sind_verstaendlich(
    angemeldet: TestClient, ha: tuple[HomeAssistant, LaufenderServer]
) -> None:
    falsch = _testen(
        angemeldet, _konfig(angemeldet, ha[1].url, token="falsches-token-0123456789", name="Falsch")
    )
    assert falsch["ok"] is False
    assert falsch["meldung"] == "Die Gegenstelle lehnt den Zugang ab (401 – nicht angemeldet)."

    richtig = _konfig(angemeldet, f"http://127.0.0.1:{freier_port()}")
    aus = _testen(angemeldet, richtig)
    assert (aus["ok"], aus["meldung"]) == (False, "Die Gegenstelle ist nicht erreichbar.")

    with LaufenderServer(artikel_rest_api()) as anderes:  # irgendein anderer Dienst
        kein_ha = _testen(angemeldet, {**richtig, "url": anderes.url})
    assert kein_ha["ok"] is False
    assert kein_ha["meldung"] == "Die Adresse wurde nicht gefunden (404)."


def test_faellt_home_assistant_aus_wird_das_gemeldet(angemeldet: TestClient) -> None:
    with LaufenderServer(HomeAssistant(TOKEN)) as server:
        integration = _einrichten(angemeldet, server.url)
    antwort = _aufrufen(angemeldet, integration, "geraete_anzeigen")
    assert (antwort["ok"], antwort["meldung"]) == (False, "Die Gegenstelle ist nicht erreichbar.")
    assert angemeldet.get(f"/api/integrationen/{integration['id']}").json()["status"] == "fehler"
    ereignisse = [e["art"] for e in angemeldet.get("/api/ereignisse").json()]
    assert "integration_ausgefallen" in ereignisse  # darauf können Regeln reagieren
