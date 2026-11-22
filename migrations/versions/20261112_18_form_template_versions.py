"""Store versioned Excel print templates.

Revision ID: 20261112_18
Revises: 20261112_17
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_18"
down_revision: str | None = "20261112_17"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "form_template_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_form_template_version_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_form_template_versions_version_not_deleted",
        "form_template_versions",
        ["version"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_form_template_versions_active",
        "form_template_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_form_template_versions_active", table_name="form_template_versions")
    op.drop_index(
        "uq_form_template_versions_version_not_deleted",
        table_name="form_template_versions",
    )
    op.drop_table("form_template_versions")
