"""Assign one operator to each machine pair and defer blank quantity to warehouse.

Revision ID: 20261112_19
Revises: 20261112_18
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_19"
down_revision: str | None = "20261112_18"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column("blank_requests", "blank_quantity", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "blank_request_pairs",
        sa.Column("employee_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_blank_request_pairs_employee_id_employees",
        "blank_request_pairs",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_unquantified_requests = connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM blank_requests WHERE blank_quantity IS NULL)")
    )
    if has_unquantified_requests:
        raise RuntimeError(
            "Cannot downgrade: new blank requests have no requester quantity to restore."
        )
    op.drop_constraint(
        "fk_blank_request_pairs_employee_id_employees",
        "blank_request_pairs",
        type_="foreignkey",
    )
    op.drop_column("blank_request_pairs", "employee_id")
    op.alter_column("blank_requests", "blank_quantity", existing_type=sa.Integer(), nullable=False)
