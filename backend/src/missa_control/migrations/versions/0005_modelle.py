"""Modelle: Modell-Endpunkte, Rollen und Anfragen-Statistik

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modelle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column(
            "zugang_id", sa.Integer(), sa.ForeignKey("zugaenge.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("modellname", sa.String(), nullable=False),
        sa.Column("kontextlaenge", sa.Integer(), nullable=True),
        sa.Column("test_ok", sa.Boolean(), nullable=True),
        sa.Column("test_meldung", sa.Text(), nullable=False),
        sa.Column("test_hinweis", sa.Text(), nullable=False),
        sa.Column("test_ms", sa.Integer(), nullable=True),
        sa.Column("test_tokens_pro_s", sa.Float(), nullable=True),
        sa.Column("getestet", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("geaendert", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "modell_rollen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kennung", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("beschreibung", sa.Text(), nullable=False),
        sa.Column(
            "haupt_modell_id", sa.Integer(), sa.ForeignKey("modelle.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "ersatz_modell_id", sa.Integer(), sa.ForeignKey("modelle.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("fest", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "modell_anfragen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("modell_id", sa.Integer(), nullable=False),
        sa.Column("rolle", sa.String(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("dauer_ms", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("tokens_pro_s", sa.Float(), nullable=True),
        sa.Column("ersatz", sa.Boolean(), nullable=False),
        sa.Column("fehler", sa.Text(), nullable=False),
    )
    op.create_index("ix_modell_anfragen_zeit", "modell_anfragen", ["zeit"])
    op.create_index("ix_modell_anfragen_modell_id", "modell_anfragen", ["modell_id"])


def downgrade() -> None:
    for tabelle in ("modell_anfragen", "modell_rollen", "modelle"):
        op.drop_table(tabelle)
