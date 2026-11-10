"""Geräte: gekoppelte Geräte und ihre Messwerte

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geraete",
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integrationen.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mqtt_benutzer", sa.String(), nullable=False, unique=True),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("status_seit", sa.DateTime(), nullable=True),
        sa.Column("zuletzt_gesehen", sa.DateTime(), nullable=True),
        sa.Column("firmware", sa.String(), nullable=False),
        sa.Column("faehigkeiten", sa.JSON(), nullable=False),
        sa.Column("letzte", sa.JSON(), nullable=False),
        sa.Column("gekoppelt", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "geraete_werte",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integrationen.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("faehigkeit", sa.String(), nullable=False),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("wert", sa.Float(), nullable=False),
    )
    op.create_index("ix_geraete_werte_integration_id", "geraete_werte", ["integration_id"])
    op.create_index("ix_geraete_werte_zeit", "geraete_werte", ["zeit"])


def downgrade() -> None:
    op.drop_table("geraete_werte")
    op.drop_table("geraete")
