"""Freigaben: Aufrufe von „erst nachfragen“-Funktionen warten hier auf eine Entscheidung."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.fehler import PanelFehler
from missa_control.gateway.modelle import (
    FREIGABE_ABGELAUFEN,
    FREIGABE_ABGELEHNT,
    FREIGABE_ERLAUBT,
    FREIGABE_OFFEN,
    Freigabe,
)

log = logging.getLogger(__name__)


def ansicht(freigabe: Freigabe) -> dict[str, Any]:
    return {
        "id": freigabe.id,
        "erstellt": freigabe.erstellt.isoformat(),
        "laeuft_ab": freigabe.laeuft_ab.isoformat(),
        "client": freigabe.client_name,
        "integration": freigabe.integration_name,
        "funktion": freigabe.funktion,
        "beschreibung": freigabe.beschreibung,
        # Ein Satz der Integration, was genau passieren würde (leer, wenn sie keinen liefert).
        "vorschau": freigabe.vorschau or "",
        "argumente": freigabe.argumente or {},
        "status": freigabe.status,
        "entschieden": freigabe.entschieden.isoformat() if freigabe.entschieden else None,
    }


class FreigabeDienst:
    def __init__(self, datenbank: Datenbank, ereignisse: EreignisDienst, frist_sekunden: float) -> None:
        self.datenbank = datenbank
        self.ereignisse = ereignisse
        self.frist_sekunden = frist_sekunden
        self._wartende: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Future[str]]] = {}
        # Nach einem Neustart wartet niemand mehr auf alte Anfragen.
        with datenbank.sitzung() as db:
            db.execute(
                update(Freigabe)
                .where(Freigabe.status == FREIGABE_OFFEN)
                .values(status=FREIGABE_ABGELAUFEN, entschieden=zeit.jetzt())
            )
            db.commit()

    async def anfragen(
        self,
        *,
        client_name: str,
        integration_name: str,
        funktion: str,
        beschreibung: str,
        argumente: dict[str, Any],
        vorschau: str = "",
    ) -> str:
        """Hält den Aufruf an, bis im Panel entschieden wurde. Gibt erlaubt, abgelehnt oder abgelaufen zurück."""
        with self.datenbank.sitzung() as db:
            jetzt = zeit.jetzt()
            freigabe = Freigabe(
                erstellt=jetzt,
                laeuft_ab=jetzt + timedelta(seconds=self.frist_sekunden),
                client_name=client_name,
                integration_name=integration_name,
                funktion=funktion,
                beschreibung=beschreibung,
                vorschau=vorschau,
                argumente=argumente,
                status=FREIGABE_OFFEN,
            )
            db.add(freigabe)
            db.commit()
            freigabe_id = freigabe.id

        loop = asyncio.get_running_loop()
        antwort: asyncio.Future[str] = loop.create_future()
        self._wartende[freigabe_id] = (loop, antwort)
        self.ereignisse.melden(
            "freigabe",
            f"Freigabe nötig: {funktion}",
            f"„{client_name}“ möchte „{funktion}“ ausführen. Bitte im Panel unter „Freigaben“ erlauben oder ablehnen.",
            dringlichkeit="hoch",
            quelle=integration_name,
            daten={"freigabe_id": freigabe_id, "funktion": funktion, "client": client_name},
        )
        try:
            return await asyncio.wait_for(antwort, timeout=self.frist_sekunden)
        except TimeoutError:
            self._abschliessen(freigabe_id, FREIGABE_ABGELAUFEN)
            return FREIGABE_ABGELAUFEN
        except asyncio.CancelledError:
            # Der Client hat die Verbindung beendet – die Anfrage ist damit hinfällig.
            self._abschliessen(freigabe_id, FREIGABE_ABGELAUFEN)
            raise
        finally:
            self._wartende.pop(freigabe_id, None)

    def _abschliessen(self, freigabe_id: int, status: str) -> None:
        with self.datenbank.sitzung() as db:
            db.execute(
                update(Freigabe)
                .where(Freigabe.id == freigabe_id, Freigabe.status == FREIGABE_OFFEN)
                .values(status=status, entschieden=zeit.jetzt())
            )
            db.commit()

    def entscheiden(self, db: Session, freigabe_id: int, erlauben: bool) -> dict[str, Any]:
        """„Erlauben“ oder „Ablehnen“ im Panel. Der wartende Aufruf läuft sofort weiter."""
        freigabe = db.get(Freigabe, freigabe_id)
        if freigabe is None:
            raise PanelFehler(404, "Diese Freigabe gibt es nicht (mehr).")
        wartender = self._wartende.get(freigabe_id)
        if freigabe.status != FREIGABE_OFFEN or wartender is None:
            if freigabe.status == FREIGABE_OFFEN:
                freigabe.status = FREIGABE_ABGELAUFEN
                freigabe.entschieden = zeit.jetzt()
                db.commit()
            raise PanelFehler(
                409,
                "Diese Anfrage wartet nicht mehr auf eine Entscheidung.",
                "Sie ist abgelaufen oder wurde schon entschieden. Missa muss die Aktion erneut anstossen.",
            )
        freigabe.status = FREIGABE_ERLAUBT if erlauben else FREIGABE_ABGELEHNT
        freigabe.entschieden = zeit.jetzt()
        db.commit()
        loop, antwort = wartender
        status = freigabe.status

        def setzen() -> None:
            if not antwort.done():
                antwort.set_result(status)

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(setzen)
        return ansicht(freigabe)

    @staticmethod
    def offene(db: Session) -> list[dict[str, Any]]:
        abfrage = select(Freigabe).where(Freigabe.status == FREIGABE_OFFEN).order_by(Freigabe.id)
        return [ansicht(freigabe) for freigabe in db.scalars(abfrage)]

    @staticmethod
    def anzahl_offen(db: Session) -> int:
        return (
            db.scalar(select(func.count()).select_from(Freigabe).where(Freigabe.status == FREIGABE_OFFEN))
            or 0
        )

    @staticmethod
    def verlauf(db: Session, limit: int = 50) -> list[dict[str, Any]]:
        abfrage = (
            select(Freigabe)
            .where(Freigabe.status != FREIGABE_OFFEN)
            .order_by(Freigabe.id.desc())
            .limit(limit)
        )
        return [ansicht(freigabe) for freigabe in db.scalars(abfrage)]

    def aufraeumen(self, tage: int) -> int:
        with self.datenbank.sitzung() as db:
            ergebnis = db.execute(
                delete(Freigabe).where(
                    Freigabe.status != FREIGABE_OFFEN, Freigabe.erstellt < zeit.jetzt() - timedelta(days=tage)
                )
            )
            db.commit()
            return ergebnis.rowcount or 0
