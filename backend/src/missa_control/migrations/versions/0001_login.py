"""Login: Admin-Benutzer und Sitzungen

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passwort_hash", sa.String(), nullable=False),
        sa.Column("totp_geheimnis", sa.String(), nullable=False),
        sa.Column("eingerichtet", sa.Boolean(), nullable=False),
        sa.Column("einrichtung_pruefsumme", sa.String(), nullable=True),
        sa.Column("totp_letzter_schritt", sa.Integer(), nullable=True),
        sa.Column("fehlversuche", sa.Integer(), nullable=False),
        sa.Column("gesperrt_bis", sa.DateTime(), nullable=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sitzungen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_pruefsumme", sa.String(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("laeuft_ab", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sitzungen_token_pruefsumme", "sitzungen", ["token_pruefsumme"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sitzungen_token_pruefsumme", table_name="sitzungen")
    op.drop_table("sitzungen")
    op.drop_table("admin")
