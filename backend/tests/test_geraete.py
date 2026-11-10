"""Geräte (ESP32, Raspberry Pi Pico) per MQTT: koppeln, Fähigkeiten, Werte, Knöpfe, online/offline.

Als Broker läuft der echte Mosquitto aus `compose.yaml` mit der Konfiguration aus dem Repo (als
Test-Container). Die Geräte sind simuliert: Sie sprechen dasselbe wie die Beispiel-Firmware.
Ohne Docker werden diese Tests übersprungen.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr, client_token, einrichten, mcp_client, mcp_text, warte_auf
from missa_control.config import Einstellungen
from missa_control.geraete.dienst import befehl_aus, faehigkeiten_lesen, funktionen_aus
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.main import alte_daten_loeschen, create_app
from pico import Feierabend, PicoPruefstand
from server import LaufenderServer, MqttBroker, SimuliertesGeraet, docker_vorhanden, freier_port

FAEHIGKEITEN = [
    {"id": "temperatur", "art": "sensor", "name": "Temperatur", "einheit": "°C"},
    {"id": "knopf", "art": "knopf", "name": "Knopf"},
    {"id": "led", "art": "aktor", "name": "LED", "typ": "schalter"},
]


@pytest.fixture(scope="session")
def broker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MqttBroker]:
    if not docker_vorhanden():
        if os.environ.get("GERAETE_TESTS_PFLICHT"):  # in der CI darf hier nichts übersprungen werden
            pytest.fail("Docker ist nicht verfügbar, die Geräte-Tests sind hier aber Pflicht")
        pytest.skip("Docker ist nicht verfügbar – die Geräte-Tests brauchen den echten MQTT-Broker")
    with MqttBroker(tmp_path_factory.mktemp("mqtt")) as laufend:
        yield laufend


@pytest.fixture
def einstellungen(einstellungen: Einstellungen, broker: MqttBroker) -> Einstellungen:
    return dataclasses.replace(
        einstellungen,
        mqtt_host="127.0.0.1",
        mqtt_port=broker.port,
        mqtt_port_aussen=1883,
        mqtt_passwort_datei_pfad=broker.passwort_datei,
    )


def warte(bedingung: Callable[[], Any], sekunden: float = 8.0) -> Any:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        wert = bedingung()
        if wert:
            return wert
        time.sleep(0.05)
    raise AssertionError("Bedingung wurde nicht rechtzeitig erfüllt")


@pytest.fixture
def admin(app: FastAPI, angemeldet: TestClient) -> TestClient:
    """Angemeldeter Besitzer; das Panel ist mit dem MQTT-Broker verbunden."""
    warte(lambda: app.state.geraete.broker.bereit)
    return angemeldet


def _hinzufuegen(admin: TestClient, name: str = "Wohnzimmer") -> dict:
    """Die drei Schritte: Karte „Gerät“ → Name → testen und aktivieren. Gibt die Antwort mit den Kopplungsdaten zurück."""
    test = admin.post("/api/integrationen/testen", json={"manifest_id": "geraet", "konfig": {}}).json()
    assert test["ok"] is True, test
    antwort = admin.post(
        "/api/integrationen",
        json={"manifest_id": "geraet", "name": name, "konfig": {}, "test_id": test["test_id"]},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _geraet(admin: TestClient, geraet_id: int) -> dict:
    return next(g for g in admin.get("/api/geraete").json()["geraete"] if g["id"] == geraet_id)


def _verbunden(
    admin: TestClient, broker: MqttBroker, name: str = "Wohnzimmer", **mehr: Any
) -> tuple[dict, SimuliertesGeraet]:
    """Ein gekoppeltes Gerät, das sich verbunden und seine Fähigkeiten gemeldet hat."""
    integration = _hinzufuegen(admin, name)
    geraet = SimuliertesGeraet(broker.port, integration["kopplung"], **mehr)
    assert geraet.verbinden() is True
    geraet.melden(FAEHIGKEITEN)
    warte(lambda: len(_geraet(admin, integration["id"])["faehigkeiten"]) == 3)
    return integration, geraet


def _ereignisse(admin: TestClient, art: str = "geraet") -> list[dict]:
    return [e for e in reversed(admin.get("/api/ereignisse").json()) if e["art"] == art]


# ====================================================================== koppeln


def test_geraet_hinzufuegen_zeigt_die_kopplungsdaten_genau_einmal(app: FastAPI, admin: TestClient) -> None:
    karte = next(e for e in admin.get("/api/katalog").json()["eintraege"] if e["id"] == "geraet")
    assert (karte["art"], karte["verfuegbar"], karte["felder"]) == (
        "geraet",
        True,
        [],
    )  # nur der Name ist nötig

    integration = _hinzufuegen(admin)
    kopplung = integration["kopplung"]
    assert kopplung["benutzer"].startswith("geraet-")
    assert len(kopplung["passwort"]) >= 20
    assert kopplung["port"] == 1883
    basis = f"missa/geraete/{kopplung['benutzer']}"
    assert kopplung["themen"] == {
        "basis": basis,
        "status": f"{basis}/status",
        "faehigkeiten": f"{basis}/faehigkeiten",
        "wert": f"{basis}/wert/<fähigkeit>",
        "ereignis": f"{basis}/ereignis/<fähigkeit>",
        "zustand": f"{basis}/zustand/<fähigkeit>",
        "befehl": f"{basis}/befehl/<fähigkeit>",
    }

    # Das Passwort gibt es nur in dieser einen Antwort – danach nirgends mehr.
    spaeter = admin.get(f"/api/integrationen/{integration['id']}").json()
    assert "kopplung" not in spaeter
    assert kopplung["passwort"] not in admin.get("/api/geraete").text
    assert kopplung["passwort"].encode() not in app.state.einstellungen.datenbank_pfad.read_bytes()

    uebersicht = admin.get("/api/geraete").json()
    assert uebersicht["broker"] == {
        "eingerichtet": True,
        "verbunden": True,
        "meldung": "Verbunden.",
        "port": 1883,
    }
    geraet = uebersicht["geraete"][0]
    assert (geraet["name"], geraet["online"], geraet["status_seit"], geraet["faehigkeiten"]) == (
        "Wohnzimmer",
        False,
        None,  # hat sich noch nie gemeldet
        [],
    )
    assert geraet["mqtt_benutzer"] == kopplung["benutzer"]
    assert spaeter["status_meldung"].startswith("Der MQTT-Broker ist bereit")
    erneut = admin.post(f"/api/integrationen/{integration['id']}/testen").json()
    assert erneut["status_meldung"] == "Das Gerät hat sich noch nicht gemeldet."


def test_geraet_meldet_sich_und_seine_faehigkeiten_werden_zu_funktionen(
    admin: TestClient, broker: MqttBroker
) -> None:
    """Fertig-wenn: Mit der Konfiguration aus dem Panel erscheint das Gerät online."""
    integration = _hinzufuegen(admin)
    geraet = SimuliertesGeraet(broker.port, integration["kopplung"])
    assert geraet.verbinden() is True

    warte(lambda: _geraet(admin, integration["id"])["online"])
    geraet.melden(FAEHIGKEITEN, firmware="pico-beispiel 1.0")
    stand = warte(lambda: (g := _geraet(admin, integration["id"]))["faehigkeiten"] and g)
    assert stand["firmware"] == "pico-beispiel 1.0"
    assert [(f["id"], f["art"], f["funktion"], f["recht"]) for f in stand["faehigkeiten"]] == [
        ("temperatur", "sensor", "wohnzimmer_temperatur", "erlaubt"),  # lesen: sofort erlaubt
        ("knopf", "knopf", None, None),  # ein Knopf ist keine Funktion, sondern ein Ereignis
        ("led", "aktor", "wohnzimmer_led_schalten", "nachfragen"),  # schalten: erst nachfragen
    ]
    funktionen = {
        f["name"]: f for f in admin.get(f"/api/integrationen/{integration['id']}").json()["funktionen"]
    }
    assert funktionen["temperatur"]["beschreibung"] == (
        "Liest den aktuellen Wert von „Temperatur“ (in °C) am Gerät „Wohnzimmer“."
    )
    assert funktionen["led_schalten"]["parameter"]["required"] == ["an"]
    assert _ereignisse(admin)[0]["titel"] == "Gerät „Wohnzimmer“ ist online"

    # Ein Recht, das der Besitzer einstellt, übersteht ein erneutes Melden der Fähigkeiten.
    admin.put(f"/api/integrationen/{integration['id']}", json={"rechte": {"led_schalten": "erlaubt"}})
    geraet.melden(
        [*FAEHIGKEITEN, {"id": "feuchte", "art": "sensor", "name": "Luftfeuchtigkeit", "einheit": "%"}]
    )
    warte(lambda: len(_geraet(admin, integration["id"])["faehigkeiten"]) == 4)
    rechte = {
        f["name"]: f["recht"]
        for f in admin.get(f"/api/integrationen/{integration['id']}").json()["funktionen"]
    }
    assert rechte == {"temperatur": "erlaubt", "led_schalten": "erlaubt", "feuchte": "erlaubt"}
    geraet.trennen()


@pytest.mark.anyio
async def test_missa_liest_sensor_und_schaltet_aktor_ueber_das_gateway(
    admin: TestClient, broker: MqttBroker, panel: LaufenderServer
) -> None:
    integration, geraet = _verbunden(admin, broker)
    geraet.wert("temperatur", 21.5)
    warte(lambda: _geraet(admin, integration["id"])["faehigkeiten"][0]["wert"] == 21.5)
    admin.put(f"/api/integrationen/{integration['id']}", json={"rechte": {"led_schalten": "erlaubt"}})

    async with mcp_client(panel.url, client_token(admin)) as missa:
        assert {w.name for w in (await missa.list_tools()).tools} == {
            "wohnzimmer_temperatur",
            "wohnzimmer_led_schalten",
        }
        gelesen = json.loads(mcp_text(await missa.call_tool("wohnzimmer_temperatur", {})))
        assert (gelesen["wert"], gelesen["einheit"], gelesen["geraet_online"]) == (21.5, "°C", True)

        geschaltet = await missa.call_tool("wohnzimmer_led_schalten", {"an": True})
        assert mcp_text(geschaltet) == "„LED“ ist jetzt an."  # das Gerät hat den neuen Zustand bestätigt
        assert geraet.befehle == [("led", "an")]
        await missa.call_tool("wohnzimmer_led_schalten", {"an": False})
        assert geraet.befehle[-1] == ("led", "aus")
        assert _geraet(admin, integration["id"])["faehigkeiten"][2]["wert"] == 0

        # Ist das Gerät offline, sagt Missa das – statt einen Befehl ins Leere zu schicken.
        geraet.trennen()
        warte(lambda: not _geraet(admin, integration["id"])["online"])
        offline = await missa.call_tool("wohnzimmer_led_schalten", {"an": True})
        assert offline.is_error is True
        assert "Das Gerät „Wohnzimmer“ ist offline." in mcp_text(offline)
        letzter = json.loads(mcp_text(await missa.call_tool("wohnzimmer_temperatur", {})))
        assert (letzter["wert"], letzter["geraet_online"]) == (21.5, False)
        assert "letzte gemeldete Wert" in letzter["hinweis"]


@pytest.mark.anyio
async def test_schalten_fragt_erst_nach_und_die_freigabe_sagt_was_passiert(
    admin: TestClient, broker: MqttBroker, panel: LaufenderServer
) -> None:
    _, geraet = _verbunden(admin, broker)
    async with mcp_client(panel.url, client_token(admin)) as missa:
        aufruf = asyncio.create_task(missa.call_tool("wohnzimmer_led_schalten", {"an": True}))
        offen = await warte_auf(lambda: admin.get("/api/freigaben").json()["offen"])
        assert offen[0]["funktion"] == "wohnzimmer_led_schalten"
        assert offen[0]["vorschau"] == "„LED“ am Gerät „Wohnzimmer“ wird eingeschaltet."
        assert geraet.befehle == []  # noch ist nichts geschaltet
        admin.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        erlaubt = await asyncio.wait_for(aufruf, timeout=5)
        assert mcp_text(erlaubt) == "„LED“ ist jetzt an."
        assert geraet.befehle == [("led", "an")]

        # Fehlt die Angabe, wird niemand gefragt – die Antwort kommt sofort.
        ohne = await missa.call_tool("wohnzimmer_led_schalten", {})
        assert ohne.is_error is True
        assert "Für „LED“ fehlt die Angabe „an“." in mcp_text(ohne)
        assert admin.get("/api/freigaben").json()["offen"] == []
    geraet.trennen()


def test_befehle_werden_geprueft_bevor_sie_ans_geraet_gehen() -> None:
    helligkeit = {"id": "h", "name": "Helligkeit", "typ": "zahl", "min": 0, "max": 100, "einheit": "%"}
    led = {"id": "led", "name": "LED", "typ": "schalter"}
    anzeige = {"id": "a", "name": "Anzeige", "typ": "text"}
    assert befehl_aus(led, "schalten", {"an": True}) == "an"
    assert befehl_aus(led, "schalten", {"an": "aus"}) == "aus"  # nachsichtig mit Text statt true/false
    assert befehl_aus(helligkeit, "setzen", {"wert": 40}) == "40"
    assert befehl_aus(helligkeit, "setzen", {"wert": "12,5"}) == "12.5"
    assert befehl_aus({**helligkeit, "max": 5_000_000}, "setzen", {"wert": 1234567}) == "1234567"
    assert befehl_aus(anzeige, "senden", {"text": "Hallo"}) == "Hallo"
    for faehigkeit, aktion, argumente, meldung, hinweis in (
        (led, "schalten", {"an": 5}, "Für „LED“ fehlt die Angabe „an“.", "an = true (einschalten)"),
        (helligkeit, "setzen", {}, "Für „Helligkeit“ fehlt die Angabe „wert“.", "eine Zahl"),
        (helligkeit, "setzen", {"wert": True}, "fehlt die Angabe „wert“", "eine Zahl"),
        (
            helligkeit,
            "setzen",
            {"wert": 150},
            "150 passt nicht zu „Helligkeit“.",
            "Erlaubt ist mindestens 0 und höchstens 100.",
        ),
        (anzeige, "senden", {"text": "  "}, "Für „Anzeige“ fehlt die Angabe „text“.", ""),
    ):
        with pytest.raises(IntegrationsFehler) as fehler:
            befehl_aus(faehigkeit, aktion, argumente)
        assert meldung in fehler.value.meldung
        assert hinweis in (fehler.value.hinweis or "")


# ====================================================================== Knopf, Regeln, offline


def test_knopfdruck_erzeugt_ein_ereignis_und_loest_eine_regel_aus(
    app: FastAPI, admin: TestClient, broker: MqttBroker
) -> None:
    """Fertig-wenn: Knopfdruck erzeugt ein Ereignis und kann eine Regel auslösen."""
    integration, geraet = _verbunden(admin, broker)
    optionen = admin.get("/api/regeln").json()["optionen"]
    assert optionen["geraete"] == [
        {
            "id": integration["id"],
            "name": "Wohnzimmer",
            "meldungen": [
                {"wert": "knopf", "titel": "Knopf"},
                {"wert": "offline", "titel": "geht offline"},
                {"wert": "online", "titel": "kommt online"},
            ],
        }
    ]
    regel = admin.post(
        "/api/regeln",
        json={
            "name": "Klingel",
            "ausloeser": {"art": "geraet", "geraet_id": integration["id"], "faehigkeit": "knopf"},
            "aktion": {
                "art": "ereignis",
                "nachricht": "Jemand hat den Knopf im Wohnzimmer gedrückt",
                "dringlichkeit": "hoch",
            },
            "ruhezeit_minuten": 0,
        },
    )
    assert regel.status_code == 201, regel.text
    assert regel.json()["satz"].startswith("Wenn das Gerät „Wohnzimmer“ „Knopf“ meldet, dann bekommt Missa")

    geraet.knopf("knopf")
    ereignis = warte(lambda: [e for e in _ereignisse(admin) if e["daten"].get("faehigkeit") == "knopf"])[0]
    assert ereignis["titel"] == "Gerät „Wohnzimmer“: Knopf"
    assert ereignis["nachricht"] == "„Knopf“ wurde gedrückt."
    assert ereignis["daten"]["geraet_id"] == integration["id"]

    warte(lambda: _ereignisse(admin, "regel"))
    assert app.state.regeln.warten()
    assert [e["nachricht"] for e in _ereignisse(admin, "regel")] == [
        "Jemand hat den Knopf im Wohnzimmer gedrückt"
    ]
    assert admin.get("/api/regeln/verlauf").json()["eintraege"][0]["anlass"] == "Gerät „Wohnzimmer“: Knopf"
    geraet.trennen()


def test_offline_wird_ueber_den_letzten_willen_erkannt_und_kann_regeln_ausloesen(
    app: FastAPI, admin: TestClient, broker: MqttBroker
) -> None:
    """Fertig-wenn: Gerät offline wird (innerhalb von 60 s) angezeigt.

    Die Beispiel-Firmware meldet sich alle 30 Sekunden (keepalive); der Broker erklärt ein Gerät nach
    dem anderthalbfachen davon für weg – also nach 45 Sekunden. Im Test sind es 2 Sekunden.
    """
    integration, geraet = _verbunden(admin, broker, keepalive=2)
    admin.post(
        "/api/regeln",
        json={
            "name": "Gerät weg",
            "ausloeser": {"art": "geraet", "geraet_id": integration["id"], "faehigkeit": "offline"},
            "aktion": {"art": "ereignis", "nachricht": "Das Gerät im Wohnzimmer meldet sich nicht mehr"},
        },
    )
    assert _geraet(admin, integration["id"])["online"] is True

    geraet.trennen(hart=True)  # Strom weg: keine Abmeldung, das Gerät verstummt einfach
    start = time.monotonic()
    warte(lambda: not _geraet(admin, integration["id"])["online"], sekunden=15)
    assert 1.0 < time.monotonic() - start < 10  # erst nach dem Anderthalbfachen des Lebenszeichens (3 s)
    assert _ereignisse(admin)[-1]["titel"] == "Gerät „Wohnzimmer“ ist offline"
    warte(lambda: _ereignisse(admin, "regel"))
    assert _ereignisse(admin, "regel")[0]["nachricht"] == "Das Gerät im Wohnzimmer meldet sich nicht mehr"

    # Kommt es wieder, ist es sofort wieder online.
    zurueck = SimuliertesGeraet(broker.port, integration["kopplung"])
    assert zurueck.verbinden() is True
    warte(lambda: _geraet(admin, integration["id"])["online"])
    assert _ereignisse(admin)[-1]["titel"] == "Gerät „Wohnzimmer“ ist online"
    zurueck.trennen()


def test_sensor_als_messwert_fuer_schwellwert_regeln(
    app: FastAPI, admin: TestClient, broker: MqttBroker
) -> None:
    integration, geraet = _verbunden(admin, broker)
    kennung = f"geraet.{integration['id']}.temperatur"
    messwert = next(
        m for m in admin.get("/api/regeln").json()["optionen"]["messwerte"] if m["kennung"] == kennung
    )
    assert (messwert["titel"], messwert["einheit"]) == ("Wohnzimmer: Temperatur", "°C")
    regel = admin.post(
        "/api/regeln",
        json={
            "name": "Zu warm",
            "ausloeser": {"art": "messwert", "messwert": kennung, "schwelle": 28},
            "aktion": {"art": "ereignis", "nachricht": "Im Wohnzimmer sind es {wert} Grad"},
        },
    ).json()
    assert regel["satz"].startswith("Wenn „Wohnzimmer: Temperatur“ über 28 °C liegt, dann")

    geraet.wert("temperatur", 24.0)
    warte(lambda: _geraet(admin, integration["id"])["faehigkeiten"][0]["wert"] == 24.0)
    assert app.state.regeln.warten()
    assert _ereignisse(admin, "regel") == []
    geraet.wert("temperatur", "29,5")  # auch mit Komma
    warte(lambda: _ereignisse(admin, "regel"))
    assert _ereignisse(admin, "regel")[0]["nachricht"] == "Im Wohnzimmer sind es 29,5 Grad"
    geraet.trennen()


# ====================================================================== Sicherheit am Broker


def test_jedes_geraet_darf_nur_seine_eigenen_themen(admin: TestClient, broker: MqttBroker) -> None:
    wohnzimmer, geraet = _verbunden(admin, broker)
    kueche = _hinzufuegen(admin, "Küche")
    fremd = SimuliertesGeraet(broker.port, kueche["kopplung"])
    assert fremd.verbinden() is True

    # Die Küche versucht, sich als Wohnzimmer auszugeben und dessen Befehle mitzulesen.
    fremd.senden(f"{wohnzimmer['kopplung']['themen']['basis']}/wert/temperatur", "99")
    fremd.senden(f"{wohnzimmer['kopplung']['themen']['basis']}/ereignis/knopf", "gedrueckt")
    fremd.client.subscribe(f"{wohnzimmer['kopplung']['themen']['basis']}/befehl/#", qos=1)
    fremd.client.subscribe("missa/geraete/#", qos=1)
    geraet.wert("temperatur", 20.0)  # das echte Wohnzimmer meldet danach
    warte(lambda: _geraet(admin, wohnzimmer["id"])["faehigkeiten"][0]["wert"] == 20.0)
    assert not [e for e in _ereignisse(admin) if e["daten"].get("faehigkeit") == "knopf"]
    warte(lambda: len(fremd.abos) >= 3)
    assert fremd.abos[0] == "Granted QoS 1"  # die eigenen Befehle
    assert fremd.abos[1:] != ["Granted QoS 1", "Granted QoS 1"]  # die fremden nicht

    # Falsches Passwort: kein Zutritt.
    assert (
        SimuliertesGeraet(broker.port, kueche["kopplung"], passwort="falsches-passwort").verbinden() is False
    )
    # Ohne Anmeldung: kein Zutritt.
    import paho.mqtt.client as mqtt

    ohne = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    gruende: list[str] = []
    ohne.on_connect = lambda _c, _u, _f, grund, _e=None: gruende.append(str(grund))
    ohne.connect("127.0.0.1", broker.port)
    ohne.loop_start()
    warte(lambda: gruende)
    ohne.loop_stop()
    assert gruende[0] != "Success"

    # Neu koppeln: das alte Passwort gilt sofort nicht mehr, das neue schon.
    fremd.trennen()
    neu = admin.post(f"/api/geraete/{kueche['id']}/koppeln")
    assert neu.status_code == 200, neu.text
    assert neu.json()["benutzer"] == kueche["kopplung"]["benutzer"]
    assert neu.json()["passwort"] != kueche["kopplung"]["passwort"]
    assert SimuliertesGeraet(broker.port, kueche["kopplung"]).verbinden(sekunden=2) is False
    wieder = SimuliertesGeraet(broker.port, neu.json())
    assert wieder.verbinden() is True
    wieder.trennen()

    # Entfernt: der Zugang ist weg – am Broker und im Panel.
    assert admin.delete(f"/api/integrationen/{kueche['id']}").status_code == 200
    assert SimuliertesGeraet(broker.port, neu.json()).verbinden(sekunden=2) is False
    assert [g["name"] for g in admin.get("/api/geraete").json()["geraete"]] == ["Wohnzimmer"]
    assert admin.post(f"/api/geraete/{kueche['id']}/koppeln").status_code == 404
    geraet.trennen()


def test_koppeln_geht_nur_bei_geraeten(admin: TestClient) -> None:
    serverlast = admin.post("/api/integrationen", json={"manifest_id": "serverlast", "konfig": {}}).json()
    antwort = admin.post(f"/api/geraete/{serverlast['id']}/koppeln")
    assert (antwort.status_code, antwort.json()["meldung"]) == (409, "Diese Integration ist kein Gerät.")


# ====================================================================== Verlauf, Aufräumen, ungültige Meldungen


def test_verlauf_sieben_tage_und_hoechstens_ein_wert_pro_halbe_minute(
    app: FastAPI, admin: TestClient, broker: MqttBroker, uhr: Uhr, geheimnis: str
) -> None:
    from hilfen import anmelden

    integration, geraet = _verbunden(admin, broker)

    def messen(wert: float) -> None:
        geraet.wert("temperatur", wert)
        warte(lambda: _geraet(admin, integration["id"])["faehigkeiten"][0]["wert"] == wert)

    def verlauf(zeitraum: str = "1h") -> list[float]:
        antwort = admin.get(
            f"/api/geraete/{integration['id']}/verlauf",
            params={"faehigkeit": "temperatur", "zeitraum": zeitraum},
        )
        assert antwort.status_code == 200, antwort.text
        return [punkt["wert"] for punkt in antwort.json()["verlauf"]]

    messen(20.0)
    messen(20.5)  # gleich danach: letzter Wert ja, Verlauf nein
    uhr.vor(seconds=30)
    messen(21.0)
    uhr.vor(seconds=30)
    messen(22.0)
    assert verlauf() == [20.0, 21.0, 22.0]
    assert verlauf("24h") == [21.0]  # zu 5-Minuten-Mittelwerten zusammengefasst
    assert (
        admin.get(
            f"/api/geraete/{integration['id']}/verlauf",
            params={"faehigkeit": "temperatur", "zeitraum": "ewig"},
        ).status_code
        == 422
    )
    assert admin.get("/api/geraete/999/verlauf", params={"faehigkeit": "temperatur"}).status_code == 404

    uhr.vor(days=6)
    alte_daten_loeschen(app)
    anmelden(admin, uhr, geheimnis)
    assert verlauf("7t") == [21.0]
    uhr.vor(days=2)
    alte_daten_loeschen(app)
    anmelden(admin, uhr, geheimnis)
    assert verlauf("7t") == []
    geraet.trennen()


def test_ungueltige_faehigkeiten_werden_auf_der_seite_gemeldet(admin: TestClient, broker: MqttBroker) -> None:
    integration = _hinzufuegen(admin)
    geraet = SimuliertesGeraet(broker.port, integration["kopplung"])
    assert geraet.verbinden() is True
    geraet.senden(
        f"{geraet.basis}/faehigkeiten", '{"faehigkeiten": [{"id": "Temperatur Aussen", "art": "sensor"}]}'
    )
    problem = warte(lambda: _geraet(admin, integration["id"])["problem"])
    assert problem == (
        "Das Gerät meldet seine Fähigkeiten in einer ungültigen Form: "
        "Die Kennung „Temperatur Aussen“ ist ungültig (Kleinbuchstaben, Ziffern, _)."
    )
    geraet.melden(FAEHIGKEITEN)  # korrigiert
    warte(lambda: _geraet(admin, integration["id"])["problem"] is None)
    geraet.trennen()


def test_faehigkeiten_pruefen_und_funktionen_ableiten() -> None:
    firmware, faehigkeiten = faehigkeiten_lesen(
        json.dumps(
            {
                "firmware": "esp32 1.0",
                "faehigkeiten": [
                    {
                        "id": "helligkeit",
                        "art": "aktor",
                        "name": "Helligkeit",
                        "typ": "zahl",
                        "min": 0,
                        "max": 100,
                        "einheit": "%",
                    },
                    {"id": "anzeige", "art": "aktor", "typ": "text"},
                    {"id": "tuer", "art": "sensor", "name": "Tür", "typ": "schalter"},
                ],
            }
        ).encode()
    )
    assert firmware == "esp32 1.0"
    funktionen = {f.name: f for f in funktionen_aus(faehigkeiten, "Flur")}
    assert set(funktionen) == {"helligkeit_setzen", "anzeige_senden", "tuer"}
    assert funktionen["helligkeit_setzen"].parameter["properties"]["wert"] == {
        "type": "number",
        "description": "Neuer Wert (in %)",
        "minimum": 0,
        "maximum": 100,
    }
    assert (funktionen["tuer"].schreibend, funktionen["anzeige_senden"].schreibend) == (False, True)

    for kaputt, meldung in (
        (b"kein json", "kein gültiges JSON"),
        (b'{"x": 1}', "fehlt die Liste"),
        (b'{"faehigkeiten": [{"id": "a", "art": "motor"}]}', "Die Art „motor“ gibt es nicht"),
        (
            b'{"faehigkeiten": [{"id": "a", "art": "sensor"}, {"id": "a", "art": "knopf"}]}',
            "kommt doppelt vor",
        ),
        (b'{"faehigkeiten": [{"id": "a", "art": "aktor", "typ": "laser"}]}', "Den Typ „laser“ gibt es nicht"),
    ):
        with pytest.raises(ValueError, match=meldung):
            faehigkeiten_lesen(kaputt)


# ====================================================================== Beispiel-Firmware (Pico)


def test_pico_beispiel_firmware_am_pruefstand(app: FastAPI, admin: TestClient, broker: MqttBroker) -> None:
    """Fertig-wenn: Ein Gerät mit der Beispiel-Firmware und der Konfiguration aus dem Panel erscheint
    online; Knopfdruck erzeugt ein Ereignis und kann eine Regel auslösen; offline wird angezeigt.

    Auf einem echten Pico ist das hier nicht geprüft. Am Prüfstand (tests/pico.py) laufen aber die
    echte Firmware-Datei und die echte MQTT-Bibliothek von MicroPython gegen den echten Broker.
    """
    integration = _hinzufuegen(admin, "Pico")
    admin.post(
        "/api/regeln",
        json={
            "name": "Klingel",
            "ausloeser": {"art": "geraet", "geraet_id": integration["id"], "faehigkeit": "knopf"},
            "aktion": {"art": "ereignis", "nachricht": "Am Pico wurde der Knopf gedrückt"},
            "ruhezeit_minuten": 0,
        },
    )
    pico = PicoPruefstand(broker.port, integration["kopplung"], lebenszeichen=2)

    def stand() -> dict:
        return _geraet(admin, integration["id"])

    def knopf_ereignisse() -> list[dict]:
        return [e for e in _ereignisse(admin) if e["daten"].get("faehigkeit") == "knopf"]

    try:
        with pico.laeuft():  # wie auf dem Pico: start() verbindet WLAN und Broker und läuft dann endlos
            warte(lambda: len(stand()["faehigkeiten"]) == 3)
            assert (stand()["online"], stand()["firmware"]) == (True, "pico-beispiel 1.0")
            assert [(f["id"], f["art"], f["name"], f["funktion"]) for f in stand()["faehigkeiten"]] == [
                ("temperatur", "sensor", "Temperatur", "pico_temperatur"),
                ("knopf", "knopf", "Knopf", None),
                ("led", "aktor", "LED", "pico_led_schalten"),
            ]
            # Die Temperatur kommt gleich nach dem Start (danach alle 30 Sekunden).
            warte(lambda: stand()["faehigkeiten"][0]["wert"] == 21.5)
            assert stand()["faehigkeiten"][2]["wert"] == 0  # die LED meldet ihren Zustand: aus

            # Knopf: ein Druck ist genau ein Ereignis – auch wenn man den Knopf eine Weile hält.
            pico.knopf_druecken()
            warte(knopf_ereignisse)
            time.sleep(0.3)
            pico.knopf_loslassen()
            assert len(knopf_ereignisse()) == 1
            warte(lambda: _ereignisse(admin, "regel"))
            assert _ereignisse(admin, "regel")[0]["nachricht"] == "Am Pico wurde der Knopf gedrückt"

            # LED schalten – wie mit „Ausprobieren“ im Panel; das Gerät bestätigt den neuen Zustand.
            geschaltet = admin.post(
                f"/api/integrationen/{integration['id']}/aufrufen",
                json={"funktion": "led_schalten", "argumente": {"an": True}},
            ).json()
            assert geschaltet == {"ok": True, "ergebnis": "„LED“ ist jetzt an."}
            assert pico.led.wert == 1

            # Die Lebenszeichen halten die Verbindung: auch nach mehr als dem Anderthalbfachen noch online.
            time.sleep(3.5)
            assert stand()["online"] is True

        # Strom weg (die Firmware steht, ohne sich abzumelden): Der Broker meldet das Gerät als offline.
        start = time.monotonic()
        warte(lambda: not stand()["online"], sekunden=15)
        assert time.monotonic() - start < 10
        assert _ereignisse(admin)[-1]["titel"] == "Gerät „Pico“ ist offline"

        # Strom wieder da: Die Firmware meldet sich von selbst wieder an; die LED ist noch an.
        with pico.laeuft():
            warte(lambda: stand()["online"])
            assert stand()["faehigkeiten"][2]["wert"] == 1
    finally:
        pico.aufraeumen()


def test_pico_firmware_versucht_es_bei_fehlern_immer_wieder(
    admin: TestClient, broker: MqttBroker, capsys: pytest.CaptureFixture[str]
) -> None:
    integration = _hinzufuegen(admin, "Pico")

    # Falsches Passwort (z. B. nach „Neu koppeln“ im Panel): verständliche Meldung, neuer Versuch alle 5 s.
    falsch = PicoPruefstand(broker.port, integration["kopplung"], passwort="nicht-mehr-gueltig")
    falsch.zeit.hoechstens_pausen = 2
    with pytest.raises(Feierabend):
        falsch.modul.start()
    falsch.aufraeumen()
    assert falsch.zeit.pausen == [5, 5]
    ausgabe = capsys.readouterr().out
    assert ausgabe.count("Der Broker lehnt Benutzer oder Passwort ab - im Panel neu koppeln") == 2

    # WLAN nicht erreichbar: 30 Sekunden lang blinken, dann die Meldung und ein neuer Versuch.
    ohne_wlan = PicoPruefstand(broker.port, integration["kopplung"], wlan_passwort="ein-anderes")
    ohne_wlan.zeit.hoechstens_pausen = 61
    with pytest.raises(Feierabend):
        ohne_wlan.modul.start()
    assert ohne_wlan.zeit.pausen == [0.5] * 60 + [5]
    assert "WLAN nicht erreichbar" in capsys.readouterr().out
    assert ohne_wlan.stecker == []  # ohne WLAN wird der Broker gar nicht erst angesprochen

    # Broker nicht erreichbar (falsche Adresse in config.py).
    ohne_broker = PicoPruefstand(freier_port(), integration["kopplung"])
    ohne_broker.zeit.hoechstens_pausen = 1
    with pytest.raises(Feierabend):
        ohne_broker.modul.start()
    ohne_broker.aufraeumen()
    assert "Adresse des Brokers in config.py und das WLAN pruefen" in capsys.readouterr().out
    assert _geraet(admin, integration["id"])["status_seit"] is None  # hat sich nie gemeldet


def test_esp32_beispiel_passt_zum_panel() -> None:
    """Der ESP32-Sketch lässt sich hier nicht ausführen – geprüft wird, was sich am Text prüfen lässt:
    Die gemeldeten Fähigkeiten sind für das Panel gültig, die Themen stimmen, und die Muster-Konfiguration
    kennt genau die Angaben, die der Sketch braucht (dieselben, die das Panel in config.h schreibt)."""
    ordner = Path(__file__).resolve().parents[2] / "examples" / "geraete" / "esp32-arduino"
    sketch = (ordner / "esp32-arduino.ino").read_text(encoding="utf-8")

    block = sketch.split("const char FAEHIGKEITEN[] =", 1)[1].split(";\n", 1)[0]
    gemeldet = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', block)).replace('\\"', '"')
    firmware, faehigkeiten = faehigkeiten_lesen(gemeldet.encode())
    assert firmware == "esp32-beispiel 1.0"
    assert [(f["id"], f["art"], f["typ"], f["einheit"]) for f in faehigkeiten] == [
        ("temperatur", "sensor", "zahl", "°C"),
        ("knopf", "knopf", "zahl", ""),
        ("led", "aktor", "schalter", ""),
    ]
    assert len(gemeldet.encode()) + 60 < 512  # passt in den Puffer, den der Sketch für MQTT einstellt

    assert set(re.findall(r'thema\("([^"]+)"\)', sketch)) == {
        "status",
        "faehigkeiten",
        "befehl/#",
        "befehl/led",
        "zustand/led",
        "ereignis/knopf",
        "wert/temperatur",
    }
    assert 'String("missa/geraete/") + MQTT_BENUTZER' in sketch

    muster = (ordner / "config.beispiel.h").read_text(encoding="utf-8")
    angaben = set(re.findall(r"^#define (\w+)", muster, flags=re.MULTILINE))
    assert angaben == {
        "WLAN_NAME",
        "WLAN_PASSWORT",
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_BENUTZER",
        "MQTT_PASSWORT",
        "KNOPF_PIN",
        "LED_PIN",
    }
    assert all(re.search(rf"\b{angabe}\b", sketch) for angabe in angaben)


# ====================================================================== ohne Broker


def test_ohne_mqtt_broker_gibt_es_eine_verstaendliche_meldung(tmp_path: Path, uhr: Uhr) -> None:
    from cryptography.fernet import Fernet

    basis = Einstellungen(
        secret_key="test-secret-key-" + "x" * 32,
        encryption_key=Fernet.generate_key().decode(),
        daten_ordner=tmp_path / "data",
        integrations_ordner=Path(__file__).resolve().parents[2] / "integrations",
        mess_intervall_sekunden=0,
    )
    # 1) Der Broker ist gar nicht eingerichtet (COMPOSE_PROFILES ohne „geraete“ bzw. Start ohne Docker).
    app = create_app(basis)
    try:
        with TestClient(app) as ohne:
            einrichten(ohne, uhr)
            test = ohne.post("/api/integrationen/testen", json={"manifest_id": "geraet", "konfig": {}}).json()
            assert (test["ok"], test["meldung"]) == (
                False,
                "Der MQTT-Broker für Geräte ist nicht eingerichtet.",
            )
            assert "COMPOSE_PROFILES=geraete" in test["hinweis"]
            broker = ohne.get("/api/geraete").json()["broker"]
            assert (broker["eingerichtet"], broker["verbunden"]) == (False, False)
    finally:
        app.state.datenbank.schliessen()

    # 2) Eingerichtet, aber nicht erreichbar bzw. noch ohne Passwort-Datei.
    app = create_app(
        dataclasses.replace(
            basis, daten_ordner=tmp_path / "data2", mqtt_host="127.0.0.1", mqtt_port=freier_port()
        )
    )
    try:
        with TestClient(app) as aus:
            einrichten(aus, uhr)
            test = aus.post("/api/integrationen/testen", json={"manifest_id": "geraet", "konfig": {}}).json()
            assert (test["ok"], test["meldung"]) == (
                False,
                "Der MQTT-Broker für Geräte ist gerade nicht erreichbar.",
            )
            assert "docker compose -p missa-control ps" in test["hinweis"]
            anlegen = aus.post(
                "/api/integrationen", json={"manifest_id": "geraet", "name": "X", "konfig": {}}
            )
            assert anlegen.status_code == 422
            assert aus.get("/api/integrationen").json() == []  # es bleibt nichts Halbes zurück
            warte(
                lambda: (
                    "dynamic-security.json.pw fehlt" in aus.get("/api/geraete").json()["broker"]["meldung"]
                )
            )
    finally:
        app.state.datenbank.schliessen()
