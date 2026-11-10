from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime

DRINGLICHKEITEN = ("niedrig", "normal", "hoch", "dringend")


class Ereignis(Base):
    __tablename__ = "ereignisse"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    # Art des Ereignisses, z. B. regel, geraet, webhook, integration_ausgefallen, freigabe, test
    art: Mapped[str] = mapped_column(String, index=True)
    quelle: Mapped[str] = mapped_column(String, default="")
    titel: Mapped[str] = mapped_column(String)
    nachricht: Mapped[str] = mapped_column(Text, default="")
    dringlichkeit: Mapped[str] = mapped_column(String, default="normal")
    daten: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = ({"sqlite_autoincrement": True},)  # Nummern werden nie wiederverwendet
