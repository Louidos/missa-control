"""Verbindung des Panels zum eigenen MQTT-Broker (Mosquitto im Compose-Projekt „missa-control“).

Das Panel meldet sich als Verwalter an. Darüber
- empfängt es, was die Geräte melden (Themen `missa/geraete/#`),
- sendet es Befehle an Geräte und
- verwaltet es die Zugänge der Geräte (Dynamic-Security-Plugin von Mosquitto, Thema `$CONTROL/…`).

Das Verwalter-Passwort legt Mosquitto beim ersten Start selbst an und schreibt es in die Datei
`data/mosquitto/dynamic-security.json.pw`; von dort liest es das Panel.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from missa_control.zugaenge.schwaerzen import SCHWAERZER

log = logging.getLogger(__name__)

THEMEN = "missa/geraete"
VERWALTER = "admin"
_STEUERUNG = "$CONTROL/dynamic-security/v1"
_ANTWORT = _STEUERUNG + "/response"
WARTEN_SEKUNDEN = 5.0


class BrokerFehler(Exception):
    """Der MQTT-Broker ist nicht erreichbar oder hat einen Verwaltungsbefehl abgelehnt."""


class Broker:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        passwort_datei: Path,
        bei_nachricht: Callable[[str, bytes, bool], None],
        bei_verbunden: Callable[[], bool | None] | None = None,
    ) -> None:
        """`bei_verbunden` richtet eine frische Verbindung ein (Zugänge abgleichen). Erst danach gilt der
        Broker als `bereit`. Gibt es `False` zurück, baut der Broker die Verbindung gleich noch einmal
        neu auf – dann geht es beim Wiederverbinden weiter."""
        self.host, self.port = host, port
        self.passwort_datei = passwort_datei
        self.bei_nachricht = bei_nachricht
        self.bei_verbunden = bei_verbunden
        self.verbunden = False  # die Verbindung steht
        self.bereit = False  # … und ist eingerichtet: Geräte können gekoppelt und angesprochen werden
        self._unterbrochen = threading.Event()
        self._verbindung = 0  # zählt die Verbindungen: eine neue löst das Einrichten der alten ab
        # Warum es gerade keine Verbindung gibt – für die Anzeige auf der Seite „Geräte“.
        self.meldung = "Die Verbindung zum MQTT-Broker wird aufgebaut."
        self._client: mqtt.Client | None = None
        self._ende = threading.Event()
        self._thread: threading.Thread | None = None
        self._verwalten = threading.Lock()
        self._antworten: dict[str, tuple[threading.Event, list[dict[str, Any]]]] = {}

    # ------------------------------------------------------------------ Verbindung

    def _passwort(self) -> str | None:
        """Liest das Verwalter-Passwort, das Mosquitto beim ersten Start erzeugt hat (Zeile „admin <Passwort>“)."""
        try:
            for zeile in self.passwort_datei.read_text(encoding="utf-8").splitlines():
                name, _, passwort = zeile.partition(" ")
                if name == VERWALTER and passwort.strip():
                    SCHWAERZER.merken(passwort.strip())
                    return passwort.strip()
        except OSError:
            return None
        return None

    def starten(self) -> None:
        if self._thread is None:
            self._ende.clear()
            self._thread = threading.Thread(target=self._verbinden, name="mqtt-verbindung", daemon=True)
            self._thread.start()

    def stoppen(self) -> None:
        self._ende.set()
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.disconnect()
            client.loop_stop()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.verbunden = self.bereit = False

    def _verbinden(self) -> None:
        """Wartet, bis der Broker bereit ist, und verbindet sich. Danach hält paho die Verbindung selbst."""
        gemeldet = ""
        while not self._ende.is_set():
            passwort = self._passwort()
            if passwort is None:
                self.meldung = (
                    "Der MQTT-Broker hat noch kein Verwalter-Passwort angelegt "
                    f"(die Datei {self.passwort_datei.name} fehlt). Läuft der Dienst „mqtt“?"
                )
            else:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2, client_id=f"missa-control-{uuid.uuid4().hex[:8]}"
                )
                client.username_pw_set(VERWALTER, passwort)
                client.on_connect = self._verbunden
                client.on_disconnect = self._getrennt
                client.on_message = self._nachricht
                client.reconnect_delay_set(min_delay=1, max_delay=20)
                try:
                    client.connect(self.host, self.port, keepalive=30)
                except OSError as fehler:
                    self.meldung = f"Der MQTT-Broker ({self.host}:{self.port}) ist nicht erreichbar: {fehler}"
                else:
                    self._client = client
                    client.loop_start()
                    return
            if self.meldung != gemeldet:
                gemeldet = self.meldung
                log.warning("%s", self.meldung)
            self._ende.wait(2.0)

    def _verbunden(
        self, client: mqtt.Client, _daten: Any, _flags: Any, grund: Any, _eigenschaften: Any = None
    ) -> None:
        if getattr(grund, "is_failure", False):
            self.verbunden = self.bereit = False
            self.meldung = f"Der MQTT-Broker lehnt die Anmeldung des Panels ab ({grund})."
            log.warning("%s", self.meldung)
            # Wurde der Broker neu aufgesetzt, steht ein neues Passwort in der Datei.
            passwort = self._passwort()
            if passwort:
                client.username_pw_set(VERWALTER, passwort)
            return
        client.subscribe([(_ANTWORT, 1), (THEMEN + "/#", 1)])
        self._unterbrochen.clear()
        self._verbindung += 1
        self.verbunden, self.bereit = True, False
        self.meldung = "Die Verbindung zum MQTT-Broker wird eingerichtet."
        log.info("MQTT-Broker verbunden (%s:%s)", self.host, self.port)
        # In einem eigenen Thread: dort dürfen Verwaltungsbefehle gesendet und Antworten abgewartet werden.
        threading.Thread(
            target=self._einrichten, args=(self._verbindung,), name="mqtt-abgleich", daemon=True
        ).start()

    def _einrichten(self, verbindung: int) -> None:
        """Richtet die frische Verbindung ein. Klappt das nicht, wird es alle 5 Sekunden neu versucht."""
        while not self._ende.is_set() and self.verbunden and self._verbindung == verbindung:
            try:
                fertig = self.bei_verbunden() if self.bei_verbunden is not None else True
            except Exception as fehler:
                if not self.verbunden or self._verbindung != verbindung:
                    return  # die Verbindung ist inzwischen weg: beim Wiederverbinden geht es von vorn los
                self.meldung = f"Der MQTT-Broker ist verbunden, lässt sich aber nicht einrichten: {fehler}"
                log.warning("%s", self.meldung, exc_info=not isinstance(fehler, BrokerFehler))
                self._ende.wait(5.0)
                continue
            if fertig is not False and self.verbunden and self._verbindung == verbindung:
                self.bereit, self.meldung = True, "Verbunden."
                log.info("MQTT-Broker bereit: Geräte können sich verbinden")
            return

    def _getrennt(
        self, _client: mqtt.Client, _daten: Any, _flags: Any, grund: Any, _eigenschaften: Any = None
    ) -> None:
        if self.bereit and not self._ende.is_set():
            log.warning("Verbindung zum MQTT-Broker verloren (%s) – wird neu aufgebaut", grund)
        self.verbunden = self.bereit = False
        self.meldung = "Die Verbindung zum MQTT-Broker ist unterbrochen und wird neu aufgebaut."
        self._unterbrochen.set()
        for fertig, _ in list(self._antworten.values()):
            fertig.set()  # wer auf eine Antwort wartet, erfährt sofort, dass sie nicht mehr kommt

    def warte_auf_trennung(self, sekunden: float) -> bool:
        """Wartet, ob der Broker die Verbindung trennt (das tut er, wenn sich die eigenen Rechte ändern)."""
        return self._unterbrochen.wait(sekunden)

    def _nachricht(self, _client: mqtt.Client, _daten: Any, nachricht: mqtt.MQTTMessage) -> None:
        if nachricht.topic == _ANTWORT:
            self._antwort(nachricht.payload)
            return
        try:
            self.bei_nachricht(nachricht.topic, nachricht.payload, bool(nachricht.retain))
        except Exception:
            log.exception("Nachricht auf %s konnte nicht verarbeitet werden", nachricht.topic)

    # ------------------------------------------------------------------ senden

    def senden(self, thema: str, inhalt: str, *, behalten: bool = False) -> None:
        client = self._client
        if client is None or not self.verbunden:
            raise BrokerFehler(self.meldung)
        client.publish(thema, inhalt, qos=1, retain=behalten)

    # ------------------------------------------------------------------ Zugänge verwalten

    def _antwort(self, inhalt: bytes) -> None:
        try:
            antworten = json.loads(inhalt).get("responses", [])
        except (ValueError, AttributeError):
            return
        kennung = next((a.get("correlationData") for a in antworten if a.get("correlationData")), None)
        wartend = self._antworten.get(str(kennung))
        if wartend is not None:
            wartend[1].extend(antworten)
            wartend[0].set()

    def verwalten(self, *kommandos: dict[str, Any], duldet: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """Schickt Verwaltungsbefehle an den Broker und wartet auf die Antwort.

        `duldet`: Fehlertexte, die kein Problem sind (z. B. „Client not found“ beim Aufräumen).
        """
        client = self._client
        if client is None or not self.verbunden:
            raise BrokerFehler(self.meldung)
        kennung = uuid.uuid4().hex
        fertig = threading.Event()
        antworten: list[dict[str, Any]] = []
        with self._verwalten:
            self._antworten[kennung] = (fertig, antworten)
            try:
                befehle = [{**kommando, "correlationData": kennung} for kommando in kommandos]
                client.publish(_STEUERUNG, json.dumps({"commands": befehle}), qos=1)
                if not fertig.wait(WARTEN_SEKUNDEN):
                    raise BrokerFehler("Der MQTT-Broker hat auf einen Verwaltungsbefehl nicht geantwortet.")
                if not antworten:
                    raise BrokerFehler(
                        "Die Verbindung zum MQTT-Broker wurde während eines Verwaltungsbefehls unterbrochen."
                    )
            finally:
                self._antworten.pop(kennung, None)
        for antwort in antworten:
            fehler = antwort.get("error")
            if fehler and not any(text.lower() in str(fehler).lower() for text in duldet):
                raise BrokerFehler(f"Der MQTT-Broker meldet bei „{antwort.get('command')}“: {fehler}")
        return antworten
