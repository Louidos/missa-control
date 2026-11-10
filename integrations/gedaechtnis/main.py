"""Eingebaute Integration „Gedächtnis“: Missa merkt sich Dinge, sucht danach und vergisst auf Wunsch."""

from typing import Literal

from missa_control.sdk import Kontext, funktion, verbindungstest

Kategorie = Literal["vorlieben", "gewohnheiten", "projektwissen", "personen", "sonstiges"]


@verbindungstest
def testen(kontext: Kontext) -> str:
    anzahl = kontext.panel.gedaechtnis.bestand()
    return f"Gedächtnis bereit: {anzahl} {'Eintrag' if anzahl == 1 else 'Einträge'}."


@funktion(
    beschreibung=(
        "Merkt sich etwas dauerhaft, z. B. eine Vorliebe, eine Gewohnheit, Wissen zu einem Projekt oder "
        "etwas über eine Person. Der Besitzer kann alle Einträge im Panel sehen, korrigieren und löschen."
    ),
)
def merken(kontext: Kontext, text: str, kategorie: Kategorie = "sonstiges") -> dict:
    """
    text: Was gemerkt werden soll – ein vollständiger Satz, der auch ohne das Gespräch verständlich ist
    kategorie: vorlieben, gewohnheiten, projektwissen, personen oder sonstiges
    """
    return kontext.panel.gedaechtnis.merken(text, kategorie)


@funktion(
    beschreibung=(
        "Durchsucht das Gedächtnis nach Stichwörtern (Volltext, auch Wortteile). Bei mehreren Stichwörtern "
        "genügt eines; die besten Treffer stehen vorn. Ohne Stichwort kommen die neuesten Einträge."
    ),
    schreibend=False,
)
def suchen(kontext: Kontext, text: str = "", kategorie: Kategorie | None = None, anzahl: int = 10) -> dict:
    """
    text: Ein oder mehrere Stichwörter, z. B. „Kaffee“ oder „Geburtstag Oma“
    kategorie: Nur in dieser Kategorie suchen (vorlieben, gewohnheiten, projektwissen, personen, sonstiges)
    anzahl: Wie viele Einträge höchstens zurückkommen (1 bis 50)
    """
    return kontext.panel.gedaechtnis.fuer_missa_suchen(text, kategorie, anzahl)


def _vergessen_vorschau(kontext: Kontext, id: int) -> str:
    return kontext.panel.gedaechtnis.vergessen_vorschau(id)


@funktion(
    beschreibung=(
        "Löscht einen Eintrag endgültig aus dem Gedächtnis. Die Nummer (id) des Eintrags liefert „suchen“."
    ),
    vorschau=_vergessen_vorschau,
)
def vergessen(kontext: Kontext, id: int) -> dict:
    """
    id: Nummer des Eintrags, der gelöscht werden soll
    """
    return kontext.panel.gedaechtnis.vergessen(id)
