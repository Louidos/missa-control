"""Missa Control – lokales Admin- und Integrations-Panel für die KI-Assistentin Missa."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("missa-control")
except PackageNotFoundError:  # pragma: no cover - nur ohne Installation des Pakets
    __version__ = "0.0.0"

__all__ = ["__version__"]
