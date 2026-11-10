"""Art `webhook`: eine geheime Adresse, an die andere Dienste Meldungen schicken können.

Ein Webhook bietet Missa keine Funktionen an. Was eingeht, wird zum Ereignis (siehe
`integrationen/webhook.py`). Die Adresse enthält einen zufälligen Schlüssel; gespeichert wird er
nur verschlüsselt, zum Wiederfinden dient seine Prüfsumme.
"""

from __future__ import annotations

import secrets
from typing import Any

from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, IntegrationsFehler, TestErgebnis
from missa_control.krypto import EntschluesselungsFehler, Krypto
from missa_control.zugaenge.schwaerzen import SCHWAERZER

PFAD = "/api/webhook/"


def neuer_schluessel(krypto: Krypto) -> dict[str, str]:
    """Erzeugt den geheimen Teil der Adresse und gibt zurück, was davon gespeichert wird."""
    token = secrets.token_urlsafe(24)
    SCHWAERZER.merken(token)  # die Adresse soll in keinem Log stehen
    return {"token": krypto.verschluesseln(token), "pruefsumme": krypto.token_pruefsumme(token)}


def pfad(zustand: dict[str, Any] | None, krypto: Krypto) -> str | None:
    """Der Pfad der geheimen Adresse – nur für die Oberfläche des angemeldeten Besitzers."""
    verschluesselt = (zustand or {}).get("token")
    if not verschluesselt:
        return None
    try:
        token = krypto.entschluesseln(str(verschluesselt))
    except EntschluesselungsFehler:
        return None
    SCHWAERZER.merken(token)
    return PFAD + token


class WebhookAdapter:
    art = "webhook"

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        if kontext.panel is None:
            raise IntegrationsFehler("Webhooks stehen hier nicht zur Verfügung.")
        if not kontext.zustand.get("token"):
            kontext.zustand.update(neuer_schluessel(kontext.panel.krypto))
        return TestErgebnis(
            ok=True,
            meldung="Bereit. Die geheime Adresse zum Senden steht nach dem Aktivieren bereit.",
            zustand=dict(kontext.zustand),
        )

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        raise IntegrationsFehler("Ein Webhook hat keine Funktionen – er empfängt nur Meldungen.")
