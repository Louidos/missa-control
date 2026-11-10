"""Eingebaute Integration „Telefonie“: Missa ruft an – nach Freigabe und nur, wen sie anrufen darf."""

from typing import Literal

from missa_control.sdk import Kontext, funktion, verbindungstest

Dringlichkeit = Literal["niedrig", "normal", "hoch", "dringend"]


@verbindungstest
def testen(kontext: Kontext) -> str:
    return kontext.panel.telefonie.stand()


def _anrufen_vorschau(
    kontext: Kontext, text: str, nummer: str | None = None, dringlichkeit: Dringlichkeit = "normal"
) -> str:
    return kontext.panel.telefonie.vorschau(text, nummer, dringlichkeit)


@funktion(
    beschreibung=(
        "Ruft jemanden an und sagt den angegebenen Text. Ohne Nummer wird der Besitzer unter seiner eigenen "
        "Nummer angerufen. In der Ruhezeit gehen nur Anrufe mit der Dringlichkeit „dringend“ durch."
    ),
    vorschau=_anrufen_vorschau,
)
async def anrufen(
    kontext: Kontext, text: str, nummer: str | None = None, dringlichkeit: Dringlichkeit = "normal"
) -> dict:
    """
    text: Was beim Anruf gesagt werden soll – ein vollständiger Satz
    nummer: Telefonnummer, z. B. +41 79 123 45 67 (weglassen = eigene Nummer des Besitzers)
    dringlichkeit: niedrig, normal, hoch oder dringend
    """
    return await kontext.panel.telefonie.fuer_missa_anrufen(text, nummer, dringlichkeit)


@funktion(
    beschreibung="Zeigt die letzten Anrufe: Zeit, Richtung, Nummer, Dauer und worum es ging.",
    schreibend=False,
)
def anrufe_anzeigen(kontext: Kontext, anzahl: int = 10) -> dict:
    """
    anzahl: Wie viele Anrufe höchstens zurückkommen (1 bis 50)
    """
    return kontext.panel.telefonie.fuer_missa_verlauf(anzahl)
