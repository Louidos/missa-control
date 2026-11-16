"""Meldungen: Das Panel schickt von sich aus eine Nachricht an ntfy oder einen Webhook.

Der Dienst hängt als Zuhörer an den Ereignissen. Gesendet wird in einem eigenen Thread – ein
langsames oder nicht erreichbares Ziel hält deshalb weder Freigaben noch das Panel auf.

Schutz vor Flut, pro Ziel:
- dieselbe Meldung (gleiche Art und gleicher Titel) höchstens einmal pro Minute;
- mehr als 5 Meldungen in einer Minute werden zu einer einzigen zusammengefasst.

Meldungen enthalten nie Parameter eines Aufrufs (sie können Geheimnisse enthalten) – bei einer Freigabe
nur den Vorschau-Satz („was genau würde passieren“) und den Link zur Seite „Freigaben“. Erlauben und
Ablehnen geht weiterhin nur im Panel.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.fehler import PanelFehler
from missa_control.gateway.protokoll import ProtokollDienst
from missa_control.integrationen.fehlertexte import fehler_erklaeren, http_status_erklaeren
from missa_control.integrationen.kontext import auth_header
from missa_control.meldungen.modelle import MELDE_ARTEN, ZIEL_ARTEN, Meldeziel
from missa_control.zugaenge.dienst import ZugangsDienst
from missa_control.zugaenge.modelle import Zugang
from missa_control.zugaenge.schwaerzen import SCHWAERZER

log = logging.getLogger(__name__)

SEKUNDEN_PRO_VERSUCH = 5.0
GLEICHE_MELDUNG_SEKUNDEN = 60.0
FENSTER_SEKUNDEN = 60.0
HOECHSTENS_PRO_FENSTER = 5
NTFY_PRIORITAET = {"niedrig": 2, "normal": 3, "hoch": 4, "dringend": 5}


@dataclass
class Meldung:
    art: str  # freigabe | integration | geraet_offline | regel_hoch | test
    titel: str
    text: str
    dringlichkeit: str = "normal"
    pfad: str = ""  # Seite im Panel, z. B. /freigaben
    daten: dict[str, Any] = field(default_factory=dict)


def meldung_aus_ereignis(ereignis: dict[str, Any]) -> Meldung | None:
    """Welche Ereignisse gemeldet werden – und wie die Meldung aussieht."""
    art = ereignis.get("art")
    daten = ereignis.get("daten") or {}
    titel = str(ereignis.get("titel") or "")
    if art == "freigabe":
        vorschau = str(daten.get("vorschau") or "").strip()
        funktion = str(daten.get("funktion") or "")
        text = vorschau or f"Missa möchte „{funktion}“ ausführen."
        return Meldung(
            "freigabe",
            f"Freigabe wartet: {funktion}",
            f"{text} – Bitte im Panel unter „Freigaben“ erlauben oder ablehnen.",
            "hoch",
            "/freigaben",
            {"freigabe_id": daten.get("freigabe_id"), "funktion": funktion},
        )
    if art in ("integration_ausgefallen", "integration_wieder_da"):
        return Meldung(
            "integration",
            titel,
            str(ereignis.get("nachricht") or ""),
            "hoch" if art == "integration_ausgefallen" else "normal",
            "/integrationen",
            {"integration_id": daten.get("integration_id"), "ereignis": art},
        )
    if art == "geraet" and daten.get("faehigkeit") == "offline":
        return Meldung(
            "geraet_offline",
            titel,
            str(ereignis.get("nachricht") or ""),
            "normal",
            "/geraete",
            {"geraet": daten.get("geraet")},
        )
    if art == "regel" and ereignis.get("dringlichkeit") in ("hoch", "dringend") and not daten.get("test"):
        return Meldung(
            "regel_hoch",
            titel,
            str(ereignis.get("nachricht") or ""),
            str(ereignis.get("dringlichkeit")),
            "/regeln",
            {"regel": daten.get("regel")},
        )
    return None


@dataclass
class _Fenster:
    beginn: float = 0.0
    gesendet: int = 0
    zurueckgehalten: list[str] = field(default_factory=list)


class MeldungsDienst:
    def __init__(
        self,
        datenbank: Datenbank,
        zugaenge: ZugangsDienst,
        protokoll: ProtokollDienst,
        *,
        starten: bool = True,
    ) -> None:
        self.datenbank = datenbank
        self.zugaenge = zugaenge
        self.protokoll = protokoll
        self._schlange: queue.Queue[Meldung | None] = queue.Queue(maxsize=1000)
        self._zuletzt: dict[tuple[int, str, str], float] = {}
        self._fenster: dict[int, _Fenster] = {}
        self._thread: threading.Thread | None = None
        self._uhr = time.monotonic
        self._starten = starten

    # ------------------------------------------------------------------ Ereignisse empfangen

    def zuhoeren(self, ereignis: dict[str, Any]) -> None:
        """Zuhörer am Ereignis-Dienst: nimmt nur entgegen, gesendet wird im eigenen Thread."""
        meldung = meldung_aus_ereignis(ereignis)
        if meldung is None:
            return
        try:
            self._schlange.put_nowait(meldung)
        except queue.Full:
            log.warning("Zu viele Meldungen auf einmal – eine wurde verworfen")
        self._sicherstellen()

    def _sicherstellen(self) -> None:
        if not self._starten or (self._thread is not None and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._arbeiten, name="meldungen", daemon=True)
        self._thread.start()

    def stoppen(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._schlange.put(None)
            self._thread.join(timeout=10)

    def _arbeiten(self) -> None:
        while True:
            try:
                meldung = self._schlange.get(timeout=1.0)
            except queue.Empty:
                meldung = False  # type: ignore[assignment]
            if meldung is None:
                return
            try:
                if meldung:
                    self.verteilen(meldung)
                self._zusammenfassungen_senden()
            except Exception:
                log.exception("Fehler beim Senden einer Meldung")

    # ------------------------------------------------------------------ Verteilen mit Schutz vor Flut

    def verteilen(self, meldung: Meldung) -> None:
        with self.datenbank.sitzung() as db:
            ziele = [
                z
                for z in db.scalars(select(Meldeziel).where(Meldeziel.aktiv))
                if meldung.art in (z.arten or [])
            ]
            for ziel in ziele:
                jetzt = self._uhr()
                schluessel = (ziel.id, meldung.art, meldung.titel)
                if jetzt - self._zuletzt.get(schluessel, -1e9) < GLEICHE_MELDUNG_SEKUNDEN:
                    continue  # dieselbe Meldung kam gerade erst
                self._zuletzt[schluessel] = jetzt
                fenster = self._fenster.setdefault(ziel.id, _Fenster(beginn=jetzt))
                if jetzt - fenster.beginn >= FENSTER_SEKUNDEN:
                    self._zusammenfassung(db, ziel, fenster)
                    fenster.beginn, fenster.gesendet = jetzt, 0
                if fenster.gesendet >= HOECHSTENS_PRO_FENSTER:
                    fenster.zurueckgehalten.append(meldung.titel)
                    continue
                fenster.gesendet += 1
                self._senden_und_merken(db, ziel, meldung)

    def _zusammenfassungen_senden(self) -> None:
        """Ist ein Fenster abgelaufen, gehen die zurückgehaltenen Meldungen als eine einzige hinaus."""
        offen = [
            (ziel_id, fenster)
            for ziel_id, fenster in self._fenster.items()
            if fenster.zurueckgehalten and self._uhr() - fenster.beginn >= FENSTER_SEKUNDEN
        ]
        if not offen:
            return
        with self.datenbank.sitzung() as db:
            for ziel_id, fenster in offen:
                ziel = db.get(Meldeziel, ziel_id)
                if ziel is not None:
                    self._zusammenfassung(db, ziel, fenster)
                fenster.beginn, fenster.gesendet = self._uhr(), 0

    def _zusammenfassung(self, db: Session, ziel: Meldeziel, fenster: _Fenster) -> None:
        if not fenster.zurueckgehalten:
            return
        titel = fenster.zurueckgehalten
        fenster.zurueckgehalten = []
        liste = "\n".join(f"• {eintrag}" for eintrag in titel[:10])
        mehr = f"\n… und {len(titel) - 10} weitere" if len(titel) > 10 else ""
        self._senden_und_merken(
            db,
            ziel,
            Meldung(
                "zusammenfassung",
                f"{len(titel)} weitere Meldungen",
                f"In der letzten Minute kam noch mehr:\n{liste}{mehr}",
                "normal",
                "/protokoll",
            ),
        )

    def _senden_und_merken(self, db: Session, ziel: Meldeziel, meldung: Meldung) -> str | None:
        """Sendet und merkt sich das Ergebnis am Ziel. Gibt den Fehler zurück (oder `None`)."""
        start = time.monotonic()
        fehler = self._senden(db, ziel, meldung)
        if fehler:
            ziel.letzter_fehler = fehler
            ziel.letzter_fehler_zeit = zeit.jetzt()
            self.protokoll.eintragen(
                quelle="meldung",
                client_name="Meldungen",
                integration_name=ziel.name,
                funktion=f"meldung_{ziel.art}",
                ok=False,
                fehler=fehler,
                dauer_ms=int((time.monotonic() - start) * 1000),
            )
        else:
            ziel.letzter_fehler = ""
            ziel.letzter_fehler_zeit = None
            ziel.zuletzt_gesendet = zeit.jetzt()
        db.commit()
        return fehler

    # ------------------------------------------------------------------ Senden

    def _senden(self, db: Session, ziel: Meldeziel, meldung: Meldung) -> str | None:
        link = ziel.panel_adresse.rstrip("/") + meldung.pfad if ziel.panel_adresse and meldung.pfad else ""
        headers: dict[str, str] = {}
        if ziel.zugang_id is not None:
            try:
                headers.update(auth_header(self.zugaenge.klartext(db, ziel.zugang_id)))
            except PanelFehler as fehler:
                return SCHWAERZER.schwaerzen(fehler.meldung)
        titel = SCHWAERZER.schwaerzen(meldung.titel)[:200]
        text = SCHWAERZER.schwaerzen(meldung.text)[:2000]
        if ziel.art == "ntfy":
            url = ziel.adresse.rstrip("/") + "/"
            inhalt: dict[str, Any] = {
                "topic": ziel.thema,
                "title": titel,
                "message": text,
                "priority": NTFY_PRIORITAET.get(meldung.dringlichkeit, 3),
                "tags": ["missa"],
            }
            if link:
                inhalt["click"] = link
        else:
            url = ziel.adresse
            inhalt = {
                "quelle": "missa-control",
                "art": meldung.art,
                "titel": titel,
                "nachricht": text,
                "dringlichkeit": meldung.dringlichkeit,
                "zeit": zeit.jetzt().isoformat(),
                "link": link or None,
                "daten": meldung.daten,
            }
        try:
            with httpx2.Client(
                timeout=httpx2.Timeout(SEKUNDEN_PRO_VERSUCH), follow_redirects=False
            ) as client:
                antwort = client.post(url, json=inhalt, headers=headers)
        except Exception as fehler:
            meldung_text, hinweis = fehler_erklaeren(fehler)
            return meldung_text + (f" {hinweis}" if hinweis else "")
        if antwort.status_code >= 400:
            meldung_text, hinweis = http_status_erklaeren(antwort.status_code)
            return SCHWAERZER.schwaerzen(f"{meldung_text} {hinweis}")
        return None

    # ------------------------------------------------------------------ Verwalten

    def alle(self, db: Session) -> dict[str, Any]:
        return {
            "ziele": [self.ansicht(ziel) for ziel in db.scalars(select(Meldeziel).order_by(Meldeziel.name))],
            "arten": [
                {"wert": wert, "titel": titel, "standard": standard}
                for wert, (titel, standard) in MELDE_ARTEN.items()
            ],
        }

    @staticmethod
    def ansicht(ziel: Meldeziel) -> dict[str, Any]:
        return {
            "id": ziel.id,
            "name": ziel.name,
            "art": ziel.art,
            "adresse": ziel.adresse,
            "thema": ziel.thema,
            "zugang_id": ziel.zugang_id,
            "panel_adresse": ziel.panel_adresse,
            "arten": list(ziel.arten or []),
            "aktiv": ziel.aktiv,
            "letzter_fehler": ziel.letzter_fehler,
            "letzter_fehler_zeit": ziel.letzter_fehler_zeit.isoformat() if ziel.letzter_fehler_zeit else None,
            "zuletzt_gesendet": ziel.zuletzt_gesendet.isoformat() if ziel.zuletzt_gesendet else None,
        }

    def speichern(self, db: Session, daten: dict[str, Any], ziel_id: int | None = None) -> Meldeziel:
        ziel = self.holen(db, ziel_id) if ziel_id is not None else None
        name = str(daten.get("name") or "").strip()
        art = str(daten.get("art") or (ziel.art if ziel else ""))
        adresse = str(daten.get("adresse") or "").strip()
        thema = str(daten.get("thema") or "").strip()
        if not name:
            raise PanelFehler(422, "Bitte einen Namen angeben.", "Zum Beispiel „Handy“.")
        if art not in ZIEL_ARTEN:
            raise PanelFehler(422, "Unbekannte Art.", "Erlaubt: ntfy oder Webhook.")
        if not adresse.startswith(("http://", "https://")):
            raise PanelFehler(
                422,
                "Die Adresse ist ungültig.",
                "Sie muss mit http:// oder https:// beginnen, z. B. https://ntfy.sh",
            )
        if art == "ntfy" and not thema:
            raise PanelFehler(
                422, "Bitte das Thema angeben.", "Das Thema, das du in der ntfy-App abonniert hast."
            )
        arten = [a for a in daten.get("arten") or [] if a in MELDE_ARTEN]
        zugang_id = daten.get("zugang_id")
        if zugang_id is not None and db.get(Zugang, int(zugang_id)) is None:
            raise PanelFehler(422, "Der ausgewählte Zugang existiert nicht mehr.")
        if ziel is None:
            ziel = Meldeziel(erstellt=zeit.jetzt(), letzter_fehler="")
            db.add(ziel)
        ziel.name, ziel.art, ziel.adresse, ziel.thema = name, art, adresse, thema if art == "ntfy" else ""
        ziel.zugang_id = int(zugang_id) if zugang_id is not None else None
        ziel.panel_adresse = str(daten.get("panel_adresse") or ziel.panel_adresse or "").strip()
        ziel.arten = arten
        ziel.aktiv = bool(daten.get("aktiv", True))
        db.commit()
        return ziel

    @staticmethod
    def holen(db: Session, ziel_id: int) -> Meldeziel:
        ziel = db.get(Meldeziel, ziel_id)
        if ziel is None:
            raise PanelFehler(404, "Dieses Ziel gibt es nicht (mehr).")
        return ziel

    def loeschen(self, db: Session, ziel_id: int) -> None:
        db.delete(self.holen(db, ziel_id))
        db.commit()

    def testen(self, db: Session, ziel_id: int) -> dict[str, Any]:
        """„Test-Meldung senden“ – sofort, ohne Schutz vor Flut."""
        ziel = self.holen(db, ziel_id)
        fehler = self._senden_und_merken(
            db,
            ziel,
            Meldung(
                "test",
                "Test von Missa Control",
                "Wenn du das liest, kommen Meldungen an.",
                "normal",
                "/meldungen",
            ),
        )
        return {
            "ok": fehler is None,
            "meldung": fehler or "Die Test-Meldung wurde gesendet.",
            "ziel": self.ansicht(ziel),
        }
