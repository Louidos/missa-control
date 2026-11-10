"""Protokoll aller Funktionsaufrufe."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.gateway.modelle import Aufruf
from missa_control.zugaenge.schwaerzen import SCHWAERZER


class ProtokollDienst:
    def __init__(self, datenbank: Datenbank) -> None:
        self.datenbank = datenbank

    def eintragen(
        self,
        *,
        quelle: str,
        funktion: str,
        ok: bool,
        dauer_ms: int,
        client_name: str = "",
        integration_name: str = "",
        fehler: str = "",
        freigabe: str = "ohne",
    ) -> None:
        """Schreibt einen Eintrag. Parameter und Ergebnisse werden bewusst nicht gespeichert."""
        with self.datenbank.sitzung() as db:
            db.add(
                Aufruf(
                    zeit=zeit.jetzt(),
                    quelle=quelle,
                    client_name=client_name,
                    integration_name=integration_name,
                    funktion=funktion,
                    ok=ok,
                    fehler=SCHWAERZER.schwaerzen(fehler)[:1000],
                    dauer_ms=max(int(dauer_ms), 0),
                    freigabe=freigabe,
                )
            )
            db.commit()

    @staticmethod
    def suchen(
        db: Session,
        *,
        client: str | None = None,
        integration: str | None = None,
        suche: str | None = None,
        ok: bool | None = None,
        von: datetime | None = None,
        bis: datetime | None = None,
        limit: int = 100,
        versatz: int = 0,
    ) -> dict[str, Any]:
        bedingungen = []
        if client:
            bedingungen.append(Aufruf.client_name == client)
        if integration:
            bedingungen.append(Aufruf.integration_name == integration)
        if suche:
            muster = f"%{suche.strip()}%"
            bedingungen.append(or_(Aufruf.funktion.ilike(muster), Aufruf.fehler.ilike(muster)))
        if ok is not None:
            bedingungen.append(Aufruf.ok.is_(ok))
        if von is not None:
            bedingungen.append(Aufruf.zeit >= von)
        if bis is not None:
            bedingungen.append(Aufruf.zeit <= bis)
        anzahl = db.scalar(select(func.count()).select_from(Aufruf).where(*bedingungen)) or 0
        zeilen = db.scalars(
            select(Aufruf).where(*bedingungen).order_by(Aufruf.id.desc()).limit(limit).offset(versatz)
        )
        return {
            "anzahl": anzahl,
            "eintraege": [
                {
                    "id": aufruf.id,
                    "zeit": aufruf.zeit.isoformat(),
                    "quelle": aufruf.quelle,
                    "client": aufruf.client_name,
                    "integration": aufruf.integration_name,
                    "funktion": aufruf.funktion,
                    "ok": aufruf.ok,
                    "fehler": aufruf.fehler,
                    "dauer_ms": aufruf.dauer_ms,
                    "freigabe": aufruf.freigabe,
                }
                for aufruf in zeilen
            ],
            "clients": sorted(name for name in db.scalars(select(Aufruf.client_name).distinct()) if name),
            "integrationen": sorted(
                name for name in db.scalars(select(Aufruf.integration_name).distinct()) if name
            ),
        }

    def aufraeumen(self, tage: int) -> int:
        """Löscht Einträge, die älter als `tage` Tage sind."""
        with self.datenbank.sitzung() as db:
            ergebnis = db.execute(delete(Aufruf).where(Aufruf.zeit < zeit.jetzt() - timedelta(days=tage)))
            db.commit()
            return ergebnis.rowcount or 0
