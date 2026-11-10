"""Der Dienst hinter „Katalog“ und „Integrationen“: einrichten, testen, Rechte, aufrufen."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import anyio
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from missa_control import zeit
from missa_control.fehler import PanelFehler
from missa_control.integrationen.adapter import Adapter, standard_adapter
from missa_control.integrationen.adapter import python as python_adapter
from missa_control.integrationen.adapter import webhook as webhook_adapter
from missa_control.integrationen.fehlertexte import fehler_erklaeren
from missa_control.integrationen.katalog import Katalog, KatalogEintrag
from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.manifest import ART_NAMEN, Feld, Manifest
from missa_control.integrationen.modelle import Funktion, Integration
from missa_control.integrationen.typen import (
    RECHTE,
    STATUS_FEHLER,
    STATUS_OK,
    AufrufErgebnis,
    FunktionsInfo,
    IntegrationsFehler,
    Recht,
    TestErgebnis,
    standardrecht,
)
from missa_control.zugaenge.dienst import TYP_NAMEN, ZugangsDienst
from missa_control.zugaenge.modelle import Zugang

log = logging.getLogger(__name__)

TEST_SEKUNDEN = 45.0
# Die regelmässige Prüfung wartet kürzer: Antwortet die Gegenstelle so lange nicht, gilt sie als ausgefallen.
PRUEF_SEKUNDEN = 8.0
# Arten mit einer Gegenstelle, die ausfallen kann. Geräte melden ihren Zustand selbst (MQTT),
# ein Webhook wartet nur auf Eingänge.
REGELMAESSIG_GEPRUEFT = ("mcp", "openapi", "python")
VORSCHAU_SEKUNDEN = 10.0
TEST_GUELTIG = timedelta(minutes=15)
# Ab so vielen Funktionen (grosse REST-APIs) ist zunächst nichts ausgewählt – man wählt gezielt aus.
VORAUSWAHL_GRENZE = 40
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def kennung_aus_name(name: str) -> str:
    """„Mein Wetter-Dienst“ → `mein_wetter_dienst` (Vorsilbe für Funktionsnamen)."""
    roh = re.sub(r"[^a-z0-9]+", "_", name.lower().translate(_UMLAUTE)).strip("_")[:30].strip("_")
    if not roh:
        return "integration"
    return roh if roh[0].isalpha() else f"i_{roh}"


def gateway_name(kennung: str, funktion: str) -> str:
    """Name einer Funktion am Gateway: mit Vorsilbe der Integration, höchstens 64 Zeichen."""
    name = funktion if funktion == kennung or funktion.startswith(kennung + "_") else f"{kennung}_{funktion}"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    if len(name) > 64:
        name = name[:55] + "_" + hashlib.sha1(name.encode()).hexdigest()[:8]
    return name


@dataclass
class _GemerkterTest:
    zeitpunkt: datetime
    manifest_id: str
    konfig_pruefsumme: str
    ergebnis: TestErgebnis


def _pruefsumme(konfig: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(konfig, sort_keys=True, default=str).encode()).hexdigest()


class IntegrationsDienst:
    def __init__(self, *, katalog: Katalog, zugaenge: ZugangsDienst, panel: Any = None) -> None:
        self.katalog = katalog
        self.zugaenge = zugaenge
        self.panel = panel
        self.adapter: dict[str, Adapter] = standard_adapter()
        self._tests: dict[str, _GemerkterTest] = {}
        # Wird beim Start gesetzt: meldet Ausfälle als Ereignis (für Missa und für Regeln).
        self.ereignis_melden: Callable[..., Any] | None = None

    # ------------------------------------------------------------------ Katalog

    def katalog_ansicht(self, db: Session) -> dict[str, Any]:
        anzahl = dict(
            db.execute(select(Integration.manifest_id, func.count()).group_by(Integration.manifest_id)).all()
        )
        eintraege = []
        for eintrag in sorted(
            self.katalog.eintraege.values(), key=lambda e: (not e.eingebaut, e.manifest.name.lower())
        ):
            manifest = eintrag.manifest
            eingerichtet = int(anzahl.get(manifest.id, 0))
            eintraege.append(
                {
                    **self._manifest_ansicht(manifest),
                    "eingebaut": eintrag.eingebaut,
                    "eingerichtet": eingerichtet,
                    "verfuegbar": manifest.art in self.adapter,
                    "kann_hinzufuegen": manifest.art in self.adapter
                    and (manifest.mehrfach or eingerichtet == 0),
                }
            )
        probleme = [
            {"ordner": problem.ordner, "meldungen": problem.meldungen} for problem in self.katalog.probleme
        ]
        return {"eintraege": eintraege, "probleme": probleme}

    @staticmethod
    def _manifest_ansicht(manifest: Manifest) -> dict[str, Any]:
        return {
            "id": manifest.id,
            "name": manifest.name,
            "beschreibung": manifest.beschreibung,
            "symbol": manifest.symbol,
            "art": manifest.art,
            "art_name": ART_NAMEN[manifest.art],
            "version": manifest.version,
            "mehrfach": manifest.mehrfach,
            "hinweis": manifest.hinweis,
            "felder": [feld.model_dump() for feld in manifest.felder],
        }

    # ------------------------------------------------------------------ Formularwerte

    def _konfig_pruefen(
        self,
        db: Session,
        manifest: Manifest,
        eingabe: dict[str, Any],
        *,
        vollstaendig: bool,
        bisher: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prüft und bereinigt die Formularwerte. `vollstaendig=False`: Felder nach dem Test dürfen fehlen."""
        konfig: dict[str, Any] = {}
        for feld in manifest.felder:
            wert = eingabe.get(feld.name)
            if feld.typ == "datei" and (wert is None or isinstance(wert, dict)) and bisher:
                wert = bisher.get(feld.name)  # gespeicherte Datei behalten
            if wert is None or (isinstance(wert, str) and not wert.strip()):
                wert = feld.standard
            wert = self._feld_pruefen(db, feld, wert)
            fehlt = wert is None or wert == ""
            if fehlt and feld.pflicht and (vollstaendig or not feld.nach_test):
                raise PanelFehler(422, f"Bitte „{feld.titel}“ ausfüllen.", feld.hilfe or None)
            if not fehlt:
                konfig[feld.name] = wert
        return konfig

    def _feld_pruefen(self, db: Session, feld: Feld, wert: Any) -> Any:
        if wert is None or wert == "":
            return None
        titel = feld.titel
        if feld.typ == "schalter":
            return (
                wert
                if isinstance(wert, bool)
                else str(wert).strip().lower() in ("1", "true", "ja", "an", "on")
            )
        if feld.typ == "zahl":
            try:
                zahl = float(str(wert).replace(",", "."))
            except ValueError:
                raise PanelFehler(422, f"„{titel}“ muss eine Zahl sein.") from None
            return int(zahl) if zahl.is_integer() else zahl
        if feld.typ == "zugang":
            try:
                zugang_id = int(wert)
            except (TypeError, ValueError):
                raise PanelFehler(422, f"„{titel}“: ungültiger Zugang.") from None
            zugang = db.get(Zugang, zugang_id)
            if zugang is None:
                raise PanelFehler(
                    422,
                    f"„{titel}“: Der ausgewählte Zugang existiert nicht mehr.",
                    "Bitte einen anderen Zugang auswählen oder einen neuen anlegen.",
                )
            if feld.zugang_typen and zugang.typ not in feld.zugang_typen:
                erlaubt = ", ".join(TYP_NAMEN[typ] for typ in feld.zugang_typen)
                raise PanelFehler(
                    422, f"„{titel}“: Der Zugang hat die falsche Art.", f"Erwartet wird: {erlaubt}."
                )
            return zugang_id
        text = str(wert) if feld.typ == "datei" else str(wert).strip()
        if feld.typ == "url" and not re.match(r"^https?://[^\s/]+", text):
            raise PanelFehler(
                422,
                f"„{titel}“ ist keine gültige Adresse.",
                "Die Adresse muss mit http:// oder https:// beginnen, z. B. http://192.168.1.20:8000",
            )
        if feld.typ == "auswahl" and feld.optionen and text not in {option.wert for option in feld.optionen}:
            raise PanelFehler(422, f"„{titel}“: „{text}“ steht nicht zur Auswahl.")
        return text

    def _kontext(
        self,
        db: Session,
        eintrag: KatalogEintrag,
        *,
        name: str,
        kennung: str,
        konfig: dict[str, Any],
        zustand: dict[str, Any] | None,
        integration_id: int | None,
    ) -> Kontext:
        zugangsdaten = {}
        werte = {}
        for feld in eintrag.manifest.felder:
            if feld.typ == "zugang":
                if konfig.get(feld.name) is not None:
                    zugangsdaten[feld.name] = self.zugaenge.klartext(db, int(konfig[feld.name]))
            elif feld.name in konfig:
                werte[feld.name] = konfig[feld.name]
        return Kontext(
            name=name,
            kennung=kennung,
            manifest=eintrag.manifest,
            konfig=werte,
            zustand=copy.deepcopy(zustand or {}),
            zugangsdaten=zugangsdaten,
            ordner=eintrag.ordner,
            panel=self.panel,
            integration_id=integration_id,
        )

    def _adapter(self, manifest: Manifest) -> Adapter:
        adapter = self.adapter.get(manifest.art)
        if adapter is None:
            raise PanelFehler(
                409,
                f"Integrationen der Art „{ART_NAMEN[manifest.art]}“ kommen mit einer späteren Version.",
            )
        return adapter

    # ------------------------------------------------------------------ Verbindung testen

    async def _test_ausfuehren(
        self, adapter: Adapter, kontext: Kontext, sekunden: float = TEST_SEKUNDEN
    ) -> TestErgebnis:
        try:
            with anyio.fail_after(sekunden):
                return await adapter.testen(kontext)
        except Exception as fehler:
            meldung, hinweis = fehler_erklaeren(fehler)
            log.info("Verbindungstest für „%s“ fehlgeschlagen: %s", kontext.name, meldung)
            return TestErgebnis(ok=False, meldung=meldung, hinweis=hinweis)

    def _empfohlenes_recht(self, manifest: Manifest, info: FunktionsInfo, viele: bool) -> Recht:
        if info.name in manifest.standardrechte:
            return manifest.standardrechte[info.name]
        if viele:
            return "gesperrt"
        return standardrecht(info.schreibend)

    async def testen(
        self, db: Session, *, manifest_id: str, konfig: dict[str, Any], integration_id: int | None = None
    ) -> dict[str, Any]:
        """Testet ein (noch nicht gespeichertes) Formular. Schlägt der Test fehl, steht das im Ergebnis."""
        eintrag = self.katalog.holen(manifest_id)
        manifest = eintrag.manifest
        integration = self.holen(db, integration_id) if integration_id is not None else None
        bereinigt = self._konfig_pruefen(
            db, manifest, konfig, vollstaendig=False, bisher=integration.konfig if integration else None
        )
        kontext = self._kontext(
            db,
            eintrag,
            name=integration.name if integration else manifest.name,
            kennung=integration.kennung
            if integration
            else (manifest.kennung or kennung_aus_name(manifest.name)),
            konfig=bereinigt,
            zustand=integration.zustand if integration else None,
            integration_id=integration_id,
        )
        ergebnis = await self._test_ausfuehren(self._adapter(manifest), kontext)
        if not ergebnis.ok:
            return {"ok": False, "meldung": ergebnis.meldung, "hinweis": ergebnis.hinweis}

        self._tests_aufraeumen()
        test_id = secrets.token_urlsafe(16)
        self._tests[test_id] = _GemerkterTest(zeit.jetzt(), manifest_id, _pruefsumme(bereinigt), ergebnis)
        bisherige = {f.name: f.recht for f in integration.funktionen} if integration else {}
        viele = len(ergebnis.funktionen) > VORAUSWAHL_GRENZE and not integration
        return {
            "ok": True,
            "test_id": test_id,
            "meldung": ergebnis.meldung,
            "details": ergebnis.details,
            "optionen": ergebnis.optionen,
            "viele_funktionen": viele,
            "funktionen": [
                {
                    "name": info.name,
                    "beschreibung": info.beschreibung,
                    "schreibend": info.schreibend,
                    "recht": bisherige.get(info.name) or self._empfohlenes_recht(manifest, info, viele),
                }
                for info in sorted(ergebnis.funktionen, key=lambda info: info.name)
            ],
        }

    def _tests_aufraeumen(self) -> None:
        grenze = zeit.jetzt() - TEST_GUELTIG
        for test_id in [test_id for test_id, test in self._tests.items() if test.zeitpunkt < grenze]:
            del self._tests[test_id]

    async def _ergebnis_fuer(
        self,
        db: Session,
        eintrag: KatalogEintrag,
        kontext: Kontext,
        konfig: dict[str, Any],
        test_id: str | None,
    ) -> TestErgebnis:
        """Nimmt das Ergebnis des gerade gelaufenen Tests – oder testet neu, wenn es nicht (mehr) passt."""
        self._tests_aufraeumen()
        gemerkt = self._tests.pop(test_id, None) if test_id else None
        # Felder, die erst nach dem Test ausgefüllt werden, ändern den Test selbst nicht.
        ohne_nachtraege = {
            name: wert
            for name, wert in konfig.items()
            if not getattr(eintrag.manifest.feld(name), "nach_test", False)
        }
        if (
            gemerkt is not None
            and gemerkt.manifest_id == eintrag.manifest.id
            and gemerkt.konfig_pruefsumme in (_pruefsumme(konfig), _pruefsumme(ohne_nachtraege))
        ):
            return gemerkt.ergebnis
        return await self._test_ausfuehren(self._adapter(eintrag.manifest), kontext)

    # ------------------------------------------------------------------ eingerichtete Integrationen

    def alle(self, db: Session) -> list[dict[str, Any]]:
        abfrage = select(Integration).options(selectinload(Integration.funktionen)).order_by(Integration.name)
        return [self.ansicht(integration) for integration in db.scalars(abfrage)]

    def holen(self, db: Session, integration_id: int) -> Integration:
        integration = db.get(Integration, integration_id)
        if integration is None:
            raise PanelFehler(404, "Diese Integration gibt es nicht (mehr).")
        return integration

    def ansicht(self, integration: Integration) -> dict[str, Any]:
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        manifest = eintrag.manifest if eintrag else None
        konfig = dict(integration.konfig or {})
        if manifest:
            for feld in manifest.felder:
                if feld.typ == "datei" and isinstance(konfig.get(feld.name), str):
                    konfig[feld.name] = {"datei": True, "zeichen": len(konfig[feld.name])}
        zusatz: dict[str, Any] = {}
        if getattr(integration, "einmalig", None):
            # Nur direkt nach dem Einrichten: z. B. die Zugangsdaten eines Geräts (werden nie wieder gezeigt).
            zusatz["kopplung"] = integration.einmalig
        if manifest and manifest.art == "webhook" and self.panel is not None:
            # Die geheime Adresse, an die andere Dienste senden – nur der angemeldete Besitzer sieht sie.
            zusatz["webhook"] = {"pfad": webhook_adapter.pfad(integration.zustand, self.panel.krypto)}
        return {
            **zusatz,
            "id": integration.id,
            "manifest_id": integration.manifest_id,
            "manifest": self._manifest_ansicht(manifest) if manifest else None,
            "name": integration.name,
            "kennung": integration.kennung,
            "symbol": manifest.symbol if manifest else "❓",
            "art": manifest.art if manifest else None,
            "art_name": ART_NAMEN[manifest.art] if manifest else "unbekannt",
            "konfig": konfig,
            "aktiv": integration.aktiv,
            "status": integration.status if manifest else STATUS_FEHLER,
            "status_meldung": integration.status_meldung
            if manifest
            else "Diese Integration ist nicht mehr im Katalog vorhanden.",
            "status_hinweis": integration.status_hinweis
            if manifest
            else "Wurde der Ordner der Integration gelöscht? Wieder hinzufügen oder die Integration entfernen.",
            "geprueft": integration.geprueft.isoformat() if integration.geprueft else None,
            "erstellt": integration.erstellt.isoformat(),
            "geaendert": integration.geaendert.isoformat(),
            "funktionen": [
                {
                    "id": funktion.id,
                    "name": funktion.name,
                    "gateway_name": gateway_name(integration.kennung, funktion.name),
                    "beschreibung": funktion.beschreibung,
                    "schreibend": funktion.schreibend,
                    "recht": funktion.recht,
                    "vorhanden": funktion.vorhanden,
                    "parameter": funktion.parameter,
                }
                for funktion in integration.funktionen
            ],
        }

    def _freie_kennung(self, db: Session, wunsch: str, ausser: int | None = None) -> str:
        vergeben = {
            kennung
            for kennung, integration_id in db.execute(select(Integration.kennung, Integration.id))
            if integration_id != ausser
        }
        kandidat, nummer = wunsch, 2
        while kandidat in vergeben:
            kandidat = f"{wunsch}_{nummer}"
            nummer += 1
        return kandidat

    @staticmethod
    def _rechte_pruefen(rechte: dict[str, str] | None) -> dict[str, Recht]:
        geprueft: dict[str, Recht] = {}
        for name, recht in (rechte or {}).items():
            if recht not in RECHTE:
                raise PanelFehler(
                    422, f"Unbekanntes Recht „{recht}“.", "Erlaubt: erlaubt, nachfragen, gesperrt."
                )
            geprueft[name] = recht  # type: ignore[assignment]
        return geprueft

    def _funktionen_abgleichen(
        self,
        integration: Integration,
        manifest: Manifest,
        gefunden: list[FunktionsInfo],
        rechte: dict[str, Recht],
    ) -> None:
        """Übernimmt die Funktionen aus einem Test: neue dazu, bekannte aktualisieren, fehlende markieren."""
        vorhandene = {funktion.name: funktion for funktion in integration.funktionen}
        viele = len(gefunden) > VORAUSWAHL_GRENZE and not vorhandene
        for info in gefunden:
            funktion = vorhandene.pop(info.name, None)
            if funktion is None:
                funktion = Funktion(
                    name=info.name,
                    recht=rechte.get(info.name) or self._empfohlenes_recht(manifest, info, viele),
                )
                integration.funktionen.append(funktion)
            elif info.name in rechte:
                funktion.recht = rechte[info.name]
            funktion.beschreibung = info.beschreibung
            funktion.parameter = info.parameter
            funktion.schreibend = info.schreibend
            funktion.extra = info.extra
            funktion.vorhanden = True
        for funktion in vorhandene.values():
            funktion.vorhanden = False

    def _status_setzen(self, integration: Integration, ergebnis: TestErgebnis) -> None:
        self._status_uebernehmen(
            integration, STATUS_OK if ergebnis.ok else STATUS_FEHLER, ergebnis.meldung, ergebnis.hinweis or ""
        )

    def _status_uebernehmen(
        self, integration: Integration, status: str, meldung: str, hinweis: str = ""
    ) -> None:
        """Setzt den Status und meldet einen Ausfall bzw. die Rückkehr als Ereignis."""
        vorher = integration.status
        integration.status = status
        integration.status_meldung = meldung
        integration.status_hinweis = hinweis
        integration.geprueft = zeit.jetzt()
        if self.ereignis_melden is None or integration.id is None or not integration.aktiv:
            return
        daten = {"integration_id": integration.id, "kennung": integration.kennung}
        if status == STATUS_FEHLER and vorher != STATUS_FEHLER:
            self.ereignis_melden(
                "integration_ausgefallen",
                f"Integration „{integration.name}“ ist ausgefallen",
                meldung,
                dringlichkeit="hoch",
                quelle=integration.name,
                daten=daten,
            )
        elif status == STATUS_OK and vorher == STATUS_FEHLER:
            self.ereignis_melden(
                "integration_wieder_da",
                f"Integration „{integration.name}“ funktioniert wieder",
                meldung,
                quelle=integration.name,
                daten=daten,
            )

    async def anlegen(
        self,
        db: Session,
        *,
        manifest_id: str,
        name: str,
        konfig: dict[str, Any],
        rechte: dict[str, str] | None = None,
        test_id: str | None = None,
    ) -> Integration:
        """„Aktivieren“ im Assistenten: speichert die Integration samt Funktionen und Rechten."""
        eintrag = self.katalog.holen(manifest_id)
        manifest = eintrag.manifest
        adapter = self._adapter(manifest)
        name = name.strip() or manifest.name
        if not manifest.mehrfach and db.scalar(
            select(Integration).where(Integration.manifest_id == manifest_id)
        ):
            raise PanelFehler(
                409,
                f"„{manifest.name}“ ist bereits eingerichtet.",
                "Diese Integration gibt es nur einmal – unter „Integrationen“ lässt sie sich bearbeiten.",
            )
        gepruefte_rechte = self._rechte_pruefen(rechte)
        bereinigt = self._konfig_pruefen(db, manifest, konfig, vollstaendig=True)
        kennung = self._freie_kennung(db, manifest.kennung or kennung_aus_name(name))
        kontext = self._kontext(
            db, eintrag, name=name, kennung=kennung, konfig=bereinigt, zustand=None, integration_id=None
        )
        ergebnis = await self._ergebnis_fuer(db, eintrag, kontext, bereinigt, test_id)
        if not ergebnis.ok:
            raise PanelFehler(422, ergebnis.meldung, ergebnis.hinweis)

        zeitpunkt = zeit.jetzt()
        integration = Integration(
            manifest_id=manifest_id,
            name=name,
            kennung=kennung,
            konfig=bereinigt,
            zustand=ergebnis.zustand,
            aktiv=True,
            erstellt=zeitpunkt,
            geaendert=zeitpunkt,
        )
        self._status_setzen(integration, ergebnis)
        self._funktionen_abgleichen(integration, manifest, ergebnis.funktionen, gepruefte_rechte)
        db.add(integration)
        db.commit()
        eingerichtet = getattr(adapter, "eingerichtet", None)
        if eingerichtet is not None:
            # Manche Arten brauchen nach dem Speichern noch etwas (Geräte: Zugangsdaten am MQTT-Broker).
            # Was dabei nur einmal gezeigt werden darf, steht einmalig in der Antwort.
            try:
                integration.einmalig = await eingerichtet(db, integration, self.panel)
            except IntegrationsFehler as fehler:
                db.delete(integration)
                db.commit()
                raise PanelFehler(503, fehler.meldung, fehler.hinweis) from fehler
        return integration

    async def aendern(
        self,
        db: Session,
        integration_id: int,
        *,
        name: str | None = None,
        konfig: dict[str, Any] | None = None,
        aktiv: bool | None = None,
        rechte: dict[str, str] | None = None,
    ) -> Integration:
        integration = self.holen(db, integration_id)
        if name is not None and name.strip():
            integration.name = name.strip()
        if aktiv is not None:
            integration.aktiv = aktiv
        gepruefte_rechte = self._rechte_pruefen(rechte)
        for funktion in integration.funktionen:
            if funktion.name in gepruefte_rechte:
                funktion.recht = gepruefte_rechte[funktion.name]
        if konfig is not None:
            eintrag = self.katalog.holen(integration.manifest_id)
            integration.konfig = self._konfig_pruefen(
                db, eintrag.manifest, konfig, vollstaendig=True, bisher=integration.konfig
            )
            await self._testen_und_uebernehmen(db, integration, eintrag, gepruefte_rechte)
        integration.geaendert = zeit.jetzt()
        db.commit()
        return integration

    async def erneut_testen(self, db: Session, integration_id: int) -> Integration:
        integration = self.holen(db, integration_id)
        eintrag = self.katalog.holen(integration.manifest_id)
        await self._testen_und_uebernehmen(db, integration, eintrag, {})
        db.commit()
        return integration

    async def _testen_und_uebernehmen(
        self, db: Session, integration: Integration, eintrag: KatalogEintrag, rechte: dict[str, Recht]
    ) -> None:
        kontext = self._kontext(
            db,
            eintrag,
            name=integration.name,
            kennung=integration.kennung,
            konfig=integration.konfig,
            zustand=integration.zustand,
            integration_id=integration.id,
        )
        ergebnis = await self._test_ausfuehren(self._adapter(eintrag.manifest), kontext)
        self._status_setzen(integration, ergebnis)
        if ergebnis.ok:
            integration.zustand = ergebnis.zustand or integration.zustand
            self._funktionen_abgleichen(integration, eintrag.manifest, ergebnis.funktionen, rechte)

    async def alle_pruefen(self, db: Session) -> int:
        """Prüft die Verbindung aller aktiven Integrationen, die eine Gegenstelle haben – regelmässig,
        damit ein Ausfall auch dann auffällt, wenn Missa gerade nichts aufruft.

        Es ändert sich nur der Status (mit Ereignis bei Ausfall bzw. Rückkehr). Die Funktionsliste und
        die Rechte bleiben, wie sie sind: Neue Funktionen einer Gegenstelle kommen erst mit „Testen“ dazu.
        Gibt zurück, wie viele Integrationen geprüft wurden.
        """
        geprueft = 0
        nummern = list(db.scalars(select(Integration.id).where(Integration.aktiv)))
        for nummer in nummern:
            # Jede Prüfung kann einige Sekunden dauern. In der Zwischenzeit kann die Integration im Panel
            # entfernt oder ausgeschaltet worden sein – deshalb wird sie jedes Mal frisch gelesen.
            db.expire_all()
            integration = db.get(Integration, nummer)
            if integration is None or not integration.aktiv:
                continue
            eintrag = self.katalog.eintraege.get(integration.manifest_id)
            if eintrag is None or eintrag.manifest.art not in REGELMAESSIG_GEPRUEFT:
                continue
            try:
                kontext = self._kontext(
                    db,
                    eintrag,
                    name=integration.name,
                    kennung=integration.kennung,
                    konfig=integration.konfig,
                    zustand=integration.zustand,
                    integration_id=integration.id,
                )
                ergebnis = await self._test_ausfuehren(
                    self._adapter(eintrag.manifest), kontext, PRUEF_SEKUNDEN
                )
            except Exception:
                log.exception("Prüfung der Integration „%s“ fehlgeschlagen", integration.name)
                continue
            db.expire_all()
            integration = db.get(Integration, nummer)
            if integration is None or not integration.aktiv:
                continue  # während der Prüfung entfernt oder ausgeschaltet
            self._status_setzen(integration, ergebnis)
            db.commit()
            geprueft += 1
        return geprueft

    def entfernen(self, db: Session, integration_id: int) -> None:
        integration = self.holen(db, integration_id)
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        entfernt = getattr(self.adapter.get(eintrag.manifest.art), "entfernt", None) if eintrag else None
        if entfernt is not None:
            entfernt(db, integration, self.panel)  # z. B. den Zugang eines Geräts am MQTT-Broker löschen
        db.delete(integration)
        db.commit()

    def funktionen_uebernehmen(
        self, db: Session, integration: Integration, funktionen: list[FunktionsInfo]
    ) -> None:
        """Für Integrationen, die ihre Funktionen von sich aus melden (Geräte beim Start).

        Neue Funktionen bekommen das übliche Recht (lesend = erlaubt, schreibend = erst nachfragen);
        bereits eingestellte Rechte bleiben. Gespeichert wird mit dem nächsten `db.commit()`.
        """
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        if eintrag is not None:
            self._funktionen_abgleichen(integration, eintrag.manifest, funktionen, {})

    # ------------------------------------------------------------------ Funktionen aufrufen

    async def aufrufen(
        self, db: Session, integration: Integration, funktionsname: str, argumente: dict[str, Any] | None
    ) -> AufrufErgebnis:
        """Führt eine Funktion aus. Fehler kommen als `IntegrationsFehler` mit Meldung und Hinweis."""
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        if eintrag is None:
            raise IntegrationsFehler(
                f"Die Integration „{integration.name}“ ist nicht mehr im Katalog vorhanden.",
                "Wurde ihr Ordner gelöscht? Wieder hinzufügen oder die Integration entfernen.",
            )
        funktion = next((f for f in integration.funktionen if f.name == funktionsname and f.vorhanden), None)
        if funktion is None:
            raise IntegrationsFehler(
                f"Die Funktion „{funktionsname}“ gibt es bei „{integration.name}“ nicht (mehr).",
                "Unter „Integrationen“ erneut testen, damit die Funktionsliste aktualisiert wird.",
            )
        adapter = self.adapter.get(eintrag.manifest.art)
        if adapter is None:
            raise IntegrationsFehler(f"Für die Art „{eintrag.manifest.art}“ gibt es keinen Adapter.")
        kontext = self._kontext(
            db,
            eintrag,
            name=integration.name,
            kennung=integration.kennung,
            konfig=integration.konfig,
            zustand=integration.zustand,
            integration_id=integration.id,
        )
        zustand_vorher = copy.deepcopy(kontext.zustand)
        try:
            ergebnis = await adapter.aufrufen(kontext, funktion, dict(argumente or {}))
        except IntegrationsFehler:
            raise
        except Exception as fehler:
            # Kein „normaler“ Fehler der Funktion, sondern z. B. Gegenstelle nicht erreichbar:
            # das zeigt auch der Status der Integration.
            meldung, hinweis = fehler_erklaeren(fehler)
            log.warning("Aufruf %s.%s fehlgeschlagen: %s", integration.kennung, funktionsname, meldung)
            self._status_uebernehmen(integration, STATUS_FEHLER, meldung, hinweis or "")
            db.commit()
            raise IntegrationsFehler(meldung, hinweis) from fehler
        if kontext.zustand != zustand_vorher:
            integration.zustand = kontext.zustand
        if integration.status != STATUS_OK:
            self._status_uebernehmen(integration, STATUS_OK, "Letzter Aufruf erfolgreich.")
        db.commit()
        return ergebnis

    # ------------------------------------------------------------------ Telefonie-Adapter aus Integrationen

    def _telefon_modul(self, integration: Integration) -> tuple[KatalogEintrag, Any] | None:
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        if eintrag is None or eintrag.manifest.art != "python":
            return None
        try:
            modul = python_adapter.modul_laden(eintrag.ordner, eintrag.manifest.id)
        except IntegrationsFehler:
            return None
        return (eintrag, modul) if modul.telefon_anrufen is not None else None

    def telefon_adapter(self, db: Session) -> list[Integration]:
        """Aktive Integrationen, deren main.py einen Telefonie-Adapter mitbringt (`@telefon_anrufen`)."""
        aktive = db.scalars(
            select(Integration).where(Integration.aktiv).order_by(func.lower(Integration.name))
        )
        return [integration for integration in aktive if self._telefon_modul(integration) is not None]

    async def telefon_aufruf(self, db: Session, integration: Integration, was: str, *angaben: Any) -> Any:
        """Ruft `@telefon_anrufen` bzw. `@telefon_auflegen` einer Integration auf."""
        gefunden = self._telefon_modul(integration) if integration.aktiv else None
        if gefunden is None:
            raise IntegrationsFehler(
                f"Die Integration „{integration.name}“ steht als Telefonie-Adapter nicht (mehr) zur Verfügung.",
                "Unter „Anrufe“ einen anderen Adapter wählen oder die Integration wieder aktivieren.",
            )
        eintrag, modul = gefunden
        aufruf = modul.telefon_anrufen if was == "anrufen" else modul.telefon_auflegen
        if aufruf is None:
            return None  # Auflegen ist freiwillig
        kontext = self._kontext(
            db,
            eintrag,
            name=integration.name,
            kennung=integration.kennung,
            konfig=integration.konfig,
            zustand=integration.zustand,
            integration_id=integration.id,
        )
        try:
            return await python_adapter.ausfuehren(aufruf, kontext, *angaben)
        except IntegrationsFehler:
            raise
        except Exception as fehler:
            kontext.log.exception("Fehler im Telefonie-Adapter (%s)", was)
            meldung, hinweis = fehler_erklaeren(fehler)
            if meldung.startswith("Unerwarteter Fehler"):
                meldung = (
                    f"Fehler im Telefonie-Adapter „{integration.name}“: {type(fehler).__name__}: {fehler}"
                )
                hinweis = "Der Fehler kommt aus dem Code der Integration (main.py). Details stehen im Protokoll des Panels."
            raise IntegrationsFehler(meldung, hinweis) from fehler

    async def vorschau(
        self, db: Session, integration: Integration, funktionsname: str, argumente: dict[str, Any] | None
    ) -> str:
        """Ein Satz, was der Aufruf bewirken würde – für die Freigabe. Leer, wenn es keine Vorschau gibt.

        Steht schon fest, dass der Aufruf scheitert (z. B. weil es den Eintrag nicht gibt), kommt ein
        `IntegrationsFehler`: dann muss niemand über etwas entscheiden, das ohnehin nicht geht.
        """
        eintrag = self.katalog.eintraege.get(integration.manifest_id)
        funktion = next((f for f in integration.funktionen if f.name == funktionsname and f.vorhanden), None)
        adapter = self.adapter.get(eintrag.manifest.art) if eintrag else None
        vorschau = getattr(adapter, "vorschau", None)
        if eintrag is None or funktion is None or vorschau is None:
            return ""
        kontext = self._kontext(
            db,
            eintrag,
            name=integration.name,
            kennung=integration.kennung,
            konfig=integration.konfig,
            zustand=integration.zustand,
            integration_id=integration.id,
        )
        try:
            with anyio.fail_after(VORSCHAU_SEKUNDEN):
                text = await vorschau(kontext, funktion, dict(argumente or {}))
        except IntegrationsFehler:
            raise
        except PanelFehler as fehler:
            raise IntegrationsFehler(fehler.meldung, fehler.hinweis) from fehler
        except Exception:
            # Die Vorschau ist nur eine Hilfe: klappt sie nicht, wird ohne sie nachgefragt.
            log.exception("Vorschau für %s.%s fehlgeschlagen", integration.kennung, funktionsname)
            return ""
        return (text or "")[:500]

    # ------------------------------------------------------------------ Zugänge

    def zugang_verwendung(self, db: Session) -> dict[int, list[str]]:
        """Welche Integrationen welchen Zugang verwenden (Nummer des Zugangs → Namen)."""
        verwendung: dict[int, list[str]] = {}
        for integration in db.scalars(select(Integration)):
            eintrag = self.katalog.eintraege.get(integration.manifest_id)
            if eintrag is None:
                continue
            for feld in eintrag.manifest.felder:
                wert = (integration.konfig or {}).get(feld.name)
                if feld.typ == "zugang" and isinstance(wert, int):
                    verwendung.setdefault(wert, []).append(integration.name)
        return verwendung


def ergebnis_als_text(ergebnis: AufrufErgebnis) -> str:
    """Das Ergebnis eines Aufrufs als lesbarer Text (für die Oberfläche und für Missa)."""
    if ergebnis.mcp_inhalt is not None:
        teile = []
        for block in ergebnis.mcp_inhalt:
            text = getattr(block, "text", None)
            teile.append(text if isinstance(text, str) else f"[{getattr(block, 'type', 'Inhalt')}]")
        return "\n".join(teile)
    if isinstance(ergebnis.wert, str):
        return ergebnis.wert
    if ergebnis.wert is None:
        return "Erledigt."
    return json.dumps(ergebnis.wert, ensure_ascii=False, indent=2, default=str)
