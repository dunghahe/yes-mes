from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.modules.assets.models import Machine, MachineGroup, MachineGroupAssignment, MachinePair
from app.modules.auth.models import AuditLog
from app.modules.blank_requests.models import (
    BlankRequest,
    BlankRequestCounter,
    BlankRequestOperator,
    BlankRequestPair,
)
from app.modules.blank_requests.schemas import BlankRequestCreate
from app.modules.employees.models import Employee
from app.modules.orders.models import ProductionOrder
from app.modules.products.models import Product
from app.modules.schedules.models import ProductionSchedule
from app.modules.shifts.models import Shift

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class BlankRequestManagementError(Exception):
    """A blank request business rule rejected the requested change."""


def create_blank_request(
    db: Session, data: BlankRequestCreate, actor_id: int, *, today: date | None = None
) -> BlankRequest:
    now = datetime.now(UTC)
    schedule = db.scalar(
        select(ProductionSchedule)
        .where(
            ProductionSchedule.id == data.schedule_id,
            ProductionSchedule.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if schedule is None:
        raise BlankRequestManagementError("Chọn dòng lịch đang sử dụng.")

    group = db.scalar(
        select(MachineGroup).where(
            MachineGroup.id == data.machine_group_id,
            MachineGroup.is_active.is_(True),
            MachineGroup.deleted_at.is_(None),
        )
    )
    if group is None:
        raise BlankRequestManagementError("Chọn nhóm máy đang sử dụng.")

    assignments = list(
        db.scalars(
            select(MachineGroupAssignment)
            .join(MachinePair, MachinePair.id == MachineGroupAssignment.machine_pair_id)
            .where(
                MachineGroupAssignment.machine_group_id == data.machine_group_id,
                MachineGroupAssignment.valid_from <= now,
                or_(
                    MachineGroupAssignment.valid_to.is_(None), MachineGroupAssignment.valid_to > now
                ),
                MachineGroupAssignment.deleted_at.is_(None),
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                MachinePair.id.in_(data.machine_pair_ids),
            )
        )
    )
    assigned_pair_ids = {assignment.machine_pair_id for assignment in assignments}
    if assigned_pair_ids != set(data.machine_pair_ids):
        raise BlankRequestManagementError("Chỉ chọn cặp máy đang thuộc nhóm máy đã chọn.")

    operators = list(
        db.scalars(
            select(Employee).where(
                Employee.id.in_(data.operator_ids),
                Employee.employee_type == "operator",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
        )
    )
    if len(operators) != len(data.operator_ids):
        raise BlankRequestManagementError("Chỉ chọn nhân viên vận hành đang sử dụng.")

    counter_date = today or datetime.now(LOCAL_TZ).date()
    counter_insert = insert(BlankRequestCounter).values(
        counter_date=counter_date,
        last_number=0,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.execute(counter_insert.on_conflict_do_nothing(index_elements=["counter_date"]))
    counter = db.scalar(
        select(BlankRequestCounter)
        .where(BlankRequestCounter.counter_date == counter_date)
        .with_for_update()
    )
    old_number = counter.last_number
    counter.last_number += 1
    counter.updated_by = actor_id
    counter.updated_at = now
    req_no = f"YC-{counter_date:%y%m%d}-{counter.last_number:02d}"
    db.add(
        AuditLog(
            table_name="blank_request_counters",
            record_id=counter.id,
            action="update",
            old_values={"last_number": old_number},
            new_values={"last_number": counter.last_number},
            reason="Sinh số yêu cầu phôi",
            actor_id=actor_id,
        )
    )

    blank_request = BlankRequest(
        req_no=req_no,
        schedule_id=schedule.id,
        blank_quantity=data.blank_quantity,
        machine_group_id=group.id,
        status="submitted",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(blank_request)
    db.flush()
    for pair_id in data.machine_pair_ids:
        link = BlankRequestPair(
            blank_request_id=blank_request.id,
            machine_pair_id=pair_id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(link)
        db.flush()
        _audit(
            db,
            actor_id,
            "blank_request_pairs",
            link.id,
            "create",
            None,
            {"blank_request_id": blank_request.id, "machine_pair_id": pair_id},
            "Chọn cặp máy cho yêu cầu phôi",
        )
    for employee in operators:
        link = BlankRequestOperator(
            blank_request_id=blank_request.id,
            employee_id=employee.id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(link)
        db.flush()
        _audit(
            db,
            actor_id,
            "blank_request_operators",
            link.id,
            "create",
            None,
            {"blank_request_id": blank_request.id, "employee_id": employee.id},
            "Chọn người vận hành cho yêu cầu phôi",
        )
    _audit(
        db,
        actor_id,
        "blank_requests",
        blank_request.id,
        "create",
        None,
        {
            "req_no": req_no,
            "schedule_id": schedule.id,
            "order_id": schedule.order_id,
            "blank_quantity": data.blank_quantity,
            "machine_group_id": group.id,
            "machine_pair_ids": data.machine_pair_ids,
            "operator_ids": data.operator_ids,
            "status": "submitted",
        },
        "Kỹ thuật tạo yêu cầu xuất phôi",
    )
    return blank_request


def list_blank_requests(db: Session):
    return list(
        db.execute(
            select(
                BlankRequest,
                ProductionSchedule,
                ProductionOrder,
                Product,
                Shift,
                MachineGroup,
            )
            .join(ProductionSchedule, ProductionSchedule.id == BlankRequest.schedule_id)
            .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
            .join(Product, Product.id == ProductionOrder.product_id)
            .join(Shift, Shift.id == ProductionSchedule.shift_id)
            .join(MachineGroup, MachineGroup.id == BlankRequest.machine_group_id)
            .where(BlankRequest.deleted_at.is_(None))
            .order_by(BlankRequest.created_at.desc(), BlankRequest.id.desc())
        )
    )


def active_groups(db: Session) -> list[MachineGroup]:
    return list(
        db.scalars(
            select(MachineGroup)
            .where(MachineGroup.is_active.is_(True), MachineGroup.deleted_at.is_(None))
            .order_by(MachineGroup.code)
        )
    )


def active_pairs_for_group(db: Session, group_id: int):
    now = datetime.now(UTC)
    machine_1 = aliased(Machine)
    machine_2 = aliased(Machine)
    return list(
        db.execute(
            select(MachinePair, machine_1, machine_2)
            .join(MachineGroupAssignment, MachineGroupAssignment.machine_pair_id == MachinePair.id)
            .join(machine_1, machine_1.id == MachinePair.machine_1_id)
            .join(machine_2, machine_2.id == MachinePair.machine_2_id)
            .where(
                MachineGroupAssignment.machine_group_id == group_id,
                MachineGroupAssignment.valid_from <= now,
                or_(
                    MachineGroupAssignment.valid_to.is_(None), MachineGroupAssignment.valid_to > now
                ),
                MachineGroupAssignment.deleted_at.is_(None),
                MachinePair.is_active.is_(True),
                MachinePair.deleted_at.is_(None),
                machine_1.is_active.is_(True),
                machine_1.deleted_at.is_(None),
                machine_2.is_active.is_(True),
                machine_2.deleted_at.is_(None),
            )
            .order_by(MachinePair.id)
        ).unique()
    )


def active_operators(db: Session) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .where(
                Employee.employee_type == "operator",
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.code)
        )
    )


def available_schedules(db: Session):
    return list(
        db.execute(
            select(ProductionSchedule, ProductionOrder, Product, Shift)
            .join(ProductionOrder, ProductionOrder.id == ProductionSchedule.order_id)
            .join(Product, Product.id == ProductionOrder.product_id)
            .join(Shift, Shift.id == ProductionSchedule.shift_id)
            .where(ProductionSchedule.deleted_at.is_(None))
            .order_by(
                ProductionSchedule.production_date.desc(), Shift.start_time, ProductionOrder.po_no
            )
        )
    )


def request_resources(
    db: Session, request_ids: list[int]
) -> dict[int, tuple[list[int], list[int]]]:
    resources = {request_id: ([], []) for request_id in request_ids}
    if not request_ids:
        return resources
    for request_id, pair_id in db.execute(
        select(BlankRequestPair.blank_request_id, BlankRequestPair.machine_pair_id).where(
            BlankRequestPair.blank_request_id.in_(request_ids),
            BlankRequestPair.deleted_at.is_(None),
        )
    ):
        resources[request_id][0].append(pair_id)
    for request_id, employee_id in db.execute(
        select(BlankRequestOperator.blank_request_id, BlankRequestOperator.employee_id).where(
            BlankRequestOperator.blank_request_id.in_(request_ids),
            BlankRequestOperator.deleted_at.is_(None),
        )
    ):
        resources[request_id][1].append(employee_id)
    return resources


def _audit(
    db: Session,
    actor_id: int,
    table_name: str,
    record_id: int,
    action: str,
    old_values: dict[str, object] | None,
    new_values: dict[str, object],
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
