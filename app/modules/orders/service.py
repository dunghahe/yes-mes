from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.daily_reports.models import (
    BaviaReport,
    DailyReport,
    DailyReportLine,
    DailyReportPair,
)
from app.modules.orders.models import ProductionLot, ProductionOrder
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.products.models import Product
from app.modules.qc.models import LotQcInspection
from app.modules.schedules.models import ProductionSchedule


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
    _rebuild_lots(db, order, actor_id)
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
    active_schedule_ids = select(ProductionSchedule.id).where(
        ProductionSchedule.order_id == order.id,
        ProductionSchedule.deleted_at.is_(None),
    )
    has_schedule = db.scalar(active_schedule_ids.limit(1)) is not None
    has_request = db.scalar(
        select(BlankRequest.id)
        .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
        .where(
            ProductionSchedule.order_id == order.id,
            BlankRequest.deleted_at.is_(None),
            ProductionSchedule.deleted_at.is_(None),
        )
        .limit(1)
    )
    if (has_schedule or has_request) and (
        data.product_id != order.product_id or data.process_type != order.process_type
    ):
        raise OrderManagementError(
            "Không đổi mã hàng hoặc loại công đoạn sau khi đã lập lịch hoặc tạo yêu cầu phôi."
        )
    if data.ordered_quantity < order.ordered_quantity and has_schedule:
        planned_quantity = db.scalar(
            select(func.coalesce(func.sum(ProductionSchedule.planned_quantity), 0)).where(
                ProductionSchedule.order_id == order.id,
                ProductionSchedule.deleted_at.is_(None),
            )
        )
        if data.ordered_quantity < planned_quantity:
            raise OrderManagementError(
                f"Số lượng PO không thể thấp hơn tổng đã lập lịch ({planned_quantity})."
            )

    lot_configuration_changed = (
        data.ordered_quantity != order.ordered_quantity or data.lot_size != order.lot_size
    )
    if lot_configuration_changed:
        if has_schedule:
            raise OrderManagementError("Không đổi số lượng PO hoặc cỡ lô sau khi đã lập lịch.")
        active_lots = list(
            db.scalars(
                select(ProductionLot)
                .where(ProductionLot.order_id == order.id, ProductionLot.deleted_at.is_(None))
                .with_for_update()
            )
        )
        if any(lot.printed_at is not None for lot in active_lots):
            raise OrderManagementError("Không đổi số lượng PO hoặc cỡ lô sau khi đã in phiếu lô.")

    old_values = _values(order)
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(order, field, value)
    order.version += 1
    order.updated_at = datetime.now(UTC)
    order.updated_by = actor_id
    if lot_configuration_changed:
        _rebuild_lots(db, order, actor_id)
    _audit(db, actor_id, order, "update", old_values, _values(order), "Kế hoạch cập nhật PO")
    from app.modules.orders.lifecycle import OrderLifecycleError, refresh_order_lifecycle

    try:
        refresh_order_lifecycle(db, order.id, actor_id)
    except OrderLifecycleError as exc:
        raise OrderManagementError(str(exc)) from exc
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


def _rebuild_lots(db: Session, order: ProductionOrder, actor_id: int) -> None:
    now = datetime.now(UTC)
    existing = list(
        db.scalars(
            select(ProductionLot)
            .where(ProductionLot.order_id == order.id, ProductionLot.deleted_at.is_(None))
            .with_for_update()
        )
    )
    for lot in existing:
        lot.deleted_at = now
        lot.updated_at = now
        lot.updated_by = actor_id
    if existing:
        db.flush()

    remaining = order.ordered_quantity
    lot_number = 1
    while remaining:
        quantity = min(order.lot_size, remaining)
        db.add(
            ProductionLot(
                order_id=order.id,
                lot_number=lot_number,
                lot_code=f"L{order.id:06d}-{lot_number:03d}",
                quantity=quantity,
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        remaining -= quantity
        lot_number += 1
    db.flush()


def list_orders(
    db: Session, *, limit: int | None = None, offset: int = 0
) -> list[tuple[ProductionOrder, Product]]:
    query = (
        select(ProductionOrder, Product)
        .join(Product, Product.id == ProductionOrder.product_id)
        .where(ProductionOrder.deleted_at.is_(None))
        .order_by(ProductionOrder.created_at.desc(), ProductionOrder.id.desc())
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.execute(query))


def count_orders(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(ProductionOrder.id)).where(ProductionOrder.deleted_at.is_(None))
        )
        or 0
    )


def order_progress_summary(db: Session, order_ids: list[int]) -> dict[int, dict[str, int | None]]:
    """Summarize confirmed production and first-pass lot QC without join fan-out."""
    if not order_ids:
        return {}
    summaries: dict[int, dict[str, int | None]] = {
        order_id: {"production": 0, "bavia": 0, "qc_ok": 0, "qc_ng": 0} for order_id in order_ids
    }
    production_rows = db.execute(
        select(DailyReportLine.order_id, func.sum(DailyReportLine.quantity_produced))
        .join(DailyReportPair, DailyReportPair.id == DailyReportLine.daily_report_pair_id)
        .join(DailyReport, DailyReport.id == DailyReportPair.daily_report_id)
        .where(
            DailyReportLine.order_id.in_(order_ids),
            DailyReport.status == "confirmed",
            DailyReport.deleted_at.is_(None),
            DailyReportPair.deleted_at.is_(None),
            DailyReportLine.deleted_at.is_(None),
        )
        .group_by(DailyReportLine.order_id)
    )
    for order_id, quantity in production_rows:
        summaries[order_id]["production"] = int(quantity or 0)

    bavia_rows = db.execute(
        select(BaviaReport.order_id, func.sum(BaviaReport.quantity_produced))
        .where(BaviaReport.order_id.in_(order_ids), BaviaReport.deleted_at.is_(None))
        .group_by(BaviaReport.order_id)
    )
    for order_id, quantity in bavia_rows:
        summaries[order_id]["bavia"] = int(quantity or 0)

    qc_rows = db.execute(
        select(
            ProductionLot.order_id,
            func.sum(LotQcInspection.quantity_ok),
            func.sum(LotQcInspection.ng_scrap + LotQcInspection.ng_repair),
        )
        .join(LotQcInspection, LotQcInspection.production_lot_id == ProductionLot.id)
        .where(
            ProductionLot.order_id.in_(order_ids),
            ProductionLot.deleted_at.is_(None),
            LotQcInspection.deleted_at.is_(None),
        )
        .group_by(ProductionLot.order_id)
    )
    for order_id, quantity_ok, quantity_ng in qc_rows:
        summaries[order_id]["qc_ok"] = int(quantity_ok or 0)
        summaries[order_id]["qc_ng"] = int(quantity_ng or 0)

    bavia_only_ids = set(
        db.scalars(
            select(ProductionOrder.id).where(
                ProductionOrder.id.in_(order_ids), ProductionOrder.process_type == "BAVIA_ONLY"
            )
        )
    )
    for order_id in bavia_only_ids:
        summaries[order_id]["production"] = None
        summaries[order_id]["qc_ok"] = None
        summaries[order_id]["qc_ng"] = None
    return summaries


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
        "lot_size": order.lot_size,
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
