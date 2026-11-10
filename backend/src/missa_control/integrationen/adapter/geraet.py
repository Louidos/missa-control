"""Art `geraet`: ein per MQTT angebundenes Gerät (ESP32, Raspberry Pi Pico).

Die eigentliche Arbeit macht der Geräte-Dienst (`geraete/dienst.py`). Der Adapter verbindet ihn mit
dem Integrations-Framework: So bekommen Geräte Rechte pro Funktion, Freigaben und Protokoll wie alles andere.
"""

from __future__ import annotations

from typing import Any

import anyio
from sqlalchemy.orm import Session

from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.integrationen.typen import AufrufErgebnis, IntegrationsFehler, TestErgebnis


def _dienst(panel: Any) -> Any:
    dienst = getattr(panel, "geraete", None) if panel is not None else None
    if dienst is None:
        raise IntegrationsFehler("Geräte stehen hier nicht zur Verfügung.")
    return dienst


class GeraetAdapter:
    art = "geraet"

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        dienst = _dienst(kontext.panel)
        dienst.bereit()  # meldet verständlich, wenn der MQTT-Broker fehlt oder nicht erreichbar ist
        if kontext.integration_id is None:
            return TestErgebnis(
                ok=True,
                meldung="Der MQTT-Broker ist bereit. Mit dem Aktivieren bekommt das Gerät seine Zugangsdaten.",
            )
        with kontext.panel.datenbank.sitzung() as db:
            return TestErgebnis(
                ok=True,
                meldung=dienst.stand(db, kontext.integration_id),
                funktionen=dienst.funktionen(db, kontext.integration_id, kontext.name),
            )

    async def eingerichtet(self, db: Session, integration: Integration, panel: Any) -> dict[str, Any]:
        """Nach dem Aktivieren: Zugangsdaten für das Gerät erzeugen (das Passwort gibt es nur jetzt)."""
        return _dienst(panel).koppeln(db, integration)

    def entfernt(self, db: Session, integration: Integration, panel: Any) -> None:
        _dienst(panel).entkoppeln(db, integration)

    async def vorschau(self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]) -> str | None:
        """Der Satz für die Freigabe, z. B. „‚LED‘ am Gerät ‚Wohnzimmer‘ wird eingeschaltet.“"""
        if kontext.integration_id is None:
            return None
        dienst = _dienst(kontext.panel)
        return await anyio.to_thread.run_sync(
            lambda: dienst.vorschau(kontext.integration_id, kontext.name, funktion.extra or {}, argumente)
        )

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        dienst = _dienst(kontext.panel)
        if kontext.integration_id is None:
            raise IntegrationsFehler("Das Gerät ist noch nicht eingerichtet.")
        wert = await anyio.to_thread.run_sync(
            lambda: dienst.aufrufen(kontext.integration_id, kontext.name, funktion.extra or {}, argumente)
        )
        return AufrufErgebnis(wert=wert)
