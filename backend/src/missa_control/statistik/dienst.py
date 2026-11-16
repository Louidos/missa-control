"""Berechnet die Nutzungs-Statistik aus dem Protokoll (Tabelle `aufrufe`) – ohne eigene Daten."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.gateway.modelle import Aufruf
from missa_control.gateway.server import sichtbare_funktionen

ZEITRAEUME = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


class StatistikDienst:
    def __init__(self, zeitzone: str = "Europe/Zurich") -> None:
        self.zeitzone = ZoneInfo(zeitzone)

    def berechnen(self, db: Session, zeitraum: str) -> dict[str, Any]:
        jetzt = zeit.jetzt()
        seit = jetzt - ZEITRAEUME[zeitraum]
        im_zeitraum = Aufruf.zeit >= seit

        zahl = func.count()
        fehler = func.sum(case((Aufruf.ok.is_(False), 1), else_=0))

        def freigabe(wert: str) -> Any:
            return func.sum(case((Aufruf.freigabe == wert, 1), else_=0))

        zeilen = db.execute(
            select(
                Aufruf.integration_name,
                Aufruf.funktion,
                zahl,
                fehler,
                func.avg(Aufruf.dauer_ms),
                func.max(Aufruf.dauer_ms),
                func.max(Aufruf.zeit),
                func.sum(case((Aufruf.quelle == "gateway", 1), else_=0)),
                freigabe("erlaubt"),
                freigabe("abgelehnt"),
                freigabe("abgelaufen"),
            )
            .where(im_zeitraum)
            .group_by(Aufruf.integration_name, Aufruf.funktion)
        ).all()

        funktionen = []
        for (
            integration,
            name,
            anzahl,
            fehlgeschlagen,
            mittel,
            laengste,
            letzter,
            missa,
            erl,
            abg,
            abl,
        ) in zeilen:
            funktionen.append(
                {
                    "integration": integration or "",
                    "funktion": name,
                    "aufrufe": int(anzahl),
                    "von_missa": int(missa or 0),
                    "fehler": int(fehlgeschlagen or 0),
                    "fehlerquote": round(int(fehlgeschlagen or 0) / int(anzahl), 4) if anzahl else 0.0,
                    "dauer_mittel_ms": round(float(mittel or 0)),
                    "dauer_max_ms": int(laengste or 0),
                    "letzter_aufruf": letzter.isoformat() if letzter else None,
                    "freigaben": {
                        "erlaubt": int(erl or 0),
                        "abgelehnt": int(abg or 0),
                        "abgelaufen": int(abl or 0),
                    },
                }
            )
        funktionen.sort(key=lambda eintrag: (-eintrag["aufrufe"], eintrag["funktion"]))

        # Aufrufe pro Tag (nach Ortszeit), auch Tage ohne Aufruf
        tage: dict[date, dict[str, int]] = {}
        erster = seit.astimezone(self.zeitzone).date()
        letzter_tag = jetzt.astimezone(self.zeitzone).date()
        tag = erster
        while tag <= letzter_tag:
            tage[tag] = {"aufrufe": 0, "fehler": 0}
            tag += timedelta(days=1)
        for zeitpunkt, ok in db.execute(select(Aufruf.zeit, Aufruf.ok).where(im_zeitraum)):
            eintrag = tage.setdefault(zeitpunkt.astimezone(self.zeitzone).date(), {"aufrufe": 0, "fehler": 0})
            eintrag["aufrufe"] += 1
            eintrag["fehler"] += 0 if ok else 1

        # Nie benutzt: aktive Funktionen, die Missa sehen kann, ohne Aufruf im Zeitraum
        benutzt = {eintrag["funktion"] for eintrag in funktionen}
        nie = [
            {
                "integration": integration.name,
                "integration_id": integration.id,
                "funktion": name,
                "schreibend": funktion.schreibend,
                "recht": funktion.recht,
            }
            for name, integration, funktion in sichtbare_funktionen(db)
            if name not in benutzt
        ]

        gesamt = sum(eintrag["aufrufe"] for eintrag in funktionen)
        gesamt_fehler = sum(eintrag["fehler"] for eintrag in funktionen)
        return {
            "zeitraum": zeitraum,
            "seit": seit.isoformat(),
            "bis": jetzt.isoformat(),
            "gesamt": {
                "aufrufe": gesamt,
                "fehler": gesamt_fehler,
                "fehlerquote": round(gesamt_fehler / gesamt, 4) if gesamt else 0.0,
                "funktionen": len(funktionen),
            },
            "pro_tag": [{"tag": tag.isoformat(), **werte} for tag, werte in sorted(tage.items())],
            "funktionen": funktionen,
            "nie_benutzt": nie,
        }
