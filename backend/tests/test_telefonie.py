"""Telefonie: Einstellungen, ausgehende Anrufe (Regeln, Missa, Panel), eingehende Anrufe und Adapter.

Ein echtes Telefon gibt es hier nicht: Der Test-Adapter protokolliert nur. Der Weg dorthin – wer
anrufen darf, Ruhezeit, Freigabe, Verlauf – ist aber derselbe wie später mit einem echten Adapter.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr, anmelden, client_token, integration_anlegen, mcp_client, mcp_text, warte_auf
from missa_control.config import Einstellungen
from missa_control.main import alte_daten_loeschen
from missa_control.serverlast.messen import Messung
from missa_control.telefonie.nummern import normalisieren
from server import LaufenderServer

LOUIS, OMA, FREMD = "+41791234567", "+41445556677", "+41780000000"


def _einstellen(admin: TestClient, **angaben: Any) -> dict:
    """Eigene Nummer, eine erlaubte Anruferin – und was der Test sonst noch braucht."""
    daten = {
        "eigene_nummern": [{"nummer": "079 123 45 67", "name": "Louis"}],
        "erlaubte_anrufer": [{"nummer": "+41 44 555 66 77", "name": "Oma"}],
        **angaben,
    }
    antwort = admin.put("/api/telefonie/einstellungen", json=daten)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _anrufe(admin: TestClient, **filter: Any) -> list[dict]:
    antwort = admin.get("/api/telefonie/anrufe", params=filter)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()["anrufe"]


def _ereignisse(admin: TestClient) -> list[dict]:
    return [e for e in reversed(admin.get("/api/ereignisse").json()) if e["art"] == "anruf"]


def _anrufen(admin: TestClient, text: str = "Die Waschmaschine ist fertig.", **mehr: Any) -> dict:
    antwort = admin.post("/api/telefonie/anrufen", json={"text": text, **mehr})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# ====================================================================== Einstellungen


def test_einstellungen_speichern_nummern_werden_einheitlich_geschrieben(angemeldet: TestClient) -> None:
    anfang = angemeldet.get("/api/telefonie").json()
    assert anfang["einstellungen"] == {
        "adapter": "test",
        "landesvorwahl": "+41",
        "eigene_nummern": [],
        "erlaubte_anrufer": [],
        "ruhezeiten": [],
        "nur_bekannte": True,
    }
    assert anfang["adapter"] == [
        {
            "kennung": "test",
            "name": "Test-Adapter",
            "beschreibung": "Ruft niemanden an – Anrufe werden nur protokolliert und als Ereignis gemeldet.",
            "test": True,
        }
    ]
    assert (anfang["adapter_fehlt"], anfang["ruhezeit_jetzt"], anfang["zeitzone"]) == (
        False,
        None,
        "Europe/Zurich",
    )

    gespeichert = _einstellen(angemeldet, ruhezeiten=[{"von": "22", "bis": "7:00"}])["einstellungen"]
    assert gespeichert["eigene_nummern"] == [{"nummer": LOUIS, "name": "Louis"}]
    assert gespeichert["erlaubte_anrufer"] == [{"nummer": OMA, "name": "Oma"}]
    assert gespeichert["ruhezeiten"] == [{"von": "22:00", "bis": "07:00"}]

    # Andere Landesvorwahl: Nummern ohne Vorwahl gehören dann dorthin.
    deutsch = _einstellen(
        angemeldet,
        landesvorwahl="0049",
        eigene_nummern=[{"nummer": "030 / 12 34 56", "name": ""}],
        erlaubte_anrufer=[],
    )["einstellungen"]
    assert (deutsch["landesvorwahl"], deutsch["eigene_nummern"]) == (
        "+49",
        [{"nummer": "+4930123456", "name": ""}],
    )

    for angaben, meldung in (
        ({"eigene_nummern": [{"nummer": "keine Nummer"}]}, "„keine Nummer“ ist keine gültige Telefonnummer."),
        (
            {"erlaubte_anrufer": [{"nummer": "044 555 66 77"}, {"nummer": "+49 44 555 66 77"}]},
            "„Erlaubte Anrufer“: Die Nummer +49445556677 steht doppelt in der Liste.",
        ),
        (
            {"eigene_nummern": [{"nummer": "0791234567"}], "erlaubte_anrufer": [{"nummer": "+49791234567"}]},
            "Die Nummer +49791234567 steht bei den eigenen Nummern und bei den erlaubten Anrufern.",
        ),
        ({"ruhezeiten": [{"von": "22:00", "bis": "25:00"}]}, "„bis“ ist keine gültige Uhrzeit."),
        (
            {"ruhezeiten": [{"von": "08:00", "bis": "08:00"}]},
            "Bei einer Ruhezeit dürfen „von“ und „bis“ nicht gleich sein.",
        ),
        ({"adapter": "integration:99"}, "Diesen Telefonie-Adapter gibt es nicht (mehr)."),
        ({"landesvorwahl": "41"}, "Die Landesvorwahl ist ungültig."),
    ):
        antwort = angemeldet.put("/api/telefonie/einstellungen", json=angaben)
        assert (antwort.status_code, antwort.json()["meldung"]) == (422, meldung), angaben
    # Nach den abgelehnten Versuchen steht noch alles wie zuvor.
    assert angemeldet.get("/api/telefonie").json()["einstellungen"] == deutsch


def test_nummern_normalisieren() -> None:
    assert normalisieren("079 123 45 67") == LOUIS
    assert normalisieren("0041 (79) 123-45-67") == LOUIS
    assert normalisieren("+41.79.123.45.67") == LOUIS
    assert normalisieren("030 123456", "+49") == "+4930123456"
    assert normalisieren("101") == "101"  # interne Kurznummer bleibt, wie sie ist


# ====================================================================== Regeln rufen an


def test_regel_mit_aktion_anrufen_erzeugt_einen_eintrag_im_verlauf(
    app: FastAPI, angemeldet: TestClient
) -> None:
    """Fertig-wenn: Eine Regel mit Aktion „anrufen“ erzeugt mit dem Test-Adapter einen Eintrag im Verlauf."""
    _einstellen(angemeldet)
    assert {"wert": "anruf", "titel": "Anrufen"} in angemeldet.get("/api/regeln").json()["optionen"][
        "aktionen"
    ]
    regel = angemeldet.post(
        "/api/regeln",
        json={
            "name": "CPU-Alarm",
            "ausloeser": {"art": "messwert", "messwert": "cpu", "schwelle": 90},
            "aktion": {
                "art": "anruf",
                "nachricht": "Die CPU von ai01 glüht: {wert} %",
                "dringlichkeit": "hoch",
            },
        },
    )
    assert regel.status_code == 201, regel.text
    assert regel.json()["satz"] == (
        "Wenn die CPU-Auslastung über 90 % liegt, dann ruft Missa dich an und sagt: "
        "„Die CPU von ai01 glüht: {wert} %“ (Dringlichkeit: hoch). Danach 30 Minuten Ruhe."
    )
    assert _anrufe(angemeldet) == []

    app.state.serverlast.quelle = lambda _intervall: Messung(
        cpu=97.0, ram=40.0, speicher=55.0, cpu_kerne=8, last=1.0
    )
    app.state.serverlast.aufzeichnen()
    assert app.state.regeln.warten()

    (anruf,) = _anrufe(angemeldet)
    assert {
        name: anruf[name]
        for name in ("richtung", "nummer", "name", "status", "status_text", "dauer_sekunden")
    } == {
        "richtung": "ausgehend",
        "nummer": LOUIS,
        "name": "Louis",
        "status": "test",
        "status_text": "Test – nur protokolliert",
        "dauer_sekunden": 0,
    }
    assert (anruf["grund"], anruf["dringlichkeit"]) == ("Die CPU von ai01 glüht: 97 %", "hoch")
    assert (anruf["quelle"], anruf["quelle_name"], anruf["adapter"]) == ("regel", "CPU-Alarm", "test")
    assert anruf["meldung"] == "Test-Adapter: Es wurde niemand wirklich angerufen."

    # Der Test-Adapter meldet den Anruf als Ereignis – so erfährt auch Missa davon.
    (ereignis,) = _ereignisse(angemeldet)
    assert (ereignis["titel"], ereignis["nachricht"], ereignis["dringlichkeit"]) == (
        f"Anruf an Louis ({LOUIS}) (Test)",
        "Die CPU von ai01 glüht: 97 %",
        "hoch",
    )
    assert ereignis["daten"] == {
        "anruf_id": anruf["id"],
        "richtung": "ausgehend",
        "nummer": LOUIS,
        "name": "Louis",
        "status": "test",
        "adapter": "test",
        "test": True,
    }
    ausloesung = angemeldet.get("/api/regeln/verlauf").json()["eintraege"][0]
    assert (ausloesung["ergebnis"], ausloesung["meldung"]) == (
        "ok",
        f"Test-Adapter: Der Anruf an Louis ({LOUIS}) wurde nur protokolliert – es hat nirgends geklingelt.",
    )

    # Mit Nummer statt „dich“ – und ohne eigene Nummer sagt die Regel, was fehlt.
    mit_nummer = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Oma wecken",
            "ausloeser": {"art": "zeitplan", "uhrzeit": "08:00"},
            "aktion": {"art": "anruf", "nummer": "044 555 66 77", "nachricht": "Guten Morgen!"},
        },
    ).json()
    assert (
        mit_nummer["satz"]
        == "Jeden Tag um 08:00 Uhr ruft Missa die Nummer 044 555 66 77 an und sagt: „Guten Morgen!“."
    )
    assert angemeldet.post(f"/api/regeln/{mit_nummer['id']}/testen").json()["ok"] is True
    assert _anrufe(angemeldet)[0]["nummer"] == OMA
    ungueltig = angemeldet.post(
        "/api/regeln",
        json={
            "name": "x",
            "ausloeser": {"art": "zeitplan", "uhrzeit": "08:00"},
            "aktion": {"art": "anruf", "nummer": "abc", "nachricht": "Hallo"},
        },
    )
    assert (ungueltig.status_code, ungueltig.json()["meldung"]) == (
        422,
        "„abc“ ist keine gültige Telefonnummer.",
    )

    _einstellen(angemeldet, eigene_nummern=[])
    ohne = angemeldet.post(f"/api/regeln/{regel.json()['id']}/testen").json()
    assert ohne["ok"] is False
    assert ohne["meldung"].startswith("Es ist keine eigene Nummer hinterlegt.")


def test_missa_kann_eine_regel_mit_anruf_anlegen(app: FastAPI, angemeldet: TestClient) -> None:
    satz = app.state.regeln.vorschau_anlegen(
        name="Wecker",
        ausloeser="zeitplan",
        uhrzeit="06:30",
        aktion="anruf",
        nachricht="Aufstehen!",
        nummer="079 123 45 67",
    )
    assert "ruft Missa die Nummer 079 123 45 67 an und sagt: „Aufstehen!“" in satz


# ====================================================================== eingehende Anrufe


def test_unbekannter_anrufer_wird_abgewiesen_und_protokolliert(angemeldet: TestClient) -> None:
    """Fertig-wenn: Nummer nicht in der Liste erlaubter Anrufer wird abgewiesen und protokolliert."""
    _einstellen(angemeldet)

    fremd = angemeldet.post("/api/telefonie/eingehend-simulieren", json={"nummer": "078 000 00 00"}).json()
    assert (fremd["annehmen"], fremd["nummer"], fremd["grund"]) == (
        False,
        FREMD,
        "Die Nummer steht nicht in der Liste erlaubter Anrufer.",
    )
    (anruf,) = _anrufe(angemeldet)
    assert (anruf["richtung"], anruf["nummer"], anruf["status"], anruf["status_text"], anruf["grund"]) == (
        "eingehend",
        FREMD,
        "abgewiesen",
        "abgewiesen",
        "Die Nummer steht nicht in der Liste erlaubter Anrufer.",
    )
    (ereignis,) = _ereignisse(angemeldet)
    assert (ereignis["titel"], ereignis["dringlichkeit"]) == (f"Anruf von {FREMD} abgewiesen", "niedrig")

    # Erlaubte Anrufer kommen durch – auch wenn die Nummer anders geschrieben ankommt.
    oma = angemeldet.post("/api/telefonie/eingehend-simulieren", json={"nummer": "0445556677"}).json()
    assert (oma["annehmen"], oma["name"], oma["grund"]) == (True, "Oma", "")
    # Die eigene Nummer darf immer.
    assert (
        angemeldet.post("/api/telefonie/eingehend-simulieren", json={"nummer": LOUIS}).json()["annehmen"]
        is True
    )
    # Unterdrückte Nummer: abgewiesen.
    anonym = angemeldet.post("/api/telefonie/eingehend-simulieren", json={"nummer": ""}).json()
    assert (anonym["annehmen"], anonym["grund"]) == (False, "Die Nummer ist unterdrückt oder ungültig.")

    verlauf = _anrufe(angemeldet, richtung="eingehend")
    assert [(a["nummer"], a["name"], a["status"]) for a in verlauf] == [
        ("unbekannt", "", "abgewiesen"),
        (LOUIS, "Louis", "test"),
        (OMA, "Oma", "test"),
        (FREMD, "", "abgewiesen"),
    ]
    assert _anrufe(angemeldet, richtung="ausgehend") == []
    assert angemeldet.get("/api/telefonie/anrufe", params={"richtung": "quer"}).status_code == 422
    assert _ereignisse(angemeldet)[1]["titel"] == f"Anruf von Oma ({OMA})"


def test_adapter_meldet_eingehende_anrufe_und_das_ende_mit_client_token(angemeldet: TestClient) -> None:
    """Ein Adapter ausserhalb des Panels (App, SIP-Brücke) spricht mit einem Client-Token."""
    _einstellen(angemeldet)
    token = {"Authorization": f"Bearer {client_token(angemeldet, 'Telefon-App')}"}
    ohne = TestClient(angemeldet.app)
    assert ohne.post("/api/telefonie/adapter/eingehend", json={"nummer": OMA}).status_code == 401
    assert (
        ohne.post(
            "/api/telefonie/adapter/eingehend",
            json={"nummer": OMA},
            headers={"Authorization": "Bearer falsch"},
        ).status_code
        == 401
    )
    # Mit dem Token eines Clients kommt man nur an den Adapter-Anschluss, nicht an die Einstellungen.
    assert ohne.get("/api/telefonie", headers=token).status_code == 401

    entscheidung = ohne.post("/api/telefonie/adapter/eingehend", json={"nummer": OMA}, headers=token).json()
    assert (entscheidung["annehmen"], entscheidung["name"]) == (True, "Oma")
    laufend = _anrufe(angemeldet)[0]
    assert (laufend["status"], laufend["status_text"], laufend["adapter"], laufend["dauer_sekunden"]) == (
        "laeuft",
        "läuft",
        "Telefon-App",
        None,
    )
    beendet = ohne.post(
        f"/api/telefonie/adapter/anrufe/{entscheidung['anruf_id']}/beendet",
        json={"dauer_sekunden": 42},
        headers=token,
    )
    assert beendet.status_code == 200, beendet.text
    assert (_anrufe(angemeldet)[0]["status"], _anrufe(angemeldet)[0]["dauer_sekunden"]) == ("beendet", 42)

    nochmal = ohne.post(
        f"/api/telefonie/adapter/anrufe/{entscheidung['anruf_id']}/beendet", json={}, headers=token
    )
    assert (nochmal.status_code, nochmal.json()["meldung"]) == (
        409,
        "Dieser Anruf ist bereits abgeschlossen.",
    )
    assert ohne.post("/api/telefonie/adapter/anrufe/999/beendet", json={}, headers=token).status_code == 404
    abgewiesen = ohne.post("/api/telefonie/adapter/eingehend", json={"nummer": FREMD}, headers=token).json()
    assert abgewiesen["annehmen"] is False
    unsinn = ohne.post(
        f"/api/telefonie/adapter/anrufe/{abgewiesen['anruf_id']}/beendet",
        json={"ergebnis": "explodiert"},
        headers=token,
    )
    assert unsinn.status_code == 422


# ====================================================================== Missa ruft an


@pytest.mark.anyio
async def test_missa_ruft_erst_nach_freigabe_an(angemeldet: TestClient, panel: LaufenderServer) -> None:
    _einstellen(angemeldet)
    integration = integration_anlegen(angemeldet, "telefonie")
    assert (
        integration["status_meldung"]
        == "Telefonie bereit: Test-Adapter, 1 eigene Nummer, 1 erlaubter Anrufer."
    )
    assert {f["name"]: f["recht"] for f in integration["funktionen"]} == {
        "anrufen": "nachfragen",
        "anrufe_anzeigen": "erlaubt",
    }

    async with mcp_client(panel.url, client_token(angemeldet)) as missa:
        assert {w.name for w in (await missa.list_tools()).tools} == {
            "telefon_anrufen",
            "telefon_anrufe_anzeigen",
        }

        aufruf = asyncio.create_task(missa.call_tool("telefon_anrufen", {"text": "Das Essen ist fertig."}))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        assert offen[0]["vorschau"] == (
            f"Ruft Louis ({LOUIS}) an (Test-Adapter: nur protokolliert) und sagt: „Das Essen ist fertig.“"
        )
        assert _anrufe(angemeldet) == []  # noch ist nichts passiert
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": True})
        ergebnis = json.loads(mcp_text(await asyncio.wait_for(aufruf, timeout=5)))
        assert (ergebnis["nummer"], ergebnis["name"], ergebnis["status"]) == (LOUIS, "Louis", "test")
        assert "nur protokolliert" in ergebnis["meldung"]
        assert [(a["quelle"], a["grund"]) for a in _anrufe(angemeldet)] == [
            ("missa", "Das Essen ist fertig.")
        ]

        # Eine fremde Nummer: Dafür wird niemand gefragt – die Antwort kommt sofort.
        fremd = await missa.call_tool("telefon_anrufen", {"text": "Hallo", "nummer": FREMD})
        assert fremd.is_error is True
        assert f"Die Nummer {FREMD} darf nicht angerufen werden" in mcp_text(fremd)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []

        verlauf = json.loads(mcp_text(await missa.call_tool("telefon_anrufe_anzeigen", {"anzahl": 5})))
        assert verlauf["anzahl"] == 1
        assert (verlauf["anrufe"][0]["richtung"], verlauf["anrufe"][0]["status_text"]) == (
            "ausgehend",
            "Test – nur protokolliert",
        )


# ====================================================================== Ruhezeit, bekannte Nummern


def test_in_der_ruhezeit_gehen_nur_dringende_anrufe_durch(
    angemeldet: TestClient, uhr: Uhr, geheimnis: str
) -> None:
    # Die Test-Uhr steht auf 12:00 UTC – in Zürich ist es 13:00.
    ansicht = _einstellen(angemeldet, ruhezeiten=[{"von": "12:30", "bis": "14:00"}])
    assert ansicht["ruhezeit_jetzt"] == {"von": "12:30", "bis": "14:00"}

    still = _anrufen(angemeldet)
    assert still == {
        "ok": False,
        "meldung": "Nicht angerufen: Es ist Ruhezeit (12:30 bis 14:00 Uhr).",
        "hinweis": "In der Ruhezeit gehen nur Anrufe mit der Dringlichkeit „dringend“ durch.",
    }
    (anruf,) = _anrufe(angemeldet)
    assert (anruf["status"], anruf["status_text"], anruf["meldung"]) == (
        "unterdrueckt",
        "nicht angerufen (Ruhezeit)",
        "Nicht angerufen: Es ist Ruhezeit (12:30 bis 14:00 Uhr).",
    )
    # Es geht nichts verloren: Missa erfährt als Ereignis, was sie hätte ausrichten sollen.
    assert (_ereignisse(angemeldet)[0]["titel"], _ereignisse(angemeldet)[0]["nachricht"]) == (
        "Anruf in der Ruhezeit nicht ausgeführt",
        "Die Waschmaschine ist fertig.",
    )

    dringend = _anrufen(angemeldet, "Rauchmelder im Keller!", dringlichkeit="dringend")
    assert dringend["ok"] is True
    assert _anrufe(angemeldet)[0]["status"] == "test"

    uhr.vor(hours=1, minutes=5)  # 14:05 – die Ruhezeit ist vorbei
    assert _anrufen(angemeldet)["ok"] is True

    # Eine Ruhezeit über Mitternacht.
    _einstellen(angemeldet, ruhezeiten=[{"von": "22:00", "bis": "07:00"}])
    assert angemeldet.get("/api/telefonie").json()["ruhezeit_jetzt"] is None
    uhr.vor(hours=9)  # 23:05
    assert _anrufen(angemeldet)["ok"] is False
    uhr.vor(hours=7)  # 06:05 am nächsten Morgen (die Anmeldung von gestern ist inzwischen abgelaufen)
    anmelden(angemeldet, uhr, geheimnis)
    assert _anrufen(angemeldet)["ok"] is False
    uhr.vor(hours=1)  # 07:05
    assert _anrufen(angemeldet)["ok"] is True


def test_missa_ruft_nur_bekannte_nummern_an_ausser_es_ist_anders_eingestellt(angemeldet: TestClient) -> None:
    _einstellen(angemeldet)
    abgelehnt = _anrufen(angemeldet, nummer="078 000 00 00")
    assert abgelehnt["ok"] is False
    assert abgelehnt["meldung"].startswith(f"Die Nummer {FREMD} darf nicht angerufen werden")
    assert "Im Panel unter „Anrufe“ die Nummer eintragen" in abgelehnt["hinweis"]
    # Auch der abgelehnte Versuch steht im Verlauf.
    (versuch,) = _anrufe(angemeldet)
    assert (versuch["richtung"], versuch["status"], versuch["nummer"]) == (
        "ausgehend",
        "abgewiesen",
        "078 000 00 00",
    )

    assert _anrufen(angemeldet, nummer="044 555 66 77")["anruf"]["name"] == "Oma"

    _einstellen(angemeldet, nur_bekannte=False)
    frei = _anrufen(angemeldet, nummer="078 000 00 00")
    assert (frei["ok"], frei["anruf"]["nummer"], frei["anruf"]["name"]) == (True, FREMD, "")

    for angaben, meldung in (
        ({"text": "  "}, "Bitte angeben, was beim Anruf gesagt werden soll."),
        ({"text": "x" * 501}, "Der Text ist zu lang (höchstens 500 Zeichen)."),
        ({"text": "Hallo", "dringlichkeit": "sofort"}, "Die Dringlichkeit „sofort“ gibt es nicht."),
        ({"text": "Hallo", "nummer": "abc"}, "„abc“ ist keine gültige Telefonnummer."),
    ):
        antwort = angemeldet.post("/api/telefonie/anrufen", json=angaben).json()
        assert (antwort["ok"], antwort["meldung"]) == (False, meldung), angaben


# ====================================================================== Adapter aus einer Integration

ADAPTER_MANIFEST = """
id: telefon-probe
name: Telefon-Probe
beschreibung: Ein Telefonie-Adapter für den Test.
art: python
"""

ADAPTER_MAIN = """
from missa_control.sdk import Fehler, Kontext, funktion, telefon_anrufen, telefon_auflegen

