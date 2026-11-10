"""Prüfstand für die Pico-Beispiel-Firmware: lässt `examples/geraete/pico-micropython/main.py` am Rechner laufen.

Der Pico selbst fehlt hier – nachgebaut sind nur seine Anschlüsse (Knopf, LED, Temperaturfühler, WLAN)
und die Uhr von MicroPython. Alles andere ist echt: die Firmware-Datei aus dem Repo, die
MQTT-Bibliothek von MicroPython (`tests/micropython/umqtt_simple.py`) und der Broker.

Auch zum Ausprobieren ohne Hardware: Mit einer `config.py` aus dem Panel (Seite „Geräte“) läuft die
Firmware als „Gerät“ am Rechner und erscheint im Panel als online:

    uv run python tests/pico.py /pfad/zu/config.py
"""

from __future__ import annotations

import binascii
import contextlib
import importlib.util
import runpy
import socket
import struct
import sys
import threading
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
ORDNER = REPO / "examples" / "geraete" / "pico-micropython"
UMQTT = Path(__file__).resolve().parent / "micropython" / "umqtt_simple.py"


class Feierabend(BaseException):
    """Beendet die Endlosschleifen der Firmware (auf dem Pico laufen sie, bis der Strom weg ist)."""


class _Stecker:
    """Eine Netzwerkverbindung, wie MicroPython sie kennt: mit `read()` und `write()`."""

    def __init__(self) -> None:
        self.echt = socket.socket()
        self._wartet = True

    def connect(self, adresse: Any) -> None:
        self.echt.connect(adresse)

    def setblocking(self, wartet: bool) -> None:
        self._wartet = wartet

    def write(self, daten: Any, laenge: int | None = None) -> None:
        roh = daten.encode() if isinstance(daten, str) else bytes(daten)
        self.echt.sendall(roh if laenge is None else roh[:laenge])

    def read(self, anzahl: int) -> bytes | None:
        """Wartend: genau `anzahl` Bytes (weniger nur, wenn die Verbindung endet). Sonst: `None`, wenn nichts da ist."""
        if not self._wartet:
            self.echt.setblocking(False)
            try:
                return self.echt.recv(anzahl)
            except BlockingIOError:
                return None
            finally:
                self.echt.setblocking(True)
        daten = b""
        while len(daten) < anzahl:
            teil = self.echt.recv(anzahl - len(daten))
            if not teil:
                break
            daten += teil
        return daten

    def close(self) -> None:
        self.echt.close()


class _Pin:
    OUT, IN, PULL_UP = "OUT", "IN", "PULL_UP"

    def __init__(self, nummer: Any, _richtung: Any = None, zug: Any = None) -> None:
        self.nummer = nummer
        self.wert = 1 if zug == _Pin.PULL_UP else 0  # ein Eingang mit Pull-up liegt in Ruhe auf 1

    def value(self, neu: Any = None) -> int | None:
        if neu is None:
            return self.wert
        self.wert = 1 if neu else 0
        return None

    def on(self) -> None:
        self.wert = 1

    def off(self) -> None:
        self.wert = 0

    def toggle(self) -> None:
        self.wert ^= 1


class _Zeit:
    """Die Uhr von MicroPython (`ticks_ms` & Co.).

    Im Test wartet `sleep()` nicht wirklich und `sleep_ms()` nur kurz; mit `echt=True` läuft alles in Echtzeit.
    """

    def __init__(self, echt: bool = False) -> None:
        self.echt = echt
        self.ende = threading.Event()
        self.pausen: list[float] = []
        self.hoechstens_pausen: int | None = None

    def ticks_ms(self) -> int:
        return int(time.monotonic() * 1000)

    @staticmethod
    def ticks_add(ticks: int, mehr: int) -> int:
        return ticks + mehr

    @staticmethod
    def ticks_diff(a: int, b: int) -> int:
        return a - b

    def sleep_ms(self, millisekunden: int) -> None:
        if self.ende.is_set():
            raise Feierabend
        time.sleep((millisekunden if self.echt else min(millisekunden, 20)) / 1000)

    def sleep(self, sekunden: float) -> None:
        self.pausen.append(sekunden)
        if self.echt:
            self.ende.wait(sekunden)
        if self.ende.is_set() or (
            self.hoechstens_pausen is not None and len(self.pausen) >= self.hoechstens_pausen
        ):
            raise Feierabend


