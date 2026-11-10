"""Art `openapi`: eine beliebige REST-API. Aus jedem Endpunkt der OpenAPI-Beschreibung wird eine Funktion."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx2
import yaml

from missa_control.integrationen.fehlertexte import http_status_erklaeren
from missa_control.integrationen.kontext import Kontext, auth_header
from missa_control.integrationen.modelle import Funktion
from missa_control.integrationen.typen import AufrufErgebnis, FunktionsInfo, IntegrationsFehler, TestErgebnis
from missa_control.zugaenge.dienst import Zugangsdaten

METHODEN = ("get", "post", "put", "patch", "delete")
MAX_SPEC_BYTES = 5 * 1024 * 1024
MAX_ANTWORT_ZEICHEN = 100_000
MAX_TIEFE = 10
_UNGUELTIG = re.compile(r"[^A-Za-z0-9_]+")


def spec_lesen(text: str) -> dict[str, Any]:
    """Liest eine OpenAPI-Beschreibung (JSON oder YAML) und prüft, ob sie brauchbar ist."""
    if len(text.encode()) > MAX_SPEC_BYTES:
        raise IntegrationsFehler("Die OpenAPI-Beschreibung ist zu gross (höchstens 5 MB).")
    try:
        spec = json.loads(text)
    except ValueError:
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as fehler:
            raise IntegrationsFehler(
                "Die OpenAPI-Beschreibung ist weder gültiges JSON noch gültiges YAML.",
                "Bitte die Datei bzw. URL prüfen – oft ist es die Adresse der Doku-Seite statt der "
                "eigentlichen Beschreibung (meist …/openapi.json oder …/swagger.json).",
            ) from fehler
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise IntegrationsFehler(
            "Das ist keine OpenAPI-Beschreibung (der Abschnitt „paths“ fehlt).",
            "Erwartet wird eine OpenAPI- bzw. Swagger-Datei, meist unter …/openapi.json oder …/swagger.json.",
        )
    return spec


class _Aufloeser:
    """Löst `$ref`-Verweise innerhalb der Beschreibung auf (mit Schutz vor Endlosschleifen)."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec

    def ziel(self, verweis: str) -> Any:
        if not verweis.startswith("#/"):
            return {}
        knoten: Any = self.spec
        for teil in verweis[2:].split("/"):
            teil = teil.replace("~1", "/").replace("~0", "~")
            if not isinstance(knoten, dict) or teil not in knoten:
                return {}
            knoten = knoten[teil]
        return knoten

    def objekt(self, wert: Any) -> dict[str, Any]:
        """Folgt einem Verweis auf oberster Ebene (für Parameter, Antworten, Request-Bodies)."""
        for _ in range(MAX_TIEFE):
            if isinstance(wert, dict) and isinstance(wert.get("$ref"), str):
                wert = self.ziel(wert["$ref"])
            else:
                break
        return wert if isinstance(wert, dict) else {}

    def schema(self, wert: Any, tiefe: int = 0, pfad: tuple[str, ...] = ()) -> Any:
        """Setzt Verweise direkt ein, damit das Schema für sich allein verständlich ist."""
        if isinstance(wert, list):
            return [self.schema(eintrag, tiefe, pfad) for eintrag in wert]
        if not isinstance(wert, dict):
            return wert
        verweis = wert.get("$ref")
        if isinstance(verweis, str):
            if verweis in pfad or tiefe >= MAX_TIEFE:
                return {"type": "object", "description": "(verschachtelt, hier gekürzt)"}
            return self.schema(self.ziel(verweis), tiefe + 1, (*pfad, verweis))
        if tiefe >= MAX_TIEFE:
            return {"type": wert.get("type", "object")}
        ergebnis: dict[str, Any] = {}
        for schluessel, inhalt in wert.items():
            if schluessel in ("xml", "externalDocs", "example", "examples") or schluessel.startswith("x-"):
                continue
            if schluessel == "nullable":  # OpenAPI 3.0 → JSON Schema
                continue
            ergebnis[schluessel] = self.schema(inhalt, tiefe + 1, pfad)
        if wert.get("nullable") is True and isinstance(ergebnis.get("type"), str):
            ergebnis["type"] = [ergebnis["type"], "null"]
        return ergebnis


def _name_bilden(operation: dict[str, Any], methode: str, pfad: str, vergeben: set[str]) -> str:
    roh = str(operation.get("operationId") or f"{methode}_{pfad}")
    name = re.sub(r"_+", "_", _UNGUELTIG.sub("_", roh)).strip("_")[:56] or methode
    if name[0].isdigit():
        name = f"f_{name}"
    kandidat, nummer = name, 2
    while kandidat in vergeben:
        kandidat = f"{name}_{nummer}"
        nummer += 1
    vergeben.add(kandidat)
    return kandidat


