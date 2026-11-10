"""Werkzeuge für eigene Integrationen.

    from missa_control.sdk import Fehler, Kontext, funktion

    @funktion(beschreibung="Sagt Hallo", schreibend=False)
    def hallo(kontext: Kontext, name: str = "Welt") -> str:
        return f"{kontext.konfig['gruss']} {name}!"

Mehr dazu in `docs/eigene-integration.md`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from missa_control.integrationen.kontext import Kontext, auth_header
from missa_control.integrationen.typen import IntegrationsFehler as Fehler
from missa_control.zugaenge.dienst import Zugangsdaten

__all__ = ["Fehler", "Kontext", "Zugangsdaten", "auth_header", "funktion", "verbindungstest"]

FUNKTION_MERKMAL = "__missa_funktion__"
TEST_MERKMAL = "__missa_verbindungstest__"


@dataclass(frozen=True)
class FunktionsAngaben:
    name: str | None
    beschreibung: str | None
    schreibend: bool
    vorschau: Callable[..., Any] | None = None


def funktion(
    fn: Callable[..., Any] | None = None,
    /,
    *,
    beschreibung: str | None = None,
    schreibend: bool = True,
    name: str | None = None,
    vorschau: Callable[..., Any] | None = None,
) -> Any:
    """Macht aus einer Python-Funktion eine Funktion für Missa.

    - `beschreibung`: was die Funktion tut (sonst wird der Docstring verwendet)
    - `schreibend`: `False` für Funktionen, die nur lesen – sie sind dann sofort „erlaubt“.
      Ohne Angabe gilt eine Funktion vorsichtshalber als schreibend („erst nachfragen“).
    - `name`: Name für Missa (sonst der Name der Python-Funktion)
    - `vorschau`: optionale Funktion mit denselben Parametern, die in einem Satz sagt, was der Aufruf
      bewirken würde (z. B. „Löscht den Termin ‚Zahnarzt‘ am 3. Mai“). Der Satz steht in der Freigabe,
      wenn die Funktion „erst nachfragen“ muss. Löst sie `Fehler` aus, wird gar nicht erst nachgefragt.

    Parameter und ihre Beschreibung kommen aus den Typ-Hinweisen und dem Docstring.
    """

    def markieren(ziel: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            ziel,
            FUNKTION_MERKMAL,
            FunktionsAngaben(name=name, beschreibung=beschreibung, schreibend=schreibend, vorschau=vorschau),
        )
        return ziel

    return markieren(fn) if fn is not None else markieren


def verbindungstest[F: Callable[..., Any]](fn: F) -> F:
    """Markiert die Funktion, die „Verbindung testen“ ausführt (optional, höchstens eine).

    Sie bekommt den Kontext und gibt einen kurzen Text zurück (z. B. „Verbunden als missa“).
    Klappt etwas nicht, löst sie `Fehler("Meldung", "Lösungshinweis")` aus.
    """
    setattr(fn, TEST_MERKMAL, True)
    return fn
