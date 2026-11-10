"""Datenbank: SQLite in `data/missa-control.db`, Schema-Änderungen über Alembic-Migrationen."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

MIGRATIONS_ORDNER = Path(__file__).parent / "migrations"


class Base(DeclarativeBase):
    """Basisklasse aller Tabellen."""


class UTCDateTime(TypeDecorator[datetime]):
    """Zeitpunkt in UTC. SQLite kennt keine Zeitzonen, deshalb wird beim Lesen UTC ergänzt."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Zeitpunkte müssen eine Zeitzone haben (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Datenbank:
    def __init__(self, pfad: Path) -> None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        self.pfad = pfad
        self.engine: Engine = create_engine(
            f"sqlite:///{pfad}", connect_args={"check_same_thread": False, "timeout": 15}
        )
        event.listen(self.engine, "connect", _sqlite_einstellen)
        self.sitzung = sessionmaker(self.engine, expire_on_commit=False)

    def migrieren(self) -> None:
        """Bringt das Schema auf den neuesten Stand (wird bei jedem Start ausgeführt)."""
        konfig = Config()
        konfig.set_main_option("script_location", str(MIGRATIONS_ORDNER))
        with self.engine.begin() as verbindung:
            konfig.attributes["connection"] = verbindung
            command.upgrade(konfig, "head")

    def schliessen(self) -> None:
        self.engine.dispose()


def _sqlite_einstellen(dbapi_verbindung: Any, _: Any) -> None:
    cursor = dbapi_verbindung.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI-Abhängigkeit: eine Datenbank-Sitzung pro Anfrage."""
    datenbank: Datenbank = request.app.state.datenbank
    with datenbank.sitzung() as sitzung:
        yield sitzung
