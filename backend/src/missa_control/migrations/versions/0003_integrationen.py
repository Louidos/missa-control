"""Integrationen: eingerichtete Integrationen und ihre Funktionen mit Rechten

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrationen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manifest_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kennung", sa.String(), nullable=False, unique=True),
        sa.Column("konfig", sa.JSON(), nullable=False),
        sa.Column("zustand", sa.JSON(), nullable=False),
        sa.Column("aktiv", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_meldung", sa.Text(), nullable=False),
        sa.Column("status_hinweis", sa.Text(), nullable=False),
        sa.Column("geprueft", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("geaendert", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_integrationen_manifest_id", "integrationen", ["manifest_id"])
    op.create_table(
        "funktionen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("integrationen.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("beschreibung", sa.Text(), nullable=False),
        sa.Column("parameter", sa.JSON(), nullable=False),
        sa.Column("schreibend", sa.Boolean(), nullable=False),
        sa.Column("recht", sa.String(), nullable=False),
        sa.Column("vorhanden", sa.Boolean(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.UniqueConstraint("integration_id", "name", name="uq_funktionen_integration_name"),
    )
    op.create_index("ix_funktionen_integration_id", "funktionen", ["integration_id"])


def downgrade() -> None:
    op.drop_table("funktionen")
    op.drop_table("integrationen")
