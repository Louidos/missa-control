"""Fertige Vorlagen: ÖV-Fahrplan, ntfy, SearXNG (nur YAML) und Wetter (Python) – gegen Nachbauten der Schnittstellen."""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from missa_control.config import Einstellungen
from missa_control.integrationen.manifest import ManifestFehler, manifest_aus_text
from server import LaufenderServer

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------- Nachbauten


def fahrplan_api() -> FastAPI:
    """Nachbau von transport.opendata.ch/v1 (Antworten gekürzt nach der offiziellen Doku)."""
    app = FastAPI()
    app.state.anfragen = []

    @app.get("/v1/locations")
    def orte(request: Request) -> dict[str, Any]:
        app.state.anfragen.append(("locations", list(request.query_params.multi_items())))
        return {"stations": [{"id": "8503000", "name": "Zürich HB", "coordinate": {"type": "WGS84"}}]}

    @app.get("/v1/connections")
    def verbindungen(request: Request) -> dict[str, Any]:
        app.state.anfragen.append(("connections", list(request.query_params.multi_items())))
        return {
            "connections": [
                {
                    "from": {
                        "station": {"name": request.query_params["from"]},
                        "departure": "2026-11-16T08:02:00+0100",
                    },
                    "to": {
                        "station": {"name": request.query_params["to"]},
                        "arrival": "2026-11-16T08:58:00+0100",
                    },
                    "duration": "00d00:56:00",
                }
            ]
        }

    @app.get("/v1/stationboard")
    def abfahrten(request: Request) -> dict[str, Any]:
        app.state.anfragen.append(("stationboard", list(request.query_params.multi_items())))
        return {
            "station": {"name": request.query_params["station"]},
            "stationboard": [{"category": "S", "number": "3", "to": "Wetzikon"}],
        }

    return app


def ntfy_server(token: str) -> FastAPI:
    """Nachbau eines ntfy-Servers: JSON per POST an die Adresse des Servers, mit Bearer-Token."""
    app = FastAPI()
    app.state.nachrichten = []

    @app.get("/")
    def webapp() -> dict[str, str]:
        return {"app": "ntfy"}

    @app.post("/")
    async def senden(request: Request) -> Any:
        if request.headers.get("authorization") != f"Bearer {token}":
            return JSONResponse({"code": 40101, "error": "unauthorized"}, status_code=401)
        nachricht = await request.json()
        if "topic" not in nachricht:
            return JSONResponse({"error": "topic fehlt"}, status_code=400)
        app.state.nachrichten.append(nachricht)
        return {"id": "abc123", "event": "message", **nachricht}

    return app


def searxng(json_an: bool = True) -> FastAPI:
    """Nachbau von SearXNG: /search mit format=json – ohne eingeschaltetes JSON-Format kommt 403."""
    app = FastAPI()
    app.state.anfragen = []

    @app.get("/")
    def start() -> dict[str, str]:
        return {"searxng": "ok"}

    @app.get("/search")
    def suchen(request: Request) -> Any:
        app.state.anfragen.append(dict(request.query_params))
        if request.query_params.get("format") == "json" and not json_an:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return {
            "query": request.query_params["q"],
            "results": [
                {"title": "SearXNG", "url": "https://docs.searxng.org/", "content": "Metasuchmaschine"}
            ],
        }

    return app


