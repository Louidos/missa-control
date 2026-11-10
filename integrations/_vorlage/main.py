"""Vorlage für eine eigene Integration – siehe docs/eigene-integration.md."""

from missa_control.sdk import Fehler, Kontext, funktion, verbindungstest


@verbindungstest
def testen(kontext: Kontext) -> str:
    """Läuft bei „Verbindung testen“. Hier prüfen, ob alles Nötige vorhanden und erreichbar ist."""
    if not kontext.konfig.get("gruss"):
        raise Fehler("Das Grusswort fehlt.", "Bitte im Formular ein Grusswort eintragen.")
    return "Alles bereit."


@funktion(beschreibung="Begrüsst eine Person mit dem eingestellten Grusswort.", schreibend=False)
def begruessen(kontext: Kontext, name: str = "Welt") -> str:
    """Begrüsst jemanden.

    name: Wer begrüsst werden soll
    """
    return f"{kontext.konfig['gruss']}, {name}!"
