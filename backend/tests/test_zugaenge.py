"""Zugänge: verschlüsselt gespeichert, nur maskiert sichtbar, nie im Klartext in Logs oder Antworten."""

from __future__ import annotations

import logging

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from missa_control.config import Einstellungen
from missa_control.krypto import EntschluesselungsFehler, Krypto
from missa_control.main import create_app
from missa_control.zugaenge.dienst import Zugangsdaten, maskieren
from missa_control.zugaenge.schwaerzen import SCHWAERZER

API_KEY = "sk-geheimer-api-key-9f8e7d6c5b4a"
PASSWORT_WERT = "Sup3r-Geh3imes-Passw0rt!"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.geheimer-bearer-token-zyxw"
ALLE_GEHEIMNISSE = (API_KEY, PASSWORT_WERT, TOKEN)


def _anlegen(client: TestClient, **daten: object) -> dict:
    antwort = client.post("/api/zugaenge", json=daten)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_anlegen_zeigt_nur_maskierten_wert(angemeldet: TestClient) -> None:
    zugang = _anlegen(
        angemeldet, name="Wetter-API", typ="api_key", wert=API_KEY, notiz="für die Wetter-Integration"
    )
    assert zugang["maske"] == "••••5b4a"
    assert zugang["typ_name"] == "API-Key"
    assert "wert" not in zugang

    # "Seite neu laden": die Liste liefert ebenfalls nur die Maske.
    liste = angemeldet.get("/api/zugaenge").json()
    assert [eintrag["name"] for eintrag in liste] == ["Wetter-API"]
    assert liste[0]["maske"] == "••••5b4a"
    assert API_KEY not in angemeldet.get("/api/zugaenge").text


def test_benutzer_und_passwort(angemeldet: TestClient) -> None:
    zugang = _anlegen(
        angemeldet, name="Nextcloud", typ="benutzer_passwort", benutzer="missa", wert=PASSWORT_WERT
    )
    assert zugang["benutzer"] == "missa"  # der Benutzername ist kein Geheimnis
    assert zugang["maske"] == "••••ort!"

    ohne_benutzer = angemeldet.post(
        "/api/zugaenge", json={"name": "Ohne", "typ": "benutzer_passwort", "wert": PASSWORT_WERT}
    )
    assert ohne_benutzer.status_code == 422
    assert "Benutzernamen" in ohne_benutzer.json()["meldung"]


def test_kurze_werte_werden_ganz_verdeckt() -> None:
    assert maskieren("abc") == "••••"
    assert maskieren("1234567") == "••••"
    assert maskieren("12345678") == "••••78"
    assert maskieren("123456789012") == "••••9012"


def test_aendern_ohne_wert_laesst_das_geheimnis_unveraendert(angemeldet: TestClient, app: FastAPI) -> None:
    zugang = _anlegen(angemeldet, name="HA", typ="bearer_token", wert=TOKEN)

    geaendert = angemeldet.put(
        f"/api/zugaenge/{zugang['id']}", json={"name": "Home Assistant", "notiz": "neu"}
    )
    assert geaendert.status_code == 200
    assert geaendert.json()["name"] == "Home Assistant"
    assert geaendert.json()["maske"] == zugang["maske"]

    neuer_token = "ein-ganz-neuer-bearer-token-1234"
    ersetzt = angemeldet.put(f"/api/zugaenge/{zugang['id']}", json={"wert": neuer_token})
    assert ersetzt.json()["maske"] == "••••1234"
    with app.state.datenbank.sitzung() as db:
        assert app.state.zugaenge.klartext(db, zugang["id"]).wert == neuer_token


