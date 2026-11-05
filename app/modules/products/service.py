from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.products.models import Product
from app.modules.products.schemas import ProductCreate, ProductUpdate


class ProductManagementError(Exception):
    """A product master data rule rejected the requested change."""


class ConcurrentProductChange(ProductManagementError):
    """The product changed since the administrator loaded it."""


def create_product(db: Session, data: ProductCreate, actor_id: int) -> Product:
    code = data.code.strip()
    if db.scalar(select(Product.id).where(Product.code == code, Product.deleted_at.is_(None))):
        raise ProductManagementError("Mã hàng này đã được sử dụng.")

    now = datetime.now(UTC)
    product = Product(
        code=code,
        name=data.name.strip(),
        cycle_time_seconds=data.cycle_time_seconds,
        default_process_type=data.default_process_type,
        is_active=True,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(product)
    db.flush()
    _write_audit(
        db,
        actor_id=actor_id,
        product=product,
        action="create",
        old_values=None,
        new_values=_product_values(product),
        reason="Admin tạo mã hàng",
    )
    return product


def update_product(db: Session, product_id: int, data: ProductUpdate, actor_id: int) -> Product:
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.deleted_at.is_(None))
        .with_for_update()
    )
    if product is None:
        raise ProductManagementError("Không tìm thấy mã hàng.")
    if product.version != data.version:
        raise ConcurrentProductChange("Mã hàng đã được thay đổi. Hãy tải lại trang rồi thử lại.")

    code = data.code.strip()
    if code != product.code and db.scalar(
        select(Product.id).where(
            Product.code == code,
            Product.deleted_at.is_(None),
            Product.id != product.id,
        )
    ):
        raise ProductManagementError("Mã hàng này đã được sử dụng.")

    old_values = _product_values(product)
    product.code = code
    product.name = data.name.strip()
    product.cycle_time_seconds = data.cycle_time_seconds
    product.default_process_type = data.default_process_type
    product.is_active = data.is_active
    product.version += 1
    product.updated_at = datetime.now(UTC)
    product.updated_by = actor_id
    _write_audit(
        db,
        actor_id=actor_id,
        product=product,
        action="update",
        old_values=old_values,
        new_values=_product_values(product),
        reason="Admin cập nhật mã hàng hoặc trạng thái sử dụng",
    )
    return product


def list_products(db: Session) -> list[Product]:
    return list(
        db.scalars(
            select(Product)
            .where(Product.deleted_at.is_(None))
            .order_by(Product.is_active.desc(), Product.code, Product.id)
        )
    )


def list_active_products(db: Session) -> list[Product]:
    return list(
        db.scalars(
            select(Product)
            .where(Product.deleted_at.is_(None), Product.is_active.is_(True))
            .order_by(Product.code, Product.id)
        )
    )


def _product_values(product: Product) -> dict[str, str | bool]:
    return {
        "code": product.code,
        "name": product.name,
        "cycle_time_seconds": _decimal_text(product.cycle_time_seconds),
        "default_process_type": product.default_process_type,
        "is_active": product.is_active,
    }


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.001")), "f")


def _write_audit(
    db: Session,
    *,
    actor_id: int,
    product: Product,
    action: str,
    old_values: dict[str, str | bool] | None,
    new_values: dict[str, str | bool],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="products",
            record_id=product.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
