"""Integrationen: Zugriffsstufe pro Integration und Merker für neue Funktionen

Bestehende Integrationen bekommen die Stufe „nachfragen“; ihre einzelnen Rechte bleiben unverändert.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("integrationen") as tabelle:
        tabelle.add_column(sa.Column("zugriff", sa.String(), nullable=False, server_default="nachfragen"))
    with op.batch_alter_table("funktionen") as tabelle:
        tabelle.add_column(sa.Column("zu_pruefen", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("funktionen") as tabelle:
        tabelle.drop_column("zu_pruefen")
    with op.batch_alter_table("integrationen") as tabelle:
        tabelle.drop_column("zugriff")
