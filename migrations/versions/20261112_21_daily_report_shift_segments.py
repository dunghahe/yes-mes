"""Track production per shift and machine segment."""

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_21"
down_revision: str | None = "20261112_20"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "daily_report_pairs",
        sa.Column("shift_id", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE daily_report_pairs AS pair "
        "SET shift_id = report.shift_id "
        "FROM daily_reports AS report WHERE report.id = pair.daily_report_id"
    )
    op.alter_column("daily_report_pairs", "shift_id", nullable=False)
    op.create_foreign_key(
        "fk_daily_report_pairs_shift_id_shifts",
        "daily_report_pairs",
        "shifts",
        ["shift_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("uq_daily_report_pairs_report_pair_active", table_name="daily_report_pairs")
    op.create_index(
        "uq_daily_report_pairs_report_shift_pair_active",
        "daily_report_pairs",
        ["daily_report_id", "shift_id", "machine_pair_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_daily_reports_date_shift_active", table_name="daily_reports")
    op.create_index("ix_daily_reports_date_active", "daily_reports", ["report_date", "deleted_at"])
    op.drop_constraint("ck_daily_reports_time_order", "daily_reports", type_="check")
    op.drop_column("daily_reports", "actual_start")
    op.drop_column("daily_reports", "actual_end")
    op.drop_column("daily_reports", "shift_id")


def downgrade() -> None:
    op.add_column(
        "daily_reports",
        sa.Column("shift_id", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE daily_reports AS report SET shift_id = ("
        "SELECT pair.shift_id FROM daily_report_pairs AS pair "
        "WHERE pair.daily_report_id = report.id ORDER BY pair.id LIMIT 1)"
    )
    op.alter_column("daily_reports", "shift_id", nullable=False)
    op.create_foreign_key(
        "fk_daily_reports_shift_id_shifts",
        "daily_reports",
        "shifts",
        ["shift_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_daily_reports_date_active", table_name="daily_reports")
    op.create_index(
        "ix_daily_reports_date_shift_active",
        "daily_reports",
        ["report_date", "shift_id", "deleted_at"],
    )
    op.add_column(
        "daily_reports",
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_reports",
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE daily_reports SET actual_start = created_at, "
        "actual_end = created_at + interval '1 hour'"
    )
    op.alter_column("daily_reports", "actual_start", nullable=False)
    op.alter_column("daily_reports", "actual_end", nullable=False)
    op.create_check_constraint(
        "ck_daily_reports_time_order", "daily_reports", "actual_end > actual_start"
    )
    op.drop_index("uq_daily_report_pairs_report_shift_pair_active", table_name="daily_report_pairs")
    op.create_index(
        "uq_daily_report_pairs_report_pair_active",
        "daily_report_pairs",
        ["daily_report_id", "machine_pair_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint(
        "fk_daily_report_pairs_shift_id_shifts", "daily_report_pairs", type_="foreignkey"
    )
    op.drop_column("daily_report_pairs", "shift_id")
