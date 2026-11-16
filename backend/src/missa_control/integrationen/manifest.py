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

import re
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

Art = Literal["api", "mcp", "openapi", "python", "webhook", "geraet"]
ART_NAMEN = {
    "api": "API",
    "mcp": "MCP-Server",
    "openapi": "REST-API",
    "python": "Python",
    "webhook": "Webhook",
    "geraet": "Gerät",
}

FeldTyp = Literal["text", "zahl", "url", "auswahl", "zugang", "schalter", "datei", "endpunkte"]
Methode = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
METHODEN: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE")
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


ParameterTyp = Literal["string", "integer", "number", "boolean", "array"]


class EndpunktParameter(BaseModel):
    """Ein Parameter eines Endpunkts aus einer Vorlage – wird ein Parameter der Funktion für Missa.

    `ort`: `query` (URL-Parameter, Standard) oder `json` (Feld im JSON-Inhalt der Anfrage).
    `url_name`: so heisst er in der URL bzw. im JSON, falls anders als `name` (z. B. `via[]`).
    """

    model_config = ConfigDict(extra="forbid")

    name: Kennung
    typ: ParameterTyp = "string"
    beschreibung: str = Field(default="", max_length=300)
    pflicht: bool = False
    ort: Literal["query", "json"] = "query"
    url_name: str | None = Field(default=None, max_length=60)
    optionen: list[str] = Field(default_factory=list)
    standard: str | int | float | bool | None = None


class Endpunkt(BaseModel):
    """Ein Endpunkt einer API, aus dem eine eigene Funktion wird (Feldtyp `endpunkte`).

    `pfad` ist relativ zur Adresse der API und darf Platzhalter enthalten, z. B. `/artikel/{id}`.
    GET ist lesend, alles andere schreibend.
    """

    model_config = ConfigDict(extra="forbid")

    name: Kennung
    methode: Methode = "GET"
    pfad: str = Field(min_length=1, max_length=300)
    beschreibung: str = Field(default="", max_length=500)
    # Nur in Vorlagen (integration.yaml): genau beschriebene Parameter …
    parameter: list[EndpunktParameter] = Field(default_factory=list)
    # … feste URL-Parameter und feste Felder im JSON-Inhalt. `{{feld}}` setzt einen Formularwert ein,
    # z. B. `topic: "{{thema}}"`.
    query: dict[str, str] = Field(default_factory=dict)
    daten: dict[str, Any] = Field(default_factory=dict)
    # Lesend oder schreibend – Standard: GET ist lesend, alles andere schreibend.
    schreibend: bool | None = None

    @field_validator("methode", mode="before")
    @classmethod
    def _gross(cls, wert: Any) -> Any:
        return wert.strip().upper() if isinstance(wert, str) else wert

    @field_validator("pfad")
    @classmethod
    def _pfad(cls, wert: str) -> str:
        wert = wert.strip()
        if not wert.startswith("/"):
            wert = "/" + wert
        if "://" in wert or wert.startswith("//") or "\\" in wert:
            raise ValueError(
                "Der Pfad darf keine vollständige Adresse sein – nur der Teil nach der Adresse der API"
            )
        if ".." in wert.split("?")[0].split("/"):
            raise ValueError("Der Pfad darf kein „..“ enthalten")
        return wert

    @property
    def ist_schreibend(self) -> bool:
        return self.schreibend if self.schreibend is not None else self.methode != "GET"

    def platzhalter(self) -> list[str]:
        """Die Namen der Platzhalter im Pfad, z. B. `["id"]` für `/artikel/{id}`."""
        return re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", self.pfad)


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
    # Feld erscheint nur, wenn ein anderes Feld einen dieser Werte hat, z. B. {key_art: [header, query]}.
    sichtbar_wenn: dict[str, list[str]] = Field(default_factory=dict)

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
    # Karte steht im Katalog ganz vorne und ist hervorgehoben.
    hervorgehoben: bool = False
    # Gruppe im Katalog, z. B. „Vorlagen“ (leer = ohne Gruppe).
    gruppe: str = Field(default="", max_length=40)
    # Nur bei `art: api` – eine Vorlage nur mit YAML: feste Adresse (sonst aus dem Feld „adresse“)
    # und fest beschriebene Endpunkte. Gibt es `endpunkte`, sucht das Panel keine Beschreibung.
    basis_url: str | None = Field(default=None, max_length=300)
    endpunkte: list[Endpunkt] = Field(default_factory=list)

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

    @model_validator(mode="after")
    def _vorlage(self) -> Manifest:
        if (self.basis_url or self.endpunkte) and self.art != "api":
            raise ValueError("„basis_url“ und „endpunkte“ gibt es nur bei „art: api“")
        if self.basis_url and not re.match(r"^https?://[^\s/]+", self.basis_url):
            raise ValueError("„basis_url“ muss mit http:// oder https:// beginnen")
        if self.art == "api" and not self.basis_url and not self.feld("adresse"):
            raise ValueError("Bei „art: api“ braucht es „basis_url“ oder ein Feld „adresse“")
        namen = [endpunkt.name for endpunkt in self.endpunkte]
        doppelt = sorted({name for name in namen if namen.count(name) > 1})
        if doppelt:
            raise ValueError(f"Endpunkte kommen mehrfach vor: {', '.join(doppelt)}")
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
