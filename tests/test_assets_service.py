from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.assets.models import Machine, MachineGroup, MachineGroupAssignment
from app.modules.assets.schemas import MachineInput
from app.modules.assets.service import (
    AssetManagementError,
    create_machine,
    create_pair,
    update_pair_status,
)
from app.modules.auth.models import AuditLog, User


def _admin(db: Session) -> User:
    admin = User(
        username=f"assets-admin-{uuid4().hex}",
        display_name="Admin kiểm thử",
        password_hash="not-used-by-this-test",
        role="admin",
        must_change_password=False,
        password_changed_at=datetime.now(UTC),
    )
    db.add(admin)
    db.flush()
    return admin


def _machines(db: Session, actor_id: int) -> tuple[Machine, Machine]:
    key = uuid4().hex[:12]
    return (
        create_machine(
            db, MachineInput(code=f"M1-{key}", name="Máy một", production_area="Khu A"), actor_id
        ),
        create_machine(
            db, MachineInput(code=f"M2-{key}", name="Máy hai", production_area="Khu B"), actor_id
        ),
    )


def test_machine_creation_records_audit_and_area() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        machine = create_machine(
            db,
            MachineInput(code=f"M-{uuid4().hex}", name="Máy ép", production_area="Khu ép"),
            actor.id,
        )
        logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.actor_id == actor.id,
                    AuditLog.table_name == "machines",
                    AuditLog.record_id == machine.id,
                )
            )
        )

        assert machine.production_area == "Khu ép"
        assert len(logs) == 1
    finally:
        db.rollback()
        db.close()


def test_pair_requires_two_distinct_active_machines_and_is_order_independent() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        first, second = _machines(db, actor.id)
        pair = create_pair(db, first.id, second.id, actor.id)

        with pytest.raises(AssetManagementError, match="đã tồn tại"):
            create_pair(db, second.id, first.id, actor.id)
        with pytest.raises(AssetManagementError, match="khác nhau"):
            create_pair(db, first.id, first.id, actor.id)

        assert pair.machine_1_id == min(first.id, second.id)
        assert pair.machine_2_id == max(first.id, second.id)
    finally:
        db.rollback()
        db.close()


def test_pair_deactivation_closes_legacy_group_assignment() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        first, second = _machines(db, actor.id)
        pair = create_pair(db, first.id, second.id, actor.id)
        group = MachineGroup(code=f"G-{uuid4().hex}", name="Nhóm cũ", is_active=True)
        db.add(group)
        db.flush()
        assignment = MachineGroupAssignment(
            machine_pair_id=pair.id,
            machine_group_id=group.id,
            valid_from=datetime.now(UTC),
            created_by=actor.id,
            updated_by=actor.id,
        )
        db.add(assignment)
        db.flush()

        update_pair_status(db, pair.id, False, pair.version, actor.id)

        assert not pair.is_active
        assert assignment.valid_to is not None
        assert assignment.version == 2
    finally:
        db.rollback()
        db.close()
