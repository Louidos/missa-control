"""Serverlast aufzeichnen (alle 30 s), 7 Tage aufbewahren und für Diagramme aufbereiten."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.fehler import PanelFehler
from missa_control.serverlast import messen as messung
from missa_control.serverlast.messen import Messung
from missa_control.serverlast.modelle import Messwert

log = logging.getLogger(__name__)

AUFBEWAHRUNG_TAGE = 7
# Kennung → (Titel, Einheit). Diese Messwerte stehen auch den Regeln als Auslöser zur Verfügung.
MESSWERTE: dict[str, tuple[str, str]] = {
    "cpu": ("CPU-Auslastung", "%"),
    "ram": ("Arbeitsspeicher", "%"),
    "speicher": ("Speicherplatz", "%"),
    "last": ("Systemlast (1 Minute)", ""),
    "cpu_temp": ("CPU-Temperatur", "°C"),
    "gpu": ("GPU-Auslastung", "%"),
    "gpu_speicher": ("GPU-Speicher", "%"),
    "gpu_temp": ("GPU-Temperatur", "°C"),
}
# Zeitraum → (Dauer, Raster in Sekunden): längere Zeiträume werden zu Mittelwerten zusammengefasst.
ZEITRAEUME: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 0),
    "24h": (timedelta(hours=24), 300),
    "7t": (timedelta(days=7), 1800),
}


class ServerlastDienst:
    def __init__(self, einstellungen: Einstellungen, datenbank: Datenbank) -> None:
        self.einstellungen = einstellungen
        self.datenbank = datenbank
        self.intervall = einstellungen.mess_intervall_sekunden
        messung.procfs_einstellen(einstellungen.host_proc)
        # Woher die Messung kommt – in Tests austauschbar.
        self.quelle: Callable[[float | None], Messung] = self._messen
        # Wird nach jeder aufgezeichneten Messung aufgerufen (z. B. von den Regeln).
        self.zuhoerer: list[Callable[[dict[str, float | None]], None]] = []
        self.letzte: Messung | None = None
        self._messen(None)  # erster Aufruf setzt nur den Vergleichspunkt für die CPU-Auslastung

    def _messen(self, cpu_intervall: float | None) -> Messung:
        return messung.messen(self.einstellungen.daten_ordner, self.einstellungen.host_sys, cpu_intervall)

    def messen(self) -> Messung:
        """Frische Messung (für „jetzt gerade“): misst die CPU über eine halbe Sekunde."""
        return self.quelle(0.5)

    def aufzeichnen(self) -> Messung:
        """Misst und speichert einen Wert im 30-Sekunden-Takt; informiert die Zuhörer."""
        aktuelle = self.quelle(None)
        with self.datenbank.sitzung() as db:
            db.add(Messwert(zeit=zeit.jetzt(), **aktuelle.werte()))
            db.commit()
        self.letzte = aktuelle
        for zuhoerer in list(self.zuhoerer):
            try:
                zuhoerer(aktuelle.werte())
            except Exception:
                log.exception("Fehler in einem Zuhörer der Serverlast")
        return aktuelle

    async def laufen(self) -> None:
        """Hintergrundaufgabe: misst, solange das Panel läuft."""
        while True:
            try:
                await asyncio.to_thread(self.aufzeichnen)
            except Exception:
                log.exception("Messung der Serverlast fehlgeschlagen")
            await asyncio.sleep(self.intervall)

    # ---------- für das Panel ----------

    def uebersicht(self, db: Session, zeitraum: str) -> dict[str, Any]:
        if zeitraum not in ZEITRAEUME:
            raise PanelFehler(422, "Unbekannter Zeitraum.", "Erlaubt sind 1h, 24h und 7t.")
        aktuell = self.letzte or self.messen()
        return {
            "aktuell": aktuell.ansicht(),
            "verlauf": self.verlauf(db, zeitraum),
            "zeitraum": zeitraum,
            "intervall_sekunden": self.intervall,
            "messwerte": [
                {"kennung": kennung, "titel": titel, "einheit": einheit}
                for kennung, (titel, einheit) in MESSWERTE.items()
            ],
        }

    @staticmethod
    def verlauf(db: Session, zeitraum: str) -> list[dict[str, Any]]:
        dauer, raster = ZEITRAEUME[zeitraum]
        seit = zeit.jetzt() - dauer
        spalten = [getattr(Messwert, kennung) for kennung in MESSWERTE]
        if raster == 0:
            zeilen = db.execute(
                select(Messwert.zeit, *spalten).where(Messwert.zeit >= seit).order_by(Messwert.zeit)
            )
            return [
                {"zeit": zeile[0].isoformat(), **dict(zip(MESSWERTE, zeile[1:], strict=True))}
                for zeile in zeilen
            ]
        # Ganzzahlige Division (//): alle Messungen eines Rasters fallen in dasselbe Fach.
        fach = func.cast(func.strftime("%s", Messwert.zeit), Integer) // raster
        zeilen = db.execute(
            select(fach, *(func.avg(spalte) for spalte in spalten))
            .where(Messwert.zeit >= seit)
            .group_by(fach)
            .order_by(fach)
        )
        return [
            {
                "zeit": datetime.fromtimestamp(int(zeile[0]) * raster, UTC).isoformat(),
                **{
                    kennung: (round(wert, 1) if wert is not None else None)
                    for kennung, wert in zip(MESSWERTE, zeile[1:], strict=True)
                },
            }
            for zeile in zeilen
        ]

    # ---------- für Missa ----------

    def fuer_missa(self) -> dict[str, Any]:
        """Antwort der Funktion `serverlast_aktuell`: Zahlen plus ein Satz zum Vorlesen."""
        m = self.messen()
        saetze = [
            f"CPU {m.cpu:.0f} % ausgelastet ({m.cpu_kerne} Kerne)",
            f"Arbeitsspeicher {m.ram:.0f} % belegt ({m.ram_belegt_gb:.1f} von {m.ram_gesamt_gb:.1f} GB)",
            f"Speicherplatz {m.speicher:.0f} % belegt ({m.speicher_frei_gb:.0f} GB frei)",
        ]
        if m.gpus:
            saetze.append(
                f"GPU {m.gpu or 0:.0f} % ausgelastet, GPU-Speicher {m.gpu_speicher or 0:.0f} % belegt"
            )
        ergebnis: dict[str, Any] = {
            "zusammenfassung": "; ".join(saetze) + ".",
            "cpu_prozent": m.cpu,
            "cpu_kerne": m.cpu_kerne,
            "systemlast_1min": m.last,
            "arbeitsspeicher_prozent": m.ram,
            "arbeitsspeicher_belegt_gb": m.ram_belegt_gb,
            "arbeitsspeicher_gesamt_gb": m.ram_gesamt_gb,
            "speicherplatz_prozent": m.speicher,
            "speicherplatz_frei_gb": m.speicher_frei_gb,
            "speicherplatz_gesamt_gb": m.speicher_gesamt_gb,
        }
        if m.cpu_temp is not None:
            ergebnis["cpu_temperatur_grad"] = m.cpu_temp
        if m.gpus:
            ergebnis["gpus"] = [
                {
                    "name": gpu.name,
                    "auslastung_prozent": gpu.auslastung,
                    "speicher_belegt_mb": gpu.speicher_belegt_mb,
                    "speicher_gesamt_mb": gpu.speicher_gesamt_mb,
                    "temperatur_grad": gpu.temperatur,
                }
                for gpu in m.gpus
            ]
        return ergebnis

    def aufraeumen(self) -> int:
        """Löscht Messwerte, die älter als 7 Tage sind."""
        with self.datenbank.sitzung() as db:
            grenze = zeit.jetzt() - timedelta(days=AUFBEWAHRUNG_TAGE)
            ergebnis = db.execute(delete(Messwert).where(Messwert.zeit < grenze))
            db.commit()
            return ergebnis.rowcount or 0
