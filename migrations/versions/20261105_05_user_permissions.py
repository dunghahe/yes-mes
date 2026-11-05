"""Add per-user additive module permissions.

Revision ID: 20261105_05
Revises: 20261105_04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_05"
down_revision: str | None = "20261105_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("module", sa.String(30), nullable=False),
        sa.Column("can_view", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("can_create", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("can_edit", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("can_delete", sa.Boolean(), server_default=sa.false(), nullable=False),
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
        sa.CheckConstraint(
            "module IN ('master', 'orders', 'schedules', 'blank_requests', 'daily_reports', "
            "'qc', 'repairs', 'reports', 'audit')",
            name="ck_user_permissions_module",
        ),
        sa.CheckConstraint(
            "NOT (can_create OR can_edit OR can_delete) OR can_view",
            name="ck_user_permissions_write_requires_view",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_user_permissions_user_module_active",
        "user_permissions",
        ["user_id", "module"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_user_permissions_user_active",
        "user_permissions",
        ["user_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_permissions_user_active", table_name="user_permissions")
    op.drop_index("uq_user_permissions_user_module_active", table_name="user_permissions")
    op.drop_table("user_permissions")
