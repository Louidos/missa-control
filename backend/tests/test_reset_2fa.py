"""Notfall-Reset der Zwei-Faktor-Anmeldung (scripts/reset-2fa.sh).

Wer das Handy mit der Authenticator-App verliert, setzt auf ai01 die Zwei-Faktor-Anmeldung zurück.
Danach braucht es das bisherige Passwort, um einen neuen QR-Code zu bekommen – wer nur zufällig im
Netz ist, kann das Panel in dieser Zeit nicht übernehmen.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import PASSWORT, Uhr, code_fuer, integration_anlegen
from missa_control import cli
from missa_control.config import Einstellungen


def _zuruecksetzen(app: FastAPI, **angaben: bool) -> str:
    with app.state.datenbank.sitzung() as db:
        return app.state.auth.zwei_faktor_zuruecksetzen(db, **angaben)


def _status(client: TestClient) -> dict:
    status = client.get("/api/auth/status").json()
    return {name: status[name] for name in ("eingerichtet", "zwei_faktor_neu", "angemeldet")}


def test_nach_dem_reset_braucht_es_das_bisherige_passwort(
    app: FastAPI, client: TestClient, geheimnis: str, uhr: Uhr
) -> None:
    integration_anlegen(client, "serverlast")
    assert _status(client) == {"eingerichtet": True, "zwei_faktor_neu": False, "angemeldet": True}

    meldung = _zuruecksetzen(app)
    assert meldung.startswith("Die Zwei-Faktor-Anmeldung ist zurückgesetzt, alle Anmeldungen sind beendet.")
    # Alle Anmeldungen sind beendet; das Panel wartet auf die neue Einrichtung des zweiten Faktors.
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": True, "angemeldet": False}
    assert client.get("/api/integrationen").status_code == 401
    anmeldung = client.post(
        "/api/auth/anmelden", json={"passwort": PASSWORT, "code": code_fuer(geheimnis, uhr)}
    )
    assert anmeldung.status_code == 409  # der alte Code öffnet nichts mehr

    # Ohne das bisherige Passwort gibt es keinen neuen QR-Code – auch nicht mit einem „neuen“ Passwort.
    falsch = client.post("/api/auth/einrichten", json={"passwort": "ein-ganz-anderes-passwort"})
    assert (falsch.status_code, falsch.json()["meldung"]) == (401, "Das Passwort stimmt nicht.")
    assert "nur mit dem bisherigen Passwort" in falsch.json()["hinweis"]
    assert "(noch 4 Versuch(e))" in falsch.json()["hinweis"]
    assert "./scripts/reset-2fa.sh --auch-passwort" in falsch.json()["hinweis"]

    # Mit dem bisherigen Passwort: neuer QR-Code, neues Geheimnis.
    neu = client.post("/api/auth/einrichten", json={"passwort": PASSWORT})
    assert neu.status_code == 200, neu.text
    neues_geheimnis = neu.json()["geheimnis"]
    assert neues_geheimnis != geheimnis
    assert neu.json()["qr_svg"].startswith("data:image/svg+xml")
    alter_code = client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    assert alter_code.status_code == 401  # die alte App gilt nicht mehr
    bestaetigt = client.post(
        "/api/auth/einrichten/bestaetigen", json={"code": code_fuer(neues_geheimnis, uhr)}
    )
    assert bestaetigt.status_code == 200, bestaetigt.text
    assert _status(client) == {"eingerichtet": True, "zwei_faktor_neu": False, "angemeldet": True}

    # Alles andere ist noch da – und das Passwort ist dasselbe geblieben.
    assert [i["manifest_id"] for i in client.get("/api/integrationen").json()] == ["serverlast"]
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)
    wieder = client.post(
        "/api/auth/anmelden", json={"passwort": PASSWORT, "code": code_fuer(neues_geheimnis, uhr)}
    )
    assert wieder.status_code == 200, wieder.text


def test_falsches_passwort_sperrt_auch_beim_neu_einrichten(
    app: FastAPI, client: TestClient, geheimnis: str, uhr: Uhr
) -> None:
    _zuruecksetzen(app)
    for _ in range(4):
        assert client.post("/api/auth/einrichten", json={"passwort": "geraten-geraten"}).status_code == 401
    gesperrt = client.post("/api/auth/einrichten", json={"passwort": "geraten-geraten"})
    assert (gesperrt.status_code, gesperrt.json()["meldung"]) == (
        429,
        "Zu viele Fehlversuche – die Anmeldung ist vorübergehend gesperrt.",
    )
    # Während der Sperre hilft auch das richtige Passwort nicht.
    assert client.post("/api/auth/einrichten", json={"passwort": PASSWORT}).status_code == 429
    uhr.vor(minutes=16)
    assert client.post("/api/auth/einrichten", json={"passwort": PASSWORT}).status_code == 200


def test_mit_auch_passwort_beginnt_die_einrichtung_von_vorn(
    app: FastAPI, client: TestClient, geheimnis: str, uhr: Uhr
) -> None:
    integration_anlegen(client, "serverlast")
    meldung = _zuruecksetzen(app, auch_passwort=True)
    assert meldung.startswith("Passwort und Zwei-Faktor-Anmeldung sind zurückgesetzt")
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": False, "angemeldet": False}

    neues_passwort = "ein-neues-langes-passwort"
    neu = client.post("/api/auth/einrichten", json={"passwort": neues_passwort})
    assert neu.status_code == 200, neu.text
    client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(neu.json()["geheimnis"], uhr)})
    assert _status(client)["angemeldet"] is True
    assert [i["manifest_id"] for i in client.get("/api/integrationen").json()] == ["serverlast"]

    # Das alte Passwort gilt nicht mehr.
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)
    alt = client.post(
        "/api/auth/anmelden", json={"passwort": PASSWORT, "code": code_fuer(neu.json()["geheimnis"], uhr)}
    )
    assert alt.status_code == 401


def test_ohne_einrichtung_gibt_es_nichts_zurueckzusetzen(app: FastAPI, client: TestClient) -> None:
    assert _zuruecksetzen(app) == "Das Panel ist noch nicht eingerichtet – es gibt nichts zurückzusetzen."
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": False, "angemeldet": False}
    # Eine begonnene, aber nie abgeschlossene Einrichtung ändert daran nichts.
    client.post("/api/auth/einrichten", json={"passwort": PASSWORT})
    assert _zuruecksetzen(app, auch_passwort=True).startswith("Das Panel ist noch nicht eingerichtet")


def test_zweimal_zuruecksetzen_und_wechsel_zu_auch_passwort(
    app: FastAPI, client: TestClient, geheimnis: str
) -> None:
    _zuruecksetzen(app)
    assert _zuruecksetzen(app).startswith("Die Zwei-Faktor-Anmeldung ist zurückgesetzt")  # schadet nicht
    assert _status(client)["zwei_faktor_neu"] is True
    # Ist auch das Passwort weg, lässt sich nachträglich ganz zurücksetzen.
    _zuruecksetzen(app, auch_passwort=True)
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": False, "angemeldet": False}
    assert (
        client.post("/api/auth/einrichten", json={"passwort": "noch-ein-neues-passwort"}).status_code == 200
    )


def test_das_werkzeug_fuer_das_skript(
    einstellungen: Einstellungen,
    client: TestClient,
    geheimnis: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`python -m missa_control.cli zwei-faktor-zuruecksetzen` – so ruft es scripts/reset-2fa.sh im Container auf."""
    monkeypatch.setenv("SECRET_KEY", einstellungen.secret_key)
    monkeypatch.setenv("ENCRYPTION_KEY", einstellungen.encryption_key)
    monkeypatch.setenv("MISSA_CONTROL_DATA_DIR", str(einstellungen.daten_ordner))

    cli.main(["zwei-faktor-zuruecksetzen"])
    assert "Die Zwei-Faktor-Anmeldung ist zurückgesetzt" in capsys.readouterr().out
    # Das laufende Panel merkt es sofort – ohne Neustart.
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": True, "angemeldet": False}

    cli.main(["zwei-faktor-zuruecksetzen", "--auch-passwort"])
    assert "Passwort und Zwei-Faktor-Anmeldung sind zurückgesetzt" in capsys.readouterr().out
    assert _status(client) == {"eingerichtet": False, "zwei_faktor_neu": False, "angemeldet": False}

    monkeypatch.setenv("MISSA_CONTROL_DATA_DIR", str(einstellungen.daten_ordner / "gibt-es-nicht"))
    with pytest.raises(SystemExit, match="Keine Datenbank gefunden"):
        cli.main(["zwei-faktor-zuruecksetzen"])
