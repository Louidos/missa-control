from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class Geraet(Base):
    """Ein gekoppeltes Gerät. Name, Rechte und Funktionen stehen in der zugehörigen Integration."""

    __tablename__ = "geraete"

    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrationen.id", ondelete="CASCADE"), primary_key=True
    )
    # Benutzername am MQTT-Broker und zugleich Teil der Themen: missa/geraete/<mqtt_benutzer>/…
    mqtt_benutzer: Mapped[str] = mapped_column(String, unique=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    # Seit wann das Gerät online bzw. offline ist.
    status_seit: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    zuletzt_gesehen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    firmware: Mapped[str] = mapped_column(String, default="")
    # Was das Gerät beim Start gemeldet hat: [{"id": "temperatur", "art": "sensor", "name": …, "einheit": …}, …]
    faehigkeiten: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Letzter Wert je Fähigkeit: {"temperatur": {"wert": 21.5, "zeit": "…"}}
    letzte: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Wann zuletzt Zugangsdaten für das Gerät erzeugt wurden.
    gekoppelt: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class GeraeteWert(Base):
    """Ein gemessener Wert (höchstens einer pro halbe Minute und Fähigkeit, 7 Tage aufbewahrt)."""

    __tablename__ = "geraete_werte"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrationen.id", ondelete="CASCADE"), index=True
    )
    faehigkeit: Mapped[str] = mapped_column(String)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    wert: Mapped[float] = mapped_column(Float)
