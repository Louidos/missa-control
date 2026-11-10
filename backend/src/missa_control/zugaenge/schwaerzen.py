"""Schwärzt bekannte Geheimnisse in Texten – als zweite Sicherung für Logs und Fehlermeldungen.

Fremde Bibliotheken schreiben manchmal ganze Adressen oder Header in ihre Fehlermeldungen.
Damit ein Geheimnis auch dann nirgends im Klartext landet, merkt sich der Schwärzer jeden Wert,
der im Panel verwendet wird, und ersetzt ihn in Log-Zeilen und Fehlertexten.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

ERSATZ = "•••"
_MIN_LAENGE = 4


class Schwaerzer:
    def __init__(self) -> None:
        self._werte: set[str] = set()
        self._sperre = threading.Lock()

    def merken(self, wert: str | None) -> None:
        if wert and len(wert) >= _MIN_LAENGE:
            with self._sperre:
                self._werte.add(wert)

    def schwaerzen(self, text: str) -> str:
        with self._sperre:
            werte = sorted(self._werte, key=len, reverse=True)
        for wert in werte:
            if wert in text:
                text = text.replace(wert, ERSATZ)
        return text


# Ein Schwärzer für den ganzen Prozess: Geheimnisse sind überall gleich geheim.
SCHWAERZER = Schwaerzer()


def _teil_schwaerzen(wert: Any) -> Any:
    """Schwärzt einen einzelnen Bestandteil einer Log-Zeile. Zahlen und Ähnliches bleiben, was sie sind."""
    if isinstance(wert, str):
        return SCHWAERZER.schwaerzen(wert)
    try:
        text = str(wert)
    except Exception:
        return wert
    sauber = SCHWAERZER.schwaerzen(text)
    return wert if sauber == text else sauber


def _eintrag_schwaerzen(record: logging.LogRecord, fertiger_text: str) -> None:
    """Entfernt ein Geheimnis aus einem Log-Eintrag.

    Text und Bestandteile werden einzeln geschwärzt, damit der Eintrag seine Form behält: Manche
    Ausgaben – etwa das Zugriffsprotokoll des Webservers – greifen später noch auf die einzelnen
    Bestandteile zu. Nur wenn das nicht reicht, wird der Eintrag durch den fertigen Text ersetzt.
    """
    if isinstance(record.msg, str):
        record.msg = SCHWAERZER.schwaerzen(record.msg)
    if isinstance(record.args, tuple):
        record.args = tuple(_teil_schwaerzen(teil) for teil in record.args)
    elif isinstance(record.args, dict):
        record.args = {name: _teil_schwaerzen(teil) for name, teil in record.args.items()}
    try:
        danach = record.getMessage()
    except Exception:
        danach = None
    if danach is None or SCHWAERZER.schwaerzen(danach) != danach:
        record.msg = fertiger_text
        record.args = None


_eingerichtet = False


def log_schutz_einrichten() -> None:
    """Sorgt dafür, dass jede Log-Zeile – egal von welcher Bibliothek – geschwärzt wird.

    Greift direkt beim Erzeugen eines Log-Eintrags und ist damit unabhängig davon,
    welche Ausgaben (Handler) später eingerichtet werden.
    """
    global _eingerichtet
    if _eingerichtet:
        return
    _eingerichtet = True
    vorherige_fabrik = logging.getLogRecordFactory()
    formatierer = logging.Formatter()

    def fabrik(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = vorherige_fabrik(*args, **kwargs)
        try:
            text = record.getMessage()
        except Exception:
            return record
        sauber = SCHWAERZER.schwaerzen(text)
        if sauber != text:
            _eintrag_schwaerzen(record, sauber)
        if record.exc_info and record.exc_info[0] is not None:
            # Fehlertext sofort erzeugen und schwärzen; spätere Ausgaben verwenden diesen Text.
            record.exc_text = SCHWAERZER.schwaerzen(formatierer.formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(fabrik)
