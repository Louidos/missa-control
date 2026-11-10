"""Macht aus technischen Fehlern verständliche Meldungen mit Lösungshinweis."""

from __future__ import annotations

import ssl

import httpx2
from mcp.shared.exceptions import MCPError

from missa_control.fehler import PanelFehler
from missa_control.integrationen.typen import IntegrationsFehler
from missa_control.krypto import EntschluesselungsFehler
from missa_control.zugaenge.schwaerzen import SCHWAERZER

_STATUS_TEXTE: dict[int, tuple[str, str]] = {
    400: ("Die Gegenstelle hat die Anfrage abgelehnt (400).", "Stimmen die übergebenen Werte?"),
    401: (
        "Die Gegenstelle lehnt den Zugang ab (401 – nicht angemeldet).",
        "Ist der richtige Zugang ausgewählt und der Key bzw. das Token noch gültig? Unter „Zugänge“ lässt sich der Wert neu eintragen.",
    ),
    403: (
        "Der Zugang hat dafür keine Berechtigung (403).",
        "Der Key bzw. das Token ist gültig, darf diese Aktion aber nicht ausführen – bitte bei der Gegenstelle die Rechte prüfen.",
    ),
    404: (
        "Die Adresse wurde nicht gefunden (404).",
        "Stimmt die URL – vor allem der Pfad am Ende? Ein Tippfehler oder ein fehlendes /mcp bzw. /api ist häufig die Ursache.",
    ),
    405: (
        "Die Gegenstelle erlaubt diese Art von Anfrage nicht (405).",
        "Stimmt die URL und die Art der Verbindung?",
    ),
    408: ("Die Gegenstelle hat zu lange gebraucht (408).", "Später erneut versuchen."),
    429: (
        "Zu viele Anfragen – die Gegenstelle bremst (429).",
        "Kurz warten und erneut versuchen. Tritt das oft auf, hat der Zugang ein zu kleines Kontingent.",
    ),
}


def http_status_erklaeren(status: int) -> tuple[str, str]:
    if status in _STATUS_TEXTE:
        return _STATUS_TEXTE[status]
    if status >= 500:
        return (
            f"Die Gegenstelle meldet einen internen Fehler ({status}).",
            "Das Problem liegt beim anderen Dienst. Läuft er richtig? Später erneut versuchen.",
        )
    return (f"Die Gegenstelle antwortet mit einem Fehler ({status}).", "Bitte URL und Zugang prüfen.")


def _ursachen(fehler: BaseException) -> list[BaseException]:
    """Der Fehler selbst, seine Ursachen und – bei Fehlergruppen – alle enthaltenen Fehler."""
    gefunden: list[BaseException] = []
    offen: list[BaseException] = [fehler]
    while offen and len(gefunden) < 50:
        aktuell = offen.pop(0)
        if aktuell in gefunden:
            continue
        gefunden.append(aktuell)
        if isinstance(aktuell, BaseExceptionGroup):
            offen.extend(aktuell.exceptions)
        if aktuell.__cause__ is not None:
            offen.append(aktuell.__cause__)
        if aktuell.__context__ is not None:
            offen.append(aktuell.__context__)
    return gefunden


def ist_ausfall(fehler: BaseException) -> bool:
    """Liegt es an der Gegenstelle (nicht erreichbar, Zugang abgelehnt, interner Fehler dort)?

    Dann ist nicht nur dieser eine Aufruf gescheitert – die Integration gilt als ausgefallen.
    """
    for ursache in _ursachen(fehler):
        if isinstance(ursache, httpx2.HTTPStatusError):
            status = ursache.response.status_code
            return status in (401, 403) or status >= 500
        if isinstance(ursache, httpx2.TransportError | ConnectionError | ssl.SSLError):
            return True
    return False


def fehler_erklaeren(fehler: BaseException) -> tuple[str, str | None]:
    """Gibt (Meldung, Lösungshinweis) zurück. Geheimnisse werden dabei geschwärzt."""
    meldung, hinweis = _erklaeren(fehler)
    return SCHWAERZER.schwaerzen(meldung), SCHWAERZER.schwaerzen(hinweis) if hinweis else None


def _erklaeren(fehler: BaseException) -> tuple[str, str | None]:
    kette = _ursachen(fehler)

    for ursache in kette:
        if isinstance(ursache, IntegrationsFehler):
            return ursache.meldung, ursache.hinweis
        if isinstance(ursache, PanelFehler):
            return ursache.meldung, ursache.hinweis
        if isinstance(ursache, EntschluesselungsFehler):
            return (
                "Der hinterlegte Zugang lässt sich nicht entschlüsseln.",
                "Wurde ENCRYPTION_KEY in der .env geändert? Den Wert unter „Zugänge“ neu eintragen.",
            )

    for ursache in kette:
        if isinstance(ursache, httpx2.HTTPStatusError):
            return http_status_erklaeren(ursache.response.status_code)
        if isinstance(ursache, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(ursache):
            return (
                "Das Zertifikat der Gegenstelle ist ungültig oder unbekannt.",
                "Bei selbst ausgestellten Zertifikaten im eigenen Netz die Adresse mit http:// statt https:// "
                "verwenden oder ein gültiges Zertifikat einrichten.",
            )
        if isinstance(ursache, httpx2.ConnectTimeout | httpx2.PoolTimeout):
            return (
                "Die Gegenstelle antwortet nicht (Zeitüberschreitung beim Verbinden).",
                "Ist die Adresse von ai01 aus erreichbar? Firewall, VPN und den Port in der URL prüfen.",
            )
        if isinstance(ursache, httpx2.TimeoutException | TimeoutError):
            return (
                "Die Gegenstelle hat zu lange für die Antwort gebraucht.",
                "Der Dienst ist erreichbar, aber langsam oder überlastet. Später erneut versuchen.",
            )
        if isinstance(ursache, httpx2.ConnectError | ConnectionError):
            text = str(ursache).lower()
            if "name or service not known" in text or "nodename" in text or "name resolution" in text:
                return (
                    "Der Servername ist unbekannt.",
                    "Stimmt die Adresse? ai01 muss den Namen auflösen können – notfalls die IP-Adresse verwenden.",
                )
            return (
                "Die Gegenstelle ist nicht erreichbar.",
                "Läuft der Dienst und stimmen Adresse und Port? ai01 muss ihn im Netz erreichen können "
                "(Achtung: „localhost“ meint hier den Panel-Container, nicht ai01 selbst).",
            )
        if isinstance(ursache, httpx2.UnsupportedProtocol | httpx2.InvalidURL):
            return (
                "Die URL ist ungültig.",
                "Eine vollständige Adresse angeben, z. B. http://192.168.1.20:8000/mcp",
            )
        if isinstance(ursache, httpx2.TransportError):
            return (
                "Die Verbindung zur Gegenstelle ist abgebrochen.",
                "Läuft der Dienst stabil? Stimmt http:// bzw. https:// in der URL?",
            )

    for ursache in kette:
        if isinstance(ursache, MCPError):
            return (
                f"Der MCP-Server meldet einen Fehler: {ursache.message}",
                "Die Verbindung steht, aber der Server lehnt die Anfrage ab. Details stehen im Protokoll des MCP-Servers.",
            )

    kurz = str(fehler).strip() or type(fehler).__name__
    return (f"Unerwarteter Fehler: {kurz[:300]}", "Details stehen im Protokoll des Panels.")
