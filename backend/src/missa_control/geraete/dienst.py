"""Der Geräte-Dienst: koppeln, Meldungen der Geräte verarbeiten, Befehle senden, Verlauf führen.

Themen je Gerät (`<benutzer>` ist sein Benutzername am Broker):

    missa/geraete/<benutzer>/status              „online“ bzw. „offline“ (gemerkt; „offline“ als Last Will)
    missa/geraete/<benutzer>/faehigkeiten        JSON beim Start: was das Gerät kann (gemerkt)
    missa/geraete/<benutzer>/wert/<fähigkeit>    Messwert eines Sensors
    missa/geraete/<benutzer>/ereignis/<fähigkeit>  ein Knopf wurde gedrückt
    missa/geraete/<benutzer>/zustand/<fähigkeit>   aktueller Zustand eines Aktors (Rückmeldung)
    missa/geraete/<benutzer>/befehl/<fähigkeit>    Befehl des Panels an einen Aktor

Jedes Gerät darf nur unter seinen eigenen Themen senden und nur seine eigenen Befehle empfangen.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.fehler import PanelFehler
from missa_control.geraete.modelle import Geraet, GeraeteWert
from missa_control.geraete.mqtt import THEMEN, VERWALTER, Broker, BrokerFehler
from missa_control.integrationen.dienst import IntegrationsDienst, gateway_name
from missa_control.integrationen.modelle import Integration
from missa_control.integrationen.typen import FunktionsInfo, IntegrationsFehler
from missa_control.regeln.dienst import RegelDienst
from missa_control.zugaenge.schwaerzen import SCHWAERZER

log = logging.getLogger(__name__)

AUFBEWAHRUNG_TAGE = 7
SPEICHER_ABSTAND = timedelta(seconds=30)
BESTAETIGUNG_SEKUNDEN = 2.0
MAX_FAEHIGKEITEN = 32
ROLLE_BEFEHLE = "missa-control-befehle"
ARTEN = ("sensor", "knopf", "aktor")
# Zeitraum → (Dauer, Raster in Sekunden) – wie bei der Serverlast.
ZEITRAEUME: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 0),
    "24h": (timedelta(hours=24), 300),
    "7t": (timedelta(days=7), 1800),
}
_KENNUNG = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
_AN = ("an", "on", "ein", "true", "1")
_AUS = ("aus", "off", "false", "0")


def faehigkeiten_lesen(inhalt: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Prüft, was ein Gerät über sich meldet. Gibt (Firmware, Fähigkeiten) zurück oder löst ValueError aus."""
    try:
        daten = json.loads(inhalt)
    except ValueError:
        raise ValueError("Die Meldung ist kein gültiges JSON.") from None
    liste = daten.get("faehigkeiten") if isinstance(daten, dict) else daten
    if not isinstance(liste, list):
        raise ValueError("Es fehlt die Liste „faehigkeiten“.")
    gefunden: list[dict[str, Any]] = []
    for eintrag in liste[:MAX_FAEHIGKEITEN]:
        if not isinstance(eintrag, dict):
            raise ValueError("Jede Fähigkeit muss aus Angaben wie id und art bestehen.")
        kennung, art = str(eintrag.get("id", "")).strip().lower(), str(eintrag.get("art", "")).strip().lower()
        if not _KENNUNG.match(kennung):
            raise ValueError(f"Die Kennung „{eintrag.get('id')}“ ist ungültig (Kleinbuchstaben, Ziffern, _).")
        if art not in ARTEN:
            raise ValueError(f"Die Art „{eintrag.get('art')}“ gibt es nicht (erlaubt: sensor, knopf, aktor).")
        if any(kennung == vorhandene["id"] for vorhandene in gefunden):
            raise ValueError(f"Die Kennung „{kennung}“ kommt doppelt vor.")
        typ = str(eintrag.get("typ") or ("schalter" if art == "aktor" else "zahl")).strip().lower()
        if typ not in ("zahl", "schalter", "text"):
            raise ValueError(f"Den Typ „{eintrag.get('typ')}“ gibt es nicht (erlaubt: zahl, schalter, text).")
        faehigkeit: dict[str, Any] = {
            "id": kennung,
            "art": art,
            "name": str(eintrag.get("name") or kennung).strip()[:60],
            "typ": typ,
            "einheit": str(eintrag.get("einheit") or "").strip()[:12],
        }
        for grenze in ("min", "max"):
            if isinstance(eintrag.get(grenze), int | float) and not isinstance(eintrag.get(grenze), bool):
                faehigkeit[grenze] = eintrag[grenze]
        gefunden.append(faehigkeit)
    firmware = str(daten.get("firmware") or "")[:80] if isinstance(daten, dict) else ""
    return firmware, gefunden


