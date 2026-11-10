"""Regeln und Alarme mit Verlauf der Auslösungen

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regeln",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aktiv", sa.Boolean(), nullable=False),
        sa.Column("ausloeser", sa.JSON(), nullable=False),
        sa.Column("bedingung", sa.JSON(), nullable=False),
        sa.Column("aktion", sa.JSON(), nullable=False),
        sa.Column("ruhezeit_minuten", sa.Integer(), nullable=False),
        sa.Column("quelle", sa.String(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("geaendert", sa.DateTime(), nullable=False),
        sa.Column("zuletzt_ausgeloest", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "regel_ausloesungen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("regel_id", sa.Integer(), sa.ForeignKey("regeln.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("anlass", sa.Text(), nullable=False),
        sa.Column("ergebnis", sa.String(), nullable=False),
        sa.Column("meldung", sa.Text(), nullable=False),
        sa.Column("test", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_regel_ausloesungen_regel_id", "regel_ausloesungen", ["regel_id"])
    op.create_index("ix_regel_ausloesungen_zeit", "regel_ausloesungen", ["zeit"])


def downgrade() -> None:
    op.drop_table("regel_ausloesungen")
    op.drop_table("regeln")
