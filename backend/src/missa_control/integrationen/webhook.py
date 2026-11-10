"""Eingehende Webhooks: `/api/webhook/<geheimer Schlüssel>` macht aus einer Meldung ein Ereignis.

Diese Adresse ist ohne Anmeldung erreichbar – der zufällige Schlüssel in der Adresse ist der Zugang.
Was eingeht, wird nur gespeichert und weitergemeldet (Ereignis für Missa, Auslöser für Regeln);
ausgeführt wird davon nichts.
"""

from __future__ import annotations

import hmac
import json
import threading
import time
from collections import deque
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from missa_control.db import get_db
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.ereignisse.modelle import DRINGLICHKEITEN
from missa_control.fehler import PanelFehler
from missa_control.integrationen.adapter import webhook as adapter
from missa_control.integrationen.dienst import IntegrationsDienst
from missa_control.integrationen.modelle import Integration
from missa_control.krypto import Krypto

MAX_BYTES = 64 * 1024
MAX_JE_MINUTE = 120
_TEXT_FELDER = ("nachricht", "message", "text", "titel", "title", "msg", "betreff", "subject")

router = APIRouter(tags=["Webhook (ohne Anmeldung, geheime Adresse)"])


class WebhookDienst:
    def __init__(
        self, *, integrationen: IntegrationsDienst, ereignisse: EreignisDienst, krypto: Krypto
    ) -> None:
        self.integrationen = integrationen
        self.ereignisse = ereignisse
        self.krypto = krypto
        self._sperre = threading.Lock()
        self._eingaenge: dict[int, deque[float]] = {}

    def _webhooks(self, db: Session) -> list[Integration]:
        katalog = self.integrationen.katalog.eintraege
        return [
            integration
            for integration in db.scalars(select(Integration).where(Integration.aktiv.is_(True)))
            if (eintrag := katalog.get(integration.manifest_id)) is not None
            and eintrag.manifest.art == "webhook"
        ]

    def finden(self, db: Session, token: str) -> Integration:
        """Der aktive Webhook zu diesem Schlüssel. Unbekannt oder deaktiviert: beides sieht von aussen gleich aus."""
        pruefsumme = self.krypto.token_pruefsumme(token)
        gefunden = None
        for integration in self._webhooks(db):
            gespeichert = str((integration.zustand or {}).get("pruefsumme", ""))
            if hmac.compare_digest(gespeichert, pruefsumme):
                gefunden = integration
        if gefunden is None:
            raise PanelFehler(404, "Diesen Webhook gibt es nicht.")
        return gefunden

    def _bremsen(self, integration_id: int) -> None:
        """Höchstens 120 Meldungen pro Minute und Webhook – schützt vor Dauerfeuer."""
        jetzt = time.monotonic()
        with self._sperre:
            eingaenge = self._eingaenge.setdefault(integration_id, deque())
            while eingaenge and jetzt - eingaenge[0] > 60:
                eingaenge.popleft()
            if len(eingaenge) >= MAX_JE_MINUTE:
                raise PanelFehler(
                    429, "Zu viele Meldungen in kurzer Zeit.", f"Höchstens {MAX_JE_MINUTE} pro Minute."
                )
            eingaenge.append(jetzt)

    def empfangen(self, db: Session, token: str, inhalt: Any) -> dict[str, Any]:
        integration = self.finden(db, token)
        self._bremsen(integration.id)
        daten: dict[str, Any] = {"integration_id": integration.id, "inhalt": inhalt}
        dringlichkeit = str((integration.konfig or {}).get("dringlichkeit") or "normal")
        if isinstance(inhalt, dict):
            if str(inhalt.get("dringlichkeit", "")).lower() in DRINGLICHKEITEN:
                dringlichkeit = str(inhalt["dringlichkeit"]).lower()
            if isinstance(inhalt.get("wert"), str | int | float) and not isinstance(inhalt.get("wert"), bool):
                daten["wert"] = inhalt["wert"]  # steht Regeln als {wert} zur Verfügung
        ereignis = self.ereignisse.melden(
            "webhook",
            f"Webhook „{integration.name}“ hat etwas empfangen",
            _als_nachricht(inhalt),
            dringlichkeit=dringlichkeit,
            quelle=integration.name,
            daten=daten,
        )
        return {"ok": True, "ereignis_id": ereignis["id"]}

    def erneuern(self, db: Session, integration_id: int) -> Integration:
        """Neue geheime Adresse – die alte gilt sofort nicht mehr."""
        integration = self.integrationen.holen(db, integration_id)
        eintrag = self.integrationen.katalog.eintraege.get(integration.manifest_id)
        if eintrag is None or eintrag.manifest.art != "webhook":
            raise PanelFehler(409, "Diese Integration ist kein Webhook.")
        integration.zustand = {**(integration.zustand or {}), **adapter.neuer_schluessel(self.krypto)}
        db.commit()
        return integration

    def schluessel_merken(self, db: Session) -> None:
        """Beim Start: alle Adressen dem Schwärzer bekannt machen, damit sie in keinem Log stehen."""
        for integration in self._webhooks(db):
            adapter.pfad(integration.zustand, self.krypto)


