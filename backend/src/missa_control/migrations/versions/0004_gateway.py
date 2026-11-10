"""Gateway: Clients, Freigaben, Protokoll der Aufrufe und Ereignisse

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("token_pruefsumme", sa.String(), nullable=False),
        sa.Column("token_anfang", sa.String(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("zuletzt_gesehen", sa.DateTime(), nullable=True),
        sa.Column("widerrufen", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_clients_token_pruefsumme", "clients", ["token_pruefsumme"], unique=True)

    op.create_table(
        "ereignisse",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("art", sa.String(), nullable=False),
        sa.Column("quelle", sa.String(), nullable=False),
        sa.Column("titel", sa.String(), nullable=False),
        sa.Column("nachricht", sa.Text(), nullable=False),
        sa.Column("dringlichkeit", sa.String(), nullable=False),
        sa.Column("daten", sa.JSON(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_ereignisse_zeit", "ereignisse", ["zeit"])
    op.create_index("ix_ereignisse_art", "ereignisse", ["art"])

    op.create_table(
        "freigaben",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("laeuft_ab", sa.DateTime(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("integration_name", sa.String(), nullable=False),
        sa.Column("funktion", sa.String(), nullable=False),
        sa.Column("beschreibung", sa.Text(), nullable=False),
        sa.Column("argumente", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("entschieden", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_freigaben_erstellt", "freigaben", ["erstellt"])
    op.create_index("ix_freigaben_status", "freigaben", ["status"])

    op.create_table(
        "aufrufe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zeit", sa.DateTime(), nullable=False),
        sa.Column("quelle", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("integration_name", sa.String(), nullable=False),
        sa.Column("funktion", sa.String(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("fehler", sa.Text(), nullable=False),
        sa.Column("dauer_ms", sa.Integer(), nullable=False),
        sa.Column("freigabe", sa.String(), nullable=False),
    )
    op.create_index("ix_aufrufe_zeit", "aufrufe", ["zeit"])
    op.create_index("ix_aufrufe_funktion", "aufrufe", ["funktion"])


def downgrade() -> None:
    for tabelle in ("aufrufe", "freigaben", "ereignisse", "clients"):
        op.drop_table(tabelle)
