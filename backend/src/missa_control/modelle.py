"""Sammelt alle Tabellen, damit Migrationen und Tests das ganze Schema kennen."""

from missa_control.auth.modelle import Admin, Sitzung
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.zugaenge.modelle import Zugang

__all__ = ["Admin", "Funktion", "Integration", "Sitzung", "Zugang"]
