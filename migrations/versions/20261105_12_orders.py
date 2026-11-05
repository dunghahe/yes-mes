"""Create production orders with required material data.

Revision ID: 20261105_12
Revises: 20261105_11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_12"
down_revision: str | None = "20261105_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("po_no", sa.String(100), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("ordered_quantity", sa.Integer(), nullable=False),
        sa.Column("process_type", sa.String(20), nullable=False),
        sa.Column("raw_material_code", sa.String(100), nullable=False),
        sa.Column("drawing_number", sa.String(100), nullable=False),
        sa.Column("revision", sa.String(30), nullable=False),
        sa.Column("material", sa.String(100), nullable=False),
        sa.Column("blank_size", sa.String(100), nullable=False),
        sa.Column("order_received_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint("ordered_quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint(
            "process_type IN ('FULL', 'SX_ONLY', 'BAVIA_ONLY')",
            name="ck_orders_process_type",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_orders_po_no_not_deleted",
        "orders",
        ["po_no"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_orders_product_active", "orders", ["product_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_product_active", table_name="orders")
    op.drop_index("uq_orders_po_no_not_deleted", table_name="orders")
    op.drop_table("orders")
