"""Eingebaute Integration „Nextcloud-Kalender“: Termine lesen, eintragen, ändern und löschen (CalDAV)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from datetime import time as uhrzeit_typ
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from missa_control import zeit
from missa_control.sdk import Fehler, Kontext, funktion, verbindungstest

from .caldav import CalDav, Kalender, Termin

TAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
TAGE_LANG = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
HOECHSTENS_TAGE = 366
HOECHSTENS_TERMINE = 100
_RELATIV = {"heute": 0, "morgen": 1, "übermorgen": 2, "uebermorgen": 2, "gestern": -1}
_DATUM = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$|^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_UHRZEIT = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?(?::\d{2})?\s*(?:uhr)?$", re.IGNORECASE)
_SERIE = " Achtung: Das ist ein Serientermin – es betrifft alle Termine der Serie."


# ---------------------------------------------------------------------- Zeiten lesen und schreiben


def _zone(kontext: Kontext) -> ZoneInfo:
    return ZoneInfo(kontext.panel.einstellungen.zeitzone if kontext.panel is not None else "Europe/Zurich")


def _zeit_lesen(text: str, zone: ZoneInfo, feld: str) -> datetime | date:
    """„2026-11-12 14:00“, „12.11.2026“, „morgen 9:30“ → Zeitpunkt in Ortszeit bzw. Datum (ohne Uhrzeit)."""
    eingabe = text.strip().replace("T", " ").replace(",", " ")
    eingabe = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", eingabe).strip()  # Zeitzonen-Angaben: es gilt die Ortszeit
    teile = eingabe.split()
    heute = zeit.jetzt().astimezone(zone).date()
    tag: date | None = None
    if teile and teile[0].lower() in _RELATIV:
        tag = heute + timedelta(days=_RELATIV[teile[0].lower()])
    elif teile and (treffer := _DATUM.match(teile[0])):
        jahr, monat, zahl = (
            (treffer.group(1), treffer.group(2), treffer.group(3))
            if treffer.group(1)
            else (treffer.group(6), treffer.group(5), treffer.group(4))
        )
        try:
            tag = date(int(jahr), int(monat), int(zahl))
        except ValueError:
            tag = None
    uhr = _UHRZEIT.match(" ".join(teile[1:])) if len(teile) > 1 else None
    if tag is None or (len(teile) > 1 and uhr is None):
        raise Fehler(
            f"„{text}“ ({feld}) ist kein gültiger Zeitpunkt.",
            "Erwartet wird z. B. 2026-11-12 14:00, 12.11.2026 14:00, „morgen 9:30“ oder nur ein Datum (ganztägig).",
        )
    if uhr is None:
        return tag
    stunde, minute = int(uhr.group(1)), int(uhr.group(2) or 0)
    if stunde > 23 or minute > 59:
        raise Fehler(f"„{text}“ ({feld}) enthält keine gültige Uhrzeit.", "Erwartet wird z. B. 14:00.")
    return datetime.combine(tag, uhrzeit_typ(stunde, minute), tzinfo=zone)


def _tag(wert: datetime | date) -> str:
    return f"{TAGE[wert.weekday()]}, {wert.day:02d}.{wert.month:02d}.{wert.year}"


def _wann(beginn: datetime | date, ende: datetime | date, zone: ZoneInfo) -> str:
    """„Do, 12.11.2026, 14:00–15:00“ bzw. „Fr, 13.11.2026 bis So, 15.11.2026 (ganztägig)“."""
    if not isinstance(beginn, datetime):
        letzter = ende.date() if isinstance(ende, datetime) else ende
        return (
            f"{_tag(beginn)} (ganztägig)"
            if letzter <= beginn
            else f"{_tag(beginn)} bis {_tag(letzter)} (ganztägig)"
        )
    start = beginn.astimezone(zone)
    schluss = (ende if isinstance(ende, datetime) else beginn).astimezone(zone)
    if schluss.date() == start.date():
        zeit = f"{start:%H:%M}" if schluss <= start else f"{start:%H:%M}–{schluss:%H:%M}"
        return f"{_tag(start)}, {zeit}"
    return f"{_tag(start)}, {start:%H:%M} bis {_tag(schluss)}, {schluss:%H:%M}"


def _als_text(wert: datetime | date, zone: ZoneInfo) -> str:
    return (
        wert.astimezone(zone).isoformat(timespec="minutes")
        if isinstance(wert, datetime)
        else wert.isoformat()
    )


def _ansicht(termin: Termin, zone: ZoneInfo) -> dict[str, Any]:
    ansicht: dict[str, Any] = {
        "id": termin.uid,
        "titel": termin.titel,
        "wann": _wann(termin.beginn, termin.ende, zone),
        "beginn": _als_text(termin.beginn, zone),
        "ende": _als_text(termin.ende, zone),
        "ganztaegig": termin.ganztaegig,
        "kalender": termin.kalender,
    }
    if termin.ort:
        ansicht["ort"] = termin.ort
    if termin.beschreibung:
        ansicht["beschreibung"] = termin.beschreibung[:500]
    if termin.serie:
        ansicht["serie"] = True
    return ansicht


# ---------------------------------------------------------------------- Verbindung


def _pfad(adresse: str) -> str:
    return urlsplit(adresse).path.rstrip("/") + "/"


class _Verbindung:
    """Angemeldeter CalDAV-Zugriff für die Dauer eines Aufrufs."""

    def __init__(self, kontext: Kontext) -> None:
        zugang = kontext.zugang("zugang")
        self.kontext = kontext
        self._client = kontext.http(auth=(zugang.benutzer, zugang.wert))
        self.dav = CalDav(self._client, str(kontext.konfig["url"]))

    async def __aenter__(self) -> _Verbindung:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *fehler: Any) -> None:
        await self._client.__aexit__(*fehler)

    async def kalender(self, neu_lesen: bool = False) -> list[Kalender]:
        """Die Kalender des Benutzers – gemerkt vom letzten Test, damit Aufrufe schnell bleiben."""
        gemerkt = self.kontext.zustand.get("kalender")
        if gemerkt and not neu_lesen:
            return [Kalender(**eintrag) for eintrag in gemerkt]
        gefunden = await self.dav.kalender_finden()
        self.kontext.zustand["kalender"] = [
            {"adresse": k.adresse, "name": k.name, "schreibbar": k.schreibbar} for k in gefunden
        ]
        return gefunden

    async def ziel(self) -> Kalender:
        """Der Kalender, in den neue Termine kommen."""
        gewaehlt = _pfad(str(self.kontext.konfig.get("kalender", "")))
        for kalender in await self.kalender():
            if _pfad(kalender.adresse) == gewaehlt:
                return kalender
        raise Fehler(
            "Der gewählte Kalender wurde nicht gefunden.",
            f"Unter „Integrationen“ → „{self.kontext.name}“ bearbeiten und den Kalender neu auswählen.",
        )

    async def lesbare(self) -> list[Kalender]:
        if self.kontext.konfig.get("alle_kalender", True):
            return await self.kalender()
        return [await self.ziel()]


@verbindungstest
async def testen(kontext: Kontext) -> dict:
    async with _Verbindung(kontext) as verbindung:
        kalender = await verbindung.kalender(neu_lesen=True)
    if not kalender:
        raise Fehler(
            "Die Anmeldung klappt, aber es wurde kein Kalender gefunden.",
            "In der Nextcloud unter „Kalender“ mindestens einen Kalender anlegen.",
        )
    schreibbare = [k for k in kalender if k.schreibbar]
    if not schreibbare:
        raise Fehler(
            "Es gibt nur Kalender, in die nicht geschrieben werden darf.",
            "In der Nextcloud einen eigenen Kalender anlegen.",
        )
    benutzer = kontext.zugang("zugang").benutzer
    return {
        "meldung": f"Verbunden als {benutzer} – {len(kalender)} Kalender gefunden.",
        "details": [k.name + ("" if k.schreibbar else " (nur lesbar)") for k in kalender],
        "optionen": {"kalender": [{"wert": _pfad(k.adresse), "titel": k.name} for k in schreibbare]},
    }


# ---------------------------------------------------------------------- Funktionen für Missa


@funktion(
    beschreibung=(
        "Zeigt die Termine in einem Zeitraum. Ohne Angaben: die nächsten 7 Tage ab heute. "
        "Jeder Termin hat eine Nummer (id) – sie wird zum Ändern und Löschen gebraucht."
    ),
    schreibend=False,
)
async def termine_anzeigen(kontext: Kontext, von: str = "", bis: str = "", suche: str = "") -> dict:
    """
    von: Beginn des Zeitraums, z. B. 2026-11-12, „heute“ oder „morgen“ (Standard: heute)
    bis: Ende des Zeitraums, einschliesslich dieses Tages (Standard: 7 Tage nach „von“)
    suche: Nur Termine, in deren Titel, Ort oder Beschreibung dieses Wort vorkommt
    """
    zone = _zone(kontext)
    heute = zeit.jetzt().astimezone(zone)
    start = _zeit_lesen(von, zone, "von") if von.strip() else heute.date()
    start_zeit = (
        start if isinstance(start, datetime) else datetime.combine(start, uhrzeit_typ(0), tzinfo=zone)
    )
    if bis.strip():
        schluss = _zeit_lesen(bis, zone, "bis")
        ende_zeit = (
            schluss
            if isinstance(schluss, datetime)
            else datetime.combine(schluss + timedelta(days=1), uhrzeit_typ(0), tzinfo=zone)
        )
    else:
        ende_zeit = start_zeit + timedelta(days=7)
    if ende_zeit <= start_zeit:
        raise Fehler("Das Ende des Zeitraums liegt vor dem Beginn.", "„bis“ muss nach „von“ liegen.")
    if ende_zeit - start_zeit > timedelta(days=HOECHSTENS_TAGE):
        raise Fehler("Der Zeitraum ist zu lang.", f"Höchstens {HOECHSTENS_TAGE} Tage auf einmal.")

    async with _Verbindung(kontext) as verbindung:
        termine: list[Termin] = []
        for kalender in await verbindung.lesbare():
            termine.extend(await verbindung.dav.termine(kalender, start_zeit, ende_zeit))
    if suche.strip():
        wort = suche.strip().lower()
        termine = [t for t in termine if wort in f"{t.titel}\n{t.ort}\n{t.beschreibung}".lower()]
    termine.sort(
        key=lambda t: (_als_text(t.beginn, zone)[:10], not t.ganztaegig, _als_text(t.beginn, zone), t.titel)
    )
    letzter_tag = (ende_zeit - timedelta(seconds=1)).date()
    ergebnis: dict[str, Any] = {
        "heute": f"{TAGE_LANG[heute.weekday()]}, {heute.day:02d}.{heute.month:02d}.{heute.year}",
        "zeitraum": _tag(start_zeit)
        if letzter_tag == start_zeit.date()
        else f"{_tag(start_zeit)} bis {_tag(letzter_tag)}",
        "anzahl": len(termine),
        "termine": [_ansicht(termin, zone) for termin in termine[:HOECHSTENS_TERMINE]],
    }
    if len(termine) > HOECHSTENS_TERMINE:
        ergebnis["hinweis"] = (
            f"Es sind {len(termine)} Termine – angezeigt werden die ersten {HOECHSTENS_TERMINE}. Zeitraum eingrenzen."
        )
    elif not termine:
        ergebnis["hinweis"] = "In diesem Zeitraum gibt es keine Termine."
    return ergebnis


def _neuer_termin(
    kontext: Kontext, titel: str, beginn: str, ende: str
) -> tuple[str, datetime | date, datetime | date]:
    """Prüft die Angaben für einen neuen Termin (für die Vorschau und das Eintragen gleich)."""
    zone = _zone(kontext)
    name = " ".join(titel.split())
    if not name:
        raise Fehler("Der Termin braucht einen Titel.")
    start = _zeit_lesen(beginn, zone, "beginn")
    if ende.strip():
        schluss = _zeit_lesen(ende, zone, "ende")
        if isinstance(start, datetime) != isinstance(schluss, datetime):
            raise Fehler(
                "Beginn und Ende passen nicht zusammen.",
                "Entweder beide mit Uhrzeit angeben oder beide nur als Datum (ganztägig).",
            )
    else:
        schluss = start + timedelta(hours=1) if isinstance(start, datetime) else start
    if schluss < start:
        raise Fehler("Das Ende liegt vor dem Beginn.")
    return name, start, schluss


async def _eintragen_vorschau(
    kontext: Kontext, titel: str, beginn: str, ende: str = "", ort: str = "", beschreibung: str = ""
) -> str:
    name, start, schluss = _neuer_termin(kontext, titel, beginn, ende)
    async with _Verbindung(kontext) as verbindung:
        kalender = await verbindung.ziel()
    zusatz = f", Ort: {ort.strip()}" if ort.strip() else ""
    return f"Trägt in den Kalender „{kalender.name}“ ein: „{name}“ – {_wann(start, schluss, _zone(kontext))}{zusatz}"


@funktion(
    beschreibung="Trägt einen neuen Termin in den Kalender ein. Ohne Uhrzeit wird er ganztägig, ohne Ende dauert er eine Stunde.",
    vorschau=_eintragen_vorschau,
)
async def termin_eintragen(
    kontext: Kontext, titel: str, beginn: str, ende: str = "", ort: str = "", beschreibung: str = ""
) -> dict:
    """
    titel: Wie der Termin heisst
    beginn: Datum und Uhrzeit, z. B. 2026-11-12 14:00 oder „morgen 9:30“ – nur ein Datum bedeutet ganztägig
    ende: Datum und Uhrzeit des Endes (Standard: eine Stunde nach Beginn bzw. derselbe Tag)
    ort: Wo der Termin stattfindet
    beschreibung: Weitere Notizen zum Termin
    """
    name, start, schluss = _neuer_termin(kontext, titel, beginn, ende)
    zone = _zone(kontext)
    async with _Verbindung(kontext) as verbindung:
        kalender = await verbindung.ziel()
        termin = await verbindung.dav.anlegen(
            kalender,
            titel=name,
            beginn=start,
            ende=schluss,
            ort=ort.strip(),
            beschreibung=beschreibung.strip(),
        )
    return {
        "id": termin.uid,
        "meldung": f"Eingetragen: „{name}“ – {_wann(start, schluss, zone)} (Kalender „{kalender.name}“)",
    }


async def _aenderung(
    verbindung: _Verbindung, id: str, **neu: str | None
) -> tuple[Termin, str, dict[str, Any]]:
    """Holt den Termin und rechnet aus, was sich ändert (für die Vorschau und das Ändern gleich)."""
    zone = _zone(verbindung.kontext)
    termin, _, daten = await verbindung.dav.termin_holen(await verbindung.kalender(), id.strip())
    aenderung: dict[str, Any] = {}
    for feld in ("titel", "ort", "beschreibung"):
        if neu.get(feld) is not None:
            aenderung[feld] = (
                " ".join(str(neu[feld]).split()) if feld != "beschreibung" else str(neu[feld]).strip()
            )
    if "titel" in aenderung and not aenderung["titel"]:
        raise Fehler("Der Termin braucht einen Titel.")
    if neu.get("beginn") or neu.get("ende"):
        beginn = _zeit_lesen(str(neu["beginn"]), zone, "beginn") if neu.get("beginn") else termin.beginn
        if neu.get("ende"):
            ende = _zeit_lesen(str(neu["ende"]), zone, "ende")
        elif type(beginn) is type(termin.beginn) and type(termin.ende) is type(termin.beginn):
            ende = beginn + (termin.ende - termin.beginn)  # nur der Beginn ändert sich: die Dauer bleibt
        else:
            ende = beginn + timedelta(hours=1) if isinstance(beginn, datetime) else beginn
        if isinstance(beginn, datetime) != isinstance(ende, datetime):
            raise Fehler(
                "Beginn und Ende passen nicht zusammen.",
                "Entweder beide mit Uhrzeit angeben oder beide nur als Datum (ganztägig).",
            )
        if ende < beginn:
            raise Fehler("Das Ende liegt vor dem Beginn.")
        aenderung["beginn"], aenderung["ende"] = beginn, ende
    if not aenderung:
        raise Fehler(
            "Es wurde nichts angegeben, das sich ändern soll.",
            "Mindestens titel, beginn, ende, ort oder beschreibung angeben.",
        )
    return termin, daten, aenderung


async def _aendern_vorschau(
    kontext: Kontext,
    id: str,
    titel: str | None = None,
    beginn: str | None = None,
    ende: str | None = None,
    ort: str | None = None,
    beschreibung: str | None = None,
) -> str:
    zone = _zone(kontext)
    async with _Verbindung(kontext) as verbindung:
        termin, _, aenderung = await _aenderung(
            verbindung, id, titel=titel, beginn=beginn, ende=ende, ort=ort, beschreibung=beschreibung
        )
    teile = []
    if "titel" in aenderung:
        teile.append(f"Titel „{aenderung['titel']}“")
    if "beginn" in aenderung:
        teile.append(_wann(aenderung["beginn"], aenderung["ende"], zone))
    if "ort" in aenderung:
        teile.append(f"Ort „{aenderung['ort']}“" if aenderung["ort"] else "ohne Ort")
    if "beschreibung" in aenderung:
        teile.append("neue Beschreibung")
    return (
        f"Ändert den Termin „{termin.titel}“ ({_wann(termin.beginn, termin.ende, zone)}, Kalender „{termin.kalender}“). "
        f"Neu: {'; '.join(teile)}." + (_SERIE if termin.serie else "")
    )


@funktion(
    beschreibung="Ändert einen bestehenden Termin. Nur die genannten Angaben ändern sich. Die Nummer (id) liefert „termine_anzeigen“.",
    vorschau=_aendern_vorschau,
)
async def termin_aendern(
    kontext: Kontext,
    id: str,
    titel: str | None = None,
    beginn: str | None = None,
    ende: str | None = None,
    ort: str | None = None,
    beschreibung: str | None = None,
) -> dict:
    """
    id: Nummer des Termins (aus termine_anzeigen)
    titel: Neuer Titel
    beginn: Neuer Beginn, z. B. 2026-11-12 16:00 – ohne neues Ende behält der Termin seine Dauer
    ende: Neues Ende
    ort: Neuer Ort (leerer Text entfernt den Ort)
    beschreibung: Neue Beschreibung
    """
    zone = _zone(kontext)
    async with _Verbindung(kontext) as verbindung:
        termin, daten, aenderung = await _aenderung(
            verbindung, id, titel=titel, beginn=beginn, ende=ende, ort=ort, beschreibung=beschreibung
        )
        await verbindung.dav.aendern(termin, daten, **aenderung)
    neuer_titel = aenderung.get("titel", termin.titel)
    wann = _wann(aenderung.get("beginn", termin.beginn), aenderung.get("ende", termin.ende), zone)
    return {"id": termin.uid, "meldung": f"Geändert: „{neuer_titel}“ – {wann}"}


async def _loeschen_vorschau(kontext: Kontext, id: str) -> str:
    async with _Verbindung(kontext) as verbindung:
        termin, _, _ = await verbindung.dav.termin_holen(await verbindung.kalender(), id.strip())
    return (
        f"Löscht den Termin „{termin.titel}“ – {_wann(termin.beginn, termin.ende, _zone(kontext))} "
        f"(Kalender „{termin.kalender}“)." + (_SERIE if termin.serie else "")
    )


@funktion(
    beschreibung="Löscht einen Termin endgültig. Die Nummer (id) liefert „termine_anzeigen“.",
    vorschau=_loeschen_vorschau,
)
async def termin_loeschen(kontext: Kontext, id: str) -> dict:
    """
    id: Nummer des Termins (aus termine_anzeigen)
    """
    async with _Verbindung(kontext) as verbindung:
        termin, _, _ = await verbindung.dav.termin_holen(await verbindung.kalender(), id.strip())
        await verbindung.dav.loeschen(termin)
    return {
        "id": termin.uid,
        "meldung": f"Gelöscht: „{termin.titel}“ – {_wann(termin.beginn, termin.ende, _zone(kontext))}",
    }
