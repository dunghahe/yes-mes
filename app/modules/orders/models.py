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

PROCESS_TYPES = ("FULL", "SX_ONLY", "BAVIA_ONLY")


class ProductionOrder(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint(
            "process_type IN ('FULL', 'SX_ONLY', 'BAVIA_ONLY')",
            name="ck_orders_process_type",
        ),
        Index(
            "uq_orders_po_no_not_deleted",
            "po_no",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_orders_product_active", "product_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    po_no: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    process_type: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_material_code: Mapped[str] = mapped_column(String(100), nullable=False)
    drawing_number: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[str] = mapped_column(String(30), nullable=False)
    material: Mapped[str] = mapped_column(String(100), nullable=False)
    blank_size: Mapped[str] = mapped_column(String(100), nullable=False)
    order_received_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
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
