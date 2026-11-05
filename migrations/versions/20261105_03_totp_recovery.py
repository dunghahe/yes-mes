"""Add one-time TOTP recovery codes and replay prevention.

Revision ID: 20261105_03
Revises: 20261105_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261105_03"
down_revision: str | None = "20261105_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "totp_recovery_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("totp_last_used_counter", sa.BigInteger(), nullable=True),
    )
    op.drop_constraint("ck_auth_events_type", "auth_events", type_="check")
    op.create_check_constraint(
        "ck_auth_events_type",
        "auth_events",
        "event_type IN ('login_success', 'login_failure', 'logout', 'lockout', "
        "'totp_enrolled', 'totp_recovery_used')",
    )


def downgrade() -> None:
    op.drop_column("users", "totp_last_used_counter")
    op.drop_column("users", "totp_recovery_hashes")
