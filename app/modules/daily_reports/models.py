from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        CheckConstraint("status = 'confirmed'", name="ck_daily_reports_confirmed_only"),
        Index(
            "uq_daily_reports_request_active",
            "blank_request_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_daily_reports_date_active", "report_date", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blank_request_id: Mapped[int] = mapped_column(
        ForeignKey("blank_requests.id", ondelete="RESTRICT"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="confirmed")
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


class BaviaReport(Base):
    __tablename__ = "bavia_reports"
    __table_args__ = (
        CheckConstraint("quantity_produced >= 0", name="ck_bavia_reports_qty_nonnegative"),
        Index(
            "uq_bavia_reports_order_date_shift_employee_active",
            "order_id",
            "report_date",
            "shift_id",
            "employee_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_bavia_reports_order_date_active", "order_id", "report_date", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    quantity_produced: Mapped[int] = mapped_column(Integer, nullable=False)
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


class DailyReportPair(Base):
    __tablename__ = "daily_report_pairs"
    __table_args__ = (
        CheckConstraint("planned_minutes > 0", name="ck_daily_report_pairs_planned_positive"),
        Index(
            "uq_daily_report_pairs_report_shift_pair_active",
            "daily_report_id",
            "shift_id",
            "machine_pair_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="RESTRICT"), nullable=False
    )
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    machine_pair_id: Mapped[int] = mapped_column(
        ForeignKey("machine_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    downtime_recorded: Mapped[bool] = mapped_column(
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


class DailyReportLine(Base):
    __tablename__ = "daily_report_lines"
    __table_args__ = (
        CheckConstraint(
            "quantity_produced >= 0", name="ck_daily_report_lines_quantity_nonnegative"
        ),
        CheckConstraint(
            "cycle_time_snapshot_seconds > 0", name="ck_daily_report_lines_cycle_positive"
        ),
        Index("ix_daily_report_lines_order_active", "order_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    daily_report_pair_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    quantity_produced: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_time_snapshot_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DowntimeEntry(Base):
    __tablename__ = "downtime_entries"
    __table_args__ = (CheckConstraint("minutes > 0", name="ck_downtime_entries_minutes_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    daily_report_pair_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    downtime_reason_id: Mapped[int] = mapped_column(
        ForeignKey("downtime_reasons.id", ondelete="RESTRICT"), nullable=False
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
