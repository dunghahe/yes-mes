from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.downtime.models import DEFAULT_DOWNTIME_REASONS
from app.modules.downtime.schemas import DowntimeReasonCreate, DowntimeReasonUpdate
from app.modules.downtime.service import (
    ConcurrentDowntimeReasonChange,
    DowntimeReasonError,
    create_reason,
    list_active_reasons,
    list_reasons,
    update_reason,
)


def _admin(db: Session) -> User:
    actor = User(
        username=f"downtime-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(actor)
    db.flush()
    return actor


def test_default_reasons_are_seeded_and_audited() -> None:
    db = SessionLocal()
    try:
        names = {item.name for item in list_reasons(db)}
        assert {name for _, name in DEFAULT_DOWNTIME_REASONS} <= names
        logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.table_name == "downtime_reasons",
                    AuditLog.reason == "Tạo lý do dừng máy mặc định trong migration",
                )
            )
        )
        assert len(logs) == len(DEFAULT_DOWNTIME_REASONS)
        assert all(log.actor_id is None for log in logs)
    finally:
        db.close()


def test_create_reason_is_audited_and_code_must_be_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        code = f"CUSTOM-{uuid4().hex}"
        item = create_reason(db, DowntimeReasonCreate(code=code, name="Chờ vật tư phụ"), actor.id)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.table_name == "downtime_reasons", AuditLog.record_id == item.id
            )
        )
        assert audit.actor_id == actor.id
        assert audit.new_values["name"] == "Chờ vật tư phụ"
        with pytest.raises(DowntimeReasonError, match="đã được sử dụng"):
            create_reason(db, DowntimeReasonCreate(code=code, name="Tên khác"), actor.id)
    finally:
        db.rollback()
        db.close()


def test_reason_validation_and_inactive_selector_behavior() -> None:
    with pytest.raises(ValidationError):
        DowntimeReasonCreate(code="", name="Lý do")
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        item = create_reason(
            db,
            DowntimeReasonCreate(code=f"TEMP-{uuid4().hex}", name="Lý do thử"),
            actor.id,
        )
        original_version = item.version
        update_reason(
            db,
            item.id,
            DowntimeReasonUpdate(
                code=item.code,
                name=item.name,
                is_active=False,
                version=original_version,
            ),
            actor.id,
        )
        assert item not in list_active_reasons(db)
        with pytest.raises(ConcurrentDowntimeReasonChange, match="tải lại"):
            update_reason(
                db,
                item.id,
                DowntimeReasonUpdate(
                    code=item.code,
                    name=item.name,
                    is_active=True,
                    version=original_version,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()
