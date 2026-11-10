"""Art `python`: Funktionen aus der `main.py` einer Integration."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import re
import sys
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from missa_control.integrationen.fehlertexte import fehler_erklaeren
from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, FunktionsInfo, IntegrationsFehler, TestErgebnis
from missa_control.sdk import FUNKTION_MERKMAL, TEST_MERKMAL, FunktionsAngaben

_KONTEXT_NAMEN = ("kontext", "ctx", "context")
_NAME_MUSTER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DOC_PARAMETER = re.compile(r"^\s*[-*]?\s*`?(\w+)`?\s*(?:\([^)]*\))?\s*[:–—-]\s+(.+)$")


@dataclass
class GeladeneFunktion:
    info: FunktionsInfo
    fn: Callable[..., Any]
    modell: type[BaseModel]
    braucht_kontext: bool
    # Sagt in einem Satz, was der Aufruf bewirken würde (für die Freigabe) – siehe `@funktion(vorschau=...)`.
    vorschau: Callable[..., Any] | None = None


@dataclass
class GeladenesModul:
    funktionen: dict[str, GeladeneFunktion]
    test: Callable[..., Any] | None
    modul: types.ModuleType


_geladen: dict[Path, tuple[tuple[tuple[str, int], ...], GeladenesModul]] = {}


def _stand(ordner: Path) -> tuple[tuple[str, int], ...]:
    """Änderungsstand aller Python-Dateien – ändert er sich, wird neu geladen."""
    return tuple(sorted((str(datei), datei.stat().st_mtime_ns) for datei in ordner.rglob("*.py")))


def modul_laden(ordner: Path, manifest_id: str) -> GeladenesModul:
    """Lädt `main.py` (bei Änderungen neu) und sammelt alle mit `@funktion` markierten Funktionen."""
    stand = _stand(ordner)
    vorhanden = _geladen.get(ordner)
    if vorhanden is not None and vorhanden[0] == stand:
        return vorhanden[1]

    paket_name = "missa_integration_" + manifest_id.replace("-", "_")
    for name in [name for name in sys.modules if name == paket_name or name.startswith(paket_name + ".")]:
        del sys.modules[name]
    paket = types.ModuleType(paket_name)
    paket.__path__ = [str(ordner)]
    sys.modules[paket_name] = paket
    importlib.invalidate_caches()
    try:
        modul = importlib.import_module(f"{paket_name}.main")
    except SyntaxError as fehler:
        raise IntegrationsFehler(
            f"main.py enthält einen Syntaxfehler in Zeile {fehler.lineno}: {fehler.msg}",
            "Bitte den Fehler in main.py korrigieren und erneut testen.",
        ) from fehler
    except ModuleNotFoundError as fehler:
        raise IntegrationsFehler(
            f"main.py braucht ein Python-Paket, das nicht installiert ist: {fehler.name}",
            "Im Panel stehen u. a. httpx2, pydantic und pyyaml bereit. Weitere Pakete müssen ins Image "
            "(backend/pyproject.toml) aufgenommen werden.",
        ) from fehler
    except Exception as fehler:
        raise IntegrationsFehler(
            f"main.py konnte nicht geladen werden: {type(fehler).__name__}: {fehler}",
            "Der Fehler tritt schon beim Laden der Datei auf (ausserhalb der Funktionen).",
        ) from fehler

    funktionen: dict[str, GeladeneFunktion] = {}
    test: Callable[..., Any] | None = None
    for objekt in vars(modul).values():
        if not callable(objekt) or getattr(objekt, "__module__", None) != modul.__name__:
            continue
        if getattr(objekt, TEST_MERKMAL, False):
            test = objekt
        angaben = getattr(objekt, FUNKTION_MERKMAL, None)
        if isinstance(angaben, FunktionsAngaben):
            geladene = _funktion_beschreiben(objekt, angaben)
            if geladene.info.name in funktionen:
                raise IntegrationsFehler(
                    f"Der Funktionsname „{geladene.info.name}“ kommt in main.py doppelt vor."
                )
            funktionen[geladene.info.name] = geladene

    ergebnis = GeladenesModul(funktionen=funktionen, test=test, modul=modul)
    _geladen[ordner] = (stand, ergebnis)
    return ergebnis


def _funktion_beschreiben(fn: Callable[..., Any], angaben: FunktionsAngaben) -> GeladeneFunktion:
    name = angaben.name or fn.__name__
    if not _NAME_MUSTER.match(name):
        raise IntegrationsFehler(
            f"Der Funktionsname „{name}“ ist ungültig.",
            "Erlaubt sind Buchstaben, Ziffern und Unterstriche (höchstens 64 Zeichen).",
        )
    signatur = inspect.signature(fn)
    kurz, parameter_texte = _docstring_lesen(inspect.getdoc(fn) or "", set(signatur.parameters))
    try:
        hinweise = typing.get_type_hints(fn, include_extras=True)
    except Exception as fehler:
        raise IntegrationsFehler(
            f"Die Typ-Hinweise von „{name}“ lassen sich nicht auswerten: {fehler}",
            "Sind alle verwendeten Typen in main.py importiert?",
        ) from fehler

    felder: dict[str, Any] = {}
    braucht_kontext = False
    for index, parameter in enumerate(signatur.parameters.values()):
        typ = hinweise.get(parameter.name, Any)
        if index == 0 and (parameter.name in _KONTEXT_NAMEN or typ is Kontext):
            braucht_kontext = True
            continue
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise IntegrationsFehler(
                f"„{name}“ verwendet *args oder **kwargs – das geht bei Funktionen für Missa nicht.",
                "Bitte jeden Parameter einzeln mit Typ-Hinweis angeben.",
            )
        standard = ... if parameter.default is inspect.Parameter.empty else parameter.default
        felder[parameter.name] = (typ, Field(standard, description=parameter_texte.get(parameter.name)))

    try:
        modell = create_model(f"Parameter_{name}", __config__=ConfigDict(extra="forbid"), **felder)
        schema = _schema_aufraeumen(modell.model_json_schema())
    except Exception as fehler:
        raise IntegrationsFehler(
            f"Die Parameter von „{name}“ lassen sich nicht beschreiben: {fehler}",
            "Unterstützt werden einfache Typen (str, int, float, bool), Listen, Wörterbücher, Literal, Optional.",
        ) from fehler

    info = FunktionsInfo(
        name=name,
        beschreibung=(angaben.beschreibung or kurz or name).strip(),
        parameter=schema,
        schreibend=angaben.schreibend,
    )
    return GeladeneFunktion(
        info=info, fn=fn, modell=modell, braucht_kontext=braucht_kontext, vorschau=angaben.vorschau
    )


def _docstring_lesen(doc: str, parameter_namen: set[str]) -> tuple[str, dict[str, str]]:
    """Zeilen der Form `name: Text` beschreiben Parameter; der erste Absatz ohne sie ist die Beschreibung."""
    parameter: dict[str, str] = {}
    beschreibung: list[str] = []
    erster_absatz = True
    for zeile in doc.strip().splitlines():
        if not zeile.strip():
            erster_absatz = not beschreibung  # leere Zeile beendet den ersten Absatz (sobald er Text hat)
            continue
        treffer = _DOC_PARAMETER.match(zeile)
        if treffer and treffer.group(1) in parameter_namen:
            parameter[treffer.group(1)] = treffer.group(2).strip()
        elif erster_absatz:
            beschreibung.append(zeile.strip())
    return " ".join(beschreibung), parameter


def _schema_aufraeumen(schema: dict[str, Any]) -> dict[str, Any]:
    """Entfernt die automatisch erzeugten Titel – sie blähen die Beschreibung für das Modell nur auf."""

    def ohne_titel(wert: Any, ist_eigenschaften: bool = False) -> Any:
        if isinstance(wert, dict):
            return {
                schluessel: ohne_titel(inhalt, schluessel in ("properties", "$defs"))
                for schluessel, inhalt in wert.items()
                if ist_eigenschaften or schluessel != "title"
            }
        if isinstance(wert, list):
            return [ohne_titel(eintrag) for eintrag in wert]
        return wert

    sauber = ohne_titel(schema)
    sauber.setdefault("type", "object")
    sauber.setdefault("properties", {})
    return sauber


def _ergebnis_vereinfachen(wert: Any) -> Any:
    if isinstance(wert, BaseModel):
        return wert.model_dump(mode="json")
    if dataclasses.is_dataclass(wert) and not isinstance(wert, type):
        return dataclasses.asdict(wert)
    return wert


async def _ausfuehren(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Führt eine Funktion aus – asynchrone direkt, normale in einem eigenen Thread."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


def _geladene_funktion(kontext: Kontext, name: str) -> GeladeneFunktion:
    if kontext.ordner is None:
        raise IntegrationsFehler("Der Ordner der Integration fehlt.")
    geladene = modul_laden(kontext.ordner, kontext.manifest.id).funktionen.get(name)
    if geladene is None:
        raise IntegrationsFehler(
            f"Die Funktion „{name}“ gibt es in main.py nicht mehr.",
            "Unter „Integrationen“ erneut testen, damit die Funktionsliste aktualisiert wird.",
        )
    return geladene


def _parameter_pruefen(geladene: GeladeneFunktion, name: str, argumente: dict[str, Any]) -> dict[str, Any]:
    try:
        geprueft = geladene.modell(**argumente)
    except ValidationError as fehler:
        stellen = "; ".join(
            f"{'.'.join(str(teil) for teil in eintrag['loc']) or 'Parameter'}: {eintrag['msg']}"
            for eintrag in fehler.errors()
        )
        raise IntegrationsFehler(
            f"Ungültige Parameter für „{name}“: {stellen}",
            "Die erwarteten Parameter stehen in der Beschreibung der Funktion.",
        ) from fehler
    return {feld: getattr(geprueft, feld) for feld in type(geprueft).model_fields}


class PythonAdapter:
    art = "python"

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        if kontext.ordner is None:
            raise IntegrationsFehler("Der Ordner der Integration fehlt.")
        modul = modul_laden(kontext.ordner, kontext.manifest.id)
        meldung = "Integration geladen."
        ergebnis = TestErgebnis(ok=True, meldung=meldung)
        if modul.test is not None:
            antwort = await _ausfuehren(modul.test, kontext)
            if isinstance(antwort, str) and antwort.strip():
                ergebnis.meldung = antwort.strip()
            elif isinstance(antwort, dict):
                ergebnis.meldung = str(antwort.get("meldung") or meldung)
                ergebnis.details = [str(zeile) for zeile in antwort.get("details", [])]
                ergebnis.optionen = {
                    feld: [
                        {"wert": str(o["wert"]), "titel": str(o.get("titel", o["wert"]))}
                        if isinstance(o, dict)
                        else {"wert": str(o), "titel": str(o)}
                        for o in optionen
                    ]
                    for feld, optionen in dict(antwort.get("optionen", {})).items()
                }
        ergebnis.funktionen = [geladene.info for geladene in modul.funktionen.values()]
        ergebnis.zustand = dict(kontext.zustand)
        if not ergebnis.funktionen:
            ergebnis.details.append("Hinweis: main.py enthält noch keine mit @funktion markierte Funktion.")
        return ergebnis

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        geladene = _geladene_funktion(kontext, funktion.name)
        werte = _parameter_pruefen(geladene, funktion.name, argumente)
        args = (kontext,) if geladene.braucht_kontext else ()
        try:
            wert = await _ausfuehren(geladene.fn, *args, **werte)
        except IntegrationsFehler:
            raise
        except Exception as fehler:
            kontext.log.exception("Fehler in Funktion %s", funktion.name)
            meldung, hinweis = fehler_erklaeren(fehler)
            if meldung.startswith("Unerwarteter Fehler"):
                meldung = f"Fehler in „{funktion.name}“: {type(fehler).__name__}: {fehler}"
                hinweis = "Der Fehler kommt aus dem Code der Integration (main.py). Details stehen im Protokoll des Panels."
            raise IntegrationsFehler(meldung, hinweis) from fehler
        return AufrufErgebnis(wert=_ergebnis_vereinfachen(wert))

    async def vorschau(self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]) -> str | None:
        """Der Satz für die Freigabe – oder `None`, wenn die Funktion keine Vorschau hat.

        Ungültige Parameter und `Fehler` aus der Vorschau kommen als `IntegrationsFehler` zurück:
        dann wird gar nicht erst nachgefragt.
        """
        geladene = _geladene_funktion(kontext, funktion.name)
        if geladene.vorschau is None:
            return None
        werte = _parameter_pruefen(geladene, funktion.name, argumente)
        args = (kontext,) if geladene.braucht_kontext else ()
        text = await _ausfuehren(geladene.vorschau, *args, **werte)
        return (str(text).strip() or None) if text is not None else None
