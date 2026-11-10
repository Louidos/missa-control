"""Sammelt alle Tabellen, damit Migrationen und Tests das ganze Schema kennen."""

from missa_control.auth.modelle import Admin, Sitzung
from missa_control.clients.modelle import Client
from missa_control.ereignisse.modelle import Ereignis
from missa_control.gateway.modelle import Aufruf, Freigabe
from missa_control.gedaechtnis.modelle import GedaechtnisEintrag
from missa_control.geraete.modelle import Geraet, GeraeteWert
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.modellverwaltung.modelle import Modell, ModellAnfrage, Rolle
from missa_control.profil.modelle import ProfilVersion
from missa_control.regeln.modelle import Ausloesung, Regel
from missa_control.serverlast.modelle import Messwert
from missa_control.telefonie.modelle import Anruf, TelefonieEinstellung
from missa_control.zugaenge.modelle import Zugang

__all__ = [
    "Admin",
    "Anruf",
    "Aufruf",
    "Ausloesung",
    "Client",
    "Ereignis",
    "Freigabe",
    "Funktion",
    "GedaechtnisEintrag",
    "Geraet",
    "GeraeteWert",
    "Integration",
    "Messwert",
    "Modell",
    "ModellAnfrage",
    "ProfilVersion",
    "Regel",
    "Rolle",
    "Sitzung",
    "TelefonieEinstellung",
    "Zugang",
]
