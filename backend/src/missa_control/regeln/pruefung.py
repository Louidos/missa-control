"""Prüft die Angaben einer Regel und bringt sie in eine einheitliche Form.

Eine Regel besteht aus drei Teilen (alle als einfache Wörterbücher gespeichert):

    ausloeser   {"art": "zeitplan", "modus": "uhrzeit", "uhrzeit": "07:30"}
                {"art": "zeitplan", "modus": "intervall", "intervall_minuten": 15}
                {"art": "messwert", "messwert": "cpu", "vergleich": "ueber", "schwelle": 90, "dauer_minuten": 5}
                {"art": "geraet", "geraet_id": 3, "faehigkeit": "knopf"}        (ohne Angabe: jedes Gerät)
                {"art": "webhook", "integration_id": 7}                          (ohne Angabe: jeder Webhook)
                {"art": "integration_ausgefallen", "integration_id": 2}          (ohne Angabe: jede)
    bedingung   {"tage": [0, 1, 2, 3, 4], "von": "08:00", "bis": "22:00"}       (alles freiwillig; 0 = Montag)
    aktion      {"art": "ereignis", "nachricht": "…", "dringlichkeit": "hoch"}
                {"art": "funktion", "funktion": "licht_schalten", "argumente": {"an": true}}

Fehler kommen als `PanelFehler` mit einem Satz, was nicht stimmt, und einem Hinweis, was erlaubt ist.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from missa_control.ereignisse.modelle import DRINGLICHKEITEN
from missa_control.fehler import PanelFehler

AUSLOESER_ARTEN: dict[str, str] = {
    "zeitplan": "Zeitplan",
    "messwert": "Messwert über oder unter einer Schwelle",
    "geraet": "Gerät meldet etwas",
    "webhook": "Webhook geht ein",
    "integration_ausgefallen": "Integration ausgefallen",
}
WOCHENTAGE = ("mo", "di", "mi", "do", "fr", "sa", "so")
VERGLEICHE = {"ueber": "ueber", "über": "ueber", ">": "ueber", "unter": "unter", "<": "unter"}
MAX_MINUTEN = 7 * 24 * 60  # eine Woche
STANDARD_RUHEZEIT = 30

_UHRZEIT = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:uhr)?\s*$", re.IGNORECASE)


@dataclass
class FunktionsAngabe:
    """Eine Funktion, die eine Regel aufrufen kann (alles, was am Gateway nicht gesperrt ist)."""

    integration: str
    beschreibung: str
    parameter: dict[str, Any]
    recht: str


@dataclass
class AktionsArt:
    """Eine Art von Aktion. Weitere Arten (z. B. „Anruf“) melden sich beim Regel-Dienst an."""

    titel: str
    # Prüft die Angaben und gibt sie bereinigt zurück.
    pruefen: Callable[[dict[str, Any], Umfeld], dict[str, Any]]
    # Satzteil wie „bekommt Missa die Nachricht …“ (beginnt mit dem Verb).
    satz: Callable[[dict[str, Any], Umfeld], str]
    # Führt die Aktion aus und gibt einen kurzen Satz für den Verlauf zurück.
    ausfuehren: Callable[..., Awaitable[str]]


@dataclass
class Umfeld:
    """Was es gerade gibt: daran werden Regeln geprüft, daraus entstehen Auswahllisten und lesbare Sätze."""

    # Kennung → (Titel, Einheit)
    messwerte: dict[str, tuple[str, str]] = field(default_factory=dict)
    integrationen: dict[int, str] = field(default_factory=dict)
    webhooks: dict[int, str] = field(default_factory=dict)
    geraete: dict[int, str] = field(default_factory=dict)
    # Was ein Gerät melden kann (Kennung, Bezeichnung) – z. B. ("knopf", "Knopf"), ("offline", "geht offline")
    geraete_meldungen: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    # Name am Gateway → Angaben
    funktionen: dict[str, FunktionsAngabe] = field(default_factory=dict)
    aktionen: dict[str, AktionsArt] = field(default_factory=dict)


def _fehler(meldung: str, hinweis: str | None = None) -> PanelFehler:
    return PanelFehler(422, meldung, hinweis)


def uhrzeit(wert: Any, feld: str) -> str:
    """„7:30“, „07.30“ oder „7 Uhr“ → „07:30“."""
    treffer = _UHRZEIT.match(str(wert if wert is not None else ""))
    if treffer:
        stunde, minute = int(treffer.group(1)), int(treffer.group(2) or 0)
        if stunde < 24 and minute < 60:
            return f"{stunde:02d}:{minute:02d}"
    raise _fehler(f"„{feld}“ ist keine gültige Uhrzeit.", "Bitte im Format HH:MM angeben, z. B. 07:30.")


def zahl(wert: Any, feld: str, *, von: float, bis: float, ganz: bool = False) -> float | int:
    try:
        ergebnis = float(str(wert).replace(",", ".")) if not isinstance(wert, bool) else float("nan")
    except (TypeError, ValueError):
        ergebnis = float("nan")
    if ergebnis != ergebnis or (ganz and not ergebnis.is_integer()):  # NaN oder Kommazahl
        raise _fehler(f"„{feld}“ muss eine {'ganze ' if ganz else ''}Zahl sein.")
    if not von <= ergebnis <= bis:
        raise _fehler(f"„{feld}“ muss zwischen {von:g} und {bis:g} liegen.")
    return int(ergebnis) if ganz or ergebnis.is_integer() else ergebnis


def _nummer(wert: Any, bekannte: dict[int, str], was: str) -> int | None:
    """Nummer einer Integration bzw. eines Geräts – oder `None` für „alle“."""
    if wert in (None, "", 0, "0"):
        return None
    try:
        nummer = int(wert)
    except (TypeError, ValueError):
        nummer = -1
    if nummer not in bekannte:
        raise _fehler(
            f"{was} gibt es nicht (mehr).",
            "Zur Auswahl stehen: " + (", ".join(bekannte.values()) or "noch nichts") + ".",
        )
    return nummer


def ausloeser_pruefen(daten: Any, umfeld: Umfeld) -> dict[str, Any]:
    if not isinstance(daten, dict) or daten.get("art") not in AUSLOESER_ARTEN:
        raise _fehler(
            "Bitte einen Auslöser wählen.",
            "Möglich sind: " + ", ".join(AUSLOESER_ARTEN) + ".",
        )
    art = daten["art"]
    if art == "zeitplan":
        modus = daten.get("modus") or ("intervall" if daten.get("intervall_minuten") else "uhrzeit")
        if modus == "intervall":
            minuten = zahl(daten.get("intervall_minuten"), "Intervall", von=1, bis=MAX_MINUTEN, ganz=True)
            return {"art": art, "modus": "intervall", "intervall_minuten": minuten}
        if modus != "uhrzeit":
            raise _fehler("Beim Zeitplan bitte „uhrzeit“ oder „intervall“ wählen.")
        return {"art": art, "modus": "uhrzeit", "uhrzeit": uhrzeit(daten.get("uhrzeit"), "Uhrzeit")}
    if art == "messwert":
        messwert = str(daten.get("messwert") or "").strip()
        if messwert not in umfeld.messwerte:
            raise _fehler(
                f"Den Messwert „{messwert}“ gibt es nicht." if messwert else "Bitte einen Messwert wählen.",
                "Zur Auswahl stehen: " + ", ".join(umfeld.messwerte) + ".",
            )
        vergleich = VERGLEICHE.get(str(daten.get("vergleich") or "ueber").strip().lower())
        if vergleich is None:
            raise _fehler("Der Vergleich muss „ueber“ oder „unter“ sein.")
        if daten.get("schwelle") in (None, ""):
            raise _fehler("Bitte eine Schwelle angeben.", "Zum Beispiel 90 für „über 90 %“.")
        return {
            "art": art,
            "messwert": messwert,
            "vergleich": vergleich,
            "schwelle": zahl(daten.get("schwelle"), "Schwelle", von=-1_000_000, bis=1_000_000),
            "dauer_minuten": zahl(
                daten.get("dauer_minuten") or 0, "Mindestdauer", von=0, bis=1440, ganz=True
            ),
        }
    if art == "geraet":
        return {
            "art": art,
            "geraet_id": _nummer(daten.get("geraet_id"), umfeld.geraete, "Dieses Gerät"),
            "faehigkeit": str(daten.get("faehigkeit") or "").strip()[:60],
        }
    if art == "webhook":
        return {
            "art": art,
            "integration_id": _nummer(daten.get("integration_id"), umfeld.webhooks, "Diesen Webhook"),
        }
    return {
        "art": art,
        "integration_id": _nummer(daten.get("integration_id"), umfeld.integrationen, "Diese Integration"),
    }


def bedingung_pruefen(daten: Any) -> dict[str, Any]:
    if daten in (None, ""):
        return {}
    if not isinstance(daten, dict):
        raise _fehler("Die Bedingung ist ungültig.")
    ergebnis: dict[str, Any] = {}
    tage: set[int] = set()
    for tag in daten.get("tage") or []:
        text = str(tag).strip().lower()[:2]
        if text in WOCHENTAGE:
            tage.add(WOCHENTAGE.index(text))
        elif isinstance(tag, int) and not isinstance(tag, bool) and 0 <= tag <= 6:
            tage.add(tag)
        else:
            raise _fehler(f"„{tag}“ ist kein Wochentag.", "Erlaubt sind: " + ", ".join(WOCHENTAGE) + ".")
    if tage and len(tage) < 7:
        ergebnis["tage"] = sorted(tage)
    von, bis = daten.get("von") or None, daten.get("bis") or None
    if (von is None) != (bis is None):
        raise _fehler("Für das Zeitfenster bitte beide Uhrzeiten angeben („von“ und „bis“).")
    if von is not None:
        ergebnis["von"], ergebnis["bis"] = uhrzeit(von, "von"), uhrzeit(bis, "bis")
        if ergebnis["von"] == ergebnis["bis"]:
            raise _fehler("„von“ und „bis“ dürfen nicht gleich sein.")
    return ergebnis


def aktion_pruefen(daten: Any, umfeld: Umfeld) -> dict[str, Any]:
    art = umfeld.aktionen.get(daten.get("art")) if isinstance(daten, dict) else None
    if art is None:
        raise _fehler("Bitte eine Aktion wählen.", "Möglich sind: " + ", ".join(umfeld.aktionen) + ".")
    return {"art": daten["art"], **art.pruefen(daten, umfeld)}


def ereignis_aktion_pruefen(daten: dict[str, Any], _: Umfeld) -> dict[str, Any]:
    nachricht = str(daten.get("nachricht") or "").strip()
    if not nachricht:
        raise _fehler(
            "Bitte eine Nachricht für Missa angeben.",
            "Zum Beispiel: „Die CPU ist seit 5 Minuten stark ausgelastet.“",
        )
    if len(nachricht) > 500:
        raise _fehler("Die Nachricht ist zu lang (höchstens 500 Zeichen).")
    dringlichkeit = str(daten.get("dringlichkeit") or "normal").strip().lower()
    if dringlichkeit not in DRINGLICHKEITEN:
        raise _fehler(
            f"Die Dringlichkeit „{dringlichkeit}“ gibt es nicht.",
            "Erlaubt sind: " + ", ".join(DRINGLICHKEITEN) + ".",
        )
    return {"nachricht": nachricht, "dringlichkeit": dringlichkeit}


def funktion_aktion_pruefen(daten: dict[str, Any], umfeld: Umfeld) -> dict[str, Any]:
    name = str(daten.get("funktion") or "").strip()
    angabe = umfeld.funktionen.get(name)
    if angabe is None:
        raise _fehler(
            f"Die Funktion „{name}“ gibt es nicht oder sie ist gesperrt."
            if name
            else "Bitte eine Funktion wählen.",
            "Zur Auswahl stehen alle Funktionen aktiver Integrationen, die nicht gesperrt sind"
            + (
                ": " + ", ".join(sorted(umfeld.funktionen)[:30]) + "."
                if umfeld.funktionen
                else " – im Moment keine."
            ),
        )
    argumente = daten.get("argumente") or {}
    if not isinstance(argumente, dict):
        raise _fehler("Die Parameter der Funktion müssen aus Namen und Werten bestehen.")
    fehlend = [p for p in angabe.parameter.get("required") or [] if argumente.get(p) in (None, "")]
    if fehlend:
        raise _fehler(f"Für „{name}“ fehlt der Parameter „{fehlend[0]}“.", angabe.beschreibung or None)
    return {"funktion": name, "argumente": argumente}


def regel_pruefen(daten: Any, umfeld: Umfeld) -> dict[str, Any]:
    """Prüft eine ganze Regel. Gibt Name, Auslöser, Bedingung, Aktion, Ruhezeit und „aktiv“ bereinigt zurück."""
    if not isinstance(daten, dict):
        raise _fehler("Die Angaben zur Regel fehlen.")
    name = " ".join(str(daten.get("name") or "").split())
    if not name:
        raise _fehler("Bitte der Regel einen Namen geben.", "Zum Beispiel „CPU-Alarm“.")
    if len(name) > 80:
        raise _fehler("Der Name ist zu lang (höchstens 80 Zeichen).")
    ruhezeit = daten.get("ruhezeit_minuten")
    return {
        "name": name,
        "ausloeser": ausloeser_pruefen(daten.get("ausloeser"), umfeld),
        "bedingung": bedingung_pruefen(daten.get("bedingung")),
        "aktion": aktion_pruefen(daten.get("aktion"), umfeld),
        "ruhezeit_minuten": STANDARD_RUHEZEIT
        if ruhezeit in (None, "")
        else zahl(ruhezeit, "Ruhezeit", von=0, bis=MAX_MINUTEN, ganz=True),
        "aktiv": daten.get("aktiv") is not False,
    }
