from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class Admin(Base):
    """Der einzige Benutzer des Panels (es gibt bewusst keine Benutzerverwaltung)."""

    __tablename__ = "admin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passwort_hash: Mapped[str] = mapped_column(String)
    totp_geheimnis: Mapped[str] = mapped_column(String)  # verschlüsselt
    eingerichtet: Mapped[bool] = mapped_column(Boolean, default=False)
    # Nach dem Notfall-Reset (scripts/reset-2fa.sh): Die Zwei-Faktor-Anmeldung wird neu eingerichtet –
    # dafür braucht es das bisherige Passwort.
    zwei_faktor_neu: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Nur der Browser, der die Einrichtung begonnen hat, darf sie abschliessen.
    einrichtung_pruefsumme: Mapped[str | None] = mapped_column(String, nullable=True)
    # Letzter verwendeter 30-Sekunden-Schritt: derselbe Code gilt nicht zweimal.
    totp_letzter_schritt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fehlversuche: Mapped[int] = mapped_column(Integer, default=0)
    gesperrt_bis: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)


class Sitzung(Base):
    __tablename__ = "sitzungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_pruefsumme: Mapped[str] = mapped_column(String, unique=True, index=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    laeuft_ab: Mapped[datetime] = mapped_column(UTCDateTime)
