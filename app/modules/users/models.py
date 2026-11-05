from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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

PERMISSION_MODULES = (
    "master",
    "orders",
    "schedules",
    "blank_requests",
    "daily_reports",
    "qc",
    "repairs",
    "reports",
    "audit",
)


class UserPermission(Base):
    __tablename__ = "user_permissions"
    __table_args__ = (
        CheckConstraint(
            "module IN ('master', 'orders', 'schedules', 'blank_requests', 'daily_reports', "
            "'qc', 'repairs', 'reports', 'audit')",
            name="ck_user_permissions_module",
        ),
        CheckConstraint(
            "NOT (can_create OR can_edit OR can_delete) OR can_view",
            name="ck_user_permissions_write_requires_view",
        ),
        Index(
            "uq_user_permissions_user_module_active",
            "user_id",
            "module",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_user_permissions_user_active", "user_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    can_create: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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
