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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BlankRequest(Base):
    __tablename__ = "blank_requests"
    __table_args__ = (
        CheckConstraint(
            "blank_quantity IS NULL OR blank_quantity > 0",
            name="ck_blank_requests_quantity_positive",
        ),
        CheckConstraint(
            "status IN ('submitted', 'cancelled', 'delivered')",
            name="ck_blank_requests_status",
        ),
        CheckConstraint(
            "delivered_quantity IS NULL OR delivered_quantity > 0",
            name="ck_blank_requests_delivered_quantity_positive",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL AND delivered_by IS NOT NULL) "
            "OR (status <> 'delivered' AND delivered_quantity IS NULL "
            "AND delivered_at IS NULL AND delivered_by IS NULL)",
            name="ck_blank_requests_delivery_matches_status",
        ),
        Index(
            "uq_blank_requests_req_no_not_deleted",
            "req_no",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_blank_requests_schedule_active", "schedule_id", "deleted_at"),
        Index("ix_blank_requests_status_created", "status", "created_at", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    req_no: Mapped[str] = mapped_column(String(30), nullable=False)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedules.id", ondelete="RESTRICT"), nullable=False
    )
    blank_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    machine_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("machine_groups.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="submitted")
    delivered_quantity: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
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


class BlankRequestPair(Base):
    __tablename__ = "blank_request_pairs"
    __table_args__ = (
        Index(
            "uq_blank_request_pairs_request_pair_not_deleted",
            "blank_request_id",
            "machine_pair_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_blank_request_pairs_pair_active", "machine_pair_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blank_request_id: Mapped[int] = mapped_column(
        ForeignKey("blank_requests.id", ondelete="RESTRICT"), nullable=False
    )
    machine_pair_id: Mapped[int] = mapped_column(
        ForeignKey("machine_pairs.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
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


class BlankRequestOperator(Base):
    __tablename__ = "blank_request_operators"
    __table_args__ = (
        Index(
            "uq_blank_request_operators_request_employee_not_deleted",
            "blank_request_id",
            "employee_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_blank_request_operators_employee_active", "employee_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blank_request_id: Mapped[int] = mapped_column(
        ForeignKey("blank_requests.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
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


class BlankRequestCounter(Base):
    __tablename__ = "blank_request_counters"
    __table_args__ = (Index("uq_blank_request_counters_date", "counter_date", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    counter_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlankRequestPrint(Base):
    __tablename__ = "blank_request_prints"
    __table_args__ = (
        CheckConstraint(
            "form_type IN ('production', 'qc')", name="ck_blank_request_prints_form_type"
        ),
        Index(
            "ix_blank_request_prints_request_type_time",
            "blank_request_id",
            "form_type",
            "printed_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blank_request_id: Mapped[int] = mapped_column(
        ForeignKey("blank_requests.id", ondelete="RESTRICT"), nullable=False
    )
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)
    printed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    printed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
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
