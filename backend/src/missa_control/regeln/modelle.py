from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from missa_control.db import Base, UTCDateTime


class Regel(Base):
    """Eine Regel: Wenn der Auslöser eintritt (und die Bedingung passt), wird die Aktion ausgeführt."""

    __tablename__ = "regeln"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    # Aufbau siehe regeln/pruefung.py – z. B. {"art": "messwert", "messwert": "cpu", "schwelle": 90, …}
    ausloeser: Mapped[dict[str, Any]] = mapped_column(JSON)
    bedingung: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    aktion: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Nach einer Auslösung bleibt die Regel so lange still (gegen Dauer-Alarme).
    ruhezeit_minuten: Mapped[int] = mapped_column(Integer, default=30)
    # missa (über das Gateway angelegt) oder manuell (im Panel)
    quelle: Mapped[str] = mapped_column(String, default="manuell")
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    geaendert: Mapped[datetime] = mapped_column(UTCDateTime)
    zuletzt_ausgeloest: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    ausloesungen: Mapped[list[Ausloesung]] = relationship(
        back_populates="regel", cascade="all, delete-orphan", passive_deletes=True
    )


class Ausloesung(Base):
    """Ein Eintrag im Verlauf: wann hat welche Regel ausgelöst und was kam dabei heraus."""

    __tablename__ = "regel_ausloesungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regel_id: Mapped[int] = mapped_column(ForeignKey("regeln.id", ondelete="CASCADE"), index=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    # Was die Regel ausgelöst hat, z. B. „CPU-Auslastung 93 % (über 90 %)“
    anlass: Mapped[str] = mapped_column(Text, default="")
    # ok, fehler, ruhezeit (in der Ruhezeit übersprungen), bedingung (Bedingung nicht erfüllt)
    ergebnis: Mapped[str] = mapped_column(String)
    meldung: Mapped[str] = mapped_column(Text, default="")
    # Auslösung über „Jetzt testen“
    test: Mapped[bool] = mapped_column(Boolean, default=False)

    regel: Mapped[Regel] = relationship(back_populates="ausloesungen")