def funktionen_aus_spec(spec: dict[str, Any]) -> list[FunktionsInfo]:
    """Erzeugt aus jedem Endpunkt eine Funktion: GET = lesend, alles andere = schreibend."""
    aufloeser = _Aufloeser(spec)
    swagger2 = str(spec.get("swagger", "")).startswith("2")
    funktionen: list[FunktionsInfo] = []
    vergeben: set[str] = set()

    for pfad, eintrag in spec["paths"].items():
        eintrag = aufloeser.objekt(eintrag)
        gemeinsame = eintrag.get("parameters") or []
        for methode in METHODEN:
            operation = eintrag.get(methode)
            if not isinstance(operation, dict):
                continue
            eigenschaften: dict[str, Any] = {}
            pflicht: list[str] = []
            parameter_orte: list[dict[str, Any]] = []
            koerper: dict[str, Any] | None = None

            zusammen: dict[tuple[str, str], dict[str, Any]] = {}
            for roh in [*gemeinsame, *(operation.get("parameters") or [])]:
                parameter = aufloeser.objekt(roh)
                if parameter.get("name") and parameter.get("in"):
                    zusammen[(parameter["name"], parameter["in"])] = parameter

            for (name, ort), parameter in zusammen.items():
                if ort == "body":  # Swagger 2
                    koerper = {"art": "json", "schema": aufloeser.schema(parameter.get("schema") or {})}
                    if parameter.get("required"):
                        pflicht.append("body")
                    continue
                if ort not in ("path", "query", "header") or ort == "formData":
                    continue
                if swagger2:
                    schema = {
                        k: v
                        for k, v in parameter.items()
                        if k in ("type", "format", "enum", "items", "default")
                    }
                else:
                    schema = aufloeser.schema(parameter.get("schema") or {})
                schema = dict(schema) if isinstance(schema, dict) else {}
                if parameter.get("description"):
                    schema["description"] = str(parameter["description"])[:500]
                schluessel = name if name not in eigenschaften and name != "body" else f"{name}_{ort}"
                eigenschaften[schluessel] = schema
                parameter_orte.append({"name": name, "ort": ort, "schluessel": schluessel})
                if parameter.get("required") or ort == "path":
                    pflicht.append(schluessel)

            anfrage = aufloeser.objekt(operation.get("requestBody"))
            inhalte = anfrage.get("content") if isinstance(anfrage.get("content"), dict) else {}
            for medientyp, art in (
                ("application/json", "json"),
                ("application/x-www-form-urlencoded", "formular"),
            ):
                treffer = next(
                    (wert for typ, wert in inhalte.items() if typ.split(";")[0].strip() == medientyp), None
                )
                if treffer is not None and koerper is None:
                    koerper = {
                        "art": art,
                        "schema": aufloeser.schema(aufloeser.objekt(treffer).get("schema") or {}),
                    }
                    if anfrage.get("required"):
                        pflicht.append("body")
            if koerper is None and inhalte:
                json_artig = next((typ for typ in inhalte if typ.endswith("+json")), None)
                if json_artig:
                    schema = aufloeser.schema(aufloeser.objekt(inhalte[json_artig]).get("schema") or {})
                    koerper = {"art": "json", "schema": schema, "medientyp": json_artig}

            if koerper is not None:
                schema = koerper.pop("schema")
                schema = dict(schema) if isinstance(schema, dict) and schema else {"type": "object"}
                schema.setdefault("description", "Inhalt der Anfrage")
                eigenschaften["body"] = schema

            beschreibung = str(operation.get("summary") or operation.get("description") or "").strip()
            kopf = f"{methode.upper()} {pfad}"
            funktionen.append(
                FunktionsInfo(
                    name=_name_bilden(operation, methode, pfad, vergeben),
                    beschreibung=(f"{beschreibung[:400]} ({kopf})" if beschreibung else kopf),
                    parameter={
                        "type": "object",
                        "properties": eigenschaften,
                        **({"required": sorted(set(pflicht))} if pflicht else {}),
                    },
                    schreibend=methode != "get",
                    extra={
                        "methode": methode.upper(),
                        "pfad": pfad,
                        "parameter": parameter_orte,
                        "koerper": koerper,
                    },
                )
            )
    return funktionen


