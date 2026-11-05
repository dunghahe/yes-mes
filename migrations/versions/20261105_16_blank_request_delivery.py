"""Store blank request delivery confirmation.

Revision ID: 20261105_16
Revises: 20261105_15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_16"
down_revision: str | None = "20261105_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("blank_requests", sa.Column("delivered_quantity", sa.Integer(), nullable=True))
    op.add_column(
        "blank_requests", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("blank_requests", sa.Column("delivered_by", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_blank_requests_delivered_by_users",
        "blank_requests",
        "users",
        ["delivered_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_blank_requests_delivered_quantity_positive",
        "blank_requests",
        "delivered_quantity IS NULL OR delivered_quantity > 0",
    )
    op.create_check_constraint(
        "ck_blank_requests_delivery_matches_status",
        "blank_requests",
        "(status = 'delivered' AND delivered_quantity IS NOT NULL AND delivered_at IS NOT NULL "
        "AND delivered_by IS NOT NULL) OR (status <> 'delivered' AND delivered_quantity IS NULL "
        "AND delivered_at IS NULL AND delivered_by IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_blank_requests_delivery_matches_status", "blank_requests", type_="check")
    op.drop_constraint(
        "ck_blank_requests_delivered_quantity_positive", "blank_requests", type_="check"
    )
    op.drop_constraint("fk_blank_requests_delivered_by_users", "blank_requests", type_="foreignkey")
    op.drop_column("blank_requests", "delivered_by")
    op.drop_column("blank_requests", "delivered_at")
    op.drop_column("blank_requests", "delivered_quantity")
