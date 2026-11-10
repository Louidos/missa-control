"""Integrationen einrichten: MCP-Server, REST-API (OpenAPI) und Python – mit Rechten und Fehlermeldungen."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from missa_control.config import Einstellungen
from missa_control.integrationen.adapter.openapi import funktionen_aus_spec, spec_lesen
from missa_control.integrationen.dienst import gateway_name, kennung_aus_name
from missa_control.integrationen.typen import IntegrationsFehler
from server import LaufenderServer, NurMitToken, artikel_rest_api, freier_port, notizen_mcp_server

TOKEN = "mcp-geheimes-token-0123456789"
API_KEY = "rest-geheimer-key-abcdefghij"


@pytest.fixture
def mcp_server() -> Iterator[LaufenderServer]:
    with LaufenderServer(notizen_mcp_server().streamable_http_app()) as server:
        yield server


@pytest.fixture
def rest_api() -> Iterator[LaufenderServer]:
    with LaufenderServer(artikel_rest_api(API_KEY)) as server:
        yield server


def _zugang(client: TestClient, name: str, typ: str, wert: str, **mehr: str) -> int:
    antwort = client.post("/api/zugaenge", json={"name": name, "typ": typ, "wert": wert, **mehr})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def _testen(client: TestClient, manifest_id: str, konfig: dict[str, Any], **mehr: Any) -> dict[str, Any]:
    antwort = client.post(
        "/api/integrationen/testen", json={"manifest_id": manifest_id, "konfig": konfig, **mehr}
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _einrichten(
    client: TestClient, manifest_id: str, konfig: dict[str, Any], name: str = "", rechte: dict | None = None
) -> dict[str, Any]:
    """Der Weg des Assistenten: testen, dann aktivieren."""
    test = _testen(client, manifest_id, konfig)
    assert test["ok"] is True, test
    antwort = client.post(
        "/api/integrationen",
        json={
            "manifest_id": manifest_id,
            "name": name,
            "konfig": konfig,
            "test_id": test["test_id"],
            "rechte": rechte if rechte is not None else {f["name"]: f["recht"] for f in test["funktionen"]},
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _aufrufen(
    client: TestClient, integration: dict[str, Any], funktion: str, **argumente: Any
) -> dict[str, Any]:
    return client.post(
        f"/api/integrationen/{integration['id']}/aufrufen",
        json={"funktion": funktion, "argumente": argumente},
    ).json()


# ====================================================================== MCP-Server


def test_mcp_server_in_drei_schritten(angemeldet: TestClient, mcp_server: LaufenderServer) -> None:
    """Fertig-wenn: Karte wählen → Formular (nur die URL) → testen und aktivieren; Funktionen werden angezeigt."""
    # Schritt 1: Karte im Katalog
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "mcp-server")
    pflichtfelder = [feld["name"] for feld in karte["felder"] if feld["pflicht"]]
    assert pflichtfelder == ["url"]

    # Schritt 2: Formular ausfüllen und testen
    test = _testen(angemeldet, "mcp-server", {"url": mcp_server.url + "/mcp"})
    assert test["ok"] is True
    assert "4 Funktion(en) gefunden" in test["meldung"]
    assert test["details"] == ["Verbindungsart: Streamable HTTP"]
    rechte = {funktion["name"]: funktion["recht"] for funktion in test["funktionen"]}
    assert rechte == {
        "notizen_auflisten": "erlaubt",  # vom Server als lesend gekennzeichnet
        "search_notizen": "erlaubt",  # ohne Kennzeichnung, aber eindeutig lesender Name
        "notiz_anlegen": "nachfragen",  # schreibend
        "get_and_delete_all": "nachfragen",  # als zerstörend gekennzeichnet, trotz „get“ im Namen
    }

    # Schritt 3: aktivieren
    antwort = angemeldet.post(
        "/api/integrationen",
        json={
            "manifest_id": "mcp-server",
            "name": "Notizen",
            "konfig": {"url": mcp_server.url + "/mcp"},
            "rechte": rechte,
            "test_id": test["test_id"],
        },
    )
    assert antwort.status_code == 201
    integration = antwort.json()
    assert integration["aktiv"] is True
    assert integration["status"] == "ok"
    assert integration["kennung"] == "notizen"
    assert sorted(f["gateway_name"] for f in integration["funktionen"]) == [
        "notizen_auflisten",
        "notizen_get_and_delete_all",
        "notizen_notiz_anlegen",
        "notizen_search_notizen",
    ]
    assert [
        e["eingerichtet"]
        for e in angemeldet.get("/api/katalog").json()["eintraege"]
        if e["id"] == "mcp-server"
    ] == [1]

    # Die Funktionen lassen sich wirklich aufrufen:
    assert (
        _aufrufen(angemeldet, integration, "notiz_anlegen", text="Brot kaufen")["ergebnis"]
        == "Notiz 2 gespeichert"
    )
    liste = _aufrufen(angemeldet, integration, "notizen_auflisten")
    assert liste["ok"] is True
    assert "Brot kaufen" in liste["ergebnis"]


def test_mcp_ueber_sse_wird_automatisch_erkannt(angemeldet: TestClient) -> None:
    with LaufenderServer(notizen_mcp_server().sse_app()) as server:
        integration = _einrichten(angemeldet, "mcp-server", {"url": server.url + "/sse"}, name="Alt")
        assert integration["status"] == "ok"
        assert (
            _aufrufen(angemeldet, integration, "search_notizen", begriff="milch")["ergebnis"]
            == "Milch kaufen"
        )
        # Auch wenn die Adresse nicht auf /sse endet, findet „automatisch“ die richtige Art:
        test = _testen(angemeldet, "mcp-server", {"url": server.url + "/sse", "verbindung": "auto"})
        assert test["details"] == ["Verbindungsart: SSE"]


def test_mcp_mit_zugang(angemeldet: TestClient) -> None:
    with LaufenderServer(NurMitToken(notizen_mcp_server().streamable_http_app(), TOKEN)) as server:
        ohne = _testen(angemeldet, "mcp-server", {"url": server.url + "/mcp"})
        assert ohne["ok"] is False
        assert "lehnt den Zugang ab" in ohne["meldung"]
        assert "Zugang" in ohne["hinweis"]

        falsch = _zugang(angemeldet, "Falsch", "bearer_token", "ein-falsches-token-999")
        mit_falschem = _testen(angemeldet, "mcp-server", {"url": server.url + "/mcp", "zugang": falsch})
        assert mit_falschem["ok"] is False
        assert "ein-falsches-token-999" not in json.dumps(mit_falschem)

        richtig = _zugang(angemeldet, "Notizen-Token", "bearer_token", TOKEN)
        integration = _einrichten(angemeldet, "mcp-server", {"url": server.url + "/mcp", "zugang": richtig})
        assert integration["konfig"]["zugang"] == richtig  # nur die Nummer, nie der Wert
        assert TOKEN not in json.dumps(integration)
        assert _aufrufen(angemeldet, integration, "notizen_auflisten")["ok"] is True

        # Der Zugang wird jetzt verwendet: Anzeige und Schutz vor versehentlichem Löschen.
        zugaenge = {z["name"]: z for z in angemeldet.get("/api/zugaenge").json()}
        assert zugaenge["Notizen-Token"]["verwendet_von"] == ["MCP-Server"]
        assert zugaenge["Falsch"]["verwendet_von"] == []
        loeschen = angemeldet.delete(f"/api/zugaenge/{richtig}")
        assert loeschen.status_code == 409
        assert "MCP-Server" in loeschen.json()["meldung"]


@pytest.mark.parametrize(
    ("pfad", "meldung", "hinweis"),
    [
        ("/gibt-es-nicht", "nicht gefunden (404)", "Stimmt die URL"),
        (None, "nicht erreichbar", "Läuft der Dienst"),
    ],
)
def test_mcp_fehler_sind_verstaendlich(
    angemeldet: TestClient, mcp_server: LaufenderServer, pfad: str | None, meldung: str, hinweis: str
) -> None:
    url = mcp_server.url + pfad if pfad else f"http://127.0.0.1:{freier_port()}/mcp"
    test = _testen(angemeldet, "mcp-server", {"url": url})
    assert test["ok"] is False
    assert meldung in test["meldung"]
    assert hinweis in test["hinweis"]
    # Aktivieren ohne erfolgreichen Test geht nicht:
    antwort = angemeldet.post(
        "/api/integrationen", json={"manifest_id": "mcp-server", "konfig": {"url": url}}
    )
    assert antwort.status_code == 422
    assert meldung in antwort.json()["meldung"]
    assert angemeldet.get("/api/integrationen").json() == []


def test_formular_wird_geprueft(angemeldet: TestClient) -> None:
    fehlt = angemeldet.post("/api/integrationen/testen", json={"manifest_id": "mcp-server", "konfig": {}})
    assert fehlt.status_code == 422
    assert fehlt.json()["meldung"] == "Bitte „URL des MCP-Servers“ ausfüllen."

    keine_url = angemeldet.post(
        "/api/integrationen/testen", json={"manifest_id": "mcp-server", "konfig": {"url": "192.168.1.5:8000"}}
    )
    assert keine_url.status_code == 422
    assert "keine gültige Adresse" in keine_url.json()["meldung"]
    assert "http://" in keine_url.json()["hinweis"]

    kein_zugang = angemeldet.post(
        "/api/integrationen/testen",
        json={"manifest_id": "mcp-server", "konfig": {"url": "http://x.example/mcp", "zugang": 999}},
    )
    assert kein_zugang.status_code == 422
    assert "existiert nicht mehr" in kein_zugang.json()["meldung"]

    falsche_auswahl = angemeldet.post(
        "/api/integrationen/testen",
        json={
            "manifest_id": "mcp-server",
            "konfig": {"url": "http://x.example/mcp", "verbindung": "brieftaube"},
        },
    )
    assert falsche_auswahl.status_code == 422

    unbekannt = angemeldet.post(
        "/api/integrationen/testen", json={"manifest_id": "gibt-es-nicht", "konfig": {}}
    )
    assert unbekannt.status_code == 404


# ====================================================================== Verwalten


def test_verwalten_deaktivieren_rechte_umbenennen_entfernen(
    angemeldet: TestClient, mcp_server: LaufenderServer
) -> None:
    integration = _einrichten(angemeldet, "mcp-server", {"url": mcp_server.url + "/mcp"}, name="Notizen")
    pfad = f"/api/integrationen/{integration['id']}"

    aus = angemeldet.put(pfad, json={"aktiv": False}).json()
    assert aus["aktiv"] is False
    assert angemeldet.put(pfad, json={"aktiv": True}).json()["aktiv"] is True

    geaendert = angemeldet.put(
        pfad, json={"rechte": {"notiz_anlegen": "erlaubt", "notizen_auflisten": "gesperrt"}}
    ).json()
    rechte = {f["name"]: f["recht"] for f in geaendert["funktionen"]}
    assert rechte["notiz_anlegen"] == "erlaubt"
    assert rechte["notizen_auflisten"] == "gesperrt"
    assert rechte["get_and_delete_all"] == "nachfragen"  # unverändert
    assert angemeldet.put(pfad, json={"rechte": {"notiz_anlegen": "manchmal"}}).status_code == 422

    umbenannt = angemeldet.put(pfad, json={"name": "Meine Notizen"}).json()
    assert umbenannt["name"] == "Meine Notizen"
    assert umbenannt["kennung"] == "notizen"  # Funktionsnamen bleiben stabil

    # Erneut testen behält die eingestellten Rechte.
    getestet = angemeldet.post(pfad + "/testen").json()
    assert getestet["status"] == "ok"
    assert {f["name"]: f["recht"] for f in getestet["funktionen"]}["notiz_anlegen"] == "erlaubt"

    assert angemeldet.delete(pfad).json() == {"ok": True}
    assert angemeldet.get("/api/integrationen").json() == []
    assert angemeldet.get(pfad).status_code == 404


def test_bearbeiten_mit_neuer_adresse_und_ausfall(
    angemeldet: TestClient, mcp_server: LaufenderServer
) -> None:
    integration = _einrichten(angemeldet, "mcp-server", {"url": mcp_server.url + "/mcp"}, name="Notizen")
    pfad = f"/api/integrationen/{integration['id']}"

    # Adresse zeigt ins Leere: wird gespeichert, der Status zeigt den Fehler mit Hinweis.
    kaputt = angemeldet.put(pfad, json={"konfig": {"url": f"http://127.0.0.1:{freier_port()}/mcp"}}).json()
    assert kaputt["status"] == "fehler"
    assert "nicht erreichbar" in kaputt["status_meldung"]
    assert kaputt["status_hinweis"]
    assert len(kaputt["funktionen"]) == 4  # Funktionen und Rechte bleiben erhalten

    aufruf = _aufrufen(angemeldet, kaputt, "notizen_auflisten")
    assert aufruf["ok"] is False
    assert "nicht erreichbar" in aufruf["meldung"]

    repariert = angemeldet.put(pfad, json={"konfig": {"url": mcp_server.url + "/mcp"}}).json()
    assert repariert["status"] == "ok"


def test_zwei_gleiche_integrationen_bekommen_eigene_vorsilben(
    angemeldet: TestClient, mcp_server: LaufenderServer
) -> None:
    eins = _einrichten(angemeldet, "mcp-server", {"url": mcp_server.url + "/mcp"}, name="Notizen")
    zwei = _einrichten(angemeldet, "mcp-server", {"url": mcp_server.url + "/mcp"}, name="Notizen")
    assert (eins["kennung"], zwei["kennung"]) == ("notizen", "notizen_2")
    namen = [f["gateway_name"] for i in angemeldet.get("/api/integrationen").json() for f in i["funktionen"]]
    assert len(namen) == len(set(namen)) == 8


def test_kennung_und_gateway_namen() -> None:
    assert kennung_aus_name("Mein Wetter-Dienst (Zürich)") == "mein_wetter_dienst_zuerich"
    assert kennung_aus_name("123 Sonne") == "i_123_sonne"
    assert kennung_aus_name("!!!") == "integration"
    assert gateway_name("kalender", "termine_anzeigen") == "kalender_termine_anzeigen"
    assert gateway_name("serverlast", "serverlast_aktuell") == "serverlast_aktuell"  # keine doppelte Vorsilbe
    assert gateway_name("api", "get.user/by-id") == "api_get_user_by-id"
    lang = gateway_name(
        "eine_sehr_lange_kennung_fuer_tests", "und_ein_noch_viel_laengerer_funktionsname_als_erlaubt"
    )
    assert len(lang) <= 64


# ====================================================================== REST-API (OpenAPI)

SPEC_YAML = """
openapi: 3.0.3
info: {title: Artikel-API, version: "1.0"}
paths:
  /artikel:
    get:
      operationId: artikel_auflisten
      summary: Alle Artikel auflisten
      parameters:
        - {name: suche, in: query, schema: {type: string}, description: Suchbegriff}
    post:
      operationId: artikel_anlegen
      summary: Einen Artikel anlegen
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: "#/components/schemas/Artikel"}
  /artikel/{artikel_id}:
    parameters:
      - {name: artikel_id, in: path, required: true, schema: {type: integer}}
    get: {operationId: artikel_lesen, summary: Einen Artikel lesen}
    delete: {operationId: artikel_loeschen, summary: Einen Artikel löschen}
