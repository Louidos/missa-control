"""Ereignisse speichern und an wartende Clients verteilen."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.ereignisse.modelle import DRINGLICHKEITEN, Ereignis
from missa_control.zugaenge.schwaerzen import SCHWAERZER

log = logging.getLogger(__name__)

WARTESCHLANGE = 500


def ansicht(ereignis: Ereignis) -> dict[str, Any]:
    return {
        "id": ereignis.id,
        "zeit": ereignis.zeit.isoformat(),
        "art": ereignis.art,
        "quelle": ereignis.quelle,
        "titel": ereignis.titel,
        "nachricht": ereignis.nachricht,
        "dringlichkeit": ereignis.dringlichkeit,
        "daten": ereignis.daten or {},
    }


class EreignisDienst:
    """`melden()` darf aus jedem Thread aufgerufen werden (z. B. aus dem MQTT-Empfang)."""

    def __init__(self, datenbank: Datenbank) -> None:
        self.datenbank = datenbank
        self._schlange_je_abo: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = {}
        self._naechstes_abo = 0
        self._sperre = threading.Lock()
        # Interne Zuhörer (z. B. die Regeln): werden bei jedem Ereignis direkt aufgerufen.
        self.zuhoerer: list[Callable[[dict[str, Any]], None]] = []

    def melden(
        self,
        art: str,
        titel: str,
        nachricht: str = "",
        *,
        dringlichkeit: str = "normal",
        quelle: str = "",
        daten: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Speichert ein Ereignis und verteilt es an alle, die gerade zuhören."""
        if dringlichkeit not in DRINGLICHKEITEN:
            dringlichkeit = "normal"
        with self.datenbank.sitzung() as db:
            ereignis = Ereignis(
                zeit=zeit.jetzt(),
                art=art,
                quelle=quelle,
                titel=SCHWAERZER.schwaerzen(titel),
                nachricht=SCHWAERZER.schwaerzen(nachricht),
                dringlichkeit=dringlichkeit,
                daten=daten or {},
            )
            db.add(ereignis)
            db.commit()
            inhalt = ansicht(ereignis)

        with self._sperre:
            abos = list(self._schlange_je_abo.values())
        for loop, schlange in abos:
            with contextlib.suppress(RuntimeError):  # Loop schon beendet
                loop.call_soon_threadsafe(self._einreihen, schlange, inhalt)
        for zuhoerer in list(self.zuhoerer):
            try:
                zuhoerer(inhalt)
            except Exception:
                log.exception("Fehler in einem Ereignis-Zuhörer")
        return inhalt

    @staticmethod
    def _einreihen(schlange: asyncio.Queue[dict[str, Any]], inhalt: dict[str, Any]) -> None:
        if schlange.full():  # langsamer Client: ältestes Ereignis verwerfen (er kann per GET nachladen)
            with contextlib.suppress(asyncio.QueueEmpty):
                schlange.get_nowait()
        schlange.put_nowait(inhalt)

    async def abonnieren(self, nach_id: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Liefert zuerst verpasste Ereignisse (nach `nach_id`), danach laufend alle neuen."""
        schlange: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=WARTESCHLANGE)
        with self._sperre:
            abo = self._naechstes_abo
            self._naechstes_abo += 1
            self._schlange_je_abo[abo] = (asyncio.get_running_loop(), schlange)
        try:
            letzte = nach_id or 0
            if nach_id is not None:
                with self.datenbank.sitzung() as db:
                    for inhalt in self.seit(db, nach_id=nach_id, limit=WARTESCHLANGE):
                        letzte = inhalt["id"]
                        yield inhalt
            while True:
                inhalt = await schlange.get()
                if inhalt["id"] > letzte:
                    letzte = inhalt["id"]
                    yield inhalt
        finally:
            with self._sperre:
                self._schlange_je_abo.pop(abo, None)

    @staticmethod
    def seit(
        db: Session,
        *,
        nach_id: int | None = None,
        seit_zeit: datetime | None = None,
        art: str | None = None,
        limit: int = 200,
        neueste_zuerst: bool = False,
    ) -> list[dict[str, Any]]:
        abfrage = select(Ereignis)
        if nach_id is not None:
            abfrage = abfrage.where(Ereignis.id > nach_id)
        if seit_zeit is not None:
            abfrage = abfrage.where(Ereignis.zeit >= seit_zeit)
        if art:
            abfrage = abfrage.where(Ereignis.art == art)
        abfrage = abfrage.order_by(Ereignis.id.desc() if neueste_zuerst else Ereignis.id).limit(limit)
        return [ansicht(ereignis) for ereignis in db.scalars(abfrage)]

    def aufraeumen(self, tage: int) -> int:
        """Löscht Ereignisse, die älter als `tage` Tage sind."""
        with self.datenbank.sitzung() as db:
            ergebnis = db.execute(delete(Ereignis).where(Ereignis.zeit < zeit.jetzt() - timedelta(days=tage)))
            db.commit()
            return ergebnis.rowcount or 0
