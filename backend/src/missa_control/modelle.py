"""Sammelt alle Tabellen, damit Migrationen und Tests das ganze Schema kennen."""

from missa_control.auth.modelle import Admin, Sitzung

__all__ = ["Admin", "Sitzung"]