def open_meteo() -> FastAPI:
    """Nachbau beider Open-Meteo-Adressen (Ortssuche und Wetter) in einem Server."""
    app = FastAPI()
    app.state.anfragen = []

    @app.get("/v1/search")
    def suchen(request: Request) -> dict[str, Any]:
        app.state.anfragen.append(("search", dict(request.query_params)))
        if request.query_params["name"] == "Atlantis":
            return {"generationtime_ms": 0.1}
        return {
            "results": [
                {
                    "name": "Zürich",
                    "latitude": 47.36667,
                    "longitude": 8.55,
                    "country": "Schweiz",
                    "admin1": "Zürich",
                    "timezone": "Europe/Zurich",
                }
            ]
        }

    @app.get("/v1/forecast")
    def vorhersage(request: Request) -> dict[str, Any]:
        app.state.anfragen.append(("forecast", dict(request.query_params)))
        daten: dict[str, Any] = {"latitude": 47.37, "longitude": 8.55}
        if "current" in request.query_params:
            daten["current"] = {
                "time": "2026-11-16T12:00",
                "temperature_2m": 6.4,
                "apparent_temperature": 3.9,
                "relative_humidity_2m": 81,
                "precipitation": 0.2,
                "weather_code": 61,
                "wind_speed_10m": 11.2,
            }
            daten["current_units"] = {"temperature_2m": "°C", "wind_speed_10m": "km/h"}
        if "daily" in request.query_params:
            tage = int(request.query_params.get("forecast_days", 7))
            daten["daily"] = {
                "time": [f"2026-11-{16 + i}" for i in range(tage)],
                "weather_code": [3] * tage,
                "temperature_2m_max": [8.1] * tage,
                "temperature_2m_min": [1.2] * tage,
                "precipitation_sum": [0.0] * tage,
                "precipitation_probability_max": [10] * tage,
                "wind_speed_10m_max": [14.0] * tage,
                "sunrise": ["07:30"] * tage,
                "sunset": ["16:50"] * tage,
            }
        return daten

    return app


# ---------------------------------------------------------------------- Hilfen


@pytest.fixture
def fahrplan() -> Iterator[tuple[LaufenderServer, FastAPI]]:
    app = fahrplan_api()
    with LaufenderServer(app) as server:
        yield server, app


@pytest.fixture
def einstellungen(
    einstellungen: Einstellungen, tmp_path: Path, fahrplan: tuple[LaufenderServer, FastAPI]
) -> Einstellungen:
    """Die eingebauten Integrationen – nur die feste Adresse des Fahrplans zeigt auf den Nachbau."""
    ordner = tmp_path / "integrations"
    shutil.copytree(REPO / "integrations", ordner)
    datei = ordner / "oev-fahrplan" / "integration.yaml"
    text = datei.read_text(encoding="utf-8")
    datei.write_text(
        text.replace("https://transport.opendata.ch/v1", fahrplan[0].url + "/v1"), encoding="utf-8"
    )
    return dataclasses.replace(einstellungen, integrations_ordner=ordner)


