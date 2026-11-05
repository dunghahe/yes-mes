"""Add restricted pre-authentication states for first login.

Revision ID: 20261105_04
Revises: 20261105_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_04"
down_revision: str | None = "20261105_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "login_sessions",
        sa.Column("auth_state", sa.String(30), server_default="active", nullable=False),
    )
    op.create_check_constraint(
        "ck_login_sessions_auth_state",
        "login_sessions",
        "auth_state IN ('password_change', 'totp_setup', 'active')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_login_sessions_auth_state", "login_sessions", type_="check")
    op.drop_column("login_sessions", "auth_state")
