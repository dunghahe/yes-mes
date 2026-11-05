from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.orders.models import ProductionOrder
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.products.models import Product


class OrderManagementError(Exception):
    """An order business rule rejected the request."""


class ConcurrentOrderChange(OrderManagementError):
    """The order changed since the user loaded it."""


def create_order(db: Session, data: OrderCreate, actor_id: int) -> ProductionOrder:
    if db.scalar(
        select(ProductionOrder.id).where(
            ProductionOrder.po_no == data.po_no,
            ProductionOrder.deleted_at.is_(None),
        )
    ):
        raise OrderManagementError("Số PO này đã được sử dụng.")
    _require_active_product(db, data.product_id)
    now = datetime.now(UTC)
    order = ProductionOrder(
        **data.model_dump(),
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    db.flush()
    _audit(db, actor_id, order, "create", None, _values(order), "Kế hoạch tạo PO")
    return order


def update_order(db: Session, order_id: int, data: OrderUpdate, actor_id: int) -> ProductionOrder:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None:
        raise OrderManagementError("Không tìm thấy PO.")
    if order.version != data.version:
        raise ConcurrentOrderChange("PO đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if data.po_no != order.po_no and db.scalar(
        select(ProductionOrder.id).where(
            ProductionOrder.po_no == data.po_no,
            ProductionOrder.deleted_at.is_(None),
            ProductionOrder.id != order_id,
        )
    ):
        raise OrderManagementError("Số PO này đã được sử dụng.")
    if data.product_id != order.product_id:
        _require_active_product(db, data.product_id)

    old_values = _values(order)
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(order, field, value)
    order.version += 1
    order.updated_at = datetime.now(UTC)
    order.updated_by = actor_id
    _audit(db, actor_id, order, "update", old_values, _values(order), "Kế hoạch cập nhật PO")
    return order


def _require_active_product(db: Session, product_id: int) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
        )
    )
    if product is None:
        raise OrderManagementError("Chọn mã hàng đang được sử dụng.")
    return product


def list_orders(db: Session) -> list[tuple[ProductionOrder, Product]]:
    return list(
        db.execute(
            select(ProductionOrder, Product)
            .join(Product, Product.id == ProductionOrder.product_id)
            .where(ProductionOrder.deleted_at.is_(None))
            .order_by(ProductionOrder.created_at.desc(), ProductionOrder.id.desc())
        )
    )


def get_order(db: Session, order_id: int) -> tuple[ProductionOrder, Product] | None:
    row = db.execute(
        select(ProductionOrder, Product)
        .join(Product, Product.id == ProductionOrder.product_id)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
    ).first()
    return row


def _values(order: ProductionOrder) -> dict[str, object]:
    return {
        "po_no": order.po_no,
        "product_id": order.product_id,
        "ordered_quantity": order.ordered_quantity,
        "process_type": order.process_type,
        "raw_material_code": order.raw_material_code,
        "drawing_number": order.drawing_number,
        "revision": order.revision,
        "material": order.material,
        "blank_size": order.blank_size,
        "order_received_date": order.order_received_date.isoformat(),
        "notes": order.notes,
    }


def _audit(
    db: Session,
    actor_id: int,
    order: ProductionOrder,
    action: str,
    old_values: dict[str, object] | None,
    new_values: dict[str, object],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="orders",
            record_id=order.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
