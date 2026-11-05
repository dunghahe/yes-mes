"""Create and seed downtime reason master data.

Revision ID: 20261105_10
Revises: 20261105_09
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_10"
down_revision: str | None = "20261105_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_REASONS = (
    ("MACHINE_BREAKDOWN", "Hỏng máy"),
    ("CHANGEOVER", "Đổi mã"),
    ("WAITING_MATERIAL", "Chờ phôi"),
    ("WAITING_TECHNICIAN", "Chờ kỹ thuật"),
    ("WAITING_OPERATOR", "Chờ người vận hành"),
)
SEED_REASON = "Tạo lý do dừng máy mặc định trong migration"


def upgrade() -> None:
    op.create_table(
        "downtime_reasons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_downtime_reasons_code_not_deleted",
        "downtime_reasons",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_downtime_reasons_active_name", "downtime_reasons", ["is_active", "name"])

    connection = op.get_bind()
    for code, name in DEFAULT_REASONS:
        reason_id = connection.execute(
            sa.text("INSERT INTO downtime_reasons (code, name) VALUES (:code, :name) RETURNING id"),
            {"code": code, "name": name},
        ).scalar_one()
        connection.execute(
            sa.text(
                "INSERT INTO audit_log "
                "(table_name, record_id, action, new_values, reason, actor_id) "
                "VALUES ('downtime_reasons', :record_id, 'create', CAST(:new_values AS jsonb), "
                ":reason, NULL)"
            ),
            {
                "record_id": reason_id,
                "new_values": json.dumps({"code": code, "name": name, "is_active": True}),
                "reason": SEED_REASON,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM audit_log WHERE table_name = 'downtime_reasons' AND reason = :reason"),
        {"reason": SEED_REASON},
    )
    op.drop_index("ix_downtime_reasons_active_name", table_name="downtime_reasons")
    op.drop_index("uq_downtime_reasons_code_not_deleted", table_name="downtime_reasons")
    op.drop_table("downtime_reasons")
