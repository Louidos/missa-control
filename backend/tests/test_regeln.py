"""Regeln und Alarme: Auslöser, Bedingung, Aktion, Ruhezeit, Verlauf – und Missa legt selbst Regeln an."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr, anmelden, client_token, integration_anlegen, mcp_client, mcp_text, warte_auf
from missa_control.config import Einstellungen, EinstellungsFehler
from missa_control.main import alte_daten_loeschen, create_app
from missa_control.serverlast.messen import Messung
from server import LaufenderServer

pytestmark = pytest.mark.anyio

MANIFEST = """
id: lampe
name: Lampe
beschreibung: Test-Integration für Regeln
art: python
standardrechte:
  tresor_oeffnen: gesperrt
"""

MAIN = """
from missa_control.sdk import Fehler, Kontext, funktion


@funktion(beschreibung="Schaltet die Lampe.")
def schalten(kontext: Kontext, an: bool, farbe: str = "weiss") -> str:
    if farbe == "kaputt":
        raise Fehler("Die Lampe antwortet nicht.", "Steckt der Stecker?")
    kontext.zustand["an"] = an
    kontext.zustand["schaltungen"] = kontext.zustand.get("schaltungen", 0) + 1
    return f"Lampe ist {'an' if an else 'aus'} ({farbe})"


@funktion(beschreibung="Öffnet den Tresor.")
def tresor_oeffnen(kontext: Kontext) -> str:
    return "offen"
