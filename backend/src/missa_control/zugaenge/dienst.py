"""Zugänge anlegen, ändern, löschen – und für Integrationen entschlüsseln."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.fehler import PanelFehler
from missa_control.krypto import Krypto
from missa_control.zugaenge.modelle import TYP_BENUTZER_PASSWORT, TYPEN, Zugang
from missa_control.zugaenge.schwaerzen import Schwaerzer

TYP_NAMEN = {
    "api_key": "API-Key",
    "benutzer_passwort": "Benutzer + Passwort",
    "bearer_token": "Bearer-Token",
}


@dataclass(frozen=True)
class Zugangsdaten:
    """Entschlüsselter Zugang – nur für den Aufruf einer Integration, nie für die Oberfläche."""

    typ: str
    wert: str = ""
    benutzer: str = ""

    @property
    def passwort(self) -> str:
        return self.wert

    def __repr__(self) -> str:  # Klartext soll nie versehentlich in einem Log landen
        return f"Zugangsdaten(typ={self.typ!r}, wert=•••)"


def maskieren(wert: str) -> str:
    """`••••abcd`: zeigt nur das Ende, bei kurzen Werten gar nichts."""
    if len(wert) >= 12:
        return "••••" + wert[-4:]
    if len(wert) >= 8:
        return "••••" + wert[-2:]
    return "••••"


class ZugangsDienst:
    def __init__(self, krypto: Krypto, schwaerzer: Schwaerzer) -> None:
        self.krypto = krypto
        self.schwaerzer = schwaerzer

    # ---------- für die Oberfläche (immer maskiert) ----------

    def alle(self, db: Session) -> list[dict[str, object]]:
        return [self.ansicht(zugang) for zugang in db.scalars(select(Zugang).order_by(Zugang.name))]

    def ansicht(self, zugang: Zugang) -> dict[str, object]:
        try:
            maske = maskieren(self._entschluesseln(zugang))
            lesbar = True
        except Exception:
            maske, lesbar = "••••", False
        return {
            "id": zugang.id,
            "name": zugang.name,
            "typ": zugang.typ,
            "typ_name": TYP_NAMEN.get(zugang.typ, zugang.typ),
            "benutzer": zugang.benutzer,
            "maske": maske,
            "lesbar": lesbar,
            "notiz": zugang.notiz,
            "erstellt": zugang.erstellt.isoformat(),
            "geaendert": zugang.geaendert.isoformat(),
        }

    def anlegen(
        self, db: Session, *, name: str, typ: str, wert: str, benutzer: str | None = None, notiz: str = ""
    ) -> Zugang:
        name = name.strip()
        self._pruefen(db, name=name, typ=typ, wert=wert, benutzer=benutzer)
        zeitpunkt = zeit.jetzt()
        zugang = Zugang(
            name=name,
            typ=typ,
            benutzer=(benutzer or "").strip() or None if typ == TYP_BENUTZER_PASSWORT else None,
            wert_verschluesselt=self._verschluesseln(wert),
            notiz=notiz.strip(),
            erstellt=zeitpunkt,
            geaendert=zeitpunkt,
        )
        db.add(zugang)
        db.commit()
        return zugang

    def aendern(
        self,
        db: Session,
        zugang_id: int,
        *,
        name: str | None = None,
        wert: str | None = None,
        benutzer: str | None = None,
        notiz: str | None = None,
    ) -> Zugang:
        zugang = self.holen(db, zugang_id)
        if name is not None and name.strip() != zugang.name:
            self._pruefen(db, name=name.strip(), typ=zugang.typ, wert=wert or "x", benutzer=benutzer or "x")
            zugang.name = name.strip()
        if zugang.typ == TYP_BENUTZER_PASSWORT and benutzer is not None:
            if not benutzer.strip():
                raise PanelFehler(422, "Der Benutzername darf nicht leer sein.")
            zugang.benutzer = benutzer.strip()
        if wert:  # leer = unverändert lassen
            zugang.wert_verschluesselt = self._verschluesseln(wert)
        if notiz is not None:
            zugang.notiz = notiz.strip()
        zugang.geaendert = zeit.jetzt()
        db.commit()
        return zugang

    def loeschen(self, db: Session, zugang_id: int) -> None:
        db.delete(self.holen(db, zugang_id))
        db.commit()

    def holen(self, db: Session, zugang_id: int) -> Zugang:
        zugang = db.get(Zugang, zugang_id)
        if zugang is None:
            raise PanelFehler(404, "Diesen Zugang gibt es nicht (mehr).")
        return zugang

    # ---------- für Integrationen (Klartext, nur intern) ----------

    def klartext(self, db: Session, zugang_id: int) -> Zugangsdaten:
        zugang = db.get(Zugang, zugang_id)
        if zugang is None:
            raise PanelFehler(
                404,
                "Der hinterlegte Zugang existiert nicht mehr.",
                "Bitte in der Integration einen anderen Zugang auswählen oder einen neuen anlegen.",
            )
        return Zugangsdaten(typ=zugang.typ, wert=self._entschluesseln(zugang), benutzer=zugang.benutzer or "")

    # ---------- intern ----------

    def _verschluesseln(self, wert: str) -> str:
        self.schwaerzer.merken(wert)
        return self.krypto.verschluesseln(wert)

    def _entschluesseln(self, zugang: Zugang) -> str:
        wert = self.krypto.entschluesseln(zugang.wert_verschluesselt)
        self.schwaerzer.merken(wert)
        return wert

    @staticmethod
    def _pruefen(db: Session, *, name: str, typ: str, wert: str, benutzer: str | None) -> None:
        if not name:
            raise PanelFehler(422, "Bitte einen Namen für den Zugang angeben.")
        if typ not in TYPEN:
            raise PanelFehler(
                422, "Unbekannter Typ.", "Erlaubt sind API-Key, Benutzer + Passwort und Bearer-Token."
            )
        if not wert:
            raise PanelFehler(422, "Der Wert darf nicht leer sein.")
        if typ == TYP_BENUTZER_PASSWORT and not (benutzer or "").strip():
            raise PanelFehler(422, "Bitte einen Benutzernamen angeben.")
        if db.scalar(select(Zugang).where(Zugang.name == name)) is not None:
            raise PanelFehler(
                409,
                f"Es gibt bereits einen Zugang mit dem Namen „{name}“.",
                "Bitte einen anderen Namen wählen.",
            )
