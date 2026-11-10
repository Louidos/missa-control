"""Gedächtnis: Einträge anlegen, ändern, löschen und im Volltext durchsuchen (SQLite FTS5)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, column, func, literal_column, or_, select, table
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.db import Datenbank
from missa_control.fehler import PanelFehler
from missa_control.gedaechtnis.modelle import GedaechtnisEintrag

KATEGORIEN: dict[str, str] = {
    "vorlieben": "Vorlieben",
    "gewohnheiten": "Gewohnheiten",
    "projektwissen": "Projektwissen",
    "personen": "Personen",
    "sonstiges": "Sonstiges",
}
QUELLE_MISSA = "missa"
QUELLE_MANUELL = "manuell"
QUELLEN: dict[str, str] = {QUELLE_MISSA: "Missa", QUELLE_MANUELL: "manuell"}
MAX_ZEICHEN = 2000
# Der Volltext-Index arbeitet mit Dreiergruppen von Zeichen: kürzere Begriffe sucht ein einfacher Vergleich.
_MIN_VOLLTEXT = 3
_MAX_BEGRIFFE = 12
_RAND = " \t\r\n.,;:!?()[]{}\"'„“”‚‘’«»*"
# Füllwörter: Missa sucht oft mit ganzen Sätzen („Wo ist der Autoschlüssel?“). Da ihr schon ein passender
# Begriff genügt, würden „ist“ und „der“ fast jeden Eintrag finden – sie zählen deshalb nicht mit.
_FUELLWORT_LISTE = """
    aber alle allem allen aller alles als also auch auf aus bei bin bis bist bitte dann das dass dein deine
    dem den denn der des dessen die dies diese diesem diesen dieser dieses doch dort durch ein eine einem
    einen einer eines etwas euch euer eure für gegen gibt habe haben hast hat hatte hier ihm ihn ihr ihre
    ihrem ihren ihrer immer ist jede jedem jeden jeder jedes kann kein keine keinem keinen keiner können
    man mein meine meinem meinen meiner mich mir mit muss nach nicht noch nun nur oder ohne sehr sein seine
    seinem seinen seiner sich sie sind soll über und uns unser unsere unter viel vom von vor wann war waren
    warum was weiss welche welchem welchen welcher welches wem wen wenn wer werden wie wieder wir wird
    wo zum zur zwischen am an da du er es ich im in ja ob so um zu
