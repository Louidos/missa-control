from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from missa_control.db import Base, UTCDateTime


class GedaechtnisEintrag(Base):
    """Etwas, das Missa sich gemerkt hat (oder das im Panel von Hand eingetragen wurde).

    Zur Tabelle gehört der Volltext-Index `gedaechtnis_fts` (FTS5). Er wird in der Migration angelegt
    und über Trigger aktuell gehalten – wer hier schreibt, muss sich nicht darum kümmern.
    """

    __tablename__ = "gedaechtnis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    kategorie: Mapped[str] = mapped_column(String, index=True)
    # missa (über das Gateway gemerkt) oder manuell (im Panel eingetragen)
    quelle: Mapped[str] = mapped_column(String)
    erstellt: Mapped[datetime] = mapped_column(UTCDateTime)
    geaendert: Mapped[datetime] = mapped_column(UTCDateTime)
