"""Meldungen: Ziele (ntfy oder Webhook), an die das Panel von sich aus Nachrichten schickt

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meldeziele",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("art", sa.String(), nullable=False),
        sa.Column("adresse", sa.String(), nullable=False),
        sa.Column("thema", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "zugang_id", sa.Integer(), sa.ForeignKey("zugaenge.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("panel_adresse", sa.String(), nullable=False, server_default=""),
        sa.Column("arten", sa.JSON(), nullable=False),
        sa.Column("aktiv", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("letzter_fehler", sa.Text(), nullable=False, server_default=""),
        sa.Column("letzter_fehler_zeit", sa.DateTime(), nullable=True),
        sa.Column("zuletzt_gesendet", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("meldeziele")
