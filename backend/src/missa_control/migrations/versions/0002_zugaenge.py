"""Zugänge: verschlüsselt gespeicherte API-Keys, Tokens und Passwörter

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zugaenge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("typ", sa.String(), nullable=False),
        sa.Column("benutzer", sa.String(), nullable=True),
        sa.Column("wert_verschluesselt", sa.Text(), nullable=False),
        sa.Column("notiz", sa.Text(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("geaendert", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("zugaenge")
