"""Make machine group optional for legacy blank requests.

Revision ID: 20261112_17
Revises: 20261105_16
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_17"
down_revision: str | None = "20261105_16"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "blank_requests",
        "machine_group_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_nulls = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM blank_requests WHERE machine_group_id IS NULL)")
    ).scalar_one()
    if has_nulls:
        raise RuntimeError(
            "Cannot restore NOT NULL: blank requests created without a machine group exist."
        )
    op.alter_column(
        "blank_requests",
        "machine_group_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
