from __future__ import annotations

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base


class KnotenPosition(Base):
    """Wo ein Knoten in der Übersicht liegt, nachdem er von Hand verschoben wurde."""

    __tablename__ = "uebersicht_positionen"

    knoten: Mapped[str] = mapped_column(String, primary_key=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