components:
  securitySchemes:
    key: {type: apiKey, in: header, name: X-API-Key}
  schemas:
    Artikel:
      type: object
      required: [name]
      properties:
        name: {type: string}
        preis: {type: number, nullable: true}
        aehnlich: {$ref: "#/components/schemas/Artikel"}
"""


def test_openapi_datei_hochladen_erzeugt_funktionen_mit_auswahl_und_rechten(
    angemeldet: TestClient, rest_api: LaufenderServer
) -> None:
    """Fertig-wenn: OpenAPI-Datei hochladen erzeugt Funktionen; Auswahl und Rechte funktionieren."""
    zugang = _zugang(angemeldet, "Artikel-Key", "api_key", API_KEY)
    konfig = {"spec_datei": SPEC_YAML, "basis_url": rest_api.url, "zugang": zugang}

    test = _testen(angemeldet, "rest-api", konfig)
    assert test["ok"] is True, test
    assert test["meldung"] == "Artikel-API: 4 Funktion(en) aus der Beschreibung erzeugt."
    assert (
        "Zugang wird mitgeschickt als: Header „X-API-Key“ (wird beim ersten Aufruf geprüft)"
        in test["details"]
    )
    assert {f["name"]: (f["schreibend"], f["recht"]) for f in test["funktionen"]} == {
        "artikel_auflisten": (False, "erlaubt"),  # GET = lesend
        "artikel_lesen": (False, "erlaubt"),
        "artikel_anlegen": (True, "nachfragen"),  # alles andere = schreibend
        "artikel_loeschen": (True, "nachfragen"),
    }

    # Auswahl: Löschen soll Missa gar nicht sehen.
    rechte = {f["name"]: f["recht"] for f in test["funktionen"]} | {"artikel_loeschen": "gesperrt"}
    integration = _einrichten(angemeldet, "rest-api", konfig, name="Artikel", rechte=rechte)
    nach_name = {f["name"]: f for f in integration["funktionen"]}
    assert nach_name["artikel_loeschen"]["recht"] == "gesperrt"
    assert nach_name["artikel_auflisten"]["beschreibung"] == "Alle Artikel auflisten (GET /artikel)"
    assert nach_name["artikel_auflisten"]["parameter"]["properties"]["suche"] == {
        "type": "string",
        "description": "Suchbegriff",
    }
    koerper = nach_name["artikel_anlegen"]["parameter"]
    assert koerper["required"] == ["body"]
    assert koerper["properties"]["body"]["properties"]["name"] == {"type": "string"}
    assert koerper["properties"]["body"]["properties"]["preis"] == {"type": ["number", "null"]}
    assert "$ref" not in json.dumps(koerper)  # Verweise sind aufgelöst, auch der auf sich selbst
    assert nach_name["artikel_lesen"]["parameter"]["required"] == ["artikel_id"]

    # Die hochgeladene Datei wird nicht zurückgeschickt, nur dass es sie gibt.
    assert integration["konfig"]["spec_datei"] == {"datei": True, "zeichen": len(SPEC_YAML)}

    # Aufrufe gehen mit dem Key im richtigen Header an die API:
    assert json.loads(_aufrufen(angemeldet, integration, "artikel_auflisten")["ergebnis"]) == [
        {"id": 1, "name": "Apfel", "preis": 0.5}
    ]
    neu = _aufrufen(angemeldet, integration, "artikel_anlegen", body={"name": "Birne", "preis": 0.8})
    assert json.loads(neu["ergebnis"]) == {"id": 2, "name": "Birne", "preis": 0.8}
    assert (
        json.loads(_aufrufen(angemeldet, integration, "artikel_lesen", artikel_id=2)["ergebnis"])["name"]
        == "Birne"
    )
    gefunden = json.loads(_aufrufen(angemeldet, integration, "artikel_auflisten", suche="bir")["ergebnis"])
    assert [a["name"] for a in gefunden] == ["Birne"]

    fehlt = _aufrufen(angemeldet, integration, "artikel_lesen", artikel_id=99)
    assert fehlt["ok"] is False
    assert "404" in fehlt["meldung"]
    assert "gibt es nicht" in fehlt["meldung"]

    # Bearbeiten ohne erneutes Hochladen behält die Datei:
    geaendert = angemeldet.put(
        f"/api/integrationen/{integration['id']}",
        json={
            "konfig": {
                "spec_datei": integration["konfig"]["spec_datei"],
                "basis_url": rest_api.url,
                "zugang": zugang,
            }
        },
    ).json()
    assert geaendert["status"] == "ok"
    assert len(geaendert["funktionen"]) == 4
    assert {f["name"]: f["recht"] for f in geaendert["funktionen"]}["artikel_loeschen"] == "gesperrt"


def test_openapi_per_url_und_falscher_key(angemeldet: TestClient, rest_api: LaufenderServer) -> None:
    falsch = _zugang(angemeldet, "Falscher Key", "api_key", "falscher-key-000000")
    integration = _einrichten(
        angemeldet, "rest-api", {"spec_url": rest_api.url + "/openapi.json", "zugang": falsch}, name="Artikel"
    )
    assert integration["status"] == "ok"  # die Beschreibung ist lesbar, der Key wird erst beim Aufruf geprüft
    assert len(integration["funktionen"]) == 4

    aufruf = _aufrufen(angemeldet, integration, "artikel_auflisten")
    assert aufruf["ok"] is False
    assert "lehnt den Zugang ab (401" in aufruf["meldung"]
    assert "Zugang" in aufruf["hinweis"]
    assert "falscher-key-000000" not in json.dumps(aufruf)

    # Key korrigieren (unter „Zugänge“) – danach klappt es ohne weitere Änderung.
    assert angemeldet.put(f"/api/zugaenge/{falsch}", json={"wert": API_KEY}).status_code == 200
    assert _aufrufen(angemeldet, integration, "artikel_auflisten")["ok"] is True


@pytest.mark.parametrize(
    ("konfig", "meldung"),
    [
        ({}, "Es fehlt die OpenAPI-Beschreibung"),
        ({"spec_datei": "das ist: [kein gültiges yaml"}, "weder gültiges JSON noch gültiges YAML"),
        ({"spec_datei": '{"hallo": "welt"}'}, "keine OpenAPI-Beschreibung"),
        ({"spec_datei": '{"openapi": "3.0.0", "paths": {}}'}, "enthält keine Endpunkte"),
        (
            {"spec_datei": '{"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}'},
            "Adresse der API ist unbekannt",
        ),
    ],
)
def test_openapi_fehler_sind_verstaendlich(
    angemeldet: TestClient, konfig: dict[str, str], meldung: str
) -> None:
    test = _testen(angemeldet, "rest-api", konfig)
    assert test["ok"] is False
    assert meldung in test["meldung"]
    assert test["hinweis"]


def test_openapi_nicht_erreichbar(angemeldet: TestClient) -> None:
    test = _testen(angemeldet, "rest-api", {"spec_url": f"http://127.0.0.1:{freier_port()}/openapi.json"})
    assert test["ok"] is False
    assert "nicht erreichbar" in test["meldung"]


def test_grosse_api_startet_ohne_auswahl(angemeldet: TestClient, rest_api: LaufenderServer) -> None:
    pfade = {f"/dinge/{nummer}": {"get": {"operationId": f"ding_{nummer}"}} for nummer in range(60)}
    spec = json.dumps({"openapi": "3.0.0", "info": {"title": "Gross"}, "paths": pfade})
    test = _testen(angemeldet, "rest-api", {"spec_datei": spec, "basis_url": rest_api.url})
    assert test["viele_funktionen"] is True
    assert {f["recht"] for f in test["funktionen"]} == {"gesperrt"}  # man wählt gezielt aus, was Missa sieht


def test_swagger_2_und_namen_ohne_operation_id() -> None:
    spec = spec_lesen(
        yaml.safe_dump(
            {
                "swagger": "2.0",
                "host": "api.example.ch",
                "basePath": "/v2",
                "paths": {
                    "/pets/{petId}": {
                        "get": {
                            "parameters": [
                                {"name": "petId", "in": "path", "required": True, "type": "integer"}
                            ]
                        },
                        "put": {
                            "parameters": [
                                {"name": "petId", "in": "path", "required": True, "type": "integer"},
                                {
                                    "name": "body",
                                    "in": "body",
                                    "required": True,
                                    "schema": {"type": "object"},
                                },
                            ]
                        },
                    },
                    "/2fa/status": {"get": {}},
                },
            }
        )
    )
    funktionen = {f.name: f for f in funktionen_aus_spec(spec)}
    assert set(funktionen) == {"get_pets_petId", "put_pets_petId", "get_2fa_status"}
    assert funktionen["get_pets_petId"].schreibend is False
    assert funktionen["put_pets_petId"].schreibend is True
    assert funktionen["put_pets_petId"].parameter["required"] == ["body", "petId"]
    assert funktionen["get_pets_petId"].parameter["properties"]["petId"] == {"type": "integer"}
    with pytest.raises(IntegrationsFehler, match="zu gross"):
        spec_lesen("x" * (5 * 1024 * 1024 + 1))


# ====================================================================== Python-Integrationen

MANIFEST = """
id: werkbank
name: Werkbank
beschreibung: Test-Integration
art: python
mehrfach: false
felder:
  - {name: faktor, titel: Faktor, typ: zahl, standard: 2}
  - {name: laut, titel: Laut, typ: schalter}
  - {name: geheim, titel: Geheimnis, typ: zugang}
  - {name: raum, titel: Raum, typ: auswahl, nach_test: true, pflicht: true}
