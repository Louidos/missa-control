"""Die Schnittstelle zwischen Panel und Telefon – und der mitgelieferte Test-Adapter.

Ein Adapter verbindet das Panel mit etwas, das wirklich telefonieren kann (SIP-Anlage, Telefon-App,
Modem …). Die Schnittstelle besteht aus drei Dingen:

1. **anrufen** (Panel → Adapter): `TelefonAdapter.anrufen(auftrag)` baut den Anruf auf.
2. **Anruf beendet** (Adapter → Panel): `TelefonieDienst.anruf_beendet(anruf_id, …)` – oder gleich als
   Ergebnis von `anrufen`, wenn der Adapter bis zum Ende des Gesprächs wartet.
3. **eingehender Anruf** (Adapter → Panel): `TelefonieDienst.eingehender_anruf(nummer)` – das Panel
   antwortet, ob der Anrufer erlaubt ist.

Weitere Adapter kommen als Integration dazu: In ihrer `main.py` markiert `@telefon_anrufen` die
Funktion, die einen Anruf aufbaut (siehe docs/telefonie.md).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Anrufauftrag:
    """Ein Anruf, den der Adapter aufbauen soll."""

    anruf_id: int
    nummer: str
    name: str
    # Was beim Anruf gesagt werden soll.
    text: str
    dringlichkeit: str


@dataclass(frozen=True)
class Anrufstart:
    """Was der Adapter nach dem Aufbau meldet.

    `ergebnis`: „laeuft“ (das Ende meldet der Adapter später mit `anruf_beendet`), „beendet“,
    „nicht_erreicht“ oder „test“ (nur protokolliert).
    """

    ergebnis: str = "laeuft"
    dauer_sekunden: int | None = None
    meldung: str = ""


class TelefonAdapter(ABC):
    kennung: str
    name: str
    beschreibung: str = ""

    @abstractmethod
    async def anrufen(self, auftrag: Anrufauftrag) -> Anrufstart | None:
        """Baut den Anruf auf. Klappt das nicht, löst der Adapter einen `IntegrationsFehler` aus."""

    async def auflegen(self, anruf_id: int) -> None:  # noqa: B027 – darf, muss aber nicht überschrieben werden
        """Beendet einen laufenden Anruf (optional)."""


class TestAdapter(TelefonAdapter):
    """Ruft niemanden an: Der Anruf wird nur protokolliert und als Ereignis gemeldet."""

    __test__ = False  # kein Testfall für pytest, auch wenn der Name so beginnt
    kennung = "test"
    name = "Test-Adapter"
    beschreibung = "Ruft niemanden an – Anrufe werden nur protokolliert und als Ereignis gemeldet."

    async def anrufen(self, auftrag: Anrufauftrag) -> Anrufstart:
        return Anrufstart(
            ergebnis="test", dauer_sekunden=0, meldung="Test-Adapter: Es wurde niemand wirklich angerufen."
        )
