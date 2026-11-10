"""Gemeinsame Begriffe des Integrations-Frameworks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Recht = Literal["erlaubt", "nachfragen", "gesperrt"]
RECHTE: tuple[Recht, ...] = ("erlaubt", "nachfragen", "gesperrt")
RECHT_NAMEN = {"erlaubt": "erlaubt", "nachfragen": "erst nachfragen", "gesperrt": "gesperrt"}

STATUS_OK = "ok"
STATUS_FEHLER = "fehler"
STATUS_UNGETESTET = "ungetestet"


class IntegrationsFehler(Exception):
    """Ein Fehler mit verständlicher Meldung und – wenn möglich – einem Lösungshinweis.

    Integrationen lösen ihn aus, wenn etwas nicht klappt; das Panel zeigt Meldung und Hinweis an.
    """

    def __init__(self, meldung: str, hinweis: str | None = None) -> None:
        super().__init__(meldung)
        self.meldung = meldung
        self.hinweis = hinweis


def standardrecht(schreibend: bool) -> Recht:
    """Lesende Funktionen sind erlaubt, schreibende/löschende/anrufende fragen erst nach."""
    return "nachfragen" if schreibend else "erlaubt"


@dataclass
class FunktionsInfo:
    """Eine Funktion, die eine Integration Missa anbietet."""

    name: str
    beschreibung: str = ""
    parameter: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    schreibend: bool = True
    # Zusatzangaben des Adapters, z. B. Methode und Pfad bei REST-APIs.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestErgebnis:
    """Ergebnis von „Verbindung testen“."""

    __test__ = False  # kein pytest-Test, auch wenn der Name so anfängt

    ok: bool
    meldung: str
    hinweis: str | None = None
    funktionen: list[FunktionsInfo] = field(default_factory=list)
    # Auswahlmöglichkeiten für Felder, die erst nach dem Test erscheinen (z. B. gefundene Kalender).
    optionen: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    # Was sich die Integration dauerhaft merken möchte (z. B. welche Verbindungsart funktioniert hat).
    zustand: dict[str, Any] = field(default_factory=dict)


@dataclass
class AufrufErgebnis:
    """Ergebnis eines Funktionsaufrufs, so wie es an Missa zurückgeht."""

    # Entweder ein beliebiger Wert (wird als Text/JSON übergeben) …
    wert: Any = None
    # … oder fertige MCP-Inhaltsblöcke (unverändert durchgereicht, z. B. Bilder von MCP-Servern).
    mcp_inhalt: list[Any] | None = None
    strukturiert: Any = None
    ist_fehler: bool = False
