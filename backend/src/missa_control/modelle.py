"""Sammelt alle Tabellen, damit Migrationen und Tests das ganze Schema kennen."""

from missa_control.auth.modelle import Admin, Sitzung
from missa_control.clients.modelle import Client
from missa_control.ereignisse.modelle import Ereignis
from missa_control.gateway.modelle import Aufruf, Freigabe
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.modellverwaltung.modelle import Modell, ModellAnfrage, Rolle
from missa_control.zugaenge.modelle import Zugang

__all__ = [
    "Admin",
    "Aufruf",
    "Client",
    "Ereignis",
    "Freigabe",
    "Funktion",
    "Integration",
    "Modell",
    "ModellAnfrage",
    "Rolle",
    "Sitzung",
    "Zugang",
]