class PicoPruefstand:
    """Ein „Pico“ mit der Beispiel-Firmware aus dem Repo und der Konfiguration aus dem Panel."""

    def __init__(
        self,
        port: int,
        kopplung: dict[str, Any],
        *,
        lebenszeichen: int | None = None,
        passwort: str | None = None,
        wlan_passwort: str = "wlan-geheim",
        konfig: dict[str, Any] | None = None,
        echtzeit: bool = False,
    ) -> None:
        """`konfig`: eine fertige Konfiguration (Inhalt einer config.py aus dem Panel) statt der Test-Angaben."""
        self.zeit = _Zeit(echt=echtzeit)
        self.pins: dict[Any, _Pin] = {}
        self.grad = 21.5
        self.wlan_da = True
        self.wlan_verbunden = False
        self.stecker: list[_Stecker] = []
        self.melden: Any = print if echtzeit else (lambda *_: None)
        self._konfig = konfig or {
            "WLAN_NAME": "Heimnetz",
            "WLAN_PASSWORT": "wlan-geheim",
            "MQTT_HOST": "127.0.0.1",
            "MQTT_PORT": port,
            "MQTT_BENUTZER": kopplung["benutzer"],
            "MQTT_PASSWORT": passwort or kopplung["passwort"],
        }
        # Das nachgebaute WLAN lässt nur mit diesen Angaben herein.
        self._wlan = (
            (self._konfig["WLAN_NAME"], self._konfig["WLAN_PASSWORT"])
            if konfig
            else ("Heimnetz", wlan_passwort)
        )
        self.modul = self._laden()
        if lebenszeichen is not None:
            self.modul.LEBENSZEICHEN_SEKUNDEN = lebenszeichen

    @classmethod
    def aus_datei(cls, konfig_datei: Path) -> PicoPruefstand:
        """Die Firmware mit einer echten `config.py` aus dem Panel – in Echtzeit, wie auf dem Gerät."""
        konfig = {name: wert for name, wert in runpy.run_path(str(konfig_datei)).items() if name.isupper()}
        return cls(0, {}, konfig=konfig, echtzeit=True)

    # ------------------------------------------------------------------ nachgebaute Teile

    def _machine(self) -> types.ModuleType:
        pruefstand = self

        class Pin(_Pin):
            def __init__(self, nummer: Any, richtung: Any = None, zug: Any = None) -> None:
                super().__init__(nummer, richtung, zug)
                pruefstand.pins[nummer] = self

            def value(self, neu: Any = None) -> int | None:
                if neu is not None and self.nummer == "LED" and self.wert != (1 if neu else 0):
                    pruefstand.melden(f"Die LED ist jetzt {'an' if neu else 'aus'}.")
                return super().value(neu)

        class ADC:
            def __init__(self, kanal: int) -> None:
                assert kanal == 4, "der eingebaute Temperaturfühler des Pico hängt an Kanal 4"

            def read_u16(self) -> int:
                # Datenblatt: bei 27 °C liegen 0,706 V an, je Grad mehr 1,721 mV weniger.
                spannung = 0.706 - (pruefstand.grad - 27) * 0.001721
                return round(spannung * 65535 / 3.3)

        modul = types.ModuleType("machine")
        modul.Pin, modul.ADC = Pin, ADC  # type: ignore[attr-defined]
        return modul

    def _network(self) -> types.ModuleType:
        pruefstand = self

        class WLAN:
            def __init__(self, schnittstelle: Any) -> None:
                assert schnittstelle == "STA_IF"

            def active(self, _an: bool | None = None) -> bool:
                return True

            def isconnected(self) -> bool:
                return pruefstand.wlan_verbunden and pruefstand.wlan_da

            def connect(self, name: str, passwort: str) -> None:
                pruefstand.wlan_verbunden = (name, passwort) == pruefstand._wlan

        modul = types.ModuleType("network")
        modul.STA_IF, modul.WLAN = "STA_IF", WLAN  # type: ignore[attr-defined]
        return modul

    def _usocket(self) -> types.ModuleType:
        pruefstand = self

        def neuer_stecker() -> _Stecker:
            pruefstand.stecker.append(_Stecker())
            return pruefstand.stecker[-1]

        modul = types.ModuleType("usocket")
        modul.socket, modul.getaddrinfo = neuer_stecker, socket.getaddrinfo  # type: ignore[attr-defined]
        return modul

    def _config(self) -> types.ModuleType:
        """Die Muster-Konfiguration aus dem Repo, ausgefüllt mit den Daten aus dem Panel."""
        modul = types.ModuleType("config")
        exec((ORDNER / "config.beispiel.py").read_text(encoding="utf-8"), modul.__dict__)
        muster = {name for name in vars(modul) if name.isupper()}
        fehlend = set(self._konfig) - muster
        assert not fehlend, f"config.beispiel.py kennt {fehlend} nicht"
        vars(modul).update(self._konfig)
        return modul

    def _laden(self) -> types.ModuleType:
        """Lädt die MQTT-Bibliothek und die Firmware – mit den nachgebauten Teilen statt der echten."""
        fremd = {
            "machine": self._machine(),
            "network": self._network(),
            "config": self._config(),
            "usocket": self._usocket(),
            "ustruct": struct,
            "ubinascii": binascii,
        }
        vorher = {name: sys.modules.get(name) for name in (*fremd, "umqtt", "umqtt.simple")}
        sys.modules.update(fremd)
        try:
            for name, pfad in (("umqtt.simple", UMQTT), ("pico_firmware", ORDNER / "main.py")):
                if name == "umqtt.simple":
                    sys.modules["umqtt"] = types.ModuleType("umqtt")
                spec = importlib.util.spec_from_file_location(name, pfad)
                assert spec is not None and spec.loader is not None
                modul = importlib.util.module_from_spec(spec)
                if name == "umqtt.simple":
                    sys.modules[name] = modul
                spec.loader.exec_module(modul)
        finally:
            for name, altes in vorher.items():
                if altes is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = altes
        modul.time = self.zeit  # type: ignore[attr-defined]
        return modul

    # ------------------------------------------------------------------ bedienen

    @property
    def knopf(self) -> _Pin:
        return self.pins[self.modul.config.KNOPF_PIN]

    @property
    def led(self) -> _Pin:
        return self.pins["LED"]

    def knopf_druecken(self) -> None:
        self.knopf.wert = 0  # der Taster zieht den Eingang auf GND

    def knopf_loslassen(self) -> None:
        self.knopf.wert = 1

    @contextlib.contextmanager
    def laeuft(self) -> Iterator[None]:
        """Lässt die Firmware im Hintergrund laufen – wie auf dem Pico, wenn er Strom bekommt.

        Am Ende steht sie einfach still: keine Abmeldung, die Verbindung bleibt offen („Strom weg“).
        """
        fehler: list[BaseException] = []

        def schleife() -> None:
            try:
                self.modul.start()
            except Feierabend:
                pass
            except BaseException as geschehen:
                fehler.append(geschehen)

        self.zeit.ende.clear()
        faden = threading.Thread(target=schleife, name="pico-firmware", daemon=True)
        faden.start()
        try:
            yield
        finally:
            self.zeit.ende.set()
            faden.join(timeout=5)
            self.zeit.ende.clear()
        if fehler:
            raise fehler[0]

    def aufraeumen(self) -> None:
        for stecker in self.stecker:
            stecker.close()


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        print(
            "Aufruf: uv run python tests/pico.py /pfad/zu/config.py   (config.py aus dem Panel, Seite „Geräte“)"
        )
        raise SystemExit(2)
    pico = PicoPruefstand.aus_datei(Path(sys.argv[1]))
    print("Die Pico-Beispiel-Firmware läuft jetzt am Rechner (ohne echten Pico) und meldet sich beim Panel.")
    print("Eingabetaste = Knopf drücken · eine Zahl = Temperatur einstellen · q = Strom weg (beenden)")
    with pico.laeuft():
        for zeile in sys.stdin:
            eingabe = zeile.strip().replace(",", ".")
            if eingabe == "q":
                break
            if eingabe == "":
                pico.knopf_druecken()
                time.sleep(0.2)
                pico.knopf_loslassen()
                print("Knopf gedrückt.")
                continue
            try:
                pico.grad = float(eingabe)
                print(f"Temperatur ist jetzt {pico.grad} °C (wird mit der nächsten Messung gemeldet).")
            except ValueError:
                print("Nicht verstanden: Eingabetaste, eine Zahl oder q.")


if __name__ == "__main__":
    main()
