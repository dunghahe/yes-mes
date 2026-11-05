"""Create blank requests and selected resources.

Revision ID: 20261105_14
Revises: 20261105_13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_14"
down_revision: str | None = "20261105_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _audit_foreign_keys() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
    ]


def upgrade() -> None:
    op.create_table(
        "blank_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("req_no", sa.String(30), nullable=False),
        sa.Column("schedule_id", sa.BigInteger(), nullable=False),
        sa.Column("blank_quantity", sa.Integer(), nullable=False),
        sa.Column("machine_group_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_common_columns(),
        sa.CheckConstraint("blank_quantity > 0", name="ck_blank_requests_quantity_positive"),
        sa.CheckConstraint(
            "status IN ('submitted', 'cancelled', 'delivered')", name="ck_blank_requests_status"
        ),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_group_id"], ["machine_groups.id"], ondelete="RESTRICT"),
        *_audit_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_blank_requests_req_no_not_deleted",
        "blank_requests",
        ["req_no"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_blank_requests_schedule_active", "blank_requests", ["schedule_id", "deleted_at"]
    )
    op.create_index(
        "ix_blank_requests_status_created", "blank_requests", ["status", "created_at", "deleted_at"]
    )

    for table_name, child_column, child_table, index_name, child_index in (
        (
            "blank_request_pairs",
            "machine_pair_id",
            "machine_pairs",
            "uq_blank_request_pairs_request_pair_not_deleted",
            "ix_blank_request_pairs_pair_active",
        ),
        (
            "blank_request_operators",
            "employee_id",
            "employees",
            "uq_blank_request_operators_request_employee_not_deleted",
            "ix_blank_request_operators_employee_active",
        ),
    ):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("blank_request_id", sa.BigInteger(), nullable=False),
            sa.Column(child_column, sa.BigInteger(), nullable=False),
            *_common_columns(),
            sa.ForeignKeyConstraint(
                ["blank_request_id"], ["blank_requests.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint([child_column], [f"{child_table}.id"], ondelete="RESTRICT"),
            *_audit_foreign_keys(),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            index_name,
            table_name,
            ["blank_request_id", child_column],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )
        op.create_index(child_index, table_name, [child_column, "deleted_at"])

    op.create_table(
        "blank_request_counters",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        *_common_columns(),
        *_audit_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_blank_request_counters_date", "blank_request_counters", ["counter_date"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_blank_request_counters_date", table_name="blank_request_counters")
    op.drop_table("blank_request_counters")
    op.drop_index(
        "ix_blank_request_operators_employee_active", table_name="blank_request_operators"
    )
    op.drop_index(
        "uq_blank_request_operators_request_employee_not_deleted",
        table_name="blank_request_operators",
    )
    op.drop_table("blank_request_operators")
    op.drop_index("ix_blank_request_pairs_pair_active", table_name="blank_request_pairs")
    op.drop_index(
        "uq_blank_request_pairs_request_pair_not_deleted", table_name="blank_request_pairs"
    )
    op.drop_table("blank_request_pairs")
    op.drop_index("ix_blank_requests_status_created", table_name="blank_requests")
    op.drop_index("ix_blank_requests_schedule_active", table_name="blank_requests")
    op.drop_index("uq_blank_requests_req_no_not_deleted", table_name="blank_requests")
    op.drop_table("blank_requests")
