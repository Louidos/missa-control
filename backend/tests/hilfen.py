"""Helfer für Tests: stellbare Uhr und Abkürzungen für Einrichtung und Codes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
from fastapi.testclient import TestClient

PASSWORT = "ein-langes-test-passwort"


class Uhr:
    """Ersetzt die Systemzeit des Panels, damit Tests Zeit vergehen lassen können."""

    def __init__(self) -> None:
        self.jetzt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.jetzt

    def vor(self, **zeitraum: float) -> None:
        self.jetzt += timedelta(**zeitraum)


def code_fuer(geheimnis: str, uhr: Uhr) -> str:
    """Der Code, den die Authenticator-App gerade anzeigen würde."""
    return pyotp.TOTP(geheimnis).at(int(uhr.jetzt.timestamp()))


def einrichten(client: TestClient, uhr: Uhr, passwort: str = PASSWORT) -> str:
    """Führt die Einrichtung durch (danach ist der Client angemeldet) und gibt das 2FA-Geheimnis zurück."""
    antwort = client.post("/api/auth/einrichten", json={"passwort": passwort})
    assert antwort.status_code == 200, antwort.text
    geheimnis = antwort.json()["geheimnis"]
    antwort = client.post("/api/auth/einrichten/bestaetigen", json={"code": code_fuer(geheimnis, uhr)})
    assert antwort.status_code == 200, antwort.text
    return geheimnis