def _einrichten(client: TestClient, manifest_id: str, konfig: dict[str, Any]) -> dict[str, Any]:
    test = client.post(
        "/api/integrationen/testen", json={"manifest_id": manifest_id, "konfig": konfig}
    ).json()
    assert test["ok"] is True, test
    antwort = client.post(
        "/api/integrationen",
        json={
            "manifest_id": manifest_id,
            "konfig": konfig,
            "test_id": test["test_id"],
            "rechte": {f["name"]: f["recht"] for f in test["funktionen"]},
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _aufrufen(client: TestClient, integration: dict[str, Any], funktion: str, **argumente: Any) -> dict:
    return client.post(
        f"/api/integrationen/{integration['id']}/aufrufen",
        json={"funktion": funktion, "argumente": argumente},
    ).json()


def _zugang(client: TestClient, typ: str, wert: str) -> int:
    return client.post("/api/zugaenge", json={"name": "Vorlage", "typ": typ, "wert": wert}).json()["id"]


# ---------------------------------------------------------------------- Katalog


def test_vier_vorlagen_in_eigener_gruppe(angemeldet: TestClient) -> None:
    eintraege = angemeldet.get("/api/katalog").json()["eintraege"]
    vorlagen = [e for e in eintraege if e["gruppe"] == "Vorlagen"]
    assert {e["id"] for e in vorlagen} == {"wetter", "oev-fahrplan", "ntfy", "searxng"}
    # Vorlagen stehen nach den übrigen Karten, „API hinzufügen“ ganz vorne
    assert eintraege[0]["id"] == "api"
    assert [e["gruppe"] for e in eintraege] == sorted([e["gruppe"] for e in eintraege], key=bool)
    # Wetter und Fahrplan: kein Pflichtfeld, kein Key
    for kennung in ("wetter", "oev-fahrplan"):
        karte = next(e for e in vorlagen if e["id"] == kennung)
        assert [f for f in karte["felder"] if f["pflicht"] or f["typ"] == "zugang"] == []


# ---------------------------------------------------------------------- ÖV-Fahrplan


def test_oev_fahrplan_ohne_key(angemeldet: TestClient, fahrplan: tuple[LaufenderServer, FastAPI]) -> None:
    _server, app = fahrplan
    integration = _einrichten(angemeldet, "oev-fahrplan", {})
    assert {f["gateway_name"]: f["recht"] for f in integration["funktionen"]} == {
        "oev_abfahrten": "erlaubt",
        "oev_haltestelle_suchen": "erlaubt",
        "oev_verbindungen": "erlaubt",
    }
    verbindungen = next(f for f in integration["funktionen"] if f["name"] == "verbindungen")
    assert verbindungen["parameter"]["required"] == ["von", "nach"]
    assert verbindungen["parameter"]["properties"]["via"]["type"] == "array"

    ergebnis = _aufrufen(
        angemeldet,
        integration,
        "verbindungen",
        von="Bern",
        nach="Zürich HB",
        via=["Olten", "Aarau"],
        zeit="08:00",
    )
    assert ergebnis["ok"] is True, ergebnis
    assert "Zürich HB" in ergebnis["ergebnis"]
    art, parameter = app.state.anfragen[-1]
    assert art == "connections"
    assert parameter == [
        ("from", "Bern"),
        ("to", "Zürich HB"),
        ("via[]", "Olten"),
        ("via[]", "Aarau"),
        ("time", "08:00"),
        ("limit", "4"),
    ]

    assert "Wetzikon" in _aufrufen(angemeldet, integration, "abfahrten", haltestelle="Uster")["ergebnis"]
    assert app.state.anfragen[-1][1] == [("station", "Uster"), ("limit", "10")]
    assert _aufrufen(angemeldet, integration, "haltestelle_suchen", suchbegriff="Zürich")["ok"] is True
    assert app.state.anfragen[-1][1] == [("query", "Zürich"), ("type", "station")]
    fehlt = _aufrufen(angemeldet, integration, "verbindungen", von="Bern")
    assert fehlt["ok"] is False and "„nach“ fehlt" in fehlt["meldung"]
    # Nur einmal einrichtbar
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "oev-fahrplan")
    assert karte["kann_hinzufuegen"] is False


# ---------------------------------------------------------------------- ntfy


def test_ntfy_nachricht_senden(angemeldet: TestClient) -> None:
    token = "tk_ntfy-geheimes-token-123456"
    app = ntfy_server(token)
    with LaufenderServer(app) as server:
        zugang = _zugang(angemeldet, "bearer_token", token)
        integration = _einrichten(
            angemeldet, "ntfy", {"adresse": server.url, "thema": "missa-test", "zugang": zugang}
        )
        senden = next(f for f in integration["funktionen"] if f["name"] == "nachricht_senden")
        assert (senden["schreibend"], senden["recht"]) == (
            True,
            "erlaubt",
        )  # Senden ist standardmässig erlaubt
        ergebnis = _aufrufen(
            angemeldet,
            integration,
            "nachricht_senden",
            nachricht="Die Waschmaschine ist fertig",
            titel="Haushalt",
            prioritaet=4,
        )
        assert ergebnis["ok"] is True, ergebnis
        assert app.state.nachrichten == [
            {
                "topic": "missa-test",
                "message": "Die Waschmaschine ist fertig",
                "title": "Haushalt",
                "priority": 4,
            }
        ]
        assert token not in str(ergebnis)


def test_ntfy_ohne_thema_wird_erklaert(angemeldet: TestClient) -> None:
    antwort = angemeldet.post(
        "/api/integrationen/testen", json={"manifest_id": "ntfy", "konfig": {"adresse": "https://ntfy.sh"}}
    )
    assert antwort.status_code == 422
    assert "Thema" in antwort.json()["meldung"]


# ---------------------------------------------------------------------- SearXNG


def test_searxng_suche_mit_json(angemeldet: TestClient) -> None:
    app = searxng()
    with LaufenderServer(app) as server:
        integration = _einrichten(angemeldet, "searxng", {"adresse": server.url})
        assert [f["gateway_name"] for f in integration["funktionen"]] == ["websuche_suchen"]
        ergebnis = _aufrufen(
            angemeldet, integration, "suchen", suchbegriff="Missa", sprache="de", zeitraum="month"
        )
        assert ergebnis["ok"] is True, ergebnis
        assert "docs.searxng.org" in ergebnis["ergebnis"]
        assert app.state.anfragen[-1] == {
            "format": "json",
            "q": "Missa",
            "language": "de",
            "time_range": "month",
        }


def test_searxng_ohne_json_format_meldet_403(angemeldet: TestClient) -> None:
    with LaufenderServer(searxng(json_an=False)) as server:
        integration = _einrichten(angemeldet, "searxng", {"adresse": server.url})
        ergebnis = _aufrufen(angemeldet, integration, "suchen", suchbegriff="Missa")
        assert ergebnis["ok"] is False
        assert "403" in ergebnis["meldung"]
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "searxng")
    assert "JSON-Format" in karte["hinweis"] and "formats" in karte["hinweis"]


