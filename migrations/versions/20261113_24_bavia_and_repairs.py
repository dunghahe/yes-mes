"""Add Bavia production/QC and repair-return tracking.

Revision ID: 20261113_24
Revises: 20261113_23
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_24"
down_revision: str | None = "20261113_23"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "bavia_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_produced", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("quantity_produced >= 0", name="ck_bavia_reports_qty_nonnegative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_bavia_reports_order_date_shift_employee_active",
        "bavia_reports",
        ["order_id", "report_date", "shift_id", "employee_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_bavia_reports_order_date_active",
        "bavia_reports",
        ["order_id", "report_date", "deleted_at"],
    )
    op.create_table(
        "bavia_qc_inspections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bavia_report_id", sa.BigInteger(), nullable=False),
        sa.Column("inspected_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("qc_employee_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_in", sa.Integer(), nullable=False),
        sa.Column("ng_scrap", sa.Integer(), nullable=False),
        sa.Column("ng_repair", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("quantity_in > 0", name="ck_bavia_qc_in_positive"),
        sa.CheckConstraint("ng_scrap >= 0", name="ck_bavia_qc_scrap_nonnegative"),
        sa.CheckConstraint("ng_repair >= 0", name="ck_bavia_qc_repair_nonnegative"),
        sa.CheckConstraint(
            "ng_scrap + ng_repair <= quantity_in", name="ck_bavia_qc_counts_within_in"
        ),
        sa.ForeignKeyConstraint(["bavia_report_id"], ["bavia_reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qc_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_bavia_qc_report_active",
        "bavia_qc_inspections",
        ["bavia_report_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "repair_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("repair_employee_id", sa.BigInteger(), nullable=False),
        sa.Column("repair_date", sa.Date(), nullable=False),
        sa.Column("quantity_repaired", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.CheckConstraint("stage IN ('QC', 'QC_BAVIA')", name="ck_repair_jobs_stage"),
        sa.CheckConstraint("quantity_repaired > 0", name="ck_repair_jobs_qty_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repair_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repair_jobs_order_stage_date",
        "repair_jobs",
        ["order_id", "stage", "repair_date", "deleted_at"],
    )

    op.create_table(
        "repair_qc_rechecks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("inspected_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("qc_employee_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_in", sa.Integer(), nullable=False),
        sa.Column("quantity_ok", sa.Integer(), nullable=False),
        sa.Column("ng_scrap", sa.Integer(), nullable=False),
        sa.Column("ng_repair", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("stage IN ('QC', 'QC_BAVIA')", name="ck_repair_qc_rechecks_stage"),
        sa.CheckConstraint("quantity_in > 0", name="ck_repair_qc_rechecks_in_positive"),
        sa.CheckConstraint("quantity_ok >= 0", name="ck_repair_qc_rechecks_ok_nonnegative"),
        sa.CheckConstraint("ng_scrap >= 0", name="ck_repair_qc_rechecks_scrap_nonnegative"),
        sa.CheckConstraint("ng_repair >= 0", name="ck_repair_qc_rechecks_repair_nonnegative"),
        sa.CheckConstraint(
            "quantity_ok + ng_scrap + ng_repair = quantity_in",
            name="ck_repair_qc_rechecks_counts_match",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qc_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repair_qc_rechecks_order_stage_date",
        "repair_qc_rechecks",
        ["order_id", "stage", "inspected_date", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_table("repair_qc_rechecks")
    op.drop_index("ix_repair_jobs_order_stage_date", table_name="repair_jobs")
    op.drop_table("repair_jobs")
    op.drop_index("uq_bavia_qc_report_active", table_name="bavia_qc_inspections")
    op.drop_table("bavia_qc_inspections")
    op.drop_index("ix_bavia_reports_order_date_active", table_name="bavia_reports")
    op.drop_index("uq_bavia_reports_order_date_shift_employee_active", table_name="bavia_reports")
    op.drop_table("bavia_reports")
