"""Remove process routing from product master data.

Revision ID: 20261114_31
Revises: 20261114_30
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_31"
down_revision: str | None = "20261114_30"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_products_default_process_type", "products", type_="check")
    op.drop_column("products", "default_process_type")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "default_process_type", sa.String(length=20), nullable=False, server_default="FULL"
        ),
    )
    op.alter_column("products", "default_process_type", server_default=None)
    op.create_check_constraint(
        "ck_products_default_process_type",
        "products",
        "default_process_type IN ('FULL', 'SX_ONLY', 'BAVIA_ONLY')",
    )
