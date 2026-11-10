"""Die Übersicht (Verbindungsbaum): Knoten, Kanten und ihr Status – und der einzige Kontakt zu missa-core."""

from __future__ import annotations

import asyncio
import dataclasses
import socket
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from mcp.types import ToolAnnotations

from hilfen import Uhr, client_token, einrichten, integration_anlegen, mcp_client, mcp_text, warte_auf
from missa_control.config import Einstellungen
from missa_control.integrationen import dienst as integrations_dienst
from missa_control.integrationen.modelle import Integration
from missa_control.main import create_app
from server import LaufenderServer, freier_port, notizen_mcp_server


def _status(admin: TestClient) -> dict:
    antwort = admin.get("/api/status")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _pruefen(admin: TestClient) -> dict:
    """Wie die regelmässige Prüfung des Panels – nur sofort."""
    antwort = admin.post("/api/status/pruefen")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _knoten(uebersicht: dict, kennung: str) -> dict:
    return next(knoten for knoten in uebersicht["knoten"] if knoten["id"] == kennung)


def _kanten(uebersicht: dict) -> set[tuple[str, str, str]]:
    return {(kante["von"], kante["nach"], kante["art"]) for kante in uebersicht["kanten"]}


# ====================================================================== missa-core


class HealthServer:
    """Steht für missa-core: merkt sich jede Anfrage – so lässt sich prüfen, dass das Panel nur liest."""

    def __init__(self) -> None:
        self.anfragen: list[tuple[str, str]] = []
        self.status = 200
        app = FastAPI()

        @app.api_route("/{pfad:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        async def alles(pfad: str, request: Request) -> JSONResponse:
            self.anfragen.append((request.method, "/" + pfad))
            return JSONResponse({"status": "ok"}, status_code=self.status)

        self.app = app


@pytest.fixture
def missa_core() -> Iterator[tuple[HealthServer, LaufenderServer]]:
    health = HealthServer()
    with LaufenderServer(health.app) as server:
        yield health, server


def test_ohne_health_url_ist_missa_grau_statt_rot(angemeldet: TestClient) -> None:
    """Fertig-wenn: Ohne Health-URL ist der missa-core-Knoten grau statt rot."""
    missa = _knoten(_pruefen(angemeldet), "missa")
    assert (missa["art"], missa["name"], missa["untertitel"], missa["status"]) == (
        "missa",
        "Missa",
        "missa-core",
        "grau",
    )
    assert missa["status_text"] == "Nicht eingerichtet – ohne Health-URL wird missa-core nicht abgefragt."
    assert missa["details"][0] == {
        "titel": "Health-URL",
        "wert": "nicht eingestellt (MISSA_CORE_HEALTH_URL in .env)",
        "zeit": False,
    }


def test_mit_health_url_gruen_oder_rot_und_nur_lesend(
    einstellungen: Einstellungen, uhr: Uhr, missa_core: tuple[HealthServer, LaufenderServer]
) -> None:
    """Der einzige Kontakt zu missa-core ist ein GET auf die Health-URL."""
    health, server = missa_core
    app = create_app(dataclasses.replace(einstellungen, missa_core_health_url=server.url + "/health"))
    try:
        with TestClient(app) as admin:
            einrichten(admin, uhr)
            assert _knoten(_status(admin), "missa")["status_text"] == "Wird gleich zum ersten Mal geprüft."

            missa = _knoten(_pruefen(admin), "missa")
            assert (missa["status"], missa["status_text"]) == ("ok", "missa-core antwortet.")
            assert missa["details"][0]["wert"] == server.url + "/health"
            assert missa["details"][2]["wert"].endswith(" ms")

            health.status = 503
            missa = _knoten(_pruefen(admin), "missa")
            assert (missa["status"], missa["status_text"]) == (
                "fehler",
                "missa-core meldet einen Fehler (HTTP 503).",
            )
    finally:
        app.state.datenbank.schliessen()
    # Was auch immer das Panel getan hat: bei missa-core kam nur das an.
    assert set(health.anfragen) == {("GET", "/health")}
    assert len(health.anfragen) == 2

    # Nicht erreichbar: rot.
    app = create_app(
        dataclasses.replace(
            einstellungen,
            daten_ordner=einstellungen.daten_ordner.parent / "data2",
            missa_core_health_url=f"http://127.0.0.1:{freier_port()}/health",
        )
    )
    try:
        with TestClient(app) as admin:
            einrichten(admin, uhr)
            missa = _knoten(_pruefen(admin), "missa")
            assert missa["status"] == "fehler"
            assert missa["status_text"].startswith("missa-core antwortet nicht")
    finally:
        app.state.datenbank.schliessen()


def test_das_panel_prueft_von_selbst(
    einstellungen: Einstellungen, uhr: Uhr, missa_core: tuple[HealthServer, LaufenderServer]
) -> None:
    health, server = missa_core
    app = create_app(
        dataclasses.replace(
            einstellungen, missa_core_health_url=server.url + "/health", pruef_intervall_sekunden=0.05
        )
    )
    try:
        with TestClient(app) as admin:
            einrichten(admin, uhr)
            ende = time.monotonic() + 5
            while len(health.anfragen) < 3 and time.monotonic() < ende:
                time.sleep(0.02)
            assert len(health.anfragen) >= 3
            assert _knoten(_status(admin), "missa")["status"] == "ok"
    finally:
        app.state.datenbank.schliessen()
    assert set(health.anfragen) == {("GET", "/health")}
    # Im Betrieb: alle 20 Sekunden. Die Übersicht fragt alle 30 Sekunden nach, die Prüfung selbst wartet
    # höchstens 8 Sekunden – ein Ausfall ist so nach spätestens 58 Sekunden zu sehen.
    assert Einstellungen.aus_umgebung.__name__ == "aus_umgebung"
    assert integrations_dienst.PRUEF_SEKUNDEN <= 8


def test_im_betrieb_wird_alle_20_sekunden_geprueft(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MISSA_CORE_HEALTH_URL", " http://192.168.1.10:8000/health ")
    betrieb = Einstellungen.aus_umgebung()
    assert betrieb.pruef_intervall_sekunden == 20.0
    assert betrieb.missa_core_health_url == "http://192.168.1.10:8000/health"

    monkeypatch.setenv("MISSA_CORE_HEALTH_URL", "192.168.1.10:8000/health")
    with pytest.raises(Exception, match="MISSA_CORE_HEALTH_URL muss mit http:// oder https:// beginnen"):
        Einstellungen.aus_umgebung()
    monkeypatch.setenv("MISSA_CORE_HEALTH_URL", "")
    assert Einstellungen.aus_umgebung().missa_core_health_url is None


# ====================================================================== Integrationen


def test_neue_integration_erscheint_und_ein_ausfall_wird_rot(
    angemeldet: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fertig-wenn: Neue Integration erscheint im Graph; eine ausgefallene wird (bei der nächsten Prüfung) rot."""
    vorher = _status(angemeldet)
    assert [k["id"] for k in vorher["knoten"]] == ["missa", "rolle:schnell", "rolle:stark"]

    port = freier_port()
    server = notizen_mcp_server()
    with LaufenderServer(server.streamable_http_app(), port=port) as notizen:
        integration = integration_anlegen(
            angemeldet, "mcp-server", {"url": notizen.url + "/mcp"}, name="Notizen"
        )
        kennung = f"integration:{integration['id']}"

        # Die Übersicht kennt die Integration sofort – ohne dass irgendetwas neu gestartet wird.
        uebersicht = _status(angemeldet)
        knoten = _knoten(uebersicht, kennung)
        assert (knoten["art"], knoten["name"], knoten["untertitel"], knoten["status"]) == (
            "integration",
            "Notizen",
            "MCP-Server",
            "ok",
        )
        assert ("missa", kennung, "nutzt") in _kanten(uebersicht)
        assert knoten["link"] == {"pfad": "/integrationen", "titel": "Zur Integration"}
        assert {f["name"]: (f["recht"], f["recht_name"]) for f in knoten["funktionen"]} == {
            "notizen_auflisten": ("erlaubt", "erlaubt"),
            "notizen_notiz_anlegen": ("nachfragen", "erst nachfragen"),
            "notizen_get_and_delete_all": ("nachfragen", "erst nachfragen"),
            "notizen_search_notizen": ("erlaubt", "erlaubt"),
        }
        assert {d["titel"]: d["wert"] for d in knoten["details"][:2]} == {
            "Art": "MCP-Server",
            "Funktionen für Missa": "4 von 4",
        }

        # Solange alles läuft, bleibt die Prüfung unauffällig – und meldet nichts.
        assert _knoten(_pruefen(angemeldet), kennung)["status"] == "ok"
        assert angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json() == []

        # Die Gegenstelle bekommt eine neue Funktion: Die Prüfung übernimmt sie NICHT von selbst
        # (sonst wäre plötzlich etwas erlaubt, das niemand gesehen hat) – erst „Testen“ tut das.
        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        def notizen_zaehlen() -> int:
            """Zählt die Notizen."""
            return 1

        assert len(_knoten(_pruefen(angemeldet), kennung)["funktionen"]) == 4
        angemeldet.post(f"/api/integrationen/{integration['id']}/testen")
        assert len(_knoten(_status(angemeldet), kennung)["funktionen"]) == 5

    # Der MCP-Server ist weg. Niemand ruft etwas auf – trotzdem fällt es bei der nächsten Prüfung auf.
    start = time.monotonic()
    ausgefallen = _knoten(_pruefen(angemeldet), kennung)
    assert time.monotonic() - start < 8
    assert ausgefallen["status"] == "fehler"
    assert "nicht erreichbar" in ausgefallen["status_text"]
    assert ausgefallen["hinweis"]
    assert _pruefen(angemeldet)["zusammenfassung"]["fehler"] == 1
    ereignisse = angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json()
    assert [e["titel"] for e in ereignisse] == [
        "Integration „Notizen“ ist ausgefallen"
    ]  # nur einmal gemeldet

    # Antwortet die Gegenstelle gar nicht (statt abzulehnen), wartet die Prüfung nur kurz.
    stumm = socket.socket()
    stumm.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    stumm.bind(("127.0.0.1", port))
    stumm.listen(5)  # nimmt Verbindungen an, antwortet aber nie
    try:
        with monkeypatch.context() as kurz:
            kurz.setattr(integrations_dienst, "PRUEF_SEKUNDEN", 0.4)
            start = time.monotonic()
            assert _knoten(_pruefen(angemeldet), kennung)["status"] == "fehler"
            assert time.monotonic() - start < 4
    finally:
        stumm.close()

    # Der Server kommt zurück: wieder grün, und das Panel meldet die Rückkehr.
    with LaufenderServer(notizen_mcp_server().streamable_http_app(), port=port):
        assert _knoten(_pruefen(angemeldet), kennung)["status"] == "ok"
    zurueck = angemeldet.get("/api/ereignisse", params={"art": "integration_wieder_da"}).json()
    assert [e["titel"] for e in zurueck] == ["Integration „Notizen“ funktioniert wieder"]

    # Deaktiviert: grau – und wird nicht mehr geprüft.
    angemeldet.put(f"/api/integrationen/{integration['id']}", json={"aktiv": False})
    aus = _knoten(_pruefen(angemeldet), kennung)
    assert (aus["status"], aus["status_text"]) == ("grau", "Deaktiviert.")


def test_wird_waehrend_der_pruefung_eine_integration_entfernt_laeuft_die_runde_weiter(
    app: FastAPI, angemeldet: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine Prüfung dauert bis zu einigen Sekunden – in der Zeit kann im Panel etwas entfernt werden."""
    erste = integration_anlegen(angemeldet, "serverlast")
    zweite = integration_anlegen(angemeldet, "gedaechtnis")
    dritte = integration_anlegen(angemeldet, "regeln")
    dienst = app.state.integrationen
    echt = dienst._test_ausfuehren
    geprueft: list[str] = []
    betroffen: dict[str, int] = {}

    async def mit_zwischenfall(adapter: Any, kontext: Any, sekunden: float = 0) -> Any:
        geprueft.append(kontext.name)
        if len(geprueft) == 1:
            # Während die Prüfungen laufen, entfernt der Besitzer in einer anderen Anfrage (eigene
            # Datenbank-Sitzung) eine Integration – und schaltet eine weitere aus.
            andere = next(i for i in (erste, zweite, dritte) if i["id"] != kontext.integration_id)
            betroffen.update(entfernt=kontext.integration_id, aus=andere["id"])
            with app.state.datenbank.sitzung() as zweite_sitzung:
                zweite_sitzung.delete(zweite_sitzung.get(Integration, kontext.integration_id))
                zweite_sitzung.get(Integration, andere["id"]).aktiv = False
                zweite_sitzung.commit()
        ergebnis = await echt(adapter, kontext, sekunden)
        if kontext.integration_id == betroffen.get("aus"):
            # Diese Prüfung „scheitert“ – ihr Ergebnis darf nicht mehr zählen: Die Integration ist ja aus.
            return dataclasses.replace(ergebnis, ok=False, meldung="zu spät")
        return ergebnis

    monkeypatch.setattr(dienst, "_test_ausfuehren", mit_zwischenfall)
    uebersicht = _pruefen(angemeldet)  # ohne Fehler – die Runde läuft für die übrigen weiter

    integrationen = {k["id"]: k for k in uebersicht["knoten"] if k["art"] == "integration"}
    assert f"integration:{betroffen['entfernt']}" not in integrationen  # die entfernte ist weg
    assert len(integrationen) == 2
    assert integrationen[f"integration:{betroffen['aus']}"]["status"] == "grau"  # ausgeschaltet: kein Fehler
    assert sorted(k["status"] for k in integrationen.values()) == ["grau", "ok"]
    assert angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json() == []
    # Die nächste Runde läuft ganz normal.
    monkeypatch.setattr(dienst, "_test_ausfuehren", echt)
    assert _pruefen(angemeldet)["zusammenfassung"]["fehler"] == 0


def test_haengen_mehrere_gegenstellen_gleichzeitig_dauert_die_runde_nicht_laenger(
    angemeldet: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fällt das Netz aus, hängen alle Gegenstellen auf einmal. Die Prüfung wartet auf alle gleichzeitig –
    sonst würde die letzte erst nach Minuten rot."""
    stumme: list[socket.socket] = []
    kennungen = []
    for nummer in range(4):
        with LaufenderServer(notizen_mcp_server().streamable_http_app()) as server:
            integration = integration_anlegen(
                angemeldet, "mcp-server", {"url": server.url + "/mcp"}, name=f"Notizen {nummer + 1}"
            )
            port = server.port
        kennungen.append(f"integration:{integration['id']}")
        # An derselben Adresse lauscht jetzt etwas, das Verbindungen annimmt, aber nie antwortet.
        stumm = socket.socket()
        stumm.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        stumm.bind(("127.0.0.1", port))
        stumm.listen(5)
        stumme.append(stumm)
    try:
        monkeypatch.setattr(integrations_dienst, "PRUEF_SEKUNDEN", 1.0)
        start = time.monotonic()
        uebersicht = _pruefen(angemeldet)
        dauer = time.monotonic() - start
    finally:
        for stumm in stumme:
            stumm.close()
    assert [_knoten(uebersicht, kennung)["status"] for kennung in kennungen] == ["fehler"] * 4
    # Vier hängende Gegenstellen, je 1 Sekunde Geduld: nacheinander wären das 4 Sekunden.
    assert dauer < 2.5, f"die Runde hat {dauer:.1f} s gedauert"
    ausgefallen = angemeldet.get("/api/ereignisse", params={"art": "integration_ausgefallen"}).json()
    assert len(ausgefallen) == 4


@pytest.mark.anyio
async def test_offene_freigabe_macht_die_integration_gelb(
    angemeldet: TestClient, panel: LaufenderServer
) -> None:
    integration = integration_anlegen(angemeldet, "gedaechtnis")
    kennung = f"integration:{integration['id']}"
    eintrag = angemeldet.post(
        "/api/gedaechtnis", json={"text": "Mag keine Oliven", "kategorie": "vorlieben"}
    ).json()
    assert _knoten(_status(angemeldet), kennung)["status"] == "ok"

    async with mcp_client(panel.url, client_token(angemeldet)) as missa:
        aufruf = asyncio.create_task(missa.call_tool("gedaechtnis_vergessen", {"id": eintrag["id"]}))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        wartend = _knoten(_status(angemeldet), kennung)
        assert (wartend["status"], wartend["status_text"]) == (
            "warn",
            "1 Freigabe wartet auf deine Entscheidung.",
        )
        assert wartend["link"] == {"pfad": "/freigaben", "titel": "Zu den Freigaben"}
        assert _status(angemeldet)["zusammenfassung"]["warn"] == 1

        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": False})
        assert "abgelehnt" in mcp_text(await asyncio.wait_for(aufruf, timeout=5))
    assert _knoten(_status(angemeldet), kennung)["status"] == "ok"
    # Der Client, der sich verbunden hat, steht in der Übersicht – verbunden mit Missa.
    uebersicht = _status(angemeldet)
    client = next(k for k in uebersicht["knoten"] if k["art"] == "client")
    assert (client["name"], client["status"], client["status_text"]) == (
        "missa-core",
        "ok",
        "Hat sich schon verbunden.",
    )
    assert (client["id"], "missa", "verbindet") in _kanten(uebersicht)


# ====================================================================== alles andere


def _modell(admin: TestClient, name: str, **mehr: Any) -> dict:
    antwort = admin.post(
        "/api/modelle", json={"name": name, "url": "http://127.0.0.1:9/v1", "modellname": "test", **mehr}
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_modelle_rollen_zugaenge_und_regeln_haengen_richtig_zusammen(
    app: FastAPI, angemeldet: TestClient
) -> None:
    zugang = angemeldet.post(
        "/api/zugaenge", json={"name": "Modell-Key", "typ": "api_key", "wert": "sk-geheim-12345678"}
    ).json()
    ungenutzt = angemeldet.post(
        "/api/zugaenge", json={"name": "Alt", "typ": "api_key", "wert": "sk-alt-12345678"}
    ).json()
    haupt = _modell(angemeldet, "Schnelles Modell", zugang_id=zugang["id"])
    ersatz = _modell(angemeldet, "Ersatz")
    rollen = angemeldet.get("/api/modelle").json()["rollen"]
    schnell = next(rolle for rolle in rollen if rolle["kennung"] == "schnell")
    angemeldet.put(
        f"/api/rollen/{schnell['id']}",
        json={"haupt_modell_id": haupt["id"], "ersatz_modell_id": ersatz["id"]},
    )

    uebersicht = _status(angemeldet)
    kanten = _kanten(uebersicht)
    assert ("missa", "rolle:schnell", "nutzt") in kanten
    assert ("rolle:schnell", f"modell:{haupt['id']}", "haupt") in kanten
    assert ("rolle:schnell", f"modell:{ersatz['id']}", "ersatz") in kanten
    assert (f"modell:{haupt['id']}", f"zugang:{zugang['id']}", "zugang") in kanten
    assert _knoten(uebersicht, "rolle:stark")["status_text"] == "Noch kein Modell zugewiesen."
    assert (
        _knoten(uebersicht, "rolle:schnell")["status_text"] == "„Schnelles Modell“ ist noch nicht getestet."
    )
    benutzt, alt = (
        _knoten(uebersicht, f"zugang:{zugang['id']}"),
        _knoten(uebersicht, f"zugang:{ungenutzt['id']}"),
    )
    assert (benutzt["status"], benutzt["details"][0]["wert"]) == ("ok", "Schnelles Modell")
    assert (alt["status"], alt["status_text"]) == ("grau", "Wird von nichts verwendet.")
    assert "sk-geheim" not in str(uebersicht)  # Geheimnisse stehen nie in der Übersicht

    # Rollen: Hauptmodell gestört → mit funktionierendem Ersatz gelb, ohne rot.
    from missa_control.modellverwaltung.modelle import Modell

    def testergebnis(modell_id: int, ok: bool | None) -> None:
        with app.state.datenbank.sitzung() as db:
            db.get(Modell, modell_id).test_ok = ok
            db.commit()

    testergebnis(haupt["id"], True)
    assert _knoten(_status(angemeldet), "rolle:schnell")["status"] == "ok"
    testergebnis(haupt["id"], False)
    assert _knoten(_status(angemeldet), "rolle:schnell")["status"] == "fehler"
    testergebnis(ersatz["id"], True)
    gelb = _knoten(_status(angemeldet), "rolle:schnell")
    assert (gelb["status"], gelb["status_text"]) == (
        "warn",
        "„Schnelles Modell“ ist gestört – das Ersatzmodell „Ersatz“ springt ein.",
    )
    assert _knoten(_status(angemeldet), f"modell:{haupt['id']}")["status"] == "fehler"

    # Regeln: hängen an dem, was sie auslöst – sonst direkt an Missa. Ruft die Regel eine Funktion auf,
    # zeigt eine Querverbindung dorthin.
    serverlast = integration_anlegen(angemeldet, "serverlast")
    regel = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Stündlich messen",
            "ausloeser": {"art": "zeitplan", "modus": "intervall", "intervall_minuten": 60},
            "aktion": {"art": "funktion", "funktion": "serverlast_aktuell", "argumente": {}},
        },
    ).json()
    ausfall = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Serverlast weg",
            "ausloeser": {"art": "integration_ausgefallen", "integration_id": serverlast["id"]},
            "aktion": {"art": "ereignis", "nachricht": "Die Serverlast fehlt"},
            "aktiv": False,
        },
    ).json()
    uebersicht = _status(angemeldet)
    kanten = _kanten(uebersicht)
    assert ("missa", f"regel:{regel['id']}", "ausloeser") in kanten
    assert (f"regel:{regel['id']}", f"integration:{serverlast['id']}", "aktion") in kanten
    assert (f"integration:{serverlast['id']}", f"regel:{ausfall['id']}", "ausloeser") in kanten
    quer = next(k for k in uebersicht["kanten"] if k["art"] == "aktion")
    assert quer["ordnet"] is False  # zählt nicht für die automatische Anordnung
    aktiv, pausiert = (
        _knoten(uebersicht, f"regel:{regel['id']}"),
        _knoten(uebersicht, f"regel:{ausfall['id']}"),
    )
    assert (aktiv["status"], aktiv["details"][0]["wert"]) == (
        "ok",
        "Jede Stunde wird die Funktion „serverlast_aktuell“ aufgerufen.",
    )
    assert (pausiert["status"], pausiert["status_text"]) == ("grau", "Pausiert.")

    # Fehlt, worauf sich eine Regel bezieht, wird sie gelb.
    angemeldet.delete(f"/api/integrationen/{serverlast['id']}")
    uebersicht = _status(angemeldet)
    assert _knoten(uebersicht, f"regel:{regel['id']}")["status"] == "warn"
    assert all(
        kennung != f"integration:{serverlast['id']}" for kante in _kanten(uebersicht) for kennung in kante[:2]
    )
    assert sum(uebersicht["zusammenfassung"].values()) == len(uebersicht["knoten"])


def test_positionen_speichern_und_zuruecksetzen(angemeldet: TestClient) -> None:
    assert _status(angemeldet)["positionen"] == {}
    gespeichert = angemeldet.put(
        "/api/status/positionen",
        json={
            "positionen": {
                "missa": {"x": 10, "y": -20.5},
                "rolle:schnell": {"x": 300, "y": 40},
                "weg:1": {"x": 1, "y": 2},
            }
        },
    )
    assert (gespeichert.status_code, gespeichert.json()) == (200, {"gespeichert": 3})
    # Positionen von Knoten, die es nicht (mehr) gibt, kommen nicht zurück.
    assert _status(angemeldet)["positionen"] == {
        "missa": {"x": 10.0, "y": -20.5},
        "rolle:schnell": {"x": 300.0, "y": 40.0},
    }

    angemeldet.put("/api/status/positionen", json={"positionen": {"missa": {"x": 55, "y": 66}}})
    assert _status(angemeldet)["positionen"]["missa"] == {"x": 55.0, "y": 66.0}
    assert _status(angemeldet)["positionen"]["rolle:schnell"] == {"x": 300.0, "y": 40.0}  # bleibt

    for ungueltig in (
        {"positionen": []},
        {"positionen": {"missa": {"x": "links", "y": 1}}},
        {"positionen": {"missa": None}},
        {},
    ):
        assert angemeldet.put("/api/status/positionen", json=ungueltig).status_code == 422, ungueltig

    assert angemeldet.delete("/api/status/positionen").json() == {"gespeichert": 0}
    assert _status(angemeldet)["positionen"] == {}


def test_uebersicht_nur_fuer_den_besitzer(client: TestClient) -> None:
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/status/pruefen").status_code == 401
