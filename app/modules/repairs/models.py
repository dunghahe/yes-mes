from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RepairJob(Base):
    __tablename__ = "repair_jobs"
    __table_args__ = (
        CheckConstraint("stage IN ('QC', 'QC_BAVIA')", name="ck_repair_jobs_stage"),
        CheckConstraint("quantity_repaired > 0", name="ck_repair_jobs_qty_positive"),
        Index("ix_repair_jobs_order_stage_date", "order_id", "stage", "repair_date", "deleted_at"),
        Index(
            "uq_repair_jobs_repair_code_active",
            "repair_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_repair_jobs_legacy_repair_code_active",
            "legacy_repair_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND legacy_repair_code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repair_code: Mapped[str] = mapped_column(String(40), nullable=False)
    legacy_repair_code: Mapped[str | None] = mapped_column(String(40))
    production_lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_lots.id", ondelete="RESTRICT")
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    repair_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    repair_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_repaired: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepairQcRecheck(Base):
    __tablename__ = "repair_qc_rechecks"
    __table_args__ = (
        CheckConstraint("stage IN ('QC', 'QC_BAVIA')", name="ck_repair_qc_rechecks_stage"),
        CheckConstraint("quantity_in > 0", name="ck_repair_qc_rechecks_in_positive"),
        CheckConstraint("quantity_ok >= 0", name="ck_repair_qc_rechecks_ok_nonnegative"),
        CheckConstraint("ng_scrap >= 0", name="ck_repair_qc_rechecks_scrap_nonnegative"),
        CheckConstraint("ng_repair >= 0", name="ck_repair_qc_rechecks_repair_nonnegative"),
        CheckConstraint(
            "quantity_ok + ng_scrap + ng_repair = quantity_in",
            name="ck_repair_qc_rechecks_counts_match",
        ),
        Index(
            "ix_repair_qc_rechecks_order_stage_date",
            "order_id",
            "stage",
            "inspected_date",
            "deleted_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repair_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("repair_jobs.id", ondelete="RESTRICT")
    )
    production_lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_lots.id", ondelete="RESTRICT")
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    inspected_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    qc_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    quantity_in: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_ok: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_scrap: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_repair: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