def basis_url_aus_spec(spec: dict[str, Any], spec_url: str | None) -> str | None:
    """Die Adresse der API laut Beschreibung (OpenAPI 3: `servers`, Swagger 2: `host`)."""
    server = spec.get("servers")
    if isinstance(server, list) and server and isinstance(server[0], dict) and server[0].get("url"):
        url = str(server[0]["url"])
        for name, variable in (server[0].get("variables") or {}).items():
            url = url.replace("{" + name + "}", str((variable or {}).get("default", "")))
        return urljoin(spec_url, url) if spec_url else (url if urlsplit(url).scheme else None)
    host = spec.get("host")
    if host:
        schema = (spec.get("schemes") or ["https"])[0]
        return f"{schema}://{host}{spec.get('basePath', '')}"
    if spec_url:
        teile = urlsplit(spec_url)
        return f"{teile.scheme}://{teile.netloc}"
    return None


def auth_aus_spec(spec: dict[str, Any], zugang: Zugangsdaten | None) -> dict[str, str]:
    """Wie der Zugang mitgeschickt wird – laut Beschreibung, sonst nach Art des Zugangs."""
    if zugang is None:
        return {"art": "keine"}
    if zugang.typ == "benutzer_passwort":
        return {"art": "basic"}
    schemata = (spec.get("components") or {}).get("securitySchemes") or spec.get("securityDefinitions") or {}
    kandidaten = [schema for schema in schemata.values() if isinstance(schema, dict)]
    if zugang.typ == "api_key":
        for schema in kandidaten:
            if (
                schema.get("type") == "apiKey"
                and schema.get("in") in ("header", "query")
                and schema.get("name")
            ):
                return {"art": schema["in"], "name": str(schema["name"])}
        if any(
            schema.get("type") == "http" and schema.get("scheme", "").lower() == "bearer"
            for schema in kandidaten
        ):
            return {"art": "bearer"}
        return {"art": "header", "name": "X-API-Key"}
    return {"art": "bearer"}


def _auth_anwenden(
    auth: dict[str, str], zugang: Zugangsdaten | None, headers: dict[str, str], query: list[tuple[str, str]]
) -> None:
    if zugang is None or auth.get("art") in (None, "keine"):
        return
    art = auth["art"]
    if art in ("basic", "bearer"):
        headers.update(auth_header(zugang))
    elif art == "header":
        headers[auth.get("name") or "X-API-Key"] = zugang.wert
    elif art == "query":
        query.append((auth.get("name") or "api_key", zugang.wert))