def test_doppelter_name_und_unbekannter_zugang(angemeldet: TestClient) -> None:
    _anlegen(angemeldet, name="Doppelt", typ="api_key", wert=API_KEY)
    doppelt = angemeldet.post(
        "/api/zugaenge", json={"name": "Doppelt", "typ": "api_key", "wert": "x-anderer-wert"}
    )
    assert doppelt.status_code == 409
    assert "hinweis" in doppelt.json()
    assert angemeldet.put("/api/zugaenge/999", json={"notiz": "x"}).status_code == 404
    assert angemeldet.delete("/api/zugaenge/999").status_code == 404


def test_loeschen(angemeldet: TestClient) -> None:
    zugang = _anlegen(angemeldet, name="Weg", typ="api_key", wert=API_KEY)
    assert angemeldet.delete(f"/api/zugaenge/{zugang['id']}").json() == {"ok": True}
    assert angemeldet.get("/api/zugaenge").json() == []


def test_ohne_login_gesperrt(client: TestClient) -> None:
    assert client.get("/api/zugaenge").status_code == 401
    assert (
        client.post("/api/zugaenge", json={"name": "x", "typ": "api_key", "wert": API_KEY}).status_code == 401
    )


def test_wert_steht_nicht_im_klartext_in_der_datenbank(
    angemeldet: TestClient, einstellungen: Einstellungen
) -> None:
    _anlegen(angemeldet, name="A", typ="api_key", wert=API_KEY)
    _anlegen(angemeldet, name="B", typ="benutzer_passwort", benutzer="missa", wert=PASSWORT_WERT)
    _anlegen(angemeldet, name="C", typ="bearer_token", wert=TOKEN)

    inhalt = b"".join(datei.read_bytes() for datei in einstellungen.daten_ordner.glob("missa-control.db*"))
    assert b"missa" in inhalt  # Benutzername: lesbar gespeichert
    for geheimnis in ALLE_GEHEIMNISSE:
        assert geheimnis.encode() not in inhalt
        assert geheimnis[-8:].encode() not in inhalt  # auch kein lesbares Ende


def test_klartext_nirgends_in_antworten_logs_und_fehlermeldungen(
    angemeldet: TestClient, app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    """Der zentrale Test: Geheimnisse tauchen in keiner API-Antwort, keinem Log, keiner Fehlermeldung auf."""
    caplog.set_level(logging.DEBUG)  # alles mitschneiden, auch von fremden Bibliotheken
    logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)  # inklusive SQL mit Parametern
    antworten: list[str] = []

    def merke(antwort):
        antworten.append(antwort.text)
        antworten.append(str(dict(antwort.headers)))
        return antwort

    try:
        a = merke(
            angemeldet.post("/api/zugaenge", json={"name": "A", "typ": "api_key", "wert": API_KEY})
        ).json()
        b = merke(
            angemeldet.post(
                "/api/zugaenge",
                json={"name": "B", "typ": "benutzer_passwort", "benutzer": "missa", "wert": PASSWORT_WERT},
            )
        ).json()
        merke(angemeldet.post("/api/zugaenge", json={"name": "C", "typ": "bearer_token", "wert": TOKEN}))
        merke(angemeldet.get("/api/zugaenge"))
        merke(angemeldet.put(f"/api/zugaenge/{a['id']}", json={"notiz": "geändert"}))
        merke(angemeldet.put(f"/api/zugaenge/{b['id']}", json={"wert": PASSWORT_WERT + "-neu"}))

        # Fehlerfälle, bei denen der Wert in der Anfrage steht:
        merke(
            angemeldet.post("/api/zugaenge", json={"name": "A", "typ": "api_key", "wert": API_KEY})
        )  # doppelt
        merke(angemeldet.post("/api/zugaenge", json={"name": "D", "typ": "gibt-es-nicht", "wert": TOKEN}))
        merke(angemeldet.post("/api/zugaenge", json={"name": "", "typ": "api_key", "wert": API_KEY}))
        merke(angemeldet.post("/api/zugaenge", json={"name": "E", "typ": "api_key", "wert": {"x": API_KEY}}))
        merke(angemeldet.post("/api/zugaenge", json={"typ": "benutzer_passwort", "wert": PASSWORT_WERT}))
        merke(angemeldet.put("/api/zugaenge/999", json={"wert": TOKEN}))
        merke(angemeldet.put(f"/api/zugaenge/{a['id']}", json={"name": "B", "wert": API_KEY}))
        merke(angemeldet.post("/api/zugaenge", content=f'{{"name": "kaputt", "wert": "{API_KEY}"'))

        # Interne Verwendung (wie später durch Integrationen), inklusive versehentlichem Loggen:
        with app.state.datenbank.sitzung() as db:
            daten = app.state.zugaenge.klartext(db, a["id"])
        assert daten.wert == API_KEY
        logging.getLogger("fremde.bibliothek").warning(
            "Anfrage an https://api.example/?key=%s fehlgeschlagen", API_KEY
        )
        logging.getLogger("missa_control").info("Zugangsdaten: %r / %s", daten, daten)
        try:
            raise RuntimeError(f"Verbindung mit Token {TOKEN} abgelehnt")
        except RuntimeError:
            logging.getLogger("missa_control").exception("Fehler beim Aufruf")

        merke(angemeldet.delete(f"/api/zugaenge/{a['id']}"))
    finally:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.NOTSET)

    log_text = caplog.text + "\n".join(
        (eintrag.exc_text or "") + eintrag.getMessage() for eintrag in caplog.records
    )
    assert "INSERT INTO zugaenge" in log_text  # SQL wurde wirklich mitgeschnitten
    assert "fehlgeschlagen" in log_text
    for geheimnis in (*ALLE_GEHEIMNISSE, PASSWORT_WERT + "-neu"):
        assert geheimnis not in log_text, "Geheimnis steht in einem Log"
        for text in antworten:
            assert geheimnis not in text, "Geheimnis steht in einer API-Antwort"


