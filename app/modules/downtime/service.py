from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.downtime.models import DowntimeReason
from app.modules.downtime.schemas import DowntimeReasonCreate, DowntimeReasonUpdate


class DowntimeReasonError(Exception):
    """A downtime reason rule rejected the request."""


class ConcurrentDowntimeReasonChange(DowntimeReasonError):
    """The reason changed since the administrator loaded it."""


def create_reason(db: Session, data: DowntimeReasonCreate, actor_id: int) -> DowntimeReason:
    if db.scalar(
        select(DowntimeReason.id).where(
            DowntimeReason.code == data.code,
            DowntimeReason.deleted_at.is_(None),
        )
    ):
        raise DowntimeReasonError("Mã lý do dừng máy này đã được sử dụng.")
    now = datetime.now(UTC)
    item = DowntimeReason(
        code=data.code,
        name=data.name,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    _audit(db, actor_id, item, "create", None, _values(item), "Admin tạo lý do dừng máy")
    return item


def update_reason(
    db: Session, reason_id: int, data: DowntimeReasonUpdate, actor_id: int
) -> DowntimeReason:
    item = db.scalar(
        select(DowntimeReason)
        .where(DowntimeReason.id == reason_id, DowntimeReason.deleted_at.is_(None))
        .with_for_update()
    )
    if item is None:
        raise DowntimeReasonError("Không tìm thấy lý do dừng máy.")
    if item.version != data.version:
        raise ConcurrentDowntimeReasonChange(
            "Lý do dừng máy đã thay đổi. Hãy tải lại trang rồi thử lại."
        )
    if data.code != item.code and db.scalar(
        select(DowntimeReason.id).where(
            DowntimeReason.code == data.code,
            DowntimeReason.deleted_at.is_(None),
            DowntimeReason.id != item.id,
        )
    ):
        raise DowntimeReasonError("Mã lý do dừng máy này đã được sử dụng.")
    old_values = _values(item)
    item.code = data.code
    item.name = data.name
    item.is_active = data.is_active
    item.version += 1
    item.updated_at = datetime.now(UTC)
    item.updated_by = actor_id
    _audit(db, actor_id, item, "update", old_values, _values(item), "Admin cập nhật lý do dừng máy")
    return item


def list_reasons(db: Session) -> list[DowntimeReason]:
    return list(
        db.scalars(
            select(DowntimeReason)
            .where(DowntimeReason.deleted_at.is_(None))
            .order_by(DowntimeReason.is_active.desc(), DowntimeReason.name)
        )
    )


def list_active_reasons(db: Session) -> list[DowntimeReason]:
    return list(
        db.scalars(
            select(DowntimeReason)
            .where(DowntimeReason.is_active.is_(True), DowntimeReason.deleted_at.is_(None))
            .order_by(DowntimeReason.name)
        )
    )


def _values(item: DowntimeReason) -> dict[str, str | bool]:
    return {"code": item.code, "name": item.name, "is_active": item.is_active}


def _audit(
    db: Session,
    actor_id: int,
    item: DowntimeReason,
    action: str,
    old_values: dict[str, str | bool] | None,
    new_values: dict[str, str | bool],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="downtime_reasons",
            record_id=item.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