class OpenApiAdapter:
    art = "openapi"

    async def _spec_holen(self, kontext: Kontext) -> tuple[dict[str, Any], str | None]:
        datei = str(kontext.konfig.get("spec_datei") or "").strip()
        url = str(kontext.konfig.get("spec_url") or "").strip()
        if datei:
            return spec_lesen(datei), None
        if not url:
            raise IntegrationsFehler(
                "Es fehlt die OpenAPI-Beschreibung.",
                "Entweder die URL der Beschreibung angeben oder die Datei hochladen.",
            )
        headers: dict[str, str] = {"Accept": "application/json, application/yaml, */*"}
        query: list[tuple[str, str]] = []
        gemerkt = kontext.zustand.get("auth")
        if isinstance(gemerkt, dict):
            _auth_anwenden(gemerkt, kontext.zugang_optional("zugang"), headers, query)
        async with kontext.http() as client:
            antwort = await client.get(url, headers=headers, params=query or None)
            if antwort.status_code in (401, 403) and not gemerkt and kontext.zugang_optional("zugang"):
                # Manche APIs schützen auch ihre Beschreibung: einmal mit Zugang versuchen.
                antwort = await client.get(
                    url, headers={**headers, **auth_header(kontext.zugang_optional("zugang"))}
                )
            antwort.raise_for_status()
        return spec_lesen(antwort.text), str(antwort.url)

    async def testen(self, kontext: Kontext) -> TestErgebnis:
        spec, spec_url = await self._spec_holen(kontext)
        funktionen = funktionen_aus_spec(spec)
        if not funktionen:
            raise IntegrationsFehler(
                "Die OpenAPI-Beschreibung enthält keine Endpunkte.",
                "Unter „paths“ muss mindestens ein Endpunkt mit GET, POST, PUT, PATCH oder DELETE stehen.",
            )
        basis = str(kontext.konfig.get("basis_url") or "").strip() or basis_url_aus_spec(spec, spec_url)
        if not basis or urlsplit(basis).scheme not in ("http", "https"):
            raise IntegrationsFehler(
                "Die Adresse der API ist unbekannt.",
                "Die Beschreibung nennt keine Server-Adresse – bitte das Feld „Basis-URL“ ausfüllen, "
                "z. B. https://api.example.ch/v1",
            )
        basis = basis.rstrip("/")
        auth = auth_aus_spec(spec, kontext.zugang_optional("zugang"))

        # Erreichbarkeit prüfen: jede Antwort des Servers zählt, nur "keine Verbindung" ist ein Fehler.
        async with kontext.http() as client:
            await client.get(basis, headers={"Accept": "*/*"})

        lesend = sum(1 for funktion in funktionen if not funktion.schreibend)
        titel = str((spec.get("info") or {}).get("title") or "die API")
        details = [f"Adresse der API: {basis}", f"{lesend} lesend, {len(funktionen) - lesend} schreibend"]
        if auth["art"] != "keine":
            wie = {
                "basic": "Benutzer + Passwort (Basic)",
                "bearer": "Authorization: Bearer …",
                "header": f"Header „{auth.get('name')}“",
                "query": f"URL-Parameter „{auth.get('name')}“",
            }[auth["art"]]
            details.append(f"Zugang wird mitgeschickt als: {wie} (wird beim ersten Aufruf geprüft)")
        return TestErgebnis(
            ok=True,
            meldung=f"{titel}: {len(funktionen)} Funktion(en) aus der Beschreibung erzeugt.",
            details=details,
            funktionen=funktionen,
            zustand={"basis_url": basis, "auth": auth},
        )

    async def aufrufen(
        self, kontext: Kontext, funktion: Funktion, argumente: dict[str, Any]
    ) -> AufrufErgebnis:
        extra = funktion.extra or {}
        basis = str(kontext.konfig.get("basis_url") or "").strip() or str(
            kontext.zustand.get("basis_url") or ""
        )
        if not basis or "methode" not in extra:
            raise IntegrationsFehler(
                "Die Integration ist unvollständig eingerichtet.",
                "Unter „Integrationen“ erneut testen, damit Adresse und Funktionen neu ermittelt werden.",
            )
        pfad = str(extra["pfad"])
        headers: dict[str, str] = {"Accept": "application/json, */*"}
        query: list[tuple[str, str]] = []
        for parameter in extra.get("parameter") or []:
            wert = argumente.get(parameter["schluessel"])
            if wert is None:
                if parameter["ort"] == "path":
                    raise IntegrationsFehler(f"Der Parameter „{parameter['schluessel']}“ fehlt.")
                continue
            if parameter["ort"] == "path":
                pfad = pfad.replace("{" + parameter["name"] + "}", quote(str(wert), safe=""))
            elif parameter["ort"] == "query":
                werte = wert if isinstance(wert, list) else [wert]
                query.extend((parameter["name"], _als_text(eintrag)) for eintrag in werte)
            elif parameter["ort"] == "header":
                headers[parameter["name"]] = _als_text(wert)

        auth = kontext.zustand.get("auth") or {"art": "bearer"}
        _auth_anwenden(auth, kontext.zugang_optional("zugang"), headers, query)

        optionen: dict[str, Any] = {}
        koerper = extra.get("koerper")
        if koerper and "body" in argumente:
            if koerper.get("art") == "formular":
                optionen["data"] = argumente["body"]
            else:
                optionen["json"] = argumente["body"]
                if koerper.get("medientyp"):
                    headers["Content-Type"] = koerper["medientyp"]

        async with kontext.http(timeout=httpx2.Timeout(60.0, connect=10.0)) as client:
            antwort = await client.request(
                extra["methode"], basis.rstrip("/") + pfad, params=query or None, headers=headers, **optionen
            )
        inhalt = _antwort_lesen(antwort)
        if antwort.status_code >= 400:
            meldung, hinweis = http_status_erklaeren(antwort.status_code)
            auszug = inhalt if isinstance(inhalt, str) else json.dumps(inhalt, ensure_ascii=False)
            if auszug:
                meldung = f"{meldung} Antwort: {auszug[:400]}"
            raise IntegrationsFehler(meldung, hinweis)
        return AufrufErgebnis(wert=inhalt if inhalt != "" else {"status": antwort.status_code})


def _als_text(wert: Any) -> str:
    if isinstance(wert, bool):
        return "true" if wert else "false"
    return str(wert)


def _antwort_lesen(antwort: httpx2.Response) -> Any:
    typ = antwort.headers.get("content-type", "")
    if "json" in typ:
        try:
            return antwort.json()
        except ValueError:
            pass
    text = antwort.text
    if len(text) > MAX_ANTWORT_ZEICHEN:
        text = text[:MAX_ANTWORT_ZEICHEN] + "\n… (gekürzt)"
    return text
