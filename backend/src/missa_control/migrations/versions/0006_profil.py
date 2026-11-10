"""Charakterprofil: Versionen

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profil_versionen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("kommentar", sa.Text(), nullable=False),
        sa.Column("inhalt", sa.JSON(), nullable=False),
    )
    op.create_index("ix_profil_versionen_erstellt", "profil_versionen", ["erstellt"])


def downgrade() -> None:
    op.drop_table("profil_versionen")
