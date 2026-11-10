from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class Modell(Base):
    """Ein Modell-Endpunkt (OpenAI-kompatibel), z. B. ein lokaler vLLM- oder Ollama-Server."""

    __tablename__ = "modelle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    # Basis-URL bis einschliesslich /v1, z. B. http://192.168.1.30:8000/v1
    url: Mapped[str] = mapped_column(String)
    zugang_id: Mapped[int | None] = mapped_column(
        ForeignKey("zugaenge.id", ondelete="SET NULL"), nullable=True
    )
    # Name des Modells beim Endpunkt, z. B. "qwen2.5:32b"
    modellname: Mapped[str] = mapped_column(String)
    kontextlaenge: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Ergebnis des letzten Verbindungstests
    test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    test_meldung: Mapped[str] = mapped_column(Text, default="")
    test_hinweis: Mapped[str] = mapped_column(Text, default="")
    test_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_tokens_pro_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    getestet: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    geaendert: Mapped[datetime] = mapped_column(UTCDateTime)


class Rolle(Base):
    """Eine Aufgabe für ein Modell. Clients verwenden den festen Namen `missa-<kennung>`."""

    __tablename__ = "modell_rollen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kennung: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    haupt_modell_id: Mapped[int | None] = mapped_column(
        ForeignKey("modelle.id", ondelete="SET NULL"), nullable=True
    )
    ersatz_modell_id: Mapped[int | None] = mapped_column(
        ForeignKey("modelle.id", ondelete="SET NULL"), nullable=True
    )
    # Die Rollen „schnell“ und „stark“ gibt es immer.
    fest: Mapped[bool] = mapped_column(Boolean, default=False)


class ModellAnfrage(Base):
    """Eine Anfrage an ein Modell – Grundlage der Statistik (7 Tage)."""

    __tablename__ = "modell_anfragen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    modell_id: Mapped[int] = mapped_column(Integer, index=True)
    rolle: Mapped[str] = mapped_column(String, default="")
    ok: Mapped[bool] = mapped_column(Boolean)
    dauer_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_pro_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True, wenn dieses Modell als Ersatz eingesprungen ist.
    ersatz: Mapped[bool] = mapped_column(Boolean, default=False)
    fehler: Mapped[str] = mapped_column(Text, default="")
