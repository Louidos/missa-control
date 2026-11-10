"""Misst die Auslastung des Servers – ausschliesslich lesend.

- CPU, Arbeitsspeicher und Systemlast kommen über psutil aus dem `/proc` des Hosts
  (im Container nur lesend unter `/host/proc` eingebunden).
- Temperaturen kommen aus dem `/sys` des Hosts (nur lesend unter `/host/sys`).
- Der Speicherplatz ist der des Laufwerks, auf dem `data/` liegt.
- GPU-Werte liefert `nvidia-smi`, falls vorhanden. Fehlt es, gibt es einfach keine GPU-Werte.

Der Docker-Socket wird nie verwendet.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil

log = logging.getLogger(__name__)

GB = 1024**3
NVIDIA_ABFRAGE = (
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
    "--format=csv,noheader,nounits",
)


@dataclass
class Gpu:
    name: str
    auslastung: float | None
    speicher_belegt_mb: float | None
    speicher_gesamt_mb: float | None
    temperatur: float | None


@dataclass
class Messung:
    cpu: float
    ram: float
    speicher: float
    cpu_kerne: int = 0
    last: float | None = None
    ram_gesamt_gb: float = 0.0
    ram_belegt_gb: float = 0.0
    speicher_gesamt_gb: float = 0.0
    speicher_frei_gb: float = 0.0
    cpu_temp: float | None = None
    gpus: list[Gpu] = field(default_factory=list)

    @property
    def gpu(self) -> float | None:
        """Höchste Auslastung aller GPUs in Prozent."""
        werte = [gpu.auslastung for gpu in self.gpus if gpu.auslastung is not None]
        return max(werte) if werte else None

    @property
    def gpu_speicher(self) -> float | None:
        """Belegter GPU-Speicher in Prozent (über alle GPUs)."""
        belegt = sum(gpu.speicher_belegt_mb or 0 for gpu in self.gpus)
        gesamt = sum(gpu.speicher_gesamt_mb or 0 for gpu in self.gpus)
        return round(belegt / gesamt * 100, 1) if gesamt else None

    @property
    def gpu_temp(self) -> float | None:
        werte = [gpu.temperatur for gpu in self.gpus if gpu.temperatur is not None]
        return max(werte) if werte else None

    def werte(self) -> dict[str, float | None]:
        """Die Messwerte, die gespeichert werden und Regeln auslösen können."""
        return {
            "cpu": self.cpu,
            "ram": self.ram,
            "speicher": self.speicher,
            "last": self.last,
            "cpu_temp": self.cpu_temp,
            "gpu": self.gpu,
            "gpu_speicher": self.gpu_speicher,
            "gpu_temp": self.gpu_temp,
        }

    def ansicht(self) -> dict[str, Any]:
        return {**asdict(self), **self.werte(), "gpu_vorhanden": bool(self.gpus)}


def procfs_einstellen(host_proc: Path | None) -> None:
    """Lässt psutil das `/proc` des Hosts lesen, wenn es eingebunden ist."""
    if host_proc is not None and (host_proc / "stat").is_file():
        psutil.PROCFS_PATH = str(host_proc)


# Vergleichspunkt für die CPU-Auslastung „seit der letzten Messung“. Bewusst hier gehalten und nicht
# psutil überlassen: `psutil.cpu_percent()` merkt sich den Vergleichspunkt pro Thread – die Messungen
# laufen aber nicht immer im selben Thread und lieferten dann 0 % oder Werte über einen falschen Zeitraum.
_cpu_sperre = threading.Lock()
_cpu_vorher: Any = None


def _cpu_anteil(vorher: Any, jetzt: Any) -> float:
    """Anteil der Zeit zwischen zwei Zählerständen, in der die CPU gearbeitet hat (in Prozent)."""
    unterschied = {
        name: max(getattr(jetzt, name) - getattr(vorher, name, 0.0), 0.0) for name in jetzt._fields
    }
    # Unter Linux steckt die Gast-Zeit schon in „user“ bzw. „nice“ – nicht doppelt zählen.
    gesamt = sum(wert for name, wert in unterschied.items() if name not in ("guest", "guest_nice"))
    untaetig = unterschied.get("idle", 0.0) + unterschied.get("iowait", 0.0)
    return round((gesamt - untaetig) / gesamt * 100, 1) if gesamt > 0 else 0.0


def cpu_auslastung(intervall: float | None = None) -> float:
    """CPU-Auslastung in Prozent.

    Ohne `intervall`: seit dem letzten Aufruf dieser Art – egal aus welchem Thread (für den
    30-Sekunden-Takt). Mit `intervall`: über genau so viele Sekunden (für „jetzt gerade“); der
    Vergleichspunkt des 30-Sekunden-Takts bleibt davon unberührt.
    """
    global _cpu_vorher
    if intervall:
        vorher = psutil.cpu_times()
        time.sleep(intervall)
        return _cpu_anteil(vorher, psutil.cpu_times())
    with _cpu_sperre:
        vorher, _cpu_vorher = _cpu_vorher, psutil.cpu_times()
        return _cpu_anteil(vorher, _cpu_vorher) if vorher is not None else 0.0


def _systemlast() -> float | None:
    try:
        return float(Path(psutil.PROCFS_PATH, "loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def cpu_temperatur(host_sys: Path | None) -> float | None:
    """Höchste gemeldete Temperatur in °C – oder `None`, wenn es (wie in vielen VMs) keine Fühler gibt."""
    basis = host_sys if host_sys is not None and host_sys.is_dir() else Path("/sys")
    werte = []
    for datei in basis.glob("class/thermal/thermal_zone*/temp"):
        try:
            wert = int(datei.read_text().strip()) / 1000
        except (OSError, ValueError):
            continue
        if 0 < wert < 150:
            werte.append(wert)
    return round(max(werte), 1) if werte else None


def _zahl(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:  # z. B. "[N/A]"
        return None


def gpus_aus_ausgabe(ausgabe: str) -> list[Gpu]:
    """Liest die CSV-Ausgabe von nvidia-smi. Unlesbare Zeilen werden übersprungen."""
    gpus = []
    for zeile in ausgabe.strip().splitlines():
        teile = [teil.strip() for teil in zeile.split(",")]
        if len(teile) != 5 or not teile[0]:
            continue
        gpus.append(
            Gpu(
                name=teile[0],
                auslastung=_zahl(teile[1]),
                speicher_belegt_mb=_zahl(teile[2]),
                speicher_gesamt_mb=_zahl(teile[3]),
                temperatur=_zahl(teile[4]),
            )
        )
    return gpus


def gpus_messen() -> list[Gpu]:
    """GPU-Werte per nvidia-smi. Ohne nvidia-smi (oder bei einem Fehler) gibt es keine – ohne Fehlermeldung."""
    if shutil.which(NVIDIA_ABFRAGE[0]) is None:
        return []
    try:
        ergebnis = subprocess.run(NVIDIA_ABFRAGE, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return gpus_aus_ausgabe(ergebnis.stdout) if ergebnis.returncode == 0 else []


def messen(daten_ordner: Path, host_sys: Path | None = None, cpu_intervall: float | None = None) -> Messung:
    """Eine Messung. `cpu_intervall=None` vergleicht mit der vorigen Messung (für den 30-Sekunden-Takt)."""
    speicher_ram = psutil.virtual_memory()
    platte = psutil.disk_usage(str(daten_ordner if daten_ordner.exists() else Path("/")))
    return Messung(
        cpu=cpu_auslastung(cpu_intervall),
        cpu_kerne=psutil.cpu_count() or 0,
        last=_systemlast(),
        ram=round(speicher_ram.percent, 1),
        ram_gesamt_gb=round(speicher_ram.total / GB, 1),
        ram_belegt_gb=round((speicher_ram.total - speicher_ram.available) / GB, 1),
        speicher=round(platte.percent, 1),
        speicher_gesamt_gb=round(platte.total / GB, 1),
        speicher_frei_gb=round(platte.free / GB, 1),
        cpu_temp=cpu_temperatur(host_sys),
        gpus=gpus_messen(),
    )
