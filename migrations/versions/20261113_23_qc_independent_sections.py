"""Allow production QC sections to be saved independently.

Revision ID: 20261113_23
Revises: 20261113_22
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_23"
down_revision: str | None = "20261113_22"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "qc_inspections",
        sa.Column("pair_section_saved", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "qc_inspections",
        sa.Column("steps_section_saved", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        "UPDATE qc_inspections AS inspection SET pair_section_saved = EXISTS ("
        "SELECT 1 FROM qc_pair_results AS result WHERE result.qc_inspection_id = inspection.id "
        "AND result.deleted_at IS NULL)"
    )
    op.execute(
        "UPDATE qc_inspections AS inspection SET steps_section_saved = ("
        "SELECT count(*) FROM qc_check_steps AS step WHERE step.qc_inspection_id = inspection.id "
        "AND step.deleted_at IS NULL) = 4"
    )


def downgrade() -> None:
    op.drop_column("qc_inspections", "steps_section_saved")
    op.drop_column("qc_inspections", "pair_section_saved")
