"""Der einzige Kontakt des Panels zu missa-core: ein lesender HTTP-GET auf die Health-URL.

Mehr geschieht hier nicht und darf hier nicht geschehen (oberste Regel): keine anderen Anfragen,
nichts wird an missa-core gesendet oder dort verändert. Ohne `MISSA_CORE_HEALTH_URL` wird missa-core
gar nicht angesprochen – der Knoten in der Übersicht ist dann grau.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx2

from missa_control import zeit

log = logging.getLogger(__name__)

ANTWORT_SEKUNDEN = 4.0


class MissaCore:
    def __init__(self, health_url: str | None) -> None:
        self.health_url = (health_url or "").strip() or None
        self.erreichbar: bool | None = None  # None: noch nicht geprüft
        self.meldung = ""
        self.geprueft: datetime | None = None
        self.antwort_ms: int | None = None

    async def pruefen(self) -> None:
        """Fragt die Health-URL ab (nur GET). Jede Antwort unter 400 gilt als „läuft“."""
        if self.health_url is None:
            return
        start = time.monotonic()
        try:
            async with httpx2.AsyncClient(timeout=ANTWORT_SEKUNDEN, follow_redirects=False) as client:
                antwort = await client.get(self.health_url)
        except Exception as fehler:
            self.erreichbar, self.antwort_ms = False, None
            self.meldung = f"missa-core antwortet nicht ({type(fehler).__name__})."
        else:
            self.antwort_ms = int((time.monotonic() - start) * 1000)
            self.erreichbar = antwort.status_code < 400
            self.meldung = (
                "missa-core antwortet."
                if self.erreichbar
                else f"missa-core meldet einen Fehler (HTTP {antwort.status_code})."
            )
        self.geprueft = zeit.jetzt()

    def stand(self) -> tuple[str, str]:
        """(Status, Satz) für den Knoten in der Übersicht."""
        if self.health_url is None:
            return "grau", "Nicht eingerichtet – ohne Health-URL wird missa-core nicht abgefragt."
        if self.erreichbar is None:
            return "grau", "Wird gleich zum ersten Mal geprüft."
        return ("ok" if self.erreichbar else "fehler"), self.meldung
