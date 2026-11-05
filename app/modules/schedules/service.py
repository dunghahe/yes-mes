from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import BlankRequest
from app.modules.orders.models import ProductionOrder
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.schedules.schemas import ScheduleBatchCreate, ScheduleUpdate
from app.modules.shifts.models import Shift


class ScheduleManagementError(Exception):
    """A schedule business rule rejected the requested change."""


class ConcurrentScheduleChange(ScheduleManagementError):
    """The schedule changed since the user loaded it."""


def create_schedule_batch(
    db: Session, data: ScheduleBatchCreate, actor_id: int
) -> tuple[list[ProductionSchedule], bool]:
    order = _lock_order(db, data.order_id)
    _require_active_shift(db, data.shift_id)
    existing_total = db.scalar(
        select(func.coalesce(func.sum(ProductionSchedule.planned_quantity), 0)).where(
            ProductionSchedule.order_id == order.id,
            ProductionSchedule.deleted_at.is_(None),
        )
    )
    exceeds_order = (
        existing_total + data.planned_quantity * len(data.production_dates) > order.ordered_quantity
    )
    now = datetime.now(UTC)
    schedules = []
    for production_date in data.production_dates:
        schedule = ProductionSchedule(
            production_date=production_date,
            shift_id=data.shift_id,
            order_id=data.order_id,
            planned_quantity=data.planned_quantity,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(schedule)
        db.flush()
        _audit(db, actor_id, schedule, "create", None, _values(schedule), "Kế hoạch lập lịch")
        schedules.append(schedule)
    return schedules, exceeds_order


def update_schedule(
    db: Session, schedule_id: int, data: ScheduleUpdate, actor_id: int
) -> tuple[ProductionSchedule, bool]:
    schedule = db.scalar(
        select(ProductionSchedule)
        .where(ProductionSchedule.id == schedule_id, ProductionSchedule.deleted_at.is_(None))
        .with_for_update()
    )
    if schedule is None:
        raise ScheduleManagementError("Không tìm thấy dòng lịch.")
    if schedule.version != data.version:
        raise ConcurrentScheduleChange("Dòng lịch đã thay đổi. Hãy tải lại trang rồi thử lại.")

    order = _lock_order(db, data.order_id)
    _require_active_shift(db, data.shift_id)
    old_values = _values(schedule)
    other_total = db.scalar(
        select(func.coalesce(func.sum(ProductionSchedule.planned_quantity), 0)).where(
            ProductionSchedule.order_id == data.order_id,
            ProductionSchedule.deleted_at.is_(None),
            ProductionSchedule.id != schedule_id,
        )
    )
    exceeds_order = other_total + data.planned_quantity > order.ordered_quantity
    schedule.production_date = data.production_date
    schedule.shift_id = data.shift_id
    schedule.order_id = data.order_id
    schedule.planned_quantity = data.planned_quantity
    schedule.version += 1
    schedule.updated_at = datetime.now(UTC)
    schedule.updated_by = actor_id
    _audit(db, actor_id, schedule, "update", old_values, _values(schedule), "Kế hoạch sửa lịch")
    return schedule, exceeds_order


def soft_delete_schedule(db: Session, schedule_id: int, actor_id: int) -> ProductionSchedule:
    schedule = db.scalar(
        select(ProductionSchedule)
        .where(ProductionSchedule.id == schedule_id, ProductionSchedule.deleted_at.is_(None))
        .with_for_update()
    )
    if schedule is None:
        raise ScheduleManagementError("Không tìm thấy dòng lịch.")
    delivered_request = db.scalar(
        select(BlankRequest.id).where(
            BlankRequest.schedule_id == schedule.id,
            BlankRequest.status == "delivered",
            BlankRequest.deleted_at.is_(None),
        )
    )
    if delivered_request is not None:
        raise ScheduleManagementError("Không thể xóa lịch đã có yêu cầu phôi được xác nhận giao.")
    old_values = _values(schedule)
    now = datetime.now(UTC)
    schedule.deleted_at = now
    schedule.updated_at = now
    schedule.updated_by = actor_id
    schedule.version += 1
    _audit(
        db,
        actor_id,
        schedule,
        "delete",
        old_values,
        {"deleted_at": now.isoformat()},
        "Kế hoạch xóa dòng lịch",
    )
    return schedule


def list_schedules(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    shift_id: int | None = None,
    order_id: int | None = None,
    include_deleted: bool = False,
):
    query = (
        select(ProductionSchedule, ProductionOrder, Shift, Product)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .order_by(ProductionSchedule.production_date, Shift.start_time, ProductionSchedule.id)
    )
    if not include_deleted:
        query = query.where(ProductionSchedule.deleted_at.is_(None))
    if start_date is not None:
        query = query.where(ProductionSchedule.production_date >= start_date)
    if end_date is not None:
        query = query.where(ProductionSchedule.production_date <= end_date)
    if shift_id is not None:
        query = query.where(ProductionSchedule.shift_id == shift_id)
    if order_id is not None:
        query = query.where(ProductionSchedule.order_id == order_id)
    return list(db.execute(query))


def get_schedule(db: Session, schedule_id: int):
    return db.execute(
        select(ProductionSchedule, ProductionOrder, Shift, Product)
        .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
        .join(Product, Product.id == ProductionOrder.product_id)
        .join(Shift, Shift.id == ProductionSchedule.shift_id)
        .where(ProductionSchedule.id == schedule_id, ProductionSchedule.deleted_at.is_(None))
    ).first()


def _lock_order(db: Session, order_id: int) -> ProductionOrder:
    order = db.scalar(
        select(ProductionOrder)
        .where(ProductionOrder.id == order_id, ProductionOrder.deleted_at.is_(None))
        .with_for_update()
    )
    if order is None:
        raise ScheduleManagementError("Chọn PO đang được sử dụng.")
    return order


def _require_active_shift(db: Session, shift_id: int) -> Shift:
    shift = db.scalar(
        select(Shift).where(
            Shift.id == shift_id,
            Shift.is_active.is_(True),
            Shift.deleted_at.is_(None),
        )
    )
    if shift is None:
        raise ScheduleManagementError("Chọn kíp đang được sử dụng.")
    return shift


def _values(schedule: ProductionSchedule) -> dict[str, object]:
    return {
        "production_date": schedule.production_date.isoformat(),
        "shift_id": schedule.shift_id,
        "order_id": schedule.order_id,
        "planned_quantity": schedule.planned_quantity,
    }


def _audit(
    db: Session,
    actor_id: int,
    schedule: ProductionSchedule,
    action: str,
    old_values: dict[str, object] | None,
    new_values: dict[str, object],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="schedules",
            record_id=schedule.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
