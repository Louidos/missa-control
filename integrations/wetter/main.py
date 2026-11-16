"""Vorlage „Wetter“: Open-Meteo – Ortssuche, Wetter aktuell und Vorhersage (ohne Key).

Nach der offiziellen Doku von Open-Meteo:
- Ortssuche: GET {ort_url}/v1/search?name=…&count=…&language=de&format=json
- Wetter:    GET {wetter_url}/v1/forecast?latitude=…&longitude=…&current=…&daily=…&timezone=auto
"""

from __future__ import annotations

from typing import Any

from missa_control.sdk import Fehler, Kontext, funktion, verbindungstest

AKTUELL = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
TAEGLICH = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,wind_speed_10m_max,sunrise,sunset"
)

# Wettercodes nach WMO (so liefert sie Open-Meteo im Feld weather_code)
WETTER = {
    0: "klar",
    1: "überwiegend klar",
    2: "teilweise bewölkt",
    3: "bedeckt",
    45: "Nebel",
    48: "Nebel mit Reif",
    51: "leichter Nieselregen",
    53: "Nieselregen",
    55: "starker Nieselregen",
    56: "leichter gefrierender Nieselregen",
    57: "gefrierender Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    66: "leichter gefrierender Regen",
    67: "gefrierender Regen",
    71: "leichter Schneefall",
    73: "Schneefall",
    75: "starker Schneefall",
    77: "Schneegriesel",
    80: "leichte Regenschauer",
    81: "Regenschauer",
    82: "heftige Regenschauer",
    85: "leichte Schneeschauer",
    86: "Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "Gewitter mit starkem Hagel",
}


def _adresse(kontext: Kontext, feld: str, standard: str) -> str:
    return str(kontext.konfig.get(feld) or standard).rstrip("/")


async def _holen(kontext: Kontext, url: str, parameter: dict[str, Any]) -> Any:
    async with kontext.http() as client:
        antwort = await client.get(url, params=parameter)
    if antwort.status_code >= 400:
        try:
            grund = antwort.json().get("reason", "")
        except ValueError:
            grund = ""
        raise Fehler(
            f"Open-Meteo antwortet mit einem Fehler ({antwort.status_code}){': ' + grund if grund else ''}.",
            "Stimmen Ort und Angaben? Bei 429 wurden zu viele Anfragen gestellt – später erneut versuchen.",
        )
    return antwort.json()


async def _orte(kontext: Kontext, name: str, anzahl: int = 5) -> list[dict[str, Any]]:
    daten = await _holen(
        kontext,
        _adresse(kontext, "ort_url", "https://geocoding-api.open-meteo.com") + "/v1/search",
        {"name": name, "count": anzahl, "language": "de", "format": "json"},
    )
    return [
        {
            "name": eintrag.get("name"),
            "region": eintrag.get("admin1"),
            "land": eintrag.get("country"),
            "breite": eintrag.get("latitude"),
            "laenge": eintrag.get("longitude"),
            "zeitzone": eintrag.get("timezone"),
        }
        for eintrag in (daten.get("results") or [])
    ]


async def _ort(kontext: Kontext, ort: str) -> dict[str, Any]:
    name = (ort or str(kontext.konfig.get("ort") or "")).strip()
    if not name:
        raise Fehler(
            "Für welchen Ort? Es ist kein Ort angegeben.",
            "Den Ort nennen oder im Formular einen Standard-Ort eintragen.",
        )
    gefunden = await _orte(kontext, name, 1)
    if not gefunden:
        raise Fehler(
            f"Den Ort „{name}“ kennt Open-Meteo nicht.", "Anders schreiben, z. B. „Zürich“ oder „Bern“."
        )
    return gefunden[0]


def _ortsname(ort: dict[str, Any]) -> str:
    return ", ".join(str(teil) for teil in (ort["name"], ort.get("region"), ort.get("land")) if teil)


async def _vorhersage(kontext: Kontext, ort: dict[str, Any], **parameter: Any) -> Any:
    return await _holen(
        kontext,
        _adresse(kontext, "wetter_url", "https://api.open-meteo.com") + "/v1/forecast",
        {"latitude": ort["breite"], "longitude": ort["laenge"], "timezone": "auto", **parameter},
    )


