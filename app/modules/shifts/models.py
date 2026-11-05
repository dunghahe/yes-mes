from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        CheckConstraint("start_time <> end_time", name="ck_shifts_distinct_start_end"),
        CheckConstraint(
            "(crosses_midnight AND end_time < start_time) OR "
            "(NOT crosses_midnight AND end_time > start_time)",
            name="ck_shifts_midnight_matches_times",
        ),
        CheckConstraint("planned_break_minutes >= 0", name="ck_shifts_break_nonnegative"),
        Index(
            "uq_shifts_name_not_deleted",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_shifts_active_start", "is_active", "start_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    planned_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
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
