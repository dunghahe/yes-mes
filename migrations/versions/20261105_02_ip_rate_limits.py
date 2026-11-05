"""Add database-backed failed-login rate limits by IP.

Revision ID: 20261105_02
Revises: 20261105_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_02"
down_revision: str | None = "20261105_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_ip_limits",
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("failure_count >= 0", name="ck_auth_ip_limits_failure_count"),
        sa.PrimaryKeyConstraint("ip_address"),
    )
    op.execute("REVOKE UPDATE, DELETE ON TABLE auth_events FROM mes_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE auth_ip_limits TO mes_app")
    op.execute("REVOKE DELETE ON TABLE auth_ip_limits FROM mes_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON TABLE auth_ip_limits FROM mes_app")
    op.drop_table("auth_ip_limits")
    op.execute("GRANT UPDATE, DELETE ON TABLE auth_events TO mes_app")
