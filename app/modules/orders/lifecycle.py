from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.orders.models import ProductionOrder
from app.modules.settings.service import po_auto_close_pct


class OrderLifecycleError(ValueError):
    pass


def refresh_order_lifecycle(
    db: Session, order_id: int, actor_id: int | None
) -> ProductionOrder | None:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None or order.status == "cancelled":
        return order
    if order.closed_manually:
        return order
    summary = db.execute(
        text("SELECT finished_quantity FROM v_po_summary WHERE order_id = :order_id"),
        {"order_id": order_id},
    ).first()
    finished = int(summary[0] or 0) if summary else 0
    threshold_pct = po_auto_close_pct(db)
    threshold = int(
        (Decimal(order.ordered_quantity) * Decimal(threshold_pct) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )
    if finished >= threshold:
        next_status = "done"
    else:
        from app.modules.daily_reports.models import BaviaReport, DailyReport

        has_bavia = db.scalar(
            select(BaviaReport.id)
            .where(
                BaviaReport.order_id == order_id,
                BaviaReport.deleted_at.is_(None),
            )
            .limit(1)
        )
        from app.modules.blank_requests.models import BlankRequest
        from app.modules.schedules.models import ProductionSchedule

        has_order_report = db.scalar(
            select(DailyReport.id)
            .join(BlankRequest, BlankRequest.id == DailyReport.blank_request_id)
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .where(
                ProductionSchedule.order_id == order_id,
                DailyReport.deleted_at.is_(None),
                BlankRequest.deleted_at.is_(None),
                ProductionSchedule.deleted_at.is_(None),
            )
            .limit(1)
        )
        next_status = "in_progress" if has_order_report or has_bavia else "open"
    if order.status != next_status:
        old_status = order.status
        order.status = next_status
        order.version += 1
        db.add(
            AuditLog(
                table_name="orders",
                record_id=order.id,
                action="update",
                old_values={"status": old_status, "closed_manually": False},
                new_values={"status": next_status, "closed_manually": False},
                reason="Tự cập nhật trạng thái PO theo số thành phẩm",
                actor_id=actor_id,
            )
        )
    return order


def close_order_manually(db: Session, order_id: int, actor_id: int, reason: str) -> ProductionOrder:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None:
        raise ValueError("Không tìm thấy PO đang hoạt động.")
    if order.status == "cancelled":
        raise ValueError("Không thể đóng PO đã hủy.")
    if not reason.strip():
        raise ValueError("Nhập lý do đóng PO.")
    old = {"status": order.status, "closed_manually": order.closed_manually}
    order.status = "done"
    order.closed_manually = True
    order.version += 1
    db.add(
        AuditLog(
            table_name="orders",
            record_id=order.id,
            action="update",
            old_values=old,
            new_values={"status": "done", "closed_manually": True},
            reason=reason.strip(),
            actor_id=actor_id,
        )
    )
    return order
