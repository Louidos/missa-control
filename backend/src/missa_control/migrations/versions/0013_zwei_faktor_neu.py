"""Login: Merker für den Notfall-Reset der Zwei-Faktor-Anmeldung

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin", sa.Column("zwei_faktor_neu", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("admin", "zwei_faktor_neu")
