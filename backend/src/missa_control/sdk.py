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
from missa_control.integrationen.typen import AufrufErgebnis, FunktionsInfo
from missa_control.integrationen.typen import IntegrationsFehler as Fehler
from missa_control.zugaenge.dienst import Zugangsdaten

__all__ = [
    "AufrufErgebnis",
    "Fehler",
    "FunktionsInfo",
    "Kontext",
    "Zugangsdaten",
    "aufruf_weiterer_funktionen",
    "auth_header",
    "funktion",
    "telefon_anrufen",
    "telefon_auflegen",
    "verbindungstest",
    "weitere_funktionen",
]

FUNKTION_MERKMAL = "__missa_funktion__"
TEST_MERKMAL = "__missa_verbindungstest__"
QUELLE_MERKMAL = "__missa_weitere_funktionen__"
WEITERLEITUNG_MERKMAL = "__missa_aufruf_weiterer_funktionen__"
TELEFON_ANRUFEN_MERKMAL = "__missa_telefon_anrufen__"
TELEFON_AUFLEGEN_MERKMAL = "__missa_telefon_auflegen__"


@dataclass(frozen=True)
class FunktionsAngaben:
    name: str | None
    beschreibung: str | None
    schreibend: bool
    vorschau: Callable[..., Any] | None = None
    wenn: Callable[[Kontext], bool] | None = None


def funktion(
    fn: Callable[..., Any] | None = None,
    /,
    *,
    beschreibung: str | None = None,
    schreibend: bool = True,
    name: str | None = None,
    vorschau: Callable[..., Any] | None = None,
    wenn: Callable[[Kontext], bool] | None = None,
) -> Any:
    """Macht aus einer Python-Funktion eine Funktion für Missa.

    - `beschreibung`: was die Funktion tut (sonst wird der Docstring verwendet)
    - `schreibend`: `False` für Funktionen, die nur lesen – sie sind dann sofort „erlaubt“.
      Ohne Angabe gilt eine Funktion vorsichtshalber als schreibend („erst nachfragen“).
    - `name`: Name für Missa (sonst der Name der Python-Funktion)
    - `vorschau`: optionale Funktion mit denselben Parametern, die in einem Satz sagt, was der Aufruf
      bewirken würde (z. B. „Löscht den Termin ‚Zahnarzt‘ am 3. Mai“). Der Satz steht in der Freigabe,
      wenn die Funktion „erst nachfragen“ muss. Löst sie `Fehler` aus, wird gar nicht erst nachgefragt.
    - `wenn`: optionale Prüfung `(kontext) -> bool`. Liefert sie beim Testen `False`, wird die Funktion
      nicht angeboten (z. B. weil die Gegenstelle sie in dieser Einrichtung nicht unterstützt).

    Parameter und ihre Beschreibung kommen aus den Typ-Hinweisen und dem Docstring.
    """

    def markieren(ziel: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            ziel,
            FUNKTION_MERKMAL,
            FunktionsAngaben(
                name=name, beschreibung=beschreibung, schreibend=schreibend, vorschau=vorschau, wenn=wenn
            ),
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


def weitere_funktionen[F: Callable[..., Any]](fn: F) -> F:
    """Markiert die Funktion, die beim Testen weitere Funktionen meldet (optional, höchstens eine).

    Für Funktionen, die erst zur Laufzeit feststehen – etwa die Werkzeuge eines anderen Dienstes.
    Sie bekommt den Kontext und gibt eine Liste von `FunktionsInfo(name, beschreibung, parameter,
    schreibend)` zurück. Ausgeführt werden sie von der mit `@aufruf_weiterer_funktionen` markierten Funktion.
    """
    setattr(fn, QUELLE_MERKMAL, True)
    return fn


def aufruf_weiterer_funktionen[F: Callable[..., Any]](fn: F) -> F:
    """Markiert die Funktion, die gemeldete weitere Funktionen ausführt: `(kontext, name, argumente)`.

    Sie gibt einen beliebigen Wert zurück – oder ein `AufrufErgebnis`, um z. B. die Antwort eines
    MCP-Servers unverändert durchzureichen.
    """
    setattr(fn, WEITERLEITUNG_MERKMAL, True)
    return fn


def telefon_anrufen[F: Callable[..., Any]](fn: F) -> F:
    """Macht die Integration zum Telefonie-Adapter: Diese Funktion baut einen Anruf auf (höchstens eine).

    Sie bekommt `(kontext, auftrag)` – `auftrag` hat `anruf_id`, `nummer`, `name`, `text` und
    `dringlichkeit`. Wartet sie bis zum Ende des Gesprächs, gibt sie z. B.
    `{"ergebnis": "beendet", "dauer_sekunden": 42}` zurück („beendet“ oder „nicht_erreicht“). Gibt sie
    nichts zurück, läuft der Anruf weiter – das Ende meldet der Adapter dann mit
    `kontext.panel.telefonie.anruf_beendet(anruf_id, dauer_sekunden=…)`. Mehr in `docs/telefonie.md`.
    """
    setattr(fn, TELEFON_ANRUFEN_MERKMAL, True)
    return fn


def telefon_auflegen[F: Callable[..., Any]](fn: F) -> F:
    """Markiert die Funktion, die einen laufenden Anruf beendet: `(kontext, anruf_id)` (optional)."""
    setattr(fn, TELEFON_AUFLEGEN_MERKMAL, True)
    return fn
