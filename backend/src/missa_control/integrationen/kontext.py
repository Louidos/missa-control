"""Das Kontext-Objekt: Zugriff einer Integration auf Formularwerte, Zugänge und Hilfsmittel."""

from __future__ import annotations

import base64
import logging
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx2

from missa_control.integrationen.manifest import Manifest
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.zugaenge.dienst import Zugangsdaten

STANDARD_TIMEOUT = httpx2.Timeout(30.0, connect=10.0)


class Kontext:
    """Wird jeder Funktion einer Integration als erster Parameter übergeben.

    - `kontext.konfig["feldname"]` – Werte aus dem Formular
    - `kontext.zugang("feldname")` – der dort ausgewählte Zugang (`.wert`, `.benutzer`, `.passwort`)
    - `kontext.http()` – fertiger HTTP-Client (`async with kontext.http() as client: ...`)
    - `kontext.zustand` – kleines Gedächtnis der Integration, bleibt über Neustarts erhalten
    - `kontext.log` – Protokoll (Geheimnisse werden automatisch geschwärzt)
    """

    def __init__(
        self,
        *,
        name: str,
        kennung: str,
        manifest: Manifest,
        konfig: Mapping[str, Any],
        zustand: dict[str, Any] | None = None,
        zugangsdaten: Mapping[str, Zugangsdaten] | None = None,
        ordner: Path | None = None,
        panel: Any = None,
        integration_id: int | None = None,
    ) -> None:
        self.name = name
        self.kennung = kennung
        self.manifest = manifest
        self.konfig: Mapping[str, Any] = MappingProxyType(dict(konfig))
        self.zustand: dict[str, Any] = dict(zustand or {})
        self.ordner = ordner
        self.integration_id = integration_id
        self.log = logging.getLogger(f"missa_control.integration.{kennung}")
        # Nur für eingebaute Integrationen: Zugriff auf die Dienste des Panels.
        self.panel = panel
        self._zugangsdaten = dict(zugangsdaten or {})

    def zugang(self, feld: str) -> Zugangsdaten:
        """Der im Formularfeld `feld` ausgewählte Zugang. Fehlt er, gibt es eine klare Meldung."""
        daten = self._zugangsdaten.get(feld)
        if daten is None:
            beschreibung = self.manifest.feld(feld)
            titel = beschreibung.titel if beschreibung else feld
            raise IntegrationsFehler(
                f"Für „{titel}“ ist kein Zugang hinterlegt.",
                f"Unter „Integrationen“ → „{self.name}“ bearbeiten und einen Zugang auswählen oder neu anlegen.",
            )
        return daten

    def zugang_optional(self, feld: str) -> Zugangsdaten | None:
        return self._zugangsdaten.get(feld)

    def http(self, **optionen: Any) -> httpx2.AsyncClient:
        """HTTP-Client mit sinnvollen Zeitlimits. Weitere Optionen wie bei `httpx2.AsyncClient`."""
        optionen.setdefault("timeout", STANDARD_TIMEOUT)
        optionen.setdefault("follow_redirects", True)
        return httpx2.AsyncClient(**optionen)


def auth_header(zugang: Zugangsdaten | None) -> dict[str, str]:
    """Der übliche `Authorization`-Header zu einem Zugang (Bearer bzw. Basic)."""
    if zugang is None:
        return {}
    if zugang.typ == "benutzer_passwort":
        paar = f"{zugang.benutzer}:{zugang.wert}".encode()
        return {"Authorization": "Basic " + base64.b64encode(paar).decode()}
    return {"Authorization": f"Bearer {zugang.wert}"}