def _als_nachricht(inhalt: Any) -> str:
    """Der Text des Ereignisses: ein passendes Feld der Meldung – sonst die Meldung selbst, gekürzt."""
    if isinstance(inhalt, dict):
        for feld in _TEXT_FELDER:
            wert = inhalt.get(feld)
            if isinstance(wert, str) and wert.strip():
                return wert.strip()[:500]
        return json.dumps(inhalt, ensure_ascii=False)[:500] if inhalt else "(ohne Inhalt)"
    text = inhalt if isinstance(inhalt, str) else json.dumps(inhalt, ensure_ascii=False)
    return text.strip()[:500] or "(ohne Inhalt)"


async def _inhalt_lesen(request: Request) -> Any:
    """Liest die Meldung: JSON, Formularfelder oder einfacher Text; Angaben in der Adresse (?a=b) zählen mit."""
    koerper = b""
    async for stueck in request.stream():
        koerper += stueck
        if len(koerper) > MAX_BYTES:
            raise PanelFehler(413, "Die Meldung ist zu gross.", f"Höchstens {MAX_BYTES // 1024} kB.")
    art = request.headers.get("content-type", "").split(";")[0].strip().lower()
    angaben: dict[str, Any] = dict(request.query_params)
    if not koerper.strip():
        return angaben
    text = koerper.decode("utf-8", errors="replace")
    if art == "application/x-www-form-urlencoded":
        return {**angaben, **dict(parse_qsl(text, keep_blank_values=True))}
    if art == "application/json" or (not art and text.lstrip()[:1] in "{["):
        try:
            inhalt = json.loads(text)
        except ValueError:
            raise PanelFehler(
                400,
                "Die Meldung ist kein gültiges JSON.",
                'Beispiel: {"nachricht": "Die Waschmaschine ist fertig"}',
            ) from None
        return {**angaben, **inhalt} if isinstance(inhalt, dict) else inhalt
    return {**angaben, "text": text.strip()[:4000]} if angaben else text.strip()[:4000]


async def _annehmen(token: str, request: Request, db: Session) -> dict[str, Any]:
    dienst: WebhookDienst = request.app.state.webhooks
    dienst.finden(db, token)  # erst prüfen, ob es den Webhook gibt – dann erst die Meldung lesen
    return dienst.empfangen(db, token, await _inhalt_lesen(request))


@router.post("/api/webhook/{token}")
async def empfangen(token: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Nimmt eine Meldung entgegen (JSON, Formularfelder oder Text) und macht daraus ein Ereignis."""
    return await _annehmen(token, request, db)


@router.put("/api/webhook/{token}")
async def empfangen_put(token: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Wie POST – für Dienste, die nur PUT senden können."""
    return await _annehmen(token, request, db)


@router.get("/api/webhook/{token}")
async def empfangen_get(token: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Wie POST – für einfache Geräte, die nur eine Adresse aufrufen können (Angaben als ?nachricht=…)."""
    return await _annehmen(token, request, db)