"""


@pytest.fixture
def einstellungen(einstellungen: Einstellungen) -> Einstellungen:
    ordner = einstellungen.eigene_integrationen_ordner / "lampe"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(MANIFEST, encoding="utf-8")
    (ordner / "main.py").write_text(MAIN, encoding="utf-8")
    return einstellungen


def _messung(cpu: float, ram: float = 40.0) -> Messung:
    return Messung(cpu=cpu, ram=ram, speicher=55.0, cpu_kerne=8, last=1.0)


def _messen(app: FastAPI, cpu: float, ram: float = 40.0) -> None:
    """Eine Messung der Serverlast mit Test-Werten – und warten, bis die Regeln sie verarbeitet haben."""
    app.state.serverlast.quelle = lambda _intervall: _messung(cpu, ram)
    app.state.serverlast.aufzeichnen()
    assert app.state.regeln.warten()


def _regel(admin: TestClient, **angaben: Any) -> dict:
    daten = {
        "name": "CPU-Alarm",
        "ausloeser": {"art": "messwert", "messwert": "cpu", "schwelle": 90, "dauer_minuten": 5},
        "aktion": {"art": "ereignis", "nachricht": "Die CPU glüht: {wert} %", "dringlichkeit": "hoch"},
        **angaben,
    }
    antwort = admin.post("/api/regeln", json=daten)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _regel_ereignisse(admin: TestClient) -> list[dict]:
    return [e for e in reversed(admin.get("/api/ereignisse").json()) if e["art"] == "regel"]


def _verlauf(admin: TestClient, **filter: Any) -> list[dict]:
    return admin.get("/api/regeln/verlauf", params=filter).json()["eintraege"]


# ====================================================================== Messwert-Schwelle und Ruhezeit


def test_schwellwert_regel_loest_bei_test_werten_aus_und_erzeugt_ein_ereignis(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    """Fertig-wenn: Eine Schwellwert-Regel löst bei Test-Werten aus und erzeugt ein Ereignis."""
    regel = _regel(angemeldet)
    assert regel["satz"] == (
        "Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann bekommt Missa die Nachricht "
        "„Die CPU glüht: {wert} %“ (Dringlichkeit: hoch). Danach 30 Minuten Ruhe."
    )
    assert (regel["aktiv"], regel["quelle"], regel["ruhezeit_minuten"]) == (True, "manuell", 30)

    _messen(app, 95)  # über der Schwelle – aber noch keine 5 Minuten
    uhr.vor(minutes=3)
    _messen(app, 96)
    assert _regel_ereignisse(angemeldet) == []
    uhr.vor(seconds=30)
    _messen(app, 40)  # kurz darunter: die Mindestdauer beginnt von vorn
    uhr.vor(seconds=30)
    _messen(app, 95)
    uhr.vor(minutes=4, seconds=30)
    _messen(app, 99)
    assert _regel_ereignisse(angemeldet) == []
    uhr.vor(seconds=30)
    _messen(app, 97.4)  # jetzt 5 Minuten am Stück darüber

    ereignisse = _regel_ereignisse(angemeldet)
    assert len(ereignisse) == 1
    ereignis = ereignisse[0]
    assert ereignis["titel"] == "Regel „CPU-Alarm“ ausgelöst"
    assert ereignis["nachricht"] == "Die CPU glüht: 97,4 %"  # {wert} wurde eingesetzt
    assert (ereignis["dringlichkeit"], ereignis["quelle"]) == ("hoch", "Regeln")
    assert ereignis["daten"]["regel_id"] == regel["id"]
    assert ereignis["daten"]["wert"] == 97.4

    # Missa holt das Ereignis mit ihrem Client-Token ab.
    token = client_token(angemeldet)
    abgeholt = angemeldet.get("/api/events", headers={"Authorization": f"Bearer {token}"}).json()
    assert [e["nachricht"] for e in abgeholt["ereignisse"] if e["art"] == "regel"] == [
        "Die CPU glüht: 97,4 %"
    ]

    verlauf = _verlauf(angemeldet)
    assert len(verlauf) == 1
    assert verlauf[0]["regel"] == "CPU-Alarm"
    assert verlauf[0]["anlass"] == "CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)"
    assert (verlauf[0]["ergebnis"], verlauf[0]["ergebnis_name"], verlauf[0]["test"]) == (
        "ok",
        "ausgeführt",
        False,
    )
    aktuell = angemeldet.get("/api/regeln").json()["regeln"][0]
    assert aktuell["zuletzt_ausgeloest"] == uhr.jetzt.isoformat()


def test_ruhezeit_verhindert_wiederholte_ausloesung(app: FastAPI, angemeldet: TestClient, uhr: Uhr) -> None:
    """Fertig-wenn: Ruhezeit verhindert wiederholte Auslösung."""
    _regel(
        angemeldet,
        ausloeser={"art": "messwert", "messwert": "cpu", "schwelle": 90},  # ohne Mindestdauer
        ruhezeit_minuten=30,
    )
    _messen(app, 95)
    assert len(_regel_ereignisse(angemeldet)) == 1
    for _ in range(58):  # 29 Minuten lang alle 30 Sekunden weiter über der Schwelle
        uhr.vor(seconds=30)
        _messen(app, 96)
    assert len(_regel_ereignisse(angemeldet)) == 1  # Ruhe
    assert len(_verlauf(angemeldet)) == 1  # und kein Eintrag pro Messung im Verlauf

    uhr.vor(minutes=1, seconds=1)
    _messen(app, 97)  # Ruhezeit vorbei, Wert immer noch zu hoch: Erinnerung
    assert len(_regel_ereignisse(angemeldet)) == 2

    # „unter“ funktioniert genauso; ein fehlender Wert (z. B. keine GPU) löst nie aus.
    _regel(
        angemeldet,
        name="Wenig Arbeitsspeicher belegt",
        ausloeser={"art": "messwert", "messwert": "ram", "vergleich": "unter", "schwelle": 10},
        aktion={"art": "ereignis", "nachricht": "RAM bei {wert} %"},
        ruhezeit_minuten=0,
    )
    _regel(
        angemeldet,
        name="GPU",
        ausloeser={"art": "messwert", "messwert": "gpu", "vergleich": "unter", "schwelle": 50},
        aktion={"art": "ereignis", "nachricht": "GPU"},
    )
    _messen(app, 10, ram=5)
    _messen(app, 10, ram=5)  # ohne Ruhezeit: jedes Mal
    nachrichten = [e["nachricht"] for e in _regel_ereignisse(angemeldet)]
    assert nachrichten.count("RAM bei 5 %") == 2
    assert "GPU" not in nachrichten


def test_pausierte_regel_loest_nicht_aus_und_zaehlt_danach_neu(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    regel = _regel(angemeldet)
    _messen(app, 95)
    uhr.vor(minutes=4)
    pausiert = angemeldet.patch(f"/api/regeln/{regel['id']}", json={"aktiv": False})
    assert pausiert.json()["aktiv"] is False
    uhr.vor(minutes=2)
    _messen(app, 95)
    assert _regel_ereignisse(angemeldet) == []  # pausiert
    angemeldet.patch(f"/api/regeln/{regel['id']}", json={"aktiv": True})
    _messen(app, 95)
    assert _regel_ereignisse(angemeldet) == []  # wieder aktiv: die 5 Minuten zählen neu
    uhr.vor(minutes=5)
    _messen(app, 95)
    assert len(_regel_ereignisse(angemeldet)) == 1


# ====================================================================== Ereignisse als Auslöser, Bedingung


def test_integration_ausgefallen_loest_aus_und_ruhezeit_steht_im_verlauf(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    lampe = integration_anlegen(angemeldet, "lampe")
    alle = _regel(
        angemeldet,
        name="Ausfall melden",
        ausloeser={"art": "integration_ausgefallen"},
        aktion={"art": "ereignis", "nachricht": "Achtung: {anlass}", "dringlichkeit": "dringend"},
        ruhezeit_minuten=10,
    )
    andere = _regel(
        angemeldet,
        name="Nur die andere",
        ausloeser={"art": "integration_ausgefallen", "integration_id": lampe["id"]},
        aktion={"art": "ereignis", "nachricht": "Lampe weg"},
    )
    assert alle["satz"].startswith("Wenn eine Integration ausfällt, dann bekommt Missa")
    assert andere["satz"].startswith("Wenn die Integration „Lampe“ ausfällt, dann")

    def ausfall(integration_id: int, name: str) -> None:
        app.state.ereignisse.melden(
            "integration_ausgefallen",
            f"Integration „{name}“ ist ausgefallen",
            "nicht erreichbar",
            daten={"integration_id": integration_id},
        )
        assert app.state.regeln.warten()

    ausfall(999, "Kalender")  # eine andere Integration: nur die allgemeine Regel
    assert [e["nachricht"] for e in _regel_ereignisse(angemeldet)] == [
        "Achtung: Integration „Kalender“ ist ausgefallen"
    ]
    uhr.vor(minutes=5)
    ausfall(lampe["id"], "Lampe")  # jetzt beide – aber die allgemeine ist noch in der Ruhezeit
    assert [e["nachricht"] for e in _regel_ereignisse(angemeldet)][-1] == "Lampe weg"
    verlauf = _verlauf(angemeldet, regel_id=alle["id"])
    assert [(v["ergebnis"], v["anlass"]) for v in verlauf] == [
        ("ruhezeit", "Integration „Lampe“ ist ausgefallen"),
        ("ok", "Integration „Kalender“ ist ausgefallen"),
    ]
    assert verlauf[0]["ergebnis_name"] == "in der Ruhezeit übersprungen"
    assert verlauf[0]["meldung"] == "Nicht ausgeführt: Ruhezeit bis 13:10 Uhr."  # Ortszeit (Europe/Zurich)
    assert angemeldet.get("/api/regeln/verlauf").json()["anzahl"] == 3


def test_bedingung_wochentage_und_zeitfenster(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr, geheimnis: str
) -> None:
    """Die Uhr steht auf Donnerstag, 15.01.2026, 13:00 Uhr Ortszeit (12:00 UTC)."""
    nachts = _regel(
        angemeldet,
        name="Nur nachts",
        ausloeser={"art": "webhook"},
        bedingung={"von": "22:00", "bis": "06:00"},
        aktion={"art": "ereignis", "nachricht": "nachts"},
        ruhezeit_minuten=0,
    )
    wochenende = _regel(
        angemeldet,
        name="Nur am Wochenende",
        ausloeser={"art": "webhook"},
        bedingung={"tage": ["sa", "so"], "von": "08:00", "bis": "20:00"},
        aktion={"art": "ereignis", "nachricht": "wochenende"},
        ruhezeit_minuten=0,
    )
    assert "(nur zwischen 22:00 und 06:00 Uhr)" in nachts["satz"]
    assert "(nur am Wochenende zwischen 08:00 und 20:00 Uhr)" in wochenende["satz"]
    assert wochenende["bedingung"] == {"tage": [5, 6], "von": "08:00", "bis": "20:00"}

    def webhook() -> list[str]:
        anmelden(angemeldet, uhr, geheimnis)  # die Sitzung läuft nach 12 Stunden ab
        vorher = len(_regel_ereignisse(angemeldet))
        app.state.ereignisse.melden(
            "webhook", "Webhook „Test“ hat etwas empfangen", daten={"integration_id": 1}
        )
        assert app.state.regeln.warten()
        return [e["nachricht"] for e in _regel_ereignisse(angemeldet)][vorher:]

    assert webhook() == []  # Donnerstag 13:00
    assert _verlauf(angemeldet, regel_id=nachts["id"])[0]["meldung"] == (
        "Nicht ausgeführt: gilt nur zwischen 22:00 und 06:00 Uhr."
    )
    uhr.vor(hours=10)  # Donnerstag 23:00
    assert webhook() == ["nachts"]
    uhr.vor(hours=6)  # Freitag 05:00 – das Fenster reicht über Mitternacht
    assert webhook() == ["nachts"]
    uhr.vor(hours=29)  # Samstag 10:00
    assert webhook() == ["wochenende"]
    uhr.vor(hours=11)  # Samstag 21:00 – richtiger Tag, falsche Zeit
    assert webhook() == []
    uhr.vor(hours=37)  # Montag 10:00
    assert webhook() == []


# ====================================================================== Zeitplan


def test_zeitplan_uhrzeit_und_intervall(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr, geheimnis: str
) -> None:
    regeln = app.state.regeln

    def faellig() -> list[str]:
        anmelden(angemeldet, uhr, geheimnis)  # die Sitzung läuft nach 12 Stunden ab
        vorher = len(_regel_ereignisse(angemeldet))
        regeln.zeitplan_pruefen()
        assert regeln.warten()
        return [e["nachricht"] for e in _regel_ereignisse(angemeldet)][vorher:]

    morgens = _regel(
        angemeldet,
        name="Guten Morgen",
        ausloeser={"art": "zeitplan", "uhrzeit": "7:30"},
        bedingung={"tage": ["mo", "di", "mi", "do", "fr"]},
        aktion={"art": "ereignis", "nachricht": "Guten Morgen"},
    )
    assert morgens["satz"] == "Montags bis freitags um 07:30 Uhr bekommt Missa die Nachricht „Guten Morgen“."
    assert morgens["ausloeser"] == {"art": "zeitplan", "modus": "uhrzeit", "uhrzeit": "07:30"}
    # Donnerstag 13:00 Ortszeit → nächste Ausführung Freitag 07:30 Ortszeit = 06:30 UTC
    assert morgens["naechste_ausfuehrung"] == datetime(2026, 1, 16, 6, 30, tzinfo=UTC).isoformat()

    takt = _regel(
        angemeldet,
        name="Takt",
        ausloeser={"art": "zeitplan", "intervall_minuten": 15},
        aktion={"art": "ereignis", "nachricht": "tick"},
        ruhezeit_minuten=600,  # spielt beim Zeitplan keine Rolle
    )
    assert takt["satz"] == "Alle 15 Minuten bekommt Missa die Nachricht „tick“."

    assert faellig() == []
    uhr.vor(minutes=14)
    assert faellig() == []
    uhr.vor(minutes=1)
    assert faellig() == ["tick"]
    uhr.vor(minutes=15)
    assert faellig() == ["tick"]  # die Ruhezeit bremst den Zeitplan nicht
    assert _verlauf(angemeldet, regel_id=takt["id"])[0]["anlass"] == "Zeitplan (13:30 Uhr)"

    angemeldet.delete(f"/api/regeln/{takt['id']}")
    uhr.jetzt = datetime(2026, 1, 16, 6, 29, tzinfo=UTC)
    assert faellig() == []
    uhr.vor(minutes=1)
    assert faellig() == ["Guten Morgen"]  # Freitag 07:30
    assert faellig() == []  # nicht doppelt
    uhr.vor(days=1)
    assert faellig() == []  # Samstag: Zeitpunkt erreicht, aber die Bedingung passt nicht – still übersprungen
    assert [v["ergebnis"] for v in _verlauf(angemeldet, regel_id=morgens["id"])] == ["ok"]
    uhr.vor(days=2)
    assert faellig() == ["Guten Morgen"]  # Montag


def test_zeitplan_holt_nach_einem_neustart_nichts_nach(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    _regel(
        angemeldet,
        name="Mittag",
        ausloeser={"art": "zeitplan", "uhrzeit": "14:00"},
        aktion={"art": "ereignis", "nachricht": "Mittag"},
    )
    uhr.vor(hours=5)  # das Panel war „aus“, 14:00 Uhr ist vorbei
    neu = create_app(app.state.einstellungen)
    try:
        neu.state.regeln.zeitplan_pruefen()
        with neu.state.datenbank.sitzung() as db:
            regel = neu.state.regeln.uebersicht(db)["regeln"][0]
        assert regel["naechste_ausfuehrung"] == datetime(2026, 1, 16, 13, 0, tzinfo=UTC).isoformat()
        assert neu.state.regeln._anstehend == type(neu.state.regeln._anstehend)()  # nichts eingereiht
    finally:
        neu.state.datenbank.schliessen()


async def test_hintergrundaufgabe_prueft_den_zeitplan_von_selbst(
    einstellungen: Einstellungen, uhr: Uhr
) -> None:
    from hilfen import einrichten

    app = create_app(dataclasses.replace(einstellungen, regel_takt_sekunden=0.05))
    try:
        with TestClient(app) as admin:
            einrichten(admin, uhr)
            _regel(
                admin,
                name="Takt",
                ausloeser={"art": "zeitplan", "intervall_minuten": 1},
                aktion={"art": "ereignis", "nachricht": "tick"},
            )
            await asyncio.sleep(0.2)
            assert _regel_ereignisse(admin) == []
            uhr.vor(minutes=1)
            await warte_auf(lambda: _regel_ereignisse(admin))
    finally:
        app.state.datenbank.schliessen()


# ====================================================================== Aktion: Funktion aufrufen, testen


def test_regel_ruft_funktion_auf_ohne_freigabe_und_steht_im_protokoll(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr
) -> None:
    lampe = integration_anlegen(angemeldet, "lampe")
    assert {f["name"]: f["recht"] for f in lampe["funktionen"]} == {
        "schalten": "nachfragen",
        "tresor_oeffnen": "gesperrt",
    }
    optionen = angemeldet.get("/api/regeln").json()["optionen"]
    assert [f["name"] for f in optionen["funktionen"]] == ["lampe_schalten"]  # gesperrte fehlen
    assert optionen["funktionen"][0]["parameter"]["required"] == ["an"]

    regel = _regel(
        angemeldet,
        name="Licht bei Last",
        ausloeser={"art": "messwert", "messwert": "cpu", "schwelle": 90},
        aktion={"art": "funktion", "funktion": "lampe_schalten", "argumente": {"an": True, "farbe": "rot"}},
    )
    assert regel["satz"] == (
        "Wenn die CPU-Auslastung über 90 % liegt, dann wird die Funktion „lampe_schalten“ aufgerufen "
        "(an = ja, farbe = rot). Danach 30 Minuten Ruhe."
    )
    _messen(app, 95)

    with app.state.datenbank.sitzung() as db:
        zustand = app.state.integrationen.holen(db, lampe["id"]).zustand
    assert zustand == {"an": True, "schaltungen": 1}  # ausgeführt, ohne dass jemand gefragt wurde
    assert angemeldet.get("/api/freigaben").json()["offen"] == []
    verlauf = _verlauf(angemeldet)
    assert (verlauf[0]["ergebnis"], verlauf[0]["meldung"]) == (
        "ok",
        "„lampe_schalten“ aufgerufen. Antwort: Lampe ist an (rot)",
    )
    eintrag = angemeldet.get("/api/protokoll").json()["eintraege"][0]
    assert (eintrag["quelle"], eintrag["client"], eintrag["funktion"], eintrag["ok"]) == (
        "regel",
        "Regel „Licht bei Last“",
        "lampe_schalten",
        True,
    )
    assert _regel_ereignisse(angemeldet) == []  # nur die Funktion, kein Ereignis

    # Fehler der Funktion stehen im Verlauf – und auch ein Fehlschlag zählt für die Ruhezeit.
    angemeldet.put(
        f"/api/regeln/{regel['id']}",
        json={
            **{k: regel[k] for k in ("name", "ausloeser", "bedingung")},
            "aktion": {
                "art": "funktion",
                "funktion": "lampe_schalten",
                "argumente": {"an": True, "farbe": "kaputt"},
            },
        },
    )
    uhr.vor(minutes=31)
    _messen(app, 95)
    uhr.vor(seconds=30)
    _messen(app, 95)
    verlauf = _verlauf(angemeldet)
    assert len(verlauf) == 2
    assert (verlauf[0]["ergebnis"], verlauf[0]["ergebnis_name"]) == ("fehler", "fehlgeschlagen")
    assert verlauf[0]["meldung"] == "Die Lampe antwortet nicht. Hinweis: Steckt der Stecker?"


def test_gesperrte_und_entfernte_funktionen(app: FastAPI, angemeldet: TestClient, uhr: Uhr) -> None:
    lampe = integration_anlegen(angemeldet, "lampe")
    gesperrt = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Tresor",
            "ausloeser": {"art": "webhook"},
            "aktion": {"art": "funktion", "funktion": "lampe_tresor_oeffnen"},
        },
    )
    assert gesperrt.status_code == 422
    assert (
        gesperrt.json()["meldung"]
        == "Die Funktion „lampe_tresor_oeffnen“ gibt es nicht oder sie ist gesperrt."
    )
    assert "lampe_schalten" in gesperrt.json()["hinweis"]
    ohne_parameter = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Licht",
            "ausloeser": {"art": "webhook"},
            "aktion": {"art": "funktion", "funktion": "lampe_schalten"},
        },
    )
    assert ohne_parameter.json()["meldung"] == "Für „lampe_schalten“ fehlt der Parameter „an“."

    regel = _regel(
        angemeldet,
        name="Licht",
        ausloeser={"art": "messwert", "messwert": "cpu", "schwelle": 90},
        aktion={"art": "funktion", "funktion": "lampe_schalten", "argumente": {"an": False}},
    )
    assert regel["problem"] is None
    vorschau = angemeldet.post(
        "/api/regeln/satz", json={k: regel[k] for k in ("name", "ausloeser", "bedingung", "aktion")}
    )
    assert vorschau.json() == {"ok": True, "satz": regel["satz"]}
    # Die Integration wird entfernt: die Regel bleibt, zeigt aber, was nicht stimmt.
    angemeldet.delete(f"/api/integrationen/{lampe['id']}")
    kaputt = angemeldet.get("/api/regeln").json()["regeln"][0]
    assert kaputt["problem"] == "Die Funktion „lampe_schalten“ gibt es nicht oder sie ist gesperrt."
    _messen(app, 95)
    verlauf = _verlauf(angemeldet)
    assert verlauf[0]["ergebnis"] == "fehler"
    assert verlauf[0]["meldung"].startswith(
        "Die Funktion „lampe_schalten“ gibt es nicht (mehr) oder sie ist gesperrt."
    )


def test_jetzt_testen_fuehrt_die_aktion_sofort_aus(app: FastAPI, angemeldet: TestClient, uhr: Uhr) -> None:
    regel = _regel(angemeldet, bedingung={"tage": ["so"]})  # heute (Donnerstag) würde sie nicht auslösen
    antwort = angemeldet.post(f"/api/regeln/{regel['id']}/testen")
    assert antwort.status_code == 200
    assert antwort.json() == {"ok": True, "meldung": "Ereignis an Missa gesendet."}
    ereignis = _regel_ereignisse(angemeldet)[0]
    assert ereignis["titel"] == "Regel „CPU-Alarm“ ausgelöst (Test)"
    assert ereignis["nachricht"] == "Die CPU glüht: ? %"  # im Test gibt es keinen Messwert
    assert ereignis["daten"]["test"] is True
    verlauf = _verlauf(angemeldet)
    assert (verlauf[0]["anlass"], verlauf[0]["test"], verlauf[0]["ergebnis"]) == ("Test im Panel", True, "ok")
    # Der Test startet keine Ruhezeit.
    assert angemeldet.get("/api/regeln").json()["regeln"][0]["zuletzt_ausgeloest"] is None
    assert angemeldet.post("/api/regeln/999/testen").status_code == 404

    lampe = integration_anlegen(angemeldet, "lampe")
    licht = _regel(
        angemeldet,
        name="Licht",
        ausloeser={"art": "webhook"},
        aktion={
            "art": "funktion",
            "funktion": "lampe_schalten",
            "argumente": {"an": True, "farbe": "kaputt"},
        },
    )
    fehlschlag = angemeldet.post(f"/api/regeln/{licht['id']}/testen").json()
    assert fehlschlag == {"ok": False, "meldung": "Die Lampe antwortet nicht. Hinweis: Steckt der Stecker?"}
    assert lampe["id"]


# ====================================================================== verwalten und prüfen


def test_anlegen_aendern_loeschen_und_optionen(app: FastAPI, angemeldet: TestClient, uhr: Uhr) -> None:
    leer = angemeldet.get("/api/regeln").json()
    assert leer["regeln"] == []
    optionen = leer["optionen"]
    assert [a["wert"] for a in optionen["ausloeser"]] == [
        "zeitplan",
        "messwert",
        "geraet",
        "webhook",
        "integration_ausgefallen",
    ]
    assert [a["wert"] for a in optionen["aktionen"]] == ["ereignis", "funktion"]
    assert {m["kennung"] for m in optionen["messwerte"]} >= {"cpu", "ram", "speicher", "gpu"}
    assert optionen["zeitzone"] == "Europe/Zurich"
    assert optionen["standard_ruhezeit"] == 30
    assert optionen["dringlichkeiten"] == ["niedrig", "normal", "hoch", "dringend"]

    regel = _regel(angemeldet)
    uhr.vor(minutes=10)
    geaendert = angemeldet.put(
        f"/api/regeln/{regel['id']}",
        json={
            "name": "  RAM-Alarm ",
            "ausloeser": {"art": "messwert", "messwert": "ram", "vergleich": "über", "schwelle": "85,5"},
            "aktion": {"art": "ereignis", "nachricht": "Arbeitsspeicher wird knapp"},
            "ruhezeit_minuten": 120,
        },
    )
    assert geaendert.status_code == 200, geaendert.text
    daten = geaendert.json()
    assert daten["name"] == "RAM-Alarm"
    assert daten["ausloeser"] == {
        "art": "messwert",
        "messwert": "ram",
        "vergleich": "ueber",
        "schwelle": 85.5,
        "dauer_minuten": 0,
    }
    assert daten["satz"] == (
        "Wenn die Auslastung des Arbeitsspeichers über 85,5 % liegt, dann bekommt Missa die Nachricht "
        "„Arbeitsspeicher wird knapp“. Danach 2 Stunden Ruhe."
    )
    assert daten["geaendert"] == uhr.jetzt.isoformat()
    assert daten["erstellt"] == regel["erstellt"]

    # Mit dem Löschen der Regel verschwindet auch ihr Verlauf.
    _messen(app, 10, ram=95)
    assert len(_verlauf(angemeldet)) == 1
    assert angemeldet.delete(f"/api/regeln/{regel['id']}").status_code == 204
    assert angemeldet.get("/api/regeln").json()["regeln"] == []
    assert _verlauf(angemeldet) == []
    assert angemeldet.delete(f"/api/regeln/{regel['id']}").status_code == 404
    assert angemeldet.put(f"/api/regeln/{regel['id']}", json={}).status_code == 404
    assert angemeldet.patch(f"/api/regeln/{regel['id']}", json={"aktiv": False}).status_code == 404


@pytest.mark.parametrize(
    ("aenderung", "meldung"),
    [
        ({"name": ""}, "Bitte der Regel einen Namen geben."),
        ({"name": "x" * 81}, "Der Name ist zu lang (höchstens 80 Zeichen)."),
        ({"ausloeser": {"art": "mondphase"}}, "Bitte einen Auslöser wählen."),
        ({"ausloeser": {"art": "zeitplan", "uhrzeit": "25:00"}}, "„Uhrzeit“ ist keine gültige Uhrzeit."),
        ({"ausloeser": {"art": "zeitplan"}}, "„Uhrzeit“ ist keine gültige Uhrzeit."),
        (
            {"ausloeser": {"art": "zeitplan", "intervall_minuten": 0, "modus": "intervall"}},
            "„Intervall“ muss zwischen 1 und 10080 liegen.",
        ),
        (
            {"ausloeser": {"art": "messwert", "messwert": "luft", "schwelle": 1}},
            "Den Messwert „luft“ gibt es nicht.",
        ),
        ({"ausloeser": {"art": "messwert", "messwert": "cpu"}}, "Bitte eine Schwelle angeben."),
        (
            {"ausloeser": {"art": "messwert", "messwert": "cpu", "schwelle": "viel"}},
            "„Schwelle“ muss eine Zahl sein.",
        ),
        (
            {"ausloeser": {"art": "messwert", "messwert": "cpu", "schwelle": 5, "vergleich": "gleich"}},
            "Der Vergleich muss „ueber“ oder „unter“ sein.",
        ),
        ({"ausloeser": {"art": "webhook", "integration_id": 42}}, "Diesen Webhook gibt es nicht (mehr)."),
        (
            {"ausloeser": {"art": "integration_ausgefallen", "integration_id": 42}},
            "Diese Integration gibt es nicht (mehr).",
        ),
        ({"ausloeser": {"art": "geraet", "geraet_id": 42}}, "Dieses Gerät gibt es nicht (mehr)."),
        ({"bedingung": {"tage": ["heute"]}}, "„heute“ ist kein Wochentag."),
        (
            {"bedingung": {"von": "08:00"}},
            "Für das Zeitfenster bitte beide Uhrzeiten angeben („von“ und „bis“).",
        ),
        ({"bedingung": {"von": "08:00", "bis": "8:00"}}, "„von“ und „bis“ dürfen nicht gleich sein."),
        ({"aktion": {"art": "zaubern"}}, "Bitte eine Aktion wählen."),
        ({"aktion": {"art": "ereignis", "nachricht": " "}}, "Bitte eine Nachricht für Missa angeben."),
        (
            {"aktion": {"art": "ereignis", "nachricht": "x", "dringlichkeit": "panik"}},
            "Die Dringlichkeit „panik“ gibt es nicht.",
        ),
        (
            {"aktion": {"art": "funktion", "funktion": "gibt_es_nicht"}},
            "Die Funktion „gibt_es_nicht“ gibt es nicht oder sie ist gesperrt.",
        ),
        ({"ruhezeit_minuten": -1}, "„Ruhezeit“ muss zwischen 0 und 10080 liegen."),
        ({"ruhezeit_minuten": 2.5}, "„Ruhezeit“ muss eine ganze Zahl sein."),
    ],
)
def test_ungueltige_regeln_werden_verstaendlich_abgelehnt(
    angemeldet: TestClient, aenderung: dict, meldung: str
) -> None:
    daten = {
        "name": "Test",
        "ausloeser": {"art": "webhook"},
        "aktion": {"art": "ereignis", "nachricht": "x"},
        **aenderung,
    }
    antwort = angemeldet.post("/api/regeln", json=daten)
    assert antwort.status_code == 422, antwort.text
    assert antwort.json()["meldung"] == meldung
    # Die Vorschau im Editor meldet dasselbe – als Auskunft, nicht als Fehler.
    vorschau = angemeldet.post("/api/regeln/satz", json=daten)
    assert vorschau.status_code == 200
    assert (vorschau.json()["ok"], vorschau.json()["meldung"]) == (False, meldung)
    assert angemeldet.get("/api/regeln").json()["regeln"] == []


def test_verlauf_wird_nach_30_tagen_geloescht_und_zeitzone_wird_geprueft(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr, einstellungen: Einstellungen, geheimnis: str
) -> None:
    regel = _regel(angemeldet)
    angemeldet.post(f"/api/regeln/{regel['id']}/testen")
    uhr.vor(days=29)
    alte_daten_loeschen(app)
    anmelden(angemeldet, uhr, geheimnis)
    assert len(_verlauf(angemeldet)) == 1
    uhr.vor(days=2)
    alte_daten_loeschen(app)
    anmelden(angemeldet, uhr, geheimnis)
    assert _verlauf(angemeldet) == []
    assert angemeldet.get("/api/regeln").json()["regeln"][0]["name"] == "CPU-Alarm"  # die Regel bleibt

    with pytest.raises(EinstellungsFehler, match="Zeitzone „Mond/Krater“ gibt es nicht"):
        dataclasses.replace(einstellungen, zeitzone="Mond/Krater")
    berlin = dataclasses.replace(einstellungen, zeitzone="Europe/Berlin")
    assert berlin.zeitzone == "Europe/Berlin"


def test_ohne_anmeldung_sind_die_regeln_nicht_erreichbar(client: TestClient) -> None:
    assert client.get("/api/regeln").status_code == 401
    assert client.get("/api/regeln/verlauf").status_code == 401
    assert client.post("/api/regeln", json={}).status_code == 401
    assert client.post("/api/regeln/1/testen").status_code == 401


# ====================================================================== Missa verwaltet Regeln


async def test_von_missa_angelegte_regel_erscheint_nach_freigabe_im_panel(
    app: FastAPI, angemeldet: TestClient, panel: LaufenderServer
) -> None:
    """Fertig-wenn: Eine von Missa angelegte Regel erscheint nach Freigabe im Panel."""
    regeln = integration_anlegen(angemeldet, "regeln")
    assert {f["gateway_name"]: f["recht"] for f in regeln["funktionen"]} == {
        "regeln_auflisten": "erlaubt",
        "regeln_regel_anlegen": "nachfragen",
        "regeln_regel_aendern": "nachfragen",
        "regeln_regel_loeschen": "nachfragen",
    }
    token = client_token(angemeldet)

    async def mit_freigabe(missa: Any, name: str, argumente: dict, erlauben: bool = True) -> tuple[Any, dict]:
        aufruf = asyncio.create_task(missa.call_tool(name, argumente))
        offen = await warte_auf(lambda: angemeldet.get("/api/freigaben").json()["offen"])
        await asyncio.sleep(0.1)
        assert not aufruf.done()
        angemeldet.post(f"/api/freigaben/{offen[0]['id']}", json={"erlauben": erlauben})
        return await asyncio.wait_for(aufruf, timeout=5), offen[0]

    async with mcp_client(panel.url, token) as missa:
        leer = json.loads(mcp_text(await missa.call_tool("regeln_auflisten", {})))
        assert leer == {"anzahl": 0, "regeln": []}

        wunsch = {
            "name": "CPU-Alarm",
            "ausloeser": "messwert",
            "messwert": "cpu",
            "schwelle": 90,
            "dauer_minuten": 5,
            "nachricht": "Die CPU ist seit 5 Minuten bei {wert} %",
            "dringlichkeit": "hoch",
        }
        # Abgelehnt: es entsteht keine Regel.
        abgelehnt, freigabe = await mit_freigabe(missa, "regeln_regel_anlegen", wunsch, erlauben=False)
        assert abgelehnt.is_error is True
        assert angemeldet.get("/api/regeln").json()["regeln"] == []
        # Die Freigabe zeigt die Regel als ganzen Satz.
        assert freigabe["vorschau"] == (
            "Legt die Regel „CPU-Alarm“ an: Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann bekommt "
            "Missa die Nachricht „Die CPU ist seit 5 Minuten bei {wert} %“ (Dringlichkeit: hoch). "
            "Danach 30 Minuten Ruhe."
        )

        # Erlaubt: die Regel erscheint im Panel.
        erlaubt, _ = await mit_freigabe(missa, "regeln_regel_anlegen", wunsch)
        assert erlaubt.is_error is False, mcp_text(erlaubt)
        antwort = json.loads(mcp_text(erlaubt))
        assert antwort["meldung"] == "Regel angelegt."
        im_panel = angemeldet.get("/api/regeln").json()["regeln"]
        assert len(im_panel) == 1
        assert (im_panel[0]["id"], im_panel[0]["name"], im_panel[0]["quelle"]) == (
            antwort["id"],
            "CPU-Alarm",
            "missa",
        )
        assert im_panel[0]["satz"] == antwort["beschreibung"]
        assert im_panel[0]["ausloeser"] == {
            "art": "messwert",
            "messwert": "cpu",
            "vergleich": "ueber",
            "schwelle": 90,
            "dauer_minuten": 5,
        }

        # … und sie funktioniert.
        app.state.serverlast.quelle = lambda _intervall: _messung(95)
        app.state.serverlast.aufzeichnen()
        liste = json.loads(mcp_text(await missa.call_tool("regeln_auflisten", {})))
        assert liste["anzahl"] == 1
        assert liste["regeln"][0]["beschreibung"].startswith(
            "Wenn die CPU-Auslastung 5 Minuten lang über 90 %"
        )

        # Ändern: nur das Genannte ändert sich; die Freigabe zeigt den neuen Satz.
        geaendert, freigabe = await mit_freigabe(
            missa, "regeln_regel_aendern", {"id": antwort["id"], "schwelle": 80, "wochentage": ["mo", "di"]}
        )
        assert geaendert.is_error is False, mcp_text(geaendert)
        assert freigabe["vorschau"].startswith(
            "Ändert die Regel „CPU-Alarm“. Neu: Wenn die CPU-Auslastung 5 Minuten lang über 80 % liegt "
            "(nur montags und dienstags), dann bekommt Missa"
        )
        neu = angemeldet.get("/api/regeln").json()["regeln"][0]
        assert (neu["ausloeser"]["schwelle"], neu["ausloeser"]["dauer_minuten"]) == (80, 5)
        assert neu["bedingung"] == {"tage": [0, 1]}
        assert neu["aktion"]["nachricht"] == "Die CPU ist seit 5 Minuten bei {wert} %"

        # Pausieren und ein ganz anderer Auslöser.
        pausiert, freigabe = await mit_freigabe(
            missa,
            "regeln_regel_aendern",
            {
                "id": antwort["id"],
                "aktiv": False,
                "ausloeser": "zeitplan",
                "uhrzeit": "7:30",
                "wochentage": [],
            },
        )
        assert pausiert.is_error is False, mcp_text(pausiert)
        assert freigabe["vorschau"].endswith("Die Regel ist danach pausiert.")
        neu = angemeldet.get("/api/regeln").json()["regeln"][0]
        assert (neu["aktiv"], neu["ausloeser"]) == (
            False,
            {"art": "zeitplan", "modus": "uhrzeit", "uhrzeit": "07:30"},
        )
        assert neu["bedingung"] == {}

        # Ungültiges wird sofort abgelehnt – ohne dass jemand gefragt wird.
        for name, argumente, erwartet in (
            (
                "regeln_regel_anlegen",
                {"name": "X", "ausloeser": "messwert", "messwert": "luft", "schwelle": 1, "nachricht": "x"},
                "Den Messwert „luft“ gibt es nicht.",
            ),
            (
                "regeln_regel_anlegen",
                {"name": "X", "ausloeser": "zeitplan", "nachricht": "x"},
                "keine gültige Uhrzeit",
            ),
            (
                "regeln_regel_anlegen",
                {"name": "X", "ausloeser": "webhook", "integration": "Gibtsnicht", "nachricht": "x"},
                "Den Webhook „Gibtsnicht“ gibt es nicht.",
            ),
            ("regeln_regel_aendern", {"id": 999, "schwelle": 1}, "Die Regel 999 gibt es nicht"),
            ("regeln_regel_loeschen", {"id": 999}, "Die Regel 999 gibt es nicht"),
        ):
            sofort = await asyncio.wait_for(missa.call_tool(name, argumente), timeout=5)
            assert sofort.is_error is True
            assert erwartet in mcp_text(sofort)
        assert angemeldet.get("/api/freigaben").json()["offen"] == []

        # Löschen: die Freigabe sagt, welche Regel verschwindet.
        geloescht, freigabe = await mit_freigabe(missa, "regeln_regel_loeschen", {"id": antwort["id"]})
        assert geloescht.is_error is False
        assert freigabe["vorschau"].startswith(
            "Löscht die Regel „CPU-Alarm“: Jeden Tag um 07:30 Uhr bekommt Missa"
        )
        assert angemeldet.get("/api/regeln").json()["regeln"] == []


def test_missa_kann_eine_regel_mit_funktion_anlegen(app: FastAPI, angemeldet: TestClient) -> None:
    """Die Einzelangaben der Missa-Funktionen ergeben dieselben Regeln wie der Editor im Panel."""
    integration_anlegen(angemeldet, "lampe")
    regeln = app.state.regeln
    vorschau = regeln.vorschau_anlegen(
        name="Abendlicht",
        ausloeser="zeitplan",
        uhrzeit="18:00",
        aktion="funktion",
        funktion="lampe_schalten",
        argumente={"an": True},
        wochentage=["sa", "so"],
    )
    assert vorschau == (
        "Legt die Regel „Abendlicht“ an: Am Wochenende um 18:00 Uhr wird die Funktion „lampe_schalten“ "
        "aufgerufen (an = ja)."
    )
    angelegt = regeln.fuer_missa_anlegen(
        name="Ausfall",
        ausloeser="integration_ausgefallen",
        integration="lampe",
        nachricht="Die Lampe ist weg",
    )
    assert angelegt["beschreibung"].startswith("Wenn die Integration „Lampe“ ausfällt, dann bekommt Missa")
    jede = regeln.fuer_missa_aendern(angelegt["id"], integration="alle")
    assert jede["beschreibung"].startswith("Wenn eine Integration ausfällt, dann")
    assert Path(app.state.einstellungen.eigene_integrationen_ordner / "lampe" / "main.py").is_file()
