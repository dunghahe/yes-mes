"""Create product master data table.

Revision ID: 20261105_06
Revises: 20261105_05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_06"
down_revision: str | None = "20261105_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cycle_time_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("default_process_type", sa.String(length=20), nullable=False),
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
        sa.CheckConstraint("cycle_time_seconds > 0", name="ck_products_cycle_time_positive"),
        sa.CheckConstraint(
            "default_process_type IN ('FULL', 'SX_ONLY', 'BAVIA_ONLY')",
            name="ck_products_default_process_type",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_products_code_not_deleted",
        "products",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_products_active_name", "products", ["is_active", "name"])


def downgrade() -> None:
    op.drop_index("ix_products_active_name", table_name="products")
    op.drop_index("uq_products_code_not_deleted", table_name="products")
    op.drop_table("products")
