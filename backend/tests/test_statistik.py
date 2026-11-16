"""Nutzungs-Statistik: Aufrufe, Fehlerquote und Dauer pro Integration und Funktion – aus dem Protokoll."""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import integration_anlegen
from missa_control import zeit
from missa_control.gateway.modelle import Aufruf


def _eintragen(
    app: FastAPI, funktion: str, ok: bool, dauer_ms: int, vor_tagen: float = 0, **mehr: str
) -> None:
    """Ein Eintrag im Protokoll – auf Wunsch so, als wäre er vor einigen Tagen entstanden."""
    with app.state.datenbank.sitzung() as db:
        db.add(
            Aufruf(
                zeit=zeit.jetzt() - timedelta(days=vor_tagen),
                quelle=mehr.pop("quelle", "gateway"),
                client_name="missa-core",
                integration_name=mehr.pop("integration", "Serverlast"),
                funktion=funktion,
                ok=ok,
                dauer_ms=dauer_ms,
                fehler=mehr.pop("fehler", ""),
                freigabe=mehr.pop("freigabe", "ohne"),
            )
        )
        db.commit()


def _statistik(client: TestClient, zeitraum: str) -> dict:
    antwort = client.get("/api/statistik", params={"zeitraum": zeitraum})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_zahlen_pro_funktion_und_zeitraum(app: FastAPI, angemeldet: TestClient) -> None:
    # vor 20 Tagen: einer; vor 3 Tagen: zwei; heute: vier (einer davon fehlgeschlagen, einer abgelehnt)
    _eintragen(app, "serverlast_aktuell", True, 100, vor_tagen=20)
    _eintragen(app, "serverlast_aktuell", True, 200, vor_tagen=3)
    _eintragen(app, "kalender_eintragen", True, 50, vor_tagen=3, integration="Kalender", freigabe="erlaubt")
    _eintragen(app, "serverlast_aktuell", True, 30)
    _eintragen(app, "serverlast_aktuell", False, 90, fehler="Zeitüberschreitung")
    _eintragen(app, "serverlast_aktuell", True, 60, quelle="panel")
    _eintragen(app, "kalender_eintragen", False, 10, integration="Kalender", freigabe="abgelehnt")

    tag = _statistik(angemeldet, "24h")
    zeile = next(f for f in tag["funktionen"] if f["funktion"] == "serverlast_aktuell")
    assert (zeile["aufrufe"], zeile["fehler"], zeile["von_missa"]) == (3, 1, 2)
    assert zeile["fehlerquote"] == round(1 / 3, 4)
    assert (zeile["dauer_mittel_ms"], zeile["dauer_max_ms"]) == (60, 90)
    assert zeile["letzter_aufruf"].startswith("2026-01-15T12:00")
    kalender = next(f for f in tag["funktionen"] if f["funktion"] == "kalender_eintragen")
    assert kalender["freigaben"] == {"erlaubt": 0, "abgelehnt": 1, "abgelaufen": 0}
    assert tag["gesamt"] == {"aufrufe": 4, "fehler": 2, "fehlerquote": 0.5, "funktionen": 2}

    woche = _statistik(angemeldet, "7d")
    assert next(f for f in woche["funktionen"] if f["funktion"] == "serverlast_aktuell")["aufrufe"] == 4
    assert next(f for f in woche["funktionen"] if f["funktion"] == "kalender_eintragen")["freigaben"] == {
        "erlaubt": 1,
        "abgelehnt": 1,
        "abgelaufen": 0,
    }
    assert len(woche["pro_tag"]) == 8  # 7 Tage zurück bis heute, auch Tage ohne Aufruf
    assert sum(t["aufrufe"] for t in woche["pro_tag"]) == 6

    monat = _statistik(angemeldet, "30d")
    assert monat["gesamt"]["aufrufe"] == 7
    assert monat["funktionen"][0]["funktion"] == "serverlast_aktuell"  # häufigste zuerst

    assert angemeldet.get("/api/statistik", params={"zeitraum": "1j"}).status_code == 422


def test_stimmt_mit_dem_protokoll_ueberein(app: FastAPI, angemeldet: TestClient) -> None:
    for nummer in range(10):
        _eintragen(app, "serverlast_aktuell", nummer % 4 != 0, 10 * nummer)
    protokoll = [
        e
        for e in angemeldet.get("/api/protokoll", params={"limit": 100}).json()["eintraege"]
        if e["funktion"] == "serverlast_aktuell"
    ]
    zeile = _statistik(angemeldet, "24h")["funktionen"][0]
    fehler = sum(1 for e in protokoll if not e["ok"])
    dauern = [e["dauer_ms"] for e in protokoll]
    assert zeile["aufrufe"] == len(protokoll) == 10
    assert zeile["fehlerquote"] == round(fehler / len(protokoll), 4) == 0.3
    assert zeile["dauer_mittel_ms"] == round(sum(dauern) / len(dauern))
    assert zeile["dauer_max_ms"] == max(dauern)


def test_nie_benutzt_listet_aktive_funktionen_ohne_aufruf(app: FastAPI, angemeldet: TestClient) -> None:
    integration = integration_anlegen(angemeldet, "gedaechtnis")
    namen = {f["gateway_name"] for f in integration["funktionen"] if f["recht"] != "gesperrt"}
    assert len(namen) >= 2
    benutzt = sorted(namen)[0]
    _eintragen(app, benutzt, True, 5, integration=integration["name"])

    nie = _statistik(angemeldet, "7d")["nie_benutzt"]
    assert {e["funktion"] for e in nie} == namen - {benutzt}
    assert all(e["integration_id"] == integration["id"] for e in nie)

    # Deaktivierte Integrationen sind nicht „nie benutzt“ – Missa sieht sie ja gar nicht
    angemeldet.put(f"/api/integrationen/{integration['id']}", json={"aktiv": False})
    assert _statistik(angemeldet, "7d")["nie_benutzt"] == []
