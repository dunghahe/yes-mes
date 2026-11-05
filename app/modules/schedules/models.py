from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProductionSchedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("planned_quantity > 0", name="ck_schedules_quantity_positive"),
        Index("ix_schedules_date_shift_active", "production_date", "shift_id", "deleted_at"),
        Index("ix_schedules_order_active", "order_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    production_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int] = mapped_column(
        ForeignKey("shifts.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    planned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
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
