"""Alembic-Umgebung. Die Verbindung kommt von `Datenbank.migrieren()`."""

from alembic import context

from missa_control import modelle  # noqa: F401 - registriert alle Tabellen
from missa_control.db import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    verbindung = context.config.attributes["connection"]
    context.configure(connection=verbindung, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
