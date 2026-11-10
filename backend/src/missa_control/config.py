"""Einstellungen des Panels – alle Werte kommen aus Umgebungsvariablen (siehe `.env.example`)."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

_INSTALL_HINWEIS = (
    "Bitte ./scripts/install.sh ausführen – das Skript erzeugt die Datei .env mit zufälligen Schlüsseln."
)


def _repo_ordner(name: str) -> Path | None:
    """Ordner im Repo (für den Start ohne Docker): backend/src/missa_control/ → drei Ebenen höher."""
    ordner = Path(__file__).resolve().parents[3] / name
    return ordner if ordner.is_dir() else None


def _vorhandener_ordner(pfad: str) -> Path | None:
    ordner = Path(pfad) if pfad.strip() else None
    return ordner if ordner is not None and ordner.is_dir() else None


def _port_aus(bind: str, standard: int) -> int:
    """„0.0.0.0:1883“ → 1883."""
    teil = bind.strip().rsplit(":", 1)[-1]
    return int(teil) if teil.isdigit() else standard


def _health_url(wert: str) -> str | None:
    return wert.strip() or None


class EinstellungsFehler(RuntimeError):
    """Eine Einstellung fehlt oder ist ungültig. Die Meldung sagt, was zu tun ist."""


@dataclass(frozen=True)
class Einstellungen:
    """Alle Einstellungen an einem Ort. Wird beim Start einmal aus der Umgebung gelesen."""

    secret_key: str
    encryption_key: str
    daten_ordner: Path
    frontend_ordner: Path | None = None
    # Ordner mit den eingebauten Integrationen (im Repo: integrations/).
    integrations_ordner: Path | None = None
    # Ordner mit Beispiel-Konfiguration (im Repo: config/).
    config_ordner: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8090
    # "auto": Cookie nur über HTTPS senden, wenn das Panel über HTTPS aufgerufen wird.
    cookie_secure: str = "auto"
    sitzung_stunden: int = 12
    max_fehlversuche: int = 5
    sperre_minuten: int = 15
    # So lange wartet ein „erst nachfragen“-Aufruf auf eine Entscheidung im Panel.
    freigabe_sekunden: float = 300.0
    # Protokoll, Ereignisse und entschiedene Freigaben werden nach so vielen Tagen gelöscht.
    aufbewahrung_tage: int = 30
    # Ereignis-Stream: so oft kommt ein Lebenszeichen; dabei wird auch geprüft, ob der Token noch gilt.
    stream_ping_sekunden: float = 15.0
    # Der Test-Chat auf der Seite „Charakter“ wartet höchstens so lange auf das Modell.
    testchat_sekunden: float = 120.0
    # Serverlast: Abstand der Messungen in Sekunden (0 = nicht automatisch messen).
    mess_intervall_sekunden: float = 30.0
    # /proc und /sys des Hosts, im Container nur lesend eingebunden (ausserhalb von Docker: unbenutzt).
    host_proc: Path | None = None
    host_sys: Path | None = None
    # Zeitzone für Uhrzeiten in Regeln und Ruhezeiten (das Panel selbst speichert alles in UTC).
    zeitzone: str = "Europe/Zurich"
    # Regeln: so oft wird der Zeitplan geprüft (Sekunden).
    regel_takt_sekunden: float = 10.0
    # Optional: Health-URL von missa-core. Das Panel fragt sie nur lesend ab (HTTP-GET) – sonst nichts.
    missa_core_health_url: str | None = None
    # So oft prüft das Panel missa-core und die Integrationen von sich aus (0 = nie). Im Betrieb alle
    # 20 Sekunden (siehe `aus_umgebung`): Zusammen mit der Übersicht, die alle 30 Sekunden nachfragt,
    # ist ein Ausfall so innerhalb einer Minute zu sehen.
    pruef_intervall_sekunden: float = 0.0
    # MQTT-Broker für Geräte (im Compose-Projekt: der Dienst „mqtt“). Leer = keine Geräte.
    mqtt_host: str = ""
    mqtt_port: int = 1883
    # Unter diesem Port erreichen die Geräte den Broker von aussen (aus MQTT_BIND, nur zur Anzeige).
    mqtt_port_aussen: int = 1883
    # Hier legt Mosquitto das Verwalter-Passwort ab (Standard: data/mosquitto/dynamic-security.json.pw).
    mqtt_passwort_datei_pfad: Path | None = None

    def __post_init__(self) -> None:
        if len(self.secret_key) < 32:
            raise EinstellungsFehler(
                "SECRET_KEY fehlt oder ist zu kurz (mindestens 32 Zeichen). " + _INSTALL_HINWEIS
            )
        try:
            schluessel = base64.urlsafe_b64decode(self.encryption_key.encode())
        except (binascii.Error, ValueError):
            schluessel = b""
        if len(schluessel) != 32:
            raise EinstellungsFehler(
                "ENCRYPTION_KEY fehlt oder ist ungültig (erwartet wird ein Fernet-Schlüssel). "
                + _INSTALL_HINWEIS
            )
        if self.cookie_secure not in ("auto", "ja", "nein"):
            raise EinstellungsFehler("MISSA_CONTROL_COOKIE_SECURE muss auto, ja oder nein sein.")
        if self.missa_core_health_url is not None and not self.missa_core_health_url.startswith(
            ("http://", "https://")
        ):
            raise EinstellungsFehler(
                "MISSA_CORE_HEALTH_URL muss mit http:// oder https:// beginnen – "
                "z. B. http://192.168.1.10:8000/health. Leer lassen, wenn missa-core nicht abgefragt werden soll."
            )
        try:
            ZoneInfo(self.zeitzone)
        except (KeyError, ValueError, OSError):
            raise EinstellungsFehler(
                f"MISSA_CONTROL_ZEITZONE: Die Zeitzone „{self.zeitzone}“ gibt es nicht. "
                "Erwartet wird ein Name wie Europe/Zurich oder Europe/Berlin."
            ) from None

    @property
    def datenbank_pfad(self) -> Path:
        return self.daten_ordner / "missa-control.db"

    @property
    def mqtt_passwort_datei(self) -> Path:
        return self.mqtt_passwort_datei_pfad or self.daten_ordner / "mosquitto" / "dynamic-security.json.pw"

    @property
    def eigene_integrationen_ordner(self) -> Path:
        """Hier liegen selbst geschriebene oder hochgeladene Integrationen."""
        return self.daten_ordner / "integrations"

    @classmethod
    def aus_umgebung(cls) -> Einstellungen:
        umgebung = os.environ
        frontend = umgebung.get("MISSA_CONTROL_FRONTEND_DIR", "").strip()
        integrationen = umgebung.get("MISSA_CONTROL_INTEGRATIONS_DIR", "").strip()
        config = umgebung.get("MISSA_CONTROL_CONFIG_DIR", "").strip()
        return cls(
            secret_key=umgebung.get("SECRET_KEY", "").strip(),
            encryption_key=umgebung.get("ENCRYPTION_KEY", "").strip(),
            daten_ordner=Path(umgebung.get("MISSA_CONTROL_DATA_DIR", "data")).resolve(),
            frontend_ordner=Path(frontend).resolve() if frontend else None,
            integrations_ordner=Path(integrationen).resolve()
            if integrationen
            else _repo_ordner("integrations"),
            config_ordner=Path(config).resolve() if config else _repo_ordner("config"),
            host_proc=_vorhandener_ordner(umgebung.get("MISSA_CONTROL_HOST_PROC", "/host/proc")),
            host_sys=_vorhandener_ordner(umgebung.get("MISSA_CONTROL_HOST_SYS", "/host/sys")),
            host=umgebung.get("MISSA_CONTROL_HOST", "127.0.0.1"),
            port=int(umgebung.get("MISSA_CONTROL_PORT", "8090")),
            cookie_secure=umgebung.get("MISSA_CONTROL_COOKIE_SECURE", "auto").strip().lower() or "auto",
            zeitzone=umgebung.get("MISSA_CONTROL_ZEITZONE", "").strip() or "Europe/Zurich",
            mqtt_host=umgebung.get("MISSA_CONTROL_MQTT_HOST", "").strip(),
            mqtt_port=int(umgebung.get("MISSA_CONTROL_MQTT_PORT", "1883")),
            mqtt_port_aussen=_port_aus(umgebung.get("MQTT_BIND", ""), 1883),
            missa_core_health_url=_health_url(umgebung.get("MISSA_CORE_HEALTH_URL", "")),
            pruef_intervall_sekunden=20.0,
        )
