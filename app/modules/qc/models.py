from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QcInspection(Base):
    __tablename__ = "qc_inspections"
    __table_args__ = (
        Index(
            "uq_qc_inspections_report_active",
            "daily_report_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_qc_inspections_inspected_date_active", "inspected_date", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="RESTRICT"), nullable=False
    )
    inspected_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    pair_section_saved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    steps_section_saved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QcPairResult(Base):
    __tablename__ = "qc_pair_results"
    __table_args__ = (
        CheckConstraint("quantity_in >= 0", name="ck_qc_pair_results_in_nonnegative"),
        CheckConstraint("ng_scrap >= 0", name="ck_qc_pair_results_scrap_nonnegative"),
        CheckConstraint("ng_repair >= 0", name="ck_qc_pair_results_repair_nonnegative"),
        CheckConstraint(
            "ng_scrap + ng_repair <= quantity_in", name="ck_qc_pair_results_counts_within_in"
        ),
        Index(
            "uq_qc_pair_results_inspection_pair_active",
            "qc_inspection_id",
            "daily_report_pair_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    qc_inspection_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspections.id", ondelete="RESTRICT"), nullable=False
    )
    daily_report_pair_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_in: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_scrap: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_repair: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QcCheckStep(Base):
    __tablename__ = "qc_check_steps"
    __table_args__ = (
        CheckConstraint("step_number BETWEEN 1 AND 4", name="ck_qc_check_steps_number"),
        CheckConstraint("ng_scrap >= 0", name="ck_qc_check_steps_scrap_nonnegative"),
        CheckConstraint("ng_repair >= 0", name="ck_qc_check_steps_repair_nonnegative"),
        Index(
            "uq_qc_check_steps_inspection_number_active",
            "qc_inspection_id",
            "step_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    qc_inspection_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspections.id", ondelete="RESTRICT"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_scrap: Mapped[int] = mapped_column(Integer, nullable=False)
    ng_repair: Mapped[int] = mapped_column(Integer, nullable=False)
    qc_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BaviaQcInspection(Base):
    __tablename__ = "bavia_qc_inspections"
    __table_args__ = (
        CheckConstraint("quantity_in > 0", name="ck_bavia_qc_in_positive"),
        CheckConstraint("ng_scrap >= 0", name="ck_bavia_qc_scrap_nonnegative"),
        CheckConstraint("ng_repair >= 0", name="ck_bavia_qc_repair_nonnegative"),
        CheckConstraint("ng_scrap + ng_repair <= quantity_in", name="ck_bavia_qc_counts_within_in"),
        Index(
            "uq_bavia_qc_report_active",
            "bavia_report_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bavia_report_id: Mapped[int] = mapped_column(
        ForeignKey("bavia_reports.id", ondelete="RESTRICT"), nullable=False
    )
    inspected_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    qc_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    quantity_in: Mapped[int] = mapped_column(Integer, nullable=False)
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


class LotQcInspection(Base):
    __tablename__ = "lot_qc_inspections"
    __table_args__ = (
        CheckConstraint("quantity_in > 0", name="ck_lot_qc_quantity_in_positive"),
        CheckConstraint("quantity_ok >= 0", name="ck_lot_qc_ok_nonnegative"),
        CheckConstraint("ng_scrap >= 0", name="ck_lot_qc_scrap_nonnegative"),
        CheckConstraint("ng_repair >= 0", name="ck_lot_qc_repair_nonnegative"),
        CheckConstraint(
            "quantity_ok + ng_scrap + ng_repair = quantity_in",
            name="ck_lot_qc_counts_match",
        ),
        Index(
            "uq_lot_qc_inspection_lot_active",
            "production_lot_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_lot_qc_inspection_date_active", "inspected_date", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    production_lot_id: Mapped[int] = mapped_column(
        ForeignKey("production_lots.id", ondelete="RESTRICT"), nullable=False
    )
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


class LotQcDefectLine(Base):
    __tablename__ = "lot_qc_defect_lines"
    __table_args__ = (
        CheckConstraint("disposition IN ('scrap', 'repair')", name="ck_lot_qc_defect_disposition"),
        CheckConstraint("quantity > 0", name="ck_lot_qc_defect_quantity_positive"),
        Index(
            "uq_lot_qc_defect_identity_active",
            "lot_qc_inspection_id",
            "defect_code_id",
            "machine_id",
            "disposition",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_lot_qc_defects_inspection_active", "lot_qc_inspection_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lot_qc_inspection_id: Mapped[int] = mapped_column(
        ForeignKey("lot_qc_inspections.id", ondelete="RESTRICT"), nullable=False
    )
    defect_code_id: Mapped[int] = mapped_column(
        ForeignKey("defect_codes.id", ondelete="RESTRICT"), nullable=False
    )
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="RESTRICT"))
    disposition: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
