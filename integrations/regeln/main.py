"""Eingebaute Integration „Regeln“: Missa verwaltet Regeln und Alarme per Sprache."""

from typing import Literal

from missa_control.sdk import Kontext, funktion, verbindungstest

Ausloeser = Literal["zeitplan", "messwert", "webhook", "geraet", "integration_ausgefallen"]
Aktion = Literal["ereignis", "funktion", "anruf"]
Vergleich = Literal["ueber", "unter"]
Dringlichkeit = Literal["niedrig", "normal", "hoch", "dringend"]
Wochentag = Literal["mo", "di", "mi", "do", "fr", "sa", "so"]

_PARAMETER = """
    name: Kurzer Name der Regel, z. B. „CPU-Alarm“
    ausloeser: Was die Regel auslöst – zeitplan (mit uhrzeit oder intervall_minuten), messwert (mit messwert, vergleich, schwelle, dauer_minuten), webhook, geraet oder integration_ausgefallen
    aktion: Was dann passiert – ereignis (Missa bekommt die nachricht), funktion (ruft funktion mit argumente auf) oder anruf (ruft an und sagt die nachricht)
    uhrzeit: Für zeitplan – Uhrzeit im Format HH:MM, z. B. 07:30
    intervall_minuten: Für zeitplan – stattdessen alle so viele Minuten
    messwert: Für messwert – cpu, ram, speicher (jeweils Prozent), last, cpu_temp, gpu, gpu_speicher oder gpu_temp
    vergleich: Für messwert – ueber oder unter der Schwelle
    schwelle: Für messwert – der Grenzwert, z. B. 90
    dauer_minuten: Für messwert – wie lange der Wert mindestens darüber bzw. darunter liegen muss
    integration: Für webhook und integration_ausgefallen – Name der Integration (weglassen = jede)
    geraet: Für geraet – Name des Geräts (weglassen = jedes)
    faehigkeit: Für geraet – was das Gerät meldet, z. B. knopf (weglassen = alles)
    nachricht: Für ereignis und anruf – der Text an Missa bzw. was beim Anruf gesagt wird; {wert} steht für den aktuellen Messwert
    dringlichkeit: Für ereignis und anruf – niedrig, normal, hoch oder dringend (in der Ruhezeit gehen nur dringende Anrufe durch)
    nummer: Für anruf – die Telefonnummer (weglassen = eigene Nummer des Besitzers)
    funktion: Für funktion – Name der Funktion, genau wie in der Werkzeugliste
    argumente: Für funktion – ihre Parameter als Objekt
    wochentage: Bedingung – nur an diesen Tagen (mo, di, mi, do, fr, sa, so)
    von: Bedingung – nur ab dieser Uhrzeit (HH:MM), zusammen mit bis
    bis: Bedingung – nur bis zu dieser Uhrzeit (HH:MM), zusammen mit von
    ruhezeit_minuten: So lange bleibt die Regel nach einer Auslösung still (Standard 30)
"""


@verbindungstest
def testen(kontext: Kontext) -> str:
    anzahl = kontext.panel.regeln.fuer_missa_auflisten()["anzahl"]
    return f"Regeln bereit: {anzahl} {'Regel' if anzahl == 1 else 'Regeln'} vorhanden."


@funktion(
    beschreibung="Listet alle Regeln und Alarme auf – mit Nummer (id), Name, einem Satz, was die Regel tut, und ob sie aktiv ist.",
    schreibend=False,
)
def regeln_auflisten(kontext: Kontext) -> dict:
    return kontext.panel.regeln.fuer_missa_auflisten()


def _anlegen_vorschau(kontext: Kontext, **angaben) -> str:
    return kontext.panel.regeln.vorschau_anlegen(**angaben)


@funktion(
    beschreibung=(
        "Legt eine neue Regel an: Wenn der Auslöser eintritt, wird die Aktion ausgeführt. "
        "Beispiel: ausloeser=messwert, messwert=cpu, schwelle=90, dauer_minuten=5, aktion=ereignis, "
        "nachricht=„Die CPU ist stark ausgelastet ({wert} %)“."
    ),
    vorschau=_anlegen_vorschau,
)
def regel_anlegen(
    kontext: Kontext,
    name: str,
    ausloeser: Ausloeser,
    aktion: Aktion = "ereignis",
    uhrzeit: str | None = None,
    intervall_minuten: int | None = None,
    messwert: str | None = None,
    vergleich: Vergleich | None = None,
    schwelle: float | None = None,
    dauer_minuten: int | None = None,
    integration: str | None = None,
    geraet: str | None = None,
    faehigkeit: str | None = None,
    nachricht: str | None = None,
    dringlichkeit: Dringlichkeit | None = None,
    funktion: str | None = None,
    argumente: dict | None = None,
    nummer: str | None = None,
    wochentage: list[Wochentag] | None = None,
    von: str | None = None,
    bis: str | None = None,
    ruhezeit_minuten: int | None = None,
) -> dict:
    angaben = dict(locals())
    del angaben["kontext"]
    return kontext.panel.regeln.fuer_missa_anlegen(**angaben)


def _aendern_vorschau(kontext: Kontext, id: int, **angaben) -> str:
    return kontext.panel.regeln.vorschau_aendern(id, **angaben)


@funktion(
    beschreibung=(
        "Ändert eine bestehende Regel. Nur die genannten Angaben ändern sich, alles andere bleibt. "
        "Mit aktiv=false wird die Regel pausiert, mit aktiv=true wieder eingeschaltet."
    ),
    vorschau=_aendern_vorschau,
)
def regel_aendern(
    kontext: Kontext,
    id: int,
    name: str | None = None,
    aktiv: bool | None = None,
    ausloeser: Ausloeser | None = None,
    aktion: Aktion | None = None,
    uhrzeit: str | None = None,
    intervall_minuten: int | None = None,
    messwert: str | None = None,
    vergleich: Vergleich | None = None,
    schwelle: float | None = None,
    dauer_minuten: int | None = None,
    integration: str | None = None,
    geraet: str | None = None,
    faehigkeit: str | None = None,
    nachricht: str | None = None,
    dringlichkeit: Dringlichkeit | None = None,
    funktion: str | None = None,
    argumente: dict | None = None,
    nummer: str | None = None,
    wochentage: list[Wochentag] | None = None,
    von: str | None = None,
    bis: str | None = None,
    ruhezeit_minuten: int | None = None,
) -> dict:
    angaben = dict(locals())
    del angaben["kontext"], angaben["id"]
    return kontext.panel.regeln.fuer_missa_aendern(id, **angaben)


def _loeschen_vorschau(kontext: Kontext, id: int) -> str:
    return kontext.panel.regeln.vorschau_loeschen(id)


@funktion(
    beschreibung="Löscht eine Regel endgültig. Die Nummer (id) liefert „regeln_auflisten“.",
    vorschau=_loeschen_vorschau,
)
def regel_loeschen(kontext: Kontext, id: int) -> dict:
    """
    id: Nummer der Regel
    """
    return kontext.panel.regeln.fuer_missa_loeschen(id)


regel_anlegen.__doc__ = _PARAMETER
regel_aendern.__doc__ = "\n    id: Nummer der Regel (aus regeln_auflisten)\n    aktiv: false pausiert die Regel, true schaltet sie wieder ein" + _PARAMETER
