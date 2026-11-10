"""Macht aus einer Regel einen lesbaren Satz: „Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann …“."""

from __future__ import annotations

from typing import Any

from missa_control.regeln.pruefung import Umfeld

# Messwerte der Serverlast lesen sich mit Artikel besser; alle anderen stehen in Anführungszeichen.
_MIT_ARTIKEL = {
    "cpu": "die CPU-Auslastung",
    "ram": "die Auslastung des Arbeitsspeichers",
    "speicher": "der belegte Speicherplatz",
    "last": "die Systemlast",
    "cpu_temp": "die CPU-Temperatur",
    "gpu": "die GPU-Auslastung",
    "gpu_speicher": "der belegte GPU-Speicher",
    "gpu_temp": "die GPU-Temperatur",
}
_TAGE = ("montags", "dienstags", "mittwochs", "donnerstags", "freitags", "samstags", "sonntags")


def zahl_text(wert: float | int) -> str:
    """90 → „90“, 87.5 → „87,5“ (so, wie man es im Deutschen schreibt)."""
    return f"{wert:g}".replace(".", ",")


def mit_einheit(wert: float | int, einheit: str) -> str:
    return f"{zahl_text(wert)} {einheit}".strip()


def dauer_text(minuten: int) -> str:
    if minuten % 1440 == 0:
        tage = minuten // 1440
        return "1 Tag" if tage == 1 else f"{tage} Tage"
    if minuten % 60 == 0:
        stunden = minuten // 60
        return "1 Stunde" if stunden == 1 else f"{stunden} Stunden"
    return "1 Minute" if minuten == 1 else f"{minuten} Minuten"


def _aufzaehlung(teile: list[str]) -> str:
    return teile[0] if len(teile) == 1 else ", ".join(teile[:-1]) + " und " + teile[-1]


def tage_text(tage: list[int]) -> str:
    if tage == [0, 1, 2, 3, 4]:
        return "montags bis freitags"
    if tage == [5, 6]:
        return "am Wochenende"
    return _aufzaehlung([_TAGE[tag] for tag in tage])


def bedingung_text(bedingung: dict[str, Any]) -> str:
    """„montags bis freitags zwischen 08:00 und 22:00 Uhr“ – oder leer, wenn es keine Bedingung gibt."""
    teile = []
    if bedingung.get("tage"):
        teile.append(tage_text(bedingung["tage"]))
    if bedingung.get("von"):
        teile.append(f"zwischen {bedingung['von']} und {bedingung['bis']} Uhr")
    return " ".join(teile)


def _name(nummer: int | None, bekannte: dict[int, str]) -> str | None:
    return None if nummer is None else bekannte.get(nummer, "(gelöscht)")


def ausloeser_text(ausloeser: dict[str, Any], umfeld: Umfeld) -> str:
    """Der „Wenn“-Teil ohne das Wort „Wenn“ – z. B. „die CPU-Auslastung 5 Minuten lang über 90 % liegt“."""
    art = ausloeser.get("art")
    if art == "messwert":
        kennung = ausloeser["messwert"]
        titel, einheit = umfeld.messwerte.get(kennung, (kennung, ""))
        wer = _MIT_ARTIKEL.get(kennung, f"„{titel}“")
        dauer = f" {dauer_text(ausloeser['dauer_minuten'])} lang" if ausloeser.get("dauer_minuten") else ""
        richtung = "über" if ausloeser.get("vergleich") != "unter" else "unter"
        return f"{wer}{dauer} {richtung} {mit_einheit(ausloeser['schwelle'], einheit)} liegt"
    if art == "geraet":
        name = _name(ausloeser.get("geraet_id"), umfeld.geraete)
        was = f"„{ausloeser['faehigkeit']}“" if ausloeser.get("faehigkeit") else "etwas"
        return f"das Gerät „{name}“ {was} meldet" if name else f"ein Gerät {was} meldet"
    if art == "webhook":
        name = _name(ausloeser.get("integration_id"), umfeld.webhooks)
        return f"der Webhook „{name}“ etwas empfängt" if name else "ein Webhook etwas empfängt"
    if art == "integration_ausgefallen":
        name = _name(ausloeser.get("integration_id"), umfeld.integrationen)
        return f"die Integration „{name}“ ausfällt" if name else "eine Integration ausfällt"
    return "der Zeitplan fällig ist"


def zeitplan_text(ausloeser: dict[str, Any], bedingung: dict[str, Any]) -> str:
    """„Jeden Tag um 07:30 Uhr“, „Montags bis freitags um 07:30 Uhr“ oder „Alle 15 Minuten“."""
    if ausloeser.get("modus") == "intervall":
        minuten = ausloeser["intervall_minuten"]
        takt = {1: "Jede Minute", 60: "Jede Stunde", 1440: "Jeden Tag"}.get(
            minuten
        ) or f"Alle {dauer_text(minuten)}"
        nur = bedingung_text(bedingung)
        return f"{takt} ({nur})" if nur else takt
    wann = f"um {ausloeser['uhrzeit']} Uhr"
    tage = tage_text(bedingung["tage"]) if bedingung.get("tage") else "jeden Tag"
    fenster = f" (nur zwischen {bedingung['von']} und {bedingung['bis']} Uhr)" if bedingung.get("von") else ""
    return f"{tage[0].upper()}{tage[1:]} {wann}{fenster}"


def argumente_text(argumente: dict[str, Any]) -> str:
    teile = [f"{name} = {wert if isinstance(wert, str) else _wert(wert)}" for name, wert in argumente.items()]
    return ", ".join(teile)


def _wert(wert: Any) -> str:
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    if isinstance(wert, int | float):
        return zahl_text(wert)
    return str(wert)


def ereignis_aktion_text(aktion: dict[str, Any], _: Umfeld) -> str:
    dringlichkeit = aktion.get("dringlichkeit", "normal")
    zusatz = f" (Dringlichkeit: {dringlichkeit})" if dringlichkeit != "normal" else ""
    return f"bekommt Missa die Nachricht „{aktion.get('nachricht', '')}“{zusatz}"


def funktion_aktion_text(aktion: dict[str, Any], _: Umfeld) -> str:
    argumente = argumente_text(aktion.get("argumente") or {})
    return f"wird die Funktion „{aktion.get('funktion', '')}“ aufgerufen" + (
        f" ({argumente})" if argumente else ""
    )


def aktion_text(aktion: dict[str, Any], umfeld: Umfeld) -> str:
    art = umfeld.aktionen.get(aktion.get("art", ""))
    return art.satz(aktion, umfeld) if art else "passiert nichts (unbekannte Aktion)"


def regel_satz(regel: dict[str, Any], umfeld: Umfeld) -> str:
    """Die ganze Regel als ein bis zwei Sätze."""
    ausloeser, bedingung = regel["ausloeser"], regel.get("bedingung") or {}
    dann = aktion_text(regel["aktion"], umfeld)
    if ausloeser.get("art") == "zeitplan":
        return f"{zeitplan_text(ausloeser, bedingung)} {dann}."
    nur = bedingung_text(bedingung)
    wenn = f"Wenn {ausloeser_text(ausloeser, umfeld)}" + (f" (nur {nur})" if nur else "")
    ruhezeit = regel.get("ruhezeit_minuten", 0)
    ruhe = f"Danach {dauer_text(ruhezeit)} Ruhe." if ruhezeit else "Ohne Ruhezeit – löst jedes Mal aus."
    return f"{wenn}, dann {dann}. {ruhe}"
