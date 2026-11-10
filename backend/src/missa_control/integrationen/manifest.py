"""Das Manifest `integration.yaml`: beschreibt eine Integration und ihr Formular.

Beispiel:

    id: wetter
    name: Wetter
    beschreibung: Aktuelles Wetter abfragen
    symbol: "🌦️"
    art: python
    version: 1.0.0
    felder:
      - name: ort
        titel: Ort
        typ: text
        pflicht: true
    standardrechte:
      wetter_aktuell: erlaubt
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from missa_control.integrationen.typen import Recht

MANIFEST_DATEI = "integration.yaml"

Art = Literal["mcp", "openapi", "python", "webhook", "geraet"]
ART_NAMEN = {
    "mcp": "MCP-Server",
    "openapi": "REST-API",
    "python": "Python",
    "webhook": "Webhook",
    "geraet": "Gerät",
}

FeldTyp = Literal["text", "zahl", "url", "auswahl", "zugang", "schalter", "datei"]
ZugangTyp = Literal["api_key", "benutzer_passwort", "bearer_token"]

Kennung = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]
ManifestId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=40)]
Kurztext = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wert: str
    titel: str = ""

    @model_validator(mode="before")
    @classmethod
    def _kurzform(cls, daten: Any) -> Any:
        """Erlaubt die Kurzform `- wert` statt `- {wert: ..., titel: ...}`."""
        if isinstance(daten, str | int | float):
            return {"wert": str(daten), "titel": str(daten)}
        return daten

    @model_validator(mode="after")
    def _titel(self) -> Option:
        if not self.titel:
            self.titel = self.wert
        return self


class Feld(BaseModel):
    """Ein Feld im automatisch erzeugten Formular."""

    model_config = ConfigDict(extra="forbid")

    name: Kennung
    titel: Kurztext
    typ: FeldTyp = "text"
    pflicht: bool = False
    hilfe: str = ""
    platzhalter: str = ""
    standard: str | int | float | bool | None = None
    # typ: auswahl
    optionen: list[Option] = Field(default_factory=list)
    # typ: zugang – welche Arten von Zugängen passen (leer = alle)
    zugang_typen: list[ZugangTyp] = Field(default_factory=list)
    # typ: datei – erlaubte Endungen, z. B. [".json", ".yaml"]
    endungen: list[str] = Field(default_factory=list)
    # Feld erscheint erst nach erfolgreichem Test (Auswahl kommt aus dem Testergebnis).
    nach_test: bool = False

    @model_validator(mode="after")
    def _pruefen(self) -> Feld:
        if self.typ == "auswahl" and not self.optionen and not self.nach_test:
            raise ValueError("ein Feld vom Typ „auswahl“ braucht „optionen“ (oder „nach_test: true“)")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ManifestId
    name: Kurztext
    beschreibung: str = Field(min_length=1, max_length=500)
    symbol: str = Field(default="🧩", max_length=16)
    art: Art
    version: str = Field(default="1.0.0", max_length=30)
    felder: list[Feld] = Field(default_factory=list)
    # Funktionsname → Recht; nicht genannte Funktionen: lesend = erlaubt, schreibend = nachfragen.
    standardrechte: dict[str, Recht] = Field(default_factory=dict)
    # Darf die Integration mehrmals eingerichtet werden (z. B. mehrere MCP-Server)?
    mehrfach: bool = True
    # Vorsilbe der Funktionsnamen (Standard: aus dem Namen der eingerichteten Integration).
    kennung: Kennung | None = None
    # Längerer Hinweis über dem Formular.
    hinweis: str = ""

    @field_validator("version", mode="before")
    @classmethod
    def _version_als_text(cls, wert: Any) -> Any:
        return str(wert) if isinstance(wert, int | float) else wert

    @model_validator(mode="after")
    def _felder_eindeutig(self) -> Manifest:
        namen = [feld.name for feld in self.felder]
        doppelt = sorted({name for name in namen if namen.count(name) > 1})
        if doppelt:
            raise ValueError(f"Feldnamen kommen mehrfach vor: {', '.join(doppelt)}")
        return self

    def feld(self, name: str) -> Feld | None:
        return next((feld for feld in self.felder if feld.name == name), None)


class ManifestFehler(Exception):
    """Das Manifest ist ungültig. `meldungen` erklärt jede Stelle einzeln."""

    def __init__(self, meldungen: list[str]) -> None:
        super().__init__("; ".join(meldungen))
        self.meldungen = meldungen


_FEHLER_TEXTE = {
    "missing": "fehlt (Pflichtangabe)",
    "extra_forbidden": "ist kein bekannter Eintrag (Tippfehler?)",
    "string_pattern_mismatch": "hat ein ungültiges Format (nur Kleinbuchstaben, Ziffern und - bzw. _, am Anfang ein Buchstabe)",
    "string_too_short": "darf nicht leer sein",
    "string_too_long": "ist zu lang",
    "string_type": "muss ein Text sein",
    "bool_type": "muss true oder false sein",
    "bool_parsing": "muss true oder false sein",
    "list_type": "muss eine Liste sein",
    "dict_type": "muss aus Schlüssel und Wert bestehen",
    "model_type": "muss aus Schlüssel und Wert bestehen",
}


def fehler_als_text(fehler: ValidationError) -> list[str]:
    """Übersetzt pydantic-Fehler in verständliche deutsche Sätze."""
    meldungen = []
    for eintrag in fehler.errors():
        ort = " → ".join(str(teil) for teil in eintrag["loc"]) or "Manifest"
        art = eintrag["type"]
        if art == "literal_error":
            erlaubt = eintrag.get("ctx", {}).get("expected", "")
            text = f"hat einen ungültigen Wert (erlaubt: {erlaubt})"
        elif art == "value_error":
            text = str(eintrag.get("ctx", {}).get("error", eintrag["msg"]))
        else:
            text = _FEHLER_TEXTE.get(art, eintrag["msg"])
        meldungen.append(f"„{ort}“ {text}")
    return meldungen


def manifest_aus_text(text: str) -> Manifest:
    try:
        daten = yaml.safe_load(text)
    except yaml.YAMLError as fehler:
        stelle = getattr(fehler, "problem_mark", None)
        zeile = f" in Zeile {stelle.line + 1}" if stelle is not None else ""
        raise ManifestFehler(
            [f"Die Datei ist kein gültiges YAML{zeile}: {getattr(fehler, 'problem', fehler)}"]
        ) from fehler
    if not isinstance(daten, dict):
        raise ManifestFehler(["Die Datei muss aus Einträgen der Form „schlüssel: wert“ bestehen."])
    try:
        return Manifest.model_validate(daten)
    except ValidationError as fehler:
        raise ManifestFehler(fehler_als_text(fehler)) from fehler


def manifest_laden(ordner: Path) -> Manifest:
    datei = ordner / MANIFEST_DATEI
    if not datei.is_file():
        raise ManifestFehler([f"Die Datei {MANIFEST_DATEI} fehlt."])
    try:
        text = datei.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as fehler:
        raise ManifestFehler([f"{MANIFEST_DATEI} kann nicht gelesen werden: {fehler}"]) from fehler
    return manifest_aus_text(text)