def funktionen_aus(faehigkeiten: list[dict[str, Any]], geraet_name: str) -> list[FunktionsInfo]:
    """Aus den gemeldeten Fähigkeiten werden Funktionen für Missa: Sensoren lesen, Aktoren schalten."""
    funktionen: list[FunktionsInfo] = []
    for faehigkeit in faehigkeiten:
        kennung, name, typ = faehigkeit["id"], faehigkeit["name"], faehigkeit.get("typ", "zahl")
        einheit = f" (in {faehigkeit['einheit']})" if faehigkeit.get("einheit") else ""
        if faehigkeit["art"] == "sensor":
            funktionen.append(
                FunktionsInfo(
                    name=kennung,
                    beschreibung=f"Liest den aktuellen Wert von „{name}“{einheit} am Gerät „{geraet_name}“.",
                    schreibend=False,
                    extra={"faehigkeit": kennung, "aktion": "lesen"},
                )
            )
        elif faehigkeit["art"] == "aktor":
            if typ == "schalter":
                endung, parameter, was = (
                    "schalten",
                    {"an": {"type": "boolean", "description": "true = ein, false = aus"}},
                    "Schaltet",
                )
            elif typ == "zahl":
                zahl: dict[str, Any] = {"type": "number", "description": f"Neuer Wert{einheit}"}
                if "min" in faehigkeit:
                    zahl["minimum"] = faehigkeit["min"]
                if "max" in faehigkeit:
                    zahl["maximum"] = faehigkeit["max"]
                endung, parameter, was = "setzen", {"wert": zahl}, "Setzt"
            else:
                endung, parameter, was = (
                    "senden",
                    {"text": {"type": "string", "description": "Der Text für das Gerät"}},
                    "Sendet einen Text an",
                )
            funktionen.append(
                FunktionsInfo(
                    name=f"{kennung}_{endung}",
                    beschreibung=f"{was} „{name}“ am Gerät „{geraet_name}“.",
                    parameter={"type": "object", "properties": parameter, "required": list(parameter)},
                    schreibend=True,
                    extra={"faehigkeit": kennung, "aktion": endung},
                )
            )
    return funktionen


def _als_zahl(text: str) -> float | None:
    """„21.5“, „21,5“, {"wert": 21.5}, „an“/„aus“ → Zahl. Alles andere: `None`."""
    roh = text.strip()
    if roh.startswith("{"):
        try:
            inhalt = json.loads(roh)
        except ValueError:
            return None
        roh = str(inhalt.get("wert", "")) if isinstance(inhalt, dict) else ""
    klein = roh.lower()
    if klein in _AN:
        return 1.0
    if klein in _AUS:
        return 0.0
    try:
        zahl = float(roh.replace(",", "."))
    except ValueError:
        return None
    return zahl if zahl == zahl and abs(zahl) != float("inf") else None


def _zahl_text(wert: float) -> str:
    return f"{wert:.10g}"


def befehl_aus(faehigkeit: dict[str, Any], aktion: str, argumente: dict[str, Any]) -> str:
    """Der Befehl, der ans Gerät geht – oder eine verständliche Meldung, wenn die Angaben nicht passen."""
    if aktion == "schalten":
        an = argumente.get("an")
        if isinstance(an, str) and an.strip().lower() in (*_AN, *_AUS):
            an = an.strip().lower() in _AN
        if not isinstance(an, bool):
            raise IntegrationsFehler(
                f"Für „{faehigkeit['name']}“ fehlt die Angabe „an“.",
                "Erwartet wird an = true (einschalten) oder an = false (ausschalten).",
            )
        return "an" if an else "aus"
    if aktion == "setzen":
        wert = argumente.get("wert")
        if isinstance(wert, str):
            wert = _als_zahl(wert)
        if (
            isinstance(wert, bool)
            or not isinstance(wert, int | float)
            or wert != wert
            or abs(wert) == float("inf")
        ):
            raise IntegrationsFehler(
                f"Für „{faehigkeit['name']}“ fehlt die Angabe „wert“.", "Erwartet wird eine Zahl."
            )
        unten, oben = faehigkeit.get("min"), faehigkeit.get("max")
        if (unten is not None and wert < unten) or (oben is not None and wert > oben):
            bereich = " und ".join(
                teil
                for teil in (
                    f"mindestens {_zahl_text(unten)}" if unten is not None else "",
                    f"höchstens {_zahl_text(oben)}" if oben is not None else "",
                )
                if teil
            )
            raise IntegrationsFehler(
                f"{_zahl_text(wert)} passt nicht zu „{faehigkeit['name']}“.", f"Erlaubt ist {bereich}."
            )
        return _zahl_text(wert)
    text = argumente.get("text")
    if not isinstance(text, str) or not text.strip():
        raise IntegrationsFehler(f"Für „{faehigkeit['name']}“ fehlt die Angabe „text“.")
    return text[:500]


