"""Clients: wann ein Client zuletzt die Funktionen abgeholt hat (tools/list)

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as tabelle:
        tabelle.add_column(sa.Column("zuletzt_abgeholt", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as tabelle:
        tabelle.drop_column("zuletzt_abgeholt")
