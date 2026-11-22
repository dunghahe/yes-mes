"""Create confirmed daily production reports.

Revision ID: 20261112_20
Revises: 20261112_19
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_20"
down_revision: str | None = "20261112_19"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("blank_request_id", sa.BigInteger(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="confirmed", nullable=False),
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
        sa.CheckConstraint("actual_end > actual_start", name="ck_daily_reports_time_order"),
        sa.CheckConstraint("status = 'confirmed'", name="ck_daily_reports_confirmed_only"),
        sa.ForeignKeyConstraint(["blank_request_id"], ["blank_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_daily_reports_request_active",
        "daily_reports",
        ["blank_request_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_daily_reports_date_shift_active",
        "daily_reports",
        ["report_date", "shift_id", "deleted_at"],
    )

    op.create_table(
        "daily_report_pairs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("daily_report_id", sa.BigInteger(), nullable=False),
        sa.Column("machine_pair_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("downtime_recorded", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("planned_minutes > 0", name="ck_daily_report_pairs_planned_positive"),
        sa.ForeignKeyConstraint(["daily_report_id"], ["daily_reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_pair_id"], ["machine_pairs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_daily_report_pairs_report_pair_active",
        "daily_report_pairs",
        ["daily_report_id", "machine_pair_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "daily_report_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("daily_report_pair_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_produced", sa.Integer(), nullable=False),
        sa.Column("cycle_time_snapshot_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "quantity_produced >= 0", name="ck_daily_report_lines_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "cycle_time_snapshot_seconds > 0", name="ck_daily_report_lines_cycle_positive"
        ),
        sa.ForeignKeyConstraint(
            ["daily_report_pair_id"], ["daily_report_pairs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_daily_report_lines_order_active", "daily_report_lines", ["order_id", "deleted_at"]
    )

    op.create_table(
        "downtime_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("daily_report_pair_id", sa.BigInteger(), nullable=False),
        sa.Column("downtime_reason_id", sa.BigInteger(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("minutes > 0", name="ck_downtime_entries_minutes_positive"),
        sa.ForeignKeyConstraint(
            ["daily_report_pair_id"], ["daily_report_pairs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["downtime_reason_id"], ["downtime_reasons.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("downtime_entries")
    op.drop_index("ix_daily_report_lines_order_active", table_name="daily_report_lines")
    op.drop_table("daily_report_lines")
    op.drop_index("uq_daily_report_pairs_report_pair_active", table_name="daily_report_pairs")
    op.drop_table("daily_report_pairs")
    op.drop_index("ix_daily_reports_date_shift_active", table_name="daily_reports")
    op.drop_index("uq_daily_reports_request_active", table_name="daily_reports")
    op.drop_table("daily_reports")
