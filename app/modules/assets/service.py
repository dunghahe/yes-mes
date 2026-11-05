from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import (
    Machine,
    MachineGroup,
    MachineGroupAssignment,
    MachinePair,
)
from app.modules.assets.schemas import GroupInput, GroupUpdate, MachineInput, MachineUpdate
from app.modules.auth.models import AuditLog


class AssetManagementError(Exception):
    """An asset management rule rejected the requested change."""


class ConcurrentAssetChange(AssetManagementError):
    """An asset changed since the administrator loaded it."""


def create_machine(db: Session, data: MachineInput, actor_id: int) -> Machine:
    _require_unique_code(db, Machine, data.code, "Mã máy")
    now = datetime.now(UTC)
    machine = Machine(
        code=data.code,
        name=data.name,
        production_area=data.production_area,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(machine)
    db.flush()
    _audit(
        db,
        actor_id,
        "machines",
        machine.id,
        "create",
        None,
        _machine_values(machine),
        "Admin tạo máy",
    )
    return machine


def update_machine(db: Session, machine_id: int, data: MachineUpdate, actor_id: int) -> Machine:
    machine = _load_for_update(db, Machine, machine_id, "Không tìm thấy máy.")
    _check_version(machine.version, data.version, "Máy")
    if data.code != machine.code:
        _require_unique_code(db, Machine, data.code, "Mã máy", machine_id)
    if machine.is_active and not data.is_active:
        used_by_pair = db.scalar(
            select(MachinePair.id).where(
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                (MachinePair.machine_1_id == machine_id) | (MachinePair.machine_2_id == machine_id),
            )
        )
        if used_by_pair:
            raise AssetManagementError(
                "Hãy ngừng dùng các cặp máy liên quan trước khi ngừng dùng máy này."
            )

    old_values = _machine_values(machine)
    machine.code = data.code
    machine.name = data.name
    machine.production_area = data.production_area
    machine.is_active = data.is_active
    machine.version += 1
    machine.updated_at = datetime.now(UTC)
    machine.updated_by = actor_id
    _audit(
        db,
        actor_id,
        "machines",
        machine.id,
        "update",
        old_values,
        _machine_values(machine),
        "Admin cập nhật máy",
    )
    return machine


def create_group(db: Session, data: GroupInput, actor_id: int) -> MachineGroup:
    _require_unique_code(db, MachineGroup, data.code, "Mã nhóm máy")
    now = datetime.now(UTC)
    group = MachineGroup(
        code=data.code,
        name=data.name,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    db.flush()
    _audit(
        db,
        actor_id,
        "machine_groups",
        group.id,
        "create",
        None,
        _group_values(group),
        "Admin tạo nhóm máy",
    )
    return group


def update_group(db: Session, group_id: int, data: GroupUpdate, actor_id: int) -> MachineGroup:
    group = _load_for_update(db, MachineGroup, group_id, "Không tìm thấy nhóm máy.")
    _check_version(group.version, data.version, "Nhóm máy")
    if data.code != group.code:
        _require_unique_code(db, MachineGroup, data.code, "Mã nhóm máy", group_id)
    if group.is_active and not data.is_active:
        assigned = db.scalar(
            select(MachineGroupAssignment.id).where(
                MachineGroupAssignment.machine_group_id == group_id,
                MachineGroupAssignment.valid_to.is_(None),
                MachineGroupAssignment.deleted_at.is_(None),
            )
        )
        if assigned:
            raise AssetManagementError(
                "Hãy chuyển các cặp máy khỏi nhóm trước khi ngừng dùng nhóm này."
            )

    old_values = _group_values(group)
    group.code = data.code
    group.name = data.name
    group.is_active = data.is_active
    group.version += 1
    group.updated_at = datetime.now(UTC)
    group.updated_by = actor_id
    _audit(
        db,
        actor_id,
        "machine_groups",
        group.id,
        "update",
        old_values,
        _group_values(group),
        "Admin cập nhật nhóm máy",
    )
    return group


def create_pair(db: Session, machine_1_id: int, machine_2_id: int, actor_id: int) -> MachinePair:
    if machine_1_id == machine_2_id:
        raise AssetManagementError("Một cặp phải gồm hai máy khác nhau.")
    first_id, second_id = sorted((machine_1_id, machine_2_id))
    machines = list(
        db.scalars(
            select(Machine)
            .where(
                Machine.id.in_((first_id, second_id)),
                Machine.deleted_at.is_(None),
                Machine.is_active.is_(True),
            )
            .with_for_update()
        )
    )
    if len(machines) != 2:
        raise AssetManagementError("Chỉ ghép được hai máy đang hoạt động.")
    if db.scalar(
        select(MachinePair.id).where(
            MachinePair.machine_1_id == first_id,
            MachinePair.machine_2_id == second_id,
            MachinePair.deleted_at.is_(None),
        )
    ):
        raise AssetManagementError("Cặp máy này đã tồn tại.")
    now = datetime.now(UTC)
    pair = MachinePair(
        machine_1_id=first_id,
        machine_2_id=second_id,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(pair)
    db.flush()
    values = {"machine_1_id": first_id, "machine_2_id": second_id, "is_active": True}
    _audit(db, actor_id, "machine_pairs", pair.id, "create", None, values, "Admin tạo cặp máy")
    return pair


def update_pair_status(
    db: Session, pair_id: int, is_active: bool, version: int, actor_id: int
) -> MachinePair:
    pair = _load_for_update(db, MachinePair, pair_id, "Không tìm thấy cặp máy.")
    _check_version(pair.version, version, "Cặp máy")
    if pair.is_active == is_active:
        return pair
    if is_active:
        active_machines = db.scalar(
            select(func.count())
            .select_from(Machine)
            .where(
                Machine.id.in_((pair.machine_1_id, pair.machine_2_id)),
                Machine.is_active.is_(True),
                Machine.deleted_at.is_(None),
            )
        )
        if active_machines != 2:
            raise AssetManagementError("Không thể mở lại cặp khi một trong hai máy đã ngừng dùng.")

    old_values = _pair_values(pair)
    now = datetime.now(UTC)
    if not is_active:
        current = db.scalar(
            select(MachineGroupAssignment)
            .where(
                MachineGroupAssignment.machine_pair_id == pair.id,
                MachineGroupAssignment.valid_to.is_(None),
                MachineGroupAssignment.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if current:
            if now <= current.valid_from:
                now = current.valid_from + timedelta(microseconds=1)
            previous = _assignment_values(current)
            current.valid_to = now
            current.updated_at = now
            current.updated_by = actor_id
            current.version += 1
            _audit(
                db,
                actor_id,
                "machine_group_assignments",
                current.id,
                "update",
                previous,
                _assignment_values(current),
                "Đóng hiệu lực nhóm do cặp máy ngừng dùng",
            )
    pair.is_active = is_active
    pair.version += 1
    pair.updated_at = now
    pair.updated_by = actor_id
    _audit(
        db,
        actor_id,
        "machine_pairs",
        pair.id,
        "update",
        old_values,
        _pair_values(pair),
        "Admin cập nhật trạng thái cặp máy",
    )
    return pair


def assign_pair_group(
    db: Session, pair_id: int, machine_group_id: int | None, actor_id: int
) -> MachineGroupAssignment | None:
    pair = _load_for_update(db, MachinePair, pair_id, "Không tìm thấy cặp máy.")
    if not pair.is_active:
        raise AssetManagementError("Chỉ gán nhóm cho cặp máy đang hoạt động.")
    current = db.scalar(
        select(MachineGroupAssignment)
        .where(
            MachineGroupAssignment.machine_pair_id == pair_id,
            MachineGroupAssignment.valid_to.is_(None),
            MachineGroupAssignment.deleted_at.is_(None),
        )
        .with_for_update()
    )
    group = None
    if machine_group_id is not None:
        group = _load_for_update(db, MachineGroup, machine_group_id, "Không tìm thấy nhóm máy.")
        if not group.is_active:
            raise AssetManagementError("Không thể gán nhóm đã ngừng dùng.")
    if current and group and current.machine_group_id == group.id:
        return current
    if current is None and group is None:
        return None

    now = datetime.now(UTC)
    if current and now <= current.valid_from:
        now = current.valid_from + timedelta(microseconds=1)
    if current:
        old_values = _assignment_values(current)
        current.valid_to = now
        current.version += 1
        current.updated_at = now
        current.updated_by = actor_id
        _audit(
            db,
            actor_id,
            "machine_group_assignments",
            current.id,
            "update",
            old_values,
            _assignment_values(current),
            "Đóng hiệu lực gán nhóm máy",
        )
    if group is None:
        return None

    assignment = MachineGroupAssignment(
        machine_pair_id=pair.id,
        machine_group_id=group.id,
        valid_from=now,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(assignment)
    db.flush()
    _audit(
        db,
        actor_id,
        "machine_group_assignments",
        assignment.id,
        "create",
        None,
        _assignment_values(assignment),
        "Gán nhóm máy cho cặp",
    )
    return assignment


def list_machines(db: Session) -> list[Machine]:
    return list(
        db.scalars(
            select(Machine).where(Machine.deleted_at.is_(None)).order_by(Machine.code, Machine.id)
        )
    )


def list_active_machines(db: Session) -> list[Machine]:
    return list(
        db.scalars(
            select(Machine)
            .where(Machine.deleted_at.is_(None), Machine.is_active.is_(True))
            .order_by(Machine.code, Machine.id)
        )
    )


def list_groups(db: Session) -> list[MachineGroup]:
    return list(
        db.scalars(
            select(MachineGroup)
            .where(MachineGroup.deleted_at.is_(None))
            .order_by(MachineGroup.is_active.desc(), MachineGroup.code)
        )
    )


def list_active_groups(db: Session) -> list[MachineGroup]:
    return list(
        db.scalars(
            select(MachineGroup)
            .where(MachineGroup.deleted_at.is_(None), MachineGroup.is_active.is_(True))
            .order_by(MachineGroup.code)
        )
    )


def list_pairs(db: Session) -> list[tuple[MachinePair, Machine, Machine, MachineGroup | None]]:
    first_machine = aliased(Machine)
    second_machine = aliased(Machine)
    current_assignment = aliased(MachineGroupAssignment)
    group = aliased(MachineGroup)
    return list(
        db.execute(
            select(MachinePair, first_machine, second_machine, group)
            .join(first_machine, first_machine.id == MachinePair.machine_1_id)
            .join(second_machine, second_machine.id == MachinePair.machine_2_id)
            .outerjoin(
                current_assignment,
                (current_assignment.machine_pair_id == MachinePair.id)
                & current_assignment.valid_to.is_(None)
                & current_assignment.deleted_at.is_(None),
            )
            .outerjoin(group, group.id == current_assignment.machine_group_id)
            .where(MachinePair.deleted_at.is_(None))
            .order_by(MachinePair.id)
        )
    )


def _load_for_update(db: Session, model: type, record_id: int, message: str):
    record = db.scalar(
        select(model).where(model.id == record_id, model.deleted_at.is_(None)).with_for_update()
    )
    if record is None:
        raise AssetManagementError(message)
    return record


def _check_version(current: int, submitted: int, label: str) -> None:
    if current != submitted:
        raise ConcurrentAssetChange(f"{label} đã thay đổi. Hãy tải lại trang rồi thử lại.")


def _require_unique_code(
    db: Session, model: type, code: str, label: str, exclude_id: int | None = None
) -> None:
    query = select(model.id).where(model.code == code, model.deleted_at.is_(None))
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if db.scalar(query):
        raise AssetManagementError(f"{label} này đã được sử dụng.")


def _machine_values(machine: Machine) -> dict[str, str | bool]:
    return {
        "code": machine.code,
        "name": machine.name,
        "production_area": machine.production_area,
        "is_active": machine.is_active,
    }


def _group_values(group: MachineGroup) -> dict[str, str | bool]:
    return {"code": group.code, "name": group.name, "is_active": group.is_active}


def _pair_values(pair: MachinePair) -> dict[str, int | bool]:
    return {
        "machine_1_id": pair.machine_1_id,
        "machine_2_id": pair.machine_2_id,
        "is_active": pair.is_active,
    }


def _assignment_values(assignment: MachineGroupAssignment) -> dict[str, int | str | None]:
    return {
        "machine_pair_id": assignment.machine_pair_id,
        "machine_group_id": assignment.machine_group_id,
        "valid_from": assignment.valid_from.isoformat(),
        "valid_to": assignment.valid_to.isoformat() if assignment.valid_to else None,
    }


def _audit(
    db: Session,
    actor_id: int,
    table_name: str,
    record_id: int,
    action: str,
    old_values: dict | None,
    new_values: dict,
    reason: str,
) -> None:
    db.add(
        AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            actor_id=actor_id,
        )
    )
