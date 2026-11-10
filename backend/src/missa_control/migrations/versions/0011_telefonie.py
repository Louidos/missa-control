"""Telefonie: Einstellungen und Anrufverlauf

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telefonie_einstellungen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adapter", sa.String(), nullable=False),
        sa.Column("landesvorwahl", sa.String(), nullable=False),
        sa.Column("eigene_nummern", sa.JSON(), nullable=False),
        sa.Column("erlaubte_anrufer", sa.JSON(), nullable=False),
        sa.Column("ruhezeiten", sa.JSON(), nullable=False),
        sa.Column("nur_bekannte", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "anrufe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("richtung", sa.String(), nullable=False),
        sa.Column("nummer", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dauer_sekunden", sa.Integer(), nullable=True),
        sa.Column("grund", sa.String(), nullable=False),
        sa.Column("dringlichkeit", sa.String(), nullable=False),
        sa.Column("quelle", sa.String(), nullable=False),
        sa.Column("quelle_name", sa.String(), nullable=False),
        sa.Column("adapter", sa.String(), nullable=False),
        sa.Column("meldung", sa.String(), nullable=False),
        sa.Column("beendet", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_anrufe_zeit", "anrufe", ["zeit"])


def downgrade() -> None:
    op.drop_index("ix_anrufe_zeit", table_name="anrufe")
    op.drop_table("anrufe")
    op.drop_table("telefonie_einstellungen")
