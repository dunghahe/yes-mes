from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.defects.schemas import DefectCodeCreate, DefectCodeUpdate
from app.modules.defects.service import (
    ConcurrentDefectCodeChange,
    DefectCodeError,
    create_defect_code,
    list_active_defect_codes,
    update_defect_code,
)


def _admin(db: Session) -> User:
    actor = User(
        username=f"defect-admin-{uuid4().hex}",
        display_name="Admin thử nghiệm",
        password_hash="not-used-by-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(actor)
    db.flush()
    return actor


def _data(code: str, detected_at: str = "SX") -> DefectCodeCreate:
    return DefectCodeCreate(
        code=code,
        name="Lỗi thử nghiệm",
        defect_group="Ngoại quan",
        detected_at=detected_at,
    )


def test_create_defect_code_audits_without_machine_binding() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        item = create_defect_code(db, _data(f"NG-{uuid4().hex}"), actor.id)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.table_name == "defect_codes", AuditLog.record_id == item.id
            )
        )

        assert item.detected_at == "SX"
        assert "machine_id" not in item.__table__.columns
        assert audit.actor_id == actor.id
        assert audit.new_values["defect_group"] == "Ngoại quan"
    finally:
        db.rollback()
        db.close()


def test_defect_code_is_unique() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        code = f"NG-{uuid4().hex}"
        create_defect_code(db, _data(code), actor.id)
        with pytest.raises(DefectCodeError, match="đã được sử dụng"):
            create_defect_code(db, _data(code), actor.id)
    finally:
        db.rollback()
        db.close()


def test_detected_process_is_limited_to_sx_or_bavia() -> None:
    with pytest.raises(ValidationError):
        DefectCodeCreate(code="NG-1", name="Lỗi", defect_group="Nhóm", detected_at="OTHER")


def test_inactive_code_is_hidden_and_stale_update_is_blocked() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        item = create_defect_code(db, _data(f"NG-{uuid4().hex}"), actor.id)
        old_version = item.version
        update_defect_code(
            db,
            item.id,
            DefectCodeUpdate(
                code=item.code,
                name=item.name,
                defect_group=item.defect_group,
                detected_at="BAVIA",
                is_active=False,
                version=old_version,
            ),
            actor.id,
        )

        assert item not in list_active_defect_codes(db, "BAVIA")
        with pytest.raises(ConcurrentDefectCodeChange, match="tải lại"):
            update_defect_code(
                db,
                item.id,
                DefectCodeUpdate(
                    code=item.code,
                    name=item.name,
                    defect_group=item.defect_group,
                    detected_at="SX",
                    is_active=True,
                    version=old_version,
                ),
                actor.id,
            )
    finally:
        db.rollback()
        db.close()
