"""Serverlast: lesend messen, 7 Tage aufzeichnen, Verlauf für Diagramme, Abfrage durch Missa."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import httpx2
import psutil
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from hilfen import Uhr
from missa_control.config import Einstellungen
from missa_control.main import alte_daten_loeschen, create_app
from missa_control.serverlast import messen as messung
from missa_control.serverlast.messen import Gpu, Messung, gpus_aus_ausgabe
from server import LaufenderServer

pytestmark = pytest.mark.anyio


def _fest(cpu: float, ram: float = 40.0, speicher: float = 55.0, gpus: list[Gpu] | None = None) -> Messung:
    return Messung(
        cpu=cpu,
        ram=ram,
        speicher=speicher,
        cpu_kerne=8,
        last=1.5,
        ram_gesamt_gb=32.0,
        ram_belegt_gb=12.8,
        speicher_gesamt_gb=500.0,
        speicher_frei_gb=225.0,
        gpus=gpus or [],
    )


def test_echte_messung_liefert_plausible_werte_auch_ohne_gpu(app: FastAPI) -> None:
    """Fertig-wenn: Ohne GPU keine Fehlermeldung, nur ausgeblendet."""
    m = app.state.serverlast.messen()
    assert 0 <= m.cpu <= 100
    assert 0 < m.ram <= 100
    assert 0 < m.speicher <= 100
    assert m.cpu_kerne >= 1
    assert m.ram_gesamt_gb > 0
    assert m.speicher_gesamt_gb > m.speicher_frei_gb > 0
    assert m.gpus == []  # hier gibt es kein nvidia-smi
    assert (m.gpu, m.gpu_speicher, m.gpu_temp) == (None, None, None)
    assert m.ansicht()["gpu_vorhanden"] is False


def test_werte_kommen_aus_dem_eingebundenen_proc_des_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Messung liest das /proc, das unter /host/proc eingebunden ist – nicht das des Containers."""
    proc = tmp_path / "host" / "proc"
    proc.mkdir(parents=True)
    sys_ordner = tmp_path / "host" / "sys"
    (sys_ordner / "class" / "thermal" / "thermal_zone0").mkdir(parents=True)
    (sys_ordner / "class" / "thermal" / "thermal_zone0" / "temp").write_text("61500\n")

    def stat(benutzt: int, leerlauf: int) -> None:
        (proc / "stat").write_text(
            f"cpu  {benutzt} 0 0 {leerlauf} 0 0 0 0 0 0\ncpu0 {benutzt} 0 0 {leerlauf} 0 0 0 0 0 0\n"
        )

    stat(1000, 1000)
    (proc / "meminfo").write_text(
        "MemTotal:       16000000 kB\nMemFree:         2000000 kB\nMemAvailable:    4000000 kB\n"
        "Buffers:          500000 kB\nCached:          1500000 kB\nSReclaimable:          0 kB\nShmem:                 0 kB\n"
        "Active:          6000000 kB\nInactive:        3000000 kB\n"
    )
    (proc / "loadavg").write_text("3.25 2.10 1.05 2/345 6789\n")
    monkeypatch.setattr(psutil, "PROCFS_PATH", "/proc")  # wird von procfs_einstellen umgestellt

    messung.procfs_einstellen(proc)
    assert str(proc) == psutil.PROCFS_PATH
    messung.messen(tmp_path, sys_ordner)  # setzt den Vergleichspunkt
    stat(1750, 1250)  # seither: 750 Einheiten Arbeit, 250 Leerlauf → 75 %
    m = messung.messen(tmp_path, sys_ordner)
    assert m.cpu == 75.0
    assert m.ram == 75.0  # 12 von 16 GB belegt
    assert m.last == 3.25
    assert m.cpu_temp == 61.5

    # Ohne eingebundenes /proc (ausserhalb von Docker) bleibt alles beim Alten.
    monkeypatch.setattr(psutil, "PROCFS_PATH", "/proc")
    messung.procfs_einstellen(tmp_path / "gibt-es-nicht")
    assert psutil.PROCFS_PATH == "/proc"
    assert messung.cpu_temperatur(tmp_path / "leer") is None or messung.cpu_temperatur(tmp_path / "leer") > 0


def test_gpu_werte_aus_nvidia_smi() -> None:
    ausgabe = (
        "NVIDIA GeForce RTX 4090, 35, 10240, 24564, 61\nTesla T4, [N/A], 512, 15360, 44\nkaputte zeile\n"
    )
    gpus = gpus_aus_ausgabe(ausgabe)
    assert [gpu.name for gpu in gpus] == ["NVIDIA GeForce RTX 4090", "Tesla T4"]
    assert gpus[1].auslastung is None  # „[N/A]“ ist kein Fehler
    m = _fest(10, gpus=gpus)
    assert m.gpu == 35
    assert m.gpu_temp == 61
    assert m.gpu_speicher == round((10240 + 512) / (24564 + 15360) * 100, 1)
    assert gpus_aus_ausgabe("") == []
    assert messung.gpus_messen() == []  # kein nvidia-smi vorhanden: leere Liste, kein Fehler


