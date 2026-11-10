"""Das Beispiel aus docs/eigene-integration.md muss wirklich funktionieren – und kurz bleiben."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from missa_control.config import Einstellungen
from server import LaufenderServer

DOKU = Path(__file__).resolve().parents[2] / "docs" / "eigene-integration.md"


def _block(sprache: str, nach: str) -> str:
    text = DOKU.read_text(encoding="utf-8")
    treffer = re.search(rf"```{sprache}\n(.*?)```", text[text.index(nach) :], re.DOTALL)
    assert treffer, f"Kein {sprache}-Block nach „{nach}“"
    return treffer.group(1)


def test_beispiel_aus_der_doku_laeuft(angemeldet: TestClient, einstellungen: Einstellungen) -> None:
    manifest = _block("yaml", "`integration.yaml`:")
    code = _block("python", "`main.py`")
    zeilen = code.rstrip("\n").splitlines()  # alle Zeilen, auch die leeren
    assert len(zeilen) < 30, "Das Beispiel soll unter 30 Zeilen Python bleiben"
    assert f"({len(zeilen)} Zeilen)" in DOKU.read_text(encoding="utf-8")

    ordner = einstellungen.eigene_integrationen_ordner / "erreichbar"
    ordner.mkdir(parents=True)
    (ordner / "integration.yaml").write_text(manifest, encoding="utf-8")
    (ordner / "main.py").write_text(code, encoding="utf-8")
    assert angemeldet.post("/api/katalog/einlesen").json()["probleme"] == []

    dienst = FastAPI()

    @dienst.get("/")
    def start() -> dict[str, bool]:
        return {"ok": True}

    with LaufenderServer(dienst) as server:
        konfig = {"adresse": server.url}
        test = angemeldet.post(
            "/api/integrationen/testen", json={"manifest_id": "erreichbar", "konfig": konfig}
        ).json()
        assert test["ok"] is True, test
        assert test["meldung"] == "Dienst antwortet mit Status 200."
        assert {f["name"]: f["recht"] for f in test["funktionen"]} == {
            "dienst_pruefen": "erlaubt",
            "notiz_merken": "nachfragen",
        }
        integration = angemeldet.post(
            "/api/integrationen",
            json={"manifest_id": "erreichbar", "konfig": konfig, "test_id": test["test_id"]},
        ).json()
        namen = sorted(f["gateway_name"] for f in integration["funktionen"])
        assert namen == ["erreichbarkeit_dienst_pruefen", "erreichbarkeit_notiz_merken"]
        parameter = next(f for f in integration["funktionen"] if f["name"] == "dienst_pruefen")["parameter"]
        assert (
            parameter["properties"]["pfad"]["description"]
            == "Unterseite, die geprüft werden soll, z. B. /status"
        )

        def aufrufen(funktion: str, **argumente: str) -> dict:
            return angemeldet.post(
                f"/api/integrationen/{integration['id']}/aufrufen",
                json={"funktion": funktion, "argumente": argumente},
            ).json()

        assert '"erreichbar": true' in aufrufen("dienst_pruefen")["ergebnis"]
        assert '"status": 404' in aufrufen("dienst_pruefen", pfad="/gibt-es-nicht")["ergebnis"]
        assert aufrufen("notiz_merken", text="Läuft seit Montag")["ergebnis"] == "1 Notiz(en) gespeichert."
        assert aufrufen("notiz_merken", text="Neustart am Freitag")["ergebnis"] == "2 Notiz(en) gespeichert."


def test_vorlage_entspricht_der_doku() -> None:
    """Die Doku verweist auf die Vorlage – die muss es geben und sie muss die genannten Dateien enthalten."""
    vorlage = DOKU.parents[1] / "integrations" / "_vorlage"
    assert (vorlage / "integration.yaml").is_file()
    assert (vorlage / "main.py").is_file()
    assert "integrations/_vorlage/" in DOKU.read_text(encoding="utf-8")
