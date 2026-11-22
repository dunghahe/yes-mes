"""Allow warehouse delivery confirmation without collecting the actual quantity.

Revision ID: 20261122_35
Revises: 20261119_34
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261122_35"
down_revision: str | None = "20261119_34"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_blank_requests_delivery_matches_status", "blank_requests", type_="check")
    op.create_check_constraint(
        "ck_blank_requests_delivery_matches_status",
        "blank_requests",
        "(status = 'delivered' AND delivered_at IS NOT NULL AND delivered_by IS NOT NULL) "
        "OR (status <> 'delivered' AND delivered_quantity IS NULL "
        "AND delivered_at IS NULL AND delivered_by IS NULL)",
    )


def downgrade() -> None:
    unknown_quantity = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM blank_requests "
            "WHERE status = 'delivered' AND delivered_quantity IS NULL)"
        )
    )
    if unknown_quantity:
        raise RuntimeError(
            "Không thể lùi migration khi có phiếu đã giao chưa có số thực giao. "
            "Cần bổ sung số thực tế trước; không tự điền số lượng giả."
        )
    op.drop_constraint("ck_blank_requests_delivery_matches_status", "blank_requests", type_="check")
    op.create_check_constraint(
        "ck_blank_requests_delivery_matches_status",
        "blank_requests",
        "(status = 'delivered' AND delivered_quantity IS NOT NULL "
        "AND delivered_at IS NOT NULL AND delivered_by IS NOT NULL) "
        "OR (status <> 'delivered' AND delivered_quantity IS NULL "
        "AND delivered_at IS NULL AND delivered_by IS NULL)",
    )
