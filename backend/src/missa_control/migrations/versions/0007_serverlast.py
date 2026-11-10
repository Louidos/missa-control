"""Serverlast: Messwerte

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messwerte",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("ram", sa.Float(), nullable=False),
        sa.Column("speicher", sa.Float(), nullable=False),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("cpu_temp", sa.Float(), nullable=True),
        sa.Column("gpu", sa.Float(), nullable=True),
        sa.Column("gpu_speicher", sa.Float(), nullable=True),
        sa.Column("gpu_temp", sa.Float(), nullable=True),
    )
    op.create_index("ix_messwerte_zeit", "messwerte", ["zeit"])


def downgrade() -> None:
    op.drop_table("messwerte")
