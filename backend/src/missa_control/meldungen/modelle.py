from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime

# Was gemeldet werden kann – und was ein neues Ziel standardmässig meldet.
MELDE_ARTEN: dict[str, tuple[str, bool]] = {
    "freigabe": ("Freigabe wartet", True),
    "integration": ("Integration ausgefallen / wieder da", True),
    "geraet_offline": ("Gerät offline", False),
    "regel_hoch": ("Regel ausgelöst (Dringlichkeit hoch oder dringend)", False),
}
ZIEL_ARTEN = {"ntfy": "ntfy", "webhook": "Webhook"}


class Meldeziel(Base):
    """Wohin das Panel Meldungen schickt: ein ntfy-Thema oder ein Webhook (JSON per POST)."""

    __tablename__ = "meldeziele"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    art: Mapped[str] = mapped_column(String)  # ntfy | webhook
    adresse: Mapped[str] = mapped_column(String)
    thema: Mapped[str] = mapped_column(String, default="", server_default="")  # nur ntfy
    zugang_id: Mapped[int | None] = mapped_column(
        ForeignKey("zugaenge.id", ondelete="SET NULL"), nullable=True
    )
    # So ist das Panel im Browser erreichbar – für den Link zur Seite „Freigaben“.
    panel_adresse: Mapped[str] = mapped_column(String, default="", server_default="")
    arten: Mapped[list[str]] = mapped_column(JSON, default=list)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    letzter_fehler: Mapped[str] = mapped_column(Text, default="", server_default="")
    letzter_fehler_zeit: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    zuletzt_gesendet: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
