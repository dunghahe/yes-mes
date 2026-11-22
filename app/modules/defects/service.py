from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.defects.models import DefectCode
from app.modules.defects.schemas import DefectCodeCreate, DefectCodeUpdate


class DefectCodeError(Exception):
    """A defect code rule rejected the requested change."""


class ConcurrentDefectCodeChange(DefectCodeError):
    """The defect code changed since the administrator loaded it."""


def create_defect_code(db: Session, data: DefectCodeCreate, actor_id: int) -> DefectCode:
    if db.scalar(
        select(DefectCode.id).where(
            DefectCode.code == data.code,
            DefectCode.deleted_at.is_(None),
        )
    ):
        raise DefectCodeError("Mã lỗi này đã được sử dụng.")
    now = datetime.now(UTC)
    item = DefectCode(
        code=data.code,
        name=data.name,
        defect_group=data.defect_group,
        detected_at=data.detected_at,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    _audit(db, actor_id, item, "create", None, _values(item), "Admin tạo mã lỗi")
    return item


def update_defect_code(
    db: Session, defect_code_id: int, data: DefectCodeUpdate, actor_id: int
) -> DefectCode:
    item = db.scalar(
        select(DefectCode)
        .where(DefectCode.id == defect_code_id, DefectCode.deleted_at.is_(None))
        .with_for_update()
    )
    if item is None:
        raise DefectCodeError("Không tìm thấy mã lỗi.")
    if item.version != data.version:
        raise ConcurrentDefectCodeChange("Mã lỗi đã thay đổi. Hãy tải lại trang rồi thử lại.")
    if data.code != item.code and db.scalar(
        select(DefectCode.id).where(
            DefectCode.code == data.code,
            DefectCode.deleted_at.is_(None),
            DefectCode.id != item.id,
        )
    ):
        raise DefectCodeError("Mã lỗi này đã được sử dụng.")
    old_values = _values(item)
    item.code = data.code
    item.name = data.name
    if "defect_group" in data.model_fields_set:
        item.defect_group = data.defect_group
    item.detected_at = data.detected_at
    item.is_active = data.is_active
    item.version += 1
    item.updated_at = datetime.now(UTC)
    item.updated_by = actor_id
    _audit(db, actor_id, item, "update", old_values, _values(item), "Admin cập nhật mã lỗi")
    return item


def list_defect_codes(db: Session) -> list[DefectCode]:
    return list(
        db.scalars(
            select(DefectCode)
            .where(DefectCode.deleted_at.is_(None))
            .order_by(DefectCode.is_active.desc(), DefectCode.detected_at, DefectCode.code)
        )
    )


def list_active_defect_codes(db: Session, detected_at: str) -> list[DefectCode]:
    return list(
        db.scalars(
            select(DefectCode)
            .where(
                DefectCode.is_active.is_(True),
                DefectCode.deleted_at.is_(None),
                DefectCode.detected_at == detected_at,
            )
            .order_by(DefectCode.code)
        )
    )


def _values(item: DefectCode) -> dict[str, str | bool]:
    return {
        "code": item.code,
        "name": item.name,
        "defect_group": item.defect_group,
        "detected_at": item.detected_at,
        "is_active": item.is_active,
    }


def _audit(
    db: Session,
    actor_id: int,
    item: DefectCode,
    action: str,
    old_values: dict[str, str | bool] | None,
    new_values: dict[str, str | bool],
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name="defect_codes",
            record_id=item.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
