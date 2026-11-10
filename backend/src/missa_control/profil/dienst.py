"""Charakterprofil laden, speichern, vergleichen, als YAML austauschen und im Test-Chat ausprobieren."""

from __future__ import annotations

import difflib
import time
from pathlib import Path
from typing import Any

import httpx2
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.fehler import PanelFehler
from missa_control.modellverwaltung.dienst import ModellDienst, ModellFehler, rollen_name
from missa_control.profil.modelle import ProfilVersion

BEISPIEL_DATEI = "profil.example.yaml"


class Profil(BaseModel):
    """Missas Charakterprofil: feste Felder plus ein freier Systemprompt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="Missa", max_length=80)
    aussprache: str = Field(default="", max_length=200)
    wesen: str = Field(default="", max_length=8000)
    sprechweise: str = Field(default="", max_length=8000)
    darf: list[str] = Field(default_factory=list, max_length=100)
    darf_nicht: list[str] = Field(default_factory=list, max_length=100)
    fremde: str = Field(default="", max_length=8000)
    systemprompt: str = Field(default="", max_length=40000)

    def bereinigt(self) -> Profil:
        """Ohne leere Listeneinträge."""
        return self.model_copy(
            update={
                "darf": [regel.strip() for regel in self.darf if regel.strip()],
                "darf_nicht": [regel.strip() for regel in self.darf_nicht if regel.strip()],
            }
        )


FELD_TITEL = {
    "name": "Name",
    "aussprache": "Aussprache",
    "wesen": "Wesen",
    "sprechweise": "Sprechweise",
    "darf": "Regeln: darf",
    "darf_nicht": "Regeln: darf nicht",
    "fremde": "Verhalten gegenüber Fremden",
    "systemprompt": "Freier Systemprompt",
}


def systemprompt_bauen(profil: Profil) -> str:
    """Setzt aus den Feldern den Systemprompt zusammen, den das Modell bekommt."""
    teile = [f"Du bist {profil.name or 'Missa'}."]
    if profil.aussprache:
        teile[0] += f" Dein Name wird so ausgesprochen: {profil.aussprache}."
    if profil.wesen:
        teile.append(f"Dein Wesen:\n{profil.wesen}")
    if profil.sprechweise:
        teile.append(f"So sprichst du:\n{profil.sprechweise}")
    if profil.darf:
        teile.append("Das darfst du:\n" + "\n".join(f"- {regel}" for regel in profil.darf))
    if profil.darf_nicht:
        teile.append("Das darfst du nicht:\n" + "\n".join(f"- {regel}" for regel in profil.darf_nicht))
    if profil.fremde:
        teile.append(f"So verhältst du dich gegenüber Fremden:\n{profil.fremde}")
    if profil.systemprompt:
        teile.append(profil.systemprompt)
    return "\n\n".join(teile)


def profil_als_yaml(profil: Profil) -> str:
    daten = {
        "name": profil.name,
        "aussprache": profil.aussprache,
        "wesen": profil.wesen,
        "sprechweise": profil.sprechweise,
        "regeln": {"darf": profil.darf, "darf_nicht": profil.darf_nicht},
        "fremde": profil.fremde,
        "systemprompt": profil.systemprompt,
    }
    return yaml.dump(daten, Dumper=_BlockDumper, allow_unicode=True, sort_keys=False, width=100)


class _BlockDumper(yaml.SafeDumper):
    """Schreibt mehrzeilige Texte als lesbaren Block (`|`)."""


def _text_als_block(dumper: yaml.SafeDumper, wert: str) -> yaml.ScalarNode:
    stil = "|" if "\n" in wert else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", wert, style=stil)


_BlockDumper.add_representer(str, _text_als_block)


def profil_aus_yaml(text: str) -> Profil:
    """Liest ein Profil aus YAML. Fehler werden so erklärt, dass man sie beheben kann."""
    try:
        daten = yaml.safe_load(text)
    except yaml.YAMLError as fehler:
        stelle = getattr(fehler, "problem_mark", None)
        zeile = f" in Zeile {stelle.line + 1}" if stelle is not None else ""
        raise PanelFehler(
            422,
            f"Die Datei ist kein gültiges YAML{zeile}.",
            "Am einfachsten: das Profil im Panel exportieren und diese Datei als Vorlage verwenden.",
        ) from fehler
    if not isinstance(daten, dict):
        raise PanelFehler(
            422, "Die Datei enthält kein Profil.", "Erwartet werden Einträge wie „name: Missa“."
        )
    regeln = daten.pop("regeln", None)
    if isinstance(regeln, dict):
        daten.setdefault("darf", regeln.get("darf") or [])
        daten.setdefault("darf_nicht", regeln.get("darf_nicht") or [])
    elif regeln is not None:
        raise PanelFehler(422, "„regeln“ muss die Einträge „darf“ und „darf_nicht“ enthalten.")
    daten = {schluessel: ("" if wert is None else wert) for schluessel, wert in daten.items()}
    try:
        return Profil.model_validate(daten).bereinigt()
    except ValidationError as fehler:
        stellen = []
        for eintrag in fehler.errors():
            ort = ".".join(str(teil) for teil in eintrag["loc"])
            if eintrag["type"] == "extra_forbidden":
                stellen.append(f"„{ort}“ ist kein bekannter Eintrag")
            else:
                stellen.append(f"„{ort}“: {eintrag['msg']}")
        raise PanelFehler(
            422,
            "Das Profil ist ungültig: " + "; ".join(stellen),
            "Erlaubte Einträge: name, aussprache, wesen, sprechweise, regeln (darf, darf_nicht), fremde, systemprompt.",
        ) from fehler


def _als_zeilen(wert: Any) -> list[str]:
    if isinstance(wert, list):
        return [str(eintrag) for eintrag in wert]
    return str(wert or "").splitlines()


def unterschiede(alt: Profil, neu: Profil) -> list[dict[str, Any]]:
    """Vergleicht zwei Profile Feld für Feld. Gibt nur geänderte Felder zurück, mit markierten Zeilen."""
    ergebnis = []
    for feld, titel in FELD_TITEL.items():
        vorher, nachher = _als_zeilen(getattr(alt, feld)), _als_zeilen(getattr(neu, feld))
        if vorher == nachher:
            continue
        zeilen = []
        for zeile in difflib.ndiff(vorher, nachher):
            if zeile.startswith("? "):
                continue
            art = {"- ": "entfernt", "+ ": "neu"}.get(zeile[:2], "gleich")
            zeilen.append({"art": art, "text": zeile[2:]})
        ergebnis.append({"feld": feld, "titel": titel, "zeilen": zeilen})
    return ergebnis


def _version_ansicht(version: ProfilVersion) -> dict[str, Any]:
    return {"id": version.id, "erstellt": version.erstellt.isoformat(), "kommentar": version.kommentar}


class ProfilDienst:
    def __init__(self, modelle: ModellDienst, config_ordner: Path | None, testchat_sekunden: float) -> None:
        self.modelle = modelle
        self.config_ordner = config_ordner
        self.testchat_sekunden = testchat_sekunden

    # ---------- lesen ----------

    @staticmethod
    def _neueste(db: Session) -> ProfilVersion | None:
        return db.scalar(select(ProfilVersion).order_by(ProfilVersion.id.desc()).limit(1))

    @staticmethod
    def _profil(version: ProfilVersion | None) -> Profil:
        return Profil.model_validate(version.inhalt) if version else Profil()

    def aktuell(self, db: Session) -> dict[str, Any]:
        version = self._neueste(db)
        profil = self._profil(version)
        return {
            "profil": profil.model_dump(),
            "version": _version_ansicht(version) if version else None,
            "systemprompt": systemprompt_bauen(profil),
        }

    def fuer_clients(self, db: Session) -> dict[str, Any]:
        """Antwort von `GET /api/config/profile`."""
        version = self._neueste(db)
        if version is None:
            return {"vorhanden": False, "profil": None, "systemprompt": None, "version": None}
        profil = self._profil(version)
        return {
            "vorhanden": True,
            "profil": profil.model_dump(),
            "systemprompt": systemprompt_bauen(profil),
            "version": _version_ansicht(version),
        }

    # ---------- speichern und Versionen ----------

    def speichern(self, db: Session, profil: Profil, kommentar: str = "") -> dict[str, Any]:
        """Jede Speicherung ergibt eine neue Version – ausser es hat sich nichts geändert."""
        profil = profil.bereinigt()
        neueste = self._neueste(db)
        if neueste is not None and self._profil(neueste) == profil:
            return {**self.aktuell(db), "unveraendert": True}
        db.add(ProfilVersion(erstellt=zeit.jetzt(), kommentar=kommentar.strip(), inhalt=profil.model_dump()))
        db.commit()
        return {**self.aktuell(db), "unveraendert": False}

    @staticmethod
    def versionen(db: Session) -> list[dict[str, Any]]:
        return [
            _version_ansicht(v) for v in db.scalars(select(ProfilVersion).order_by(ProfilVersion.id.desc()))
        ]

    def _version(self, db: Session, version_id: int) -> ProfilVersion:
        version = db.get(ProfilVersion, version_id)
        if version is None:
            raise PanelFehler(404, "Diese Version gibt es nicht (mehr).")
        return version

    def version(self, db: Session, version_id: int) -> dict[str, Any]:
        """Eine frühere Version mit den Unterschieden zur aktuellen."""
        version = self._version(db, version_id)
        profil = self._profil(version)
        return {
            **_version_ansicht(version),
            "profil": profil.model_dump(),
            "unterschiede": unterschiede(profil, self._profil(self._neueste(db))),
        }

    def wiederherstellen(self, db: Session, version_id: int) -> dict[str, Any]:
        version = self._version(db, version_id)
        datum = version.erstellt.strftime("%d.%m.%Y %H:%M")
        return self.speichern(db, self._profil(version), f"Wiederhergestellt: Version vom {datum} UTC")

    # ---------- Beispiel ----------

    def beispiel(self) -> Profil:
        datei = (self.config_ordner / BEISPIEL_DATEI) if self.config_ordner else None
        if datei is None or not datei.is_file():
            raise PanelFehler(
                404, "Das Beispielprofil wurde nicht gefunden.", f"Erwartet in config/{BEISPIEL_DATEI}."
            )
        return profil_aus_yaml(datei.read_text(encoding="utf-8"))

    # ---------- Test-Chat ----------

    async def testchat(self, profil: Profil, rolle: str, nachrichten: list[dict[str, str]]) -> dict[str, Any]:
        """Schickt den bisherigen Verlauf mit dem (auch ungespeicherten) Profil direkt ans Modell."""
        verlauf = [{"role": "system", "content": systemprompt_bauen(profil.bereinigt())}]
        for nachricht in nachrichten:
            sprecher = "assistant" if nachricht.get("von") == "missa" else "user"
            verlauf.append({"role": sprecher, "content": str(nachricht.get("text", ""))})
        start = time.monotonic()
        try:
            antwort = await self.modelle.chat(
                rollen_name(rolle),
                {"messages": verlauf},
                zeitlimit=httpx2.Timeout(self.testchat_sekunden, connect=min(10.0, self.testchat_sekunden)),
            )
        except ModellFehler as fehler:
            sekunden = round(self.testchat_sekunden)
            if time.monotonic() - start >= self.testchat_sekunden * 0.95:
                raise PanelFehler(
                    504,
                    f"Das Modell hat nicht innerhalb von {sekunden} Sekunden geantwortet.",
                    "Der Test-Chat wartet höchstens so lange. Mit der Rolle „schnell“ versuchen oder unter "
                    "„Modelle“ prüfen, ob das Modell ausgelastet ist.",
                ) from fehler
            raise PanelFehler(
                502 if fehler.status >= 500 else 409, fehler.meldung, fehler.hinweis
            ) from fehler
        try:
            text = antwort.inhalt["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            fehlertext = (
                (antwort.inhalt.get("error") or {}).get("message")
                if isinstance(antwort.inhalt, dict)
                else None
            )
            raise PanelFehler(
                502,
                f"Das Modell „{antwort.ziel.name}“ hat keine verwertbare Antwort geliefert.",
                fehlertext or "Unter „Modelle“ die Verbindung testen.",
            ) from None
        return {
            "antwort": text,
            "modell": antwort.ziel.name,
            "dauer_ms": round((time.monotonic() - start) * 1000),
        }
