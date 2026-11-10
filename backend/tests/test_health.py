from pathlib import Path

from fastapi.testclient import TestClient

from missa_control import __version__
from missa_control.config import Einstellungen
from missa_control.main import create_app


def _einstellungen(tmp_path: Path, frontend: Path | None = None) -> Einstellungen:
    return Einstellungen(
        host="127.0.0.1", port=8090, daten_ordner=tmp_path / "data", frontend_ordner=frontend
    )


def test_health_antwortet(tmp_path: Path) -> None:
    client = TestClient(create_app(_einstellungen(tmp_path)))
    antwort = client.get("/api/health")
    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok", "version": __version__}


def test_frontend_wird_ausgeliefert(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>Missa Control</html>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("console.log('hallo')", encoding="utf-8")
    client = TestClient(create_app(_einstellungen(tmp_path, frontend)))

    assert "Missa Control" in client.get("/").text
    assert "hallo" in client.get("/assets/app.js").text
    # Unbekannte Seiten bekommen die Oberfläche (Single-Page-App) …
    assert "Missa Control" in client.get("/katalog").text
    # … unbekannte API-Pfade aber nicht.
    assert client.get("/api/gibt-es-nicht").status_code == 404


def test_frontend_verlaesst_ordner_nicht(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>Missa Control</html>", encoding="utf-8")
    (tmp_path / "geheim.txt").write_text("geheim", encoding="utf-8")
    client = TestClient(create_app(_einstellungen(tmp_path, frontend)))

    antwort = client.get("/%2e%2e/geheim.txt")
    assert antwort.text == "<html>Missa Control</html>"
