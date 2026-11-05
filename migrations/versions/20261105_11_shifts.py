"""Create production shift master data.

Revision ID: 20261105_11
Revises: 20261105_10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_11"
down_revision: str | None = "20261105_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shifts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("planned_break_minutes", sa.Integer(), nullable=False),
        sa.Column("crosses_midnight", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("start_time <> end_time", name="ck_shifts_distinct_start_end"),
        sa.CheckConstraint(
            "(crosses_midnight AND end_time < start_time) OR "
            "(NOT crosses_midnight AND end_time > start_time)",
            name="ck_shifts_midnight_matches_times",
        ),
        sa.CheckConstraint("planned_break_minutes >= 0", name="ck_shifts_break_nonnegative"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_shifts_name_not_deleted",
        "shifts",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_shifts_active_start", "shifts", ["is_active", "start_time"])


def downgrade() -> None:
    op.drop_index("ix_shifts_active_start", table_name="shifts")
    op.drop_index("uq_shifts_name_not_deleted", table_name="shifts")
    op.drop_table("shifts")
