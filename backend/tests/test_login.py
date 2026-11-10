"""Login: Einrichtung, Anmeldung mit Passwort + 2FA, Sitzung, Sperre und Zugriffsschutz."""

from __future__ import annotations

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import PASSWORT, Uhr, code_fuer, einrichten
from missa_control.auth.schutz import OEFFENTLICHE_PFADE, ist_webhook_pfad
from missa_control.config import Einstellungen, EinstellungsFehler


def _anmelden(client: TestClient, geheimnis: str, uhr: Uhr, passwort: str = PASSWORT):
    return client.post("/api/auth/anmelden", json={"passwort": passwort, "code": code_fuer(geheimnis, uhr)})


def _neu_anmelden(client: TestClient, geheimnis: str, uhr: Uhr):
    """Meldet ab und mit einem frischen Code wieder an (jeder Code gilt nur einmal)."""
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)
    return _anmelden(client, geheimnis, uhr)


# ---------- Zugriffsschutz ----------


def test_ohne_login_ist_nichts_erreichbar(app: FastAPI, client: TestClient) -> None:
    """Jede Route ausser Health und Login antwortet ohne Sitzung mit 401."""
    geprueft = 0
    for pfad, methoden in app.openapi()["paths"].items():
        if pfad in OEFFENTLICHE_PFADE:
            continue
        for methode in methoden:
            antwort = client.request(methode.upper(), pfad.replace("{", "").replace("}", ""))
            if ist_webhook_pfad(pfad):
                # Bewusste Ausnahme: Bei Webhooks ist der Schlüssel in der Adresse der Zugang.
                # Ein falscher Schlüssel verrät nichts.
                assert antwort.status_code == 404, f"{methode} {pfad}"
                assert antwort.json() == {"meldung": "Diesen Webhook gibt es nicht."}
                continue
            assert antwort.status_code == 401, f"{methode} {pfad} ist ohne Login erreichbar"
            geprueft += 1
    assert geprueft > 0


@pytest.mark.parametrize(
    "pfad", ["/api/gibt-es-nicht", "/api", "/mcp", "/mcp/", "/v1/models", "/v1/chat/completions"]
)
def test_unbekannte_geschuetzte_pfade_verraten_nichts(client: TestClient, pfad: str) -> None:
    assert client.get(pfad).status_code == 401
    assert client.post(pfad, json={}).status_code == 401


def test_oeffentlich_sind_nur_health_und_login() -> None:
    assert OEFFENTLICHE_PFADE == {
        "/api/health",
        "/api/auth/status",
        "/api/auth/einrichten",
        "/api/auth/einrichten/bestaetigen",
        "/api/auth/anmelden",
    }


def test_fremde_seite_wird_abgelehnt(client: TestClient, uhr: Uhr) -> None:
    antwort = client.post(
        "/api/auth/einrichten", json={"passwort": PASSWORT}, headers={"Origin": "https://boese.example"}
    )
    assert antwort.status_code == 403
    gleiche = client.post(
        "/api/auth/einrichten", json={"passwort": PASSWORT}, headers={"Origin": "http://testserver"}
    )
    assert gleiche.status_code == 200


# ---------- Einrichtung ----------


def test_einrichtung_ablauf(client: TestClient, uhr: Uhr) -> None:
    assert client.get("/api/auth/status").json()["eingerichtet"] is False

    antwort = client.post("/api/auth/einrichten", json={"passwort": PASSWORT})
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["otpauth_url"].startswith("otpauth://totp/Missa%20Control:admin?secret=")
    assert daten["qr_svg"].startswith("data:image/svg+xml")
    assert client.get("/api/auth/status").json() == {
        "eingerichtet": False,
        "angemeldet": False,
        "version": client.get("/api/health").json()["version"],
    }

    falsch = client.post("/api/auth/einrichten/bestaetigen", json={"code": "000000"})
    assert falsch.status_code == 401
    assert "hinweis" in falsch.json()

    richtig = client.post(
        "/api/auth/einrichten/bestaetigen", json={"code": code_fuer(daten["geheimnis"], uhr)}
    )
    assert richtig.status_code == 200
    status = client.get("/api/auth/status").json()
    assert status["eingerichtet"] is True
    assert status["angemeldet"] is True


def test_einrichtung_verlangt_langes_passwort(client: TestClient) -> None:
    antwort = client.post("/api/auth/einrichten", json={"passwort": "kurz"})
    assert antwort.status_code == 422
    assert "zu kurz" in antwort.json()["meldung"]


def test_einrichtung_nur_im_selben_browser(app: FastAPI, client: TestClient, uhr: Uhr) -> None:
    geheimnis = client.post("/api/auth/einrichten", json={"passwort": PASSWORT}).json()["geheimnis"]
    with TestClient(app) as fremder:
        antwort = fremder.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    assert antwort.status_code == 403
    assert client.get("/api/auth/status").json()["eingerichtet"] is False


def test_einrichtung_geht_nur_einmal(angemeldet: TestClient, app: FastAPI) -> None:
    with TestClient(app) as fremder:
        assert (
            fremder.post("/api/auth/einrichten", json={"passwort": "anderes-langes-passwort"}).status_code
            == 409
        )
        assert fremder.post("/api/auth/einrichten/bestaetigen", json={"code": "123456"}).status_code == 409


# ---------- Anmeldung ----------


