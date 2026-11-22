"""Persist short-lived spreadsheet previews between app workers.

Revision ID: 20261114_30
Revises: 20261114_29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261114_30"
down_revision: str | None = "20261114_29"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "import_previews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("resource", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_import_previews_token_hash"),
    )
    op.create_index(
        "ix_import_previews_expires_at", "import_previews", ["expires_at"], unique=False
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON TABLE import_previews TO mes_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE import_previews_id_seq TO mes_app")


def downgrade() -> None:
    op.drop_index("ix_import_previews_expires_at", table_name="import_previews")
    op.drop_table("import_previews")