def test_zugangsdaten_verraten_sich_nicht_selbst() -> None:
    daten = Zugangsdaten(typ="api_key", wert=API_KEY)
    assert API_KEY not in repr(daten)
    assert API_KEY not in str(daten)
    assert API_KEY not in f"{daten}"


def test_schwaerzer_ersetzt_bekannte_werte() -> None:
    SCHWAERZER.merken("mein-geheimer-wert")
    assert SCHWAERZER.schwaerzen("Fehler bei mein-geheimer-wert!") == "Fehler bei •••!"
    SCHWAERZER.merken("ab")  # zu kurz – würde normale Texte zerstören
    assert SCHWAERZER.schwaerzen("ab hier") == "ab hier"


def test_falscher_schluessel_gibt_keine_daten_preis(
    angemeldet: TestClient, einstellungen: Einstellungen
) -> None:
    _anlegen(angemeldet, name="A", typ="api_key", wert=API_KEY)
    # Dasselbe Panel mit anderem ENCRYPTION_KEY (z. B. .env verloren und neu erzeugt):
    andere = create_app(
        Einstellungen(
            secret_key=einstellungen.secret_key,
            encryption_key=Fernet.generate_key().decode(),
            daten_ordner=einstellungen.daten_ordner,
        )
    )
    with andere.state.datenbank.sitzung() as db:
        liste = andere.state.zugaenge.alle(db)
        assert liste[0]["maske"] == "••••"
        assert liste[0]["lesbar"] is False
        with pytest.raises(EntschluesselungsFehler, match="ENCRYPTION_KEY"):
            andere.state.zugaenge.klartext(db, liste[0]["id"])
    andere.state.datenbank.schliessen()


def test_krypto_verschluesselt_jedes_mal_anders() -> None:
    krypto = Krypto("x" * 40, Fernet.generate_key().decode())
    eins, zwei = krypto.verschluesseln(API_KEY), krypto.verschluesseln(API_KEY)
    assert eins != zwei
    assert API_KEY not in eins
    assert krypto.entschluesseln(eins) == krypto.entschluesseln(zwei) == API_KEY
