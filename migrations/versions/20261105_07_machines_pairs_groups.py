"""Create machines, pairs, groups, and effective assignments.

Revision ID: 20261105_07
Revises: 20261105_06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_07"
down_revision: str | None = "20261105_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _standard_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("production_area", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_standard_columns(),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_machines_code_not_deleted",
        "machines",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_machines_active_area", "machines", ["is_active", "production_area"])

    op.create_table(
        "machine_groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_standard_columns(),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_machine_groups_code_not_deleted",
        "machine_groups",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "machine_pairs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("machine_1_id", sa.BigInteger(), nullable=False),
        sa.Column("machine_2_id", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_standard_columns(),
        sa.CheckConstraint("machine_1_id < machine_2_id", name="ck_machine_pairs_distinct_ordered"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_1_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_2_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_machine_pairs_members_not_deleted",
        "machine_pairs",
        ["machine_1_id", "machine_2_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "machine_group_assignments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("machine_pair_id", sa.BigInteger(), nullable=False),
        sa.Column("machine_group_id", sa.BigInteger(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *_standard_columns(),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_machine_group_dates"
        ),
        sa.ForeignKeyConstraint(["machine_pair_id"], ["machine_pairs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_group_id"], ["machine_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_machine_group_assignments_pair_current",
        "machine_group_assignments",
        ["machine_pair_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_machine_group_assignments_history",
        "machine_group_assignments",
        ["machine_pair_id", "valid_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_machine_group_assignments_history", table_name="machine_group_assignments")
    op.drop_index(
        "uq_machine_group_assignments_pair_current", table_name="machine_group_assignments"
    )
    op.drop_table("machine_group_assignments")
    op.drop_index("uq_machine_pairs_members_not_deleted", table_name="machine_pairs")
    op.drop_table("machine_pairs")
    op.drop_index("uq_machine_groups_code_not_deleted", table_name="machine_groups")
    op.drop_table("machine_groups")
    op.drop_index("ix_machines_active_area", table_name="machines")
    op.drop_index("uq_machines_code_not_deleted", table_name="machines")
    op.drop_table("machines")
