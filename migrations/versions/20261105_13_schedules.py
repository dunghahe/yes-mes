"""Create production schedules.

Revision ID: 20261105_13
Revises: 20261105_12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_13"
down_revision: str | None = "20261105_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("planned_quantity > 0", name="ck_schedules_quantity_positive"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedules_date_shift_active", "schedules", ["production_date", "shift_id", "deleted_at"]
    )
    op.create_index("ix_schedules_order_active", "schedules", ["order_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_schedules_order_active", table_name="schedules")
    op.drop_index("ix_schedules_date_shift_active", table_name="schedules")
    op.drop_table("schedules")
