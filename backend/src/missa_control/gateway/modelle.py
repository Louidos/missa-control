from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime

FREIGABE_OFFEN = "offen"
FREIGABE_ERLAUBT = "erlaubt"
FREIGABE_ABGELEHNT = "abgelehnt"
FREIGABE_ABGELAUFEN = "abgelaufen"


class Freigabe(Base):
    """Ein angehaltener Aufruf, der auf „Erlauben“ oder „Ablehnen“ wartet."""

    __tablename__ = "freigaben"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    laeuft_ab: Mapped[datetime] = mapped_column(UTCDateTime)
    client_name: Mapped[str] = mapped_column(String)
    integration_name: Mapped[str] = mapped_column(String)
    funktion: Mapped[str] = mapped_column(String)  # Name am Gateway
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    # Was genau passieren würde – ein Satz der Integration (z. B. welcher Eintrag gelöscht wird).
    vorschau: Mapped[str] = mapped_column(Text, default="", server_default="")
    argumente: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default=FREIGABE_OFFEN, index=True)
    entschieden: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Aufruf(Base):
    """Ein Eintrag im Protokoll: wer hat wann welche Funktion aufgerufen – ohne Parameter und Geheimnisse."""

    __tablename__ = "aufrufe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    # gateway (ein Client über /mcp), panel (Ausprobieren), regel (Aktion einer Regel)
    quelle: Mapped[str] = mapped_column(String)
    client_name: Mapped[str] = mapped_column(String, default="")
    integration_name: Mapped[str] = mapped_column(String, default="")
    funktion: Mapped[str] = mapped_column(String, index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    fehler: Mapped[str] = mapped_column(Text, default="")
    dauer_ms: Mapped[int] = mapped_column(Integer, default=0)
    # ohne, erlaubt, abgelehnt, abgelaufen
    freigabe: Mapped[str] = mapped_column(String, default="ohne")
