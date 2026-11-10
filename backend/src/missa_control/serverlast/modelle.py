from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class Messwert(Base):
    """Eine Messung der Serverlast (alle 30 Sekunden, 7 Tage aufbewahrt)."""

    __tablename__ = "messwerte"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    cpu: Mapped[float] = mapped_column(Float)
    ram: Mapped[float] = mapped_column(Float)
    speicher: Mapped[float] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_speicher: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
