"""Shorten repair codes while accepting previous codes as aliases.

Revision ID: 20261114_29
Revises: 20261113_28
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_29"
down_revision: str | None = "20261113_28"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "repair_jobs", sa.Column("legacy_repair_code", sa.String(length=40), nullable=True)
    )
    op.execute(
        """
        UPDATE repair_jobs
        SET legacy_repair_code = repair_code,
            repair_code = 'SR-' || id::text
        WHERE repair_code <> 'SR-' || id::text
        """
    )
    op.create_index(
        "uq_repair_jobs_legacy_repair_code_active",
        "repair_jobs",
        ["legacy_repair_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND legacy_repair_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE repair_jobs
        SET repair_code = legacy_repair_code
        WHERE legacy_repair_code IS NOT NULL
        """
    )
    op.drop_index("uq_repair_jobs_legacy_repair_code_active", table_name="repair_jobs")
    op.drop_column("repair_jobs", "legacy_repair_code")
