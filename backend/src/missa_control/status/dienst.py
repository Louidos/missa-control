"""Baut die Übersicht: Knoten (Missa, Clients, Rollen, Modelle, Integrationen, Geräte, Zugänge, Regeln)
und Kanten (was womit verbunden ist) – jeweils mit Status.

Status: ok (grün), warn (gelb: offene Freigabe oder Warnung), fehler (rot), grau (deaktiviert oder
nicht eingerichtet).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from missa_control.clients.modelle import Client
from missa_control.db import Datenbank
from missa_control.fehler import PanelFehler
from missa_control.gateway.modelle import FREIGABE_OFFEN, Freigabe
from missa_control.geraete.dienst import GeraeteDienst
from missa_control.geraete.modelle import Geraet
from missa_control.integrationen.dienst import IntegrationsDienst, gateway_name
from missa_control.integrationen.manifest import ART_NAMEN
from missa_control.integrationen.modelle import Integration
from missa_control.integrationen.typen import STATUS_FEHLER, STATUS_OK
from missa_control.modellverwaltung.modelle import Modell, Rolle
from missa_control.regeln.dienst import RegelDienst
from missa_control.regeln.modelle import Regel
from missa_control.status.missa_core import MissaCore
from missa_control.status.modelle import KnotenPosition
from missa_control.zugaenge.dienst import TYP_NAMEN
from missa_control.zugaenge.modelle import Zugang

log = logging.getLogger(__name__)

MISSA = "missa"
RECHT_NAMEN = {"erlaubt": "erlaubt", "nachfragen": "erst nachfragen", "gesperrt": "gesperrt"}
MAX_POSITIONEN = 500


def _zeit(wert: datetime | None) -> str | None:
    return wert.isoformat() if wert else None


def _detail(titel: str, wert: Any, *, zeit: bool = False) -> dict[str, Any]:
    """Eine Zeile für die Seitenleiste. `zeit`: der Wert ist ein Zeitpunkt (das Panel zeigt ihn in Ortszeit)."""
    return {"titel": titel, "wert": wert, "zeit": zeit}


class StatusDienst:
    def __init__(
        self,
        *,
        datenbank: Datenbank,
        integrationen: IntegrationsDienst,
        regeln: RegelDienst,
        geraete: GeraeteDienst,
        missa_core: MissaCore,
    ) -> None:
        self.datenbank = datenbank
        self.integrationen = integrationen
        self.regeln = regeln
        self.geraete = geraete
        self.missa_core = missa_core

    # ------------------------------------------------------------------ regelmässig prüfen

    async def pruefen(self) -> None:
        """Prüft missa-core (nur GET) und alle Integrationen mit Gegenstelle – damit ein Ausfall auch dann
        auffällt, wenn Missa gerade nichts aufruft."""
        await self.missa_core.pruefen()
        with self.datenbank.sitzung() as db:
            await self.integrationen.alle_pruefen(db)

    # ------------------------------------------------------------------ Übersicht

    def uebersicht(self, db: Session) -> dict[str, Any]:
        knoten: list[dict[str, Any]] = []
        kanten: list[dict[str, Any]] = []

        def kante(von: str, nach: str, art: str = "nutzt", ordnet: bool = True) -> None:
            # `ordnet`: zählt für die automatische Anordnung. Querverbindungen (Regel → Funktion) nicht.
            kanten.append(
                {"id": f"{von}>{nach}:{art}", "von": von, "nach": nach, "art": art, "ordnet": ordnet}
            )

        zugaenge_benutzt: dict[int, list[str]] = {}

        # ---------- Missa (missa-core)
        status, text = self.missa_core.stand()
        knoten.append(
            {
                "id": MISSA,
                "art": "missa",
                "name": "Missa",
                "untertitel": "missa-core",
                "status": status,
                "status_text": text,
                "details": [
                    _detail(
                        "Health-URL",
                        self.missa_core.health_url or "nicht eingestellt (MISSA_CORE_HEALTH_URL in .env)",
                    ),
                    _detail("Zuletzt geprüft", _zeit(self.missa_core.geprueft), zeit=True),
                    _detail(
                        "Antwortzeit",
                        f"{self.missa_core.antwort_ms} ms"
                        if self.missa_core.antwort_ms is not None
                        else None,
                    ),
                ],
                "hinweis": "Das Panel fragt missa-core nur lesend ab (HTTP-GET) und verändert dort nichts. "
                "Alles, was Missa braucht, holt missa-core selbst ab – siehe docs/anbindung-missa-core.md.",
                "link": {"pfad": "/clients", "titel": "Clients verwalten"},
            }
        )

        # ---------- Clients
        for client in db.scalars(
            select(Client).where(Client.widerrufen.is_(None)).order_by(func.lower(Client.name))
        ):
            gesehen = client.zuletzt_gesehen is not None
            knoten.append(
                {
                    "id": f"client:{client.id}",
                    "art": "client",
                    "name": client.name,
                    "untertitel": "Client",
                    "status": "ok" if gesehen else "grau",
                    "status_text": "Hat sich schon verbunden." if gesehen else "Hat sich noch nie verbunden.",
                    "details": [
                        _detail("Token beginnt mit", client.token_anfang),
                        _detail("Zuletzt gesehen", _zeit(client.zuletzt_gesehen), zeit=True),
                        _detail("Angelegt", _zeit(client.erstellt), zeit=True),
                    ],
                    "link": {"pfad": "/clients", "titel": "Clients verwalten"},
                }
            )
            kante(f"client:{client.id}", MISSA, "verbindet")

        # ---------- Modelle und Rollen
        modelle = {
            modell.id: modell for modell in db.scalars(select(Modell).order_by(func.lower(Modell.name)))
        }
        for modell in modelle.values():
            status = "grau" if modell.test_ok is None else ("ok" if modell.test_ok else "fehler")
            knoten.append(
                {
                    "id": f"modell:{modell.id}",
                    "art": "modell",
                    "name": modell.name,
                    "untertitel": modell.modellname,
                    "status": status,
                    "status_text": modell.test_meldung
                    or ("Noch nicht getestet." if modell.test_ok is None else ""),
                    "details": [
                        _detail("Adresse", modell.url),
                        _detail(
                            "Antwortzeit", f"{modell.test_ms} ms" if modell.test_ms is not None else None
                        ),
                        _detail("Zuletzt getestet", _zeit(modell.getestet), zeit=True),
                    ],
                    "hinweis": modell.test_hinweis or None,
                    "link": {"pfad": "/modelle", "titel": "Modelle verwalten"},
                }
            )
            if modell.zugang_id is not None:
                zugaenge_benutzt.setdefault(modell.zugang_id, []).append(modell.name)
                kante(f"modell:{modell.id}", f"zugang:{modell.zugang_id}", "zugang")
        for rolle in db.scalars(select(Rolle).order_by(Rolle.id)):
            haupt, ersatz = modelle.get(rolle.haupt_modell_id or 0), modelle.get(rolle.ersatz_modell_id or 0)
            if haupt is None:
                status, text = "grau", "Noch kein Modell zugewiesen."
            elif haupt.test_ok is None:
                status, text = "grau", f"„{haupt.name}“ ist noch nicht getestet."
            elif haupt.test_ok:
                status, text = "ok", f"Antwortet mit „{haupt.name}“."
            elif ersatz is not None and ersatz.test_ok:
                status, text = (
                    "warn",
                    f"„{haupt.name}“ ist gestört – das Ersatzmodell „{ersatz.name}“ springt ein.",
                )
            else:
                status, text = (
                    "fehler",
                    f"„{haupt.name}“ ist gestört und es gibt kein funktionierendes Ersatzmodell.",
                )
            knoten.append(
                {
                    "id": f"rolle:{rolle.kennung}",
                    "art": "rolle",
                    "name": rolle.name,
                    "untertitel": f"Rolle · missa-{rolle.kennung}",
                    "status": status,
                    "status_text": text,
                    "details": [
                        _detail("Hauptmodell", haupt.name if haupt else None),
                        _detail("Ersatzmodell", ersatz.name if ersatz else None),
                    ],
                    "link": {"pfad": "/modelle", "titel": "Rollen zuweisen"},
                }
            )
            kante(MISSA, f"rolle:{rolle.kennung}")
            if haupt is not None:
                kante(f"rolle:{rolle.kennung}", f"modell:{haupt.id}", "haupt")
            if ersatz is not None and ersatz is not haupt:
                kante(f"rolle:{rolle.kennung}", f"modell:{ersatz.id}", "ersatz")

        # ---------- Integrationen und Geräte
        offen: dict[str, int] = {}
        for name in db.scalars(select(Freigabe.integration_name).where(Freigabe.status == FREIGABE_OFFEN)):
            offen[name] = offen.get(name, 0) + 1
        geraete = {geraet.integration_id: geraet for geraet in db.scalars(select(Geraet))}
        funktion_gehoert: dict[str, str] = {}  # Name am Gateway → Knoten der Integration
        integrationen = db.scalars(
            select(Integration)
            .options(selectinload(Integration.funktionen))
            .order_by(func.lower(Integration.name))
        )
        for integration in integrationen:
            eintrag = self.integrationen.katalog.eintraege.get(integration.manifest_id)
            manifest = eintrag.manifest if eintrag else None
            geraet = geraete.get(integration.id)
            kennung = f"geraet:{integration.id}" if geraet is not None else f"integration:{integration.id}"
            funktionen = [
                {
                    "name": gateway_name(integration.kennung, funktion.name),
                    "beschreibung": funktion.beschreibung,
                    "recht": funktion.recht,
                    "recht_name": RECHT_NAMEN.get(funktion.recht, funktion.recht),
                    "schreibend": funktion.schreibend,
                }
                for funktion in integration.funktionen
                if funktion.vorhanden
            ]
            for funktion in funktionen:
                funktion_gehoert[funktion["name"]] = kennung
            wartend = offen.get(integration.name, 0)
            details = []
            hinweis = None
            if geraet is not None:
                status, text = self._geraet_status(integration, geraet)
                details = [
                    _detail("Firmware", geraet.firmware or None),
                    _detail("Zuletzt gesehen", _zeit(geraet.zuletzt_gesehen), zeit=True),
                    *[
                        _detail(f["name"], self._wert_text(f, (geraet.letzte or {}).get(f["id"])))
                        for f in geraet.faehigkeiten or []
                    ],
                ]
                link = {"pfad": "/geraete", "titel": "Zum Gerät"}
                untertitel = "Gerät"
            else:
                if not integration.aktiv:
                    status, text = "grau", "Deaktiviert."
                elif integration.status == STATUS_FEHLER:
                    status, text = "fehler", integration.status_meldung
                    hinweis = integration.status_hinweis or None
                elif integration.status == STATUS_OK:
                    status, text = "ok", integration.status_meldung
                else:
                    status, text = "grau", "Noch nicht getestet."
                sichtbar = sum(1 for funktion in funktionen if funktion["recht"] != "gesperrt")
                details = [
                    _detail(
                        "Art", ART_NAMEN.get(manifest.art, manifest.art) if manifest else "Vorlage fehlt"
                    ),
                    _detail(
                        "Funktionen für Missa", f"{sichtbar} von {len(funktionen)}" if funktionen else None
                    ),
                    _detail("Zuletzt geprüft", _zeit(integration.geprueft), zeit=True),
                ]
                link = {"pfad": "/integrationen", "titel": "Zur Integration"}
                untertitel = ART_NAMEN.get(manifest.art, manifest.art) if manifest else "Integration"
            if wartend and status in ("ok", "grau") and integration.aktiv:
                status = "warn"
                text = f"{wartend} Freigabe{'' if wartend == 1 else 'n'} wartet{'' if wartend == 1 else 'en'} auf deine Entscheidung."
                link = {"pfad": "/freigaben", "titel": "Zu den Freigaben"}
            knoten.append(
                {
                    "id": kennung,
                    "art": "geraet" if geraet is not None else "integration",
                    "name": integration.name,
                    "symbol": manifest.symbol if manifest else "",
                    "untertitel": untertitel,
                    "status": status,
                    "status_text": text,
                    "details": details,
                    "hinweis": hinweis,
                    "funktionen": funktionen,
                    "link": link,
                }
            )
            kante(MISSA, kennung)
            for feld in manifest.felder if manifest else []:
                wert = (integration.konfig or {}).get(feld.name)
                if feld.typ == "zugang" and isinstance(wert, int):
                    zugaenge_benutzt.setdefault(wert, []).append(integration.name)
                    kante(kennung, f"zugang:{wert}", "zugang")

        # ---------- Zugänge
        for zugang in db.scalars(select(Zugang).order_by(func.lower(Zugang.name))):
            benutzt = zugaenge_benutzt.get(zugang.id, [])
            knoten.append(
                {
                    "id": f"zugang:{zugang.id}",
                    "art": "zugang",
                    "name": zugang.name,
                    "untertitel": TYP_NAMEN.get(zugang.typ, zugang.typ),
                    "status": "ok" if benutzt else "grau",
                    "status_text": "Wird verwendet." if benutzt else "Wird von nichts verwendet.",
                    "details": [
                        _detail("Verwendet von", ", ".join(sorted(benutzt)) or None),
                        _detail("Geändert", _zeit(zugang.geaendert), zeit=True),
                    ],
                    "link": {"pfad": "/zugaenge", "titel": "Zugänge verwalten"},
                }
            )

        # ---------- Regeln
        vorhandene = {eintrag["id"] for eintrag in knoten}
        umfeld = self.regeln.umfeld(db)
        for regel in db.scalars(select(Regel).order_by(func.lower(Regel.name), Regel.id)):
            ansicht = self.regeln.ansicht(regel, umfeld)
            if not regel.aktiv:
                status, text = "grau", "Pausiert."
            elif ansicht["problem"]:
                status, text = "warn", ansicht["problem"]
            else:
                status, text = "ok", "Aktiv."
            knoten.append(
                {
                    "id": f"regel:{regel.id}",
                    "art": "regel",
                    "name": regel.name,
                    "untertitel": "Regel",
                    "status": status,
                    "status_text": text,
                    "details": [
                        _detail("Was sie tut", ansicht["satz"]),
                        _detail("Zuletzt ausgelöst", _zeit(regel.zuletzt_ausgeloest), zeit=True),
                        _detail("Angelegt von", "Missa" if regel.quelle == "missa" else "dir im Panel"),
                    ],
                    "link": {"pfad": "/regeln", "titel": "Regeln bearbeiten"},
                }
            )
            quelle = self._regel_quelle(regel.ausloeser or {})
            kante(quelle if quelle in vorhandene else MISSA, f"regel:{regel.id}", "ausloeser")
            ziel = funktion_gehoert.get(str((regel.aktion or {}).get("funktion", "")))
            if ziel is not None:
                kante(f"regel:{regel.id}", ziel, "aktion", ordnet=False)

        positionen = {
            position.knoten: {"x": position.x, "y": position.y}
            for position in db.scalars(select(KnotenPosition))
            if position.knoten in vorhandene or position.knoten.startswith("regel:")
        }
        zusammenfassung = dict.fromkeys(("ok", "warn", "fehler", "grau"), 0)
        for eintrag in knoten:
            zusammenfassung[eintrag["status"]] += 1
        # Kanten, deren Ende es nicht (mehr) gibt – etwa ein gelöschter Zugang –, werden nicht gezeichnet.
        alle = {eintrag["id"] for eintrag in knoten}
        return {
            "knoten": knoten,
            "kanten": [k for k in kanten if k["von"] in alle and k["nach"] in alle],
            "positionen": {kennung: ort for kennung, ort in positionen.items() if kennung in alle},
            "zusammenfassung": zusammenfassung,
        }

    def _geraet_status(self, integration: Integration, geraet: Geraet) -> tuple[str, str]:
        if not integration.aktiv:
            return "grau", "Deaktiviert."
        if geraet.mqtt_benutzer in self.geraete.ohne_zugang:
            return "warn", "Der Zugang am MQTT-Broker fehlt – neu koppeln."
        if self.geraete.probleme.get(integration.id):
            return "warn", self.geraete.probleme[integration.id]
        if geraet.status_seit is None:
            return "grau", "Wartet auf das Gerät – es hat sich noch nie gemeldet."
        return (
            ("ok", "Online.") if geraet.online else ("fehler", "Offline – das Gerät meldet sich nicht mehr.")
        )

    @staticmethod
    def _wert_text(faehigkeit: dict[str, Any], letzter: dict[str, Any] | None) -> str | None:
        if letzter is None:
            return None
        wert = letzter.get("wert")
        if faehigkeit.get("art") == "knopf":
            return "gedrückt"
        if faehigkeit.get("typ") == "schalter" and isinstance(wert, int | float):
            return "an" if wert else "aus"
        einheit = f" {faehigkeit['einheit']}" if faehigkeit.get("einheit") else ""
        return f"{wert:g}{einheit}" if isinstance(wert, int | float) else str(wert)

    @staticmethod
    def _regel_quelle(ausloeser: dict[str, Any]) -> str:
        """Der Knoten, von dem die Regel ausgelöst wird (sonst hängt sie direkt an Missa)."""
        art = ausloeser.get("art")
        if art == "geraet" and ausloeser.get("geraet_id") is not None:
            return f"geraet:{ausloeser['geraet_id']}"
        if art in ("webhook", "integration_ausgefallen") and ausloeser.get("integration_id") is not None:
            return f"integration:{ausloeser['integration_id']}"
        messwert = str(ausloeser.get("messwert", ""))
        if art == "messwert" and messwert.startswith("geraet."):
            return f"geraet:{messwert.split('.')[1]}"
        return MISSA

    # ------------------------------------------------------------------ Positionen

    def positionen_speichern(self, db: Session, positionen: Any) -> dict[str, Any]:
        """Merkt sich, wohin Knoten gezogen wurden. Was nicht mitkommt, bleibt, wie es ist."""
        if not isinstance(positionen, dict) or len(positionen) > MAX_POSITIONEN:
            raise PanelFehler(422, "Die Positionen sind ungültig.")
        for kennung, ort in positionen.items():
            x, y = (ort or {}).get("x"), (ort or {}).get("y") if isinstance(ort, dict) else (None, None)
            gueltig = all(
                isinstance(zahl, int | float) and not isinstance(zahl, bool) and abs(zahl) < 1_000_000
                for zahl in (x, y)
            )
            if not isinstance(kennung, str) or len(kennung) > 80 or not gueltig:
                raise PanelFehler(422, "Die Positionen sind ungültig.")
            vorhanden = db.get(KnotenPosition, kennung)
            if vorhanden is None:
                db.add(KnotenPosition(knoten=kennung, x=float(x), y=float(y)))
            else:
                vorhanden.x, vorhanden.y = float(x), float(y)
        db.commit()
        return {"gespeichert": len(positionen)}

    def positionen_loeschen(self, db: Session) -> dict[str, Any]:
        """Zurück zur automatischen Anordnung."""
        db.execute(delete(KnotenPosition))
        db.commit()
        return {"gespeichert": 0}
