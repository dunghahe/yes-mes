"""Record blank request print events.

Revision ID: 20261105_15
Revises: 20261105_14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_15"
down_revision: str | None = "20261105_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blank_request_prints",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("blank_request_id", sa.BigInteger(), nullable=False),
        sa.Column("form_type", sa.String(20), nullable=False),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("printed_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "form_type IN ('production', 'qc')", name="ck_blank_request_prints_form_type"
        ),
        sa.ForeignKeyConstraint(["blank_request_id"], ["blank_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["printed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blank_request_prints_request_type_time",
        "blank_request_prints",
        ["blank_request_id", "form_type", "printed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_blank_request_prints_request_type_time", table_name="blank_request_prints")
    op.drop_table("blank_request_prints")
