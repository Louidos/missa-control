"""Ein kleiner CalDAV-Client: Kalender finden, Termine lesen, anlegen, ändern und löschen.

Spricht den Standard (RFC 4791), so wie ihn Nextcloud anbietet – funktioniert deshalb auch mit
anderen CalDAV-Servern. Zeiten gehen als UTC an den Server; die Umrechnung in die Ortszeit macht `main.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx2
from dateutil.rrule import rrulestr
from icalendar import Calendar, Event

from missa_control.sdk import Fehler

D = "{DAV:}"
C = "{urn:ietf:params:xml:ns:caldav}"
XML = {"Content-Type": "application/xml; charset=utf-8"}
_SCHREIBRECHTE = (f"{D}write", f"{D}write-content", f"{D}all", f"{D}bind")


@dataclass
class Kalender:
    adresse: str  # vollständige URL der Kalender-Sammlung (endet mit /)
    name: str
    schreibbar: bool = True


@dataclass
class Termin:
    uid: str
    titel: str
    beginn: datetime | date
    ende: datetime | date
    ganztaegig: bool
    ort: str = ""
    beschreibung: str = ""
    kalender: str = ""
    # Teil eines Serientermins (wiederholt sich)
    serie: bool = False
    # Wo der Termin auf dem Server liegt – zum Ändern und Löschen
    adresse: str = ""
    etag: str = ""


def _utc(zeitpunkt: datetime) -> str:
    return zeitpunkt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _als_zeitpunkt(wert: datetime | date) -> datetime:
    """Zum Vergleichen und Sortieren: ein Datum ohne Uhrzeit zählt als Mitternacht (UTC)."""
    if isinstance(wert, datetime):
        return wert if wert.tzinfo else wert.replace(tzinfo=UTC)
    return datetime(wert.year, wert.month, wert.day, tzinfo=UTC)


class CalDav:
    def __init__(self, client: httpx2.AsyncClient, basis_url: str) -> None:
        self.client = client
        self.basis = basis_url.rstrip("/") + "/"

    # ------------------------------------------------------------------ Anfragen

    async def _anfrage(
        self, methode: str, url: str, *, inhalt: str | None = None, tiefe: str | None = None, **kopf: str
    ) -> httpx2.Response:
        headers = dict(kopf)
        if tiefe is not None:
            headers["Depth"] = tiefe
        if inhalt is not None:
            headers.setdefault("Content-Type", XML["Content-Type"])
        return await self.client.request(
            methode, url, content=inhalt.encode() if inhalt is not None else None, headers=headers
        )

    async def _propfind(self, url: str, eigenschaften: str, tiefe: str = "0") -> list[ET.Element]:
        inhalt = (
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:prop>{eigenschaften}</d:prop></d:propfind>"
        )
        antwort = await self._anfrage("PROPFIND", url, inhalt=inhalt, tiefe=tiefe)
        antwort.raise_for_status()
        return self._antworten(antwort)

    @staticmethod
    def _antworten(antwort: httpx2.Response) -> list[ET.Element]:
        try:
            return ET.fromstring(antwort.content).findall(f"{D}response")
        except ET.ParseError as fehler:
            raise Fehler(
                "Die Antwort des Servers ist kein gültiges CalDAV.",
                "Stimmt die Adresse? Erwartet wird die Adresse der Nextcloud, z. B. https://cloud.example.ch",
            ) from fehler

    @staticmethod
    def _verweis(antworten: list[ET.Element], eigenschaft: str) -> str | None:
        for antwort in antworten:
            verweis = antwort.find(f"{D}propstat/{D}prop/{eigenschaft}/{D}href")
            if verweis is not None and verweis.text:
                return verweis.text.strip()
        return None

    # ------------------------------------------------------------------ Kalender finden

    async def _wurzel(self) -> tuple[str, str]:
        """Findet den DAV-Einstieg: bei Nextcloud unter /remote.php/dav/, sonst die Adresse selbst."""
        kandidaten = [self.basis]
        if "remote.php/dav" not in self.basis:
            kandidaten.insert(0, urljoin(self.basis, "remote.php/dav/"))
        letzter: httpx2.Response | None = None
        for url in kandidaten:
            inhalt = '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
            antwort = await self._anfrage("PROPFIND", url, inhalt=inhalt, tiefe="0")
            if antwort.status_code == 207:
                benutzer = self._verweis(self._antworten(antwort), f"{D}current-user-principal")
                if benutzer:
                    return url, urljoin(url, benutzer)
            letzter = antwort
            if antwort.status_code == 401:
                break  # falscher Zugang: an anderer Stelle weiterzusuchen bringt nichts
        if letzter is not None and letzter.status_code not in (207, 404, 405):
            letzter.raise_for_status()  # z. B. 401: das Panel macht daraus eine verständliche Meldung
        raise Fehler(
            "Unter dieser Adresse wurde kein Kalender-Dienst (CalDAV) gefunden.",
            "Bitte die Adresse der Nextcloud angeben, so wie sie im Browser steht, z. B. https://cloud.example.ch",
        )

    async def kalender_finden(self) -> list[Kalender]:
        """Alle Kalender des angemeldeten Benutzers (ohne Aufgabenlisten, Papierkorb und Postfächer)."""
        _, benutzer = await self._wurzel()
        zuhause = self._verweis(
            await self._propfind(benutzer, "<c:calendar-home-set/>"), f"{C}calendar-home-set"
        )
        if not zuhause:
            raise Fehler(
                "Der Server nennt keinen Ort für Kalender.", "Ist die Kalender-App in der Nextcloud aktiv?"
            )
        antworten = await self._propfind(
            urljoin(benutzer, zuhause),
            "<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/><d:current-user-privilege-set/>",
            tiefe="1",
        )
        gefunden: list[Kalender] = []
        for antwort in antworten:
            eigenschaften = antwort.find(f"{D}propstat/{D}prop")
            verweis = antwort.findtext(f"{D}href")
            if eigenschaften is None or not verweis:
                continue
            if eigenschaften.find(f"{D}resourcetype/{C}calendar") is None:
                continue
            arten = [
                comp.get("name")
                for comp in eigenschaften.findall(f"{C}supported-calendar-component-set/{C}comp")
            ]
            if arten and "VEVENT" not in arten:
                continue  # reine Aufgabenliste
            rechte = eigenschaften.find(f"{D}current-user-privilege-set")
            schreibbar = rechte is None or any(
                rechte.find(f"{D}privilege/{recht}") is not None for recht in _SCHREIBRECHTE
            )
            adresse = urljoin(benutzer, verweis.strip())
            name = (eigenschaften.findtext(f"{D}displayname") or "").strip()
            gefunden.append(
                Kalender(
                    adresse=adresse if adresse.endswith("/") else adresse + "/",
                    name=name or urlsplit(adresse).path.rstrip("/").rsplit("/", 1)[-1],
                    schreibbar=schreibbar,
                )
            )
        return sorted(gefunden, key=lambda kalender: kalender.name.lower())

    # ------------------------------------------------------------------ Termine lesen

    async def _bericht(
        self, kalender: Kalender, filter_xml: str, daten_xml: str = "<c:calendar-data/>"
    ) -> list[tuple[str, str, str]]:
        """Führt eine Abfrage aus. Gibt je Treffer (Adresse, ETag, Kalenderdaten) zurück."""
        inhalt = (
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:prop><d:getetag/>{daten_xml}</d:prop>"
            f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">{filter_xml}'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        antwort = await self._anfrage("REPORT", kalender.adresse, inhalt=inhalt, tiefe="1")
        antwort.raise_for_status()
        treffer = []
        for eintrag in self._antworten(antwort):
            eigenschaften = eintrag.find(f"{D}propstat/{D}prop")
            daten = eigenschaften.findtext(f"{C}calendar-data") if eigenschaften is not None else None
            if daten:
                treffer.append(
                    (
                        urljoin(kalender.adresse, (eintrag.findtext(f"{D}href") or "").strip()),
                        (eigenschaften.findtext(f"{D}getetag") or "").strip(),  # type: ignore[union-attr]
                        daten,
                    )
                )
        return treffer

    async def termine(self, kalender: Kalender, von: datetime, bis: datetime) -> list[Termin]:
        """Alle Termine, die den Zeitraum berühren. Serientermine werden in einzelne Termine aufgelöst."""
        bereich = f'start="{_utc(von)}" end="{_utc(bis)}"'
        treffer = await self._bericht(
            kalender,
            f"<c:time-range {bereich}/>",
            f"<c:calendar-data><c:expand {bereich}/></c:calendar-data>",
        )
        termine: list[Termin] = []
        for adresse, etag, daten in treffer:
            for termin in termine_aus_ical(daten, von, bis):
                termin.kalender, termin.adresse, termin.etag = kalender.name, adresse, etag
                termine.append(termin)
        return sorted(termine, key=lambda termin: (_als_zeitpunkt(termin.beginn), termin.titel))

    async def termin_holen(self, kalender_liste: list[Kalender], uid: str) -> tuple[Termin, Kalender, str]:
        """Sucht einen Termin anhand seiner Nummer (UID). Gibt Termin, Kalender und die Rohdaten zurück."""
        suche = f'<c:prop-filter name="UID"><c:text-match collation="i;octet">{escape(uid)}</c:text-match></c:prop-filter>'
        for kalender in kalender_liste:
            for adresse, etag, daten in await self._bericht(kalender, suche):
                for termin in termine_aus_ical(daten, None, None):
                    if termin.uid == uid:
                        termin.kalender, termin.adresse, termin.etag = kalender.name, adresse, etag
                        return termin, kalender, daten
        raise Fehler(
            f"Den Termin mit der Nummer „{uid}“ gibt es nicht (mehr).",
            "Die Nummer (id) eines Termins liefert „termine_anzeigen“.",
        )

    # ------------------------------------------------------------------ Termine schreiben

    async def anlegen(
        self,
        kalender: Kalender,
        *,
        titel: str,
        beginn: datetime | date,
        ende: datetime | date,
        ort: str = "",
        beschreibung: str = "",
    ) -> Termin:
        uid = str(uuid.uuid4())
        termin = Event()
        termin.add("uid", uid)
        termin.add("dtstamp", datetime.now(UTC))
        termin.add("summary", titel)
        _zeiten_setzen(termin, beginn, ende)
        if ort:
            termin.add("location", ort)
        if beschreibung:
            termin.add("description", beschreibung)
        huelle = Calendar()
        huelle.add("prodid", "-//Missa Control//Kalender//DE")
        huelle.add("version", "2.0")
        huelle.add_component(termin)
        adresse = kalender.adresse + uid + ".ics"
        antwort = await self.client.put(
            adresse,
            content=huelle.to_ical(),
            headers={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
        )
        antwort.raise_for_status()
        return Termin(
            uid=uid,
            titel=titel,
            beginn=beginn,
            ende=ende,
            ganztaegig=not isinstance(beginn, datetime),
            ort=ort,
            beschreibung=beschreibung,
            kalender=kalender.name,
            adresse=adresse,
            etag=antwort.headers.get("etag", ""),
        )

    async def aendern(self, termin: Termin, daten: str, **neu: Any) -> None:
        """Schreibt geänderte Felder zurück. `neu`: titel, beginn, ende, ort, beschreibung (nur die genannten)."""
        huelle = Calendar.from_ical(daten)
        haupt = next(
            (
                teil
                for teil in huelle.walk("VEVENT")
                if str(teil.get("uid")) == termin.uid and teil.get("recurrence-id") is None
            ),
            None,
        )
        if haupt is None:
            raise Fehler("Dieser Termin lässt sich nicht ändern.", "Bitte direkt in der Nextcloud ändern.")
        for feld, name in (("titel", "summary"), ("ort", "location"), ("beschreibung", "description")):
            if feld in neu:
                haupt.pop(name, None)
                if neu[feld]:
                    haupt.add(name, neu[feld])
        if "beginn" in neu or "ende" in neu:
            for name in ("dtstart", "dtend", "duration"):
                haupt.pop(name, None)
            _zeiten_setzen(haupt, neu.get("beginn", termin.beginn), neu.get("ende", termin.ende))
        folge = int(haupt.get("sequence", 0)) + 1
        for name, wert in (
            ("sequence", folge),
            ("last-modified", datetime.now(UTC)),
            ("dtstamp", datetime.now(UTC)),
        ):
            haupt.pop(name, None)
            haupt.add(name, wert)
        kopf = {"Content-Type": "text/calendar; charset=utf-8"}
        if termin.etag:
            kopf["If-Match"] = termin.etag
        antwort = await self.client.put(termin.adresse, content=huelle.to_ical(), headers=kopf)
        _geaendert_pruefen(antwort)

    async def loeschen(self, termin: Termin) -> None:
        antwort = await self.client.delete(
            termin.adresse, headers={"If-Match": termin.etag} if termin.etag else {}
        )
        _geaendert_pruefen(antwort)


def _geaendert_pruefen(antwort: httpx2.Response) -> None:
    if antwort.status_code == 412:
        raise Fehler(
            "Der Termin wurde inzwischen an anderer Stelle geändert.",
            "Bitte die Termine neu anzeigen lassen und es dann noch einmal versuchen.",
        )
    antwort.raise_for_status()


def _zeiten_setzen(termin: Any, beginn: datetime | date, ende: datetime | date) -> None:
    if isinstance(beginn, datetime):
        termin.add("dtstart", beginn.astimezone(UTC))
        termin.add("dtend", _als_zeitpunkt(ende).astimezone(UTC))
    else:
        # Ganztägig: das Ende zählt in CalDAV nicht mehr mit, deshalb der Tag danach.
        letzter = ende.date() if isinstance(ende, datetime) else ende
        termin.add("dtstart", beginn)
        termin.add("dtend", max(letzter, beginn) + timedelta(days=1))


def termine_aus_ical(daten: str, von: datetime | None, bis: datetime | None) -> list[Termin]:
    """Liest Termine aus Kalenderdaten. Mit Zeitraum werden Serientermine aufgelöst und eingegrenzt."""
    try:
        huelle = Calendar.from_ical(daten)
    except ValueError:
        return []
    ergebnis: list[Termin] = []
    for teil in huelle.walk("VEVENT"):
        if str(teil.get("status", "")).upper() == "CANCELLED" or teil.get("dtstart") is None:
            continue
        beginn = teil.decoded("dtstart")
        ganztaegig = not isinstance(beginn, datetime)
        if teil.get("dtend") is not None:
            ende = teil.decoded("dtend")
        elif teil.get("duration") is not None:
            ende = beginn + teil.decoded("duration")
        else:
            ende = beginn + timedelta(days=1) if ganztaegig else beginn
        if ganztaegig and ende > beginn:
            ende = ende - timedelta(days=1)  # das Ende zählt nicht mit → letzter Tag des Termins
        regel = teil.get("rrule")
        termin = Termin(
            uid=str(teil.get("uid", "")),
            titel=str(teil.get("summary", "")) or "(ohne Titel)",
            beginn=beginn,
            ende=ende,
            ganztaegig=ganztaegig,
            ort=str(teil.get("location", "")),
            beschreibung=str(teil.get("description", "")),
            serie=regel is not None or teil.get("recurrence-id") is not None,
        )
        if regel is None or von is None or bis is None:
            ergebnis.append(termin)
            continue
        # Der Server hat die Serie nicht aufgelöst: die Wiederholungen im Zeitraum selbst berechnen.
        dauer = ende - beginn
        start = _als_zeitpunkt(beginn)
        ausnahmen = {_als_zeitpunkt(tag.dt) for liste in _als_liste(teil.get("exdate")) for tag in liste.dts}
        try:
            wiederholungen = rrulestr(regel.to_ical().decode(), dtstart=start).between(
                von - dauer, bis, inc=True
            )
        except (ValueError, TypeError):
            wiederholungen = [start]
        for zeitpunkt in wiederholungen[:500]:
            if zeitpunkt in ausnahmen:
                continue
            neuer_beginn: datetime | date = (
                zeitpunkt.date() if ganztaegig else zeitpunkt.astimezone(start.tzinfo)
            )
            ergebnis.append(
                Termin(**{**termin.__dict__, "beginn": neuer_beginn, "ende": neuer_beginn + dauer})
            )
    if von is not None and bis is not None:
        ergebnis = [
            termin
            for termin in ergebnis
            if _als_zeitpunkt(termin.beginn) < bis
            and _als_zeitpunkt(termin.ende) + (timedelta(days=1) if termin.ganztaegig else timedelta(0)) > von
        ]
    return ergebnis


def _als_liste(wert: Any) -> list[Any]:
    if wert is None:
        return []
    return wert if isinstance(wert, list) else [wert]