# ---------------------------------------------------------------------- Wetter


def test_wetter_ohne_key(angemeldet: TestClient) -> None:
    app = open_meteo()
    with LaufenderServer(app) as server:
        konfig = {"ort": "Zürich", "wetter_url": server.url, "ort_url": server.url}
        test = angemeldet.post(
            "/api/integrationen/testen", json={"manifest_id": "wetter", "konfig": konfig}
        ).json()
        assert test["ok"] is True, test
        assert "6.4 °C" in test["meldung"]
        integration = _einrichten(angemeldet, "wetter", konfig)
        assert {f["name"]: f["recht"] for f in integration["funktionen"]} == {
            "ort_suchen": "erlaubt",
            "vorhersage": "erlaubt",
            "wetter_aktuell": "erlaubt",
        }
        jetzt = _aufrufen(angemeldet, integration, "wetter_aktuell")
        assert jetzt["ok"] is True, jetzt
        assert "leichter Regen" in jetzt["ergebnis"] and "Zürich, Zürich, Schweiz" in jetzt["ergebnis"]
        assert app.state.anfragen[-2] == (
            "search",
            {"name": "Zürich", "count": "1", "language": "de", "format": "json"},
        )
        art, parameter = app.state.anfragen[-1]
        assert art == "forecast" and parameter["timezone"] == "auto"
        assert parameter["current"].split(",")[:2] == ["temperature_2m", "apparent_temperature"]

        drei = _aufrufen(angemeldet, integration, "vorhersage", ort="Zürich", tage=3)
        assert drei["ok"] is True and drei["ergebnis"].count('"datum"') == 3
        assert app.state.anfragen[-1][1]["forecast_days"] == "3"
        unbekannt = _aufrufen(angemeldet, integration, "wetter_aktuell", ort="Atlantis")
        assert unbekannt["ok"] is False and "Atlantis" in unbekannt["meldung"]


# ---------------------------------------------------------------------- eigene Vorlage nur mit YAML


def test_eigene_vorlage_nur_mit_yaml(einstellungen: Einstellungen, angemeldet: TestClient, fahrplan) -> None:
    server, _app = fahrplan
    ordner = einstellungen.eigene_integrationen_ordner / "meine-abfahrten"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "meine-abfahrten",
                "name": "Meine Abfahrten",
                "beschreibung": "Abfahrten ab Uster",
                "art": "api",
                "gruppe": "Vorlagen",
                "basis_url": server.url + "/v1",
                "endpunkte": [
                    {
                        "name": "ab_uster",
                        "pfad": "/stationboard",
                        "beschreibung": "Nächste Abfahrten ab Uster",
                        "query": {"station": "Uster"},
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    angemeldet.post("/api/katalog/einlesen")
    integration = _einrichten(angemeldet, "meine-abfahrten", {})
    assert "Wetzikon" in _aufrufen(angemeldet, integration, "ab_uster")["ergebnis"]


@pytest.mark.parametrize(
    ("teil", "meldung"),
    [
        ({"art": "python", "basis_url": "https://x.ch"}, "nur bei „art: api“"),
        ({"basis_url": "ftp://x.ch"}, "http://"),
        ({}, "„basis_url“ oder ein Feld „adresse“"),
    ],
)
def test_ungueltige_vorlage_wird_erklaert(teil: dict, meldung: str) -> None:
    daten = {"id": "x", "name": "X", "beschreibung": "x", "art": "api", **teil}
    with pytest.raises(ManifestFehler) as fehler:
        manifest_aus_text(yaml.safe_dump(daten))
    assert meldung in " ".join(fehler.value.meldungen)