ANRUFE = []
AUFGELEGT = []


@funktion(schreibend=False)
def bereit(kontext: Kontext) -> str:
    return "ja"


@telefon_anrufen
async def anrufen(kontext: Kontext, auftrag):
    if auftrag.nummer.endswith("6677"):
        raise Fehler("Besetzt.", "Später noch einmal versuchen.")
    ANRUFE.append((auftrag.anruf_id, auftrag.nummer, auftrag.name, auftrag.text, auftrag.dringlichkeit))
    if "kurz" in auftrag.text:
        return {"ergebnis": "beendet", "dauer_sekunden": 12, "meldung": "aufgelegt"}
    return None  # der Anruf läuft – das Ende meldet der Adapter später


@telefon_auflegen
def auflegen(kontext: Kontext, anruf_id: int) -> None:
    AUFGELEGT.append(anruf_id)
"""


@pytest.fixture
def probe_adapter(einstellungen: Einstellungen) -> Path:
    ordner = einstellungen.eigene_integrationen_ordner / "telefon-probe"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(ADAPTER_MANIFEST, encoding="utf-8")
    (ordner / "main.py").write_text(ADAPTER_MAIN, encoding="utf-8")
    return ordner


def test_weitere_adapter_kommen_als_integration_dazu(
    probe_adapter: Path, app: FastAPI, angemeldet: TestClient
) -> None:
    """Ein Adapter ist eine Integration, deren main.py `@telefon_anrufen` enthält."""
    _einstellen(angemeldet)
    assert [a["kennung"] for a in angemeldet.get("/api/telefonie").json()["adapter"]] == [
        "test"
    ]  # noch nicht eingerichtet
    integration = integration_anlegen(angemeldet, "telefon-probe")
    kennung = f"integration:{integration['id']}"
    adapter = angemeldet.get("/api/telefonie").json()["adapter"]
    assert [(a["kennung"], a["name"], a["test"]) for a in adapter] == [
        ("test", "Test-Adapter", True),
        (kennung, "Telefon-Probe", False),
    ]
    _einstellen(angemeldet, adapter=kennung)

    # Der Adapter wartet bis zum Ende des Gesprächs und meldet die Dauer gleich mit.
    kurz = _anrufen(angemeldet, "Nur kurz: Das Paket ist da.", dringlichkeit="hoch")
    assert (kurz["ok"], kurz["meldung"]) == (True, f"Anruf an Louis ({LOUIS}): beendet.")
    erster = _anrufe(angemeldet)[0]
    assert (erster["status"], erster["dauer_sekunden"], erster["meldung"], erster["adapter"]) == (
        "beendet",
        12,
        "aufgelegt",
        kennung,
    )
    assert (
        _ereignisse(angemeldet)[0]["titel"] == f"Anruf an Louis ({LOUIS})"
    )  # ohne „(Test)“: ein echter Adapter

    # Der Anruf läuft weiter; das Ende meldet der Adapter später.
    lang = _anrufen(angemeldet, "Eine lange Geschichte.")
    assert lang["anruf"]["status"] == "laeuft"
    app.state.telefonie.anruf_beendet(lang["anruf"]["id"], dauer_sekunden=75)
    assert (_anrufe(angemeldet)[0]["status"], _anrufe(angemeldet)[0]["dauer_sekunden"]) == ("beendet", 75)

    import sys

    modul = sys.modules["missa_integration_telefon_probe.main"]
    assert modul.ANRUFE == [
        (erster["id"], LOUIS, "Louis", "Nur kurz: Das Paket ist da.", "hoch"),
        (lang["anruf"]["id"], LOUIS, "Louis", "Eine lange Geschichte.", "normal"),
    ]

    # Ein Fehler des Adapters kommt verständlich an und steht im Verlauf.
    besetzt = _anrufen(angemeldet, "Hallo Oma", nummer=OMA)
    assert besetzt == {"ok": False, "meldung": "Besetzt.", "hinweis": "Später noch einmal versuchen."}
    assert (_anrufe(angemeldet)[0]["status"], _anrufe(angemeldet)[0]["meldung"]) == ("fehler", "Besetzt.")

    # Wird die Integration ausgeschaltet, fehlt der Adapter – das Panel sagt es, statt still nichts zu tun.
    angemeldet.put(f"/api/integrationen/{integration['id']}", json={"aktiv": False})
    assert angemeldet.get("/api/telefonie").json()["adapter_fehlt"] is True
    ohne = _anrufen(angemeldet)
    assert (ohne["ok"], ohne["meldung"]) == (
        False,
        "Der gewählte Telefonie-Adapter steht nicht mehr zur Verfügung.",
    )
    assert _anrufe(angemeldet)[0]["status"] == "fehler"


# ====================================================================== Aufräumen


def test_alte_anrufe_werden_geloescht_und_haengende_abgeschlossen(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr, geheimnis: str
) -> None:
    _einstellen(angemeldet)
    _anrufen(angemeldet)
    haengt = app.state.telefonie.eingehender_anruf(OMA)  # der Adapter meldet das Ende nie
    assert _anrufe(angemeldet)[0]["status"] == "laeuft"

    uhr.vor(hours=13)
    alte_daten_loeschen(app)
    anmelden(angemeldet, uhr, geheimnis)
    abgeschlossen = next(a for a in _anrufe(angemeldet) if a["id"] == haengt["anruf_id"])
    assert (abgeschlossen["status"], abgeschlossen["meldung"]) == (
        "beendet",
        "Ohne Rückmeldung des Adapters abgeschlossen.",
    )

    uhr.vor(days=31)
    alte_daten_loeschen(app)
    anmelden(angemeldet, uhr, geheimnis)
    assert _anrufe(angemeldet) == []
