from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuditLog
from app.modules.settings.models import SystemSetting
from app.modules.settings.schemas import ProductionSettingsInput

DEFAULT_PO_AUTO_CLOSE_PCT = 100


class SettingsError(ValueError):
    pass


def po_auto_close_pct(db: Session) -> int:
    setting = db.get(SystemSetting, "po_auto_close_pct")
    if setting is None:
        return DEFAULT_PO_AUTO_CLOSE_PCT
    try:
        value = int(setting.value)
    except ValueError:
        return DEFAULT_PO_AUTO_CLOSE_PCT
    return value if 1 <= value <= 100 else DEFAULT_PO_AUTO_CLOSE_PCT


def get_production_settings(db: Session) -> tuple[int, int]:
    setting = db.get(SystemSetting, "po_auto_close_pct")
    return (po_auto_close_pct(db), setting.version if setting else 1)


def update_production_settings(
    db: Session, data: ProductionSettingsInput, actor_id: int
) -> SystemSetting:
    setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "po_auto_close_pct").with_for_update()
    )
    if setting is None:
        setting = SystemSetting(
            key="po_auto_close_pct",
            value=str(data.po_auto_close_pct),
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(setting)
        db.flush()
        old_values = None
        action = "insert"
    else:
        if setting.version != data.version:
            raise SettingsError("Cài đặt đã thay đổi. Tải lại trước khi lưu.")
        old_values = {"po_auto_close_pct": int(setting.value), "version": setting.version}
        setting.value = str(data.po_auto_close_pct)
        setting.version += 1
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = actor_id
        action = "update"
    db.add(
        AuditLog(
            table_name="settings",
            record_id=1,
            action=action,
            old_values=old_values,
            new_values={"po_auto_close_pct": int(setting.value), "version": setting.version},
            reason="Cập nhật ngưỡng tự đóng PO",
            actor_id=actor_id,
        )
    )
    db.flush()
    from app.modules.orders.lifecycle import refresh_order_lifecycle
    from app.modules.orders.models import ProductionOrder

    for order_id in db.scalars(
        select(ProductionOrder.id).where(ProductionOrder.deleted_at.is_(None))
    ):
        refresh_order_lifecycle(db, order_id, actor_id)
    return setting
