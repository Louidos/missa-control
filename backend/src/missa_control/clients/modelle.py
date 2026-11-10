from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    # Vom Token wird nur die Prüfsumme gespeichert; der Token selbst ist nur einmal sichtbar.
    token_pruefsumme: Mapped[str] = mapped_column(String, unique=True, index=True)
    # Die ersten Zeichen, damit man Tokens im Panel wiedererkennt.
    token_anfang: Mapped[str] = mapped_column(String)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    zuletzt_gesehen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    widerrufen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
