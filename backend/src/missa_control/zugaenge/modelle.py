from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime

TYP_API_KEY = "api_key"
TYP_BENUTZER_PASSWORT = "benutzer_passwort"
TYP_BEARER_TOKEN = "bearer_token"
TYPEN = (TYP_API_KEY, TYP_BENUTZER_PASSWORT, TYP_BEARER_TOKEN)


class Zugang(Base):
    __tablename__ = "zugaenge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    typ: Mapped[str] = mapped_column(String)
    # Benutzername bei "Benutzer + Passwort" – kein Geheimnis, deshalb lesbar.
    benutzer: Mapped[str | None] = mapped_column(String, nullable=True)
    # Das eigentliche Geheimnis (Key, Token oder Passwort), mit ENCRYPTION_KEY verschlüsselt.
    wert_verschluesselt: Mapped[str] = mapped_column(Text)
    notiz: Mapped[str] = mapped_column(Text, default="")
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    geaendert: Mapped[datetime] = mapped_column(UTCDateTime)
