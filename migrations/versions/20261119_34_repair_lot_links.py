"""Keep repair dispatch and recheck linked to the original production lot.

Revision ID: 20261119_34
Revises: 20261119_33
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_34"
down_revision: str | None = "20261119_33"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("repair_jobs", sa.Column("production_lot_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "repair_qc_rechecks", sa.Column("production_lot_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_repair_jobs_production_lot_id_production_lots",
        "repair_jobs",
        "production_lots",
        ["production_lot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_repair_qc_rechecks_production_lot_id_production_lots",
        "repair_qc_rechecks",
        "production_lots",
        ["production_lot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_repair_jobs_lot_stage_active",
        "repair_jobs",
        ["production_lot_id", "stage", "deleted_at"],
    )
    op.create_index(
        "ix_repair_rechecks_lot_stage_active",
        "repair_qc_rechecks",
        ["production_lot_id", "stage", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_repair_rechecks_lot_stage_active", table_name="repair_qc_rechecks")
    op.drop_index("ix_repair_jobs_lot_stage_active", table_name="repair_jobs")
    op.drop_constraint(
        "fk_repair_qc_rechecks_production_lot_id_production_lots",
        "repair_qc_rechecks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_repair_jobs_production_lot_id_production_lots",
        "repair_jobs",
        type_="foreignkey",
    )
    op.drop_column("repair_qc_rechecks", "production_lot_id")
    op.drop_column("repair_jobs", "production_lot_id")
