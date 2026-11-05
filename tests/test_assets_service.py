from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.modules.assets.models import Machine, MachineGroupAssignment
from app.modules.assets.schemas import GroupInput, MachineInput
from app.modules.assets.service import (
    AssetManagementError,
    assign_pair_group,
    create_group,
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


def test_machine_and_group_creation_records_audit_and_area() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        machine = create_machine(
            db,
            MachineInput(code=f"M-{uuid4().hex}", name="Máy ép", production_area="Khu ép"),
            actor.id,
        )
        group = create_group(
            db,
            GroupInput(code=f"G-{uuid4().hex}", name="Nhóm máy ép"),
            actor.id,
        )
        logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.actor_id == actor.id,
                    AuditLog.record_id.in_((machine.id, group.id)),
                )
            )
        )

        assert machine.production_area == "Khu ép"
        assert group.is_active
        assert len(logs) == 2
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


def test_group_change_closes_previous_effective_assignment_and_audits() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        first, second = _machines(db, actor.id)
        pair = create_pair(db, first.id, second.id, actor.id)
        old_group = create_group(db, GroupInput(code=f"GA-{uuid4().hex}", name="Nhóm A"), actor.id)
        new_group = create_group(db, GroupInput(code=f"GB-{uuid4().hex}", name="Nhóm B"), actor.id)
        old_assignment = assign_pair_group(db, pair.id, old_group.id, actor.id)
        new_assignment = assign_pair_group(db, pair.id, new_group.id, actor.id)
        assignments = list(
            db.scalars(
                select(MachineGroupAssignment)
                .where(MachineGroupAssignment.machine_pair_id == pair.id)
                .order_by(MachineGroupAssignment.valid_from)
            )
        )
        audit_logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.table_name == "machine_group_assignments",
                    AuditLog.record_id.in_((old_assignment.id, new_assignment.id)),
                )
            )
        )

        assert len(assignments) == 2
        assert assignments[0].valid_to == assignments[1].valid_from
        assert assignments[1].valid_to is None
        assert assignments[1].machine_group_id == new_group.id
        assert len(audit_logs) == 3
    finally:
        db.rollback()
        db.close()


def test_pair_has_at_most_one_current_group_and_deactivation_closes_it() -> None:
    db = SessionLocal()
    try:
        db.begin()
        actor = _admin(db)
        first, second = _machines(db, actor.id)
        pair = create_pair(db, first.id, second.id, actor.id)
        group = create_group(db, GroupInput(code=f"G-{uuid4().hex}", name="Nhóm"), actor.id)
        assignment = assign_pair_group(db, pair.id, group.id, actor.id)

        with pytest.raises(AssetManagementError, match="chuyển các cặp"):
            from app.modules.assets.schemas import GroupUpdate
            from app.modules.assets.service import update_group

            update_group(
                db,
                group.id,
                GroupUpdate(
                    code=group.code, name=group.name, is_active=False, version=group.version
                ),
                actor.id,
            )

        update_pair_status(db, pair.id, False, pair.version, actor.id)

        assert not pair.is_active
        assert assignment.valid_to is not None
        assert assignment.version == 2
    finally:
        db.rollback()
        db.close()
