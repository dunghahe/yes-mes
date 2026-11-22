"""Add production lot QC inspections and defect details.

Revision ID: 20261119_33
Revises: 20261119_32
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_33"
down_revision: str | None = "20261119_32"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "lot_qc_inspections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("production_lot_id", sa.BigInteger(), nullable=False),
        sa.Column("inspected_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("qc_employee_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_in", sa.Integer(), nullable=False),
        sa.Column("quantity_ok", sa.Integer(), nullable=False),
        sa.Column("ng_scrap", sa.Integer(), nullable=False),
        sa.Column("ng_repair", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("quantity_in > 0", name="ck_lot_qc_quantity_in_positive"),
        sa.CheckConstraint("quantity_ok >= 0", name="ck_lot_qc_ok_nonnegative"),
        sa.CheckConstraint("ng_scrap >= 0", name="ck_lot_qc_scrap_nonnegative"),
        sa.CheckConstraint("ng_repair >= 0", name="ck_lot_qc_repair_nonnegative"),
        sa.CheckConstraint(
            "quantity_ok + ng_scrap + ng_repair = quantity_in",
            name="ck_lot_qc_counts_match",
        ),
        sa.ForeignKeyConstraint(["production_lot_id"], ["production_lots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qc_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_lot_qc_inspection_lot_active",
        "lot_qc_inspections",
        ["production_lot_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lot_qc_inspection_date_active",
        "lot_qc_inspections",
        ["inspected_date", "deleted_at"],
    )
    op.create_table(
        "lot_qc_defect_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("lot_qc_inspection_id", sa.BigInteger(), nullable=False),
        sa.Column("defect_code_id", sa.BigInteger(), nullable=False),
        sa.Column("machine_id", sa.BigInteger(), nullable=False),
        sa.Column("disposition", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
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
            "disposition IN ('scrap', 'repair')", name="ck_lot_qc_defect_disposition"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_lot_qc_defect_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["lot_qc_inspection_id"], ["lot_qc_inspections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["defect_code_id"], ["defect_codes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_lot_qc_defect_identity_active",
        "lot_qc_defect_lines",
        ["lot_qc_inspection_id", "defect_code_id", "machine_id", "disposition"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lot_qc_defects_inspection_active",
        "lot_qc_defect_lines",
        ["lot_qc_inspection_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_lot_qc_defects_inspection_active", table_name="lot_qc_defect_lines")
    op.drop_index("uq_lot_qc_defect_identity_active", table_name="lot_qc_defect_lines")
    op.drop_table("lot_qc_defect_lines")
    op.drop_index("ix_lot_qc_inspection_date_active", table_name="lot_qc_inspections")
    op.drop_index("uq_lot_qc_inspection_lot_active", table_name="lot_qc_inspections")
    op.drop_table("lot_qc_inspections")