standardrechte:
  zaehler_erhoehen: erlaubt
"""

MAIN = '''
from typing import Literal

from missa_control.sdk import Fehler, Kontext, funktion, verbindungstest


@verbindungstest
async def testen(kontext: Kontext) -> dict:
    return {"meldung": "Werkbank bereit", "details": ["2 Räume gefunden"],
            "optionen": {"raum": [{"wert": "k", "titel": "Küche"}, "Bad"]}}


@funktion(schreibend=False)
def rechnen(kontext: Kontext, zahl: int, art: Literal["mal", "plus"] = "mal") -> dict:
    """Rechnet mit dem eingestellten Faktor.

    zahl: Die Zahl, mit der gerechnet wird
    art: Rechenart
    """
    faktor = kontext.konfig["faktor"]
    return {"ergebnis": zahl * faktor if art == "mal" else zahl + faktor, "raum": kontext.konfig.get("raum")}


@funktion(beschreibung="Zählt hoch und merkt sich den Stand.")
async def zaehler_erhoehen(kontext: Kontext) -> int:
    kontext.zustand["zaehler"] = kontext.zustand.get("zaehler", 0) + 1
    return kontext.zustand["zaehler"]


@funktion
def geheimnis_laenge(kontext: Kontext) -> int:
    """Gibt nur die Länge des Geheimnisses zurück."""
    return len(kontext.zugang("geheim").wert)


@funktion(schreibend=False, name="ohne_kontext")
def kein_kontext(text: str) -> str:
    return text.upper()


@funktion(schreibend=False)
def absichtlich(kontext: Kontext) -> None:
    raise Fehler("Die Werkbank klemmt.", "Bitte ölen.")


@funktion(schreibend=False)
def versehentlich(kontext: Kontext) -> None:
    return 1 / 0


def hilfsfunktion() -> None:  # ohne @funktion: bleibt für Missa unsichtbar
    pass
'''


@pytest.fixture
def werkbank(einstellungen: Einstellungen) -> Path:
    ordner = einstellungen.eigene_integrationen_ordner / "werkbank"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(MANIFEST, encoding="utf-8")
    (ordner / "main.py").write_text(MAIN, encoding="utf-8")
    return ordner


def test_python_funktionen_aus_typ_hinweisen_und_docstring(werkbank: Path, angemeldet: TestClient) -> None:
    test = _testen(angemeldet, "werkbank", {})
    assert test["ok"] is True, test
    assert test["meldung"] == "Werkbank bereit"
    assert test["details"] == ["2 Räume gefunden"]
    assert test["optionen"] == {"raum": [{"wert": "k", "titel": "Küche"}, {"wert": "Bad", "titel": "Bad"}]}
    nach_name = {f["name"]: f for f in test["funktionen"]}
    assert set(nach_name) == {
        "rechnen",
        "zaehler_erhoehen",
        "geheimnis_laenge",
        "ohne_kontext",
        "absichtlich",
        "versehentlich",
    }
    assert nach_name["rechnen"]["beschreibung"] == "Rechnet mit dem eingestellten Faktor."
    assert nach_name["rechnen"]["recht"] == "erlaubt"  # lesend
    assert nach_name["geheimnis_laenge"]["recht"] == "nachfragen"  # ohne Angabe gilt: schreibend
    assert nach_name["geheimnis_laenge"]["beschreibung"] == "Gibt nur die Länge des Geheimnisses zurück."
    assert nach_name["zaehler_erhoehen"]["recht"] == "erlaubt"  # laut standardrechte im Manifest

    # Das Feld „Raum“ kommt erst nach dem Test – ohne Auswahl lässt sich nicht aktivieren.
    ohne_raum = angemeldet.post(
        "/api/integrationen", json={"manifest_id": "werkbank", "konfig": {}, "test_id": test["test_id"]}
    )
    assert ohne_raum.status_code == 422
    assert ohne_raum.json()["meldung"] == "Bitte „Raum“ ausfüllen."

    geheim = _zugang(angemeldet, "Geheim", "api_key", "zwölf-zeichen")
    antwort = angemeldet.post(
        "/api/integrationen",
        json={
            "manifest_id": "werkbank",
            "konfig": {"raum": "k", "geheim": geheim},
            "test_id": test["test_id"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    integration = antwort.json()
    assert integration["kennung"] == "werkbank"
    schema = {f["name"]: f["parameter"] for f in integration["funktionen"]}["rechnen"]
    assert schema == {
        "type": "object",
        "additionalProperties": False,
        "required": ["zahl"],
        "properties": {
            "zahl": {"type": "integer", "description": "Die Zahl, mit der gerechnet wird"},
            "art": {"type": "string", "enum": ["mal", "plus"], "default": "mal", "description": "Rechenart"},
        },
    }

    assert json.loads(_aufrufen(angemeldet, integration, "rechnen", zahl=21)["ergebnis"]) == {
        "ergebnis": 42,
        "raum": "k",
    }
    assert (
        json.loads(_aufrufen(angemeldet, integration, "rechnen", zahl="5", art="plus")["ergebnis"])[
            "ergebnis"
        ]
        == 7
    )
    assert _aufrufen(angemeldet, integration, "ohne_kontext", text="hallo")["ergebnis"] == "HALLO"
    assert _aufrufen(angemeldet, integration, "geheimnis_laenge")["ergebnis"] == "13"

    # Das kleine Gedächtnis der Integration bleibt erhalten:
    assert _aufrufen(angemeldet, integration, "zaehler_erhoehen")["ergebnis"] == "1"
    assert _aufrufen(angemeldet, integration, "zaehler_erhoehen")["ergebnis"] == "2"

    # Fehler: falsche Parameter, absichtlich gemeldet, versehentlich passiert.
    falsch = _aufrufen(angemeldet, integration, "rechnen", zahl="viele", unbekannt=1)
    assert falsch["ok"] is False
    assert "Ungültige Parameter für „rechnen“" in falsch["meldung"]
    assert _aufrufen(angemeldet, integration, "absichtlich") == {
        "ok": False,
        "meldung": "Die Werkbank klemmt.",
        "hinweis": "Bitte ölen.",
    }
    versehen = _aufrufen(angemeldet, integration, "versehentlich")
    assert versehen["ok"] is False
    assert "Fehler in „versehentlich“: ZeroDivisionError" in versehen["meldung"]
    assert "main.py" in versehen["hinweis"]
    assert _aufrufen(angemeldet, integration, "hilfsfunktion")["ok"] is False

    # mehrfach: false → kein zweites Mal
    nochmal = angemeldet.post("/api/integrationen", json={"manifest_id": "werkbank", "konfig": {"raum": "k"}})
    assert nochmal.status_code == 409
    assert "bereits eingerichtet" in nochmal.json()["meldung"]
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "werkbank")
    assert karte["kann_hinzufuegen"] is False


def test_python_aenderungen_an_main_py_wirken_nach_erneutem_test(
    werkbank: Path, angemeldet: TestClient
) -> None:
    test = _testen(angemeldet, "werkbank", {})
    integration = angemeldet.post(
        "/api/integrationen",
        json={"manifest_id": "werkbank", "konfig": {"raum": "k"}, "test_id": test["test_id"]},
    ).json()

    neu = MAIN.replace("return text.upper()", "return text.lower()").replace(
        "@funktion(schreibend=False)\ndef versehentlich(kontext: Kontext) -> None:\n    return 1 / 0\n", ""
    )
    neu += '\n\n@funktion(schreibend=False)\ndef neu_dabei(kontext: Kontext) -> str:\n    return "neu"\n'
    (werkbank / "main.py").write_text(neu, encoding="utf-8")

    getestet = angemeldet.post(f"/api/integrationen/{integration['id']}/testen").json()
    vorhanden = {f["name"]: f["vorhanden"] for f in getestet["funktionen"]}
    assert vorhanden["neu_dabei"] is True
    assert vorhanden["versehentlich"] is False  # gibt es nicht mehr, wird nur markiert
    assert _aufrufen(angemeldet, getestet, "ohne_kontext", text="HALLO")["ergebnis"] == "hallo"
    assert _aufrufen(angemeldet, getestet, "versehentlich")["ok"] is False


@pytest.mark.parametrize(
    ("code", "meldung"),
    [
        ("def kaputt(:\n", "Syntaxfehler in Zeile 1"),
        (
            "import gibt_es_nicht_paket\n",
            "braucht ein Python-Paket, das nicht installiert ist: gibt_es_nicht_paket",
        ),
        ("raise RuntimeError('beim Laden')\n", "konnte nicht geladen werden: RuntimeError: beim Laden"),
        (
            "from missa_control.sdk import funktion\n@funktion\ndef f(*alles): pass\n",
            "verwendet *args oder **kwargs",
        ),
        (
            "from missa_control.sdk import funktion\n@funktion\ndef f(x: 'GibtEsNicht'): pass\n",
            "Typ-Hinweise von „f“ lassen sich nicht auswerten",
        ),
    ],
)
def test_python_fehler_in_main_py_sind_verstaendlich(
    werkbank: Path, angemeldet: TestClient, code: str, meldung: str
) -> None:
    (werkbank / "main.py").write_text(code, encoding="utf-8")
    test = _testen(angemeldet, "werkbank", {})
    assert test["ok"] is False
    assert meldung in test["meldung"]
    assert test["hinweis"]
