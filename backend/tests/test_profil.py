"""Charakterprofil: bearbeiten, Versionen, Unterschiede, YAML, Test-Chat und Abruf für Clients."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from hilfen import Uhr, einrichten
from missa_control.config import Einstellungen
from missa_control.main import create_app
from missa_control.profil.dienst import Profil, profil_als_yaml, profil_aus_yaml, systemprompt_bauen
from server import LaufenderServer, modell_server

pytestmark = pytest.mark.anyio

PROFIL = {
    "name": "Missa",
    "aussprache": "Mi-ssa",
    "wesen": "Aufmerksam und warmherzig.\nMit trockenem Humor.",
    "sprechweise": "Kurz und natürlich.",
    "darf": ["Termine nachschlagen", "Rückfragen stellen"],
    "darf_nicht": ["Etwas ohne Auftrag löschen"],
    "fremde": "Höflich, aber zurückhaltend.",
    "systemprompt": "Antworte immer auf Deutsch.",
}


def _speichern(client: TestClient, kommentar: str = "", **aenderung: Any) -> dict[str, Any]:
    antwort = client.put("/api/profil", json={"profil": {**PROFIL, **aenderung}, "kommentar": kommentar})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_bearbeiten_speichern_neu_laden(angemeldet: TestClient) -> None:
    """Fertig-wenn: Bearbeiten, speichern, neu laden: Änderung ist da."""
    leer = angemeldet.get("/api/profil").json()
    assert leer["version"] is None
    assert leer["profil"]["name"] == "Missa"
    assert leer["systemprompt"] == "Du bist Missa."

    gespeichert = _speichern(angemeldet, kommentar="Erste Fassung")
    assert gespeichert["unveraendert"] is False
    assert gespeichert["version"]["kommentar"] == "Erste Fassung"

    geladen = angemeldet.get("/api/profil").json()  # „neu laden“
    assert geladen["profil"] == PROFIL
    assert geladen["version"]["id"] == gespeichert["version"]["id"]

    # Speichern ohne Änderung erzeugt keine neue Version.
    nochmal = _speichern(angemeldet)
    assert nochmal["unveraendert"] is True
    assert len(angemeldet.get("/api/profil/versionen").json()) == 1

    # Leere Regeln werden beim Speichern entfernt.
    bereinigt = _speichern(angemeldet, darf=["Termine nachschlagen", "  ", ""])
    assert bereinigt["profil"]["darf"] == ["Termine nachschlagen"]


def test_systemprompt_wird_aus_den_feldern_zusammengesetzt() -> None:
    prompt = systemprompt_bauen(Profil.model_validate(PROFIL))
    assert prompt == (
        "Du bist Missa. Dein Name wird so ausgesprochen: Mi-ssa.\n\n"
        "Dein Wesen:\nAufmerksam und warmherzig.\nMit trockenem Humor.\n\n"
        "So sprichst du:\nKurz und natürlich.\n\n"
        "Das darfst du:\n- Termine nachschlagen\n- Rückfragen stellen\n\n"
        "Das darfst du nicht:\n- Etwas ohne Auftrag löschen\n\n"
        "So verhältst du dich gegenüber Fremden:\nHöflich, aber zurückhaltend.\n\n"
        "Antworte immer auf Deutsch."
    )
    assert systemprompt_bauen(Profil(name="Mia", systemprompt="Nur das.")) == "Du bist Mia.\n\nNur das."


def test_vorschau_zeigt_den_prompt_des_ungespeicherten_profils(angemeldet: TestClient) -> None:
    vorschau = angemeldet.post("/api/profil/vorschau", json={**PROFIL, "name": "Mia"}).json()
    assert vorschau["systemprompt"].startswith("Du bist Mia.")
    assert angemeldet.get("/api/profil").json()["version"] is None  # nichts gespeichert


def test_versionsverlauf_unterschiede_und_wiederherstellen(angemeldet: TestClient, uhr: Uhr) -> None:
    """Fertig-wenn: Alte Version wiederherstellen funktioniert."""
    erste = _speichern(angemeldet, kommentar="Erste Fassung")["version"]
    uhr.vor(minutes=5)
    zweite = _speichern(
        angemeldet,
        kommentar="Frecher",
        wesen="Aufmerksam und warmherzig.\nFrech und direkt.",
        darf_nicht=["Etwas ohne Auftrag löschen", "Lügen"],
    )["version"]

    versionen = angemeldet.get("/api/profil/versionen").json()
    assert [(v["id"], v["kommentar"]) for v in versionen] == [
        (zweite["id"], "Frecher"),
        (erste["id"], "Erste Fassung"),
    ]
    assert versionen[0]["erstellt"] > versionen[1]["erstellt"]

    alt = angemeldet.get(f"/api/profil/versionen/{erste['id']}").json()
    assert alt["profil"]["wesen"] == PROFIL["wesen"]
    nach_feld = {u["feld"]: u for u in alt["unterschiede"]}
    assert set(nach_feld) == {"wesen", "darf_nicht"}  # nur geänderte Felder
    assert nach_feld["wesen"]["titel"] == "Wesen"
    assert nach_feld["wesen"]["zeilen"] == [
        {"art": "gleich", "text": "Aufmerksam und warmherzig."},
        {"art": "entfernt", "text": "Mit trockenem Humor."},
        {"art": "neu", "text": "Frech und direkt."},
    ]
    assert nach_feld["darf_nicht"]["zeilen"][-1] == {"art": "neu", "text": "Lügen"}
    assert angemeldet.get(f"/api/profil/versionen/{zweite['id']}").json()["unterschiede"] == []

    uhr.vor(minutes=5)
    wieder = angemeldet.post(f"/api/profil/versionen/{erste['id']}/wiederherstellen").json()
    assert wieder["profil"] == PROFIL
    assert wieder["version"]["kommentar"].startswith("Wiederhergestellt: Version vom 15.01.2026 12:00")
    assert len(angemeldet.get("/api/profil/versionen").json()) == 3  # der Verlauf bleibt vollständig
    assert angemeldet.get("/api/profil/versionen/999").status_code == 404


def test_yaml_export_und_import(angemeldet: TestClient) -> None:
    _speichern(angemeldet)
    export = angemeldet.get("/api/profil/export")
    assert export.headers["content-disposition"] == 'attachment; filename="missa-profil.yaml"'
    assert "wesen: |" in export.text  # mehrzeilige Texte bleiben lesbar
    assert "regeln:\n  darf:\n  - Termine nachschlagen" in export.text
    assert "darf_nicht:\n  - Etwas ohne Auftrag löschen" in export.text

    eingelesen = angemeldet.post("/api/profil/import", json={"yaml": export.text})
    assert eingelesen.status_code == 200
    assert eingelesen.json()["profil"] == PROFIL  # verlustfrei hin und zurück
    assert profil_aus_yaml(profil_als_yaml(Profil.model_validate(PROFIL))) == Profil.model_validate(PROFIL)

    # Import speichert nicht von selbst.
    geaendert = export.text.replace("name: Missa", "name: Mia")
    assert angemeldet.post("/api/profil/import", json={"yaml": geaendert}).json()["profil"]["name"] == "Mia"
    assert angemeldet.get("/api/profil").json()["profil"]["name"] == "Missa"


@pytest.mark.parametrize(
    ("inhalt", "meldung"),
    [
        ("name: [unfertig", "kein gültiges YAML in Zeile"),
        ("- nur\n- eine\n- liste", "enthält kein Profil"),
        ("name: Missa\nlaune: gut", "„laune“ ist kein bekannter Eintrag"),
        ("name: Missa\nregeln: alles", "„regeln“ muss die Einträge „darf“ und „darf_nicht“ enthalten"),
    ],
)
def test_import_erklaert_fehler(angemeldet: TestClient, inhalt: str, meldung: str) -> None:
    antwort = angemeldet.post("/api/profil/import", json={"yaml": inhalt})
    assert antwort.status_code == 422
    assert meldung in antwort.json()["meldung"]


def test_beispielprofil_ist_gueltig_und_laesst_sich_laden(angemeldet: TestClient) -> None:
    beispiel = angemeldet.get("/api/profil/beispiel")
    assert beispiel.status_code == 200
    profil = beispiel.json()["profil"]
    assert profil["name"] == "Missa"
    assert len(profil["darf"]) >= 2
    assert len(profil["darf_nicht"]) >= 2
    assert profil["fremde"]
    datei = Path(__file__).resolve().parents[2] / "config" / "profil.example.yaml"
    assert profil_aus_yaml(datei.read_text(encoding="utf-8")).model_dump() == profil


# ====================================================================== Test-Chat


def _rolle_mit_modell(
    admin: TestClient, server: LaufenderServer, modellname: str, rolle: str = "schnell"
) -> None:
    modell = admin.post(
        "/api/modelle", json={"name": modellname, "url": server.url + "/v1", "modellname": modellname}
    )
    rollen = admin.get("/api/modelle").json()["rollen"]
    rolle_id = next(r["id"] for r in rollen if r["kennung"] == rolle)
    assert (
        admin.put(f"/api/rollen/{rolle_id}", json={"haupt_modell_id": modell.json()["id"]}).status_code == 200
    )


def test_testchat_antwortet_mit_dem_ungespeicherten_profil(angemeldet: TestClient) -> None:
    """Fertig-wenn: Test-Chat antwortet mit dem Profil."""
    with (
        LaufenderServer(app_schnell := modell_server("schnell-modell")) as schnell,
        LaufenderServer(app_stark := modell_server("stark-modell")) as stark,
    ):
        _rolle_mit_modell(angemeldet, schnell, "schnell-modell", "schnell")
        _rolle_mit_modell(angemeldet, stark, "stark-modell", "stark")

        profil = {**PROFIL, "wesen": "Du bist heute besonders gut gelaunt."}  # nicht gespeichert
        antwort = angemeldet.post(
            "/api/profil/testchat",
            json={
                "profil": profil,
                "rolle": "schnell",
                "nachrichten": [{"von": "nutzer", "text": "Wer bist du?"}],
            },
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["antwort"] == "Antwort von schnell-modell auf: Wer bist du?"
        assert antwort.json()["modell"] == "schnell-modell"
        assert antwort.json()["dauer_ms"] >= 0

        # Beim Modell kommt das Profil als Systemprompt an – direkt, nicht über missa-core.
        gesendet = app_schnell.state.anfragen[-1]["messages"]
        assert gesendet[0]["role"] == "system"
        assert "Du bist heute besonders gut gelaunt." in gesendet[0]["content"]
        assert "Das darfst du nicht:\n- Etwas ohne Auftrag löschen" in gesendet[0]["content"]
        assert gesendet[1] == {"role": "user", "content": "Wer bist du?"}
        assert angemeldet.get("/api/profil").json()["version"] is None  # der Test-Chat speichert nichts

        # Der Verlauf geht mit, die Rolle ist wählbar.
        verlauf = [
            {"von": "nutzer", "text": "Wer bist du?"},
            {"von": "missa", "text": "Ich bin Missa."},
            {"von": "nutzer", "text": "Und was kannst du?"},
        ]
        zweite = angemeldet.post(
            "/api/profil/testchat", json={"profil": profil, "rolle": "stark", "nachrichten": verlauf}
        )
        assert zweite.json()["modell"] == "stark-modell"
        rollen = [nachricht["role"] for nachricht in app_stark.state.anfragen[-1]["messages"]]
        assert rollen == ["system", "user", "assistant", "user"]


def test_testchat_ohne_modell_und_bei_ausfall_gibt_klare_meldung(angemeldet: TestClient) -> None:
    frage = {"profil": PROFIL, "rolle": "schnell", "nachrichten": [{"von": "nutzer", "text": "Hallo"}]}
    ohne = angemeldet.post("/api/profil/testchat", json=frage)
    assert ohne.status_code == 502
    assert "noch kein Modell ausgewählt" in ohne.json()["meldung"]
    assert "Modelle" in ohne.json()["hinweis"]

    with LaufenderServer(app := modell_server("m")) as server:
        _rolle_mit_modell(angemeldet, server, "m")
        app.state.kaputt = True
        aus = angemeldet.post("/api/profil/testchat", json=frage)
    assert aus.status_code == 502
    assert "Kein Modell der Rolle „schnell“ hat geantwortet" in aus.json()["meldung"]
    assert (
        angemeldet.post("/api/profil/testchat", json={**frage, "rolle": "gibt-es-nicht"}).status_code == 409
    )


def test_testchat_zeitlimit_mit_klarer_meldung(einstellungen: Einstellungen, uhr: Uhr) -> None:
    app = create_app(dataclasses.replace(einstellungen, testchat_sekunden=0.4))
    with TestClient(app) as admin, LaufenderServer(modell_server("lahm", pause=3.0)) as lahm:
        einrichten(admin, uhr)
        _rolle_mit_modell(admin, lahm, "lahm")
        antwort = admin.post(
            "/api/profil/testchat",
            json={"profil": PROFIL, "rolle": "schnell", "nachrichten": [{"von": "nutzer", "text": "Hallo"}]},
        )
    app.state.datenbank.schliessen()
    assert antwort.status_code == 504
    assert antwort.json()["meldung"] == "Das Modell hat nicht innerhalb von 0 Sekunden geantwortet."
    assert "wartet höchstens so lange" in antwort.json()["hinweis"]


def test_standard_zeitlimit_ist_120_sekunden(einstellungen: Einstellungen) -> None:
    assert (
        Einstellungen(
            secret_key=einstellungen.secret_key,
            encryption_key=einstellungen.encryption_key,
            daten_ordner=Path("x"),
        ).testchat_sekunden
        == 120.0
    )


# ====================================================================== Abruf für Clients


async def test_profil_fuer_clients_abrufbar(angemeldet: TestClient, panel: LaufenderServer) -> None:
    token = angemeldet.post("/api/clients", json={"name": "missa-core"}).json()["token"]
    async with httpx2.AsyncClient(base_url=panel.url, headers={"Authorization": f"Bearer {token}"}) as http:
        assert (await http.get("/api/config/profile")).json() == {
            "vorhanden": False,
            "profil": None,
            "systemprompt": None,
            "version": None,
        }
        version = _speichern(angemeldet, kommentar="Für Missa")["version"]
        profil = (await http.get("/api/config/profile")).json()
        assert profil["vorhanden"] is True
        assert profil["profil"] == PROFIL
        assert profil["systemprompt"].startswith("Du bist Missa. Dein Name wird so ausgesprochen: Mi-ssa.")
        assert profil["version"]["id"] == version["id"]
    async with httpx2.AsyncClient(base_url=panel.url) as ohne:
        assert (await ohne.get("/api/config/profile")).status_code == 401
