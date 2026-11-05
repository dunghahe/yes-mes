from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.products.schemas import ProductCreate, ProductUpdate
from app.modules.products.service import (
    ConcurrentProductChange,
    ProductManagementError,
    create_product,
    list_active_products,
    update_product,
)


def _admin(db: Session) -> User:
    admin = User(
        username=f"product-admin-{uuid4().hex}",
        display_name="Quản trị viên thử nghiệm",
        password_hash="not-used-by-this-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(admin)
    db.flush()
    return admin


def _product_create(code: str) -> ProductCreate:
    return ProductCreate(
        code=code,
        name="Mã hàng thử nghiệm",
        cycle_time_seconds=Decimal("3.25"),
        default_process_type="FULL",
    )


def test_create_product_persists_data_and_audit() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = create_product(db, _product_create(f"P-{uuid4().hex}"), actor.id)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.table_name == "products", AuditLog.record_id == product.id
            )
        )

        assert product.cycle_time_seconds == Decimal("3.250")
        assert product.default_process_type == "FULL"
        assert product.is_active
        assert audit.actor_id == actor.id
        assert audit.old_values is None
        assert audit.new_values["cycle_time_seconds"] == "3.250"
    finally:
        db.rollback()
        db.close()


def test_product_code_must_be_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        code = f"DUP-{uuid4().hex}"
        create_product(db, _product_create(code), actor.id)
        with pytest.raises(ProductManagementError, match="đã được sử dụng"):
            create_product(db, _product_create(code), actor.id)
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    ("cycle_time", "process_type"),
    [("0", "FULL"), ("-1", "FULL"), ("1", "OTHER"), ("1.1234", "FULL")],
)
def test_product_rejects_invalid_cycle_time_or_process_type(
    cycle_time: str, process_type: str
) -> None:
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(
            {
                "code": "P-TEST",
                "name": "Hàng thử",
                "cycle_time_seconds": cycle_time,
                "default_process_type": process_type,
            }
        )


def test_update_product_uses_version_audits_and_hides_inactive_items() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        product = create_product(db, _product_create(f"UPD-{uuid4().hex}"), actor.id)
        initial_version = product.version
        updated = update_product(
            db,
            product.id,
            ProductUpdate(
                code=product.code,
                name="Tên đã sửa",
                cycle_time_seconds=Decimal("7.5"),
                default_process_type="SX_ONLY",
                is_active=False,
                version=initial_version,
            ),
            actor.id,
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.table_name == "products", AuditLog.record_id == product.id)
            .order_by(AuditLog.id.desc())
        )

        assert updated.version == initial_version + 1
        assert updated.cycle_time_seconds == Decimal("7.500")
        assert not updated.is_active
        assert product not in list_active_products(db)
        assert audit.old_values["cycle_time_seconds"] == "3.250"
        assert audit.new_values["cycle_time_seconds"] == "7.500"

        with pytest.raises(ConcurrentProductChange, match="tải lại"):
            update_product(
                db,
                product.id,
                ProductUpdate(
                    code=product.code,
                    name="Tên cũ",
                    cycle_time_seconds=Decimal("3.25"),
                    default_process_type="FULL",
                    is_active=True,
                    version=initial_version,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()