class GeraeteDienst:
    def __init__(
        self,
        *,
        einstellungen: Einstellungen,
        datenbank: Datenbank,
        ereignisse: EreignisDienst,
        integrationen: IntegrationsDienst,
        regeln: RegelDienst,
    ) -> None:
        self.datenbank = datenbank
        self.ereignisse = ereignisse
        self.integrationen = integrationen
        self.regeln = regeln
        self.port_aussen = einstellungen.mqtt_port_aussen
        self.broker: Broker | None = None
        if einstellungen.mqtt_host:
            self.broker = Broker(
                host=einstellungen.mqtt_host,
                port=einstellungen.mqtt_port,
                passwort_datei=einstellungen.mqtt_passwort_datei,
                bei_nachricht=self.nachricht,
                bei_verbunden=self.abgleichen,
            )
        # Geräte, deren Zugang am Broker fehlt (z. B. nach dem Zurücksetzen des Brokers): neu koppeln.
        self.ohne_zugang: set[str] = set()
        # Ungültige Meldungen eines Geräts – für die Anzeige auf der Seite „Geräte“.
        self.probleme: dict[int, str] = {}
        self._gespeichert: dict[tuple[int, str], datetime] = {}
        # Rückmeldungen der Aktoren (Thema …/zustand/…): gezählt, damit ein Befehl auf *seine* Bestätigung warten kann.
        self._rueckmeldung = threading.Condition()
        self._rueckmeldungen: dict[tuple[int, str], int] = {}

        # Regeln: Geräte als Auslöser, ihre Sensoren als Messwerte.
        regeln.geraete_quelle = self.geraete_namen
        regeln.geraete_meldungen = self.meldungen
        regeln.messwert_quellen.append(self.messwerte)

    # ------------------------------------------------------------------ Verbindung

    def starten(self) -> None:
        if self.broker is not None:
            self.broker.starten()

    def stoppen(self) -> None:
        if self.broker is not None:
            self.broker.stoppen()

    def bereit(self) -> Broker:
        """Der verbundene Broker – oder eine verständliche Meldung, warum es ihn gerade nicht gibt."""
        if self.broker is None:
            raise IntegrationsFehler(
                "Der MQTT-Broker für Geräte ist nicht eingerichtet.",
                "In der Datei .env muss COMPOSE_PROFILES=geraete stehen; danach ./scripts/install.sh ausführen.",
            )
        if not self.broker.bereit:
            raise IntegrationsFehler(
                "Der MQTT-Broker für Geräte ist gerade nicht erreichbar.",
                self.broker.meldung
                + " Prüfen mit: docker compose -p missa-control ps – starten mit: ./scripts/install.sh",
            )
        return self.broker

    def abgleichen(self) -> bool:
        """Nach dem Verbinden: aufräumen und feststellen, welchen Geräten der Zugang am Broker fehlt.

        Gibt `False` zurück, wenn der Broker die Verbindung gleich noch einmal neu aufbaut (einmalig beim
        allerersten Start) – dann läuft der Abgleich nach dem Wiederverbinden erneut.
        """
        broker = self.broker
        assert broker is not None
        broker.verwalten({"command": "deleteClient", "username": "democlient"}, duldet=("not found",))
        if self._befehle_erlauben(broker) and broker.warte_auf_trennung(3.0):
            return False
        antwort = broker.verwalten({"command": "listClients", "count": 10000})
        vorhandene = set((antwort[0].get("data") or {}).get("clients") or []) if antwort else set()
        with self.datenbank.sitzung() as db:
            bekannte = set(db.scalars(select(Geraet.mqtt_benutzer)))
        for verwaist in sorted(vorhandene - bekannte - {VERWALTER}):
            if verwaist.startswith("geraet-"):  # Zugang eines Geräts, das es im Panel nicht mehr gibt
                self._zugang_loeschen(broker, verwaist)
        self.ohne_zugang = bekannte - vorhandene
        return True

    @staticmethod
    def _befehle_erlauben(broker: Broker) -> bool:
        """Der Verwalter-Zugang darf von Haus aus nur verwalten und mitlesen. Damit das Panel Befehle an
        Geräte senden kann, bekommt er einmalig eine Rolle dafür (nur für die Befehls-Themen).

        Gibt zurück, ob die Rolle gerade eben vergeben wurde: Dann trennt der Broker die Verbindung des
        Verwalters kurz, damit das neue Recht gilt.
        """
        antwort = broker.verwalten({"command": "getClient", "username": VERWALTER})
        rollen = {
            rolle.get("rolename")
            for rolle in ((antwort[0].get("data") or {}).get("client") or {}).get("roles", [])
        }
        if ROLLE_BEFEHLE in rollen:
            return False
        broker.verwalten(
            {
                "command": "createRole",
                "rolename": ROLLE_BEFEHLE,
                "acls": [{"acltype": "publishClientSend", "topic": f"{THEMEN}/+/befehl/#", "allow": True}],
            },
            duldet=("already exists",),
        )
        broker.verwalten({"command": "addClientRole", "username": VERWALTER, "rolename": ROLLE_BEFEHLE})
        return True

    # ------------------------------------------------------------------ koppeln

    @staticmethod
    def _zugang_anlegen(broker: Broker, benutzer: str, passwort: str) -> None:
        basis = f"{THEMEN}/{benutzer}"
        broker.verwalten(
            {
                "command": "createRole",
                "rolename": benutzer,
                "acls": [
                    {"acltype": "publishClientSend", "topic": f"{basis}/#", "allow": True},
                    {"acltype": "subscribePattern", "topic": f"{basis}/befehl/#", "allow": True},
                ],
            },
            duldet=("already exists",),
        )
        broker.verwalten(
            {
                "command": "createClient",
                "username": benutzer,
                "password": passwort,
                "roles": [{"rolename": benutzer}],
            }
        )

    @staticmethod
    def _zugang_loeschen(broker: Broker, benutzer: str) -> None:
        broker.verwalten(
            {"command": "deleteClient", "username": benutzer},
            {"command": "deleteRole", "rolename": benutzer},
            duldet=("not found",),
        )

    def koppeln(self, db: Session, integration: Integration) -> dict[str, Any]:
        """Erzeugt (neue) Zugangsdaten für das Gerät. Das Passwort gibt es nur in dieser Antwort."""
        broker = self.bereit()
        passwort = secrets.token_urlsafe(18)
        SCHWAERZER.merken(passwort)
        geraet = db.get(Geraet, integration.id)
        try:
            if geraet is None:
                geraet = Geraet(
                    integration_id=integration.id,
                    mqtt_benutzer=f"geraet-{secrets.token_hex(4)}",
                    online=False,
                    firmware="",
                    faehigkeiten=[],
                    letzte={},
                )
                self._zugang_anlegen(broker, geraet.mqtt_benutzer, passwort)
                db.add(geraet)
            else:
                # Neu koppeln: altes Passwort ungültig machen (oder den Zugang neu anlegen, falls er fehlt).
                self._zugang_loeschen(broker, geraet.mqtt_benutzer)
                self._zugang_anlegen(broker, geraet.mqtt_benutzer, passwort)
        except BrokerFehler as fehler:
            raise IntegrationsFehler(
                "Die Zugangsdaten für das Gerät konnten nicht angelegt werden.", str(fehler)
            ) from fehler
        geraet.gekoppelt = zeit.jetzt()
        db.commit()
        self.ohne_zugang.discard(geraet.mqtt_benutzer)
        basis = f"{THEMEN}/{geraet.mqtt_benutzer}"
        return {
            "benutzer": geraet.mqtt_benutzer,
            "passwort": passwort,
            "port": self.port_aussen,
            "themen": {
                "basis": basis,
                "status": f"{basis}/status",
                "faehigkeiten": f"{basis}/faehigkeiten",
                "wert": f"{basis}/wert/<fähigkeit>",
                "ereignis": f"{basis}/ereignis/<fähigkeit>",
                "zustand": f"{basis}/zustand/<fähigkeit>",
                "befehl": f"{basis}/befehl/<fähigkeit>",
            },
        }

    def entkoppeln(self, db: Session, integration: Integration) -> None:
        """Das Gerät wird entfernt: sein Zugang am Broker ist damit sofort ungültig."""
        geraet = db.get(Geraet, integration.id)
        if geraet is None:
            return
        try:
            self._zugang_loeschen(self.bereit(), geraet.mqtt_benutzer)
        except (IntegrationsFehler, BrokerFehler):
            # Broker gerade nicht erreichbar: der verwaiste Zugang wird beim nächsten Verbinden gelöscht.
            log.warning(
                "Zugang von %s wird beim nächsten Verbinden mit dem Broker gelöscht", geraet.mqtt_benutzer
            )

    # ------------------------------------------------------------------ Meldungen der Geräte

    def nachricht(self, thema: str, inhalt: bytes, gemerkt: bool) -> None:
        """Verarbeitet eine Meldung eines Geräts (wird vom Broker-Thread aufgerufen)."""
        teile = thema.split("/")
        if len(teile) < 4 or "/".join(teile[:2]) != THEMEN or teile[3] == "befehl":
            return
        benutzer, art, kennung = teile[2], teile[3], teile[4] if len(teile) > 4 else ""
        text = inhalt.decode("utf-8", errors="replace").strip()
        messwert: tuple[str, float] | None = None
        with self.datenbank.sitzung() as db:
            geraet = db.scalar(select(Geraet).where(Geraet.mqtt_benutzer == benutzer))
            integration = db.get(Integration, geraet.integration_id) if geraet is not None else None
            if geraet is None or integration is None or not integration.aktiv:
                return
            jetzt = zeit.jetzt()
            if art == "status":
                self._status(geraet, integration, text.lower() == "online", jetzt)
            else:
                if not gemerkt:
                    geraet.zuletzt_gesehen = jetzt
                    self._status(geraet, integration, True, jetzt)  # wer etwas meldet, ist online
                if art == "faehigkeiten":
                    self._faehigkeiten(db, geraet, integration, inhalt)
                elif art in ("wert", "zustand") and kennung:
                    zahl = self._wert(db, geraet, kennung, text, jetzt)
                    if zahl is not None and art == "wert":
                        messwert = (f"geraet.{integration.id}.{kennung}", zahl)
                elif art == "ereignis" and kennung and not gemerkt:
                    self._ereignis(geraet, integration, kennung, text, jetzt)
            db.commit()
        if art == "zustand" and kennung and not gemerkt:
            with self._rueckmeldung:
                schluessel = (integration.id, kennung)
                self._rueckmeldungen[schluessel] = self._rueckmeldungen.get(schluessel, 0) + 1
                self._rueckmeldung.notify_all()
        if messwert is not None:
            self.regeln.messwerte_pruefen({messwert[0]: messwert[1]})

    def _status(self, geraet: Geraet, integration: Integration, online: bool, jetzt: datetime) -> None:
        if online:
            geraet.zuletzt_gesehen = jetzt
        if geraet.online == online and geraet.status_seit is not None:
            return
        erstes_mal = geraet.status_seit is None
        geraet.online, geraet.status_seit = online, jetzt
        if erstes_mal and not online:
            return  # hat sich noch nie gemeldet: „offline“ ist dann keine Neuigkeit
        self.ereignisse.melden(
            "geraet",
            f"Gerät „{integration.name}“ ist {'online' if online else 'offline'}",
            "Das Gerät hat sich verbunden." if online else "Das Gerät meldet sich nicht mehr.",
            quelle=integration.name,
            daten={
                "geraet_id": integration.id,
                "geraet": integration.name,
                "faehigkeit": "online" if online else "offline",
            },
        )

    def _faehigkeiten(self, db: Session, geraet: Geraet, integration: Integration, inhalt: bytes) -> None:
        try:
            firmware, faehigkeiten = faehigkeiten_lesen(inhalt)
        except ValueError as fehler:
            self.probleme[integration.id] = (
                f"Das Gerät meldet seine Fähigkeiten in einer ungültigen Form: {fehler}"
            )
            log.warning("Gerät „%s“: %s", integration.name, fehler)
            return
        self.probleme.pop(integration.id, None)
        if faehigkeiten == geraet.faehigkeiten and firmware == geraet.firmware:
            return
        geraet.faehigkeiten, geraet.firmware = faehigkeiten, firmware
        self.integrationen.funktionen_uebernehmen(
            db, integration, funktionen_aus(faehigkeiten, integration.name)
        )

    def _wert(self, db: Session, geraet: Geraet, kennung: str, text: str, jetzt: datetime) -> float | None:
        zahl = _als_zahl(text)
        geraet.letzte = {
            **(geraet.letzte or {}),
            kennung: {"wert": zahl if zahl is not None else text[:200], "zeit": jetzt.isoformat()},
        }
        schluessel = (geraet.integration_id, kennung)
        zuletzt = self._gespeichert.get(schluessel)
        if zahl is not None and (zuletzt is None or jetzt - zuletzt >= SPEICHER_ABSTAND or jetzt < zuletzt):
            self._gespeichert[schluessel] = jetzt
            db.add(
                GeraeteWert(integration_id=geraet.integration_id, faehigkeit=kennung, zeit=jetzt, wert=zahl)
            )
        return zahl

    def _ereignis(
        self, geraet: Geraet, integration: Integration, kennung: str, text: str, jetzt: datetime
    ) -> None:
        name = next((f["name"] for f in geraet.faehigkeiten or [] if f["id"] == kennung), kennung)
        geraet.letzte = {
            **(geraet.letzte or {}),
            kennung: {"wert": text[:200] or "gedrückt", "zeit": jetzt.isoformat()},
        }
        daten: dict[str, Any] = {
            "geraet_id": integration.id,
            "geraet": integration.name,
            "faehigkeit": kennung,
        }
        if text:
            daten["wert"] = text[:200]
        gewoehnlich = text.lower() in ("", "1", "gedrueckt", "gedrückt", "pressed", "press")
        self.ereignisse.melden(
            "geraet",
            f"Gerät „{integration.name}“: {name}",
            f"„{name}“ wurde gedrückt." if gewoehnlich else f"„{name}“ meldet: {text[:200]}",
            quelle=integration.name,
            daten=daten,
        )

    # ------------------------------------------------------------------ Funktionen für Missa

    def funktionen(self, db: Session, integration_id: int, name: str) -> list[FunktionsInfo]:
        geraet = db.get(Geraet, integration_id)
        return funktionen_aus(geraet.faehigkeiten or [], name) if geraet is not None else []

    def stand(self, db: Session, integration_id: int) -> str:
        """Ein Satz zum Zustand des Geräts – für „Testen“ unter „Integrationen“."""
        geraet = db.get(Geraet, integration_id)
        if geraet is None:
            return "Das Gerät ist noch nicht gekoppelt."
        if geraet.status_seit is None:
            return "Das Gerät hat sich noch nicht gemeldet."
        anzahl = len(geraet.faehigkeiten or [])
        zustand = "online" if geraet.online else "offline"
        return f"Das Gerät ist {zustand} – {anzahl} Fähigkeit{'' if anzahl == 1 else 'en'} gemeldet."

    def aufrufen(
        self, integration_id: int, name: str, extra: dict[str, Any], argumente: dict[str, Any]
    ) -> Any:
        """Führt eine Funktion eines Geräts aus: Sensor lesen bzw. Befehl an einen Aktor senden."""
        kennung, aktion = str(extra.get("faehigkeit", "")), str(extra.get("aktion", ""))
        with self.datenbank.sitzung() as db:
            geraet = db.get(Geraet, integration_id)
            if geraet is None:
                raise IntegrationsFehler(
                    "Das Gerät ist nicht gekoppelt.", "Auf der Seite „Geräte“ neu koppeln."
                )
            faehigkeit = next((f for f in geraet.faehigkeiten or [] if f["id"] == kennung), None)
            if faehigkeit is None:
                raise IntegrationsFehler(
                    f"Das Gerät „{name}“ kann „{kennung}“ nicht (mehr).",
                    "Unter „Integrationen“ auf „Testen“ klicken, damit die Funktionsliste aktualisiert wird.",
                )
            online, benutzer = geraet.online, geraet.mqtt_benutzer
            letzter = (geraet.letzte or {}).get(kennung)
        if aktion == "lesen":
            if letzter is None:
                raise IntegrationsFehler(
                    f"„{faehigkeit['name']}“ hat noch keinen Wert gemeldet.",
                    "Das Gerät sendet Werte in Abständen – kurz warten und erneut versuchen.",
                )
            antwort: dict[str, Any] = {
                "wert": letzter["wert"],
                "gemessen": letzter["zeit"],
                "geraet_online": online,
            }
            if faehigkeit.get("einheit"):
                antwort["einheit"] = faehigkeit["einheit"]
            if not online:
                antwort["hinweis"] = "Das Gerät ist offline – das ist der letzte gemeldete Wert."
            return antwort
        befehl = befehl_aus(faehigkeit, aktion, argumente)
        if not online:
            raise IntegrationsFehler(
                f"Das Gerät „{name}“ ist offline.", "Stromversorgung und WLAN des Geräts prüfen."
            )
        with self._rueckmeldung:
            bisher = self._rueckmeldungen.get((integration_id, kennung), 0)
        try:
            self.bereit().senden(f"{THEMEN}/{benutzer}/befehl/{kennung}", befehl)
        except BrokerFehler as fehler:
            raise IntegrationsFehler("Der Befehl konnte nicht gesendet werden.", str(fehler)) from fehler
        # Kurz warten, ob das Gerät den neuen Zustand zurückmeldet (Thema …/zustand/<fähigkeit>).
        with self._rueckmeldung:
            bestaetigt = self._rueckmeldung.wait_for(
                lambda: self._rueckmeldungen.get((integration_id, kennung), 0) > bisher,
                timeout=BESTAETIGUNG_SEKUNDEN,
            )
        if not bestaetigt:
            return f"Befehl „{befehl}“ an „{faehigkeit['name']}“ gesendet (das Gerät hat nicht bestätigt)."
        with self.datenbank.sitzung() as db:
            geraet = db.get(Geraet, integration_id)
            zustand = ((geraet.letzte or {}).get(kennung) or {}).get("wert") if geraet is not None else None
        return f"„{faehigkeit['name']}“ ist jetzt {_zustand_text(zustand, faehigkeit)}."

    def vorschau(
        self, integration_id: int, name: str, extra: dict[str, Any], argumente: dict[str, Any]
    ) -> str | None:
        """Der Satz für die Freigabe: was der Befehl am Gerät bewirken würde. Lesen braucht keinen.

        Passen die Angaben nicht, kommt ein `IntegrationsFehler` – dann wird gar nicht erst nachgefragt.
        """
        kennung, aktion = str(extra.get("faehigkeit", "")), str(extra.get("aktion", ""))
        if aktion == "lesen":
            return None
        with self.datenbank.sitzung() as db:
            geraet = db.get(Geraet, integration_id)
            faehigkeit = next(
                (
                    f
                    for f in (geraet.faehigkeiten if geraet is not None else None) or []
                    if f["id"] == kennung
                ),
                None,
            )
        if faehigkeit is None:
            return None  # der Aufruf selbst sagt dann, was fehlt
        befehl = befehl_aus(faehigkeit, aktion, argumente)
        wo = f"„{faehigkeit['name']}“ am Gerät „{name}“"
        if aktion == "schalten":
            return f"{wo} wird {'ein' if befehl == 'an' else 'aus'}geschaltet."
        if aktion == "setzen":
            einheit = f" {faehigkeit['einheit']}" if faehigkeit.get("einheit") else ""
            return f"{wo} wird auf {befehl.replace('.', ',')}{einheit} gesetzt."
        return f"An {wo} wird der Text „{befehl[:200]}“ gesendet."

    # ------------------------------------------------------------------ für die Regeln

    def _geraete(self, db: Session) -> list[tuple[Integration, Geraet]]:
        zeilen = db.execute(
            select(Integration, Geraet)
            .join(Geraet, Geraet.integration_id == Integration.id)
            .order_by(func.lower(Integration.name))
        )
        return [(integration, geraet) for integration, geraet in zeilen]

    def geraete_namen(self, db: Session) -> dict[int, str]:
        return {integration.id: integration.name for integration, _ in self._geraete(db)}

    def meldungen(self, db: Session) -> dict[int, list[tuple[str, str]]]:
        """Was ein Gerät melden kann – als Auswahl für den Auslöser „Gerät meldet etwas“."""
        ergebnis: dict[int, list[tuple[str, str]]] = {}
        for integration, geraet in self._geraete(db):
            knoepfe = [(f["id"], f["name"]) for f in geraet.faehigkeiten or [] if f["art"] == "knopf"]
            ergebnis[integration.id] = [*knoepfe, ("offline", "geht offline"), ("online", "kommt online")]
        return ergebnis

    def messwerte(self, db: Session) -> dict[str, tuple[str, str]]:
        """Die Sensoren aller Geräte als Messwerte für Schwellwert-Regeln."""
        return {
            f"geraet.{integration.id}.{f['id']}": (f"{integration.name}: {f['name']}", f.get("einheit", ""))
            for integration, geraet in self._geraete(db)
            for f in geraet.faehigkeiten or []
            if f["art"] == "sensor" and f.get("typ", "zahl") != "text"
        }

    # ------------------------------------------------------------------ für die Seite „Geräte“

    def uebersicht(self, db: Session) -> dict[str, Any]:
        geraete = []
        for integration, geraet in self._geraete(db):
            letzte = geraet.letzte or {}
            funktionen = {(f.extra or {}).get("faehigkeit"): f for f in integration.funktionen if f.vorhanden}
            geraete.append(
                {
                    "id": integration.id,
                    "name": integration.name,
                    "aktiv": integration.aktiv,
                    "online": bool(geraet.online and integration.aktiv),
                    "status_seit": geraet.status_seit.isoformat() if geraet.status_seit else None,
                    "zuletzt_gesehen": geraet.zuletzt_gesehen.isoformat() if geraet.zuletzt_gesehen else None,
                    "gekoppelt": geraet.gekoppelt.isoformat() if geraet.gekoppelt else None,
                    "firmware": geraet.firmware,
                    "mqtt_benutzer": geraet.mqtt_benutzer,
                    "zugang_fehlt": geraet.mqtt_benutzer in self.ohne_zugang,
                    "problem": self.probleme.get(integration.id),
                    "faehigkeiten": [
                        {
                            **faehigkeit,
                            "wert": (letzte.get(faehigkeit["id"]) or {}).get("wert"),
                            "zeit": (letzte.get(faehigkeit["id"]) or {}).get("zeit"),
                            # Name der Funktion für Missa (Sensoren und Aktoren) und ihr Recht.
                            "funktion": gateway_name(integration.kennung, funktionen[faehigkeit["id"]].name)
                            if faehigkeit["id"] in funktionen
                            else None,
                            "funktion_name": funktionen[faehigkeit["id"]].name
                            if faehigkeit["id"] in funktionen
                            else None,
                            "recht": funktionen[faehigkeit["id"]].recht
                            if faehigkeit["id"] in funktionen
                            else None,
                        }
                        for faehigkeit in geraet.faehigkeiten or []
                    ],
                }
            )
        broker = self.broker
        return {
            "broker": {
                "eingerichtet": broker is not None,
                "verbunden": bool(broker and broker.bereit),
                "meldung": broker.meldung if broker else "Der MQTT-Broker für Geräte ist nicht eingerichtet.",
                "port": self.port_aussen,
            },
            "geraete": geraete,
        }

    def verlauf(
        self, db: Session, integration_id: int, faehigkeit: str, zeitraum: str
    ) -> list[dict[str, Any]]:
        if zeitraum not in ZEITRAEUME:
            raise PanelFehler(422, "Unbekannter Zeitraum.", "Erlaubt sind 1h, 24h und 7t.")
        if db.get(Geraet, integration_id) is None:
            raise PanelFehler(404, "Dieses Gerät gibt es nicht (mehr).")
        dauer, raster = ZEITRAEUME[zeitraum]
        bedingung = (
            GeraeteWert.integration_id == integration_id,
            GeraeteWert.faehigkeit == faehigkeit,
            GeraeteWert.zeit >= zeit.jetzt() - dauer,
        )
        if raster == 0:
            zeilen = db.execute(
                select(GeraeteWert.zeit, GeraeteWert.wert).where(*bedingung).order_by(GeraeteWert.zeit)
            )
            return [{"zeit": zeitpunkt.isoformat(), "wert": wert} for zeitpunkt, wert in zeilen]
        fach = func.cast(func.strftime("%s", GeraeteWert.zeit), Integer) // raster
        zeilen = db.execute(
            select(fach, func.avg(GeraeteWert.wert)).where(*bedingung).group_by(fach).order_by(fach)
        )
        return [
            {"zeit": datetime.fromtimestamp(int(nummer) * raster, UTC).isoformat(), "wert": round(wert, 2)}
            for nummer, wert in zeilen
        ]

    def aufraeumen(self) -> int:
        """Löscht Messwerte, die älter als 7 Tage sind."""
        with self.datenbank.sitzung() as db:
            grenze = zeit.jetzt() - timedelta(days=AUFBEWAHRUNG_TAGE)
            ergebnis = db.execute(delete(GeraeteWert).where(GeraeteWert.zeit < grenze))
            db.commit()
            return ergebnis.rowcount or 0


def _zustand_text(wert: Any, faehigkeit: dict[str, Any]) -> str:
    if faehigkeit.get("typ") == "schalter" and isinstance(wert, int | float):
        return "an" if wert else "aus"
    einheit = f" {faehigkeit['einheit']}" if faehigkeit.get("einheit") else ""
    return f"{wert:g}{einheit}" if isinstance(wert, int | float) else str(wert)
