from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime

RICHTUNGEN = ("ausgehend", "eingehend")
# wartet: an den Adapter übergeben · laeuft: Gespräch läuft · beendet · nicht_erreicht · abgewiesen (nicht erlaubt)
# unterdrueckt: wegen Ruhezeit nicht angerufen · fehler: der Adapter konnte nicht · test: nur protokolliert
STATUS = ("wartet", "laeuft", "beendet", "nicht_erreicht", "abgewiesen", "unterdrueckt", "fehler", "test")
OFFEN = ("wartet", "laeuft")


class TelefonieEinstellung(Base):
    """Die Einstellungen der Telefonie – es gibt genau eine Zeile (id = 1)."""

    __tablename__ = "telefonie_einstellungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Welcher Adapter Anrufe ausführt: „test“ oder „integration:<id>“.
    adapter: Mapped[str] = mapped_column(String, default="test")
    # Wird Nummern ohne Ländervorwahl vorangestellt (079 … → +4179 …).
    landesvorwahl: Mapped[str] = mapped_column(String, default="+41")
    # [{"nummer": "+41791234567", "name": "Handy"}] – unter diesen Nummern erreicht Missa den Besitzer.
    eigene_nummern: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Weitere Nummern, die Missa anrufen dürfen (eigene Nummern dürfen das immer).
    erlaubte_anrufer: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{"von": "22:00", "bis": "07:00"}] – in dieser Zeit ruft Missa nur an, wenn es dringend ist.
    ruhezeiten: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Missa ruft nur eigene Nummern und erlaubte Anrufer an.
    nur_bekannte: Mapped[bool] = mapped_column(Boolean, default=True)


class Anruf(Base):
    """Ein Eintrag im Anrufverlauf – auch abgewiesene und wegen Ruhezeit unterdrückte Anrufe stehen hier."""

    __tablename__ = "anrufe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    richtung: Mapped[str] = mapped_column(String)
    nummer: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String)
    dauer_sekunden: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Ausgehend: was gesagt werden soll. Abgewiesen bzw. unterdrückt: warum.
    grund: Mapped[str] = mapped_column(String, default="")
    dringlichkeit: Mapped[str] = mapped_column(String, default="normal")
    # Wer den Anruf ausgelöst hat: missa, regel, panel oder anrufer – und wie es heisst (z. B. Name der Regel).
    quelle: Mapped[str] = mapped_column(String, default="")
    quelle_name: Mapped[str] = mapped_column(String, default="")
    adapter: Mapped[str] = mapped_column(String, default="")
    # Rückmeldung des Adapters (z. B. „besetzt“) oder Fehlertext.
    meldung: Mapped[str] = mapped_column(String, default="")
    beendet: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
