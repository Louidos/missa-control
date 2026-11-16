"""Karte „API hinzufügen“: nur Adresse und Key – das Panel findet die Funktionen selbst."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from missa_control.integrationen.adapter.api import Adresse, pfad_pruefen
from missa_control.integrationen.typen import IntegrationsFehler
from server import LaufenderServer, einfache_api

KEY = "lager-geheimer-key-0123456789"


def _zugang(client: TestClient, typ: str = "api_key", wert: str = KEY, **mehr: str) -> int:
    antwort = client.post("/api/zugaenge", json={"name": "Lager", "typ": typ, "wert": wert, **mehr})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def _testen(client: TestClient, konfig: dict[str, Any]) -> dict[str, Any]:
    antwort = client.post("/api/integrationen/testen", json={"manifest_id": "api", "konfig": konfig})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _einrichten(client: TestClient, konfig: dict[str, Any], name: str = "Lager") -> dict[str, Any]:
    """Wie „Testen und aktivieren“ im Assistenten: testen und gleich mit den Vorschlägen aktivieren."""
    test = _testen(client, konfig)
    assert test["ok"] is True, test
    antwort = client.post(
        "/api/integrationen",
        json={
            "manifest_id": "api",
            "name": name,
            "konfig": konfig,
            "test_id": test["test_id"],
            "rechte": {f["name"]: f["recht"] for f in test["funktionen"]},
        },
    )
    assert antwort.status_code == 201, antwort.text
    return {**antwort.json(), "test": test}


def _aufrufen(client: TestClient, integration: dict[str, Any], funktion: str, **argumente: Any) -> dict:
    return client.post(
        f"/api/integrationen/{integration['id']}/aufrufen",
        json={"funktion": funktion, "argumente": argumente},
    ).json()


@pytest.fixture
def ohne_beschreibung() -> Iterator[tuple[LaufenderServer, FastAPI]]:
    app = einfache_api(KEY)
    with LaufenderServer(app) as server:
        yield server, app


def test_karte_steht_zuerst_und_ist_hervorgehoben(angemeldet: TestClient) -> None:
    eintraege = angemeldet.get("/api/katalog").json()["eintraege"]
    assert eintraege[0]["id"] == "api"
    assert eintraege[0]["hervorgehoben"] is True
    assert [f["name"] for f in eintraege[0]["felder"] if f["pflicht"]] == ["adresse"]
    rest = next(e for e in eintraege if e["id"] == "rest-api")
    assert "API hinzufügen" in rest["hinweis"]


def test_ohne_beschreibung_gibt_es_abrufen_und_senden(
    angemeldet: TestClient, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    server, app = ohne_beschreibung
    integration = _einrichten(
        angemeldet,
        {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet), "beschreibung": "Lagerverwaltung"},
    )
    test = integration["test"]
    assert "Keine OpenAPI-Beschreibung gefunden" in test["meldung"]
    rechte = {f["name"]: f["recht"] for f in test["funktionen"]}
    assert rechte == {"abrufen": "erlaubt", "senden": "nachfragen"}
    assert sorted(f["gateway_name"] for f in integration["funktionen"]) == ["lager_abrufen", "lager_senden"]
    abrufen = next(f for f in integration["funktionen"] if f["name"] == "abrufen")
    assert server.url + "/v1" in abrufen["beschreibung"] and "Lagerverwaltung" in abrufen["beschreibung"]

    # Höchstens 10 Versuche bei der Suche nach der Beschreibung
    gesucht = [a for a in app.state.anfragen if a["pfad"] not in ("/v1",)]
    assert 0 < len(gesucht) <= 10

    liste = _aufrufen(angemeldet, integration, "abrufen", pfad="/artikel", parameter={"suche": "apf"})
    assert liste["ok"] is True, liste
    assert "Apfel" in liste["ergebnis"]
    neu = _aufrufen(angemeldet, integration, "senden", methode="POST", pfad="artikel", daten={"name": "Birne"})
    assert neu["ok"] is True, neu
    assert "Birne" in neu["ergebnis"]
    falsch = _aufrufen(angemeldet, integration, "senden", methode="GET", pfad="/artikel")
    assert falsch["ok"] is False and "POST, PUT, PATCH oder DELETE" in falsch["meldung"]


@pytest.mark.parametrize("ort", ["/openapi.json", "/v1/openapi.json", "/v3/api-docs", "/v1/swagger.json"])
def test_beschreibung_unter_ueblichem_pfad_wird_gefunden(angemeldet: TestClient, ort: str) -> None:
    with LaufenderServer(einfache_api(KEY, beschreibung_unter=ort)) as server:
        integration = _einrichten(angemeldet, {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet)})
        test = integration["test"]
        assert f"gefunden unter {server.url}{ort}" in test["meldung"]
        assert "3 Funktion(en)" in test["meldung"]
        assert {f["name"] for f in integration["funktionen"]} == {
            "artikel_auflisten",
            "artikel_lesen",
            "artikel_anlegen",
        }
        lesen = _aufrufen(angemeldet, integration, "artikel_lesen", artikel_id="1")
        assert lesen["ok"] is True, lesen
        assert "Apfel" in lesen["ergebnis"]


def test_eigene_endpunkte_werden_eigene_funktionen(
    angemeldet: TestClient, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    server, _app = ohne_beschreibung
    endpunkte = [
        {"name": "artikel_lesen", "methode": "GET", "pfad": "/artikel/{id}", "beschreibung": "Einen Artikel"},
        {"name": "artikel_anlegen", "methode": "post", "pfad": "artikel", "beschreibung": ""},
        {"name": "", "methode": "GET", "pfad": "", "beschreibung": ""},  # leere Zeile im Formular
    ]
    integration = _einrichten(
        angemeldet, {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet), "endpunkte": endpunkte}
    )
    funktionen = {f["name"]: f for f in integration["funktionen"]}
    assert set(funktionen) == {"abrufen", "senden", "artikel_lesen", "artikel_anlegen"}
    assert funktionen["artikel_lesen"]["schreibend"] is False
    assert funktionen["artikel_lesen"]["recht"] == "erlaubt"
    assert funktionen["artikel_lesen"]["parameter"]["required"] == ["id"]
    assert funktionen["artikel_anlegen"]["schreibend"] is True
    assert funktionen["artikel_anlegen"]["recht"] == "nachfragen"
    assert "daten" in funktionen["artikel_anlegen"]["parameter"]["properties"]
    assert integration["konfig"]["endpunkte"][1]["pfad"] == "/artikel"

    assert "Apfel" in _aufrufen(angemeldet, integration, "artikel_lesen", id="1")["ergebnis"]
    assert "Kiwi" in _aufrufen(angemeldet, integration, "artikel_anlegen", daten={"name": "Kiwi"})["ergebnis"]
    # Ein Platzhalter-Wert kann nicht aus der Adresse ausbrechen
    ausbruch = _aufrufen(angemeldet, integration, "artikel_lesen", id="..")
    assert ausbruch["ok"] is False and "Abgelehnt" in ausbruch["meldung"]


@pytest.mark.parametrize(
    ("endpunkt", "meldung"),
    [
        ({"name": "x", "methode": "GET", "pfad": "https://anders.ch/x"}, "vollständige Adresse"),
        ({"name": "x", "methode": "GET", "pfad": "/../geheim"}, "„..“"),
        ({"name": "Gross", "methode": "GET", "pfad": "/a"}, "ungültiges Format"),
        ({"name": "x", "methode": "HOLEN", "pfad": "/a"}, "ungültigen Wert"),
    ],
)
def test_ungueltige_endpunkte_werden_erklaert(angemeldet: TestClient, endpunkt: dict, meldung: str) -> None:
    antwort = angemeldet.post(
        "/api/integrationen/testen",
        json={"manifest_id": "api", "konfig": {"adresse": "http://127.0.0.1:9", "endpunkte": [endpunkt]}},
    )
    assert antwort.status_code == 422
    assert meldung in antwort.json()["meldung"]


@pytest.mark.parametrize(
    ("art", "name", "typ", "wert", "mehr"),
    [
        ("bearer", "", "api_key", KEY, {}),
        ("header", "X-Lager-Key", "api_key", KEY, {}),
        ("query", "schluessel", "api_key", KEY, {}),
        ("basic", "", "benutzer_passwort", "passwort-geheim-123", {"benutzer": "louis"}),
    ],
)
def test_alle_vier_arten_den_key_zu_senden(
    angemeldet: TestClient, art: str, name: str, typ: str, wert: str, mehr: dict
) -> None:
    erwartet = f"louis:{wert}" if art == "basic" else wert
    app = einfache_api(erwartet, art=art, name=name or "X-API-Key")
    with LaufenderServer(app) as server:
        zugang = _zugang(angemeldet, typ, wert, **mehr)
        konfig = {"adresse": server.url + "/v1", "zugang": zugang, "key_art": art, "key_name": name}
        integration = _einrichten(angemeldet, konfig)
        aufruf = _aufrufen(angemeldet, integration, "abrufen", pfad="/artikel")
        assert aufruf["ok"] is True, aufruf
        # Antworten, die den Key zurückschicken, werden geschwärzt
        echo = _aufrufen(angemeldet, integration, "abrufen", pfad="/echo")
        assert echo["ok"] is True
        assert wert not in json.dumps(echo)

        # Ohne Key: Der Test meldet „Zugang abgelehnt“
        ohne = _testen(angemeldet, {"adresse": server.url + "/v1", "key_art": art})
        assert ohne["ok"] is False
        assert "lehnt den Zugang ab (401" in ohne["meldung"]
        assert "verlangt einen Key" in ohne["hinweis"]


def test_benutzer_und_passwort_braucht_passenden_zugang(
    angemeldet: TestClient, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    server, _app = ohne_beschreibung
    test = _testen(angemeldet, {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet), "key_art": "basic"})
    assert test["ok"] is False
    assert "Benutzer und Passwort" in test["meldung"]


def test_fremder_host_und_ausbruch_werden_abgelehnt(
    angemeldet: TestClient, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    server, app = ohne_beschreibung
    integration = _einrichten(angemeldet, {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet)})
    vorher = len(app.state.anfragen)
    for pfad in (
        "https://example.com/v1/artikel",
        "//example.com/v1",
        "/../geheim",
        "/%2e%2e/geheim",
        "javascript:alert(1)",
    ):
        aufruf = _aufrufen(angemeldet, integration, "abrufen", pfad=pfad)
        assert aufruf["ok"] is False, pfad
        assert "Abgelehnt" in aufruf["meldung"], aufruf
    assert len(app.state.anfragen) == vorher  # nichts davon ist irgendwo angekommen


def test_weiterleitung_auf_fremden_host_wird_nicht_verfolgt(angemeldet: TestClient) -> None:
    fremd_app = einfache_api()
    with LaufenderServer(fremd_app) as fremd:
        # Innerhalb der Adresse wird eine Weiterleitung verfolgt …
        with LaufenderServer(einfache_api()) as api:
            integration = _einrichten(angemeldet, {"adresse": api.url + "/v1"})
            innen = _aufrufen(angemeldet, integration, "abrufen", pfad="/weiter")
            assert innen["ok"] is True and "Apfel" in innen["ergebnis"]
        # … auf einen anderen Host nicht.
        with LaufenderServer(einfache_api(weiter_nach=fremd.url + "/v1/artikel")) as api:
            integration = _einrichten(angemeldet, {"adresse": api.url + "/v1"}, name="Umleitung")
            aufruf = _aufrufen(angemeldet, integration, "abrufen", pfad="/weiter")
            assert aufruf["ok"] is False
            assert "leitet auf eine andere Adresse weiter" in aufruf["meldung"]
    assert fremd_app.state.anfragen == []


def test_key_steht_in_keinem_protokoll(angemeldet: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with LaufenderServer(einfache_api(KEY, art="query", name="x")) as server:
        zugang = _zugang(angemeldet)
        integration = _einrichten(
            angemeldet,
            {"adresse": server.url + "/v1", "zugang": zugang, "key_art": "query", "key_name": "x"},
            name="Abfrage",
        )
        assert _aufrufen(angemeldet, integration, "abrufen", pfad="/artikel")["ok"] is True
        assert _aufrufen(angemeldet, integration, "abrufen", pfad="/gibt-es-nicht")["ok"] is False
        assert _aufrufen(angemeldet, integration, "abrufen", pfad="https://example.com")["ok"] is False
    assert "HTTP Request" in caplog.text  # die Anfragen mit dem Key in der URL stehen im Log …
    assert KEY not in caplog.text  # … aber geschwärzt
    assert KEY not in angemeldet.get("/api/protokoll").text
    assert KEY not in angemeldet.get("/api/integrationen").text
    assert KEY not in angemeldet.get("/api/ereignisse").text


def test_regelmaessige_pruefung_meldet_abgelehnten_zugang(
    app: FastAPI, angemeldet: TestClient, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    import anyio

    server, api_app = ohne_beschreibung
    zugang = _zugang(angemeldet)
    integration = _einrichten(angemeldet, {"adresse": server.url + "/v1", "zugang": zugang})
    vorher = len(api_app.state.anfragen)

    def pruefen() -> int:
        with app.state.datenbank.sitzung() as db:
            return anyio.run(app.state.integrationen.alle_pruefen, db)

    assert pruefen() >= 1
    assert len(api_app.state.anfragen) - vorher == 1  # eine günstige Anfrage, keine Suche
    assert angemeldet.get(f"/api/integrationen/{integration['id']}").json()["status"] == "ok"

    assert angemeldet.put(f"/api/zugaenge/{zugang}", json={"wert": "abgelaufen-000000"}).status_code == 200
    pruefen()
    danach = angemeldet.get(f"/api/integrationen/{integration['id']}").json()
    assert danach["status"] == "fehler"
    assert "lehnt den Zugang ab" in danach["status_meldung"]


def test_adresse_und_pfad_pruefen() -> None:
    adresse = Adresse("https://API.example.ch/v1/")
    assert adresse.url == "https://API.example.ch/v1"
    assert adresse.erlaubt("https://api.example.ch/v1/artikel")
    assert adresse.erlaubt("https://api.example.ch:443/v1")
    assert not adresse.erlaubt("https://api.example.ch/v10")
    assert not adresse.erlaubt("http://api.example.ch/v1/artikel")
    assert not adresse.erlaubt("https://api.example.ch:8443/v1/artikel")
    assert not adresse.erlaubt("https://api.example.ch.boese.ch/v1/artikel")
    assert not adresse.erlaubt("https://api.example.ch/v1/../geheim")
    assert pfad_pruefen("artikel?x=1") == "/artikel?x=1"
    for schlecht in ("..", "/a/../../b", "http://x", "\\\\x", "/a/%2E%2E/b"):
        with pytest.raises(IntegrationsFehler):
            pfad_pruefen(schlecht)
    with pytest.raises(IntegrationsFehler):
        Adresse("ftp://example.ch")


@pytest.mark.anyio
async def test_nach_dem_aktivieren_sofort_am_gateway(
    angemeldet: TestClient, panel: LaufenderServer, ohne_beschreibung: tuple[LaufenderServer, FastAPI]
) -> None:
    from test_gateway import _client_anlegen, _text, mcp

    server, _app = ohne_beschreibung
    _id, token = _client_anlegen(angemeldet)
    async with mcp(panel, token) as client:
        vorher = {werkzeug.name for werkzeug in (await client.list_tools()).tools}
        assert "lager_abrufen" not in vorher
        _einrichten(angemeldet, {"adresse": server.url + "/v1", "zugang": _zugang(angemeldet)})
        namen = {werkzeug.name for werkzeug in (await client.list_tools(cache_mode="refresh")).tools}
        assert {"lager_abrufen", "lager_senden"} <= namen
        ergebnis = await client.call_tool("lager_abrufen", {"pfad": "/artikel"})
        assert "Apfel" in _text(ergebnis)
