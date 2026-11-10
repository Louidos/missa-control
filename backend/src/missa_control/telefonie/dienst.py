"""Der Telefonie-Dienst: Einstellungen, ausgehende und eingehende Anrufe, Verlauf.

Wer anrufen darf und wann, entscheidet immer das Panel – der Adapter führt nur aus:

- Ausgehend: Missa (über die Funktion `anrufen`, Standard „erst nachfragen“), Regeln (Aktion „Anrufen“)
  oder der Besitzer im Panel. In der Ruhezeit gehen nur dringende Anrufe durch.
- Eingehend: Nur eigene Nummern und erlaubte Anrufer erreichen Missa. Alle anderen werden abgewiesen
  und stehen im Verlauf.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.config import Einstellungen
from missa_control.db import Datenbank
from missa_control.ereignisse.dienst import EreignisDienst
from missa_control.ereignisse.modelle import DRINGLICHKEITEN
from missa_control.fehler import PanelFehler
from missa_control.integrationen.dienst import IntegrationsDienst
from missa_control.integrationen.modelle import Integration
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.regeln import pruefung
from missa_control.regeln.dienst import Anlass, RegelDienst
from missa_control.regeln.modelle import Regel
from missa_control.regeln.pruefung import AktionsArt, Umfeld
from missa_control.telefonie.adapter import Anrufauftrag, Anrufstart, TelefonAdapter, TestAdapter
from missa_control.telefonie.modelle import OFFEN, RICHTUNGEN, Anruf, TelefonieEinstellung
from missa_control.telefonie.nummern import landesvorwahl_pruefen, normalisieren

log = logging.getLogger(__name__)

MAX_NUMMERN = 50
MAX_RUHEZEITEN = 10
MAX_TEXT = 500
# Meldet ein Adapter das Ende eines Anrufs nie, gilt er nach dieser Zeit als abgeschlossen.
OHNE_RUECKMELDUNG = timedelta(hours=12)
STATUS_TEXT = {
    "wartet": "wird aufgebaut",
    "laeuft": "läuft",
    "beendet": "beendet",
    "nicht_erreicht": "nicht erreicht",
    "abgewiesen": "abgewiesen",
    "unterdrueckt": "nicht angerufen (Ruhezeit)",
    "fehler": "Fehler",
    "test": "Test – nur protokolliert",
}
_ERGEBNISSE = ("laeuft", "beendet", "nicht_erreicht", "test")


class IntegrationsAdapter(TelefonAdapter):
    """Ein Adapter, den eine Integration mitbringt (`@telefon_anrufen` in ihrer main.py)."""

    def __init__(
        self, integrationen: IntegrationsDienst, datenbank: Datenbank, integration: Integration
    ) -> None:
        self.integrationen = integrationen
        self.datenbank = datenbank
        self.integration_id = integration.id
        self.kennung = f"integration:{integration.id}"
        self.name = integration.name
        self.beschreibung = "Adapter aus einer Integration."

    async def _aufruf(self, was: str, *angaben: Any) -> Any:
        with self.datenbank.sitzung() as db:
            integration = db.get(Integration, self.integration_id)
            if integration is None:
                raise IntegrationsFehler("Die Integration des Telefonie-Adapters gibt es nicht mehr.")
            return await self.integrationen.telefon_aufruf(db, integration, was, *angaben)

    async def anrufen(self, auftrag: Anrufauftrag) -> Anrufstart | None:
        antwort = await self._aufruf("anrufen", auftrag)
        if isinstance(antwort, Anrufstart) or antwort is None:
            return antwort
        if isinstance(antwort, dict):
            dauer = antwort.get("dauer_sekunden")
            return Anrufstart(
                ergebnis=str(antwort.get("ergebnis") or "laeuft"),
                dauer_sekunden=int(dauer)
                if isinstance(dauer, int | float) and not isinstance(dauer, bool)
                else None,
                meldung=str(antwort.get("meldung") or ""),
            )
        return Anrufstart(meldung=str(antwort))

    async def auflegen(self, anruf_id: int) -> None:
        await self._aufruf("auflegen", anruf_id)


def _eintraege(roh: Any, was: str, landesvorwahl: str) -> list[dict[str, str]]:
    """Prüft eine Liste aus Nummer und Name. Jede Nummer kommt nur einmal vor."""
    if not isinstance(roh, list):
        raise PanelFehler(422, f"„{was}“ muss eine Liste sein.")
    if len(roh) > MAX_NUMMERN:
        raise PanelFehler(422, f"„{was}“: höchstens {MAX_NUMMERN} Einträge.")
    ergebnis: list[dict[str, str]] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise PanelFehler(422, f"„{was}“: Jeder Eintrag braucht eine Nummer.")
        nummer = normalisieren(eintrag.get("nummer"), landesvorwahl)
        if any(nummer == vorhandener["nummer"] for vorhandener in ergebnis):
            raise PanelFehler(422, f"„{was}“: Die Nummer {nummer} steht doppelt in der Liste.")
        ergebnis.append({"nummer": nummer, "name": str(eintrag.get("name") or "").strip()[:60]})
    return ergebnis


def _ruhezeiten(roh: Any) -> list[dict[str, str]]:
    if not isinstance(roh, list):
        raise PanelFehler(422, "„Ruhezeiten“ muss eine Liste sein.")
    if len(roh) > MAX_RUHEZEITEN:
        raise PanelFehler(422, f"Höchstens {MAX_RUHEZEITEN} Ruhezeiten.")
    ergebnis = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise PanelFehler(422, "Jede Ruhezeit braucht „von“ und „bis“.")
        von, bis = pruefung.uhrzeit(eintrag.get("von"), "von"), pruefung.uhrzeit(eintrag.get("bis"), "bis")
        if von == bis:
            raise PanelFehler(
                422,
                "Bei einer Ruhezeit dürfen „von“ und „bis“ nicht gleich sein.",
                "Zum Beispiel 22:00 bis 07:00.",
            )
        ergebnis.append({"von": von, "bis": bis})
    return ergebnis


class TelefonieDienst:
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
        self.zeitzone = ZoneInfo(einstellungen.zeitzone)
        self.test_adapter = TestAdapter()
        # Regeln können anrufen: Die Aktion „Anrufen“ braucht – anders als Missa – keine Freigabe.
        regeln.aktions_arten["anruf"] = AktionsArt(
            titel="Anrufen",
            pruefen=self._aktion_pruefen,
            satz=self._aktion_satz,
            ausfuehren=self._aktion_ausfuehren,
        )

    # ------------------------------------------------------------------ Einstellungen

    def lesen(self, db: Session) -> TelefonieEinstellung:
        einstellung = db.get(TelefonieEinstellung, 1)
        if einstellung is None:
            einstellung = TelefonieEinstellung(
                id=1,
                adapter="test",
                landesvorwahl="+41",
                eigene_nummern=[],
                erlaubte_anrufer=[],
                ruhezeiten=[],
                nur_bekannte=True,
            )
            db.add(einstellung)
            db.commit()
        return einstellung

    def _alle_adapter(self, db: Session) -> list[TelefonAdapter]:
        aus_integrationen = [
            IntegrationsAdapter(self.integrationen, self.datenbank, integration)
            for integration in self.integrationen.telefon_adapter(db)
        ]
        return [self.test_adapter, *aus_integrationen]

    def _adapter(self, db: Session, einstellung: TelefonieEinstellung) -> TelefonAdapter:
        gewaehlt = next((a for a in self._alle_adapter(db) if a.kennung == einstellung.adapter), None)
        if gewaehlt is None:
            raise IntegrationsFehler(
                "Der gewählte Telefonie-Adapter steht nicht mehr zur Verfügung.",
                "Im Panel unter „Anrufe“ einen anderen Adapter wählen oder die zugehörige Integration wieder aktivieren.",
            )
        return gewaehlt

    def _ruhezeit(self, einstellung: TelefonieEinstellung, jetzt: datetime) -> dict[str, str] | None:
        """Die Ruhezeit, die gerade gilt – oder `None`."""
        uhr = jetzt.astimezone(self.zeitzone).strftime("%H:%M")
        for fenster in einstellung.ruhezeiten or []:
            von, bis = fenster["von"], fenster["bis"]
            # „22:00 bis 07:00“ reicht über Mitternacht.
            if (von <= uhr < bis) if von < bis else (uhr >= von or uhr < bis):
                return fenster
        return None

    def ansicht(self, db: Session) -> dict[str, Any]:
        einstellung = self.lesen(db)
        adapter = self._alle_adapter(db)
        ruhe = self._ruhezeit(einstellung, zeit.jetzt())
        return {
            "einstellungen": {
                "adapter": einstellung.adapter,
                "landesvorwahl": einstellung.landesvorwahl,
                "eigene_nummern": einstellung.eigene_nummern or [],
                "erlaubte_anrufer": einstellung.erlaubte_anrufer or [],
                "ruhezeiten": einstellung.ruhezeiten or [],
                "nur_bekannte": einstellung.nur_bekannte,
            },
            "adapter": [
                {
                    "kennung": a.kennung,
                    "name": a.name,
                    "beschreibung": a.beschreibung,
                    "test": a is self.test_adapter,
                }
                for a in adapter
            ],
            # Ist der gewählte Adapter verschwunden (Integration entfernt), steht das hier.
            "adapter_fehlt": all(a.kennung != einstellung.adapter for a in adapter),
            "ruhezeit_jetzt": ruhe,
            "zeitzone": str(self.zeitzone),
        }

    def speichern(self, db: Session, daten: dict[str, Any]) -> dict[str, Any]:
        einstellung = self.lesen(db)
        vorwahl = landesvorwahl_pruefen(daten.get("landesvorwahl", einstellung.landesvorwahl))
        eigene = _eintraege(
            daten.get("eigene_nummern", einstellung.eigene_nummern or []), "Eigene Nummern", vorwahl
        )
        erlaubte = _eintraege(
            daten.get("erlaubte_anrufer", einstellung.erlaubte_anrufer or []), "Erlaubte Anrufer", vorwahl
        )
        doppelt = {e["nummer"] for e in eigene} & {e["nummer"] for e in erlaubte}
        if doppelt:
            raise PanelFehler(
                422,
                f"Die Nummer {sorted(doppelt)[0]} steht bei den eigenen Nummern und bei den erlaubten Anrufern.",
                "Eigene Nummern dürfen Missa immer anrufen – einmal eintragen genügt.",
            )
        adapter = str(daten.get("adapter", einstellung.adapter))
        if all(a.kennung != adapter for a in self._alle_adapter(db)):
            raise PanelFehler(422, "Diesen Telefonie-Adapter gibt es nicht (mehr).")
        einstellung.adapter = adapter
        einstellung.landesvorwahl = vorwahl
        einstellung.eigene_nummern = eigene
        einstellung.erlaubte_anrufer = erlaubte
        einstellung.ruhezeiten = _ruhezeiten(daten.get("ruhezeiten", einstellung.ruhezeiten or []))
        einstellung.nur_bekannte = bool(daten.get("nur_bekannte", einstellung.nur_bekannte))
        db.commit()
        return self.ansicht(db)

    def stand(self) -> str:
        """Ein Satz für „Testen“ unter „Integrationen“."""
        with self.datenbank.sitzung() as db:
            einstellung = self.lesen(db)
            adapter = next((a.name for a in self._alle_adapter(db) if a.kennung == einstellung.adapter), "–")
            eigene, erlaubte = len(einstellung.eigene_nummern or []), len(einstellung.erlaubte_anrufer or [])
        return (
            f"Telefonie bereit: {adapter}, {eigene} eigene Nummer{'' if eigene == 1 else 'n'}, "
            f"{erlaubte} erlaubte{'r' if erlaubte == 1 else ''} Anrufer."
        )

    # ------------------------------------------------------------------ wer ist das?

    @staticmethod
    def _bekannt(einstellung: TelefonieEinstellung, nummer: str) -> tuple[bool, str]:
        """Steht die Nummer bei den eigenen Nummern oder den erlaubten Anrufern? Dazu ihr Name."""
        for eintrag in [*(einstellung.eigene_nummern or []), *(einstellung.erlaubte_anrufer or [])]:
            if eintrag["nummer"] == nummer:
                return True, eintrag.get("name", "")
        return False, ""

    @staticmethod
    def _wer(nummer: str, name: str) -> str:
        return f"{name} ({nummer})" if name else nummer

    def _ziel(self, einstellung: TelefonieEinstellung, nummer: str | None) -> tuple[str, str]:
        """Wen ein ausgehender Anruf erreichen soll: (Nummer, Name). Ohne Angabe die erste eigene Nummer."""
        if nummer is not None and str(nummer).strip():
            try:
                ziel = normalisieren(nummer, einstellung.landesvorwahl)
            except PanelFehler as fehler:
                raise IntegrationsFehler(fehler.meldung, fehler.hinweis) from fehler
        elif einstellung.eigene_nummern:
            ziel = einstellung.eigene_nummern[0]["nummer"]
        else:
            raise IntegrationsFehler(
                "Es ist keine eigene Nummer hinterlegt.",
                "Im Panel unter „Anrufe“ eine eigene Nummer eintragen – oder beim Anruf eine Nummer angeben.",
            )
        bekannt, name = self._bekannt(einstellung, ziel)
        if einstellung.nur_bekannte and not bekannt:
            raise IntegrationsFehler(
                f"Die Nummer {ziel} darf nicht angerufen werden: Sie steht weder bei den eigenen Nummern noch bei den erlaubten Anrufern.",
                "Im Panel unter „Anrufe“ die Nummer eintragen – oder dort erlauben, dass auch andere Nummern angerufen werden.",
            )
        return ziel, name

    @staticmethod
    def _angaben(text: Any, dringlichkeit: Any) -> tuple[str, str]:
        sauber = str(text or "").strip()
        if not sauber:
            raise IntegrationsFehler(
                "Bitte angeben, was beim Anruf gesagt werden soll.",
                "Zum Beispiel: „Die Waschmaschine ist fertig.“",
            )
        if len(sauber) > MAX_TEXT:
            raise IntegrationsFehler(f"Der Text ist zu lang (höchstens {MAX_TEXT} Zeichen).")
        stufe = str(dringlichkeit or "normal").strip().lower()
        if stufe not in DRINGLICHKEITEN:
            raise IntegrationsFehler(
                f"Die Dringlichkeit „{stufe}“ gibt es nicht.",
                "Erlaubt sind: " + ", ".join(DRINGLICHKEITEN) + ".",
            )
        return sauber, stufe

    # ------------------------------------------------------------------ ausgehend

    def vorschau(self, text: str, nummer: str | None, dringlichkeit: str) -> str:
        """Der Satz für die Freigabe. Steht schon fest, dass der Anruf nicht geht, kommt die Meldung sofort."""
        with self.datenbank.sitzung() as db:
            einstellung = self.lesen(db)
            sauber, stufe = self._angaben(text, dringlichkeit)
            ziel, name = self._ziel(einstellung, nummer)
            ruhe = self._ruhezeit(einstellung, zeit.jetzt())
            if ruhe is not None and stufe != "dringend":
                raise IntegrationsFehler(*self._ruhezeit_meldung(ruhe))
            adapter = self._adapter(db, einstellung)
        zusatz = " (Test-Adapter: nur protokolliert)" if adapter is self.test_adapter else ""
        dringend = f" Dringlichkeit: {stufe}." if stufe != "normal" else ""
        return f"Ruft {self._wer(ziel, name)} an{zusatz} und sagt: „{sauber}“{dringend}"

    @staticmethod
    def _ruhezeit_meldung(ruhe: dict[str, str]) -> tuple[str, str]:
        return (
            f"Nicht angerufen: Es ist Ruhezeit ({ruhe['von']} bis {ruhe['bis']} Uhr).",
            "In der Ruhezeit gehen nur Anrufe mit der Dringlichkeit „dringend“ durch.",
        )

    async def anrufen(
        self,
        db: Session,
        *,
        text: str,
        nummer: str | None = None,
        dringlichkeit: str = "normal",
        quelle: str,
        quelle_name: str = "",
    ) -> dict[str, Any]:
        """Löst einen Anruf aus. Alles, was dabei geschieht – auch eine Ablehnung –, steht danach im Verlauf."""
        einstellung = self.lesen(db)
        sauber, stufe = self._angaben(text, dringlichkeit)
        jetzt = zeit.jetzt()

        def eintragen(nummer_: str, name_: str, status: str, meldung: str = "") -> Anruf:
            anruf = Anruf(
                zeit=jetzt,
                richtung="ausgehend",
                nummer=nummer_,
                name=name_,
                status=status,
                grund=sauber,
                dringlichkeit=stufe,
                quelle=quelle,
                quelle_name=quelle_name[:80],
                adapter=einstellung.adapter,
                meldung=meldung[:300],
                beendet=jetzt if status not in OFFEN else None,
            )
            db.add(anruf)
            db.commit()
            return anruf

        try:
            ziel, name = self._ziel(einstellung, nummer)
        except IntegrationsFehler as fehler:
            eintragen(str(nummer or "–").strip()[:40], "", "abgewiesen", fehler.meldung)
            raise
        ruhe = self._ruhezeit(einstellung, jetzt)
        if ruhe is not None and stufe != "dringend":
            meldung, hinweis = self._ruhezeit_meldung(ruhe)
            anruf = eintragen(ziel, name, "unterdrueckt", meldung)
            # Damit es nicht untergeht: Missa erfährt es als Ereignis und kann es später ausrichten.
            self._melden(anruf, "Anruf in der Ruhezeit nicht ausgeführt", sauber, test=False)
            raise IntegrationsFehler(meldung, hinweis)

        anruf = eintragen(ziel, name, "wartet")
        try:
            adapter = self._adapter(db, einstellung)
            start = await adapter.anrufen(
                Anrufauftrag(anruf_id=anruf.id, nummer=ziel, name=name, text=sauber, dringlichkeit=stufe)
            )
        except IntegrationsFehler as fehler:
            anruf.status, anruf.meldung, anruf.beendet = "fehler", fehler.meldung[:300], zeit.jetzt()
            db.commit()
            raise
        except Exception as fehler:
            log.exception("Telefonie-Adapter „%s“ ist fehlgeschlagen", einstellung.adapter)
            anruf.status, anruf.beendet = "fehler", zeit.jetzt()
            anruf.meldung = f"Unerwarteter Fehler im Adapter: {type(fehler).__name__}"
            db.commit()
            raise IntegrationsFehler(
                "Der Telefonie-Adapter hat den Anruf nicht aufbauen können.",
                "Details stehen im Protokoll des Panels.",
            ) from fehler

        start = start or Anrufstart()
        # Hat der Adapter das Ende inzwischen schon selbst gemeldet, bleibt es dabei.
        db.refresh(anruf)
        if anruf.status == "wartet":
            anruf.status = start.ergebnis if start.ergebnis in _ERGEBNISSE else "laeuft"
            anruf.meldung = start.meldung[:300]
            if anruf.status != "laeuft":
                anruf.dauer_sekunden = max(int(start.dauer_sekunden or 0), 0)
                anruf.beendet = zeit.jetzt()
            db.commit()
        test = anruf.status == "test"
        self._melden(
            anruf, f"Anruf an {self._wer(ziel, name)}" + (" (Test)" if test else ""), sauber, test=test
        )
        return {
            **self._zeile(anruf),
            "meldung": (
                f"Test-Adapter: Der Anruf an {self._wer(ziel, name)} wurde nur protokolliert – es hat nirgends geklingelt."
                if test
                else f"Anruf an {self._wer(ziel, name)}: {STATUS_TEXT.get(anruf.status, anruf.status)}."
            ),
        }

    def _melden(self, anruf: Anruf, titel: str, nachricht: str, *, test: bool) -> None:
        self.ereignisse.melden(
            "anruf",
            titel,
            nachricht,
            dringlichkeit=anruf.dringlichkeit,
            quelle="Telefonie",
            daten={
                "anruf_id": anruf.id,
                "richtung": anruf.richtung,
                "nummer": anruf.nummer,
                "name": anruf.name,
                "status": anruf.status,
                "adapter": anruf.adapter,
                "test": test,
            },
        )

    async def fuer_missa_anrufen(self, text: str, nummer: str | None, dringlichkeit: str) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            ergebnis = await self.anrufen(
                db, text=text, nummer=nummer, dringlichkeit=dringlichkeit, quelle="missa", quelle_name="Missa"
            )
        return {name: ergebnis[name] for name in ("id", "nummer", "name", "status", "meldung")}

    def fuer_missa_verlauf(self, anzahl: int = 10) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            zeilen = self.verlauf(db, limit=min(max(int(anzahl), 1), 50))
        felder = ("id", "zeit", "richtung", "nummer", "name", "status_text", "dauer_sekunden", "grund")
        return {"anzahl": len(zeilen), "anrufe": [{feld: zeile[feld] for feld in felder} for zeile in zeilen]}

    # ------------------------------------------------------------------ Rückmeldungen des Adapters

    def eingehender_anruf(self, nummer: str, adapter: str = "") -> dict[str, Any]:
        """Ein Anruf kommt herein. Das Panel entscheidet: Nur eigene Nummern und erlaubte Anrufer kommen durch.

        Gibt `annehmen`, `anruf_id`, `name` und – bei Ablehnung – den `grund` zurück. Abgewiesene Anrufe
        stehen im Verlauf.
        """
        with self.datenbank.sitzung() as db:
            einstellung = self.lesen(db)
            roh = str(nummer or "").strip()
            try:
                normal = normalisieren(roh, einstellung.landesvorwahl)
            except PanelFehler:
                normal = ""
            erlaubt, name = self._bekannt(einstellung, normal) if normal else (False, "")
            if erlaubt:
                grund = ""
            elif not normal:
                grund = "Die Nummer ist unterdrückt oder ungültig."
            else:
                grund = "Die Nummer steht nicht in der Liste erlaubter Anrufer."
            jetzt = zeit.jetzt()
            anruf = Anruf(
                zeit=jetzt,
                richtung="eingehend",
                nummer=normal or roh[:40] or "unbekannt",
                name=name,
                status="laeuft" if erlaubt else "abgewiesen",
                grund=grund,
                dringlichkeit="normal" if erlaubt else "niedrig",
                quelle="anrufer",
                quelle_name=name,
                adapter=adapter[:80] or einstellung.adapter,
                beendet=None if erlaubt else jetzt,
            )
            db.add(anruf)
            db.commit()
            if erlaubt:
                self._melden(
                    anruf,
                    f"Anruf von {self._wer(anruf.nummer, name)}",
                    "Ein erlaubter Anrufer ruft an.",
                    test=False,
                )
            else:
                self._melden(anruf, f"Anruf von {anruf.nummer} abgewiesen", grund, test=False)
            return {
                "annehmen": erlaubt,
                "anruf_id": anruf.id,
                "nummer": anruf.nummer,
                "name": name,
                "grund": grund,
            }

    def anruf_beendet(
        self,
        anruf_id: int,
        *,
        dauer_sekunden: int | None = None,
        ergebnis: str = "beendet",
        meldung: str = "",
    ) -> dict[str, Any]:
        """Der Adapter meldet das Ende eines Anrufs („beendet“, „nicht_erreicht“ oder „test“)."""
        if ergebnis not in ("beendet", "nicht_erreicht", "test"):
            raise PanelFehler(422, "Unbekanntes Ergebnis.", "Erlaubt sind: beendet, nicht_erreicht.")
        with self.datenbank.sitzung() as db:
            anruf = db.get(Anruf, anruf_id)
            if anruf is None:
                raise PanelFehler(404, "Diesen Anruf gibt es nicht.")
            if anruf.status not in OFFEN:
                raise PanelFehler(409, "Dieser Anruf ist bereits abgeschlossen.")
            anruf.status = ergebnis
            anruf.dauer_sekunden = max(int(dauer_sekunden or 0), 0)
            anruf.meldung = str(meldung or "")[:300]
            anruf.beendet = zeit.jetzt()
            db.commit()
            return self._zeile(anruf)

    def eingehend_simulieren(self, nummer: str) -> dict[str, Any]:
        """Für den Test im Panel: tut so, als riefe diese Nummer an – ohne dass irgendwo ein Telefon klingelt."""
        entscheidung = self.eingehender_anruf(nummer, adapter="test")
        if entscheidung["annehmen"]:
            self.anruf_beendet(
                entscheidung["anruf_id"],
                dauer_sekunden=0,
                ergebnis="test",
                meldung="Simulierter Anruf – angenommen.",
            )
        return entscheidung

    # ------------------------------------------------------------------ Verlauf

    @staticmethod
    def _zeile(anruf: Anruf) -> dict[str, Any]:
        return {
            "id": anruf.id,
            "zeit": anruf.zeit.isoformat(),
            "richtung": anruf.richtung,
            "nummer": anruf.nummer,
            "name": anruf.name,
            "status": anruf.status,
            "status_text": STATUS_TEXT.get(anruf.status, anruf.status),
            "dauer_sekunden": anruf.dauer_sekunden,
            "grund": anruf.grund,
            "dringlichkeit": anruf.dringlichkeit,
            "quelle": anruf.quelle,
            "quelle_name": anruf.quelle_name,
            "adapter": anruf.adapter,
            "meldung": anruf.meldung,
        }

    def verlauf(self, db: Session, limit: int = 100, richtung: str | None = None) -> list[dict[str, Any]]:
        abfrage = select(Anruf).order_by(Anruf.zeit.desc(), Anruf.id.desc()).limit(limit)
        if richtung:
            if richtung not in RICHTUNGEN:
                raise PanelFehler(422, "Unbekannte Richtung.", "Erlaubt sind: ausgehend, eingehend.")
            abfrage = abfrage.where(Anruf.richtung == richtung)
        return [self._zeile(anruf) for anruf in db.scalars(abfrage)]

    def aufraeumen(self, tage: int) -> int:
        """Löscht alte Einträge und schliesst Anrufe ab, deren Ende nie gemeldet wurde."""
        with self.datenbank.sitzung() as db:
            jetzt = zeit.jetzt()
            db.execute(
                update(Anruf)
                .where(Anruf.status.in_(OFFEN), Anruf.zeit < jetzt - OHNE_RUECKMELDUNG)
                .values(
                    status="beendet", beendet=jetzt, meldung="Ohne Rückmeldung des Adapters abgeschlossen."
                )
            )
            ergebnis = db.execute(delete(Anruf).where(Anruf.zeit < jetzt - timedelta(days=tage)))
            db.commit()
            return ergebnis.rowcount or 0

    # ------------------------------------------------------------------ Aktion „Anrufen“ für Regeln

    @staticmethod
    def _aktion_pruefen(daten: dict[str, Any], _: Umfeld) -> dict[str, Any]:
        gemeinsam = pruefung.ereignis_aktion_pruefen(
            daten, _
        )  # Nachricht und Dringlichkeit wie beim Ereignis
        nummer = str(daten.get("nummer") or "").strip()
        if nummer:
            normalisieren(nummer)  # nur prüfen – gewählt wird später mit der dann gültigen Landesvorwahl
        return {**gemeinsam, **({"nummer": nummer} if nummer else {})}

    @staticmethod
    def _aktion_satz(aktion: dict[str, Any], _: Umfeld) -> str:
        wen = f"die Nummer {aktion['nummer']}" if aktion.get("nummer") else "dich"
        dringlichkeit = aktion.get("dringlichkeit", "normal")
        zusatz = f" (Dringlichkeit: {dringlichkeit})" if dringlichkeit != "normal" else ""
        return f"ruft Missa {wen} an und sagt: „{aktion.get('nachricht', '')}“{zusatz}"

    async def _aktion_ausfuehren(self, db: Session, regel: Regel, anlass: Anlass, test: bool) -> str:
        aktion = regel.aktion
        ergebnis = await self.anrufen(
            db,
            text=self.regeln.platzhalter(str(aktion.get("nachricht", "")), regel, anlass)[:MAX_TEXT],
            nummer=aktion.get("nummer"),
            dringlichkeit=str(aktion.get("dringlichkeit", "normal")),
            quelle="regel",
            quelle_name=regel.name,
        )
        return str(ergebnis["meldung"])
