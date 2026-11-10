from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from missa_control import __version__
from missa_control.config import Einstellungen
from missa_control.main import create_app


def test_health_antwortet_ohne_anmeldung(client: TestClient) -> None:
    antwort = client.get("/api/health")
    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok", "version": __version__}


def test_datenbank_liegt_im_datenordner(app: FastAPI, einstellungen: Einstellungen) -> None:
    assert (einstellungen.daten_ordner / "missa-control.db").is_file()


def _app_mit_frontend(einstellungen: Einstellungen, tmp_path: Path) -> FastAPI:
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>Missa Control</html>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("console.log('hallo')", encoding="utf-8")
    (tmp_path / "geheim.txt").write_text("geheim", encoding="utf-8")
    return create_app(
        Einstellungen(
            secret_key=einstellungen.secret_key,
            encryption_key=einstellungen.encryption_key,
            daten_ordner=einstellungen.daten_ordner,
            frontend_ordner=frontend,
        )
    )


def test_frontend_wird_ausgeliefert(einstellungen: Einstellungen, tmp_path: Path) -> None:
    client = TestClient(_app_mit_frontend(einstellungen, tmp_path))

    assert "Missa Control" in client.get("/").text
    assert "hallo" in client.get("/assets/app.js").text
    # Unbekannte Seiten bekommen die Oberfläche (Single-Page-App), damit der Login erscheint.
    assert "Missa Control" in client.get("/katalog").text


def test_frontend_verlaesst_ordner_nicht(einstellungen: Einstellungen, tmp_path: Path) -> None:
    client = TestClient(_app_mit_frontend(einstellungen, tmp_path))
    antwort = client.get("/%2e%2e/geheim.txt")
    assert antwort.text == "<html>Missa Control</html>"


def test_sicherheits_header_gesetzt(einstellungen: Einstellungen, tmp_path: Path) -> None:
    client = TestClient(_app_mit_frontend(einstellungen, tmp_path))
    for pfad in ("/", "/api/health", "/api/gibt-es-nicht"):
        headers = client.get(pfad).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in headers["content-security-policy"]