"""
_FUELLWOERTER = frozenset(_FUELLWORT_LISTE.split())

# Der Volltext-Index ist eine eigene (virtuelle) Tabelle; `rowid` ist die Nummer des Eintrags.
_fts = table("gedaechtnis_fts", column("rowid"), column("gedaechtnis_fts"))
_fts_rang = literal_column("bm25(gedaechtnis_fts)")


def begriffe(suche: str) -> list[str]:
    """Zerlegt die Eingabe in Suchbegriffe (ohne Satzzeichen am Rand, ohne Wiederholungen)."""
    gefunden: list[str] = []
    for teil in suche.split():
        begriff = teil.strip(_RAND).lower()
        if begriff and begriff not in gefunden:
            gefunden.append(begriff)
    return gefunden[:_MAX_BEGRIFFE]


def volltext_abfrage(woerter: list[str], alle: bool) -> str:
    """Baut die FTS5-Abfrage. Jeder Begriff steht in Anführungszeichen – Sonderzeichen sind damit harmlos."""
    teile = ['"' + wort.replace('"', '""') + '"' for wort in woerter]
    return (" AND " if alle else " OR ").join(teile)


def ansicht(eintrag: GedaechtnisEintrag) -> dict[str, Any]:
    return {
        "id": eintrag.id,
        "text": eintrag.text,
        "kategorie": eintrag.kategorie,
        "kategorie_name": KATEGORIEN.get(eintrag.kategorie, eintrag.kategorie),
        "quelle": eintrag.quelle,
        "quelle_name": QUELLEN.get(eintrag.quelle, eintrag.quelle),
        "erstellt": eintrag.erstellt.isoformat(),
        "geaendert": eintrag.geaendert.isoformat(),
    }


def _kategorie_pruefen(kategorie: str | None) -> str:
    """Gross- und Kleinschreibung ist egal („Vorlieben“ und „vorlieben“ meinen dasselbe)."""
    wert = (kategorie or "sonstiges").strip().lower()
    if wert not in KATEGORIEN:
        raise PanelFehler(
            422,
            f"Die Kategorie „{kategorie}“ gibt es nicht.",
            "Erlaubt sind: " + ", ".join(KATEGORIEN) + ".",
        )
    return wert


def _text_pruefen(text: str | None) -> str:
    # Überflüssige Leerzeichen entfernen, Zeilenumbrüche behalten.
    sauber = "\n".join(" ".join(zeile.split()) for zeile in (text or "").strip().splitlines())
    if not sauber:
        raise PanelFehler(422, "Der Eintrag ist leer.", "Bitte einen Text angeben.")
    if len(sauber) > MAX_ZEICHEN:
        raise PanelFehler(
            422,
            f"Der Eintrag ist zu lang ({len(sauber)} Zeichen).",
            f"Höchstens {MAX_ZEICHEN} Zeichen – lieber mehrere kurze Einträge anlegen.",
        )
    return sauber


class GedaechtnisDienst:
    def __init__(self, datenbank: Datenbank) -> None:
        self.datenbank = datenbank

    # ------------------------------------------------------------------ Einträge

    @staticmethod
    def holen(db: Session, eintrag_id: int) -> GedaechtnisEintrag:
        eintrag = db.get(GedaechtnisEintrag, eintrag_id)
        if eintrag is None:
            raise PanelFehler(
                404,
                f"Den Eintrag {eintrag_id} gibt es im Gedächtnis nicht (mehr).",
                "Mit „suchen“ nachsehen, welche Einträge es gibt.",
            )
        return eintrag

    @staticmethod
    def _gleicher(db: Session, text: str) -> GedaechtnisEintrag | None:
        return db.scalar(
            select(GedaechtnisEintrag).where(func.lower(GedaechtnisEintrag.text) == func.lower(text)).limit(1)
        )

    def anlegen(
        self, db: Session, text: str, kategorie: str | None = None, quelle: str = QUELLE_MANUELL
    ) -> tuple[GedaechtnisEintrag, bool]:
        """Legt einen Eintrag an. Steht derselbe Text schon da, bleibt es bei dem einen (zweiter Wert: neu?)."""
        sauber = _text_pruefen(text)
        kategorie = _kategorie_pruefen(kategorie)
        vorhanden = self._gleicher(db, sauber)
        if vorhanden is not None:
            return vorhanden, False
        jetzt = zeit.jetzt()
        eintrag = GedaechtnisEintrag(
            text=sauber, kategorie=kategorie, quelle=quelle, erstellt=jetzt, geaendert=jetzt
        )
        db.add(eintrag)
        db.commit()
        return eintrag, True

    def aendern(
        self, db: Session, eintrag_id: int, *, text: str | None = None, kategorie: str | None = None
    ) -> GedaechtnisEintrag:
        eintrag = self.holen(db, eintrag_id)
        if text is not None:
            eintrag.text = _text_pruefen(text)
        if kategorie is not None:
            eintrag.kategorie = _kategorie_pruefen(kategorie)
        if db.is_modified(eintrag):
            eintrag.geaendert = zeit.jetzt()
        db.commit()
        return eintrag

    def loeschen(self, db: Session, eintrag_id: int) -> GedaechtnisEintrag:
        eintrag = self.holen(db, eintrag_id)
        db.delete(eintrag)
        db.commit()
        return eintrag

    # ------------------------------------------------------------------ Suche

    def suchen(
        self,
        db: Session,
        suche: str = "",
        *,
        kategorie: str | None = None,
        quelle: str | None = None,
        alle_woerter: bool = True,
        limit: int = 100,
    ) -> tuple[list[GedaechtnisEintrag], int]:
        """Durchsucht das Gedächtnis. Gibt die besten Treffer und die Zahl aller Treffer zurück.

        `alle_woerter=True` (Suchfeld im Panel): jeder Begriff muss vorkommen.
        `alle_woerter=False` (Missa): ein Begriff genügt, Einträge mit mehr Treffern stehen vorn.
        Ohne Suchtext kommen die zuletzt geänderten Einträge.
        """
        bedingungen: list[ColumnElement[bool]] = []
        if kategorie:
            bedingungen.append(GedaechtnisEintrag.kategorie == _kategorie_pruefen(kategorie))
        if quelle:
            if quelle not in QUELLEN:
                raise PanelFehler(422, f"Die Quelle „{quelle}“ gibt es nicht.", "Erlaubt: missa, manuell.")
            bedingungen.append(GedaechtnisEintrag.quelle == quelle)

        woerter = begriffe(suche)
        if not alle_woerter:
            # Ein Treffer genügt: Füllwörter weglassen (ausser es bliebe sonst nichts übrig).
            woerter = [wort for wort in woerter if wort not in _FUELLWOERTER] or woerter
        lange = [wort for wort in woerter if len(wort) >= _MIN_VOLLTEXT]
        kurze = [wort for wort in woerter if len(wort) < _MIN_VOLLTEXT]
        enthaelt = [GedaechtnisEintrag.text.contains(wort, autoescape=True) for wort in kurze]

        abfrage = select(GedaechtnisEintrag)
        zaehlen = select(func.count()).select_from(GedaechtnisEintrag)
        reihenfolge: list[Any] = [GedaechtnisEintrag.geaendert.desc(), GedaechtnisEintrag.id.desc()]
        if lange:
            treffer = _fts.c.gedaechtnis_fts.op("MATCH")(volltext_abfrage(lange, alle_woerter))
            verbindung = _fts.c.rowid == GedaechtnisEintrag.id
            abfrage = abfrage.join(_fts, verbindung).where(treffer)
            zaehlen = zaehlen.join(_fts, verbindung).where(treffer)
            reihenfolge.insert(0, _fts_rang)  # beste Treffer zuerst
            if alle_woerter:
                bedingungen.extend(enthaelt)
        elif alle_woerter:
            bedingungen.extend(enthaelt)
        elif enthaelt:
            bedingungen.append(or_(*enthaelt))

        abfrage = abfrage.where(*bedingungen).order_by(*reihenfolge).limit(max(1, min(limit, 1000)))
        eintraege = list(db.scalars(abfrage))
        gesamt = db.scalar(zaehlen.where(*bedingungen)) or 0
        return eintraege, gesamt

    @staticmethod
    def anzahl(db: Session) -> int:
        return db.scalar(select(func.count()).select_from(GedaechtnisEintrag)) or 0

    # ------------------------------------------------------------------ für das Panel

    def uebersicht(
        self, db: Session, *, suche: str = "", kategorie: str = "", quelle: str = "", limit: int = 100
    ) -> dict[str, Any]:
        eintraege, treffer = self.suchen(
            db, suche, kategorie=kategorie or None, quelle=quelle or None, limit=limit
        )
        je_kategorie = dict(
            db.execute(
                select(GedaechtnisEintrag.kategorie, func.count()).group_by(GedaechtnisEintrag.kategorie)
            ).all()
        )
        return {
            "eintraege": [ansicht(eintrag) for eintrag in eintraege],
            "treffer": treffer,
            "gesamt": sum(je_kategorie.values()),
            "kategorien": [
                {"wert": wert, "titel": titel, "anzahl": int(je_kategorie.get(wert, 0))}
                for wert, titel in KATEGORIEN.items()
            ],
            "quellen": [{"wert": wert, "titel": titel} for wert, titel in QUELLEN.items()],
            "max_zeichen": MAX_ZEICHEN,
        }

    def export(self, db: Session) -> dict[str, Any]:
        """Alle Einträge für die Sicherung als JSON-Datei."""
        eintraege = db.scalars(select(GedaechtnisEintrag).order_by(GedaechtnisEintrag.id))
        liste = [
            {
                "id": eintrag.id,
                "text": eintrag.text,
                "kategorie": eintrag.kategorie,
                "quelle": eintrag.quelle,
                "erstellt": eintrag.erstellt.isoformat(),
                "geaendert": eintrag.geaendert.isoformat(),
            }
            for eintrag in eintraege
        ]
        return {"exportiert": zeit.jetzt().isoformat(), "anzahl": len(liste), "eintraege": liste}

    # ------------------------------------------------------------------ für Missa (eingebaute Integration)

    def bestand(self) -> int:
        with self.datenbank.sitzung() as db:
            return self.anzahl(db)

    def merken(self, text: str, kategorie: str | None = None) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            eintrag, neu = self.anlegen(db, text, kategorie, quelle=QUELLE_MISSA)
            return {
                "id": eintrag.id,
                "kategorie": KATEGORIEN[eintrag.kategorie],
                "meldung": "Gemerkt." if neu else "Das steht schon im Gedächtnis.",
            }

    def fuer_missa_suchen(
        self, text: str = "", kategorie: str | None = None, anzahl: int = 10
    ) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            eintraege, treffer = self.suchen(
                db, text, kategorie=kategorie, alle_woerter=False, limit=max(1, min(anzahl, 50))
            )
            ergebnis: dict[str, Any] = {
                "anzahl": len(eintraege),
                "eintraege": [
                    {
                        "id": eintrag.id,
                        "text": eintrag.text,
                        "kategorie": KATEGORIEN.get(eintrag.kategorie, eintrag.kategorie),
                        "gemerkt_am": eintrag.erstellt.date().isoformat(),
                    }
                    for eintrag in eintraege
                ],
            }
            if treffer > len(eintraege):
                ergebnis["hinweis"] = (
                    f"Es gibt {treffer} passende Einträge, angezeigt werden die {len(eintraege)} besten. "
                    "Mit genaueren Stichwörtern oder einer Kategorie eingrenzen."
                )
            elif not eintraege:
                ergebnis["hinweis"] = (
                    "Nichts gefunden. Tipp: mit einem einzelnen Stichwort (auch ein Wortteil genügt) "
                    "oder nur mit einer Kategorie suchen."
                )
            return ergebnis

    def vergessen_vorschau(self, eintrag_id: int) -> str:
        """Was „vergessen“ löschen würde – steht in der Freigabe, damit man weiss, worüber man entscheidet."""
        with self.datenbank.sitzung() as db:
            eintrag = self.holen(db, eintrag_id)
            return f"Löscht aus dem Gedächtnis ({KATEGORIEN.get(eintrag.kategorie, eintrag.kategorie)}): „{eintrag.text}“"

    def vergessen(self, eintrag_id: int) -> dict[str, Any]:
        with self.datenbank.sitzung() as db:
            eintrag = self.loeschen(db, eintrag_id)
            return {"id": eintrag_id, "meldung": f"Vergessen: „{eintrag.text}“"}
