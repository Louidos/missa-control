"""Telefonnummern einheitlich schreiben, damit „079 123 45 67“ und „+41791234567“ dieselbe Nummer sind."""

from __future__ import annotations

import re

from missa_control.fehler import PanelFehler

_TRENNER = re.compile(r"[\s\-./()]")
_NUMMER = re.compile(r"^\+?\d{2,15}$")
_VORWAHL = re.compile(r"^\+\d{1,4}$")


def landesvorwahl_pruefen(wert: object) -> str:
    text = _TRENNER.sub("", str(wert or ""))
    if text.startswith("00"):
        text = "+" + text[2:]
    if not _VORWAHL.match(text):
        raise PanelFehler(
            422,
            "Die Landesvorwahl ist ungültig.",
            "Erwartet wird z. B. +41 (Schweiz) oder +49 (Deutschland).",
        )
    return text


def normalisieren(roh: object, landesvorwahl: str = "+41") -> str:
    """„079 123 45 67“ → „+41791234567“, „0041 79 …“ → „+4179…“. Kurze interne Nummern (z. B. 101) bleiben.

    Löst `PanelFehler` (422) aus, wenn das keine Telefonnummer ist.
    """
    text = _TRENNER.sub("", str(roh if roh is not None else ""))
    if text.startswith("00"):
        text = "+" + text[2:]
    if not _NUMMER.match(text):
        raise PanelFehler(
            422,
            f"„{str(roh)[:40]}“ ist keine gültige Telefonnummer.",
            "Erlaubt sind Ziffern, auf Wunsch mit + und Ländervorwahl – z. B. +41 79 123 45 67 oder 079 123 45 67.",
        )
    if text.startswith("+"):
        return text
    if text.startswith("0") and len(text) >= 7:
        return landesvorwahl + text[1:]
    return text
