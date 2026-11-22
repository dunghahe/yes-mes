from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.orders.models import ProductionLot
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.orders.service import (
    ConcurrentOrderChange,
    OrderManagementError,
    create_order,
    list_orders,
    update_order,
)
from app.modules.products.models import Product


def _admin(db: Session) -> User:
    actor = User(
        username=f"order-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-this-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(actor)
    db.flush()
    return actor


def _product(db: Session, *, active: bool = True) -> Product:
    product = Product(
        code=f"ORDER-{uuid4().hex}",
        name="Mã hàng thử nghiệm",
        cycle_time_seconds=3,
        is_active=active,
    )
    db.add(product)
    db.flush()
    return product


def _order_data(product_id: int, po_no: str | None = None) -> OrderCreate:
    return OrderCreate(
        po_no=po_no or f"PO-{uuid4().hex}",
        product_id=product_id,
        ordered_quantity=100,
        lot_size=30,
        process_type="FULL",
        raw_material_code="RM-01",
        drawing_number="DWG-01",
        revision="A",
        material="Thép",
        blank_size="10x20",
        order_received_date=date(2026, 11, 5),
    )


def test_create_order_persists_required_data_and_audit() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = _product(db)
        data = _order_data(product.id)
        order = create_order(db, data, actor.id)
        audit = db.scalar(
            select(AuditLog).where(AuditLog.table_name == "orders", AuditLog.record_id == order.id)
        )

        assert order.product_id == product.id
        assert order.process_type == "FULL"
        lots = list(db.scalars(select(ProductionLot).where(ProductionLot.order_id == order.id)))
        assert [(lot.lot_number, lot.quantity) for lot in lots] == [
            (1, 30),
            (2, 30),
            (3, 30),
            (4, 10),
        ]
        assert len({lot.lot_code for lot in lots}) == 4
        assert order.raw_material_code == "RM-01"
        assert audit.actor_id == actor.id
        assert audit.old_values is None
        assert audit.new_values["order_received_date"] == "2026-11-05"
        assert list_orders(db)[0][0].id == order.id
    finally:
        db.rollback()
        db.close()


def test_order_number_must_be_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = _product(db)
        data = _order_data(product.id, "PO-DUPLICATE")
        create_order(db, data, actor.id)
        with pytest.raises(OrderManagementError, match="đã được sử dụng"):
            create_order(db, data, actor.id)
    finally:
        db.rollback()
        db.close()


def test_order_requires_active_product() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = _product(db, active=False)
        with pytest.raises(OrderManagementError, match="đang được sử dụng"):
            create_order(db, _order_data(product.id), actor.id)
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordered_quantity", 0),
        ("ordered_quantity", -1),
        ("lot_size", 0),
        ("lot_size", -1),
        ("process_type", "OTHER"),
        ("raw_material_code", "  "),
        ("drawing_number", ""),
        ("revision", " "),
        ("material", ""),
        ("blank_size", " "),
    ],
)
def test_order_rejects_invalid_quantity_process_or_required_material(
    field: str, value: object
) -> None:
    values = _order_data(1).model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        OrderCreate.model_validate(values)


def test_update_order_versions_and_audits_changes() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = _product(db)
        order = create_order(db, _order_data(product.id), actor.id)
        version = order.version
        values = _order_data(product.id, order.po_no).model_dump()
        values["ordered_quantity"] = 200
        updated = update_order(
            db,
            order.id,
            OrderUpdate.model_validate({**values, "version": version}),
            actor.id,
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "orders", AuditLog.record_id == order.id)
            .order_by(AuditLog.id.desc())
        )

        assert updated.version == version + 1
        assert updated.ordered_quantity == 200
        active_lot_quantities = db.scalars(
            select(ProductionLot.quantity).where(
                ProductionLot.order_id == order.id, ProductionLot.deleted_at.is_(None)
            )
        )
        assert sum(active_lot_quantities) == 200
        assert audit.old_values["ordered_quantity"] == 100
        assert audit.new_values["ordered_quantity"] == 200
        with pytest.raises(ConcurrentOrderChange, match="tải lại"):
            update_order(
                db,
                order.id,
                OrderUpdate.model_validate({**values, "version": version}),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()


def test_existing_order_can_keep_product_after_product_is_deactivated() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = _product(db)
        order = create_order(db, _order_data(product.id), actor.id)
        product.is_active = False
        values = _order_data(product.id, order.po_no).model_dump()
        values["notes"] = "Cập nhật ghi chú"
        updated = update_order(
            db,
            order.id,
            OrderUpdate.model_validate({**values, "version": order.version}),
            actor.id,
        )
        assert updated.notes == "Cập nhật ghi chú"
    finally:
        db.rollback()
        db.close()