def test_aufzeichnen_verlauf_und_loeschen_nach_sieben_tagen(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    dienst = app.state.serverlast
    werte = iter([20.0, 40.0, 60.0, 80.0])
    dienst.quelle = lambda _intervall: _fest(next(werte))
    gehoert: list[dict] = []
    dienst.zuhoerer.append(gehoert.append)

    start = uhr.jetzt
    for _ in range(4):  # alle 30 Sekunden eine Messung
        dienst.aufzeichnen()
        uhr.vor(seconds=30)
    assert [w["cpu"] for w in gehoert] == [
        20.0,
        40.0,
        60.0,
        80.0,
    ]  # Zuhörer (später: Regeln) bekommen jeden Wert

    antwort = angemeldet.get("/api/serverlast", params={"zeitraum": "1h"}).json()
    assert [punkt["cpu"] for punkt in antwort["verlauf"]] == [20.0, 40.0, 60.0, 80.0]
    assert antwort["verlauf"][0]["zeit"] == start.isoformat()
    assert antwort["verlauf"][0]["gpu"] is None
    assert antwort["aktuell"]["cpu"] == 80.0
    assert antwort["aktuell"]["gpu_vorhanden"] is False
    assert antwort["intervall_sekunden"] == 0
    assert {m["kennung"] for m in antwort["messwerte"]} >= {"cpu", "ram", "speicher", "gpu"}

    # 24 Stunden: zu 5-Minuten-Mittelwerten zusammengefasst.
    tag = angemeldet.get("/api/serverlast", params={"zeitraum": "24h"}).json()["verlauf"]
    assert len(tag) == 1
    assert tag[0]["cpu"] == 50.0
    assert tag[0]["ram"] == 40.0
    assert angemeldet.get("/api/serverlast", params={"zeitraum": "ewig"}).status_code == 422

    # Nach über einer Stunde fällt alles aus dem 1-Stunden-Fenster, bleibt aber 7 Tage gespeichert.
    uhr.vor(hours=2)
    with app.state.datenbank.sitzung() as db:
        assert dienst.verlauf(db, "1h") == []
        assert len(dienst.verlauf(db, "7t")) == 1
    uhr.vor(days=6)
    alte_daten_loeschen(app)
    with app.state.datenbank.sitzung() as db:
        assert len(dienst.verlauf(db, "7t")) == 1
    uhr.vor(days=2)
    alte_daten_loeschen(app)
    from missa_control.serverlast.modelle import Messwert

    with app.state.datenbank.sitzung() as db:
        assert db.query(Messwert).count() == 0


async def test_misst_im_hintergrund_im_eingestellten_takt(einstellungen: Einstellungen) -> None:
    app = create_app(dataclasses.replace(einstellungen, mess_intervall_sekunden=0.05))
    zaehler = iter(range(1000))
    app.state.serverlast.quelle = lambda _intervall: _fest(float(next(zaehler)))
    with LaufenderServer(app):
        await asyncio.sleep(0.5)
    with app.state.datenbank.sitzung() as db:
        verlauf = app.state.serverlast.verlauf(db, "1h")
    app.state.datenbank.schliessen()
    assert len(verlauf) >= 4
    assert (
        Einstellungen(
            secret_key=einstellungen.secret_key,
            encryption_key=einstellungen.encryption_key,
            daten_ordner=Path("x"),
        ).mess_intervall_sekunden
        == 30.0
    )


async def test_missa_fragt_die_aktuelle_last_ueber_das_gateway_ab(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer
) -> None:
    """Fertig-wenn: Missa kann die aktuelle Last über das Gateway abfragen."""
    gpu = Gpu(
        name="RTX 4090", auslastung=35, speicher_belegt_mb=6000, speicher_gesamt_mb=24000, temperatur=61
    )
    app.state.serverlast.quelle = lambda _intervall: _fest(42.0, gpus=[gpu])

    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "serverlast")
    assert karte["felder"] == []  # nichts einzustellen
    # Ein Klick genügt: aktivieren ohne Formular.
    angelegt = angemeldet.post("/api/integrationen", json={"manifest_id": "serverlast", "konfig": {}})
    assert angelegt.status_code == 201, angelegt.text
    assert angelegt.json()["status_meldung"] == "Messung klappt: CPU 42 %, Arbeitsspeicher 40 %, GPU 35 %"
    funktion = angelegt.json()["funktionen"][0]
    assert (funktion["gateway_name"], funktion["recht"], funktion["schreibend"]) == (
        "serverlast_aktuell",
        "erlaubt",
        False,
    )
    assert (
        angemeldet.post("/api/integrationen", json={"manifest_id": "serverlast", "konfig": {}}).status_code
        == 409
    )

    token = angemeldet.post("/api/clients", json={"name": "missa-core"}).json()["token"]
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=20) as http,
        Client(streamable_http_client(panel.url + "/mcp", http_client=http)) as client,
    ):
        assert [w.name for w in (await client.list_tools()).tools] == ["serverlast_aktuell"]
        ergebnis = await client.call_tool("serverlast_aktuell", {})
    assert ergebnis.is_error is False
    daten = json.loads(ergebnis.content[0].text)
    assert daten["cpu_prozent"] == 42.0
    assert daten["arbeitsspeicher_prozent"] == 40.0
    assert daten["speicherplatz_frei_gb"] == 225.0
    assert daten["gpus"][0]["name"] == "RTX 4090"
    assert daten["zusammenfassung"] == (
        "CPU 42 % ausgelastet (8 Kerne); Arbeitsspeicher 40 % belegt (12.8 von 32.0 GB); "
        "Speicherplatz 55 % belegt (225 GB frei); GPU 35 % ausgelastet, GPU-Speicher 25 % belegt."
    )

    # Ohne GPU fehlt der GPU-Teil einfach.
    app.state.serverlast.quelle = lambda _intervall: _fest(42.0)
    ohne = app.state.serverlast.fuer_missa()
    assert "gpus" not in ohne
    assert "GPU" not in ohne["zusammenfassung"]
