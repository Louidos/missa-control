"""Zugriffsschutz für das ganze Panel.

Grundsatz: Alles unter `/api/`, `/mcp` und `/v1/` ist gesperrt, solange es nicht ausdrücklich
freigegeben ist. Neue Routen sind dadurch automatisch geschützt. Die Oberfläche selbst (HTML, JS,
CSS) enthält keine Daten und wird ohne Anmeldung ausgeliefert, damit der Login angezeigt werden kann.

Einzige weitere Ausnahme sind eingehende Webhooks (`/api/webhook/<Schlüssel>`): Dort ist der zufällige
Schlüssel in der Adresse der Zugang. Sie nehmen nur Meldungen entgegen und geben nichts heraus.

Es gibt zwei getrennte Wege hinein:
- das Panel selbst: nur mit der Sitzung des Admins (Cookie nach Login mit Passwort + 2FA)
- die Anschlüsse für Clients wie missa-core (`/mcp`, `/v1/`, `/api/events`, `/api/config/`):
  nur mit einem Client-Token. Eine Admin-Sitzung öffnet diese Anschlüsse nicht – und umgekehrt.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from missa_control.auth.dienst import AuthDienst
from missa_control.auth.routen import SITZUNGS_COOKIE
from missa_control.clients.dienst import ClientAngaben, ClientDienst
from missa_control.db import Datenbank
from missa_control.fehler import fehler_antwort

# Ohne Anmeldung erreichbar: Health-Check und alles, was der Login selbst braucht.
OEFFENTLICHE_PFADE = frozenset(
    {
        "/api/health",
        "/api/auth/status",
        "/api/auth/einrichten",
        "/api/auth/einrichten/bestaetigen",
        "/api/auth/anmelden",
    }
)
_LESENDE_METHODEN = frozenset({"GET", "HEAD", "OPTIONS"})

SICHERHEITS_HEADER = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


CLIENT_SCHLUESSEL = "missa_control.client"


def ist_client_pfad(pfad: str) -> bool:
    """Anschlüsse für Clients (missa-core, Apps): Zugriff nur mit Client-Token."""
    return pfad in ("/mcp", "/v1", "/api/events") or pfad.startswith(
        ("/mcp/", "/v1/", "/api/events/", "/api/config/", "/api/telefonie/adapter/")
    )


def ist_webhook_pfad(pfad: str) -> bool:
    """Eingehende Webhooks: Der zufällige Schlüssel in der Adresse ist der Zugang."""
    return pfad.startswith("/api/webhook/")


def ist_geschuetzt(pfad: str) -> bool:
    return pfad.startswith(("/api/", "/v1/", "/mcp/")) or pfad in ("/api", "/v1", "/mcp")


class Zugriffsschutz:
    """ASGI-Middleware: prüft die Sitzung, wehrt fremde Seiten ab (CSRF) und setzt Sicherheits-Header."""

    def __init__(
        self, app: ASGIApp, *, auth: AuthDienst, clients: ClientDienst, datenbank: Datenbank
    ) -> None:
        self.app = app
        self.auth = auth
        self.clients = clients
        self.datenbank = datenbank

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_mit_headern(nachricht: Message) -> None:
            if nachricht["type"] == "http.response.start":
                headers = MutableHeaders(scope=nachricht)
                for name, wert in SICHERHEITS_HEADER.items():
                    headers.setdefault(name, wert)
                if ist_geschuetzt(scope["path"]):
                    headers.setdefault("Cache-Control", "no-store")
            await send(nachricht)

        ablehnung = self._pruefen(scope)
        if ablehnung is not None:
            await ablehnung(scope, receive, send_mit_headern)
            return
        await self.app(scope, receive, send_mit_headern)

    def _pruefen(self, scope: Scope) -> ASGIApp | None:
        """Gibt eine fertige Fehlerantwort zurück, wenn die Anfrage nicht durchgelassen wird."""
        pfad: str = scope["path"]
        if not ist_geschuetzt(pfad):
            return None
        if ist_webhook_pfad(pfad):
            return None  # ohne Anmeldung und ohne Herkunftsprüfung – es zählt allein der Schlüssel
        headers = Headers(scope=scope)
        if ist_client_pfad(pfad):
            client = self._client(headers)
            if client is None:
                antwort = fehler_antwort(
                    401,
                    "Kein gültiger Client-Token.",
                    "Im Panel unter „Clients“ einen Token erzeugen und als „Authorization: Bearer <Token>“ mitsenden.",
                )
                if pfad.startswith("/v1"):
                    antwort = _openai_fehler(401, "Kein gültiger Client-Token (als API-Key mitsenden).")
                antwort.headers["WWW-Authenticate"] = "Bearer"
                return antwort
            scope[CLIENT_SCHLUESSEL] = client
            return None
        if scope["method"] not in _LESENDE_METHODEN and not _gleiche_herkunft(headers):
            return fehler_antwort(403, "Anfrage von einer fremden Seite abgelehnt.")
        if pfad in OEFFENTLICHE_PFADE:
            return None
        if not self._angemeldet(headers):
            return fehler_antwort(401, "Nicht angemeldet.", "Bitte mit Passwort und Code anmelden.")
        return None

    def _client(self, headers: Headers) -> ClientAngaben | None:
        art, _, token = headers.get("authorization", "").partition(" ")
        if art.lower() != "bearer" or not token.strip():
            return None
        with self.datenbank.sitzung() as db:
            return self.clients.pruefen(db, token.strip())

    def _angemeldet(self, headers: Headers) -> bool:
        cookies: SimpleCookie = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
        except Exception:
            return False
        eintrag = cookies.get(SITZUNGS_COOKIE)
        if eintrag is None:
            return False
        with self.datenbank.sitzung() as db:
            return self.auth.sitzung_gueltig(db, eintrag.value)


def _openai_fehler(status: int, meldung: str) -> JSONResponse:
    """Fehler im Format der OpenAI-API – so zeigen OpenAI-Clients die Meldung an."""
    return JSONResponse(
        {"error": {"message": meldung, "type": "authentication_error", "code": "invalid_api_key"}},
        status_code=status,
    )


def _gleiche_herkunft(headers: Headers) -> bool:
    """Browser senden bei ändernden Anfragen `Origin`. Stimmt er nicht mit dem Panel überein: ablehnen."""
    origin = headers.get("origin")
    if origin is None:
        return True  # kein Browser (z. B. curl) – hier schützt der SameSite-Cookie
    return urlsplit(origin).netloc == headers.get("host", "")
