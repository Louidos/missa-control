"""Zeit-Helfer: Das Panel rechnet und speichert durchgehend in UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def jetzt() -> datetime:
    """Aktuelle Zeit in UTC (mit Zeitzone)."""
    return datetime.now(UTC)
