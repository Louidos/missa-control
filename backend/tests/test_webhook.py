"""Eingehende Webhooks: eine geheime Adresse, an die andere Dienste Meldungen schicken.

Gesendet wird hier über echtes HTTP an das laufende Panel – ohne Anmeldung, so wie es `curl` tun würde.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import client_token
from missa_control.integrationen import webhook as webhook_modul
from missa_control.main import create_app
from missa_control.zugaenge.schwaerzen import SCHWAERZER
from server import LaufenderServer


def _webhook(admin: TestClient, name: str = "Waschmaschine", **konfig: Any) -> dict:
    """Die drei Schritte des Assistenten: Karte „Webhook“ → Formular → testen und aktivieren."""
    test = admin.post("/api/integrationen/testen", json={"manifest_id": "webhook", "konfig": konfig}).json()
    assert test["ok"] is True, test
    antwort = admin.post(
        "/api/integrationen",
        json={"manifest_id": "webhook", "name": name, "konfig": konfig, "test_id": test["test_id"]},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _webhook_ereignisse(admin: TestClient) -> list[dict]:
    return [e for e in reversed(admin.get("/api/ereignisse").json()) if e["art"] == "webhook"]


def test_einrichten_erzeugt_eine_geheime_adresse(app: FastAPI, angemeldet: TestClient) -> None:
    karte = next(e for e in angemeldet.get("/api/katalog").json()["eintraege"] if e["id"] == "webhook")
    assert (karte["art"], karte["verfuegbar"], karte["kann_hinzufuegen"]) == ("webhook", True, True)

    test = angemeldet.post("/api/integrationen/testen", json={"manifest_id": "webhook", "konfig": {}}).json()
    assert test["ok"] is True
    assert test["funktionen"] == []  # ein Webhook hat keine Funktionen für Missa

    webhook = _webhook(angemeldet)
    pfad = webhook["webhook"]["pfad"]
    assert pfad.startswith("/api/webhook/")
    schluessel = pfad.removeprefix("/api/webhook/")
    assert len(schluessel) >= 32  # lang und zufällig
    assert webhook["funktionen"] == []
    assert (webhook["status"], webhook["konfig"]) == ("ok", {"dringlichkeit": "normal"})

    # Jeder Webhook hat seine eigene Adresse; in der Datenbank steht der Schlüssel nicht im Klartext.
    zweiter = _webhook(angemeldet, name="Uptime Kuma")
    assert zweiter["webhook"]["pfad"] != pfad
    assert schluessel.encode() not in app.state.einstellungen.datenbank_pfad.read_bytes()
    # … und auch nicht in Logs: der Schwärzer kennt ihn.
    assert schluessel not in SCHWAERZER.schwaerzen(f'"POST {pfad} HTTP/1.1" 200')

    # Erneut testen ändert die Adresse nicht.
    erneut = angemeldet.post(f"/api/integrationen/{webhook['id']}/testen").json()
    assert erneut["webhook"]["pfad"] == pfad


def test_meldung_an_die_adresse_erzeugt_ein_ereignis(angemeldet: TestClient, panel: LaufenderServer) -> None:
    """Fertig-wenn: `curl` an die Webhook-URL erzeugt ein Ereignis."""
    webhook = _webhook(angemeldet)
    adresse = panel.url + webhook["webhook"]["pfad"]

    # So wie: curl -X POST <Adresse> -H "Content-Type: application/json" -d '{"nachricht": "…"}'
    antwort = httpx2.post(adresse, json={"nachricht": "Die Wäsche ist fertig", "programm": "Baumwolle 40°"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {
        "ok": True,
        "ereignis_id": antwort.json()["ereignis_id"],
    }  # mehr gibt sie nicht preis
    assert antwort.headers["cache-control"] == "no-store"

    ereignisse = _webhook_ereignisse(angemeldet)
    assert len(ereignisse) == 1
    ereignis = ereignisse[0]
    assert ereignis["id"] == antwort.json()["ereignis_id"]
    assert ereignis["titel"] == "Webhook „Waschmaschine“ hat etwas empfangen"
    assert ereignis["nachricht"] == "Die Wäsche ist fertig"
    assert (ereignis["quelle"], ereignis["dringlichkeit"]) == ("Waschmaschine", "normal")
    assert ereignis["daten"] == {
        "integration_id": webhook["id"],
        "inhalt": {"nachricht": "Die Wäsche ist fertig", "programm": "Baumwolle 40°"},
    }

    # Missa holt das Ereignis mit ihrem Client-Token ab.
    token = client_token(angemeldet)
    abgeholt = httpx2.get(panel.url + "/api/events", headers={"Authorization": f"Bearer {token}"}).json()
    assert [e["nachricht"] for e in abgeholt["ereignisse"] if e["art"] == "webhook"] == [
        "Die Wäsche ist fertig"
    ]


def test_meldungen_in_verschiedenen_formen(angemeldet: TestClient, panel: LaufenderServer) -> None:
    webhook = _webhook(angemeldet, name="Garage", dringlichkeit="hoch")
    adresse = panel.url + webhook["webhook"]["pfad"]

    def gesendet(antwort: httpx2.Response) -> dict:
        assert antwort.status_code == 200, antwort.text
        return next(e for e in _webhook_ereignisse(angemeldet) if e["id"] == antwort.json()["ereignis_id"])

    # Formularfelder, wie sie viele Geräte senden
    formular = gesendet(httpx2.post(adresse, data={"text": "Tor offen", "seit": "10 min"}))
    assert (formular["nachricht"], formular["dringlichkeit"]) == (
        "Tor offen",
        "hoch",
    )  # Dringlichkeit des Webhooks
    assert formular["daten"]["inhalt"] == {"text": "Tor offen", "seit": "10 min"}

    # Einfacher Text
    text = gesendet(
        httpx2.post(adresse, content=b"Tor ist wieder zu", headers={"Content-Type": "text/plain"})
    )
    assert (text["nachricht"], text["daten"]["inhalt"]) == ("Tor ist wieder zu", "Tor ist wieder zu")

    # Nur eine Adresse aufrufen (GET) – für ganz einfache Geräte
    einfach = gesendet(
        httpx2.get(adresse, params={"nachricht": "Bewegung erkannt", "dringlichkeit": "dringend"})
    )
    assert (einfach["nachricht"], einfach["dringlichkeit"]) == ("Bewegung erkannt", "dringend")

    # JSON ohne passendes Textfeld: die Meldung selbst wird zum Text; „wert“ steht Regeln zur Verfügung
    zahlen = gesendet(httpx2.put(adresse, json={"sensor": "tor", "wert": 87.5}))
    assert zahlen["nachricht"] == '{"sensor": "tor", "wert": 87.5}'
    assert zahlen["daten"]["wert"] == 87.5

    # Ganz ohne Inhalt geht auch (als reines Signal); eine Liste ebenfalls
    assert gesendet(httpx2.post(adresse))["nachricht"] == "(ohne Inhalt)"
    assert gesendet(httpx2.post(adresse, json=[1, 2, 3]))["nachricht"] == "[1, 2, 3]"
    # Eine Meldung von einer Webseite (mit Herkunft) wird nicht abgewiesen – hier zählt allein der Schlüssel.
    assert (
        httpx2.post(adresse, json={"text": "x"}, headers={"Origin": "https://irgendwo.example"}).status_code
        == 200
    )

    kaputt = httpx2.post(adresse, content=b"{kein json", headers={"Content-Type": "application/json"})
    assert kaputt.status_code == 400
    assert kaputt.json()["meldung"] == "Die Meldung ist kein gültiges JSON."
    riesig = httpx2.post(adresse, content=b"x" * (64 * 1024 + 1), headers={"Content-Type": "text/plain"})
    assert riesig.status_code == 413
    assert riesig.json()["meldung"] == "Die Meldung ist zu gross."


def test_nur_der_richtige_schluessel_oeffnet(angemeldet: TestClient, panel: LaufenderServer) -> None:
    webhook = _webhook(angemeldet)
    pfad = webhook["webhook"]["pfad"]
    falsch = httpx2.post(panel.url + pfad[:-3] + "xyz", json={"text": "x"})
    assert falsch.status_code == 404
    assert falsch.json() == {"meldung": "Diesen Webhook gibt es nicht."}
    assert httpx2.post(panel.url + "/api/webhook/", json={}).status_code in (401, 404)
    assert _webhook_ereignisse(angemeldet) == []

    # Deaktiviert: die Adresse antwortet wie eine, die es nicht gibt.
    angemeldet.put(f"/api/integrationen/{webhook['id']}", json={"aktiv": False})
    assert httpx2.post(panel.url + pfad, json={"text": "x"}).status_code == 404
    angemeldet.put(f"/api/integrationen/{webhook['id']}", json={"aktiv": True})
    assert httpx2.post(panel.url + pfad, json={"text": "x"}).status_code == 200

    # Neue Adresse erzeugen: die alte gilt sofort nicht mehr.
    neu = angemeldet.post(f"/api/integrationen/{webhook['id']}/webhook/erneuern")
    assert neu.status_code == 200, neu.text
    neuer_pfad = neu.json()["webhook"]["pfad"]
    assert neuer_pfad != pfad
    assert httpx2.post(panel.url + pfad, json={"text": "x"}).status_code == 404
    assert httpx2.post(panel.url + neuer_pfad, json={"text": "x"}).status_code == 200

    # Entfernt: nichts geht mehr. Und die Adresse gibt nie etwas heraus.
    angemeldet.delete(f"/api/integrationen/{webhook['id']}")
    assert httpx2.post(panel.url + neuer_pfad, json={"text": "x"}).status_code == 404
    assert httpx2.post(panel.url + f"/api/integrationen/{webhook['id']}/webhook/erneuern").status_code == 401


def test_adresse_erneuern_geht_nur_bei_webhooks(angemeldet: TestClient) -> None:
    serverlast = angemeldet.post(
        "/api/integrationen", json={"manifest_id": "serverlast", "konfig": {}}
    ).json()
    assert "webhook" not in serverlast
    antwort = angemeldet.post(f"/api/integrationen/{serverlast['id']}/webhook/erneuern")
    assert antwort.status_code == 409
    assert antwort.json()["meldung"] == "Diese Integration ist kein Webhook."
    assert angemeldet.post("/api/integrationen/999/webhook/erneuern").status_code == 404


def test_webhook_loest_regeln_aus(app: FastAPI, angemeldet: TestClient, panel: LaufenderServer) -> None:
    waschmaschine = _webhook(angemeldet)
    garage = _webhook(angemeldet, name="Garage")
    optionen = angemeldet.get("/api/regeln").json()["optionen"]
    assert optionen["webhooks"] == [
        {"id": garage["id"], "name": "Garage"},
        {"id": waschmaschine["id"], "name": "Waschmaschine"},
    ]

    regel = angemeldet.post(
        "/api/regeln",
        json={
            "name": "Wäsche",
            "ausloeser": {"art": "webhook", "integration_id": waschmaschine["id"]},
            "aktion": {
                "art": "ereignis",
                "nachricht": "Bitte die Wäsche aufhängen ({wert} Minuten)",
                "dringlichkeit": "hoch",
            },
            "ruhezeit_minuten": 0,
        },
    )
    assert regel.status_code == 201, regel.text
    assert regel.json()["satz"].startswith(
        "Wenn der Webhook „Waschmaschine“ etwas empfängt, dann bekommt Missa"
    )

    httpx2.post(panel.url + garage["webhook"]["pfad"], json={"text": "Tor offen"})  # anderer Webhook
    assert app.state.regeln.warten()
    assert [e for e in angemeldet.get("/api/ereignisse").json() if e["art"] == "regel"] == []

    httpx2.post(panel.url + waschmaschine["webhook"]["pfad"], json={"text": "fertig", "wert": 95})
    assert app.state.regeln.warten()
    ausgeloest = [e for e in angemeldet.get("/api/ereignisse").json() if e["art"] == "regel"]
    assert [e["nachricht"] for e in ausgeloest] == ["Bitte die Wäsche aufhängen (95 Minuten)"]
    verlauf = angemeldet.get("/api/regeln/verlauf").json()["eintraege"]
    assert verlauf[0]["anlass"] == "Webhook „Waschmaschine“ hat etwas empfangen"


def test_dauerfeuer_wird_gebremst(
    angemeldet: TestClient, panel: LaufenderServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webhook_modul, "MAX_JE_MINUTE", 5)
    webhook = _webhook(angemeldet)
    adresse = panel.url + webhook["webhook"]["pfad"]
    antworten = [httpx2.post(adresse, json={"n": n}).status_code for n in range(7)]
    assert antworten == [200, 200, 200, 200, 200, 429, 429]
    assert len(_webhook_ereignisse(angemeldet)) == 5
    assert "Höchstens 5 pro Minute" in httpx2.post(adresse).json()["hinweis"]


def test_nach_einem_neustart_gilt_die_adresse_weiter(app: FastAPI, angemeldet: TestClient) -> None:
    webhook = _webhook(angemeldet)
    pfad = webhook["webhook"]["pfad"]
    neu = create_app(app.state.einstellungen)
    try:
        with TestClient(neu) as ohne_anmeldung:
            antwort = ohne_anmeldung.post(pfad, json={"nachricht": "Hallo nach dem Neustart"})
            assert antwort.status_code == 200, antwort.text
        # Beim Start lernt der Schwärzer die Adressen wieder – sie stehen auch dann in keinem Log.
        assert pfad.removeprefix("/api/webhook/") not in SCHWAERZER.schwaerzen(json.dumps({"pfad": pfad}))
    finally:
        neu.state.datenbank.schliessen()


def test_zugriffsprotokoll_bleibt_lesbar_und_ohne_schluessel(app: FastAPI, angemeldet: TestClient) -> None:
    """Der Webserver protokolliert jede Anfrage mit ihrer Adresse – bei Webhooks also mit dem Schlüssel.

    Der Schlüssel wird geschwärzt, und die Zeile bleibt so aufgebaut, dass das Zugriffsprotokoll sie
    noch schreiben kann (früher ging dabei der Aufbau verloren und es hagelte Protokollfehler).
    """
    import logging

    from uvicorn.logging import AccessFormatter

    pfad = _webhook(angemeldet)["webhook"]["pfad"]
    schluessel = pfad.removeprefix("/api/webhook/")
    eintrag = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("172.18.0.1:39726", "POST", pfad, "1.1", 200),
        None,
    )
    zeile = AccessFormatter(
        fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    ).format(eintrag)
    assert zeile == '172.18.0.1:39726 - "POST /api/webhook/••• HTTP/1.1" 200 OK'
    assert schluessel not in zeile
    assert eintrag.args is not None and eintrag.args[4] == 200  # Zahlen bleiben Zahlen

    # Auch Einträge mit benannten Bestandteilen und mit Objekten, die das Geheimnis enthalten:
    logger = logging.getLogger("missa_control.test")
    benannt = logger.makeRecord(
        "x", logging.INFO, __file__, 1, "Adresse %(pfad)s, Versuch %(nr)d", ({"pfad": pfad, "nr": 2},), None
    )
    assert benannt.getMessage() == "Adresse /api/webhook/•••, Versuch 2"
    objekt = logger.makeRecord("x", logging.INFO, __file__, 1, "Anfrage %s", ({"ziel": pfad},), None)
    assert schluessel not in objekt.getMessage()
    zusammengesetzt = logger.makeRecord(
        "x", logging.INFO, __file__, 1, "%s%s", (pfad[:-10], pfad[-10:]), None
    )
    assert schluessel not in zusammengesetzt.getMessage()  # letzter Ausweg: der fertige Text wird ersetzt
