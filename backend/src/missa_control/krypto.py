"""Verschlüsselung und Token-Prüfsummen.

- `ENCRYPTION_KEY` (Fernet) verschlüsselt alles, was wieder lesbar sein muss (z. B. das 2FA-Geheimnis).
- `SECRET_KEY` dient als Schlüssel für Prüfsummen von Tokens: In der Datenbank steht nie der Token
  selbst, nur seine Prüfsumme. Ohne `SECRET_KEY` lässt sich daraus kein gültiger Token ableiten.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken


class EntschluesselungsFehler(Exception):
    """Der Wert lässt sich mit dem aktuellen ENCRYPTION_KEY nicht lesen."""


class Krypto:
    def __init__(self, secret_key: str, encryption_key: str) -> None:
        self._secret = secret_key.encode()
        self._fernet = Fernet(encryption_key.encode())

    def verschluesseln(self, klartext: str) -> str:
        return self._fernet.encrypt(klartext.encode()).decode()

    def entschluesseln(self, geheimtext: str) -> str:
        try:
            return self._fernet.decrypt(geheimtext.encode()).decode()
        except InvalidToken as fehler:
            raise EntschluesselungsFehler(
                "Wert kann nicht entschlüsselt werden – wurde ENCRYPTION_KEY in der .env geändert?"
            ) from fehler

    def token_pruefsumme(self, token: str) -> str:
        """Prüfsumme eines Tokens (HMAC-SHA256), so wird der Token in der Datenbank abgelegt."""
        return hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def neuer_token(praefix: str = "") -> str:
        return praefix + secrets.token_urlsafe(32)
