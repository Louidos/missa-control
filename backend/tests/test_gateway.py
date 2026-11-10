"""Das Gateway: ein MCP-Anschluss für alle Funktionen – mit Client-Token, Freigaben, Protokoll und Ereignissen.

Die Tests starten das Panel als echten Server und sprechen es mit einem echten MCP-Client an.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from hilfen import Uhr
from missa_control.config import Einstellungen
from missa_control.main import alte_daten_loeschen, create_app
from server import LaufenderServer, NurMitToken, freier_port, notizen_mcp_server

pytestmark = pytest.mark.anyio

# So meldet der MCP-Client eine abgelehnte Verbindung (je nach Stelle einzeln oder als Gruppe).
VERBINDUNGSFEHLER = (ExceptionGroup, httpx2.HTTPError, MCPError)

MANIFEST = """
id: werkstatt
name: Werkstatt
beschreibung: Test-Integration für das Gateway
art: python
standardrechte:
  lampe_schalten: nachfragen
  tresor_oeffnen: gesperrt
"""

MAIN = """
from missa_control.sdk import Fehler, Kontext, funktion


@funktion(beschreibung="Liest die Temperatur.", schreibend=False)
def temperatur(kontext: Kontext, raum: str = "Werkstatt") -> dict:
    return {"raum": raum, "grad": 21.5}


@funktion(beschreibung="Schaltet die Lampe.", schreibend=True)
def lampe_schalten(kontext: Kontext, an: bool) -> str:
    kontext.zustand["lampe"] = an
    kontext.zustand["schaltungen"] = kontext.zustand.get("schaltungen", 0) + 1
    return "Lampe ist an" if an else "Lampe ist aus"


@funktion(beschreibung="Öffnet den Tresor.", schreibend=True)
def tresor_oeffnen(kontext: Kontext) -> str:
    return "offen"


@funktion(beschreibung="Geht immer schief.", schreibend=False)
def kaputt(kontext: Kontext) -> str:
    raise Fehler("Die Werkstatt ist geschlossen.", "Morgen wieder versuchen.")
"""


# Eine zweite Integration, deren Funktion in der Freigabe sagt, was genau passieren würde.
HEIZUNG_MANIFEST = """
id: heizung
name: Heizung
beschreibung: Test-Integration mit Vorschau für die Freigabe
art: python
"""

HEIZUNG_MAIN = """
from missa_control.sdk import Fehler, Kontext, funktion


def _vorschau(kontext: Kontext, grad: int) -> str:
    if grad > 30:
        raise Fehler("Mehr als 30 Grad sind nicht möglich.", "Einen Wert bis 30 angeben.")
    if grad < 0:
        raise RuntimeError("Vorschau kaputt")
    return f"Stellt die Heizung im {kontext.name}-Raum auf {grad} Grad"


@funktion(beschreibung="Stellt die Heizung ein.", vorschau=_vorschau)
def stellen(kontext: Kontext, grad: int) -> str:
    return f"Heizung steht auf {grad} Grad"
