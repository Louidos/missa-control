"""Der Regel-Dienst: Regeln verwalten, Auslöser beobachten, Aktionen ausführen.

So läuft eine Regel ab:

1. Ein Auslöser tritt ein – eine Messung der Serverlast, ein internes Ereignis (Webhook, Gerät,
   Integration ausgefallen) oder der Zeitplan. Das wird hier nur vermerkt („eingereiht“).
2. Eine einzige Hintergrundaufgabe arbeitet die Vermerke der Reihe nach ab: Bedingung und Ruhezeit
   prüfen, Aktion ausführen, Verlauf schreiben.

Dadurch dürfen Auslöser aus jedem Thread kommen, und zwei Regeln kommen sich nie in die Quere.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as uhrzeit_typ
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.ereignisse.modelle import DRINGLICHKEITEN
from missa_control.fehler import PanelFehler
from missa_control.gateway.protokoll import ProtokollDienst
from missa_control.gateway.server import sichtbare_funktionen
from missa_control.integrationen.dienst import IntegrationsDienst, ergebnis_als_text
from missa_control.integrationen.modelle import Integration
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.regeln import satz
from missa_control.regeln.modelle import Ausloesung, Regel
from missa_control.regeln.pruefung import (
    AUSLOESER_ARTEN,
    STANDARD_RUHEZEIT,
    AktionsArt,
    FunktionsAngabe,
    Umfeld,
    ereignis_aktion_pruefen,
    funktion_aktion_pruefen,
    regel_pruefen,
)
from missa_control.serverlast.dienst import MESSWERTE, ServerlastDienst

log = logging.getLogger(__name__)

QUELLE_MISSA = "missa"
QUELLE_MANUELL = "manuell"
ERGEBNIS_NAMEN = {
    "ok": "ausgeführt",
    "fehler": "fehlgeschlagen",
    "ruhezeit": "in der Ruhezeit übersprungen",
    "bedingung": "Bedingung nicht erfüllt",
}
# Ereignisse, die Regeln auslösen können (Art des Ereignisses = Art des Auslösers).
_EREIGNIS_AUSLOESER = ("webhook", "geraet", "integration_ausgefallen")
_ALLE = ("", "alle", "jede", "jeder", "jedes", "egal", "*")


@dataclass
class Anlass:
    """Ein eingetretener Auslöser, der auf seine Bearbeitung wartet."""

    regel_id: int
    text: str
    daten: dict[str, Any] = field(default_factory=dict)
    # Still: greifen Ruhezeit oder Bedingung, gibt es keinen Eintrag im Verlauf. Das gilt für Messwerte
    # (sonst alle 30 Sekunden ein Eintrag) und den Zeitplan. Einzelne Ereignisse werden dagegen vermerkt.
    still: bool = True


class RegelDienst:
    def __init__(
        self,
        *,
        einstellungen: Einstellungen,
        datenbank: Datenbank,
        ereignisse: EreignisDienst,
        integrationen: IntegrationsDienst,
        protokoll: ProtokollDienst,
        serverlast: ServerlastDienst,
    ) -> None:
        self.datenbank = datenbank
        self.ereignisse = ereignisse
        self.integrationen = integrationen
        self.protokoll = protokoll
        self.serverlast = serverlast
        self.zeitzone = ZoneInfo(einstellungen.zeitzone)
        self.takt_sekunden = einstellungen.regel_takt_sekunden
        self.aufbewahrung_tage = einstellungen.aufbewahrung_tage
        # Arten von Aktionen. Weitere (z. B. „anruf“) tragen sich hier ein.
        self.aktions_arten: dict[str, AktionsArt] = {
            "ereignis": AktionsArt(
                titel="Ereignis an Missa",
                pruefen=ereignis_aktion_pruefen,
                satz=satz.ereignis_aktion_text,
                ausfuehren=self._aktion_ereignis,
            ),
            "funktion": AktionsArt(
                titel="Funktion einer Integration aufrufen",
                pruefen=funktion_aktion_pruefen,
                satz=satz.funktion_aktion_text,
                ausfuehren=self._aktion_funktion,
            ),
        }
        # Weitere Messwerte bzw. Geräte (kommen mit den Geräten dazu).
        self.messwert_quellen: list[Callable[[Session], dict[str, tuple[str, str]]]] = []
        self.geraete_quelle: Callable[[Session], dict[int, str]] | None = None
        self.geraete_meldungen: Callable[[Session], dict[int, list[tuple[str, str]]]] | None = None

        self._zustand = threading.Lock()
        self._erfuellt_seit: dict[int, datetime] = {}  # Schwellwert-Regeln: seit wann über/unter der Schwelle
        self._faellig: dict[int, datetime] = {}  # Zeitplan-Regeln: nächste Ausführung
        self._anstehend: deque[Anlass] = deque()
        self._fortschritt = threading.Condition()
        self._offen = 0
        self._wecker: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None

        serverlast.zuhoerer.append(self.messwerte_pruefen)
        ereignisse.zuhoerer.append(self.ereignis_pruefen)

    # ------------------------------------------------------------------ Umfeld und Ansicht

    def umfeld(self, db: Session) -> Umfeld:
        integrationen: dict[int, str] = {}
        webhooks: dict[int, str] = {}
        for integration in db.scalars(select(Integration).order_by(Integration.name)):
            integrationen[integration.id] = integration.name
            eintrag = self.integrationen.katalog.eintraege.get(integration.manifest_id)
            if eintrag is not None and eintrag.manifest.art == "webhook":
                webhooks[integration.id] = integration.name
        messwerte = dict(MESSWERTE)
        for quelle in self.messwert_quellen:
            messwerte.update(quelle(db))
        return Umfeld(
            messwerte=messwerte,
            integrationen=integrationen,
            webhooks=webhooks,
            geraete=self.geraete_quelle(db) if self.geraete_quelle else {},
            geraete_meldungen=self.geraete_meldungen(db) if self.geraete_meldungen else {},
            funktionen={
                name: FunktionsAngabe(
                    integration=integration.name,
                    beschreibung=funktion.beschreibung,
                    parameter=funktion.parameter or {},
                    recht=funktion.recht,
                )
                for name, integration, funktion in sichtbare_funktionen(db)
            },
            aktionen=self.aktions_arten,
        )

    def optionen(self, db: Session, umfeld: Umfeld | None = None) -> dict[str, Any]:
        """Alles, was der Editor zur Auswahl anbietet."""
        umfeld = umfeld or self.umfeld(db)
        letzte = self.serverlast.letzte.werte() if self.serverlast.letzte else None
        return {
            "ausloeser": [{"wert": art, "titel": titel} for art, titel in AUSLOESER_ARTEN.items()],
            "aktionen": [{"wert": art, "titel": angabe.titel} for art, angabe in umfeld.aktionen.items()],
            "messwerte": [
                {
                    "kennung": kennung,
                    "titel": titel,
                    "einheit": einheit,
                    # Ohne GPU bzw. Temperaturfühler gibt es den Wert auf diesem Server nicht.
                    "verfuegbar": letzte is None or kennung not in letzte or letzte[kennung] is not None,
                }
                for kennung, (titel, einheit) in umfeld.messwerte.items()
            ],
            "integrationen": [{"id": nr, "name": name} for nr, name in umfeld.integrationen.items()],
            "webhooks": [{"id": nr, "name": name} for nr, name in umfeld.webhooks.items()],
            "geraete": [
                {
                    "id": nr,
                    "name": name,
                    "meldungen": [
                        {"wert": wert, "titel": titel} for wert, titel in umfeld.geraete_meldungen.get(nr, [])
                    ],
                }
                for nr, name in umfeld.geraete.items()
            ],
            "funktionen": [
                {
                    "name": name,
                    "integration": angabe.integration,
                    "beschreibung": angabe.beschreibung,
                    "parameter": angabe.parameter,
                    "recht": angabe.recht,
                }
                for name, angabe in sorted(umfeld.funktionen.items())
            ],
            "dringlichkeiten": list(DRINGLICHKEITEN),
            "zeitzone": str(self.zeitzone),
            "standard_ruhezeit": STANDARD_RUHEZEIT,
        }

    @staticmethod
    def _angaben(regel: Regel) -> dict[str, Any]:
        return {
            "name": regel.name,
            "ausloeser": copy.deepcopy(regel.ausloeser),
            "bedingung": copy.deepcopy(regel.bedingung or {}),
            "aktion": copy.deepcopy(regel.aktion),
            "ruhezeit_minuten": regel.ruhezeit_minuten,
            "aktiv": regel.aktiv,
        }

    def ansicht(self, regel: Regel, umfeld: Umfeld) -> dict[str, Any]:
        angaben = self._angaben(regel)
        problem = None
        try:
            regel_pruefen(angaben, umfeld)
        except PanelFehler as fehler:
            # Etwas, worauf sich die Regel bezieht, gibt es nicht mehr (z. B. eine entfernte Funktion).
            problem = fehler.meldung
        with self._zustand:
            faellig = self._faellig.get(regel.id) if regel.aktiv else None
        return {
            "id": regel.id,
            **angaben,
            "quelle": regel.quelle,
            "satz": satz.regel_satz(angaben, umfeld),
            "problem": problem,
            "erstellt": regel.erstellt.isoformat(),
            "geaendert": regel.geaendert.isoformat(),
            "zuletzt_ausgeloest": regel.zuletzt_ausgeloest.isoformat() if regel.zuletzt_ausgeloest else None,
            "naechste_ausfuehrung": faellig.isoformat() if faellig else None,
        }

    def uebersicht(self, db: Session) -> dict[str, Any]:
        umfeld = self.umfeld(db)
        regeln = db.scalars(select(Regel).order_by(func.lower(Regel.name), Regel.id))
        return {
            "regeln": [self.ansicht(regel, umfeld) for regel in regeln],
            "optionen": self.optionen(db, umfeld),
        }

    def als_satz(self, db: Session, daten: Any) -> str:
        """Der lesbare Satz zu (noch nicht gespeicherten) Angaben – für die Vorschau im Editor."""
        umfeld = self.umfeld(db)
        return satz.regel_satz(regel_pruefen(daten, umfeld), umfeld)

    # ------------------------------------------------------------------ verwalten

    @staticmethod
    def holen(db: Session, regel_id: int) -> Regel:
        regel = db.get(Regel, regel_id)
        if regel is None:
            raise PanelFehler(
                404,
                f"Die Regel {regel_id} gibt es nicht (mehr).",
                "Welche Regeln es gibt, zeigt die Seite „Regeln“ bzw. die Funktion „regeln_auflisten“.",
            )
        return regel

    def _zuruecksetzen(self, regel_id: int) -> None:
        """Nach einer Änderung beginnt die Regel neu zu zählen (Mindestdauer, nächster Zeitpunkt)."""
        with self._zustand:
            self._erfuellt_seit.pop(regel_id, None)
            self._faellig.pop(regel_id, None)

    def _zeitplan_vormerken(self, regel: Regel) -> None:
        if regel.aktiv and regel.ausloeser.get("art") == "zeitplan":
            with self._zustand:
                self._faellig[regel.id] = self._naechste(regel.ausloeser, zeit.jetzt())

    def anlegen(self, db: Session, daten: Any, quelle: str = QUELLE_MANUELL) -> Regel:
        angaben = regel_pruefen(daten, self.umfeld(db))
        jetzt = zeit.jetzt()
        regel = Regel(**angaben, quelle=quelle, erstellt=jetzt, geaendert=jetzt)
        db.add(regel)
        db.commit()
        self._zeitplan_vormerken(regel)
        return regel

    def aendern(self, db: Session, regel_id: int, daten: Any) -> Regel:
        regel = self.holen(db, regel_id)
        angaben = regel_pruefen(daten, self.umfeld(db))
        for name, wert in angaben.items():
            setattr(regel, name, wert)
        regel.geaendert = zeit.jetzt()
        db.commit()
        self._zuruecksetzen(regel.id)
        self._zeitplan_vormerken(regel)
        return regel

    def aktiv_setzen(self, db: Session, regel_id: int, aktiv: bool) -> Regel:
        """Regel pausieren oder wieder einschalten."""
        regel = self.holen(db, regel_id)
        regel.aktiv = aktiv
        regel.geaendert = zeit.jetzt()
        db.commit()
        self._zuruecksetzen(regel.id)
        self._zeitplan_vormerken(regel)
        return regel

    def loeschen(self, db: Session, regel_id: int) -> Regel:
        regel = self.holen(db, regel_id)
        db.delete(regel)
        db.commit()
        self._zuruecksetzen(regel_id)
        return regel

    def verlauf(self, db: Session, regel_id: int | None = None, limit: int = 50) -> dict[str, Any]:
        abfrage = select(Ausloesung, Regel.name).join(Regel, Regel.id == Ausloesung.regel_id)
        zaehlen = select(func.count()).select_from(Ausloesung)
        if regel_id is not None:
            abfrage = abfrage.where(Ausloesung.regel_id == regel_id)
            zaehlen = zaehlen.where(Ausloesung.regel_id == regel_id)
        zeilen = db.execute(abfrage.order_by(Ausloesung.id.desc()).limit(max(1, min(limit, 500))))
        return {
            "anzahl": db.scalar(zaehlen) or 0,
            "eintraege": [
                {
                    "id": eintrag.id,
                    "regel_id": eintrag.regel_id,
                    "regel": name,
                    "zeit": eintrag.zeit.isoformat(),
                    "anlass": eintrag.anlass,
                    "ergebnis": eintrag.ergebnis,
                    "ergebnis_name": ERGEBNIS_NAMEN.get(eintrag.ergebnis, eintrag.ergebnis),
                    "meldung": eintrag.meldung,
                    "test": eintrag.test,
                }
                for eintrag, name in zeilen
            ],
        }

    def aufraeumen(self, tage: int) -> int:
        """Löscht Einträge im Verlauf, die älter als `tage` Tage sind."""
        with self.datenbank.sitzung() as db:
            grenze = zeit.jetzt() - timedelta(days=tage)
            ergebnis = db.execute(delete(Ausloesung).where(Ausloesung.zeit < grenze))
            db.commit()
            return ergebnis.rowcount or 0

    # ------------------------------------------------------------------ Auslöser beobachten

    def _aktive(self, db: Session, art: str) -> list[Regel]:
        return [
            regel
            for regel in db.scalars(select(Regel).where(Regel.aktiv.is_(True)).order_by(Regel.id))
            if (regel.ausloeser or {}).get("art") == art
        ]

    def messwerte_pruefen(self, werte: dict[str, float | None]) -> None:
        """Neue Messwerte (Serverlast, später auch Geräte): prüft alle Schwellwert-Regeln dazu."""
        jetzt = zeit.jetzt()
        with self.datenbank.sitzung() as db:
            regeln = [r for r in self._aktive(db, "messwert") if r.ausloeser.get("messwert") in werte]
            if not regeln:
                return
            messwerte = self.umfeld(db).messwerte
            for regel in regeln:
                ausloeser = regel.ausloeser
                wert, schwelle = werte[ausloeser["messwert"]], ausloeser["schwelle"]
                ueber = ausloeser.get("vergleich") != "unter"
                erfuellt = wert is not None and (wert > schwelle if ueber else wert < schwelle)
                with self._zustand:
                    if not erfuellt:
                        self._erfuellt_seit.pop(regel.id, None)
                        continue
                    seit = self._erfuellt_seit.setdefault(regel.id, jetzt)
                dauer = int(ausloeser.get("dauer_minuten") or 0)
                if wert is None or jetzt - seit < timedelta(minutes=dauer):
                    continue
                titel, einheit = messwerte.get(ausloeser["messwert"], (ausloeser["messwert"], ""))
                text = (
                    f"{titel}: {satz.mit_einheit(round(wert, 1), einheit)} "
                    f"({'über' if ueber else 'unter'} {satz.mit_einheit(schwelle, einheit)}"
                    + (f" seit {satz.dauer_text(dauer)}" if dauer else "")
                    + ")"
                )
                self._einreihen(Anlass(regel.id, text, {"wert": round(wert, 1)}))

    def ereignis_pruefen(self, ereignis: dict[str, Any]) -> None:
        """Ein internes Ereignis (Webhook, Gerät, Integration ausgefallen): passende Regeln auslösen."""
        art = ereignis.get("art")
        if art not in _EREIGNIS_AUSLOESER:
            return
        daten = ereignis.get("daten") or {}
        with self.datenbank.sitzung() as db:
            for regel in self._aktive(db, str(art)):
                ausloeser = regel.ausloeser
                if art == "geraet":
                    if ausloeser.get("geraet_id") not in (None, daten.get("geraet_id")):
                        continue
                    if ausloeser.get("faehigkeit") and ausloeser["faehigkeit"] != daten.get("faehigkeit"):
                        continue
                elif ausloeser.get("integration_id") not in (None, daten.get("integration_id")):
                    continue
                text = str(ereignis.get("titel") or AUSLOESER_ARTEN[str(art)])
                mitgabe = {"wert": daten["wert"]} if "wert" in daten else {}
                self._einreihen(Anlass(regel.id, text, mitgabe, still=False))

    def _naechste(self, ausloeser: dict[str, Any], ab: datetime) -> datetime:
        """Wann eine Zeitplan-Regel das nächste Mal fällig ist (nach `ab`)."""
        if ausloeser.get("modus") == "intervall":
            return ab + timedelta(minutes=int(ausloeser["intervall_minuten"]))
        stunde, minute = (int(teil) for teil in ausloeser["uhrzeit"].split(":"))
        lokal = ab.astimezone(self.zeitzone)
        ziel = datetime.combine(lokal.date(), uhrzeit_typ(stunde, minute), tzinfo=self.zeitzone)
        if ziel <= lokal:
            ziel = datetime.combine(
                lokal.date() + timedelta(days=1), uhrzeit_typ(stunde, minute), tzinfo=self.zeitzone
            )
        return ziel.astimezone(UTC)

    def zeitplan_pruefen(self) -> None:
        """Reiht alle Zeitplan-Regeln ein, deren Zeitpunkt gekommen ist (läuft im Takt der Hintergrundaufgabe)."""
        jetzt = zeit.jetzt()
        with self.datenbank.sitzung() as db:
            regeln = self._aktive(db, "zeitplan")
        aktive = {regel.id for regel in regeln}
        faellige: list[Regel] = []
        with self._zustand:
            for regel in regeln:
                faellig = self._faellig.get(regel.id)
                if faellig is None:
                    # Erste Sichtung (z. B. nach einem Neustart): ab jetzt zählen, nichts nachholen.
                    self._faellig[regel.id] = self._naechste(regel.ausloeser, jetzt)
                elif jetzt >= faellig:
                    self._faellig[regel.id] = self._naechste(regel.ausloeser, jetzt)
                    faellige.append(regel)
            for regel_id in set(self._faellig) - aktive:
                del self._faellig[regel_id]
        uhr = jetzt.astimezone(self.zeitzone).strftime("%H:%M")
        for regel in faellige:
            self._einreihen(Anlass(regel.id, f"Zeitplan ({uhr} Uhr)"))

    # ------------------------------------------------------------------ abarbeiten

    def _einreihen(self, anlass: Anlass) -> None:
        with self._fortschritt:
            self._anstehend.append(anlass)
            self._offen += 1
        wecker = self._wecker
        if wecker is not None:
            loop, klingel = wecker
            with contextlib.suppress(RuntimeError):  # Loop schon beendet
                loop.call_soon_threadsafe(klingel.set)

    async def laufen(self) -> None:
        """Hintergrundaufgabe: prüft den Zeitplan im Takt und arbeitet ab, was ausgelöst wurde."""
        klingel = asyncio.Event()
        self._wecker = (asyncio.get_running_loop(), klingel)
        try:
            while True:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(klingel.wait(), timeout=self.takt_sekunden)
                klingel.clear()
                try:
                    await asyncio.to_thread(self.zeitplan_pruefen)
                    await self.abarbeiten()
                except Exception:
                    log.exception("Fehler beim Abarbeiten der Regeln")
        finally:
            self._wecker = None

    async def abarbeiten(self) -> None:
        """Bearbeitet alles, was gerade ansteht – der Reihe nach."""
        while True:
            with self._fortschritt:
                if not self._anstehend:
                    return
                anlass = self._anstehend.popleft()
            try:
                await self._bearbeiten(anlass)
            except Exception:
                log.exception("Regel %s konnte nicht bearbeitet werden", anlass.regel_id)
            finally:
                with self._fortschritt:
                    self._offen -= 1
                    self._fortschritt.notify_all()

    def warten(self, sekunden: float = 5.0) -> bool:
        """Wartet, bis alles Ausgelöste bearbeitet ist (für Tests und „Jetzt testen“)."""
        with self._fortschritt:
            return self._fortschritt.wait_for(lambda: self._offen == 0, timeout=sekunden)

    def _bedingung_erfuellt(self, bedingung: dict[str, Any], jetzt: datetime) -> bool:
        lokal = jetzt.astimezone(self.zeitzone)
        if bedingung.get("tage") and lokal.weekday() not in bedingung["tage"]:
            return False
        if bedingung.get("von"):
            uhr, von, bis = lokal.strftime("%H:%M"), bedingung["von"], bedingung["bis"]
            # „22:00 bis 06:00“ reicht über Mitternacht.
            return von <= uhr < bis if von < bis else (uhr >= von or uhr < bis)
        return True

    async def _bearbeiten(self, anlass: Anlass) -> None:
        with self.datenbank.sitzung() as db:
            regel = db.get(Regel, anlass.regel_id)
            if regel is None or not regel.aktiv:
                return
            jetzt = zeit.jetzt()
            if not self._bedingung_erfuellt(regel.bedingung or {}, jetzt):
                if not anlass.still:
                    nur = satz.bedingung_text(regel.bedingung or {})
                    self._vermerken(db, regel, anlass, "bedingung", f"Nicht ausgeführt: gilt nur {nur}.")
                return
            ruhe = timedelta(minutes=regel.ruhezeit_minuten or 0)
            zeitplan = regel.ausloeser.get("art") == "zeitplan"  # der Zeitplan gibt den Takt selbst vor
            if not zeitplan and regel.zuletzt_ausgeloest and jetzt - regel.zuletzt_ausgeloest < ruhe:
                if not anlass.still:
                    bis = (regel.zuletzt_ausgeloest + ruhe).astimezone(self.zeitzone).strftime("%H:%M")
                    self._vermerken(
                        db, regel, anlass, "ruhezeit", f"Nicht ausgeführt: Ruhezeit bis {bis} Uhr."
                    )
                return
            await self._ausfuehren(db, regel, anlass, test=False)

    @staticmethod
    def _vermerken(
        db: Session, regel: Regel, anlass: Anlass, ergebnis: str, meldung: str, test: bool = False
    ) -> None:
        db.add(
            Ausloesung(
                regel_id=regel.id,
                zeit=zeit.jetzt(),
                anlass=anlass.text[:500],
                ergebnis=ergebnis,
                meldung=meldung[:1000],
                test=test,
            )
        )
        db.commit()

    async def _ausfuehren(self, db: Session, regel: Regel, anlass: Anlass, *, test: bool) -> tuple[bool, str]:
        art = self.aktions_arten.get((regel.aktion or {}).get("art", ""))
        try:
            if art is None:
                raise IntegrationsFehler("Diese Art von Aktion gibt es nicht (mehr).")
            meldung, ok = await art.ausfuehren(db, regel, anlass, test), True
        except (IntegrationsFehler, PanelFehler) as fehler:
            meldung, ok = fehler.meldung + (f" Hinweis: {fehler.hinweis}" if fehler.hinweis else ""), False
        except Exception as fehler:
            log.exception("Aktion der Regel „%s“ fehlgeschlagen", regel.name)
            meldung, ok = f"Unerwarteter Fehler: {type(fehler).__name__}", False
        if not test:
            # Auch ein Fehlschlag zählt für die Ruhezeit – sonst würde alle 30 Sekunden neu versucht.
            regel.zuletzt_ausgeloest = zeit.jetzt()
        self._vermerken(db, regel, anlass, "ok" if ok else "fehler", meldung, test)
        return ok, meldung

    async def testen(self, db: Session, regel_id: int) -> dict[str, Any]:
        """„Jetzt testen“: führt die Aktion sofort aus – ohne Auslöser, Bedingung und Ruhezeit."""
        regel = self.holen(db, regel_id)
        ok, meldung = await self._ausfuehren(db, regel, Anlass(regel.id, "Test im Panel"), test=True)
        return {"ok": ok, "meldung": meldung}

    # ------------------------------------------------------------------ Aktionen

    @staticmethod
    def platzhalter(text: str, regel: Regel, anlass: Anlass) -> str:
        """In der Nachricht stehen {wert}, {anlass} und {name} für den aktuellen Wert, den Anlass und die Regel."""
        wert = anlass.daten.get("wert")
        ersetzungen = {
            "{wert}": satz.zahl_text(wert)
            if isinstance(wert, int | float)
            else str(wert if wert is not None else "?"),
            "{anlass}": anlass.text,
            "{name}": regel.name,
        }
        for platzhalter, inhalt in ersetzungen.items():
            text = text.replace(platzhalter, inhalt)
        return text

    async def _aktion_ereignis(self, db: Session, regel: Regel, anlass: Anlass, test: bool) -> str:
        aktion = regel.aktion
        self.ereignisse.melden(
            "regel",
            f"Regel „{regel.name}“ ausgelöst" + (" (Test)" if test else ""),
            self.platzhalter(str(aktion.get("nachricht", "")), regel, anlass),
            dringlichkeit=str(aktion.get("dringlichkeit", "normal")),
            quelle="Regeln",
            daten={
                "regel_id": regel.id,
                "regel": regel.name,
                "anlass": anlass.text,
                "test": test,
                **anlass.daten,
            },
        )
        return "Ereignis an Missa gesendet."

    async def _aktion_funktion(self, db: Session, regel: Regel, anlass: Anlass, test: bool) -> str:
        name = str(regel.aktion.get("funktion", ""))
        treffer = next((t for t in sichtbare_funktionen(db) if t[0] == name), None)
        if treffer is None:
            raise IntegrationsFehler(
                f"Die Funktion „{name}“ gibt es nicht (mehr) oder sie ist gesperrt.",
                "Die Regel bearbeiten und eine andere Funktion wählen – oder die Funktion unter „Integrationen“ wieder freigeben.",
            )
        _, integration, funktion = treffer
        start = time.monotonic()

        def protokollieren(ok: bool, fehler: str = "") -> None:
            self.protokoll.eintragen(
                quelle="regel",
                client_name=f"Regel „{regel.name}“",
                integration_name=integration.name,
                funktion=name,
                ok=ok,
                fehler=fehler,
                dauer_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            ergebnis = await self.integrationen.aufrufen(
                db, integration, funktion.name, dict(regel.aktion.get("argumente") or {})
            )
        except IntegrationsFehler as fehler:
            protokollieren(False, fehler.meldung)
            raise
        text = ergebnis_als_text(ergebnis)
        protokollieren(not ergebnis.ist_fehler, text[:300] if ergebnis.ist_fehler else "")
        if ergebnis.ist_fehler:
            raise IntegrationsFehler(text[:300])
        return f"„{name}“ aufgerufen. Antwort: {text[:300]}"

    # ------------------------------------------------------------------ für Missa (eingebaute Integration)

    @staticmethod
    def _nach_name(name: Any, bekannte: dict[int, str], was: str) -> int | None:
        gesucht = str(name).strip().lower()
        if gesucht in _ALLE:
            return None
        for nummer, bekannt in bekannte.items():
            if bekannt.lower() == gesucht:
                return nummer
        raise PanelFehler(
            422,
            f"{was} „{name}“ gibt es nicht.",
            "Zur Auswahl stehen: " + (", ".join(bekannte.values()) or "noch nichts") + ".",
        )

    def _aus_einzelangaben(
        self, einzeln: dict[str, Any], bisher: dict[str, Any] | None, umfeld: Umfeld
    ) -> dict[str, Any]:
        """Macht aus den einzelnen Parametern der Missa-Funktionen die Angaben einer Regel.

        Beim Ändern (`bisher`) bleibt alles, was nicht genannt wird, wie es ist.
        """
        neu = {name: wert for name, wert in einzeln.items() if wert is not None}
        regel: dict[str, Any] = bisher or {
            "bedingung": {},
            "ruhezeit_minuten": STANDARD_RUHEZEIT,
            "aktiv": True,
        }
        for feld in ("name", "aktiv", "ruhezeit_minuten"):
            if feld in neu:
                regel[feld] = neu[feld]

        alter = regel.get("ausloeser") or {}
        art = neu.get("ausloeser") or alter.get("art")
        ausloeser = {**alter} if art == alter.get("art") else {}
        ausloeser["art"] = art
        for feld in ("messwert", "vergleich", "schwelle", "dauer_minuten", "faehigkeit"):
            if feld in neu:
                ausloeser[feld] = neu[feld]
        if "uhrzeit" in neu:
            ausloeser.update(modus="uhrzeit", uhrzeit=neu["uhrzeit"])
        elif "intervall_minuten" in neu:
            ausloeser.update(modus="intervall", intervall_minuten=neu["intervall_minuten"])
        if "integration" in neu:
            bekannte = umfeld.webhooks if art == "webhook" else umfeld.integrationen
            was = "Den Webhook" if art == "webhook" else "Die Integration"
            ausloeser["integration_id"] = self._nach_name(neu["integration"], bekannte, was)
        if "geraet" in neu:
            ausloeser["geraet_id"] = self._nach_name(neu["geraet"], umfeld.geraete, "Das Gerät")
        regel["ausloeser"] = ausloeser

        alte = regel.get("aktion") or {}
        aktion_art = neu.get("aktion") or alte.get("art") or ("funktion" if "funktion" in neu else "ereignis")
        aktion = {**alte} if aktion_art == alte.get("art") else {}
        aktion["art"] = aktion_art
        for feld in ("nachricht", "dringlichkeit", "funktion", "argumente", "nummer"):
            if feld in neu:
                aktion[feld] = neu[feld]
        regel["aktion"] = aktion

        bedingung = dict(regel.get("bedingung") or {})
        if "wochentage" in neu:
            bedingung["tage"] = neu["wochentage"]
        for feld in ("von", "bis"):
            if feld in neu:
                bedingung[feld] = neu[feld]
        regel["bedingung"] = bedingung
        return regel

    def fuer_missa_auflisten(self) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            umfeld = self.umfeld(db)
            regeln = [self.ansicht(regel, umfeld) for regel in db.scalars(select(Regel).order_by(Regel.id))]
        return {
            "anzahl": len(regeln),
            "regeln": [
                {
                    "id": regel["id"],
                    "name": regel["name"],
                    "aktiv": regel["aktiv"],
                    "beschreibung": regel["satz"],
                    "zuletzt_ausgeloest": regel["zuletzt_ausgeloest"],
                }
                for regel in regeln
            ],
        }

    def vorschau_anlegen(self, **einzeln: Any) -> str:
        with self.datenbank.sitzung() as db:
            umfeld = self.umfeld(db)
            angaben = regel_pruefen(self._aus_einzelangaben(einzeln, None, umfeld), umfeld)
            return f"Legt die Regel „{angaben['name']}“ an: {satz.regel_satz(angaben, umfeld)}"

    def fuer_missa_anlegen(self, **einzeln: Any) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            umfeld = self.umfeld(db)
            regel = self.anlegen(db, self._aus_einzelangaben(einzeln, None, umfeld), quelle=QUELLE_MISSA)
            ansicht = self.ansicht(regel, umfeld)
        return {"id": ansicht["id"], "meldung": "Regel angelegt.", "beschreibung": ansicht["satz"]}

    def _geaendert(
        self, db: Session, regel_id: int, einzeln: dict[str, Any], umfeld: Umfeld
    ) -> dict[str, Any]:
        return self._aus_einzelangaben(einzeln, self._angaben(self.holen(db, regel_id)), umfeld)

    def vorschau_aendern(self, regel_id: int, **einzeln: Any) -> str:
        with self.datenbank.sitzung() as db:
            umfeld = self.umfeld(db)
            vorher = self.holen(db, regel_id)
            angaben = regel_pruefen(self._geaendert(db, regel_id, einzeln, umfeld), umfeld)
            zustand = "" if angaben["aktiv"] else " Die Regel ist danach pausiert."
            return f"Ändert die Regel „{vorher.name}“. Neu: {satz.regel_satz(angaben, umfeld)}{zustand}"

    def fuer_missa_aendern(self, regel_id: int, **einzeln: Any) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            umfeld = self.umfeld(db)
            regel = self.aendern(db, regel_id, self._geaendert(db, regel_id, einzeln, umfeld))
            ansicht = self.ansicht(regel, umfeld)
        return {
            "id": ansicht["id"],
            "meldung": "Regel geändert.",
            "aktiv": ansicht["aktiv"],
            "beschreibung": ansicht["satz"],
        }

    def vorschau_loeschen(self, regel_id: int) -> str:
        with self.datenbank.sitzung() as db:
            regel = self.holen(db, regel_id)
            return (
                f"Löscht die Regel „{regel.name}“: {satz.regel_satz(self._angaben(regel), self.umfeld(db))}"
            )

    def fuer_missa_loeschen(self, regel_id: int) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            regel = self.loeschen(db, regel_id)
            return {"id": regel_id, "meldung": f"Regel „{regel.name}“ gelöscht."}
