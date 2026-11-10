"""Eingebaute Integration „Home Assistant“.

Zwei Wege, je nachdem, was Home Assistant anbietet:

- **MCP-Server von Home Assistant** (Integration „Model Context Protocol Server“): Ist er eingerichtet,
  reicht das Panel seine Werkzeuge an Missa durch. Welche Geräte dabei sichtbar sind, bestimmt Home Assistant.
- **REST-API** (sonst): Geräte anzeigen, Zustände lesen, ein- und ausschalten, Dienste aufrufen.

Beim Testen wird der Weg festgestellt und gemerkt.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import anyio

from missa_control.integrationen.adapter.mcp import mcp_verbinden, werkzeuge_auflisten
from missa_control.sdk import (
    AufrufErgebnis,
    Fehler,
    FunktionsInfo,
    Kontext,
    aufruf_weiterer_funktionen,
    funktion,
    verbindungstest,
    weitere_funktionen,
)

# Hier bietet Home Assistant seinen MCP-Server an (neuere Versionen zuerst, dann die ältere SSE-Adresse).
MCP_PFADE = ("/api/mcp", "/mcp_server/sse")
MCP_SEKUNDEN = 15.0
HOECHSTENS = 200

# Art (Domäne) in Home Assistant → Bezeichnung im Panel
ARTEN = {
    "light": "Lichter",
    "switch": "Schalter",
    "sensor": "Sensoren",
    "binary_sensor": "Melder",
    "climate": "Heizung/Klima",
    "cover": "Storen/Rollläden",
    "media_player": "Mediengeräte",
    "lock": "Schlösser",
    "fan": "Ventilatoren",
    "vacuum": "Staubsauger",
    "camera": "Kameras",
    "scene": "Szenen",
    "script": "Skripte",
    "automation": "Automationen",
    "person": "Personen",
    "weather": "Wetter",
}
# So darf Missa die Art auch auf Deutsch nennen.
_DEUTSCH = {
    "licht": "light",
    "lichter": "light",
    "lampe": "light",
    "lampen": "light",
    "schalter": "switch",
    "steckdose": "switch",
    "steckdosen": "switch",
    "sensor": "sensor",
    "sensoren": "sensor",
    "melder": "binary_sensor",
    "heizung": "climate",
    "klima": "climate",
    "thermostat": "climate",
    "storen": "cover",
    "rollladen": "cover",
    "rollläden": "cover",
    "jalousie": "cover",
    "schloss": "lock",
    "szene": "scene",
    "szenen": "scene",
}
_KENNUNG = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_DIENST = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)$")


# ---------------------------------------------------------------------- Verbindung


def _basis(kontext: Kontext) -> str:
    return str(kontext.konfig["url"]).rstrip("/")


def _kopf(kontext: Kontext) -> dict[str, str]:
    return {"Authorization": f"Bearer {kontext.zugang('zugang').wert}"}


async def _rest(kontext: Kontext, methode: str, pfad: str, daten: dict[str, Any] | None = None) -> Any:
    async with kontext.http(headers=_kopf(kontext)) as client:
        antwort = await client.request(methode, _basis(kontext) + pfad, json=daten)
    antwort.raise_for_status()
    try:
        return antwort.json()
    except ValueError as fehler:
        raise Fehler(
            "Unter dieser Adresse antwortet kein Home Assistant.",
            "Bitte die Adresse prüfen, z. B. http://homeassistant.local:8123",
        ) from fehler


async def _mcp_suchen(kontext: Kontext) -> list[FunktionsInfo] | None:
    """Sucht den MCP-Server von Home Assistant. Gibt seine Werkzeuge zurück – oder `None`, wenn es ihn nicht gibt."""
    for pfad in MCP_PFADE:
        try:
            with anyio.fail_after(MCP_SEKUNDEN):
                async with mcp_verbinden(_basis(kontext) + pfad, _kopf(kontext)) as (client, transport):
                    werkzeuge = await werkzeuge_auflisten(client)
        except Exception:  # nicht eingerichtet, ältere Version, anderer Pfad: dann eben der nächste Weg
            continue
        kontext.zustand.update(weg="mcp", mcp_url=_basis(kontext) + pfad, mcp_transport=transport)
        return werkzeuge
    kontext.zustand.update(weg="rest", mcp_url=None, mcp_transport=None)
    return None


def _rest_weg(kontext: Kontext) -> bool:
    return kontext.zustand.get("weg") != "mcp"


def _name(zustand: dict[str, Any]) -> str:
    return str((zustand.get("attributes") or {}).get("friendly_name") or zustand.get("entity_id", ""))


def _uebersicht(zustaende: list[dict[str, Any]]) -> list[str]:
    """„23 Geräte und Entitäten: 8 Lichter, 4 Schalter, …“ plus ein paar Namen als Beispiel."""
    arten = Counter(str(z.get("entity_id", "")).split(".", 1)[0] for z in zustaende)
    bekannte = [(anzahl, ARTEN[art]) for art, anzahl in arten.most_common() if art in ARTEN]
    weitere = sum(anzahl for art, anzahl in arten.items() if art not in ARTEN)
    teile = [f"{anzahl} {name}" for anzahl, name in bekannte[:6]]
    rest = sum(anzahl for anzahl, _ in bekannte[6:]) + weitere
    if rest:
        teile.append(f"{rest} weitere")
    zeilen = [f"{len(zustaende)} Geräte und Entitäten: " + ", ".join(teile)]
    steuerbar = [
        z
        for z in zustaende
        if str(z.get("entity_id", "")).split(".", 1)[0] in ("light", "switch", "climate", "cover")
    ]
    beispiele = [_name(z) for z in (steuerbar or zustaende)[:5]]
    if beispiele:
        zeilen.append("Zum Beispiel: " + ", ".join(beispiele))
    return zeilen


@verbindungstest
async def testen(kontext: Kontext) -> dict:
    konfig = await _rest(kontext, "GET", "/api/config")
    zustaende = await _rest(kontext, "GET", "/api/states")
    if not isinstance(konfig, dict) or not isinstance(zustaende, list):
        raise Fehler(
            "Unter dieser Adresse antwortet kein Home Assistant.",
            "Bitte die Adresse prüfen, z. B. http://homeassistant.local:8123",
        )
    werkzeuge = await _mcp_suchen(kontext)
    if werkzeuge is None:
        weg = "Verbindung über die REST-API (der MCP-Server von Home Assistant ist nicht eingerichtet)"
    else:
        weg = f"Verbindung über den MCP-Server von Home Assistant ({len(werkzeuge)} Funktionen)"
    ort = konfig.get("location_name") or "Home Assistant"
    version = f" (Version {konfig['version']})" if konfig.get("version") else ""
    return {
        "meldung": f"Verbunden mit „{ort}“{version} – {len(zustaende)} Geräte und Entitäten gefunden.",
        "details": [*_uebersicht(zustaende), weg],
    }


# ---------------------------------------------------------------------- Weg 1: MCP-Server von Home Assistant


@weitere_funktionen
async def mcp_werkzeuge(kontext: Kontext) -> list[FunktionsInfo]:
    """Im MCP-Betrieb: die Werkzeuge, die Home Assistant selbst anbietet."""
    if _rest_weg(kontext):
        return []
    werkzeuge = await _mcp_suchen(kontext) or []
    for werkzeug in werkzeuge:
        if werkzeug.name.lower().startswith("get"):
            werkzeug.schreibend = False  # z. B. GetLiveContext: liest nur
    return werkzeuge


@aufruf_weiterer_funktionen
async def mcp_aufrufen(kontext: Kontext, name: str, argumente: dict[str, Any]) -> AufrufErgebnis:
    url = kontext.zustand.get("mcp_url")
    if not url:
        raise Fehler(
            "Der MCP-Server von Home Assistant ist nicht (mehr) eingerichtet.",
            f"Unter „Integrationen“ → „{kontext.name}“ auf „Testen“ klicken – dann wird der Weg neu bestimmt.",
        )
    async with mcp_verbinden(url, _kopf(kontext), bekannt=kontext.zustand.get("mcp_transport")) as (
        client,
        _,
    ):
        ergebnis = await client.call_tool(name, argumente)
    return AufrufErgebnis(
        mcp_inhalt=list(ergebnis.content),
        strukturiert=ergebnis.structured_content,
        ist_fehler=bool(ergebnis.is_error),
    )


# ---------------------------------------------------------------------- Weg 2: REST-API


def _art(eingabe: str) -> str:
    art = eingabe.strip().lower()
    return _DEUTSCH.get(art, art)


def _kurz(zustand: dict[str, Any]) -> dict[str, Any]:
    eigenschaften = zustand.get("attributes") or {}
    wert = str(zustand.get("state", ""))
    einheit = eigenschaften.get("unit_of_measurement")
    return {
        "id": zustand.get("entity_id"),
        "name": _name(zustand),
        "zustand": f"{wert} {einheit}" if einheit else wert,
        "art": str(zustand.get("entity_id", "")).split(".", 1)[0],
    }


@funktion(
    beschreibung=(
        "Listet Geräte und Entitäten in Home Assistant mit ihrem aktuellen Zustand auf. "
        "Die Kennung (id, z. B. light.wohnzimmer) wird zum Lesen und Schalten gebraucht."
    ),
    schreibend=False,
    wenn=_rest_weg,
)
async def geraete_anzeigen(kontext: Kontext, art: str = "", suche: str = "", anzahl: int = 50) -> dict:
    """
    art: Nur diese Art, z. B. light (Licht), switch (Schalter), sensor, climate (Heizung), cover (Storen)
    suche: Nur Geräte, deren Name oder Kennung dieses Wort enthält, z. B. „wohnzimmer“
    anzahl: Wie viele höchstens zurückkommen (1 bis 200)
    """
    zustaende = await _rest(kontext, "GET", "/api/states")
    gewuenscht, wort = _art(art), suche.strip().lower()
    passende = [
        z
        for z in zustaende
        if (not gewuenscht or str(z.get("entity_id", "")).startswith(gewuenscht + "."))
        and (not wort or wort in _name(z).lower() or wort in str(z.get("entity_id", "")).lower())
    ]
    passende.sort(key=lambda z: (str(z.get("entity_id", "")).split(".", 1)[0], _name(z).lower()))
    grenze = max(1, min(anzahl, HOECHSTENS))
    ergebnis: dict[str, Any] = {"anzahl": len(passende), "geraete": [_kurz(z) for z in passende[:grenze]]}
    if len(passende) > grenze:
        ergebnis["hinweis"] = (
            f"Es gibt {len(passende)} passende – angezeigt werden {grenze}. Mit art oder suche eingrenzen."
        )
    elif not passende:
        ergebnis["hinweis"] = "Nichts gefunden. Ohne art und suche kommen alle Geräte."
    return ergebnis


async def _zustand(kontext: Kontext, id: str) -> dict[str, Any]:
    kennung = id.strip().lower()
    if not _KENNUNG.match(kennung):
        raise Fehler(
            f"„{id}“ ist keine gültige Kennung.",
            "Kennungen sehen so aus: light.wohnzimmer – „geraete_anzeigen“ liefert sie.",
        )
    async with kontext.http(headers=_kopf(kontext)) as client:
        antwort = await client.get(f"{_basis(kontext)}/api/states/{kennung}")
    if antwort.status_code == 404:
        raise Fehler(
            f"Das Gerät „{kennung}“ gibt es in Home Assistant nicht.",
            "Die Kennungen aller Geräte liefert „geraete_anzeigen“.",
        )
    antwort.raise_for_status()
    return antwort.json()


@funktion(
    beschreibung="Liest den aktuellen Zustand eines Geräts in Home Assistant, mit allen Einzelheiten (z. B. Helligkeit, Temperatur).",
    schreibend=False,
    wenn=_rest_weg,
)
async def zustand_lesen(kontext: Kontext, id: str) -> dict:
    """
    id: Kennung des Geräts, z. B. light.wohnzimmer (aus geraete_anzeigen)
    """
    zustand = await _zustand(kontext, id)
    eigenschaften = {
        name: wert
        for name, wert in (zustand.get("attributes") or {}).items()
        if name != "friendly_name" and isinstance(wert, str | int | float | bool) and len(str(wert)) <= 100
    }
    return {
        **_kurz(zustand),
        "eigenschaften": eigenschaften,
        "zuletzt_geaendert": zustand.get("last_changed"),
    }


async def _dienst(kontext: Kontext, dienst: str, id: str, daten: dict[str, Any] | None) -> str:
    treffer = _DIENST.match(dienst.strip().lower())
    if not treffer:
        raise Fehler(
            f"„{dienst}“ ist kein gültiger Dienst.",
            "Dienste sehen so aus: light.turn_on, switch.toggle, climate.set_temperature.",
        )
    koerper = dict(daten or {})
    if id.strip():
        koerper["entity_id"] = (await _zustand(kontext, id))["entity_id"]
    async with kontext.http(headers=_kopf(kontext)) as client:
        antwort = await client.post(
            f"{_basis(kontext)}/api/services/{treffer.group(1)}/{treffer.group(2)}", json=koerper
        )
    if antwort.status_code in (400, 404):
        raise Fehler(
            f"Home Assistant hat „{dienst}“ abgelehnt: {antwort.text[:200].strip() or antwort.status_code}",
            "Gibt es diesen Dienst und passen die Angaben? In Home Assistant unter „Entwicklerwerkzeuge → Aktionen“ lässt er sich ausprobieren.",
        )
    antwort.raise_for_status()
    return "Erledigt."


async def _schalten_vorschau(kontext: Kontext, id: str, was: str) -> str:
    zustand = await _zustand(kontext, id)
    return f"Schaltet „{_name(zustand)}“ ({zustand['entity_id']}) {was} – jetzt: {zustand.get('state')}"


async def _ein_vorschau(kontext: Kontext, id: str) -> str:
    return await _schalten_vorschau(kontext, id, "ein")


async def _aus_vorschau(kontext: Kontext, id: str) -> str:
    return await _schalten_vorschau(kontext, id, "aus")


@funktion(
    beschreibung="Schaltet ein Gerät in Home Assistant ein (Licht, Schalter, Steckdose …).",
    vorschau=_ein_vorschau,
    wenn=_rest_weg,
)
async def einschalten(kontext: Kontext, id: str) -> str:
    """
    id: Kennung des Geräts, z. B. light.wohnzimmer (aus geraete_anzeigen)
    """
    zustand = await _zustand(kontext, id)
    await _dienst(kontext, "homeassistant.turn_on", id, None)
    return f"„{_name(zustand)}“ ist eingeschaltet."


@funktion(beschreibung="Schaltet ein Gerät in Home Assistant aus.", vorschau=_aus_vorschau, wenn=_rest_weg)
async def ausschalten(kontext: Kontext, id: str) -> str:
    """
    id: Kennung des Geräts, z. B. light.wohnzimmer (aus geraete_anzeigen)
    """
    zustand = await _zustand(kontext, id)
    await _dienst(kontext, "homeassistant.turn_off", id, None)
    return f"„{_name(zustand)}“ ist ausgeschaltet."


async def _dienst_vorschau(kontext: Kontext, dienst: str, id: str = "", daten: dict | None = None) -> str:
    if not _DIENST.match(dienst.strip().lower()):
        raise Fehler(f"„{dienst}“ ist kein gültiger Dienst.", "Dienste sehen so aus: light.turn_on.")
    ziel = f" für „{_name(await _zustand(kontext, id))}“ ({id.strip().lower()})" if id.strip() else ""
    angaben = ", ".join(f"{name} = {wert}" for name, wert in (daten or {}).items())
    return f"Ruft in Home Assistant „{dienst.strip().lower()}“{ziel} auf" + (
        f" ({angaben})" if angaben else ""
    )


@funktion(
    beschreibung=(
        "Ruft einen beliebigen Dienst (Aktion) in Home Assistant auf, z. B. light.turn_on mit "
        'daten {"brightness_pct": 40} oder climate.set_temperature mit {"temperature": 21}.'
    ),
    vorschau=_dienst_vorschau,
    wenn=_rest_weg,
)
async def dienst_aufrufen(kontext: Kontext, dienst: str, id: str = "", daten: dict | None = None) -> str:
    """
    dienst: Name des Dienstes in der Form art.aktion, z. B. light.turn_on
    id: Kennung des Geräts, für das der Dienst gilt, z. B. light.wohnzimmer
    daten: Weitere Angaben für den Dienst als Objekt, z. B. {"brightness_pct": 40}
    """
    return await _dienst(kontext, dienst, id, daten)