"""


@pytest.fixture
def einstellungen(einstellungen: Einstellungen) -> Einstellungen:
    for name, manifest, main in (("werkstatt", MANIFEST, MAIN), ("heizung", HEIZUNG_MANIFEST, HEIZUNG_MAIN)):
        ordner = einstellungen.eigene_integrationen_ordner / name
        ordner.mkdir(parents=True)
        (ordner / "integration.yaml").write_text(manifest, encoding="utf-8")
        (ordner / "main.py").write_text(main, encoding="utf-8")
    return dataclasses.replace(einstellungen, stream_ping_sekunden=0.2)


def _integration(
    admin: TestClient, manifest_id: str = "werkstatt", konfig: dict | None = None, name: str = ""
) -> dict:
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


def _client_anlegen(admin: TestClient, name: str = "missa-core") -> tuple[int, str]:
    antwort = admin.post("/api/clients", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"], antwort.json()["token"]


@asynccontextmanager
async def mcp(panel: LaufenderServer, token: str) -> AsyncIterator[Client]:
    kopf = {"Authorization": f"Bearer {token}"}
    async with (
        httpx2.AsyncClient(headers=kopf, timeout=httpx2.Timeout(20.0)) as http,
        Client(streamable_http_client(panel.url + "/mcp", http_client=http)) as client,
    ):
        yield client


def _text(ergebnis: Any) -> str:
    return "\n".join(block.text for block in ergebnis.content if hasattr(block, "text"))


async def _warte_auf(bedingung, sekunden: float = 5.0) -> Any:
    for _ in range(int(sekunden / 0.02)):
        wert = bedingung()
        if wert:
            return wert
        await asyncio.sleep(0.02)
    raise AssertionError("Bedingung wurde nicht rechtzeitig erfüllt")


# ====================================================================== Zugriff nur mit Client-Token


async def test_ohne_gueltigen_token_wird_abgelehnt(angemeldet: TestClient, panel: LaufenderServer) -> None:
    _integration(angemeldet)
    anfrage = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    kopf = {"Accept": "application/json, text/event-stream"}
    async with httpx2.AsyncClient(base_url=panel.url) as http:
        ohne = await http.post("/mcp", json=anfrage, headers=kopf)
        assert ohne.status_code == 401
        assert ohne.headers["www-authenticate"] == "Bearer"
        assert "Clients" in ohne.json()["hinweis"]

        falsch = await http.post(
            "/mcp", json=anfrage, headers={**kopf, "Authorization": "Bearer mc_erfunden"}
        )
        assert falsch.status_code == 401

        # Auch die Sitzung des Admins öffnet die Anschlüsse für Clients nicht.
        sitzung = {"Cookie": f"missa_control_sitzung={angemeldet.cookies.get('missa_control_sitzung')}"}
        for pfad in (
            "/mcp",
            "/api/events",
            "/api/events/stream",
            "/api/config/integrations",
            "/api/config/profile",
        ):
            assert (await http.get(pfad, headers=sitzung)).status_code == 401, pfad

    with pytest.raises(VERBINDUNGSFEHLER):
        async with mcp(panel, "mc_gibt-es-nicht"):
            pass


async def test_client_token_oeffnet_das_panel_nicht(angemeldet: TestClient, panel: LaufenderServer) -> None:
    _, token = _client_anlegen(angemeldet)
    async with httpx2.AsyncClient(base_url=panel.url, headers={"Authorization": f"Bearer {token}"}) as http:
        for pfad in (
            "/api/zugaenge",
            "/api/integrationen",
            "/api/clients",
            "/api/freigaben",
            "/api/protokoll",
        ):
            assert (await http.get(pfad)).status_code == 401, pfad


# ====================================================================== Funktionen sehen und aufrufen


async def test_client_sieht_genau_die_aktiven_nicht_gesperrten_funktionen(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    werkstatt = _integration(angemeldet)
    zweite = _integration(angemeldet, name="Lager")
    angemeldet.put(f"/api/integrationen/{zweite['id']}", json={"aktiv": False})
    _, token = _client_anlegen(angemeldet)

    async with mcp(panel, token) as client:
        werkzeuge = {werkzeug.name: werkzeug for werkzeug in (await client.list_tools()).tools}
        # tresor_oeffnen ist gesperrt, „Lager“ ist deaktiviert – beides bleibt unsichtbar.
        assert set(werkzeuge) == {"werkstatt_temperatur", "werkstatt_lampe_schalten", "werkstatt_kaputt"}
        assert werkzeuge["werkstatt_temperatur"].description == "Liest die Temperatur."
        assert werkzeuge["werkstatt_temperatur"].annotations.read_only_hint is True
        assert (
            "nachdem der Besitzer im Panel zugestimmt hat"
            in werkzeuge["werkstatt_lampe_schalten"].description
        )
        assert werkzeuge["werkstatt_lampe_schalten"].annotations.read_only_hint is False
        assert werkzeuge["werkstatt_temperatur"].input_schema["properties"]["raum"]["type"] == "string"

        ergebnis = await client.call_tool("werkstatt_temperatur", {"raum": "Keller"})
        assert ergebnis.is_error is False
        assert json.loads(_text(ergebnis)) == {"raum": "Keller", "grad": 21.5}
        assert ergebnis.structured_content == {"raum": "Keller", "grad": 21.5}

        # Gesperrtes, Deaktiviertes und Unbekanntes lässt sich auch nicht „auf gut Glück“ aufrufen.
        for name in ("werkstatt_tresor_oeffnen", "lager_temperatur", "gibt_es_nicht"):
            abgelehnt = await client.call_tool(name, {})
            assert abgelehnt.is_error is True
            assert "nicht freigegeben" in _text(abgelehnt)

        # Rechte wirken sofort – ohne dass der Client etwas neu einrichten muss.
        angemeldet.put(f"/api/integrationen/{werkstatt['id']}", json={"rechte": {"temperatur": "gesperrt"}})
        angemeldet.put(f"/api/integrationen/{zweite['id']}", json={"aktiv": True})
        namen = {werkzeug.name for werkzeug in (await client.list_tools(cache_mode="refresh")).tools}
        assert namen == {
            "werkstatt_lampe_schalten",
            "werkstatt_kaputt",
            "lager_temperatur",
            "lager_lampe_schalten",
            "lager_kaputt",
        }

        fehler = await client.call_tool("werkstatt_kaputt", {})
        assert fehler.is_error is True
        assert _text(fehler) == "Die Werkstatt ist geschlossen. Hinweis: Morgen wieder versuchen."


async def test_zugaenge_setzt_das_panel_ein_der_client_sieht_sie_nie(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    geheim = "ein-sehr-geheimes-upstream-token"
    with LaufenderServer(NurMitToken(notizen_mcp_server().streamable_http_app(), geheim)) as notizen:
        zugang = angemeldet.post(
            "/api/zugaenge", json={"name": "Notizen", "typ": "bearer_token", "wert": geheim}
        ).json()
        _integration(
            angemeldet, "mcp-server", {"url": notizen.url + "/mcp", "zugang": zugang["id"]}, name="Notizen"
        )
        _, token = _client_anlegen(angemeldet)

        async with mcp(panel, token) as client:
            werkzeuge = (await client.list_tools()).tools
            assert {w.name for w in werkzeuge} >= {"notizen_auflisten", "notizen_search_notizen"}
            assert geheim not in json.dumps([w.model_dump(mode="json") for w in werkzeuge])
            ergebnis = await client.call_tool("notizen_search_notizen", {"begriff": "milch"})
            assert _text(ergebnis) == "Milch kaufen"  # Antwort des MCP-Servers wird durchgereicht
            assert geheim not in ergebnis.model_dump_json()

        async with httpx2.AsyncClient(
            base_url=panel.url, headers={"Authorization": f"Bearer {token}"}
        ) as http:
            assert geheim not in (await http.get("/api/config/integrations")).text


# ====================================================================== Freigaben


async def test_nachfragen_funktion_laeuft_erst_nach_dem_erlauben(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer
) -> None:
    werkstatt = _integration(angemeldet)
    _, token = _client_anlegen(angemeldet)

    def schaltungen() -> int:
        return angemeldet.get(f"/api/integrationen/{werkstatt['id']}").status_code and (
            app.state.integrationen.holen(app.state.datenbank.sitzung(), werkstatt["id"]).zustand.get(
                "schaltungen", 0
            )
        )

    async with mcp(panel, token) as client:
        aufruf = asyncio.create_task(client.call_tool("werkstatt_lampe_schalten", {"an": True}))

        offen = await _warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert len(offen) == 1
        assert offen[0]["client"] == "missa-core"
        assert offen[0]["funktion"] == "werkstatt_lampe_schalten"
        assert offen[0]["beschreibung"] == "Schaltet die Lampe."
        assert offen[0]["argumente"] == {"an": True}  # Funktion und Parameter sind sichtbar
        assert angemeldet.get("/api/freigaben/anzahl").json() == {"offen": 1}  # Zähler in der Navigation

        await asyncio.sleep(0.3)
        assert not aufruf.done()  # der Aufruf wartet …
        assert schaltungen() == 0  # … und hat noch nichts ausgeführt

        entschieden = angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        assert entschieden.status_code == 200
        ergebnis = await asyncio.wait_for(aufruf, timeout=5)
        assert ergebnis.is_error is False
        assert _text(ergebnis) == "Lampe ist an"
        assert schaltungen() == 1

    assert angemeldet.get("/api/freigaben/anzahl").json() == {"offen": 0}
    verlauf = angemeldet.get("/api/freigaben").json()["verlauf"]
    assert [(f["funktion"], f["status"]) for f in verlauf] == [("werkstatt_lampe_schalten", "erlaubt")]
    eintrag = angemeldet.get("/api/protokoll").json()["eintraege"][0]
    assert (eintrag["funktion"], eintrag["ok"], eintrag["freigabe"]) == (
        "werkstatt_lampe_schalten",
        True,
        "erlaubt",
    )
    # Zweimal entscheiden geht nicht:
    assert angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": False}).status_code == 409


async def test_freigabe_zeigt_die_vorschau_der_funktion(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    """Mit `@funktion(vorschau=...)` steht in der Freigabe ein Satz, was genau passieren würde."""
    _integration(angemeldet, "heizung")
    _integration(angemeldet)
    _, token = _client_anlegen(angemeldet)

    async def anfragen(client: Client, name: str, argumente: dict) -> tuple[asyncio.Task, dict]:
        aufruf = asyncio.create_task(client.call_tool(name, argumente))
        offen = await _warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        return aufruf, offen[0]

    async with mcp(panel, token) as client:
        aufruf, offen = await anfragen(client, "heizung_stellen", {"grad": 21})
        assert offen["vorschau"] == "Stellt die Heizung im Heizung-Raum auf 21 Grad"
        assert offen["argumente"] == {"grad": 21}
        angemeldet.post(f"/api/freigaben/{offen['id']}", json={"erlauben": True})
        assert _text(await asyncio.wait_for(aufruf, timeout=5)) == "Heizung steht auf 21 Grad"

        # Sagt die Vorschau schon, dass es nicht geht, wird niemand gefragt.
        zu_warm = await asyncio.wait_for(client.call_tool("heizung_stellen", {"grad": 35}), timeout=5)
        assert zu_warm.is_error is True
        assert _text(zu_warm) == "Mehr als 30 Grad sind nicht möglich. Hinweis: Einen Wert bis 30 angeben."
        falsch = await asyncio.wait_for(client.call_tool("heizung_stellen", {"grad": "warm"}), timeout=5)
        assert falsch.is_error is True
        assert "Ungültige Parameter" in _text(falsch)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []
        eintrag = angemeldet.get("/api/protokoll").json()["eintraege"][0]
        assert (eintrag["funktion"], eintrag["ok"], eintrag["freigabe"]) == ("heizung_stellen", False, "ohne")

        # Eine kaputte Vorschau hält nichts auf: es wird ohne sie nachgefragt.
        aufruf, offen = await anfragen(client, "heizung_stellen", {"grad": -5})
        assert offen["vorschau"] == ""
        angemeldet.post(f"/api/freigaben/{offen['id']}", json={"erlauben": True})
        assert _text(await asyncio.wait_for(aufruf, timeout=5)) == "Heizung steht auf -5 Grad"

        # Funktionen ohne Vorschau: wie bisher nur Funktion und Parameter.
        aufruf, offen = await anfragen(client, "werkstatt_lampe_schalten", {"an": False})
        assert offen["vorschau"] == ""
        angemeldet.post(f"/api/freigaben/{offen['id']}", json={"erlauben": False})
        assert (await asyncio.wait_for(aufruf, timeout=5)).is_error is True


async def test_ablehnen_fuehrt_nichts_aus_und_antwortet_verstaendlich(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer
) -> None:
    werkstatt = _integration(angemeldet)
    _, token = _client_anlegen(angemeldet)
    async with mcp(panel, token) as client:
        aufruf = asyncio.create_task(client.call_tool("werkstatt_lampe_schalten", {"an": True}))
        offen = await _warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": False})
        ergebnis = await asyncio.wait_for(aufruf, timeout=5)
    assert ergebnis.is_error is True
    assert _text(ergebnis) == (
        "Die Aktion „werkstatt_lampe_schalten“ wurde vom Besitzer im Panel abgelehnt und nicht ausgeführt."
    )
    with app.state.datenbank.sitzung() as db:
        assert "schaltungen" not in app.state.integrationen.holen(db, werkstatt["id"]).zustand
    eintrag = angemeldet.get("/api/protokoll").json()["eintraege"][0]
    assert (eintrag["ok"], eintrag["freigabe"]) == (False, "abgelehnt")


async def test_ohne_antwort_wird_nach_ablauf_der_frist_abgelehnt(
    einstellungen: Einstellungen, uhr: Uhr
) -> None:
    from hilfen import einrichten

    app = create_app(dataclasses.replace(einstellungen, freigabe_sekunden=0.4))
    with TestClient(app) as admin, LaufenderServer(app) as panel:
        einrichten(admin, uhr)
        werkstatt = _integration(admin)
        _, token = _client_anlegen(admin)
        async with mcp(panel, token) as client:
            ergebnis = await asyncio.wait_for(
                client.call_tool("werkstatt_lampe_schalten", {"an": True}), timeout=5
            )
        assert ergebnis.is_error is True
        assert "wurde nicht ausgeführt: Innerhalb von 1 Minute(n) hat niemand im Panel zugestimmt" in _text(
            ergebnis
        )
        assert "erneut versuchen" in _text(ergebnis)

        freigaben = admin.get("/api/freigaben").json()
        assert freigaben["offen"] == []
        assert freigaben["verlauf"][0]["status"] == "abgelaufen"
        zu_spaet = admin.post(f"/api/freigaben/{freigaben['verlauf'][0]['id']}", json={"erlauben": True})
        assert zu_spaet.status_code == 409
        assert "wartet nicht mehr" in zu_spaet.json()["meldung"]
        with app.state.datenbank.sitzung() as db:
            assert "schaltungen" not in app.state.integrationen.holen(db, werkstatt["id"]).zustand
    app.state.datenbank.schliessen()


def test_standard_frist_ist_fuenf_minuten(einstellungen: Einstellungen) -> None:
    assert (
        Einstellungen(
            secret_key=einstellungen.secret_key,
            encryption_key=einstellungen.encryption_key,
            daten_ordner=einstellungen.daten_ordner,
        ).freigabe_sekunden
        == 300
    )


def test_offene_freigaben_ueberleben_keinen_neustart(
    einstellungen: Einstellungen, app: FastAPI, uhr: Uhr
) -> None:
    from missa_control.gateway.modelle import Freigabe

    with app.state.datenbank.sitzung() as db:
        db.add(
            Freigabe(
                erstellt=uhr.jetzt,
                laeuft_ab=uhr.jetzt,
                client_name="missa-core",
                integration_name="Werkstatt",
                funktion="werkstatt_lampe_schalten",
                argumente={},
                status="offen",
            )
        )
        db.commit()
    neu = create_app(einstellungen)  # Neustart: niemand wartet mehr auf die alte Anfrage
    with neu.state.datenbank.sitzung() as db:
        assert neu.state.freigaben.offene(db) == []
        assert neu.state.freigaben.verlauf(db)[0]["status"] == "abgelaufen"
    neu.state.datenbank.schliessen()


# ====================================================================== Clients und Widerruf


async def test_clients_token_nur_einmal_sichtbar_und_widerruf_wirkt_sofort(
    einstellungen: Einstellungen, angemeldet: TestClient, panel: LaufenderServer
) -> None:
    _integration(angemeldet)
    client_id, token = _client_anlegen(angemeldet, "Overlay-App")
    assert token.startswith("mc_")
    liste = angemeldet.get("/api/clients")
    assert token not in liste.text  # danach nie wieder lesbar
    assert liste.json()[0]["token_anfang"] == token[:7] + "…"
    assert liste.json()[0]["aktiv"] is True
    inhalt = b"".join(datei.read_bytes() for datei in einstellungen.daten_ordner.glob("missa-control.db*"))
    assert token.encode() not in inhalt  # in der Datenbank steht nur die Prüfsumme
    assert angemeldet.post("/api/clients", json={"name": "Overlay-App"}).status_code == 409

    kopf = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(base_url=panel.url, headers=kopf, timeout=10) as http:
        assert (await http.get("/api/config/integrations")).status_code == 200
        assert angemeldet.get("/api/clients").json()[0]["zuletzt_gesehen"] is not None

        async with http.stream("GET", "/api/events/stream") as strom:
            assert strom.status_code == 200
            widerrufen = angemeldet.post(f"/api/clients/{client_id}/widerrufen")
            assert widerrufen.json()["aktiv"] is False

            # Sofort: neue Anfragen werden abgelehnt …
            assert (await http.get("/api/config/integrations")).status_code == 401
            assert (await http.get("/api/events")).status_code == 401

            # … und auch der bereits offene Stream endet von selbst.
            async def bis_zum_ende() -> None:
                async for _ in strom.aiter_lines():
                    pass

            await asyncio.wait_for(bis_zum_ende(), timeout=3)

    with pytest.raises(VERBINDUNGSFEHLER):
        async with mcp(panel, token):
            pass

    assert angemeldet.delete(f"/api/clients/{client_id}").json() == {"ok": True}
    assert angemeldet.get("/api/clients").json() == []


# ====================================================================== Ereignisse


async def _naechstes_ereignis(zeilen: AsyncIterator[str]) -> dict[str, Any]:
    kopf: dict[str, str] = {}
    async for zeile in zeilen:
        if zeile.startswith(":"):
            continue  # Lebenszeichen
        if not zeile.strip():
            if "data" in kopf:
                return {"id": int(kopf["id"]), "event": kopf["event"], "data": json.loads(kopf["data"])}
            continue
        name, _, wert = zeile.partition(": ")
        kopf[name] = wert
    raise AssertionError("Stream endete ohne Ereignis")


async def test_test_ereignis_kommt_ueber_den_stream_beim_client_an(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    _, token = _client_anlegen(angemeldet)
    kopf = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(base_url=panel.url, headers=kopf, timeout=10) as http:
        async with http.stream("GET", "/api/events/stream") as strom:
            assert strom.headers["content-type"].startswith("text/event-stream")
            zeilen = strom.aiter_lines()
            gesendet = angemeldet.post(
                "/api/ereignisse/test", json={"nachricht": "Hallo Missa", "dringlichkeit": "hoch"}
            )
            assert gesendet.status_code == 200
            ereignis = await asyncio.wait_for(_naechstes_ereignis(zeilen), timeout=5)
        assert ereignis["event"] == "ereignis"
        assert ereignis["data"]["art"] == "test"
        assert ereignis["data"]["nachricht"] == "Hallo Missa"
        assert ereignis["data"]["dringlichkeit"] == "hoch"
        assert ereignis["id"] == ereignis["data"]["id"] == gesendet.json()["id"]

        # Abholen ohne Stream: seit einem Zeitpunkt oder nach einer Nummer.
        angemeldet.post("/api/ereignisse/test", json={"nachricht": "Zweites"})
        alle = (await http.get("/api/events", params={"seit": "2026-01-01T00:00:00Z"})).json()
        assert [e["nachricht"] for e in alle["ereignisse"]] == ["Hallo Missa", "Zweites"]
        neuere = (await http.get("/api/events", params={"nach_id": ereignis["id"]})).json()
        assert [e["nachricht"] for e in neuere["ereignisse"]] == ["Zweites"]
        assert neuere["letzte_id"] == neuere["ereignisse"][0]["id"]
        assert (await http.get("/api/events", params={"seit": "2099-01-01T00:00:00Z"})).json()[
            "ereignisse"
        ] == []
        assert (await http.get("/api/events", params={"seit": "gestern"})).status_code == 422

        # Nach einer Unterbrechung setzt Last-Event-ID genau dort fort.
        async with http.stream(
            "GET", "/api/events/stream", headers={"Last-Event-ID": str(ereignis["id"])}
        ) as strom:
            verpasst = await asyncio.wait_for(_naechstes_ereignis(strom.aiter_lines()), timeout=5)
        assert verpasst["data"]["nachricht"] == "Zweites"

    # Das Panel zeigt dieselben Ereignisse (neueste zuerst).
    assert [e["nachricht"] for e in angemeldet.get("/api/ereignisse").json()] == ["Zweites", "Hallo Missa"]


async def test_ausfall_und_rueckkehr_einer_integration_werden_gemeldet(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    port = freier_port()
    with LaufenderServer(notizen_mcp_server().streamable_http_app()) as notizen:
        integration = _integration(angemeldet, "mcp-server", {"url": notizen.url + "/mcp"}, name="Notizen")
    _, token = _client_anlegen(angemeldet)

    async with mcp(panel, token) as client:
        ausfall = await client.call_tool("notizen_auflisten", {})  # der MCP-Server läuft nicht mehr
        assert ausfall.is_error is True
        assert "nicht erreichbar" in _text(ausfall)
    ereignisse = angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json()
    assert len(ereignisse) == 1
    assert ereignisse[0]["titel"] == "Integration „Notizen“ ist ausgefallen"
    assert ereignisse[0]["dringlichkeit"] == "hoch"
    assert ereignisse[0]["daten"]["integration_id"] == integration["id"]
    assert angemeldet.get(f"/api/integrationen/{integration['id']}").json()["status"] == "fehler"

    # Ein zweiter Fehlschlag meldet nicht noch einmal; die Rückkehr schon.
    async with mcp(panel, token) as client:
        await client.call_tool("notizen_auflisten", {})
    assert len(angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json()) == 1
    del port
    with LaufenderServer(notizen_mcp_server().streamable_http_app()) as neu:
        angemeldet.put(f"/api/integrationen/{integration['id']}", json={"konfig": {"url": neu.url + "/mcp"}})
    zurueck = angemeldet.get("/api/ereignisse", params={"art": "integration_wieder_da"}).json()
    assert [e["titel"] for e in zurueck] == ["Integration „Notizen“ funktioniert wieder"]


# ====================================================================== Konfig-API und Protokoll


async def test_konfig_api_fuer_clients(angemeldet: TestClient, panel: LaufenderServer) -> None:
    _integration(angemeldet)
    _, token = _client_anlegen(angemeldet)
    async with httpx2.AsyncClient(base_url=panel.url, headers={"Authorization": f"Bearer {token}"}) as http:
        integrationen = (await http.get("/api/config/integrations")).json()["integrationen"]
        assert [(i["name"], i["kennung"], i["status"]) for i in integrationen] == [
            ("Werkstatt", "werkstatt", "ok")
        ]
        assert {(f["name"], f["recht"]) for f in integrationen[0]["funktionen"]} == {
            ("werkstatt_temperatur", "erlaubt"),
            ("werkstatt_kaputt", "erlaubt"),
            ("werkstatt_lampe_schalten", "nachfragen"),
        }
        profil = (await http.get("/api/config/profile")).json()
        assert profil["vorhanden"] is False
        # Die Konfig-API ist nur lesend.
        assert (await http.post("/api/config/integrations", json={})).status_code == 405


async def test_protokoll_filter_und_loeschen_nach_30_tagen(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer, uhr: Uhr
) -> None:
    werkstatt = _integration(angemeldet)
    _, token = _client_anlegen(angemeldet)
    _, token_app = _client_anlegen(angemeldet, "Overlay-App")
    async with mcp(panel, token) as client:
        await client.call_tool("werkstatt_temperatur", {"raum": "ein-auffaelliger-parameterwert"})
        await client.call_tool("werkstatt_kaputt", {})
    async with mcp(panel, token_app) as client:
        await client.call_tool("werkstatt_temperatur", {})
    angemeldet.post(
        f"/api/integrationen/{werkstatt['id']}/aufrufen", json={"funktion": "temperatur", "argumente": {}}
    )

    alles = angemeldet.get("/api/protokoll").json()
    assert alles["anzahl"] == 4
    assert alles["clients"] == ["Overlay-App", "Panel (Ausprobieren)", "missa-core"]
    assert alles["integrationen"] == ["Werkstatt"]
    neuester = alles["eintraege"][0]
    assert (neuester["quelle"], neuester["client"], neuester["funktion"]) == (
        "panel",
        "Panel (Ausprobieren)",
        "werkstatt_temperatur",
    )
    assert set(neuester) == {
        "id",
        "zeit",
        "quelle",
        "client",
        "integration",
        "funktion",
        "ok",
        "fehler",
        "dauer_ms",
        "freigabe",
    }
    assert "ein-auffaelliger-parameterwert" not in json.dumps(alles)  # Parameter werden nicht protokolliert

    def anzahl(**filter_: str) -> int:
        return angemeldet.get("/api/protokoll", params=filter_).json()["anzahl"]

    assert anzahl(client="missa-core") == 2
    assert anzahl(client="Overlay-App") == 1
    assert anzahl(ergebnis="fehler") == 1
    assert anzahl(ergebnis="ok") == 3
    assert anzahl(suche="kaputt") == 1
    assert anzahl(suche="geschlossen") == 1  # Suche findet auch den Fehlertext
    assert anzahl(integration="Werkstatt") == 4
    assert anzahl(von="2099-01-01T00:00:00Z") == 0
    fehler = angemeldet.get("/api/protokoll", params={"ergebnis": "fehler"}).json()["eintraege"][0]
    assert fehler["fehler"] == "Die Werkstatt ist geschlossen. Hinweis: Morgen wieder versuchen."
    assert (
        angemeldet.get("/api/protokoll", params={"limit": 1, "versatz": 3}).json()["eintraege"][0]["client"]
        == "missa-core"
    )

    # Nach 30 Tagen wird gelöscht – Protokoll, Ereignisse und entschiedene Freigaben.
    angemeldet.post("/api/ereignisse/test", json={})

    def gespeichert() -> tuple[int, int]:
        with app.state.datenbank.sitzung() as db:
            return app.state.protokoll.suchen(db)["anzahl"], len(app.state.ereignisse.seit(db))

    uhr.vor(days=29)
    alte_daten_loeschen(app)
    assert gespeichert() == (4, 1)
    uhr.vor(days=2)
    alte_daten_loeschen(app)
    assert gespeichert() == (0, 0)


def test_geheimnisse_landen_nicht_im_protokoll(app: FastAPI, angemeldet: TestClient) -> None:
    geheim = "noch-ein-geheimer-wert-123456"
    angemeldet.post("/api/zugaenge", json={"name": "X", "typ": "api_key", "wert": geheim})
    app.state.protokoll.eintragen(
        quelle="gateway", funktion="f", ok=False, dauer_ms=1, fehler=f"Abgelehnt für Key {geheim}"
    )
    app.state.ereignisse.melden("test", f"Titel mit {geheim}", f"Nachricht mit {geheim}")
    assert geheim not in angemeldet.get("/api/protokoll").text
    assert geheim not in angemeldet.get("/api/ereignisse").text
    assert "•••" in angemeldet.get("/api/protokoll").json()["eintraege"][0]["fehler"]


def test_integrationsordner_im_test_ist_vollstaendig(einstellungen: Einstellungen) -> None:
    assert (Path(einstellungen.eigene_integrationen_ordner) / "werkstatt" / "main.py").is_file()
