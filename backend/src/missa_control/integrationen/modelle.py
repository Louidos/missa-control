from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from missa_control.db import Base, UTCDateTime


class Integration(Base):
    """Eine eingerichtete Integration: ein Katalog-Eintrag plus ausgefülltes Formular."""

    __tablename__ = "integrationen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manifest_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    # Vorsilbe der Funktionsnamen am Gateway, z. B. "kalender" → kalender_termine_anzeigen
    kennung: Mapped[str] = mapped_column(String, unique=True)
    # Formularwerte; Felder vom Typ "zugang" enthalten die Nummer des Zugangs, nie den Wert.
    konfig: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Was sich die Integration selbst merkt (z. B. welche Verbindungsart funktioniert).
    zustand: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="ungetestet")
    status_meldung: Mapped[str] = mapped_column(Text, default="")
    status_hinweis: Mapped[str] = mapped_column(Text, default="")
    geprueft: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    geaendert: Mapped[datetime] = mapped_column(UTCDateTime)

    funktionen: Mapped[list[Funktion]] = relationship(
        back_populates="integration", cascade="all, delete-orphan", order_by="Funktion.name"
    )


class Funktion(Base):
    """Eine Funktion einer eingerichteten Integration mit ihrem Recht."""

    __tablename__ = "funktionen"
    __table_args__ = (UniqueConstraint("integration_id", "name", name="uq_funktionen_integration_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrationen.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    parameter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schreibend: Mapped[bool] = mapped_column(Boolean, default=True)
    recht: Mapped[str] = mapped_column(String, default="nachfragen")
    # False, wenn die Integration die Funktion beim letzten Test nicht mehr angeboten hat.
    vorhanden: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    integration: Mapped[Integration] = relationship(back_populates="funktionen")
