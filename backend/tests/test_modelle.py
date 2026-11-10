"""Modell-Verwaltung: Endpunkte, Rollen mit Ersatzmodell, OpenAI-kompatibler Anschluss und Statistik."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr
from missa_control.main import alte_daten_loeschen
from server import LaufenderServer, freier_port, modell_server

pytestmark = pytest.mark.anyio

KEY = "modell-geheimer-key-0123456789"


@pytest.fixture
def klein() -> Iterator[LaufenderServer]:
    with LaufenderServer(modell_server("klein-7b", api_key=KEY)) as server:
        yield server


@pytest.fixture
def gross() -> Iterator[LaufenderServer]:
    with LaufenderServer(modell_server("gross-70b")) as server:
        yield server


def _modell(
    admin: TestClient, name: str, server: LaufenderServer, modellname: str, **mehr: Any
) -> dict[str, Any]:
    antwort = admin.post(
        "/api/modelle", json={"name": name, "url": server.url + "/v1", "modellname": modellname, **mehr}
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _rolle(admin: TestClient, kennung: str) -> dict[str, Any]:
    return next(r for r in admin.get("/api/modelle").json()["rollen"] if r["kennung"] == kennung)


def _zuweisen(admin: TestClient, kennung: str, **modelle: int | None) -> None:
    antwort = admin.put(f"/api/rollen/{_rolle(admin, kennung)['id']}", json=modelle)
    assert antwort.status_code == 200, antwort.text


def _token(admin: TestClient) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {admin.post('/api/clients', json={'name': 'missa-core'}).json()['token']}"
    }


def _frage(text: str = "Hallo", modell: str = "missa-schnell", **mehr: Any) -> dict[str, Any]:
    return {"model": modell, "messages": [{"role": "user", "content": text}], **mehr}


def _statistik(admin: TestClient, name: str) -> dict[str, Any]:
    return next(m for m in admin.get("/api/modelle").json()["modelle"] if m["name"] == name)["statistik"]


# ====================================================================== Rollen


def test_rollen_schnell_und_stark_gibt_es_immer(angemeldet: TestClient) -> None:
    rollen = angemeldet.get("/api/modelle").json()["rollen"]
    assert [(r["kennung"], r["modellname"], r["fest"]) for r in rollen] == [
        ("schnell", "missa-schnell", True),
        ("stark", "missa-stark", True),
    ]
    assert "Gespräche" in rollen[0]["beschreibung"]
    assert "darf länger dauern" in rollen[1]["beschreibung"]
    fest = angemeldet.delete(f"/api/rollen/{rollen[0]['id']}")
    assert fest.status_code == 409

    neu = angemeldet.post("/api/rollen", json={"kennung": "uebersetzen", "name": "Übersetzen"})
    assert neu.status_code == 201
    assert neu.json()["modellname"] == "missa-uebersetzen"
    assert angemeldet.post("/api/rollen", json={"kennung": "uebersetzen"}).status_code == 409
    assert angemeldet.post("/api/rollen", json={"kennung": "Mit Leerzeichen"}).status_code == 422
    assert angemeldet.delete(f"/api/rollen/{neu.json()['id']}").json() == {"ok": True}


# ====================================================================== Modelle eintragen und testen


def test_modell_eintragen_und_testen_misst_antwortzeit_und_tokens(
    angemeldet: TestClient, klein: LaufenderServer
) -> None:
    zugang = angemeldet.post(
        "/api/zugaenge", json={"name": "Modell-Key", "typ": "api_key", "wert": KEY}
    ).json()
    modell = _modell(angemeldet, "Klein", klein, "klein-7b", zugang_id=zugang["id"], kontextlaenge=8192)
    assert modell["test"]["ok"] is None  # noch nie getestet
    assert modell["kontextlaenge"] == 8192
    assert KEY not in json.dumps(modell)

    test = angemeldet.post(f"/api/modelle/{modell['id']}/testen").json()["test"]
    assert test["ok"] is True
    assert test["meldung"] == "Das Modell antwortet."
    assert test["ms"] >= 0
    assert test["tokens_pro_s"] > 0
    assert test["zeit"]

    # Der Zugang wird verwendet: Anzeige und Schutz vor dem Löschen.
    zugaenge = angemeldet.get("/api/zugaenge").json()
    assert zugaenge[0]["verwendet_von"] == ["Modell „Klein“"]
    assert angemeldet.delete(f"/api/zugaenge/{zugang['id']}").status_code == 409


def test_verbindungstest_erklaert_fehler(angemeldet: TestClient, klein: LaufenderServer) -> None:
    def testen(**daten: Any) -> dict[str, Any]:
        modell = angemeldet.post("/api/modelle", json=daten).json()
        return angemeldet.post(f"/api/modelle/{modell['id']}/testen").json()["test"]

    ohne_key = testen(name="Ohne Key", url=klein.url + "/v1", modellname="klein-7b")
    assert ohne_key["ok"] is False
    assert "lehnt den Zugang ab (401" in ohne_key["meldung"]
    assert "Zugang" in ohne_key["hinweis"]

    zugang = angemeldet.post("/api/zugaenge", json={"name": "K", "typ": "api_key", "wert": KEY}).json()["id"]
    falscher_name = testen(
        name="Falscher Name", url=klein.url + "/v1", modellname="gibt-es-nicht", zugang_id=zugang
    )
    assert falscher_name["ok"] is False
    assert "404" in falscher_name["meldung"]
    assert "Modellname" in falscher_name["hinweis"]
    assert "gibt-es-nicht not found" in falscher_name["hinweis"]

    kein_openai = testen(name="Kein OpenAI", url=klein.url + "/kein-openai/v1", modellname="x")
    assert kein_openai["ok"] is False
    assert "nicht wie eine OpenAI-kompatible Schnittstelle" in kein_openai["meldung"]

    aus = testen(name="Aus", url=f"http://127.0.0.1:{freier_port()}/v1", modellname="x")
    assert aus["ok"] is False
    assert "nicht erreichbar" in aus["meldung"]
    assert aus["ms"] is None


def test_modell_eingaben_werden_geprueft(angemeldet: TestClient, gross: LaufenderServer) -> None:
    def anlegen(**daten: Any):
        return angemeldet.post(
            "/api/modelle", json={"name": "M", "url": "http://x/v1", "modellname": "m", **daten}
        )

    assert anlegen(url="kein-url").status_code == 422
    assert "/v1" in anlegen(url="kein-url").json()["hinweis"]
    assert anlegen(modellname=" ").status_code == 422
    assert anlegen(name=" ").status_code == 422
    assert anlegen(zugang_id=999).status_code == 422
    assert anlegen().status_code == 201
    assert anlegen().status_code == 409  # Name schon vergeben

    modell = _modell(angemeldet, "Gross", gross, "gross-70b")
    geaendert = angemeldet.put(
        f"/api/modelle/{modell['id']}",
        json={"name": "Gross 70B", "url": gross.url + "/v1/", "modellname": "gross-70b"},
    )
    assert geaendert.json()["name"] == "Gross 70B"
    assert geaendert.json()["url"] == gross.url + "/v1"  # Schrägstrich am Ende wird entfernt

    _zuweisen(angemeldet, "stark", haupt_modell_id=modell["id"])
    benutzt = angemeldet.delete(f"/api/modelle/{modell['id']}")
    assert benutzt.status_code == 409
    assert "„Stark“" in benutzt.json()["meldung"]
    _zuweisen(angemeldet, "stark", haupt_modell_id=None)
    assert angemeldet.delete(f"/api/modelle/{modell['id']}").json() == {"ok": True}


# ====================================================================== Modell-Anschluss /v1


async def test_anschluss_nur_mit_client_token(angemeldet: TestClient, panel: LaufenderServer) -> None:
    async with httpx2.AsyncClient(base_url=panel.url) as http:
        for antwort in (await http.get("/v1/models"), await http.post("/v1/chat/completions", json=_frage())):
            assert antwort.status_code == 401
            # Im Format der OpenAI-API, damit Clients die Meldung anzeigen:
            assert "Client-Token" in antwort.json()["error"]["message"]
        sitzung = {"Cookie": f"missa_control_sitzung={angemeldet.cookies.get('missa_control_sitzung')}"}
        assert (await http.get("/v1/models", headers=sitzung)).status_code == 401


async def test_rolle_umstellen_wirkt_sofort_ohne_aenderung_beim_client(
    angemeldet: TestClient, panel: LaufenderServer, klein: LaufenderServer, gross: LaufenderServer
) -> None:
    """Fertig-wenn: Rolle auf ein anderes Modell umstellen wirkt sofort, ohne dass der Client etwas ändert."""
    zugang = angemeldet.post("/api/zugaenge", json={"name": "K", "typ": "api_key", "wert": KEY}).json()["id"]
    modell_klein = _modell(angemeldet, "Klein", klein, "klein-7b", zugang_id=zugang)
    modell_gross = _modell(angemeldet, "Gross", gross, "gross-70b")
    _zuweisen(angemeldet, "schnell", haupt_modell_id=modell_klein["id"])

    async with httpx2.AsyncClient(base_url=panel.url, headers=_token(angemeldet)) as http:
        # Nur Rollen mit Modell erscheinen als Modellnamen.
        assert [m["id"] for m in (await http.get("/v1/models")).json()["data"]] == ["missa-schnell"]

        erste = await http.post("/v1/chat/completions", json=_frage("Wie geht's?"))
        assert erste.status_code == 200
        assert erste.json()["choices"][0]["message"]["content"] == "Antwort von klein-7b auf: Wie geht's?"
        assert erste.headers["x-missa-modell"] == "Klein"
        # Beim Modell kommen der echte Modellname und der Key aus dem Zugang an.
        letzte = klein.url and klein._server.config.app.state.anfragen[-1]
        assert letzte["model"] == "klein-7b"
        assert letzte["auth"] == f"Bearer {KEY}"
        assert KEY not in erste.text

        _zuweisen(angemeldet, "schnell", haupt_modell_id=modell_gross["id"])  # im Panel umgestellt
        zweite = await http.post("/v1/chat/completions", json=_frage("Wie geht's?"))  # dieselbe Anfrage
        assert zweite.json()["choices"][0]["message"]["content"] == "Antwort von gross-70b auf: Wie geht's?"
        assert zweite.headers["x-missa-modell"] == "Gross"

        unbekannt = await http.post("/v1/chat/completions", json=_frage(modell="gpt-4"))
        assert unbekannt.status_code == 404
        assert "missa-schnell, missa-stark" in unbekannt.json()["error"]["message"]
        ohne_modell = await http.post("/v1/chat/completions", json=_frage(modell="missa-stark"))
        assert ohne_modell.status_code == 503
        assert "noch kein Modell ausgewählt" in ohne_modell.json()["error"]["message"]
        assert (await http.post("/v1/chat/completions", content=b"kein json")).status_code == 400
        assert (await http.post("/v1/chat/completions", json={"messages": []})).status_code == 400


async def test_faellt_das_hauptmodell_aus_antwortet_das_ersatzmodell(
    angemeldet: TestClient, panel: LaufenderServer, gross: LaufenderServer
) -> None:
    """Fertig-wenn: Fällt das Hauptmodell aus, antwortet das Ersatzmodell."""
    with LaufenderServer(haupt_app := modell_server("haupt")) as haupt:
        modell_haupt = _modell(angemeldet, "Haupt", haupt, "haupt")
        modell_ersatz = _modell(angemeldet, "Ersatz", gross, "gross-70b")
        _zuweisen(
            angemeldet, "stark", haupt_modell_id=modell_haupt["id"], ersatz_modell_id=modell_ersatz["id"]
        )
        rolle = _rolle(angemeldet, "stark")
        assert (rolle["haupt_modell"], rolle["ersatz_modell"]) == ("Haupt", "Ersatz")

        async with httpx2.AsyncClient(base_url=panel.url, headers=_token(angemeldet), timeout=20) as http:
            normal = await http.post("/v1/chat/completions", json=_frage(modell="missa-stark"))
            assert normal.headers["x-missa-modell"] == "Haupt"

            haupt_app.state.kaputt = True  # Hauptmodell antwortet mit Fehler 500
            ersatz = await http.post("/v1/chat/completions", json=_frage(modell="missa-stark"))
            assert ersatz.status_code == 200
            assert ersatz.headers["x-missa-modell"] == "Ersatz"
            assert "Antwort von gross-70b" in ersatz.json()["choices"][0]["message"]["content"]

            # Ein Fehler in der Anfrage selbst (400) ist kein Ausfall: wird unverändert zurückgegeben.
            haupt_app.state.kaputt = False
            falsch = await http.post("/v1/chat/completions", json={"model": "missa-stark", "messages": []})
            assert falsch.status_code == 400
            assert falsch.json()["error"]["message"] == "messages must not be empty"
            assert falsch.headers["x-missa-modell"] == "Haupt"

    # Hauptmodell ganz weg (Server aus): auch dann springt das Ersatzmodell ein.
    async with httpx2.AsyncClient(
        base_url=panel.url, headers={"Authorization": _token_wieder(angemeldet)}
    ) as http:
        weg = await http.post("/v1/chat/completions", json=_frage(modell="missa-stark"))
        assert weg.headers["x-missa-modell"] == "Ersatz"

    assert _statistik(angemeldet, "Haupt") | {"antwortzeit_ms": 0, "tokens_pro_s": 0} == {
        "anfragen": 4,
        "fehler": 2,
        "antwortzeit_ms": 0,
        "tokens_pro_s": 0,
    }
    assert _statistik(angemeldet, "Ersatz")["anfragen"] == 2
    assert _statistik(angemeldet, "Ersatz")["fehler"] == 0


def _token_wieder(admin: TestClient) -> str:
    return "Bearer " + admin.post("/api/clients", json={"name": "zweiter"}).json()["token"]


async def test_alle_modelle_ausgefallen_gibt_klare_meldung(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    with LaufenderServer(app := modell_server("m")) as server:
        app.state.kaputt = True
        modell = _modell(angemeldet, "Einziges", server, "m")
        _zuweisen(angemeldet, "schnell", haupt_modell_id=modell["id"], ersatz_modell_id=modell["id"])
        async with httpx2.AsyncClient(base_url=panel.url, headers=_token(angemeldet)) as http:
            antwort = await http.post("/v1/chat/completions", json=_frage())
            strom = await http.post("/v1/chat/completions", json=_frage(stream=True))
    for fehler in (antwort, strom):
        assert fehler.status_code == 502
        assert "Kein Modell der Rolle „schnell“ hat geantwortet" in fehler.json()["error"]["message"]
        assert "model crashed" in fehler.json()["error"]["message"]
    assert len(app.state.anfragen) == 2  # dasselbe Modell wird nicht doppelt versucht


async def test_streaming_ueber_den_anschluss(angemeldet: TestClient, panel: LaufenderServer) -> None:
    """Fertig-wenn: Streaming über den Proxy funktioniert – Stück für Stück, nicht erst am Ende."""
    with (
        LaufenderServer(modell_server("strom", pause=0.08)) as server,
        LaufenderServer(kaputt := modell_server("x")) as aus,
    ):
        kaputt.state.kaputt = True
        modell = _modell(angemeldet, "Strom", server, "strom")
        defekt = _modell(angemeldet, "Defekt", aus, "x")
        _zuweisen(angemeldet, "schnell", haupt_modell_id=modell["id"])
        _zuweisen(angemeldet, "stark", haupt_modell_id=defekt["id"], ersatz_modell_id=modell["id"])

        async with httpx2.AsyncClient(base_url=panel.url, headers=_token(angemeldet), timeout=20) as http:
            for name, erwartet in (
                ("missa-schnell", "Strom"),
                ("missa-stark", "Strom"),
            ):  # stark: Ersatz springt ein
                zeiten: list[float] = []
                text = ""
                beendet = False
                start = time.monotonic()
                async with http.stream(
                    "POST", "/v1/chat/completions", json=_frage("eins zwei drei", name, stream=True)
                ) as strom:
                    assert strom.status_code == 200
                    assert strom.headers["content-type"].startswith("text/event-stream")
                    assert strom.headers["x-missa-modell"] == erwartet
                    async for zeile in strom.aiter_lines():
                        if zeile == "data: [DONE]":
                            beendet = True
                        elif zeile.startswith("data: "):
                            zeiten.append(time.monotonic() - start)
                            text += json.loads(zeile[6:])["choices"][0]["delta"]["content"]
                assert beendet
                assert text.strip() == "Antwort von strom auf: eins zwei drei"
                assert len(zeiten) == 7
                # Das erste Stück kommt deutlich vor dem letzten an: es wird wirklich gestreamt.
                assert zeiten[-1] - zeiten[0] > 0.3
                assert zeiten[0] < zeiten[-1] / 2

    statistik = _statistik(angemeldet, "Strom")
    assert statistik["anfragen"] == 2
    assert statistik["tokens_pro_s"] > 0  # beim Streaming werden die Stücke gezählt
    assert _statistik(angemeldet, "Defekt") == {
        "anfragen": 1,
        "fehler": 1,
        "antwortzeit_ms": None,
        "tokens_pro_s": None,
    }


async def test_statistik_der_letzten_sieben_tage(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer, gross: LaufenderServer, uhr: Uhr
) -> None:
    modell = _modell(angemeldet, "Gross", gross, "gross-70b")
    _zuweisen(angemeldet, "schnell", haupt_modell_id=modell["id"])
    kopf = _token(angemeldet)
    async with httpx2.AsyncClient(base_url=panel.url, headers=kopf) as http:
        for _ in range(3):
            assert (await http.post("/v1/chat/completions", json=_frage())).status_code == 200
    statistik = _statistik(angemeldet, "Gross")
    assert statistik["anfragen"] == 3
    assert statistik["fehler"] == 0
    assert statistik["antwortzeit_ms"] >= 0
    assert statistik["tokens_pro_s"] > 0

    def gespeichert() -> int:
        from missa_control.modellverwaltung.modelle import ModellAnfrage

        with app.state.datenbank.sitzung() as db:
            return db.query(ModellAnfrage).count()

    uhr.vor(days=6)
    alte_daten_loeschen(app)
    assert gespeichert() == 3
    uhr.vor(days=2)  # älter als 7 Tage
    with app.state.datenbank.sitzung() as db:
        assert app.state.modelle.uebersicht(db)["modelle"][0]["statistik"]["anfragen"] == 0
    alte_daten_loeschen(app)
    assert gespeichert() == 0
