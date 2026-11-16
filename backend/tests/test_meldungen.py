"""Meldungen an ntfy oder einen Webhook: Freigabe wartet, Integration ausgefallen, Schutz vor Flut."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from missa_control.meldungen.dienst import Meldung
from server import LaufenderServer, freier_port

TOKEN = "tk_meldungs-token-geheim-0123"


def empfaenger(langsam: float = 0.0) -> FastAPI:
    """Nimmt Meldungen entgegen wie ntfy (POST an die Adresse) bzw. ein Webhook – und merkt sie sich."""
    app = FastAPI()
    app.state.meldungen = []

    @app.post("/")
    @app.post("/hook")
    async def annehmen(request: Request) -> Any:
        if langsam:
            time.sleep(langsam)
        if request.headers.get("authorization") not in (None, f"Bearer {TOKEN}"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        app.state.meldungen.append(
            {"inhalt": await request.json(), "auth": request.headers.get("authorization")}
        )
        return {"ok": True}

    return app


@pytest.fixture
def ziel_server() -> Iterator[tuple[LaufenderServer, FastAPI]]:
    app = empfaenger()
    with LaufenderServer(app) as server:
        yield server, app


def _warte(bedingung, sekunden: float = 5.0) -> Any:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        wert = bedingung()
        if wert:
            return wert
        time.sleep(0.05)
    raise AssertionError("Bedingung nicht rechtzeitig erfüllt")


def _ziel(client: TestClient, **daten: Any) -> dict[str, Any]:
    antwort = client.post(
        "/api/meldungen",
        json={"name": "Handy", "art": "ntfy", "thema": "missa", "panel_adresse": "http://ai01:8090", **daten},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_standardarten_und_pruefung(angemeldet: TestClient) -> None:
    arten = {a["wert"]: a["standard"] for a in angemeldet.get("/api/meldungen").json()["arten"]}
    assert arten == {"freigabe": True, "integration": True, "geraet_offline": False, "regel_hoch": False}
    ohne_thema = angemeldet.post(
        "/api/meldungen", json={"name": "x", "art": "ntfy", "adresse": "https://ntfy.sh"}
    )
    assert ohne_thema.status_code == 422 and "Thema" in ohne_thema.json()["meldung"]
    falsch = angemeldet.post("/api/meldungen", json={"name": "x", "art": "mail", "adresse": "https://x.ch"})
    assert falsch.status_code == 422


def test_wartende_freigabe_kommt_mit_vorschau_und_link_an(
    app: FastAPI, angemeldet: TestClient, ziel_server: tuple[LaufenderServer, FastAPI]
) -> None:
    server, empfang = ziel_server
    zugang = angemeldet.post(
        "/api/zugaenge", json={"name": "ntfy", "typ": "bearer_token", "wert": TOKEN}
    ).json()["id"]
    _ziel(angemeldet, adresse=server.url, zugang_id=zugang, arten=["freigabe", "integration"])
    start = time.monotonic()
    app.state.ereignisse.melden(
        "freigabe",
        "Freigabe nötig: kalender_termin_loeschen",
        "…",
        dringlichkeit="hoch",
        daten={
            "freigabe_id": 7,
            "funktion": "kalender_termin_loeschen",
            "client": "missa-core",
            "vorschau": "Löscht den Termin „Zahnarzt“ am 3. Februar",
        },
    )
    assert time.monotonic() - start < 0.5  # das Panel wartet nicht aufs Senden
    eingang = _warte(lambda: empfang.state.meldungen)[0]
    inhalt = eingang["inhalt"]
    assert inhalt["topic"] == "missa"
    assert inhalt["title"] == "Freigabe wartet: kalender_termin_loeschen"
    assert "Löscht den Termin „Zahnarzt“" in inhalt["message"]
    assert inhalt["click"] == "http://ai01:8090/freigaben"
    assert inhalt["priority"] == 4
    assert eingang["auth"] == f"Bearer {TOKEN}"
    assert "actions" not in inhalt  # Erlauben und Ablehnen nur im Panel


def test_freigabe_im_gateway_meldet_vorschau_ohne_parameter(app: FastAPI) -> None:
    """Das Ereignis einer echten Freigabe trägt die Vorschau, aber keine Parameter."""
    gesehen: list[dict[str, Any]] = []
    app.state.ereignisse.zuhoerer.append(gesehen.append)

    import anyio

    async def anfragen() -> str:
        with anyio.move_on_after(0.3):
            return await app.state.freigaben.anfragen(
                client_name="missa-core",
                integration_name="Kalender",
                funktion="kalender_loeschen",
                beschreibung="",
                argumente={"passwort": "streng-geheim-42"},
                vorschau="Löscht den Termin",
            )
        return "abgebrochen"

    anyio.run(anfragen)
    ereignis = next(e for e in gesehen if e["art"] == "freigabe")
    assert ereignis["daten"]["vorschau"] == "Löscht den Termin"
    assert "streng-geheim-42" not in str(ereignis)


def test_ausfall_und_wiederkehr_je_einmal_als_webhook(
    app: FastAPI, angemeldet: TestClient, ziel_server: tuple[LaufenderServer, FastAPI]
) -> None:
    server, empfang = ziel_server
    _ziel(angemeldet, name="Hook", art="webhook", adresse=server.url + "/hook", arten=["integration"])
    for _ in range(3):  # dieselbe Meldung mehrfach: nur einmal pro Minute
        app.state.ereignisse.melden(
            "integration_ausgefallen",
            "Integration „Lager“ ist ausgefallen",
            "nicht erreichbar",
            dringlichkeit="hoch",
            daten={"integration_id": 3},
        )
    app.state.ereignisse.melden(
        "integration_wieder_da", "Integration „Lager“ funktioniert wieder", "ok", daten={"integration_id": 3}
    )
    app.state.ereignisse.melden(
        "geraet", "Gerät „Flur“ ist offline", "weg", daten={"faehigkeit": "offline"}
    )  # nicht gewählt
    _warte(lambda: len(empfang.state.meldungen) >= 2)
    time.sleep(0.3)
    titel = [m["inhalt"]["titel"] for m in empfang.state.meldungen]
    assert titel == ["Integration „Lager“ ist ausgefallen", "Integration „Lager“ funktioniert wieder"]
    erste = empfang.state.meldungen[0]["inhalt"]
    assert (
        erste["quelle"] == "missa-control"
        and erste["art"] == "integration"
        and erste["dringlichkeit"] == "hoch"
    )
    assert erste["link"] == "http://ai01:8090/integrationen"


def test_mehr_als_fuenf_pro_minute_werden_zusammengefasst(
    app: FastAPI, angemeldet: TestClient, ziel_server: tuple[LaufenderServer, FastAPI]
) -> None:
    server, empfang = ziel_server
    _ziel(angemeldet, adresse=server.url, arten=["integration"])
    dienst = app.state.meldungen
    jetzt = [1000.0]
    dienst._uhr = lambda: jetzt[0]
    for nummer in range(8):
        dienst.verteilen(Meldung("integration", f"Integration {nummer} ist ausgefallen", "weg"))
    assert len(empfang.state.meldungen) == 5
    jetzt[0] += 61
    dienst._zusammenfassungen_senden()
    assert len(empfang.state.meldungen) == 6
    zusammen = empfang.state.meldungen[-1]["inhalt"]
    assert zusammen["title"] == "3 weitere Meldungen"
    assert "Integration 7 ist ausgefallen" in zusammen["message"]


def test_nicht_erreichbares_ziel_haelt_nichts_auf_und_meldet_den_grund(
    app: FastAPI, angemeldet: TestClient
) -> None:
    langsam = empfaenger(langsam=8.0)
    with LaufenderServer(langsam) as server:
        tot = _ziel(angemeldet, name="Tot", adresse=f"http://127.0.0.1:{freier_port()}", arten=["freigabe"])
        _ziel(angemeldet, name="Langsam", adresse=server.url, arten=["freigabe"])
        start = time.monotonic()
        for nummer in range(3):
            app.state.ereignisse.melden(
                "freigabe", "Freigabe", "", daten={"funktion": f"f{nummer}", "vorschau": ""}
            )
        assert time.monotonic() - start < 0.5
        # Das Panel antwortet währenddessen normal
        assert angemeldet.get("/api/freigaben/anzahl").status_code == 200
        ziel = _warte(
            lambda: next(
                (
                    z
                    for z in angemeldet.get("/api/meldungen").json()["ziele"]
                    if z["id"] == tot["id"] and z["letzter_fehler"]
                ),
                None,
            ),
        )
        assert "nicht erreichbar" in ziel["letzter_fehler"]
        protokoll = angemeldet.get("/api/protokoll").json()["eintraege"]
        assert any(e["funktion"] == "meldung_ntfy" and not e["ok"] for e in protokoll)


def test_test_meldung(angemeldet: TestClient, ziel_server: tuple[LaufenderServer, FastAPI]) -> None:
    server, empfang = ziel_server
    ziel = _ziel(angemeldet, adresse=server.url, arten=[])
    ok = angemeldet.post(f"/api/meldungen/{ziel['id']}/testen").json()
    assert ok["ok"] is True and ok["ziel"]["zuletzt_gesendet"]
    assert empfang.state.meldungen[0]["inhalt"]["title"] == "Test von Missa Control"

    zugang = angemeldet.post(
        "/api/zugaenge", json={"name": "Falsch", "typ": "bearer_token", "wert": "tk_falsch-000000"}
    ).json()["id"]
    angemeldet.put(f"/api/meldungen/{ziel['id']}", json={**ziel, "zugang_id": zugang})
    fehler = angemeldet.post(f"/api/meldungen/{ziel['id']}/testen").json()
    assert fehler["ok"] is False and "401" in fehler["meldung"]
    assert "tk_falsch-000000" not in str(fehler)
    assert fehler["ziel"]["letzter_fehler"]
