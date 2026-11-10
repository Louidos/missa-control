"""Clients anlegen, Tokens prüfen und widerrufen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from missa_control import zeit
from missa_control.clients.modelle import Client
from missa_control.fehler import PanelFehler
from missa_control.krypto import Krypto
from missa_control.zugaenge.schwaerzen import SCHWAERZER

TOKEN_PRAEFIX = "mc_"
_GESEHEN_ABSTAND = timedelta(minutes=1)


@dataclass(frozen=True)
class ClientAngaben:
    """Der angemeldete Client einer Anfrage."""

    id: int
    name: str


class ClientDienst:
    def __init__(self, krypto: Krypto) -> None:
        self.krypto = krypto

    def alle(self, db: Session) -> list[dict[str, object]]:
        return [self.ansicht(client) for client in db.scalars(select(Client).order_by(Client.name))]

    @staticmethod
    def ansicht(client: Client) -> dict[str, object]:
        return {
            "id": client.id,
            "name": client.name,
            "token_anfang": client.token_anfang,
            "erstellt": client.erstellt.isoformat(),
            "zuletzt_gesehen": client.zuletzt_gesehen.isoformat() if client.zuletzt_gesehen else None,
            "widerrufen": client.widerrufen.isoformat() if client.widerrufen else None,
            "aktiv": client.widerrufen is None,
        }

    def anlegen(self, db: Session, name: str) -> tuple[Client, str]:
        """Legt einen Client an und gibt ihn mit seinem Token zurück – der Token ist nur jetzt lesbar."""
        name = name.strip()
        if not name:
            raise PanelFehler(422, "Bitte einen Namen für den Client angeben.", "Zum Beispiel „missa-core“.")
        if db.scalar(select(Client).where(Client.name == name)) is not None:
            raise PanelFehler(
                409,
                f"Es gibt bereits einen Client mit dem Namen „{name}“.",
                "Bitte einen anderen Namen wählen.",
            )
        token = self.krypto.neuer_token(TOKEN_PRAEFIX)
        SCHWAERZER.merken(token)
        client = Client(
            name=name,
            token_pruefsumme=self.krypto.token_pruefsumme(token),
            token_anfang=token[:7] + "…",
            erstellt=zeit.jetzt(),
        )
        db.add(client)
        db.commit()
        return client, token

    def holen(self, db: Session, client_id: int) -> Client:
        client = db.get(Client, client_id)
        if client is None:
            raise PanelFehler(404, "Diesen Client gibt es nicht (mehr).")
        return client

    def widerrufen(self, db: Session, client_id: int) -> Client:
        client = self.holen(db, client_id)
        if client.widerrufen is None:
            client.widerrufen = zeit.jetzt()
            db.commit()
        return client

    def loeschen(self, db: Session, client_id: int) -> None:
        db.delete(self.holen(db, client_id))
        db.commit()

    def pruefen(self, db: Session, token: str | None) -> ClientAngaben | None:
        """Gibt den Client zum Token zurück – oder `None`, wenn der Token unbekannt oder widerrufen ist."""
        if not token or not token.startswith(TOKEN_PRAEFIX):
            return None
        client = db.scalar(
            select(Client).where(Client.token_pruefsumme == self.krypto.token_pruefsumme(token))
        )
        if client is None or client.widerrufen is not None:
            return None
        jetzt = zeit.jetzt()
        if client.zuletzt_gesehen is None or jetzt - client.zuletzt_gesehen > _GESEHEN_ABSTAND:
            client.zuletzt_gesehen = jetzt
            db.commit()
        return ClientAngaben(id=client.id, name=client.name)