@verbindungstest
async def testen(kontext: Kontext) -> str:
    ort = await _ort(kontext, str(kontext.konfig.get("ort") or "Zürich"))
    daten = await _vorhersage(kontext, ort, current="temperature_2m")
    if "current" not in daten:
        raise Fehler(
            "Unter dieser Adresse antwortet keine Wetter-API von Open-Meteo.", "Die Adressen prüfen."
        )
    return (
        f"Open-Meteo antwortet – in {_ortsname(ort)} sind es gerade {daten['current']['temperature_2m']} °C."
    )


@funktion(beschreibung="Sucht Orte nach Namen (mit Region, Land und Koordinaten).", schreibend=False)
async def ort_suchen(kontext: Kontext, name: str, anzahl: int = 5) -> list[dict[str, Any]]:
    """name: Name des Orts, z. B. „Winterthur“
    anzahl: Wie viele Treffer (1 bis 20)"""
    return await _orte(kontext, name, max(1, min(int(anzahl), 20)))


@funktion(
    beschreibung="Das Wetter jetzt: Temperatur, gefühlt, Niederschlag, Wind und Luftfeuchtigkeit.",
    schreibend=False,
)
async def wetter_aktuell(kontext: Kontext, ort: str = "") -> dict[str, Any]:
    """ort: Für welchen Ort (leer = Standard-Ort)"""
    gefunden = await _ort(kontext, ort)
    daten = await _vorhersage(kontext, gefunden, current=AKTUELL)
    jetzt = daten.get("current") or {}
    einheiten = daten.get("current_units") or {}
    return {
        "ort": _ortsname(gefunden),
        "zeit": jetzt.get("time"),
        "wetter": WETTER.get(jetzt.get("weather_code"), "unbekannt"),
        "temperatur": f"{jetzt.get('temperature_2m')} {einheiten.get('temperature_2m', '°C')}",
        "gefuehlt": f"{jetzt.get('apparent_temperature')} {einheiten.get('apparent_temperature', '°C')}",
        "niederschlag": f"{jetzt.get('precipitation')} {einheiten.get('precipitation', 'mm')}",
        "wind": f"{jetzt.get('wind_speed_10m')} {einheiten.get('wind_speed_10m', 'km/h')}",
        "luftfeuchtigkeit": f"{jetzt.get('relative_humidity_2m')} {einheiten.get('relative_humidity_2m', '%')}",
    }


@funktion(
    beschreibung="Wettervorhersage für die nächsten Tage (Höchst- und Tiefstwert, Regen, Wind).",
    schreibend=False,
)
async def vorhersage(kontext: Kontext, ort: str = "", tage: int = 3) -> dict[str, Any]:
    """ort: Für welchen Ort (leer = Standard-Ort)
    tage: Wie viele Tage (1 bis 16)"""
    gefunden = await _ort(kontext, ort)
    tage = max(1, min(int(tage), 16))
    daten = await _vorhersage(kontext, gefunden, daily=TAEGLICH, forecast_days=tage)
    taeglich = daten.get("daily") or {}
    liste = []
    for nummer, datum in enumerate(taeglich.get("time") or []):

        def wert(name: str, i: int = nummer) -> Any:
            werte = taeglich.get(name) or []
            return werte[i] if i < len(werte) else None

        liste.append(
            {
                "datum": datum,
                "wetter": WETTER.get(wert("weather_code"), "unbekannt"),
                "hoechst": wert("temperature_2m_max"),
                "tiefst": wert("temperature_2m_min"),
                "niederschlag_mm": wert("precipitation_sum"),
                "regenwahrscheinlichkeit": wert("precipitation_probability_max"),
                "wind_max": wert("wind_speed_10m_max"),
                "sonnenaufgang": wert("sunrise"),
                "sonnenuntergang": wert("sunset"),
            }
        )
    return {"ort": _ortsname(gefunden), "einheit": "°C, mm, km/h, %", "tage": liste}
