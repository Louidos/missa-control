"""Übersicht: von Hand gesetzte Positionen der Knoten

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uebersicht_positionen",
        sa.Column("knoten", sa.String(), primary_key=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("uebersicht_positionen")
