"""Eingebaute Integration „Serverlast“: gibt Missa die aktuelle Auslastung von ai01."""

from missa_control.sdk import Kontext, funktion, verbindungstest


@verbindungstest
def testen(kontext: Kontext) -> str:
    messung = kontext.panel.serverlast.messen()
    gpu = f", GPU {messung.gpu:.0f} %" if messung.gpus else " (keine GPU gefunden)"
    return f"Messung klappt: CPU {messung.cpu:.0f} %, Arbeitsspeicher {messung.ram:.0f} %{gpu}"


@funktion(
    beschreibung=(
        "Aktuelle Auslastung des Servers ai01: CPU, Arbeitsspeicher, Speicherplatz und – falls vorhanden – GPU. "
        "Liefert Zahlen und einen Satz zum Vorlesen."
    ),
    schreibend=False,
)
def serverlast_aktuell(kontext: Kontext) -> dict:
    return kontext.panel.serverlast.fuer_missa()
