"""Art `api`: eine REST-API nur mit Adresse und (falls nötig) Key.

„Verbindung testen“ sucht selbst nach einer OpenAPI-Beschreibung unter den üblichen Pfaden. Gibt es
eine, entstehen die Funktionen daraus (wie bei der Art `openapi`). Sonst bekommt Missa zwei
allgemeine Funktionen: `abrufen` (GET) und `senden` (POST/PUT/PATCH/DELETE). Dazu kommen – auf
Wunsch – eigene Endpunkte als eigene Funktionen.

Sicherheit: Jeder Aufruf geht nur an die eingetragene Adresse (gleiches Schema, gleicher Host und
Port, unterhalb des Basis-Pfads). Weiterleitungen werden nur innerhalb dieser Adresse verfolgt.
Der Key steht in keinem Ergebnis und in keiner Meldung.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import anyio
import httpx2

from missa_control.integrationen.adapter.openapi import (
    MAX_ANTWORT_ZEICHEN,
    _als_text,
    _auth_anwenden,
    basis_url_aus_spec,
    funktionen_aus_spec,
    spec_lesen,
)
from missa_control.integrationen.fehlertexte import http_status_erklaeren
from missa_control.integrationen.kontext import Kontext
from missa_control.integrationen.manifest import METHODEN, Endpunkt
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, FunktionsInfo, IntegrationsFehler, TestErgebnis
from missa_control.zugaenge.dienst import Zugangsdaten
from missa_control.zugaenge.schwaerzen import SCHWAERZER

# Hier liegt die OpenAPI-Beschreibung meistens (relativ zur Adresse und zu ihrem Ursprung).
UEBLICHE_PFADE = (
    "openapi.json",
    "swagger.json",
    "v3/api-docs",
    "api-docs",
    "api/openapi.json",
    "swagger/v1/swagger.json",
    "openapi.yaml",
    "api/schema/",
)
MAX_VERSUCHE = 10
SEKUNDEN_PRO_VERSUCH = 5.0
SEKUNDEN_SUCHE = 20.0
MAX_WEITERLEITUNGEN = 5
STANDARD_PORTS = {"http": 80, "https": 443}
SCHREIBENDE_METHODEN = tuple(methode for methode in METHODEN if methode != "GET")
KEY_ARTEN = {
    "bearer": "Authorization: Bearer …",
    "header": "eigener Header",
    "query": "URL-Parameter",
    "basic": "Benutzer und Passwort",
}


# ---------------------------------------------------------------------- Adresse und Sicherheit


class Adresse:
    """Die eingetragene Adresse der API – und die Prüfung, ob eine URL darunter liegt."""

    def __init__(self, text: str) -> None:
        text = (text or "").strip()
        teile = urlsplit(text)
        if teile.scheme not in ("http", "https") or not teile.hostname:
            raise IntegrationsFehler(
                "Die Adresse der API ist ungültig.",
                "Die Adresse muss mit http:// oder https:// beginnen, z. B. https://api.example.ch/v1",
            )
        self.schema = teile.scheme
        self.host = teile.hostname.lower()
        self.port = teile.port or STANDARD_PORTS[teile.scheme]
        self.pfad = teile.path.rstrip("/")
        self.url = f"{teile.scheme}://{teile.netloc}{self.pfad}"
        self.ursprung = f"{teile.scheme}://{teile.netloc}"

    def erlaubt(self, url: str) -> bool:
        teile = urlsplit(url)
        try:
            port = teile.port or STANDARD_PORTS.get(teile.scheme)
        except ValueError:
            return False
        if teile.scheme != self.schema or (teile.hostname or "").lower() != self.host or port != self.port:
            return False
        pfad = teile.path
        if any(segment in ("..", ".") for segment in unquote(pfad).split("/")):
            return False
        return not self.pfad or pfad == self.pfad or pfad.startswith(self.pfad + "/")

    def pruefen(self, url: str) -> str:
        """Gibt die URL zurück, wenn sie an diese API geht – sonst eine verständliche Ablehnung."""
        if not self.erlaubt(url):
            ziel = urlsplit(url)
            wohin = f"{ziel.scheme}://{ziel.netloc}{ziel.path}" if ziel.netloc else url
            raise IntegrationsFehler(
                f"Abgelehnt: „{SCHWAERZER.schwaerzen(wohin)[:200]}“ liegt nicht unter der eingetragenen "
                f"Adresse {self.url}.",
                "Aus Sicherheitsgründen gehen Aufrufe nur an die Adresse der API (gleicher Host, gleicher "
                "Port, unterhalb des Pfads). Für einen anderen Dienst eine eigene Integration einrichten.",
            )
        return url


def pfad_pruefen(pfad: Any) -> str:
    """Der Pfad, den Missa bei `abrufen`/`senden` angibt: nur ein relativer Pfad, kein `..`."""
    if not isinstance(pfad, str):
        raise IntegrationsFehler("Der Parameter „pfad“ muss ein Text sein, z. B. /artikel")
    pfad = pfad.strip()
    roh = unquote(pfad)
    if "://" in roh or roh.startswith("//") or "\\" in roh or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", roh):
        raise IntegrationsFehler(
            "Abgelehnt: „pfad“ darf keine vollständige Adresse sein.",
            "Nur den Teil nach der Adresse der API angeben, z. B. /artikel/12",
        )
    if any(segment in ("..", ".") for segment in roh.split("?")[0].split("/")):
        raise IntegrationsFehler(
            "Abgelehnt: „pfad“ darf kein „..“ enthalten.",
            "Aufrufe gehen nur an Pfade unterhalb der Adresse der API.",
        )
    pfad = pfad.split("#")[0]
    return pfad if pfad.startswith("/") else "/" + pfad


# ---------------------------------------------------------------------- Key mitschicken


def _auth(kontext: Kontext) -> tuple[dict[str, str], Zugangsdaten | None]:
    zugang = kontext.zugang_optional("zugang")
    art = str(kontext.konfig.get("key_art") or "bearer")
    name = str(kontext.konfig.get("key_name") or "").strip()
    if zugang is None:
        return {"art": "keine"}, None
    if art == "basic" and zugang.typ != "benutzer_passwort":
        raise IntegrationsFehler(
            "„Benutzer und Passwort“ braucht einen Zugang mit Benutzer und Passwort.",
            "Einen Zugang der Art „Benutzer + Passwort“ auswählen oder eine andere Art wählen, den Key zu senden.",
        )
    if art in ("header", "query"):
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", name or "x"):
            raise IntegrationsFehler(
                "Der Name des Headers bzw. URL-Parameters ist ungültig.",
                "Nur Buchstaben, Ziffern, - und _, z. B. X-API-Key oder api_key.",
            )
        return {"art": art, "name": name or ("X-API-Key" if art == "header" else "api_key")}, zugang
    if art == "bearer" and zugang.typ == "benutzer_passwort":
        return {"art": "basic"}, zugang
    return {"art": art if art in KEY_ARTEN else "bearer"}, zugang


def _auth_text(auth: dict[str, str]) -> str:
    return {
        "basic": "Benutzer + Passwort (Basic)",
        "bearer": "Authorization: Bearer …",
        "header": f"Header „{auth.get('name')}“",
        "query": f"URL-Parameter „{auth.get('name')}“",
    }.get(auth["art"], "")


# ---------------------------------------------------------------------- Anfragen


def _schwaerzen(wert: Any) -> Any:
    """Entfernt bekannte Geheimnisse aus einem Ergebnis (falls die API den Key zurückschickt)."""
    if isinstance(wert, str):
        return SCHWAERZER.schwaerzen(wert)
    if isinstance(wert, list):
        return [_schwaerzen(eintrag) for eintrag in wert]
    if isinstance(wert, dict):
        return {_schwaerzen(schluessel): _schwaerzen(inhalt) for schluessel, inhalt in wert.items()}
    return wert


def _antwort_lesen(antwort: httpx2.Response) -> Any:
    text = antwort.text
    if "json" in antwort.headers.get("content-type", "") and len(text) <= MAX_ANTWORT_ZEICHEN:
        try:
            return _schwaerzen(antwort.json())
        except ValueError:
            pass
    if len(text) > MAX_ANTWORT_ZEICHEN:
        text = text[:MAX_ANTWORT_ZEICHEN] + "\n… (gekürzt)"
    return SCHWAERZER.schwaerzen(text)


async def _anfrage(
    client: httpx2.AsyncClient,
    adresse: Adresse,
    methode: str,
    url: str,
    *,
    headers: dict[str, str],
    query: list[tuple[str, str]],
    key_query: list[tuple[str, str]],
    **optionen: Any,
) -> httpx2.Response:
    """Eine Anfrage, Weiterleitungen nur innerhalb der Adresse der API.

    `key_query` ist der Key als URL-Parameter (falls so gewählt) – er geht auch nach einer
    Weiterleitung mit, die übrigen Parameter bringt die Ziel-URL selbst mit.
    """
    adresse.pruefen(url)
    antwort = await client.request(
        methode, url, headers=headers, params=[*query, *key_query] or None, **optionen
    )
    for _ in range(MAX_WEITERLEITUNGEN):
        if not antwort.is_redirect or "location" not in antwort.headers:
            return antwort
        ziel = str(antwort.url.join(antwort.headers["location"]))
        if not adresse.erlaubt(ziel):
            host = urlsplit(ziel).netloc or ziel
            raise IntegrationsFehler(
                f"Abgelehnt: Die API leitet auf eine andere Adresse weiter ({SCHWAERZER.schwaerzen(host)[:100]}).",
                "Weiterleitungen werden aus Sicherheitsgründen nur innerhalb der eingetragenen Adresse "
                "verfolgt. Stimmt die Adresse – z. B. https statt http oder mit bzw. ohne www?",
            )
        if antwort.status_code in (301, 302, 303) and methode != "GET":
            methode, optionen = "GET", {}
        antwort = await client.request(methode, ziel, headers=headers, params=key_query or None, **optionen)
    raise IntegrationsFehler("Die API leitet zu oft weiter.", "Stimmt die Adresse der API?")


def _fehler_pruefen(antwort: httpx2.Response, inhalt: Any) -> None:
    if antwort.status_code < 400:
        return
    meldung, hinweis = http_status_erklaeren(antwort.status_code)
    auszug = inhalt if isinstance(inhalt, str) else json.dumps(inhalt, ensure_ascii=False)
    if auszug:
        meldung = f"{meldung} Antwort: {SCHWAERZER.schwaerzen(auszug)[:400]}"
    raise IntegrationsFehler(meldung, hinweis)


# ---------------------------------------------------------------------- Funktionen


def _zur_api(kontext: Kontext) -> str:
    text = str(kontext.konfig.get("beschreibung") or "").strip()
    return f" Zur API: {text[:300]}" if text else ""


def allgemeine_funktionen(adresse: str, zur_api: str) -> list[FunktionsInfo]:
    """`abrufen` und `senden` – für APIs ohne Beschreibung."""
    return [
        FunktionsInfo(
            name="abrufen",
            beschreibung=(
                f"Ruft Daten von der API {adresse} ab (GET). „pfad“ ist der Teil nach dieser Adresse, "
                f"z. B. /artikel; „parameter“ kommen als URL-Parameter dazu.{zur_api}"
            ),
            parameter={
                "type": "object",
                "properties": {
                    "pfad": {
                        "type": "string",
                        "description": "Pfad unterhalb der Adresse, z. B. /artikel/12",
                    },
                    "parameter": {
                        "type": "object",
                        "description": 'URL-Parameter, z. B. {"suche": "Apfel"}',
                        "additionalProperties": True,
                    },
                },
                "required": ["pfad"],
            },
            schreibend=False,
            extra={"typ": "abrufen"},
        ),
        FunktionsInfo(
            name="senden",
            beschreibung=(
                f"Sendet Daten an die API {adresse} (POST, PUT, PATCH oder DELETE) – ändert dort etwas. "
                f"„pfad“ ist der Teil nach dieser Adresse, „daten“ wird als JSON gesendet.{zur_api}"
            ),
            parameter={
                "type": "object",
                "properties": {
                    "methode": {"type": "string", "enum": list(SCHREIBENDE_METHODEN)},
                    "pfad": {"type": "string", "description": "Pfad unterhalb der Adresse, z. B. /artikel"},
                    "daten": {"description": "Inhalt der Anfrage (JSON)"},
                    "parameter": {
                        "type": "object",
                        "description": "URL-Parameter",
                        "additionalProperties": True,
                    },
                },
                "required": ["methode", "pfad"],
            },
            schreibend=True,
            extra={"typ": "senden"},
        ),
    ]


_JSON_TYPEN = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}


def endpunkt_funktion(endpunkt: Endpunkt, zur_api: str = "") -> FunktionsInfo:
    """Ein Endpunkt als Funktion: Platzhalter werden Parameter.

    Eigene Endpunkte aus dem Formular bekommen dazu `parameter` (URL-Parameter) und – ausser bei GET –
    `daten`. Endpunkte aus einer Vorlage haben genau die Parameter, die die Vorlage beschreibt.
    """
    eigenschaften: dict[str, Any] = {
        name: {"type": "string", "description": f"Wert für {{{name}}} im Pfad"}
        for name in endpunkt.platzhalter()
    }
    pflicht = list(endpunkt.platzhalter())
    if endpunkt.parameter:
        for parameter in endpunkt.parameter:
            schema: dict[str, Any] = (
                {"type": "array", "items": {"type": "string"}}
                if parameter.typ == "array"
                else {"type": _JSON_TYPEN[parameter.typ]}
            )
            if parameter.beschreibung:
                schema["description"] = parameter.beschreibung
            if parameter.optionen:
                schema["enum"] = list(parameter.optionen)
            if parameter.standard is not None:
                schema["default"] = parameter.standard
            eigenschaften[parameter.name] = schema
            if parameter.pflicht:
                pflicht.append(parameter.name)
    else:
        eigenschaften["parameter"] = {
            "type": "object",
            "description": "Weitere URL-Parameter (optional)",
            "additionalProperties": True,
        }
        if endpunkt.methode != "GET":
            eigenschaften["daten"] = {"description": "Inhalt der Anfrage (JSON)"}
    kopf = f"{endpunkt.methode} {endpunkt.pfad}"
    beschreibung = endpunkt.beschreibung.strip()
    return FunktionsInfo(
        name=endpunkt.name,
        beschreibung=f"{beschreibung} ({kopf}).{zur_api}" if beschreibung else f"{kopf}.{zur_api}",
        parameter={
            "type": "object",
            "properties": eigenschaften,
            **({"required": pflicht} if pflicht else {}),
        },
        schreibend=endpunkt.ist_schreibend,
        extra={"typ": "endpunkt", **endpunkt.model_dump(exclude={"name", "beschreibung", "schreibend"})},
    )


def _einsetzen(wert: Any, konfig: Any) -> Any:
    """Setzt `{{feld}}` aus dem Formular ein (in Texten, Listen und verschachtelten Feldern)."""
    if isinstance(wert, str):
        return re.sub(
            r"\{\{([a-z][a-z0-9_]*)\}\}", lambda treffer: _als_text(konfig.get(treffer.group(1), "")), wert
        )
    if isinstance(wert, list):
        return [_einsetzen(eintrag, konfig) for eintrag in wert]
    if isinstance(wert, dict):
        return {schluessel: _einsetzen(inhalt, konfig) for schluessel, inhalt in wert.items()}
    return wert


def _adresse(kontext: Kontext) -> Adresse:
    """Die Adresse der API: aus dem Formular – oder fest aus der Vorlage (`basis_url`)."""
    return Adresse(str(kontext.konfig.get("adresse") or kontext.manifest.basis_url or ""))


def eigene_endpunkte(kontext: Kontext) -> list[Endpunkt]:
    roh = kontext.konfig.get("endpunkte") or []
    return [Endpunkt.model_validate(eintrag) for eintrag in roh] if isinstance(roh, list) else []


def _parameter_liste(wert: Any) -> list[tuple[str, str]]:
    if wert is None:
        return []
    if not isinstance(wert, dict):
        raise IntegrationsFehler('„parameter“ muss aus Name und Wert bestehen, z. B. {"suche": "Apfel"}')
    liste: list[tuple[str, str]] = []
    for name, inhalt in wert.items():
        for eintrag in inhalt if isinstance(inhalt, list) else [inhalt]:
            if eintrag is not None:
                liste.append((str(name), _als_text(eintrag)))
    return liste


# ---------------------------------------------------------------------- Adapter


class ApiAdapter:
    art = "api"

    async def _erreichbar(self, kontext: Kontext, adresse: Adresse, sekunden: float) -> httpx2.Response:
        """Eine günstige Anfrage an die Adresse. 401/403 heisst: Der Zugang wird abgelehnt."""
        auth, zugang = _auth(kontext)
        headers: dict[str, str] = {"Accept": "application/json, */*"}
        key: list[tuple[str, str]] = []
        _auth_anwenden(auth, zugang, headers, key)
        async with kontext.http(
            follow_redirects=False, timeout=httpx2.Timeout(sekunden, connect=min(sekunden, 5.0))
        ) as client:
            antwort = await _anfrage(
                client, adresse, "GET", adresse.url, headers=headers, query=[], key_query=key
            )
        if antwort.status_code in (401, 403):
            meldung, hinweis = http_status_erklaeren(antwort.status_code)
            if zugang is None:
                hinweis = "Die API verlangt einen Key. Unter „Zugang“ einen API-Key oder ein Token eintragen."
            raise IntegrationsFehler(meldung, hinweis)
        return antwort

    async def pruefen(self, kontext: Kontext) -> TestErgebnis:
        """Die regelmässige Prüfung: nur erreichbar und Zugang angenommen? (keine Suche nach der Beschreibung)"""
        adresse = _adresse(kontext)
        antwort = await self._erreichbar(kontext, adresse, 8.0)
        return TestErgebnis(ok=True, meldung=f"Erreichbar (Antwort {antwort.status_code}).")

    async def _spec_suchen(self, kontext: Kontext, adresse: Adresse) -> tuple[dict[str, Any], str] | None:
        """Sucht die OpenAPI-Beschreibung unter den üblichen Pfaden (höchstens 10 Versuche, 20 Sekunden)."""
        basis = adresse.url + "/"
        ursprung = adresse.ursprung + "/"
        # Abwechselnd unter der Adresse und unter ihrem Ursprung – die häufigsten Pfade zuerst.
        kandidaten = list(
            dict.fromkeys(url for pfad in UEBLICHE_PFADE for url in (basis + pfad, ursprung + pfad))
        )[:MAX_VERSUCHE]
        # Die Beschreibung darf auch am Ursprung liegen (nur lesend, nur für die Suche).
        suchbereich = Adresse(adresse.ursprung)

        auth, zugang = _auth(kontext)
        headers: dict[str, str] = {"Accept": "application/json, application/yaml, */*"}
        key: list[tuple[str, str]] = []
        _auth_anwenden(auth, zugang, headers, key)
        with anyio.move_on_after(SEKUNDEN_SUCHE):
            async with kontext.http(
                follow_redirects=False, timeout=httpx2.Timeout(SEKUNDEN_PRO_VERSUCH)
            ) as client:
                for url in kandidaten:
                    try:
                        with anyio.fail_after(SEKUNDEN_PRO_VERSUCH):
                            antwort = await _anfrage(
                                client, suchbereich, "GET", url, headers=headers, query=[], key_query=key
                            )
                        if antwort.status_code != 200 or len(antwort.content) > 5 * 1024 * 1024:
                            continue
                        spec = spec_lesen(antwort.text)
                    except (IntegrationsFehler, httpx2.HTTPError, TimeoutError):
                        continue
                    if funktionen_aus_spec(spec):
                        return spec, str(antwort.url)
        return None

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        adresse = _adresse(kontext)
        auth, _zugang = _auth(kontext)
        await self._erreichbar(kontext, adresse, 10.0)
        endpunkte = eigene_endpunkte(kontext)
        zur_api = _zur_api(kontext)
        eigene = [endpunkt_funktion(endpunkt, zur_api) for endpunkt in endpunkte]
        eigene_namen = {funktion.name for funktion in eigene}
        details = [f"Adresse der API: {adresse.url}"]
        zustand: dict[str, Any] = {"auth": auth}

        vorlage = kontext.manifest.endpunkte
        if vorlage:
            # Eine Vorlage bringt ihre Funktionen fertig beschrieben mit – keine Suche nötig.
            funktionen = [
                *[endpunkt_funktion(e, zur_api) for e in vorlage if e.name not in eigene_namen],
                *eigene,
            ]
            lesend = sum(1 for funktion in funktionen if not funktion.schreibend)
            details.append(f"{lesend} lesend, {len(funktionen) - lesend} schreibend")
            if auth["art"] != "keine":
                details.append(f"Key wird gesendet als: {_auth_text(auth)}")
            return TestErgebnis(
                ok=True,
                meldung=f"{kontext.manifest.name}: verbunden – {len(funktionen)} Funktion(en) bereit.",
                details=details,
                funktionen=funktionen,
                zustand=zustand,
            )

        gefunden = await self._spec_suchen(kontext, adresse)
        if gefunden is not None:
            spec, spec_url = gefunden
            aus_spec = [
                funktion for funktion in funktionen_aus_spec(spec) if funktion.name not in eigene_namen
            ]
            for funktion in aus_spec:
                funktion.extra = {**funktion.extra, "typ": "spec"}
                if zur_api:
                    funktion.beschreibung = (funktion.beschreibung + "." + zur_api)[:900]
            # Die Beschreibung nennt die eigentliche Adresse (z. B. …/v1) – aber nur innerhalb der eingetragenen.
            spec_basis = (basis_url_aus_spec(spec, spec_url) or "").rstrip("/")
            teile = urlsplit(spec_basis)
            ruf_basis = (
                spec_basis
                if spec_basis and f"{teile.scheme}://{teile.netloc}" == adresse.ursprung
                else adresse.url
            )
            zustand["ruf_basis"] = ruf_basis
            funktionen = [*aus_spec, *eigene]
            titel = str((spec.get("info") or {}).get("title") or "Die API")
            meldung = (
                f"{titel}: Beschreibung gefunden unter {spec_url} – {len(funktionen)} Funktion(en) erzeugt."
            )
            details.append(f"OpenAPI-Beschreibung: {spec_url}")
        else:
            funktionen = [
                *[
                    funktion
                    for funktion in allgemeine_funktionen(adresse.url, zur_api)
                    if funktion.name not in eigene_namen
                ],
                *eigene,
            ]
            meldung = (
                f"Verbunden mit {adresse.url}. Keine OpenAPI-Beschreibung gefunden – Missa bekommt "
                f"{len(funktionen)} Funktion(en), darunter „abrufen“ und „senden“."
            )
            details.append("Keine OpenAPI-Beschreibung unter den üblichen Pfaden gefunden")
        if eigene:
            details.append(f"{len(eigene)} eigene(r) Endpunkt(e)")
        lesend = sum(1 for funktion in funktionen if not funktion.schreibend)
        details.append(f"{lesend} lesend, {len(funktionen) - lesend} schreibend")
        if auth["art"] != "keine":
            details.append(f"Key wird gesendet als: {_auth_text(auth)}")
        return TestErgebnis(ok=True, meldung=meldung, details=details, funktionen=funktionen, zustand=zustand)

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        adresse = _adresse(kontext)
        extra = funktion.extra or {}
        typ = extra.get("typ")
        headers: dict[str, str] = {"Accept": "application/json, */*"}
        query: list[tuple[str, str]] = []
        optionen: dict[str, Any] = {}

        if typ in ("abrufen", "senden"):
            if typ == "abrufen":
                methode = "GET"
            else:
                methode = str(argumente.get("methode") or "").upper()
                if methode not in SCHREIBENDE_METHODEN:
                    raise IntegrationsFehler(
                        "„methode“ muss POST, PUT, PATCH oder DELETE sein.",
                        "Zum Lesen gibt es die Funktion „abrufen“.",
                    )
                if argumente.get("daten") is not None:
                    optionen["json"] = argumente["daten"]
            url = adresse.url + pfad_pruefen(argumente.get("pfad"))
            query.extend(_parameter_liste(argumente.get("parameter")))
        elif typ == "endpunkt":
            methode = str(extra.get("methode") or "GET")
            pfad = str(extra.get("pfad") or "/")
            for name in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", pfad):
                if argumente.get(name) is None:
                    raise IntegrationsFehler(f"Der Parameter „{name}“ fehlt.")
                pfad = pfad.replace("{" + name + "}", quote(_als_text(argumente[name]), safe=""))
            url = adresse.url + pfad_pruefen(pfad)
            if not extra.get("parameter"):
                query.extend(_parameter_liste(argumente.get("parameter")))
            if extra.get("parameter") or extra.get("query") or extra.get("daten"):
                koerper = self._vorlage_werte(kontext, extra, argumente, query)
                if koerper is not None:
                    optionen["json"] = koerper
            elif methode != "GET" and argumente.get("daten") is not None:
                optionen["json"] = argumente["daten"]
        elif typ == "spec":
            methode, url, optionen = self._spec_anfrage(kontext, adresse, extra, argumente, headers, query)
        else:
            raise IntegrationsFehler(
                "Die Integration ist unvollständig eingerichtet.",
                "Unter „Integrationen“ erneut testen, damit die Funktionen neu ermittelt werden.",
            )

        auth, zugang = _auth(kontext)
        key: list[tuple[str, str]] = []
        _auth_anwenden(auth, zugang, headers, key)
        async with kontext.http(follow_redirects=False, timeout=httpx2.Timeout(60.0, connect=10.0)) as client:
            antwort = await _anfrage(
                client, adresse, methode, url, headers=headers, query=query, key_query=key, **optionen
            )
        inhalt = _antwort_lesen(antwort)
        _fehler_pruefen(antwort, inhalt)
        return AufrufErgebnis(wert=inhalt if inhalt != "" else {"status": antwort.status_code})

    @staticmethod
    def _vorlage_werte(
        kontext: Kontext, extra: dict[str, Any], argumente: dict[str, Any], query: list[tuple[str, str]]
    ) -> dict[str, Any] | None:
        """Parameter eines Endpunkts aus einer Vorlage: URL-Parameter in `query`, JSON-Felder als Rückgabe."""
        koerper: dict[str, Any] = dict(_einsetzen(extra.get("daten") or {}, kontext.konfig))
        for name, wert in (extra.get("query") or {}).items():
            query.append((name, _als_text(_einsetzen(wert, kontext.konfig))))
        for parameter in extra.get("parameter") or []:
            wert = argumente.get(parameter["name"])
            if wert is None or wert == "":
                wert = parameter.get("standard")
            if wert is None or wert == "":
                if parameter.get("pflicht"):
                    raise IntegrationsFehler(f"Der Parameter „{parameter['name']}“ fehlt.")
                continue
            ziel = parameter.get("url_name") or parameter["name"]
            if parameter.get("ort") == "json":
                koerper[ziel] = wert
            else:
                for eintrag in wert if isinstance(wert, list) else [wert]:
                    query.append((ziel, _als_text(eintrag)))
        return koerper or None

    @staticmethod
    def _spec_anfrage(
        kontext: Kontext,
        adresse: Adresse,
        extra: dict[str, Any],
        argumente: dict[str, Any],
        headers: dict[str, str],
        query: list[tuple[str, str]],
    ) -> tuple[str, str, dict[str, Any]]:
        """Wie bei der Art `openapi` – nur dass die Adresse immer geprüft wird."""
        pfad = str(extra.get("pfad") or "/")
        for parameter in extra.get("parameter") or []:
            wert = argumente.get(parameter["schluessel"])
            if wert is None:
                if parameter["ort"] == "path":
                    raise IntegrationsFehler(f"Der Parameter „{parameter['schluessel']}“ fehlt.")
                continue
            if parameter["ort"] == "path":
                pfad = pfad.replace("{" + parameter["name"] + "}", quote(_als_text(wert), safe=""))
            elif parameter["ort"] == "query":
                werte = wert if isinstance(wert, list) else [wert]
                query.extend((parameter["name"], _als_text(eintrag)) for eintrag in werte)
            elif parameter["ort"] == "header":
                headers[parameter["name"]] = _als_text(wert)
        optionen: dict[str, Any] = {}
        koerper = extra.get("koerper")
        if koerper and "body" in argumente:
            if koerper.get("art") == "formular":
                optionen["data"] = argumente["body"]
            else:
                optionen["json"] = argumente["body"]
                if koerper.get("medientyp"):
                    headers["Content-Type"] = koerper["medientyp"]
        basis = str(kontext.zustand.get("ruf_basis") or adresse.url).rstrip("/")
        return str(extra.get("methode") or "GET"), basis + pfad_pruefen(pfad), optionen
