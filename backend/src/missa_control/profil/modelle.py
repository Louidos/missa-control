from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class ProfilVersion(Base):
    """Jede Speicherung des Profils ist eine eigene Version; die neueste gilt."""

    __tablename__ = "profil_versionen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    kommentar: Mapped[str] = mapped_column(Text, default="")
    inhalt: Mapped[dict[str, Any]] = mapped_column(JSON)
