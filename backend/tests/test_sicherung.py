"""Einrichtung sichern und einspielen: Export → leere Datenbank → Import ergibt dieselbe Einrichtung."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import PASSWORT, Uhr, code_fuer, einrichten, integration_anlegen
from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.main import create_app
from missa_control.modellverwaltung.modelle import Modell, Rolle
from missa_control.regeln.modelle import Regel
from missa_control.status.modelle import KnotenPosition
from missa_control.telefonie.modelle import TelefonieEinstellung
from server import LaufenderServer, einfache_api

KEY = "lager-geheimer-key-0123456789"
SICHERUNGS_PASSWORT = "ein-eigenes-sicherungs-passwort"


@pytest.fixture
def api_server() -> Iterator[LaufenderServer]:
    with LaufenderServer(einfache_api(KEY)) as server:
        yield server


@pytest.fixture
def leeres_panel(einstellungen: Einstellungen, tmp_path: Path, uhr: Uhr) -> Iterator[tuple[TestClient, str]]:
    """Ein zweites, frisch installiertes Panel (eigene Datenbank, eigener ENCRYPTION_KEY)."""
    app = create_app(
        dataclasses.replace(
            einstellungen, daten_ordner=tmp_path / "neu", encryption_key=Fernet.generate_key().decode()
        )
    )
    with TestClient(app) as client:
        geheimnis = einrichten(client, uhr)
        yield client, geheimnis
    app.state.datenbank.schliessen()


def _bestaetigung(geheimnis: str, uhr: Uhr) -> dict[str, str]:
    """Passwort und frischer Code – jeder Code gilt nur einmal, also die Uhr weiterstellen."""
    uhr.vor(seconds=31)
    return {"passwort": PASSWORT, "code": code_fuer(geheimnis, uhr)}


def _einrichtung_anlegen(app: FastAPI, client: TestClient, server: LaufenderServer) -> dict[str, Any]:
    zugang = client.post("/api/zugaenge", json={"name": "Lager-Key", "typ": "api_key", "wert": KEY}).json()[
        "id"
    ]
    test = client.post(
        "/api/integrationen/testen",
        json={"manifest_id": "api", "konfig": {"adresse": server.url + "/v1", "zugang": zugang}},
    ).json()
    lager = client.post(
        "/api/integrationen",
        json={
            "manifest_id": "api",
            "name": "Lager",
            "konfig": {"adresse": server.url + "/v1", "zugang": zugang},
            "test_id": test["test_id"],
            "zugriff": "lesen",
            "rechte": {"abrufen": "erlaubt", "senden": "gesperrt"},
        },
    ).json()
    serverlast = integration_anlegen(client, "serverlast")
    client.put(f"/api/integrationen/{serverlast['id']}", json={"aktiv": False})
    assert client.put(
        "/api/profil", json={"profil": {"name": "Missa", "wesen": "neugierig"}}
    ).status_code in (200, 201)
    jetzt = zeit.jetzt()
    with app.state.datenbank.sitzung() as db:
        db.add(
            Regel(
                name="Lager weg",
                aktiv=True,
                ausloeser={"art": "integration_ausgefallen", "integration_id": lager["id"]},
                bedingung={},
                aktion={"art": "ereignis", "nachricht": "Das Lager ist weg", "dringlichkeit": "hoch"},
                ruhezeit_minuten=15,
                quelle="manuell",
                erstellt=jetzt,
                geaendert=jetzt,
            )
        )
        modell = Modell(
            name="Klein",
            url="http://127.0.0.1:9/v1",
            modellname="klein-7b",
            zugang_id=zugang,
            erstellt=jetzt,
            geaendert=jetzt,
        )
        db.add(modell)
        db.flush()
        rolle = db.query(Rolle).filter_by(kennung="schnell").one()
        rolle.haupt_modell_id = modell.id
        einstellung = db.query(TelefonieEinstellung).one_or_none() or TelefonieEinstellung()
        einstellung.landesvorwahl = "+41"
        einstellung.erlaubte_anrufer = [{"name": "Louis", "nummer": "+41790000000"}]
        einstellung.ruhezeiten = [{"von": "22:00", "bis": "07:00"}]
        einstellung.adapter = f"integration:{lager['id']}"
        db.add(einstellung)
        db.add(KnotenPosition(knoten=f"integration:{lager['id']}", x=120.0, y=-40.0))
        db.add(KnotenPosition(knoten="missa", x=0.0, y=0.0))
        db.commit()
    return lager


def _export(client: TestClient, **eingabe: Any) -> dict[str, Any]:
    antwort = client.post("/api/sicherung/export", json=eingabe)
    assert antwort.status_code == 200, antwort.text
    assert "attachment" in antwort.headers["content-disposition"]
    return antwort.json()


def _vergleichbar(datei: dict[str, Any]) -> dict[str, Any]:
    """Was gleich sein muss: alles ausser Zeitpunkt und Verschlüsselung der Zugänge."""
    datei = json.loads(json.dumps(datei))
    datei.pop("erstellt")
    datei["zugaenge"] = [eintrag["name"] for eintrag in datei["zugaenge"]["liste"]]
    for integration in datei["integrationen"]:
        integration["konfig"].pop("adresse", None)
    return datei


def test_export_leere_datenbank_import_ergibt_dieselbe_einrichtung(
    app: FastAPI, angemeldet: TestClient, geheimnis: str, uhr: Uhr, api_server: LaufenderServer, leeres_panel
) -> None:
    lager = _einrichtung_anlegen(app, angemeldet, api_server)
    datei = _export(angemeldet, sicherungs_passwort=SICHERUNGS_PASSWORT, **_bestaetigung(geheimnis, uhr))
    assert datei["format"] == "missa-control-sicherung" and datei["version"] == 1
    assert KEY not in json.dumps(datei)  # auch verschlüsselt steht der Key nicht im Klartext drin
    assert [i["kennung"] for i in datei["integrationen"]] == ["lager", "serverlast"]
    assert datei["regeln"][0]["ausloeser"] == {"art": "integration_ausgefallen", "integration": "lager"}
    assert datei["telefonie"]["adapter"] == "integration@lager"

    neu, geheimnis_neu = leeres_panel
    text = json.dumps(datei)
    vorschau = neu.post(
        "/api/sicherung/vorschau", json={"datei": text, "sicherungs_passwort": SICHERUNGS_PASSWORT}
    )
    assert vorschau.status_code == 200, vorschau.text
    bereiche = {b["bereich"]: b for b in vorschau.json()["bereiche"]}
    assert {e["status"] for e in bereiche["integrationen"]["eintraege"]} == {"neu"}
    assert bereiche["zugaenge"]["eintraege"] == [{"name": "Lager-Key", "status": "neu"}]

    eingespielt = neu.post(
        "/api/sicherung/einspielen",
        json={"datei": text, "sicherungs_passwort": SICHERUNGS_PASSWORT, **_bestaetigung(geheimnis_neu, uhr)},
    )
    assert eingespielt.status_code == 200, eingespielt.text
    assert eingespielt.json()["zugang_fehlt"] == []

    # Dieselbe Einrichtung: der Export des neuen Panels gleicht dem alten
    wieder = _export(neu, sicherungs_passwort=SICHERUNGS_PASSWORT, **_bestaetigung(geheimnis_neu, uhr))
    assert _vergleichbar(wieder) == _vergleichbar(datei)

    integrationen = {i["kennung"]: i for i in neu.get("/api/integrationen").json()}
    assert integrationen["lager"]["status"] == "ungetestet"
    assert integrationen["lager"]["zugriff"] == "lesen"
    assert integrationen["serverlast"]["aktiv"] is False
    # Nach dem Test funktioniert der eingespielte Zugang (mit dem neuen ENCRYPTION_KEY verschlüsselt)
    getestet = neu.post(f"/api/integrationen/{integrationen['lager']['id']}/testen").json()
    assert getestet["status"] == "ok", getestet
    aufruf = neu.post(
        f"/api/integrationen/{getestet['id']}/aufrufen",
        json={"funktion": "abrufen", "argumente": {"pfad": "/artikel"}},
    ).json()
    assert aufruf["ok"] is True, aufruf

    # Zweites Mal einspielen: alles unverändert
    nochmal = neu.post(
        "/api/sicherung/vorschau", json={"datei": text, "sicherungs_passwort": SICHERUNGS_PASSWORT}
    ).json()
    stati = {e["status"] for b in nochmal["bereiche"] if b["bereich"] != "uebersicht" for e in b["eintraege"]}
    assert stati == {"unveraendert"}, nochmal
    assert lager["id"]


def test_ohne_passwort_steht_kein_geheimnis_in_der_datei(
    app: FastAPI, angemeldet: TestClient, uhr: Uhr, api_server: LaufenderServer, leeres_panel
) -> None:
    _einrichtung_anlegen(app, angemeldet, api_server)
    datei = _export(angemeldet)  # ohne Passwort: keine erneute Anmeldung nötig
    text = json.dumps(datei)
    assert KEY not in text
    assert datei["zugaenge"] == {
        "verschluesselt": False,
        "liste": [{"name": "Lager-Key", "typ": "api_key", "benutzer": None, "notiz": ""}],
    }
    # Kein Wert, kein verschlüsselter Inhalt, keine Client-Tokens, kein 2FA-Geheimnis
    for verboten in ("wert", "inhalt", "token", "totp", "passwort_hash"):
        assert f'"{verboten}"' not in text

    neu, geheimnis_neu = leeres_panel
    vorschau = neu.post("/api/sicherung/vorschau", json={"datei": text}).json()
    zugaenge = next(b for b in vorschau["bereiche"] if b["bereich"] == "zugaenge")
    assert zugaenge["eintraege"] == [{"name": "Lager-Key", "status": "fehlt"}]
    ergebnis = neu.post(
        "/api/sicherung/einspielen", json={"datei": text, **_bestaetigung(geheimnis_neu, uhr)}
    )
    assert ergebnis.status_code == 200, ergebnis.text
    assert ergebnis.json()["zugang_fehlt"] == ["Lager"]
    lager = next(i for i in neu.get("/api/integrationen").json() if i["kennung"] == "lager")
    assert lager["status"] == "ungetestet"
    assert lager["status_meldung"] == "Zugang fehlt: Lager-Key"


def test_falsches_passwort_und_fremde_dateien(
    app: FastAPI, angemeldet: TestClient, geheimnis: str, uhr: Uhr, api_server: LaufenderServer
) -> None:
    _einrichtung_anlegen(app, angemeldet, api_server)
    text = json.dumps(
        _export(angemeldet, sicherungs_passwort=SICHERUNGS_PASSWORT, **_bestaetigung(geheimnis, uhr))
    )

    falsch = angemeldet.post(
        "/api/sicherung/vorschau", json={"datei": text, "sicherungs_passwort": "ganz-falsches-passwort"}
    )
    assert falsch.status_code == 422 and "Passwort der Sicherung stimmt nicht" in falsch.json()["meldung"]
    ohne = angemeldet.post("/api/sicherung/vorschau", json={"datei": text})
    assert ohne.status_code == 422 and "verschlüsselte Zugänge" in ohne.json()["meldung"]

    neuer = json.dumps({**json.loads(text), "version": 99})
    antwort = angemeldet.post(
        "/api/sicherung/vorschau", json={"datei": neuer, "sicherungs_passwort": SICHERUNGS_PASSWORT}
    )
    assert antwort.status_code == 422 and "neueren Version" in antwort.json()["meldung"]
    for kaputt in ("kein json", json.dumps({"format": "etwas-anderes", "version": 1})):
        antwort = angemeldet.post("/api/sicherung/vorschau", json={"datei": kaputt})
        assert antwort.status_code == 422 and "keine Sicherung von Missa Control" in antwort.json()["meldung"]
    zu_kurz = angemeldet.post(
        "/api/sicherung/export", json={"sicherungs_passwort": "kurz", **_bestaetigung(geheimnis, uhr)}
    )
    assert zu_kurz.status_code == 422


def test_schutz_durch_erneute_anmeldung(
    app: FastAPI, angemeldet: TestClient, geheimnis: str, uhr: Uhr, api_server: LaufenderServer
) -> None:
    _einrichtung_anlegen(app, angemeldet, api_server)
    # Export mit Zugängen: ohne bzw. mit falschem Code abgelehnt
    ohne = angemeldet.post("/api/sicherung/export", json={"sicherungs_passwort": SICHERUNGS_PASSWORT})
    assert ohne.status_code == 403
    uhr.vor(seconds=31)
    falsch = angemeldet.post(
        "/api/sicherung/export",
        json={"sicherungs_passwort": SICHERUNGS_PASSWORT, "passwort": PASSWORT, "code": "000000"},
    )
    assert falsch.status_code == 403 and "Passwort oder Code falsch" in falsch.json()["meldung"]
    # Einspielen nur mit Passwort und Code
    text = json.dumps(_export(angemeldet))
    abgelehnt = angemeldet.post(
        "/api/sicherung/einspielen", json={"datei": text, "passwort": PASSWORT, "code": "123456"}
    )
    assert abgelehnt.status_code == 403
    # Ohne Anmeldung gar nichts
    angemeldet.post("/api/auth/abmelden")
    assert angemeldet.post("/api/sicherung/export", json={}).status_code == 401


def test_ersetzen_leert_den_bereich_ergaenzen_behaelt(
    app: FastAPI, angemeldet: TestClient, geheimnis: str, uhr: Uhr, api_server: LaufenderServer
) -> None:
    _einrichtung_anlegen(app, angemeldet, api_server)
    text = json.dumps(_export(angemeldet))
    extra = integration_anlegen(angemeldet, "gedaechtnis")

    vorschau = angemeldet.post("/api/sicherung/vorschau", json={"datei": text}).json()
    integrationen = next(b for b in vorschau["bereiche"] if b["bereich"] == "integrationen")
    assert integrationen["nur_hier"] == [f"{extra['name']} ({extra['kennung']})"]

    ergaenzt = angemeldet.post(
        "/api/sicherung/einspielen",
        json={"datei": text, "modi": {"integrationen": "ergaenzen"}, **_bestaetigung(geheimnis, uhr)},
    )
    assert ergaenzt.status_code == 200, ergaenzt.text
    assert extra["kennung"] in {i["kennung"] for i in angemeldet.get("/api/integrationen").json()}

    ersetzt = angemeldet.post(
        "/api/sicherung/einspielen",
        json={"datei": text, "modi": {"integrationen": "ersetzen"}, **_bestaetigung(geheimnis, uhr)},
    )
    assert ersetzt.status_code == 200, ersetzt.text
    assert {i["kennung"] for i in angemeldet.get("/api/integrationen").json()} == {"lager", "serverlast"}
