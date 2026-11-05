from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.shifts.models import Shift
from app.modules.shifts.schemas import ShiftCreate, ShiftUpdate


class ShiftManagementError(Exception):
    """A shift master data rule rejected the request."""


class ConcurrentShiftChange(ShiftManagementError):
    """The shift changed since the administrator loaded it."""


def create_shift(db: Session, data: ShiftCreate, actor_id: int) -> Shift:
    if db.scalar(select(Shift.id).where(Shift.name == data.name, Shift.deleted_at.is_(None))):
        raise ShiftManagementError("Tên kíp này đã được sử dụng.")
    now = datetime.now(UTC)
    shift = Shift(
        name=data.name,
        start_time=data.start_time,
        end_time=data.end_time,
        planned_break_minutes=data.planned_break_minutes,
        crosses_midnight=data.crosses_midnight,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(shift)
    db.flush()
    _audit(db, actor_id, shift, "create", None, _values(shift), "Admin tạo kíp")
    return shift


def update_shift(db: Session, shift_id: int, data: ShiftUpdate, actor_id: int) -> Shift:
    shift = db.scalar(
        select(Shift).where(Shift.id == shift_id, Shift.deleted_at.is_(None)).with_for_update()
    )
    if shift is None:
        raise ShiftManagementError("Không tìm thấy kíp.")
    if shift.version != data.version:
        raise ConcurrentShiftChange("Kíp đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if data.name != shift.name and db.scalar(
        select(Shift.id).where(
            Shift.name == data.name,
            Shift.deleted_at.is_(None),
            Shift.id != shift_id,
        )
    ):
        raise ShiftManagementError("Tên kíp này đã được sử dụng.")
    old_values = _values(shift)
    shift.name = data.name
    shift.start_time = data.start_time
    shift.end_time = data.end_time
    shift.planned_break_minutes = data.planned_break_minutes
    shift.crosses_midnight = data.crosses_midnight
    shift.is_active = data.is_active
    shift.version += 1
    shift.updated_at = datetime.now(UTC)
    shift.updated_by = actor_id
    _audit(db, actor_id, shift, "update", old_values, _values(shift), "Admin cập nhật kíp")
    return shift


def list_shifts(db: Session) -> list[Shift]:
    return list(
        db.scalars(
            select(Shift)
            .where(Shift.deleted_at.is_(None))
            .order_by(Shift.is_active.desc(), Shift.start_time, Shift.id)
        )
    )


def list_active_shifts(db: Session) -> list[Shift]:
    return list(
        db.scalars(
            select(Shift)
            .where(Shift.deleted_at.is_(None), Shift.is_active.is_(True))
            .order_by(Shift.start_time, Shift.id)
        )
    )


def _values(shift: Shift) -> dict[str, str | int | bool]:
    return {
        "name": shift.name,
        "start_time": shift.start_time.isoformat(),
        "end_time": shift.end_time.isoformat(),
        "planned_break_minutes": shift.planned_break_minutes,
        "crosses_midnight": shift.crosses_midnight,
        "is_active": shift.is_active,
    }


def _audit(
    db: Session,
    actor_id: int,
    shift: Shift,
    action: str,
    old_values: dict[str, str | int | bool] | None,
    new_values: dict[str, str | int | bool],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="shifts",
            record_id=shift.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
