"""Gemeinsame Test-Helfer: eine frische App mit eigener Datenbank pro Test und eine stellbare Uhr."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hilfen import Uhr, einrichten
from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.main import create_app


@pytest.fixture
def uhr(monkeypatch: pytest.MonkeyPatch) -> Uhr:
    uhr = Uhr()
    monkeypatch.setattr(zeit, "jetzt", uhr)
    return uhr


@pytest.fixture
def einstellungen(tmp_path: Path) -> Einstellungen:
    return Einstellungen(
        secret_key="test-secret-key-" + "x" * 32,
        encryption_key=Fernet.generate_key().decode(),
        daten_ordner=tmp_path / "data",
    )


@pytest.fixture
def app(einstellungen: Einstellungen, uhr: Uhr) -> Iterator[FastAPI]:
    app = create_app(einstellungen)
    yield app
    app.state.datenbank.schliessen()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def geheimnis(client: TestClient, uhr: Uhr) -> str:
    """Richtet das Panel ein; der `client` ist danach angemeldet."""
    return einrichten(client, uhr)


@pytest.fixture
def angemeldet(client: TestClient, geheimnis: str) -> TestClient:
    return client
