"""Modelle und Rollen verwalten, testen und Anfragen an das richtige Modell weiterleiten."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx2
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.fehler import PanelFehler
from missa_control.integrationen.fehlertexte import fehler_erklaeren, http_status_erklaeren
from missa_control.integrationen.kontext import auth_header
from missa_control.modellverwaltung.modelle import Modell, ModellAnfrage, Rolle
from missa_control.zugaenge.dienst import ZugangsDienst
from missa_control.zugaenge.modelle import Zugang

log = logging.getLogger(__name__)

ROLLEN_PRAEFIX = "missa-"
STATISTIK_TAGE = 7
TEST_ZEITLIMIT = httpx2.Timeout(60.0, connect=10.0)
# „stark“ darf länger dauern: grosszügiges Limit fürs Lesen der Antwort.
ANFRAGE_ZEITLIMIT = httpx2.Timeout(600.0, connect=10.0)
# Bei diesen Antworten des Hauptmodells springt das Ersatzmodell ein (Modell kaputt oder falsch eingerichtet).
ERSATZ_BEI_STATUS = frozenset({401, 403, 404, 408, 429})
FESTE_ROLLEN = (
    ("schnell", "Schnell", "Für Gespräche: antwortet zügig."),
    ("stark", "Stark", "Für schwierige Aufgaben – darf länger dauern."),
)
_KENNUNG = re.compile(r"^[a-z][a-z0-9-]{0,29}$")


class ModellFehler(Exception):
    """Kein Modell konnte antworten. `status` ist der HTTP-Status für den Client."""

    def __init__(self, status: int, meldung: str, hinweis: str | None = None) -> None:
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung
        self.hinweis = hinweis


@dataclass
class Ziel:
    """Alles, was für eine Anfrage an ein Modell nötig ist (ohne offene Datenbank-Sitzung)."""

    modell_id: int
    name: str
    url: str
    modellname: str
    headers: dict[str, str]
    ersatz: bool


@dataclass
class Antwort:
    ziel: Ziel
    status: int
    inhalt: dict[str, Any]


def rollen_name(kennung: str) -> str:
    return ROLLEN_PRAEFIX + kennung


def _text_kuerzen(text: str, laenge: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= laenge else text[:laenge] + " …"


class ModellDienst:
    def __init__(self, datenbank: Datenbank, zugaenge: ZugangsDienst) -> None:
        self.datenbank = datenbank
        self.zugaenge = zugaenge
        with datenbank.sitzung() as db:
            vorhanden = set(db.scalars(select(Rolle.kennung)))
            for kennung, name, beschreibung in FESTE_ROLLEN:
                if kennung not in vorhanden:
                    db.add(Rolle(kennung=kennung, name=name, beschreibung=beschreibung, fest=True))
            db.commit()

    # ------------------------------------------------------------------ Ansicht fürs Panel

    def uebersicht(self, db: Session) -> dict[str, Any]:
        statistik = self._statistik(db)
        modelle = list(db.scalars(select(Modell).order_by(Modell.name)))
        namen = {modell.id: modell.name for modell in modelle}
        rollen = db.scalars(select(Rolle).order_by(Rolle.fest.desc(), Rolle.id))
        return {
            "modelle": [self.modell_ansicht(modell, statistik.get(modell.id)) for modell in modelle],
            "rollen": [self.rollen_ansicht(rolle, namen) for rolle in rollen],
        }

    @staticmethod
    def modell_ansicht(modell: Modell, statistik: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "id": modell.id,
            "name": modell.name,
            "url": modell.url,
            "zugang_id": modell.zugang_id,
            "modellname": modell.modellname,
            "kontextlaenge": modell.kontextlaenge,
            "test": {
                "ok": modell.test_ok,
                "meldung": modell.test_meldung,
                "hinweis": modell.test_hinweis,
                "ms": modell.test_ms,
                "tokens_pro_s": modell.test_tokens_pro_s,
                "zeit": modell.getestet.isoformat() if modell.getestet else None,
            },
            "statistik": statistik
            or {"anfragen": 0, "fehler": 0, "antwortzeit_ms": None, "tokens_pro_s": None},
        }

    @staticmethod
    def rollen_ansicht(rolle: Rolle, namen: dict[int, str]) -> dict[str, Any]:
        return {
            "id": rolle.id,
            "kennung": rolle.kennung,
            "modellname": rollen_name(rolle.kennung),
            "name": rolle.name,
            "beschreibung": rolle.beschreibung,
            "haupt_modell_id": rolle.haupt_modell_id,
            "ersatz_modell_id": rolle.ersatz_modell_id,
            "haupt_modell": namen.get(rolle.haupt_modell_id or 0),
            "ersatz_modell": namen.get(rolle.ersatz_modell_id or 0),
            "fest": rolle.fest,
        }

    def _statistik(self, db: Session) -> dict[int, dict[str, Any]]:
        """Je Modell: Anfragen, Fehler, mittlere Antwortzeit und Tokens/s der letzten 7 Tage."""
        seit = zeit.jetzt() - timedelta(days=STATISTIK_TAGE)
        erfolgreich = ModellAnfrage.ok.is_(True)
        zeilen = db.execute(
            select(
                ModellAnfrage.modell_id,
                func.count(),
                func.sum(func.iif(erfolgreich, 0, 1)),
                func.avg(func.iif(erfolgreich, ModellAnfrage.dauer_ms, None)),
                func.avg(func.iif(erfolgreich, ModellAnfrage.tokens_pro_s, None)),
            )
            .where(ModellAnfrage.zeit >= seit)
            .group_by(ModellAnfrage.modell_id)
        )
        return {
            modell_id: {
                "anfragen": anfragen,
                "fehler": int(fehler or 0),
                "antwortzeit_ms": round(antwortzeit) if antwortzeit is not None else None,
                "tokens_pro_s": round(tokens, 1) if tokens is not None else None,
            }
            for modell_id, anfragen, fehler, antwortzeit, tokens in zeilen
        }

    # ------------------------------------------------------------------ Modelle

    def _modell_pruefen(
        self, db: Session, daten: dict[str, Any], ausser: int | None = None
    ) -> dict[str, Any]:
        name = str(daten.get("name") or "").strip()
        url = str(daten.get("url") or "").strip().rstrip("/")
        modellname = str(daten.get("modellname") or "").strip()
        if not name:
            raise PanelFehler(422, "Bitte einen Namen für das Modell angeben.")
        if not re.match(r"^https?://[^\s/]+", url):
            raise PanelFehler(
                422,
                "Die URL ist ungültig.",
                "Erwartet wird die Adresse bis einschliesslich /v1, z. B. http://192.168.1.30:8000/v1",
            )
        if not modellname:
            raise PanelFehler(
                422,
                "Bitte den Modellnamen angeben.",
                "So, wie ihn der Server kennt – z. B. „qwen2.5:32b“ oder „gpt-4o-mini“.",
            )
        vorhandenes = db.scalar(select(Modell).where(Modell.name == name))
        if vorhandenes is not None and vorhandenes.id != ausser:
            raise PanelFehler(409, f"Es gibt bereits ein Modell mit dem Namen „{name}“.")
        zugang_id = daten.get("zugang_id")
        if zugang_id is not None and db.get(Zugang, int(zugang_id)) is None:
            raise PanelFehler(422, "Der ausgewählte Zugang existiert nicht mehr.")
        kontext = daten.get("kontextlaenge")
        return {
            "name": name,
            "url": url,
            "modellname": modellname,
            "zugang_id": int(zugang_id) if zugang_id is not None else None,
            "kontextlaenge": int(kontext) if kontext else None,
        }

    def modell_anlegen(self, db: Session, daten: dict[str, Any]) -> Modell:
        zeitpunkt = zeit.jetzt()
        modell = Modell(**self._modell_pruefen(db, daten), erstellt=zeitpunkt, geaendert=zeitpunkt)
        db.add(modell)
        db.commit()
        return modell

    def modell_aendern(self, db: Session, modell_id: int, daten: dict[str, Any]) -> Modell:
        modell = self.modell_holen(db, modell_id)
        for feld, wert in self._modell_pruefen(db, daten, ausser=modell_id).items():
            setattr(modell, feld, wert)
        modell.geaendert = zeit.jetzt()
        db.commit()
        return modell

    def modell_holen(self, db: Session, modell_id: int) -> Modell:
        modell = db.get(Modell, modell_id)
        if modell is None:
            raise PanelFehler(404, "Dieses Modell gibt es nicht (mehr).")
        return modell

    def modell_loeschen(self, db: Session, modell_id: int) -> None:
        modell = self.modell_holen(db, modell_id)
        rollen = db.scalars(
            select(Rolle).where((Rolle.haupt_modell_id == modell_id) | (Rolle.ersatz_modell_id == modell_id))
        ).all()
        if rollen:
            namen = ", ".join(f"„{rolle.name}“" for rolle in rollen)
            raise PanelFehler(
                409,
                f"Das Modell wird noch verwendet von: {namen}.",
                "Zuerst bei diesen Rollen ein anderes Modell auswählen.",
            )
        db.delete(modell)
        db.commit()

    # ------------------------------------------------------------------ Rollen

    def rolle_anlegen(self, db: Session, *, kennung: str, name: str, beschreibung: str = "") -> Rolle:
        kennung = kennung.strip().lower()
        if not _KENNUNG.match(kennung):
            raise PanelFehler(
                422,
                "Der Kurzname der Rolle ist ungültig.",
                "Erlaubt sind Kleinbuchstaben, Ziffern und Bindestriche, z. B. „uebersetzen“.",
            )
        if db.scalar(select(Rolle).where(Rolle.kennung == kennung)) is not None:
            raise PanelFehler(409, f"Die Rolle „{kennung}“ gibt es bereits.")
        rolle = Rolle(kennung=kennung, name=name.strip() or kennung, beschreibung=beschreibung.strip())
        db.add(rolle)
        db.commit()
        return rolle

    def rolle_aendern(self, db: Session, rolle_id: int, daten: dict[str, Any]) -> Rolle:
        rolle = self.rolle_holen(db, rolle_id)
        for feld in ("haupt_modell_id", "ersatz_modell_id"):
            if feld in daten:
                wert = daten[feld]
                if wert is not None:
                    self.modell_holen(db, int(wert))
                setattr(rolle, feld, int(wert) if wert is not None else None)
        if daten.get("name"):
            rolle.name = str(daten["name"]).strip()
        if "beschreibung" in daten and daten["beschreibung"] is not None:
            rolle.beschreibung = str(daten["beschreibung"]).strip()
        db.commit()
        return rolle

    def rolle_holen(self, db: Session, rolle_id: int) -> Rolle:
        rolle = db.get(Rolle, rolle_id)
        if rolle is None:
            raise PanelFehler(404, "Diese Rolle gibt es nicht (mehr).")
        return rolle

    def rolle_loeschen(self, db: Session, rolle_id: int) -> None:
        rolle = self.rolle_holen(db, rolle_id)
        if rolle.fest:
            raise PanelFehler(
                409, f"Die Rolle „{rolle.name}“ gehört fest zum Panel und kann nicht gelöscht werden."
            )
        db.delete(rolle)
        db.commit()

    # ------------------------------------------------------------------ Verbindungstest

    def _ziel(self, db: Session, modell: Modell, ersatz: bool = False) -> Ziel:
        headers = {"Content-Type": "application/json"}
        if modell.zugang_id is not None:
            headers.update(auth_header(self.zugaenge.klartext(db, modell.zugang_id)))
        return Ziel(
            modell_id=modell.id,
            name=modell.name,
            url=modell.url.rstrip("/") + "/chat/completions",
            modellname=modell.modellname,
            headers=headers,
            ersatz=ersatz,
        )

    async def testen(self, db: Session, modell_id: int) -> Modell:
        """Kurze Anfrage an das Modell: misst Antwortzeit und Tokens pro Sekunde."""
        modell = self.modell_holen(db, modell_id)
        koerper = {
            "model": modell.modellname,
            "messages": [{"role": "user", "content": "Zähle von 1 bis 20. Antworte nur mit den Zahlen."}],
            "max_tokens": 64,
            "stream": False,
        }
        start = time.monotonic()
        modell.test_ms = None
        modell.test_tokens_pro_s = None
        try:
            ziel = self._ziel(db, modell)
            async with httpx2.AsyncClient(timeout=TEST_ZEITLIMIT) as client:
                antwort = await client.post(ziel.url, headers=ziel.headers, json=koerper)
            dauer = time.monotonic() - start
            if antwort.status_code >= 400:
                meldung, hinweis = http_status_erklaeren(antwort.status_code)
                if antwort.status_code == 404:
                    hinweis = (
                        "Stimmt die URL (bis einschliesslich /v1) und der Modellname? "
                        f"Antwort des Servers: {_text_kuerzen(antwort.text, 150)}"
                    )
                raise PanelFehler(antwort.status_code, meldung, hinweis)
            daten = antwort.json()
            if not isinstance(daten, dict) or not daten.get("choices"):
                raise PanelFehler(
                    502,
                    "Der Server antwortet, aber nicht wie eine OpenAI-kompatible Schnittstelle.",
                    "Die URL muss auf eine OpenAI-kompatible API zeigen (Pfad meist …/v1).",
                )
            tokens = (daten.get("usage") or {}).get("completion_tokens")
            modell.test_ok = True
            modell.test_ms = round(dauer * 1000)
            modell.test_tokens_pro_s = round(tokens / dauer, 1) if tokens and dauer > 0 else None
            modell.test_meldung = "Das Modell antwortet."
            modell.test_hinweis = ""
        except Exception as fehler:
            modell.test_ok = False
            modell.test_meldung, hinweis = fehler_erklaeren(fehler)
            modell.test_hinweis = hinweis or ""
        modell.getestet = zeit.jetzt()
        db.commit()
        return modell

    # ------------------------------------------------------------------ Anfragen weiterleiten

    def ziele(self, name: str) -> tuple[str, list[Ziel]]:
        """Löst `missa-<rolle>` in Haupt- und Ersatzmodell auf. Gibt (Kennung der Rolle, Ziele) zurück."""
        with self.datenbank.sitzung() as db:
            kennung = name.removeprefix(ROLLEN_PRAEFIX) if name.startswith(ROLLEN_PRAEFIX) else ""
            rolle = db.scalar(select(Rolle).where(Rolle.kennung == kennung)) if kennung else None
            if rolle is None:
                verfuegbar = ", ".join(
                    rollen_name(k) for k in db.scalars(select(Rolle.kennung).order_by(Rolle.id))
                )
                raise ModellFehler(
                    404, f"Das Modell „{name}“ gibt es nicht.", f"Verfügbar sind die Rollen: {verfuegbar}."
                )
            ziele: list[Ziel] = []
            for modell_id, ersatz in ((rolle.haupt_modell_id, False), (rolle.ersatz_modell_id, True)):
                modell = db.get(Modell, modell_id) if modell_id is not None else None
                if modell is not None and modell.id not in {ziel.modell_id for ziel in ziele}:
                    ziele.append(self._ziel(db, modell, ersatz=ersatz))
            if not ziele:
                raise ModellFehler(
                    503,
                    f"Für die Rolle „{rolle.name}“ ist noch kein Modell ausgewählt.",
                    "Im Panel unter „Modelle“ bei dieser Rolle ein Hauptmodell auswählen.",
                )
            return kennung, ziele

    def rollen_namen(self) -> list[str]:
        """Alle Rollen, hinter denen ein Modell steckt – als Modellnamen für Clients."""
        with self.datenbank.sitzung() as db:
            abfrage = select(Rolle.kennung).where(Rolle.haupt_modell_id.is_not(None)).order_by(Rolle.id)
            return [rollen_name(kennung) for kennung in db.scalars(abfrage)]

    def _merken(
        self,
        ziel: Ziel,
        rolle: str,
        *,
        ok: bool,
        start: float,
        tokens: int | None = None,
        fehler: str = "",
    ) -> None:
        dauer = max(time.monotonic() - start, 0.001)
        with self.datenbank.sitzung() as db:
            db.add(
                ModellAnfrage(
                    zeit=zeit.jetzt(),
                    modell_id=ziel.modell_id,
                    rolle=rolle,
                    ok=ok,
                    dauer_ms=round(dauer * 1000),
                    tokens=tokens,
                    tokens_pro_s=round(tokens / dauer, 1) if tokens else None,
                    ersatz=ziel.ersatz,
                    fehler=_text_kuerzen(fehler),
                )
            )
            db.commit()

    @staticmethod
    def _ersatz_noetig(status: int) -> bool:
        return status >= 500 or status in ERSATZ_BEI_STATUS

    def _alle_ausgefallen(self, kennung: str, letzter: str) -> ModellFehler:
        return ModellFehler(
            502,
            f"Kein Modell der Rolle „{kennung}“ hat geantwortet. Letzter Fehler: {letzter}",
            "Im Panel unter „Modelle“ die Verbindung testen.",
        )

    async def chat(
        self, name: str, koerper: dict[str, Any], zeitlimit: httpx2.Timeout | None = None
    ) -> Antwort:
        """Anfrage ohne Streaming: versucht das Hauptmodell, bei Ausfall das Ersatzmodell."""
        kennung, ziele = self.ziele(name)
        letzter = ""
        async with httpx2.AsyncClient(timeout=zeitlimit or ANFRAGE_ZEITLIMIT) as client:
            for ziel in ziele:
                start = time.monotonic()
                try:
                    antwort = await client.post(
                        ziel.url,
                        headers=ziel.headers,
                        json={**koerper, "model": ziel.modellname, "stream": False},
                    )
                except httpx2.HTTPError as fehler:
                    letzter = fehler_erklaeren(fehler)[0]
                    self._merken(ziel, kennung, ok=False, start=start, fehler=letzter)
                    continue
                if self._ersatz_noetig(antwort.status_code):
                    letzter = (
                        f"{ziel.name}: Status {antwort.status_code} – {_text_kuerzen(antwort.text, 150)}"
                    )
                    self._merken(ziel, kennung, ok=False, start=start, fehler=letzter)
                    continue
                try:
                    inhalt = antwort.json()
                except ValueError:
                    inhalt = {"error": {"message": _text_kuerzen(antwort.text)}}
                tokens = (
                    (inhalt.get("usage") or {}).get("completion_tokens") if isinstance(inhalt, dict) else None
                )
                # Ein Fehler in der Anfrage selbst (z. B. 400) zählt nicht als Fehler des Modells.
                self._merken(ziel, kennung, ok=True, start=start, tokens=tokens)
                return Antwort(ziel=ziel, status=antwort.status_code, inhalt=inhalt)
        raise self._alle_ausgefallen(kennung, letzter)

    async def chat_stream(self, name: str, koerper: dict[str, Any]) -> tuple[Ziel, int, AsyncIterator[bytes]]:
        """Anfrage mit Streaming. Das Ersatzmodell springt ein, solange noch nichts gesendet wurde."""
        kennung, ziele = self.ziele(name)
        letzter = ""
        client = httpx2.AsyncClient(timeout=ANFRAGE_ZEITLIMIT)
        try:
            for ziel in ziele:
                start = time.monotonic()
                anfrage = client.build_request(
                    "POST",
                    ziel.url,
                    headers=ziel.headers,
                    json={**koerper, "model": ziel.modellname, "stream": True},
                )
                try:
                    antwort = await client.send(anfrage, stream=True)
                except httpx2.HTTPError as fehler:
                    letzter = fehler_erklaeren(fehler)[0]
                    self._merken(ziel, kennung, ok=False, start=start, fehler=letzter)
                    continue
                if self._ersatz_noetig(antwort.status_code):
                    text = (await antwort.aread()).decode(errors="replace")
                    await antwort.aclose()
                    letzter = f"{ziel.name}: Status {antwort.status_code} – {_text_kuerzen(text, 150)}"
                    self._merken(ziel, kennung, ok=False, start=start, fehler=letzter)
                    continue
                return ziel, antwort.status_code, self._durchreichen(client, antwort, ziel, kennung, start)
        except BaseException:
            await client.aclose()
            raise
        await client.aclose()
        raise self._alle_ausgefallen(kennung, letzter)

    async def _durchreichen(
        self, client: httpx2.AsyncClient, antwort: httpx2.Response, ziel: Ziel, kennung: str, start: float
    ) -> AsyncIterator[bytes]:
        """Reicht die Antwort Stück für Stück durch und zählt dabei die Tokens für die Statistik."""
        zaehler = _TokenZaehler()
        ok = True
        fehler = ""
        try:
            async for stueck in antwort.aiter_raw():
                zaehler.lesen(stueck)
                yield stueck
        except httpx2.HTTPError as ausnahme:
            ok = False
            fehler = fehler_erklaeren(ausnahme)[0]
            raise
        finally:
            await antwort.aclose()
            await client.aclose()
            self._merken(ziel, kennung, ok=ok, start=start, tokens=zaehler.tokens(), fehler=fehler)

    def aufraeumen(self) -> int:
        """Löscht Statistik-Einträge, die älter als 7 Tage sind."""
        with self.datenbank.sitzung() as db:
            grenze = zeit.jetzt() - timedelta(days=STATISTIK_TAGE)
            ergebnis = db.execute(delete(ModellAnfrage).where(ModellAnfrage.zeit < grenze))
            db.commit()
            return ergebnis.rowcount or 0

    def zugang_verwendung(self, db: Session) -> dict[int, list[str]]:
        verwendung: dict[int, list[str]] = {}
        for modell in db.scalars(select(Modell).where(Modell.zugang_id.is_not(None))):
            verwendung.setdefault(int(modell.zugang_id or 0), []).append(f"Modell „{modell.name}“")
        return verwendung


class _TokenZaehler:
    """Zählt beim Durchreichen eines Streams die Textstücke (≈ Tokens) oder liest die Angabe des Servers."""

    def __init__(self) -> None:
        self._rest = b""
        self._stuecke = 0
        self._laut_server: int | None = None

    def lesen(self, daten: bytes) -> None:
        *zeilen, self._rest = (self._rest + daten).split(b"\n")
        for zeile in zeilen:
            if not zeile.startswith(b"data:") or zeile.strip() == b"data: [DONE]":
                continue
            try:
                inhalt = json.loads(zeile[5:])
            except ValueError:
                continue
            if not isinstance(inhalt, dict):
                continue
            nutzung = inhalt.get("usage")
            if isinstance(nutzung, dict) and nutzung.get("completion_tokens"):
                self._laut_server = int(nutzung["completion_tokens"])
            for wahl in inhalt.get("choices") or []:
                if isinstance(wahl, dict) and (wahl.get("delta") or {}).get("content"):
                    self._stuecke += 1

    def tokens(self) -> int | None:
        return self._laut_server or self._stuecke or None
