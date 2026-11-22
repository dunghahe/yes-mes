"""Add traceable repair slip codes and recheck references.

Revision ID: 20261113_28
Revises: 20261113_27
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_28"
down_revision: str | None = "20261113_27"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("repair_jobs", sa.Column("repair_code", sa.String(length=40), nullable=True))
    op.execute(
        """
        UPDATE repair_jobs
        SET repair_code = 'SR-' || to_char(repair_date, 'YYYYMMDD') || '-' || lpad(id::text, 6, '0')
        WHERE repair_code IS NULL
        """
    )
    op.alter_column("repair_jobs", "repair_code", nullable=False)
    op.create_index(
        "uq_repair_jobs_repair_code_active",
        "repair_jobs",
        ["repair_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.add_column(
        "repair_qc_rechecks",
        sa.Column("repair_job_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_repair_qc_rechecks_repair_job_id_repair_jobs",
        "repair_qc_rechecks",
        "repair_jobs",
        ["repair_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_repair_qc_rechecks_job_active",
        "repair_qc_rechecks",
        ["repair_job_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_repair_qc_rechecks_job_active", table_name="repair_qc_rechecks")
    op.drop_constraint(
        "fk_repair_qc_rechecks_repair_job_id_repair_jobs",
        "repair_qc_rechecks",
        type_="foreignkey",
    )
    op.drop_column("repair_qc_rechecks", "repair_job_id")
    op.drop_index("uq_repair_jobs_repair_code_active", table_name="repair_jobs")
    op.drop_column("repair_jobs", "repair_code")