def test_anmeldung_braucht_passwort_und_code(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)

    nur_passwort = client.post("/api/auth/anmelden", json={"passwort": PASSWORT, "code": "000000"})
    assert nur_passwort.status_code == 401
    nur_code = _anmelden(client, geheimnis, uhr, passwort="falsches-passwort")
    assert nur_code.status_code == 401
    assert nur_code.json()["meldung"] == nur_passwort.json()["meldung"]  # verrät nicht, was falsch war
    assert client.get("/api/auth/status").json()["angemeldet"] is False

    assert _anmelden(client, geheimnis, uhr).status_code == 200
    assert client.get("/api/auth/status").json()["angemeldet"] is True


def test_code_gilt_nur_einmal(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)
    code = code_fuer(geheimnis, uhr)
    assert client.post("/api/auth/anmelden", json={"passwort": PASSWORT, "code": code}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/anmelden", json={"passwort": PASSWORT, "code": code}).status_code == 401


def test_code_mit_leerzeichen_und_uhr_abweichung(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    client.cookies.clear()
    uhr.vor(seconds=120)
    vorheriger = pyotp.TOTP(geheimnis).at(int(uhr.jetzt.timestamp()) - 30)
    antwort = client.post(
        "/api/auth/anmelden", json={"passwort": PASSWORT, "code": f"{vorheriger[:3]} {vorheriger[3:]}"}
    )
    assert antwort.status_code == 200


def test_sperre_nach_fuenf_fehlversuchen(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    client.post("/api/auth/abmelden")
    client.cookies.clear()
    uhr.vor(seconds=90)

    for versuch in range(1, 6):
        antwort = client.post("/api/auth/anmelden", json={"passwort": "falsches-passwort", "code": "000000"})
        assert antwort.status_code == (401 if versuch < 5 else 429), versuch

    # Während der Sperre hilft auch die richtige Eingabe nicht.
    assert _anmelden(client, geheimnis, uhr).status_code == 429
    uhr.vor(minutes=14)
    gesperrt = _anmelden(client, geheimnis, uhr)
    assert gesperrt.status_code == 429
    assert "Minute" in gesperrt.json()["hinweis"]

    uhr.vor(minutes=1, seconds=1)
    assert _anmelden(client, geheimnis, uhr).status_code == 200


def test_erfolg_setzt_fehlversuche_zurueck(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    client.cookies.clear()
    for _ in range(4):
        assert (
            client.post(
                "/api/auth/anmelden", json={"passwort": "falsch-falsch", "code": "000000"}
            ).status_code
            == 401
        )
    assert _neu_anmelden(client, geheimnis, uhr).status_code == 200
    client.cookies.clear()
    for _ in range(4):
        assert (
            client.post(
                "/api/auth/anmelden", json={"passwort": "falsch-falsch", "code": "000000"}
            ).status_code
            == 401
        )


# ---------- Sitzung ----------


def test_sitzung_ablauf(client: TestClient, geheimnis: str, uhr: Uhr) -> None:
    uhr.vor(hours=11, minutes=59)
    assert client.get("/api/auth/status").json()["angemeldet"] is True
    uhr.vor(minutes=2)
    assert client.get("/api/auth/status").json()["angemeldet"] is False
    assert client.post("/api/auth/abmelden").status_code == 401


def test_abmelden_beendet_die_sitzung(app: FastAPI, client: TestClient, geheimnis: str) -> None:
    cookie = client.cookies.get("missa_control_sitzung")
    assert cookie
    assert client.post("/api/auth/abmelden").status_code == 200
    # Auch ein kopierter Cookie ist danach wertlos.
    with TestClient(app, cookies={"missa_control_sitzung": cookie}) as kopie:
        assert kopie.get("/api/auth/status").json()["angemeldet"] is False
        assert kopie.post("/api/auth/abmelden").status_code == 401


def test_cookie_ist_httponly_und_samesite(client: TestClient, uhr: Uhr) -> None:
    geheimnis = client.post("/api/auth/einrichten", json={"passwort": PASSWORT}).json()["geheimnis"]
    antwort = client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    cookie = next(c for c in antwort.headers.get_list("set-cookie") if c.startswith("missa_control_sitzung="))
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=43200" in cookie
    assert "Secure" not in cookie  # Aufruf über http im lokalen Netz


def test_cookie_ist_secure_ueber_https(app: FastAPI, uhr: Uhr) -> None:
    with TestClient(app, base_url="https://panel.example") as client:
        geheimnis = client.post("/api/auth/einrichten", json={"passwort": PASSWORT}).json()["geheimnis"]
        antwort = client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    cookie = next(c for c in antwort.headers.get_list("set-cookie") if c.startswith("missa_control_sitzung="))
    assert "Secure" in cookie


# ---------- Gespeicherte Daten ----------


def test_passwort_und_geheimnis_nicht_im_klartext_gespeichert(
    client: TestClient, uhr: Uhr, einstellungen: Einstellungen
) -> None:
    geheimnis = einrichten(client, uhr)
    token = client.cookies.get("missa_control_sitzung")
    assert token
    inhalt = b"".join(datei.read_bytes() for datei in einstellungen.daten_ordner.glob("missa-control.db*"))
    assert PASSWORT.encode() not in inhalt
    assert geheimnis.encode() not in inhalt
    assert token.encode() not in inhalt
    assert b"$argon2id$" in inhalt


# ---------- Einstellungen ----------


def test_fehlende_schluessel_geben_klare_meldung(tmp_path) -> None:
    with pytest.raises(EinstellungsFehler, match=r"install\.sh"):
        Einstellungen(secret_key="", encryption_key="", daten_ordner=tmp_path)
    with pytest.raises(EinstellungsFehler, match="ENCRYPTION_KEY"):
        Einstellungen(secret_key="x" * 40, encryption_key="kein-fernet-schluessel", daten_ordner=tmp_path)
