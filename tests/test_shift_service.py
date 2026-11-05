from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.shifts.schemas import ShiftCreate, ShiftUpdate
from app.modules.shifts.service import (
    ConcurrentShiftChange,
    ShiftManagementError,
    create_shift,
    list_active_shifts,
    update_shift,
)


def _admin(db: Session) -> User:
    actor = User(
        username=f"shift-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(actor)
    db.flush()
    return actor


def test_shift_requires_explicit_matching_overnight_flag_and_valid_break() -> None:
    shift = ShiftCreate(
        name="Ca đêm",
        start_time=time(22, 0),
        end_time=time(6, 0),
        planned_break_minutes=30,
        crosses_midnight=True,
    )
    assert shift.crosses_midnight

    for start_time, end_time, pause, overnight in (
        (time(22), time(6), 30, False),
        (time(8), time(16), 481, False),
        (time(8), time(8), 0, False),
    ):
        with pytest.raises(ValidationError):
            ShiftCreate(
                name="Kíp lỗi",
                start_time=start_time,
                end_time=end_time,
                planned_break_minutes=pause,
                crosses_midnight=overnight,
            )


def test_create_shift_audits_and_name_is_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        name = f"Kíp-{uuid4().hex}"
        data = ShiftCreate(
            name=name,
            start_time=time(8),
            end_time=time(16),
            planned_break_minutes=30,
            crosses_midnight=False,
        )
        shift = create_shift(db, data, actor.id)
        audit = db.scalar(
            select(AuditLog).where(AuditLog.table_name == "shifts", AuditLog.record_id == shift.id)
        )
        assert audit.actor_id == actor.id
        assert audit.new_values["planned_break_minutes"] == 30
        with pytest.raises(ShiftManagementError, match="đã được sử dụng"):
            create_shift(db, data, actor.id)
    finally:
        db.rollback()
        db.close()


def test_inactive_shift_is_hidden_and_stale_update_is_rejected() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        shift = create_shift(
            db,
            ShiftCreate(
                name=f"Kíp-{uuid4().hex}",
                start_time=time(7),
                end_time=time(15),
                planned_break_minutes=30,
                crosses_midnight=False,
            ),
            actor.id,
        )
        original_version = shift.version
        update_shift(
            db,
            shift.id,
            ShiftUpdate(
                name=shift.name,
                start_time=time(7),
                end_time=time(15),
                planned_break_minutes=30,
                crosses_midnight=False,
                is_active=False,
                version=original_version,
            ),
            actor.id,
        )
        assert shift not in list_active_shifts(db)
        with pytest.raises(ConcurrentShiftChange, match="tải lại"):
            update_shift(
                db,
                shift.id,
                ShiftUpdate(
                    name=shift.name,
                    start_time=time(7),
                    end_time=time(15),
                    planned_break_minutes=30,
                    crosses_midnight=False,
                    is_active=True,
                    version=original_version,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()
