"""Store production QC and its four paper inspection checkpoints.

Revision ID: 20261113_22
Revises: 20261112_21
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_22"
down_revision: str | None = "20261112_21"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "qc_inspections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("daily_report_id", sa.BigInteger(), nullable=False),
        sa.Column("inspected_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(["daily_report_id"], ["daily_reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_qc_inspections_report_active",
        "qc_inspections",
        ["daily_report_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_qc_inspections_inspected_date_active",
        "qc_inspections",
        ["inspected_date", "deleted_at"],
    )
    op.create_table(
        "qc_pair_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("qc_inspection_id", sa.BigInteger(), nullable=False),
        sa.Column("daily_report_pair_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_in", sa.Integer(), nullable=False),
        sa.Column("ng_scrap", sa.Integer(), nullable=False),
        sa.Column("ng_repair", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity_in >= 0", name="ck_qc_pair_results_in_nonnegative"),
        sa.CheckConstraint("ng_scrap >= 0", name="ck_qc_pair_results_scrap_nonnegative"),
        sa.CheckConstraint("ng_repair >= 0", name="ck_qc_pair_results_repair_nonnegative"),
        sa.CheckConstraint(
            "ng_scrap + ng_repair <= quantity_in", name="ck_qc_pair_results_counts_within_in"
        ),
        sa.ForeignKeyConstraint(["qc_inspection_id"], ["qc_inspections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["daily_report_pair_id"], ["daily_report_pairs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_qc_pair_results_inspection_pair_active",
        "qc_pair_results",
        ["qc_inspection_id", "daily_report_pair_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "qc_check_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("qc_inspection_id", sa.BigInteger(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("ng_scrap", sa.Integer(), nullable=False),
        sa.Column("ng_repair", sa.Integer(), nullable=False),
        sa.Column("qc_employee_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("step_number BETWEEN 1 AND 4", name="ck_qc_check_steps_number"),
        sa.CheckConstraint("ng_scrap >= 0", name="ck_qc_check_steps_scrap_nonnegative"),
        sa.CheckConstraint("ng_repair >= 0", name="ck_qc_check_steps_repair_nonnegative"),
        sa.ForeignKeyConstraint(["qc_inspection_id"], ["qc_inspections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qc_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_qc_check_steps_inspection_number_active",
        "qc_check_steps",
        ["qc_inspection_id", "step_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("qc_check_steps")
    op.drop_index("uq_qc_pair_results_inspection_pair_active", table_name="qc_pair_results")
    op.drop_table("qc_pair_results")
    op.drop_index("ix_qc_inspections_inspected_date_active", table_name="qc_inspections")
    op.drop_index("uq_qc_inspections_report_active", table_name="qc_inspections")
    op.drop_table("qc_inspections")
