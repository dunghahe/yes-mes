"""Add lot sizing and pre-generated production lot identities.

Revision ID: 20261119_32
Revises: 20261114_31
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_32"
down_revision: str | None = "20261114_31"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("lot_size", sa.Integer(), nullable=True))
    op.execute("UPDATE orders SET lot_size = ordered_quantity")
    op.alter_column("orders", "lot_size", nullable=False)
    op.create_check_constraint("ck_orders_lot_size_positive", "orders", "lot_size > 0")

    op.create_table(
        "production_lots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_number", sa.Integer(), nullable=False),
        sa.Column("lot_code", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("lot_number > 0", name="ck_production_lots_number_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_production_lots_quantity_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_production_lots_code_active",
        "production_lots",
        ["lot_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_production_lots_order_number_active",
        "production_lots",
        ["order_id", "lot_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_production_lots_order_active", "production_lots", ["order_id", "deleted_at"]
    )
    op.execute(
        """
        INSERT INTO production_lots (
            order_id, lot_number, lot_code, quantity, created_by, updated_by
        )
        SELECT
            id,
            1,
            'L' || lpad(id::text, 6, '0') || '-001',
            ordered_quantity,
            created_by,
            updated_by
        FROM orders
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_production_lots_order_active", table_name="production_lots")
    op.drop_index("uq_production_lots_order_number_active", table_name="production_lots")
    op.drop_index("uq_production_lots_code_active", table_name="production_lots")
    op.drop_table("production_lots")
    op.drop_constraint("ck_orders_lot_size_positive", "orders", type_="check")
    op.drop_column("orders", "lot_size")
