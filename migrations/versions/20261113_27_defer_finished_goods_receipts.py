"""Defer finished goods warehouse receipts from the current scope.

Revision ID: 20261113_27
Revises: 20261113_26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_27"
down_revision: str | None = "20261113_26"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM finished_goods_receipts LIMIT 1) THEN
                RAISE EXCEPTION
                    'Cannot defer finished goods receipts while the table contains data.';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_finished_goods_receipts_order_date", table_name="finished_goods_receipts")
    op.drop_table("finished_goods_receipts")


def downgrade() -> None:
    op.create_table(
        "finished_goods_receipts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity_received > 0", name="ck_finished_goods_receipts_qty_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_finished_goods_receipts_order_date",
        "finished_goods_receipts",
        ["order_id", "receipt_date", "deleted_at"],
    )
