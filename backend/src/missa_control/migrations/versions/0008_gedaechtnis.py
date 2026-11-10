"""Gedächtnis: Einträge mit Volltextsuche; Freigaben: Vorschau, was genau passiert

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gedaechtnis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kategorie", sa.String(), nullable=False),
        sa.Column("quelle", sa.String(), nullable=False),
        sa.Column("erstellt", sa.DateTime(), nullable=False),
        sa.Column("geaendert", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gedaechtnis_kategorie", "gedaechtnis", ["kategorie"])

    # Volltext-Index (FTS5). „trigram“ findet auch Wortteile – wichtig bei zusammengesetzten Wörtern
    # („schlüssel“ findet „Autoschlüssel“). Die Trigger halten den Index bei jeder Änderung aktuell.
    op.execute(
        "CREATE VIRTUAL TABLE gedaechtnis_fts USING fts5("
        "text, content='gedaechtnis', content_rowid='id', tokenize='trigram')"
    )
    op.execute(
        "CREATE TRIGGER gedaechtnis_fts_neu AFTER INSERT ON gedaechtnis BEGIN "
        "INSERT INTO gedaechtnis_fts(rowid, text) VALUES (new.id, new.text); END"
    )
    op.execute(
        "CREATE TRIGGER gedaechtnis_fts_weg AFTER DELETE ON gedaechtnis BEGIN "
        "INSERT INTO gedaechtnis_fts(gedaechtnis_fts, rowid, text) VALUES ('delete', old.id, old.text); END"
    )
    op.execute(
        "CREATE TRIGGER gedaechtnis_fts_anders AFTER UPDATE OF text ON gedaechtnis BEGIN "
        "INSERT INTO gedaechtnis_fts(gedaechtnis_fts, rowid, text) VALUES ('delete', old.id, old.text); "
        "INSERT INTO gedaechtnis_fts(rowid, text) VALUES (new.id, new.text); END"
    )

    op.add_column("freigaben", sa.Column("vorschau", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("freigaben", "vorschau")
    for trigger in ("gedaechtnis_fts_neu", "gedaechtnis_fts_weg", "gedaechtnis_fts_anders"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS gedaechtnis_fts")
    op.drop_table("gedaechtnis")
