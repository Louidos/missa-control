"""Stellt sicher, dass Migrationen und Tabellen-Definitionen zusammenpassen."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI

from missa_control import modelle  # noqa: F401 - registriert alle Tabellen
from missa_control.db import Base


def test_migrationen_passen_zu_den_tabellen(app: FastAPI) -> None:
    with app.state.datenbank.engine.connect() as verbindung:
        kontext = MigrationContext.configure(verbindung, opts={"compare_type": True})
        unterschiede = compare_metadata(kontext, Base.metadata)
    assert unterschiede == [], f"Migration fehlt für: {unterschiede}"


def test_migrieren_ist_wiederholbar(app: FastAPI) -> None:
    app.state.datenbank.migrieren()
    app.state.datenbank.migrieren()
